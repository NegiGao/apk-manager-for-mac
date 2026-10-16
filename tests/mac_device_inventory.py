"""只读盘点：这台 Mac 上能看到哪些安卓设备、怎么连的、型号和序号，以及候选测试包是否已在设备上。

只读，具体做法：
- 不执行任何 adb 可执行文件。adb 客户端发现与服务版本不一致时会结束并重启服务，
  那会替换共享的 adb 服务、影响其他软件，所以这里一律不调用。
- 只有当 127.0.0.1:5037 上已经有 adb 服务在监听时，才用 adb 自带的本地查询协议问它：
  host:version、host:devices-l，以及对已授权设备执行 getprop / pm path / dumpsys package（都只读）。
  没有服务在监听就不查，也不启动。
- USB 硬件信息来自 system_profiler SPUSBDataType（只读）；进程与端口来自 ps / lsof（只读）。
- 不安装、不卸载、不连接 / 断开无线设备、不改设置、不结束任何进程。

用法：python3 mac_device_inventory.py --out <输出目录>
"""
import argparse, json, os, socket, subprocess, sys, time

TEST_PACKAGES = [  # 候选测试包（来自 tests/apks）
    ("Termux", "com.termux", "0.118.0", 118),
    ("NewPipe", "org.schabi.newpipe", "0.27.6", 1003),
    ("Seal", "com.junkfood.seal", "1.13.1", 11310),
]
ANDROID_VENDORS = {  # 常见安卓厂商 USB vendor id（用于从 USB 列表里挑出疑似安卓设备）
    0x18d1: "Google", 0x04e8: "Samsung", 0x2717: "Xiaomi", 0x22b8: "Motorola", 0x12d1: "Huawei",
    0x2a70: "OnePlus", 0x22d9: "OPPO", 0x2d95: "vivo", 0x0bb4: "HTC", 0x1004: "LG", 0x0fce: "Sony",
    0x2ae5: "Fairphone", 0x05c6: "Qualcomm", 0x0e8d: "MediaTek", 0x1949: "Amazon", 0x3318: "XREAL",
}
OUT = []


def say(s=""):
    OUT.append(s)
    print(s, flush=True)


