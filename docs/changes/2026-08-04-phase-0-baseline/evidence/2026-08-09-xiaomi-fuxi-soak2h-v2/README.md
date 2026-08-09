# 2026-08-09 Xiaomi Fuxi 两小时 soak 结论（v2，真机带流遥测）

- 设备：Xiaomi fuxi（Android 16，USB，serial 8a023e3a），交流供电，全程 100% 电量。
- 主机：Telemachus.app（pid 27437），运行中未重启；未以 VIBE_SCREEN_TELEMETRY_PATH 启动，故沿用既有做法：用 host_log_telemetry.py 把主机已打印的 Pipeline 日志行忠实再编码为 stream_stats 遥测（非合成数据）。
- 窗口：2h（240 个 30s 采样），`run_id=xiaomi-fuxi-8a023e3a-2h-v2`。

## 判定：两小时「无增长」门禁仍未关闭（主机 RSS 存在缓慢上升趋势）

- 连接性/稳定性：240/240 采样全部 connected、主机进程存活、reconnect_count=0。
- 流质量：fps 均值 59.94（min 54.1 / max 61.0），reported_dropped_frames=0，frame_queue_drop_total=0，全窗口零丢帧。
- 客户端内存（PSS）：first 88286 KiB → final 77621 KiB；full-window 斜率 +6.1 KiB/min，second-half −15.0 KiB/min（平/降，无泄漏迹象）。
- 主机内存（RSS）：first 499856 KiB → final 518144 KiB（min 498960 / max 519312），单调上升约 +18.3 MB（约 +3.7%）；full-window 斜率 +191.2 KiB/min，second-half 仍为 **+96.5 KiB/min**（约 +5.8 MB/h）。后半程无平台期。
- 因此 Phase 1「两小时内无内存增长」目标对主机侧**未达成**：真机流稳定、客户端内存稳定，但主机 RSS 仍有缓慢持续上升，需作为独立的主机内存增长根因排查项跟进。

## 已知局限

- `derivation_status: partial`：再编码器只重塑 Pipeline 行，不产生 heartbeat_received 事件，故精确窗口派生为「描述性证据」，非形式化 no-leak 判定。
- stream_stats 最大间隔 180s（主机日志 1 MiB 轮转期间存在一次短暂无新 Pipeline 行；再编码器按设计跳过、只在行变化时记录，避免伪造遥测运动）。109 条 stream_stats 覆盖 2h。
- 电池 sysfs（power.current/voltage/charge）读取被设备权限拒绝，产生 960 条 power.* 采样错误；与内存/无增长判定无关。

## 复现

见同目录 `run_soak.sh` 等价命令与 `daemonize_soak.py` 双 fork 守护方式；派生报告：
```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.soak_report \
  --summary summary.json --samples samples.jsonl \
  --host-telemetry host-stream-telemetry.jsonl --output soak-report.json
```

## 原始文件

- samples.jsonl（240）、host-stream-telemetry.jsonl（109 stream_stats）、summary.json、soak-report.json、soak.stdout.log、host_telemetry.stdout.log。

