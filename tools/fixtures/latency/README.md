# Latency CLI fixtures

These fixtures are synthetic inputs for `vibescreen_evidence.latency` tests and
documentation examples. They are not device acceptance evidence and must not be
used to claim a shipped latency result.

- `usb-glass-to-glass-pass.csv`: external-camera frame deltas whose P95 passes
  `usb-glass-to-glass-sub50`.
- `lan-glass-to-glass-fail.csv`: direct latency samples whose P95 fails
  `lan-glass-to-glass-sub80`.
- `input-latency-pass.json`: JSON-wrapped external-camera input-latency samples
  whose P95 passes `input-p95-sub50`.
- `usb-glass-to-glass-insufficient.csv`: too few samples to evaluate
  `usb-glass-to-glass-sub50`; the verdict is `insufficient` and the CLI exits
  with a non-zero status.
- `telemetry-stage-informational.csv`: host telemetry-stage samples that remain
  informational and cannot close a performance gate.
