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

The salvage review also exposed one Internet-specific parity gap that was not
safe to leave as documentation-only: Internet controller batches could place a
`STATE` event behind a new `CONNECTED` event before the Host accepted that
controller lifecycle. The recovered mainline now drops same-connection `STATE`
events while the connection acknowledgement is pending and relies on
`MainActivity` to send a fresh full-state resynchronization when the accepted
ACK is correlated back to that controller. This matches the USB/LAN behavior
without replaying a stale queued state snapshot.
Focused Internet session tests cover ACK-before-state ordering, transport
backpressure before ACK tracking, disconnect while a connection ACK is pending,
and mixed pending/accepted controller state dispatch.

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
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest contracts.tests.test_protocol_fixtures contracts.tests.test_security_contract -v
cd baseline/AndroidClient && ./gradlew testDebugUnitTest lintDebug assembleDebug
```

These checks can support controller protocol and Android forwarding readiness.
They cannot close the physical controller or virtual-HID runtime acceptance
gate.

## Verification Results

Executed from current branch `codex/controller-forwarding-contract-20260901`
after fast-forwarding to `origin/main` commit
`f1fde5fdbd4f7148e992bfe4e7a5cdcfef87f484`.

| Check | Result | Evidence |
| --- | --- | --- |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.internet.InternetProductSessionTest --tests dev.telemachus.display.MainActivityControllerForwardingContractTest` | PASS | Focused Internet controller ACK gate and MainActivity resync regression tests passed |
| `make protocol` | PASS | 45 protocol/fixture/security/shared-model tests passed after Buf format/lint/build/breaking checks |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest contracts.tests.test_protocol_fixtures contracts.tests.test_security_contract -v` | PASS | 29 targeted protocol fixture and security contract tests passed |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest` | PASS | Android JVM unit tests built and passed |
| `cd baseline/AndroidClient && ./gradlew --no-daemon lintDebug assembleDebug` | PASS | Lint report generated and debug APK assembled |
| `cd baseline/AndroidClient && ./gradlew --no-daemon :transport:check assembleDebugAndroidTest` | PASS | Transport boundary checks and instrumentation APK assembly passed |

No ADB command was run, no Host process was started, and no TCC or Keychain
state was touched during this recovery.
