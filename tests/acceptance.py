"""需求文档第八节的 8 个最低验收场景 + 第五节的安装暂停边界。

每个场景起一个独立实例（独立 HOME / 假设备 / adb 调用日志），互不影响。
用法：
    sh tests/get_test_apks.sh          # 第一次：下载 3 个测试用的真实 APK
    python3 tests/acceptance.py        # 全部场景
    python3 tests/acceptance.py 5 9    # 只跑指定场景

不需要真机：tests/fakeadb/adb 是一个假 adb，用控制文件模拟拔线、未授权、离线、
换了另一台手机、无线连不上、安装中途被打断、安装报 Success 但实际没装上等情况。
"""
import os, subprocess, sys, threading, time, urllib.request, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Inst, APKS, REPO as REPO_DIR, HERE as HERE_DIR, SERVER_PY

FAST = {"APKMGR_DISCOVERY_INTERVAL": "1", "APKMGR_RECONNECT_BACKOFF": "1,2,3"}
USB = "FAKE1234567890"
WIFI = "192.168.1.9:5555"
RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("   ✓ " if cond else "   ✗ ") + msg)
    return cond


def cmds(I, since, word):
    return [a for ts, a in I.adb_calls(since) if a.split() and word in a.split()]


def ready(I):
    I.wait(lambda: I.sup()["devicesAt"], what="首次检测")
    I.wait(lambda: all(d.get("physical") for d in I.sup()["devices"] if d["state"] == "device"),
           what="物理序号")


def import_all(I, keys=("termux", "newpipe", "seal")):
    for k in keys:
        I.post("/api/import", {"path": APKS[k]})


def job(I):
    return I.get("/api/state")["job"] or {}


# ---------------------------------------------------------------------------
def s1():
    print("\n[1] USB 安装时暂停无线后台：安装不中断，且没有新的无线连接或 tcpip")
    I = Inst("s1", FAST, {"wirelessHistory": [WIFI], "autoReconnect": True})
    try:
        I.ctl(".install_delay", "1.5")
        I.ctl(".wireless", WIFI)            # 无线也连着（同一台手机）
        ready(I)
        I.post("/api/supervisor/pause-wifi")
        t0 = time.time()
        I.ctl(".wireless", "")               # 无线掉线 —— 暂停中不应重连
        import_all(I)
        I.post("/api/supervisor/select", {"serial": USB})
        r = I.post("/api/install", {"serial": USB, "mode": "all"})
        check(r.get("ok"), "安装已开始")
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=60, what="安装完成")
        d = [e for e in I.events if e["type"] == "install_done"][0]
        check(d["ok"] == 3 and d["failed"] == 0, "3 个全部装好（%d 成功 / %d 失败）" % (d["ok"], d["failed"]))
        time.sleep(4)                        # 再多观察几个调度周期
        check(not cmds(I, t0, "connect"), "暂停期间没有任何 adb connect（%d 条）" % len(cmds(I, t0, "connect")))
        check(not cmds(I, t0, "tcpip"), "没有执行 adb tcpip")
        st = I.sup()
        check(st["tasks"]["wifi_reconnect"]["state"] == "paused", "断线重连显示为「已暂停」")
        check(st["tasks"]["discovery"]["state"] in ("idle", "running"), "设备发现照常运行（只停无线）")
    finally:
        I.close()


def s2():
    print("\n[2] 无线连接失败后「暂停等待」：后台不再循环重试；不暂停时也会在 3 次后停下")
    I = Inst("s2", FAST, {"wirelessHistory": [WIFI], "autoReconnect": True})
    try:
        I.ctl(".wireless", WIFI)
        ready(I)
        I.ctl(".wifi_down", "1")
        I.ctl(".wireless", "")               # 掉线，且重连会失败
        I.wait(lambda: cmds(I, 0, "connect"), timeout=20, what="出现第一次重连尝试")
        I.post("/api/supervisor/pause")
        t_pause = time.time()
        time.sleep(0.6)                      # 允许已开始的那一条收尾
        settle = time.time()
        time.sleep(10)
        after = [a for ts, a in I.adb_calls(settle)]
        check(not after, "暂停后 10 秒内没有任何 adb 命令（%d 条）" % len(after))
        st = I.sup()
        check(st["bgPaused"] and all(t["state"] == "paused" for t in st["tasks"].values()),
              "所有后台任务显示「已暂停」（%s）" % {k: v["state"] for k, v in st["tasks"].items()})
        check(st["stale"], "设备信息标记为非实时（stale）")
        check(st["lastFailure"] and "connect" in (st["lastFailure"]["reason"] or "").lower()
              or st["lastFailure"]["stage"] == "wifi_reconnect", "最近失败记录了重连失败")
    finally:
        I.close()

    I = Inst("s2b", FAST, {"wirelessHistory": [WIFI], "autoReconnect": True})
    try:
        I.ctl(".wireless", WIFI)
        ready(I)
        I.ctl(".wifi_down", "1")
        I.ctl(".wireless", "")
        I.wait(lambda: any(r.get("gaveUp") for r in I.sup()["reconnect"]), timeout=30, what="重连放弃")
        n = len(cmds(I, 0, "connect"))
        time.sleep(6)
        n2 = len(cmds(I, 0, "connect"))
        check(n <= 3, "自动重连只试了 %d 次（上限 3）" % n)
        check(n2 == n, "放弃之后不再自动重试（6 秒内新增 %d 次）" % (n2 - n))
        r = I.post("/api/supervisor/retry", {"target": WIFI})
        time.sleep(4)
        n3 = len(cmds(I, 0, "connect"))
        check(n3 == n2 + 1, "手动「重试一次」只执行一次，不重新开启自动循环")
    finally:
        I.close()


