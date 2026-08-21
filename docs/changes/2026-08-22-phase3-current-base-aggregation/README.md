# Phase 3 current-base aggregation plan

Status: docs-only aggregation plan; not Phase 3 Internet release evidence

Owner: Vibe Screen core team

Current base audited: `4dc84505e6e0a07fa1052df12bca03824f161bf6` (`origin/main`, 2026-08-22)

## Purpose

This document establishes the current-base coordination owner for Phase 3 Secure
Internet release-gate convergence. The immediate goal is to stop accumulating
overlapping readiness and blocked-evidence pull requests, identify the smallest
useful merge sequence, and keep public-release language aligned with the real
evidence. The executable aggregate gate owner is PR #258; this document is the
human merge and closure plan around that generated summary.

This is not a readiness package and does not close any Internet release gate.
Local loopback, forced local coturn, synthetic Protocol v1 peers, synthetic
pixel-buffer input, Android dialog instrumentation, and offline policy tests may
prove only the slice they execute. They do not prove public Internet traversal,
remote TURN deployment, real ScreenCaptureKit capture, Android MediaCodec decode,
network handoff, cross-service revocation propagation, packet-capture
confidentiality, external-camera latency, or two-hour mixed-route soak.

## Current-base evidence ledger

| Evidence | Source binding | Current-base status | Boundary |
| --- | --- | --- | --- |
| Current `origin/main` | `4dc84505e6e0a07fa1052df12bca03824f161bf6` | Source contains the local Phase 3 product slice, production WebRTC adapters, app-record protection, local authority/signaling/relay scaffolding, merged signaling multi-node waiter recovery from #223, the open-gates coverage audit from #241, and VideoToolbox-generated HEVC payloads in the local product E2E path. | No current Android Internet device/media acceptance is recorded. The local product E2E still uses a synthetic Protocol v1 peer and synthetic pixel-buffer input, with no ScreenCaptureKit/CGDisplayStream capture and no Android MediaCodec/UI/public route. |
| Executable aggregate gate summary | PR #258, `codex/phase3-current-base-gates` | Current-base aggregate owner for generated Phase 3 release-gate state. Its summary is expected to remain `OPEN` until real public-path evidence exists. | It is a fail-closed summary/checker, not release evidence. Child gate PRs should feed it rather than duplicate aggregate ownership. |
| Local readiness record | `docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-20-local-phase3-readiness/README.md`, commit `18a6ea70d0fbf6bc187f5a7242424ad3e88cf5ee` | Useful regression baseline for protocol, security/service/static tests, local Authority container, relay coturn scripts, and direct plus forced-local-coturn synthetic product E2E. | Local loopback only; no Android UI, real screen capture, public Internet path, real remote TURN, packet capture, handoff, revocation propagation, latency, or soak. |
| Current-main real-media attempt | `docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-18-nubia-p0110-current-main-real-media-blocked/README.md`, commit `5f7a4c394ac6f33b75636b17e12d15b425a0688b` | Valid blocked evidence for a current-main attempt. | Host lacked Screen Recording permission and the session did not enter capture, encoding, WebRTC transport, or Android decode. |
| Historical Nubia Internet interop | `docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-05-nubia-p0110-internet/README.md`, commit `597518f948075e396352bc353afcec01a30303f3` | Useful historical regression context for Nubia P0110/pacific Android 16, local Android UI, M144/M150 adapter interop, application AEAD, and synthetic media over direct plus forced local coturn. | Bound only to its dated source/device/media boundary. Not current-base evidence and not public Internet, real ScreenCaptureKit, visible Mac input, handoff, revocation, latency, or soak proof. |
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
- Xiaomi 13 (model 2211133C) Internet evidence unless the requirement is
  explicitly changed. Nubia P0110/pacific evidence may be recorded separately but
  must not be relabeled as Xiaomi evidence.

## Pull request disposition matrix

