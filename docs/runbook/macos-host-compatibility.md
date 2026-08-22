# macOS Host compatibility matrix gate

This runbook defines the evidence required before README or release notes can
claim that Vibe Screen supports a macOS Host hardware row. It is owned by the
Vibe Screen core team / macOS Host maintainer. The gate is
separate from Android device acceptance, Host XCTest, and CI runner build
success.

Each passing row is scoped only to the exact Mac architecture, model, macOS
build, display topology, transport, Android counterpart, Host build identity,
and artifacts recorded for that run. Do not infer Intel support from Apple
silicon, a full macOS 13+ range from one OS build, or dummy/headless behavior
from a built-in or external-display run.

## Current status

| Matrix area | Current repository status | What can be claimed | Open implementation path |
| --- | --- | --- | --- |
| Apple silicon | Local Apple silicon development and historical device evidence exist, but no row has been summarized by `macos-hardware-compatibility-gate` yet. | Apple silicon has been locally exercised. Do not claim a published compatibility row until a gate summary passes for the exact host. | Collect one row per Mac model family, macOS build, display topology, and transport. |
| Intel Mac | No retained Intel Host compatibility row is published. | Open gate only. | Run the same build, package, TCC, capture, input, reconnect, and evidence summary on an Intel Mac. |
| macOS versions | Source minimum is macOS 13. CI currently runs macOS Host checks on `macos-15`; retained device evidence includes specific local macOS builds. | macOS 13+ is a build/runtime requirement, not proof that every 13+ release is compatible. | Add rows for each supported macOS major/minor build before broadening support text. |
| Display hardware | Physical/current-main, private virtual display, mirroring fallback, and headless/dummy behavior are topology-specific. | Only the topology actually recorded in a passing row is accepted. | Record built-in, single external, multi-display, dummy/headless, and Screen Sharing rows separately as needed. |

## Row dimensions

Define one matrix row with these dimensions before running the gate:

- CPU architecture: `apple_silicon` or `intel`.
- Mac model identifier and CPU/chip name.
- Exact macOS version and build.
- Display topology: `built_in`, `single_external`, `multi_display`,
  `dummy_or_headless`, or `screen_sharing`.
- Capture backend observed: `screencapturekit`, `cgdisplaystream_fallback`,
  `current_main_fallback`, or `unavailable`, with first-frame or terminal-failure
  evidence.
- VideoToolbox encoder path: `h264_hevc_available`, `h264_only`, `hevc_only`,
  or `unavailable`.
- Transport: USB or trusted LAN.
- Android counterpart identity used to prove a real Protocol v1 stream.

The row owner must also record the intended implementation path. Examples are
"support as accepted", "support only through current-main fallback",
"blocked pending Intel hardware", or "blocked pending dummy-display adapter".

## Evidence package

Create a directory such as:

```text
docs/changes/<change>/evidence/<date>-macos-host-compatibility-<host>-<os>/
```

Keep these artifacts in that directory:

- `host-identity.txt`: `sw_vers`, `uname -m`, `sysctl -n hw.model`, relevant
  `sysctl machdep.cpu.brand_string` or Apple chip output, and Xcode/Swift
  versions.
- `host-build.txt`: repository commit and dirty state, Host binary SHA-256,
  bundle id, signing identity, designated requirement, and install path.
- `host-signing-and-permissions.txt`: `scripts/macos_dev_host.py preflight`
  output or an equivalent read-only TCC/signing report.
- `display-topology.txt`: display UUIDs, online display IDs, logical and
  physical sizes, scale, refresh rate, rotation, and which display is built-in,
  external, dummy, virtual, or Screen Sharing.
- Host logs proving capture backend, display list/selection, virtual-display
  success or fallback, mirror success or fallback, VideoToolbox encoder path,
  Protocol v1 stream, input smoke, reconnect, and Host PID continuity.
- Android device identity, APK identity, logcat, screenshots or external photos
  showing the stream and visible input result.
- `macos-hardware-compatibility.json`: the boolean observations consumed by the
  gate.
- `macos-hardware-compatibility-gate.json`: the generated gate summary.

## Commands

Run the source and Host checks on the same source revision as the evidence row:

```bash
make baseline-macos-build
make baseline-macos-test
make baseline-macos-self-test
make baseline-macos-app
make baseline-macos-touch-preflight
```

Then launch the packaged Host, establish the selected USB or trusted-LAN
Protocol v1 session, and exercise at least these runtime probes:

- packaged Host launch on the recorded Mac row;
- display list and selected-display start;
- physical/current-main capture;
- private virtual display creation/capture, or an explicit fallback/unavailable
  result for that row;
