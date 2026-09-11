# 2026-09-11 PR #768 Trusted Network Dialog Local Head

## Scope

This evidence package records the local rebuild of PR #768 for the Android
Wireless trusted-network confirmation dialog. The final local source uses the
standard `MaterialAlertDialogBuilder.setMessage(...)` path, then configures only
the framework `android.R.id.message` text and dialog action buttons from
`onShow`.

This package also retains two earlier failed device instrumentation outputs from
the same investigation. They are diagnostic failure records only. They are not
passing evidence for the final source state, and no final device rerun was
performed after the standard-message pivot.

This is not Host-backed product-session evidence. It does not claim LAN
streaming, Internet traversal, video decode, input forwarding, reconnect timing,
latency, soak, Host signing/TCC readiness, Android ClipboardManager <-> macOS
NSPasteboard transfer, Android/macOS file-transfer bytes landing, native
pointer, stylus, controller, iOS behavior, macOS hardware acceptance, or Xiaomi
13/fuxi behavior.

## Source

| Field | Value |
| --- | --- |
| Branch | `codex/trusted-network-material-dialog-clean` |
| Base HEAD after rebase | `2e8ad308097f49a5323d9fa20d6b0484930bf70e` |
| Tested source state | PR #768 standard-message `baseline/AndroidClient` source/test diff from the base HEAD to this package's head |
| Base-to-head `baseline/AndroidClient` diff SHA-256 | `5d9a4c4c0a99e72f126c1712beeb6465df698d4f34daf20233d9d1a0d9319175` |
| Evidence package date | 2026-09-11 |
| Timezone | Asia/Shanghai |

The local branch has been rebased onto current `origin/main`, including #770 and
#763. The base HEAD is not claimed as the tested PR source; the tested state is
the committed `baseline/AndroidClient` PR diff above it. The checksum was
computed with:

```bash
git diff --binary 2e8ad308097f49a5323d9fa20d6b0484930bf70e HEAD -- baseline/AndroidClient | shasum -a 256
```

No Host operation, TCC operation, `adb reverse`, or final device test was
performed in this handoff.

See `metadata/source-provenance.txt` for the retained source state and local
change summary.

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Focused JVM contract tests plus Android instrumentation Kotlin compile | `logs/focused-jvm-and-androidtest-compile-standard-message.log`, `logs/focused-jvm-and-androidtest-compile-standard-message.status`, `unit-test-results/` | PASS, Gradle `BUILD SUCCESSFUL`; `WirelessTabControllerContractTest` 6/6 and `MainActivityTerminalGuidanceContractTest` 72/72 |
| Full Android CI-equivalent local gate | `.build/pr768/baseline-android-check-after-lint-fix.log` (not retained in this evidence package) | PASS, `make baseline-android-check`; includes `:transport:check --configuration-cache --configuration-cache-problems=fail`, `testDebugUnitTest`, `lintDebug`, `assembleDebug`, and `auditReleaseDependencies` |
| Earlier device instrumentation before the first abandoned custom-content attempt | `android-test-results/trusted-network-dialog-am-instrument.failed-before-height-fix.raw.txt` | FAIL, `Tests run: 4, Failures: 1`; `trusted network content stays above dialog actions` |
| Earlier device instrumentation after the abandoned intermediate custom-content attempt | `android-test-results/trusted-network-dialog-am-instrument.failed-after-content-height-fix.raw.txt`, `android-test-results/trusted-network-dialog-am-instrument.raw.txt` | FAIL, `INSTRUMENTATION_STATUS_CODE: -2` and `Tests run: 4, Failures: 1`; `trusted network content stays above dialog actions` |
| Device cleanup after the second failed run | `logs/after-second-failure-cleanup.summary` | PASS, force-stop status 0, test process absent, adb reverse empty after whitespace trim |

Final local validation command:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon :app:testDebugUnitTest \
  --tests dev.telemachus.display.WirelessTabControllerContractTest \
  --tests dev.telemachus.display.MainActivityTerminalGuidanceContractTest \
  :app:compileDebugAndroidTestKotlin
```

The final command did not run a device test and did not use `adb`.

## Retained Failure Boundary

The retained device failures predate the final standard `setMessage(...)` source
state. They document why the abandoned custom-content direction was rejected and
must not be read as final validation. A future device run, if explicitly
released, should run only
`dev.telemachus.display.TrustedNetworkDialogLayoutInstrumentedTest`, confirm the
test package is stopped before and after, confirm no reverse mapping exists, and
parse the raw output for `FAILURES!!!`, `INSTRUMENTATION_STATUS_CODE: -2`, and
`Tests run: ..., Failures: ...`.

## Integrity

Verify retained evidence from the evidence package directory with:

```bash
cd docs/changes/2026-08-22-android-ui-ux-audit/evidence/2026-09-11-pr768-trusted-network-dialog-local-head
shasum -a 256 -c SHA256SUMS
```
