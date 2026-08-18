# Android + macOS 剪贴板技术设计

## 共享契约

本变更复用现有 Protocol v1 契约，不修改 proto：

```text
ClipboardOffer {
  bytes  change_id
  string origin_device_id
  string mime_type
  uint64 byte_length
  bytes  sha256
}
ClipboardRequest { bytes change_id }
ClipboardContent {
  bytes  change_id
  string origin_device_id
  string mime_type
  bytes  content
  bytes  sha256
}
```

固定约束：

- `change_id` 必须为 16 字节。
- `sha256` 必须为 32 字节，并等于正文的 SHA-256。
- `mime_type` 必须为 `text/plain`。
- `content` 必须非空且能以严格 UTF-8 解码，禁止替换非法字节。
- Android 发出的 origin 为 `ClientHello.device_id`；MacHost 发出的 origin 为
  `HostHello.host_id`。接收端必须与握手身份精确匹配。
- Envelope 必须匹配当前 `session_id + session_epoch`。剪贴板不带 display /
  stream target。

## 能力协商与旧 Peer

- Android `ClientHello` 与 MacHost `HostHello` 都通告
  `CAPABILITY_CLIPBOARD`，并在本地 clipboard deny-wins 门控所需范围内通告
  `CAPABILITY_MANAGED_CONFIGURATION`。
- 只有双方交集进入 `SessionAccepted.negotiated_capabilities` 后才创建会话级
  clipboard 状态并显示/启用入口。
- Android 未协商时对外暴露的 clipboard 上限为 0，按钮隐藏，API 返回
  `false`。
- MacHost legacy 或未协商会话禁用菜单，公开 server API 返回 `false`；收到
  未协商 clipboard payload 时返回 `unsupportedCapability` 并关闭违规会话。

## Managed Policy 剪贴板门控

该候选只实现 clipboard 所需的最小 deny-wins 协议互锁，不读取系统 MDM 配置，也
不替代独立 managed-policy 产品化任务。

- 双方协商 `CAPABILITY_MANAGED_CONFIGURATION` 后，各自发送本地未受管
  `ManagedPolicyStatus(managed=false, clipboard_allowed=true)`。
- 收到远端 `managed=true && clipboard_allowed=false` 时，当前 session 的 clipboard
  effective policy 立即变为 denied。
- denied 状态会清空本地 snapshot、pending offer/request 和 UI pending 状态；本地
  share/request API 返回 `false`，UI 入口隐藏或禁用。
- denied 后若 peer 继续发送 `ClipboardOffer`、`ClipboardRequest` 或
  `ClipboardContent`，接收端按策略违规 fail-closed，不写入系统剪贴板。
- 远端未声明 managed 或 `clipboard_allowed=true` 不会放宽本地其他边界：显式动作、
  大小上限、MIME/UTF-8、origin、epoch 和 digest 校验仍全部执行。

## 大小协商

本地硬上限为 `1_024 * 1_024` 字节，所有比较都基于 UTF-8 字节数。

- 对端上限为非零值：使用 `min(本地 1 MiB, 对端上限)`。
- 对端上限为 0：视为未声明，不放宽本地硬上限。
- Android 同时约束 `HostHello.resource_limits` 和
  `SessionAccepted.negotiated_resource_limits`，取三个非零约束的最小值。
- MacHost 从 `ClientHello.resource_limits` 计算结果，并在 `HostHello` 与
  `SessionAccepted` 中回告同一协商值。
- Offer 的 `byte_length`、实际 Content 大小和发送前本地快照均受该上限约束。

## 主流程

```text
发送方                                接收方
  用户点击发送
  读取一次系统剪贴板
  缓存 bounded snapshot
  -------- ClipboardOffer ----------> 校验并 stage 最新 Offer
                                        用户点击获取
  <------- ClipboardRequest ---------- 记录一次 pending Request
  从缓存 snapshot 构建正文
  -------- ClipboardContent --------> 精确校验 Offer/Request
                                      写入系统剪贴板
```

收到 Offer 绝不自动发 Request。solicited Content 只有在以下条件全部满足时才
交给 UI 写入：

- change ID 正是用户批准且仍 pending 的 Request；
- origin、MIME、长度和 digest 与原 Offer 精确一致；
- Content 自身大小、严格 UTF-8 和重新计算的 digest 均合法；
- 当前会话 epoch 和 UI owner / generation 仍有效。

## Direct Content

无匹配 pending Request 的合法 Content 被标记为 direct：

- 协议核心仅返回已验证数据，不写系统剪贴板；
- UI 不允许不同 ID 的 direct Content 抢占已批准 Request 或更新 Offer；同一
  ID 的迟到正文可在 core 超时与 UI 清理之间接管该槽，但仍显示 direct 覆盖
  确认，绝不自动写入；
