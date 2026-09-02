# 主机 RSS 两小时增长排查（进行中）

## 背景

Phase 1 目标之一是「两小时内无延迟或内存增长」。2026-08-09 在 Xiaomi Fuxi
（<redacted-xiaomi-adb-serial>，Android 16，USB）完成了首个带真机流遥测的有效 2h soak，证据见
docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-09-xiaomi-fuxi-soak2h-v2/README.md。

结论：流质量与客户端内存均稳定，但主机 RSS 存在缓慢净增长，两小时无增长门禁**未关闭**。

## 现象（证据）

- 主机 RSS：first 499856 KiB → final 518144 KiB（min 498960 / max 519312），净 +约 18.3 MB / +3.7%。
- 斜率：full-window +191.2 KiB/min，second-half +96.5 KiB/min（约 +5.8 MB/h），后半程无平台期。
- 流：110 条 stream_stats，fps 54.1–61.0（多数 60.0），2 个采样点合计丢帧 25（占约 0.006%），reconnect=0。
- 客户端 PSS：净下降（second-half −15 KiB/min），非客户端问题。

## 归因初判

- `/usr/bin/leaks 27437`：仅 20 处、~4.3 KB 未引用泄漏 → **非经典泄漏**。
- `/usr/bin/footprint`：增长集中在 MALLOC_SMALL（108 region，随时间 371→375 MB），
  MALLOC_LARGE（帧缓冲级别）稳定在 84 MB。
- 判断：增长来自**仍可达、随时间累积的小对象**（缓存/数组/字典/保留对象），
  而非泄漏，故 `leaks` 不报。

## 2026-08-10 活体 heap 归因

在不中断现有推流进程的前提下，`vmmap -summary` 与 `heap -H -s` 已将主要存活
对象收敛到 SwiftUI Observation 图，而不是视频帧或 IOSurface：

- 运行约 26 小时后，进程内约 53 万套 `ObservationRegistrar` 字典、
  `AnyKeyPath` 集合与配套锁状态仍然存活；这些对象连同约 86 万个
  `_SetStorage<Int>` 占据数百 MB。
- 一次 memory graph 基线与约 6 分钟后的活体 `heap --diffFrom` 对比新增
  1,255 套 registrar、约 12 万个 `_SetStorage<Int>` 和大量闭包上下文。
- 引用链落在 SwiftUI `ObservationEntry` 大字典。同期新增的 Process/Pipe/XPC
  对象数量很小，不支持「ADB 状态探测子进程是主增长源」的初始假设。
- `DisplaySettings` 原先把每秒 FPS/码率与每两秒主机状态都放在同一个
  `ObservableObject`；根 `SettingsView` 观察整个对象，且 hosting view 在窗口
  关闭后仍常驻。每次发布都会让整棵大型设置视图重新建立观察依赖。

当前修复把 FPS/码率移到不参与 SwiftUI observation 的 Combine subjects，由
`NSViewRepresentable` coordinator 直接更新 AppKit 文本控件；周期状态字段也只在
值实际变化时发布。离线测试覆盖「metrics 不触发根 settings publisher」与「同值
不发布」契约。该证据足以定位并消除一个主要增长贡献源，但**不能替代修复后的
两小时复测**，因此无增长门禁仍保持开放。

2026-09-01 补充一个确定性离线回归门禁：`StreamMetricsTests` 现在用公开行为
不变量覆盖 10,000 次变化 FPS/码率更新、10,000 次重复 FPS/码率更新、
10,000 次未变化 Host 状态刷新，以及 10,000 次真实变化 Host 状态刷新。
断言点是 `DisplaySettings.objectWillChange` 的
发布次数、`StreamMetrics` subject 的发布次数、`setIfChanged` 的写入次数，以及
`DisplaySettings` 对同一个 `StreamMetrics` 实例的所有权；不读取或匹配私有
`ObservationRegistrar` heap 类型、类名或 SwiftUI runtime 内部结构。该门禁能证明
高频 telemetry 与不变状态刷新不会通过根 settings publisher 触发 O(N) SwiftUI
观察重建，真实变化状态也只按实际写入次数发布，同时证明相同值不会重复发布。
证据边界仍是离线 publisher/所有权不变量：
它不测 Host RSS、不启动 Host、不做 memory soak，也不得用于关闭正式
`host_rss_2h_no_growth` / `host_rss_gate`。

