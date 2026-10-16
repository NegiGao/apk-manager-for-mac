"""在真实 macOS 上做「隔离验收」：只在一个新建的测试目录里活动。

- 不碰现场：每个场景用独立的临时 HOME（数据目录、队列、设置、日志、端口文件、锁文件全在里面），
  提取输出目录也指到测试目录里。不修改全局环境变量，不清除隔离属性，不碰系统安全设置。
- 只用假 ADB：启动前确认假 ADB 的绝对路径存在且可执行、确实是假的；启动后再核对程序实际用的 ADB 路径，
  对不上立刻停止这个测试实例并中止验收（不会去调用真实 adb，也不会碰共享 adb 服务）。
- 浏览器：程序的「打开窗口」被指到一个只记录参数的脚本（APKMGR_BROWSER），不会接管你的 Chrome。
  界面版本号用 Claude 桌面应用自带的浏览器面板单独查看（驱动在那一步暂停等待）。
- 只结束本驱动启动的进程（按 PID，以及命令行里带本测试目录路径的进程）。

这是测试驱动，不改产品代码。用法见 run.command。
"""
import argparse, hashlib, json, os, plistlib, shutil, signal, socket, subprocess, sys, time, zipfile
import urllib.request

RESULTS = []
STARTED = []          # 本驱动启动的进程
LOG = []
LOG_PATH = [None]


