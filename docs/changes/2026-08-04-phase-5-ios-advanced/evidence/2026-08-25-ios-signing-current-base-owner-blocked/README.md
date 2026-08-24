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

## Not proven

This record does not prove iOS signing, install, launch, VideoToolbox decode,
input, reconnect, audio playback, HDR output, or full iPhone/iPad device
acceptance. Simulator, unsigned, ad-hoc, Android-derived, or hand-written
manifest-only evidence must remain blocked or failed by the machine gates.
