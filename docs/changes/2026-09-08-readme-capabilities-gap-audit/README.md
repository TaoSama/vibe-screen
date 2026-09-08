# README capabilities gap audit

Date: 2026-09-08 local / 2026-09-08 UTC
Base: `origin/main` at `043e1f5d819b1eea336fb92123812a6559503e1d`
Scope: audit only. This record does not close any README gate and does not
change product status.

## Inputs checked

- `README.md` Current capabilities and Delivery Plan sections.
- `docs/changes/2026-08-22-phase0-stable-release-aggregate/phase0-stable-release-manifest.json`.
- Phase 0 aggregate evidence under
  `docs/changes/2026-08-22-phase0-stable-release-aggregate/evidence/2026-09-08-after-681-current-main-gate-blocked/`.
- Current-main Nubia P0110 no-Host UI/UX evidence under
  `docs/changes/2026-08-22-android-ui-ux-audit/evidence/2026-09-08-nubia-p0110-no-host-uiux-current-main-rerun/`.
- Current-main Nubia P0110 no-Host Android audio evidence under
  `docs/changes/2026-08-24-p0110-audio-current-base/evidence/2026-09-08-p0110-audio-android-track-no-host-current-main/`.
- Existing open-gate owner records under `docs/changes`.
- GitHub PR context after PR #685 merged into `origin/main`.

## Audit rules

- Treat `pass`, `blocked`, `insufficient`, `historical`, `offline`,
  `no-Host`, and `readiness` as different evidence strengths.
- Android no-Host instrumentation can improve UI/layout confidence, but it does
  not prove Host-backed bytes, macOS system services, transport negotiation,
  stream decode, input injection, reconnect, latency, or soak behavior.
- Nubia P0110 / pacific / Android 16 evidence can support only general Android
  substitute claims when the specific gate criteria allow it. It cannot be
  relabeled as Xiaomi 13/fuxi, iOS, HarmonyOS, tablet, external-camera, or
  missing-peripheral evidence.
- README should move a requirement from open to closed only after that
  requirement's specific gate reports `pass` with closing-strength current
  evidence.

## Current README gap matrix

