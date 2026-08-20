# Android + macOS 剪贴板验证记录

Status: 本地离线门禁完成；P0110 真机 Android 系统剪贴板 smoke 通过；Mac
XCTest 受本机 SDK 环境阻断；Android <-> macOS 系统剪贴板端到端 gate 仍 open
Date: 2026-08-21
Baseline: `origin/main` at `8e630ad3` plus this PR branch's local clipboard
evidence commits

## 证据边界

本记录证明当前本地候选的源代码、JVM 单元/回环集成测试、协议 fixture、
MacHost 可执行自测，以及一次 Nubia P0110/pacific/Android 16 前台 Activity 内的
Android `ClipboardManager` 读写 smoke。它不证明真实 macOS `NSPasteboard`、
TalkBack、USB/LAN 双向系统剪贴板互操作或发布状态。模拟器、离线、自测和
Android 本机 smoke 结果不得转述为 Android <-> Mac clipboard E2E 证据。

## 已运行

### 2026-08-21 复核

本轮从 origin/main 建立 codex/android-clipboard-e2e-evidence 分支，并在提交前
rebase 到最新 origin/main 8e630ad3；复核 Android 与 MacHost
clipboard 代码路径后确认：Android ClipboardManager 与 macOS
NSPasteboard 的生产边界已接入显式用户动作和 Protocol v1 会话，但仓库仍缺
真实 USB/LAN 双向系统剪贴板端到端证据。

新增 [RUNBOOK.md](RUNBOOK.md) 作为后续短真机验收步骤，要求记录设备身份、
Protocol v1 clipboard 能力协商、Android -> Mac 与 Mac -> Android 两个方向的
唯一 marker、Android logcat/diag、Host clipboard 日志和人工可见读回结果。

设备短测在任何 ADB 命令前被锁阻断：/tmp/vibe-screen-device-android.lock
已存在且为空，因此未读取设备身份、未安装 APK、未改 ADB reverse、未启动 Host
或客户端，未生成 Nubia P0110/pacific Android 16 真机证据。阻断记录保存在
[evidence/2026-08-21-android-device-lock-blocked/README.md](evidence/2026-08-21-android-device-lock-blocked/README.md)。

本轮复跑：

    cd baseline/AndroidClient
    ./gradlew --no-daemon testDebugUnitTest \
      --tests dev.telemachus.display.protocol.ProtocolV1ClipboardTest \
      --tests dev.telemachus.display.ClipboardApprovalStateTest

结果：BUILD SUCCESSFUL in 28s。

在用户确认 /tmp/vibe-screen-device-android.lock 是 stale 空文件并删除后，本轮用
flock(LOCK_EX|LOCK_NB) 重新获取 /tmp/vibe-screen-device-android.lock，最终锁记录
pid=60011、serial=EP0110PZ0B9110300B。随后读取设备身份并确认目标设备为：

- manufacturer: nubia
- model: P0110
- codename/device: pacific
- Android release: 16
- SDK: 36
- fingerprint: nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys

新增真机 Android 本地系统剪贴板 smoke：

```bash
cd baseline/AndroidClient
./gradlew --no-daemon assembleDebug assembleDebugAndroidTest
adb -s EP0110PZ0B9110300B install -r -t app/build/outputs/apk/debug/app-debug.apk
adb -s EP0110PZ0B9110300B install -r -t app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s EP0110PZ0B9110300B shell am instrument -w \
  -e class dev.telemachus.display.ClipboardManagerInstrumentedTest \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
```

结果：OK (1 test)。Logcat 记录
ClipboardDeviceTest: clipboard_manager_roundtrip marker=vs-clipboard-device-1787249745010。
该测试只证明前台 Android Activity 可以通过系统 ClipboardManager 写入并读回
唯一 marker；它不经过 Protocol v1、不经过 MacHost、不读取或写入 macOS
NSPasteboard，不能关闭 Android <-> Mac clipboard E2E gate。

