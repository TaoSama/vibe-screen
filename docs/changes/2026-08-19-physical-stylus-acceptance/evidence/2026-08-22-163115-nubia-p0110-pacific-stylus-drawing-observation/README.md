# Nubia P0110 physical stylus drawing observation

## Conclusion

- Status: blocked_physical_stylus_not_observed
- Result: The gate remains open. A physical drawing observation window was
  attempted, but no raw stylus events appeared on `/dev/input/event7`, the
  Android app diagnostic log did not contain a same-window `Stylus forwarded:`
  contact sample, and no Host `Stylus injected:` excerpt was produced.

## Device

- Manufacturer: nubia
- Model/device: P0110 / pacific
- Android: 16 / SDK 36
- Serial: EP0110PZ0B9110300B
- Fingerprint: nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys

## Attempt

The Android coordination locks were absent before this run. A short lease was
created for this task, ADB reverse was configured for `tcp:54321`, and
`dev.telemachus.display/.MainActivity` was launched on the target device. The
Host app was running at `/Applications/Vibe Screen.app/Contents/MacOS/Vibe
Screen`, with logs at `/Users/luwentao/Library/Logs/Telemachus/telemachus.log`.

During the 30 second observation window, the script required all pass evidence
from the same window: physical stylus contact, Android `Stylus forwarded:`
diagnostics, appended Host `Stylus injected:` logs with pressure and signed
tilt, and visible macOS drawing output. The pass criteria were not met.

## Evidence files

- `preflight.txt`: device identity, foreground app, ADB reverse state, Host
  process, and Host log path.
- `android-getevent-stylus.log`: raw `/dev/input/event7` capture during the
  observation window; this file contains zero lines.
- `android-getevent-stylus.err`: stderr from the raw event capture.
- `script-output.txt` and `script-stderr.txt`: acceptance script result.
- `host-stylus-search.txt`: post-window search for Host stylus injection lines.
- `android-screen-before.png` and `android-screen-after.png`: Android
  screenshots bracketing the attempt.
- `commands.txt`: exact commands and outcome summary.

## Gate rule

Do not close the physical-stylus drawing-app gate from this run. The Nubia
P0110/pacific identity and stylus-capable hardware remain readiness evidence
only until a later run captures a real physical stylus stroke, Android
forwarding diagnostics, Host stylus injection, and visible macOS drawing-app
output from the same session.
