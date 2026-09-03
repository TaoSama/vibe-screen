# Open gates coverage audit

Date: 2026-08-22 local / 2026-08-21 UTC
Last refreshed: 2026-09-04
Base: `origin/main` at `93d4450a5e583a54fe53616993cc9865c370c076`
Scope: audit only. This document does not close any README gate and does not
change product status.

## Inputs checked

- `git fetch origin main --prune` completed before this refresh.
- `git merge-base --is-ancestor 93d4450a5e583a54fe53616993cc9865c370c076 HEAD`
  confirmed the PR #536 merge commit is included in the audited base.
- `gh pr view 535 --json number,state,mergedAt,mergeCommit,title,url` and
  `gh pr view 536 --json number,state,mergedAt,mergeCommit,title,url`
  confirmed both PRs are merged.
- `gh pr list --repo TaoSama/vibe-screen --state open --limit 200 --json number,title,headRefName,headRefOid,baseRefName,updatedAt,isDraft,mergeStateStatus,url`
  returned no open PRs before this refresh PR was opened, so there are no
  active external open PR owners in this refresh.
- Evidence and command coverage were scanned under `README.md`,
  `docs/changes`, `docs/testing.md`, `Makefile`, `scripts/`, and `tools/`.
- The Phase 0 stable-release aggregate manifest now records the same open-PR
  snapshot. Its checker fails closed if any active `owner_prs` entry is absent
  from that snapshot, so merged or closed PRs cannot remain current owners.

## Audit rules

- Treat `pass`, `blocked`, `insufficient`, `historical`, `offline`,
  `synthetic`, and `readiness` as different evidence strengths. Readiness and
  tooling records are preparation only; they do not close runtime gates.
- Nubia P0110 evidence must stay labeled `Nubia P0110 / pacific / Android 16 /
  SDK 36 / [redacted-adb-serial]`. It can close only general Android gates when
  the recorded artifacts satisfy the same pass criteria. It cannot be relabeled
  as Xiaomi/fuxi evidence, and it cannot close iOS, HarmonyOS, physical tablet,
  external-camera latency, or hardware-specific peripheral gates unless those
  exact hardware conditions are present in the run.
- Active owner PR freshness is sourced from the GitHub open-PR snapshot. In this
  refresh there are no open PRs; every active gate `owner_prs` list remains
  empty. Historical merged PR numbers may appear in prose only as baseline
  context.

## 2026-09-04 refresh

- The current base is the PR #536 merge commit `93d4450a5e583a54fe53616993cc9865c370c076`.
- PR #535 and PR #536 are merged, and there were no open PRs when this refresh
  branch captured the snapshot. Previous owner mappings from #157 through #536
  are now merged, closed, or superseded historical context rather than active
  external gate owners.
- The Phase 0 module-ownership sub-gate now passes on current main. This closes
  only the source/offline module-boundary requirement. It does not close any
  missing runtime evidence gate.
- The Phase 0 stable-release aggregate remains blocked by required gates that
  lack closing-strength current evidence: macOS Host hardware compatibility,
  latency archive, Host RSS, native pointer HID, controller runtime, clipboard
  product E2E, and file-transfer product E2E.

## Coverage matrix

