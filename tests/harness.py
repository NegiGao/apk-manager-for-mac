"""验收测试用的公共工具：起一个隔离的服务实例（独立 HOME、独立假设备、独立 adb 日志）。"""
import json, os, shutil, subprocess, sys, tempfile, threading, time, urllib.request, socket

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FAKE_ADB = os.path.join(HERE, "fakeadb", "adb")
# 被测程序代码目录（默认就是本仓库）。指向旧版本的检出目录，即可用同一套测试跑出「修复前」的结果
CODE = os.environ.get("APKMGR_TEST_CODE") or REPO
SC = os.environ.get("APKMGR_TEST_WORK") or os.path.join(tempfile.gettempdir(), "apkmgr-tests")
APK_DIR = os.environ.get("APKMGR_TEST_APKS") or os.path.join(HERE, "apks")
# 被测服务用哪个 Python 跑（默认就是跑测试的这个），可以用来在 3.9 上验收
SERVER_PY = os.environ.get("APKMGR_TEST_SERVER_PY") or sys.executable
# 证据目录：每个实例结束时把 adb 命令记录、服务日志、队列/设置快照拷过去
EVIDENCE = os.environ.get("APKMGR_TEST_EVIDENCE")
APKS = {k: os.path.join(APK_DIR, v) for k, v in
        {"termux": "termux.apk", "newpipe": "newpipe.apk", "seal": "seal.apk"}.items()}
for _p in APKS.values():
    if not os.path.exists(_p):
        raise SystemExit("缺少测试用 APK：%s\n先运行 tests/get_test_apks.sh 下载" % _p)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Inst(object):
    def __init__(self, name, env_extra=None, settings=None, args=None, code=None):
        self.root = os.path.join(SC, "t_" + name)
        shutil.rmtree(self.root, ignore_errors=True)
        self.home = os.path.join(self.root, "home")
        self.dev = os.path.join(self.root, "dev")
        self.adblog = os.path.join(self.root, "adb.log")
        os.makedirs(self.home); os.makedirs(self.dev)
        settings = dict({"extractDir": self.root}, **(settings or {}))   # 提取的文件留在实例目录里
        os.makedirs(os.path.join(self.home, ".apk-installer"), exist_ok=True)
        json.dump(settings, open(os.path.join(self.home, ".apk-installer", "settings.json"), "w"))
        self.port = free_port()
        self.B = "http://127.0.0.1:%d" % self.port
        env = dict(os.environ)
        env.update({"HOME": self.home, "APKMGR_ADB": FAKE_ADB,
                    "FAKE_DEV_ROOT": self.dev, "FAKE_ADB_LOG": self.adblog})
        env.update(env_extra or {})
        self.env = env
        self.name = name
        self.proc = subprocess.Popen([SERVER_PY, "app.py", "--port", str(self.port), "--no-browser"]
                                     + list(args or []),
                                     cwd=code or CODE, env=env, stdout=open(os.path.join(self.root, "srv.log"), "w"),
                                     stderr=subprocess.STDOUT)
        self.events = []
        for _ in range(400):
            try:
                self.get("/api/ping"); break
            except Exception:
                time.sleep(0.025)
        self._listen()

    # ---------------------------------------------------------------- 屏障
    def hold(self, name, regex, skip=0):
        """让第 skip+1 条匹配 regex 的 adb 命令停在执行前（命令已发出并记入日志）。"""
        for f in (".held_" + name, ".holdcount_" + name):
            try: os.remove(os.path.join(self.dev, f))
            except FileNotFoundError: pass
        self.ctl(".hold_" + name, "%s\n%d" % (regex, skip))

    def wait_held(self, name, timeout=30):
        p = os.path.join(self.dev, ".held_" + name)
        return self.wait(lambda: os.path.exists(p) and open(p).read(), timeout=timeout,
                         step=0.02, what="屏障 " + name)

    def release(self, name):
        self.ctl(".hold_" + name)

    # ---------------------------------------------------------------- HTTP
    def post(self, p, o=None, timeout=90):
        d = json.dumps(o or {}).encode()
        r = urllib.request.Request(self.B + p, data=d, headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(r, timeout=timeout))

    def get(self, p, timeout=30):
        return json.load(urllib.request.urlopen(self.B + p, timeout=timeout))

    def sup(self):
        return self.get("/api/supervisor")["state"]

    def _listen(self):
        def run():
            try:
                for l in urllib.request.urlopen(self.B + "/api/events", timeout=600):
                    s = l.decode().strip()
                    if s.startswith("data: "):
                        self.events.append(json.loads(s[6:]))
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()
        time.sleep(0.3)

    # ---------------------------------------------------------------- 等待 / 日志
    def wait(self, pred, timeout=30, step=0.1, what=""):
        t = time.time()
        while time.time() - t < timeout:
            try:
                v = pred()
                if v:
                    return v
            except Exception:
                pass
            time.sleep(step)
        raise AssertionError("超时等待: " + what)

    def adb_calls(self, since=0.0):
        out = []
        try:
            for line in open(self.adblog):
                ts, _, args = line.rstrip("\n").partition("\t")
                if float(ts) >= since:
                    out.append((float(ts), args))
        except FileNotFoundError:
            pass
        return out

    # ---------------------------------------------------------------- 假设备控制
    def ctl(self, name, content=None):
        p = os.path.join(self.dev, name)
        if content is None:
            try: os.remove(p)
            except FileNotFoundError: pass
        else:
            open(p, "w").write(content)

    def preinstall(self, key, pkg):
        d = os.path.join(self.dev, "data/app/%s-1" % pkg)
        os.makedirs(d, exist_ok=True)
        shutil.copyfile(APKS[key], os.path.join(d, "base.apk"))

    def close(self):
        try:
            for f in os.listdir(self.dev):          # 放开所有屏障，免得假 adb 进程挂着
                if f.startswith(".hold_"):
                    os.remove(os.path.join(self.dev, f))
        except Exception:
            pass
        try:
            self.proc.kill(); self.proc.wait(5)
        except Exception:
            pass
        if EVIDENCE:
            dst = os.path.join(EVIDENCE, self.name)
            os.makedirs(dst, exist_ok=True)
            for src, nm in ((self.adblog, "adb-commands.log"), (os.path.join(self.root, "srv.log"), "server.log"),
                            (os.path.join(self.home, ".apk-installer", "queue.json"), "queue.json"),
                            (os.path.join(self.home, ".apk-installer", "settings.json"), "settings.json")):
                if os.path.exists(src):
                    shutil.copyfile(src, os.path.join(dst, nm))
            with open(os.path.join(dst, "events.jsonl"), "w") as f:
                for e in self.events:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
