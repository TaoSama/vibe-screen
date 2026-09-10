# Nubia P0110 no-Host Settings showStatsRow refresh after PR #762

Date: 2026-09-10

Scope: focused Android Settings dialog `showStatsRow` UI/UX verification on
current `origin/main` containing PR #762 merge commit
`6f463421efb2a7a8c89c3cccb111b4d1441aa6c3`. This evidence covers the
side-effect-free responsive row decision, narrow large-text stacking, wide
normal-font horizontal layout, repeated wide/narrow reflow restoration, switch
checked-state preservation, no duplicate accessibility names, no text ellipsis,
no text/switch overlap, scroll reachability, and 48dp touch target coverage.

No Vibe Screen, MacHost, or Telemachus macOS GUI was launched. No `swift run`,
macOS TCC, Screen Recording, Accessibility, Microphone, Keychain, System
Settings, signing configuration, or `adb reverse` command was used.

## Source

Recorded in `metadata/source-provenance.txt`:

    repository=git@github.com:TaoSama/vibe-screen.git
    branch=codex/settings-show-stats-row-responsive
    head=6f463421efb2a7a8c89c3cccb111b4d1441aa6c3
    origin_main=6f463421efb2a7a8c89c3cccb111b4d1441aa6c3
    origin_main_contains_pr_762_merge=yes
    local_change=Android Settings dialog showStatsRow side-effect-free responsive layout and accessibility regression coverage.

`metadata/source-provenance.txt` also records the SHA-256 of the working-tree
diff for the Android source/test changes captured by this evidence.

## Device

Recorded in `metadata/device-identity.txt`:

    serial=<redacted-adb-serial>
    actual_serial_verified_online=yes
    manufacturer=nubia
    model=P0110
    device=pacific
    release=16
    sdk=36

This record is Nubia P0110 / pacific / Android 16 / API 36 evidence only. It
must not be reported as Xiaomi 13/fuxi evidence. The forbidden serial
`EP0110PZ0B9110300B` was not used.

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Source sync | `metadata/source-provenance.txt` | `HEAD` and `origin/main` were both `6f463421efb2a7a8c89c3cccb111b4d1441aa6c3`, and the PR #762 merge commit was confirmed as contained in `origin/main`. |
| Diff hygiene | `logs/git-diff-check.txt` | `git diff --check` passed with no output. |
| Focused JVM checks | `logs/focused-settings-jvm.log`, `unit-test-results/` | Passed `SettingsDialogLayoutPolicyTest` 6/6, `MainActivitySettingsAccessibilityContractTest` 5/5, and `DesignTokenContrastTest` 9/9. |
| androidTest compile | `logs/gradle-compile-debug-androidtest-kotlin.log` | `:app:compileDebugAndroidTestKotlin` passed. |
| P0110 focused instrumentation | `logs/connected-settings-dialog-instrumentation.log`, `android-test-results/TEST-P0110 - 16-_app-.xml`, `android-test-report/index.html` | Passed 23/23 `SettingsDialogLayoutInstrumentedTest` tests on P0110 - 16 with failures=0, errors=0, skipped=0. |
| No-Host boundary | `logs/no-host-boundary-lsof-54321-before-status.txt`, `logs/no-host-boundary-lsof-54321-after-status.txt` | Both `lsof -nP -iTCP:54321 -sTCP:LISTEN` samples returned status `1`, showing no local `tcp:54321` Host listener before or after the run. |
| Checksum | `SHA256SUMS`, `logs/sha256-check.txt` | `shasum -a 256 -c SHA256SUMS` passed for all retained artifacts. |

The focused instrumentation class includes the requested `showStatsRow`
coverage: 320/360dp with fontScale 1.5/2.0 stack vertically; 600dp normal-font
layout remains horizontal; repeated wide-to-narrow-to-wide applications restore
orientation, text width/weight, switch margins/gravity, and checked state on the
same row view; row/text/title/description/switch do not introduce duplicate
`contentDescription`; title keeps the single `labelFor` relationship to the
switch; text has no ellipsis, the switch and text do not overlap, the row is
scroll-reachable, and the switch measures at least 48dp in both axes.

## Artifact Notes

UTP binary protobuf files, lock files, Gradle binary caches, and screenshots were
not retained for this focused source/test refresh. Text XML, HTML reports,
device identity, command logs, and SHA-256 checksums are sufficient for the
no-Host Settings dialog verification boundary.

## Verification

Run from this evidence directory:

```bash
shasum -a 256 -c SHA256SUMS
```
