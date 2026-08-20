# Native pointer HID acceptance: blocked

Created: 2026-08-20T11:04:35Z
Reason: No external Android input device with MOUSE, TOUCHPAD, or TRACKBALL source is currently attached.
Device: nubia P0110 / pacific / Android 16 / serial EP0110PZ0B9110300B
External mouse devices: 0
Observed pointer events: none

## Scope

This was a hardware preflight for the native pointer HID mouse gate on the
connected Nubia P0110 (`pacific`) running Android 16. It was run under the
Android device lock and used only `adb -s EP0110PZ0B9110300B`.

The run did not attempt synthetic `adb shell input mouse` motion. Synthetic ADB
input can exercise parts of Android dispatch, but it cannot close the README
native pointer move/click gate because it does not prove physical HID hover,
button press, or release delivery to the foreground streaming view.

## Artifacts

- `result.json`: structured device identity, required pointer events, and
  blocked result. The normalized `move`, `press`, and `release` keys describe
  the acceptance events required for a future pass; this record did not observe
  Host-log-only pointer injection or a visible Mac pointer/button result.
- `dumpsys-input.txt`: raw Android input-device snapshot showing no external
  `MOUSE`, `MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL` source.

## Re-run

Attach a real USB or Bluetooth mouse to `EP0110PZ0B9110300B`, start a matching
Protocol v1 Vibe Screen session, then run:

```bash
python3 scripts/native_pointer_hid_acceptance.py \
  --serial EP0110PZ0B9110300B \
  --host-log "$HOME/Library/Logs/Telemachus/telemachus.log" \
  --visible-result-note "Mac cursor moved and the primary click focused <target app>" \
  --evidence-dir docs/changes/2026-08-05-phase-1-android-client/evidence/$(date -u +%F)-p0110-native-pointer-hid
```

A pass requires Android `native pointer forwarded` logcat lines for `MOVE`,
`BUTTON_PRESS`, and `BUTTON_RELEASE` from the attached mouse-like source, newly
appended Host log lines for pointer `changed`, `began`, and `ended` injection,
and a visible Mac pointer/button result. The rerun writes the bounded Android
logcat window to `android-logcat-native-pointer.txt` and the bounded Host log
window to `host-log-appended.txt`. This record is blocked, not a Host-log-only
pass, does not close the native pointer HID gate, and must remain scoped to the
device identity above.
