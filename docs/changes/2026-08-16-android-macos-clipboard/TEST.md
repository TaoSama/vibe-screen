# Android + macOS 剪贴板验证记录

Status: 本地离线门禁完成；Mac XCTest 受本机 SDK 环境阻断；无真机 USB/LAN
端到端或发布证据
Original run date: 2026-08-19
Original baseline: `origin/main` at `0a66aeb2` plus that PR branch's local
clipboard commit, salvaged from `e989a1c833b85c4732c137b428504252f8c62d7e`

## 证据边界

本记录只证明当前本地候选的源代码、JVM 单元/回环集成测试、协议 fixture 和
MacHost 可执行自测。它不证明真实 Android `ClipboardManager`、真实 macOS
`NSPasteboard`、TalkBack、USB 线缆、可信 LAN、真机互操作或发布状态。模拟器、
离线和自测结果不得转述为真机证据。

## 已运行

### Android clipboard 聚焦覆盖

命令：

```bash
cd baseline/AndroidClient
./gradlew --no-daemon testDebugUnitTest \
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardTest \
  --tests dev.telemachus.display.ClipboardApprovalStateTest
```

结果：post-rebase `BUILD SUCCESSFUL in 8s`。覆盖包括能力/上限协商、非 streaming 发送
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

本轮没有启动模拟器、连接真机、执行 USB/LAN 互操作或生成设备验收记录。

## 未验证风险

- 真机 USB 会话中 Android <-> MacHost 双向传输。
- 可信 LAN 上的实际风险提示与明文传输行为。
- 真实 Android `ClipboardManager` / macOS `NSPasteboard` 权限与读写行为。
- TalkBack 对按钮、pending 状态与弹窗的实际播报。
- iOS direct Content 与本候选的跨端互操作。
- 连接切换、进程重启和两小时以上长会话中的状态/内存稳定性。
- 仅有 Command Line Tools 的本机无法执行 Mac clipboard XCTest；需完整 Xcode
  或 CI 补证。

## 2026-08-22 Nubia P0110 readiness rerun

Evidence:
[evidence/2026-08-22-nubia-p0110-clipboard-file-transfer-readiness-blocked](evidence/2026-08-22-nubia-p0110-clipboard-file-transfer-readiness-blocked/README.md).

Status remains open. The P0110 device identity was recorded as nubia P0110 /
pacific / Android 16 / SDK 36, debug and androidTest APKs installed, and the
Android local ClipboardManagerInstrumentedTest passed on device with OK (3
tests). This is a local Android clipboard smoke only; no Android <-> Mac
clipboard transfer over USB or LAN was executed.

The same run verified local readiness improvements for bounded file transfer:
Android focused file-transfer JVM tests, Android lint/build, protocol fixtures,
evidence-tool tests, and MacHost swift build all passed. Real USB/LAN E2E is
blocked by the current Mac environment: security find-identity -v -p
codesigning reports zero valid identities, xcodebuild is unavailable under
Command Line Tools, and MacHost XCTest still fails before execution with no
such module XCTest.

## 2026-08-27 Nubia P0110 current-base E2E gate attempt

Evidence:
[evidence/2026-08-27-nubia-p0110-clipboard-e2e-current-base-blocked](evidence/2026-08-27-nubia-p0110-clipboard-e2e-current-base-blocked/README.md).

Status remains open. The run refreshed from `origin/main` at
`3b2ba11e832a3618eaedfc67f92414b161423a00` and introduced the explicit
`clipboard-e2e-gate` aggregator. The aggregator requires all of the following
before it can close the gate:

- current signed/TCC-ready Host readiness,
- at least one real Protocol v1 USB or trusted-LAN device path ready,
- current Android local `ClipboardManagerInstrumentedTest` pass,
- retained product E2E JSON proving both Android `ClipboardManager` -> macOS
  `NSPasteboard` and macOS `NSPasteboard` -> Android `ClipboardManager` with
  explicit user action, source system clipboard read, remote system clipboard
  write, Protocol v1 session ownership, and final marker match.

The 2026-08-27 run confirmed the device identity as nubia P0110 / pacific /
Android 16 / SDK 36 and reran the local Android ClipboardManager smoke on
device with `OK (3 tests)`. That remains local Android system-clipboard
evidence only. The E2E gate output is `blocked` because Host stable signing and
permission readiness failed, USB readiness is blocked by that Host preflight,
trusted LAN is blocked by the device Wi-Fi/route state plus Host signing, and no
bidirectional product E2E transfer record exists. Offline, synthetic, local, or
preflight-only evidence is explicitly marked as insufficient for closing the
real Android/macOS system-pasteboard gate.

## 2026-08-28 Nubia P0110 Android E2E smoke attempt

Evidence:
[evidence/2026-08-28-nubia-p0110-clipboard-android-e2e-smoke-blocked](evidence/2026-08-28-nubia-p0110-clipboard-android-e2e-smoke-blocked/README.md).

Status remains open. The run refreshed from `origin/main` at
`27d2b0e493e807ae439fbd43b06b4c2f0ce9c503`, confirmed no `sfltool` process was
running before collection, and did not opt into the Host login-item diagnostic
that invokes `/usr/bin/sfltool dumpbtm`. All ADB/device operations were executed
while holding `/tmp/vibe-screen-android-REDACTED_P0110_USB_SERIAL.lock`, and
each ADB command used `adb -s REDACTED_P0110_USB_SERIAL`.

The target device identity was recorded as nubia P0110 / pacific / Android 16 /
SDK 36. Debug and androidTest APKs installed, and the canonical Android local
`ClipboardManagerInstrumentedTest` passed on device with `OK (3 tests)`. ADB
reverse for TCP 54321 was configured, but USB readiness stayed blocked because
the Android app was not foreground, the Mac Host was not listening on TCP 54321,
and Host stable-signing/TCC preflight failed. Trusted LAN stayed blocked because
the device Wi-Fi was not associated, `wlan0` had no IPv4 route to the Mac LAN
candidate, and Host stable signing was blocked.

No Android `ClipboardManager` -> macOS `NSPasteboard` or macOS `NSPasteboard` ->
Android `ClipboardManager` product transfer was executed. The 1 MiB ceiling,
old-peer fallback, and clipboard deny-wins behavior remain offline/protocol
evidence only for this run, not real USB/LAN product smoke evidence.
