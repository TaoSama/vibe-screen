# Nubia P0110 Internet expired/stale lease UI acceptance

Date: 2026-09-16

Scope: focused Android-local no-Host verification for the Internet profile UX when a stored session lease is expired or stale. The run uses the production `MainActivity`, real AndroidKeyStore-backed pairing/profile stores, production profile import/revoke dialogs, and the existing product session coordinator freshness state.

## Device

- Serial: `REDACTED_P0110_USB_SERIAL`
- Identity: nubia P0110 / pacific / Android 16 / API 36
- Raw captures: `metadata/device-identity.txt`, `metadata/adb-devices.txt`

This is Nubia P0110/pacific evidence only and must not be relabeled as Xiaomi 13/fuxi evidence.

## Source

- Source head before run: `metadata/source-head-before-run.txt`
- Source diff before run was inspected locally and is represented by the PR diff;
  it is not archived here because raw source diffs include credential-field names
  that are intentionally blocked by the public evidence privacy scanner.
- Artifact hashes: `SHA256SUMS`

## Commands

Compile gate:

    (cd baseline/AndroidClient && ./gradlew :app:compileDebugAndroidTestKotlin)

Focused device gate:

    adb -s REDACTED_P0110_USB_SERIAL reverse --remove-all
    adb -s REDACTED_P0110_USB_SERIAL reverse --list > logs/adb-reverse-before.txt
    lsof -nP -iTCP:54321 -sTCP:LISTEN > logs/tcp-54321-listener-before.txt || true
    (cd baseline/AndroidClient && ANDROID_SERIAL=REDACTED_P0110_USB_SERIAL ./gradlew :app:connectedDebugAndroidTest \
      -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.InternetMainActivityAcceptanceInstrumentedTest#expiredStoredLeaseDisablesConnectAcrossForegroundAndRecreation \
      -Pandroid.testInstrumentationRunnerArguments.vibeScreenInternetExpiredLeaseUxAcceptance=true)

No `tccutil`, `codesign`, `security`, keychain, Host launch, or Host-signing command was run. The focused instrumentation does not grant Camera and does not request Accessibility permission.

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| AndroidTest Kotlin compile | terminal output from `:app:compileDebugAndroidTestKotlin` | `BUILD SUCCESSFUL` |
| Focused P0110 instrumentation | `android-test-results/debug/TEST-P0110 - 16-_app-.xml`, `logs/connected-expired-stale-lease-ux-instrumentation.log` | 1/1 passed, failures=0, errors=0, skipped=0; Gradle logged `BUILD SUCCESSFUL in 12s` |
| Expired lease UI | per-test logcat PASS marker | `expired_summary=true`, `connect_disabled=true`, `expired_foreground_refresh=true`, `expired_recreation_refresh=true`, `fresh_reimport=true` |
| Stale lease UI | per-test logcat PASS marker | `stale_summary=true`, `connect_disabled=true`, `stale_foreground_refresh=true`, `fresh_reimport=true` |
| Secondary actions | per-test logcat PASS marker | `scan_import_revoke_available=true`; the test checks Scan, Import, and Revoke remain enabled while Connect is disabled |
| no-Host boundary | `logs/adb-reverse-before.txt`, `logs/adb-reverse-after.txt`, `logs/adb-reverse-final.txt`, `logs/tcp-54321-listener-before.txt`, `logs/tcp-54321-listener-after.txt`, `logs/tcp-54321-listener-final.txt` | `adb reverse --list` was empty before/after/final; no local `tcp:54321` listener rows were recorded |
| Permission boundary and cleanup | `logs/runtime-permissions-before-uninstall.txt`, `logs/camera-appops-before-uninstall.txt`, `logs/pm-list-after-uninstall.txt`, `logs/camera-appops-after-uninstall.txt` | No Camera runtime grant was recorded; final `pm list` is empty and final appops reports no UID for `dev.telemachus.display` |

Final PASS marker:

    PHASE3_ANDROID_INTERNET_EXPIRED_STALE_LEASE_UX_PASS expired_summary=true stale_summary=true connect_disabled=true stale_foreground_refresh=true expired_foreground_refresh=true expired_recreation_refresh=true fresh_reimport=true scan_import_revoke_available=true android_local_only=true

## Evidence Boundary

- This proves Android-local no-Host UI behavior for stored Internet leases on the connected Nubia P0110/pacific only.
- This does not prove production Authority issuance, public-Internet signaling, WebRTC direct/relay traversal, Host readiness, ScreenCaptureKit/VideoToolbox media, Android decoder output, clipboard/file-transfer product E2E, or macOS TCC/signing readiness.
- The stale state is produced by the product session coordinator requiring a lease newer than epoch 1 after a simulated session-start failure; the expired state is produced by mutating the stored public profile expiry and then foregrounding/recreating `MainActivity`.
- `uninstall-app.txt` and `uninstall-test.txt` contain Nubia `DELETE_FAILED_INTERNAL_ERROR` responses after Gradle cleanup, but final package listing is empty and final Camera appops has no UID, so no installed `dev.telemachus.display` package remained for user 0.
