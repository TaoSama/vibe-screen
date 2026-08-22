# Phase 1 macOS host verification record

## Original local environment

- host: macOS 26.4.1 (`25E253`), arm64;
- Swift: 6.3.1;
- selected developer directory: `/Library/Developer/CommandLineTools`;
- full Xcode/XCTest: unavailable (`xcodebuild` rejects the selected developer
  directory);
- Android soak lease was present during implementation and later released
  without starting its two-hour clock because the locked Mac exposed zero
  ScreenCaptureKit displays. Android Phase 1 and Internet work retain device
  priority, so this task ran no ADB, media-port, normal Host, or device action.

## Completed evidence

The following output is abridged; persistent display UUID values are omitted
from the document but were present in the local command output.

```text
make baseline-macos-self-test
Build complete!
Host display evidence: id=1, logical=1512x982, physical=3024x1964
Host display evidence: id=2, logical=1920x1080, physical=3840x2160
Private virtual display API shape check: available
(class/selector presence is not creation/capture evidence)
Host self-test: PASS (display identity/catalog, input/window geometry,
startup/recovery policy, callback generation, fallback replacement)
Transport self-test: PASS (config=true, keyframe=true, pong=true, touch=true,
malformedTouchRejected=true, portConflict=true, codecNegotiations=1, error=none)
Reliability self-test: PASS (queue, epoch, heartbeat/backoff, codec, JSONL)

make baseline-macos-app
.build/release-artifacts/Telemachus-macos-0.12.0-arm64.zip
.build/release-artifacts/Telemachus-macos-0.12.0-arm64.sha256

shasum -a 256 -c Telemachus-macos-0.12.0-arm64.sha256
Telemachus-macos-0.12.0-arm64.zip: OK
SHA-256: dd0094d5d2b9c8da0fc8f35ef6701b755e822eb0a564b33bc23b183a2d2430dd

unzip -t Telemachus-macos-0.12.0-arm64.zip
No errors detected in compressed data

codesign --verify --deep --strict <extracted>/Telemachus.app
<extracted>/Telemachus.app: valid on disk
Signature=adhoc

spctl -a -vv <extracted>/Telemachus.app
<extracted>/Telemachus.app: rejected
(expected for the explicitly non-notarized ad-hoc development artifact)
```

The self-test covers stable display UUID enumeration/fallback, density-aware
virtual identity, negative-origin input mapping and malformed-coordinate
rejection, UUID-aware online/offline window recovery geometry, startup
eligibility, and the bounded recovery schedule. The loopback transport
self-test also proves malformed touch cancellation without posting a real
system event. It now also rejects a callback queued before an authoritative
same-server client-generation takeover and checks stopped-first main-display
replacement policy. XCTest sources add focused policy/lifecycle cases under
`Phase1HostCapabilityTests.swift` and `StreamingServerLifecycleTests.swift`.
The added cases cover concurrent double-start admission, stop invalidation of a
suspended start, current/stale fallback stop generations, blank/idle fallback
frames, missing private classes/selectors, and exact unchanged-bounds window
recovery. At the original local run they remained source-level regression
coverage because XCTest could not run; the 2026-08-06 main CI result below
subsequently executed them as part of the full suite.
The XCTest sources also include queued-old-callback rejection, asynchronous
codec startup de-duplication, stopped-first current-main replacement policy,
and single-consumption automatic-launch intent cases. The queued-callback cases
cover both host-session replacement and same-server client takeover before the
new client's MainActor callback is observed.

In the original local Command Line Tools environment,
`make baseline-macos-test` compiled the application target but failed before
test execution with `error: no such module 'XCTest'`; full Xcode was not
installed/selected. This historical environment result is distinct from the
2026-08-06 main CI result.

## Main Xcode verification snapshot (2026-08-06)

On 2026-08-06, main commit `4c2e908fe31af4c187684991301e163371444eab`
passed GitHub Actions Phase 0
[run 31084214883](https://github.com/TaoSama/vibe-screen/actions/runs/31084214883).
The `macos-15` job executed the full MacHost XCTest suite: 202/202 tests passed
with zero failures, including the Phase 1 policy and lifecycle cases described
above. The same SHA also passed iOS engineering
[run 31084214830](https://github.com/TaoSama/vibe-screen/actions/runs/31084214830)
and HarmonyOS portable
[run 31084214856](https://github.com/TaoSama/vibe-screen/actions/runs/31084214856);
those workflows do not prove platform real-device behavior.

The 202-test pass proves the covered test cases on the CI runner. It does
not prove private display creation/capture, actual mirroring, Accessibility or
CGEvent effects, login-item approval, hot-plug, headless reboot, device input,
latency, or sustained memory behavior.

## Login/headless readiness snapshot (2026-08-21)

The repository now has a read-only local readiness command for the login
startup, headless Mac mini, and unattended recovery integration gates:

    make baseline-macos-startup-readiness

It records installed Host signing, TCC Screen Recording/Accessibility rows,
startup defaults, Launch at Login state, current display inventory, and recent
Host startup/recovery markers into text and JSON reports. It does not register
login items, reboot, launch or stop the Host, reset TCC, grant permissions,
modify Keychain, or contact an Android device.

On 2026-08-21 the command produced a blocked readiness snapshot under
evidence/2026-08-21-login-headless-readiness-blocked/. The installed Host was
stable-signed, and onboarding and startup defaults were ready. Readiness
remained blocked because the read-only TCC database check could not verify
Screen Recording or Accessibility from this shell, the read-only Login Items
dump timed out, and no active CoreGraphics display was visible to the diagnostic
subprocess. Display inventory was present through
`system_profiler`, but that inventory remains diagnostic only and does not
prove ScreenCaptureKit capture after a headless reboot. The captured Host log
segment showed auto-start was deferred until onboarding and Screen Recording
were complete. This is blocker diagnostics only: it was not a controlled
acceptance run and does not close the unattended recovery gate.

## Remaining gates

- private normal/HiDPI extension creation and first captured frame;
- true mirror state before start and cleared state after stop;
- AX migration/restore of a disposable real window, including display removal;
- Launch at Login approval plus logout/login relaunch;
- headless Mac mini reboot with a usable physical, dummy, or Screen Sharing
  display after login;
- selected-display hot-plug while streaming;
- Android touch/reconnect/keyboard/native-mouse checks after the device lease
  is released (keyboard/native mouse also require a future transport entry);
- Phase 1 two-hour no-growth result, USB glass-to-glass
  (`usb-glass-to-glass-sub50`), LAN glass-to-glass
  (`lan-glass-to-glass-sub80`), and input P95 (`input-p95-sub50`) latency. The
  glass-to-glass gates require external-camera evidence, and the input gate
  requires external-camera evidence or a synchronized-clock package with a
  sub-5 ms total error budget.

None of these gates is inferred from compilation or private-symbol presence.
