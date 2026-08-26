# Phase 2 evidence directory

Create one subdirectory per physical-tablet run:

```text
YYYY-MM-DD-<device>-phase2-8h/
├── README.md
├── device-info.json
├── device.txt
├── host.txt
├── build.txt
├── apk-sha256.txt
├── phase2-tablet-manifest.json
├── soak-8h/
│   ├── samples.jsonl
│   ├── summary.json
│   ├── host-telemetry.jsonl
│   ├── exact-window-report.json
│   ├── phase2-device-memory-gate.json
│   ├── phase2-device-environment-summary.json
│   └── phase2-tablet-gate.json
├── samples.csv              # optional derived conversion; keep raw JSONL
├── adb-battery-before.txt
├── adb-battery-after.txt
├── adb-power-before.txt
├── adb-power-after.txt
├── phase2-device-environment-observations.json
├── thermal-before.txt
├── thermal-after.txt
├── thermal-before.err       # stderr capture; use status and dump content for failure
├── thermal-after.err        # stderr capture; use status and dump content for failure
├── raw-logcat.txt
├── reconnects.log
├── frame-drops.log
├── decoder-telemetry.jsonl
├── stylus-evidence.json
├── hardware-keyboard-evidence.json
├── orientation-evidence.json
├── recovery-evidence.json
├── phase2-tablet-preflight.json
└── screenshots/
    ├── sustained-use-portrait.png
    └── sustained-use-landscape.png
```

Collect `device-info.json` with:

```bash
make evidence-device-info EVIDENCE_SERIAL="$ADB_SERIAL" EVIDENCE_DIR="$RUN_DIR"
```

Before starting the eight-hour timer, create the Phase 2 manifest with
`make phase2-tablet-manifest EVIDENCE_DIR="$RUN_DIR" ...` and fill in the
stand, charger, host build, APK hash, transport, video preferences, thresholds,
and planned recovery scenarios. The file must validate against
`tools/schemas/phase2-tablet-manifest.schema.json`. It also records the Android
PSS source, Host RSS source, Host PID, minimum eight-hour duration, sample
cadence, and required memory/charging/thermal fields.
After the eight-hour soak and `phase2-tablet-gate` derivation, run
`make phase2-tablet-preflight EVIDENCE_DIR="$RUN_DIR"`. The generated
`phase2-tablet-preflight.json` is the final machine-readable bundle check for
physical-tablet identity, portrait/landscape UI, stylus, hardware keyboard,
recovery, thermal/power, and the eight-hour soak gate.
Create `phase2-device-environment-observations.json` before the final package
gate. It records whether the stand-mounted setup, eight-hour environment
window, battery/power samples, thermal samples, controlled thermal-load,
thermal recovery, and sustained-use UI/platform match were actually observed.

The artifact must validate against `tools/schemas/device-info.schema.json`;
`device.txt` and `phase2-tablet-manifest.json` are supporting records, not substitutes for the
schema-backed device identity. `thermal-before.err` and `thermal-after.err` are
stderr captures created by the runbook commands on every run. Determine thermal
collection failure from the command status and whether the corresponding dump is
usable, not from stderr-file presence alone.

After deriving the exact-window report, run `make phase2-device-environment-gate`
and then `make phase2-tablet-gate` from the repository root. The environment
gate writes `soak-8h/phase2-device-environment-summary.json`; the tablet gate
requires that summary to pass before the package can close. The tablet gate also
consumes `phase2-tablet-manifest.json`, the eight-hour soak report, and this raw
evidence directory before it can report `pass`. The wrapper-level close contract
is `phase2-soak-readiness.json` with `can_close_phase2_gate=true`; a standalone
README statement or APK placeholder hash is not formal pass evidence. Missing
raw artifacts, a missing or blocked device-environment summary, a phone
substitute such as Nubia P0110/pacific/Android 16, or an undeclared threshold
leaves the result `insufficient`.

