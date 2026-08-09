# 主机 RSS 两小时增长排查（进行中）

## 背景

Phase 1 目标之一是「两小时内无延迟或内存增长」。2026-08-09 在 Xiaomi Fuxi
（8a023e3a，Android 16，USB）完成了首个带真机流遥测的有效 2h soak，证据见
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

## 复现与下一步（需可中断当前会话）

若修复后的短时 heap 差分仍出现持续增长，再以分配栈日志重启主机并采样：

```bash
# 关闭当前 Telemachus 后，带分配栈日志启动（会重置会话与 TCC 无关）
MallocStackLogging=1 MallocStackLoggingNoCompact=1 \
  "/Applications/Vibe Screen.app/Contents/MacOS/Telemachus" &
# 建立 adb reverse + 客户端连接，稳定流 10–15 分钟后：
/usr/bin/malloc_history <pid> -allBySize | head -60   # 按大小聚合分配栈
/usr/bin/heap <pid> | head -60                         # 按类聚合存活对象
# 两次间隔采样对比 MALLOC_SMALL 中增长最快的分配栈/类。
```

复测判据：先跑 10–15 分钟短时流，确认 Observation 对象计数与 host RSS 斜率不再
持续上升；通过后再跑完整 2h soak。只有后半程 RSS 斜率进入工具规定的无增长容差，
且流与客户端指标继续通过，才关闭 Phase 1 门禁。若仍增长，再检查按帧/秒累积且
未逐出的集合、按 generation/epoch 键控的表，以及保留 CMSampleBuffer、
CVPixelBuffer 或 NSData 的路径。

## 状态

- 已记录 pitfall（见 docs/pitfall/index.md）。
- 已完成不中断会话的 heap 类型与引用链归因，并实现针对 SwiftUI Observation
  高频失效的候选修复。
- 修复尚未装入当前运行进程；待授权重启后执行短时 heap 差分与完整 2h soak。
