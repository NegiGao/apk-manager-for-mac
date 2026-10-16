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
from harness import Inst, APKS

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
        I.post("/api/supervisor/pause")       # 暂停后台不能杀掉正在进行的安装
        I.post("/api/install/pause")
        I.wait(lambda: job(I).get("paused"), timeout=20, what="暂停")
        j = job(I)
        check(j["pauseReason"] == "user" and j["ok"] == 1 and j["remaining"] == 2,
              "第一个装完才停（成功 %d，剩余 %d）" % (j["ok"], j["remaining"]))
        check(len([a for ts, a in I.adb_calls(t0) if "install" in a.split()]) == 1, "暂停后没有开始第二个")
        I.post("/api/supervisor/resume")
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


ALL = {"1": s1, "2": s2, "3": s3, "4": s4, "5": s5, "6": s6, "7": s7, "8": s8, "9": s9}
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