def s3():
    print("\n[3] 连点恢复、刷新页面、开第二个窗口：后台仍只有一份任务")
    I = Inst("s3", {"APKMGR_DISCOVERY_INTERVAL": "2"})
    try:
        ready(I)
        I.post("/api/supervisor/pause")
        ths = [threading.Thread(target=lambda: I.post("/api/supervisor/resume")) for _ in range(12)]
        [t.start() for t in ths]; [t.join() for t in ths]
        extra = []
        for _ in range(3):                   # 再开 3 个「窗口」
            def listen():
                try:
                    for _ in urllib.request.urlopen(I.B + "/api/events", timeout=30):
                        pass
                except Exception:
                    pass
            th = threading.Thread(target=listen, daemon=True); th.start(); extra.append(th)
        for _ in range(20):                  # 模拟刷新页面
            I.get("/api/state"); I.get("/api/supervisor"); I.get("/api/devices")
        t0 = time.time()
        time.sleep(12.5)
        n = len(cmds(I, t0, "devices"))
        st = I.sup()
        check(st["threads"] == 1, "后台调度线程数 = %d" % st["threads"])
        check(5 <= n <= 7, "12.5 秒内 adb devices 调用 %d 次（2 秒一次，只有一份循环）" % n)
        check(not st["bgPaused"], "当前为已恢复状态")
        before = len(I.adb_calls(0))
        for _ in range(10):
            I.get("/api/devices")
        check(len(I.adb_calls(0)) - before <= 1, "反复请求设备列表不会触发额外的 adb 命令")
    finally:
        I.close()


def s4():
    print("\n[4] 同一台设备同时 USB / Wi-Fi 接入：合并显示，不重复安装，不装错设备")
    I = Inst("s4", FAST)
    try:
        I.ctl(".wireless", WIFI)
        ready(I)
        devs = {d["serial"]: d for d in I.sup()["devices"]}
        check(devs[USB]["physical"] == devs[WIFI]["physical"] == "PHYS-A", "两个入口核验出同一个物理序号")
        check(devs[USB]["duplicate"] and WIFI in devs[USB]["peers"], "合并为同一台设备展示")
        import_all(I)
        t0 = time.time()
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=60, what="安装完成")
        ins = [a for ts, a in I.adb_calls(t0) if " install" in " " + a]
        check(len(ins) == 3, "一共只执行了 3 次 install（%d）" % len(ins))
        check(all(a.startswith("-s %s " % USB) for a in ins), "每一次都明确指定 -s %s" % USB)
        check(not any(a.startswith("-s %s" % WIFI) and "install" in a for a in ins), "没有装到 Wi-Fi 入口")
        bare = [a for ts, a in I.adb_calls(0) if a.split()[:1] and a.split()[0] in
                ("install", "install-multiple", "shell", "uninstall", "tcpip", "pull")]
        check(not bare, "全程没有不带 -s 的设备级命令（%d 条）" % len(bare))
    finally:
        I.close()


