# Protocol v1 视频偏好验证记录

## 已通过

```text
cd baseline/MacHost
swift build -c release
cd ../..
make baseline-macos-self-test
cd baseline/MacHost
swift build -c debug --sanitize=address
ASAN_OPTIONS=abort_on_error=1:halt_on_error=1 \
  .build/debug/Vibe\ Screen --video-encoder-self-test
swift build -c debug --sanitize=thread
TSAN_OPTIONS=halt_on_error=1 \
  .build/debug/Vibe\ Screen --video-encoder-self-test
cd ../AndroidClient
./gradlew testDebugUnitTest lintDebug assembleDebug
```

结果：全部通过。VideoEncoder self-test 同时覆盖活跃帧提交、码率/质量/FPS 原地
更新和异步 callback。Protocol v1 self-test 还覆盖 encoder 拒绝偏好时不发送新
VideoConfig、不推进 epoch 的契约。

## 真机验证

验证机为 Xiaomi 13（2211133C、fuxi、Android 16、ADB `bac5b092`）。最终
Host SHA-256 为
`a1a656b7c53b99e8bcf91fc3432066055c2048b64a649ad53c95c1f02663878a`，
Debug APK SHA-256 为
`3ee109d911a6acd8482cbf81cd604e0882341860828199881e05c524214d45e0`。

最终产物的可复现码率/重连序列：

```text
epoch 2: 5 Mbps / 60 FPS applied
epoch 3: 50 Mbps / 60 FPS applied
restart Android only (Host PID remains 24536)
epoch 1: 50 Mbps / 60 FPS applied
```

保留的 Host 日志还记录了 2 Mbps / 60 FPS 的原地更新。Smooth/Balanced/Sharp/
Auto 和 30 FPS 组合有离线协议/编码器覆盖，但本目录没有足以逐项复核的真机原始
日志，因此不把它们列为已保留的设备证据。

30 分钟短测命令：

```text
PYTHONPATH=tools python3 -m vibescreen_evidence.host_log_telemetry \
  --log "$HOME/Library/Logs/Telemachus/telemachus.log" \
  --output-jsonl evidence/2026-08-10-xiaomi13-bac5b092-30m/host-telemetry.jsonl \
  --duration-seconds 1800 --interval-seconds 1

PYTHONPATH=tools python3 -m vibescreen_evidence.soak \
  --serial bac5b092 --duration 30m --interval 30s \
  --package dev.telemachus.display --host-pid 24536 \
  --telemetry-jsonl evidence/2026-08-10-xiaomi13-bac5b092-30m/host-telemetry.jsonl \
  --require-stream-telemetry \
  --output-jsonl evidence/2026-08-10-xiaomi13-bac5b092-30m/samples.jsonl \
  --summary-json evidence/2026-08-10-xiaomi13-bac5b092-30m/summary.json \
  --run-id xiaomi13-bac5b092-video-preferences-30m
```

结果：60/60 connected、60/60 进程存活、0 reconnect、0 sample error；平均
59.93 FPS，Host 报告 350 个丢帧。Host RSS 93,728 -> 64,240 KiB，客户端 PSS
78,631 -> 76,682 KiB。完整记录见
[`evidence/2026-08-10-xiaomi13-bac5b092-30m`](evidence/2026-08-10-xiaomi13-bac5b092-30m/README.md)。

该 30 分钟记录只关闭本变更的短时真机回归，不关闭两小时 Host RSS no-growth
门禁。`exact-window-report.json` 因没有 `heartbeat_received` 事件保持 `partial`
derivation，内存斜率仅为描述性证据。
