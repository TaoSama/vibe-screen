# 2026-09-07 permission reprompt audit

## Scope

This record investigates why a previously usable macOS Host can appear to ask
for Screen Recording and Accessibility again. The audit was source-only and
read-only: it did not launch Vibe Screen, run `swift run`, open System Settings,
request or reset TCC permissions, modify Keychain, install a Host bundle, or
touch Android/ADB state.

The checkout inspected was `ac842cf8934e98d5e7d405b3ababdba2482966a5`.

## Findings

The current Host startup path does not actively request Screen Recording or
Accessibility permission. `applicationDidFinishLaunching`, the two-second
refresh path, and the asynchronous permission check use
`CGPreflightScreenCaptureAccess()` and `AXIsProcessTrusted()` to observe state.
The permission-request APIs remain confined to explicit user actions from the
onboarding or settings UI: `requestScreenRecordingPermission()` calls
`CGRequestScreenCaptureAccess()` and opens the Screen Recording pane only after
that explicit action, while `requestAccessibilityPermission()` calls
`AXIsProcessTrustedWithOptions` with the prompt option only after the explicit
Accessibility action.

The most likely reason for seeing the permission UI again is Host identity
drift, not a startup-request regression. macOS TCC grants are bound to the
installed app identity through the bundle identifier and decoded designated
requirement. Stable `/Applications/Vibe Screen.app` path, signing leaf, and
source provenance are separate repository readiness gates: they prove the
installed Host is the intended current artifact before read-only TCC rows are
accepted as evidence for runtime claims. Rebuilt, re-signed, ad-hoc, or
non-canonical Host bundles can therefore leave the repository unable to prove
that existing TCC rows apply to the exact Host under test.

The current local readiness blocker pattern is therefore consistent with macOS
seeing a different Host identity or with the repository being unable to prove
the same identity. The latest retained compatibility evidence remained blocked
because the configured `Vibe Screen Dev` identity was missing, strict codesign
inspection of `/Applications/Vibe Screen.app` failed, installed source
provenance could not be read, Screen Recording and Accessibility could not be
verified from read-only TCC evidence, no TCP `54321` listener was observed, the
virtual HID entitlement was missing, and full Xcode was unavailable.

## Regression check

No code regression was found that moved Screen Recording or Accessibility
request APIs into launch, automatic start, polling, or manual start failure
paths. The static permission-prompt contract now also asserts that the manual
start missing-permission alert is explanatory only: it must not call
`CGRequestScreenCaptureAccess`, `AXIsProcessTrustedWithOptions`,
`kAXTrustedCheckOptionPrompt`, `NSWorkspace.shared.open`, either privacy URL,
or either explicit request wrapper.

## Verification

```bash
make baseline-macos-permission-prompt-contract
python3 -m py_compile scripts/macos_dev_host.py scripts/tests/test_macos_dev_host.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts.tests.test_macos_dev_host -v
```

Results: the permission-prompt contract passed, Python compilation passed, and
`scripts.tests.test_macos_dev_host` passed 143 tests. No Host GUI, `swift run`,
TCC mutation, Keychain mutation, System Settings launch, app installation, or
ADB reverse setup was used.

## Evidence references

- `baseline/MacHost/Sources/AppDelegate.swift`: startup state seeding uses only
  `CGPreflightScreenCaptureAccess()` and `AXIsProcessTrusted()`; refresh and
  `checkPermissions()` use the same observation APIs; request APIs are confined
  to `requestScreenRecordingPermission()` and `requestAccessibilityPermission()`.
- `baseline/MacHost/Sources/PermissionOnboardingView.swift` and
  `baseline/MacHost/Sources/SettingsWindow.swift`: UI buttons are the call sites
  for the explicit request wrappers.
- `scripts/verify_macos_permission_prompt_contract.swift`: static contract
  rejects permission-request APIs, prompt options, privacy URLs, and System
  Settings opens outside explicit user-action functions.
- `scripts/macos_dev_host.py`: readiness records TCC identity binding, checks
  stable install path, canonical designated requirement/signing leaf, source
  provenance, read-only TCC rows, listener state, and virtual HID entitlement;
  the safety record states that readiness does not start the Host GUI, request
  permissions, modify TCC, or modify Keychain.

## Remaining blockers

This audit does not close any runtime gate. The next runtime-capable step still
requires a stable `Vibe Screen Dev` codesigning identity, a strict-codesign
passing `/Applications/Vibe Screen.app` built from the current clean source with
embedded commit/tree provenance, Screen Recording and Accessibility grants for
that exact app identity proven through read-only TCC rows, full Xcode build/test
evidence, and then the real Host listener plus USB/LAN runtime probes.
