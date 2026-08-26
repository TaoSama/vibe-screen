# Phase 3 current-base aggregation audit

Status: docs-only current-base audit; not Phase 3 Internet release evidence

Owner: Vibe Screen core team

Current base audited: `e94d3a051e6838c0c41ff710228ab742867fa193`
(`origin/main`, 2026-08-27)

## Purpose

This document records the current disposition of the Phase 3 Secure Internet
convergence queue after the earlier aggregate and several child gates landed on
`main`. It exists as human coordination evidence for PR and branch cleanup. The
executable release-gate source of truth is now on `main` through the merged
current-base summary and child verifiers listed below.

This is not a readiness package and does not close any Internet release gate.
Local loopback, forced local coturn, synthetic Protocol v1 peers, synthetic
pixel-buffer input, Android dialog instrumentation, and blocked preflights may
prove only the slice they execute. They do not prove public Internet traversal,
remote TURN deployment, real ScreenCaptureKit or CGDisplayStream capture, Android
MediaCodec decode, network handoff, cross-service revocation propagation, packet
capture confidentiality, external-camera latency, or a two-hour mixed-route soak.

## Current-base evidence ledger

| Evidence | Source binding | Current-base status | Boundary |
| --- | --- | --- | --- |
| Current `origin/main` | `e94d3a051e6838c0c41ff710228ab742867fa193` | Source contains the local Phase 3 product slice, production WebRTC adapters, application-record protection, local Authority/signaling/relay scaffolding, signaling multi-node waiter recovery, the production PostgreSQL signaling store slice, coturn reconciliation product-slice code, network handoff fresh-session code, revocation propagation gates, real-media/adaptive/DataChannel readiness gates, the generated current-base release-gate summary, release-gate manifest hardening, and later non-Phase 3 current-base owners such as WakeHost and the touch-rerun evidence gate. | No current public Internet release pass is recorded. Current evidence remains local, synthetic, historical, or blocked unless a named gate says otherwise. |
| Executable aggregate gate summary | Merged PR #258, commit `4b0c1eaad` | Current-base aggregate summary/checker is already on `main` and intentionally keeps public Internet release gates open. | It is fail-closed release-state tooling, not release evidence. Future child gates should feed or supersede it instead of duplicating aggregate ownership. |
| Open gates coverage audit | Merged PR #241, commit `4dc84505e` | Docs-only audit baseline is on `main`; it inventories missing evidence and duplicate/stale PR clusters. | It does not generate pass/fail release state. |
| Local readiness record | `docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-20-local-phase3-readiness/README.md`, commit `18a6ea70d0fbf6bc187f5a7242424ad3e88cf5ee` | Useful regression baseline for protocol, security/service/static tests, local Authority container, relay coturn scripts, and direct plus forced-local-coturn synthetic product E2E. | Local loopback only; no Android UI, real screen capture, public Internet path, real remote TURN, packet capture, handoff, revocation propagation, latency, or soak. |
| Current-main real-media attempts | `2026-08-18-nubia-p0110-current-main-real-media-blocked` and later current-base real-media gate records | Valid blocked evidence for the missing real capture-to-device decode path. | These records do not enter real ScreenCaptureKit capture, Android MediaCodec decode, or public Internet streaming acceptance. |
| Historical Nubia Internet interop | `docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-05-nubia-p0110-internet/README.md`, commit `597518f948075e396352bc353afcec01a30303f3` | Useful historical regression context for Nubia P0110/pacific Android 16, local Android UI, M144/M150 adapter interop, application AEAD, and synthetic media over direct plus forced local coturn. | Bound only to its dated source/device/media boundary. Not current-base evidence and not public Internet, real ScreenCaptureKit, visible Mac input, handoff, revocation, latency, or soak proof. |
| Public NAT/TURN readiness | Merged public NAT/TURN and Authority TURN readiness records | Current-base preflight/checker coverage exists and fails closed without production deployment evidence. | Checked-in production examples and local coturn runs are readiness fixtures only. |
| Withdrawn interop pointer | `docs/changes/2026-08-04-phase-3-secure-internet/evidence/android-product-interop.json` | Must remain withdrawn because the source commit and raw evidence are not bindable. | Do not cite as evidence for any current or historical gate. |
| Android dialog polish | `docs/changes/2026-08-21-android-internet-pairing-polish/evidence/2026-08-21-nubia-p0110-internet-dialogs/README.md` | Dated focused UI layout/input-safety evidence; bind it to its recorded source revision before using it as current-base context. | Does not prove pairing transport, WebRTC, public traversal, TURN, ScreenCaptureKit, streaming media, reconnect, or soak. |