| PR | Head | Current status | Disposition | Reason |
| --- | --- | --- | --- | --- |
| #164 Add Phase 3 release gate manifest verifier | `d54d8da8`, `codex/phase3-release-gate-matrix` | Draft, conflicting, based on `22da2681`; overlaps #171/#188/#214 in `Makefile`, README, `release_gate_manifest.py`, and tests. | Supersede by #171 or the aggregate gate-tooling owner; close after replacement lands. | The gap matrix idea is useful, but #171 continues the same verifier lineage and later PRs extend the same gate surface. Taking #164 directly would preserve an older split and conflict with newer gate definitions. |
| #171 Harden network recovery gate evidence | `461fc9ab`, `codex/phase3-network-recovery-gates` | Non-draft, `mergeable=MERGEABLE`, `mergeStateStatus=BEHIND`; extends release-gate manifest, network-profile simulation, Android acceptance metadata, and blocked evidence. | Rebase into the aggregate gate-tooling owner as the successor to #164. | Useful fail-closed evidence tooling. It should remain a gate/preflight slice only, and its blocked package must not be used as handoff evidence. |
| #172 Add Phase 3 coturn reconciliation contract | `e5973596`, `codex/phase3-coturn-reconciliation` | Non-draft, `mergeable=MERGEABLE`, `mergeStateStatus=BLOCKED`; three commits. | Supersede by #228 if #228 passes review; otherwise merge/rebase #172 as the minimal coturn contract. | #228 contains #172's commit lineage plus production reconciliation work. Keeping both open creates duplicate ownership of `coturn_reconcile.py`, authority relay ledger fields, and production docs. |
| #173 Add Phase 3 real media continuity preflight | `5ec09676`, `codex/phase3-real-media-continuity` | Non-draft, `mergeable=MERGEABLE`, `mergeStateStatus=BEHIND`; standalone verifier/docs/evidence package. | Rebase and merge as an independent fail-closed preflight slice. | It is mostly orthogonal to service runtime work and correctly records a blocked real-media continuity gate. Keep its wording strict: retained logs and preflight output are not real media evidence. |
| #188 Add Phase 3 release gate contracts | `98d08844`, `codex/phase3-release-gates` | Draft, conflicting, based on `22da2681`; large overlap with #164/#172/#190/#194/#214/#228. | Supersede/close after extracting any unique assertions not already covered by #171, #190, #194, #214, and #228. | It bundles release-gate, coturn exporter, revocation, and soak surfaces into one stale branch. That makes it a poor aggregate base and risks reintroducing older docs. |
| #190 Add Phase 3 revocation propagation verifier | `44c21168`, `codex/phase3-revocation-propagation` | Draft, mergeable, based on `22da2681`; focused verifier plus blocked evidence. | Rebase and merge after #228/#200 ordering is settled, or fold into the gate-tooling owner. | The verifier is useful, but its service-test assertions touch the same authority/signaling/relay boundary as #200/#228. It must continue to report active coturn teardown as blocked. |
| #194 Add fail-closed Phase 3 public Internet evidence gates | `fb39798b`, `codex/phase3-public-internet-evidence` | Draft, conflicting, based on `22da2681`; overlaps #214 and #188 on public Internet/soak evidence tooling. | Supersede into #214 plus the aggregate gate-tooling owner; close as a standalone stale branch. | The public Internet/remote TURN preflight contract is valuable, but the branch duplicates the broader soak gate and is stale. Preserve #194's remote-TURN and public-route verifier requirements so they are not hidden inside the soak gate. |
| #200 Phase 3 authority session profile issuance | `b58903ad`, `codex/phase3-authority-issuance` | Draft, conflicting, based on `22da2681`; service/runtime changes across authority, signaling, Mac lease issuer, docs. | Rebase as a dedicated runtime slice; do not merge until conflicts with #223/#228 are resolved. | This is a real implementation prerequisite for automatic profile issuance, not evidence of public release readiness. It touches the same service boundaries as the newer signaling/coturn work and needs explicit integration ordering. |
| #212 Add Phase 3 Internet latency gate verifier | `03fe04d0`, `codex/phase3-internet-latency-gate` | Draft, conflicting, based on `22da2681`; focused tools/schema/runbook evidence gate. | Rebase and merge as an independent fail-closed latency gate after checking overlap with #214. | The Internet latency profile is useful and should stay separate from soak. Its placeholder/blocking samples must remain `insufficient` without public route and external-camera provenance. |
| #214 Add Phase 3 public Internet soak gate | `24b22036`, `codex/phase3-internet-soak` | Draft, conflicting, based on `22da2681`; soak manifest/gate plus blocked package. | Rebase and merge as the aggregate public-Internet soak gate; absorb non-duplicative #194 public-route checks. | It is the best owner for the composite public Internet soak gate, but it must stay fail-closed and should not duplicate #164's lower-level matrix unless that matrix is retired. If the soak gate needs a revocation stage, reference #190's verifier semantics rather than copying a second revocation model. |
| #215 Add production Postgres signaling store slice | `ed9587fa`, `codex/signaling-multi-node-store` | Draft, mergeable, base now stale after merged #223/#241; initial single-commit slice. | Supersede by merged #223 after unique #215 PRD/TEST/static production-gate assertions are diffed and either absorbed or deliberately dropped. | #223 is now on `origin/main` and is the newer signaling owner with waiter-lease correctness fixes, but it does not touch every #215 doc/test file. Closing #215 still requires an explicit unique-diff check. |
| #216 Harden Phase 3 QR pairing verification | `a65506e3`, `codex/phase3-qr-pairing-flow` | Draft, mergeable, based on `22da2681`; focused Android/Mac pairing parser and lease tests. | Rebase and merge as an independent pairing-safety slice after #200, or keep separate if #200 stays blocked. | It is lower-risk than the authority profile issuer and mostly orthogonal, but both touch Mac lease issuer docs/tests. It must not claim production TLS, public Internet, or real Android camera scan acceptance. |
| #223 Add signaling multi-node waiter lease recovery | `28cb1865`, `codex/phase3-signaling-multinode-failover` | Merged into `origin/main` before this audit. | Treat as the current signaling multi-node owner; use it as the base for #200/#228 conflict resolution. | It is now current-base service readiness context. It still does not prove public ingress, throughput, multi-region consistency, or release readiness. |
| #224 Add bounded network handoff recovery | `78797730`, `codex/phase3-network-handoff-recovery` | Open, non-draft, currently mergeable after refresh; runtime recovery changes in Android and Mac transports/product sessions. | Rebase/verify and merge after #171 gate-tooling decisions. | This is the runtime recovery slice, while #171 is evidence tooling. It still only proves local/fail-closed behavior; real public handoff remains open. |
| #228 Add coturn production reconciliation slice | `8978409b`, `codex/phase3-coturn-production-20260821` | Draft, conflicting after current-main updates; includes #172 lineage and production reconciler/registry work. | Make this the coturn/relay reconciliation owner; rebase to current main, finish review, then merge. Close #172 if #228 lands. | It consolidates the newer coturn production path. It still lacks public deployment, durable scheduler/WAL, provider billing reconciliation, and observed active TURN disconnect evidence. |
| #241 Add open gates coverage audit | `02949e9d`, `codex/open-gates-coverage-audit` | Merged into `origin/main` before this audit. | Treat as docs-only audit context, not an executable aggregate owner. | It inventories missing gate coverage and supports this convergence plan, but it does not generate pass/fail release state. |
| #248 Add current-base aggregation plan | current branch, `codex/phase3-current-base-aggregation` | Draft, docs-only coordination PR, rebased on current `origin/main`. | Keep as the human conflict/merge-order owner if a separate coordination note is desired; otherwise close after #258 and this plan are copied into tracking. | It must not duplicate #258's executable aggregate status. |
| #254 Add Phase 3 production enforcement gate | `56a6e47f`, `codex/phase3-production-enforcement` | Draft, mergeable; focused production-evidence checker and blocked package. | Keep as a child production-enforcement gate; merge only as fail-closed evidence tooling. | Its blocked observations are useful, but do not prove deployed public services, remote TURN, active coturn disconnect, or mixed-route soak. |
| #258 Add Phase 3 current-base release gate summary | `d3439b4b`, `codex/phase3-current-base-gates` | Open, non-draft, mergeable, based on current `origin/main`. | Use as the unique executable aggregate owner. | It generates a current-base release-gate summary and intentionally keeps every public Internet release gate open until real public-path evidence exists. |

