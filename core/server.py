# -*- coding: utf-8 -*-
"""本地 HTTP 服务：给浏览器界面提供 API（仅监听 127.0.0.1）。"""
import json
import mimetypes
import os
import queue
import re
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .engine import Engine, STAGING_DIR, ICON_DIR, human_size
from .adbkit import download_platform_tools, find_adb, BASE_DIR

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
TOKEN = uuid.uuid4().hex


class Boot(object):
    """承载后台初始化的引擎，让 HTTP 端口可以先监听、后干活。"""

    def __init__(self):
        self.engine = None
        self.ready = threading.Event()
        self.error = None

    def start(self):
        def run():
            try:
                self.engine = Engine()
                Handler.engine = self.engine
            except Exception as exc:
                self.error = str(exc)
            finally:
                self.ready.set()
        threading.Thread(target=run, daemon=True).start()
        return self

    def wait(self, timeout=20):
        self.ready.wait(timeout)
        return self.engine


class Handler(BaseHTTPRequestHandler):
    engine = None
    boot = None
    protocol_version = "HTTP/1.1"
    server_version = "APKInstaller/1.0"

    def log_message(self, fmt, *args):
        pass

    # -- 工具 ------------------------------------------------------------
    def _send(self, code, body=b"", ctype="application/json; charset=utf-8",
              extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return b""
        chunks = []
        remain = n
        while remain > 0:
            chunk = self.rfile.read(min(remain, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remain -= len(chunk)
        return b"".join(chunks)

    def _json_body(self):
        try:
            return json.loads(self._body().decode("utf-8") or "{}")
        except Exception:
            return {}

    def _query(self):
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, dict(urllib.parse.parse_qsl(parsed.query))

    # -- 路由 ------------------------------------------------------------
    def _wait_engine(self, timeout=25):
        """静态资源不等引擎；需要引擎的接口最多等它初始化完。"""
        if self.engine is not None:
            return self.engine
        if self.boot is not None:
            self.boot.wait(timeout)
        return self.engine

    def do_GET(self):
        path, q = self._query()
        try:
            # 页面与静态资源不依赖引擎，先发出去，界面立刻可见
            if path == "/" or path == "/index.html":
                return self._file(os.path.join(WEB_DIR, "index.html"))
            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                safe = os.path.normpath(rel).lstrip("./")
                return self._file(os.path.join(WEB_DIR, safe))
            if path == "/api/ping":
                return self._json({"ok": True, "ready": self.engine is not None})
            E = self._wait_engine()
            if E is None:
                return self._json({"ok": False, "booting": True,
                                   "error": "正在启动…"}, 200)
            if path == "/api/state":
                return self._json(E.state())
            if path == "/api/devices":
                return self._json(E.devices())
            if path == "/api/profiles":
                return self._json({"ok": True, "profiles": E.profiles()})
            if path == "/api/apps":
                scan = E.apps_scan or {}
                return self._json({"ok": True, "running": scan.get("running", False),
                                   "total": scan.get("total", 0),
                                   "done": scan.get("done", 0),
                                   "apps": scan.get("apps", []),
                                   "error": scan.get("error")})
            if path.startswith("/api/icon/"):
                return self._file(os.path.join(ICON_DIR, path.split("/")[-1] + ".img"),
                                  ctype="image/png")
            if path.startswith("/api/appicon/"):
                return self._file(os.path.join(ICON_DIR, path.split("/")[-1]),
                                  ctype="image/png")
            if path == "/api/events":
                return self._events()
            return self._send(404, "not found", "text/plain; charset=utf-8")
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)}, 500)

    def do_POST(self):
        path, q = self._query()
        E = self._wait_engine()
        try:
            if E is None:
                return self._json({"ok": False, "booting": True,
                                   "error": "程序还在启动，请稍候"}, 200)
            if path == "/api/upload":
                name = urllib.parse.unquote(self.headers.get("X-File-Name") or "upload.apk")
                name = os.path.basename(name)
                safe = re.sub(r'[\\/:*?"<>|]', "_", name)
                dest = os.path.join(STAGING_DIR, uuid.uuid4().hex[:8] + "_" + safe)
                n = int(self.headers.get("Content-Length") or 0)
                with open(dest, "wb") as f:
                    remain = n
                    while remain > 0:
                        chunk = self.rfile.read(min(remain, 1 << 20))
                        if not chunk:
                            break
                        f.write(chunk)
                        remain -= len(chunk)
                return self._json(E.add_file(dest, source="staged", original_name=name))
            if path == "/api/import":
                data = self._json_body()
                p = (data.get("path") or "").strip().strip("'\"")
                if not p:
                    return self._json({"ok": False, "error": "请填写文件或文件夹路径"})
                p = os.path.expanduser(p)
                if os.path.isdir(p):
                    return self._json(E.add_folder(p))
                return self._json(E.add_file(p, source="link"))
            if path == "/api/queue/remove":
                return self._json(E.remove(self._json_body().get("ids") or []))
            if path == "/api/queue/clear":
                return self._json(E.clear())
            if path == "/api/queue/reorder":
                return self._json(E.reorder(self._json_body().get("ids") or []))
            if path == "/api/queue/sort":
                d = self._json_body()
                return self._json(E.sort_by(d.get("key"), bool(d.get("desc"))))
            if path == "/api/queue/reset":
                return self._json(E.reset_status())
            if path == "/api/install":
                d = self._json_body()
                return self._json(E.start_install(d.get("serial"), d.get("ids")))
            if path == "/api/install/stop":
                return self._json(E.stop_install())
            if path == "/api/settings":
                d = self._json_body()
                E.settings.update(d or {})
                E.save_settings()
                return self._json({"ok": True, "settings": E.settings})
            if path == "/api/profile/save":
                return self._json(E.save_profile(self._json_body().get("name")))
            if path == "/api/profile/load":
                d = self._json_body()
                return self._json(E.load_profile(d.get("name"), d.get("replace", True)))
            if path == "/api/profile/delete":
                return self._json(E.delete_profile(self._json_body().get("name")))
            if path == "/api/apps/scan":
                d = self._json_body()
                return self._json(E.start_app_scan(d.get("serial"),
                                                   d.get("scope", "third"),
                                                   d.get("icons", True)))
            if path == "/api/apps/stop":
                return self._json(E.stop_app_scan())
            if path == "/api/extract":
                d = self._json_body()
                threading.Thread(
                    target=E.extract,
                    args=(d.get("serial"), d.get("packages") or [], d.get("apps")),
                    daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/wireless/pair":
                d = self._json_body()
                return self._json(E.wireless_pair(d.get("hostPort"), d.get("code")))
            if path == "/api/wireless/connect":
                return self._json(E.wireless_connect(self._json_body().get("hostPort")))
            if path == "/api/wireless/disconnect":
                return self._json(E.wireless_disconnect(self._json_body().get("hostPort")))
            if path == "/api/wireless/switch":
                d = self._json_body()
                return self._json(E.wireless_switch(d.get("serial"),
                                                    int(d.get("port") or 5555)))
            if path == "/api/wireless/forget":
                return self._json(E.forget_wireless(self._json_body().get("hostPort")))
            if path == "/api/mark":
                return self._json(E.mark_installed(self._json_body().get("serial")))
            if path == "/api/uninstall":
                d = self._json_body()
                threading.Thread(
                    target=E.uninstall,
                    args=(d.get("serial"), d.get("packages") or [],
                          bool(d.get("keepData", E.settings.get("keepDataOnUninstall"))),
                          d.get("labels") or {}),
                    daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/reveal":
                return self._json(E.reveal(self._json_body().get("path") or BASE_DIR))
            if path == "/api/adb/download":
                def run():
                    try:
                        p = download_platform_tools(
                            progress=lambda m: E.bus.emit("adb", text=m))
                        E.adb.path = p or find_adb()
                        E.bus.emit("adb", text="完成" if E.adb.available else "失败",
                                   done=True, ok=E.adb.available)
                    except Exception as exc:
                        E.bus.emit("adb", text="下载失败: %s" % exc, done=True, ok=False)
                threading.Thread(target=run, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/adb/set":
                p = (self._json_body().get("path") or "").strip()
                if p and os.path.isfile(p):
                    E.adb.path = p
                    return self._json({"ok": True, "path": p})
                return self._json({"ok": False, "error": "路径无效"})
            if path == "/api/quit":
                threading.Thread(target=self._shutdown, daemon=True).start()
                return self._json({"ok": True})
            return self._send(404, "not found", "text/plain; charset=utf-8")
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)}, 500)

    def _shutdown(self):
        time.sleep(0.4)
        os._exit(0)

    # -- SSE -------------------------------------------------------------
    def _events(self):
        E = self._wait_engine()
        if E is None:
            return self._json({"ok": False, "booting": True}, 200)
        q = E.bus.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    evt = q.get(timeout=5)   # 5 秒心跳，便于及时发现窗口已关
                    payload = json.dumps(evt, ensure_ascii=False)
                    self.wfile.write(("data: %s\n\n" % payload).encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            E.bus.unsubscribe(q)

    # -- 静态文件 ---------------------------------------------------------
    def _file(self, path, ctype=None):
        if not os.path.isfile(path):
            return self._send(404, "not found", "text/plain; charset=utf-8")
        ctype = ctype or (mimetypes.guess_type(path)[0] or "application/octet-stream")
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, ctype)


def serve(port=0, open_browser=True):
    # 先把端口监听起来（毫秒级），引擎在后台初始化，窗口就能立刻打开
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    boot = Boot().start()
    Handler.boot = boot
    real_port = httpd.server_address[1]
    url = "http://127.0.0.1:%d/" % real_port
    if open_browser:
        def op():
            import webbrowser
            webbrowser.open(url)
        threading.Thread(target=op, daemon=True).start()
    return httpd, url, boot