2026-08-24 的当前源码补强继续收敛可验证面：`debugLog` 与 `TelemetryEvent`
共用一个加锁的 `ISO8601DateFormatter`，避免推流期间每条日志和 telemetry 都构造
新的 formatter；生产 `stream_stats` 现在同时携带 `frame_registry_count` 与
`latest_pixel_buffer_retained`/`latest_pixel_buffer_capacity`，并报告
`fallback_capture_active`/`encoder_present` 状态。短窗诊断现在可以直接判定
VideoToolbox callback registry、encoder capacity 稳定性和 capture 侧最新帧缓存是否
超过固定容量，而不是事后只凭 RSS/heap 猜测。该变更降低一个高频小对象分配源并
补足诊断盲点，但仍需要当前源码真机短窗或正式两小时复验来证明实际 RSS 行为。
2026-08-25 复核 current `origin/main`、open draft PR #222 与已合并 PR #329 后，
结论保持不变：这些变更是 telemetry/readiness 与小对象分配面收敛，不是可关闭
README Phase 0 Host RSS no-growth gate 的两小时通过证据。正式 `host_rss_gate` 现在
除 RSS 斜率和漂移阈值外，还必须消费同一 exact window 的 `soak_report` 输出，并
fail-closed 校验原生 `VIBE_SCREEN_TELEMETRY_PATH` telemetry 的 heartbeat、
`stream_stats` 覆盖、queue depth/capacity、VideoToolbox in-flight/callback registry、
latest pixel-buffer retained/capacity、frame-queue drop 和 encoder-present 状态。
历史 2026-08-09 Xiaomi/fuxi 2h soak 用当前 gate 复核仍为 `insufficient`：RSS
增长阈值失败，同时 legacy telemetry 缺 heartbeat 与新增生命周期字段，不能作为
通过证据。

最新主线也已把帧生命周期限制为常数：VideoToolbox 在途准入固定为 2，callback
registry 在回调或 teardown 时逐项 claim/drain；网络侧只保留一个 latest mailbox
帧、一个 pending 帧和一个在发帧。独立并发生命周期审查未发现新的稳态无界
retained 路径。`ScreenCapture` 的 `lastPixelBuffer`、`encoder` 和
`currentFrameSink` 仍存在跨线程正确性风险，但这些引用数量有界，当前证据没有把
它们与历史持续 RSS 斜率建立因果关系，因此不把猜测性并发重构混入内存候选。
2026-08-24 的 current-base 跟进确认：`HOST_PID` fail-closed 正式门禁目标、
closed-socket FD cleanup/readiness、VideoToolbox in-flight admission 与 callback
registry 均已分别由主线和已合并 PR 覆盖；本轮仅把仍未覆盖的 frame-pacer cleanup
consolidation、frame-pacer timer/queue 锁保护与 release-focused tests 最小移植到
当前 `origin/main`。当前环境可完成 MacHost source build 与 P0110 身份读取，但
缺少完整 Xcode/XCTest 与 Screen Recording 授权下的当前源码 Host RSS 实测，因此
记录为 blocked readiness；不得把该记录解读为 10-17 分钟短窗诊断通过或两小时 Host
RSS no-growth 通过。

为避免再次只凭 RSS 猜测，现提供 10-17 分钟的
`vibescreen_evidence.host_memory_diagnostic` 作为独立短窗回归门禁。它联合
RSS、physical footprint、`MALLOC_SMALL`、malloc zone
dirty/live/fragmentation、三次 heap 类型快照及连续网络队列深度，输出顶层
`verdict`（`pass`/`fail`/`insufficient`）与归因
`attribution`（`retained_growth`/`allocator_high_water`/`inconclusive`）。

`verdict` 语义如下：

- `pass`：10-17 分钟窗口样本完整、所有必需内存信号落在短窗稳定阈值内、流遥测
  与有界网络队列健康；若存在 VideoToolbox in-flight、callback registry 或
  latest pixel-buffer telemetry，也必须在容量内。仅表示短窗回归通过，
  **不能替代或关闭正式两小时 `host_rss_gate`**。
- `fail`：窗口归因到 `retained_growth` 或 `allocator_high_water`，或生产流
  出现队列越界、队列容量非法/变化、可选 VideoToolbox in-flight、callback
  registry 或 latest pixel-buffer 越界、encoder capacity 非法/变化、非正 FPS 异常。
