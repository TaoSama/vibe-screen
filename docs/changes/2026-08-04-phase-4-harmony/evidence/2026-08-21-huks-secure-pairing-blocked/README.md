# HarmonyOS HUKS secure-pairing blocked record

Date: 2026-08-21
Source base: `22da26816465257b4a09f95de47be8567e448b74`

This record documents a source/verifier closure for the Phase 4 HUKS-backed
secure-pairing gap. It is not HarmonyOS device acceptance evidence.

## What is covered

- Harmony portable pairing now requires a `harmony_huks_v1` security profile
  before producing `PairingRequest`.
- The required profile pins non-exportable P-256 signing keys, HUKS-bound
  credential storage, persistent identity, and an Authority device ID matching
  the signed device identity.
- Stored secure-pairing credentials are version 2 and must include that profile.
  Legacy records, missing profiles, no-HUKS providers, exported-key profiles,
  and Authority-device mismatches fail closed.
- Portable tests cover single-use PairingOffer/Request/Result handling,
  host-signature verification, encrypted credential install, replay high-water,
  revocation tombstones, expired result rejection, and no-HUKS rejection.
- `scripts/harmony_secure_pairing_gate.py` defines the redacted evidence
  contract required before a real MatePad Mini run can close the HUKS gate.

## Why this remains blocked

The current Codex environment does not have DevEco Studio, the HarmonyOS NEXT
SDK/HDC, a signed release HAP, a MatePad Mini, a live HUKS runtime, production
Authority/Signaling deployment, or a public network path. Android devices,
including nubia P0110 / pacific / Android 16 / SDK 36, cannot close this
HarmonyOS gate.

## Re-run commands

```bash
cd /Users/luwentao/Workspaces/vibe-screen/.claude/worktrees/harmony-huks-secure-pairing-20260821
cd apps/harmony && pnpm run verify
cd ../.. && python3 -m unittest scripts.tests.test_harmony_secure_pairing_gate -v
python3 scripts/harmony_secure_pairing_gate.py --allow-blocked docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-21-huks-secure-pairing-blocked/harmony-secure-pairing.json
```

A real acceptance run must replace the blocked manifest values with redacted
DevEco, signed-HAP, HUKS, MatePad Mini, Host, Authority, Signaling, replay,
revocation, and old-peer/no-HUKS rejection artifacts, then run:

```bash
make harmony-secure-pairing-gate EVIDENCE_DIR=/path/to/evidence
make harmony-device-gate EVIDENCE_DIR=/path/to/evidence
```
