# Troubleshooting

## ADB cannot find the device

```bash
adb devices -l
adb connect DEVICE_HOST:5555   # only for an already-authorized ADB TCP device
adb -s DEVICE_SERIAL get-state
```

`unauthorized` requires accepting the debugging prompt on the device. `offline`
usually requires reconnecting ADB. If multiple devices are listed, always pass
`-s DEVICE_SERIAL`; never rely on the implicit first device.

## Android stays on “Waiting for your Mac”

Check all three layers:

```bash
lsof -nP -iTCP:54321 -sTCP:LISTEN
adb -s DEVICE_SERIAL reverse --list
adb -s DEVICE_SERIAL shell am start -S -W \
  -n dev.telemachus.display/.MainActivity --ez auto_connect true
```

The host must listen on `127.0.0.1:54321`, and the device list must contain
`tcp:54321 tcp:54321`. Remove only this mapping if it is stale:

```bash
adb -s DEVICE_SERIAL reverse --remove tcp:54321
adb -s DEVICE_SERIAL reverse tcp:54321 tcp:54321
```

## Host has no picture

- Grant Screen Recording to the stable-signed `/Applications/Vibe Screen.app`
  bundle and restart it through `make baseline-macos-launch` after
  `make baseline-macos-host-preflight` passes. Do not repeatedly launch a
  `.build/` binary or ad-hoc app while diagnosing permissions.
- Inspect `~/Library/Logs/Telemachus/telemachus.log` for the selected capture
  method and errors.
- If the private virtual-display API fails, select the current physical display
  or use a documented dummy-display fallback.
- Port `54321` must not already be owned by another process.

## Picture works but touch does not

Grant Accessibility to the same stable-signed `/Applications/Vibe Screen.app`
bundle and restart it through `make baseline-macos-launch` after the read-only
preflight passes. Confirm the host log does not contain
`Accessibility not granted - touch ignored`. Touch is sent only while the
Android streaming surface is active; dismiss the settings dialog before testing.

## TCC identity keeps changing

macOS privacy grants are tied to the app identity that TCC sees: the bundle id
`dev.telemachus.display`, the canonical designated requirement with signing
leaf SHA-1 `9AAE572BF6D764E3436A6109197D345B5A87998C`, the stable install path
`/Applications/Vibe Screen.app`, and the source provenance embedded in the
bundle. A rebuilt ad-hoc app, a fresh same-named certificate with a different
leaf, or a direct run from `.build/` can be treated as a different app and ask
for Screen Recording or Accessibility again. Reinstall with
`make baseline-macos-dev-install`, then use the read-only
`make baseline-macos-host-preflight` report to identify which identity field
drifted before requesting permissions again.

## Black ADB screenshot during streaming

This is expected: the Android window sets `FLAG_SECURE` while connected. Use
decoder/frame logs, on-device visual inspection, or an external camera. Do not
interpret a protected screenshot as proof that decoding failed.

## Decoder fails or freezes

Export the debug APK's private diagnostic log:

```bash
adb -s DEVICE_SERIAL exec-out run-as dev.telemachus.display sh -c \
  'cat files/diag.log.old 2>/dev/null; cat files/diag.log 2>/dev/null'
```

Look for the selected decoder, `First output frame`, frame counters, dropped
input buffers, and keyframe requests. H.264 fallback must be explicitly
negotiated; do not assume it occurred merely because the connection survived.

## LAN pairing fails

- Both devices must be on the same trusted network without VPN isolation.
- Allow the host through the macOS firewall.
- Camera permission is needed only for a new QR scan.
- Generate a fresh QR if the token was reset.
- Never paste pairing tokens into public issues or logs.

## Collect a useful report

Include operating-system versions, exact repository revision, device
manufacturer/model/fingerprint, build command, host log, Android diagnostic
log, and reproduction steps. Redact pairing tokens, Wi-Fi credentials, public
IP addresses, hardware identifiers such as ADB serials, `ro.serialno`, UDIDs,
MAC addresses, and personal screen content.
