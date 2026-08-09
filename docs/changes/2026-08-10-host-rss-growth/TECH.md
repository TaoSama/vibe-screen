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

## 复现与下一步（需可中断当前会话）

精确归因需以分配栈日志重启主机，并在短时流下采样：

```bash
# 关闭当前 Telemachus 后，带分配栈日志启动（会重置会话与 TCC 无关）
MallocStackLogging=1 MallocStackLoggingNoCompact=1 \
  /Applications/Telemachus.app/Contents/MacOS/Telemachus &
# 建立 adb reverse + 客户端连接，稳定流 10–15 分钟后：
/usr/bin/malloc_history <pid> -allBySize | head -60   # 按大小聚合分配栈
/usr/bin/heap <pid> | head -60                         # 按类聚合存活对象
# 两次间隔采样对比 MALLOC_SMALL 中增长最快的分配栈/类。
```

候选审查点（静态）：按帧/秒累积且未逐出的集合；每重连自增且未清理的键控字典
（如按 generation/epoch 键控的表）；保留 CMSampleBuffer/CVPixelBuffer 或 NSData 的路径。

## 状态

- 已记录 pitfall（见 docs/pitfall/index.md）。
- 排查因需中断用户实时会话而暂缓；待授权后在专门会话中执行上面复现步骤并定位根因。

