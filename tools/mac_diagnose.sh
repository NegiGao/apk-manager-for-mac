#!/bin/bash
# APK Manager —— macOS 只读诊断脚本 / 読み取り専用の診断スクリプト / read-only diagnostics
#
# 只读：不重启 adb、不启动 adb 服务、不连接 adb 服务、不结束任何进程、不安装/卸载 APK、不改任何设置。
# 对 adb 只执行 `adb version`（只打印客户端版本，不连接服务）。
# 読み取りのみ：adb の再起動・起動、プロセス終了、APK の操作、設定変更は一切しません。
# Read-only: never restarts or starts the adb server, ends no process, installs nothing.
#
# 用法 / Usage:   bash mac_diagnose.sh
# 结果同时打印到屏幕并保存到桌面 / 結果はデスクトップにも保存 / also saved to the Desktop.

OUT="$HOME/Desktop/APK-Manager-diagnose-$(date +%Y%m%d-%H%M%S).txt"
SUP="$HOME/Library/Application Support/APK安装管家"
LOG="$HOME/Library/Logs/APK安装管家.log"

{
sec() { printf '\n==== %s ====\n' "$1"; }

sec "1. macOS"
sw_vers 2>/dev/null
echo "arch: $(uname -m)"
echo "date: $(date)"

sec "2. App bundles found (Spotlight, read-only)"
APPS=$(mdfind "kMDItemCFBundleIdentifier == 'local.apk.installer'" 2>/dev/null)
[ -z "$APPS" ] && for c in "/Applications/APK Manager.app" "$HOME/Applications/APK Manager.app" \
    "$HOME/Downloads/APK Manager.app" "$HOME/Desktop/APK Manager.app"; do [ -d "$c" ] && APPS="$APPS
$c"; done
echo "$APPS" | while IFS= read -r a; do
  [ -z "$a" ] && continue
  echo "• $a"
  echo "    version: $(/usr/bin/defaults read "$a/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null)"
  echo "    quarantine: $(/usr/bin/xattr -p com.apple.quarantine "$a" 2>/dev/null || echo none)"
  echo "    writable: $([ -w "$a/Contents/Resources" ] && echo yes || echo no)"
  echo "    pyc tags: $(ls "$a/Contents/Resources/core/__pycache__" 2>/dev/null | sed -E 's/.*\.(cpython-[0-9]+)\..*/\1/' | sort -u | tr '\n' ' ')"
done

sec "3. Python candidates (same order as the launcher)"
PYX=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3 "$HOME/.pyenv/shims/python3"; do
  if [ -x "$c" ]; then echo "  $c -> $("$c" -c 'import sys;print(sys.version.split()[0])' 2>&1)"; [ -z "$PYX" ] && PYX="$c"
  else echo "  $c -> (none)"; fi
done
if /usr/bin/xcode-select -p >/dev/null 2>&1; then
  echo "  Command Line Tools: $(/usr/bin/xcode-select -p)"
  echo "  /usr/bin/python3 -> $(/usr/bin/python3 -c 'import sys;print(sys.version.split()[0])' 2>&1)"
  [ -z "$PYX" ] && PYX=/usr/bin/python3
else
  echo "  Command Line Tools: NOT installed (/usr/bin/python3 is only a stub; not executed here)"
fi
echo "  PATH seen by Finder-launched apps: $(launchctl getenv PATH 2>/dev/null || echo '(default) /usr/bin:/bin:/usr/sbin:/sbin')"

sec "4. adb binaries (version only; 'adb version' does not start the server)"
for c in "$SUP/platform-tools/adb" /opt/homebrew/bin/adb /usr/local/bin/adb \
         "$HOME/Library/Android/sdk/platform-tools/adb" "$HOME/platform-tools/adb"; do
  if [ -x "$c" ]; then echo "  $c"; "$c" version 2>&1 | head -2 | sed 's/^/      /'; fi
done

sec "5. adb server (port 5037) — process / port info only"
# 这里刻意不调用任何会连接 adb 服务的命令：即使服务正在运行也不安全——
# 服务恰好退出时会被重新拉起；客户端与服务版本不一致时会把共享服务换掉，影响其他软件。
# 设备列表看第 6 节：那是本程序自己的缓存，读取它不会碰 adb。
lsof -nP -iTCP:5037 -sTCP:LISTEN 2>/dev/null || echo "  nothing listening on 5037"
echo "  adb processes:"
ps -Ao pid=,ppid=,args= | grep -E '(^|[ /])adb( |$)' | grep -v grep | sed 's/^/    /'

sec "6. APK Manager processes (device list = the app's own cache)"
ps -Ao pid=,ppid=,etime=,args= | grep -E 'app\.py --app-mode|MacOS/launcher' | grep -v grep | sed 's/^/  /' || true
if [ -f "$SUP/port" ]; then
  P=$(cat "$SUP/port")
  echo "  port file: $P"
  echo "  ping: $(curl -s -m 2 "http://127.0.0.1:$P/api/ping" || echo 'no response')"
  STATE=$(curl -s -m 3 "http://127.0.0.1:$P/api/state" 2>/dev/null)
  if [ -z "$PYX" ]; then
    echo "  state (raw, no usable Python to format it):"; echo "$STATE" | head -c 3000; echo
  else
  echo "$STATE" | "$PYX" -c '
import json,sys
try:
    s=json.load(sys.stdin)
except Exception:
    print("  state: (unreadable)"); sys.exit()
sup=s.get("sup") or {}
print("  version:", s.get("version"), "| runtime:", s.get("runtime"))
print("  bgPaused:", sup.get("bgPaused"), "wifiPaused:", sup.get("wifiPaused"), "usbOnly:", sup.get("usbOnly"))
print("  scheduler threads:", sup.get("threads"))
print("  tasks:", {k:v.get("state") for k,v in (sup.get("tasks") or {}).items()})
for d in sup.get("devices") or []:
    print("  device:", d.get("serial"), d.get("state"), "wireless" if d.get("wireless") else "usb",
          "physical=%s" % d.get("physical"), "origin=%s" % d.get("origin", "-"))
for p in ((sup.get("server") or {}).get("processes") or []):
    print("  adb process as seen by the app:", p.get("pid"), p.get("owner"), p.get("args")[:80])
j=s.get("job") or {}
if j: print("  job:", {k:j.get(k) for k in ("running","paused","pauseReason","serial","remaining","pending")})
' 2>/dev/null || true
  fi
else
  echo "  no port file (app not running)"
fi

sec "7. Saved state (sizes only, no contents)"
ls -la "$SUP" 2>/dev/null | sed 's/^/  /'

sec "8. Last 60 log lines"
tail -n 60 "$LOG" 2>/dev/null || echo "  (no log yet)"
} 2>&1 | tee "$OUT"

echo
echo "Saved to / 已保存到 / 保存先: $OUT"
