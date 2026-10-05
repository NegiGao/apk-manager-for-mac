"use strict";
/* 三语文案表：中文 / 日本語 / English */
const I18N = {
  zh: {
    appName: "APK 安装管家", appTag: "拖进来 · 排好序 · 一键按序安装",
    tabQueue: "安装队列", tabApps: "设备应用 / 提取", tabWireless: "无线连接", tabSettings: "设置",
    refresh: "刷新设备", quit: "退出", adbReady: "adb 已就绪", adbMissing: "未找到 adb",
    booting: "正在启动…", noDevice: "未检测到设备",

    dropMain: "把 APK 拖到这里", dropSub: "也可以从访达按 ⌥⌘C 复制路径，粘贴到下面的输入框",
    pathPlaceholder: "粘贴 APK 文件或文件夹路径，回车导入（文件夹会整个扫描）",
    import: "导入", veilMain: "松手即可加入安装队列", veilSub: "支持 .apk / .xapk / .apks / .apkm",

    sort: "排序", sortCustom: "自定义（拖动调整）", sortLabel: "应用名", sortFile: "文件名",
    sortPackage: "包名", sortSize: "文件大小", sortVersion: "版本号", sortAdded: "添加时间",
    asc: "↑ 升序", desc: "↓ 降序",
    profilePlaceholder: "顺序方案…", profileLoad: "载入", profileSave: "保存当前顺序", profileDelete: "删除",
    mark: "标记已安装", installNew: "只装未安装/可更新", clear: "清空队列", stop: "停止",
    install: "按顺序安装", emptyQueue: "队列是空的 —— 把 APK 拖进来就行", logs: "安装日志",

    stPending: "待安装", stWaiting: "排队中", stInstalling: "正在安装…",
    insSame: "已安装 · 同版本 {v}", insUpdate: "已安装旧版 {v} · 可更新",
    insDown: "设备版本更高 {v}", insUnknown: "已安装 {v}", insNone: "设备上没装过",
    tagSplit: "分包 ×{n}", tagDup: "队列中有同包名", tagMinSdk: "需 Android API {n}+",
    uninstall: "卸载", removeFromQueue: "移出队列",

    scopeThird: "用户安装的应用", scopeSystem: "系统应用", scopeAll: "全部应用",
    scan: "读取设备应用列表", searchApps: "搜索应用名或包名", selectAll: "全选 / 反选",
    uninstallSel: "卸载选中 ({n})", extractSel: "提取选中 ({n})", openOut: "打开「提取APP」文件夹",
    extract: "提取", appsEmpty: "先连接安卓设备，然后点「读取设备应用列表」",
    appsEmptySub: "会显示你在手机上看到的真实应用名称",
    scanned: "已读取 {a}/{b}", scanReading: "共 {n} 个应用，正在读取真实名称…",

    wTitle: "无线连接（Wi-Fi 调试）",
    wIntro: "手机和这台 Mac 要在同一个 Wi-Fi 下。第一次用必须先配对，之后开着无线调试就能自动连上。",
    wStep1: "① 第一次使用：配对",
    wStep1Tip: "手机：开发者选项 → 无线调试 → 使用配对码配对设备。把那一屏显示的「IP 地址和端口」和「配对码」填进来。",
    wPairAddr: "配对用 IP:端口（如 192.168.1.9:37251）", wPairCode: "6 位配对码", wPair: "配对并连接",
    wStep2: "② 已配对过：直接连",
    wStep2Tip: "填无线调试主界面显示的「IP 地址和端口」，通常是 :5555 或 :3xxxx。",
    wConnAddr: "IP:端口（如 192.168.1.9:5555）", wConnect: "连接",
    wStep3: "③ 把现在插线的手机转成无线",
    wStep3Tip: "先用数据线连好并在上面选中它，点下面的按钮会自动读取手机 IP 并切到无线，之后就能拔线。",
    wSwitch: "USB 转无线", wHistory: "用过的地址", wForget: "删除", wDisconnectAll: "断开全部无线",
    wTagUSB: "USB", wTagWiFi: "无线", wDup: "同一台手机同时有 USB 和无线连接，装大包建议选 USB（更快）",
    wPairOk: "配对成功", wPairFail: "配对失败", wConnOk: "已连接 {t}", wConnFail: "连接失败",
    wSwitchOk: "已转为无线：{t}，现在可以拔掉数据线了", wSwitchFail: "转无线失败",
    wDisconnected: "已断开无线连接", wReconnected: "已自动重连无线设备 {t}",
    wNeedUsb: "请先在上方选中一台用数据线连着的设备",
    wSlowHint: "当前目标是无线连接，大安装包会比插线慢不少",

    setInstall: "安装选项", setReinstall: "覆盖安装已存在的应用（-r）",
    setDowngrade: "允许降级安装（-d）", setGrant: "安装时自动授予全部权限（-g）",
    setSkipSame: "设备上已是同版本或更新版本时跳过", setStopErr: "遇到失败就停止，不继续后面的",
    setAutoMark: "连接设备时自动标记队列里哪些已经装过",
    setUninstall: "卸载选项", setKeepData: "卸载时保留应用数据与缓存（-k，重装后数据还在）",
    setUninstallTip: "卸载会直接从设备上移除应用，无法撤销，操作前会再确认一次。",
    setWireless: "无线选项", setAutoReconnect: "启动时自动重连上次用过的无线设备",
    setNotify: "完成提示", setNotifyOn: "使用 macOS 通知中心提醒（每个安装完成 + 全部完成）",
    setSound: "全部完成时播放提示音",
    setOut: "提取输出位置", setOutTip: "提取的应用会放进这个目录下的「提取APP」文件夹，每个应用一个子文件夹。",
    save: "保存", setAdb: "adb 工具", adbPathPlaceholder: "手动指定 adb 可执行文件路径",
    adbUse: "使用这个", adbDownload: "自动下载 adb", language: "语言",

    tInstalled: "安装成功", tFailed: "安装失败：{name}", tSkipped: "已跳过",
    tAllDone: "全部安装完成", tQueueAdded: "已加入队列", tImported: "已导入",
    tImportFail: "导入失败", tAddFail: "加入失败", tNoApk: "没有可用的安装包",
    tNoApkSub: "只接受 .apk / .xapk / .apks / .apkm", tExpanding: "正在展开文件夹",
    tExpandingSub: "会把里面的安装包都找出来",
    tNoDevice: "没有选择设备", tNoDeviceSub: "插上安卓设备并打开 USB 调试，再点刷新",
    tQueueEmpty: "队列是空的", tQueueEmptySub: "先把 APK 拖进来",
    tCantStart: "无法开始", tStopping: "已请求停止", tStoppingSub: "当前这个装完就停",
    tDevDone: "设备检测完成", tDevFound: "已连接 {n} 台可用设备", tDevNone: "没有找到可用设备",
    tMarkDone: "标记完成", tMarkMsg: "队列中 {n} 个已装在这台设备上", tMarkUpd: "，其中 {n} 个可更新",
    tMarkFail: "标记失败", tNothingNew: "没有要装的",
    tNothingNewSub: "队列里的应用设备上都已是同版本或更高版本",
    tStartInstall: "开始安装", tStartInstallSub: "按顺序安装其中 {n} 个",
    tProfSaved: "方案已保存", tProfLoaded: "方案已载入", tProfLoadedSub: "{n} 个应用按原顺序排好",
    tProfMissing: "，{n} 个文件已不在原位置", tProfMissTitle: "有文件找不到了",
    tProfMissBody: "这些应用的安装包不在原来的位置，需要重新拖进来：",
    tSaveFail: "保存失败", tLoadFail: "载入失败", tSelectProfile: "先选一个方案",
    tUninstalled: "已卸载", tUninstallFail: "卸载失败", tUninstallStart: "开始卸载",
    tUninstallDone: "卸载完成 — 成功 {a} / {b}", tExtractStart: "开始提取",
    tExtractStartSub: "{n} 个应用，完成后会提示", tExtracting: "正在提取",
    tExtractDone: "提取完成", tExtractDoneSub: "{a}/{b} 个成功", tExtractSaved: "已保存到：{d}",
    tScanDone: "应用列表读取完成", tScanStopped: "已停止读取", tScanTotal: "共 {n} 个应用",
    tScanFail: "读取失败", tOpenFail: "打开失败", tOpenFailSub: "文件夹可能还不存在",
    tSetSaved: "设置已保存", tOutSaved: "输出目录已保存", tAdbSet: "已设置 adb",
    tAdbBad: "路径无效", tAdbReady: "adb 已就绪", tAdbReadySub: "现在可以连接设备了",
    tAdbFail: "下载失败", tFiles: "{n} 个文件",
    tProgress: "{d}/{t} · 成功 {o} · 失败 {f}", tProgressSkip: " · 跳过 {s}",
    tAllDoneLine: "全部完成 · {s} · 共用时 {sec} 秒", tPrepare: "准备安装 {n} 个应用…",
    tSummary: "成功 {o} · 失败 {f} · 跳过 {s}", tTook: "用时 {n} 秒",
    tDoneTitle: "安装完成 — {s}", tDoneBody: "共 {n} 个，用时 {sec} 秒。按你排的顺序依次执行：",
    tReading: "正在读取 {f}（{i}/{n}）", tAdded: "{n} 个成功", tAddedFail: "，{n} 个失败",
    tAddedSkip: "，忽略 {n} 个非安装包", tQuit: "退出 APK 安装管家？队列和顺序会保留，下次打开还在。",
    tQuitDone: "已退出，可以关掉这个窗口了。", tConfirmClear: "清空整个队列？",
    tConfirmDelProfile: "删除方案「{n}」？", tProfPrompt: "给这个安装顺序起个名字（换设备时可直接载入）：",
    tProfDefault: "我的安装顺序", tConfirmUn1: "确定从设备上卸载「{n}」？",
    tConfirmUnN: "确定卸载这 {n} 个应用？", tKeepNote: "（设置里开了保留数据）",
    tDataNote: "应用数据会一并删除。",

    cInstalled: "安装成功", cInstalledV: "安装成功 · v{v}",
    cAlreadyCurrent: "设备上已是同版本或更新版本（v{v}）",
    cFileMissing: "文件已不存在", cFileMissingFix: "重新拖入这个 APK",
    cAlreadyExists: "设备上已存在同包名应用", cAlreadyExistsFix: "勾选「覆盖安装」后重试",
    cDowngrade: "设备上的版本比这个包更新", cDowngradeFix: "勾选「允许降级」后重试",
    cSigMismatch: "签名与已安装版本不一致", cSigMismatchFix: "先卸载设备上的同名应用再装",
    cNoSpace: "设备存储空间不足", cNoSpaceFix: "清理设备空间后重试",
    cAbiMismatch: "APK 的 CPU 架构与设备不匹配", cAbiMismatchFix: "换一个对应架构的安装包",
    cNoCert: "安装包没有签名", cNoCertFix: "使用正式签名过的 APK",
    cBrokenApk: "安装包已损坏", cBrokenApkFix: "重新下载这个 APK",
    cOldSdk: "系统版本太低，不满足这个应用要求", cOldSdkFix: "换低版本安装包或升级系统",
    cUserRestricted: "手机拒绝了本次安装", cUserRestrictedFix: "在手机上允许「USB 安装」并保持屏幕解锁",
    cVerification: "设备的安装校验拦截了它", cVerificationFix: "关闭手机的「安装监控/应用校验」后重试",
    cTestOnly: "这是测试包(test-only)", cTestOnlyFix: "需要用 -t 方式安装或换正式包",
    cMissingLib: "缺少依赖的共享库", cMissingLibFix: "该应用可能需要 GMS 等组件",
    cInvalidApk: "安装包无效", cInvalidApkFix: "重新获取这个 APK",
    cUnauthorized: "设备未授权调试", cUnauthorizedFix: "在手机上点「允许 USB 调试」",
    cNoDevice: "没有检测到设备", cNoDeviceFix: "检查数据线与 USB 调试开关",
    cOffline: "设备连接掉线", cOfflineFix: "重新插拔数据线后刷新设备",
    cRejected: "安装被系统拒绝（{v}）", cRejectedFix: "可查看下方日志了解详情",
    cFailed: "安装失败", cFailedFix: "可查看下方日志了解详情",
    cAdbError: "adb 执行出错", cExecError: "执行出错",
    cUnOk: "已卸载", cUnOkKeep: "已卸载（保留了数据）", cUnNotFound: "设备上没有这个应用",
    cUnSystemApp: "系统不允许卸载它（可能是预装应用）", cUnPolicy: "设备管理策略禁止卸载",
    cUnFailed: "卸载失败",
    sUnauthorized: "未授权：请在手机上点「允许 USB 调试」",
    sOffline: "连接掉线：重新插拔数据线",
  },

  ja: {
    appName: "APK インストール管理", appTag: "ドラッグ → 並べ替え → 順番どおり一括インストール",
    tabQueue: "インストール待ち", tabApps: "端末のアプリ / 抽出", tabWireless: "ワイヤレス接続", tabSettings: "設定",
    refresh: "端末を再検出", quit: "終了", adbReady: "adb 準備完了", adbMissing: "adb が見つかりません",
    booting: "起動中…", noDevice: "端末が見つかりません",

    dropMain: "ここに APK をドラッグ", dropSub: "Finder で ⌥⌘C を押すとパスをコピーできます。下の欄に貼り付けてもOK",
    pathPlaceholder: "APK ファイルまたはフォルダのパスを貼り付けて Enter（フォルダは中身をすべて検索）",
    import: "読み込む", veilMain: "離すとインストール待ちに追加されます",
    veilSub: ".apk / .xapk / .apks / .apkm に対応",

    sort: "並べ替え", sortCustom: "手動（ドラッグで入れ替え）", sortLabel: "アプリ名", sortFile: "ファイル名",
    sortPackage: "パッケージ名", sortSize: "サイズ", sortVersion: "バージョン", sortAdded: "追加順",
    asc: "↑ 昇順", desc: "↓ 降順",
    profilePlaceholder: "並び順プリセット…", profileLoad: "読み込む", profileSave: "今の並び順を保存", profileDelete: "削除",
    mark: "インストール済みを確認", installNew: "未導入/更新のみ", clear: "すべて削除", stop: "停止",
    install: "この順番でインストール", emptyQueue: "まだ何もありません —— APK をドラッグしてください", logs: "ログ",

    stPending: "待機中", stWaiting: "順番待ち", stInstalling: "インストール中…",
    insSame: "導入済み · 同じ版 {v}", insUpdate: "旧版が導入済み {v} · 更新可",
    insDown: "端末の方が新しい {v}", insUnknown: "導入済み {v}", insNone: "未導入",
    tagSplit: "分割 ×{n}", tagDup: "同じパッケージが他にもあります", tagMinSdk: "Android API {n}+ が必要",
    uninstall: "アンインストール", removeFromQueue: "一覧から外す",

    scopeThird: "ユーザーが入れたアプリ", scopeSystem: "システムアプリ", scopeAll: "すべて",
    scan: "端末のアプリ一覧を読み込む", searchApps: "アプリ名・パッケージ名で検索", selectAll: "全選択 / 解除",
    uninstallSel: "選択をアンインストール ({n})", extractSel: "選択を抽出 ({n})", openOut: "「提取APP」フォルダを開く",
    extract: "抽出", appsEmpty: "Android 端末を接続してから「端末のアプリ一覧を読み込む」を押してください",
    appsEmptySub: "ホーム画面に表示される実際のアプリ名が出ます",
    scanned: "{a}/{b} 読み込み済み", scanReading: "全 {n} 件、アプリ名を読み取り中…",

    wTitle: "ワイヤレス接続（Wi-Fi デバッグ）",
    wIntro: "スマホとこの Mac を同じ Wi-Fi につないでください。初回のみペア設定が必要で、以降は自動で接続されます。",
    wStep1: "① 初回：ペア設定",
    wStep1Tip: "スマホ：開発者向けオプション → ワイヤレスデバッグ → ペア設定コードによるデバイスのペア設定。表示される「IP アドレスとポート」と「ペア設定コード」を入力します。",
    wPairAddr: "ペア用 IP:ポート（例 192.168.1.9:37251）", wPairCode: "6 桁のコード", wPair: "ペア設定して接続",
    wStep2: "② ペア済み：そのまま接続",
    wStep2Tip: "ワイヤレスデバッグ画面に出ている「IP アドレスとポート」を入力してください（:5555 や :3xxxx）。",
    wConnAddr: "IP:ポート（例 192.168.1.9:5555）", wConnect: "接続",
    wStep3: "③ USB 接続中の端末をワイヤレスに切り替える",
    wStep3Tip: "ケーブルでつないで上の一覧から選んだ状態で押すと、IP を自動取得してワイヤレスに切り替えます。その後ケーブルを抜けます。",
    wSwitch: "USB → ワイヤレス", wHistory: "使ったアドレス", wForget: "削除", wDisconnectAll: "すべて切断",
    wTagUSB: "USB", wTagWiFi: "無線",
    wDup: "同じ端末が USB と無線の両方でつながっています。大きい APK は USB の方が速いです",
    wPairOk: "ペア設定できました", wPairFail: "ペア設定に失敗", wConnOk: "{t} に接続しました", wConnFail: "接続できません",
    wSwitchOk: "ワイヤレスに切り替えました：{t}。ケーブルを抜いて大丈夫です", wSwitchFail: "切り替えに失敗",
    wDisconnected: "ワイヤレス接続を切断しました", wReconnected: "ワイヤレス端末 {t} に自動再接続しました",
    wNeedUsb: "先に上の一覧で USB 接続中の端末を選んでください",
    wSlowHint: "いまの接続はワイヤレスです。大きい APK はケーブル接続の方がかなり速くなります",

    setInstall: "インストール設定", setReinstall: "既存アプリに上書きインストール（-r）",
    setDowngrade: "ダウングレードを許可（-d）", setGrant: "権限をすべて自動付与（-g）",
    setSkipSame: "同じ版か新しい版が入っていればスキップ", setStopErr: "失敗したらそこで中断する",
    setAutoMark: "端末接続時に導入済みかどうかを自動判定する",
    setUninstall: "アンインストール設定", setKeepData: "データとキャッシュを残す（-k、入れ直しても残ります）",
    setUninstallTip: "アンインストールは取り消せません。実行前に確認ダイアログが出ます。",
    setWireless: "ワイヤレス設定", setAutoReconnect: "起動時に前回のワイヤレス端末へ自動再接続する",
    setNotify: "完了通知", setNotifyOn: "macOS の通知センターで知らせる（1 件ごと + 全体）",
    setSound: "全部終わったら音を鳴らす",
    setOut: "抽出先", setOutTip: "このフォルダの下に「提取APP」を作り、アプリごとにサブフォルダを作ります。",
    save: "保存", setAdb: "adb ツール", adbPathPlaceholder: "adb の実行ファイルのパスを指定",
    adbUse: "これを使う", adbDownload: "adb を自動ダウンロード", language: "言語",

    tInstalled: "インストール完了", tFailed: "失敗：{name}", tSkipped: "スキップしました",
    tAllDone: "すべて完了", tQueueAdded: "追加しました", tImported: "読み込みました",
    tImportFail: "読み込めません", tAddFail: "追加できません", tNoApk: "使える APK がありません",
    tNoApkSub: ".apk / .xapk / .apks / .apkm のみ対応", tExpanding: "フォルダを展開中",
    tExpandingSub: "中の APK をすべて探します",
    tNoDevice: "端末が選ばれていません", tNoDeviceSub: "USB デバッグを有効にして接続し、再検出してください",
    tQueueEmpty: "一覧が空です", tQueueEmptySub: "まず APK をドラッグしてください",
    tCantStart: "開始できません", tStopping: "停止します", tStoppingSub: "いま実行中の 1 件が終わったら止まります",
    tDevDone: "検出しました", tDevFound: "{n} 台の端末が使えます", tDevNone: "使える端末がありません",
    tMarkDone: "判定しました", tMarkMsg: "一覧のうち {n} 件がこの端末に入っています", tMarkUpd: "（うち {n} 件は更新可）",
    tMarkFail: "判定できません", tNothingNew: "入れるものがありません",
    tNothingNewSub: "どれも同じ版か新しい版が既に入っています",
    tStartInstall: "開始しました", tStartInstallSub: "{n} 件を順番にインストールします",
    tProfSaved: "保存しました", tProfLoaded: "読み込みました", tProfLoadedSub: "{n} 件を元の順番で並べました",
    tProfMissing: "（{n} 件は元の場所にありません）", tProfMissTitle: "見つからないファイルがあります",
    tProfMissBody: "次のアプリの APK が元の場所にありません。もう一度ドラッグしてください：",
    tSaveFail: "保存できません", tLoadFail: "読み込めません", tSelectProfile: "プリセットを選んでください",
    tUninstalled: "アンインストールしました", tUninstallFail: "アンインストール失敗", tUninstallStart: "開始しました",
    tUninstallDone: "アンインストール完了 — 成功 {a} / {b}", tExtractStart: "抽出を開始",
    tExtractStartSub: "{n} 件。終わったら通知します", tExtracting: "抽出中",
    tExtractDone: "抽出完了", tExtractDoneSub: "{a}/{b} 件成功", tExtractSaved: "保存先：{d}",
    tScanDone: "読み込み完了", tScanStopped: "停止しました", tScanTotal: "全 {n} 件",
    tScanFail: "読み込めません", tOpenFail: "開けません", tOpenFailSub: "フォルダがまだ無いかもしれません",
    tSetSaved: "保存しました", tOutSaved: "保存先を変更しました", tAdbSet: "adb を設定しました",
    tAdbBad: "パスが正しくありません", tAdbReady: "adb 準備完了", tAdbReadySub: "端末を接続できます",
    tAdbFail: "ダウンロード失敗", tFiles: "{n} ファイル",
    tProgress: "{d}/{t} · 成功 {o} · 失敗 {f}", tProgressSkip: " · スキップ {s}",
    tAllDoneLine: "すべて完了 · {s} · 所要 {sec} 秒", tPrepare: "{n} 件の準備中…",
    tSummary: "成功 {o} · 失敗 {f} · スキップ {s}", tTook: "{n} 秒",
    tDoneTitle: "完了 — {s}", tDoneBody: "全 {n} 件、所要 {sec} 秒。指定の順番で実行しました：",
    tReading: "{f} を読み込み中（{i}/{n}）", tAdded: "{n} 件成功", tAddedFail: "、{n} 件失敗",
    tAddedSkip: "、{n} 件は対象外", tQuit: "終了しますか？一覧と並び順は保存され、次回もそのままです。",
    tQuitDone: "終了しました。このウインドウは閉じて大丈夫です。", tConfirmClear: "一覧をすべて削除しますか？",
    tConfirmDelProfile: "プリセット「{n}」を削除しますか？", tProfPrompt: "この並び順に名前を付けてください（別の端末でそのまま使えます）：",
    tProfDefault: "インストール順", tConfirmUn1: "「{n}」を端末からアンインストールしますか？",
    tConfirmUnN: "{n} 件のアプリをアンインストールしますか？", tKeepNote: "（データを残す設定です）",
    tDataNote: "アプリのデータも削除されます。",

    cInstalled: "インストール完了", cInstalledV: "インストール完了 · v{v}",
    cAlreadyCurrent: "同じ版か新しい版が既に入っています（v{v}）",
    cFileMissing: "ファイルが見つかりません", cFileMissingFix: "もう一度ドラッグしてください",
    cAlreadyExists: "同じパッケージが既にあります", cAlreadyExistsFix: "「上書きインストール」をオンにして再試行",
    cDowngrade: "端末の版の方が新しいです", cDowngradeFix: "「ダウングレードを許可」をオンにして再試行",
    cSigMismatch: "署名が既存のアプリと一致しません", cSigMismatchFix: "端末側の同名アプリを先に削除してください",
    cNoSpace: "端末の空き容量が足りません", cNoSpaceFix: "空き容量を増やして再試行",
    cAbiMismatch: "CPU アーキテクチャが合いません", cAbiMismatchFix: "端末に合う APK を用意してください",
    cNoCert: "APK が署名されていません", cNoCertFix: "正式に署名された APK を使ってください",
    cBrokenApk: "APK が壊れています", cBrokenApkFix: "ダウンロードし直してください",
    cOldSdk: "OS のバージョンが要件を満たしません", cOldSdkFix: "古い版の APK を使うか OS を更新",
    cUserRestricted: "端末側で拒否されました", cUserRestrictedFix: "「USB 経由のインストール」を許可し、画面をロック解除したままに",
    cVerification: "端末のインストール検証にブロックされました", cVerificationFix: "「アプリの確認」を一時的に無効化して再試行",
    cTestOnly: "テスト専用（test-only）の APK です", cTestOnlyFix: "-t 付きインストールか正式版が必要です",
    cMissingLib: "必要な共有ライブラリがありません", cMissingLibFix: "GMS などの依存が必要かもしれません",
    cInvalidApk: "APK が無効です", cInvalidApkFix: "入手し直してください",
    cUnauthorized: "USB デバッグが許可されていません", cUnauthorizedFix: "スマホ側で「許可」をタップ",
    cNoDevice: "端末が見つかりません", cNoDeviceFix: "ケーブルと USB デバッグ設定を確認",
    cOffline: "接続が切れました", cOfflineFix: "ケーブルを挿し直して再検出",
    cRejected: "システムに拒否されました（{v}）", cRejectedFix: "下のログを確認してください",
    cFailed: "インストール失敗", cFailedFix: "下のログを確認してください",
    cAdbError: "adb の実行エラー", cExecError: "実行エラー",
    cUnOk: "アンインストールしました", cUnOkKeep: "アンインストールしました（データは保持）",
    cUnNotFound: "端末にこのアプリはありません",
    cUnSystemApp: "システムが削除を許可していません（プリインストール）", cUnPolicy: "管理ポリシーで禁止されています",
    cUnFailed: "アンインストール失敗",
    sUnauthorized: "未許可：スマホで「USB デバッグを許可」をタップ",
    sOffline: "切断：ケーブルを挿し直してください",
  },

  en: {
    appName: "APK Manager", appTag: "Drop · Reorder · Install in sequence",
    tabQueue: "Install queue", tabApps: "Device apps / Extract", tabWireless: "Wireless", tabSettings: "Settings",
    refresh: "Refresh devices", quit: "Quit", adbReady: "adb ready", adbMissing: "adb not found",
    booting: "Starting…", noDevice: "No device detected",

    dropMain: "Drop APK files here", dropSub: "Or copy a path in Finder with ⌥⌘C and paste it below",
    pathPlaceholder: "Paste an APK file or folder path and press Enter (folders are scanned)",
    import: "Import", veilMain: "Release to add to the install queue",
    veilSub: "Supports .apk / .xapk / .apks / .apkm",

    sort: "Sort", sortCustom: "Manual (drag to reorder)", sortLabel: "App name", sortFile: "File name",
    sortPackage: "Package", sortSize: "Size", sortVersion: "Version", sortAdded: "Date added",
    asc: "↑ Asc", desc: "↓ Desc",
    profilePlaceholder: "Saved orders…", profileLoad: "Load", profileSave: "Save current order", profileDelete: "Delete",
    mark: "Check installed", installNew: "Only new / upgradable", clear: "Clear queue", stop: "Stop",
    install: "Install in order", emptyQueue: "Queue is empty — drop some APKs in", logs: "Install log",

    stPending: "Pending", stWaiting: "Queued", stInstalling: "Installing…",
    insSame: "Installed · same version {v}", insUpdate: "Older version installed {v} · upgradable",
    insDown: "Device has newer {v}", insUnknown: "Installed {v}", insNone: "Not on device",
    tagSplit: "{n} splits", tagDup: "Duplicate package in queue", tagMinSdk: "Needs Android API {n}+",
    uninstall: "Uninstall", removeFromQueue: "Remove from queue",

    scopeThird: "User-installed apps", scopeSystem: "System apps", scopeAll: "All apps",
    scan: "Load device app list", searchApps: "Search name or package", selectAll: "Select / clear all",
    uninstallSel: "Uninstall selected ({n})", extractSel: "Extract selected ({n})", openOut: "Open the 提取APP folder",
    extract: "Extract", appsEmpty: "Connect an Android device, then press “Load device app list”",
    appsEmptySub: "Shows the real app names as they appear on the phone",
    scanned: "{a}/{b} read", scanReading: "{n} apps found, reading real names…",

    wTitle: "Wireless (Wi-Fi debugging)",
    wIntro: "Phone and Mac must be on the same Wi-Fi. Pair once; after that it reconnects on its own.",
    wStep1: "① First time: pair",
    wStep1Tip: "On the phone: Developer options → Wireless debugging → Pair device with pairing code. Enter the IP:port and the code shown there.",
    wPairAddr: "Pairing IP:port (e.g. 192.168.1.9:37251)", wPairCode: "6-digit code", wPair: "Pair and connect",
    wStep2: "② Already paired: just connect",
    wStep2Tip: "Use the IP:port shown on the Wireless debugging screen (usually :5555 or :3xxxx).",
    wConnAddr: "IP:port (e.g. 192.168.1.9:5555)", wConnect: "Connect",
    wStep3: "③ Switch the cabled phone to wireless",
    wStep3Tip: "Connect by USB, select it above, then press this. It reads the phone's IP and switches over, so you can unplug.",
    wSwitch: "USB → wireless", wHistory: "Recent addresses", wForget: "Remove", wDisconnectAll: "Disconnect all",
    wTagUSB: "USB", wTagWiFi: "Wi-Fi",
    wDup: "Same phone connected over both USB and Wi-Fi — pick USB for large APKs, it's much faster",
    wPairOk: "Paired", wPairFail: "Pairing failed", wConnOk: "Connected to {t}", wConnFail: "Could not connect",
    wSwitchOk: "Now wireless: {t} — you can unplug the cable", wSwitchFail: "Switch failed",
    wDisconnected: "Wireless connection closed", wReconnected: "Reconnected to {t}",
    wNeedUsb: "Select a USB-connected device above first",
    wSlowHint: "Target is a wireless connection — large APKs go much faster over USB",

    setInstall: "Install options", setReinstall: "Replace existing app (-r)",
    setDowngrade: "Allow downgrade (-d)", setGrant: "Grant all permissions on install (-g)",
    setSkipSame: "Skip when the device already has this version or newer", setStopErr: "Stop at the first failure",
    setAutoMark: "Check what's already installed when a device connects",
    setUninstall: "Uninstall options", setKeepData: "Keep app data and cache (-k)",
    setUninstallTip: "Uninstalling removes the app from the device and can't be undone. You'll be asked to confirm.",
    setWireless: "Wireless options", setAutoReconnect: "Reconnect to the last wireless device on startup",
    setNotify: "Notifications", setNotifyOn: "Use macOS Notification Center (per app + on completion)",
    setSound: "Play a sound when everything finishes",
    setOut: "Extraction output", setOutTip: "Extracted apps go into a 提取APP folder here, one subfolder per app.",
    save: "Save", setAdb: "adb tool", adbPathPlaceholder: "Path to the adb executable",
    adbUse: "Use this", adbDownload: "Download adb automatically", language: "Language",

    tInstalled: "Installed", tFailed: "Failed: {name}", tSkipped: "Skipped",
    tAllDone: "All installs finished", tQueueAdded: "Added to queue", tImported: "Imported",
    tImportFail: "Import failed", tAddFail: "Could not add", tNoApk: "No usable installer",
    tNoApkSub: "Only .apk / .xapk / .apks / .apkm", tExpanding: "Expanding folder",
    tExpandingSub: "Finding every installer inside",
    tNoDevice: "No device selected", tNoDeviceSub: "Plug in an Android device with USB debugging on, then refresh",
    tQueueEmpty: "Queue is empty", tQueueEmptySub: "Drop some APKs in first",
    tCantStart: "Can't start", tStopping: "Stopping", tStoppingSub: "Will stop after the current one",
    tDevDone: "Scan complete", tDevFound: "{n} device(s) ready", tDevNone: "No usable device found",
    tMarkDone: "Checked", tMarkMsg: "{n} of them are already on this device", tMarkUpd: ", {n} upgradable",
    tMarkFail: "Check failed", tNothingNew: "Nothing to install",
    tNothingNewSub: "The device already has the same or a newer version of everything",
    tStartInstall: "Started", tStartInstallSub: "Installing {n} of them in order",
    tProfSaved: "Order saved", tProfLoaded: "Order loaded", tProfLoadedSub: "{n} apps back in their original order",
    tProfMissing: ", {n} file(s) no longer at their original path", tProfMissTitle: "Some files are missing",
    tProfMissBody: "These APKs are no longer where they were — drop them in again:",
    tSaveFail: "Could not save", tLoadFail: "Could not load", tSelectProfile: "Pick a saved order first",
    tUninstalled: "Uninstalled", tUninstallFail: "Uninstall failed", tUninstallStart: "Uninstalling",
    tUninstallDone: "Uninstall done — {a} of {b} succeeded", tExtractStart: "Extraction started",
    tExtractStartSub: "{n} app(s); you'll get a notice when it's done", tExtracting: "Extracting",
    tExtractDone: "Extraction done", tExtractDoneSub: "{a}/{b} succeeded", tExtractSaved: "Saved to: {d}",
    tScanDone: "App list loaded", tScanStopped: "Stopped", tScanTotal: "{n} apps",
    tScanFail: "Could not read", tOpenFail: "Could not open", tOpenFailSub: "The folder may not exist yet",
    tSetSaved: "Saved", tOutSaved: "Output folder saved", tAdbSet: "adb set",
    tAdbBad: "Invalid path", tAdbReady: "adb ready", tAdbReadySub: "You can connect a device now",
    tAdbFail: "Download failed", tFiles: "{n} file(s)",
    tProgress: "{d}/{t} · {o} ok · {f} failed", tProgressSkip: " · {s} skipped",
    tAllDoneLine: "All done · {s} · {sec}s total", tPrepare: "Preparing {n} installs…",
    tSummary: "{o} succeeded · {f} failed · {s} skipped", tTook: "{n}s",
    tDoneTitle: "Finished — {s}", tDoneBody: "{n} apps in {sec}s, run in the order you set:",
    tReading: "Reading {f} ({i}/{n})", tAdded: "{n} added", tAddedFail: ", {n} failed",
    tAddedSkip: ", {n} ignored", tQuit: "Quit APK Manager? Your queue and order are kept for next time.",
    tQuitDone: "Stopped — you can close this window.", tConfirmClear: "Clear the whole queue?",
    tConfirmDelProfile: "Delete saved order “{n}”?", tProfPrompt: "Name this install order (loadable on another device):",
    tProfDefault: "My install order", tConfirmUn1: "Uninstall “{n}” from the device?",
    tConfirmUnN: "Uninstall these {n} apps?", tKeepNote: "(keeping data, per settings)",
    tDataNote: "App data will be deleted too.",

    cInstalled: "Installed", cInstalledV: "Installed · v{v}",
    cAlreadyCurrent: "Device already has this version or newer (v{v})",
    cFileMissing: "File no longer exists", cFileMissingFix: "Drop this APK in again",
    cAlreadyExists: "That package is already on the device", cAlreadyExistsFix: "Turn on “Replace existing app” and retry",
    cDowngrade: "The device has a newer version", cDowngradeFix: "Turn on “Allow downgrade” and retry",
    cSigMismatch: "Signature doesn't match the installed app", cSigMismatchFix: "Uninstall the app on the device first",
    cNoSpace: "Not enough storage on the device", cNoSpaceFix: "Free up space and retry",
    cAbiMismatch: "CPU architecture doesn't match the device", cAbiMismatchFix: "Use an APK for this device's ABI",
    cNoCert: "The APK isn't signed", cNoCertFix: "Use a properly signed APK",
    cBrokenApk: "The APK is damaged", cBrokenApkFix: "Download it again",
    cOldSdk: "Android version is too old for this app", cOldSdkFix: "Use an older build or update the OS",
    cUserRestricted: "The phone refused the install", cUserRestrictedFix: "Allow “Install via USB” and keep the screen unlocked",
    cVerification: "Blocked by the device's install verification", cVerificationFix: "Turn off “Verify apps” and retry",
    cTestOnly: "This is a test-only build", cTestOnlyFix: "Needs -t install or a release build",
    cMissingLib: "A required shared library is missing", cMissingLibFix: "The app may need GMS or similar",
    cInvalidApk: "Invalid APK", cInvalidApkFix: "Get the file again",
    cUnauthorized: "USB debugging not authorised", cUnauthorizedFix: "Tap “Allow” on the phone",
    cNoDevice: "No device detected", cNoDeviceFix: "Check the cable and USB debugging",
    cOffline: "Device went offline", cOfflineFix: "Replug the cable and refresh",
    cRejected: "Rejected by the system ({v})", cRejectedFix: "See the log below for details",
    cFailed: "Install failed", cFailedFix: "See the log below for details",
    cAdbError: "adb error", cExecError: "Execution error",
    cUnOk: "Uninstalled", cUnOkKeep: "Uninstalled (data kept)", cUnNotFound: "That app isn't on the device",
    cUnSystemApp: "The system won't allow removing it (preinstalled)", cUnPolicy: "Blocked by device policy",
    cUnFailed: "Uninstall failed",
    sUnauthorized: "Unauthorised — tap “Allow USB debugging” on the phone",
    sOffline: "Offline — replug the cable",
  },
};

