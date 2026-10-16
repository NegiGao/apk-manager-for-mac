# macOS 隔离验收报告 · macOS 隔離受け入れ報告 · macOS isolated acceptance report — v1.5.3

**[中文](#中文) · [日本語](#日本語) · [English](#english)**

---

## 中文

### 范围与环境
- 日期：2026-10-16；真实 Mac（Apple Silicon，arm64）；**真机未参与**，只用假 ADB。
- 被测包：`APK-Manager-mac-v1.5.3.zip`（commit `c9e9ab3`），SHA-256 `429a0f47d838141945e12efcdfc031459a8936bdabfc85f746fe46a28e42121c`。
- 启动方式：测试驱动在「终端」里以最小 PATH 调用 `.app/Contents/MacOS/launcher`。**不是 Finder 双击，也不涉及 Gatekeeper。**
- 隔离：测试目录 `~/tmp/APKMgr 隔离验收/`；每个场景独立的临时 HOME（数据目录、日志、端口、锁、提取输出都在里面）；ADB 由 `APKMGR_ADB` 指向测试目录里的假 ADB，启动前后各核对一次；程序的「打开窗口」由 `APKMGR_BROWSER` 指向只记录参数的脚本；升级用的旧版数据由 v1.4 / v1.5.0 源码在测试目录里临时构造。没有改全局环境变量、没有清除隔离属性、没有关闭安全检查、没有接触共享 adb 服务。
- 实际使用的 Python：启动器选中 `/opt/homebrew/bin/python3`，运行时为 Python 3.12.4。

### 结果
**首轮（`work-20261016-195954`）：29 / 30。** 失败的 1 项是「退出」：该项复用了启动测试的实例，而那个实例在界面检查结束、窗口关闭后已按设计自动退出，所以「退出」本身并没有被测到（记为测试设计问题，不是程序故障）。

**退出专项补测（`work-T5-20261016-200701`）：7 / 7。** 「退出」「关窗」各用一个新实例重测。

| 项目 | 首轮 | 补测 |
|---|---|---|
| ZIP 哈希一致、ditto 解压到新目录（含中文和空格）、启动器可执行、Info.plist = 1.5.3 | ✅ | ✅ |
| 启动（0.3 秒出端口），启动后核对实际 ADB = 假 ADB | ✅ | ✅（补测实例同样核对） |
| 单实例：已运行时再启动 5 次 → 仍 1 个后台；冷启动同时 5 个 → 1 个 | ✅ | — |
| 版本：/api/ping = /api/state = Info.plist = 1.5.3；界面「ADB コンソール」显示 1.5.3 | ✅ | — |
| 提取中关窗：等待 75 秒（> 25 秒时限）仍在且报告提取中；放行后文件落在测试目录，2 秒后自动退出 | ✅ | — |
| 退出 | ❌（见上） | ✅ 0.4 秒后进程结束 |
| 空闲关窗 → 约 25 秒宽限后自动退出 | — | ✅ 31 秒 |
| 从 v1.4 / v1.5.0 升级：队列顺序、方案、设置保留，版本 1.5.3 | ✅ | — |
| 测试结束无残留测试进程 | ✅ | ✅ |

### 「关窗」证据分两类记录
- **模拟（驱动断开事件流连接）**：提取中关窗、空闲关窗（31 秒退出）、窗口开着时退出——以上「窗口」都是驱动用 `/api/events` 事件流连接模拟的。这三项是这一类的通过。
- **真实浏览器窗口**：**尚未验证。** 程序自己打开的浏览器窗口在本轮被指向记录脚本，没有出现真实 Chrome 窗口。唯一一次真实浏览器关闭是：用 Claude 桌面应用自带的浏览器面板（不是 Chrome）打开首轮实例的界面查看版本号，约 20:01:01 关闭该面板；首轮实例在 20:02:20 已经不在。这只是间接观察：没有记录退出时刻，也不是程序自己打开的窗口，不计为通过。

### 清理范围说明
首轮和补测时的驱动，清理逻辑还包含「命令行含测试目录路径即结束」。两轮在这一步都发现 0 个残留进程，所以实际没有按路径结束过任何进程。此后驱动已收紧（commit `234c48f`）：只结束驱动自己启动的进程，以及运行中按父进程链确认过的子进程；路径匹配只做只读核对。新驱动目前只在 Linux 上演练过（31 / 31），**尚未在 Mac 上重跑**。

### 尚未验证
Finder 双击启动与 Gatekeeper（需按实际交付渠道下载后验证）；真实浏览器窗口关窗；没有 Python 的 Mac；只读诊断脚本在真实 Mac 上运行；真机安装、暂停、取消、拔插、无线重连。

### 已登记的问题（暂不修改产品）
见 [KNOWN_ISSUES.md](../KNOWN_ISSUES.md)：KI-1 断开连接时日志里出现 `ConnectionResetError` 报错堆栈；KI-2 程序拉起浏览器后不回收已退出的子进程（僵尸进程，程序退出时才消失）。

---

## 日本語

### 範囲と環境
- 2026-10-16、実機の Mac（arm64）。**スマホは未使用**、代用 ADB のみ。
- 対象：`APK-Manager-mac-v1.5.3.zip`（commit `c9e9ab3`）、SHA-256 `429a0f47…121c`。
- 起動方法：テストドライバが「ターミナル」上で最小 PATH のまま `launcher` を実行。**Finder のダブルクリックでも Gatekeeper 経由でもありません。**
- 隔離：シナリオごとの一時 HOME、代用 ADB（起動前後に確認）、ブラウザは記録用スクリプト、旧版データはテストフォルダ内で作成。グローバル環境変数・隔離属性・セキュリティ設定・共有 adb サーバには触れていません。
- 使用 Python：`/opt/homebrew/bin/python3`（3.12.4）。

### 結果
**1 回目：29 / 30。** 失敗した「終了」は、起動テストのインスタンスを使い回したため。そのインスタンスは UI 確認後にウインドウが閉じられ、仕様どおり自動終了していたので、「終了」そのものは検証できていませんでした（テスト設計の問題）。
**「終了」の追加テスト：7 / 7。** 新しいインスタンスで「終了」（0.4 秒で終了）と「アイドル時にウインドウを閉じる」（31 秒後に自動終了）を確認。
抽出中にウインドウを閉じる（75 秒待っても存続、解放後 2 秒で終了）、単一インスタンス、バージョン表示 1.5.3、v1.4 / v1.5.0 からの更新でデータ保持、残存プロセスなし——いずれも合格。

### 「ウインドウを閉じる」の証拠は 2 種類に分けて記録
- **模擬（イベントストリームの切断）**：上記 3 項目はこの種類で合格。
- **実ブラウザのウインドウ**：**未検証。** アプリが開くウインドウは記録スクリプトに差し替えていました。唯一の実ブラウザでの閉じ操作は、Claude デスクトップアプリ内蔵のブラウザパネル（Chrome ではない）でバージョン確認後に閉じたもので、1 回目のインスタンスは 20:02:20 には終了済みでした。終了時刻は記録しておらず、間接的な観察なので合格には数えません。

### 後片付けの範囲
1 回目と追加テストの時点では「コマンドラインにテストフォルダのパスを含むものを終了」という処理が残っていましたが、どちらも該当 0 件で、実際には何も終了していません。その後ドライバを修正し（`234c48f`）、自分で起動したプロセスと、実行中に親プロセスの連鎖で確認した子プロセスだけを終了するようにしました。パス一致は読み取り専用の確認だけです。新しいドライバは Linux での予行（31 / 31）のみで、**Mac では未再実行**です。

### 未検証
Finder／Gatekeeper（実際の配布経路でダウンロードして確認予定）、実ブラウザでのウインドウ閉じ、Python のない Mac、診断スクリプトの実機実行、実機スマホでの操作。

### 登録済みの問題（製品は変更しない）
[KNOWN_ISSUES.md](../KNOWN_ISSUES.md) の KI-1（切断時のログに `ConnectionResetError`）、KI-2（ブラウザ起動後の終了済み子プロセスを回収しない）。

---

## English

### Scope and environment
- 2026-10-16, a real Mac (arm64). **No phone**; fake ADB only.
- Package: `APK-Manager-mac-v1.5.3.zip` (commit `c9e9ab3`), SHA-256 `429a0f47…121c`.
- Launch: the test driver ran `.app/Contents/MacOS/launcher` from Terminal with a minimal PATH. **Not a Finder double-click; Gatekeeper was not involved.**
- Isolation: per-scenario temporary HOME, fake ADB (checked before and after launch), browser replaced by a recorder script, old-version data built inside the test folder. No global environment variables, quarantine attributes, security settings or shared adb server were touched.
- Python used: `/opt/homebrew/bin/python3` (3.12.4).

### Results
**First run: 29 / 30.** The failure was "Quit": it reused the launch-test instance, which had already auto-quit (as designed) after its window closed following the UI check — so Quit itself was never exercised. A test-design issue, not an app fault.
**Quit re-test: 7 / 7.** On fresh instances: Quit (process gone after 0.4 s) and idle close-window (auto-quit after 31 s).
Close-window during extraction (still alive after 75 s, exits 2 s after release), single instance, version 1.5.3 shown, data kept when upgrading from v1.4 / v1.5.0, no leftover processes — all passed.

### Close-window evidence, kept separate
- **Simulated (driver drops its event-stream connection):** the three items above passed in this category.
- **Real browser window:** **not verified.** The app's own window launch was redirected to a recorder script. The only real browser close was the Claude desktop app's built-in browser pane (not Chrome), closed after the version check; the first-run instance was already gone at 20:02:20. Exit time wasn't recorded and it wasn't the app's own window, so it's an indirect observation, not a pass.

### Cleanup scope
Both Mac runs used a driver whose cleanup still included "end anything whose command line contains the test-folder path". It matched 0 processes both times, so nothing was ended that way. The driver has since been tightened (`234c48f`): it ends only processes it started and children confirmed via the parent-PID chain while running; the path match is now a read-only check. The new driver has only been dry-run on Linux (31 / 31) and **has not been re-run on the Mac yet**.

### Not yet verified
Finder / Gatekeeper (to be checked after downloading through the real delivery channel), closing a real browser window, a Mac without Python, the diagnostics script on a real Mac, and anything on a real phone.

### Registered issues (no product change for now)
See [KNOWN_ISSUES.md](../KNOWN_ISSUES.md): KI-1 `ConnectionResetError` tracebacks in the log on disconnect; KI-2 exited browser-launcher children are not reaped until the app exits.