- mirror success, or explicit current-main fallback/unavailable result;
- touch plus keyboard or scroll input through the Host path;
- client or process reconnect while the Host PID survives.

Summarize the row with:

```bash
make macos-hardware-compatibility-gate EVIDENCE_DIR=<evidence-dir>
```

The target reads `<evidence-dir>/macos-hardware-compatibility.json`, verifies
listed artifacts relative to that directory, and writes
`<evidence-dir>/macos-hardware-compatibility-gate.json`. The underlying Python
CLI exits `0` for `pass`, `1` for `blocked` or `insufficient`, and `2` for
`failed` invalid extrapolation claims; Make reports any non-pass result as a
failed target while still leaving the summary JSON behind. Treat the row as
accepted only when the summary contains `verdict=pass` and
`can_close_macos_host_compatibility_row=true`.

## Gate input

Start from this shape and set each observation only after the corresponding
artifact exists:

```json
{
  "owner": "Vibe Screen core team / macOS Host maintainer",
  "implementation_path": "support as accepted for this exact row",
  "repository_commit": "<40-character hexadecimal git commit>",
  "repository_dirty_state": "clean",
  "cpu_architecture": "apple_silicon",
  "host_model_identifier": "Mac14,10",
  "host_cpu_name": "Apple M2 Pro",
  "macos_version": "26.4.1",
  "macos_build": "25E253",
  "xcode_version": "Xcode 16.x",
  "swift_version": "Swift 6.x",
  "host_build_identity": "Vibe Screen Dev, bundle id, SHA-256, signing identity",
  "display_topology": "built_in",
  "capture_backend": "screencapturekit",
  "screen_capturekit_result": "selected_display_first_frame",
  "cgdisplaystream_result": "not_used",
  "videotoolbox_result": "h264_hevc_available",
  "virtual_display_result": "created_online_captured",
  "mirror_result": "current_main_fallback",
  "stream_transport": "usb",
  "android_counterpart": "manufacturer/model/codename/Android build/SDK",
  "compatibility_scope": "exact row only",
  "owner_recorded": true,
  "implementation_path_recorded": true,
  "repository_commit_recorded": true,
  "host_model_recorded": true,
  "cpu_architecture_recorded": true,
  "macos_version_build_recorded": true,
  "xcode_swift_recorded": true,
  "host_build_identity_recorded": true,
  "signing_and_tcc_state_recorded": true,
  "display_topology_recorded": true,
  "capture_backend_recorded": true,
  "video_encoder_path_recorded": true,
  "automated_macos_checks_passed": true,
  "packaged_host_launch_observed": true,
  "protocol_v1_stream_observed": true,
  "display_selection_observed": true,
  "physical_display_capture_observed": true,
  "virtual_display_or_fallback_recorded": true,
  "mirror_or_fallback_recorded": true,
  "input_smoke_observed": true,
  "reconnect_observed": true,
  "artifacts_retained": true,
  "claim_scoped_to_exact_row": true,
  "ci_runner_only": false,
  "claims_intel_from_apple_silicon": false,
  "claims_os_range_from_single_build": false,
  "claims_display_topology_from_different_setup": false,
  "claims_screencapturekit_from_cgdisplaystream": false,
  "claims_virtual_display_without_result": false,
  "claims_virtual_display_from_symbol_probe": false,
  "claims_virtual_display_from_current_main_fallback": false,
  "claims_dummy_headless_from_attached_monitor": false,
  "artifact_paths": ["host-identity.txt", "host.log"],
  "blocking_notes": [],
  "notes": ""
}
```

Missing observations default to `false`. If any `claims_*` or `ci_runner_only`
field is `true`, or the capture backend contradicts the recorded first-frame or
fallback result, the summary is `failed` because the evidence attempts to close
a row from another environment or implementation path. Missing owner,
implementation path, a clean 40-character repository commit, Host identity,
architecture, OS build, topology, automated macOS checks, packaged launch,
Protocol v1 stream, artifact retention, or exact-row scoping is `blocked`. Other
missing runtime probes are `insufficient`. Artifact paths must be existing
non-empty relative paths under the evidence directory; absolute paths, `..`
escapes, or stdin input without `--evidence-dir` keep the row blocked.

## Reporting rules

- A passing row may be listed as accepted only with its exact scope.
- A blocked or insufficient row is useful readiness evidence, but it must stay an
  open gate in README, release notes, and PR descriptions.
- A fallback row can be accepted only as fallback behavior. For example, a
  current-main mirror fallback does not prove hardware mirroring to a private
  virtual display.
- CI `macos-15` build/test success remains source-level evidence. It cannot close
  Intel, OS-range, display-topology, TCC, packaged-launch, or real-stream matrix
  rows by itself.
