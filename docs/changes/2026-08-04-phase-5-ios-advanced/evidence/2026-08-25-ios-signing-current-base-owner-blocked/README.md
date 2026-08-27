# iOS app-signing readiness current-base owner record

Date: 2026-08-25
Scope: Phase 5 iOS app-signing readiness prerequisite
Verdict: blocked

## Owner identity

- Owner role: `ios_app_signing_readiness_current_base_owner`
- Owner branch: `codex/phase5-ios-signing-readiness`
- Repository: `TaoSama/vibe-screen`

## Current-base state

This record establishes the dedicated fail-closed owner shape for iOS
app-signing readiness on the current base. It does not include retained signing
material and therefore cannot close the signing prerequisite. A passing evidence
bundle must be generated from a clean current-base commit and must include only
sanitized public summaries.

Machine-readable artifacts in this directory:

- `ios-app-signing-readiness.json`: sanitized blocked input fixture with the
  current-base commit and no signing material.
- `ios-app-signing-readiness-gate.json`: generated dedicated owner gate output
  with `verdict=blocked`, `can_close_ios_app_signing_readiness=false`, and
  `can_close_ios_device_acceptance=false`.
- `ios-current-base-manifest.json` and `ios-current-base-gate.json`: generated
  aggregate binding outputs showing the signing row and broader Phase 5 device
  gates remain blocked.
- `commands.txt`, `privacy-scan.json`, and `SHA256SUMS`: retained command log,
  privacy scan, and checksum manifest for this blocked owner record.

Required retained evidence remains open for:

- Apple Team ID recording
- provisioning profile UUID recording
- unique iPhoneOS bundle ID
- non-ad-hoc codesign identity recording
- registered physical-device UDID hashes
- signed-app entitlements
- signed app or archive SHA-256
- archive command, codesign-entitlements, and provisioning-profile artifacts

## Gate commands

Run from the repository root with a sanitized readiness JSON:

```bash
make ios-app-signing-readiness-gate \
  IOS_APP_SIGNING_READINESS_JSON=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/YYYY-MM-DD-ios-signing/ios-app-signing-readiness.json

make ios-current-base-gate \
  EVIDENCE_DIR=.build/evidence/ios-current-base \
  IOS_APP_SIGNING_READINESS_GATE_JSON=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/YYYY-MM-DD-ios-signing/ios-app-signing-readiness-gate.json
```

The aggregate gate accepts the signing row only when the bound readiness gate
declares `owner.role=ios_app_signing_readiness_current_base_owner`,
`owner.head_ref=codex/phase5-ios-signing-readiness`,
`owner.repository=TaoSama/vibe-screen`, and a complete sanitized
`signing_summary` from a clean current-base commit.

For this blocked record, `make ios-app-signing-readiness-gate` exits nonzero
after writing the gate JSON because signing material is absent. The aggregate
command also exits nonzero as expected: it consumes the dedicated owner JSON and
keeps `can_close_ios_device_acceptance=false` and
`can_close_current_base_aggregate=false`.

## Not proven

This record does not prove iOS signing, install, launch, VideoToolbox decode,
input, reconnect, audio playback, HDR output, or full iPhone/iPad device
acceptance. Simulator, unsigned, ad-hoc, Android-derived, or hand-written
manifest-only evidence must remain blocked or failed by the machine gates.
