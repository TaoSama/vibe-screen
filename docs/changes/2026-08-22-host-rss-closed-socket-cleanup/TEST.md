# Host RSS Closed Socket Cleanup Test Record

## Scope

This change addresses one concrete Host resource-retention candidate found while
working toward the two-hour Host RSS no-growth gate: server-side TCP socket
wrappers can remain owned by the Host after their TCP state reaches `CLOSED`.
It also adds a read-only `lsof` summarizer and fail-fast Makefile entry points
for future formal Host RSS runs.

This record does not close the formal Host RSS gate. That still requires a
complete two-hour `soak-2h` evidence package and `host_rss_gate` with
`verdict=pass`.

## Existing State Reviewed

- `README.md` still marks Host RSS no-growth as open.
- `docs/changes/2026-08-10-host-rss-growth/TECH.md` records the historical
  Xiaomi/fuxi two-hour run with stable streaming but Host RSS growth.
- PR #158 adds `HOST_PID`/Makefile readiness and blocked P0110 evidence.
- PR #195 tightens capture frame lifecycle readiness but remains draft.
- PR #222 instruments frame lifecycle telemetry but remains draft.
- PR #230 identifies the closed socket FD retention candidate and provided the
  minimal production fix mirrored here.

## Root Cause Candidate

The Host installed a `NWConnection.stateUpdateHandler` closure that could retain
the same `NWConnection` object. If a client disconnected or a new connection
replaced an old one, the TCP socket could enter `CLOSED` while the process still
kept the server-side wrapper reachable. That is not enough to prove the full
historical RSS slope, but it is a real resource-retention path and is observable
with `lsof` on the Host PID.

The fix tracks accepted-but-not-yet-admitted connections, weakens the connection
capture in handlers and receive loops, clears `stateUpdateHandler` during
connection end/replacement/stop/token rotation, and cancels pending accepted
connections during teardown.

## Local Preflight

Read-only P0110/device state from the local environment:

- ADB serial: `<device-serial>`
- Manufacturer/model/device: `nubia` / `P0110` / `pacific`
- Android release/SDK: `16` / `36`
- ADB state: `device`
- ADB reverse: `UsbFfs tcp:54321 tcp:54321`
- Current Host PID: `92943`, command `/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen`

The current installed Host was already running and producing pipeline logs, but
it was not launched with `VIBE_SCREEN_TELEMETRY_PATH`, so the short diagnostic
and formal two-hour soak would not have complete Host telemetry. This shell also
reported `0 valid identities found` for code signing, Full Xcode was not active,
and direct TCC database reads were denied by macOS. No short diagnostic or
formal soak was started under those conditions.

Future Host RSS runs must first retain the shared Host readiness snapshot with
`make baseline-macos-host-readiness EVIDENCE_DIR=<evidence-dir>` and require
`host-readiness.json` to report `can_start_host_rss_gate=true` before a short
diagnostic or two-hour soak starts. This readiness artifact is a prerequisite
only: even when ready, it does not close the Host RSS no-growth gate without a
complete telemetry-backed run and `host_rss_gate` pass.

2026-08-22T08:34:55Z refresh on PR #260 head
`e6346fd060842844ce8bf761a80b520e83b3158b` kept the formal soak blocked:

- P0110 still identified as `nubia` / `P0110` / `pacific`, Android `16`,
  SDK `36`, with `UsbFfs tcp:54321 tcp:54321` reverse present.
- `/tmp/vibe-screen-device-soak.lock` was absent. A
  `/tmp/vibe-screen-device-android.lock` file was present for
  `android-ui-ux-p0110-e2e-pr272`, but its recorded PID was not observed alive
  during this refresh.
- `security find-identity -v -p codesigning` still reported `0 valid identities
  found`.
- `python3 scripts/macos_dev_host.py preflight --report ...` still failed
  closed because the `Vibe Screen Dev` signing identity was unavailable to this
  keychain.
- The installed `/Applications/Vibe Screen.app` was signed as
  `dev.telemachus.display`, but the current environment could not re-sign and
  reinstall the current source build, and the running Host was not proven to be
  the current-source telemetry-enabled binary.
- PR #260 remained `MERGEABLE/BLOCKED`: completed required checks passed, no
  unresolved review thread existed, and only the iOS `core` and
  `app-build-test-archive` checks were still queued.

No short Host memory diagnostic or formal two-hour soak was started during this
refresh, and the Host RSS no-growth gate remains open.

## Verification

Local checks run for this branch:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_host_socket_fd -v
```

Result: pass, 6 tests.

```sh
make release-tools-test
```

Result after rebasing onto `origin/main` at `47207c5`: pass, 87 tests.

```sh
make evidence-tools-test
```

Result after rebasing onto `origin/main` at `47207c5`: pass, 259 tests.

```sh
make baseline-macos-build
make baseline-macos-self-test
```

Result: pass. The release Host target built, then Host, transport, reliability,
Protocol v1, and video-encoder executable self-tests passed.

```sh
make -n soak-2h EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=.build/evidence HOST_PID=12345
make -n host-rss-gate EVIDENCE_DIR=.build/evidence
make -n soak-2h-host-rss-gate EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=.build/evidence HOST_PID=12345
```

Result: pass. The dry run includes `--host-pid 12345`, derives the exact-window
report, and then runs `host_rss_gate`.

```sh
make soak-2h-host-rss-gate EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=.build/evidence
```

Result: expected fail-fast, exit 2, before starting a two-hour run:
`error: set HOST_PID to the running Vibe Screen Host process id`.

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.host_socket_fd \
  --pid 92943 --port 54321 --samples 1 --interval-seconds 0 \
  --output .build/evidence/host-socket-fd-current/host-socket-fd.json
```

Result: diagnostic `fail`, `closed_count=82`, `listen_count=1`,
`gate.can_close_host_rss_no_growth_gate=false`. This samples the pre-existing
installed Host process, not a current-source fixed binary, so it is only
readiness/root-cause evidence.

The 2026-08-22T08:34:55Z refresh of the same read-only diagnostic on PID 92943
returned exit 2 with `closed_count=164`, `established_count=1`,
`listen_count=1`, and `gate.can_close_host_rss_no_growth_gate=false`. This
again sampled the pre-existing installed Host process, not a current-source
fixed binary.

```sh
git diff --check
```

Result: pass.

Swift/XCTest validation should include:

```sh
cd baseline/MacHost && swift test --filter StreamingServerLifecycleTests/testClosedUSBConnectionsReleaseServerSocketWrappers
```

If this environment still has only Command Line Tools selected and cannot build
`XCTest`, record that as blocked rather than treating the XCTest as passed.
Current result: blocked. The focused `swift test` reached test target
compilation and then failed with `no such module 'XCTest'`; `xcodebuild
-version` also reports that `/Library/Developer/CommandLineTools` is active
instead of full Xcode.

## Non-Claims

- This is not Xiaomi/fuxi evidence.
- This is not a short Host memory diagnostic result.
- This is not a formal two-hour Host RSS no-growth result.
- The Host RSS gate remains open until `host_rss_gate` reports `pass` on a
  complete, current-source, telemetry-backed two-hour run.
