# Android + macOS 剪贴板双向传输

Status: 本地离线门禁完成；Mac XCTest 受本机 SDK 环境阻断；无真机、USB/LAN 端到端或发布证据
Owner: Android + MacHost clipboard
Started: 2026-08-16

## 目标

在 Android 客户端与 MacHost 的 USB / 可信 LAN Protocol v1 会话中提供最小、
完整的双向 `text/plain` 剪贴板传输。任何系统剪贴板读取或覆盖都必须由用户
显式触发，不做后台轮询、自动抓取或静默覆盖。

## 五维语义矩阵

| 维度 | Android → Mac | Mac → Android | 固定边界 |
| --- | --- | --- | --- |
| 现状 | 本地候选已接通 Android UI、会话调度、Protocol v1 与 MacHost UI/核心 | 同一候选已接通反向路径 | 不是 README shipped 状态；真机、USB/LAN 端到端均未验证 |
| 隐私 | Android 仅在用户选择“发送到 Mac”时读取；可信 LAN 在发送前警告“已认证但未加密” | Mac 仅在用户点击分享菜单时读取；可信 LAN 在传输前显示同等警告 | USB 无应用层 E2E；可信 LAN 正文明文可见；不覆盖 Internet E2EE |
| 大小 | 严格 UTF-8，发送与接收均以字节计；上限为 `min(本地 1 MiB, 对端非零上限)` | 同左 | 对端 `maximum_clipboard_bytes == 0` 表示未声明，不能放宽本地 1 MiB 硬上限 |
| 方向 | Offer → 用户获取 → Request → Content；直接 Content 只暂存 | 同左 | 剪贴板是会话级数据，不带 display / stream target |
| 产品证据 | 必须记录 Android `ClipboardManager` 作为源端点、macOS `NSPasteboard` 作为目标端点、正 session epoch、16 字节 change ID、SHA-256、字节长度和最终 marker 匹配 | 必须记录 macOS `NSPasteboard` 作为源端点、Android `ClipboardManager` 作为目标端点、正 session epoch、16 字节 change ID、SHA-256、字节长度和最终 marker 匹配 | 两个方向必须使用不同 marker，单次传输或本地 smoke 不能同时满足双向 E2E |
| 用户确认 | 发送点击才读；收到 Offer 不自动 Request；用户点击获取后，匹配 Content 才覆盖；直接 Content 需二次确认 | 同左 | 未协商能力或旧 peer 不显示可用入口；禁止后台静默抓取或覆盖 |

## 协议现状

- 共享 Protocol v1 已有 `CAPABILITY_CLIPBOARD`、`ClipboardOffer`、
  `ClipboardRequest`、`ClipboardContent` 与
  `ResourceLimits.maximum_clipboard_bytes`；本变更不修改 proto。
- Android 候选通告能力与 1 MiB 本地上限，并实现协商、严格字段校验、显式
  UI 操作、会话代际绑定和旧 peer 回退。
- MacHost 候选通告能力，通过会话核心验证消息，通过主线程 UI 控制器执行
  `NSPasteboard` 读写，并按连接代际丢弃旧回调。
- Android 与 MacHost 在双方协商 `CAPABILITY_MANAGED_CONFIGURATION` 时交换本地
  `ManagedPolicyStatus`，并把远端 `managed=true && clipboard_allowed=false`
  作为 clipboard deny-wins 门控：清空 pending 状态、隐藏/禁用入口，后续 peer
  clipboard payload fail-closed。完整 managed-policy deny-wins 与
  `restriction_results` 产品边界记录在
  [2026-08-21-managed-policy-deny-wins](../2026-08-21-managed-policy-deny-wins/PRD.md)。
- iOS 现有实现保持不变。直接 `ClipboardContent` 的接收兼容只作为 Android /
  MacHost 的防御性协议行为，不构成 iOS 互操作证据。

## 范围

- MIME 仅为 `text/plain`，正文必须是严格 UTF-8。
- 单条正文的本地硬上限为 1 MiB。
- Android 与 MacHost 双向传输。
- USB（ADB reverse TCP）和可信 LAN 的既有 Protocol v1 主会话。
- `session_id + session_epoch`、握手 peer ID、UI owner / connection generation
  校验。
- 剪贴板范围内的 managed-policy deny-wins：消费对端显式
  `ManagedPolicyStatus.clipboard_allowed=false` 和完整 `restriction_results`，并复用
  独立 managed-policy 产品化任务的本机配置源。
- Android 48dp 控件、内容描述、pending 状态描述和可访问性公告。
- Mac `NSPasteboard` 访问限制在 `@MainActor` 适配器，并带主队列断言。

## 非目标

- 不修改 iOS、HarmonyOS 或共享 proto。
- 不支持图片、富文本、文件、音频或任意 MIME。
- 不为可信 LAN 增加加密，也不接入 Internet record layer。
- 不声明真实受管配置/MDM profile 注入已经验收；该 gate 仍由独立 managed-policy
  evidence 关闭。
- 不实现剪贴板历史、跨会话持久化、后台监听或自动同步。
- 不更新 README 宣称能力已发布。

## 用户动作矩阵

| 阶段 | 用户动作 | 读取本地 | 协议动作 | 写入本地 |
| --- | --- | --- | --- | --- |
| 主动发送 | 点击发送/分享 | 此时才读取一次 | 发送仅含元数据的 `ClipboardOffer` | 否 |
| 收到 Offer | 无 | 否 | 仅 stage 最新 Offer | 否 |
| 主动获取 | 点击获取/接收 | 否 | 发送一次 `ClipboardRequest` | 否 |
| solicited Content | 已由前一步明确批准 | 否 | 校验 exact Offer/Request 后消费 | 校验通过才覆盖 |
| direct Content | 点击覆盖确认 | 否 | 不抢占不同 ID 的已批准 Request/更新 Offer；同 ID 迟到正文可 stage，不污染已接受 change ID 历史 | 确认后才覆盖 |
| 断开/换 owner | 无 | 否 | 清除会话和 UI pending 状态 | 否 |

## 隐私与安全边界

- USB 通过 ADB reverse 的本机 TCP 路径承载，未增加应用层 E2E。
- 可信 LAN 使用既有已认证但未加密的连接；发送正文或请求正文前显示风险
  确认，不得描述为 E2EE。
- `origin_device_id` 必须等于握手中的对端身份：Android 校验
  `HostHello.host_id`，MacHost 校验 `ClientHello.device_id`。
- Envelope 必须匹配当前 `session_id + session_epoch`；UI 回调还必须匹配当前
  StreamClient owner / generation 或 MacHost connection generation。
- 本地生成或已通过 solicited 流程接受的 `change_id` 再次从对端返回时
  fail-closed；direct Content 在用户确认前不进入该历史，避免阻断之后合法的
  Offer → Request 流程。
- 合法但未知、已替换或已消费的 `ClipboardRequest` 是静默 no-op；错误长度等
  畸形消息 fail-closed。

## 验收边界

- 离线协议、UI 策略、调度和服务集成结果记录在 `TEST.md`。
- 真机 USB / LAN、真实 Android `ClipboardManager`、真实 `NSPasteboard`、
  TalkBack 以及长时内存稳定性仍需单独证据。
- 真实产品 E2E 必须由 `clipboard-e2e-gate` 读取 retained product JSON 判定；
  该 JSON 必须区分 local ClipboardManager smoke、protocol/offline pass 和真实
  Android `ClipboardManager` <-> macOS `NSPasteboard` 双向 product transfer。
