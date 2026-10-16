# -*- coding: utf-8 -*-
"""业务引擎: 安装队列、顺序方案、按序安装、设备应用枚举与提取。"""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from . import apkinfo as AI
from .adbkit import Adb, AdbError, RemoteApkReader
from .paths import (SUPPORT_DIR, BASE_DIR, ensure_dir, STAGING_DIR, ICON_DIR,
                    PROFILE_FILE, QUEUE_FILE, SETTINGS_FILE, LABEL_CACHE_FILE)

DEFAULT_SETTINGS = {
    "allowDowngrade": True,       # -d
    "grantPermissions": False,    # -g
    "reinstall": True,            # -r
    "skipSameVersion": False,     # 已安装同版本则跳过
    "stopOnError": False,         # 失败即停止
    "keepDataOnUninstall": False,  # 卸载时保留数据与缓存（-k）
    "autoMark": True,              # 连接设备时自动标记哪些已安装
    "notify": True,               # macOS 通知中心提醒
    "sound": True,                # 完成提示音
    "extractDir": BASE_DIR,       # 提取输出目录（将在其下建「提取APP」）
    "locale": "zh-CN",
    "lang": "",                   # 界面语言 zh / ja / en，空=跟随系统
    "wirelessHistory": [],        # 用过的无线地址
    "autoReconnect": True,        # 启动后自动重连上次的无线设备
}

# 常见安装失败原因 → 结果代码（界面按所选语言显示对应说明与建议）
FAIL_HINTS = [
    ("INSTALL_FAILED_ALREADY_EXISTS", "already_exists"),
    ("INSTALL_FAILED_VERSION_DOWNGRADE", "downgrade"),
    ("INSTALL_FAILED_UPDATE_INCOMPATIBLE", "sig_mismatch"),
    ("INSTALL_FAILED_DUPLICATE_PACKAGE", "sig_mismatch"),
    ("INSTALL_FAILED_INSUFFICIENT_STORAGE", "no_space"),
    ("INSTALL_FAILED_NO_MATCHING_ABIS", "abi_mismatch"),
    ("INSTALL_PARSE_FAILED_NO_CERTIFICATES", "no_cert"),
    ("INSTALL_PARSE_FAILED_MANIFEST_MALFORMED", "broken_apk"),
    ("INSTALL_FAILED_OLDER_SDK", "old_sdk"),
    ("INSTALL_FAILED_USER_RESTRICTED", "user_restricted"),
    ("INSTALL_FAILED_VERIFICATION_FAILURE", "verification"),
    ("INSTALL_FAILED_TEST_ONLY", "test_only"),
    ("INSTALL_FAILED_MISSING_SHARED_LIBRARY", "missing_lib"),
    ("INSTALL_FAILED_INVALID_APK", "invalid_apk"),
    ("device unauthorized", "unauthorized"),
    ("no devices/emulators found", "no_device"),
    ("device offline", "offline"),
]


def explain_failure(text):
    """返回 (code, 额外信息)。文案在界面侧按语言渲染。"""
    t = text or ""
    for key, code in FAIL_HINTS:
        if key.lower() in t.lower():
            return code, ""
    m = re.search(r"INSTALL_[A-Z_]+", t)
    if m:
        return "rejected", m.group(0)
    return "failed", ""


def human_size(n):
    if n is None:
        return ""
    units = ["B", "KB", "MB", "GB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == "GB":
            return ("%.0f %s" if u == "B" else "%.1f %s") % (f, u)
        f /= 1024


# 通知中心用的少量文案（界面文案全部在前端 i18n 里）
NOTIFY_TEXT = {
    "zh": {"ok": "安装成功", "fail": "安装失败", "done": "全部安装完成",
           "installed": "%s 已装到设备上", "uninstall_done": "卸载完成",
           "extract_done": "提取完成", "extract_msg": "%d 个应用已保存到「提取APP」文件夹",
           "summary": "成功 %d · 失败 %d", "paused": "安装队列已暂停：目标设备断开或不一致"},
    "ja": {"ok": "インストール完了", "fail": "インストール失敗", "done": "すべて完了",
           "installed": "%s を端末にインストールしました", "uninstall_done": "アンインストール完了",
           "extract_done": "抽出完了", "extract_msg": "%d 件のアプリを「提取APP」フォルダに保存しました",
           "summary": "成功 %d · 失敗 %d", "paused": "インストールを一時停止：対象端末が切断／不一致"},
    "en": {"ok": "Installed", "fail": "Install failed", "done": "All done",
           "installed": "%s is now on the device", "uninstall_done": "Uninstalled",
           "extract_done": "Extraction done", "extract_msg": "%d app(s) saved to the 提取APP folder",
           "summary": "%d succeeded · %d failed",
           "paused": "Install queue paused: target device lost or changed"},
}


def notify_text(lang, key):
    table = NOTIFY_TEXT.get((lang or "zh")[:2], NOTIFY_TEXT["zh"])
    return table.get(key, NOTIFY_TEXT["zh"].get(key, key))


def notify_mac(title, message, sound=False):
    if sys.platform != "darwin":
        return
    try:
        script = 'display notification %s with title %s' % (
            json.dumps(message), json.dumps(title))
        if sound:
            script += ' sound name "Glass"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except Exception:
        pass


class EventBus(object):
    """给所有 SSE 订阅者广播事件。"""

    def __init__(self):
        self.subs = []
        self.lock = threading.Lock()
        self.history = []
        self.last_seen = 0.0     # 最后一次有界面连着的时间
        self.ever_connected = False

    def subscribe(self):
        q = queue.Queue(maxsize=2000)
        with self.lock:
            self.subs.append(q)
            self.ever_connected = True
            self.last_seen = time.time()
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)
            self.last_seen = time.time()

    def viewers(self):
        with self.lock:
            return len(self.subs)

    def emit(self, kind, **data):
        evt = dict(data)
        evt["type"] = kind
        evt["ts"] = time.time()
        with self.lock:
            self.history.append(evt)
            if len(self.history) > 500:
                self.history = self.history[-500:]
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(evt)
            except queue.Full:
                pass


