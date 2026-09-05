# Nubia P0110 no-Host managed-policy empty restrictions smoke

Date: 2026-09-06
Status: PASS for unmanaged empty `RestrictionsManager.applicationRestrictions`
device smoke; managed-policy product E2E remains open.

## Source State

- Main baseline: `origin/main` at
  `94992a5a7f429521b85f16a0111af5e719784998`.
- Source under test: PR branch
  `codex/android-no-host-policy-av1-instrumentation-20260906` with the
  no-Host instrumentation changes applied on top of that baseline.
- Scope: Android no-Host instrumentation only. No macOS Host was started, no
  Swift command was run, no Screen Recording/Accessibility/TCC/Keychain or
  System Settings operation was performed, and no `adb reverse` was created or
  removed.

## Device Identity

- Manufacturer/model: nubia P0110
- Codename: pacific
- Android: 16
- SDK: 36
- Serial: `<redacted-device-serial>`

## Verified

The new `ManagedConfigurationProviderInstrumentedTest` uses a real Android
application `Context` and the platform `RestrictionsManager`. On the connected
unmanaged device, `RestrictionsManager.applicationRestrictions` returned an
empty Bundle, and `ManagedConfigurationProvider(context).loadPolicy()` returned
`ProtocolV1Session.ManagedPolicy.UNMANAGED`.

This closes only the empty-restrictions no-Host device smoke. It does not prove
Android Enterprise delivery of a non-empty managed restrictions payload, USB/LAN
product enforcement, or any macOS Host interop.

## Command Result

```bash
cd baseline/AndroidClient
./gradlew --no-daemon :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ManagedConfigurationProviderInstrumentedTest,dev.telemachus.display.CodecAdmissionInstrumentedTest
```

Result: `BUILD SUCCESSFUL in 16s`; Gradle reported `Starting 2 tests on P0110 -
16` and `Finished 2 tests on P0110 - 16`.

See `commands.txt` for the exact sanitized command set.