def s5():
    print("\n[5] 安装中拔线：队列暂停；接入其他机器或重新插回都不会自动继续")
    I = Inst("s5", FAST)
    try:
        I.ctl(".install_delay", "2")
        ready(I)
        import_all(I)
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: job(I).get("current"), what="开始装第一个")
        time.sleep(0.5)
        I.ctl(".unplugged", "1")
        t_unplug = time.time()
        I.wait(lambda: job(I).get("paused"), timeout=20, what="队列暂停")
        j = job(I)
        check(j["pauseReason"] == "target_lost", "暂停原因 = 目标设备断开（%s）" % j["pauseReason"])
        check(j["remaining"] == 3, "剩余 3 个（被打断的那个算未完成）")
        # 另一台机器从 Wi-Fi 接入
        I.ctl(".wifi_phone", "PHYS-B")
        I.post("/api/wireless/connect", {"hostPort": "192.168.1.20:5555"})
        time.sleep(5)
        check(not [a for ts, a in I.adb_calls(t_unplug + 0.3) if "install" in a.split()],
              "接入另一台机器后没有自动继续安装")
        check(job(I)["paused"], "仍处于暂停")
        # 原设备插回来
        I.ctl(".unplugged")
        time.sleep(5)
        check(job(I)["paused"] and not [a for ts, a in I.adb_calls(t_unplug + 0.3) if "install" in a.split()],
              "原设备插回后也不会自动继续，要等用户点")
        r = I.post("/api/install/continue", {})
        check(r.get("ok") and r.get("remaining") == 3, "点「继续安装」后接着装剩下的 3 个")
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=60, what="完成")
        d = [e for e in I.events if e["type"] == "install_done"][0]
        check(d["ok"] == 3, "最终 3 个都装好")
    finally:
        I.close()

    print("    —— 同一个 Wi-Fi 地址背后换成另一台手机")
    I = Inst("s5b", FAST)
    try:
        I.ctl(".install_delay", "1")
        I.ctl(".wireless", WIFI)
        ready(I)
        import_all(I)
        I.post("/api/install", {"serial": WIFI, "mode": "all"})
        I.wait(lambda: job(I).get("current"), what="开始")
        I.ctl(".wifi_phone", "PHYS-B")       # 地址没变，机器变了
        I.wait(lambda: job(I).get("paused"), timeout=20, what="暂停")
        check(job(I)["pauseReason"] == "target_mismatch", "识别出不是原来那台（%s）" % job(I)["pauseReason"])
        r = I.post("/api/install/continue", {})
        check(not r.get("ok") and r.get("code") == "bound_target_mismatch", "直接继续会被拒绝，需要用户明确改绑")
    finally:
        I.close()


def s6():
    print("\n[6] 未授权、离线、连接失败、检测暂停能明确区分")
    I = Inst("s6", FAST)
    try:
        I.ctl(".extra_devices", "UNAUTH01\tunauthorized\nOFFLINE01\toffline")
        ready(I)
        I.wait(lambda: len(I.sup()["devices"]) == 3, what="三台设备")
        st = {d["serial"]: d["state"] for d in I.sup()["devices"]}
        check(st == {USB: "device", "UNAUTH01": "unauthorized", "OFFLINE01": "offline"}, "设备状态各自独立：%s" % st)
        r = I.post("/api/install", {"serial": "UNAUTH01", "mode": "all"})
        import_all(I, ("termux",))
        r = I.post("/api/install", {"serial": "UNAUTH01", "mode": "all"})
        check(not r["ok"] and r["code"] == "target_not_ready", "对未授权设备开始安装被拒绝（%s）" % r.get("code"))
        r = I.post("/api/supervisor/retry", {"target": "10.0.0.1:5555"})
        lf = I.sup()["lastFailure"]
        check(not r["ok"] and lf and lf["stage"] == "wifi_reconnect", "连接失败单独记录（环节 %s）" % (lf or {}).get("stage"))
        I.post("/api/supervisor/pause")
        s = I.sup()
        states = {k: v["state"] for k, v in s["tasks"].items()}
        check(s["bgPaused"] and s["stale"] and "running" not in states.values(),
              "暂停瞬间：标记为非实时，正在跑的只会显示「正在收尾」而不是「运行中」（%s）" % states)
        s = I.wait(lambda: (lambda x: x if all(v["state"] == "paused" for v in x["tasks"].values()) else None)(I.sup()),
                   timeout=10, what="全部变为已暂停")
        check(True, "收尾结束后所有后台任务都显示「已暂停」")
    finally:
        I.close()


def s7():
    print("\n[7] 另一个软件在用 ADB 时，本程序不会擅自结束它")
    from harness import SC
    d = os.path.join(SC, "extbin")
    os.makedirs(d, exist_ok=True)
    fake = os.path.join(d, "adb")
    open(fake, "w").write("#!/bin/bash\nsleep 120\n")
    os.chmod(fake, 0o755)
    ext = [subprocess.Popen([fake, "-L", "tcp:5037", "fork-server", "server", "--reply-fd", "4"]),
           subprocess.Popen([fake, "-s", "OTHER", "logcat"])]
    I = Inst("s7", FAST)
    try:
        I.ctl(".install_delay", "2")
        ready(I)
        I.post("/api/supervisor/check")
        procs = {p["pid"]: p["owner"] for p in I.sup()["server"]["processes"]}
        check(procs.get(ext[0].pid) == "server_other", "外部 adb 服务标为「由另一个 adb 启动」")
        check(procs.get(ext[1].pid) == "unknown", "外部 adb 客户端标为「外部／未知」")
        # 各种操作都走一遍：暂停/恢复、检测、安装、取消当前
        I.post("/api/supervisor/pause"); I.post("/api/supervisor/resume")
        I.post("/api/supervisor/pause-wifi"); I.post("/api/supervisor/resume-wifi")
        import_all(I, ("termux", "newpipe"))
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: job(I).get("current"), what="开始")
        time.sleep(0.5)
        I.post("/api/install/cancel-current")
        I.wait(lambda: job(I).get("paused"), timeout=20, what="取消后暂停")
        time.sleep(1)
        check(all(p.poll() is None for p in ext), "两个外部 adb 进程都还活着")
        kills = [a for ts, a in I.adb_calls(0) if "kill-server" in a]
        check(not kills, "从未执行 adb kill-server")
        alld = [a for ts, a in I.adb_calls(0) if a.strip() == "disconnect"]
        check(not alld, "从未执行不带地址的 adb disconnect")
    finally:
        I.close()
        for p in ext:
            p.kill()


