"""对 v1.5.0 复现评审提出的风险点。只用来确认问题是否真实存在，修复后由正式验收场景覆盖。"""
import os, sys, time, threading, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Inst, APKS
FAST = {"APKMGR_DISCOVERY_INTERVAL": "1", "APKMGR_RECONNECT_BACKOFF": "1,2,3"}
USB = "FAKE1234567890"

def job(I): return I.get("/api/state")["job"] or {}
def items(I): return {i["label"]: i for i in I.get("/api/state")["items"]}
def ready(I):
    I.wait(lambda: all(d.get("physical") for d in I.sup()["devices"] if d["state"] == "device") and I.sup()["devicesAt"], what="ready")

print("\n[P1] 慢安装途中点「暂停后台」：下一项会不会继续装？核验查询会不会照发？")
I = Inst("p1", FAST)
try:
    I.ctl(".install_delay", "2"); ready(I)
    for k in ("termux", "newpipe"): I.post("/api/import", {"path": APKS[k]})
    I.post("/api/install", {"serial": USB, "mode": "all"})
    I.wait(lambda: job(I).get("current"), what="start")
    time.sleep(0.4); I.post("/api/supervisor/pause"); tp = time.time()
    time.sleep(6)
    calls = [a for ts, a in I.adb_calls(tp)]
    print("   暂停后新发出的 adb 命令:", len(calls))
    for a in calls: print("     ", a[:110])
    print("   第二项状态:", items(I)["NewPipe"]["status"])
finally:
    I.close()

print("\n[P2] 安装成功后设备立刻查询出错：会不会被当成「没装」？")
I = Inst("p2", FAST)
try:
    ready(I); I.post("/api/import", {"path": APKS["termux"]})
    I.ctl(".fail_after_install", "1")
    I.post("/api/install", {"serial": USB, "mode": "all"})
    I.wait(lambda: any(e["type"] in ("install_done", "install_paused") for e in I.events), timeout=30, what="done")
    it = items(I)["Termux"]; print("   结果:", it["status"], it["code"], "| 标记:", it.get("installed"))
finally:
    I.close()

print("\n[P3] 取消当前安装后查询出错：会不会直接说「没装上」？")
I = Inst("p3", FAST)
try:
    I.ctl(".install_delay", "3"); ready(I); I.post("/api/import", {"path": APKS["termux"]})
    I.post("/api/install", {"serial": USB, "mode": "all"})
    I.wait(lambda: job(I).get("current"), what="start"); time.sleep(0.5)
    I.ctl(".shell_fail", "1"); I.post("/api/install/cancel-current")
    I.wait(lambda: job(I).get("paused"), timeout=20, what="paused")
    it = items(I)["Termux"]; print("   结果:", it["status"], it["code"])
finally:
    I.close()

print("\n[P4] 序号读出来是空的：核验会不会照样判成功？")
I = Inst("p4", FAST)
try:
    ready(I); I.post("/api/import", {"path": APKS["termux"]})
    I.ctl(".serialno_empty", "1")
    I.post("/api/install", {"serial": USB, "mode": "all"})
    I.wait(lambda: any(e["type"] in ("install_done", "install_paused") for e in I.events), timeout=30, what="done")
    print("   结果:", items(I)["Termux"]["code"])
finally:
    I.close()

print("\n[P5] 手动「标记已安装」途中换了设备：旧结果会不会写进队列？")
I = Inst("p5", FAST)
try:
    I.ctl(".extra_devices", "SECOND01\tdevice"); ready(I)
    I.post("/api/import", {"path": APKS["termux"]})
    I.post("/api/supervisor/select", {"serial": USB}); time.sleep(1.5)
    I.ctl(".slow_pm", "3")
    th = threading.Thread(target=lambda: I.post("/api/mark", {"serial": USB})); th.start()
    time.sleep(0.5); I.ctl(".slow_pm")
    I.post("/api/supervisor/select", {"serial": "SECOND01"}); time.sleep(1.5)
    th.join()
    print("   最终标记属于:", (items(I)["Termux"].get("installed") or {}).get("serial"), "（当前选中 SECOND01）")
finally:
    I.close()

print("\n[P6] 同时连点 5 次启动：会起几个服务？")
import json, shutil, tempfile
home = tempfile.mkdtemp()
env = dict(os.environ, HOME=home, APKMGR_ADB=os.path.join(os.path.dirname(__file__), "fakeadb/adb"),
           APKMGR_BROWSER="/bin/true", FAKE_DEV_ROOT=home + "/dev")
repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ps = [subprocess.Popen([sys.executable, "app.py", "--app-mode"], cwd=repo, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(5)]
time.sleep(4)
alive = [p for p in ps if p.poll() is None]
print("   仍在运行的服务进程:", len(alive))
for p in ps: p.kill()