- `insufficient`：采样/工具/解析/流遥测覆盖不完整，或内存信号矛盾、无法支持
  稳定或增长归因。

任何工具/解析/遥测覆盖错误、session epoch 变化、队列越界或存在的编码器在途、
callback registry、latest pixel-buffer 越界、encoder capacity 非法/变化或诊断布尔
状态类型错误都 fail closed：`verdict` 为
`insufficient` 或 `fail`，`attribution` 保持 `inconclusive`。退出码按
`verdict` 映射：`pass`→0、`fail`→2、`insufficient`→1。
该工具不会执行内存压力、修改 TCC 或访问 Keychain。具体命令与阈值见
[`tools/README.md`](../../../tools/README.md)。

## 复现与下一步（需可中断当前会话）

若修复后的短时 heap 差分仍出现持续增长，再以分配栈日志重启主机并采样：

```bash
# 关闭当前 Vibe Screen 后，给 LaunchServices 会话设置分配栈日志环境，
# 再通过 guarded launcher 启动已安装 Host（会重置会话，与 TCC 无关）。
osascript -e 'quit app "Vibe Screen"' || true
launchctl setenv MallocStackLogging 1
launchctl setenv MallocStackLoggingNoCompact 1
make baseline-macos-launch
# 建立 adb reverse + 客户端连接，稳定流 10–15 分钟后：
/usr/bin/malloc_history <pid> -allBySize | head -60   # 按大小聚合分配栈
/usr/bin/heap <pid> | head -60                         # 按类聚合存活对象
# 两次间隔采样对比 MALLOC_SMALL 中增长最快的分配栈/类。
launchctl unsetenv MallocStackLogging
launchctl unsetenv MallocStackLoggingNoCompact
```

复测判据：先跑 10–15 分钟短时流，确认 Observation 对象计数与 host RSS 斜率不再
持续上升。按当前验证约束，每次交互式 soak 最长 30 分钟，不再默认启动两小时
运行；30 分钟结果只能作为回归证据，不能替代或关闭正式两小时门禁。若以后单独
批准正式门禁运行，Host RSS 门禁由
`vibescreen_evidence.host_rss_gate` 独立判定，要求来源 soak 完整无错误、窗口至少
7056 秒、soak 样本自身 `elapsed_seconds` 跨度至少 7056 秒、Host RSS 样本至少
230 个且后半程至少 115 个、首尾和内部采样间隔均不超过 90 秒，并同时满足：
后半程 OLS 斜率 95% 上界与 Theil-Sen 稳健斜率均不高于
40 KiB/min、后半程端点中位数漂移不高于 4 MiB、全窗端点中位数漂移不高于 8
MiB、后半程最后两个四分之一窗口的均值增量不高于 2 MiB；并且同一窗口的原生
Host telemetry 必须证明流仍在活动、heartbeat 被接受、帧队列和编码器/最新帧保留
均在固定容量内且没有 frame-queue drop。任一输入不足均为
`insufficient`，不得宣称通过。流与客户端指标也须
继续通过，才关闭 Phase 1 门禁。若仍增长，再检查按帧/秒累积且未逐出的集合、按
generation/epoch 键控的表，以及保留 CMSampleBuffer、CVPixelBuffer 或 NSData
的路径。

## 状态
- 2026-08-31 current-base readiness 在 `origin/main` commit
  `075dc157c36ba71df9f757e571015905881a7154` 的 clean checkout 上重跑，同一约束下
  `pgrep -x sfltool || true` 在检查前后均无输出，且没有使用 `/usr/bin/sfltool dumpbtm`
  或任何 login-item 诊断 opt-in 参数。结果仍为 `status=blocked`、
  `can_start_host_rss_gate=false`、`host.current_source_dirty=false`：本机仍缺
  少 `Vibe Screen Dev` stable signing identity，已安装 Host 的 WebRTC framework
  sealed resource 校验失败，Host listener 未出现在 TCP 54321，Host 缺少
  `com.apple.developer.hid.virtual.device` entitlement，Launch at Login 未验证，
  且 Command Line Tools 仍无法运行 SwiftPM XCTest。见
  [`evidence/2026-08-31-current-base-host-rss-failclosed-readiness/README.md`](evidence/2026-08-31-current-base-host-rss-failclosed-readiness/README.md)。