def s8():
    print("\n[8] 安装成功后读设备上的包名和版本核验，不只看日志里的 Success")
    I = Inst("s8", FAST)
    try:
        ready(I)
        import_all(I, ("termux",))
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=30, what="完成")
        r = [e for e in I.events if e["type"] == "install_done"][-1]["results"][0]
        check(r["code"] == "installed_verified", "正常安装 → 已核验（%s）" % r["code"])
        check(any("dumpsys package com.termux" in a for ts, a in I.adb_calls(0)), "确实读取了设备上的 dumpsys")

        # 日志报 Success，但设备上其实没写进去
        I.events.clear()
        I.ctl(".verify_lie", "1")
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=30, what="完成")
        r = [e for e in I.events if e["type"] == "install_done"][-1]["results"][0]
        check(r["status"] == "success" and r["code"] == "installed_verified",
              "覆盖安装后设备上版本一致 → 已核验")
        # 换一个不存在的情况：设备上的包被换成别的版本
        import shutil
        shutil.rmtree(os.path.join(I.dev, "data/app/com.termux-1"))
        I.preinstall("newpipe", "com.termux")     # 设备上 com.termux 变成了另一个版本号
        I.events.clear()
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=30, what="完成")
        r = [e for e in I.events if e["type"] == "install_done"][-1]["results"][0]
        check(r["status"] == "unverified" and r["code"] == "verify_mismatch",
              "报 Success 但版本号对不上 → 未核验（%s %s）" % (r["code"], r.get("arg")))
        shutil.rmtree(os.path.join(I.dev, "data/app/com.termux-1"))
        I.events.clear()
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=30, what="完成")
        r = [e for e in I.events if e["type"] == "install_done"][-1]["results"][0]
        check(r["status"] == "unverified" and r["code"] == "verify_missing",
              "报 Success 但设备上根本没有 → 未核验（%s）" % r["code"])
    finally:
        I.close()


def s9():
    print("\n[9] 安装暂停边界：当前完成后暂停、继续只装剩下的、取消当前会核验、不盲目整批重装")
    I = Inst("s9", FAST)
    try:
        I.ctl(".install_delay", "1.5")
        ready(I)
        import_all(I)
        t0 = time.time()
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: job(I).get("current"), what="开始")
        I.post("/api/install/pause")
        I.wait(lambda: job(I).get("paused"), timeout=20, what="暂停")
        j = job(I)
        check(j["pauseReason"] == "user" and j["ok"] == 1 and j["remaining"] == 2,
              "第一个装完才停（成功 %d，剩余 %d）" % (j["ok"], j["remaining"]))
        check(len([a for ts, a in I.adb_calls(t0) if "install" in a.split()]) == 1, "暂停后没有开始第二个")
        r = I.post("/api/install/continue", {})
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=60, what="完成")
        n = len([a for ts, a in I.adb_calls(t0) if "install" in a.split()])
        check(n == 3, "继续时只装剩下的，全程共 3 次 install（%d）" % n)
        r = I.post("/api/install", {"serial": USB})
        check(r.get("code") == "choose_mode" and r.get("done") == 3,
              "同一台设备再点安装会先问「只装剩下的 / 全部重装」，不直接整批重来")
    finally:
        I.close()

    I = Inst("s9b", FAST)
    try:
        I.ctl(".install_delay", "4")
        ready(I)
        import_all(I, ("termux", "newpipe"))
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: job(I).get("current"), what="开始")
        time.sleep(0.8)
        I.post("/api/install/cancel-current")
        I.wait(lambda: job(I).get("paused"), timeout=20, what="暂停")
        it = [i for i in I.get("/api/state")["items"] if i["label"] == "Termux"][0]
        check(it["status"] == "cancelled" and it["code"] == "cancelled_not_installed",
              "取消后读取设备核验：确实没装上（%s）" % it["code"])
        check(job(I)["pauseReason"] == "cancelled", "队列暂停，原因 = 已取消")
    finally:
        I.close()



def items(I):
    return {i["label"]: i for i in I.get("/api/state")["items"]}


def disk_queue(I):
    import json as _j
    return {i["label"]: i for i in _j.load(open(os.path.join(I.home, ".apk-installer", "queue.json")))}


def installs_of(I, pkg_file, since=0):
    return [a for ts, a in I.adb_calls(since) if "install" in a.split() and a.endswith(pkg_file)]


