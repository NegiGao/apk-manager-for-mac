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
export LC_ALL=zh_CN.UTF-8 2>/dev/null
BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
RES="$BUNDLE/Contents/Resources"
SUPPORT="$HOME/Library/Application Support/APK安装管家"
LOGDIR="$HOME/Library/Logs"
LOG="$LOGDIR/APK安装管家.log"
mkdir -p "$SUPPORT" "$LOGDIR"

BROWSERS=(
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
  "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"
  "/Applications/Chromium.app/Contents/MacOS/Chromium"
)

launch_browser() {   # $1=可执行文件 $2=网址
  "$1" --app="$2" --window-size=1280,880 \
       --no-first-run --no-default-browser-check >/dev/null 2>&1 &
}

open_window() {
  local url="$1" b
  # 第一轮：优先用「已经在运行」的浏览器，窗口瞬间就出来，不用冷启动
  for b in "${BROWSERS[@]}"; do
    if [ -x "$b" ] && pgrep -x "$(basename "$b")" >/dev/null 2>&1; then
      launch_browser "$b" "$url"; return 0
    fi
  done
  # 第二轮：装了但没开，冷启一个应用窗口
  for b in "${BROWSERS[@]}"; do
    if [ -x "$b" ]; then launch_browser "$b" "$url"; return 0; fi
  done
  # 都没有就交给默认浏览器
  open "$url" >/dev/null 2>&1
}

# 已经在运行就只把窗口重新打开
if [ -f "$SUPPORT/port" ]; then
  OLD=$(cat "$SUPPORT/port" 2>/dev/null)
  if [ -n "$OLD" ] && curl -s -o /dev/null -m 1 "http://127.0.0.1:$OLD/api/ping"; then
    open_window "http://127.0.0.1:$OLD/"
    exit 0
  fi
fi

PY=""
for c in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  [ -x "$c" ] && PY="$c" && break
done
[ -z "$PY" ] && command -v python3 >/dev/null 2>&1 && PY="$(command -v python3)"
if [ -z "$PY" ]; then
  osascript -e 'display alert "缺少 Python 3" message "请在「终端」里执行一次：xcode-select --install
装好后再打开本程序。" as critical'
  exit 1
fi

PORT=$("$PY" -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));p=s.getsockname()[1];s.close();print(p)')
echo "$PORT" > "$SUPPORT/port"
cd "$RES" || exit 1
"$PY" app.py --port "$PORT" --no-browser --auto-quit 25 >>"$LOG" 2>&1 &
SRV=$!

URL="http://127.0.0.1:$PORT/"
# 用 bash 内建的 /dev/tcp 探测，不 fork curl；端口一通立刻开窗
for i in $(seq 1 200); do
  (exec 3<>/dev/tcp/127.0.0.1/$PORT) >/dev/null 2>&1 && break
  sleep 0.03
done
open_window "$URL"
wait $SRV
rm -f "$SUPPORT/port"
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
        "CFBundleShortVersionString": "1.3",
        "CFBundleVersion": "1.3",
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
