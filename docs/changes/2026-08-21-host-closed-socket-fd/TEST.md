# Host CLOSED Socket FD Diagnostic

## Scope

This change investigates macOS Host TCP file descriptors that remain visible in
`lsof` as `TCP 127.0.0.1:54321->... (CLOSED)` after short Android USB
connections. It is limited to Host socket/session lifecycle cleanup and
diagnostic tooling. It does not claim to close the two-hour Host RSS no-growth
gate.

## Existing evidence reviewed

Evidence directory:
`/tmp/vibe-screen-p0110-e2e/root-usb-smoke-20260821-223447`

Device identity from `device_identity.json`:

- Manufacturer: `nubia`
- Model: `P0110`
- Device codename: `pacific`
- Android release: `16`
- SDK: `36`

The saved `host_lsof_before.txt` snapshot shows Host PID `92943` with one
`LISTEN` FD on `127.0.0.1:54321` and 45 unique TCP socket FDs already in
`CLOSED` state. The 5-60 second smoke samples show one stable active ADB reverse
connection, with adb PID `11477` FD `18u` connected to Host FD `52u`. Android
logcat includes `stream_stats` around 60 FPS and zero decode drops for this
short smoke window.

The evidence proves the Host process still owned already-closed TCP socket FDs
at the time of the snapshot. The later smoke samples did not retain CLOSED rows,
so they do not establish the growth rate of the CLOSED count.

## Root cause

The Host installed an `NWConnection.stateUpdateHandler` closure that strongly
captured the same `NWConnection` instance. That forms an object cycle:

```text
NWConnection -> stateUpdateHandler closure -> NWConnection
```

When a client closed or the Host cancelled a replaced connection, the TCP state
could reach `CLOSED` while the process still held the socket through the retained
`NWConnection` wrapper. The fix weakens the self-capture and clears the state
handler when a connection reaches teardown.

## Verification

Commands run from
`/Users/luwentao/Workspaces/vibe-screen/.claude/worktrees/host-closed-fd-cleanup-20260821`:

```sh
make baseline-macos-build
```

Result: pass. The release macOS Host target built successfully.

```sh
swift build -c debug
```

Run from `baseline/MacHost`. Result: pass. The debug macOS Host target built
successfully.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_host_socket_fd -v
```

Result: pass, 5 tests.

```sh
make evidence-tools-test
```

Result: pass, 210 tests.

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.host_socket_fd \
  --input /tmp/vibe-screen-p0110-e2e/root-usb-smoke-20260821-223447/host_lsof_before.txt \
  --output /tmp/vibe-screen-p0110-e2e/root-usb-smoke-20260821-223447/host-socket-fd.json
```

Result: exit `2`, as expected for a diagnostic `fail`. The generated report
contains `closed_count=45`, `listen_count=1`, `established_count=0`, and
`gate.can_close_host_rss_no_growth_gate=false`.

```sh
cd baseline/MacHost && swift test --filter StreamingServerLifecycleTests/testClosedUSBConnectionsReleaseServerSocketWrappers
```

Result: blocked in this local environment before running tests because only
Command Line Tools are selected (`/Library/Developer/CommandLineTools`) and
`xcrun --find xcodebuild` fails; SwiftPM test compilation reports
`no such module 'XCTest'`. Run the focused XCTest on a machine with full Xcode
selected.

## Gate status

The README Host RSS/no-growth gate remains open. This change fixes and tests a
socket wrapper retention path and adds a socket-FD diagnostic, but it is not a
two-hour soak and cannot replace `host_rss_gate`.