class Engine(object):
    def __init__(self):
        for d in (SUPPORT_DIR, STAGING_DIR, ICON_DIR):
            ensure_dir(d)
        self.adb = Adb()
        self.bus = EventBus()
        self.lock = threading.RLock()
        self.items = []            # 安装队列（顺序即安装顺序）
        self.settings = dict(DEFAULT_SETTINGS)
        self.job = None            # 当前安装任务状态
        self.cancel_flag = threading.Event()
        self.apps_scan = None      # 设备应用枚举状态
        self.scan_cancel = threading.Event()
        self.label_cache = {}
        self.cur_proc = None       # 当前 adb install 进程（取消当前安装用）
        self._load_all()
        # 所有自动碰设备的动作都交给 Supervisor（单线程、可暂停）
        from .supervisor import Supervisor
        self.sup = Supervisor(self)
        self.sup.start()

    # -- 持久化 ---------------------------------------------------------
    def _load_all(self):
        self.settings.update(self._read_json(SETTINGS_FILE, {}))
        for k, v in DEFAULT_SETTINGS.items():
            self.settings.setdefault(k, v)
        self.items = [i for i in self._read_json(QUEUE_FILE, [])
                      if self._item_alive(i)]
        self.label_cache = self._read_json(LABEL_CACHE_FILE, {})

    @staticmethod
    def _item_alive(item):
        parts = item.get("parts") or [item.get("path")]
        return all(p and os.path.exists(p) for p in parts)

    @staticmethod
    def _read_json(path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    @staticmethod
    def _write_json(path, data):
        ensure_dir(os.path.dirname(path))
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def save_queue(self):
        self._write_json(QUEUE_FILE, self.items)

    def save_settings(self):
        self._write_json(SETTINGS_FILE, self.settings)

    def save_label_cache(self):
        self._write_json(LABEL_CACHE_FILE, self.label_cache)

    # -- 队列 -----------------------------------------------------------
    def add_file(self, path, source="staged", original_name=None):
        """把一个 apk / 捆绑包加入队列。"""
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(path):
            return {"ok": False, "error": "文件不存在: %s" % path}
        if os.path.isdir(path):
            return self.add_folder(path)
        if not path.lower().endswith(AI.ALL_EXTS):
            return {"ok": False, "error": "不是 APK 文件: %s" % os.path.basename(path)}

        iid = uuid.uuid4().hex[:12]
        workdir = os.path.join(STAGING_DIR, iid + "_parts")
        info, icon, parts = AI.read_any(path, want_icon=True, workdir=workdir)
        icon_url = None
        if icon:
            ipath = os.path.join(ICON_DIR, iid + ".img")
            try:
                with open(ipath, "wb") as f:
                    f.write(icon)
                icon_url = "/api/icon/" + iid
            except Exception:
                pass
        size = 0
        for p in parts or [path]:
            try:
                size += os.path.getsize(p)
            except Exception:
                pass
        item = {
            "id": iid,
            "file": original_name or os.path.basename(path),
            "path": path,
            "parts": parts or [path],
            "source": source,
            "package": info.package,
            "label": info.label or (original_name or os.path.basename(path)),
            "versionName": info.version_name,
            "versionCode": info.version_code,
            "minSdk": info.min_sdk,
            "size": size,
            "sizeText": human_size(size),
            "icon": icon_url,
            "addedAt": time.time(),
            "status": "pending",
            "message": "",
            "error": info.error,
            "splitCount": len(parts) if parts and len(parts) > 1 else 0,
        }
        with self.lock:
            # 同包名重复时提示但仍允许加入
            dup = any(x["package"] and x["package"] == item["package"] for x in self.items)
            item["duplicate"] = dup
            self.items.append(item)
            self.save_queue()
        self.bus.emit("queue", action="add", item=item)
        return {"ok": True, "item": item}

    def add_folder(self, folder, recursive=True):
        folder = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(folder):
            return {"ok": False, "error": "不是文件夹: %s" % folder}
        found = []
        if recursive:
            for root, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fn in files:
                    if fn.lower().endswith(AI.ALL_EXTS) and not fn.startswith("."):
                        found.append(os.path.join(root, fn))
        else:
            for fn in sorted(os.listdir(folder)):
                if fn.lower().endswith(AI.ALL_EXTS):
                    found.append(os.path.join(folder, fn))
        found.sort(key=lambda p: os.path.basename(p).lower())
        added, errors = [], []
        for p in found:
            r = self.add_file(p, source="link")
            if r.get("ok"):
                added.append(r["item"])
            else:
                errors.append(r.get("error"))
        return {"ok": True, "added": len(added), "errors": errors,
                "items": added}

    def remove(self, ids):
        ids = set(ids or [])
        with self.lock:
            keep, gone = [], []
            for it in self.items:
                (gone if it["id"] in ids else keep).append(it)
            self.items = keep
            self.save_queue()
        for it in gone:
            self._cleanup_item(it)
        self.bus.emit("queue", action="remove", ids=list(ids))
        return {"ok": True, "removed": len(gone)}

    def clear(self):
        with self.lock:
            gone, self.items = self.items, []
            self.save_queue()
        for it in gone:
            self._cleanup_item(it)
        self.bus.emit("queue", action="clear")
        return {"ok": True}

    def _cleanup_item(self, item):
        if item.get("source") != "staged":
            return
        try:
            if item.get("path", "").startswith(STAGING_DIR) and os.path.exists(item["path"]):
                os.remove(item["path"])
        except Exception:
            pass
        for p in item.get("parts") or []:
            try:
                if p.startswith(STAGING_DIR) and os.path.exists(p) and p != item.get("path"):
                    os.remove(p)
            except Exception:
                pass
        try:
            ipath = os.path.join(ICON_DIR, item["id"] + ".img")
            if os.path.exists(ipath):
                os.remove(ipath)
        except Exception:
            pass

    def reorder(self, ids):
        with self.lock:
            index = {it["id"]: it for it in self.items}
            new = [index[i] for i in ids if i in index]
            for it in self.items:
                if it["id"] not in set(ids):
                    new.append(it)
            self.items = new
            self.save_queue()
        self.bus.emit("queue", action="reorder")
        return {"ok": True}

    def sort_by(self, key, desc=False):
        keyfn = {
            "label": lambda i: (i.get("label") or "").lower(),
            "file": lambda i: (i.get("file") or "").lower(),
            "package": lambda i: (i.get("package") or "").lower(),
            "size": lambda i: i.get("size") or 0,
            "added": lambda i: i.get("addedAt") or 0,
            "version": lambda i: (i.get("versionCode") or 0),
        }.get(key)
        if not keyfn:
            return {"ok": False, "error": "未知排序方式"}
        with self.lock:
            self.items.sort(key=keyfn, reverse=desc)
            self.save_queue()
        self.bus.emit("queue", action="sort", key=key, desc=desc)
        return {"ok": True}

    def reset_status(self):
        with self.lock:
            for it in self.items:
                it["status"] = "pending"
                it["message"] = ""
            self.save_queue()
        self.bus.emit("queue", action="reset")
        return {"ok": True}

    # -- 顺序方案 -------------------------------------------------------
    def profiles(self):
        return self._read_json(PROFILE_FILE, {})

    def save_profile(self, name):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "请填写方案名称"}
        data = self.profiles()
        with self.lock:
            data[name] = {
                "savedAt": time.time(),
                "items": [{
                    "package": it.get("package"),
                    "label": it.get("label"),
                    "file": it.get("file"),
                    "path": it.get("path"),
                    "parts": it.get("parts"),
                    "source": it.get("source"),
                    "versionName": it.get("versionName"),
                    "size": it.get("size"),
                } for it in self.items],
            }
        self._write_json(PROFILE_FILE, data)
        return {"ok": True, "name": name, "count": len(data[name]["items"])}

    def load_profile(self, name, replace=True):
        data = self.profiles()
        prof = data.get(name)
        if not prof:
            return {"ok": False, "error": "方案不存在"}
        if replace:
            self.clear()
        missing, loaded = [], 0
        for rec in prof["items"]:
            parts = rec.get("parts") or ([rec.get("path")] if rec.get("path") else [])
            if parts and all(p and os.path.exists(p) for p in parts):
                r = self.add_file(rec["path"], source=rec.get("source", "link"))
                if r.get("ok"):
                    loaded += 1
                    continue
            missing.append(rec.get("label") or rec.get("file") or rec.get("package"))
        return {"ok": True, "loaded": loaded, "missing": missing}

    def delete_profile(self, name):
        data = self.profiles()
        if name in data:
            del data[name]
            self._write_json(PROFILE_FILE, data)
        return {"ok": True}

    # -- 设备 -----------------------------------------------------------
    def devices(self):
        """返回最近一次检测到的设备（缓存），不触发任何 adb 命令。"""
        st = self.sup.state()
        return {"ok": True, "devices": st["devices"], "devicesAt": st["devicesAt"],
                "stale": st["stale"], "bgPaused": st["bgPaused"]}

    # -- 互斥：安装 / 扫描进行中时，同一台设备上的冲突操作先挡住 ------------
    def _same_device(self, a, b):
        if not a or not b:
            return False
        if a == b:
            return True
        pa, pb = self.sup.physical_of(a), self.sup.physical_of(b)
        return bool(pa) and pa == pb

    def busy_reason(self, serial):
        job = self.job or {}
        if job.get("running") and self._same_device(job.get("serial"), serial):
            return "busy_install"
        scan = self.apps_scan or {}
        if scan.get("running") and self._same_device(scan.get("serial"), serial):
            return "busy_scan"
        return None

    # -- 无线 -----------------------------------------------------------
    def wireless_pair(self, host_port, code):
        with self.adb.source("ui"):
            ok, msg = self.adb.pair((host_port or "").strip(), code)
            if not ok:
                return {"ok": False, "error": msg}
            # 配对端口和连接端口不是同一个，配对成功后还要再连一次
            host = (host_port or "").rsplit(":", 1)[0]
            cok, cmsg, target = self.adb.connect(host)
        if cok:
            self.remember_wireless(target)
        self.sup.check_once()
        return {"ok": True, "paired": True, "connected": cok,
                "target": target, "message": msg, "connectMessage": cmsg}

    def wireless_connect(self, host_port):
        with self.adb.source("ui"):
            ok, msg, target = self.adb.connect((host_port or "").strip())
        if ok:
            self.remember_wireless(target)
        self.sup.check_once()
        return {"ok": ok, "message": msg, "target": target,
                "error": None if ok else msg}

    def wireless_disconnect(self, host_port):
        """只断开明确指定的那一个 IP:端口。"""
        if not host_port:
            return {"ok": False, "code": "need_target"}
        busy = self.busy_reason(host_port)
        if busy:
            return {"ok": False, "code": busy}
        with self.adb.source("ui"):
            ok, msg = self.adb.disconnect(host_port)
        self.sup.check_once()
        return {"ok": ok, "message": msg}

    def wireless_switch(self, serial, port=5555):
        """把当前 USB 设备转成无线连接（只在用户点击时执行，后台从不自动做）。"""
        if not serial:
            return {"ok": False, "code": "need_usb"}
        if self.adb.is_wireless_serial(serial):
            return {"ok": False, "code": "already_wireless"}
        uo = self.sup.usb_only
        if uo and self._same_device(uo.get("serial"), serial):
            return {"ok": False, "code": "usb_only_blocks_tcpip"}
        busy = self.busy_reason(serial)
        if busy:
            return {"ok": False, "code": busy}
        with self.adb.source("ui"):
            ok, target, msg = self.adb.enable_tcpip(serial, port)
        if ok and target:
            self.remember_wireless(target)
            phys = self.sup.physical_of(serial)
            if phys:
                self.sup.wifi_meta[target] = phys
        self.sup.check_once()
        return {"ok": ok, "target": target, "message": msg,
                "error": None if ok else msg}

    def remember_wireless(self, target):
        hist = [h for h in self.settings.get("wirelessHistory", []) if h != target]
        hist.insert(0, target)
        self.settings["wirelessHistory"] = hist[:8]
        self.save_settings()

    def forget_wireless(self, target):
        self.settings["wirelessHistory"] = [
            h for h in self.settings.get("wirelessHistory", []) if h != target]
        self.save_settings()
        return {"ok": True}

    # -- 已安装标记 ------------------------------------------------------
    def compute_marks(self, serial):
        """只读：算出队列里每一项在 serial 这台设备上的安装状态，不写入。
        失败时抛异常 —— 设备离线不能被当成「都没装」。"""
        with self.lock:
            snap = [(it["id"], it.get("package"), it.get("versionCode")) for it in self.items]
        pkgs = [p for _, p, _ in snap if p]
        m = self.adb.installed_map(serial, pkgs) if pkgs else {}
        marks, counts = {}, {"same": 0, "update": 0, "downgrade": 0, "none": 0, "unknown": 0}
        for iid, pkg, mine_vc in snap:
            rec = m.get(pkg) if pkg else None
            if not rec:
                marks[iid] = {"state": "none"}
                counts["none"] += 1
                continue
            dev_vc = rec.get("versionCode")
            if dev_vc is None or mine_vc is None:
                state = "unknown"
            elif dev_vc == mine_vc:
                state = "same"
            elif dev_vc < mine_vc:
                state = "update"
            else:
                state = "downgrade"
            counts[state] += 1
            marks[iid] = {"state": state, "versionName": rec.get("versionName"),
                          "versionCode": dev_vc}
        return marks, counts

    def apply_marks(self, serial, marks, counts):
        with self.lock:
            for it in self.items:
                if it["id"] in marks:
                    it["installed"] = dict(marks[it["id"]], serial=serial)
            self.save_queue()
        total = sum(v for k, v in counts.items() if k != "none")
        self.bus.emit("marked", serial=serial, count=total, counts=counts)
        return total

    def clear_marks(self):
        with self.lock:
            for it in self.items:
                it["installed"] = None
            self.save_queue()
        self.bus.emit("marked", serial=None, count=0)

    def mark_installed(self, serial):
        """手动「标记已安装」。安装进行中的那台设备不打扰。"""
        if not serial:
            self.clear_marks()
            return {"ok": True, "count": 0}
        busy = self.busy_reason(serial)
        if busy:
            return {"ok": False, "code": busy}
        try:
            marks, counts = self.compute_marks(serial)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        total = self.apply_marks(serial, marks, counts)
        return {"ok": True, "count": total, "counts": counts}

    # -- 卸载 -----------------------------------------------------------
    def uninstall(self, serial, packages, keep_data=False, labels=None):
        if not serial:
            return {"ok": False, "code": "need_target"}
        busy = self.busy_reason(serial)
        if busy:
            self.bus.emit("uninstall_done", total=0, ok=0, results=[], blocked=busy)
            return {"ok": False, "code": busy}
        labels = labels or {}
        results = []
        self.bus.emit("uninstall_start", total=len(packages))
        for i, pkg in enumerate(packages, 1):
            name = labels.get(pkg) or pkg
            try:
                code, out, err = self.adb.uninstall(serial, pkg, keep_data)
                text = (out or "") + (err or "")
                ok = "Success" in text
            except Exception as exc:
                ok, text = False, str(exc)
            if not ok:
                if "Unknown package" in text or "not installed" in text.lower():
                    code = "un_not_found"
                elif "DELETE_FAILED_INTERNAL_ERROR" in text:
                    code = "un_system_app"
                elif "DELETE_FAILED_DEVICE_POLICY_MANAGER" in text:
                    code = "un_policy"
                else:
                    code = "un_failed"
            else:
                code = "un_ok_keep" if keep_data else "un_ok"
            detail = (text.strip().splitlines() or [""])[-1][:120] if not ok else ""
            results.append({"package": pkg, "label": name, "ok": ok,
                            "code": code, "arg": detail})
            self.bus.emit("uninstall_item", package=pkg, label=name, ok=ok,
                          code=code, arg=detail, index=i, total=len(packages))
        okc = sum(1 for r in results if r["ok"])
        try:
            self.mark_installed(serial)   # 先更新标记，再通知界面
        except Exception:
            pass
        self.bus.emit("uninstall_done", total=len(packages), ok=okc, results=results)
        if self.settings.get("notify"):
            lang = self.settings.get("lang") or "zh"
            notify_mac(notify_text(lang, "uninstall_done"),
                       notify_text(lang, "summary") % (okc, len(packages) - okc),
                       sound=self.settings.get("sound", True))
        return {"ok": True, "results": results}

    # -- 安装 -----------------------------------------------------------
    # 一次安装任务（job）绑定一台设备：开始时记下它的连接标识和物理序号，
    # 每装下一个之前都核对一遍。拔线 / 换成别的机器 → 队列暂停，绝不自动续装、
    # 也不会悄悄改用同一台手机的 Wi-Fi 入口或其他设备。
    def _job_public(self):
        j = self.job or {}
        return {k: j.get(k) for k in (
            "running", "paused", "pauseReason", "pauseAfterCurrent", "finished",
            "serial", "physical", "name", "total", "done", "ok", "failed", "skipped",
            "unverified", "current", "currentLabel", "remaining", "startedAt")}

    def _target_check(self, serial, physical):
        """返回 None 表示目标设备在线且就是当初那台；否则返回原因代码。"""
        with self.adb.source("install"):
            st = self.adb.get_state(serial)
            if st != "device":
                return "target_lost"
            if physical and physical != serial:
                now = self.adb.physical_serial(serial)
                if now and now != physical:
                    return "target_mismatch"
        return None

    def _remaining_ids(self, job):
        with self.lock:
            idx = {it["id"]: it for it in self.items}
            return [i for i in job["order"]
                    if i in idx and idx[i].get("status") not in ("success", "skipped")]

    def start_install(self, serial, only_ids=None, mode=None):
        """mode: None=自动判断（有已完成记录时先问）；"remaining"=只装没装成的；"all"=全部重装。"""
        with self.lock:
            if self.job and self.job.get("running"):
                return {"ok": False, "code": "busy_install"}
        if not serial:
            return {"ok": False, "code": "need_target"}
        uo = self.sup.usb_only
        if uo and serial != uo["serial"]:
            return {"ok": False, "code": "usb_only_locked", "arg": uo.get("name")}
        problem = None
        with self.adb.source("install"):
            if self.adb.get_state(serial) != "device":
                problem = "target_not_ready"
        if problem:
            return {"ok": False, "code": problem}
        physical = self.sup.physical_of(serial)
        if not physical:
            with self.adb.source("install"):
                physical = self.adb.physical_serial(serial)
        with self.lock:
            pool = [it for it in self.items if not only_ids or it["id"] in set(only_ids)]
            if not pool:
                return {"ok": False, "code": "queue_empty"}
            done_here = [it for it in pool if it.get("status") == "success"
                         and physical and it.get("doneOn") == physical]
            if mode is None and done_here:
                return {"ok": False, "code": "choose_mode", "done": len(done_here),
                        "remaining": len(pool) - len(done_here)}
            if mode == "remaining":
                pool = [it for it in pool if not (it.get("status") == "success"
                                                  and it.get("doneOn") == physical)]
                if not pool:
                    return {"ok": False, "code": "nothing_remaining"}
            for it in pool:
                it["status"] = "waiting"
                it["code"] = None
                it["arg"] = ""
            dev = next((d for d in self.sup.devices if d["serial"] == serial), {})
            self.job = {
                "running": True, "paused": False, "pauseReason": None,
                "pauseAfterCurrent": False, "finished": False,
                "serial": serial, "physical": physical, "name": dev.get("name") or serial,
                "order": [it["id"] for it in pool], "total": len(pool),
                "done": 0, "ok": 0, "failed": 0, "skipped": 0, "unverified": 0,
                "current": None, "currentLabel": None, "remaining": len(pool),
                "startedAt": time.time(), "results": [], "cancelReq": None,
            }
            self.save_queue()
        threading.Thread(target=self._install_worker, args=(self.job,), daemon=True).start()
        return {"ok": True}

    def pause_after_current(self):
        with self.lock:
            j = self.job
            if not j or not j.get("running"):
                return {"ok": False, "code": "no_running_job"}
            j["pauseAfterCurrent"] = True
        self._emit_job()
        return {"ok": True}

    # 旧接口兼容：「停止」等同于当前完成后暂停
    def stop_install(self):
        return self.pause_after_current()

    def continue_install(self, rebind_serial=None):
        """继续剩余队列。和「恢复后台」是两回事：这里只有用户点了才会继续装。"""
        with self.lock:
            j = self.job
            if not j:
                return {"ok": False, "code": "no_job"}
            if j.get("running"):
                return {"ok": False, "code": "busy_install"}
        remaining = self._remaining_ids(j)
        if not remaining:
            return {"ok": False, "code": "nothing_remaining"}
        serial, physical = j["serial"], j.get("physical")
        if rebind_serial and rebind_serial != serial:
            # 用户明确选择改装到另一台：重新绑定（界面上会先确认）
            uo = self.sup.usb_only
            if uo and rebind_serial != uo["serial"]:
                return {"ok": False, "code": "usb_only_locked", "arg": uo.get("name")}
            with self.adb.source("install"):
                if self.adb.get_state(rebind_serial) != "device":
                    return {"ok": False, "code": "target_not_ready"}
                physical = self.sup.physical_of(rebind_serial) or \
                    self.adb.physical_serial(rebind_serial)
            serial = rebind_serial
        else:
            why = self._target_check(serial, physical)
            if why:
                return {"ok": False, "code": "bound_" + why, "arg": j.get("name")}
        with self.lock:
            dev = next((d for d in self.sup.devices if d["serial"] == serial), {})
            j.update(serial=serial, physical=physical, running=True, paused=False,
                     pauseReason=None, pauseAfterCurrent=False, finished=False,
                     name=dev.get("name") or j.get("name") or serial)
            j["order"] = remaining
            for iid in remaining:
                it = next((x for x in self.items if x["id"] == iid), None)
                if it:
                    it["status"] = "waiting"
        threading.Thread(target=self._install_worker, args=(j,), daemon=True).start()
        return {"ok": True, "remaining": len(remaining)}

    def cancel_current(self):
        """取消正在装的那一个。只结束本程序自己启动的 adb install 进程，事后核验设备上的真实结果。"""
        with self.lock:
            j = self.job
            if not j or not j.get("running") or not j.get("current"):
                return {"ok": False, "code": "no_running_job"}
            j["cancelReq"] = j["current"]
            j["pauseAfterCurrent"] = True
            proc = self.cur_proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        return {"ok": True}

    def _flags(self):
        s = self.settings
        f = []
        if s.get("reinstall", True):
            f.append("-r")
        if s.get("allowDowngrade", True):
            f.append("-d")
        if s.get("grantPermissions"):
            f.append("-g")
        return f

    def _emit_job(self):
        self.bus.emit("job", job=self._job_public())
        try:
            self.sup._emit()
        except Exception:
            pass

    def _pause_job(self, job, reason):
        with self.lock:
            job.update(running=False, paused=True, pauseReason=reason,
                       current=None, currentLabel=None, pauseAfterCurrent=False)
            job["remaining"] = len(self._remaining_ids(job))
            for it in self.items:
                if it["id"] in job["order"] and it.get("status") == "waiting":
                    it["status"] = "pending"
            self.save_queue()
        self.bus.emit("install_paused", reason=reason, job=self._job_public())
        self._emit_job()
        if self.settings.get("notify") and reason in ("target_lost", "target_mismatch"):
            lang = self.settings.get("lang") or "zh"
            notify_mac(notify_text(lang, "paused"), job.get("name") or job["serial"],
                       sound=self.settings.get("sound", True))

    def _install_worker(self, job):
        flags = self._flags()
        serial, physical = job["serial"], job.get("physical")
        order = list(job["order"])
        self.bus.emit("install_start", serial=serial, total=job["total"])
        self._emit_job()
        idx_map = {it["id"]: it for it in self.items}
        for item_id in order:
            item = idx_map.get(item_id)
            if item is None or item.get("status") in ("success", "skipped"):
                continue
            if job.get("pauseAfterCurrent"):
                self._pause_job(job, "user" if not job.get("cancelReq") else "cancelled")
                return
            why = self._target_check(serial, physical)
            if why:
                self._pause_job(job, why)
                return
            with self.lock:
                job["current"] = item_id
                job["currentLabel"] = item.get("label") or item.get("file")
                item["status"] = "installing"
            self.bus.emit("item", id=item_id, status="installing",
                          index=job["done"] + 1, total=job["total"])
            self._emit_job()

            t0 = time.time()
            result = self._install_one(serial, item, flags, job)
            result["seconds"] = round(time.time() - t0, 1)
            result["index"] = job["done"] + 1

            with self.lock:
                item["status"] = result["status"]
                item["code"] = result.get("code")
                item["arg"] = result.get("arg") or ""
                if result["status"] == "success" and physical:
                    item["doneOn"] = physical
                # 核验时已经读到了设备上的真实版本，直接拿来更新「已安装」标记
                if "devVc" in result:
                    dvc, mine = result["devVc"], item.get("versionCode")
                    if dvc is None:
                        item["installed"] = {"state": "none", "serial": serial}
                    else:
                        st = ("same" if dvc == mine else "update" if mine and dvc < mine
                              else "downgrade" if mine else "unknown")
                        item["installed"] = {"state": st, "versionCode": dvc,
                                             "versionName": result.get("devVn"), "serial": serial}
                job["done"] += 1
                key = {"success": "ok", "skipped": "skipped",
                       "unverified": "unverified"}.get(result["status"], "failed")
                job[key] += 1
                job["results"].append(result)
                job["remaining"] = max(0, job["remaining"] - 1)
                self.save_queue()
            self.bus.emit("item", id=item_id, status=result["status"],
                          code=result.get("code"), arg=result.get("arg"),
                          installed=item.get("installed"),
                          seconds=result["seconds"], index=result["index"], total=job["total"],
                          progress={k: job[k] for k in ("done", "ok", "failed", "skipped",
                                                        "unverified", "total")})
            if self.settings.get("notify") and result["status"] in ("success", "failed"):
                lang = self.settings.get("lang") or "zh"
                label = item.get("label") or item.get("file")
                if result["status"] == "success":
                    notify_mac("%s (%d/%d)" % (notify_text(lang, "ok"), result["index"], job["total"]),
                               notify_text(lang, "installed") % label)
                else:
                    notify_mac("%s (%d/%d)" % (notify_text(lang, "fail"), result["index"], job["total"]),
                               label)
            if result["status"] == "cancelled" or result["status"] == "cancel_installed":
                self._pause_job(job, "cancelled")
                return
            if result["status"] == "failed" and self.settings.get("stopOnError"):
                self._pause_job(job, "error")
                return

        with self.lock:
            job.update(running=False, finished=True, paused=False, current=None,
                       currentLabel=None, endedAt=time.time())
            self.save_queue()
        try:
            with self.adb.source("install"):
                self.mark_installed(serial)
        except Exception:
            pass
        self.bus.emit("install_done", ok=job["ok"], failed=job["failed"],
                      skipped=job["skipped"], unverified=job["unverified"],
                      total=job["total"], seconds=round(time.time() - job["startedAt"], 1),
                      results=job["results"])
        self._emit_job()
        if self.settings.get("notify"):
            lang = self.settings.get("lang") or "zh"
            notify_mac(notify_text(lang, "done"),
                       notify_text(lang, "summary") % (job["ok"], job["failed"]),
                       sound=self.settings.get("sound", True))

    def _install_one(self, serial, item, flags, job):
        base = {"id": item["id"], "label": item.get("label"), "package": item.get("package")}
        parts = item.get("parts") or [item["path"]]
        parts = [p for p in parts if os.path.exists(p)]
        if not parts:
            return dict(base, status="failed", code="file_missing", arg="")

        pkg = item.get("package")
        if pkg and self.settings.get("skipSameVersion"):
            with self.adb.source("install"):
                vn, vc = self.adb.installed_version(serial, pkg)
            if vc is not None and item.get("versionCode") is not None and vc >= item["versionCode"]:
                return dict(base, status="skipped", code="already_current", arg=str(vn or vc))

        lines = []

        def on_line(line):
            lines.append(line)
            self.bus.emit("log", id=item["id"], text=line)

        def on_proc(proc):
            self.cur_proc = proc

        try:
            with self.adb.source("install"):
                code, out = self.adb.install(serial, parts, on_line=on_line, flags=flags,
                                             on_proc=on_proc)
        except AdbError as exc:
            return dict(base, status="failed", code="adb_error", arg=str(exc))
        except Exception as exc:
            return dict(base, status="failed", code="exec_error", arg=str(exc))
        finally:
            self.cur_proc = None

        # 用户点了「取消当前」：不猜结果，读设备上的真实状态
        if job.get("cancelReq") == item["id"]:
            vn, vc = (None, None)
            if pkg:
                with self.adb.source("install"):
                    vn, vc = self.adb.installed_version(serial, pkg)
            if vc is not None and vc == item.get("versionCode"):
                return dict(base, status="cancel_installed", code="cancel_but_installed",
                            arg=vn or str(vc), devVc=vc, devVn=vn)
            return dict(base, status="cancelled", code="cancelled_not_installed", arg="",
                        **({"devVc": vc, "devVn": vn} if pkg else {}))

        text = out or "\n".join(lines)
        if re.search(r"\bSuccess\b", text) and code == 0:
            # 不只看日志里的 Success：读设备上的包名和版本确认
            if not pkg or item.get("versionCode") is None:
                return dict(base, status="success", code="installed",
                            arg=item.get("versionName") or "", verified=False)
            with self.adb.source("install"):
                vn, vc = self.adb.installed_version(serial, pkg)
            dev = {"devVc": vc, "devVn": vn}
            if vc == item.get("versionCode"):
                return dict(base, status="success", code="installed_verified",
                            arg=vn or item.get("versionName") or "", verified=True, **dev)
            if vc is None:
                return dict(base, status="unverified", code="verify_missing", arg="", **dev)
            return dict(base, status="unverified", code="verify_mismatch",
                        arg="%s ≠ %s" % (vc, item.get("versionCode")), **dev)
        code_name, extra = explain_failure(text)
        return dict(base, status="failed", code=code_name, arg=extra,
                    detail=text[-600:] if text else "")

    # -- 设备应用枚举 ----------------------------------------------------
    def start_app_scan(self, serial, scope="third", with_icons=True):
        if not serial:
            return {"ok": False, "code": "need_target"}
        busy = self.busy_reason(serial)
        if busy:
            return {"ok": False, "code": busy}
        with self.lock:
            if self.apps_scan and self.apps_scan.get("running"):
                return {"ok": False, "error": "正在读取应用列表，请稍候"}
            self.scan_cancel.clear()
            self.apps_scan = {"running": True, "serial": serial, "scope": scope,
                              "total": 0, "done": 0, "apps": [], "startedAt": time.time()}
        t = threading.Thread(target=self._scan_worker,
                             args=(serial, scope, with_icons), daemon=True)
        t.start()
        return {"ok": True}

    def stop_app_scan(self):
        self.scan_cancel.set()
        return {"ok": True}

    def _scan_worker(self, serial, scope, with_icons):
        with self.adb.source("scan"):
            return self._scan_worker_inner(serial, scope, with_icons)

    def _scan_worker_inner(self, serial, scope, with_icons):
        scan = self.apps_scan
        try:
            pkgs = self.adb.list_packages(serial, scope)
        except Exception as exc:
            scan["running"] = False
            scan["error"] = str(exc)
            self.bus.emit("scan_done", error=str(exc))
            return
        pkgs.sort(key=lambda a: a["package"])
        scan["total"] = len(pkgs)
        self.bus.emit("scan_start", total=len(pkgs))

        reader = RemoteApkReader(self.adb, serial)
        lock = threading.Lock()
        work = list(enumerate(pkgs))
        results = [None] * len(pkgs)

        def worker():
            with self.adb.source("scan"):
                return worker_inner()

        def worker_inner():
            while True:
                if self.scan_cancel.is_set():
                    return
                with lock:
                    if not work:
                        return
                    i, rec = work.pop(0)
                app = self._app_meta(reader, serial, rec, with_icons)
                results[i] = app
                with lock:
                    scan["done"] += 1
                    scan["apps"].append(app)
                self.bus.emit("scan_item", app=app, done=scan["done"], total=scan["total"])

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        scan["apps"] = [a for a in results if a] or scan["apps"]
        scan["running"] = False
        scan["endedAt"] = time.time()
        self.save_label_cache()
        self.bus.emit("scan_done", total=scan["total"], done=scan["done"],
                      cancelled=self.scan_cancel.is_set())

    def _app_meta(self, reader, serial, rec, with_icons):
        pkg = rec["package"]
        paths = rec.get("paths") or []
        base = next((p for p in paths if p.endswith("base.apk")), paths[0] if paths else None)
        app = {"package": pkg, "label": pkg, "paths": paths, "base": base,
               "versionName": None, "versionCode": None, "icon": None,
               "splitCount": max(0, len(paths) - 1), "size": None}
        cache_key = pkg
        cached = self.label_cache.get(cache_key)
        if cached and cached.get("base") == base:
            app.update({k: cached.get(k, app[k]) for k in
                        ("label", "versionName", "versionCode", "size")})
            if cached.get("icon") and os.path.exists(
                    os.path.join(ICON_DIR, cached["icon"])):
                app["icon"] = "/api/appicon/" + cached["icon"]
                return app
        if not base:
            return app
        try:
            size = self.adb.remote_size(serial, base)
            app["size"] = size
            info, icon = reader.info(base, want_icon=with_icons)
            app["label"] = info.label or pkg
            app["versionName"] = info.version_name
            app["versionCode"] = info.version_code
            icon_name = None
            if icon:
                icon_name = re.sub(r"[^A-Za-z0-9_.-]", "_", pkg) + ".img"
                try:
                    with open(os.path.join(ICON_DIR, icon_name), "wb") as f:
                        f.write(icon)
                    app["icon"] = "/api/appicon/" + icon_name
                except Exception:
                    icon_name = None
            self.label_cache[cache_key] = {
                "base": base, "label": app["label"], "versionName": app["versionName"],
                "versionCode": app["versionCode"], "icon": icon_name, "size": size}
        except Exception as exc:
            app["error"] = str(exc)
        return app

    # -- 提取 -----------------------------------------------------------
    def extract(self, serial, packages, apps_meta=None):
        busy = self.busy_reason(serial)
        if busy:
            self.bus.emit("extract_done", total=0, ok=0, results=[], dir="", blocked=busy)
            return {"ok": False, "code": busy}
        """把设备上的应用 APK 拉取到「提取APP」文件夹。"""
        out_root = os.path.join(os.path.expanduser(
            self.settings.get("extractDir") or BASE_DIR), "提取APP")
        ensure_dir(out_root)
        meta = {a["package"]: a for a in (apps_meta or [])}
        done = []
        self.bus.emit("extract_start", total=len(packages), dir=out_root)
        for i, pkg in enumerate(packages, 1):
            info = meta.get(pkg) or {}
            label = info.get("label") or pkg
            with self.adb.source("extract"):
                paths = info.get("paths") or self.adb.package_paths(serial, pkg)
            safe = re.sub(r'[\\/:*?"<>|]', "_", label).strip() or pkg
            ver = info.get("versionName")
            folder_name = "%s_%s" % (safe, pkg) + ("_v%s" % ver if ver else "")
            target_dir = os.path.join(out_root, folder_name)
            ensure_dir(target_dir)
            self.bus.emit("extract_item", package=pkg, label=label,
                          status="running", index=i, total=len(packages))
            files, errs = [], []
            for p in paths:
                name = os.path.basename(p)
                if name == "base.apk" and len(paths) > 1:
                    local_name = "base.apk"
                elif len(paths) == 1:
                    local_name = "%s.apk" % safe
                else:
                    local_name = name
                local = os.path.join(target_dir, local_name)
                try:
                    with self.adb.source("extract"):
                        code, out = self.adb.pull(serial, p, local)
                    if os.path.exists(local) and os.path.getsize(local) > 0:
                        files.append(local)
                    else:
                        errs.append(out[-200:] if out else "拉取失败")
                except Exception as exc:
                    errs.append(str(exc))
            ok = bool(files)
            if ok:
                try:
                    with open(os.path.join(target_dir, "info.txt"), "w", encoding="utf-8") as f:
                        f.write("App / アプリ / 应用     : %s\n"
                                "Package / パッケージ / 包名: %s\n"
                                "Version / バージョン / 版本 : %s\n"
                                "Files / ファイル / 文件数  : %d\n"
                                "Extracted / 抽出 / 提取时间 : %s\n"
                                % (label, pkg, ver or "-", len(files),
                                   time.strftime("%Y-%m-%d %H:%M:%S")))
                except Exception:
                    pass
            done.append({"package": pkg, "label": label, "ok": ok,
                         "dir": target_dir, "files": [os.path.basename(f) for f in files],
                         "error": "; ".join(errs) if errs and not ok else ""})
            self.bus.emit("extract_item", package=pkg, label=label,
                          status="done" if ok else "failed", dir=target_dir,
                          files=len(files), index=i, total=len(packages))
        okc = sum(1 for d in done if d["ok"])
        self.bus.emit("extract_done", total=len(packages), ok=okc, dir=out_root,
                      results=done)
        if self.settings.get("notify"):
            lang = self.settings.get("lang") or "zh"
            notify_mac(notify_text(lang, "extract_done"),
                       notify_text(lang, "extract_msg") % okc,
                       sound=self.settings.get("sound", True))
        return {"ok": True, "dir": out_root, "results": done}

    def reveal(self, path):
        """在访达中显示。"""
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", path if os.path.isdir(path)
                                else os.path.dirname(path)], capture_output=True)
                return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "当前系统不支持"}

    # -- 状态 -----------------------------------------------------------
    def state(self):
        with self.lock:
            st = {
                "adb": {"path": self.adb.path, "available": self.adb.available},
                "items": list(self.items),
                "settings": self.settings,
                "job": self._job_public() if self.job else None,
                "scan": {k: v for k, v in (self.apps_scan or {}).items() if k != "apps"},
                "profiles": sorted(self.profiles().keys()),
                "baseDir": BASE_DIR,
            }
        st["sup"] = self.sup.state()
        return st
