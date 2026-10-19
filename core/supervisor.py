# -*- coding: utf-8 -*-
"""后台 ADB 任务的统一管理入口。

本程序所有「自动」碰设备的动作都在这里，由一个线程按顺序执行：

    discovery       设备发现      adb devices -l
    status          状态查询      新设备的 getprop（含物理序号）、选中设备的已安装标记
    wifi_connect    无线自动连接  启动时连一次用过的无线地址
    wifi_reconnect  断线重连      无线设备掉线后有限次重连（5s / 15s / 45s，之后停下等手动）

几条硬规则：
- 只有一个执行线程。网页刷新、开多个窗口、连点「恢复」都不会多出一份循环。
- 暂停 = 不再发起新任务。正在跑的那一条显示「正在收尾」，它的结果会被丢弃，
  不会覆盖暂停后的状态（靠 gen 代次号判断）。
- 手动「检测一次 / 重试一次」只执行这一次，不会顺带把自动循环打开。
- 所有命令都有超时；连续失败后停在可见的等待状态，不会无限重试。
- 不执行 adb kill-server，不结束任何不是本程序启动的进程，不会断开没被明确选中的连接。

注意：adb 服务自身（platform-tools 31+）会通过 mDNS 自动连接已配对的无线设备，
那是 adb 服务的行为，不归本程序管；这里的暂停只能保证「本程序」不再发起连接。
"""
import os
import queue
import threading
import time

TASKS = ("discovery", "status", "wifi_connect", "wifi_reconnect")
# 间隔可用环境变量覆盖（主要给自动化测试用），默认值即正常使用时的节奏
DISCOVERY_INTERVAL = float(os.environ.get("APKMGR_DISCOVERY_INTERVAL") or 6)   # 秒
DISCOVERY_MAX_FAILS = 3         # 连续失败几次后停下等手动
RECONNECT_BACKOFF = tuple(float(x) for x in
                          (os.environ.get("APKMGR_RECONNECT_BACKOFF") or "5,15,45").split(","))
CMD_TIMEOUT = 8                 # 后台命令的超时


def _now():
    return time.time()


def is_wireless(serial):
    s = serial or ""
    if "._tcp" in s or s.startswith("adb-"):
        return True
    if ":" in s:
        host, _, port = s.rpartition(":")
        return bool(host) and port.isdigit()
    return False


