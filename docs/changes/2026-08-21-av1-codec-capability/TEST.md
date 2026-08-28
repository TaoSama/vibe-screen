# AV1 codec capability gate

Date: 2026-08-21
Status: current-base closure owner added; real AV1 stream blocked

## Scope

This change covers the engineering contract for the planned AV1 codec path
without claiming current Host or device stream support. Protocol v1 already
contains CODEC_AV1; this slice makes AV1 admission explicit across Host,
Android, and iOS policy surfaces.

`tools/tests/test_av1_current_base_gate.py` is the current-base closure owner.
It must stay green until AV1 is intentionally promoted from later-phase/backlog
work into a real Host/device stream codec. The gate checks both product wording
and source admission points so a future change cannot accidentally claim AV1 as
shipped, advertise AV1 from the Host, map AV1 into Android product offers, or
remove the blocked-evidence record without updating the implementation and
evidence contract together.

## Offline coverage

Expected checks for this slice:

```text
cd baseline/MacHost && swift test --filter CodecLimitsTests --filter ProtocolV1SessionTests --filter InternetProductProtocolCodecTests
cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest
cd apps/ios && swift run vibescreen-ios-selftest
PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v
```

The covered contract is:

- Host VideoToolbox capability probing distinguishes H.264, HEVC, and AV1
  hardware encoder availability, but Protocol v1 Host advertisement still
  filters out AV1 until a real AV1 encoder and frame packaging implementation
  exists; the current Host does not advertise AV1.
- Protocol v1 Host session selection ignores AV1 when the local Host has no
  stream encoder mapping and falls back to HEVC/H.264 when the client also
  supports them.
- Protocol v1 Host session fails closed with an actionable unsupported-capability
  error when the only mutually offered client codec is AV1.
- Android MediaCodec capability probing can observe AV1 decoder availability as
  diagnostic state, but Android does not offer AV1 in product sessions and
  default USB/LAN/Internet offers remain HEVC/H.264 only; a received AV1
  Internet VideoConfig is rejected as av1_decoder_unavailable.
- iOS validates CODEC_AV1 as a known protocol enum but rejects AV1 unless an
  explicit local decode capability is present, and the current VideoToolbox
  decoder implementation still throws unsupportedCodec(.av1).
- The current-base closure owner also checks that iOS recognizes CODEC_AV1 but
  rejects it without local decoder support, so all three product surfaces stay
  aligned until a real AV1 implementation and evidence gate are added.

## Real-device status

No AV1-capable macOS Host stream, Android MediaCodec stream, or iOS
VideoToolbox stream was run. The README AV1 gate remains open.

The retained blocked evidence records are
[`evidence/2026-08-21-av1-offline-blocked/README.md`](evidence/2026-08-21-av1-offline-blocked/README.md)
and
[`evidence/2026-08-27-av1-current-base-blocked/README.md`](evidence/2026-08-27-av1-current-base-blocked/README.md).

## 2026-08-21 verification

- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.
- `cd baseline/MacHost && swift test --filter CodecLimitsTests --filter ProtocolV1SessionTests --filter InternetProductProtocolCodecTests`
  - Result: blocked in this local Command Line Tools environment before test
    execution with `no such module 'XCTest'`; the MacHost product target
    compiled successfully with `swift build`.

## 2026-08-28 Nubia P0110 Android decoder capability probe

A read-only Android decoder capability snapshot was captured on `origin/main`
`27d2b0e493e807ae439fbd43b06b4c2f0ce9c503` for the connected Nubia P0110
(`pacific`, Android 16 / SDK 36, serial `<redacted-device-serial>`). The run first
checked `pgrep -x sfltool || true`, which returned no output, and no
`/usr/bin/sfltool dumpbtm` command was executed. Android device commands were
run after acquiring `/tmp/vibe-screen-android-<redacted-device-serial>.lock`.

The preferred service-level probes remained unavailable on this device:
`adb -s <redacted-device-serial> shell dumpsys media.codec` returned no stdout and
`Can't find service: media.codec` on stderr with exit code `0`, and
`adb -s <redacted-device-serial> shell cmd media.codec list` returned
`cmd: Can't find service: media.codec` with exit code `20`. Vendor/system XML
inspection still declares diagnostic AV1 decoder entries including
`c2.qti.av1.decoder`, `c2.qti.av1.decoder.low_latency`,
`c2.qti.av1.decoder.secure`, `c2.android.av1.decoder`, and
`c2.android.av1-dav1d.decoder`.

This is only an Android capability/readiness snapshot. It does not add AV1
Host/device real-stream evidence, does not prove MediaCodec configuration or a
first decoded output frame, and does not change the README AV1 gate status.
The retained raw outputs and hashes are recorded under
[`evidence/2026-08-28-nubia-p0110-av1-capability-probe/README.md`](evidence/2026-08-28-nubia-p0110-av1-capability-probe/README.md).

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 6 tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `make protocol`
  - Result: passed, including 45 protocol contract tests.