def s10():
    print("\n[10] 慢安装中「暂停后台」：当前项装完但不核验、不开始下一项；结果保留；恢复后先核验，不重复安装")
    I = Inst("s10", FAST)
    try:
        I.ctl(".install_delay", "2.5")
        ready(I)
        import_all(I)
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: job(I).get("current"), what="开始")
        time.sleep(0.5)
        I.post("/api/supervisor/pause")
        t_pause = time.time()
        I.wait(lambda: job(I).get("paused"), timeout=20, what="暂停")
        time.sleep(2)
        j = job(I); it = items(I)
        check(j["pauseReason"] == "bg_paused", "队列随后台一起暂停（原因 %s）" % j["pauseReason"])
        check(it["Termux"]["status"] == "pending_verify" and it["Termux"]["code"] == "verify_pending",
              "正在装的那一项装完了，但记为「待核验」而不是成功/失败/未安装（%s）" % it["Termux"]["status"])
        lr = disk_queue(I)["Termux"].get("lastRun") or {}
        check(lr.get("rc") == 0 and "Success" in (lr.get("log") or ""),
              "adb 退出码与日志已写入磁盘上的队列（rc=%s）" % lr.get("rc"))
        check(it["NewPipe"]["status"] == "pending", "没有开始下一项（NewPipe 状态 %s）" % it["NewPipe"]["status"])
        after = [a for ts, a in I.adb_calls(t_pause + 0.05)]
        check(not after, "暂停之后本程序没有再发任何 adb 命令（%d 条：%s）" % (len(after), after[:3]))
        r = I.post("/api/install/continue", {})
        check(not r["ok"] and r["code"] == "bg_paused_blocks_install", "后台暂停中不能继续安装（%s）" % r.get("code"))
        t_res = time.time()
        I.post("/api/supervisor/resume")
        I.wait(lambda: items(I)["Termux"]["status"] == "success", timeout=20, what="恢复后核验")
        q = [a for ts, a in I.adb_calls(t_res) if "pm path com.termux" in a]
        check(q, "恢复后台后先到设备上核验了 Termux（%d 次查询）" % len(q))
        check(job(I)["paused"] and not [a for ts, a in I.adb_calls(t_res) if "install" in a.split()],
              "恢复后台不会自己继续安装")
        I.post("/api/install/continue", {})
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=60, what="完成")
        check(len(installs_of(I, "termux.apk")) == 1, "Termux 全程只装了 1 次（没有因为丢结果而重装）")
        check(len([a for ts, a in I.adb_calls(0) if "install" in a.split()]) == 3, "三个 APK 各装一次，共 3 次")
    finally:
        I.close()

    print("    —— 恢复后核验时查询失败：保持「待核验」，继续安装也不重装它")
    I = Inst("s10b", FAST)
    try:
        I.ctl(".install_delay", "2")
        ready(I)
        import_all(I, ("termux", "newpipe"))
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: job(I).get("current"), what="开始")
        time.sleep(0.4)
        I.post("/api/supervisor/pause")
        I.wait(lambda: job(I).get("paused"), timeout=20, what="暂停")
        I.ctl(".shell_fail", "1")
        I.post("/api/supervisor/resume")
        time.sleep(3)
        it = items(I)["Termux"]
        check(it["status"] == "pending_verify", "查询失败时仍是「待核验」，没有被判成未安装（%s / %s）" % (it["status"], it["code"]))
        I.ctl(".shell_fail")
        t0 = time.time()
        r = I.post("/api/install/continue", {})
        I.wait(lambda: not job(I).get("running"), timeout=60, what="结束")
        check(not installs_of(I, "termux.apk", t0), "继续安装时没有重复安装 Termux")
        check(items(I)["Termux"]["status"] == "success", "设备恢复后核验通过，标为成功")
    finally:
        I.close()


def s11():
    print("\n[11] 迟到结果在写入前拦截：旧设备慢查询 → 暂停 → 换设备 → 恢复 → 旧结果最后返回")
    I = Inst("s11", FAST)
    try:
        I.ctl(".extra_devices", "SECOND01\tdevice")
        ready(I)
        I.post("/api/import", {"path": APKS["termux"]})
        I.preinstall("termux", "com.termux")
        I.ctl(".slow_pm", "3")
        I.post("/api/supervisor/select", {"serial": USB})
        I.wait(lambda: [a for ts, a in I.adb_calls(0) if a.startswith("-s %s shell pm list" % USB)], what="旧设备开始慢查询")
        I.post("/api/supervisor/pause")
        I.ctl(".slow_pm")
        I.post("/api/supervisor/select", {"serial": "SECOND01"})
        t_switch = time.time()
        I.post("/api/supervisor/resume")
        I.wait(lambda: (items(I)["Termux"].get("installed") or {}).get("serial") == "SECOND01", timeout=20, what="新设备标记")
        time.sleep(4)
        late = [e for e in I.events if e["type"] == "marked" and e.get("serial") == USB and e["ts"] >= t_switch]
        check(not late, "旧设备的结果没有在换设备之后写入（%d 次）" % len(late))
        check(items(I)["Termux"]["installed"]["serial"] == "SECOND01", "内存里的标记属于新设备")
        check(disk_queue(I)["Termux"]["installed"]["serial"] == "SECOND01", "磁盘上的队列也属于新设备")
        check(I.sup()["tasks"]["status"]["note"] in ("", "late_discarded"), "状态查询任务记录为丢弃迟到结果或正常")
    finally:
        I.close()

    print("    —— 手动「标记已安装」途中换设备")
    I = Inst("s11b", FAST)
    try:
        I.ctl(".extra_devices", "SECOND01\tdevice")
        ready(I)
        I.post("/api/import", {"path": APKS["termux"]})
        I.post("/api/supervisor/select", {"serial": USB}); time.sleep(1.5)
        before = disk_queue(I)["Termux"].get("installed")
        I.ctl(".slow_pm", "3")
        res = {}
        th = threading.Thread(target=lambda: res.update(I.post("/api/mark", {"serial": USB}))); th.start()
        time.sleep(0.5); I.ctl(".slow_pm")
        I.post("/api/supervisor/select", {"serial": "SECOND01"})
        th.join()
        check(res.get("code") == "late_discarded", "手动标记的结果被丢弃（%s）" % res.get("code") or res)
        cur = (items(I)["Termux"].get("installed") or {}).get("serial")
        check(cur != USB, "队列里没有旧设备的标记（现在：%s）" % cur)
    finally:
        I.close()


