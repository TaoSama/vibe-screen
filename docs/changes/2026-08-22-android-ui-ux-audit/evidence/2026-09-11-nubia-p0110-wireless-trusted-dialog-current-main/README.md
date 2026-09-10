# 2026-09-11 Nubia P0110 No-Host Wireless Trusted Dialog

## Scope

This evidence records a focused no-Host Android validation for the trusted-LAN
confirmation dialog used by the Wireless tab. The checked surface is the
Material dialog layout and behavior for the first wireless scan acknowledgement:
large-text copy readability, minimum dialog-button touch targets, standard
message semantics, and confirmation/cancel callback isolation.

This is not Host-backed product-session evidence. It does not claim LAN
streaming, Internet traversal, video decode, input forwarding, reconnect timing,
latency, soak, Host signing/TCC readiness, Android ClipboardManager <-> macOS
NSPasteboard transfer, Android/macOS file-transfer bytes landing, native
pointer, stylus, controller, iOS behavior, macOS hardware acceptance, or Xiaomi
13/fuxi behavior.

## Source

| Field | Value |
| --- | --- |
| Branch | `codex/wireless-trusted-dialog-material` |
| Baseline/source HEAD | `a322bbdedfa92989d928294cdcbf6f6089c59314` |
| Baseline/source short | `a322bbd` |
| Evidence package date | 2026-09-11 |
| Timezone | Asia/Shanghai |

See `metadata/source-provenance.txt` for the retained source state and local
change summary. This evidence package only organizes already-produced artifacts
and does not modify production code.

## Device

| Field | Value |
| --- | --- |
| Manufacturer | Nubia |
| Model | P0110 |
| Codename | pacific |
| Android | 16 |
| API | 36 |
| ADB serial | `<redacted-adb-serial>` |

See `metadata/device-identity.txt` for retained device metadata. This record
must remain Nubia P0110/pacific evidence and must not be relabeled as Xiaomi
13/fuxi evidence. The raw device serial is intentionally not retained.

## Host Boundary

The focused instrumentation run was no-Host scoped: no macOS Host was started,
installed, modified, re-signed, or granted Screen Recording, Accessibility,
Microphone, or other TCC permissions for this run. No `adb reverse tcp:54321
tcp:54321` mapping was created, and no local `tcp:54321` listener was present.

See `metadata/no-host-boundary.txt` for the retained boundary statement. Raw
logcat, UTP runtime logs, binary device metadata, and other artifacts that could
retain device identifiers or unrelated telemetry were omitted.

## Command

The retained artifacts correspond to this focused device instrumentation command:

```bash
ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.WirelessTrustedDialogLayoutInstrumentedTest
```

No additional device tests or Gradle tasks were run while creating this evidence
package.

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Focused instrumentation on Nubia P0110/pacific | `android-test-results/TEST-P0110-16-app.xml`, `android-test-results/test-results.log`, `android-test-results/test-result.redacted.textproto`, `android-test-report/` | PASS, 2/2 tests |

The retained JUnit XML reports
`tests="2" failures="0" errors="0" skipped="0"` for
`dev.telemachus.display.WirelessTrustedDialogLayoutInstrumentedTest` at
`2026-09-10T16:14:43`. The retained instrumentation status log reports
`OK (2 tests)`.

Retained test cases:

- `standardMaterialMessageDialogKeepsTrustedLanCopyReadable`
- `trustedLanDialogConfirmationAndCancelCallbacksStayIsolated`

## Artifact Notes

Retained artifacts:

- JUnit XML result: `android-test-results/TEST-P0110-16-app.xml`
- Instrumentation status log: `android-test-results/test-results.log`
- Redacted UTP textproto: `android-test-results/test-result.redacted.textproto`
- Gradle HTML report files under `android-test-report/`

Omitted artifacts:

- raw per-test logcat files
- `utp.0.log`
- binary `device-info.pb` and `test-result.pb`
- `cpuinfo`, `meminfo`, lock files, and other unneeded runtime artifacts

The retained textproto redacts local absolute worktree paths and points omitted
logcat/device-info artifacts at placeholder labels. It is retained only to
preserve UTP test status and artifact metadata without storing raw identifiers.

## Integrity

Verify retained evidence from the repository root with:

```bash
shasum -a 256 -c docs/changes/2026-08-22-android-ui-ux-audit/evidence/2026-09-11-nubia-p0110-wireless-trusted-dialog-current-main/SHA256SUMS
```