- 已记录 pitfall（见 docs/pitfall/index.md）。
- 已完成不中断会话的 heap 类型与引用链归因，并实现针对 SwiftUI Observation
  高频失效的修复；该修复已合入 `main` 并装入验证进程。
- 修复后的 30 分钟前缀包含 60 个有效样本、零采集错误：Host RSS 从 121008 KiB
  降至 111264 KiB，全窗斜率 -82.0 KiB/min、后半窗斜率 -15.9 KiB/min，平均约
  60 FPS、零丢帧、零重连。该短测支持“未见短期增长”，但不证明两小时无增长。
- 同一次随后被中止的较长观察不是完整门禁证据，来源 summary 为 `partial`，且
  后半程出现 +117.0 KiB/min 的迟发上升；不得据此宣称正式 no-growth 通过。
- 后续单次真机稳定性验证保持在 30 分钟以内；正式两小时门禁继续开放。
- 当前短窗回归门禁仅完成离线工具与阈值验证，尚无基于本分支源码的 Xiaomi 13
  10-17 分钟短窗实测证据；正式两小时 Host RSS no-growth 门禁仍需
  `host_rss_gate` 独立输出 `pass` 方可关闭。
- 2026-08-24 current-base 跟进重新审计了 open draft PR #195、已合并 #158 和
  #260；#195 在旧 base 上仍有 frame-pacer lifecycle 收紧价值，但它的
  `HOST_PID` 门禁与 closed-socket/readiness 部分已由 #158/#260/main 覆盖。本轮
  current-base evidence 见
  [`evidence/2026-08-24-frame-lifecycle-current-base-blocked/README.md`](evidence/2026-08-24-frame-lifecycle-current-base-blocked/README.md)。
- 短窗诊断报告现在把 watched heap 类按 `swiftui_observation`、`autorelease_pool`
  和 `video_frames` 聚合为 `metrics.heap_watch_summary`，让下一次短窗实测能直接
  对比已知 SwiftUI Observation 增长候选与有界视频帧候选，而不用人工从
  `heap_class_growth` 列表中重建首末漂移。
- 短窗诊断报告现在显式输出
  `gate.can_close_host_rss_no_growth_gate=false`，让自动化不能把 10-17 分钟
  `host_memory_diagnostic` 的 `pass` 误当成正式两小时 no-growth 通过。
- 2026-08-28 current-base follow-up 进一步收紧正式门禁聚合：`host_rss_gate`
  现在同时要求来源 soak 样本自身 `elapsed_seconds` 跨度满足 7056 秒，
  `real_device_gate --require-host-rss-gate` 必须消费同一 exact-window report，
  防止把 wall-clock 拉长但 elapsed 样本很短的证据误判为两小时通过。本轮
  readiness 仍阻塞于 stable-signing、TCC、已安装 Host provenance、virtual HID
  entitlement 和 full-Xcode/XCTest 前置条件，见
  [`evidence/2026-08-28-current-base-host-rss-failclosed-readiness/README.md`](evidence/2026-08-28-current-base-host-rss-failclosed-readiness/README.md)。
- 2026-08-29 current-base readiness 在 `origin/main` commit
  `7c7c2d43568cd452f7a430cbd9657bbada6be3ff` 上重跑，`pgrep -x sfltool || true`
  在 readiness 前、readiness 后、XCTest preflight 后均无输出，且没有使用
  `/usr/bin/sfltool dumpbtm` 或任何 login-item 诊断 opt-in 参数。结果仍为
  `status=blocked`、`can_start_host_rss_gate=false`、`host.current_source_dirty=false`：
  本机缺少 `Vibe Screen Dev` stable signing identity，已安装 Host 的 WebRTC
  framework sealed resource 校验失败，Host listener 未出现在 TCP 54321，Host 缺少
  `com.apple.developer.hid.virtual.device` entitlement，Launch at Login 未验证，且
  当前 developer directory 仍是 Command Line Tools、不可运行 SwiftPM XCTest。见
  [`evidence/2026-08-29-current-base-host-rss-failclosed-readiness/README.md`](evidence/2026-08-29-current-base-host-rss-failclosed-readiness/README.md)。
