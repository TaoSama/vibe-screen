# Nubia P0110 Internet dialog input hints current-source

Date: 2026-09-05

Branch: `codex/android-nohost-qr-error-focus`

Base source revision: `da382dd01779e80306b5058116d12af030268e79`

Source revision: the containing commit for this evidence package.

Device: Nubia P0110 / pacific / Android 16 / SDK 36 / serial
`<redacted-adb-serial>`.

## Scope

This evidence covers only the Android no-Host Internet dialog input affordance
change: the static profile-import and pairing-acceptance XML layouts now expose
the same input hints that the production dialog builder already applies at
runtime. The run deliberately stayed inside the Android client, static layout,
JVM contract, and device layout-test boundary.

No macOS Host binary was launched, no Screen Recording or Accessibility/TCC path
was exercised, no `adb reverse tcp:54321 tcp:54321` was created, no transport was
negotiated, and no real Internet pairing was attempted. The retained no-Host
boundary sample shows no local TCP `54321` listener and no Host-like process at
the sampled time.

This record is Nubia P0110 / pacific / Android 16 evidence only. It must not be
reported as Xiaomi 13/fuxi evidence.

## Valid Evidence

| Area | Retained artifacts | Result |
| --- | --- | --- |
| Source state | `logs/source-state.txt` | Captures the branch, modified files, base SHA, and GitHub remote used for this run. |
| no-Host boundary | `logs/no-host-boundary.txt` | No retained local TCP `54321` listener or Host-like process appeared in the sample. |
| Device identity | `metadata/device-identity.txt`, `logs/adb-devices.txt` | Confirms the connected Android test device is Nubia P0110 / pacific / Android 16 / SDK 36. |
| Static XML/JVM contract | `logs/focused-jvm-contract-test.txt`, `logs/android-offline-verification.txt` | A rerun of `MainActivityTerminalGuidanceContractTest` completed successfully, then `testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest` completed successfully. |
| Device test install | `logs/gradle-install.txt`, `logs/pm-instrumentation.txt` | Debug and androidTest APKs installed successfully; AndroidJUnitRunner was registered for `dev.telemachus.display`. |
| Focused device layout checks | `logs/focused-instrumentation-tests.txt` | The two pure layout instrumentation methods completed `OK (2 tests)` on P0110. |
| Whitespace check | `logs/git-diff-check.txt` | `git diff --check` completed with no output. |

The retained focused device run intentionally covers the pure import and pairing
layout paths that inflate the XML and assert the hint immediately after
inflation. It does not rely on the broader ActivityScenario production-dialog
test, which is outside this narrow static-layout claim and had shown
device-state-sensitive process crashes during exploratory full-class runs.

## Not Proven

This package does not prove production ActivityScenario stability, macOS Host
readiness, USB/LAN/Internet transport readiness, Protocol v1 negotiation, real
Internet pairing, QR/profile transfer, clipboard or file-transfer behavior,
video decode, input forwarding, Host signing/TCC readiness, display switching,
window actions, or Xiaomi 13/fuxi behavior.

## Verification

Run checksum verification from this evidence directory:

```bash
cd docs/changes/2026-08-22-android-ui-ux-audit/evidence/2026-09-05-nubia-p0110-internet-dialog-hints-current-source
shasum -a 256 -c SHA256SUMS
```

The submitted evidence set was checked after the README, focused JVM contract
run, final device layout run, no-Host boundary sample, and verification logs
were added; every entry in `SHA256SUMS` reported `OK`.
