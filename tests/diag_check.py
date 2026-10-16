"""检查 tools/mac_diagnose.sh 真的是只读的。

做法：造一个假 HOME，把一个「只记录参数」的 adb 放在 Android Studio 默认位置，再放一个假 lsof
声称 5037 端口正在监听（也就是共享 adb 服务正在运行——最容易诱使脚本去问 adb 的情况）。
跑一遍诊断脚本，然后看这个 adb 收到过哪些命令。

只允许 `adb version`：它只打印客户端版本，不连接、不启动 adb 服务。
`adb devices` 之类的命令即使在服务运行时也不安全：服务恰好退出会被重新拉起；
客户端与服务版本不一致时会把共享服务换掉，影响其他软件。

用法：python3 tests/diag_check.py [脚本路径]
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "tools", "mac_diagnose.sh")
RESULTS = []


def check(cond, msg):
    RESULTS.append(bool(cond))
    print(("   ✓ " if cond else "   ✗ ") + msg)


def main():
    home = tempfile.mkdtemp(prefix="diag-home-")
    os.makedirs(os.path.join(home, "Desktop"))
    pt = os.path.join(home, "Library", "Android", "sdk", "platform-tools")
    os.makedirs(pt)
    adblog = os.path.join(home, "adb-calls.log")
    with open(os.path.join(pt, "adb"), "w") as f:
        f.write('#!/bin/bash\necho "$*" >> "%s"\n'
                '[ "$1" = version ] && echo "Android Debug Bridge version 1.0.41"\nexit 0\n' % adblog)
    os.chmod(os.path.join(pt, "adb"), 0o755)
    stub = os.path.join(home, "stubbin")
    os.makedirs(stub)
    with open(os.path.join(stub, "lsof"), "w") as f:     # 声称共享 adb 服务正在监听 5037
        f.write("#!/bin/bash\necho 'adb 4242 user 9u IPv4 0t0 TCP 127.0.0.1:5037 (LISTEN)'\nexit 0\n")
    os.chmod(os.path.join(stub, "lsof"), 0o755)

    print("\n[诊断脚本只读检查] %s" % SCRIPT)
    r = subprocess.run(["bash", SCRIPT], env={"HOME": home, "PATH": stub + ":/usr/bin:/bin"},
                       capture_output=True, text=True, timeout=60)
    calls = open(adblog).read().split("\n") if os.path.exists(adblog) else []
    calls = [c for c in calls if c.strip()]
    others = [c for c in calls if c.strip() != "version"]
    check(calls and not others, "5037 正在监听时，adb 只收到 `version`（收到：%s）" % (calls or "无"))
    out = r.stdout
    check("==== 5." in out and "==== 6." in out, "脚本完整跑完（rc=%s）" % r.returncode)
    saved = [f for f in os.listdir(os.path.join(home, "Desktop")) if f.startswith("APK-Manager-diagnose-")]
    check(saved, "结果已保存到桌面（%s）" % (saved[0] if saved else "无"))

    src = open(SCRIPT, encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    # 只看 shell 层面的命令（第 6 节里嵌着的 Python 读的是本程序缓存，里面的 "devices" 字段名不算）
    shell = re.sub(r"\"\$PYX\" -c '.*?'", "", code, flags=re.S)
    bad = re.findall(r"\b(kill-server|start-server|reconnect|tcpip|install|uninstall|pkill|killall|devices|"
                     r"connect|disconnect|launchctl\s+(?:setenv|unsetenv|load|unload))\b|\bkill\s+-\w", shell)
    bad = [b for b in bad if b]
    check(not bad, "脚本源码里没有可能改动状态的命令（找到：%s）" % (sorted(set(bad)) or "无"))

    ok = sum(RESULTS)
    print("\n===== 诊断脚本检查 %d / %d 项通过 =====" % (ok, len(RESULTS)))
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