USB E2E 前置仍被 Host 侧阻断。python3 scripts/macos_dev_host.py preflight
--install-path "/Applications/Vibe Screen.app" 失败于本机 keychain 缺少稳定签名身份
Vibe Screen Dev；当前已安装的 /Applications/Vibe Screen.app 不是本分支重新安装的
稳定签名 Host，且早期 Android 连接日志出现 Protocol upgrade probe closed before a
response。本轮没有观察到同一 Protocol v1 会话中的 clipboardAvailable=true、
Offer/Request/Content、pbcopy/pbpaste 或人工双向 marker 读回。因此 Android
ClipboardManager <-> macOS NSPasteboard 真机 gate 保持 open。证据保存在
[evidence/2026-08-21-p0110-clipboard-device-attempt/README.md](evidence/2026-08-21-p0110-clipboard-device-attempt/README.md)。

    cd baseline/MacHost
    swift test --scratch-path /tmp/vibe-screen-mac-host-swift-clipboard-3c7e \
      --filter Clipboard

结果：仍在编译测试 target 时失败：error: no such module 'XCTest'。该结果与下方
XCTest 环境门禁一致，不是 clipboard XCTest 断言失败。

### Android clipboard 聚焦覆盖

命令：

```bash
cd baseline/AndroidClient
./gradlew --no-daemon testDebugUnitTest \
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardTest \
  --tests dev.telemachus.display.ClipboardApprovalStateTest
```

结果：post-rebase `BUILD SUCCESSFUL in 4s`。覆盖包括能力/上限协商、非 streaming 发送
拒绝、严格 UTF-8、16/32 字节字段、origin、Offer -> Request -> Content、
direct Content、duplicate/unknown Request、10 秒超时后的 exact 清理与同 Offer
重试、A Request -> B Offer -> A 迟到 direct 不覆盖 B、同 ID 超时 handoff
仍需二次确认、core 已消费但 UI timeout callback 未完成的竞态、旧 peer 回退，
以及 StreamClient 不自动 Request 的回环行为。

### Android 全量 JVM 测试

```bash
make baseline-android-test
```

结果：`BUILD SUCCESSFUL in 14s`。该门禁覆盖 Android transport 边界检查和
`testDebugUnitTest`。

### Android 构建、lint 与 release 依赖审计

```bash
cd baseline/AndroidClient
./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebug auditReleaseDependencies
```

结果：post-rebase `BUILD SUCCESSFUL in 21s`。这里没有安装 APK 或执行
instrumentation 测试。

### Protocol v1 契约门禁

```bash
python3 contracts/fixtures/messages/v1/generate.py
python3 -m unittest contracts.tests.test_protocol_fixtures -v
env GOMAXPROCS=2 GOFLAGS=-p=2 make protocol
```

结果：fixture 生成通过；`contracts.tests.test_protocol_fixtures` 15 tests 通过；
受限 Go 并行的 `make protocol` 通过，post-rebase 最终
`Ran 35 tests in 101.259s OK`，并包含
Buf format、lint、build、breaking 检查。未限制并行的 `make protocol` 曾在非
clipboard 的 `session_accepted` fixture 上出现一次 `buf convert` 子进程退出；同一
门禁用受限 Go 并行完整重跑通过。`python3 -m pytest ...` 曾因本机未安装
`pytest` 模块失败；项目协议门禁使用 unittest，`make protocol` 已通过。

### Mac build

```bash
cd baseline/MacHost
swift build
cd ../..
make baseline-macos-build
```

结果：post-rebase SwiftPM debug build `Build complete! (10.73s)`；
`make baseline-macos-build` release build `Build complete! (43.86s)`。

### Mac 可执行自测

```bash
cd baseline/MacHost
.build/release/Vibe\ Screen --host-self-test
.build/release/Vibe\ Screen --transport-self-test
.build/release/Vibe\ Screen --reliability-self-test
.build/release/Vibe\ Screen --protocol-v1-self-test
.build/release/Vibe\ Screen --video-encoder-self-test
```

结果：五项均 `PASS`。Protocol v1 自测覆盖 framing、golden、能力协商、
display/video gate、epoch、targeted input、heartbeat、断开、clipboard control
fixture 和 managed-policy status 接收。host self-test 的 private virtual display
输出只证明 class/selector shape，不是创建、捕获、真机或 clipboard 证据。

## XCTest 环境门禁

当前 `xcode-select -p` 为 `/Library/Developer/CommandLineTools`，不是完整 Xcode；
`xcrun --find xcodebuild` 失败。因此：

```bash
cd baseline/MacHost
swift test --filter Clipboard
```

