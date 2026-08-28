# Current-base owner blocked evidence

This package records the current-base owner state for the macOS Host signing,
TCC, and source-provenance gate. It is readiness evidence only: it proves the
gate remains fail-closed when the installed Host lacks a stable signing identity,
approved Screen Recording and Accessibility TCC rows, source-bound bundle
provenance, and same-commit Host self-test output.

- Base commit: `6cdb34a1fd9e87174f6113ff34603d8bf297eaef` (`origin/main`).
- Owner branch: `codex/host-signing-tcc-current-owner`.
- Required Host bundle id: `dev.telemachus.display`.
- Android substitute identity, when an Android helper run is needed: Nubia P0110,
  codename `pacific`, Android 16 / SDK 36, serial `<redacted-adb-serial>`, targeted
  explicitly with `adb -s <redacted-adb-serial>`. Nubia P0110 evidence must not be
  relabeled as Xiaomi 13/fuxi evidence.

The generated `macos-hardware-compatibility-gate.json` is expected to report
`verdict=blocked` and `can_close_macos_host_compatibility_row=false`. A blocked
result from this package cannot close USB, LAN, Host RSS, native-pointer,
stylus, controller, rotation, login/headless, or compatibility gates.

Draft/stale PR disposition from this owner pass:

- PR #160 supplied the most complete signing/TCC/source-bound direction and is
  superseded by this current-base owner subset for review.
- PR #233 and PR #288 are support/stale material after their runbook and gate
  requirements are absorbed here.
- PR #256 and PR #267 are already superseded by the current compatibility gate
  shape on main plus this owner hardening.
- PR #302 should remain separate because it covers login/headless/startup
  recovery, not the signing/TCC/current-source owner gate.
- Base commit: `6cdb34a1fd9e87174f6113ff34603d8bf297eaef` (`origin/main`).
+- Base commit: `1bbc8f9f3d29f4e17107c325060e16cbfbe9e323` (`origin/main`).
