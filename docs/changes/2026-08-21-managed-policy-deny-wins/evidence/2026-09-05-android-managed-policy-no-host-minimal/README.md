# Android managed-policy no-Host minimal refresh

Verdict: PASS for offline Android/JVM policy enforcement; real product E2E
remains open.
Date: 2026-09-05
Base: current `origin/main` commit `91d7414454ac1161edbd2ed4ad9aa252ed559066` plus this focused change.

## Scope

This record covers only Android/JVM managed-policy deny-wins behavior for
clipboard and file-transfer policy boundaries. No macOS Host was started, no
Swift command was run, no Screen Recording, Accessibility, or Microphone/TCC
permission was requested, and no `adb reverse tcp:54321` was configured.

## Kept From The Old Branch

- Apply the local Android managed-policy file-transfer snapshot before USB/LAN
  Protocol v1 client capability/resource-limit advertisement and before
  negotiated file-transfer policy calculation.
- Add no-host JVM coverage proving a remote clipboard deny removes clipboard
  from the effective negotiated surface and produces no outgoing clipboard offer
  or request envelope.
- Add no-host JVM coverage proving a local managed `MaximumFileBytes` value
  constrains both ClientHello resource limits and the negotiated file-transfer
  policy even when the Host peer does not negotiate managed configuration.

## Deliberately Not Kept

- No old-branch device, Host-backed, or Android Enterprise delivery claim was
  imported.
- No broad UI/UX evidence directory churn was imported.
- No MacHost, Swift, TCC, Screen Recording, Accessibility, Microphone, or ADB
  reverse workflow was introduced for this no-host baseline.

## Verified

- Android managed configuration parsing, protocol deny-wins, UI/session policy
  coordination, WakeHost policy cleanup, clipboard denial, file-transfer denial,
  and local `MaximumFileBytes` USB/LAN negotiation were covered by focused JVM
  tests.
- A broader Android JVM regression covering Protocol v1, file transfer,
  StreamClient integration, and Internet managed-policy parity passed.
- Android lint passed.
- Source/readiness and fail-closed guardrails still keep real clipboard and
  file-transfer product E2E gates blocked without Host/product evidence.

## Commands

```bash
cd baseline/AndroidClient
./gradlew --no-daemon :app:testDebugUnitTest \
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardFailClosedTest \
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest \
  --tests dev.telemachus.display.FileTransferProductOwnerTest \
  --tests dev.telemachus.display.ManagedConfigurationProviderTest \
  --tests dev.telemachus.display.ProductSessionCoordinatorTest \
  --tests dev.telemachus.display.MainActivityControllerForwardingContractTest
```

Result: `BUILD SUCCESSFUL in 46s`.

```bash
cd baseline/AndroidClient
./gradlew --no-daemon :app:testDebugUnitTest \
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest \
  --tests dev.telemachus.display.protocol.FileTransferSessionTest \
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardFailClosedTest \
  --tests dev.telemachus.display.FileTransferProductOwnerTest \
  --tests dev.telemachus.display.ManagedConfigurationProviderTest \
  --tests dev.telemachus.display.ProductSessionCoordinatorTest \
  --tests dev.telemachus.display.MainActivityControllerForwardingContractTest \
  --tests dev.telemachus.display.StreamClientProtocolV1IntegrationTest \
  --tests dev.telemachus.display.internet.InternetClipboardTest \
  --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest
```

Result: `BUILD SUCCESSFUL in 14s`.

```bash
cd baseline/AndroidClient
./gradlew --no-daemon :app:testDebugUnitTest
```

Result: `BUILD SUCCESSFUL in 24s`.

```bash
cd baseline/AndroidClient
./gradlew --no-daemon :app:lintDebug
```

Result: `BUILD SUCCESSFUL in 29s`.

```bash
make baseline-android-check
```

Result: `BUILD SUCCESSFUL`; this reran the transport boundary gate, Android
JVM tests, lint, assembleDebug, and release dependency audit.

```bash
make phase5-host-advanced-adapters-gate
```

Result: pass; wrote
`.build/evidence/phase5-host-advanced-adapters-readiness.json` with
`verdict=pass`.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest \
  tools.tests.test_clipboard_e2e_gate \
  tools.tests.test_file_transfer_android_smoke \
  tools.tests.test_file_transfer_bulk_current_base_gate \
  tools.tests.test_file_transfer_bulk_current_base_manifest -v
```

Result: `Ran 80 tests ... OK`; generated reports still mark real clipboard and
file-transfer product E2E gates blocked because Host readiness and retained
bidirectional product evidence remain unavailable.

## Not Proved

- Real Android Enterprise app-restrictions delivery through
  `RestrictionsManager.applicationRestrictions`.
- Android `ClipboardManager` <-> macOS `NSPasteboard` managed-policy denial
  over USB or trusted LAN.
- Android file-transfer bytes, cancellation, digest verification, or filesystem
  landing against a real macOS Host session under managed-policy denial.
- Any Xiaomi 13/fuxi or Nubia P0110/pacific device behavior for this specific
  no-host refresh.
