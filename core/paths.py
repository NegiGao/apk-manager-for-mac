# -*- coding: utf-8 -*-
"""程序用到的各个目录与文件位置。

单独成一个模块，是为了让启动路径上的代码（server）只付极小的导入代价，
不用把 engine / adbkit / zipfile 这些一起拖进来。
"""
import os
import sys

HOME = os.path.expanduser("~")
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 程序根目录

SUPPORT_DIR = os.path.join(HOME, "Library", "Application Support", "APK安装管家") \
    if sys.platform == "darwin" else os.path.join(HOME, ".apk-installer")

STAGING_DIR = os.path.join(SUPPORT_DIR, "staging")
ICON_DIR = os.path.join(SUPPORT_DIR, "icons")
PROFILE_FILE = os.path.join(SUPPORT_DIR, "profiles.json")
QUEUE_FILE = os.path.join(SUPPORT_DIR, "queue.json")
SETTINGS_FILE = os.path.join(SUPPORT_DIR, "settings.json")
LABEL_CACHE_FILE = os.path.join(SUPPORT_DIR, "label_cache.json")
PORT_FILE = os.path.join(SUPPORT_DIR, "port")
BROWSER_FILE = os.path.join(SUPPORT_DIR, "browser")   # 记住上次用的浏览器，省去探测


def _default_output_dir(app_dir):
    """提取文件的默认输出位置。
    打包成 .app 时不能往 bundle 内部写，改用 .app 旁边的目录；
    若 .app 装在 /Applications 这类位置，则用桌面。"""
    marker = ".app/Contents/Resources"
    norm = app_dir.replace(os.sep, "/")
    if norm.endswith(marker):
        bundle = app_dir[:-len(marker) + len(".app")]
        beside = os.path.dirname(bundle)
        desktop = os.path.join(HOME, "Desktop")
        if beside.startswith("/Applications") or not os.access(beside, os.W_OK):
            return desktop if os.path.isdir(desktop) else HOME
        return beside
    return app_dir


BASE_DIR = _default_output_dir(APP_DIR)        # 提取输出的默认位置


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p
