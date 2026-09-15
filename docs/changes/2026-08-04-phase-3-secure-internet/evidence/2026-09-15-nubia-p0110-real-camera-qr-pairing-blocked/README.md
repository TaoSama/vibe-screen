# Nubia P0110 real-camera QR pairing blocked record - 2026-09-15

This package records a fail-closed no-Host attempt to exercise the Android
Internet pairing flow through the real rear-camera CameraX ImageAnalysis and
ZXing QRCodeReader path. It is blocked evidence, not a pairing pass.

## Result

- Source/base commit: `9511483bdcc2dad9289a331b09c98f4586f26657`; the
  runner output intentionally records runtime facts only.
- Device: Nubia P0110, codename pacific, Android 16, API 36.
- Device serial: <redacted>
- MacHost: not started; TCP 54321 had no listener.
- ADB reverse: absent before and after the run.
- Camera permission: granted; the product scanner activity launched.
- QR decode: blocked. The fixed phone camera did not face the Mac display, so
  CameraX/ZXing produced no decode marker before the 60-second timeout.
- Pairing request, strict lease import, local revoke, and secure dialogs: not
  reached and not claimed.

The retained failure summary is bound to the instrumentation log SHA-256 in
blocked-result.json. The raw instrumentation log, QR offer, lease, and
credential material are not retained in this repository.

## Verified supporting gates

- Focused runner tests: 43/43 passed on macOS; Linux retains the cross-platform
  source contract and skips the three AppKit/CoreImage runtime probes.
- Full Python script suite: 479/479 passed on macOS.
- Android JVM/build gates passed: focused contracts, release Kotlin compile,
  debug instrumentation APK assembly, lintDebug, and baseline Android tests.
- Device teardown passed: application and test processes stopped, app-private
  offer/marker/ready files removed, device lock removed, no ADB reverse mapping,
  and no TCP 54321 listener.

## Evidence boundaries

This run proves that the fail-closed harness can launch the product scanner on
a real Nubia P0110 without MacHost, ADB reverse, or macOS Screen Recording,
Accessibility, or Microphone permissions. It does not prove a successful QR
decode, pairing acceptance, lease import, revoke, production Authority profile
issuance, public Internet transport, Host-backed media, Xiaomi 13 behavior, or
Phase 3 release readiness.

The blocker is physical: the mounted device camera must be pointed at the Mac
QR window for the product camera path to observe the code. Injecting an
ActivityResult, calling the analyzer directly, or bypassing CameraX/ZXing would
not satisfy this gate and is intentionally prohibited by static contracts.

## Artifacts

- blocked-result.json: sanitized runner-shaped blocked result; supporting gate
  results and claim boundaries are recorded separately in this README.
- commands.txt: reproducible commands with the device serial redacted.
- privacy-scan.json: repository evidence privacy scan.
- SHA256SUMS: package integrity manifest.