def s12():
    print("\n[12] 安装后核验绑定同一台设备；身份或查询不确定时不算成功、也不算未安装")
    I = Inst("s12", FAST)
    try:
        ready(I)
        I.post("/api/import", {"path": APKS["termux"]})
        I.ctl(".fail_after_install", "1")
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: any(e["type"] in ("install_done", "install_paused") for e in I.events), timeout=30, what="结束")
        it = items(I)["Termux"]
        check(it["status"] == "pending_verify", "装完后查询失败 → 待核验（%s / %s）" % (it["status"], it["code"]))
        check(not it.get("installed") or it["installed"].get("state") != "none", "已安装标记没有被改成「没装过」")
        I.ctl(".shell_fail"); I.ctl(".fail_after_install")
        r = I.post("/api/supervisor/check")
        check(items(I)["Termux"]["status"] == "success", "设备恢复后手动检测一次即完成核验 → 成功")
    finally:
        I.close()

    I = Inst("s12b", FAST)
    try:
        I.ctl(".serialno_empty", "1")
        I.ctl(".wireless", WIFI)
        I.wait(lambda: I.sup()["devicesAt"] and len(I.sup()["devices"]) == 2, what="设备")
        time.sleep(1.5)
        I.post("/api/import", {"path": APKS["termux"]})
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=30, what="USB 完成")
        check(items(I)["Termux"]["code"] == "installed_verified", "USB 读不到序号时用 USB 序列号 + 连接 transport_id 识别（连接未断）→ 已核验")
        I.events.clear()
        I.post("/api/install", {"serial": WIFI, "mode": "all"})
        I.wait(lambda: any(e["type"] in ("install_done", "install_paused") for e in I.events), timeout=30, what="Wi-Fi 完成")
        it = items(I)["Termux"]
        check(it["status"] == "unverified" and it["code"] == "verify_identity_unknown",
              "Wi-Fi 读不到序号 → 身份无法确认，不判成功（%s）" % it["code"])
    finally:
        I.close()

    I = Inst("s12c", FAST)
    try:
        I.ctl(".wireless", WIFI)
        ready(I)
        import_all(I, ("termux", "newpipe"))
        I.ctl(".swap_after_install", "1")
        I.post("/api/install", {"serial": WIFI, "mode": "all"})
        I.wait(lambda: job(I).get("paused"), timeout=30, what="暂停")
        it = items(I)
        check(it["Termux"]["status"] == "unverified" and it["Termux"]["code"] == "verify_identity_changed",
              "装完后同一 Wi-Fi 地址背后换了手机 → 不拿另一台的版本判成功（%s）" % it["Termux"]["code"])
        check(job(I)["pauseReason"] == "target_mismatch" and it["NewPipe"]["status"] == "pending",
              "队列暂停，没有继续往新机器上装")
    finally:
        I.close()

    # USB 读不到物理序号、两台机器共用同一个 USB 序列号：靠 transport_id 识别拔插换机
    I = Inst("s12d", FAST)
    try:
        I.ctl(".serialno_empty", "1")
        I.wait(lambda: I.sup()["devicesAt"] and len(I.sup()["devices"]) == 1, what="设备")
        time.sleep(1.5)
        import_all(I, ("termux", "newpipe"))
        I.ctl(".replug_after_install", "1")
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: job(I).get("paused"), timeout=30, what="暂停")
        it = items(I)
        check(it["Termux"]["status"] == "unverified" and it["Termux"]["code"] == "verify_identity_changed",
              "USB 无序号 + 装完后拔插换上同序列号的另一台 → 不判成功（%s）" % it["Termux"]["code"])
        check(job(I)["pauseReason"] == "target_mismatch" and it["NewPipe"]["status"] == "pending",
              "队列暂停，没有继续往换上的机器上装")
    finally:
        I.close()

    I = Inst("s12e", FAST)
    try:
        I.ctl(".serialno_empty", "1")
        I.ctl(".transport_id", "")
        I.wait(lambda: I.sup()["devicesAt"] and len(I.sup()["devices"]) == 1, what="设备")
        time.sleep(1.5)
        I.post("/api/import", {"path": APKS["termux"]})
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: any(e["type"] in ("install_done", "install_paused") for e in I.events), timeout=30, what="结束")
        it = items(I)["Termux"]
        check(it["status"] == "unverified" and it["code"] == "verify_identity_unknown",
              "USB 无序号且 adb 不提供 transport_id → 身份无法确认，不判成功（%s）" % it["code"])
    finally:
        I.close()


