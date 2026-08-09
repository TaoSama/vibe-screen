# 30 分钟真机 soak 派生总结（小米 13 (2211133C) / fuxi / 8a023e3a，Android 16）

- 采样窗口（UTC）：2026-08-07T17:26:05.812Z → 17:56:05.874Z，时长 1800.1s（≈30 分钟）。
- 采样间隔：60s。样本数：30 条（sample_index 0..29，soak.py 精确落盘）。
- 主机流遥测：29 条 stream_stats 记录落在窗口内，1 条早于窗口起点被派生器正确剔除。
- 设备：Xiaomi 2211133C（product lineage_fuxi），Android release 16，abi arm64-v8a。
- 主机进程 PID 89286，客户端 dev.telemachus.display PID 11143；窗口首尾两端均存活且 PID 未变（见 13/14 快照）。

## 逐指标统计（来自 12-soak-report.json，精确窗口派生）

- 连接与存活：连接样本 30/30；进程存活样本 30/30；重连次数 0。
- 帧计数（主机 Pipeline / 客户端 VD）：
  - Pipeline fps 均值 59.95（min 59.7 / max 60.2），窗口内 reported dropped 合计 0，frame_queue_drop 合计 0。
  - 客户端 VD Decode stats 单调递增：起点 output=53337 → 终点 output=174237，dropped=0（+120,900 帧，0 丢帧）。
  - 主机日志全程 codec/fatal 错误计数 = 0。
- 内存（斜率为线性回归 KiB/分钟）：
  - 主机 RSS：首 124.3 MiB → 末 142.9 MiB（min=首，max=末）。全窗斜率 +587.6 KiB/min；后半窗斜率 +1086.6 KiB/min（n=14）。
  - 客户端 total PSS：首 99530 → 末 96111 KiB（min 89537 / max 99530=首样本）。全窗斜率 +13.8 KiB/min；后半窗 +312.3 KiB/min。PSS 峰值未超过首样本，末值低于首值。
- 温度 / thermal：thermal status 全程 = 0（NONE，min/mean/max 均为 0）。CPU 传感器窗口内最高 62.9°C 且总体走低（如 CPU7 首 62.9°C → 末 40.6°C）。电池温度 33.1 → 33.3°C，基本平稳。
- 电量：USB 供电充电中，level 35% → 52%（充电，非放电 soak）。

## PASS / FAIL 判定

- 全程 PID 存活：PASS（主机 89286、客户端 11143 首尾均在，未变）。
- 连接持续：PASS（30/30 连接，0 重连）。
- 帧计数单调上升：PASS（客户端 VD output 53337→174237 严格递增，dropped=0；主机 Pipeline dropped 全程 0）。
- 无致命 codec error：PASS（主机日志 codec/fatal 计数为 0；客户端无 Codec error）。
- 无内存无界增长：客户端 PASS（PSS 末值低于首值、峰值=首样本，无泄漏迹象）；主机 RSS 为 CAVEAT（30 分钟净增约 18.6 MiB、斜率有界，但后半窗斜率翻倍 +587.6 → +1086.6 KiB/min）。有限的 30 分钟斜率无法区分平台期与泄漏，故本项对主机记为 CAVEAT 而非 PASS，需由两小时 gate 证实收敛。
- thermal 受控：PASS（thermal status 恒为 0，CPU 峰值 62.9°C 且走低）。

结论：本轮 30 分钟 soak 判定 PASS with CAVEAT——功能/帧计数/thermal/客户端内存均 PASS，唯主机 RSS 因后半段斜率上升记为 CAVEAT，两小时无增长 gate 仍为未关闭项（留待其证实是否收敛）。

## 证据文件

- 11-soak-samples.jsonl：逐分钟原始样本（30 条，schema vibescreen.evidence/v1）。
- 11-soak-summary.json：soak.py 汇总（status=partial，仅因 /sys 电流节点 Permission denied 的可选 power 采集失败）。
- 11b-host-stream-telemetry.jsonl：主机日志 Pipeline 行忠实再编码为 stream_stats（30 条）。
- 12-soak-report.json：soak_report.py 精确窗口派生报告（含均值/最值/斜率/间隔）。
- 12b-soak-report-public.json：说明为何未产出 privacy-minimized 公开报告（缺 heartbeat 遥测）。
- 13-soak-start-snapshot.txt / 14-soak-end-snapshot.txt：窗口首尾主机 Pipeline 与客户端 VD Decode stats、PID、错误计数。
- 16-soak-tooling-manifest.md：复用与最小适配说明。

## 已知局限（不夸大）

- 主机未以 VIBE_SCREEN_TELEMETRY_PATH 启动，无结构化 heartbeat/session 遥测；stream_stats 由主机日志忠实再编码而来，故 12-soak-report.json 的 derivation_status=partial（唯一原因是缺 heartbeat_received），privacy-minimized 公开报告未产出。
- 可选 power sysfs（current_now / current_avg / charge_counter / voltage_now）在该 MIUI 上 Permission denied，导致 11-soak-summary.json status=partial；不影响 RSS/PSS/thermal/帧计数等核心证据。电池处于充电态，本轮不评估耗电。
- 本轮为 30 分钟坐实；两小时无增长为 Phase 1 gate，未在本轮覆盖。
