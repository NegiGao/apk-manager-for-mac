# Known issues · 已知问题 · 既知の問題

| ID | 现象 / 現象 / Symptom | 影响 / 影響 / Impact | 发现于 / 発見 / Found | 状态 / 状態 / Status |
|---|---|---|---|---|
| KI-1 | 界面窗口（事件流连接）断开时，日志里出现 `ConnectionResetError: [Errno 54]` 报错堆栈（来自 Python `http.server`）。<br>UI のイベントストリームが切れたとき、ログに `ConnectionResetError` のトレースバックが出る。<br>When the UI's event stream disconnects, the log shows a `ConnectionResetError` traceback from Python's `http.server`. | 只是日志噪音，功能不受影响。<br>ログのノイズのみ。<br>Log noise only; no functional effect. | v1.5.3 macOS 隔离验收（h1、h3、h6 实例日志）<br>v1.5.3 macOS isolated acceptance (logs of instances h1, h3, h6) | 已登记，暂不修改<br>登録済み・未対応<br>Registered, not fixed |
| KI-2 | 程序用 `posix_spawn` 拉起浏览器后不回收已退出的子进程，进程表里会留下僵尸进程（`<defunct>`），程序退出时才消失。<br>ブラウザ起動用の子プロセスが終了しても回収されず、アプリ終了までゾンビとして残る。<br>Browser-launcher children spawned with `posix_spawn` are not reaped; exited ones stay as zombies (`<defunct>`) until the app exits. | 不占资源，不影响功能；每次重新打开窗口会多一个，直到程序退出。<br>資源はほぼ使わず、機能への影響なし。<br>Negligible resources, no functional effect; one more per window reopen until the app exits. | v1.5.3 测试驱动 Linux 演练；macOS 上尚未核对<br>v1.5.3 driver dry run on Linux; not yet checked on macOS | 已登记，暂不修改<br>登録済み・未対応<br>Registered, not fixed |
