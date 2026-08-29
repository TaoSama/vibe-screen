# File Transfer E2E Verification

## Scope

This change hardens the existing Protocol v1 single-file transfer path between
the macOS Host and Android client. The Android client now has a negotiated
control-bar entry point, Storage Access Framework picker for sending files, and
receiver approval dialog for incoming offers. Completed incoming Android files
are now saved to the device Downloads directory; this change does not add a
user-selected save/export flow for completed incoming files, and it does not
claim real-device, TCC, signed Host, public Internet, or WebRTC bulk DataChannel
acceptance.

## Verified locally

- Android loopback socket E2E covers a host `FileOffer` accepted by the client,
  a bulk file chunk, progress, completion, SHA-256 verification, and the
  completed app-private staging file.
- Android loopback socket E2E covers `StreamClient.offerFile(...)`, the emitted
  `FileOffer`, accepted transfer, bulk chunk bytes, final chunk SHA-256, and
  completion callback.
- Android loopback socket E2E verifies `offerFile(...)` returns false and emits
  no wire message when `CAPABILITY_FILE_TRANSFER` was not negotiated.
- Android unit tests cover the file-transfer control availability and control
  bar layout sizing, including the additional file-transfer button.
- Android `assembleDebug` verifies the app resources, data binding, and new SAF
  picker/approval UI wiring compile locally.
- macOS Host source now fail-closes bulk handling unless the active Protocol v1
  session still has file transfer negotiated, avoids retaining outgoing offers
  when file transfer is unavailable, and cancels active transfers when remote
  managed policy disables file transfer or the Host stops.

## Commands

Android targeted file-transfer socket E2E:

    cd baseline/AndroidClient
    ./gradlew testDebugUnitTest --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.hostFileOfferAcceptsBulkChunksAndCompletesStagedFile" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.clientFileOfferSendsBulkChunksAndReportsCompletion" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.fileOfferReturnsFalseWhenCapabilityNotNegotiatedWithoutWireMessage"

Result: passed locally on 2026-08-21.

Android full StreamClient Protocol v1 integration class:

    cd baseline/AndroidClient
    ./gradlew testDebugUnitTest --tests dev.telemachus.display.StreamClientProtocolV1IntegrationTest

Result: the three new file-transfer cases passed, but the existing
`decoderRejectionFlushesBeforeTermination` timing test failed waiting for its
manual termination executor. This failure is outside the file-transfer path.

Android targeted protocol, file-transfer, session, and control-bar tests:

    cd baseline/AndroidClient
    ./gradlew testDebugUnitTest --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.hostFileOfferAcceptsBulkChunksAndCompletesStagedFile" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.clientFileOfferSendsBulkChunksAndReportsCompletion" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.fileOfferReturnsFalseWhenCapabilityNotNegotiatedWithoutWireMessage" --tests dev.telemachus.display.protocol.FileTransferSessionTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest --tests dev.telemachus.display.ClientInputDispatchTest --tests dev.telemachus.display.SessionStateTest --tests dev.telemachus.display.ClientExperienceTest --tests dev.telemachus.display.DisplayCapsulePolicyTest

Result: passed locally on 2026-08-21.

Android debug build:

    cd baseline/AndroidClient
    ./gradlew assembleDebug

Result: passed locally on 2026-08-21.

Protocol contract tests:

    make protocol-tests

Result: passed locally on 2026-08-21; 36 tests ran, 0 failures.

MacHost source build:

    cd baseline/MacHost
    swift build

Result: passed locally on 2026-08-21.

MacHost XCTest attempt:

    cd baseline/MacHost
    swift test --filter ProtocolV1FileTransferTests

Result: blocked locally before executing tests because the active toolchain is
Command Line Tools only and cannot import `XCTest` (`no such module 'XCTest'`).
The MacHost package sources compiled before the test target failed to build.

## Open gates

- Android real-device UI file send/receive acceptance remains open.
- Android user-selected save/export for completed incoming files remains open;
  automatic save to Downloads is implemented but user-selected destination is
  not.
