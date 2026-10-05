# -*- coding: utf-8 -*-
"""adb 封装: 定位/下载 adb、设备列表、安装、已装应用枚举与 APK 提取。"""
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

HOME = os.path.expanduser("~")
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 程序根目录


def _default_output_dir(app_dir):
    """提取文件的默认输出位置。
    打包成 .app 时不能往 bundle 内部写，改用 .app 旁边的目录；
    若 .app 装在 /Applications 这类位置，则用桌面。"""
    marker = ".app/Contents/Resources"
    norm = app_dir.replace(os.sep, "/")
    if norm.endswith(marker):
        bundle = app_dir[:-len(marker) + len(".app")]
        beside = os.path.dirname(bundle)
        desktop = os.path.join(HOME, "Desktop")
        if beside.startswith("/Applications") or not os.access(beside, os.W_OK):
            return desktop if os.path.isdir(desktop) else HOME
        return beside
    return app_dir


BASE_DIR = _default_output_dir(APP_DIR)                                # 提取输出的默认位置
SUPPORT_DIR = os.path.join(HOME, "Library", "Application Support", "APK安装管家") \
    if sys.platform == "darwin" else os.path.join(HOME, ".apk-installer")

PLATFORM_TOOLS_URL = {
    "darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
    "win32": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
}

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p


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


class Adb(object):
    def __init__(self, path=None):
        self.path = path or find_adb()
        self._lock = threading.Lock()

    @property
    def available(self):
        return bool(self.path and os.path.isfile(self.path))

    def _base(self, serial=None):
        if not self.available:
            raise AdbError("未找到 adb，可在界面上点「自动下载 adb」一键安装")
        cmd = [self.path]
        if serial:
            cmd += ["-s", serial]
        return cmd

    def run(self, args, serial=None, timeout=120, binary=False):
        cmd = self._base(serial) + args
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        if binary:
            return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace")
        return (p.returncode,
                p.stdout.decode("utf-8", "replace"),
                p.stderr.decode("utf-8", "replace"))

    def stream(self, args, serial=None, on_line=None, timeout=1800):
        """流式执行，逐行回调。返回 (returncode, 全部输出)。"""
        cmd = self._base(serial) + args
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                bufsize=1, universal_newlines=True, errors="replace")
        lines = []
        start = time.time()
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            if on_line and line.strip():
                on_line(line)
            if time.time() - start > timeout:
                proc.kill()
                break
        proc.wait()
        return proc.returncode, "\n".join(lines)

    def start_server(self):
        try:
            self.run(["start-server"], timeout=30)
        except Exception:
            pass

    # -- 设备 -----------------------------------------------------------
    def devices(self):
        try:
            code, out, err = self.run(["devices", "-l"], timeout=20)
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
            p = subprocess.run(self._base() + ["pair", host_port, code],
                               capture_output=True, timeout=60)
            out = (p.stdout + p.stderr).decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            return False, "配对超时：检查手机与电脑是否在同一个 Wi-Fi"
        except Exception as exc:
            return False, str(exc)
        if "Successfully paired" in out or "paired to" in out.lower():
            return True, out.strip()
        return False, out.strip() or "配对失败"

    def connect(self, host_port):
        if ":" not in host_port:
            host_port += ":5555"
        try:
            code, out, err = self.run(["connect", host_port], timeout=30)
        except Exception as exc:
            return False, str(exc), host_port
        text = (out or "") + (err or "")
        ok = "connected to" in text.lower() and "cannot" not in text.lower() \
            and "failed" not in text.lower()
        return ok, text.strip(), host_port

    def disconnect(self, host_port=None):
        args = ["disconnect"] + ([host_port] if host_port else [])
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
        time.sleep(1.2)
        target = "%s:%d" % (ip, port)
        ok, msg, _ = self.connect(target)
        return ok, target, (msg or text)

    def device_detail(self, serial):
        props = {}
        try:
            code, out, _ = self.run(
                ["shell", "getprop ro.product.brand; getprop ro.product.model; "
                 "getprop ro.build.version.release; getprop ro.build.version.sdk; "
                 "getprop ro.product.cpu.abi"],
                serial=serial, timeout=20)
            vals = [v.strip() for v in out.splitlines() if v.strip()]
            keys = ["brand", "model", "android", "sdk", "abi"]
            for k, v in zip(keys, vals):
                props[k] = v
        except Exception:
            pass
        return props

    # -- 安装 -----------------------------------------------------------
    def install(self, serial, apk_paths, on_line=None, flags=None,
                timeout=1800):
        flags = list(flags or [])
        if len(apk_paths) > 1:
            args = ["install-multiple"] + flags + list(apk_paths)
        else:
            args = ["install"] + flags + [apk_paths[0]]
        return self.stream(args, serial=serial, on_line=on_line, timeout=timeout)

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
        try:
            code, out, _ = self.run(["shell", "pm", "list", "packages"],
                                    serial=serial, timeout=120)
            for line in out.splitlines():
                line = line.strip()
                if not line.startswith("package:"):
                    continue
                body = line[len("package:"):].strip()
                # 带 -f 时形如 /data/app/xx/base.apk=com.foo
                present.add(body[body.rfind("=") + 1:] if "=" in body else body)
        except Exception:
            return {}
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
