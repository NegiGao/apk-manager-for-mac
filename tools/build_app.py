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

LAUNCHER = r'''#!/bin/bash
# APK 安装管家 —— .app 启动器
# 只做一件事：找到 python3 然后 exec 过去。挑端口、开窗口都交给 Python，
# 这样整个冷启动路径上只有一次解释器启动。
BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
RES="$BUNDLE/Contents/Resources"
LOG="$HOME/Library/Logs/APK安装管家.log"
mkdir -p "$HOME/Library/Logs"

# Homebrew 的 python3 排在前面：/usr/bin/python3 是 Xcode 命令行工具的转发壳，
# 每次启动都要多走一次 xcrun 查找，明显更慢。
PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "$c" ] && PY="$c" && break
done
if [ -z "$PY" ]; then
  osascript -e 'display alert "缺少 Python 3" message "请在「终端」里执行一次：xcode-select --install
装好后再打开本程序。" as critical'
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
        "CFBundleShortVersionString": "1.4",
        "CFBundleVersion": "1.4",
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