- 用户确认后才写入；取消则丢弃；
- 用户确认前不加入 seen change-ID 历史，因此之后同 ID 的合法 Offer 仍可进入
  Offer → Request → Content 主流程。

## Request 语义

- `change_id` 长度错误属于畸形消息，fail-closed。
- 格式合法但 unknown、被新 Offer 替换或 snapshot 已消费的 Request 是已认证
  no-op，不发送正文，也不拆掉健康视频会话。
- snapshot 只响应一次；不会为 Request 重新读取系统剪贴板。

## 有界会话状态

| 平台 | 实际状态 | 上限与策略 |
| --- | --- | --- |
| Mac core | `localSnapshot` | 1；新发送替换旧快照，首次响应后 consumed |
| Mac core | `pendingOffers` | 1；新 Offer 淘汰旧 Offer，并清除对应旧 Request |
| Mac core | `pendingRequests` | 1；最新优先，同 ID 重复请求拒绝 |
| Mac core | `seenChangeIDs` | 128；FIFO |
| Mac UI | `pendingTransfer` | 1；不同 ID 的 Offer 优先于 direct Content，换代/断开清除 |
| Android core | `offeredClipboard` | 1；新发送替换旧 snapshot，响应一次后清除 |
| Android core | `receivedClipboardOffer` | 1；新 Offer 替换旧 Offer 并清除旧 Request |
| Android core | `requestedClipboardChangeId` | 1；同 ID 在途时不重复发送 |
| Android core | `clipboardSeenChangeIds` | 128；FIFO |
| Android UI | `ClipboardApprovalState` | 绑定 exact owner + generation；不同 ID 的 Offer 优先于 direct Content |

DisconnectNotice、ProtocolError、transport disconnect、owner replacement 或 Host
teardown 都会清理相应会话/UI 状态。

Android 与 Mac UI 都为已发送的 `ClipboardRequest` 设置 10 秒有界等待。超时只在
exact owner / generation / change ID 仍有效时撤销批准并恢复同一 Offer 的重试入口；
Android 的协议状态清理与原 Request 走同一 reliable FIFO。超时后才到达的正文不再
视为 solicited，而是降级为 direct Content，仍需二次覆盖确认。

## MacHost 边界

- `ProtocolV1SessionCoordinator` 负责能力、epoch、字段、origin、UTF-8、大小、
  digest、Offer/Request 关联和 bounded state，只产出 action。
- `StreamingServer` 在 network queue 串行调用会话核心，并将已验证 Offer /
  Content 连同 connection generation 转发到 main actor。
- `AppDelegate.performSessionCallback` 再校验启动 token、server identity 和
  generation。
- `ClipboardUIController` 管理菜单、LAN 警告、request-in-flight 和显式确认。
- `NSPasteboardClipboardAdapter` 是唯一系统 pasteboard 边界；它是
  `@MainActor`，每次读写都断言主队列。Protocol 层不直接操作 pasteboard。

## Android 边界

- `ProtocolV1Session` 负责纯 Kotlin 会话规则和 wire envelope。
- `StreamClient` 通过现有可靠有序的 control scheduler 发 Offer / Request /
  Content，并在旧连接 epoch 上拒绝投递回调。
- `ClipboardApprovalState` 使用 StreamClient 对象身份与 generation 双重绑定，
  防止重连后的旧批准覆盖新会话。
- `MainActivity` 仅在用户菜单动作中访问 `ClipboardManager`，并为已批准 Request
  安排 10 秒 exact owner / generation / change-ID 超时。可信 LAN 的发送、
  获取和 direct 覆盖显示明确风险确认。
- 控制按钮为 48dp，具备普通/pending `contentDescription`、tooltip 和 pending
  可访问性公告；这属于离线实现，不等同于 TalkBack 真机证据。

## 反馈循环与错误

- 本地主动发送的 ID 和通过 solicited 流程接受的 ID 进入 bounded seen 历史。
- 同一 ID 从对端以 Offer 或 Content 回送时按反馈循环 fail-closed。
- direct Content 在确认前不写 seen 历史。

| 条件 | 行为 |
| --- | --- |
| 未协商能力 | UI 隐藏/禁用；本地 API false；peer payload fail-closed |
| 非 streaming 状态发送 | 本地 API false / 空 action，不发送 |
| 非法 MIME、ID、digest、UTF-8、大小或 origin | fail-closed，不写入 |
| session ID / epoch 不匹配 | unauthorized / protocol failure，不写入 |
| solicited metadata 不匹配 | fail-closed，不降级为 direct |
| direct Content | stage，二次确认后才覆盖 |
| 合法 unknown / consumed Request | 静默 no-op |
| queue admission / pasteboard 写入失败 | UI 显式反馈，不伪造成功 |

## 范围隔离

本候选不改共享 proto、iOS、HarmonyOS、音频或文件路径，也不接入 Internet
record layer。
