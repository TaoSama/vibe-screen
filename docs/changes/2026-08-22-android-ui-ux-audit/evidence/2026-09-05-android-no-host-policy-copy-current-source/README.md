# Android no-Host transfer policy and copyable guidance current-source

Date: 2026-09-05

Branch: `codex/android-no-host-uiux-20260905`

Source revision: the containing commit for this evidence package.

Base source revision: `5b1b62c1248715e34d43a4d104235dd1cf7c057b`

Device: not exercised for this source-only record.

## Scope

This is Android-client source and offline verification evidence only. The run
deliberately kept the macOS Host out of scope: no Host binary was launched, no
Screen Recording or Accessibility/TCC path was exercised, no `adb reverse
tcp:54321 tcp:54321` was created, and no Protocol v1 product session was
negotiated.

The change improves two no-Host or pre-session UI paths:

- Settings transfer readiness now distinguishes clipboard and file-transfer
  managed-policy denial from generic compatibility or unavailable states, using
  deny-wins local and remote policy availability.
- USB inline recovery guidance is selectable so users can copy ports and
  recovery instructions from the error card.

## Valid Evidence

| Area | Command | Result |
| --- | --- | --- |
| Focused JVM tests | `cd baseline/AndroidClient && ./gradlew --no-daemon clean testDebugUnitTest --tests "dev.telemachus.display.ClientExperienceTest" --tests "dev.telemachus.display.ManagedPolicyUiAvailabilityPolicyTest" --tests "dev.telemachus.display.MainActivityTransferReadinessContractTest" --tests "dev.telemachus.display.MainActivityTerminalGuidanceContractTest"` | Passed: `BUILD SUCCESSFUL in 41s`, 41 actionable tasks executed. |
| Android lint/build/unit tests | `cd baseline/AndroidClient && ./gradlew --no-daemon lintDebug assembleDebug testDebugUnitTest` | Passed: `BUILD SUCCESSFUL in 37s`, 68 actionable tasks, 31 executed, 37 up-to-date. |
| Diff hygiene | `git diff --check` | Passed with no whitespace errors before adding this evidence README. |

An earlier focused Gradle attempt failed while another agent was still active
against the same Android build tree, with missing incremental Kotlin class
outputs under `app/build/tmp/kotlin-classes/debug`. After interrupting the
parallel read-only review and rebuilding through Gradle `clean`, the focused
tests and the wider Android offline verification both passed.

## Not Proven

This package does not prove Android device rendering, Android <-> macOS
clipboard transfer, file-transfer offer/request/content packets, receiver
approval, saved remote file bytes, SHA-256 equality across endpoints, Protocol
v1 capability negotiation, USB/LAN transport readiness, public Internet
traversal, video decode, input forwarding, reconnect timing, Host signing/TCC
readiness, display switching, window actions, Nubia P0110 behavior, or Xiaomi
13/fuxi behavior.

## Review Notes

Old no-Host UI/UX branches were scanned for small improvements worth absorbing.
The only low-risk candidate already aligned with this change was copyable USB
guidance. Larger alternatives such as a settings-button position grid or modal
file-transfer progress dialog were intentionally left out because current main
uses control-bar settings and inline transfer progress.
