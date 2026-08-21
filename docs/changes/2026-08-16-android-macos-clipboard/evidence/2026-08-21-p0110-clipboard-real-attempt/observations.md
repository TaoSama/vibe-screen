# Clipboard Observations

## Observed

- The device lock was held for `EP0110PZ0B9110300B` before device operations.
- The device identity was recorded as Nubia P0110 / pacific / Android 16 / SDK
  36 with fingerprint
  `nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys`.
- `adb -s EP0110PZ0B9110300B reverse --list` showed
  `UsbFfs tcp:54321 tcp:54321`.
- `/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen` was listening on
  `127.0.0.1:54321` as PID `92943`.
- The Android foreground instrumentation helper wrote marker
  `vs-android-to-mac-1787303772` to Android `ClipboardManager` and returned
  `OK (1 test)`.
- Android diagnostics reached USB Protocol v1 streaming and recorded
  `SC: Protocol v1 upgrade accepted`.
- The same diagnostics recorded negotiated capabilities without
  `CAPABILITY_CLIPBOARD` and the promoted binding as `clipboard=false`.
- The revealed Android control bar showed `Window actions`, `Settings`, and
  `Disconnect`, with no `controlClipboardButton`.
- The installed Host binary hash differed from the current locally built release
  binary hash.
- Current-branch Host preflight failed because the local keychain lacks the
  stable `Vibe Screen Dev` signing identity.
- Wailmer/cliclick Mac UI automation was not permission-ready for status-menu
  interaction.

## Not Observed

- No same-session `CAPABILITY_CLIPBOARD` negotiation was observed.
- No Android `clipboard=true` session binding was observed.
- No Android `controlClipboardButton` was visible after the control bar was
  revealed.
- No Android -> Mac clipboard send/receive action was executed.
- No Mac `pbpaste` value equal to `vs-android-to-mac-1787303772` was observed.
- No Mac -> Android clipboard share/get action was executed.
- No Android clipboard value equal to `vs-mac-to-android-1787303772` was
  observed.
- No trusted-LAN clipboard warning/approval, TalkBack announcement, or long
  session clipboard stability behavior was tested.

## Conclusion

This run reached a real Nubia P0110 USB Protocol v1 streaming session, but the
session did not negotiate clipboard capability. The Android `ClipboardManager`
<-> macOS `NSPasteboard` gate remains blocked until a current-branch,
stable-signed, permissioned Host produces a session with clipboard capability
and both marker directions are observed through explicit user actions.
