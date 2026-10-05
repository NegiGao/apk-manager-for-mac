#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APK 安装管家 —— Mac 上的安卓安装包批量安装 / 提取工具。

用法:
    python3 app.py              启动并自动打开浏览器界面
    python3 app.py --port 8765  指定端口
    python3 app.py --no-browser 不自动打开浏览器
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.server import serve  # noqa: E402


def _watchdog(engine, grace):
    """界面窗口关掉（没有任何页面连着）超过 grace 秒就退出，避免后台残留进程。
    正在安装 / 扫描 / 提取时不退出。"""
    start = time.time()
    while True:
        time.sleep(3)
        bus = engine.bus
        if not bus.ever_connected:
            if time.time() - start > 120:   # 两分钟都没人打开界面
                os._exit(0)
            continue
        busy = (engine.job and engine.job.get("running")) or \
               (engine.apps_scan and engine.apps_scan.get("running"))
        if busy or bus.viewers() > 0:
            continue
        if time.time() - bus.last_seen > grace:
            os._exit(0)


def main():
    ap = argparse.ArgumentParser(description="APK 安装管家")
    ap.add_argument("--port", type=int, default=8777, help="监听端口（默认 8777）")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--auto-quit", type=int, default=0,
                    help="界面关闭后 N 秒自动退出（.app 模式用，0 表示不退出）")
    args = ap.parse_args()

    try:
        httpd, url, boot = serve(args.port, not args.no_browser)
    except OSError:
        httpd, url, boot = serve(0, not args.no_browser)

    print("=" * 56)
    print("  APK 安装管家已启动")
    print("  界面地址: %s" % url)
    print("  关闭这个窗口即可退出程序")
    print("=" * 56)

    if args.auto_quit > 0:
        def later():
            engine = boot.wait(60)
            if engine:
                _watchdog(engine, args.auto_quit)
        threading.Thread(target=later, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == "__main__":
    main()
