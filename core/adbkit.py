# -*- coding: utf-8 -*-
"""adb 封装: 定位/下载 adb、设备列表、安装、已装应用枚举与 APK 提取。"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile

from . import apkinfo as AI

from .paths import (HOME, APP_DIR, SUPPORT_DIR, BASE_DIR, ensure_dir)  # noqa: F401

PLATFORM_TOOLS_URL = {
    "darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
    "win32": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
}

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# --------------------------------------------------------------------------
# 定位 adb
# --------------------------------------------------------------------------
def candidate_adb_paths():
    out = []
    env = os.environ.get("APKMGR_ADB")
    if env:
        out.append(env)
    out.append(os.path.join(SUPPORT_DIR, "platform-tools", "adb"))
    out.append(os.path.join(BASE_DIR, "platform-tools", "adb"))
    which = shutil.which("adb")
    if which:
        out.append(which)
    for base in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                 os.path.join(HOME, "Library", "Android", "sdk"),
                 os.path.join(HOME, "Android", "Sdk")):
        if base:
            out.append(os.path.join(base, "platform-tools", "adb"))
    out += ["/opt/homebrew/bin/adb", "/usr/local/bin/adb", "/usr/bin/adb",
            os.path.join(HOME, "platform-tools", "adb")]
    return out


def find_adb():
    for p in candidate_adb_paths():
        try:
            if p and os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        except Exception:
            continue
    return None


def download_platform_tools(progress=None):
    """下载官方 platform-tools 到应用支持目录，返回 adb 路径。"""
    import urllib.request
    key = "darwin" if sys.platform == "darwin" else ("win32" if os.name == "nt" else "linux")
    url = PLATFORM_TOOLS_URL[key]
    ensure_dir(SUPPORT_DIR)
    zip_path = os.path.join(SUPPORT_DIR, "platform-tools.zip")
    if progress:
        progress("正在从 Google 官方源下载 adb 工具…")
    with urllib.request.urlopen(url, timeout=120) as resp, open(zip_path, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = resp.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if progress and total:
                progress("下载中 %d%%" % int(got * 100 / total))
    dest = os.path.join(SUPPORT_DIR, "platform-tools")
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(SUPPORT_DIR)
    os.remove(zip_path)
    adb = os.path.join(dest, "adb")
    for name in os.listdir(dest):
        p = os.path.join(dest, name)
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o755)
            except Exception:
                pass
    if sys.platform == "darwin":
        # 去掉下载隔离属性，免得 macOS 拦截
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", dest],
                       capture_output=True)
    if progress:
        progress("adb 工具已就绪")
    return adb if os.path.isfile(adb) else None


# --------------------------------------------------------------------------
# adb 调用
# --------------------------------------------------------------------------
class AdbError(Exception):
    pass


class AdbBlocked(Exception):
    """命令在发起前被「门控」拦下（例如已经暂停）：没有启动任何 adb 进程。"""

    def __init__(self, reason):
        Exception.__init__(self, reason)
        self.reason = reason


# 这些子命令作用于某一台具体设备，必须带 -s 指定目标，避免设备多于一台时装错机器
DEVICE_CMDS = {
    "install", "install-multiple", "uninstall", "shell", "exec-out", "pull", "push",
    "tcpip", "usb", "get-state", "get-serialno", "reboot", "root", "unroot",
    "logcat", "forward", "reverse", "sideload",
}

_ctx = threading.local()


class _Gate(object):
    """with adb.gated(check): ... —— 这段代码里每条 adb 命令启动前，都在 gate_lock 内调用 check()；
    返回非空原因就不启动进程，抛 AdbBlocked。暂停操作也在 gate_lock 内改标志，
    所以「暂停」一返回，之后不会再有受门控的命令被启动（已经在跑的那条除外）。"""

    def __init__(self, check):
        self.check = check
        self.prev = None

    def __enter__(self):
        self.prev = getattr(_ctx, "gate", None)
        _ctx.gate = self.check
        return self

    def __exit__(self, *a):
        _ctx.gate = self.prev


class _Source(object):
    """with adb.source("bg:discovery"): ... —— 给这段代码里发出的 adb 命令打上来源标签，
    控制台里能看到每条命令是谁发的（界面操作 / 后台任务 / 安装）。"""

    def __init__(self, name):
        self.name = name
        self.prev = None

    def __enter__(self):
        self.prev = getattr(_ctx, "source", None)
        _ctx.source = self.name
        return self

    def __exit__(self, *a):
        _ctx.source = self.prev


def _short(cmd, path):
    out = []
    for i, c in enumerate(cmd):
        if i == 0 and c == path:
            out.append("adb")
        elif " " in c or not c:
            out.append('"%s"' % c)
        else:
            out.append(c)
    return " ".join(out)


class Adb(object):
    def __init__(self, path=None):
        self.path = path or find_adb()
        self._lock = threading.Lock()
        self._lk = threading.Lock()
        self.gate_lock = threading.RLock()         # 门控：检查暂停标志 + 启动进程 是一个原子步骤
        self.log = collections.deque(maxlen=400)   # 最近的 adb 命令记录
        self.active = {}                            # 正在执行的 adb 命令 token -> 信息
        self._tok = 0
        self.listeners = []                         # 命令结束时的回调
        self._version = None

    @property
    def available(self):
        return bool(self.path and os.path.isfile(self.path))

    @staticmethod
    def source(name):
        return _Source(name)

    @staticmethod
    def gated(check):
        return _Gate(check)

    def _spawn(self, cmd, serial, **kw):
        """在门控下启动进程并登记。返回 (proc, tok)。"""
        with self.gate_lock:
            check = getattr(_ctx, "gate", None)
            if check is not None:
                why = check()
                if why:
                    raise AdbBlocked(why)
            proc = subprocess.Popen(cmd, **kw)
            tok = self._begin(proc, cmd, serial)
        return proc, tok

    def _base(self, serial=None):
        if not self.available:
            raise AdbError("未找到 adb，可在界面上点「自动下载 adb」一键安装")
        cmd = [self.path]
        if serial:
            cmd += ["-s", serial]
        return cmd

    @staticmethod
    def _check_scope(args, serial):
        if args and args[0] in DEVICE_CMDS and not serial:
            raise AdbError("拒绝执行未指定目标设备的 adb %s" % args[0])

    def _begin(self, proc, cmd, serial):
        with self._lk:
            self._tok += 1
            tok = self._tok
            self.active[tok] = {
                "pid": proc.pid, "cmd": _short(cmd, self.path), "serial": serial,
                "source": getattr(_ctx, "source", None) or "ui",
                "started": time.time(),
            }
        return tok

    def _end(self, tok, rc, out, t0, timed_out=False):
        with self._lk:
            info = self.active.pop(tok, None) or {}
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        rec = dict(info)
        rec.update({
            "rc": rc, "ms": int((time.time() - t0) * 1000),
            "out": (out or "").strip()[-600:], "timeout": timed_out,
            "ended": time.time(),
        })
        rec.pop("started", None)
        self.log.append(rec)
        for cb in list(self.listeners):
            try:
                cb(rec)
            except Exception:
                pass

    def active_list(self):
        with self._lk:
            now = time.time()
            return [dict(v, ms=int((now - v["started"]) * 1000), pid=v["pid"])
                    for v in self.active.values()]

    def run(self, args, serial=None, timeout=120, binary=False):
        self._check_scope(args, serial)
        cmd = self._base(serial) + args
        t0 = time.time()
        proc, tok = self._spawn(cmd, serial, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            self._end(tok, -9, (out or b"") + (err or b""), t0, timed_out=True)
            raise
        except Exception:
            self._end(tok, -1, b"", t0)
            raise
        self._end(tok, proc.returncode, (out or b"") + (err or b""), t0)
        if binary:
            return proc.returncode, out, err.decode("utf-8", "replace")
        return (proc.returncode, out.decode("utf-8", "replace"),
                err.decode("utf-8", "replace"))

    def stream(self, args, serial=None, on_line=None, timeout=1800, on_proc=None):
        """流式执行，逐行回调。返回 (returncode, 全部输出)。
        on_proc(proc) 让调用方拿到进程句柄（用于「取消当前安装」）。"""
        self._check_scope(args, serial)
        cmd = self._base(serial) + args
        t0 = time.time()
        proc, tok = self._spawn(cmd, serial, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                bufsize=1, universal_newlines=True, errors="replace")
        if on_proc:
            try:
                on_proc(proc)
            except Exception:
                pass
        lines = []
        timed_out = False
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                lines.append(line)
                if on_line and line.strip():
                    on_line(line)
                if time.time() - t0 > timeout:
                    timed_out = True
                    proc.kill()
                    break
            proc.wait()
        finally:
            self._end(tok, proc.returncode, "\n".join(lines), t0, timed_out)
        return proc.returncode, "\n".join(lines)

    # -- adb 服务本身的信息（只读，不会启动或重启服务）-------------------
    def version(self):
        if self._version is None and self.available:
            try:
                code, out, err = self.run(["version"], timeout=8)
                m = re.search(r"Android Debug Bridge version ([\d.]+)", out)
                v = re.search(r"Version ([\w.\-]+)", out)
                self._version = " / ".join(x for x in [
                    m.group(1) if m else None, v.group(1) if v else None] if x) or out.strip()[:60]
            except Exception:
                self._version = None
        return self._version

    def server_status(self):
        """adb 服务状态。只做只读检查：探测端口、列出进程；不 start-server、不 kill。"""
        port = int(os.environ.get("ANDROID_ADB_SERVER_PORT") or 5037)
        listening = False
        try:
            import socket
            with socket.create_connection(("127.0.0.1", port), 0.3):
                listening = True
        except Exception:
            pass
        procs = []
        ours = {v["pid"] for v in self.active_list()}
        mine_real = os.path.realpath(self.path) if self.path else None
        try:
            out = subprocess.run(["ps", "-Ao", "pid=,ppid=,args="], capture_output=True,
                                 timeout=3).stdout.decode("utf-8", "replace")
        except Exception:
            out = ""
        for line in out.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) < 3:
                continue
            pid, ppid, args = parts
            toks = args.split()
            argv0 = toks[0] if toks else ""
            # 有些工具用脚本包一层 adb：ps 里第一个是解释器，第二个才是 adb
            if os.path.basename(argv0) in ("bash", "sh", "zsh", "python", "python3") and len(toks) > 1:
                argv0 = toks[1]
                args = " ".join(toks[1:])
            if os.path.basename(argv0) != "adb":
                continue
            pid, ppid = int(pid), int(ppid)
            is_server = "fork-server" in args or ("server" in args.split()[1:3])
            same_bin = bool(mine_real) and os.path.realpath(argv0) == mine_real
            if pid in ours or ppid == os.getpid():
                owner = "ours"
            elif is_server:
                owner = "server_same" if same_bin else "server_other"
            else:
                owner = "unknown"
            procs.append({"pid": pid, "args": args[:200], "server": is_server,
                          "sameBinary": same_bin, "owner": owner})
        return {"port": port, "listening": listening, "processes": procs,
                "path": self.path, "version": self.version()}

    def get_state(self, serial, timeout=6):
        try:
            code, out, err = self.run(["get-state"], serial=serial, timeout=timeout)
            return (out or err).strip().splitlines()[-1] if (out or err).strip() else ""
        except AdbBlocked:
            raise
        except Exception as exc:
            return "error: %s" % exc

    def read_serialno(self, serial, timeout=8):
        """三态读取物理序号：ok（有值）/ empty（读成功但设备不提供）/ error（读取本身失败）。"""
        try:
            code, out, err = self.run(
                ["shell", "echo __SN__; getprop ro.serialno; getprop ro.boot.serialno; echo __END__"],
                serial=serial, timeout=timeout)
        except AdbBlocked:
            raise
        except Exception as exc:
            return {"state": "error", "err": str(exc)[:200]}
        if "__SN__" not in out or "__END__" not in out:
            return {"state": "error", "err": ((err or out).strip().splitlines() or ["?"])[-1][:200]}
        body = out.split("__SN__", 1)[1].split("__END__", 1)[0]
        for v in body.splitlines():
            v = v.strip()
            if v and v != "unknown":
                return {"state": "ok", "value": v}
        return {"state": "empty"}

    def physical_serial(self, serial, timeout=8):
        """设备的物理序号（ro.serialno），用来判断 USB 和 Wi-Fi 两个入口是不是同一台机器。"""
        try:
            code, out, _ = self.run(
                ["shell", "getprop ro.serialno; getprop ro.boot.serialno"],
                serial=serial, timeout=timeout)
            for v in out.splitlines():
                v = v.strip()
                if v and v != "unknown":
                    return v
        except Exception:
            pass
        return None

    def start_server(self):
        try:
            self.run(["start-server"], timeout=30)
        except Exception:
            pass

    # -- 设备 -----------------------------------------------------------
    def devices(self):
        try:
            code, out, err = self.run(["devices", "-l"], timeout=8)
        except AdbBlocked:
            raise
        except Exception as exc:
            raise AdbError(str(exc))
        devs = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            serial = parts[0]
            state = parts[1] if len(parts) > 1 else "unknown"
            extra = {}
            for tok in parts[2:]:
                if ":" in tok:
                    k, v = tok.split(":", 1)
                    extra[k] = v
            devs.append({
                "serial": serial,
                "state": state,
                "model": extra.get("model", "").replace("_", " "),
                "device": extra.get("device", ""),
                "product": extra.get("product", ""),
                "transport": extra.get("transport_id", ""),
            })
        return devs

    # -- 无线连接 --------------------------------------------------------
    def transport_id(self, serial):
        """adb 给这条连接分配的 transport_id；每次重新连接（拔插、换机）都会变。
        返回字符串；adb 不提供时返回 ""；`adb devices` 本身失败时抛 AdbError。"""
        for d in self.devices():
            if d["serial"] == serial:
                return d.get("transport") or ""
        return ""

    @staticmethod
    def is_wireless_serial(serial):
        """无线设备的序列号形如 192.168.1.9:5555 或 adb-XXXX._adb-tls-connect._tcp"""
        s = serial or ""
        if "._tcp" in s or s.startswith("adb-"):
            return True
        if ":" in s:
            host, _, port = s.rpartition(":")
            return bool(host) and port.isdigit()
        return False

    def pair(self, host_port, code):
        """用手机「无线调试」里的配对码配对（Android 11+）。"""
        code = re.sub(r"\D", "", code or "")
        if not code:
            return False, "请输入手机上显示的 6 位配对码"
        try:
            rc, o, e = self.run(["pair", host_port, code], timeout=60)
            out = (o or "") + (e or "")
        except subprocess.TimeoutExpired:
            return False, "配对超时：检查手机与电脑是否在同一个 Wi-Fi"
        except Exception as exc:
            return False, str(exc)
        if "Successfully paired" in out or "paired to" in out.lower():
            return True, out.strip()
        return False, out.strip() or "配对失败"

    def connect(self, host_port, timeout=15):
        if ":" not in host_port:
            host_port += ":5555"
        try:
            code, out, err = self.run(["connect", host_port], timeout=timeout)
        except Exception as exc:
            return False, str(exc), host_port
        text = (out or "") + (err or "")
        ok = "connected to" in text.lower() and "cannot" not in text.lower() \
            and "failed" not in text.lower()
        return ok, text.strip(), host_port

    def disconnect(self, host_port):
        if not host_port:
            return False, "必须指定要断开的 IP:端口"
        args = ["disconnect", host_port]
        try:
            code, out, err = self.run(args, timeout=30)
            return True, ((out or "") + (err or "")).strip()
        except Exception as exc:
            return False, str(exc)

    def device_ip(self, serial):
        """读设备的无线局域网 IP。"""
        for cmd in ("ip -f inet addr show wlan0",
                    "ip route get 1.1.1.1",
                    "ifconfig wlan0"):
            try:
                code, out, _ = self.run(["shell", cmd], serial=serial, timeout=20)
            except Exception:
                continue
            m = re.search(r"(?:inet |src )(\d+\.\d+\.\d+\.\d+)", out)
            if m and not m.group(1).startswith("127."):
                return m.group(1)
        return None

    def enable_tcpip(self, serial, port=5555):
        """把 USB 连着的设备切到无线模式，返回 (ok, ip:port, 信息)。"""
        ip = self.device_ip(serial)
        if not ip:
            return False, None, "读不到设备的 Wi-Fi 地址，请确认手机已连上 Wi-Fi"
        try:
            code, out, err = self.run(["tcpip", str(port)], serial=serial, timeout=40)
        except Exception as exc:
            return False, None, str(exc)
        text = ((out or "") + (err or "")).strip()
        if "restarting" not in text.lower() and "error" in text.lower():
            return False, None, text
        target = "%s:%d" % (ip, port)
        # 手机上的 adbd 切到无线要一点时间：最多试 4 次（约 1 / 2 / 3 / 4 秒后），连上就停
        ok, msg = False, text
        for wait in (1.2, 2, 3, 4):
            time.sleep(wait)
            ok, msg, _ = self.connect(target)
            if ok:
                break
        return ok, target, (msg or text)

    def device_detail(self, serial):
        props = {}
        try:
            keys = [("brand", "ro.product.brand"), ("model", "ro.product.model"),
                    ("android", "ro.build.version.release"), ("sdk", "ro.build.version.sdk"),
                    ("abi", "ro.product.cpu.abi"), ("serialno", "ro.serialno")]
            cmd = "; ".join('echo "%s=$(getprop %s)"' % (k, p) for k, p in keys)
            code, out, _ = self.run(["shell", cmd], serial=serial, timeout=8)
            for line in out.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() in dict(keys) and v.strip():
                        props[k.strip()] = v.strip()
        except Exception:
            pass
        return props

    # -- 安装 -----------------------------------------------------------
    def install(self, serial, apk_paths, on_line=None, flags=None,
                timeout=1800, on_proc=None):
        if not serial:
            raise AdbError("安装必须指定目标设备")
        flags = list(flags or [])
        if len(apk_paths) > 1:
            args = ["install-multiple"] + flags + list(apk_paths)
        else:
            args = ["install"] + flags + [apk_paths[0]]
        return self.stream(args, serial=serial, on_line=on_line, timeout=timeout,
                           on_proc=on_proc)

    def uninstall(self, serial, package, keep_data=False):
        args = ["uninstall"]
        if keep_data:
            args.append("-k")
        args.append(package)
        return self.run(args, serial=serial, timeout=180)

    def is_installed(self, serial, package):
        try:
            code, out, _ = self.run(["shell", "pm", "path", package], serial=serial, timeout=30)
            return "package:" in out
        except Exception:
            return False

    def installed_version(self, serial, package):
        try:
            code, out, _ = self.run(
                ["shell", "dumpsys package %s | grep -m2 -E 'versionName|versionCode'" % package],
                serial=serial, timeout=30)
            vn = re.search(r"versionName=(\S+)", out)
            vc = re.search(r"versionCode=(\d+)", out)
            return (vn.group(1) if vn else None, int(vc.group(1)) if vc else None)
        except Exception:
            return (None, None)

    def query_package(self, serial, package, timeout=20):
        """三态查询，用于安装后核验与取消后核验：
            present  —— 查询成功，设备上有这个包（附版本）
            absent   —— 查询成功，设备上确实没有
            error    —— 查询本身失败（离线、断开、命令出错），结果未知
        「查询失败」绝不能被当成「没装」。
        只有首尾标志完整还不够（pm 服务报错时 echo 照样成功），所以分别取 pm path 与
        pm list packages 的退出码和输出：
            present —— pm path 退出码 0 且输出了 package: 行
            absent  —— pm path 退出码为 0/1 且没有任何输出（真 pm 找不到包时就是退出码 1、无输出），
                       并且 pm list packages 退出码 0、只输出 package: 行、其中没有这个包（证明服务正常）
            其他一律 error。"""
        cmd = ("echo __BEGIN__; pm path {p} 2>&1; echo __PMRC=$?; "
               "pm list packages {p} 2>&1; echo __LSRC=$?; "
               "dumpsys package {p} | grep -m2 -E 'versionCode=|versionName='; "
               "echo __END__").format(p=package)
        try:
            code, out, err = self.run(["shell", cmd], serial=serial, timeout=timeout)
        except AdbBlocked:
            raise
        except Exception as exc:
            return {"state": "error", "err": str(exc)[:200]}
        if "__BEGIN__" not in out or "__END__" not in out or "__PMRC=" not in out or "__LSRC=" not in out:
            return {"state": "error", "err": ((err or out).strip().splitlines() or ["?"])[-1][:200]}
        body = out.split("__BEGIN__", 1)[1].split("__END__", 1)[0]
        path_part, rest = body.split("__PMRC=", 1)
        pmrc_s, rest = (rest.split("\n", 1) + [""])[:2]
        list_part, rest = rest.split("__LSRC=", 1)
        lsrc_s, ver_part = (rest.split("\n", 1) + [""])[:2]
        try:
            pmrc, lsrc = int(pmrc_s.strip()), int(lsrc_s.strip())
        except ValueError:
            return {"state": "error", "err": "pm 退出码无法解析"}
        path_lines = [l.strip() for l in path_part.splitlines() if l.strip()]
        list_lines = [l.strip() for l in list_part.splitlines() if l.strip()]
        noise = [l for l in path_lines + list_lines if not l.startswith("package:")]
        if noise:
            return {"state": "error", "err": noise[0][:200]}
        if pmrc == 0 and path_lines:
            vn = re.search(r"versionName=(\S+)", ver_part)
            vc = re.search(r"versionCode=(\d+)", ver_part)
            return {"state": "present", "vn": vn.group(1) if vn else None,
                    "vc": int(vc.group(1)) if vc else None}
        if pmrc in (0, 1) and not path_lines and lsrc == 0 and "package:" + package not in list_lines:
            return {"state": "absent"}
        return {"state": "error", "err": "pm path rc=%s, pm list rc=%s" % (pmrc, lsrc)}

    # -- 包枚举 ---------------------------------------------------------
    def list_packages(self, serial, scope="third"):
        """返回 [{"package":..., "paths":[...]}]，scope: third/system/all。"""
        flag = {"third": "-3", "system": "-s", "all": ""}.get(scope, "-3")
        args = ["shell", "pm", "list", "packages", "-f"]
        if flag:
            args.append(flag)
        code, out, err = self.run(args, serial=serial, timeout=180)
        apps = {}
        for line in out.splitlines():
            line = line.strip()
            if not line.startswith("package:"):
                continue
            body = line[len("package:"):]
            idx = body.rfind("=")
            if idx < 0:
                continue
            path, pkg = body[:idx], body[idx + 1:]
            apps.setdefault(pkg, {"package": pkg, "paths": []})
            apps[pkg]["paths"].append(path)
        # 补齐 split apk 路径
        return list(apps.values())

    def installed_map(self, serial, packages=None, chunk=20):
        """返回设备上这些包的 {pkg: {versionName, versionCode}}；未安装的不出现。"""
        present = set()
        code, out, err = self.run(["shell", "pm", "list", "packages"],
                                  serial=serial, timeout=60)
        if code != 0 or not any(l.strip().startswith("package:") for l in out.splitlines()):
            # 设备离线 / 未授权 / 已拔线 / pm 服务报错：必须报错，不能当成「什么都没装」
            # （任何一台正常的设备都至少有系统包，一行 package: 都没有就是查询失败）
            raise AdbError(((err or out or "pm list 失败").strip().splitlines() or ["pm list 失败"])[-1][:160])
        if True:
            for line in out.splitlines():
                line = line.strip()
                if not line.startswith("package:"):
                    continue
                body = line[len("package:"):].strip()
                # 带 -f 时形如 /data/app/xx/base.apk=com.foo
                present.add(body[body.rfind("=") + 1:] if "=" in body else body)
        wanted = [p for p in (packages or present) if p in present]
        result = {p: {"versionName": None, "versionCode": None} for p in wanted}
        for i in range(0, len(wanted), chunk):
            group = wanted[i:i + chunk]
            cmd = "; ".join(
                "echo @@%s; dumpsys package %s | grep -m2 -E 'versionCode=|versionName='" % (p, p)
                for p in group)
            try:
                code, out, _ = self.run(["shell", cmd], serial=serial, timeout=180)
            except Exception:
                continue
            cur = None
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("@@"):
                    cur = line[2:].strip()
                    continue
                if not cur or cur not in result:
                    continue
                m = re.search(r"versionCode=(\d+)", line)
                if m:
                    result[cur]["versionCode"] = int(m.group(1))
                m = re.search(r"versionName=(\S+)", line)
                if m:
                    result[cur]["versionName"] = m.group(1)
        return result

    def package_paths(self, serial, package):
        code, out, _ = self.run(["shell", "pm", "path", package], serial=serial, timeout=60)
        return [l.strip()[len("package:"):] for l in out.splitlines()
                if l.strip().startswith("package:")]

    # -- 远端文件局部读取 ------------------------------------------------
    def remote_size(self, serial, path):
        for cmd in ("stat -c %%s '%s'" % path, "wc -c < '%s'" % path):
            try:
                code, out, _ = self.run(["shell", cmd], serial=serial, timeout=60)
                m = re.search(r"\d+", out)
                if m:
                    return int(m.group(0))
            except Exception:
                continue
        return None

    def remote_range(self, serial, path, offset, length):
        """读取远端文件 [offset, offset+length) 的原始字节。"""
        if length <= 0:
            return b""
        # 1) tail + head（toybox/busybox 通用，速度最快）
        cmd = "tail -c +%d '%s' | head -c %d" % (offset + 1, path, length)
        try:
            code, out, err = self.run(["exec-out", cmd], serial=serial,
                                      timeout=600, binary=True)
            if out and len(out) >= min(length, 1):
                return out[:length]
        except Exception:
            pass
        # 2) dd 回退（按块读后裁剪）
        bs = 4096
        skip = offset // bs
        pad = offset - skip * bs
        count = (pad + length + bs - 1) // bs
        cmd = "dd if='%s' bs=%d skip=%d count=%d 2>/dev/null" % (path, bs, skip, count)
        try:
            code, out, err = self.run(["exec-out", cmd], serial=serial,
                                      timeout=900, binary=True)
            if out:
                return out[pad:pad + length]
        except Exception:
            pass
        return b""

    def pull(self, serial, remote, local, on_line=None):
        ensure_dir(os.path.dirname(local))
        return self.stream(["pull", remote, local], serial=serial,
                           on_line=on_line, timeout=3600)


# --------------------------------------------------------------------------
# 远端 APK 元信息（只传输 manifest 与资源表，不整包拉取）
# --------------------------------------------------------------------------
class RemoteApkReader(object):
    def __init__(self, adb, serial):
        self.adb = adb
        self.serial = serial

    def _central_directory(self, path, size):
        tail_len = min(size, 128 * 1024)
        tail = self.adb.remote_range(self.serial, path, size - tail_len, tail_len)
        if not tail:
            raise AdbError("无法读取文件尾部")
        idx = AI.find_eocd(tail)
        if idx is None:
            tail_len = min(size, 1024 * 1024)
            tail = self.adb.remote_range(self.serial, path, size - tail_len, tail_len)
            idx = AI.find_eocd(tail)
            if idx is None:
                raise AdbError("找不到 zip 结尾记录")
        import struct
        cd_size = struct.unpack_from("<I", tail, idx + 12)[0]
        cd_off = struct.unpack_from("<I", tail, idx + 16)[0]
        if cd_off == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
            loc = tail.rfind(AI.EOCD64_LOC_SIG, 0, idx)
            if loc >= 0:
                eocd64_off = struct.unpack_from("<Q", tail, loc + 8)[0]
                head = self.adb.remote_range(self.serial, path, eocd64_off, 56)
                cd_size = struct.unpack_from("<Q", head, 40)[0]
                cd_off = struct.unpack_from("<Q", head, 48)[0]
        tail_start = size - tail_len
        if cd_off >= tail_start and cd_off + cd_size <= size:
            cd = tail[cd_off - tail_start: cd_off - tail_start + cd_size]
        else:
            cd = self.adb.remote_range(self.serial, path, cd_off, cd_size)
        return cd

    def entries(self, path, size=None, wanted=None):
        size = size or self.adb.remote_size(self.serial, path)
        if not size:
            raise AdbError("无法获取文件大小")
        cd = self._central_directory(path, size)
        return AI.parse_central_directory(cd, wanted), size

    def read_entry(self, path, ent):
        """按中央目录条目取出并解压单个 zip 条目。"""
        head_room = 30 + 512
        blob = self.adb.remote_range(self.serial, path, ent["offset"],
                                     head_room + ent["csize"])
        if len(blob) < 30:
            return None
        data_off = AI.local_header_data_offset(blob, 0)
        if data_off is None:
            return None
        raw = blob[data_off:data_off + ent["csize"]]
        if len(raw) < ent["csize"]:
            extra = self.adb.remote_range(self.serial, path,
                                          ent["offset"] + data_off + len(raw),
                                          ent["csize"] - len(raw))
            raw += extra
        try:
            return AI.inflate(raw, ent["method"])
        except Exception:
            return None

    def info(self, path, want_icon=False, max_arsc=40 * 1024 * 1024):
        """读取远端 APK 的信息。返回 (ApkInfo, icon_bytes)。"""
        wanted = {"AndroidManifest.xml", "resources.arsc"}
        ents, size = self.entries(path, wanted=None)
        man = ents.get("AndroidManifest.xml")
        if not man:
            raise AdbError("APK 内没有 AndroidManifest.xml")
        man_bytes = self.read_entry(path, man)
        if not man_bytes:
            raise AdbError("读取 manifest 失败")
        arsc_bytes = None
        arsc_ent = ents.get("resources.arsc")
        if arsc_ent and arsc_ent["size"] <= max_arsc:
            arsc_bytes = self.read_entry(path, arsc_ent)
        info, arsc = AI.parse_manifest(man_bytes, arsc_bytes)
        icon = None
        if want_icon and info.icon_path:
            icon = self._icon(path, ents, info.icon_path, arsc)
        return info, icon

    def _icon(self, path, ents, icon_path, arsc, depth=0):
        ent = ents.get(icon_path)
        if ent is None:
            return None
        data = self.read_entry(path, ent)
        if not data:
            return None
        if icon_path.lower().endswith(".xml") and depth < 2 and arsc is not None:
            from .binxml import AXML, ResRef
            try:
                sub = AXML(data)
            except Exception:
                return None
            refs = []
            stack = [sub.root] if sub.root else []
            while stack:
                node = stack.pop()
                if node is None:
                    continue
                for (ns, nm), v in node.attrs.items():
                    if isinstance(v, ResRef) and nm in ("drawable", "src", "foreground"):
                        refs.append((nm, v.id))
                stack.extend(node.children)
            refs.sort(key=lambda x: 0 if x[0] == "foreground" else 1)
            for _, rid in refs:
                for cand in arsc.file_candidates(rid):
                    if cand == icon_path:
                        continue
                    got = self._icon(path, ents, cand, arsc, depth + 1)
                    if got:
                        return got
            return None
        return data