- `cd docs/changes/2026-08-21-av1-codec-capability/evidence/2026-08-28-nubia-p0110-av1-capability-probe && shasum -a 256 -c SHA256SUMS.txt`
  - Result: passed for every retained evidence file.
- `git diff --check`
  - Result: passed.
- Sensitive-info scan over the AV1 evidence directory, `TEST.md`, and
  `tools/tests/test_av1_current_base_gate.py`
  - Result: passed; no matching secret/token/private-key patterns.

## 2026-08-23 current-base refresh

The current-base closure owner was replayed on `origin/main`
`3d23de133adc4414b4c70430c619fadbe7d90207`. This refresh only keeps the AV1
gate fail-closed and reviewable; it does not add Host/device AV1 streaming
evidence.

- `make protocol`
  - Result: passed.
- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 5 tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.
- `cd baseline/MacHost && swift test --filter CodecLimitsTests --filter ProtocolV1SessionTests --filter InternetProductProtocolCodecTests`
  - Result: blocked in this local Command Line Tools environment before test
    execution with `no such module 'XCTest'`; the MacHost product target
    compiled successfully with `swift build`.

## 2026-08-23 UTC current-base refresh

The current-base closure owner was replayed on `origin/main`
`aaea0d595f66bb25bb226ba2b61152dcb40bd174`. The README conflict was resolved
by retaining the current USB/LAN audio row and keeping the AV1 video row
fail-closed: AV1 remains a later-phase/backlog codec, not a current
Host/device stream codec. This refresh does not add Host/device AV1 streaming
evidence.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 5 tests.
- `make protocol`
  - Result: passed, including 36 protocol contract tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.
- `cd baseline/MacHost && swift test --filter CodecLimitsTests --filter ProtocolV1SessionTests --filter InternetProductProtocolCodecTests`
  - Result: blocked in this local Command Line Tools environment before test
    execution with `no such module 'XCTest'`; the MacHost product target
    compiled successfully with `swift build`.

## 2026-08-23 UTC current-base refresh after PR #313

The current-base closure owner was replayed again on `origin/main`
`6ccf580e79585dd7519671192e906ac510a15f35` after PR #313 landed. The remote
PR branch's merge commit was replaced with a linear replay of the three AV1
closure commits. No source or README gate was widened: AV1 remains a
later-phase/backlog codec, not a current Host/device stream codec. This refresh
does not add Host/device AV1 streaming evidence.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 5 tests.
- `make protocol`
  - Result: passed, including 37 protocol contract tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.
- `cd baseline/MacHost && swift test --filter CodecLimitsTests --filter ProtocolV1SessionTests --filter InternetProductProtocolCodecTests`
  - Result: blocked in this local Command Line Tools environment before test
    execution with `no such module 'XCTest'`; the MacHost product target
    compiled successfully with `swift build`.

## 2026-08-23 UTC current-base refresh after PR #306

The current-base closure owner was replayed again on `origin/main`
`44feacfc296a5e0411a43b74e3c657a0ddf95e2d` after PR #306 landed. The replay
was conflict-free and kept the PR scope limited to the README AV1 wording, AV1
gate docs/evidence, and `tools/tests/test_av1_current_base_gate.py`. No AV1
Host/device real-stream evidence was added.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 5 tests.
- `git diff --check`
  - Result: passed.

## 2026-08-23 UTC current-base refresh after PR #172

The current-base closure owner was replayed again on `origin/main`
`1230caf597f52e285d6e9e6b985aad185cb07fc8` after PR #172 landed. The replay
was conflict-free and kept the PR scope limited to the README AV1 wording, AV1
gate docs/evidence, and `tools/tests/test_av1_current_base_gate.py`. No AV1
Host/device real-stream evidence was added.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 5 tests.
- `git diff --check`
  - Result: passed.

## 2026-08-23 UTC current-base refresh after PR #296

The current-base closure owner was replayed again on `origin/main`
`a8720948a0e448afa0ff390f2f10c53583948f12` after PR #296 landed. The replay
was conflict-free and kept the PR scope limited to the README AV1 wording, AV1
gate docs/evidence, and `tools/tests/test_av1_current_base_gate.py`. No AV1
Host/device real-stream evidence was added.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 5 tests.
- `make protocol`
  - Result: passed, including 37 protocol contract tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.

## 2026-08-23 UTC current-base refresh after PR #268

The current-base closure owner was replayed again on `origin/main`
`edd34e1d8d907c2ef4d8eb93c3663c7632b06fa7` after PR #268 landed. The replay
was conflict-free and kept the PR scope limited to the README AV1 wording, AV1
gate docs/evidence, and `tools/tests/test_av1_current_base_gate.py`. No AV1
Host/device real-stream evidence was added.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 5 tests.
- `make protocol`
  - Result: passed, including 37 protocol contract tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.

## 2026-08-23 UTC current-base refresh after PR #158