def say(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    LOG.append(line)
    print(line, flush=True)
    if LOG_PATH[0]:
        with open(LOG_PATH[0], "a", encoding="utf-8") as f:
            f.write(line + "\n")


def my_lineage():
    """本驱动自己和它的上级进程（Terminal 里的 shell）——清理时绝不碰。"""
    parent = {pid: ppid for pid, ppid, _ in ps_rows()}
    keep, p = set(), os.getpid()
    while p and p not in keep:
        keep.add(p)
        p = parent.get(p)
    return keep


def check(cond, item, detail=""):
    RESULTS.append({"item": item, "ok": bool(cond), "detail": detail})
    say(("✓ " if cond else "✗ ") + item + ("（%s）" % detail if detail else ""))
    return cond


class Stop(Exception):
    pass


def http(port, path, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    rq = urllib.request.Request("http://127.0.0.1:%s%s" % (port, path), data=data,
                                headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(rq, timeout=timeout))


def sup_dir(home):
    # 与 core/paths.py 一致：macOS 的数据目录在 ~/Library/Application Support/APK安装管家
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "APK安装管家")
    return os.path.join(home, ".apk-installer")


def log_file(home):
    return os.path.join(home, "Library", "Logs", "APK安装管家.log")


def ps_rows():
    out = subprocess.run(["ps", "-ww", "-Ao", "pid=,ppid=,args="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    return rows


def proc_cwd(pid):
    """进程的工作目录（只读）：Linux 读 /proc，macOS 用 lsof。"""
    p = "/proc/%d/cwd" % pid
    if os.path.exists(p):
        try:
            return os.readlink(p)
        except Exception:
            return None
    try:
        out = subprocess.run(["/usr/sbin/lsof", "-a", "-d", "cwd", "-p", str(pid), "-Fn"],
                             capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if line.startswith("n"):
                return line[1:]
    except Exception:
        pass
    return None


class Ctx(object):
    def __init__(self, a):
        self.a = a
        self.work = a.work
        self.app = os.path.join(self.work, "解压 测试", "APK Manager.app")
        self.launcher = os.path.join(self.app, "Contents", "MacOS", "launcher")
        self.fake_src = os.path.join(a.src, "tests", "fakeadb", "adb")
        self.apks = {k: os.path.join(a.src, "tests", "apks", k + ".apk") for k in ("termux", "newpipe", "seal")}

    # ------------------------------------------------------------ 测试 HOME
    def make_home(self, name):
        home = os.path.join(self.work, "homes", name)
        for d in ("dev", "fakebin", "out", "tmp", "Library/Logs"):
            os.makedirs(os.path.join(home, d), exist_ok=True)
        wrapper = os.path.join(home, "fakebin", "adb")
        with open(wrapper, "w") as f:
            f.write('#!/bin/bash\n# 假 ADB：只操作本测试目录里的模拟设备\n'
                    'export FAKE_DEV_ROOT="%s" FAKE_ADB_LOG="%s"\nexec "%s" "%s" "$@"\n'
                    % (os.path.join(home, "dev"), os.path.join(home, "adb-commands.log"),
                       sys.executable, self.fake_src))
        os.chmod(wrapper, 0o755)
        rec = os.path.join(home, "fakebin", "browser.sh")
        with open(rec, "w") as f:
            f.write('#!/bin/bash\necho "$(date +%%H:%%M:%%S) $*" >> "%s"\n' % os.path.join(home, "browser.log"))
        os.chmod(rec, 0o755)
        sd = sup_dir(home)
        os.makedirs(sd, exist_ok=True)
        with open(os.path.join(sd, "settings.json"), "w") as f:
            json.dump({"extractDir": os.path.join(home, "out"), "notify": False}, f)
        return home

    def env(self, home):
        return {"HOME": home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "zh_CN.UTF-8",
                "TMPDIR": os.path.join(home, "tmp"),
                "APKMGR_ADB": os.path.join(home, "fakebin", "adb"),
                "APKMGR_BROWSER": os.path.join(home, "fakebin", "browser.sh"),
                **({"APKMGR_PYTHON": sys.executable} if self.a.dry_run_linux else {})}   # 仅 Linux 演练

    def verify_fake_adb(self, home):
        w = os.path.join(home, "fakebin", "adb")
        ok = os.path.isabs(w) and os.path.isfile(w) and os.access(w, os.X_OK)
        out = ""
        if ok:
            out = subprocess.run([w, "version"], capture_output=True, text=True, timeout=20).stdout
        if not (ok and "fake" in out):
            raise Stop("假 ADB 不可用（%s）：%s" % (w, out.strip()[:200]))
        return w

    def launch(self, home):
        self.verify_fake_adb(home)
        p = subprocess.Popen([self.launcher], env=self.env(home), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        STARTED.append(p)
        return p

    def wait_port(self, home, timeout=40):
        pf = os.path.join(sup_dir(home), "port")
        t = time.time()
        while time.time() - t < timeout:
            try:
                port = open(pf).read().strip()
                if port.isdigit() and http(port, "/api/ping", timeout=2):
                    return port
            except Exception:
                pass
            time.sleep(0.2)
        return None

    def adb_guard(self, home, port):
        """启动后核对实际使用的 ADB；不是假的就立刻结束这个测试实例并中止。"""
        st = http(port, "/api/state")
        used = (st.get("adb") or {}).get("path")
        want = os.path.join(home, "fakebin", "adb")
        if used != want:
            self.quit(port, force=True)
            raise Stop("程序实际使用的 ADB 不是假 ADB：%s（期望 %s）" % (used, want))
        return st

    def servers(self):
        """本次解压出来的 .app 的后台服务。启动器用相对路径 exec「python app.py」，命令行里没有
        .app 路径，所以按进程的工作目录（= .app/Contents/Resources）认。"""
        res = os.path.realpath(os.path.join(self.app, "Contents", "Resources"))
        out = []
        for pid, _, args in ps_rows():
            if "app.py" in args and "--app-mode" in args:
                cwd = proc_cwd(pid)
                if cwd and os.path.realpath(cwd) == res:
                    out.append((pid, args))
        return out

    def quit(self, port, force=False):
        try:
            return http(port, "/api/quit", {"force": True} if force else {})
        except Exception as exc:
            return {"error": str(exc)}


def wait(pred, timeout, step=0.2):
    t = time.time()
    while time.time() - t < timeout:
        try:
            v = pred()
            if v:
                return v
        except Exception:
            pass
        time.sleep(step)
    return None


# ---------------------------------------------------------------------------
def t0_package(c):
    say("== T0 安装包：哈希、解压到新目录、版本")
    sha = hashlib.sha256(open(c.a.zip, "rb").read()).hexdigest()
    if not check(sha == c.a.sha, "ZIP SHA-256 与交付值一致", sha):
        raise Stop("哈希不一致，停止")
    dest = os.path.dirname(c.app)
    if os.path.exists(dest):
        raise Stop("解压目标已存在，为避免覆盖而停止：%s" % dest)
    os.makedirs(dest)
    if os.path.exists("/usr/bin/ditto"):
        r = subprocess.run(["/usr/bin/ditto", "-x", "-k", c.a.zip, dest], capture_output=True, text=True)
        rc = r.returncode
    else:                                        # 仅 Linux 演练：没有 ditto
        with zipfile.ZipFile(c.a.zip) as z:
            z.extractall(dest)
            for i in z.infolist():
                os.chmod(os.path.join(dest, i.filename), (i.external_attr >> 16) or 0o644)
        rc = 0
    check(rc == 0 and os.path.isdir(c.app), "解压到新建的临时目录（含中文和空格）", dest)
    check(os.access(c.launcher, os.X_OK), "启动器有可执行权限")
    plist = plistlib.load(open(os.path.join(c.app, "Contents", "Info.plist"), "rb"))
    c.plist_version = plist.get("CFBundleShortVersionString")
    check(c.plist_version == c.a.version, "Info.plist 版本", c.plist_version)
    if os.path.exists("/usr/bin/xattr"):
        q = subprocess.run(["/usr/bin/xattr", "-p", "com.apple.quarantine", c.app], capture_output=True, text=True)
        say("   隔离属性（只读查看，不修改）：%s" % (q.stdout.strip() or "无"))


def t1_start(c):
    say("== T1 启动（Terminal 环境下用最小 PATH 启动启动器；不是 Finder 双击）")
    home = c.make_home("h1-启动")
    w = c.verify_fake_adb(home)
    check(True, "假 ADB 绝对路径存在、可执行、自报为假", w)
    t = time.time()
    c.launch(home)
    port = c.wait_port(home)
    if not check(port, "启动成功并写出端口", "%.1f 秒，端口 %s" % (time.time() - t, port)):
        raise Stop("启动失败")
    st = c.adb_guard(home, port)
    check(True, "启动后核对：程序实际使用的 ADB = 假 ADB", (st.get("adb") or {}).get("path"))
    rt = st.get("runtime") or {}
    check(rt.get("pythonVersion"), "实际运行的 Python", "%s（%s）" % (rt.get("pythonVersion"), rt.get("python")))
    lg = open(log_file(home)).read() if os.path.exists(log_file(home)) else ""
    check("launcher: bundle=" in lg, "日志记录启动器选中的 Python",
          next((l for l in lg.splitlines() if "launcher:" in l), "")[-160:])
    check(os.path.exists(os.path.join(sup_dir(home), "instance.lock")), "数据目录在测试 HOME 内（锁文件、端口文件）",
          sup_dir(home))
    c.h1, c.p1 = home, port
    return home, port


def t2_single(c):
    say("== T2 单实例：同一个测试 HOME 下连续启动")
    home, port = c.h1, c.p1
    n0 = len(open(os.path.join(home, "browser.log")).read().splitlines())
    ps = [c.launch(home) for _ in range(5)]
    wait(lambda: all(p.poll() is not None for p in ps), 30)
    time.sleep(1)
    srv_h1 = c.servers()
    n1 = len(open(os.path.join(home, "browser.log")).read().splitlines())
    check(all(p.poll() is not None for p in ps), "再启动 5 次：新进程都把窗口交给已有实例后退出",
          "退出码 %s" % [p.returncode for p in ps])
    check(len(srv_h1) == 1, "后台服务仍只有 1 个", "PID %s" % [s[0] for s in srv_h1])
    check(n1 - n0 == 5, "每次启动都重新拉起窗口（记录到 %d 次）" % (n1 - n0))
    # 冷启动并发：新的测试 HOME，同时启动 5 个
    home2 = c.make_home("h2-并发")
    before = {s[0] for s in c.servers()}
    ps = [c.launch(home2) for _ in range(5)]
    port2 = c.wait_port(home2)
    c.adb_guard(home2, port2) if port2 else None
    time.sleep(4)
    new = [s for s in c.servers() if s[0] not in before]
    check(port2 and len(new) == 1, "冷启动时同时启动 5 个：只有 1 个后台服务", "新服务 PID %s" % [s[0] for s in new])
    c.quit(port2, force=True)
    wait(lambda: not [s for s in c.servers() if s[0] not in before], 10)


def t3_version(c):
    say("== T3 版本显示")
    st = http(c.p1, "/api/state")
    pg = http(c.p1, "/api/ping")
    check(pg.get("version") == st.get("version") == c.plist_version == c.a.version,
          "/api/ping = /api/state = Info.plist = 交付版本", "%s / %s / %s" % (pg.get("version"), st.get("version"),
                                                                     c.plist_version))
    marker = os.path.join(c.work, "UI_CHECK_URL")
    done = os.path.join(c.work, "UI_CHECK_DONE")
    with open(marker, "w") as f:
        f.write("http://127.0.0.1:%s/\n" % c.p1)
    say("   界面版本号：请在独立浏览器里打开 %s 的控制台查看；驱动等待 %s（最多 15 分钟）" % (open(marker).read().strip(), done))
    got = wait(lambda: os.path.exists(done), 900, step=1)
    note = open(done).read().strip() if got else "超时，未查看"
    check(got and note.startswith("ok"), "界面控制台显示的版本（人工/浏览器面板查看）", note)


def t4_extract_close(c):
    say("== T4 提取中关闭窗口：等待超过自动退出时限（25 秒）")
    home = c.make_home("h3-提取中关窗")
    os.makedirs(os.path.join(home, "dev", "data/app/com.termux-1"), exist_ok=True)
    shutil.copyfile(c.apks["termux"], os.path.join(home, "dev", "data/app/com.termux-1", "base.apk"))
    with open(os.path.join(home, "dev", ".hold_pull"), "w") as f:
        f.write(" pull \n0")
    c.launch(home)
    port = c.wait_port(home)
    if not port:
        raise Stop("T4 启动失败")
    c.p3 = port
    c.adb_guard(home, port)
    devs = lambda: [d for d in http(port, "/api/supervisor")["state"]["devices"] if d.get("state") == "device"]
    if not wait(devs, 30):
        raise Stop("T4 没看到模拟设备")
    # 模拟「窗口」：一个事件流连接（界面就是这样连着后台的）
    resp = urllib.request.urlopen("http://127.0.0.1:%s/api/events" % port, timeout=30)
    resp.readline()
    serial = devs()[0]["serial"]
    r = http(port, "/api/extract", {"serial": serial, "packages": ["com.termux"]})
    held = wait(lambda: os.path.exists(os.path.join(home, "dev", ".held_pull")), 30)
    check(r.get("ok") and held, "提取已开始并停在 adb pull 上", str(r))
    resp.close()                                            # 关窗口
    t_close = time.time()
    say("   已关闭窗口（断开事件流），开始等待 75 秒")
    alive_all, busy_seen = True, []
    while time.time() - t_close < 75:
        try:
            pg = http(port, "/api/ping", timeout=3)
            busy_seen.append(",".join(pg.get("busyKinds") or []))
        except Exception:
            alive_all = False
            break
        time.sleep(5)
    check(alive_all and all(b == "extract" for b in busy_seen),
          "关窗后 75 秒（超过 25 秒时限）进程仍在，一直报告提取中", "采样 %d 次：%s" % (len(busy_seen), set(busy_seen)))
    os.remove(os.path.join(home, "dev", ".hold_pull"))
    t_rel = time.time()
    out = os.path.join(home, "out", "提取APP")
    got = wait(lambda: any(f.endswith(".apk") for _, _, fs in os.walk(out) for f in fs), 30)
    check(got, "放行后提取完成，文件写在测试目录里", out)

    def gone():
        try:
            http(port, "/api/ping", timeout=2)
            return False
        except Exception:
            return True
    ex = wait(gone, 90, step=1)
    check(ex, "提取结束、没有窗口连着 → 自动退出", "放行后 %.0f 秒" % (time.time() - t_rel))
    c.h3 = home


def t5_quit(c):
    say("== T5 退出")
    r = c.quit(c.p1)
    gone = wait(lambda: not c.servers(), 15)
    check(r.get("ok") and gone, "点「退出」：后台进程结束", str(r))


def t6_upgrade(c, label, old_dir):
    say("== T6 从 %s 升级：队列、顺序、方案、设置保留（旧版数据在测试目录里临时构造）" % label)
    home = c.make_home("h4-升级自" + label)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    c.verify_fake_adb(home)
    env = c.env(home)
    po = subprocess.Popen([sys.executable, "app.py", "--port", str(port), "--no-browser"], cwd=old_dir, env=env,
                          stdout=open(os.path.join(home, "old-version.log"), "w"), stderr=subprocess.STDOUT)
    STARTED.append(po)
    if not wait(lambda: http(port, "/api/state", timeout=2), 30):
        raise Stop("旧版本 %s 启动失败" % label)
    st = http(port, "/api/state")
    if (st.get("adb") or {}).get("path") != env["APKMGR_ADB"]:
        po.terminate()
        raise Stop("旧版本实际用的 ADB 不是假 ADB：%s" % (st.get("adb") or {}).get("path"))
    time.sleep(1)
    for k in ("termux", "newpipe", "seal"):
        http(port, "/api/import", {"path": c.apks[k]})
    ids = [i["id"] for i in http(port, "/api/state")["items"]]
    http(port, "/api/queue/reorder", {"ids": ids[::-1]})
    http(port, "/api/profile/save", {"name": "升级前的方案"})
    http(port, "/api/settings", {"lang": "ja", "autoMark": False, "grantPermissions": True})
    before = http(port, "/api/state")
    po.terminate()
    po.wait(15)
    c.launch(home)
    nport = c.wait_port(home)
    if not nport:
        raise Stop("升级后新版本启动失败")
    c.adb_guard(home, nport)
    after = http(nport, "/api/state")
    bl, al = [i["label"] for i in before["items"]], [i["label"] for i in after["items"]]
    check(al == bl, "队列与顺序保留", " → ".join(al))
    check("升级前的方案" in (after.get("profiles") or {}), "顺序方案保留")
    s0, s1 = before["settings"], after["settings"]
    keys = ("lang", "autoMark", "grantPermissions", "extractDir")
    check(all(s1.get(k) == s0.get(k) for k in keys), "设置保留", ", ".join("%s=%s" % (k, s1.get(k)) for k in keys[:3]))
    check(after.get("version") == c.a.version, "升级后版本", after.get("version"))
    c.quit(nport, force=True)
    wait(lambda: not c.servers(), 15)


def cleanup(c):
    say("== 清理：只结束本次测试启动的进程")
    for p in STARTED:
        if p.poll() is None:
            p.terminate()
    time.sleep(2)
    for p in STARTED:
        if p.poll() is None:
            p.kill()
    for f in ("homes",):
        base = os.path.join(c.work, f)
        for dp, _, fs in os.walk(base):
            for n in fs:
                if n.startswith(".hold_"):
                    os.remove(os.path.join(dp, n))
    time.sleep(1)
    kit = os.path.dirname(c.work)                # 测试工具包目录：程序、假 ADB、旧版本源码都在里面
    keep = my_lineage()
    left = [(pid, args) for pid, _, args in ps_rows() if kit in args and pid not in keep] + \
        [(pid, args) for pid, args in c.servers() if pid not in keep]
    for pid, args in left:                       # 命令行里带本测试目录路径的，一定是本次测试启动的
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    time.sleep(1)
    left2 = [(pid, args[:160]) for pid, _, args in ps_rows() if kit in args and pid not in keep] + \
        [(pid, args[:160]) for pid, args in c.servers() if pid not in keep]
    check(not left2, "测试结束后，没有残留的测试进程", "清理前残留 %d 个，清理后 %d 个" % (len(left), len(left2)))
    others = [(pid, args[:120]) for pid, _, args in ps_rows()
              if ("app.py" in args and "--app-mode" in args or "/adb " in args or args.endswith("/adb"))
              and kit not in args and pid not in {p for p, _ in c.servers()}]
    say("   （只读记录）本测试之外的 APK Manager / adb 进程，未触碰：%s" % (others or "无"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--old14")
    ap.add_argument("--old150")
    ap.add_argument("--work", required=True)
    ap.add_argument("--dry-run-linux", action="store_true", help="只用于在 Linux 上演练驱动本身")
    a = ap.parse_args()
    if sys.platform != "darwin" and not a.dry_run_linux:
        print("这个驱动只在 macOS 上运行"); return 2
    os.makedirs(a.work, exist_ok=True)
    LOG_PATH[0] = os.path.join(a.work, "driver.log")
    c = Ctx(a)
    say("测试目录：%s" % a.work)
    say("驱动 Python：%s %s" % (sys.executable, sys.version.split()[0]))
    stopped = None
    try:
        t0_package(c)
        t1_start(c)
        t2_single(c)
        t3_version(c)
        t4_extract_close(c)
        t5_quit(c)
        for label, d in (("v1.4", a.old14), ("v1.5.0", a.old150)):
            if d:
                t6_upgrade(c, label, d)
    except Stop as e:
        stopped = str(e)
        check(False, "验收中止", stopped)
    except Exception as e:
        stopped = repr(e)
        check(False, "驱动异常", stopped)
    finally:
        try:
            cleanup(c)
        except Exception as e:
            say("清理出错：%r" % e)
        logs = os.path.join(a.work, "logs")
        os.makedirs(logs, exist_ok=True)
        hb = os.path.join(a.work, "homes")
        if os.path.isdir(hb):
            for h in sorted(os.listdir(hb)):
                hd = os.path.join(hb, h)
                for src, nm in ((log_file(hd), "app.log"), (os.path.join(hd, "adb-commands.log"), "adb-commands.log"),
                                (os.path.join(hd, "browser.log"), "browser.log"),
                                (os.path.join(hd, "old-version.log"), "old-version.log")):
                    if os.path.exists(src):
                        os.makedirs(os.path.join(logs, h), exist_ok=True)
                        shutil.copyfile(src, os.path.join(logs, h, nm))
        ok = sum(r["ok"] for r in RESULTS)
        say("===== macOS 隔离验收 %d / %d 项通过%s =====" % (ok, len(RESULTS), "（中止：%s）" % stopped if stopped else ""))
        with open(os.path.join(a.work, "results.json"), "w") as f:
            json.dump({"results": RESULTS, "stopped": stopped, "log": LOG}, f, ensure_ascii=False, indent=1)
        with open(os.path.join(a.work, "DONE"), "w") as f:
            f.write("%d/%d\n" % (ok, len(RESULTS)))
    return 0 if RESULTS and ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
