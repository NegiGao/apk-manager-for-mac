# Mac acceptance checklist · Mac 验收清单 · Mac 受け入れチェックリスト

**[中文](#中文) · [日本語](#日本語) · [English](#english)**

结果报告 / 結果報告 / Results: [docs/acceptance/macos-isolated-v1.5.3.md](acceptance/macos-isolated-v1.5.3.md) · 已知问题 / 既知の問題 / Known issues: [KNOWN_ISSUES.md](KNOWN_ISSUES.md)

---

## 中文

自动化测试是在 Linux 上用假 adb 跑的，**不能代替真实 Mac 和真机验收**。这份清单就是补这一块。

开始前先跑一次只读诊断，把结果文件留着对照：

```bash
bash "/Applications/APK Manager.app/Contents/Resources/tools/mac_diagnose.sh"
# 或从仓库：bash tools/mac_diagnose.sh
```

诊断脚本只读：对 adb 只执行 `adb version`（不连接、不启动、不重启 adb 服务），不结束任何进程、不安装/卸载 APK、不改设置。设备列表取自本程序自己的缓存。结果同时存到桌面。

### A. 不需要手机（不会改动任何设备）

| # | 操作 | 期望 | 怎么核对 |
|---|---|---|---|
| A1 | 解压 ZIP，**在 Finder 里双击** `APK Manager.app`（第一次右键→打开） | 窗口出现 | 诊断第 6 节有 `app.py --app-mode` 进程 |
| A2 | 看实际用的是哪个 Python | 是你预期的那个，版本 ≥ 3.8 | 控制台「ADB 服务」卡片的「程序版本」一行；日志里 `launcher: python=` |
| A3 | 没有任何可用 Python 的机器（可选） | 弹出三语提示，说明三种安装方式 | 不会自己弹「安装命令行工具」框 |
| A4 | 把 .app 放进名字带中文和空格的文件夹（如 `~/下载 测试/`），再双击 | 正常启动 | 同 A1 |
| A5 | 连续快速双击 3 次 | 只有 1 个后台进程；窗口被重新拉起 | 诊断第 6 节只有 1 个 `app.py --app-mode` |
| A6 | 开两个窗口（再双击一次） | 控制台「后台调度线程」= 1 | 诊断第 6 节 `scheduler threads: 1` |
| A7 | 控制台显示的版本 = Finder「显示简介」里的版本 | 一致（1.5.4） | 诊断第 2 节 version 与第 6 节 version |
| A8 | 旧版运行中直接打开新版 | 1.5.2 之前的旧版：不自动关闭，弹提示请你手动退出；1.5.2 及以后：空闲时被接管，安装 / 读取列表 / 提取中继续用旧版 | 诊断第 6 节 version |
| A9 | 用新版覆盖旧版后打开 | 原来的队列、顺序、方案、设置都在 | 界面对照 |
| A10 | 关掉窗口，等 30 秒 | `app.py --app-mode` 进程消失；adb 服务（如有）仍在，这是正常的共享服务 | 诊断第 5、6 节 |
| A11 | 点「退出」 | 后台进程立即消失；adb 服务不受影响 | 同上 |
| A12 | 有其他程序（Android Studio、scrcpy 等）在用 adb 时打开本程序 | 控制台把它们标为「adb 服务（由另一个 adb 启动）」或「外部／未知」，不报冲突；本程序不结束它们 | 控制台「ADB 服务」卡片；诊断第 5 节对照 PID |

### B. 需要一台**测试用**安卓手机（会往手机上装/卸应用，请勿用工作手机）

| # | 操作 | 期望 |
|---|---|---|
| B1 | USB 连上，队列放 3 个 APK，「按顺序安装」 | 每项显示「安装成功 · 已核验」 |
| B2 | 安装中点「暂停后台并等待」 | 当前那个装完，记为「待核验」，不开始下一项；控制台原始日志里暂停后没有新命令 |
| B3 | 点「恢复后台」 | 「待核验」先被核验成成功；**不会**自己继续装 |
| B4 | 点「继续安装」 | 只装剩下的 |
| B5 | 安装中拔线 | 队列暂停，原因「目标设备断开」；插回后不自动继续 |
| B6 | 安装中点「取消当前」 | 显示真实结果：没装上 / 实际已装好 / 待核验（查不到时） |
| B7 | 「仅 USB」打开后再看原始日志 | 没有 `connect`、`tcpip` |
| B8 | 「暂停无线后台」后，若手机仍自己连上 Wi-Fi | 控制台标「不是本程序发起的连接（来源无法确定）」，摘要写「本程序的无线任务已暂停」 |

### 记录结果

每一项填：✅ 通过 / ❌ 不通过（附诊断文件和截图）/ — 未测。

---

## 日本語

自動テストは Linux 上で代用 adb を使って実行しています。**実機の Mac とスマホでの確認の代わりにはなりません。** このリストはその部分を補うためのものです。

まず読み取り専用の診断を 1 回実行し、結果ファイルを残してください：

```bash
bash "/Applications/APK Manager.app/Contents/Resources/tools/mac_diagnose.sh"
```

診断は読み取りのみです。adb は `adb version` だけを実行し（サーバへの接続・起動・再起動はしません）、プロセス終了、APK の操作、設定変更もしません。端末一覧は本アプリ自身のキャッシュから読みます。結果はデスクトップにも保存されます。

### A. スマホ不要（端末には一切触れません）

| # | 操作 | 期待される結果 | 確認方法 |
|---|---|---|---|
| A1 | ZIP を展開し **Finder でダブルクリック**（初回は右クリック→開く） | ウインドウが開く | 診断 6 に `app.py --app-mode` |
| A2 | 実際に使われた Python | 想定どおり、3.8 以上 | コンソール「ADB サーバ」の「アプリのバージョン」行、ログの `launcher: python=` |
| A3 | 使える Python がない Mac（任意） | 3 言語の案内が出る | 「コマンドラインツールのインストール」ダイアログが勝手に出ない |
| A4 | 日本語・空白を含むフォルダに入れて起動 | 正常に起動 | A1 と同じ |
| A5 | 素早く 3 回ダブルクリック | バックグラウンドは 1 つだけ | 診断 6 の `app.py --app-mode` が 1 つ |
| A6 | ウインドウを 2 つ開く | スケジューラスレッド = 1 | 診断 6 の `scheduler threads: 1` |
| A7 | コンソールのバージョン = Finder「情報を見る」のバージョン | 一致（1.5.4） | 診断 2 と 6 |
| A8 | 旧版が動いている状態で新版を開く | 1.5.2 より前の旧版：自動では終了せず、手動で終了するよう案内。1.5.2 以降：待機中なら交代、インストール・一覧読み込み・抽出中は旧版を使い続ける | 診断 6 |
| A9 | 旧版を上書きして開く | 一覧・順番・プリセット・設定が残っている | 画面で確認 |
| A10 | ウインドウを閉じて 30 秒待つ | `app.py --app-mode` が消える。adb サーバ（あれば）は残る（共有サーバなので正常） | 診断 5・6 |
| A11 | 「終了」を押す | すぐに消える。adb サーバには影響なし | 同上 |
| A12 | 他のソフト（Android Studio、scrcpy など）が adb を使っている状態で開く | 「adb サーバ（別の adb が起動）」または「外部／不明」と表示、競合扱いしない、終了させない | コンソール「ADB サーバ」、診断 5 の PID と照合 |

### B. **テスト用**の Android 端末が必要（アプリのインストール・削除を行います。業務用端末は使わないでください）

| # | 操作 | 期待される結果 |
|---|---|---|
| B1 | USB で接続し 3 件を「この順番でインストール」 | 各項目「インストール完了 · 確認済み」 |
| B2 | インストール中に「バックグラウンドを止めて待機」 | 実行中の 1 件は完了し「確認待ち」、次は始めない。生ログに停止後のコマンドなし |
| B3 | 「バックグラウンドを再開」 | 確認待ちが先に確認され成功に。自動ではインストールを再開しない |
| B4 | 「続きをインストール」 | 残りだけ入る |
| B5 | インストール中にケーブルを抜く | キューが一時停止（対象端末が切断）。挿し直しても自動再開しない |
| B6 | インストール中に「実行中を取り消す」 | 実際の結果を表示：入っていない／実は入った／確認待ち |
| B7 | 「USB のみ」をオンにして生ログを見る | `connect`・`tcpip` がない |
| B8 | 「無線バックグラウンドを停止」後もスマホが Wi-Fi でつながった場合 | 「本アプリが接続したものではありません（接続元は不明）」と表示 |

記録：✅ 合格 / ❌ 不合格（診断ファイルとスクリーンショットを添付）/ — 未実施。

---

## English

The automated tests run on Linux against a fake adb. **They do not replace checks on a real Mac and a real phone** — that's what this list is for.

Run the read-only diagnostics once first and keep the output file:

```bash
bash "/Applications/APK Manager.app/Contents/Resources/tools/mac_diagnose.sh"
```

It is read-only: the only adb command it runs is `adb version` (it never connects to, starts or restarts the adb server), it ends no process, installs nothing and changes no settings. The device list comes from the app's own cache. The output is also saved to the Desktop.

### A. No phone needed (touches no device)

| # | Do | Expect | Check |
|---|---|---|---|
| A1 | Unzip and **double-click in Finder** (first time: right-click → Open) | Window opens | Diagnostics §6 shows `app.py --app-mode` |
| A2 | Which Python is actually used | The one you expect, 3.8+ | Console "App version" line; log `launcher: python=` |
| A3 | On a Mac with no usable Python (optional) | Trilingual alert listing three ways to install | No surprise "install Command Line Tools" dialog |
| A4 | Put the .app in a folder whose name has CJK characters and spaces | Starts normally | As A1 |
| A5 | Double-click three times quickly | One background process; window re-opened | §6 has a single `app.py --app-mode` |
| A6 | Open two windows | Scheduler threads = 1 | §6 `scheduler threads: 1` |
| A7 | Console version = Finder "Get Info" version | Same (1.5.4) | §2 vs §6 |
| A8 | Open the new version while the old one is running | Older than 1.5.2: not closed; a note asks you to quit it. 1.5.2+: replaced when idle; kept while installing, loading the app list or extracting | §6 version |
| A9 | Replace the old app and open | Queue, order, saved orders and settings are kept | UI |
| A10 | Close the window, wait 30 s | `app.py --app-mode` is gone; the adb server (if any) stays — it's a shared daemon | §5, §6 |
| A11 | Press Quit | Gone immediately; adb server untouched | Same |
| A12 | Open while another tool (Android Studio, scrcpy…) uses adb | Shown as "adb server (started by another adb)" or "external / unknown", never as a conflict; not terminated | Console "ADB server"; match PIDs with §5 |

### B. Needs a **test** Android phone (installs/uninstalls apps — don't use a work phone)

| # | Do | Expect |
|---|---|---|
| B1 | USB, three APKs, Install in order | Each shows "Installed · verified" |
| B2 | Pause background & wait during an install | Current one finishes as "awaiting verification"; nothing new starts; raw log shows no commands after the pause |
| B3 | Resume background | Pending item is verified first; installing does **not** resume on its own |
| B4 | Continue | Only the remaining ones are installed |
| B5 | Unplug mid-install | Queue pauses (target disconnected); replugging doesn't resume it |
| B6 | Cancel current during an install | Shows the real outcome: not installed / actually installed / awaiting verification |
| B7 | Turn on USB only, check the raw log | No `connect`, no `tcpip` |
| B8 | After pausing the wireless background, if the phone still connects over Wi-Fi | Marked "not connected by this app (origin unknown)" |

Record each as ✅ pass / ❌ fail (attach diagnostics + screenshot) / — not tested.