## Recommended merge sequence

1. Merge #258 first as the unique executable current-base aggregate owner, unless
   a newer aggregate branch intentionally replaces it. Keep #248 docs-only.
2. Treat #223 and #241 as already merged current-base context. Diff #215 against
   current `main` and close it only after any unique PRD/TEST/static
   production-gate assertions are absorbed or deliberately dropped.
3. Rebase #200 on top of merged #223 and resolve authority/signaling profile issuance
   conflicts; keep it draft until the integration tests pass in the PostgreSQL
   environment.
4. Rebase #228 on top of the #200/#223 service base if #200 remains in scope, or
   current `main` if #200 is deferred. Let #228 own coturn/relay reconciliation,
   then close #172.
5. Merge independent fail-closed gate tooling in this order after rebasing: #173
   real-media continuity preflight, #212 latency gate, #214 public Internet soak
   gate. Fold #194's remote-TURN/public-route verifier requirements into #214
   or the aggregate gate-tooling owner before closing #194.
6. Rebase #171 as the network recovery evidence-tooling slice and #224 as the
   runtime handoff-recovery slice. Merge #171 first if #224 depends on its
   evidence terminology; otherwise keep them separate but avoid duplicate blocked
   readiness packages.
7. Rebase #216 after #200 if both modify lease issuance; otherwise merge it as a
   standalone parser/lease hardening slice.
