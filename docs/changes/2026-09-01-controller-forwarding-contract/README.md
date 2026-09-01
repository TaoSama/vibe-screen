# Controller Forwarding Recovery Audit

Date: 2026-09-01

## Scope

This record preserves and audits the two controller-forwarding salvage
worktrees named in the recovery request. The source worktrees were treated as
read-only. No source-directory rebase, reset, stash, clean, checkout, or file
write was performed. The only recovered artifacts live under this change
directory.

The requested implementation scope was controller contract, fixtures, Android
mapper/session/Internet forwarding, exactly-once connection acknowledgement,
neutral release, and offline gates. Physical controller evidence and macOS
virtual-HID runtime acceptance remain outside this scope and are not claimed by
this record.

## Recovery Snapshot

The source recovery snapshot is retained at:

- [source-recovery/run-20260901-133809](evidence/source-recovery/run-20260901-133809)

For each source worktree the snapshot contains:

- `manifest.txt` with the source path, branch, HEAD, and artifact paths
- `status.short.txt` and `status.porcelain.z`
- `diff.patch` and `cached.diff.patch`
- `untracked-files.txt`, `untracked-files.tar`, `untracked-files.sha256`, and `recovered-untracked-files.sha256`

The Android source had four untracked files. They were copied into the snapshot
and checksummed. The contract source had no untracked files.

## Source Conclusions

`controller-contract-salvage` at
`2d39bf7f78eda88aa8813bb18c0068ccb8e6574d` contained a fully staged protocol
contract patch. Current `origin/main` already contains the controller contract
as a stronger superset: `ControllerEvent`, `CAPABILITY_CONTROLLER`, controller
fixtures, controller validation, controller reference tests, exactly-once
connection acknowledgement constraints, maximum active controller rejection,
ProtocolError behavior, `PeripheralEvent`, and the retained USB HID modifier
capability and fixtures. The salvage patch also removed USB HID modifier
fixtures and failed its own fixture set check because generated/checked fixture
state drifted. It was therefore not migrated.

`android-controller-forwarding` at
`f9cd290b701030b82d30c36879f5e1e1cf4a072a` contained mixed staged and unstaged
Android controller work based on an older architecture. Current `origin/main`
already carries the equivalent behavior after later owner-boundary refactors:
Android controller mapping/state, `StreamInputDispatcher` forwarding,
`ControllerSessionFeedback`, `SessionInputIdSequence`, Internet controller send
queueing, input acknowledgement correlation, recovery resynchronization,
neutral release, and focused unit coverage. Directly applying the source patch
would overwrite newer owner boundaries and was therefore rejected.

## Mainline State

The recovered behavior is represented in current source by these main files:

- `contracts/proto/vibescreen/protocol/v1/input.proto`
- `contracts/fixtures/messages/v1/controller_validation.json`
- `contracts/reference/controller_event.py`
- `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/ControllerInputMapper.kt`
- `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/ControllerSessionFeedback.kt`
- `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/SessionInputIdSequence.kt`
- `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/StreamInputDispatcher.kt`
- `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet/InternetControllerSendQueue.kt`
- `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet/InternetProductSession.kt`
- `baseline/MacHost/Sources/GameControllerInput.swift`
- `baseline/MacHost/Sources/GameControllerVirtualHID.swift`

The salvage review also exposed an Android controller acknowledgement parity
gap that was not safe to leave as documentation-only: controller batches could
place a `STATE` or `DISCONNECTED` event behind a new `CONNECTED` event before
the Host accepted that controller lifecycle. The recovered mainline now
suppresses all non-`CONNECTED` events for a controller while its connection
acknowledgement is pending across both the USB/LAN dispatcher and Internet
session paths. Same-connection `STATE` is dropped and recovered by
`MainActivity` through an acknowledgement-triggered full-state
resynchronization. A pending `DISCONNECTED` is deferred as exactly one cleanup
event that is sent only after the Host accepts the matching `CONNECTED`;
rejected, stale, and closed-session ACK paths do not emit cleanup. Newer epochs
for the same controller wait behind the accepted old-epoch cleanup so Host
lifecycle ordering remains valid.
Focused Android session tests cover ACK-before-state ordering, USB/LAN and
Internet deferred disconnect cleanup, transport backpressure before ACK
tracking, stale/rejected/closed ACK cleanup suppression, same-controller epoch
replacement ordering, rejected-ACK replay without cleanup, session reset
cleanup, and cleanup backpressure retention.