def run(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception as exc:
        return "(%s)" % exc


class AdbProto(object):
    """adb 本地协议的只读查询（与 adb 服务直接对话，不经过 adb 客户端程序）。"""

    def __init__(self, port=5037):
        self.port = port

    def _conn(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.settimeout(10)
        return s

    @staticmethod
    def _send(s, msg):
        b = msg.encode("utf-8")
        s.sendall(b"%04x" % len(b) + b)

    @staticmethod
    def _recvn(s, n):
        buf = b""
        while len(buf) < n:
            c = s.recv(n - len(buf))
            if not c:
                raise IOError("连接被关闭")
            buf += c
        return buf

    def _status(self, s):
        st = self._recvn(s, 4)
        if st == b"OKAY":
            return
        if st == b"FAIL":
            n = int(self._recvn(s, 4), 16)
            raise IOError(self._recvn(s, n).decode("utf-8", "replace"))
        raise IOError("意外的响应 %r" % st)

    def host(self, cmd):
        s = self._conn()
        try:
            self._send(s, cmd)
            self._status(s)
            n = int(self._recvn(s, 4), 16)
            return self._recvn(s, n).decode("utf-8", "replace")
        finally:
            s.close()

    def shell(self, serial, cmd):
        s = self._conn()
        try:
            self._send(s, "host:transport:" + serial)
            self._status(s)
            self._send(s, "shell:" + cmd)
            self._status(s)
            out = b""
            while True:
                c = s.recv(65536)
                if not c:
                    break
                out += c
            return out.decode("utf-8", "replace")
        finally:
            s.close()


def usb_devices():
    raw = run(["/usr/sbin/system_profiler", "SPUSBDataType", "-json"], timeout=60)
    try:
        data = json.loads(raw)
    except Exception:
        return []
    found = []

    def walk(items):
        for it in items or []:
            vid = it.get("vendor_id", "")
            try:
                v = int(vid.split()[0], 16)
            except Exception:
                v = None
            if v is not None and v != 0x05ac:          # 跳过 Apple 自己的设备
                found.append({"name": it.get("_name"), "vendor": it.get("manufacturer") or ANDROID_VENDORS.get(v, vid),
                              "vendor_id": vid, "product_id": it.get("product_id"),
                              "serial": it.get("serial_num"), "location": it.get("location_id"),
                              "android_vendor": v in ANDROID_VENDORS})
            walk(it.get("_items"))
    for bus in data.get("SPUSBDataType", []):
        walk(bus.get("_items"))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=5037)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    result = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "server": None, "devices": [], "usb": []}
    say("APK Manager 测试设备只读盘点 %s" % result["time"])
    say("（不执行 adb 程序；只在已有 adb 服务监听时用本地协议做只读查询；不安装、不卸载、不连接/断开、不结束进程）")

    say("\n== 1. 端口 %d 与 adb 相关进程（只读）" % a.port)
    lsof = run(["/usr/sbin/lsof", "-nP", "-iTCP:%d" % a.port, "-sTCP:LISTEN"])
    say(lsof.strip() if "LISTEN" in lsof else "  没有进程在监听 %d" % a.port)
    procs = [l for l in run(["ps", "-ww", "-Ao", "pid=,ppid=,args="]).splitlines()
             if ("adb" in l.lower() or "macdroid" in l.lower()) and "mac_device_inventory" not in l]
    for l in procs:
        say("  " + l.strip()[:200])
    result["processes"] = procs
    result["listener"] = lsof.strip()

    say("\n== 2. USB 上的非 Apple 设备（system_profiler，只读）")
    usb = usb_devices()
    result["usb"] = usb
    for u in usb:
        say("  %s | %s (%s %s) | 序号 %s | %s" % (u["name"], u["vendor"], u["vendor_id"], u["product_id"],
                                              u["serial"], "疑似安卓厂商" if u["android_vendor"] else "其他"))
    if not usb:
        say("  （没有）")

    say("\n== 3. adb 服务里的设备（仅当服务已在运行）")
    if "LISTEN" not in lsof:
        say("  %d 端口没有 adb 服务在监听：按规则不启动服务，跳过这一节。" % a.port)
    else:
        p = AdbProto(a.port)
        try:
            ver = p.host("host:version")
            result["server"] = {"version_hex": ver, "version": int(ver, 16)}
            say("  服务协议版本：%d（host:version=%s）" % (int(ver, 16), ver))
            lines = [l for l in p.host("host:devices-l").splitlines() if l.strip()]
        except Exception as exc:
            say("  查询失败（未做任何改动）：%s" % exc)
            lines = []
        for line in lines:
            parts = line.split()
            serial, state = parts[0], parts[1] if len(parts) > 1 else "?"
            extra = dict(x.split(":", 1) for x in parts[2:] if ":" in x)
            conn = "Wi-Fi" if (":" in serial and serial.rsplit(":", 1)[-1].isdigit()) or "._adb-tls" in serial \
                else ("USB" if "usb" in extra else "未知")
            d = {"serial": serial, "state": state, "connection": conn, "extra": extra, "packages": []}
            if state == "device":
                try:
                    props = p.shell(serial, "for k in ro.product.manufacturer ro.product.model ro.product.brand "
                                            "ro.build.version.release ro.build.version.sdk ro.serialno; "
                                            "do echo \"$k=$(getprop $k)\"; done")
                    d["props"] = dict(l.split("=", 1) for l in props.splitlines() if "=" in l)
                except Exception as exc:
                    d["props_error"] = str(exc)
                for label, pkg, vn, vc in TEST_PACKAGES:
                    try:
                        o = p.shell(serial, "pm path %s 2>&1; echo __RC=$?; "
                                            "dumpsys package %s | grep -m2 -E 'versionName=|versionCode='" % (pkg, pkg))
                        installed = "package:" in o
                        cur = [x.strip() for x in o.splitlines() if "version" in x]
                        rc = o.split("__RC=")[-1].split()[0] if "__RC=" in o else "?"
                        state_pkg = "已安装" if installed else ("未安装" if rc == "1" else "无法确认（rc=%s）" % rc)
                        d["packages"].append({"label": label, "package": pkg, "state": state_pkg, "device": cur,
                                              "test_apk": "%s (%d)" % (vn, vc)})
                    except Exception as exc:
                        d["packages"].append({"label": label, "package": pkg, "state": "查询失败：%s" % exc})
            result["devices"].append(d)
            pr = d.get("props", {})
            say("  • %s | 状态 %s | 连接 %s | %s %s（%s）| Android %s / SDK %s | ro.serialno=%s" % (
                serial, state, conn, pr.get("ro.product.manufacturer", "?"), pr.get("ro.product.model", extra.get("model", "?")),
                pr.get("ro.product.brand", "?"), pr.get("ro.build.version.release", "?"),
                pr.get("ro.build.version.sdk", "?"), pr.get("ro.serialno", "?")))
            for pk in d["packages"]:
                say("      候选测试包 %-8s %-22s 设备上：%s %s｜测试包版本 %s" % (
                    pk["label"], pk["package"], pk["state"], " ".join(pk.get("device") or []), pk.get("test_apk", "")))
        if not lines:
            say("  服务里没有设备。")

    with open(os.path.join(a.out, "inventory.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "inventory.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(OUT) + "\n")
    say("\n已保存：%s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
