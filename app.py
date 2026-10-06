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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.paths import PORT_FILE, BROWSER_FILE, SUPPORT_DIR  # noqa: E402

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


def already_running():
    """已经有一个实例在跑就返回它的地址，这时只要把窗口重新拉起来。"""
    port = _read(PORT_FILE)
    if not port.isdigit():
        return None
    try:
        with socket.create_connection(("127.0.0.1", int(port)), 0.25) as c:
            c.sendall(b"GET /api/ping HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            if b"200" in c.recv(64):
                return "http://127.0.0.1:%s/" % port
    except Exception:
        pass
    return None


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
        busy = (engine.job and engine.job.get("running")) or \
               (engine.apps_scan and engine.apps_scan.get("running"))
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

    # 已经有实例在跑：把窗口拉回来就行，不用再起一个服务
    if app_mode:
        url = already_running()
        if url:
            open_window(url)
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