8. Close #164 and #188 once the aggregate gate-tooling owner has absorbed their
   non-duplicative verifier assertions.

## Allowed claims after this aggregation

- Current main contains a development-preview Internet product slice and local
  production-adapter checks.
- The current local product E2E can use VideoToolbox-generated HEVC payloads over
  the production WebRTC media DataChannel to a synthetic peer.
- The 2026-08-20 readiness package is a dated local loopback regression record.
- The 2026-08-05 Nubia P0110 result is historical, source-bound, and
  synthetic-media-limited.
- The 2026-08-18 and 2026-08-21 blocked packages are useful negative evidence, not
  release evidence.

## Forbidden claims

- Do not call local loopback, forced local coturn, or host-local candidate pairs a
  public Internet pass.
- Do not call synthetic Protocol v1 peers or synthetic pixel-buffer input real
  ScreenCaptureKit-to-Android media evidence.
- Do not treat Android dialog layout instrumentation as pairing, WebRTC, TURN,
  reconnect, or soak acceptance.
- Do not treat blocked evidence packages as release-gate closure.
- Do not relabel Nubia P0110/pacific evidence as Xiaomi 13/fuxi evidence.
- Do not imply revocation is end-to-end until local tombstones, signaling
  invalidation, relay credential denial, and active coturn allocation disconnect
  are proved together across the deployed service shape.

## Verification plan for the aggregation owner

For this docs-only plan, minimum verification is:

```bash
git diff --check
```

Before merging any implementation slice, rerun the slice's own verification and
then the current aggregate gates that it can affect. Typical commands are:

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
  PR metadata checks before acting on this plan.
- The plan uses PR bodies, changed-file lists, local branch commit graphs, and
  current docs. It does not line-review every implementation branch.
- Some PRs have successful local verification recorded in their bodies, but those
  commands were not rerun here. Treat them as claimed by the PR author until
  rerun on the final aggregate branch.
- The repository still needs a real current-base Internet release evidence run
  before any README or UI language changes from development-preview to release.
