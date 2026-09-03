# Reconnect Timing CLI Fixtures

These fixtures exercise `vibescreen_evidence.reconnect_timing` parser and gate
logic only. They are synthetic inputs, not device acceptance evidence, and must
not be used to claim the Phase 1 reconnect timing gate.

- `synthetic-complete-observations.json`: contains all three required disruption
  shapes with consistent timestamps, stable Host PID fields, and LAN
  secure-record markers. Every attempt is still marked as synthetic, so the
  checker must return `verdict=blocked` and `can_close_timing_gate=false`.
