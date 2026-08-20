# Android + macOS Clipboard Device Acceptance Runbook

This runbook closes only the Android ClipboardManager <-> macOS NSPasteboard
Protocol v1 clipboard gate. It is a short interactive USB or trusted-LAN check,
not a soak, latency, or accessibility pass.

## Preconditions

- Use the Android acceptance device only after acquiring
  /tmp/vibe-screen-device-android.lock. If the lock already exists, do not run
  ADB, start or stop the app, change reverse mappings, or probe the host port.
- Record the exact device identity before installing or launching anything. For
  the current shared device, expected identity is Nubia P0110 / pacific /
  Android 16; do not relabel it as Xiaomi 13/fuxi evidence.
- Use an identity-signed MacHost build that can run Protocol v1 and has the
  normal Screen Recording and Accessibility permissions needed for the stream.
- Use non-sensitive clipboard strings created specifically for the test. Do not
  capture personal pasteboard history, pairing tokens, Wi-Fi credentials, or
  private screen content.

## Evidence Directory

Create one run directory under:

    docs/changes/2026-08-16-android-macos-clipboard/evidence/YYYY-MM-DD-device-clipboard-<result>/

Keep at least:

- commands.txt: exact commands, start/end timestamps, branch, commit, and lock
  owner.
- device-info.txt: adb devices -l, serial, manufacturer, model, codename,
  Android release, SDK, and build fingerprint.
- android-logcat-clipboard.txt: focused app logcat covering connection,
  capability negotiation, clipboard send/request/content actions, and
  disconnect.
- android-diag-clipboard.txt: private app diagnostic log when run-as can read
  it.
- host-clipboard.log: MacHost log lines for connection generation,
  clipboardAvailable=true, Offer/Request/Content handling, and pasteboard
  write/read outcome.
- observations.md: human-visible Mac and Android clipboard values before and
  after each transfer.

## USB Procedure

1. Acquire /tmp/vibe-screen-device-android.lock and record the lease contents in
   commands.txt.
2. Record device identity using explicit -s <serial> ADB commands.
3. Build and install the debug Android client, then configure USB reverse:

       cd baseline/AndroidClient
       ./gradlew --no-daemon assembleDebug
       adb -s <serial> install -r -t app/build/outputs/apk/debug/app-debug.apk
       adb -s <serial> reverse tcp:54321 tcp:54321

4. Start the current MacHost build and the Android app. Wait for a Protocol v1
   streaming session whose logs show clipboard capability negotiated on both
   peers.
5. Android -> Mac:
   - Set the Android clipboard to a unique ASCII marker, for example
     vs-android-to-mac-<timestamp>.
   - Use the Android clipboard menu to send/share the clipboard to the Mac.
   - On the Mac status menu, choose the receive action for the offered Android
     clipboard.
   - Verify pbpaste equals the Android marker, and record the visible UI/log
     evidence.
6. Mac -> Android:
   - Set the Mac pasteboard to a distinct ASCII marker with pbcopy.
   - Use the Mac status menu to share the Mac clipboard.
   - On Android, use the clipboard menu to receive the offered Mac clipboard.
   - Verify the Android clipboard equals the Mac marker through the app-visible
     clipboard state or a controlled test text field, and record the visible
     UI/log evidence. If ADB clipboard inspection is not available on the OS,
     document the visible app/text-field confirmation instead.
7. Disconnect cleanly, remove reverse mapping if this run created it, stop the
   test apps, and release the lock.

## Trusted LAN Delta

Run the same two directional transfers over the trusted-LAN Protocol v1 path.
For every send/request/direct-overwrite action, record the exact warning or
confirmation text shown by the tested build and that the user explicitly
approved it. Keep the claim scoped to that build and transport; do not reuse LAN
clipboard evidence as Internet E2EE evidence.

## Pass Criteria

- The evidence names the real Android device identity and transport.
- Both peers negotiated clipboard capability in the same Protocol v1 session.
- Android -> Mac proves Android ClipboardManager was read only after the Android
  user action and macOS NSPasteboard was written only after the Mac receive
  action.
- Mac -> Android proves macOS NSPasteboard was read only after the Mac user
  action and Android ClipboardManager was written only after the Android receive
  action.
- Logs and observations show exact marker values, matching change IDs, no
  session teardown, and no background automatic clipboard polling or overwrite.

## Blocked Evidence

If any precondition fails, keep the gate open and commit a blocked evidence
record instead of running partial ADB operations. Common blockers are an existing
device lock, unavailable Android device, missing host permissions, missing
Protocol v1 clipboard negotiation, or inability to observe either system
clipboard write.