The run `README.md` must state the real tablet model, OS build, density,
orientation/window sizes, charger/cable/stand setup, Mac host identity, commit
SHA, APK SHA-256, transport, video preferences, predeclared pass/fail thresholds,
exact collection commands, raw-log links, first failure if any, measured
duration/cadence, and final result. A `phase2-8h` directory can close the
eight-hour gate only when `summary.json` records `duration_seconds >= 28800`,
`interval_seconds <= 60`, zero missing sample gaps, and
`soak-8h/phase2-device-memory-gate.json` reports `pass` from Android PSS, Host
RSS, charging/full-state, and thermal samples. The stand-mounted charging and
thermal/power rows require `soak-8h/phase2-device-environment-summary.json` to
report `pass`, `can_close_stand_charging_gate=true`, and
`can_close_device_environment_gate=true`. Any app or host crash,
unrecovered interruption, stale frame/input acceptance, sustained severe or
critical thermal state, charging failure, missing Host PID/RSS, missing Android
PSS, or untrustworthy sample/transport data must record `first_failure_at` and
fail the run. A phone run, emulator run, synthetic layout test, focused unit
test, or short soak belongs in its own evidence record but does not close the
8-9 inch tablet, eight-hour sustained-use, or device-memory gates.

Hardware-keyboard workflow evidence uses a focused gate summary alongside any
tablet or substitute-device records. A passing directory must include
`hardware-keyboard-observations.json`, `hardware-keyboard-summary.json`,
`dumpsys-input.txt`, Android production forwarding logs, active selected-display
stream proof, focus/IME boundary proof, Host `Key injected:` or CGEvent
acknowledgement logs, Host listener/signing/TCC preflight records, and a
screenshot or recording of the visible Mac result. Generate the summary with:

```bash
make hardware-keyboard-gate EVIDENCE_DIR="$RUN_DIR"
```

The summary closes the hardware-keyboard workflow gate only when
`verdict=pass` and `can_close_hardware_keyboard_gate=true`. A blocked record may
be kept here when the Android device lock, physical keyboard, Host listener, or
stable signed/TCC Host prerequisite is missing; blocked evidence must not run
ADB when the shared Android lock is already held.

Physical-stylus workflow evidence now follows the same split: retain
`stylus-evidence.json` as the collector output and derive `stylus-summary.json`
with `make physical-stylus-gate EVIDENCE_DIR="$RUN_DIR"`. A summary closes
the drawing-app gate only when it reports `verdict=pass` and
`can_close_physical_stylus_gate=true`. Capability snapshots, synthetic ADB
stylus commands, blocked device-lock records, or logs without same-session
Android forwarding plus newly appended Host `Stylus injected:` lines must remain
blocked or insufficient.

Aggregate owner records live in dated `phase2-aggregate-owner-current-base`
directories. They consume child gate summaries and write
`phase2-aggregate-owner.json` plus `SHA256SUMS`. The aggregate is an ownership
and closure report only: missing child summaries remain blocked, a blocked
device-environment summary keeps stand/thermal/power open, and a Nubia
P0110/pacific phone manifest stays `android_substitute` readiness rather than
8-9 inch tablet evidence.

Login-startup/headless Mac mini evidence uses a separate
`macos-startup-recovery-evidence.json` input and the passive
`phase2-macos-startup-recovery-gate` verifier. The minimum JSON shape is:

```json
{
  "schema_version": "vibescreen.evidence/v1",
  "kind": "macos_startup_recovery_evidence",
  "run_id": "YYYY-MM-DD-mac-mini-headless",
  "source_commit": "<git sha>",
  "mac_host": {
    "model": "Mac mini",
    "architecture": "arm64",
    "macos_version": "<version>",
    "macos_build": "<build>",
    "host_bundle_identifier": "dev.telemachus.display",
    "host_signing": "identity_signed",
    "host_cdhash": "<cdhash>",
    "host_binary_sha256": "<sha256>",
    "screen_recording_permission": "granted",
    "accessibility_permission": "granted",
    "signing_report": "host-signing-and-permissions.txt",
    "permission_report": "host-signing-and-permissions.txt",
    "host_log": "telemachus.log"
  },
  "login_item": {
    "status": "enabled",
    "requires_approval": false,
    "reboot_or_logout_login_performed": true,
    "login_launch_observed": true,
    "manual_launch_used": false,
    "system_settings_artifact": "login-items.png",
    "launch_log": "login-launch.log"
  },
  "automatic_startup": {
    "auto_start_enabled": true,
    "startup_mode": "usb",
    "onboarding_completed": true,
    "first_server_start_observed": true,
    "client_render_observed": true,
    "startup_log": "startup.log",
    "client_render_artifact": "client-render.png"
  },
  "display": {
    "topology": "dummy_or_headless",
    "capturable_display_observed": true,
    "first_frame_observed": true,
    "display_uuid": "<display uuid>",
    "claims_headless_from_attached_monitor": false,
    "dimensions": {
      "logical_width": 1920,
      "logical_height": 1080,
      "physical_width": 1920,
      "physical_height": 1080
    },
    "display_report": "display.json",
    "first_frame_artifact": "first-frame.png"
  },
  "unattended_recovery": {
    "trigger": "listener_startup_failure",
    "observed": true,
    "retry_delays_seconds": [1, 2, 4, 8, 16, 30, 30, 30],
    "full_speed_loop_observed": false,
    "restart_succeeded": true,
    "bounded_exhaustion_observed": false,
    "logs_retained": true,
    "recovery_log": "unattended-recovery.log"
  },
  "window_recovery": {
    "move_observed": true,
    "disconnect_or_failure_trigger_observed": true,
    "restored_observed": true,
    "accessibility_error_observed": false,
    "original_frame": {"x": 100, "y": 100, "width": 800, "height": 600},
    "restored_frame": {"x": 100, "y": 100, "width": 800, "height": 600},
    "window_log": "window-recovery.log",
    "before_artifact": "window-before.png",
    "after_artifact": "window-after.png"
  },
  "remote_access": {
    "method": "screen_sharing",
    "operator_intervention_path_verified": true,
    "filevault_or_first_login_blocker_absent": true,
    "requires_unavailable_local_intervention": false,
    "access_artifact": "screen-sharing-settings.png"
  },
  "android_device": {
    "adb_serial": "<adb-serial>",
    "manufacturer": "nubia",
    "model": "P0110",
    "codename": "pacific",
    "android_release": "16",
    "sdk": "36",
    "device_info": "device-info.json"
  },
  "android_reconnect": {
    "trigger": "usb_replug",
    "disconnect_observed": true,
    "reconnect_attempt_observed": true,
    "reconnect_succeeded": true,
    "client_render_after_reconnect_observed": true,
    "reconnect_log": "android-reconnect.log",
    "client_render_artifact": "android-reconnect-render.png"
  }
}
```