def s13():
    print("\n[13] 取消只结束本程序自己的进程；设备结果查不到时显示待核验而不是「没装上」")
    d = os.path.join(__import__("harness").SC, "extbin13")
    os.makedirs(d, exist_ok=True)
    fake = os.path.join(d, "adb")
    open(fake, "w").write("#!/bin/bash\nsleep 120\n"); os.chmod(fake, 0o755)
    ext = [subprocess.Popen([fake, "-L", "tcp:5037", "fork-server", "server", "--reply-fd", "4"]),
           subprocess.Popen([fake, "-s", "OTHER", "install", "x.apk"])]
    I = Inst("s13", FAST)
    try:
        I.ctl(".install_delay", "5")
        ready(I)
        I.post("/api/import", {"path": APKS["termux"]})
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: job(I).get("current"), what="开始")
        time.sleep(0.6)
        pid = next((a["pid"] for a in I.sup()["active"] if "install" in a["cmd"]), None)
        I.ctl(".shell_fail", "1")
        I.post("/api/install/cancel-current")
        I.wait(lambda: job(I).get("paused"), timeout=20, what="暂停")
        time.sleep(0.5)
        it = items(I)["Termux"]
        check(it["status"] == "pending_verify", "取消后查询失败 → 待核验，不说「没装上」（%s / %s）" % (it["status"], it["code"]))
        alive = pid and os.path.exists("/proc/%d" % pid) and open("/proc/%d/stat" % pid).read().split()[2] != "Z"
        check(pid and not alive, "被取消的是本程序自己的 install 进程（PID %s），已结束且已回收" % pid)
        check(all(p.poll() is None for p in ext), "外部 adb 服务和外部 install 进程都还活着")
        src = "".join(open(os.path.join(REPO_DIR, f), encoding="utf-8").read() for f in
                      ("core/engine.py", "core/adbkit.py", "core/supervisor.py", "core/server.py", "app.py"))
        import re as _re
        hits = _re.findall(r"""["']kill-server["']|["'](?:pkill|killall)["']|\bos\.kill\(|\bos\.killpg\(""", src)
        check(not hits, "源码里没有作为命令出现的 kill-server / pkill / killall / os.kill（命中 %s）" % hits)
        I.ctl(".shell_fail")
        I.post("/api/supervisor/check")
        it = items(I)["Termux"]
        check(it["status"] == "cancelled" and it["code"] == "cancelled_not_installed",
              "设备恢复后核验：确实没装上（%s）" % it["code"])
    finally:
        I.close()
        for p in ext:
            p.kill()


