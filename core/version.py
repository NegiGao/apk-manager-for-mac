# -*- coding: utf-8 -*-
"""程序版本号的唯一来源：界面、/api/ping、.app 的 Info.plist 都从这里读。"""
import os

# APKMGR_TEST_VERSION 只给自动化测试用：让同一份代码扮演「较旧的版本」，测试版本接管逻辑
VERSION = os.environ.get("APKMGR_TEST_VERSION") or "1.5.5"
