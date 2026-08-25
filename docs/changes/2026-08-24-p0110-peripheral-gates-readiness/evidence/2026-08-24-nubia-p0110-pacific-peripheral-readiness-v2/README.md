# P0110 peripheral gate readiness: blocked

Date: 2026-08-24

Evidence collection baseline: `origin/main` at
`6bcf185094bb2a9c77abb7c642833b7ac03b5835`. The PR was later replayed and
reverified on `origin/main` at
`32798e81bbb84e2155905a8e08ea7cc7c1ff8e46`, then again on `origin/main` at
`0ed49b5fd3b28f8504d2ea25747b176ca4971414`, and again on `origin/main` at
`8fcec1d95dbac1b41a587522f987f3890281a3ec`, then again on `origin/main` at
`d3c18962837b795e3069e8652ea8fa4111b6df8a`, then again on `origin/main` at
`549aa048d94e5131eb9f691a49a19a427fe2fe30`, then again on `origin/main` at
`fd15e0187bee7bd83b2d3938e301c2297bad4b5d`.

Device identity: `nubia P0110 / pacific / Android 16 / SDK 36`; the published
ADB serial is redacted as `<device-serial>`. This package is not Xiaomi/fuxi
evidence.

## Conclusion

This package does not close any README peripheral gate. It records current-base
readiness and fail-closed outcomes for the P0110 substitute device.
During the refreshed collection window, `/Applications/Vibe Screen.app` was
listening on `127.0.0.1:54321`, `adb reverse` still mapped `tcp:54321`, and
the Android app process was running. Those facts establish an active local
session context only; they do not substitute for physical HID, physical stylus,
or stable signed/TCC-ready Host evidence.

| Gate | Summary | Verdict | Blocking evidence |
| --- | --- | --- | --- |
| Physical stylus drawing app | `physical-stylus/stylus-summary.json` | `blocked` | Stylus-capable `goodix_stylus_input` is present, but no physical stylus drawing, stable signed/TCC-ready Host proof, Host stylus injection excerpt, or visible macOS drawing-app output was captured. |
| Native pointer HID mouse | `native-pointer-hid/native-pointer-hid-summary.json` | `blocked` | No external Android mouse/touchpad/trackball source is attached; stable signed/TCC-ready Host proof is absent. |
| Hardware keyboard workflow | `hardware-keyboard/hardware-keyboard-summary.json` | `blocked` | No external Android hardware keyboard source is attached; the current Host TCP listener was observed, but macOS Host preflight did not establish stable signing/TCC readiness. |

Synthetic `adb input` commands are not accepted as physical stylus, mouse HID,
or hardware-keyboard evidence.

## Artifacts

- `raw-adb/`: device identity and raw input snapshot collected with an explicit
  `adb -s <device-serial>` target.
- `physical-stylus/`: stylus capability collector output and gate summary.
- `native-pointer-hid/`: native pointer HID collector output and gate summary.
- `hardware-keyboard/`: hardware keyboard readiness, Host preflight artifacts,
  and gate summary.
- `SHA256SUMS`: checksum manifest for this package.

## Next Required Evidence

Closing these gates still requires the missing physical hardware plus a stable
signed/TCC-ready Host run with retained Android forwarding logs, Host injection
logs, and visible Mac-side output for the exact workflow under test.
