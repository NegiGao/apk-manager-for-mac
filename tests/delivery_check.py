"""对打包出来的 ZIP 做交付检查（在 Linux 上模拟 macOS 的 Finder 启动环境）。

不能代替真实 Mac 验收：这里没有 Finder、Gatekeeper、macOS 的 ps、Chrome 应用窗口。
能验证的是：ZIP 解压后的启动器与 Python 代码本身在「最小环境 + 中文空格路径 + 只读目录
+ 不同 Python 版本 + 旧版数据」下的行为。

用法：
    python3 tests/delivery_check.py --zip APK-Manager-mac-v1.5.1.zip --py39 /path/to/python3.9 \
        --old14 <v1.4 代码目录> --old150 <v1.5.0 代码目录>
"""
import argparse, hashlib, json, os, shutil, socket, stat, subprocess, sys, tempfile, time, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FAKE_ADB = os.path.join(HERE, "fakeadb", "adb")
sys.path.insert(0, HERE)
from harness import APKS  # noqa: E402

RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("   ✓ " if cond else "   ✗ ") + msg, flush=True)
    return cond


def http(port, path, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    rq = urllib.request.Request("http://127.0.0.1:%s%s" % (port, path), data=data,
                                headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(rq, timeout=timeout))


def wait_port(home, timeout=20):
    pf = os.path.join(home, ".apk-installer", "port")
    t = time.time()
    while time.time() - t < timeout:
        try:
            p = open(pf).read().strip()
            if p.isdigit():
                http(p, "/api/ping", timeout=2)
                return p
        except Exception:
            pass
        time.sleep(0.1)
    return None


def finder_home(py=None):
    """造一个「Finder 视角」的 HOME：adb 放在 Android Studio 默认位置，Python 放在 pyenv 位置。"""
    home = tempfile.mkdtemp(prefix="home-")
    dev = os.path.join(home, "dev")
    os.makedirs(dev)
    pt = os.path.join(home, "Library", "Android", "sdk", "platform-tools")
    os.makedirs(pt)
    # 包一层：Finder 环境里没有 FAKE_* 变量，由这个脚本补上后再交给假 adb
    with open(os.path.join(pt, "adb"), "w") as f:
        f.write("#!/bin/bash\nexport FAKE_DEV_ROOT=%s FAKE_ADB_LOG=%s/adb.log\nexec %s \"$@\"\n"
                % (dev, home, FAKE_ADB))
    os.chmod(os.path.join(pt, "adb"), 0o755)
    if py:
        os.makedirs(os.path.join(home, ".pyenv", "shims"))
        os.symlink(py, os.path.join(home, ".pyenv", "shims", "python3"))
    sup = os.path.join(home, ".apk-installer")
    os.makedirs(sup)
    with open(os.path.join(sup, "browser"), "w") as f:     # 记住的浏览器 → 一个只记录调用的假浏览器
        f.write(os.path.join(home, "browser.sh"))
    with open(os.path.join(home, "browser.sh"), "w") as f:
        f.write("#!/bin/bash\necho \"$@\" >> %s/browser.log\n" % home)
    os.chmod(os.path.join(home, "browser.sh"), 0o755)
    return home


def launch_like_finder(app, home, extra_env=None):
    env = {"HOME": home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "zh_CN.UTF-8"}
    env.update(extra_env or {})
    return subprocess.Popen([os.path.join(app, "Contents", "MacOS", "launcher")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--py39")
    ap.add_argument("--old14")
    ap.add_argument("--old150")
    a = ap.parse_args()
    version = {}
    exec(open(os.path.join(REPO, "core", "version.py")).read(), version)
    VERSION = version["VERSION"]

    print("\n[D1] ZIP 本身")
    sha = hashlib.sha256(open(a.zip, "rb").read()).hexdigest()
    print("     SHA-256", sha)
    root = tempfile.mkdtemp(prefix="交付 检查 ")
    target = os.path.join(root, "下载的 软件")
    os.makedirs(target)
    with zipfile.ZipFile(a.zip) as z:
        z.extractall(target)
        modes = {i.filename: (i.external_attr >> 16) for i in z.infolist()}
    app = os.path.join(target, "APK Manager.app")
    launcher = os.path.join(app, "Contents", "MacOS", "launcher")
    lm = modes.get("APK Manager.app/Contents/MacOS/launcher", 0)
    check(lm & stat.S_IXUSR, "ZIP 里启动器带可执行权限（%o）" % lm)
    os.chmod(launcher, 0o755)        # Python 的 zipfile 解压不还原权限；Finder/ditto 会
    plist = open(os.path.join(app, "Contents", "Info.plist")).read()
    check("<string>%s</string>" % VERSION in plist, "Info.plist 版本 = core/version.py = %s" % VERSION)
    res = os.path.join(app, "Contents", "Resources")
    pycs = [f for f in os.listdir(os.path.join(res, "core", "__pycache__"))]
    check(any(".cpython-" in f for f in pycs), "带预编译字节码（%s）" % sorted({f.split(".")[1] for f in pycs}))
    check(all(os.path.exists(os.path.join(res, "core", f.split(".")[0] + ".py")) for f in pycs),
          "每个 .pyc 都有对应的 .py 源码可回退")

    print("\n[D2] Finder 式最小环境、中文空格路径：找不到可用 Python 时")
    home = finder_home(py=None)
    p = launch_like_finder(app, home, {"APKMGR_PYTHON": "/nonexistent"})
    rc = p.wait(20)
    logf = os.path.join(home, "Library", "Logs", "APK安装管家.log")
    log = open(logf).read() if os.path.exists(logf) else ""
    have_cands = [c for c in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3",
                              "/Library/Frameworks/Python.framework/Versions/Current/bin/python3")
                  if os.access(c, os.X_OK)]
    if have_cands:
        print("     （本机存在 %s，无法模拟「完全没有 Python」，跳过）" % have_cands)
    else:
        check(rc == 1 and "python=<none>" in log,
              "没有 Homebrew / python.org / pyenv 的 Python，且没有 xcode-select 时：不盲目执行 /usr/bin/python3，"
              "记日志并退出（rc=%s）" % rc)

    if a.py39:
        print("\n[D3] Finder 式最小环境、中文空格路径、只读 Resources、Python 3.9")
        home = finder_home(py=a.py39)
        for d, _, fs in os.walk(res):                 # 模拟装进 /Applications 后不可写
            os.chmod(d, 0o555)
        p = launch_like_finder(app, home)
        port = wait_port(home)
        check(port, "启动成功，端口 %s" % port)
        if port:
            st = http(port, "/api/state")
            rt = st.get("runtime", {})
            check(rt.get("pythonVersion", "").startswith("3.9"), "实际运行的 Python：%s（%s）" % (
                rt.get("pythonVersion"), rt.get("python")))
            check(st.get("version") == VERSION, "界面拿到的版本 = %s" % st.get("version"))
            check(st["adb"]["available"] and "Library/Android/sdk" in (st["adb"]["path"] or ""),
                  "PATH 里没有 adb 时，仍按绝对路径找到：%s" % st["adb"]["path"])
            check(not any("cpython-39" in f for f in os.listdir(os.path.join(res, "core", "__pycache__"))),
                  "目录只读：没有写入新的字节码，3.13 的 .pyc 被忽略，从源码运行")
            log = open(logf).read()
            check("launcher: bundle=" in log and "python=%s" % os.path.join(home, ".pyenv/shims/python3") in log,
                  "日志记录了启动器选中的 Python")
            # 再点一次：只拉起窗口，不起第二个服务
            n0 = len(open(os.path.join(home, "browser.log")).read().splitlines())
            p2 = launch_like_finder(app, home)
            p2.wait(15)
            n1 = len(open(os.path.join(home, "browser.log")).read().splitlines())
            check(p2.returncode == 0 and n1 == n0 + 1, "再次双击：重新打开窗口，没有第二个服务")
            # 关闭窗口 → 25 秒后自动退出
            req = urllib.request.urlopen("http://127.0.0.1:%s/api/events" % port, timeout=5)
            req.readline(); req.close()
            t0 = time.time()
            p.wait(60)
            check(p.returncode is not None, "关闭窗口后自动退出（约 %.0f 秒）" % (time.time() - t0))
        for d, _, fs in os.walk(res):
            os.chmod(d, 0o755)

    print("\n[D4] 安装中强制退出：退出前把当前项记为待核验，下次启动先核验")
    home = finder_home(py=a.py39 or sys.executable)
    open(os.path.join(home, "dev", ".install_delay"), "w").write("4")
    p = launch_like_finder(app, home)
    port = wait_port(home)
    http(port, "/api/import", {"path": APKS["termux"]})
    time.sleep(1.5)
    http(port, "/api/install", {"serial": "FAKE1234567890", "mode": "all"})
    time.sleep(1.2)
    r = http(port, "/api/quit", {})
    check(not r["ok"] and r.get("code") == "busy_install", "安装中点退出：默认拒绝，要求确认（%s）" % r.get("code"))
    http(port, "/api/quit", {"force": True})
    p.wait(10)
    q = {i["label"]: i for i in json.load(open(os.path.join(home, ".apk-installer", "queue.json")))}
    check(q["Termux"]["status"] == "pending_verify" and q["Termux"]["arg"] == "quit",
          "退出前已把正在装的那项记为「待核验」")
    orphan = subprocess.run(["bash", "-c", "ps -eo args | grep -c '[f]akeadb/adb -s FAKE1234567890 install'"],
                            capture_output=True, text=True).stdout.strip()
    print("     退出瞬间仍在运行的 adb install 进程：%s 个（这是本程序启动的 adb 客户端，退出后由系统接管直到装完）" % orphan)
    time.sleep(4)
    p = launch_like_finder(app, home)
    port = wait_port(home)
    t = time.time()
    while time.time() - t < 15:
        it = {i["label"]: i for i in http(port, "/api/state")["items"]}["Termux"]
        if it["status"] != "pending_verify":
            break
        time.sleep(0.3)
    check(it["status"] == "success" and it["code"] == "installed_verified",
          "下次启动后自动核验：%s / %s" % (it["status"], it["code"]))
    http(port, "/api/quit", {"force": True}); p.wait(10)

    for label, old in (("v1.4", a.old14), ("v1.5.0", a.old150)):
        if not old:
            continue
        print("\n[D5] 从 %s 升级：队列、顺序、方案、设置保留" % label)
        home = finder_home(py=sys.executable)
        env = dict(os.environ, HOME=home, APKMGR_ADB=os.path.join(home, "Library/Android/sdk/platform-tools/adb"))
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        po = subprocess.Popen([sys.executable, "app.py", "--port", str(port), "--no-browser"], cwd=old,
                              env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                http(port, "/api/state", timeout=2); break
            except Exception:
                time.sleep(0.1)
        time.sleep(1)
        for k in ("termux", "newpipe", "seal"):
            http(port, "/api/import", {"path": APKS[k]})
        ids = [i["id"] for i in http(port, "/api/state")["items"]]
        http(port, "/api/queue/reorder", {"ids": ids[::-1]})
        http(port, "/api/profile/save", {"name": "升级前的方案"})
        http(port, "/api/settings", {"lang": "ja", "autoMark": False, "grantPermissions": True})
        before = http(port, "/api/state")
        po.kill(); po.wait()
        p = launch_like_finder(app, home)
        nport = wait_port(home)
        after = http(nport, "/api/state")
        check([i["label"] for i in after["items"]] == [i["label"] for i in before["items"]],
              "队列与顺序保留：%s" % [i["label"] for i in after["items"]])
        check("升级前的方案" in after["profiles"], "顺序方案保留")
        s0, s1 = before["settings"], after["settings"]
        check(all(s1.get(k) == s0.get(k) for k in ("lang", "autoMark", "grantPermissions", "extractDir")),
              "设置保留（lang=%s autoMark=%s grant=%s）" % (s1.get("lang"), s1.get("autoMark"), s1.get("grantPermissions")))
        check(after.get("version") == VERSION, "升级后界面版本 %s" % after.get("version"))
        http(nport, "/api/quit", {"force": True}); p.wait(10)

    ok = sum(1 for r in RESULTS if r[0])
    print("\n===== 交付检查 %d / %d 项通过 =====" % (ok, len(RESULTS)))
    for good, msg in RESULTS:
        if not good:
            print("未通过：", msg)


if __name__ == "__main__":
    main()
