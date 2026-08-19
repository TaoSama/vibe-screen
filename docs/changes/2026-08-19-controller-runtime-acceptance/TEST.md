# Controller runtime acceptance gate

Date: 2026-08-19

## Scope

This record advances the controller runtime gate without converting offline
coverage into device evidence. Android production forwarding is present in the
current source path: controller key events enter `MainActivity.dispatchKeyEvent`,
controller motion events enter `MainActivity.handleGenericMotion`, and both route
through `StreamClient.sendController` when Protocol v1 negotiates
`CAPABILITY_CONTROLLER`.

That source wiring does not close runtime acceptance. The remaining gate needs a
named physical Android controller, accepted controller capability, an
identity-signed Host build with the approved virtual HID entitlement, Host
virtual-gamepad runtime availability, a visible Mac-side controller target, and
neutral release on disconnect.

## Current blocked evidence

The local environment used for this update did not have a physical Android
controller attached and did not have an identity-signed, entitled Host capable of
creating a virtual gamepad. The evidence summary is therefore intentionally
`blocked`, not `pass`:

- [blocked-local/controller-runtime-summary.json](evidence/blocked-local/controller-runtime-summary.json)
- [blocked-local/controller-runtime-observations.json](evidence/blocked-local/controller-runtime-observations.json)

Recreate the summary with:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.controller_runtime \
  docs/changes/2026-08-19-controller-runtime-acceptance/evidence/blocked-local/controller-runtime-observations.json \
  --run-id 2026-08-19-blocked-local \
  --output docs/changes/2026-08-19-controller-runtime-acceptance/evidence/blocked-local/controller-runtime-summary.json
```

## Offline verification

The source/documentation update was verified with the local offline gates listed
in [build-and-test-results.txt](evidence/blocked-local/build-and-test-results.txt).
The Android and evidence-tool checks passed. MacHost release build passed. MacHost
XCTest remained blocked in this local environment because `xcode-select` points to
Command Line Tools and SwiftPM cannot import `XCTest`; this does not prove or
disprove controller runtime acceptance.