| Gate | README source | Current evidence | Current active open PR owner | P0110 usable? | Gap | Next step |
| --- | --- | --- | --- | --- | --- | --- |
| Phase 0 stable-release aggregate | `README.md:3-16`, `README.md:270-345` | Phase 0 Android/macOS subset has device acceptance, but Phase 0 remains in progress. The module-ownership sub-gate passes on current main. | none | Yes for general Android acceptance only. | Required runtime/evidence gates below are still open, blocked, or insufficient. | Keep Phase 0 open until every required sub-gate has the closing evidence strength required by `phase0-stable-release-manifest.json`. |
| macOS Host hardware compatibility matrix | `README.md:32`, `README.md:270-287` | Published current-base Mac16,8 summaries are blocked readiness records. | none | No. | No exact-row pass with stable signing/TCC, source-bound Host provenance, full macOS checks, packaged runtime launch, Protocol v1 stream, input smoke, and reconnect evidence. | Collect exact-row passing evidence with the macOS compatibility runbook; do not generalize from local readiness. |
| Telemetry and external latency archive | `README.md:410-424` | Latest current-base latency preflights are blocked/insufficient readiness. | none | P0110 can be the Android screen/input target. | No raw external-camera sample package or synchronized-clock physical-input proof exists for any required profile. | Collect raw camera/samples/manifest or synchronized-clock physical-input evidence, then run the latency evidence gates. |
| Host RSS two-hour no-growth | `README.md:13-15`, `README.md:270-311` | The retained 2026-08-09 Xiaomi 13 two-hour stream was stable, but Host RSS grew about 18.3 MB; current-base readiness records remain blocked. | none | Possible as an Android substitute for a future soak, but this is primarily a Host RSS gate. | No current-source `host_rss_gate` pass exists. | Run a complete two-hour current-source soak only after stable signing/TCC/listener prerequisites are satisfied; close only if the formal gate returns `pass`. |
| Native pointer HID mouse move/click | `README.md:14-15`, `README.md:38`; pass criteria in `docs/testing.md:90-118` | Latest current-base summaries remain blocked. | none | Yes, if a real mouse/touchpad/trackball is attached to the P0110 and the exact evidence criteria are met. | No pass bundle with Android forwarding logs, Host pointer-injection logs, and visible Mac move/click result from one run. | Create a current-base owner when hardware is available, then rerun `scripts/native_pointer_hid_acceptance.py` under the Android device lock. |
| Controller runtime acceptance | `README.md:38`, `README.md:270-287`; pass criteria in `docs/testing.md:130-137` | Offline controller protocol/model coverage exists, but latest runtime readiness remains blocked. | none | Yes for Android controller acceptance only with a named controller attached and signed Host entitlement available. | No physical controller, identity-signed Host with approved virtual HID entitlement, Mac-side response, and neutral disconnect release in one pass bundle. | Collect `controller_runtime_readiness.py` plus `vibescreen_evidence.controller_runtime` pass evidence when prerequisites exist. |
| Android/macOS clipboard product E2E | `README.md:39` | Protocol v1 clipboard implementation and offline/JVM checks pass; local P0110 smoke exists. | none | Yes for Android USB/LAN clipboard evidence with exact retained artifacts. | No retained bidirectional Android `ClipboardManager` <-> macOS `NSPasteboard` product transfer evidence exists. Host readiness and real transport prerequisites remain blocked. | Keep the clipboard E2E gate blocked until exact bidirectional product-transfer artifacts pass. |
| Android/macOS file-transfer product E2E | `README.md:40`, `README.md:1045-1058` | Protocol v1 file transfer source/offline tests pass. | none | P0110 could close Android USB/LAN file-transfer acceptance with retained logs. | No retained bidirectional Android/macOS product transfer evidence proves approval, remote write, SHA-256 equality, session epoch, and cancel cleanup. | Keep `make file-transfer-bulk-current-base-gate` fail-closed until child gates pass with real product evidence. |
| Trusted LAN stream and reconnect | `README.md:42` | Secure-record implementation and offline tests exist; latest retained LAN preflights were blocked by device Wi-Fi/route and Host prerequisites. | none | Yes for general Android LAN once Wi-Fi and Host prerequisites are satisfied. | No real trusted-LAN socket admission, secure-record negotiation, decoder output, reconnect, or LAN latency evidence. | Run the LAN runbook only after Wi-Fi route and stable Host readiness are satisfied. |
| Android USB/LAN audio playback | `README.md:35`, `README.md:507-509` | PCM microphone path is offline-tested; latest P0110 current-base refresh is fail-closed. | none | Yes for general Android USB/LAN audio acceptance only when exact P0110 identity and playback artifacts satisfy the gate. | No stable-signed Microphone/TCC-ready Host, accepted audio config, channel packet flow, `AudioTrack` writes, playback confirmation, or LAN secure-record playback run. | Keep `make android-audio-playback-gate` fail-closed until retained USB and LAN playback artifacts exist. |
| Rotated host-display acceptance | `README.md:412-416` | Client-local rotation with host rotation zero is verified; current-base host-display rotation readiness is blocked. | none | Yes for general Android display/input if the Mac display is really rotated. | No fresh real-device host-rotation pass across physical and virtual displays at 90/180/270 with structured inverse-touch mapping. | Run `make host-display-rotation-current-base-gate EVIDENCE_DIR=<run> EVIDENCE_SERIAL=<redacted-adb-serial>` after Host prerequisites pass. |
| Login-item approval and headless reboot | `README.md:584-604` | Startup policy coverage is offline/readiness only. | none | P0110 can be the Android client in a recovery run, but the gate is mainly macOS integration and headless hardware state. | No login approval/logout-login relaunch evidence and no headless reboot recovery evidence. | Collect a macOS login/headless bundle with preserved Host logs, PID/session state, and Android reconnect markers after stable Host readiness. |
| Phase 2 physical tablet productization | `README.md:584-638` | Phase 2 readiness exists, but P0110 is a phone substitute, not a physical 8-9 inch tablet. | none | No for tablet-specific claims. | No tablet hardware evidence, stand charging, controlled thermal load, power stability, live recovery, login/headless, stylus/keyboard workflow, or 8h sample series. | Use the Phase 2 runbook and `phase2-tablet-gate` on a real target tablet. |
| AV1 real-stream Host/device acceptance | `README.md:34`, `README.md:152-156` | Protocol reserves AV1 and admission fails closed; Host still does not advertise real AV1. | none | Only if a real AV1 Host stream is negotiated and decoded on matching hardware. | No Host AV1 encoder/advertisement, real stream, or device decode evidence. | Keep AV1 as protocol-enumerated/fail-closed until implementation and real-stream acceptance exist. |
| Phase 3 public Internet release | `README.md:720-895` | Current main includes substantial Internet source/offline work, but public release gates remain open. | none | P0110 can contribute Android Internet evidence, but cannot replace public NAT/TURN, relay, real capture/decode, handoff, latency, revocation, and soak evidence. | No public Internet E2E, real remote TURN, real media continuity, network fluctuation/handoff, soak, production coturn enforcement, multi-instance throughput, rate limiting, load-balancer, or multi-region consistency proof. | Treat local E2E as readiness only; collect public/remote evidence with the Phase 3 TEST template. |
| iOS trusted LAN and advanced device gates | `README.md:1004-1130` | iOS Core/offline/simulator and loopback readiness exist; no iPhone/iPad device acceptance is recorded. | none | No. | Signing, device install, Local Network permission, hardware VideoToolbox behavior, host-side advanced adapters, audio, HDR, input, reconnect, and advanced product flows remain unproved on device. | Use the iOS current-base gates; do not close hardware rows with Simulator, unsigned archive, loopback, or Android evidence. |
| HarmonyOS DevEco/HAP/MatePad gates | `README.md:936-1002` | Portable source checks and fail-closed readiness exist. | none | No. | No DevEco SDK, HAP, signing, install, hardware decode, HUKS, authenticated transport, Host interop, or MatePad Mini run is claimed. | Run Harmony readiness/device/current-base/MatePad gates with a real MatePad package. |
| Phase 0 module ownership extraction | `README.md:324-345` | Android TCP transport, `StreamClient`, protocol/session, file-transfer, WakeHost, decoder, renderer, and UI/product-session source boundaries are closed with focused offline evidence. | none | Not device-specific. | No source-boundary gap remains for this sub-gate; related runtime evidence remains tracked separately above. | Keep `make phase0-module-ownership-gate` passing and do not use it as evidence for hardware/runtime gates. |

## Retired PR-owner clusters

The old audit tracked overlapping open PR clusters for Host RSS/signing, Phase 2,
Phase 3, HarmonyOS, clipboard/file transfer, WakeHost, iOS, latency, and module
ownership. As of this refresh, the open PR snapshot is empty. Those clusters
are retired from current ownership tracking; any future owner must appear in the
fresh GitHub open-PR snapshot and in the manifest `owner_prs` list.

## Practical next queue

1. Keep the aggregate manifest bound to the current `origin/main` commit and a
   fresh open-PR snapshot whenever Phase 0 acceptance criteria, relevant evidence
   tooling, or active owner PRs change.
2. Stabilize recurring prerequisites: full Xcode/XCTest, `Vibe Screen Dev`
   signing identity, Screen Recording/Accessibility grants, Host source
   provenance, P0110 Wi-Fi route, and the Android device lock workflow.
3. Keep P0110 evidence scoped to general Android USB/LAN/UI/protocol reruns; do
   not use it for iOS, HarmonyOS, real tablet, external-camera, or
   missing-peripheral gates.
4. For each future gate attempt, write artifacts first, then update README only
   after the evaluator for that specific gate returns `pass` against current
   source.
