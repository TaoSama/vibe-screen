# 2026-08-09 Xiaomi Fuxi 两小时 soak 结论（v2，真机带流遥测）

- 设备：Xiaomi fuxi（Android 16，USB，serial 8a023e3a），交流供电，全程 100% 电量。
- 主机：Telemachus.app（pid 27437），运行中未重启；未以 VIBE_SCREEN_TELEMETRY_PATH 启动，故沿用既有做法：用 host_log_telemetry.py 把主机已打印的 Pipeline 日志行忠实再编码为 stream_stats 遥测（非合成数据）。
- 窗口：2h（240 个 30s 采样），run_id=xiaomi-fuxi-8a023e3a-2h-v2。

## 判定：两小时「无增长」门禁仍未关闭（主机 RSS 净增加）

- 连接性/稳定性：240/240 采样全部 connected、主机进程存活、reconnect_count=0。
- 流质量：host-stream-telemetry.jsonl 共 110 条 stream_stats；fps 区间 54.1–61.0（绝大多数 60.0）。其中 2 个采样点报告了丢帧（第 67 行 6 帧、第 70 行 19 帧，合计 25 帧），其余 108 点为 0；两次丢帧与主机日志 1 MiB 轮转窗口相邻，属短暂重配/轮转抖动，占约 2h × ~60fps ≈ 432,000 帧的 ~0.006%。soak_report 的精确窗口口径在 reported_dropped_frames 上取每采样区间增量并对首样本做差分处理，得到 sum=0 与 109 条计数，与原始 110 条/累计 25 帧属不同口径，二者均如实记录，不据此宣称「零丢帧」。
- 客户端内存（PSS）：first 88286 KiB → final 77621 KiB；full-window 斜率 +6.1 KiB/min，second-half −15.0 KiB/min（平/降，无泄漏迹象）。
- 主机内存（RSS）：first 499856 KiB → final 518144 KiB，min 498960 / max 519312（序列含小幅回落，非严格单调），净增加约 +18.3 MB（约 +3.7%）；full-window 斜率 +191.2 KiB/min，second-half 仍为 +96.5 KiB/min（约 +5.8 MB/h），后半程无平台期。
- 因此 Phase 1「两小时内无内存增长」目标对主机侧未达成：真机流稳定、客户端内存稳定，但主机 RSS 仍持续净增长，需作为独立的主机内存增长根因排查项跟进。/usr/bin/leaks 仅报告 20 处共 ~4.3KB 未引用泄漏，说明增长来自仍可达的、随时间累积的小对象（MALLOC_SMALL），而非经典泄漏；精确归因需以 MallocStackLogging 重启主机（会中断当前会话），故留待后续排查。

## 已知局限

- derivation_status: partial：再编码器只重塑 Pipeline 行，不产生 heartbeat_received 事件，故精确窗口派生为「描述性证据」，非形式化 no-leak 判定。
- 主机日志 1 MiB 轮转期间存在短暂无新 Pipeline 行，时间线出现三处约 180s 间隔（soak_report 报 maximum_interval≈180.04s）；再编码器按设计只在行变化时记录，避免伪造遥测运动。
- 电池 sysfs（power.current/voltage/charge）读取被设备权限拒绝，产生 960 条 power.* 采样错误；与内存/无增长判定无关。

## 复现

派生报告：
```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.soak_report \
  --summary summary.json --samples samples.jsonl \
  --host-telemetry host-stream-telemetry.jsonl --output soak-report.json
```

## 原始文件

- samples.jsonl（240）、host-stream-telemetry.jsonl（110 条 stream_stats）、summary.json、soak-report.json、soak.stdout.log、host_telemetry.stdout.log。

