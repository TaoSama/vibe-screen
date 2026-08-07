# 30 分钟真机 soak 最终结论（Xiaomi 12 / fuxi / 8a023e3a，Android 16）

采样窗口（UTC）：2026-08-07T17:26:05Z → 17:56:05Z，1800.06s，30 样本，间隔 60s。
被测流:主机 Telemachus PID 89286、客户端 dev.telemachus.display PID 11143。
采集进程(soak.py PID 30114 / host_log_telemetry PID 30113)均已退出，无 PID 泄漏。

数据来源:11-soak-samples.jsonl、11-soak-summary.json、12-soak-report.json、12b-soak-report-public.json、13/14 快照、主机日志、客户端 VibeScreenTelemetry logcat。

## 总判定:PASS（带 1 项 CAVEAT）

30 分钟窗口内会话全程稳定、无丢帧、无热节流、无致命 codec；客户端解码侧无内存泄漏。
唯一需如实标注的 CAVEAT 是主机侧 RSS 单调上升(见下)，需在更长窗口进一步观察，本轮不下"无增长"的过强结论。

## docs/testing.md 最后一条 Pass criteria 逐项判定

1. 全程 PID 存活 — PASS
   主机 89286、客户端 11143 在窗口首(13-soak-start-snapshot.txt)与尾(14-soak-end-snapshot.txt)均存活且 PID 未变；30/30 样本 process.running=true。

2. 连接持续 — PASS
   30/30 样本 device.connected=true；summary reconnect_count=0；主机日志 ping/pong 计数 274(心跳链路持续)。

3. 帧计数单调上升 — PASS
   客户端 VD Decode stats output 由 53337(起点快照)→174237(终点快照)严格递增，dropped=0(+120,900 帧)；主机 Pipeline dropped 全程 0；fps 均值 59.95(min 59.7/max 60.2)。

4. 无致命 codec error — PASS
   主机日志 codec/fatal 计数 = 0；客户端 logcat 无 Codec error；VibeScreenTelemetry 持续输出 stream_stats(session_epoch=1)。

5. 无内存无界增长 — CAVEAT（客户端 PASS，主机 RSS 需继续观察）
   - 客户端 total PSS:first 99530 → final 96111 KiB，全窗斜率 +13.8 KiB/min，峰值(99530)即首样本，末值低于首值 → 解码侧无泄漏，PASS。
   - 主机 RSS:127248 → 146336 KiB，净增 18.6 MiB；30 个样本单调不降(29/29 步上升、0 下降)。全窗斜率 +587 KiB/min，后半窗 +1086 KiB/min;后半陡升主要来自 elapsed≈1380s 处一次台阶(136832 → 140144 → 144912，单步 +3.3/+4.8 MB)，其后仍在爬升(末 6 样本 140144→146336)。
   - 定性:这是真实、持续、单调的上升，不能仅以"30 分钟偏短 / macOS RSS 含缓存"解释掉。但 30 分钟窗口不足以区分"缓存/一次性分配后趋稳"与"线性泄漏"。因此判为 CAVEAT——需 Phase 1 两小时 gate 复核是否收敛，不下"无增长"的结论，也不据此判 FAIL。

6. thermal 受控 — PASS
   thermal status 全程 = 0(NONE，min/mean/max 均 0)；CPU 传感器窗口内最高 62.9°C 且总体走低(如 CPU7 首 62.9 → 末 40.6°C)；电池温 33.1 → 33.3°C。设备处于 USB 充电态(level 35% → 52%)，本轮不评估耗电。

## 两个 caveat 的诚实定性

(a) Host RSS 30 分钟 +18.6 MiB、后半程 +1086 KiB/min 是否构成 docs/testing.md 的 "unbounded memory growth"?
    —— 尚不能判定为 unbounded，也不能判定为无增长。事实是:主机 RSS 在 30 分钟内单调不降、末段仍在上升，存在一次明显台阶。30 分钟窗口太短，无法区分一次性分配后趋稳与线性泄漏。结论:标注为需进一步观察(WATCH/CAVEAT)，留待两小时 gate 用更长窗口的斜率是否收敛来定性。

(b) partial 状态根因 = host telemetry 未含 heartbeat_received —— 是采样完整性问题，不是真实心跳缺失，更不是流失败。
    —— 会话心跳真实存在:主机日志 ping/pong 计数 274，客户端 VibeScreenTelemetry 持续发 stream_stats(session_epoch=1)。soak_report.py 之所以判 partial，仅因本轮喂给它的 11b-host-stream-telemetry.jsonl 是由主机日志 Pipeline 行忠实再编码而成的 stream_stats 事件，其中不含 event=heartbeat_received 记录(运行中的主机未以 VIBE_SCREEN_TELEMETRY_PATH 启动、无结构化 heartbeat/session 遥测落盘)。因此 partial 是"我提供的遥测文件只含 stream_stats"这一采集完整性问题，与流健康、心跳存活无关。

## 证据文件

- 11-soak-samples.jsonl / 11-soak-summary.json：30 样本原始数据与汇总(summary status=partial 仅因 /sys 电流节点 Permission denied 的可选 power 采集失败)。
- 11b-host-stream-telemetry.jsonl：主机日志 Pipeline 行忠实再编码的 stream_stats(30 条)。
- 12-soak-report.json：精确窗口派生(均值/最值/斜率/间隔)，derivation_status=partial(仅因缺 heartbeat_received)。
- 12b-soak-report-public.json：为何未产出 privacy-minimized 公开报告的说明。
- 13-soak-start-snapshot.txt / 14-soak-end-snapshot.txt：窗口首尾 PID、Pipeline、VD Decode stats、错误计数。
- 15-soak-derived-summary.md / 16-soak-tooling-manifest.md：派生总结与工具复用/最小适配清单。