命令在编译测试 target 时失败：`error: no such module 'XCTest'`。这是本机
测试 SDK 门禁，不是 clipboard XCTest 断言失败。测试源码已加入，但必须在完整
Xcode / CI 环境执行后才能声称通过。

## 测试覆盖清单

### 协议与安全

- 能力未协商或 legacy peer：入口隐藏/禁用，本地 API 返回失败，peer payload
  fail-closed。
- 双方都通告 `CAPABILITY_MANAGED_CONFIGURATION` 时发送本地未受管
  `ManagedPolicyStatus`；收到远端 `managed=true && clipboard_allowed=false` 后按
  deny-wins 禁用 clipboard、清空 pending state，并对后续 peer clipboard payload
  fail-closed。该覆盖仅是 clipboard 所需策略门控，不是完整 MDM 产品化。
- 本地 1 MiB 硬上限、对端 0/非零上限语义、UTF-8 字节边界。
- `change_id` 16 字节、SHA-256 32 字节、严格 UTF-8、`text/plain`。
- origin 与握手 peer ID 匹配，session ID / epoch 精确匹配。
- solicited Content 精确匹配 Offer metadata；不匹配时 fail-closed。
- direct Content 需二次确认且不污染 seen-ID。
- 合法 unknown / consumed Request no-op；畸形 Request fail-closed。
- 会话断开、ProtocolError、owner/generation 更替清理 pending 状态。

### Android UI 与调度

- 只有当前 StreamClient owner + generation 能 stage/consume 内容。
- 收到 Offer 只提示，不自动发 Request。
- 已发送 Request 在 10 秒后按 exact owner / generation / change ID 超时，恢复
  同一 Offer 重试；同 ID 迟到正文转为 direct 并仍需二次确认。
- 不同 ID direct 不能抢占已批准 Request 或更新 Offer；core 超时已生效但
  UI 清理 callback 未完成时，同 ID direct 会清除在途标记并进入二次确认，
  不会自动写入。
- 系统剪贴板只在用户选择发送时读取，只在用户批准获取/覆盖后写入。
- 可信 LAN 的发送、获取和 direct 覆盖均有风险确认。
- 48dp 控件、普通/pending content description、tooltip、pending 公告和窄屏
  layout 由源码及 JVM/instrumentation 编译门禁覆盖；TalkBack 行为仍未实测。
- clipboard 命令复用现有可靠有序 control scheduler，不合并；队列饱和按现有
  fail-closed 连接错误处理。

### MacHost UI 与集成

- `ClipboardCore` 覆盖大小、origin、digest、UTF-8、latest-only bounded state、
  direct/solicited 分流、一次性 snapshot 和 reset。
- `ClipboardUIController` 测试覆盖按点击读取、direct 覆盖确认、LAN 警告、能力
  快照、generation、request-in-flight、A/B Offer 竞态、同 ID timeout handoff 与
  可见失败反馈。
- `StreamingServerClipboardTests` 覆盖 legacy/未协商 fallback、主线程回调、
  solicited/direct 分发和旧 generation 丢弃。
- `NSPasteboardClipboardAdapter` 限定 `@MainActor` 并在读写时断言主队列；真实
  pasteboard 尚未实测。

## 执行约束

首次 2026-08-21 复核没有执行 ADB：Android 设备协调锁已存在，按
docs/runbook/android-client.md 规则必须在任何设备操作前停止。该 blocked
evidence 不证明设备身份，也不关闭 clipboard 真机 gate。

后续 2026-08-21 P0110 attempt 在重新获取排它锁后执行了 ADB、安装和 focused
instrumentation。该 run 仅证明 P0110 上 Android 前台系统剪贴板本地 smoke；Host
preflight/会话失败使跨端 clipboard 验收停在阻断状态，仍不能关闭 README gate。

## 未验证风险

- 真机 USB 会话中 Android <-> MacHost 双向传输。
- 可信 LAN 上的实际风险提示与明文传输行为。
- 真实 Android `ClipboardManager` / macOS `NSPasteboard` 权限与读写行为。
- TalkBack 对按钮、pending 状态与弹窗的实际播报。
- iOS direct Content 与本候选的跨端互操作。
- 连接切换、进程重启和两小时以上长会话中的状态/内存稳定性。
- 仅有 Command Line Tools 的本机无法执行 Mac clipboard XCTest；需完整 Xcode
  或 CI 补证。
