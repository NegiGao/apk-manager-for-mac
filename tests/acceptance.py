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
from harness import Inst, APKS, REPO as REPO_DIR, HERE as HERE_DIR, SERVER_PY, CODE as CODE_DIR
_vns = {}
exec(open(os.path.join(CODE_DIR, "core", "version.py")).read(), _vns)
CODE_VERSION = _vns["VERSION"]

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
        # 后台启动时会自己选中 USB 设备；先切到另一台，确保下面「选回 USB」是一次真正的切换，会排队标记查询
        I.post("/api/supervisor/select", {"serial": "SECOND01"})
        time.sleep(2)
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
        check(it["Termux"]["status"] == "pending_verify" and it["Termux"]["arg"] == "identity_changed"
              and (it["Termux"].get("pendingOn") or {}).get("physical") == "PHYS-A",
              "装完后同一 Wi-Fi 地址背后换了手机 → 不拿另一台的版本判成功，保持待核验并绑定原机（%s/%s）" % (
                  it["Termux"]["status"], it["Termux"]["arg"]))
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
        check(it["Termux"]["status"] == "pending_verify" and it["Termux"]["arg"] == "identity_changed",
              "USB 无序号 + 装完后拔插换上同序列号的另一台 → 不判成功，保持待核验（%s/%s）" % (
                  it["Termux"]["status"], it["Termux"]["arg"]))
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
        return [subprocess.Popen([SERVER_PY, "app.py", "--app-mode"], cwd=code_dir or CODE_DIR, env=env,
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
    try:
        pn.wait(15)
    except Exception:
        pass
    import urllib.request, json as _j
    v = _j.load(urllib.request.urlopen("http://127.0.0.1:%s/api/ping" % open(pf).read().strip(), timeout=3))
    # 1.5.0 / 1.5.1 不报告「提取中」，无法确认它真的空闲 → 按「未知」处理，不自动关闭（第 21 场景测新协议的接管）
    check(po.poll() is None and pn.poll() is not None and v.get("version") != CODE_VERSION,
          "旧版本（1.5.0）无法确认是否空闲：不自动关闭，新进程把窗口交给它后退出（仍运行 %s）" % (v.get("version") or "1.5.0，它不报告版本号"))
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


# ---------------------------------------------------------------------------
# v1.5.2：针对第二轮审查的回归测试。并发时序全部用假 adb 的屏障卡在确定位置，不靠反复运行或 sleep 碰运气。
def after(I, t, pat):
    import re as _re
    return [a for ts, a in I.adb_calls(t) if _re.search(pat, a)]


def s17():
    print("\n[17] 暂停门控：暂停一旦确认，安装线程和核验都不再发起新命令；迟到的核验结果不写入")
    I = Inst("s17a", FAST)
    try:
        ready(I)
        import_all(I, ("termux", "newpipe"))
        # USB 上 __SN__（安装引擎的身份读取）依次是：开始时、第 1 项前、第 1 项核验、第 2 项前 → 卡住第 4 次
        I.hold("pre2", "__SN__", skip=3)
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait_held("pre2")
        st = items(I)
        check(st["Termux"]["status"] == "success" and st["NewPipe"]["status"] == "waiting",
              "屏障位置正确：第 1 项已完成，正在为第 2 项读取设备身份")
        t_pause = time.time()
        r = I.post("/api/supervisor/pause")
        I.release("pre2")
        I.wait(lambda: job(I).get("paused"), timeout=20, what="队列暂停")
        bad = after(I, t_pause, r"\binstall\b")
        check(r.get("ok") and not bad, "身份查询期间暂停：确认后没有再启动安装（%d 条 install）" % len(bad))
        check(items(I)["NewPipe"]["status"] == "pending", "第 2 项保持未安装（%s）" % items(I)["NewPipe"]["status"])
    finally:
        I.close()

    I = Inst("s17b", FAST)
    try:
        ready(I)
        I.post("/api/import", {"path": APKS["termux"]})
        I.hold("verify_id", "__SN__", skip=2)        # 第 3 次 = 第 1 项装完后的核验身份读取
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait_held("verify_id")
        t_pause = time.time()
        I.post("/api/supervisor/pause")
        I.release("verify_id")
        I.wait(lambda: items(I)["Termux"]["status"] != "installing", timeout=20, what="第 1 项结束")
        it = items(I)["Termux"]
        q = after(I, t_pause, r"__BEGIN__")
        check(not q, "核验读身份期间暂停：确认后没有再发包查询（%d 条）" % len(q))
        check(it["status"] == "pending_verify" and (it.get("lastRun") or {}).get("rc") == 0,
              "记为待核验，adb 退出码与日志保留（%s, rc=%s）" % (it["status"], (it.get("lastRun") or {}).get("rc")))

        # 恢复后 verify_pending 开始核验；查询还没返回时再次暂停 → 迟到的结果不能写入
        I.hold("vp", "__BEGIN__")
        I.post("/api/supervisor/resume")
        I.wait_held("vp")
        I.post("/api/supervisor/pause")
        I.release("vp")
        I.wait(lambda: not os.path.exists(os.path.join(I.dev, ".hold_vp")), what="放行")
        time.sleep(2)                                # 观察窗口：结果若被写入会在这段时间内出现
        it = items(I)["Termux"]
        check(it["status"] == "pending_verify", "暂停后才返回的核验结果没有写入（%s）" % it["status"])
        I.post("/api/supervisor/resume")
        I.wait(lambda: items(I)["Termux"]["status"] == "success", timeout=20, what="恢复后核验")
        check(True, "再次恢复后重新核验 → 成功")
    finally:
        I.close()


def s18():
    print("\n[18] 待核验遇到换机不丢绑定：换回原机继续时不重复安装")
    I = Inst("s18", FAST)
    try:
        I.ctl(".wireless", WIFI)
        ready(I)
        import_all(I, ("termux", "newpipe"))
        I.hold("inst", r" install ")
        I.post("/api/install", {"serial": WIFI, "mode": "all"})
        I.wait_held("inst")
        I.post("/api/supervisor/pause")              # 当前这项装完记为待核验，不开始下一项
        I.release("inst")
        I.wait(lambda: job(I).get("paused"), timeout=20, what="暂停")
        check(items(I)["Termux"]["status"] == "pending_verify", "第 1 项装完，待核验")
        I.ctl(".wifi_phone", "PHYS-B")               # 同一个 Wi-Fi 地址背后换了另一台
        t_res = time.time()
        I.post("/api/supervisor/resume")
        I.wait(lambda: after(I, t_res, "__SN__"), timeout=20, what="恢复后核验")
        time.sleep(1.5)
        it = items(I)["Termux"]
        check(it["status"] == "pending_verify" and (it.get("pendingOn") or {}).get("serial") == WIFI,
              "身份对不上：保持待核验并保留原设备绑定（%s, 绑定 %s）" % (
                  it["status"], (it.get("pendingOn") or {}).get("physical")))
        I.ctl(".wifi_phone")                         # 换回原机
        t_cont = time.time()
        I.events.clear()
        r = I.post("/api/install/continue", {})
        check(r.get("ok"), "换回原机后继续（%s）" % (r.get("code") or "ok"))
        I.wait(lambda: any(e["type"] in ("install_done", "install_paused") for e in I.events), timeout=30, what="结束")
        again = after(I, t_cont, r"install .*termux\.apk")
        st = items(I)
        check(not again, "已装好的第 1 项没有被重复安装（%d 次）" % len(again))
        check(st["Termux"]["status"] == "success" and st["NewPipe"]["status"] == "success",
              "第 1 项核验成功、第 2 项正常安装（%s / %s）" % (st["Termux"]["status"], st["NewPipe"]["status"]))
    finally:
        I.close()


def s19():
    print("\n[19] Package Manager 报错（shell 正常、首尾标志完整）不能判成「未安装」")
    I = Inst("s19", FAST)
    try:
        ready(I)
        I.post("/api/import", {"path": APKS["termux"]})
        I.hold("inst", r" install ")
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait_held("inst")
        I.ctl(".pm_error", "1")
        I.release("inst")
        I.wait(lambda: items(I)["Termux"]["status"] != "installing", timeout=20, what="结束")
        it = items(I)["Termux"]
        check(it["status"] == "pending_verify" and it["code"] == "verify_query_failed",
              "pm 报错 → 待核验（%s / %s）" % (it["status"], it["code"]))
        check((it.get("installed") or {}).get("state") != "none", "安装标记没有被改成「未安装」")
        I.ctl(".pm_error")
        I.post("/api/supervisor/check")
        I.wait(lambda: items(I)["Termux"]["status"] == "success", timeout=20, what="恢复后核验")
        check(True, "pm 恢复后核验 → 成功")
    finally:
        I.close()


def s20():
    print("\n[20] 目标身份无法确认时不自动续装（至少 2 个 APK，第 1 项后换机）")
    I = Inst("s20a", FAST)
    try:
        I.ctl(".serialno_empty", "1")
        I.ctl(".wireless", WIFI)
        I.wait(lambda: I.sup()["devicesAt"] and len(I.sup()["devices"]) == 2, what="设备")
        time.sleep(1.5)
        import_all(I, ("termux", "newpipe"))
        I.ctl(".swap_after_install", "1")            # 第 1 项装完后，同一 IP 背后换成另一台同样没有序号的机器
        I.post("/api/install", {"serial": WIFI, "mode": "all"})
        I.wait(lambda: any(e["type"] in ("install_done", "install_paused") for e in I.events), timeout=30, what="结束")
        n = after(I, 0, r"install .*newpipe\.apk")
        check(not n, "Wi-Fi 身份未知：第 1 项后没有继续往（可能换掉的）机器上装（%d 次）" % len(n))
        check(job(I).get("pauseReason") == "target_unconfirmed",
              "队列暂停，原因「无法确认设备身份」（%s）" % job(I).get("pauseReason"))
    finally:
        I.close()

    I = Inst("s20b", FAST)
    try:
        I.ctl(".serialno_empty", "1")
        I.ctl(".transport_id", "")
        I.wait(lambda: I.sup()["devicesAt"] and len(I.sup()["devices"]) == 1, what="设备")
        time.sleep(1.5)
        import_all(I, ("termux", "newpipe"))
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait(lambda: any(e["type"] in ("install_done", "install_paused") for e in I.events), timeout=30, what="结束")
        n = after(I, 0, r"install .*newpipe\.apk")
        check(not n and job(I).get("pauseReason") == "target_unconfirmed",
              "USB 无序号且无 transport_id：同样只装 1 项就停（%d 次，%s）" % (len(n), job(I).get("pauseReason")))
    finally:
        I.close()


def _s20_continue_all(name, skip, preinstalled):
    """身份未知的 Wi-Fi 设备上装 3 个 APK，一直点「继续」直到结束；数每个 APK 实际发起了几次 install。"""
    I = Inst(name, FAST, {"skipSameVersion": skip})
    try:
        I.ctl(".serialno_empty", "1")
        I.ctl(".wireless", WIFI)
        for key, pkg in preinstalled:
            I.preinstall(key, pkg)
        I.wait(lambda: I.sup()["devicesAt"] and len(I.sup()["devices"]) == 2, what="设备")
        time.sleep(1.5)
        order = ("newpipe", "termux", "seal")
        import_all(I, order)
        def ended():
            return any(e["type"] in ("install_done", "install_paused") for e in I.events)
        I.events.clear()
        r = I.post("/api/install", {"serial": WIFI, "mode": "all"})
        presses, finished = 0, False
        for _ in range(8):
            I.wait(ended, timeout=30, what="本轮结束")
            if any(e["type"] == "install_done" for e in I.events):
                finished = True
                break
            I.events.clear()
            r = I.post("/api/install/continue", {})
            presses += 1
            if not r.get("ok"):
                break
        counts = {k: len(after(I, 0, r"install .*%s\.apk" % k)) for k in order}
        st = items(I)
        return I, finished, presses, counts, st, r
    except Exception:
        I.close()
        raise


def s20b_continue():
    print("\n[20b] 身份未知时一直点「继续」：每项只装一次，队列能走到底（跳过同版本 关 / 开）")
    I, finished, presses, counts, st, r = _s20_continue_all("s20c", False, ())
    try:
        check(finished and presses == 2, "跳过同版本=关：点 %d 次继续后结束（期望 2 次，结束=%s）" % (presses, finished))
        check(all(v == 1 for v in counts.values()), "每个 APK 只发起 1 次安装（%s）" % counts)
        check(all(st[k]["status"] == "unverified" and st[k]["code"] == "verify_identity_unknown"
                  for k in ("NewPipe", "Termux", "Seal")),
              "已装过的项保持「未核验（身份未知）」的真实状态，没有被说成成功（%s）" % {
                  k: st[k]["status"] for k in ("NewPipe", "Termux", "Seal")})
        r2 = I.post("/api/install/continue", {})
        check(not r2.get("ok") and r2.get("code") == "nothing_remaining", "结束后再点继续：没有可装的（%s）" % r2.get("code"))
        t = time.time()
        I.events.clear()
        r3 = I.post("/api/install", {"serial": WIFI, "mode": "all"})
        I.wait(lambda: any(e["type"] in ("install_done", "install_paused") for e in I.events), timeout=30, what="重装")
        n = len(after(I, t, r"install .*newpipe\.apk"))
        check(r3.get("ok") and n == 1, "明确选「全部重装」时才会重装第 1 项（%d 次）" % n)
    finally:
        I.close()

    # 跳过同版本=开，第 1 项设备上已是同版本：跳过不算「一次机会」
    I, finished, presses, counts, st, r = _s20_continue_all("s20d", True, (("newpipe", "org.schabi.newpipe"),))
    try:
        check(finished and presses == 1, "跳过同版本=开：点 %d 次继续后结束（期望 1 次，结束=%s）" % (presses, finished))
        check(counts == {"newpipe": 0, "termux": 1, "seal": 1}, "已是同版本的不装，其余各装 1 次（%s）" % counts)
        check(st["NewPipe"]["status"] == "skipped", "跳过的项标为已跳过（%s）" % st["NewPipe"]["status"])
    finally:
        I.close()


def _launch_app(home, code_dir=None, extra=None):
    env = dict(os.environ, HOME=home, APKMGR_ADB=os.path.join(HERE_DIR, "fakeadb/adb"),
               APKMGR_BROWSER="/bin/true", FAKE_DEV_ROOT=os.path.join(home, "dev"),
               FAKE_ADB_LOG=os.path.join(home, "adb.log"))
    env.update(extra or {})
    os.makedirs(os.path.join(home, "dev"), exist_ok=True)
    sf = os.path.join(home, ".apk-installer", "settings.json")
    if not os.path.exists(sf):                       # 提取的文件留在临时 HOME 里，不写进代码目录
        os.makedirs(os.path.dirname(sf), exist_ok=True)
        json.dump({"extractDir": home}, open(sf, "w"))
    return subprocess.Popen([SERVER_PY, "app.py", "--app-mode"], cwd=code_dir or CODE_DIR, env=env,
                            stdout=open(os.path.join(home, "launch.log"), "a"), stderr=subprocess.STDOUT)


def _api(port, path, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    rq = urllib.request.Request("http://127.0.0.1:%s%s" % (port, path), data=data,
                                headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(rq, timeout=timeout))


def _extracting_instance(home, code_dir=None, extra=None):
    """起一个实例，并让它卡在「提取 APK」的 adb pull 上。返回 (进程, 端口)。"""
    import tempfile as _t
    dev = os.path.join(home, "dev")
    os.makedirs(os.path.join(dev, "data/app/com.termux-1"), exist_ok=True)
    import shutil as _sh
    _sh.copyfile(APKS["termux"], os.path.join(dev, "data/app/com.termux-1", "base.apk"))
    open(os.path.join(dev, ".hold_pull"), "w").write(" pull \n0")
    p = _launch_app(home, code_dir, extra)
    pf = os.path.join(home, ".apk-installer", "port")
    for _ in range(150):
        if os.path.exists(pf) and open(pf).read().strip():
            break
        time.sleep(0.1)
    port = open(pf).read().strip()
    for _ in range(100):
        try:
            if _api(port, "/api/state").get("devices"):
                break
        except Exception:
            pass
        time.sleep(0.1)
    time.sleep(1.5)
    _api(port, "/api/extract", {"serial": USB, "packages": ["com.termux"]})
    for _ in range(300):
        if os.path.exists(os.path.join(dev, ".held_pull")):
            break
        time.sleep(0.02)
    return p, port


def s21():
    print("\n[21] 提取 APK 也算「忙碌」：接管、退出检查、关窗退出共用同一个判断")
    import tempfile
    I = Inst("s21a", FAST)
    try:
        ready(I)
        I.preinstall("termux", "com.termux")
        I.hold("pull", r" pull ")
        I.post("/api/extract", {"serial": USB, "packages": ["com.termux"]})
        I.wait_held("pull")
        p = I.get("/api/ping")
        check(p.get("busy") and "extract" in (p.get("busyKinds") or []),
              "提取中：/api/ping 报告忙碌（busy=%s, %s）" % (p.get("busy"), p.get("busyKinds")))
        r = I.post("/api/quit", {})
        time.sleep(1)
        check(not r.get("ok") and r.get("code") == "busy_extract" and I.proc.poll() is None,
              "提取中点退出：默认拒绝（%s），进程仍在" % r.get("code"))
        I.release("pull")
        I.wait(lambda: any(e["type"] == "extract_done" for e in I.events), timeout=20, what="提取完成")
        check(not I.get("/api/ping").get("busy"), "提取结束后不再忙碌")
    finally:
        I.close()


def s22():
    print("\n[22] 版本接管：旧版本在提取中（或无法确认是否空闲）不被关掉；能确认空闲才接管")
    import tempfile
    old = os.environ.get("APKMGR_TEST_OLD_CODE")
    if old:
        home = tempfile.mkdtemp()
        po, port = _extracting_instance(home, old)
        held = os.path.exists(os.path.join(home, "dev", ".held_pull"))
        pn = _launch_app(home)
        try:
            pn.wait(15)
        except Exception:
            pass
        check(held and po.poll() is None and pn.poll() is not None,
              "旧版本（1.5.0）正在提取：新版本不把它当空闲关掉（旧进程%s，新进程%s）" % (
                  "仍在运行" if po.poll() is None else "被关掉了", "已退出" if pn.poll() is not None else "仍在运行"))
        os.remove(os.path.join(home, "dev", ".hold_pull"))
        for p in (po, pn):
            p.kill()
    else:
        check(False, "未提供 APKMGR_TEST_OLD_CODE，跳过旧版本提取中接管测试")

    # 新协议（会报告提取状态）的较旧版本：提取中不关，空闲时才接管
    home = tempfile.mkdtemp()
    po, port = _extracting_instance(home, None, {"APKMGR_TEST_VERSION": "1.5.1.9"})
    pn = _launch_app(home)
    try:
        pn.wait(15)
    except Exception:
        pass
    check(po.poll() is None and pn.poll() is not None, "报告完整忙碌状态的旧版本在提取中：不关闭")
    os.remove(os.path.join(home, "dev", ".hold_pull"))
    for _ in range(100):
        try:
            if not _api(port, "/api/ping").get("busy"):
                break
        except Exception:
            break
        time.sleep(0.1)
    pn = _launch_app(home)
    for _ in range(150):
        if po.poll() is not None:
            break
        time.sleep(0.1)
    v = None
    try:
        v = _api(open(os.path.join(home, ".apk-installer", "port")).read().strip(), "/api/ping").get("version")
    except Exception:
        pass
    check(po.poll() is not None and v == CODE_VERSION, "同一旧版本空闲后：被请求退出，新版本 %s 接管" % v)
    for p in (po, pn):
        p.kill()

def wait_for(pred, timeout, step=0.2):
    t = time.time()
    while time.time() - t < timeout:
        try:
            if pred():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


def s23():
    print("\n[23] 插上 USB 线的设备默认成为当前设备（只改界面选中的设备，不改安装任务绑定）")
    sel = lambda I: I.sup().get("selected")
    I = Inst("s23a", FAST)
    try:
        I.ctl(".unplugged", "1")                         # 主 USB 先不插
        I.ctl(".wireless", WIFI)
        I.ctl(".extra_devices", "CABLE01\tdevice")       # 列表里 Wi-Fi 在前，USB 在后
        I.wait(lambda: I.sup()["devicesAt"] and len(I.sup()["devices"]) == 2, what="设备")
        if not wait_for(lambda: sel(I), 6):
            # 后台没有选择时，界面会自己选列表里第一台可用设备（旧版就是这样）——这里照做，模拟打开的窗口
            first = next(d["serial"] for d in I.sup()["devices"] if d["state"] == "device")
            I.post("/api/supervisor/select", {"serial": first})
        check(sel(I) == "CABLE01", "启动时 USB 优先于 Wi-Fi（选中 %s）" % sel(I))

        I.post("/api/supervisor/select", {"serial": WIFI})
        I.events.clear()
        I.ctl(".unplugged")                              # 插上另一台的 USB 线
        wait_for(lambda: sel(I) == USB, 15)
        ev = [e for e in I.events if e["type"] == "device_autoselect"]
        check(sel(I) == USB and ev and ev[-1]["previous"] == WIFI,
              "选着 Wi-Fi 时插上 USB 线 → 自动切到它，并提示（事件 %d 条）" % len(ev))

        I.ctl(".unplugged", "1")                         # 拔掉
        time.sleep(3)
        check(sel(I) == USB, "拔掉后不自动换成其他已连设备（仍是 %s，界面显示已断开）" % sel(I))

        I.ctl(".extra_devices", "CABLE01\tdevice\nPHONEB\tdevice")   # 换插另一台手机
        wait_for(lambda: sel(I) == "PHONEB", 15)
        check(sel(I) == "PHONEB", "拔掉 A、插上 B → 自动选中 B（选中 %s）" % sel(I))

        I.ctl(".unplugged")                              # 又插上一根线，但当前已选着在线的 USB 设备
        time.sleep(3)
        check(sel(I) == "PHONEB", "已选着在线的 USB 设备时，再插一台不抢选择（仍是 %s）" % sel(I))

        I.post("/api/supervisor/usb-only", {"serial": "PHONEB"})
        I.ctl(".unplugged", "1"); time.sleep(2.5); I.ctl(".unplugged")
        time.sleep(3)
        check(sel(I) == "PHONEB", "「仅 USB」锁定时不切换（仍是 %s）" % sel(I))
    finally:
        I.close()

    # 暂停中的队列绑定在 Wi-Fi 设备上：插上 USB 后选择会切过去，但继续安装仍只装到原设备
    I = Inst("s23b", FAST)
    try:
        I.ctl(".unplugged", "1")
        I.ctl(".wireless", WIFI)
        I.wait(lambda: I.sup()["devicesAt"] and len(I.sup()["devices"]) == 1, what="设备")
        time.sleep(1.5)
        import_all(I, ("termux", "newpipe"))
        I.hold("inst", r" install ")
        I.post("/api/install", {"serial": WIFI, "mode": "all"})
        I.wait_held("inst")
        I.post("/api/install/cancel-current", {})
        I.release("inst")
        I.wait(lambda: job(I).get("paused"), timeout=20, what="队列暂停")
        I.ctl(".unplugged")
        if not wait_for(lambda: sel(I) == USB, 15):
            I.post("/api/supervisor/select", {"serial": USB})   # 旧版不会自动切：手动选上，照样检查绑定
        t = time.time()
        I.events.clear()
        r = I.post("/api/install/continue", {})
        I.wait(lambda: any(e["type"] in ("install_done", "install_paused") for e in I.events), timeout=30, what="继续结束")
        on_usb = after(I, t, r"-s %s install" % USB)
        on_wifi = after(I, t, r"-s %s install" % WIFI.replace(".", r"\."))
        check(r.get("ok") and not on_usb and on_wifi,
              "选择切到 USB 后点「继续」：只装到队列绑定的原设备（USB %d 次，Wi-Fi %d 次）" % (len(on_usb), len(on_wifi)))
    finally:
        I.close()

def s24():
    print("\n[24] 「仅 USB」跟着线走：锁定的那台没插着时，自动改用用线连着的手机（启动时也一样）")
    sup = lambda I: I.sup()
    uo = lambda I: (sup(I).get("usbOnly") or {}).get("serial")
    I = Inst("s24a", FAST, {"usbOnly": {"serial": "OLDPHONE", "physical": "PHYS-OLD", "name": "Old phone"}})
    try:
        I.ctl(".wireless", WIFI)                         # 启动时：上次锁定的旧手机没插着，现在插着 USB 线的是另一台
        I.wait(lambda: sup(I)["devicesAt"] and len(sup(I)["devices"]) == 2, what="设备")
        wait_for(lambda: uo(I) == USB, 10)
        check(uo(I) == USB and sup(I).get("selected") == USB,
              "启动时插着线：「仅 USB」自动锁到这台并选中（锁定 %s，选中 %s）" % (uo(I), sup(I).get("selected")))

        I.ctl(".extra_devices", "PHONEB\tdevice")        # 锁定的那台还在，又插了一台
        time.sleep(3)
        check(uo(I) == USB, "锁定的那台还连着时，再插一台不改锁定（仍是 %s）" % uo(I))

        I.events.clear()
        I.ctl(".unplugged", "1")                         # 拔掉锁定的那台，另一台还插着
        wait_for(lambda: uo(I) == "PHONEB", 15)
        ev = [e for e in I.events if e["type"] == "usb_only_follow"]
        check(uo(I) == "PHONEB" and sup(I).get("selected") == "PHONEB" and ev,
              "锁定的那台拔掉 → 跟到还插着线的另一台，并提示（锁定 %s，事件 %d 条）" % (uo(I), len(ev)))

        I.ctl(".extra_devices")                          # 只剩 Wi-Fi
        time.sleep(3)
        check(uo(I) == "PHONEB", "没有任何 USB 设备时不会锁到 Wi-Fi 设备（仍是 %s）" % uo(I))
    finally:
        I.close()

    # 暂停中的队列绑定在原来那台：锁定跟到新手机后，「继续」不会装到新手机上
    I = Inst("s24b", FAST)
    try:
        ready(I)
        I.post("/api/supervisor/usb-only", {"serial": USB})
        import_all(I, ("termux", "newpipe"))
        I.hold("inst", r" install ")
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait_held("inst")
        I.post("/api/install/cancel-current", {})
        I.release("inst")
        I.wait(lambda: job(I).get("paused"), timeout=20, what="队列暂停")
        I.ctl(".unplugged", "1")
        I.ctl(".extra_devices", "PHONEB\tdevice")
        wait_for(lambda: uo(I) == "PHONEB", 15)
        t = time.time()
        r = I.post("/api/install/continue", {})
        time.sleep(3)
        on_b = after(I, t, r"-s PHONEB install")
        check(uo(I) == "PHONEB" and not r.get("ok") and not on_b,
              "锁定跟到新手机后点「继续」：不装到新手机（%s，新手机安装 %d 次）" % (r.get("code"), len(on_b)))
    finally:
        I.close()

def s25():
    print("\n[25] 插着线一键转无线：「仅 USB」开着时先确认再关；成功后自动连上并选中无线；adbd 重启造成的 USB 闪断不把选择抢回去")
    sup = lambda I: I.sup()
    WIFI_T = "192.168.1.9:5555"
    I = Inst("s25a", FAST)
    try:
        ready(I)
        I.post("/api/supervisor/usb-only", {"serial": USB})
        t0 = time.time()
        r = I.post("/api/wireless/switch", {"serial": USB})
        check(not r.get("ok") and r.get("code") == "usb_only_blocks_tcpip" and not after(I, t0, r"\btcpip\b"),
              "「仅 USB」开着、没确认：不切无线，没有发 tcpip（%s）" % r.get("code"))
        I.ctl(".tcpip_flap", "1")
        t1 = time.time()
        r = I.post("/api/wireless/switch", {"serial": USB, "exitUsbOnly": True}, timeout=60)
        st = sup(I)
        check(r.get("ok") and r.get("target") == WIFI_T and r.get("usbOnlyOff") and not st.get("usbOnly"),
              "确认后：关闭「仅 USB」，转无线并连上 %s（%s）" % (r.get("target"), r.get("error") or "ok"))
        check(len(after(I, t1, r"\btcpip\b")) == 1 and after(I, t1, r"\bconnect\b"), "只发了 1 次 tcpip，并发起连接")
        check(st.get("selected") == WIFI_T, "当前设备自动切到这条无线连接（%s）" % st.get("selected"))
        wait_for(lambda: any(d["serial"] == USB and d["state"] == "device" for d in sup(I)["devices"]), 15)
        time.sleep(3)
        check(sup(I).get("selected") == WIFI_T,
              "adbd 重启后 USB 重新出现：不把选择抢回 USB（%s）" % sup(I).get("selected"))
        check(WIFI_T in (I.get("/api/state").get("settings", {}).get("wirelessHistory") or []),
              "记住了这个无线地址，之后可自动重连")
    finally:
        I.close()

    # 安装进行中：不关「仅 USB」、不切无线
    I = Inst("s25b", FAST)
    try:
        ready(I)
        I.post("/api/supervisor/usb-only", {"serial": USB})
        I.post("/api/import", {"path": APKS["termux"]})
        I.hold("inst", r" install ")
        I.post("/api/install", {"serial": USB, "mode": "all"})
        I.wait_held("inst")
        t = time.time()
        r = I.post("/api/wireless/switch", {"serial": USB, "exitUsbOnly": True})
        check(not r.get("ok") and sup(I).get("usbOnly") and not after(I, t, r"\btcpip\b"),
              "安装进行中：拒绝（%s），「仅 USB」保持，没有发 tcpip" % r.get("code"))
        I.release("inst")
    finally:
        I.close()

def s26():
    print("\n[26] 单独安装 / 单独卸载 / 版本与制作者信息")
    I = Inst("s26", FAST)
    try:
        ready(I)
        I.preinstall("termux", "com.termux")
        import_all(I, ("termux", "newpipe", "seal"))
        st = I.get("/api/state")
        ab = st.get("about") or {}
        vns = {}
        exec(open(os.path.join(CODE_DIR, "core", "version.py")).read(), vns)
        check(ab.get("author") == "NegiGao" and ab.get("homepage") == "https://github.com/NegiGao/apk-manager-for-mac"
              and ab.get("version") == vns["VERSION"] == st.get("version"),
              "/api/state 带版本、制作者、GitHub 地址（%s / %s / %s）" % (ab.get("version"), ab.get("author"), ab.get("homepage")))
        ids = {i["label"]: i["id"] for i in st["items"]}
        t = time.time()
        I.events.clear()
        r = I.post("/api/install", {"serial": USB, "mode": "all", "ids": [ids["NewPipe"]]})
        I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=30, what="单独安装完成")
        inst = after(I, t, r" install ")
        it = items(I)
        check(r.get("ok") and len(inst) == 1 and "newpipe" in inst[0],
              "单独安装：只对这一个 APK 发了 1 次 install（%s）" % [a.split("/")[-1] for a in inst])
        check(it["NewPipe"]["status"] == "success" and it["Termux"]["status"] == "pending" and it["Seal"]["status"] == "pending",
              "只有这一项变成已安装，其他项保持原样（%s / %s / %s）" % (it["NewPipe"]["status"], it["Termux"]["status"], it["Seal"]["status"]))

        I.post("/api/mark", {"serial": USB})
        I.wait(lambda: (items(I)["Termux"].get("installed") or {}).get("state") == "same", what="标记")
        t = time.time()
        I.events.clear()
        r = I.post("/api/uninstall", {"serial": USB, "packages": ["com.termux"], "labels": {"com.termux": "Termux"}})
        I.wait(lambda: any(e["type"] == "uninstall_done" for e in I.events), timeout=30, what="卸载完成")
        un = after(I, t, r" uninstall ")
        check(r.get("ok") and len(un) == 1 and un[0].endswith("com.termux"),
              "单独卸载：只对这一个包发了 uninstall（%s）" % un)
        it = items(I)
        check((it["Termux"].get("installed") or {}).get("state") == "none"
              and (it["NewPipe"].get("installed") or {}).get("state") == "same",
              "卸载后：这一项标为未安装，其他已安装的不受影响（%s / %s）" % (
                  (it["Termux"].get("installed") or {}).get("state"), (it["NewPipe"].get("installed") or {}).get("state")))
    finally:
        I.close()

ALL = {"1": s1, "2": s2, "3": s3, "4": s4, "5": s5, "6": s6, "7": s7, "8": s8, "9": s9,
       "10": s10, "11": s11, "12": s12, "13": s13, "14": s14, "15": s15, "16": s16,
       "17": s17, "18": s18, "19": s19, "20": s20, "20b": s20b_continue, "21": s21, "22": s22,
       "23": s23, "24": s24, "25": s25, "26": s26}
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
    sys.exit(0 if RESULTS and ok == len(RESULTS) else 1)     # 有失败项 → 非零退出码
