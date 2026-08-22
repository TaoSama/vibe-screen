# Clipboard Observations

## Observed

- Android device identity was observed as Nubia P0110 / pacific / Android 16 / SDK 36.
- The focused instrumentation test wrote and read back the marker
  vs-clipboard-device-1787249745010 through Android's system ClipboardManager
  while MainActivity was in the foreground.
- The Android app and androidTest APK installed successfully on
  EP0110PZ0B9110300B.
- The current-branch Host preflight failed before a cross-device clipboard run
  because the local keychain lacks the stable Vibe Screen Dev signing identity.

## Not Observed

- No current-branch MacHost Protocol v1 session reached clipboard negotiation.
- No macOS NSPasteboard read or write was observed in this run.
- No Android -> Mac clipboard marker was transferred and confirmed with pbpaste.
- No Mac -> Android clipboard marker was transferred and confirmed on Android.
- No TalkBack behavior, trusted-LAN warning text, or long-session clipboard
  stability was tested.

## Conclusion

This attempt improves Android-side device evidence but remains blocked for the
Android ClipboardManager <-> macOS NSPasteboard E2E gate.
