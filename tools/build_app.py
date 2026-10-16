#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 apkmgr 打包成 macOS 的 .app（无需 Xcode / py2app，纯文件组装）。"""
import os
import plistlib
import shutil
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)      # 仓库根目录
OUT = os.path.join(os.path.dirname(HERE), "build")
APP_NAME = "APK Manager"

sys.path.insert(0, HERE)
from make_icon import build_icns  # noqa: E402

def _read_version():
    ns = {}
    exec(open(os.path.join(SRC, "core", "version.py"), encoding="utf-8").read(), ns)
    return ns["VERSION"]


VERSION = _read_version()

LAUNCHER = r'''#!/bin/bash
# APK Manager —— .app 启动器
# 从 Finder 双击时 PATH 只有 /usr/bin:/bin:/usr/sbin:/sbin，所以这里只用绝对路径找 Python，
# 不依赖终端里的 PATH。找到后 exec 过去，挑端口、开窗口、单实例都由 Python 处理。
BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
RES="$BUNDLE/Contents/Resources"
LOGDIR="$HOME/Library/Logs"
LOG="$LOGDIR/APK安装管家.log"
mkdir -p "$LOGDIR"

PY=""
for c in \
  "$APKMGR_PYTHON" \
  /opt/homebrew/bin/python3 \
  /usr/local/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  "$HOME/.pyenv/shims/python3"
do
  [ -n "$c" ] && [ -x "$c" ] && PY="$c" && break
done
# /usr/bin/python3 在没装 Xcode 命令行工具时只是一个占位程序，运行它会弹安装框；
# 先确认命令行工具确实装了再用它。
if [ -z "$PY" ] && [ -x /usr/bin/python3 ] && /usr/bin/xcode-select -p >/dev/null 2>&1; then
  PY=/usr/bin/python3
fi

{ echo "[$(date '+%Y-%m-%d %H:%M:%S')] launcher: bundle=$BUNDLE python=${PY:-<none>}"; } >>"$LOG" 2>/dev/null

if [ -z "$PY" ]; then
  /usr/bin/osascript -e 'display alert "APK Manager: Python 3 not found / 未找到 Python 3 / Python 3 が見つかりません" message "Install one of / 任选一种安装 / いずれかをインストール:

• xcode-select --install   (Command Line Tools)
• brew install python
• python.org installer

Python 3.8+ is required." as critical' >/dev/null 2>&1
  exit 1
fi

cd "$RES" || exit 1
exec "$PY" app.py --app-mode >>"$LOG" 2>&1
'''



def build():
    app = os.path.join(OUT, APP_NAME + ".app")
    if os.path.isdir(app):
        shutil.rmtree(app)
    macos = os.path.join(app, "Contents", "MacOS")
    res = os.path.join(app, "Contents", "Resources")
    os.makedirs(macos)
    os.makedirs(res)

    # 代码
    for name in ("app.py", "README.md", "README.ja.md", "README.zh-CN.md", "LICENSE"):
        src = os.path.join(SRC, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(res, name))
    os.makedirs(os.path.join(res, "tools"), exist_ok=True)
    shutil.copy2(os.path.join(SRC, "tools", "mac_diagnose.sh"), os.path.join(res, "tools", "mac_diagnose.sh"))
    os.chmod(os.path.join(res, "tools", "mac_diagnose.sh"), 0o755)
    os.makedirs(os.path.join(res, "docs"), exist_ok=True)
    shutil.copy2(os.path.join(SRC, "docs", "MAC_ACCEPTANCE.md"), os.path.join(res, "docs", "MAC_ACCEPTANCE.md"))
    for folder in ("core", "web"):
        shutil.copytree(os.path.join(SRC, folder), os.path.join(res, folder),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # 预编译字节码，省掉每次启动的编译开销（bundle 目录通常不可写）
    import compileall
    compileall.compile_dir(os.path.join(res, "core"), quiet=1, force=True)
    compileall.compile_file(os.path.join(res, "app.py"), quiet=1, force=True)

    # 图标
    build_icns(os.path.join(res, "app.icns"))

    # 启动器
    launcher = os.path.join(macos, "launcher")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER)
    os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "local.apk.installer",
        "CFBundleExecutable": "launcher",
        "CFBundleIconFile": "app.icns",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "10.13",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHumanReadableCopyright": "本地运行，不联网上传任何数据",
    }
    with open(os.path.join(app, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump(info, f)

    with open(os.path.join(app, "Contents", "PkgInfo"), "w") as f:
        f.write("APPL????")
    return app


if __name__ == "__main__":
    print(build())