- macOS signed Host, TCC permissions, and real Android-device file transfer
  acceptance remain open.
- Public Internet/WebRTC bulk DataChannel file-transfer acceptance remains open.

## 2026-08-22 Nubia P0110 readiness rerun

Evidence:
[evidence/2026-08-22-nubia-p0110-file-transfer-readiness-blocked](evidence/2026-08-22-nubia-p0110-file-transfer-readiness-blocked/README.md).

Status remains open. This run adds minimal readiness code and local/device smoke
coverage, but it is not a file-transfer device pass. Android receiver approval
now resolves asynchronously instead of blocking outbound command processing,
completed Android receives are saved to Downloads, MacHost has a file-transfer
menu path with receiver approval/save handling, and both senders validate the
final SHA-256 before accepting completion. Android senders also apply the
negotiated peer file-size limit before emitting a wire offer, and selected-file
staging plus digest preparation stays off the Android UI thread. Local
verification passed for Android focused file-transfer tests, Android lint/build,
protocol fixtures, evidence-tool tests, and MacHost swift build.

The real-device file-transfer gate is still blocked: no stable-signed,
TCC-authorized Host was available, security find-identity -v -p codesigning
reported zero valid identities, xcodebuild is unavailable, and MacHost XCTest
cannot import XCTest in this environment. A valid gate pass still requires a
recorded USB and/or LAN session with sender file selection, receiver explicit
approval, saved destination files, and matching SHA-256 on both sides.

## 2026-08-28 file-transfer Android smoke owner gate

The repository now has a dedicated fail-closed gate for the Protocol v1
Android/macOS single-file transfer smoke:

    make file-transfer-android-smoke EVIDENCE_DIR=.build/evidence/file-transfer-android-smoke

The gate writes `file-transfer-android-smoke-gate.json` and cannot close from
offline tests alone. A pass requires Host readiness, a ready USB or trusted-LAN
real-device path, a current Android file-transfer smoke log, bidirectional
Android -> macOS and macOS -> Android product evidence, observed
file-offer/request/content packets, explicit sender action, receiver approval,
saved remote file, positive session epoch, final SHA-256 equality, and
cancel/cleanup evidence. Nubia P0110 evidence must remain labeled as nubia
P0110 / pacific / Android 16 / SDK 36 and must not be relabeled as Xiaomi/fuxi.

The retained `file-transfer-product-e2e.json` must include both
`android_to_macos_file_transfer` and `macos_to_android_file_transfer`. Each
direction must include evidence-relative `retained_artifacts` entries for
`sender_action`, `receiver_approval`, `protocol_packets`, `remote_file`, and
`sha256_verification`; the files must exist under the same evidence bundle.
The `cancel_cleanup` block must similarly retain `cancel_request` and
`cleanup_state` artifacts. Absolute paths, `..` escapes, symlink escapes outside
the bundle, missing artifact files, offline fixtures, and synthetic logs cannot
close the gate.

Current 2026-08-28 collection on clean `origin/main`-based branch
`codex/file-transfer-android-smoke-readiness` remains blocked. The P0110 device
identity matched nubia P0110 / pacific / Android 16 / SDK 36 and ADB reverse
`tcp:54321 -> tcp:54321` was present, but the Android app was not running or
foreground, no macOS Host was listening on TCP 54321, and the stable Host
signing/TCC preflight failed because the `Vibe Screen Dev` signing identity was
unavailable. No file offer/request/content exchange, sender file selection,
receiver approval, destination file write, cancel cleanup, or end-to-end SHA-256
equality was observed, so the README gate remains open.

## 2026-08-28 Nubia P0110 current-source USB refresh

Evidence:
[`../2026-08-28-p0110-usb-current-source/evidence/2026-08-28-p0110-pacific-usb-e2e-current-source`](../2026-08-28-p0110-usb-current-source/evidence/2026-08-28-p0110-pacific-usb-e2e-current-source/README.md).