class Supervisor(object):
    def __init__(self, engine):
        self.E = engine
        self.adb = engine.adb
        self.lock = threading.RLock()
        st = engine.settings
        self.bg_paused = bool(st.get("bgPaused"))
        self.wifi_paused = bool(st.get("wifiPaused"))
        self.usb_only = st.get("usbOnly") or None      # {"serial", "physical", "name"}
        self.gen = 0                    # 每次暂停 +1，用来识别并丢弃迟到的结果
        self.bg_epoch = 0               # 每次「暂停后台」+1：安装核验用它判断结果是否在暂停之后才回来
        self.devices = []
        self.devices_at = None          # 最近一次成功检测的时间
        self.selected = None
        self.props = {}                 # serial -> getprop 结果
        self.wifi_meta = dict(st.get("wifiPhysical") or {})   # 无线地址 -> 物理序号
        self.reconnect = {}             # target -> {"attempts", "next", "gaveUp"}
        self.pending_detail = set()
        self.pending_mark = None
        self.wifi_connect_pending = bool(st.get("autoReconnect", True))
        self.last_failure = None
        self.last_check = None
        self.verify_pending_req = True      # 启动时也先核验上次留下的「待核验」
        self.our_connects = {}               # 本程序发起过 connect 的地址 -> 时间
        self.adb.listeners.append(self._on_cmd)
        self.server = None
        self.running = None             # 正在执行的任务名
        self.tasks = {n: {"state": "idle", "lastRun": None, "lastOk": None,
                          "lastError": None, "next": None, "fails": 0, "note": ""}
                      for n in TASKS}
        self.tasks["discovery"]["next"] = 0
        self._jobs = queue.Queue()
        self._wake = threading.Event()
        self._started = False
        self._start_lock = threading.Lock()
        self._refresh_states()

    # ------------------------------------------------------------------ 启动
    def start(self):
        """幂等：无论调用多少次，都只有一个执行线程。"""
        with self._start_lock:
            if self._started:
                return False
            self._started = True
        threading.Thread(target=self._loop, name="adb-supervisor", daemon=True).start()
        return True

    def threads_alive(self):
        return sum(1 for t in threading.enumerate() if t.name == "adb-supervisor")

    # ------------------------------------------------------------------ 状态
    def _persist(self):
        self.E.settings.update({
            "bgPaused": self.bg_paused, "wifiPaused": self.wifi_paused,
            "usbOnly": self.usb_only, "wifiPhysical": self.wifi_meta,
        })
        self.E.save_settings()

    def _refresh_states(self):
        """根据暂停开关推导每个任务该显示的状态。"""
        for name, t in self.tasks.items():
            if self.running == name:
                paused = self.bg_paused or (name.startswith("wifi") and self.wifi_paused)
                t["state"] = "finishing" if paused else "running"
                continue
            if self.bg_paused:
                t["state"] = "paused"
            elif name.startswith("wifi") and self.wifi_paused:
                t["state"] = "paused"
            elif t["state"] in ("running", "finishing", "paused"):
                t["state"] = "idle"

    def _emit(self):
        try:
            self.E.bus.emit("supervisor", state=self.state())
        except Exception:
            pass

    def state(self):
        with self.lock:
            self._refresh_states()
            stale = self.bg_paused or self.tasks["discovery"]["state"] == "waiting"
            job_pub = self.E._job_public() if self.E.job else {}
            return {
                "bgPaused": self.bg_paused, "wifiPaused": self.wifi_paused,
                "usbOnly": self.usb_only, "selected": self.selected,
                "devices": self.devices, "devicesAt": self.devices_at, "stale": stale,
                "tasks": self.tasks, "running": self.running,
                "reconnect": [dict(v, target=k, protected=self._protected(k))
                              for k, v in self.reconnect.items()],
                "server": self.server, "active": self.adb.active_list(),
                "lastFailure": self.last_failure, "lastCheck": self.last_check,
                "threads": self.threads_alive(),
                "install": job_pub,
            }

    def _on_cmd(self, rec):
        parts = (rec.get("cmd") or "").split()
        if "connect" in parts:
            tgt = parts[parts.index("connect") + 1] if len(parts) > parts.index("connect") + 1 else ""
            if tgt:
                if ":" not in tgt:
                    tgt += ":5555"
                self.our_connects[tgt] = rec.get("ended") or _now()

    def physical_of(self, serial):
        p = (self.props.get(serial) or {}).get("serialno")
        if not p and is_wireless(serial):
            p = self.wifi_meta.get(serial)
        return p

    def _protected(self, target):
        """仅 USB 模式下，属于那台设备（或无法确认归属）的无线地址不自动连接。"""
        if not self.usb_only:
            return False
        phys = self.wifi_meta.get(target)
        return phys is None or phys == self.usb_only.get("physical")

    # ------------------------------------------------------------------ 控制
    def pause_all(self):
        # 先在门控锁内立起暂停标志：这一步返回后，受门控的 adb 命令不会再被启动
        with self.E.adb.gate_lock:
            first = not self.bg_paused
            self.bg_paused = True
            if first:
                self.bg_epoch += 1
        with self.lock:
            if first:
                self.gen += 1
                self._persist()
        # 暂停后台 = 本程序不再主动碰设备：正在执行的那个 APK 让它装完，但不开始下一项
        j = self.E.job or {}
        if j.get("running"):
            self.E.pause_after_current("bg_paused")
        self._emit()
        return {"ok": True}

    def resume_all(self):
        with self.lock:
            if self.bg_paused:          # 重复点「恢复」是空操作，不会叠加任务
                self.bg_paused = False
                self.tasks["discovery"].update(next=0, fails=0)
                if self.tasks["discovery"]["state"] == "waiting":
                    self.tasks["discovery"]["state"] = "idle"
                self.verify_pending_req = True     # 恢复后先核验「待核验」的安装结果
                self._persist()
        self._wake.set()
        self._emit()
        return {"ok": True}

    def pause_wifi(self):
        with self.lock:
            if not self.wifi_paused:
                self.wifi_paused = True
                self.gen += 1
                self._persist()
        self._emit()
        return {"ok": True}

    def resume_wifi(self):
        with self.lock:
            if self.wifi_paused:
                self.wifi_paused = False
                now = _now()
                for r in self.reconnect.values():
                    if not r.get("gaveUp"):
                        r["next"] = now + RECONNECT_BACKOFF[0]
                self._persist()
        self._wake.set()
        self._emit()
        return {"ok": True}

    def set_usb_only(self, serial):
        """serial 为空表示关闭仅 USB 模式。"""
        if self.E.job and self.E.job.get("running"):
            return {"ok": False, "code": "busy_install"}
        if not serial:
            with self.lock:
                self.usb_only = None
                self._persist()
            self._emit()
            return {"ok": True}
        if is_wireless(serial):
            return {"ok": False, "code": "usb_only_needs_usb"}
        dev = next((d for d in self.devices if d["serial"] == serial), None)
        if not dev or dev["state"] != "device":
            return {"ok": False, "code": "device_not_ready"}
        phys = self.physical_of(serial) or self._run_manual("physical", serial).get("physical")
        with self.lock:
            self.usb_only = {"serial": serial, "physical": phys or serial,
                             "name": dev.get("name") or serial}
            self.selected = serial
            self._persist()
        self._emit()
        return {"ok": True, "usbOnly": self.usb_only}

    def select(self, serial):
        """界面换了目标设备。共享给所有窗口；需要时排队一次已安装标记。"""
        with self.lock:
            if self.usb_only and serial and serial != self.usb_only["serial"]:
                return {"ok": False, "code": "usb_only_locked"}
            changed = serial != self.selected
            self.selected = serial or None
            if changed:
                if not serial:
                    self.E.clear_marks()
                elif self.E.settings.get("autoMark", True):
                    self.pending_mark = serial
        self._wake.set()
        self._emit()
        return {"ok": True}

    def check_once(self):
        """手动检测一次：设备发现 + 新设备的属性。暂停中也只执行这一次。"""
        return self._run_manual("discovery")

    def retry_wifi(self, target):
        return self._run_manual("wifi_retry", target)

    # ------------------------------------------------------------------ 执行线程
    def _run_manual(self, kind, arg=None, timeout=40):
        box = {"done": threading.Event(), "result": None}
        self._jobs.put((kind, arg, box))
        self._wake.set()
        if not self._started:           # 测试或尚未启动时同步执行
            self._drain_jobs()
        box["done"].wait(timeout)
        return box["result"] or {"ok": False, "code": "timeout"}

    def _drain_jobs(self):
        while True:
            try:
                kind, arg, box = self._jobs.get_nowait()
            except queue.Empty:
                return
            try:
                if kind == "discovery":
                    box["result"] = self._task_discovery(manual=True)
                    self._task_status(manual=True)
                    j = self.E.job or {}
                    if not j.get("running") and self.E.pending_items():
                        box["result"]["verify"] = self.E.verify_pending(source="ui")
                elif kind == "wifi_retry":
                    box["result"] = self._connect(arg, task="wifi_reconnect", manual=True)
                elif kind == "physical":
                    with self.adb.source("ui"):
                        box["result"] = {"physical": self.adb.physical_serial(arg)}
            except Exception as exc:
                box["result"] = {"ok": False, "error": str(exc)}
            finally:
                box["done"].set()
                self._emit()

    def _loop(self):
        while True:
            self._wake.wait(0.5)
            self._wake.clear()
            try:
                self._drain_jobs()
                self._tick()
            except Exception as exc:     # 调度线程绝不能死
                self._fail("supervisor", str(exc))

    def _tick(self):
        now = _now()
        with self.lock:
            if self.bg_paused:
                return
            d = self.tasks["discovery"]
            due_disc = d["state"] != "waiting" and d["next"] is not None and now >= d["next"]
            due_status = bool(self.pending_detail or self.pending_mark)
            due_conn = (not self.wifi_paused and self.wifi_connect_pending
                        and self.devices_at is not None)
            due_rec = [] if self.wifi_paused else [
                t for t, r in self.reconnect.items()
                if not r.get("gaveUp") and r["next"] <= now]
        if self.verify_pending_req and self.devices_at is not None:
            self.verify_pending_req = False
            j = self.E.job or {}
            if not j.get("running") and self.E.pending_items():
                self.E.verify_pending(source="bg:verify")
                self._emit()
        if due_disc:
            self._task_discovery()
        if due_status:
            self._task_status()
        if due_conn:
            self._task_wifi_connect()
        for t in due_rec:
            if self.bg_paused or self.wifi_paused:
                break
            self._task_reconnect(t)

    # ------------------------------------------------------------------ 任务
    def _begin(self, name):
        with self.lock:
            self.running = name
            t = self.tasks[name]
            t["lastRun"] = _now()
            self._refresh_states()
            return self.gen
        # （_emit 由调用方在合适时机发）

    def _finish(self, name, gen, manual, ok, error=None, note=None):
        """返回 True 表示结果可以采用；False 表示期间被暂停，结果作废。"""
        with self.lock:
            self.running = None
            t = self.tasks[name]
            late = (gen != self.gen) and not manual
            if late:
                t["note"] = "late_discarded"
            elif ok:
                t["lastOk"] = _now()
                t["lastError"] = None
                t["fails"] = 0
                t["note"] = note or ""
            else:
                t["lastError"] = error
                t["note"] = note or ""
            self._refresh_states()
        return not late

    def _fail(self, stage, reason, detail=None):
        with self.lock:
            self.last_failure = {"ts": _now(), "stage": stage, "reason": (reason or "")[:200],
                                 "detail": (detail or "")[-1500:]}

    def _task_discovery(self, manual=False):
        g = self._begin("discovery")
        self._emit()
        ok, error, devs = False, None, None
        try:
            if not self.adb.available:
                raise RuntimeError("adb_missing")
            with self.adb.source("ui" if manual else "bg:discovery"):
                devs = self.adb.devices()
                server = self.adb.server_status()
            ok = True
        except Exception as exc:
            error = "adb_missing" if str(exc) == "adb_missing" else (str(exc) or "timeout")
        usable = self._finish("discovery", g, manual, ok, error)
        self.last_check = _now()
        with self.lock:
            d = self.tasks["discovery"]
            if not ok:
                d["fails"] += 1
                self._fail("discovery", error)
                if d["fails"] >= DISCOVERY_MAX_FAILS and not manual:
                    d["state"] = "waiting"
                    d["next"] = None
                    d["note"] = "gave_up"
                else:
                    d["next"] = _now() + DISCOVERY_INTERVAL
                self._emit()
                return {"ok": False, "error": error}
            if not usable:
                self._emit()
                return {"ok": False, "code": "late_discarded"}
            if d["state"] == "waiting":
                d["state"] = "idle"
            d["next"] = _now() + DISCOVERY_INTERVAL
            self.server = server
            self._apply_devices(devs)
        self._emit()
        return {"ok": True, "count": len(devs)}

    def _apply_devices(self, devs):
        prev = {d["serial"]: d["state"] for d in self.devices}
        live = {d["serial"] for d in devs}
        for s in list(self.props):
            if s not in live:
                self.props.pop(s, None)
        for d in devs:
            s = d["serial"]
            d["wireless"] = is_wireless(s)
            if d["state"] == "device" and s not in self.props:
                if not (d["wireless"] and self.wifi_paused):
                    self.pending_detail.add(s)
            p = self.props.get(s) or {}
            d.update({k: p[k] for k in ("brand", "android", "abi") if k in p})
            if p.get("model"):
                d["model"] = p["model"]
            name = " ".join(x for x in [(p.get("brand") or "").title(), p.get("model") or ""] if x)
            d["name"] = name or d.get("model") or s
            d["physical"] = self.physical_of(s)
            d["detailPaused"] = d["wireless"] and self.wifi_paused and s not in self.props
        # 按物理序号合并 USB / Wi-Fi 两个入口（只认核验过的序号，不按型号猜）
        groups = {}
        for d in devs:
            if d.get("physical"):
                groups.setdefault(d["physical"], []).append(d["serial"])
        for d in devs:
            peers = [x for x in groups.get(d.get("physical"), []) if x != d["serial"]]
            d["peers"] = peers
            d["duplicate"] = bool(peers)
            if d["wireless"]:
                # 只陈述能确认的事实：是不是本程序发起的连接。来源无法确定时不做归因。
                d["origin"] = "ours" if d["serial"] in self.our_connects else "unknown"
        # 记住的无线地址掉线了 → 安排有限次重连
        hist = set(self.E.settings.get("wirelessHistory") or [])
        auto = self.E.settings.get("autoReconnect", True)
        for s, st in prev.items():
            if is_wireless(s) and st == "device" and s in hist and auto:
                now_state = next((d["state"] for d in devs if d["serial"] == s), None)
                if now_state != "device" and s not in self.reconnect:
                    self.reconnect[s] = {"attempts": 0, "next": _now() + RECONNECT_BACKOFF[0],
                                         "gaveUp": False, "lastError": None}
        for d in devs:
            if d["state"] == "device" and d["serial"] in self.reconnect:
                self.reconnect.pop(d["serial"], None)
        self.devices = devs
        self.devices_at = _now()
        self._auto_select(prev, devs)

    def _auto_select(self, prev, devs):
        """插上 USB 线的设备默认成为目标设备。只改「界面选中的设备」，不改任何安装任务的绑定：
        暂停中的队列仍绑定原设备，不会因此续装到新插上的设备。
        - 新插上（或刚点了「允许」）的 USB 设备：当前没选、选的是 Wi-Fi、或选中的设备已断开 → 切到它；
          当前已经选着一台在线的 USB 设备时不抢（多根线同时接时以用户的选择为准）。
        - 还没选过：USB 优先，其次才是 Wi-Fi。
        - 选中的设备断开时，仍然不自动换到别的已连设备。仅 USB 模式下一律不动。"""
        if self.usb_only:
            return
        ready = [d for d in devs if d["state"] == "device"]
        usb_ready = [d for d in ready if not d["wireless"]]
        cur = next((d for d in ready if d["serial"] == self.selected), None)
        newly = [d for d in usb_ready if prev.get(d["serial"]) != "device"]
        pick, why = None, None
        if newly and (cur is None or cur["wireless"]):
            pick, why = newly[0], "usb_plugged"
        elif self.selected is None and ready:
            pick, why = (usb_ready or ready)[0], "initial"
        if not pick or pick["serial"] == self.selected:
            return
        old = self.selected
        self.selected = pick["serial"]
        if self.E.settings.get("autoMark", True):
            self.pending_mark = pick["serial"]
        if why == "usb_plugged" and old:
            self.E.bus.emit("device_autoselect", serial=pick["serial"], name=pick.get("name") or pick["serial"],
                            previous=old)

    def _task_status(self, manual=False):
        with self.lock:
            serials = list(self.pending_detail)
            mark = self.pending_mark
            self.pending_detail.clear()
            self.pending_mark = None
        if not serials and not mark:
            return
        g = self._begin("status")
        self._emit()
        results, err = {}, None
        try:
            with self.adb.source("ui" if manual else "bg:status"):
                for s in serials:
                    if not manual and (self.bg_paused or self.gen != g):
                        break
                    if is_wireless(s) and self.wifi_paused and not manual:
                        continue
                    results[s] = self.adb.device_detail(s)
        except Exception as exc:
            err = str(exc)
        usable = self._finish("status", g, manual, err is None, err)
        with self.lock:
            if usable:
                for s, p in results.items():
                    self.props[s] = p
                    if is_wireless(s) and p.get("serialno"):
                        self.wifi_meta[s] = p["serialno"]
                if results:
                    self._apply_devices([dict(d) for d in self.devices])
                    self._persist()
        self._emit()
        if mark and usable and not self.bg_paused:
            self._do_mark(mark, g, manual)

    def _do_mark(self, serial, g, manual):
        if self.E.busy_reason(serial):
            return                          # 正在往这台装东西，不打扰
        g = self._begin("status")
        self._emit()
        try:
            with self.adb.source("ui" if manual else "bg:status"):
                marks, counts = self.E.compute_marks(serial)
            err = None
        except Exception as exc:
            marks, err = None, str(exc)
        usable = self._finish("status", g, manual, err is None, err)
        with self.lock:
            # 迟到的结果：期间被暂停、或者界面已经换成别的设备 → 丢弃
            if not usable or self.selected != serial:
                if usable:
                    self.tasks["status"]["note"] = "late_discarded"
                self._emit()
                return
        if err:
            self._fail("status", err)
        else:
            self.E.apply_marks(serial, marks, counts)
        self._emit()

    def _task_wifi_connect(self):
        with self.lock:
            self.wifi_connect_pending = False
            online = {d["serial"] for d in self.devices if d["state"] == "device"}
            targets = [t for t in (self.E.settings.get("wirelessHistory") or [])[:3]
                       if t not in online]
        for t in targets:
            if self.bg_paused or self.wifi_paused:
                break
            if self._protected(t):
                with self.lock:
                    self.tasks["wifi_connect"]["note"] = "skipped_usb_only"
                continue
            self._connect(t, task="wifi_connect")
            if self.bg_paused or self.wifi_paused:
                break

    def _task_reconnect(self, target):
        if self._protected(target):
            with self.lock:
                self.tasks["wifi_reconnect"]["note"] = "skipped_usb_only"
                r = self.reconnect.get(target)
                if r:
                    r["next"] = _now() + RECONNECT_BACKOFF[-1]
            return
        self._connect(target, task="wifi_reconnect")

    def _connect(self, target, task, manual=False):
        g = self._begin(task)
        self._emit()
        ok, msg = False, ""
        try:
            with self.adb.source("ui" if manual else "bg:" + task):
                ok, msg, _ = self.adb.connect(target, timeout=10)
        except Exception as exc:
            msg = str(exc)
        usable = self._finish(task, g, manual, ok, None if ok else msg)
        with self.lock:
            r = self.reconnect.get(target)
            if ok and usable:
                self.reconnect.pop(target, None)
                self.tasks["discovery"]["next"] = 0     # 尽快刷新列表
            elif not ok:
                self._fail(task, msg, msg)
                if r is not None and not manual:
                    r["attempts"] += 1
                    r["lastError"] = msg[:160]
                    if r["attempts"] >= len(RECONNECT_BACKOFF):
                        r["gaveUp"] = True        # 停在这里，等手动「重试一次」
                        r["next"] = None
                    else:
                        r["next"] = _now() + RECONNECT_BACKOFF[r["attempts"]]
                elif r is not None and manual:
                    r["lastError"] = msg[:160]  # 手动重试失败不重新开启自动循环
        self._wake.set()
        self._emit()
        return {"ok": ok, "target": target, "message": msg, "discarded": not usable}