let LANG = "zh";

function detectLang(stored) {
  if (stored && I18N[stored]) return stored;
  const n = (navigator.language || "en").toLowerCase();
  if (n.startsWith("zh")) return "zh";
  if (n.startsWith("ja")) return "ja";
  return "en";
}

function setLang(code) {
  LANG = I18N[code] ? code : "en";
  document.documentElement.lang = { zh: "zh-CN", ja: "ja", en: "en" }[LANG];
}

function t(key, params) {
  const table = I18N[LANG] || I18N.en;
  let s = table[key];
  if (s === undefined) s = (I18N.en[key] !== undefined ? I18N.en[key] : key);
  if (params) {
    for (const k in params) s = s.split("{" + k + "}").join(params[k]);
  }
  return s;
}

/* 结果代码 → 说明 / 建议 */
const CODE_KEY = {
  installed: "cInstalled", already_current: "cAlreadyCurrent", file_missing: "cFileMissing",
  already_exists: "cAlreadyExists", downgrade: "cDowngrade", sig_mismatch: "cSigMismatch",
  no_space: "cNoSpace", abi_mismatch: "cAbiMismatch", no_cert: "cNoCert",
  broken_apk: "cBrokenApk", old_sdk: "cOldSdk", user_restricted: "cUserRestricted",
  verification: "cVerification", test_only: "cTestOnly", missing_lib: "cMissingLib",
  invalid_apk: "cInvalidApk", unauthorized: "cUnauthorized", no_device: "cNoDevice",
  offline: "cOffline", rejected: "cRejected", failed: "cFailed",
  adb_error: "cAdbError", exec_error: "cExecError",
  un_ok: "cUnOk", un_ok_keep: "cUnOkKeep", un_not_found: "cUnNotFound",
  un_system_app: "cUnSystemApp", un_policy: "cUnPolicy", un_failed: "cUnFailed",
};

function codeText(code, arg) {
  if (!code) return "";
  if (code === "installed") return arg ? t("cInstalledV", { v: arg }) : t("cInstalled");
  const key = CODE_KEY[code];
  if (!key) return code;
  return t(key, { v: arg || "" });
}

function codeHint(code) {
  const key = CODE_KEY[code];
  if (!key) return "";
  const fixKey = key + "Fix";
  const table = I18N[LANG] || I18N.en;
  return table[fixKey] !== undefined ? table[fixKey] : (I18N.en[fixKey] || "");
}

/* 给带 data-i18n / data-i18n-ph 的静态元素套上文案 */
function applyStatic() {
  document.querySelectorAll("[data-i18n]").forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-ph]").forEach(el => {
    el.placeholder = t(el.dataset.i18nPh);
  });
  document.querySelectorAll("[data-i18n-title]").forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.title = t("appName");
}