The current-base closure owner was replayed again on `origin/main`
`4d7e90dcce5b033ec366591816cec571382e3249` after PR #158 landed. The replay
was conflict-free and kept the PR scope limited to the README AV1 wording, AV1
gate docs/evidence, and `tools/tests/test_av1_current_base_gate.py`. No AV1
Host/device real-stream evidence was added, and the retained diagnostic device
identity remains Nubia P0110 / pacific / Android 16 / SDK 36.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 6 tests.
- `make protocol`
  - Result: passed, including 37 protocol contract tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.

## 2026-08-24 UTC current-base refresh after PR #310

The current-base closure owner was replayed again on `origin/main`
`98efe550e99ef2ce0eb8d433436453ef23548484` after PR #310 landed. The replay
was conflict-free and kept the PR scope limited to the README AV1 wording, AV1
gate docs/evidence, and `tools/tests/test_av1_current_base_gate.py`. No AV1
Host/device real-stream evidence was added, and the retained diagnostic device
identity remains Nubia P0110 / pacific / Android 16 / SDK 36.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 6 tests.
- `make protocol`
  - Result: passed, including 37 protocol contract tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.

## 2026-08-24 UTC current-base refresh after PR #171

The current-base closure owner was replayed again on `origin/main`
`0ac995206916451a4ae12f7e6980432903407b7b` after PR #171 landed. The replay
was conflict-free and kept the PR scope limited to the README AV1 wording, AV1
gate docs/evidence, and `tools/tests/test_av1_current_base_gate.py`. No AV1
Host/device real-stream evidence was added, and the retained diagnostic device
identity remains Nubia P0110 / pacific / Android 16 / SDK 36.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 6 tests.
- `make protocol`
  - Result: passed, including 37 protocol contract tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.

## 2026-08-24 UTC current-base refresh after PR #301

The current-base closure owner was replayed again on `origin/main`
`7247f313e24cc465c9ddd0b60e271b361d1f9d4a` after PR #301 landed. The replay
was conflict-free and kept the PR scope limited to the README AV1 wording, AV1
gate docs/evidence, and `tools/tests/test_av1_current_base_gate.py`. No AV1
Host/device real-stream evidence was added, and the retained diagnostic device
identity remains Nubia P0110 / pacific / Android 16 / SDK 36.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 6 tests.
- `make protocol`
  - Result: passed, including 37 protocol contract tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.

## 2026-08-27 current-base refresh

The current-base closure owner was replayed on `origin/main`
`32b05030cf4cff54029d9bffd4c9dd0cb7e1d6e3`. The audit kept AV1
fail-closed and blocked: Protocol v1 only reserves `CODEC_AV1`, the current
Host still does not advertise AV1, Android product sessions still do not offer
AV1, and no Host/device AV1 real-stream evidence was added. Public AV1 gate
evidence now redacts Android device serials and local sensitive paths.

Retained device diagnostic identity: nubia P0110 / pacific / Android 16 / SDK
36. Local ADB probes used the required explicit `adb -s` selector, but the
public evidence records it as `<redacted-device-serial>`.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 7 tests.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `make protocol`
  - Result: blocked by current-base shared-model drift before this AV1 refresh: `ManagedPolicyStatus` now has `restriction_results` and `denied_hosts` fields missing from `contracts/shared-models/v1/manifest.json`, causing 7 shared-protocol-model test failures.
- `cd baseline/MacHost && swift build`
  - Result: blocked by current-base MacHost build failures before this AV1 refresh, including missing `HostMultiClientDisplayRouter`, `ProtocolV1SessionCoordinator.close`, and extra `ProtocolV1SessionConfiguration` arguments in `StreamingServer.swift` / `ProtocolV1SelfTest.swift`.
- `git diff --check`
  - Result: passed.

## 2026-08-27 routing-boundary follow-up

The PR branch was refreshed after the Host Protocol v1 routing boundary was
restored locally. This follow-up resolves the unrelated MacHost compile blocker
and the Phase 5 host-adapter readiness script now treats `.multiClient` as
valid only when it is explicitly gated behind `maximumClients > 1`; production
defaults still keep the Host single-client and do not close the Phase 5
multi-client/display gate. AV1 remains fail-closed and blocked: no Host/device
AV1 stream was attempted or recorded.

Retained device diagnostic identity: nubia P0110 / pacific / Android 16 / SDK
36. Local ADB probes used the required explicit selector and public evidence
keeps the serial redacted.

- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 7 tests.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts.tests.test_phase5_host_advanced_adapters -v`
  - Result: passed, 5 tests.
- `make release-tools-test`
  - Result: passed, 223 tests.
- `make evidence-tools-test`
  - Result: passed, 1000 tests.
- `make protocol`
  - Result: passed, including 45 protocol contract tests.
- `swift build --package-path baseline/MacHost -c release`
  - Result: passed.
- `baseline/MacHost/.build/release/"Vibe Screen" --protocol-v1-self-test`
  - Result: passed.
- `make baseline-macos-self-test`
  - Result: passed.
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.phase3.test_repository_privacy -v`
  - Result: passed, 10 tests.
- `git diff --check`
  - Result: passed.
- Diff privacy scan for the real Android serial, local user path, TCC paths, and
  private-key headers
  - Result: passed, no matches.
