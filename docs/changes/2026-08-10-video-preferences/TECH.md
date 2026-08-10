# Protocol v1 视频偏好热更新稳定性

## 问题

2026-08-10 在 Xiaomi 13（2211133C、fuxi）真实 USB 会话中点击 `Sharp`
后，Host 先记录 `VideoToolbox encode callback failed: -12903`，随后因 malloc
检测到无效释放而以 `SIGABRT` 退出。客户端进入传输重试循环。

当时的偏好路径在 MainActor 上执行
`CompleteFrames -> Invalidate -> Create`，同时帧起搏器仍在 encode queue 上向同一
`VTCompressionSession` 提交帧。一次请求还会同步触发 `@Published` observer，再由
请求处理器显式重配，造成重复销毁/创建并放大竞态窗口。重建失败没有返回值，Host
仍会向客户端确认 `accepted=true`，可能形成“旧会话已失效、客户端却收到成功”的
黑屏状态。

## 修复

- 码率、质量、期望帧率和 GOP 帧数均使用 VideoToolbox 标记为 read/write 的属性，
  现在通过 `VTSessionSetProperty` 在现有会话上原地更新，不再为偏好变化销毁会话。
- `encode`、属性事务和 teardown 共享 session lock；属性更新逐项记录旧值，任一设置
  失败就逆序回滚并返回 `false`。
- 每帧上下文改为 retained class，由同步提交失败或异步 callback 中恰好一方消费，
  不再手工 allocate/deinitialize/deallocate 裸指针。
- 一次客户端请求先作为单个编码器事务应用；成功后才更新 `DisplaySettings`、调整
  capture pacer 并确认协议。同步 observer 在该事务期间被抑制，避免重复应用。
- 编码器拒绝时调用协议既有的 `accepted=false` 路径，保留当前 epoch、配置和流，
  不 renegotiate，也不 teardown。
- 编码器成功后，AppDelegate 在同一个 MainActor 提交点更新下一会话的视频速率
  seed；异步协议 completion 不再写 seed，因此 superseded token 或旧连接 completion
  无法污染重连配置。
- 成功提交同时更新 `DisplaySettings` 的码率、质量和帧率；这些属性由 Host 写入
  `UserDefaults`。Android 只保存 Host 确认后的数值用于设置界面，不在新会话主动
  replay。这样由 Host 作为编码器配置的唯一权威，避免 preset 与显式 bitrate 的
  优先级冲突，也避免每次连接产生一次无意义重配。当前真机证据只覆盖 Host 进程
  不变时的 Android-only restart；Host 重启后的恢复仍需单独设备证据。
- 显示选择和视频偏好回调直接在 MainActor 上按主队列 FIFO 同步执行，移除了额外的
  unstructured `Task` hop，连续请求不会逆序覆盖 encoder、settings 或 seed。

## 离线证据

- `swift build -c release`：通过。
- `make baseline-macos-self-test`：Host、Transport、Reliability、Protocol v1 与新增
  VideoEncoder self-test 全部通过。
- 新增 self-test 用合成 NV12 帧并发执行 120 次硬件编码提交和 24 次
  Sharp/Smooth/FPS 热更新；累计重复 30 次未出现新增 `-12903`、提交失败或 malloc
  错误。加强后的 10 次运行每次收到 112–120 个异步编码 callback。
- AddressSanitizer 与 ThreadSanitizer 下的同一并发 self-test 均通过。
- Android `testDebugUnitTest lintDebug assembleDebug`：通过。
- 独立代码评审未发现阻断问题；session 生命周期、回滚、observer 抑制与帧率应用
  顺序均成立。

这些结果证明源代码和本机 VideoToolbox 并发路径。下面的 Xiaomi 13 记录补充真实
主会话证据。

## 真机证据

2026-08-10 在 Xiaomi 13（2211133C、fuxi、ADB `bac5b092`）真实 USB
Protocol v1 会话中完成：

- Smooth、Balanced、Sharp、Auto 分别映射 Host LOW、MEDIUM、HIGH、ULTRALOW；
- 30 FPS 后恢复 60 FPS，低/中/高码率均在原会话内生效；
- 最终产物上 5 Mbps 为 epoch 2、50 Mbps 为 epoch 3；仅重启 Android 后，
  新会话 epoch 1 仍收到 50 Mbps / 60 FPS；Host PID `24536` 全程不变；
- 无 `-12903`、malloc、配置拒绝或 transport teardown，重配后持续出帧；
- 从零执行 30 分钟短测：60/60 样本 connected、60/60 进程存活、0 reconnect、
  0 sample error。精确窗口 1,476 条 stream stats，平均 59.93 FPS、平均帧龄
  5.87 ms、Host 报告 350 个丢帧；Host RSS 93,728 -> 64,240 KiB，客户端
  PSS 78,631 -> 76,682 KiB，后半段斜率均为负。

证据位于
[`evidence/2026-08-10-xiaomi13-bac5b092-30m`](evidence/2026-08-10-xiaomi13-bac5b092-30m/README.md)。

## 剩余门禁

单次真机验证总时长不得超过 30 分钟。本次短测不替代正式两小时 Host RSS
no-growth 门禁；该门禁仍保持 open。精确报告也因主会话没有
`heartbeat_received` 事件而标为 `partial` derivation，只用于描述趋势。