Status remains open. The run refreshed from `origin/main` at
`f5db90a761e158798065ce1078bf49428031ce49`, confirmed the device as nubia P0110
/ pacific / Android 16 / SDK 36, and reran targeted Android file-transfer and
Protocol v1 session JVM coverage successfully. Short USB live-smoke evidence
also passed before and after the Android instrumentation uninstall/reinstall
cycle.

The generated `file-transfer-current-source-gate.json` is intentionally
`blocked` and `gate_closed=false`: the available Host was not a
current-source, stable-signed/TCC-proven Host, the retained live session did not
negotiate file-transfer capability, and no Android <-> macOS product
file-transfer flow with user approval, chunk progress, final digest, and
destination-file match was captured. The P0110 evidence must not be relabeled as
Xiaomi 13/fuxi evidence.

## 2026-08-28 Nubia P0110 file-transfer current-source blocked refresh

Evidence:
[evidence/2026-08-28-nubia-p0110-file-transfer-current-source-blocked](evidence/2026-08-28-nubia-p0110-file-transfer-current-source-blocked/README.md).

Status remains open. The run refreshed from current origin/main at
e90463e5d24ee055686a9b6d3a1acd02c616b81b, recorded the device as nubia P0110
/ pacific / Android 16 / SDK 36, and kept the serial redacted as
REDACTED_P0110_USB_SERIAL. The Android file-transfer control-bar smoke passed
on the P0110 with OK (2 tests), covering the visible file-transfer action's
phone-width touch targets plus production layout-applier mode handling when the
extra action is present.

The generated blocked.json is intentionally blocked, with gate_closed=false and
can_close_file_transfer_android_smoke_gate=false. Host readiness still blocks on
stable signing/source-provenance/TCC/virtual-HID and login-headless
prerequisites; USB readiness therefore cannot prove a real Protocol v1
file-transfer path, no trusted-LAN preflight was collected, and no
file-transfer-product-e2e.json exists. This evidence does not claim Android
<-> macOS product file transfer, receiver approval, destination file SHA-256
equality, positive session epoch, or cancel cleanup.

A follow-up read-only USB live-stream smoke from the main controller is retained
as usb-live-smoke.json. It passed for the same nubia P0110 / pacific / Android
16 / SDK 36 device with adb reverse `UsbFfs tcp:54321 tcp:54321`, the Android
app foreground, 142 `stream_stats` events, average FPS about 29.99, decoder
output around 27060, and dropped frames at 0. This is only a live-stream
prerequisite reference and still does not close file-transfer E2E.

## 2026-08-29 Nubia P0110 current-base readiness owner refresh

Evidence:
[evidence/2026-08-29-nubia-p0110-file-transfer-current-base-readiness](evidence/2026-08-29-nubia-p0110-file-transfer-current-base-readiness/README.md).

Status remains open. The run started from `origin/main` at
`567dae75da22b2faa49ab59e5d95b4a642be1d97` on branch
`codex/file-transfer-current-base-readiness` and recorded the connected Android
substitute as nubia P0110 / pacific / Android 16 / SDK 36 with the USB serial
redacted. The Android debug app and Android test package installed successfully,
the file-transfer control-bar instrumentation passed with `OK (2 tests)`, the
focused Android file-transfer/session JVM tests passed, `make protocol-tests`
passed 45 protocol/fixture/security tests, and the file-transfer gate unit tests
passed 12 tests.

The generated `file-transfer-android-smoke-gate.json` is intentionally
`blocked`, with `gate_closed=false` and
`can_close_file_transfer_android_smoke_gate=false`. Host readiness still blocks
on stable signing, source provenance, read-only TCC verification, the virtual
HID entitlement, and login/headless readiness. USB readiness therefore cannot
prove a real Protocol v1 file-transfer path, no trusted-LAN preflight was
collected, and no `file-transfer-product-e2e.json` exists. This evidence does
not claim Android <-> macOS product file transfer, receiver approval,
destination-file SHA-256 equality, positive session epoch, or cancel cleanup.

The Phase 0 stable-release aggregate now tracks this as its own required
`file_transfer_android_product_e2e` gate instead of burying file transfer only in
the broader module-ownership blocker.