| Requirement area | README status today | Evidence that can advance wording | Remaining gap | Audit action |
| --- | --- | --- | --- | --- |
| Phase 0 stable-release aggregate | Open. README correctly says Phase 0 remains in progress and not stable. | Aggregate source/build/module gates pass in the after-681 bundle. | Seven runtime/product gates remain open, blocked, or insufficient: macOS Host hardware compatibility, telemetry/external latency archive, Host RSS no-growth, native pointer HID, controller runtime, clipboard product E2E, and file-transfer product E2E. | Keep Phase 0 open; update stale README aggregate link to the after-681 evidence bundle. |
| macOS Host compatibility | Open. | Current-base Mac16,8 readiness records exercise fail-closed tooling. | No exact-row passing bundle with stable signing/TCC, source-bound Host provenance, full macOS checks, packaged runtime launch, Protocol v1 stream, input smoke, and reconnect evidence. | No README promotion. |
| USB transport and Android stream baseline | Verified for the recorded device baseline. | Historical Xiaomi 13 and Nubia baseline records still support the baseline stream/reconnect claim. | Current-source reruns remain blocked by Host readiness in several owner records; this does not erase the historical baseline but prevents a broader stable-release claim. | No README promotion beyond existing wording. |
| Video and AV1 | HEVC/H.264 current; AV1 later-phase/backlog. | AV1 admission and no-Host probe evidence support fail-closed capability wording. | No Host AV1 encoder advertisement, no real AV1 stream, and no device decode acceptance. | Keep AV1 open/backlog wording. |
| Audio USB/LAN and Internet | Offline and no-Host Android playback readiness only; real Android/macOS audio E2E remains open. | `2026-09-08-p0110-audio-android-track-no-host-current-main` refreshes the Android `AudioTrack` adapter smoke on current main; it can justify Android playback-adapter readiness wording. | No stable-signed Microphone/TCC-ready Host, accepted audio config, Host-origin packets, playback confirmation, USB/LAN secure-record run, or public-Internet playback evidence. | No E2E claim. |
| Display selection, HiDPI, mirroring, and window actions | Several Xiaomi 13 device flows are verified; rotated host-display acceptance remains separate. | Existing display-switch/window-action records support current display capability text. | Real rotated physical and virtual host-display 90/180/270 acceptance remains blocked. | Keep rotation gap separate. |
| Touch gestures | General Android substitute fixed-binary rerun passed on Nubia; Xiaomi fixed-binary rerun remains blocked. | Nubia fixed-binary touch evidence can support general Android substitute wording only. | Xiaomi/fuxi fixed-binary closure, physical-finger/manual UX, and native HID mouse remain separate. | Keep device identity distinction. |
| Keyboard, mouse, stylus, controller, and peripherals | Keyboard/scroll software path verified; native mouse, stylus drawing-app confirmation, controller runtime, and concrete peripheral hardware remain open. | Offline contract coverage and P0110 blocked/preflight records improve readiness and diagnostics. | Missing physical HID mouse pass, physical stylus drawing plus Host injection/output pass, physical controller plus entitled Host pass, and concrete peripheral hardware acceptance. | No runtime promotion. |
| Clipboard product E2E | Open for Android ClipboardManager <-> macOS NSPasteboard. | The 2026-09-08 no-Host UI/UX rerun adds 2 clipboard confirmation layout tests, and existing current-main no-Host records cover local Android ClipboardManager smoke and focused JVM checks. | No bidirectional product transfer with real Android ClipboardManager and macOS NSPasteboard endpoints, real Host session, protocol packet evidence, verified epoch/origin/change ID/SHA-256, and retained distinct artifacts. | Do not close. Mention #683 only as no-Host UI/readiness evidence if README is refreshed later. |
| File-transfer product E2E | Open for Android/macOS product bytes landing. | The 2026-09-08 no-Host UI/UX rerun adds 3 file-transfer offer-dialog layout tests and focused JVM layout coverage. | No Host-backed offer/request/content exchange, receiver approval, remote write, SHA-256 equality, progress, epoch/transfer ID evidence, or cancel cleanup product bundle. | Do not close. |
| Recovery/reconnect timing | Baseline reconnect verified historically; Phase 1 three-second current-base gate remains blocked. | Existing historical USB recovery records support baseline wording. | No current-base disruption scenario with observed Host listener and bounded recovery timing. | Keep timing gate open. |
| Trusted LAN | Experimental; real-device LAN stream/reconnect evidence remains open. | Secure-record/offline tests and LAN preflight records support readiness wording. | No real LAN socket admission, secure-record negotiation, decoder output, reconnect, or LAN latency evidence. | No LAN runtime promotion. |
| Protocol v1 | Main-session display/input/video-preference flows verified; clipboard/file-transfer product E2E still open. | Existing Xiaomi 13 Protocol v1 evidence supports current display/input/video preference wording; cross-platform offline gates support protocol-contract wording. | Clipboard/file-transfer real product gates, Host RSS, native HID pointer, and some hardware gates remain separate. | Keep split wording. |
| iOS trusted LAN | Readiness only. | Loopback and offline evidence support core readiness wording. | No signed iPhone/iPad device acceptance, real-network LAN, local-network permission, hardware VideoToolbox, input, audio/HDR, or reconnect evidence. | No device claim. |
| HarmonyOS/Internet | In development. | Portable Harmony and Phase 3 offline/source evidence support readiness wording. | No DevEco/HAP/MatePad hardware, HUKS-backed production transport, Host interop, public Internet E2E, remote TURN, real capture-to-MediaCodec, handoff, revocation, latency, or soak evidence. | Keep development-preview wording. |
| Android UI/UX no-Host coverage | README references the 2026-09-08 current-main no-Host UI/UX package. | PR #683 adds a rerun package with direct per-class 86/86 instrumentation and 188/188 focused JVM checks, while preserving no `tcp:54321` reverse and no Host listener boundary. | The Gradle/UTP wrapper run failed closed after two tests, and the package has no screenshots and no Host-backed product behavior. | Candidate for a future README evidence-link refresh; not a gate closure. |

## Requirement-by-requirement conclusion

README is broadly conservative: the claims that are still marked open are still
open after reviewing current evidence. The main actionable stale item found in
README is the Phase 0 aggregate pointer: README referenced the after-676 bundle
even though the repository already contains the after-681 aggregate refresh.

The newest current-main no-Host UI/UX and Android audio reruns can advance
future README wording only inside Android UI/readiness and playback-adapter
boundaries. They should not be cited as evidence for Host-backed clipboard,
file transfer, LAN, Internet, video decode, input injection, latency, soak, Host
signing/TCC, hardware compatibility, iOS, HarmonyOS, tablet, native pointer,
stylus, controller, or Xiaomi/fuxi gates.

## Verification

- `make phase0-stable-release-gate` passed and preserved the blocked aggregate
  status in `.build/evidence/phase0-stable-release/phase0-stable-release-summary.json`.
- `make phase0-stable-release-gate PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT=043e1f5d819b1eea336fb92123812a6559503e1d` passed, proving the checked-in manifest source guard accepts the audited `043e1f5d819b1eea336fb92123812a6559503e1d` base.
- `make phase0-module-ownership-gate` passed.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.phase3.test_repository_privacy.RepositoryPrivacyTests.test_current_tree_has_no_raw_android_serial_contexts -v` passed.
- A local Markdown-link check over `README.md` and this audit file verified all
  repo-relative Markdown link targets exist.
- `git diff --check` passed.

## Boundaries

No Vibe Screen, MacHost, or Telemachus GUI was launched. No `swift run`, Screen
Recording, Accessibility, Microphone, Keychain, TCC, System Settings, signing
configuration, or `adb reverse tcp:54321 tcp:54321` operation was used.
