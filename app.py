#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APK 安装管家 —— Mac 上的安卓安装包批量安装 / 提取工具。

用法:
    python3 app.py              启动并自动打开浏览器界面
    python3 app.py --port 8765  指定端口
    python3 app.py --no-browser 不自动打开浏览器
    python3 app.py --app-mode   .app 启动器专用：自己挑端口、自己开窗口

启动路径刻意保持精简：先把监听端口绑好、把浏览器窗口拉起来，
再去导入服务端那一堆模块，让浏览器的冷启动和导入并行，窗口出现得更快。
"""
import os
import socket
import sys
import time

if sys.version_info < (3, 8):      # 先于任何新语法检查版本，给出明确提示而不是闪退
    msg = "APK Manager needs Python 3.8 or newer (found %d.%d)." % sys.version_info[:2]
    sys.stderr.write(msg + "\n")
    if sys.platform == "darwin":
        os.system("osascript -e 'display alert \"APK Manager\" message \"%s\"' >/dev/null 2>&1" % msg)
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.paths import PORT_FILE, BROWSER_FILE, SUPPORT_DIR  # noqa: E402
from core.version import VERSION  # noqa: E402

LOCK_FILE = os.path.join(SUPPORT_DIR, "instance.lock")

# 优先用这些浏览器的「应用窗口」模式打开（没有地址栏，看着就是个独立 App）
BROWSERS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def _write(path, text):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def pick_browser():
    """选一个浏览器。上次用过的直接复用，省掉探测；否则优先挑正在运行的那个。"""
    cached = os.environ.get("APKMGR_BROWSER") or _read(BROWSER_FILE)
    if cached and os.access(cached, os.X_OK):
        return cached
    found = [b for b in BROWSERS if os.access(b, os.X_OK)]
    if not found:
        return None
    chosen = found[0]
    if len(found) > 1:
        # 有多个就挑已经开着的，窗口能立刻出来，不用等冷启动
        try:
            import subprocess
            out = subprocess.run(["ps", "-Aco", "comm"], capture_output=True,
                                 timeout=3).stdout.decode("utf-8", "replace")
            running = set(out.split("\n"))
            for b in found:
                if os.path.basename(b) in running:
                    chosen = b
                    break
        except Exception:
            pass
    _write(BROWSER_FILE, chosen)
    return chosen


def open_window(url):
    """拉起界面窗口。用 posix_spawn，不额外导入 subprocess。"""
    exe = pick_browser()
    try:
        if exe:
            os.posix_spawn(exe, [exe, "--app=" + url, "--window-size=1280,880",
                                 "--no-first-run", "--no-default-browser-check"],
                           os.environ)
            return True
        if sys.platform == "darwin":
            os.posix_spawn("/usr/bin/open", ["open", url], os.environ)
            return True
    except Exception:
        pass
    try:
        import webbrowser
        webbrowser.open(url)
        return True
    except Exception:
        return False


def ping(port, timeout=0.4):
    """问一下这个端口上的是不是本程序、什么版本、忙不忙。旧版本没有 version 字段。"""
    import json
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout) as c:
            c.settimeout(timeout + 0.6)
            c.sendall(b"GET /api/ping HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            data = b""
            while True:
                chunk = c.recv(4096)
                if not chunk:
                    break
                data += chunk
        if b" 200 " not in data.split(b"\r\n", 1)[0]:
            return None
        body = data.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in data else b"{}"
        info = json.loads(body.decode("utf-8") or "{}")
        info["port"] = int(port)
        return info
    except Exception:
        return None


def _http(port, method, path, body=None, timeout=3):
    import json
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method,
                                 data=(json.dumps(body or {}).encode() if method == "POST" else None),
                                 headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except Exception:
        return None


def running_instance():
    port = _read(PORT_FILE)
    return ping(port) if port.isdigit() else None


def old_instance_busy(info):
    """True = 忙；False = 确认空闲；None = 无法判断。
    只有报告 busyProto>=2 的实例，busy 才覆盖安装、读取应用列表和提取 APK；
    更早的版本（≤1.5.1）不报告「提取中」，无法确认空闲，一律按「未知」处理，不自动关闭。"""
    try:
        if int(info.get("busyProto") or 0) >= 2 and "busy" in info:
            return bool(info["busy"])
    except (TypeError, ValueError):
        pass
    return None


NOTICE_OLD = {
    "zh": "已有旧版本 APK Manager（%s）在运行。为避免打断它正在做的事，新版本没有自动关闭它。\n"
          "请在旧版本窗口里点「退出」，再重新打开新版本。",
    "ja": "古いバージョンの APK Manager（%s）が動いています。作業を中断しないよう、自動では終了しませんでした。\n"
          "古いウインドウで「終了」を押してから、新しいバージョンを開き直してください。",
    "en": "An older APK Manager (%s) is still running. It wasn't closed automatically so nothing it's "
          "doing gets interrupted.\nQuit it from its window, then open the new version again.",
}


def notify_old_instance(version):
    """macOS 上弹一个不阻塞的提示；其他系统只写日志。"""
    if sys.platform != "darwin":
        return
    lang = (os.environ.get("LANG") or "").lower()
    key = "zh" if lang.startswith("zh") else "ja" if lang.startswith("ja") else "en"
    text = (NOTICE_OLD[key] % version).replace("\\", "\\\\").replace('"', '\\"')
    try:
        import subprocess
        subprocess.Popen(["/usr/bin/osascript", "-e",
                          'display dialog "%s" buttons {"OK"} default button 1 with title "APK Manager"' % text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def acquire_lock():
    """单实例锁。进程退出（包括崩溃）时系统自动释放，不会留下死锁。"""
    try:
        import fcntl
    except ImportError:                 # 非 POSIX 系统：不加锁
        return -1
    os.makedirs(SUPPORT_DIR, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        os.close(fd)
        return None


def log(msg):
    sys.stdout.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    sys.stdout.flush()


def settle_existing(app_mode):
    """处理已经在运行的实例。返回 True 表示「已交给现有实例，本进程应退出」。"""
    info = running_instance()
    if not info:
        return False
    url = "http://127.0.0.1:%d/" % info["port"]
    if info.get("version") == VERSION:
        log("已有同版本实例（PID %s），只打开窗口" % info.get("pid"))
        if app_mode:
            open_window(url)
        return True
    busy = old_instance_busy(info)
    if busy is not False:
        # 旧版本正在工作，或者无法确认它空闲：不能把它关掉，先用它
        ver = info.get("version", "<1.5.1")
        log("旧版本实例 %s %s，暂不替换，打开它的窗口" % (
            ver, "正在工作（%s）" % ",".join(info.get("busyKinds") or []) if busy else "无法确认是否空闲"))
        if app_mode:
            open_window(url)
            if busy is None:
                notify_old_instance(ver)
        return True
    log("发现旧版本实例 %s，空闲，请它退出后由新版本接管" % info.get("version", "<1.5.1"))
    _http(info["port"], "POST", "/api/quit", {})
    for _ in range(80):
        if not ping(info["port"], 0.2):
            break
        time.sleep(0.1)
    return False

def bind_port(port=0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(128)
    return s


def _watchdog(engine, grace):
    """界面窗口关掉（没有任何页面连着）超过 grace 秒就退出，避免后台残留进程。
    正在安装 / 扫描 / 提取时不退出。"""
    import time
    start = time.time()
    while True:
        time.sleep(3)
        bus = engine.bus
        if not bus.ever_connected:
            if time.time() - start > 120:   # 两分钟都没人打开界面
                os._exit(0)
            continue
        busy = engine.busy_kinds()                 # 安装 / 读取应用列表 / 提取：与接管、退出检查同一个判断
        if busy or bus.viewers() > 0:
            continue
        if time.time() - bus.last_seen > grace:
            os._exit(0)


def main():
    argv = sys.argv[1:]
    app_mode = "--app-mode" in argv
    no_browser = "--no-browser" in argv
    port = 0
    auto_quit = 25 if app_mode else 0
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
        elif a == "--auto-quit" and i + 1 < len(argv):
            auto_quit = int(argv[i + 1])
        elif a in ("-h", "--help"):
            print(__doc__)
            return
    if not app_mode and port == 0:
        port = 8777

    log("APK Manager %s · Python %s (%s) · PID %d" % (
        VERSION, "%d.%d.%d" % sys.version_info[:3], sys.executable, os.getpid()))

    # 已经有实例在跑：同版本就只拉起窗口；旧版本空闲就让它退出，由新版本接管
    if settle_existing(app_mode):
        return
    # 单实例锁：连点多次、多个启动同时进来，也只会有一个后台服务
    lock_fd = None
    for _ in range(100):
        lock_fd = acquire_lock()
        if lock_fd is not None:
            break
        if settle_existing(app_mode):   # 另一个启动刚抢到锁，等它起来后交给它
            return
        time.sleep(0.1)
    if lock_fd is None:
        log("另一个实例持有锁但没有响应，本次不再启动第二个后台服务")
        return
    if settle_existing(app_mode):       # 抢到锁之后再确认一次（旧版本不持锁）
        return

    # 先绑端口 —— 这样浏览器马上就能开始加载，不用等下面的导入
    try:
        sock = bind_port(port)
    except OSError:
        sock = bind_port(0)
    real_port = sock.getsockname()[1]
    url = "http://127.0.0.1:%d/" % real_port

    if app_mode:
        _write(PORT_FILE, str(real_port))
        open_window(url)                 # 浏览器冷启动与下面的导入并行进行

    from core.server import serve        # 到这一步才付导入的代价
    httpd, url, boot = serve(sock=sock, open_browser=not (app_mode or no_browser))

    log("服务已启动：%s" % url)
    if not app_mode:
        print("=" * 56)
        print("  APK 安装管家已启动")
        print("  界面地址: %s" % url)
        print("  关闭这个窗口即可退出程序")
        print("=" * 56)

    if auto_quit > 0:
        import threading
        def later():
            engine = boot.wait(60)
            if engine:
                _watchdog(engine, auto_quit)
        threading.Thread(target=later, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        if app_mode:
            try:
                os.remove(PORT_FILE)
            except Exception:
                pass


if __name__ == "__main__":
    main()