def s14():
    print("\n[14] 单实例：连点启动、锁被占用、旧版本仍在运行")
    import tempfile, fcntl
    def launch(home, n=1, code_dir=None, extra=None):
        env = dict(os.environ, HOME=home, APKMGR_ADB=os.path.join(HERE_DIR, "fakeadb/adb"),
                   APKMGR_BROWSER="/bin/true", FAKE_DEV_ROOT=os.path.join(home, "dev"),
                   FAKE_ADB_LOG=os.path.join(home, "adb.log"))
        env.update(extra or {})
        return [subprocess.Popen([SERVER_PY, "app.py", "--app-mode"], cwd=code_dir or REPO_DIR, env=env,
                                 stdout=open(os.path.join(home, "launch.log"), "a"), stderr=subprocess.STDOUT)
                for _ in range(n)]
    bad = 0
    for r in range(10):
        home = tempfile.mkdtemp()
        ps = launch(home, 5)
        time.sleep(2.5)
        alive = sum(1 for p in ps if p.poll() is None)
        bad += alive != 1
        for p in ps: p.kill()
    check(bad == 0, "10 轮 × 同时启动 5 个：每轮都只有 1 个后台服务（异常 %d 轮）" % bad)

    home = tempfile.mkdtemp()
    os.makedirs(os.path.join(home, ".apk-installer"), exist_ok=True)
    fd = os.open(os.path.join(home, ".apk-installer", "instance.lock"), os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    p = launch(home)[0]
    time.sleep(12)
    check(p.poll() is not None and not os.path.exists(os.path.join(home, ".apk-installer", "port")),
          "锁被占用且对方不响应时，不会再起第二个服务（进程已退出）")
    os.close(fd)

    old = os.environ.get("APKMGR_TEST_OLD_CODE")
    if not old:
        check(False, "未提供旧版本代码目录（APKMGR_TEST_OLD_CODE），跳过旧版本升级测试")
        return
    home = tempfile.mkdtemp()
    po = launch(home, 1, code_dir=old)[0]
    pf = os.path.join(home, ".apk-installer", "port")
    for _ in range(100):
        if os.path.exists(pf): break
        time.sleep(0.1)
    time.sleep(1)
    pn = launch(home)[0]
    time.sleep(6)
    import urllib.request, json as _j
    v = _j.load(urllib.request.urlopen("http://127.0.0.1:%s/api/ping" % open(pf).read().strip(), timeout=3))
    check(po.poll() is not None and v.get("version") == "1.5.1",
          "空闲的旧版本（1.5.0）被请求退出，新版本接管（现在运行 %s）" % v.get("version"))
    for p in (po, pn): p.kill()

    # 旧版本正在安装：不能把它关掉，新启动的进程把窗口交给它后自己退出
    home = tempfile.mkdtemp()
    os.makedirs(os.path.join(home, "dev"), exist_ok=True)
    open(os.path.join(home, "dev", ".install_delay"), "w").write("8")
    po = launch(home, 1, code_dir=old)[0]
    pf = os.path.join(home, ".apk-installer", "port")
    for _ in range(100):
        if os.path.exists(pf): break
        time.sleep(0.1)
    time.sleep(2.5)
    port = open(pf).read().strip()
    def post(path, body):
        rq = urllib.request.Request("http://127.0.0.1:%s%s" % (port, path), data=_j.dumps(body).encode(),
                                    headers={"Content-Type": "application/json"})
        return _j.load(urllib.request.urlopen(rq, timeout=10))
    post("/api/import", {"path": APKS["termux"]})
    post("/api/install", {"serial": USB, "mode": "all"})
    time.sleep(1)
    pn = launch(home)[0]
    time.sleep(4)
    check(po.poll() is None and pn.poll() is not None,
          "旧版本正在安装时不会被关掉；新启动的进程交给它后退出（旧进程%s，新进程%s）" % (
              "仍在运行" if po.poll() is None else "已退出", "已退出" if pn.poll() is not None else "仍在运行"))
    for p in (po, pn): p.kill()


def s15():
    print("\n[15] 暂停后：刷新页面 / 多窗口不会偷偷检测；新出现的无线连接只标「不是本程序发起」")
    I = Inst("s15", FAST)
    try:
        ready(I)
        I.post("/api/supervisor/pause")
        time.sleep(1.2)
        t0 = time.time()
        for _ in range(15):
            I.get("/api/state"); I.get("/api/supervisor"); I.get("/api/devices")
        for _ in range(2):
            threading.Thread(target=lambda: [None for _ in urllib.request.urlopen(I.B + "/api/events", timeout=6)],
                             daemon=True).start()
        time.sleep(6)
        check(not I.adb_calls(t0), "暂停中刷新 45 次、开 2 个窗口：0 条 adb 命令（%d）" % len(I.adb_calls(t0)))
        I.ctl(".wireless", "192.168.1.77:5555")        # 别的程序连上了一台无线设备
        I.post("/api/supervisor/check")
        d = next(x for x in I.sup()["devices"] if x["serial"] == "192.168.1.77:5555")
        check(d.get("origin") == "unknown", "新出现的无线连接标为「不是本程序发起」（origin=%s）" % d.get("origin"))
        check(not [a for ts, a in I.adb_calls(0) if "connect" in a.split()], "本程序从未发出 connect")
    finally:
        I.close()


def s16():
    print("\n[16] 暂停中手动「检测一次」只执行一次，不恢复自动循环")
    I = Inst("s16", FAST)
    try:
        ready(I)
        I.post("/api/supervisor/pause")
        time.sleep(1.2)
        t0 = time.time()
        I.post("/api/supervisor/check")
        t1 = time.time()
        time.sleep(6)
        n = [a for ts, a in I.adb_calls(t0) if "devices" in a.split()]
        later = I.adb_calls(t1 + 0.05)
        check(len(n) == 1, "只执行了 1 次 adb devices（%d）" % len(n))
        check(not later, "之后 6 秒内没有任何 adb 命令（%d）" % len(later))
        check(I.sup()["bgPaused"], "仍处于暂停")
    finally:
        I.close()

ALL = {"1": s1, "2": s2, "3": s3, "4": s4, "5": s5, "6": s6, "7": s7, "8": s8, "9": s9,
       "10": s10, "11": s11, "12": s12, "13": s13, "14": s14, "15": s15, "16": s16}
if __name__ == "__main__":
    which = sys.argv[1:] or list(ALL)
    for k in which:
        try:
            ALL[k]()
        except Exception as exc:
            check(False, "场景 %s 异常：%r" % (k, exc))
    ok = sum(1 for r in RESULTS if r[0])
    print("\n===== %d / %d 项通过 =====" % (ok, len(RESULTS)))
    for good, msg in RESULTS:
        if not good:
            print("未通过：", msg)
