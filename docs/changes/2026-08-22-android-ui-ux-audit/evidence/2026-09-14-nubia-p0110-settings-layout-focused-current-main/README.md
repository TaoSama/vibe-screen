# 2026-09-14 Nubia P0110 Settings Layout Focused Run

## Scope

This evidence records the post-merge, focused Android device validation for
`SettingsDialogLayoutInstrumentedTest` after the Settings choice accessibility
fix reached current `origin/main` as PR #780. The checked surface is the
Settings dialog layout and accessibility behavior: unique visible headings,
concise option-group context, large-text and short-landscape wrapping, measured
48dp touch targets, non-overlap, scroll reachability, and UI-only readiness
cards.

This is not Host-backed product-session evidence. It does not claim LAN
streaming, Internet traversal, video decode, input forwarding, reconnect timing,
latency, soak, Host signing/TCC readiness, Android ClipboardManager <-> macOS
NSPasteboard transfer, Android/macOS file-transfer bytes landing, native
pointer, stylus, controller, iOS behavior, macOS hardware acceptance, or Xiaomi
13/fuxi behavior.

## Source

| Field | Value |
| --- | --- |
| Branch | `codex/settings-layout-p0110-evidence` |
| Baseline/source HEAD | `58aeecc0b392cbe1e5d47dc37722b95d121b9707` |
| Baseline/source short | `58aeecc0b` |
| Source subject | `fix(android): keep file transfer dialog actions readable (#778)` |
| Evidence package date | 2026-09-14 |
| Timezone | Asia/Shanghai |

See `metadata/source-provenance.txt` for the retained source state. The product
code change was already present in `origin/main`; this package only retains the
focused device and offline verification evidence.

## Device

| Field | Value |
| --- | --- |
| Manufacturer | nubia |
| Model | P0110 |
| Codename | pacific |
| Android | 16 |
| API | 36 |
| Display | 1264x2800 @ density 560 |
| System font scale | 1.0 |
| ADB serial | `<redacted-adb-serial>` |

The local ADB serial is intentionally redacted from retained artifacts. This
record is Nubia P0110/pacific evidence only and must not be reported as Xiaomi
13/fuxi evidence. It was the only attached Android device during this rerun.

## Boundaries

No macOS Host, Vibe Screen Host, Telemachus macOS GUI, `adb reverse
tcp:54321 tcp:54321`, Screen Recording, Accessibility, Microphone, signing,
re-signing, Keychain, System Settings, or TCC operation was used. The run was
strictly UI-only on the selected Android device.

Pre-run checks observed the target device online, an empty `adb reverse --list`,
and no `dev.telemachus.display`, `dev.telemachus.display.test`,
`androidx.test.orchestrator`, or `com.android.commands.am` process. Post-run
checks again observed an empty reverse list, no target/test/orchestrator/am
processes, and no retained `dev.telemachus.display` instrumentation package.

## Command

Run from `baseline/AndroidClient` with the selected device serial constrained in
both the environment and Gradle device property:

```bash
ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon --console=plain \
  :app:connectedDebugAndroidTest \
  -Pandroid.injected.device.serial=<redacted-adb-serial> \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.SettingsDialogLayoutInstrumentedTest
```

The Gradle runner log reports `Starting 30 tests on P0110 - 16`, `Finished 30
tests on P0110 - 16`, and `BUILD SUCCESSFUL in 46s` for the final rerun at
`2026-09-14T12:07:41Z`.

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Focused Settings instrumentation | `android-test-results/TEST-P0110-16-app.xml`, `android-test-results/test-result.redacted.textproto`, `android-test-results/utp.0.redacted.log`, `android-test-results/test-results.log`, `logs/connected-settings-layout-gradle.log` | PASS, 30/30 tests |
| Runner exit | local command result | exit code 0 |
| Textproto | `scheduled_test_case_count: 30`, 30 `test_result` entries, 30 method statuses `PASSED`, no failed/error/skipped statuses | PASS |
| JUnit XML | `tests=30`, `failures=0`, `errors=0`, `skipped=0`, `testcase_count=30`, `classname=dev.telemachus.display.SettingsDialogLayoutInstrumentedTest`, `timestamp=2026-09-14T12:07:41` | PASS |
| Instrumentation status log | `OK (30 tests)` and `INSTRUMENTATION_CODE: -1` | PASS |
| UTP device targeting | install/uninstall lines reference only `<redacted-adb-serial>` for `dev.telemachus.display` and `dev.telemachus.display.test` | PASS |
| Post-run cleanup | `logs/device-postcheck-summary.txt` | PASS: reverse empty, no target/test/orchestrator/am processes, no instrumentation package |

Retained test cases include the current Settings layout class in full. Of direct
interest for this fix, the passing run includes:

- `allChoiceGroupsStayDistinctOnLargeTextPhonesAndShortLandscape`
- `scaleModeGroupStacksInResponsiveProductionLayoutOnNarrowLargeText`
- `videoAndGestureChoiceLabelsKeepTalkBackSemantics`
- `videoChoiceGroupsRemainReadableOnLargeTextPhonesAndShortLandscape`
- `settingsSectionsExposeScreenReaderHeadings`
- `settingsActionButtonsWrapWithoutEllipsizingAcrossCompactWindows`

## Offline Verification

After rebasing onto current `origin/main`, the full offline gate was rerun from
`baseline/AndroidClient` and passed:

```bash
./gradlew --no-daemon --console=plain :app:testDebugUnitTest \
  --tests dev.telemachus.display.SettingsDialogLayoutPolicyTest \
  --tests dev.telemachus.display.MainActivitySettingsAccessibilityContractTest
./gradlew --no-daemon --console=plain :app:testDebugUnitTest
./gradlew --no-daemon --console=plain \
  :app:compileDebugKotlin \
  :app:compileDebugUnitTestKotlin \
  :app:compileDebugAndroidTestKotlin
./gradlew --no-daemon --console=plain :app:lintDebug
./gradlew --no-daemon --console=plain :app:assembleDebug
git diff --check origin/main && git diff --check HEAD
```

All commands completed with `BUILD SUCCESSFUL` or no diff-check output.

## Artifact Notes

Retained artifacts:

- JUnit XML result: `android-test-results/TEST-P0110-16-app.xml`
- Redacted UTP textproto: `android-test-results/test-result.redacted.textproto`
- Redacted UTP log: `android-test-results/utp.0.redacted.log`
- Instrumentation status log: `android-test-results/test-results.log`
- Gradle runner log: `logs/connected-settings-layout-gradle.log`
- Source, device, scope-boundary, and redaction metadata under `metadata/`

Omitted artifacts:

- raw per-test logcat files
- binary `device-info.pb` and `test-result.pb`
- `cpuinfo`, `meminfo`, lock files, and other unneeded runtime artifacts

## Integrity

Verify retained evidence from the repository root with:

```bash
shasum -a 256 -c docs/changes/2026-08-22-android-ui-ux-audit/evidence/2026-09-14-nubia-p0110-settings-layout-focused-current-main/SHA256SUMS
```
