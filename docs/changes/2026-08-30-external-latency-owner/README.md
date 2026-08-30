# 2026-08-30 external latency current-base fail-closed owner

这个 change 记录 external latency gates 的 current-base fail-closed owner
边界，并新增只读回归测试，确保 README 中这三个 profile 和
`phase1-reconnect-within-3s` 在缺少可审计真实测量包时不会被误标为 pass：

- `usb-glass-to-glass-sub50`
- `lan-glass-to-glass-sub80`
- `input-p95-sub50`

## 状态

截至 2026-08-30 origin/main `fe58cb6715cf203405820bd0eab352d0a93f56d9`，
仓库内没有可关闭 USB/LAN glass-to-glass 的外部相机 raw recording、annotated
samples、formal manifest 和 profile-specific transport 证据；也没有可关闭
input P95 的 external-camera 或 synchronized-clock physical-input 证据。
`docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-28-nubia-p0110-latency-current-base-blocked`
中的 `latency-preflight.json` 仍报告三个 profile 均为 `status=blocked`，
`can_close_performance_gate=false`。

`phase1-reconnect-within-3s` 同样保持 blocked：
`docs/changes/2026-08-21-phase1-reconnect-timing/evidence/2026-08-28-p0110-usb-reconnect-current-base-blocked/reconnect-timing-summary.json`
报告 `verdict=blocked` 且 `can_close_timing_gate=false`，三个 required
disruption scenarios 均未完成。

## Owner 边界

本 change 只做 fail-closed owner 维护，不声称任何 latency 或 reconnect pass：

- 只读扫描仓库中是否有真实 camera latency evidence 文件，不允许把 fixture
  evidence、telemetry stage、decoder timing 或静态 summary 当成外部 latency
  pass。
- 校验 current-base preflight/reconnect blocked artifact 仍存在且
  can-close 字段为 false。
- 没有运行外部相机录制，没有同步时钟测量，没有真实 LAN/transport 运行。
- 没有执行 `/usr/bin/sfltool dumpbtm`；相关 sfltool 检查仅允许
  `pgrep -x sfltool || true`。

## 验证

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m unittest tools.tests.test_external_latency_current_base -v
```

同时可继续运行既有 latency/reconnect 单元测试确认工具本身没有回退：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m unittest tools.tests.test_latency_preflight -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m unittest tools.tests.test_reconnect_timing -v
```
