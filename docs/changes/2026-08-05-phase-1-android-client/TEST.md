# Phase 1 Android client verification

Date: 2026-08-05
Branch: `codex/phase1-android-client-experience`
Implementation base: `6f7ffbe0be872390144899642636dbb24d89f120`

Final branch base after synchronization: `53228758722c74592b36b3f9b0b7be41ca9f5403`

## Scope and protocol boundary

This change implements the Android-only part of the Phase 1 experience without
changing Protocol v1 or the macOS host. The runnable application still uses the
legacy touch protocol.

| Capability | Implementation status | Evidence status |
| --- | --- | --- |
| Fit/fill scaling | client-local MediaCodec mode, rotated viewport container, aspect-preserving Fit surface, and crop-aware Fill mapping | eight rotation/scale corner matrices pass on JVM; Fit synthetic-device geometry passed; Fill device check pending |
| rotation | actual Surface pixel transform with 90°/270° viewport/surface dimension exchange and input inverse transform | four-direction layout/corner matrix passes on JVM; four-mode visual device check pending |
| Mac display selection | explicit touch-only capability boundary; host-selected stream shown | correctly blocked; host/session integration required |
| tap/drag/right click/scroll/pinch | existing touch path retained; secondary mouse button and wheel adapt to touch gestures | injected tap/long swipe produced touch packets; Mac result and two-finger checks pending |
| keyboard/shortcuts | common Android keys map to protocol-neutral USB HID events | HID mapping/gate passed on device; forwarding blocked by legacy host |
| external mouse/keyboard | wheel and secondary-button adapters; physical keys captured and gated | physical peripherals pending; native pointer/keyboard protocol required |
| reconnect/errors | per-session generation gates all client/decoder callbacks; typed retryability preserves failure reasons and stops protocol-error loops | stale/no-display endpoint and synthetic cold reconnect passed on device; stale-generation and ready-session failure paths pass on JVM |
| permissions/lifecycle | Camera permission is re-evaluated after returning from Settings; background pauses input/retries and keep-awake, foreground resumes/rekeys | original camera deny/settings launch passed on device; Settings-return state machine passes on JVM; post-review device rerun pending |
| outbound input | bounded single writer reserves recovery capacity, coalesces MOVE/ping/keyframe, preserves admitted touch-boundary FIFO, gracefully drains releases, and fails the session closed instead of silently losing a saturated boundary | saturation/order/write-failure/graceful-close tests pass on JVM; physical-peripheral device check pending |

No unsupported keyboard, pointer, or display-selection bytes are added to the
legacy wire format. A compatible negotiated application session remains the
gate for those controls.

## Offline evidence

The coordinated Phase 0 two-hour HEVC soak initially owned
`100.72.246.116:5555` through `/tmp/vibe-screen-device-soak.lock`. While that
lock existed, this change performed no ADB connect/install/launch/force-stop,
reverse mutation, media-port probe, or MacHost start. That soak never opened
its formal clock because the locked Mac exposed zero ScreenCaptureKit displays.
After its owner released the lock, this task acquired the coordinated short
lease as `/tmp/vibe-screen-device-android.lock`, completed the run below, then
stopped the app/test server and removed the lock.

The final clean gate completed after implementation:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug auditReleaseDependencies
```

Results:

- 114 JVM tests, zero failures/errors/skips;
- lint reported `No issues found`;
- all requested Gradle tasks completed with `BUILD SUCCESSFUL in 28s`;
- final clean-rebuild APK SHA-256:
  `1fec4cd06c728d35d52abad99ffb3a5e284af1996e0923ef9b6d10c5eaf17e67`.

The APK hash is an offline artifact identity, not install or device evidence.

## Nubia P0110 device run

The endpoint re-identified as Nubia P0110 (`pacific`), Android 16 / SDK 36,
hardware serial `[redacted]`, fingerprint
`nubia/pacific/pacific:16/2.5.2.0/20260804.003241:userdebug/test-keys`, and
1264×2800 at 560 dpi. It is not Xiaomi 12.

The device-run APK installed with `adb install -r -t` at
`2026-08-05 01:46:06 +08:00`. Its Android Debug signer certificate SHA-256 is
`b108fb9e0c8e5544171d57eb3be57d9fb93f332fc4954e26d5f51b20b876aa0b`.
Its SHA-256 was
`37e7c2b7e107443c298a8d59d054fac027ad32021bb5eeadcb87f73d649c3892`.
After the lease ended, review added malformed-display validation and then
corrected true client rotation, callback-generation isolation, bounded
outbound scheduling, typed terminal failures, and Camera settings-return
recovery. The final 110-test clean build was not reinstalled. Those review
fixes are JVM/lint/build-verified only and retain all real-device gates below.

The Mac remained locked, so ScreenCaptureKit could not provide a real display.
The device run therefore used the repository's existing 2000×1124@60 synthetic
HEVC StreamTest for media/transport checks and keeps all Mac-side interaction
gates open.

- Qualcomm `c2.qti.hevc.decoder` produced the first output frame; continuing
  counters held approximately 60 FPS with typical 4–8 ms decoder latency.
- Fit measured as a centered `2249×1264` Surface inside the `2800×1264`
  landscape root, matching the 2000:1124 stream ratio instead of stretching.
- ADB-injected tap and long swipe produced real one-pointer touch packets at
  the synthetic server. This is packet evidence, not a visible Mac click,
  right click, scroll, pinch, or drag result.
- Injected Android C key mapped to USB HID usage 6 and was rejected with the
  touch-only compatibility path; no unnegotiated keyboard byte was sent. This
  is not physical-keyboard evidence.
- Background/foreground preserved the live transport, recreated the surface
  and decoder, requested a keyframe, and produced a new first output frame.
- Force-stop/cold-start kept StreamTest PID `40731`; the new session received
  display config at diagnostic timestamp `1785866249899`, initialized the
  decoder at `1785866250009`, and produced first output at `1785866250082`
  (183 ms config-to-first-output). The scripted wall window included an
  intentional two-second stopped interval and is not reported as reconnect
  latency.
- With Camera denied, USB cold-started without a permission dialog. First and
  permanent denial led to an actionable Camera state; **Open Settings** opened
  Android's `InstalledAppDetailsActivity`. After permission recovery,
  `QRScannerActivity` launched without a fatal exception.
- A stale reverse endpoint that accepted TCP then closed before display config
  now remained unready and showed “Open Vibe Screen on your Mac, then try
  again,” rather than entering a false connected loop.

Screenshots, UI XML, and application-tag-filtered logcat are retained in
[`evidence/device-100.72.246.116-5555/`](evidence/device-100.72.246.116-5555/).
The private diagnostic timestamps quoted above were observed during the run,
but the raw file was lost during post-run filtering and is not claimed as a
retained artifact.

## Device acceptance still required

Follow [`docs/runbook/android-client.md`](../../runbook/android-client.md) and
still record:

- identity before install, APK hash/signing/install time, and exact commit;
- Fit/Fill and all four rotation modes with corner mapping;
- tap, long-press right click, long-press drag, two-finger scroll and pinch;
- physical mouse wheel/secondary button and physical keyboard compatibility UI;
- a real unlocked Mac stream, missing reverse, host interruption, Host PID,
  visible Mac result, session epochs, and end-to-end recovery duration;
- Android diagnostic/logcat plus visible Mac-side outcomes.

Compilation, synthetic media, ADB-injected events, and old Phase 0 tap evidence
cannot close the remaining unlocked-Mac, physical-peripheral, Xiaomi 12, or
two-hour stability gates.