## Release gates still open

The Phase 3 release gate remains open until at minimum the following, plus the
TECH/TEST security and operations gates, have current-base evidence on the
required target device and production-shaped services:

- public Internet direct path across a non-LAN topology, with route provenance;
- real remote TURN deployment, not loopback or host-local coturn;
- real ScreenCaptureKit or CGDisplayStream capture encoded by the host and decoded
  by Android MediaCodec, with visible continuity;
- automatic fresh-session recovery after real network handoff, including new
  signaling tokens, PeerConnection, record keys, epoch advance, and old-record
  rejection;
- cross-service revocation propagation, including active PeerConnection/TURN
  allocation termination and reconnect denial across routes;
- key rotation interoperability, rollback rejection, and documented old-key
  overlap behavior across Swift, Kotlin, and Go boundaries;
- cross-language canonical signing/AEAD fixtures, negative parser/fuzz coverage,
  and independent security review against the threat-model exit criteria;
- adaptive media behavior under real WebRTC statistics and controlled network
  impairment, not only policy/unit tests;
- production TLS, secret delivery, monitoring, multi-node restore and rollback
  drills, quota alerts, retention, and deletion checks;
- packet capture proving no plaintext content or credentials on direct and TURN
  paths;
- external-camera Internet glass-to-glass latency evidence;
- two-hour mixed direct/relay/network-change soak with bounded queues, memory,
  nonce use, latency, and media behavior;
- primary-target Android Internet evidence unless the requirement is explicitly
  changed. Nubia P0110/pacific evidence may be recorded separately but must not
  be relabeled as another device identity.

## Pull request disposition matrix