Run:

```bash
make phase2-macos-startup-recovery-gate EVIDENCE_DIR="$RUN_DIR"
make phase2-aggregate-owner EVIDENCE_DIR="$RUN_DIR" \
  PHASE2_LOGIN_HEADLESS="$RUN_DIR/macos-startup-recovery-gate.json"
```

The gate writes `macos-startup-recovery-gate.json`. It can close the aggregate
`login_startup_headless` row only when it reports `verdict=pass` and
`can_close_login_headless_gate=true`. Missing reboot/login, Login Items
approval, identity signing, current TCC grants, capturable dummy/headless or
Screen Sharing display, first client-rendered frame, bounded recovery logs,
real window restoration, or operator intervention path evidence must stay
`blocked`. Manual app launch, an attached monitor relabeled as headless, or a
Nubia P0110/pacific Android artifact relabeled as Xiaomi/fuxi must report
`fail`.

## Blocked evidence

When no physical 8-9 inch tablet is available, create a blocked record instead
of a pass-shaped directory. The minimum blocked package is:

```text
YYYY-MM-DD-<device>-blocked-no-physical-tablet/
├── README.md
├── device-info.json
├── phase2-device-environment-observations.json
├── phase2-tablet-manifest.json    # PHASE2_DEVICE_CLASS=android_substitute
├── phase2-tablet-preflight.json   # verdict=blocked
└── soak-8h/phase2-device-environment-summary.json  # verdict=blocked
```

The README must name the substitute device, state that it is not an 8-9 inch
tablet, link any short readiness evidence, and include the exact rerun commands
for the future physical-tablet pass. The blocked preflight should preserve all
missing gates rather than editing them out.

For stand/thermal/power readiness records, also run:

```bash
make phase2-device-environment-gate EVIDENCE_DIR="$RUN_DIR"
```

The generated summary must keep both close booleans false unless a real physical
tablet run supplies the declared stand setup, full eight-hour sampling window,
and controlled thermal-load recovery evidence.

The `phase2-tablet-soak-preflight` wrapper may create readiness-only directories
such as `YYYY-MM-DD-nubia-p0110-phase2-soak-preflight/`. These records include
`phase2-soak-readiness.json` and may include a `soak-preflight/` subdirectory
rather than a formal `soak-8h/` result. When the wrapper is blocked by
`/tmp/vibe-screen-device-android.lock` or `/tmp/vibe-screen-device-soak.lock`,
it writes only `phase2-soak-readiness.json` and `README.md`; it does not collect
static ADB, logcat, or soak artifacts. A readiness result of `blocked` records
why the gate could not start, such as a phone substitute, missing Host PID,
missing Host JSONL telemetry, an existing device lock, or missing APK identity.
It is not evidence that the eight-hour gate passed.
