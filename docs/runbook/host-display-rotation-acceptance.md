# Rotated Host-Display Acceptance

This runbook prepares and validates evidence for the rotated physical and
virtual Mac display gate. It does not close the gate by itself: acceptance still
requires a fresh real-device Protocol v1 USB or LAN run with retained artifacts
for both display kinds.

## Scope

- Host display rotation is the macOS display state reported by the selected
  physical or virtual display. It is not the Android client-local 90/180/270
  viewport transform.
- The Android client rotation must stay explicitly client-local for this run,
  normally Follow Mac or 0 degrees, and the evidence must record that host
  rotation was not combined into the client Surface/input transform.
- Nubia P0110/pacific on Android 16 may be used as a general Android substitute
  device when the evidence records its actual identity. Do not relabel it as
  Xiaomi 13/fuxi evidence.

## Preflight

Use one worktree and one Android device at a time. If a local device lock is in
use, stop and keep a blocked/readiness record instead of racing another run.

    git fetch origin --prune
    git rev-parse HEAD origin/main
    git merge-base --is-ancestor origin/main HEAD

    security find-identity -v -p codesigning | grep "Vibe Screen Dev"
    make baseline-macos-dev-install
    python3 scripts/macos_dev_host.py preflight \
      --install-path "/Applications/Vibe Screen.app" \
      --report docs/changes/2026-08-05-phase-1-android-client/evidence/<run>/host-preflight.txt

    make baseline-android-apk
    adb devices -l
    adb -s <serial> get-state
    adb -s <serial> shell getprop ro.product.manufacturer
    adb -s <serial> shell getprop ro.product.model
    adb -s <serial> shell getprop ro.product.device
    adb -s <serial> shell getprop ro.build.version.release
    adb -s <serial> shell getprop ro.build.version.sdk
    adb -s <serial> reverse tcp:54321 tcp:54321
    adb -s <serial> install -r -t baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk

The Host preflight is a gate dependency, not a convenience check. It must show a
stable non-ad-hoc signing identity, the expected bundle identifier, strict
codesign validation, and authorized Screen Recording plus Accessibility for the
same installed Host. If any item is blocked, keep the preflight output and do
not claim rotated host-display acceptance. This dependency is shared with the
Host signing/TCC preflight boundary.

Before rotating any display, record a restoration plan: the original display
identity, original macOS rotation, and the exact settings or command path that
will restore it. The acceptance evidence must later prove the original rotation
was restored.

## Evidence Steps

Create one evidence directory, for example:

    RUN_DIR=docs/changes/2026-08-05-phase-1-android-client/evidence/<yyyy-mm-dd-device-host-display-rotation>
    mkdir -p "$RUN_DIR"

For an existing physical display:

1. Save the device identity, APK install details, ADB reverse state, Host
   preflight report, Host PID, and a pre-rotation macOS display snapshot.
2. Rotate the selected physical Mac display to 90, 180, or 270 degrees through
   macOS display settings or an explicitly documented operator action.
3. Start the matching Protocol v1 USB or LAN session and select that display in
   the Android client.
4. Capture the Android visual result and a Host display snapshot while the Mac
   display is rotated.
5. Probe the four corners and center. Keep the touch matrix, Host input/capture
   log, Android logcat, stream stability counters, and proof that no session
   teardown occurred.
6. Restore the original macOS display rotation and retain proof of restoration.

Repeat the same sequence for a virtual display created by the Host. The virtual
display run must identify the virtual display separately from the physical
display and must not reuse the physical display snapshot as evidence.

## Evidence Summary

Write $RUN_DIR/host-display-rotation.json with one runs[] entry for the
physical display and one for the virtual display. Artifact paths are relative to
$RUN_DIR.

    {
      "schema_version": "vibescreen.evidence/v1",
      "kind": "host_display_rotation_acceptance",
      "runs": [
        {
          "display_kind": "physical",
          "display_id": "<macOS physical display id/name>",
          "transport": "usb",
          "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_release": "16",
            "sdk": 36,
            "adb_serial": "<serial>"
          },
          "host_preflight": {
            "host_signing_identity": "Vibe Screen Dev",
            "host_bundle_id": "dev.telemachus.display",
            "screen_recording_granted": true,
            "accessibility_granted": true,
            "signing_tcc_match": true,
            "host_display_rotation_restoration_plan": true
          },
          "host_rotation_degrees": 90,
          "original_host_rotation_degrees": 0,
          "client_rotation_degrees": 0,
          "client_transform_scope": "client-local-only",
          "host_rotation_combined_with_client_transform": false,
          "host_rotation_source": "macOS Displays settings",
          "probes": {
            "visual_source_orientation": true,
            "input_mapping": true,
            "stable_stream": true,
            "no_session_teardown": true,
            "restored_original_host_rotation": true
          },
          "artifacts": {
            "device_identity": "device-and-artifact-identity.txt",
            "host_display_snapshot_before": "physical-display-before.txt",
            "host_display_snapshot_rotated": "physical-display-rotated.txt",
            "android_screenshot": "android-physical-rotated-host-display.png",
            "touch_matrix": "physical-touch-matrix.txt",
            "host_log": "host.log",
            "android_logcat": "logcat.txt"
          }
        }
      ]
    }

The final file must contain both display_kind=physical and display_kind=virtual.
Validate it with retained-artifact checks enabled:

    PYTHONPATH=tools python3 -m vibescreen_evidence.host_display_rotation_gate \
      "$RUN_DIR/host-display-rotation.json" \
      --check-artifacts \
      --output "$RUN_DIR/host-display-rotation-gate.json"

The gate exits 0 only when both display kinds are present, every required probe
is true, the device identity is explicit, the Host signing/TCC preflight is
complete, artifact paths stay inside the evidence directory, and the retained
files exist. It still does not prove anything beyond the captured real-device
run named by that evidence directory.

## Failure Modes

- Missing stable Host signing or TCC grants: keep the preflight report and
  record the run as blocked. Do not use an ad-hoc Host to close this gate.
- Device lock occupied or no exclusive device window: keep a readiness record
  only; do not start partial input or display actions.
- Only one display kind recorded: the gate must fail until both physical and
  virtual rotated host-display runs are retained.
- Client-local rotation substituted for host rotation: the gate must fail if
  host_rotation_degrees is 0 or if host_rotation_combined_with_client_transform
  is true.
- Artifact path missing or outside the evidence directory: rerun collection or
  fix the summary to point at retained files before claiming acceptance.
- Original host rotation not restored: stop and restore the display first; a
  run without restoration proof cannot close the gate.

## Current Status

The 2026-08-20 P0110/pacific record is readiness evidence only: the device lock
was occupied, the stable Host signing/TCC preflight was blocked, and no rotated
physical or virtual host-display run was started. The rotated host-display
acceptance gate remains open until a fresh real-device run satisfies this
runbook and the offline gate.