The Android README was updated to document the now-current controller forwarding
behavior and its blocked runtime acceptance boundary.

## Remaining Risks

The offline recovery does not add a controller ACK timeout, unknown-input ACK
fail-closed policy, duplicate `CONNECTED` soft-failure policy, or physical
`DISCONNECTED` runtime evidence. Those are broader protocol-lifecycle policy
changes and remain unproven by this recovery. They should be handled under a
separate scoped change if the product wants behavior beyond the existing
session reset and offline gates.

## Verification Plan

Run only offline and build gates for this recovery. Do not use ADB, do not start
the Host, and do not touch TCC or Keychain.

Required checks:

```bash
make protocol
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest contracts.tests.test_protocol_fixtures contracts.tests.test_security_contract contracts.tests.test_controller_reference -v
shasum -a 256 -c docs/changes/2026-09-01-controller-forwarding-contract/evidence/source-recovery/run-20260901-133809/SHA256SUMS
cd baseline/AndroidClient && ./gradlew testDebugUnitTest lintDebug assembleDebug
```

These checks can support controller protocol and Android forwarding readiness.
They cannot close the physical controller or virtual-HID runtime acceptance
gate.

## Verification Results

Executed from current branch `codex/controller-forwarding-contract-20260901`
rebased on `origin/main` commit
`c1e23d3e54bc706aaa8f010acb101beb46278280`.

| Check | Result | Evidence |
| --- | --- | --- |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.internet.InternetProductSessionTest --tests dev.telemachus.display.ControllerSessionFeedbackTest --tests dev.telemachus.display.StreamInputDispatcherTest --tests dev.telemachus.display.MainActivityControllerForwardingContractTest --tests dev.telemachus.display.StreamClientProtocolV1IntegrationTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest` | PASS | Focused Android controller ACK gate, deferred disconnect cleanup, tracker, USB/LAN dispatcher, MainActivity resync, StreamClient integration, and Protocol v1 session tests passed |
| `make protocol` | PASS | 45 protocol/fixture/security/shared-model tests passed after Buf format/lint/build/breaking checks |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest contracts.tests.test_protocol_fixtures contracts.tests.test_security_contract contracts.tests.test_controller_reference -v` | PASS | Targeted protocol fixture, security contract, and controller reference tests passed |
| `shasum -a 256 -c docs/changes/2026-09-01-controller-forwarding-contract/evidence/source-recovery/run-20260901-133809/SHA256SUMS` | PASS | Recovered source snapshot checksum manifest validated |
| `cd baseline/MacHost && swift test --filter ProtocolV1SessionTests && swift test --filter GameController && swift test --filter InternetProductSessionTests && swift test --filter InternetProductProtocolCodecTests && swift test --filter StreamingServerLifecycleTests && swift test --filter IOKitVirtualGamepadDeviceTests` | BLOCKED | Local Command Line Tools Swift environment cannot import XCTest, so Mac offline XCTest did not run in this worktree |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest` | PASS | Android JVM unit tests built and passed |
| `cd baseline/AndroidClient && ./gradlew --no-daemon lintDebug assembleDebug :transport:check assembleDebugAndroidTest` | PASS | Android lint, debug APK assembly, transport module check, and debug instrumentation APK assembly completed without installing or launching an app |

No ADB command was run, no Host process was started, and no TCC or Keychain
state was touched during this recovery.