- 2026-08-30 current-base readiness 在 `origin/main` commit
  `87e16d8bea4446c1ca449045678f1bafc7fd6cb2` 的干净 checkout 上重跑，同一约束下
  `pgrep -x sfltool || true` 在检查前后均无输出，且没有使用 `/usr/bin/sfltool dumpbtm`
  或任何 login-item 诊断 opt-in 参数。结果仍为 `status=blocked`、
  `can_start_host_rss_gate=false`、`host.current_source_dirty=false`：本机仍缺
  少 `Vibe Screen Dev` stable signing identity，已安装 Host 的 WebRTC framework
  sealed resource 校验失败，Host listener 未出现在 TCP 54321，Host 缺少
  `com.apple.developer.hid.virtual.device` entitlement，Launch at Login 未验证，
  且 Command Line Tools 仍无法运行 SwiftPM XCTest。见
  [`evidence/2026-08-30-current-base-host-rss-failclosed-readiness/README.md`](evidence/2026-08-30-current-base-host-rss-failclosed-readiness/README.md)。
- 正式 `host_rss_gate` 的 telemetry 侧最小输入来自同一 exact window 的
  `soak_report`：`stream_stats` 与 `heartbeat_received` 必须存在且窗口间隔不超过
  90 秒，heartbeat 必须全部 accepted，`fps` 必须为正，`frame_queue_drop_total`
  必须为 0，queue depth 必须落在固定 queue capacity 内，`encoder_in_flight` 与
  `frame_registry_count` 必须落在固定 encoder capacity 内，
  `latest_pixel_buffer_retained` 必须落在固定 latest pixel-buffer capacity 内，并且
  `encoder_present_values` 必须全程为 `[true]`；这些字段缺失或不完整都会让正式
  Host RSS gate fail closed 为 `insufficient` 或 `fail`。
- 当前源码已离线验证新增 capture/encoder telemetry 合约和诊断 fail-closed 逻辑；
  本机没有完整 Xcode XCTest runtime，`swift test` 因缺少 `xctest` 阻塞。该分支没有
  运行当前源码的真机短窗或两小时 soak，因此正式 Host RSS no-growth 门禁保持开放。
- 2026-08-22 对 P0110 运行态做只读前置检查时，确认当前已安装 Host 正在推流但
  未以 `VIBE_SCREEN_TELEMETRY_PATH` 启动，且本机 keychain 不暴露 `Vibe Screen Dev`
  签名 identity，不能重签并证明当前源码二进制与 TCC 授权一致。因此没有启动短窗
  诊断或正式两小时 soak。
- 本分支修复一个真实资源保留候选：服务端 `NWConnection.stateUpdateHandler` 原来
  强捕获同一个连接对象，连接关闭后可能让 Host 继续持有已进入 `CLOSED` 状态的
  TCP socket FD。现在连接接收、替换、结束、token 轮换和 stop 路径都会断开 handler
  并取消未采纳连接；新增 `host_socket_fd` 只读诊断用于把 saved/live `lsof` 样本
  汇总为 `pass`/`fail`/`insufficient`，但该诊断不能关闭 Host RSS no-growth gate。

正式复测仍必须由具备 Screen Recording/Accessibility 权限的主任务执行：

```bash
export EVIDENCE_SERIAL='<lease-controlled-endpoint>'
export EVIDENCE_DIR='.build/evidence'
export VIBE_SCREEN_TELEMETRY_PATH="$EVIDENCE_DIR/soak-2h/host-telemetry.jsonl"
mkdir -p "$EVIDENCE_DIR/soak-2h"
# 用以上环境启动与当前源码匹配的 Host，建立稳定推流后，记录该进程 PID：
export HOST_PID='<running-host-pid>'
make soak-2h EVIDENCE_SERIAL="$EVIDENCE_SERIAL" EVIDENCE_DIR="$EVIDENCE_DIR" HOST_PID="$HOST_PID"
make host-rss-gate EVIDENCE_DIR="$EVIDENCE_DIR"
```

也可用 `make soak-2h-host-rss-gate EVIDENCE_SERIAL="$EVIDENCE_SERIAL"
EVIDENCE_DIR="$EVIDENCE_DIR" HOST_PID="$HOST_PID"` 串联正式两小时采集和门禁判定；
`make soak-2h` 和组合目标都会在 `HOST_PID` 缺失时立即失败，避免产生缺少
`host.rss_kb` 的不可关闭证据。

只有来源 summary 为 `complete` 且无错误、流/客户端指标有效，并且
`host_rss_gate` 独立输出 `pass` 时才能关闭门禁。短诊断、30 分钟前缀或 partial
summary 都不得替代该结论。