| PR | Current status on 2026-08-27 | Disposition | Reason |
| --- | --- | --- | --- |
| #164 Add Phase 3 release gate manifest verifier | Merged. | Treat as release-gate manifest hardening now included in current `main`. | It adds package-level validation hardening but still does not produce public Internet release evidence. |
| #171 Harden network recovery gate evidence | Merged. | Treat as current-base network recovery evidence-tooling context. | It is a fail-closed gate/preflight slice, not real handoff evidence. |
| #172 Add Phase 3 coturn reconciliation contract | Merged. | Treat as absorbed by the current coturn reconciliation lineage. | The later product slice on `main` extends this contract. |
| #173 Add Phase 3 real media continuity preflight | Merged. | Treat as the real-media continuity preflight baseline. | It keeps missing capture-to-device continuity blocked. |
| #188 Add Phase 3 release gate contracts | Closed draft; conflicting. | Do not revive as-is. | It is a stale broad bundle that overlaps merged aggregate, revocation, NAT/TURN, handoff, coturn, and real-media owners. |
| #190 Add Phase 3 revocation propagation verifier | Closed; successor work merged through #309 and #344. | Do not revive as-is. | Current `main` owns the revocation propagation gate surface while keeping active end-to-end revocation open. |
| #194 Add fail-closed Phase 3 public Internet evidence gates | Closed draft; conflicting. | Do not revive as-is. | Current `main` already has public NAT/TURN and release-gate readiness coverage, still fail-closed. |
| #200 Phase 3 authority session profile issuance | Closed; successor merged through #311 and later Authority/TURN readiness work. | Do not revive as-is. | Current `main` has the current-base issuance/readiness verifier path, but automatic product-flow issuance remains blocked. |
| #212 Add Phase 3 Internet latency gate verifier | Closed draft; conflicting. | Do not revive as-is; move any still-unique latency assertion into a fresh child gate if needed. | Current `main` has latency preflight/readiness records, but no real external-camera Internet latency pass. |
| #214 Add Phase 3 public Internet soak gate | Open draft; conflicting. | Rebase only if it still owns unique soak manifest/checker semantics; otherwise supersede into the merged release-gate package. | The release gate remains open because no two-hour mixed-route soak exists. |
| #215 Add production Postgres signaling store slice | Merged. | Treat as current production PostgreSQL signaling-store context. | Current `main` includes the production store slice, while public ingress, load-balancer behavior, remote services, and mixed-route release evidence remain open. |
| #216 Harden Phase 3 QR pairing verification | Closed; successor status is on `main`. | Do not revive as-is. | QR/lease hardening moved through later current-base work. |
| #223 Add signaling multi-node waiter lease recovery | Merged. | Treat as current signaling multi-node context. | Still does not prove public ingress, multi-instance throughput, load balancer behavior, or multi-region consistency. |
| #224 Add bounded network handoff recovery | Merged. | Treat as the runtime handoff-recovery baseline. | Real public handoff remains open until device/public-route evidence exists. |
| #228 Add coturn production reconciliation slice | Closed; successor merged through #341. | Do not revive as-is. | Current `main` owns coturn reconciliation product-slice code and readiness evidence. |
| #241 Add open gates coverage audit | Merged. | Treat as docs-only context. | Useful coverage inventory, not executable release-state tooling. |
| #248 Add current-base aggregation plan | This PR. Docs-only branch rebased on current `origin/main`. | It has no executable code value after #258 and the child gates merged; merge only if this human cleanup audit is wanted, otherwise close. | The remaining value is a stale-PR disposition record. It must not duplicate the executable aggregate gate. |
| #254 Add Phase 3 production enforcement gate | Open draft; conflicting. | Keep or refresh as a child production-enforcement gate only if it still contains unique checks. | Its blocked observations remain useful but do not prove deployed public services, remote TURN, active coturn disconnect, or mixed-route soak. |
| #258 Add Phase 3 current-base release gate summary | Merged. | Use the `main` implementation as the executable aggregate owner. | It generates current-base release-gate status and keeps public Internet gates open. |
| #303 Phase 3 real-media current-base gate | Merged. | Treat as current-base child real-media gate context. | It does not replace real capture-to-Android decoder evidence. |
| #309 / #344 Revocation propagation current-base work | Merged. | Treat as current revocation gate context. | Active end-to-end revocation across deployed services remains open. |
| #310 Public NAT/TURN preflight | Merged. | Treat as current public NAT/TURN readiness preflight context. | It fails closed without production deployment and remote observer evidence. |
| #311 Authority session profile issuance | Merged. | Treat as current Authority issuance/readiness context. | Product-flow automatic issuance still needs current retained evidence. |
| #316 Adaptive media current-base gate | Merged. | Treat as current adaptive-media child gate context. | Real WebRTC network fluctuation evidence remains open. |
| #323 Advanced DataChannel gate | Merged. | Treat as current record-layer/DataChannel gate context. | Audio capture/playback, clipboard/file transfer, and public-network product flows remain unproved. |
| #341 Coturn reconciliation product slice | Merged. | Treat as current coturn reconciliation baseline. | Production exporter, scheduled loop, provider billing reconciliation, and observed active disconnect remain open. |
| #343 Network handoff fresh sessions | Merged. | Treat as current handoff implementation baseline. | Public route handoff acceptance remains open. |
| #347 Real media continuity evidence gate | Merged. | Treat as current real-media gate evidence context. | The gate remains blocked until real capture-to-device decode artifacts exist. |
| #348 Authority TURN readiness gates | Merged. | Treat as current Authority/TURN readiness context. | It is a blocked readiness gate, not production deployment evidence. |

