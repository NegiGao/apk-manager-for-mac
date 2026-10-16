#!/bin/sh
# 下载验收测试用的 3 个真实开源 APK（GitHub Releases），放到 tests/apks/
set -e
cd "$(dirname "$0")"
mkdir -p apks
dl() { [ -s "apks/$2" ] || curl -fL --retry 3 -o "apks/$2" "$1"; }
dl "https://github.com/termux/termux-app/releases/download/v0.118.0/termux-app_v0.118.0+github-debug_arm64-v8a.apk" termux.apk
dl "https://github.com/TeamNewPipe/NewPipe/releases/download/v0.27.6/NewPipe_v0.27.6.apk" newpipe.apk
dl "https://github.com/JunkFood02/Seal/releases/download/v1.13.1/Seal-1.13.1-universal-release.apk" seal.apk
ls -l apks
