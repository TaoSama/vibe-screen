# Nubia P0110 no-Host AV1 admission instrumentation smoke

Date: 2026-09-06
Status: PASS for device-profile probe plus product-admission fail-closed
assertions; real AV1 stream remains blocked.

## Source State

- Main baseline: `origin/main` at
  `94992a5a7f429521b85f16a0111af5e719784998`.
- Source under test: PR branch
  `codex/android-no-host-policy-av1-instrumentation-20260906` with the
  no-Host instrumentation changes applied on top of that baseline.
- Scope: Android no-Host instrumentation only. No macOS Host was started, no
  Swift command was run, no Screen Recording/Accessibility/TCC/Keychain or
  System Settings operation was performed, and no `adb reverse` was created or
  removed.

## Device Identity

- Manufacturer/model: nubia P0110
- Codename: pacific
- Android: 16
- SDK: 36
- Serial: `<redacted-device-serial>`

## Verified

`CodecAdmissionInstrumentedTest` probes the real Android `MediaCodecList`
through `AndroidDecoderCatalog.probe(MediaFormat.MIMETYPE_VIDEO_AV1, 1280, 720,
60.0)`, asserts that the P0110 run produced a non-empty AV1 decoder probe set
with at least one hardware candidate and a selected diagnostic decoder, then
verifies the product admission boundary remains closed. The run recorded these
AV1 decoder probes in logcat:

- `c2.qti.av1.decoder`
- `c2.qti.av1.decoder.low_latency`
- `c2.qti.av1.decoder.secure`
- `c2.android.av1-dav1d.decoder`
- `c2.android.av1.decoder`

The selected diagnostic decoder was `c2.qti.av1.decoder` with target-rate
support, while `CodecCapabilities.runtimeAdmissionSnapshot` still reported
`usableAv1=true` and `admission=false`. The test also asserts that AV1 is absent
from `CodecFallbackPolicy.candidates(runtimeSnapshot)`, that manually setting
`hasUsableAv1Decoder=true` and `av1FrameAdmissionEnabled=true` still leaves
`av1StreamAdmissionAvailable=false`, and that AV1 has no current USB/LAN
protocol or Internet product codec mapping.

This is device-profile and fail-closed admission evidence only. It does not prove
Vibe Screen AV1 negotiation, MediaCodec AV1 configuration, first decoded output
frame, sustained AV1 playback, reconnect behavior, or any macOS Host AV1 encoder
path.

## Command Result

```bash
cd baseline/AndroidClient
./gradlew --no-daemon :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ManagedConfigurationProviderInstrumentedTest,dev.telemachus.display.CodecAdmissionInstrumentedTest
```

Result: `BUILD SUCCESSFUL in 16s`; Gradle reported `Starting 2 tests on P0110 -
16` and `Finished 2 tests on P0110 - 16`.

See `commands.txt` and `logcat-summary.txt` for the exact sanitized command set
and retained diagnostic line.