## Recommended cleanup sequence

1. Keep `scripts/phase3/release_gate_summary.py` and
   `vibescreen_evidence.phase3_internet_release_gate` on `main` as the executable
   aggregate source of truth.
2. Do not revive already closed or merged broad PRs as-is: #164, #188, #194,
   and #212. For still-open broad PRs #214 and #254, close, supersede, or
   refresh only after a unique-diff check confirms whether each still owns a
   child gate not covered by current `main`.
3. Do not reopen #190, #200, #216, or #228 as-is; use their merged successors on
   `main` for future work.
4. For each still-open child PR, rerun the child's own verifier on top of current
   `main`, update any blocked evidence, and keep the status scoped to that child
   gate rather than claiming Phase 3 release readiness.
5. Create a new current-source public Internet evidence package only after the
   real route, remote TURN, capture-to-device decoder continuity, handoff,
   revocation, packet capture, latency, and soak prerequisites exist.

## Allowed claims after this audit

- Current `main` contains a development-preview Internet product slice, production
  adapter code, and multiple fail-closed current-base gate/checker paths.
- The local synthetic product E2E can use VideoToolbox-generated HEVC payloads
  over the production WebRTC media DataChannel to a synthetic peer.
- The 2026-08-20 readiness package is a dated local loopback regression record.
- The 2026-08-05 Nubia P0110 result is historical, source-bound, and
  synthetic-media-limited.
- Current blocked records are useful negative/readiness evidence, not release
  evidence.

## Forbidden claims

- Do not call local loopback, forced local coturn, or host-local candidate pairs a
  public Internet pass.
- Do not call synthetic Protocol v1 peers or synthetic pixel-buffer input real
  ScreenCaptureKit-to-Android media evidence.
- Do not treat Android dialog layout instrumentation as pairing, WebRTC, TURN,
  reconnect, or soak acceptance.
- Do not treat blocked evidence packages as release-gate closure.
- Do not relabel Nubia P0110/pacific evidence as another device identity.
- Do not imply revocation is end-to-end until local tombstones, signaling
  invalidation, relay credential denial, and active coturn allocation disconnect
  are proved together across the deployed service shape.

## Verification plan for this PR

For this docs-only audit, minimum verification is:

```bash
git diff --check
rg -n -f /path/to/local-redaction-denylist.txt docs/changes/2026-08-22-phase3-current-base-aggregation/README.md
```

The redaction denylist should include local-only device identifiers, local user
paths, local permission database names, private-key headers, and token-shaped
values. Generic security terminology is acceptable only when it describes classes
of material rather than concrete values.

Before merging or closing any implementation slice named here, rerun that slice's
own verification and then the current aggregate gates that it can affect. Typical
commands are:

```bash
make protocol
make phase3-test
make phase3-local-synthetic-product-e2e
make phase3-authority-container-test
./services/relay/integration/test-turn-rest.sh
cd services/signaling && go test -race -count=1 ./...
cd services/authority && go test -race -count=1 ./...
cd services/relay && go test -race -count=1 ./...
```

Commands that require XCTest, ADB, public TLS endpoints, remote TURN credentials,
PostgreSQL test URLs, packet capture, or external-camera footage must either run
with those prerequisites recorded in evidence or remain explicitly blocked.

## Residual risks and unknowns

- The exact mergeability reported by GitHub can change after each PR merge; rerun
  PR metadata checks before acting on this audit.
- This audit uses PR metadata, changed-file lists, commit graph evidence, and
  current docs. It does not line-review every implementation branch.
- Some PRs have successful local verification recorded in their bodies, but those
  commands were not rerun here. Treat them as claimed by the PR author until
  rerun on the final aggregate branch.
- The repository still needs real current-base Internet release evidence before
  any README or UI language changes from development-preview to release.
