# Final Android device acceptance

Date: 2026-08-04  
ADB endpoint: `100.72.246.116:5555`

## Frozen artifacts

| Artifact | SHA-256 |
| --- | --- |
| Final debug APK | `573a00cfca1ab5d39e5d2991ab5f6d19aa920271980b75b62ff64a5490922c68` |
| macOS application ZIP | `c1bc76140b241a73b32099828ceda911cc1ac1e9e9dd9d5b694d674b0c4b8c6b` |
| Device identity JSON | `209b6d2051750c79d627fac309dc6a2a5d0f283f2f67e8d027c3d9b4503fd9bb` |
| Accepted soak samples JSONL | `ba5792041cb9150b0c13afb3930e69e970697b6629b81306642ed5305e17bcad` |
| Accepted soak summary JSON | `532cb7c14750973ba2345d9709b75452d2feb148789f4e2b3a52f0fa4be37d3b` |
| Frozen Host telemetry JSONL | `7113413d1a18eaba07d1f67cfef1f19f740bc3e095763b18fb49a617fd9538fa` |
| Accepted-run Android logcat | `e46c56b21daf52036b524dcf072d8aa5101548951c358ec99c6330940fc12e8a` |
| Accepted-run Android diagnostic log | `531e2417c7099ac7c71f9bacb5fcffeb86194eb75f3d7c5373ea04e2e6a97ff3` |
| Accepted-run Host log excerpt | `8b682c69dcdea6052d8c6129f3df11ff5407923074115989f2fd60ffb83451f4` |

The raw run artifacts are under `.build/evidence/soak-30m/` in the acceptance
workspace. The compact results and immutable hashes are retained here because
`.build/` is not a source-release directory.

## Device identity

```text
device serial: EP0110PZ0B9110152B
manufacturer: nubia
model: P0110
device/product: pacific
Android: 16 (SDK 36)
fingerprint: nubia/pacific/pacific:16/2.5.2.0/20260804.003241:userdebug/test-keys
display: 1264x2800, density 560
```

This device is not the Phase 0 Xiaomi 12 target.

## Final offline gates

```bash
make protocol

cd baseline/AndroidClient
./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug auditReleaseDependencies

cd ../..
make evidence-tools-test

cd baseline/MacHost
swift package clean
swift build -c release
.build/release/Telemachus --host-self-test
.build/release/Telemachus --transport-self-test
.build/release/Telemachus --reliability-self-test
.build/release/Telemachus --phase3-internet-self-test
.build/release/Telemachus --phase3-webrtc-loopback-self-test
```

Protocol format/lint/build/breaking passed. Android completed 68 tests with no
failures/errors/skips and all clean/lint/APK/dependency-audit tasks passed.
The evidence tool suite passed 32 tests. The Host clean release build and five
self-tests passed. `swift test` failed before execution because the selected
Command Line Tools environment has no XCTest module; this is not recorded as a
pass.

Additional final checks passed:

```bash
python3 -m unittest discover -s tests/phase3 -p 'test_*.py' -v
(cd packages/security && go test -race ./... && go vet ./...)
(cd services/relay && go test -race ./... && go vet ./...)
(cd services/signaling && make verify)
python3 scripts/phase3_webrtc/run_local_e2e.py --mode direct
python3 scripts/phase3_webrtc/run_local_e2e.py --mode relay --skip-build
```

The Phase 3 Python suite passed 21 tests. Direct and real local coturn relay
WebRTC checks passed. SideScreen/Telemachus retained LICENSE/NOTICE files match
their recorded upstream hashes; Android runtime dependency/SBOM/notices audit
passed. No GPL/AGPL code was introduced by this acceptance work.

## Install and functional commands

The final APK was installed exactly once:

```bash
adb -s 100.72.246.116:5555 install -r -t \
  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
adb -s 100.72.246.116:5555 reverse --remove tcp:54321
adb -s 100.72.246.116:5555 reverse tcp:54321 tcp:54321
adb -s 100.72.246.116:5555 shell am start -S -W \
  -a android.intent.action.MAIN \
  -n dev.telemachus.display/.MainActivity \
  --ez auto_connect true
```

HEVC, touch, client restart/reconnect, H.264 fallback, and stale-epoch rejection
results are summarized in the parent `TEST.md`. H.264 and stale-epoch paths
used explicit JDWP fault injection against the debuggable final APK; neither is
presented as a spontaneous hardware failure.

## Accepted 30-minute soak

The Makefile soak command was expanded only at invocation time with the
runner's supported `--host-pid` argument so Host liveness was sampled:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 \
  -m vibescreen_evidence.soak \
  --serial 100.72.246.116:5555 \
  --preset 30m --interval 30s \
  --package dev.telemachus.display \
  --host-pid 95367 \
  --telemetry-jsonl .build/evidence/soak-30m/host-telemetry.jsonl \
  --require-stream-telemetry \
  --output-jsonl .build/evidence/soak-30m/samples.jsonl \
  --summary-json .build/evidence/soak-30m/summary.json
```

Accepted exact window: `2026-08-04T15:54:38.394286Z` to
`2026-08-04T16:24:38.347614Z`.

The runner returned `complete`, with 60 connected/running Android samples, 60
Host RSS samples, no sample errors, and no ADB reconnect. Exact-window Host
telemetry contained 1,784 stream stats and 1,797 heartbeats, with no session
admission/disconnect, queue drop, or stream drop. The minimum/mean/maximum FPS
was `59.53/60.01/61.29`; average frame age was
`4.92/6.38/11.08 ms`.

The run proves the formal 30-minute process and stream gates on this device.
It does not prove Xiaomi 12 compatibility, external glass-to-glass latency, or
the planned two-hour no-growth target. Host RSS rose about 9 MiB across this
window, so longer observation remains required before excluding a slow leak.
