# HarmonyOS current-base gate audit

Date: 2026-08-22
Base: origin/main at 4dc84505e6e0a07fa1052df12bca03824f161bf6

## Scope

This audit coordinates the overlapping HarmonyOS and MatePad Mini gate work on
top of the current main branch. It does not close a HarmonyOS real-device gate.
No DevEco SDK, signed HAP, HUKS-backed pairing run, AVCodec hardware decode,
resume-capable Host interop run, eight-hour MatePad Mini soak, or external
latency package was produced for this record.

The repository-wide open-gates baseline now lives in
docs/changes/2026-08-22-open-gates-coverage-audit/README.md on main. This file
is the narrower HarmonyOS follow-up: it keeps the focused Harmony PR owner
matrix, merge order, and strict evidence-root verifier boundary in one place.
PR #269 is this current-base follow-up. It does not supersede PR #239 as the
aggregate package owner; it makes the owner decision reviewable on current main
and adds the verifier hardening that prevents missing local artifacts from being
reported as device acceptance.

## Current-base aggregate owner

The aggregate owner should be the MatePad Mini acceptance package branch from
PR #239. It owns the final package shape that ties readiness, strict device
gates, domain-specific evidence, and the README Phase 4 claim together. The
current-base aggregate branch must absorb the README owner attribution from PR
#250, then reconcile focused gate IDs and runbook wording after each focused PR
is refreshed.

Focused PRs remain domain owners and should not independently claim the final
README aggregate state:

| PR | Branch | Domain owner | Current-base role |
| --- | --- | --- | --- |
| #202 | codex/harmonyos-auth-records | authenticated record contract verifier | focused security prerequisite; no Host/MatePad claim |
| #203 | codex/harmony-avcodec-hw-verify | AVCodec H.264/HEVC hardware decode preflight | focused decode prerequisite; no DevEco/HAP/MatePad pass |
| #204 | codex/harmony-huks-secure-pairing-20260821 | HUKS secure pairing gate | focused pairing prerequisite; no runtime HUKS or Host claim |
| #205 | codex/harmonyos-host-resume-interop | Host resume interoperability preflight | focused Host/client prerequisite; no MatePad resume pass |
| #206 | codex/harmony-hap-readiness | HAP lifecycle readiness gate | focused DevEco/HAP prerequisite; no device acceptance pass |
| #210 | codex/harmony-controller-input | controller input status drift guard | docs/static guard; fold controller lifecycle wording into aggregate |
| #239 | codex/harmony-matepad-acceptance-readiness | MatePad Mini aggregate package | preferred aggregate owner after refresh to current main |
| #250 | codex/harmony-phase4-gate-owners | README gate owner attribution | fold into the aggregate owner rather than merge standalone |
| #269 | codex/harmony-open-gates-owner | current-base owner audit and strict evidence-root guard | reviewable follow-up on current main; keeps the aggregate owner unique |

## Merge and conflict graph

After fetching origin/main at 4dc84505e6e0a07fa1052df12bca03824f161bf6,
PRs #210, #239, #250, and #269 are mergeable but behind until their branches
refresh. PRs #202, #203, #204, #205, and #206 conflict with current main and
need refresh before they can feed the aggregate owner.

Observed conflict hotspots are README.md, apps/harmony/README.md,
docs/changes/2026-08-04-phase-4-harmony/TEST.md,
docs/runbook/harmony-matepad-mini.md, Makefile,
scripts/harmony_device_gate.py, and scripts/tests/test_release_tools.py.

Recommended order:

1. Refresh or rebuild PR #239 on current origin/main as the single aggregate
   owner.
2. Fold PR #250 into that aggregate owner so README ownership is not split.
3. Fold PR #210 if its controller guard is still needed after the aggregate
   branch refreshes.
4. Refresh focused prerequisites in this order: #206 HAP lifecycle, #203
   AVCodec, #204 HUKS pairing, #202 authenticated records, #205 Host resume
   interop.
5. Reconcile the final gate ID list, Phase 4 verification record, MatePad
   runbook, and README wording only in the aggregate branch.

## Fail-closed verifier boundary

The strict harmony-device-gate validator is the current-base fail-closed guard
for final HarmonyOS acceptance claims. A strict pass requires every required
gate to be pass, a HarmonyOS NEXT MatePad Mini identity, signed HAP hashes,
a Protocol v1 Host build hash, a clean repository binding, and evidence
references. Blocked readiness records must use --allow-blocked and are not
acceptance evidence.

This branch tightens the strict path by making make harmony-device-gate pass
--evidence-root $(EVIDENCE_DIR). Direct strict script invocations default the
evidence root to the manifest directory. With that root, each strict-pass
evidence reference must be a repository-local relative file path that exists
under the evidence package. Absolute paths, URLs, directories, .. traversal,
and missing artifacts fail closed. --allow-blocked remains structure-only and
does not require local artifact files, so blocked readiness packages can still
be documented without being mistaken for acceptance.

## Still-open evidence

The following gates remain open until a real HarmonyOS NEXT MatePad Mini run
produces reviewed evidence:

- DevEco SDK sync and ArkTS/API checker output;
- signed debug/release HAP, checksum manifest, signing-certificate hash,
  install, launch, upgrade, rollback, and cleanup evidence;
- AVCodec H.264 and HEVC hardware-render evidence with decoder identity;
- HUKS-backed secure pairing, authenticated transport records, replay
  protection, and revocation evidence;
- resume-capable Protocol v1 Host interoperability across background,
  network roam, Host restart, and old-epoch rejection;
- touch, keyboard, pointer, wheel/trackpad, stylus, and controller behavior on
  the HarmonyOS device;
- eight-hour MatePad Mini soak with thermal, power, RSS, frame-drop, and queue
  metrics;
- external-camera glass-to-glass and input latency packages.

Android evidence, simulator output, portable TypeScript checks, readiness
preflights, and blocked manifests must not close any of those gates.
