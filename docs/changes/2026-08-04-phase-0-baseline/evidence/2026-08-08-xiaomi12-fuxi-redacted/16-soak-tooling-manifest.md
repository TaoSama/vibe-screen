# soak 工具复用与最小适配清单

## 复用的既有脚本（来自分支 codex/verify-phase0-two-hour-soak，已在工作树 tools/ 下）

- tools/vibescreen_evidence/soak.py：ADB soak 采样器（逐分钟落盘 JSONL + 原子写 summary）。本轮直接使用，未改逻辑。
- tools/vibescreen_evidence/soak_report.py + soak_public_report.py：精确窗口派生（均值/最值/线性回归斜率/间隔）。本轮直接使用，未改逻辑。
- tools/vibescreen_evidence/adb.py：无第三方依赖的 ADB 边界（identity/require_device/sample：process/memory/thermal/battery/power）。
- tools/schemas/soak-sample.schema.json：样本 schema（vibescreen.evidence/v1）。
- tools/tests/test_soak.py, test_soak_report.py, test_adb.py：单元测试。

## 单元测试是否跑通

命令：PYTHONPATH=tools python3 -m unittest -v tools.tests.test_adb tools.tests.test_soak tools.tests.test_soak_report
结果：26 passed（含新增的 USB 连接用例）。环境仅有 stdlib，无 pytest；按 tools/README.md 用 unittest 运行。

## 最小适配（仅为适配本机 USB 真机，不另起炉灶）

1. tools/vibescreen_evidence/adb.py：ADBClient.connect() 改为端点感知。
   - 原实现对任意 serial 执行 `adb connect <serial>`；对 USB 序列号 <redacted-xiaomi-adb-serial> 会失败（"failed to resolve host"），污染 environment/每样本 errors。
   - 适配：新增 _is_tcp_endpoint(serial)（判定 host:port 形态）。USB 序列号跳过 adb connect，仅 require_device() 校验就绪；TCP 端点保持原 adb connect 行为不变。
2. tools/tests/test_adb.py：
   - 将 test_connect_requires_adb_confirmation_and_ready_state 的 serial 由裸 "serial" 改为 "device.example:5555"（贴合 TCP 语义，裸串本就不是合法 adb connect 目标）。
   - 新增 test_connect_over_usb_serial_only_checks_readiness：断言 USB 序列号仅执行 get-state。

## 新增的采集辅助（复用 + 最小新增，非重写）

- tools/vibescreen_evidence/host_log_telemetry.py：把主机已经在打印的 `Pipeline: <fps>fps ... dropped:<n>` 日志行忠实再编码为 soak_report.py 消费的 stream_stats 遥测记录（schema_version=1，含 wall_time/monotonic_ns/attributes）。
  - 这是"忠实再编码器"而非数据源：不合成任何流数据；仅因运行中的主机未以 VIBE_SCREEN_TELEMETRY_PATH 启动、无法回填结构化遥测而需要。
  - CLI 使用 argparse，支持 --help；错误（读日志失败、参数非法）均已处理。

## 运行命令（可复现，设备一律 -s <redacted-xiaomi-adb-serial>）

主机流遥测再编码（后台，与采样器同窗）：
  PYTHONPATH=tools python3 -m vibescreen_evidence.host_log_telemetry \
    --log ~/Library/Logs/Telemachus/telemachus.log \
    --output-jsonl <ev>/11b-host-stream-telemetry.jsonl \
    --duration-seconds 1800 --interval-seconds 60

设备+主机 soak 采样（30 分钟）：
  PYTHONPATH=tools python3 -m vibescreen_evidence.soak \
    --serial <redacted-xiaomi-adb-serial> --duration 30m --interval 60s \
    --package dev.telemachus.display --host-pid 89286 \
    --telemetry-jsonl <ev>/11b-host-stream-telemetry.jsonl --require-stream-telemetry \
    --output-jsonl <ev>/11-soak-samples.jsonl --summary-json <ev>/11-soak-summary.json \
    --run-id xiaomi12-fuxi-<redacted-xiaomi-adb-serial>-2026-08-08-30m

派生报告：
  PYTHONPATH=tools python3 -m vibescreen_evidence.soak_report \
    --summary <ev>/11-soak-summary.json --samples <ev>/11-soak-samples.jsonl \
    --host-telemetry <ev>/11b-host-stream-telemetry.jsonl --output <ev>/12-soak-report.json
