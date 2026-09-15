# Nubia P0110 Internet profile import/bootstrap Android-local smoke

Date: 2026-09-16 (local, Asia/Shanghai)

This no-Host Android run verifies the real MainActivity Internet profile
import/bootstrap UI on a connected Nubia P0110. The accepted opt-in run drives
the product Internet tab, direct/forced-relay toggle, protected pairing and
profile-import dialogs, AndroidKeyStore-backed local pairing state, strict
host-signed test lease import, retryable rejected-draft recovery, local revoke,
and repair/re-pair cleanup.

No Vibe Screen macOS Host was launched. No macOS Screen Recording,
Accessibility, Microphone, signing, Keychain, or TCC operation was used. No ADB
reverse tcp:54321 mapping was created, and no local TCP 54321 listener was
present before or after the accepted run.

## Source

Recorded before this change was committed; see metadata/source-provenance.txt.

    repository=TaoSama/vibe-screen
    branch=codex/android-internet-profile-import-device-evidence
    base_head=ad94be5ae559f2b314a7edd4d7a4baf2391a82af
    origin_main=ad94be5ae559f2b314a7edd4d7a4baf2391a82af
    base_subject=Recover Internet camera scanner after manual permission grant
    date=2026-09-16
    timezone=Asia/Shanghai

## Device

Recorded in metadata/device-identity.txt:

    serial=<redacted-adb-serial>
    actual_serial_verified_online=yes
    manufacturer=nubia
    model=P0110
    device=pacific
    release=16
    sdk=36
    fingerprint=nubia/pacific/pacific:16/2.6.2.0/20260907.013634:userdebug/test-keys
    wm_size=Physical size: 1264x2800
    wm_density=Physical density: 560
    font_scale=1.0

This record is Nubia P0110 / pacific / Android 16 / API 36 evidence only. It
must not be reported as Xiaomi 13/fuxi evidence.

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Opt-in guard | logs/connected-internet-ui-bootstrap-opt-out.log | Running InternetMainActivityAcceptanceInstrumentedTest without vibeScreenInternetUiBootstrapAcceptance=true skipped the selected method through the assumption gate and did not produce a pass marker. |
| Android-local MainActivity import/bootstrap | android-test-results/TEST-P0110-16-app.xml, android-test-results/test-results.log, logs/connected-internet-ui-bootstrap-opt-in.log, logs/instrumentation-marker.log | Passed 1/1 with failures=0, errors=0, skipped=0. Gradle reported BUILD SUCCESSFUL in 16s. The retained marker is PHASE3_ANDROID_INTERNET_UI_PASS internet_tab=true route_toggle=true pairing=true strict_lease_import=true retryable_import_error=true local_revoke=true repair=true secure_dialogs=true. |
| Rejected-draft retry UX | Instrumentation source and accepted marker | The run first submitted malformed lease JSON, verified the inline dialog error was visible and no public profile was persisted, edited the same field, verified the stale error cleared before resubmitting, and then imported the valid signed test lease. |
| Local credential cleanup | Instrumentation source and accepted JUnit | The run completed local revoke and repair/re-pair cycles through product UI, then removed the test profile, pairing, identity, and stored secrets created during the run. |
| no-Host boundary | logs/no-host-boundary.txt | Read-only adb reverse --list was empty before and after the run; lsof -nP -iTCP:54321 -sTCP:LISTEN returned no listener rows before and after the run. |
| Focused source contracts | logs/focused-jvm-and-androidtest-compile.log | RealQrPairingStaticContractTest and MainActivityTerminalGuidanceContractTest passed, and :app:compileDebugAndroidTestKotlin passed. |
| Phase 3 runner regression | logs/python-phase3-runner-regression.log | tests.phase3.test_android_product_session_interop_acceptance passed 27/27, including the explicit UI opt-in argument and complete UI marker requirements. |

## Commands

The exact command list is retained in commands.txt. Device commands used the
redacted serial placeholder in the retained file.

## Boundary

The profile and lease material used by this run was constructed in memory by
the instrumentation TestHostAuthority, then entered through the product
MainActivity pairing/profile import dialogs and persisted through the product
Android profile store and AndroidKeyStore-backed credential lifecycle. This is
real Android UI/bootstrap evidence for the local product surface, not evidence
that a production Authority issued a profile or that a Host-backed Internet
session was established.

This package does not prove or close:

1. public Internet direct or remote TURN traversal
2. macOS Host launch, signing, Keychain, TCC, Screen Recording, Accessibility,
   or Microphone readiness
3. production Authority profile issuance or cross-service revocation
   propagation
4. real camera QR decode or device-to-authority pairing exchange
5. WebRTC PeerConnection, STUN/TURN candidate-pair selection, packet-capture
   confidentiality, or application DataChannel traffic
6. ScreenCaptureKit/CGDisplayStream capture, VideoToolbox host frames, Android
   MediaCodec output, audio playback, clipboard, or file-transfer product E2E
7. device handoff, public-network recovery, latency, or soak stability

Verify retained artifacts with:

    shasum -a 256 -c SHA256SUMS
