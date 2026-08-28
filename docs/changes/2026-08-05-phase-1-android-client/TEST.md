# Phase 1 Android client verification

Date: 2026-08-05

> Historical implementation record: the matrix below describes the original
> Android-only legacy-session slice. Later Protocol v1 display, keyboard,
> pointer, video-control, and Host-action work supersedes its capability
> boundary. Current status is summarized in `README.md` and the dated follow-up
> sections in this file.

Branch: `codex/phase1-android-client-experience`
Implementation base: `6f7ffbe0be872390144899642636dbb24d89f120`

Final branch base after synchronization: `5a12d2a1dcdf3a719753e413fb85b63aa35aca90`

## Scope and protocol boundary

This change implements the Android-only part of the Phase 1 experience without
changing Protocol v1 or the macOS host. The runnable application still uses the
legacy touch protocol.

| Capability | Implementation status | Evidence status |
| --- | --- | --- |
| Fit/fill scaling | client-local MediaCodec mode, rotated viewport container, aspect-preserving Fit surface, and crop-aware Fill mapping | eight rotation/scale corner matrices pass on JVM; Fit synthetic-device geometry passed; Fill device check pending |
| rotation | actual Surface pixel transform with 90°/270° viewport/surface dimension exchange and input inverse transform | four-direction layout/corner matrix passes on JVM; four-mode visual device check pending |
| Mac display selection | explicit touch-only capability boundary; host-selected stream shown | correctly blocked; host/session integration required |
| tap/drag/right click/scroll/pinch | existing touch path retained; secondary mouse button and wheel adapt to touch gestures | injected tap/long swipe produced touch packets; Mac result and two-finger checks pending |
| keyboard/shortcuts | common Android keys map to protocol-neutral USB HID events | HID mapping/gate passed on device; forwarding blocked by legacy host |
| external mouse/keyboard | wheel and secondary-button adapters; physical keys captured and gated | physical peripherals pending; native pointer/keyboard protocol required |
| reconnect/errors | per-session generation gates all client/decoder callbacks; typed retryability preserves failure reasons and stops protocol-error loops; wireless post-connect startup has exactly-once socket/stream ownership | stale/no-display endpoint and synthetic cold reconnect passed on device; stale-generation, ready-session, invalid-local-auth, and post-auth startup-failure paths pass on JVM |
| permissions/lifecycle | Camera permission is re-evaluated after returning from Settings; background pauses input/retries and keep-awake, foreground resumes/rekeys | original camera deny/settings launch passed on device; Settings-return state machine passes on JVM; post-review device rerun pending |
| outbound input | bounded single writer reserves recovery capacity, uses non-blocking atomic ingress under lock contention, coalesces MOVE/ping/keyframe, preserves admitted touch-boundary FIFO, gracefully drains releases, and fails closed only on true capacity saturation | contention/capacity/close-race/order/write-failure/graceful-close tests pass on JVM; physical-peripheral device check pending |

No unsupported keyboard, pointer, controller, peripheral, or display-selection
bytes are added to the legacy wire format. This is an intentional compatibility
boundary rather than a missing fallback implementation: the legacy session
remains touch-only so old peers never receive unnegotiated native-input bytes.
A compatible Protocol v1 negotiated application session remains the gate for
those controls.

## Offline evidence

The coordinated Phase 0 two-hour HEVC soak initially owned
the lease-controlled `$ADB_ENDPOINT` through
`/tmp/vibe-screen-device-soak.lock`. While that
lock existed, this change performed no ADB connect/install/launch/force-stop,
reverse mutation, media-port probe, or MacHost start. That soak never opened
its formal clock because the locked Mac exposed zero ScreenCaptureKit displays.
After its owner released the lock, this task acquired the coordinated short
lease as `/tmp/vibe-screen-device-android.lock`, completed the run below, then
stopped the app/test server and removed the lock.

The final clean gate completed after implementation:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug auditReleaseDependencies
```

Results:

- 468 JVM tests, zero failures/errors/skips;
- the final graceful overflow marker-gap regression passed three consecutive isolated
  `--rerun-tasks` executions;
- lint reported `No issues found`;
- all requested Gradle tasks completed with `BUILD SUCCESSFUL in 40s`;
- final clean-rebuild APK SHA-256:
  `66eaa6f7175d102dad55a94f1c983aaff3ffbcc32365c581c222e7ec46b7ed71`.

The same APK was installed on Xiaomi 13 `<redacted-xiaomi-serial>` at
`2026-08-10 22:00:21 +08:00`; the final-build device rerun is recorded below.

## Nubia P0110 device run

The endpoint re-identified as Nubia P0110 (`pacific`), Android 16 / SDK 36,
hardware serial `[redacted]`, fingerprint
`nubia/pacific/pacific:16/2.5.2.0/20260804.003241:userdebug/test-keys`, and
1264×2800 at 560 dpi. It is not the Xiaomi 13 (model 2211133C, codename fuxi)
primary target; this record is Nubia P0110 evidence only. Later Xiaomi 13
streaming, display-switch, and input evidence is recorded under
`../2026-08-04-phase-0-baseline/evidence/2026-08-08-xiaomi12-fuxi-8a023e3a/` and
the fuxi Phase 1 evidence directories.

The device-run APK installed with `adb install -r -t` at
`2026-08-05 01:46:06 +08:00`. Its Android Debug signer certificate SHA-256 is
`b108fb9e0c8e5544171d57eb3be57d9fb93f332fc4954e26d5f51b20b876aa0b`.
Its SHA-256 was
`37e7c2b7e107443c298a8d59d054fac027ad32021bb5eeadcb87f73d649c3892`.
The install-time working tree was based on
`6f7ffbe0be872390144899642636dbb24d89f120`, but its Android changes were not
yet committed, so there is no exact installed Git commit; the device APK hash
is the authoritative artifact identity.

After the lease ended, review added malformed-display validation, true client
rotation and inverse input mapping, callback-generation isolation, bounded and
recovery-prioritized outbound scheduling, typed terminal failures, Camera
Settings-return recovery, atomic capability/input-sink installation, and
strict non-blocking saturation fail-close with asynchronous cleanup. The final
implementation also serializes decoder teardown and reinitialization off the
UI thread, distinguishes writer lock contention from actual outbound capacity,
and gives wireless post-auth startup exactly-once termination ownership. The
    final clean build from that earlier Nubia run was not reinstalled there.
That historical limitation is superseded only by the later Xiaomi 13
final-build record below, not retroactively for the Nubia evidence.

The Mac remained locked, so ScreenCaptureKit could not provide a real display.
The device run therefore used the repository's existing 2000×1124@60 synthetic
HEVC StreamTest for media/transport checks and keeps all Mac-side interaction
gates open.

- Qualcomm `c2.qti.hevc.decoder` produced the first output frame; continuing
  counters held approximately 60 FPS with typical 4–8 ms decoder latency.
- Fit measured as a centered `2249×1264` Surface inside the `2800×1264`
  landscape root, matching the 2000:1124 stream ratio instead of stretching.
- ADB-injected tap and long swipe produced real one-pointer touch packets at
  the synthetic server. This is packet evidence, not a visible Mac click,
  right click, scroll, pinch, or drag result.
- Injected Android C key mapped to USB HID usage 6 and was rejected with the
  touch-only compatibility path; no unnegotiated keyboard byte was sent. This
  is not physical-keyboard evidence.
- Background/foreground preserved the live transport, recreated the surface
  and decoder, requested a keyframe, and produced a new first output frame.
- Force-stop/cold-start kept StreamTest PID `40731`; the new session received
  display config at diagnostic timestamp `1785866249899`, initialized the
  decoder at `1785866250009`, and produced first output at `1785866250082`
  (183 ms config-to-first-output). The scripted wall window included an
  intentional two-second stopped interval and is not reported as reconnect
  latency.
- With Camera denied, USB cold-started without a permission dialog. First and
  permanent denial led to an actionable Camera state; **Open Settings** opened
  Android's `InstalledAppDetailsActivity`. After permission recovery,
  `QRScannerActivity` launched without a fatal exception.
- A stale reverse endpoint that accepted TCP then closed before display config
  now remained unready and showed “Open Vibe Screen on your Mac, then try
  again,” rather than entering a false connected loop.

Screenshots, UI XML, and application-tag-filtered logcat are retained in
[`evidence/device-nubia-p0110-android16/`](evidence/device-nubia-p0110-android16/).
The private diagnostic timestamps quoted above were observed during the run,
but the raw file was lost during post-run filtering and is not claimed as a
retained artifact.

## Device acceptance still required

Follow [`docs/runbook/android-client.md`](../../runbook/android-client.md) and
still record:

- identity before install, APK hash/signing/install time, and exact commit;
- host-side rotation on existing physical and virtual displays beyond the
  client-local matrix recorded below;
- tap, long-press right click, long-press drag, two-finger scroll and pinch;
- physical mouse wheel/secondary button and physical keyboard compatibility UI;
- a real unlocked Mac stream, missing reverse, host interruption, Host PID,
  visible Mac result, session epochs, and end-to-end recovery duration;
- Android diagnostic/logcat plus visible Mac-side outcomes.
- USB glass-to-glass (`usb-glass-to-glass-sub50`), LAN glass-to-glass
  (`lan-glass-to-glass-sub80`), and input P95 (`input-p95-sub50`) latency
  gates remain open until a formal external-camera package, or synchronized-clock
  package for input only, passes the stricter latency provenance checker.

Compilation, synthetic media, ADB-injected events, and old Phase 0 tap evidence
cannot close the remaining unlocked-Mac, physical-peripheral, or Xiaomi 13
gates for this legacy-protocol record.

Separately, and outside this legacy touch-protocol acceptance, later Protocol
v1 sessions on the Xiaomi 13 have verified real streaming, display switch,
keyboard/scroll input, and reconnect; those results belong to the Protocol v1
records and evidence directories under
`../2026-08-04-phase-0-baseline/`, not to this Nubia-based legacy run. A
host-RSS-stable two-hour soak and a physical HID mouse move/click confirmation
remain open there.

## Xiaomi 13 responsive connection-page follow-up

On 2026-08-10, the disconnected Android connection page was verified on a
Xiaomi 13 (`2211133C`, `fuxi`, Android 16) in portrait and full-screen
landscape. USB, LAN, and Internet modes use a 40/60 header/actions split when
the current landscape window is at least 600dp wide, while narrower landscape
windows fall back to the scrollable stacked layout instead of compressing the
action controls.

The compiled resource table records `default=false`, `land=false`, and
`w600dp-land=true`. On device, the 914dp full-screen landscape remained two
columns; a temporary 457dp-wide landscape display override produced one
stacked column, and scrolling exposed the primary action and connection
details without horizontal clipping. The override was reset afterward. This
proves the width-qualified resource behavior but is not presented as a real
split-screen gesture run.

Evidence:

- [`evidence/2026-08-10-fuxi-landscape-connection-ui/`](evidence/2026-08-10-fuxi-landscape-connection-ui/)
- [`evidence/2026-08-10-fuxi-narrow-landscape/`](evidence/2026-08-10-fuxi-narrow-landscape/)

## Xiaomi 13 viewport and input follow-up

On 2026-08-10, the current Protocol v1 USB stream on the Xiaomi 13 completed
the client-local Fit/Fill matrix for Follow Mac, 90, 180, and 270 degree
rotation. Debug-only input records captured four corners plus center for each
mode, except that Fill/270 uses an inset bottom-left point because the exact
bottom edge was intercepted before it reached the video input view. The
normalized results match the JVM inverse-transform matrices, and the center is
`0.5,0.5` in every mode.

The same pass corrected the Viewport description and made Show Stats opt-in;
the draggable overlay consumes its covered touch region and should not create a
default blind spot. A host=90/client=Follow Mac experiment also confirmed that
host rotation must not be added to the client Surface/input transform: source
pixels remain in their captured orientation, and adding that rotation sent the
visible top-left to the Mac's bottom-left. The final client-only mapping sent it
to the Mac's top-left. This closes client-local rotation with host rotation zero
only; portrait behavior for rotated physical or virtual host displays remains a
separate gate.

Evidence:

- [`evidence/2026-08-10-xiaomi13-viewport-input/`](evidence/2026-08-10-xiaomi13-viewport-input/)

## Rotated host-display acceptance gate

The retained viewport/input evidence closes only the client-local Fit/Fill and
Follow Mac/90/180/270 matrix with `hostRotation=0`. The host=90 experiment in
that evidence is a boundary check: it proves host display rotation must not be
combined into the Android Surface/input transform. It is not an acceptance run
for a rotated physical or virtual Mac display.

Before claiming rotated host-display acceptance, run a fresh real-device pass
that records both display kinds across all required host rotations:

1. Rotate an existing physical Mac display through 90, 180, and 270 degrees;
   for each angle, stream it over a Protocol v1 USB or LAN session, capture
   visual source orientation, corner/center inverse touch mapping in host
   logical-display coordinates, stable stream state, no session teardown, and
   restoration of the original macOS rotation.
2. Repeat the same 90/180/270 probes for a virtual display in its rotated
   host-display state.
3. Keep client rotation as an explicit client-local setting, usually Follow Mac
   or 0 for the host-display run, and do not treat the existing client-local
   90/180/270 matrix as host-display rotation evidence.
4. Record retained artifacts for device identity, before/rotated host display
   snapshots, Android screenshot, touch matrix, Host log, and Android logcat.
5. Record the Host signing/TCC preflight for the exact installed Host bundle.
   The gate depends on a stable non-ad-hoc signing identity, matching bundle
   identifier, Screen Recording grant, Accessibility grant, and a restoration
   plan for the original macOS display rotation.

The detailed operator checklist is in
[`docs/runbook/host-display-rotation-acceptance.md`](../../runbook/host-display-rotation-acceptance.md).

Summarize the retained evidence in a JSON file matching
[`tools/schemas/host-display-rotation-evidence.schema.json`](../../../tools/schemas/host-display-rotation-evidence.schema.json)
and run the offline gate. This command validates the record only; it does not
rotate displays, start the Host, touch ADB, or perform device actions:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.host_display_rotation_gate \
  docs/changes/2026-08-05-phase-1-android-client/evidence/<run>/host-display-rotation.json \
  --check-artifacts \
  --output docs/changes/2026-08-05-phase-1-android-client/evidence/<run>/host-display-rotation-gate.json
```

Minimum summary shape:

```json
{
  "schema_version": "vibescreen.evidence/v1",
  "kind": "host_display_rotation_acceptance",
  "runs": [
    {
      "display_kind": "physical",
      "display_id": "<macOS display id/name>",
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
      "inverse_touch_mapping": {
        "coordinate_space": "host-logical-display",
        "tolerance_px": 8,
        "points": [
          {
            "name": "top_left",
            "android_x": 16,
            "android_y": 16,
            "expected_host_x": 0,
            "expected_host_y": 0,
            "observed_host_x": 2,
            "observed_host_y": 1,
            "error_px": 2.2,
            "within_tolerance": true
          },
          {"name": "top_right", "android_x": 1248, "android_y": 16, "expected_host_x": 1999, "expected_host_y": 0, "observed_host_x": 1997, "observed_host_y": 2, "error_px": 2.8, "within_tolerance": true},
          {"name": "bottom_left", "android_x": 16, "android_y": 2784, "expected_host_x": 0, "expected_host_y": 1199, "observed_host_x": 1, "observed_host_y": 1196, "error_px": 3.2, "within_tolerance": true},
          {"name": "bottom_right", "android_x": 1248, "android_y": 2784, "expected_host_x": 1999, "expected_host_y": 1199, "observed_host_x": 1998, "observed_host_y": 1197, "error_px": 2.2, "within_tolerance": true},
          {"name": "center", "android_x": 632, "android_y": 1400, "expected_host_x": 1000, "expected_host_y": 600, "observed_host_x": 1001, "observed_host_y": 601, "error_px": 1.4, "within_tolerance": true}
        ],
        "all_points_within_tolerance": true
      },
      "artifacts": {
        "device_identity": "device-and-artifact-identity.txt",
        "host_display_snapshot_before": "host-display-before.txt",
        "host_display_snapshot_rotated": "host-display-rotated.txt",
        "android_screenshot": "android-rotated-host-display.png",
        "touch_matrix": "touch-matrix.txt",
        "host_log": "host.log",
        "android_logcat": "logcat.txt"
      }
    },
    {
      "display_kind": "virtual",
      "display_id": "<macOS virtual display id/name>",
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
      "host_rotation_source": "macOS Displays settings or Host virtual-display configuration",
      "probes": {
        "visual_source_orientation": true,
        "input_mapping": true,
        "stable_stream": true,
        "no_session_teardown": true,
        "restored_original_host_rotation": true
      },
      "artifacts": {
        "device_identity": "device-and-artifact-identity.txt",
        "host_display_snapshot_before": "virtual-display-before.txt",
        "host_display_snapshot_rotated": "virtual-display-rotated.txt",
        "android_screenshot": "android-virtual-rotated-host-display.png",
        "touch_matrix": "virtual-touch-matrix.txt",
        "host_log": "host.log",
        "android_logcat": "logcat.txt"
      }
    }
  ]
}
```

The final evidence file must contain six successful entries: physical
90/180/270 and virtual 90/180/270. A shorter file remains a readiness or
blocked record only.

## Xiaomi 13 window-action and recovery follow-up

On 2026-08-10, the Protocol v1 Host action catalog was wired to an opt-in
Android control-bar menu for `move-window` and `return-windows`. The catalog can
arrive before display negotiation finishes; the client caches it and now
re-evaluates visibility after the session binding gains
`CAPABILITY_HOST_ACTIONS`, avoiding a permanently hidden action button.

The same run closed two display-lifecycle faults found during acceptance. Cold
extended-mode startup now waits for WindowServer registration and treats a
failed mirror-disable operation as non-fatal only when the new display is not
actually mirrored. A managed virtual display also stays registered and keeps a
stable live id while physical capture is selected, so the client can switch
physical -> virtual -> physical -> virtual without retaining an offline id.

With virtual display 35 online at `(1512,0) 2000x1200`, the focused TextEdit
window moved from `(181,102) 586x488` to `(1846,179) 586x488`, returned exactly
to `(181,102)`, and returned there again when the Android process disconnected.
Host and Android logs recorded accepted move/return results and `Restored 1
moved window(s)`. This closes Protocol v1 client-driven move, explicit return,
and disconnect recovery for the recorded Xiaomi 13 USB session. It does not
close native HID pointer confirmation, rotated-host-display acceptance, login
item/headless reboot, or the host-RSS no-growth gate.

The final clean APK
`66eaa6f7175d102dad55a94f1c983aaff3ffbcc32365c581c222e7ec46b7ed71`
was then installed on `<redacted-xiaomi-serial>`. With the Host pinned to that serial and
configured for `extended`, a clean Host/client launch created virtual display
38 and advertised it first: `selected=38`, `2000x1200`, `config epoch=1`.
The control hierarchy showed `Vibe Screen Virtu…` plus an enabled `Window
actions` button. The final build repeated the exact TextEdit move/return
geometry `(181,102) 586x488 -> (1846,179) 586x488 -> (181,102) 586x488`,
and force-stopping Android again produced `Restored 1 moved window(s)` before
the next cold launch returned directly to display 38 at about 60 FPS.

Two connected fuxi devices can otherwise fight over the Host's single-client
listener. The rerun isolated `<redacted-xiaomi-serial>`, stopped the client on `<redacted-xiaomi-serial-2>`, and
set `Telemachus_adbDeviceSerial=<redacted-xiaomi-serial>`; without that isolation, each new
connection correctly cancels the previous one and resembles a reconnect loop.

Evidence:

- [`evidence/2026-08-10-xiaomi13-window-actions/`](evidence/2026-08-10-xiaomi13-window-actions/)

## Xiaomi 13 touch-gesture follow-up

On 2026-08-13 an explicit opt-in instrumentation test drove tap, long-press
right click, long-press drag, two-finger scroll, and pinch through the live
Protocol v1 USB session. Host gesture logs and a listen-only macOS event tap
proved the production CGEvent path; the driver itself does not receive a Host
acknowledgement. Repeating the matrix exposed that pinch's
Command modifier could leak through the shared CGEvent source into later plain
pointer events. Pinch now uses a private synthetic-modifier event source, with
focused isolation coverage, while ordinary pointer events preserve legitimate
system modifiers. A later stable-signed fixed-binary rerun on the Nubia
P0110/pacific Android substitute passed the same opt-in gesture matrix and
post-pinch modifier-isolation check while keeping the device identity distinct
from Xiaomi 13/fuxi evidence; see
[`../2026-08-13-xiaomi13-touch-gestures/TEST.md`](../2026-08-13-xiaomi13-touch-gestures/TEST.md).

## P0110 Android UI polish smoke

On 2026-08-20, PR #141 installed and launched on the connected Nubia P0110
(`pacific`, Android 16 / SDK 36). Screenshots were retained before and after
an ADB tap near the top control-reveal region. The screenshots are non-blank
`1264x2800` PNGs and differ by 1913 pixels in an absolute-error image
comparison, proving only a small rendered-state change during a device smoke
check.

This does not close active-stream, display-switching, video-preference,
reconnect, or hidden-control-touch-forwarding gates, and it is not Xiaomi 13 /
fuxi evidence. See
[`evidence/2026-08-19-p0110-ui-polish-smoke/`](evidence/2026-08-19-p0110-ui-polish-smoke/).

## P0110 native pointer HID follow-up

On 2026-08-20, the connected Nubia P0110 (`pacific`, Android 16 / SDK 36)
was checked under `/tmp/vibe-screen-device-android.lock`
with the native pointer HID acceptance script. The script recorded device
identity and `dumpsys input`, but found no external Android input device with
a `MOUSE`, `MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL` source. It therefore
wrote a `blocked` evidence bundle and did not wait for pointer movement/click
observation.

This does not close the native pointer move/click gate. A passing run still
requires a real USB or Bluetooth mouse attached to the Android device during an
active Protocol v1 session, newly appended Host `Pointer injected` logs for
`changed`, `began`, and `ended`, and a visible Mac pointer/button result.
Synthetic ADB mouse events remain excluded from gate closure.

Evidence:

- [`evidence/2026-08-18-p0110-native-pointer-hid-blocked/`](evidence/2026-08-18-p0110-native-pointer-hid-blocked/)
- [`evidence/2026-08-20-p0110-native-pointer-hid/`](evidence/2026-08-20-p0110-native-pointer-hid/)

## P0110 native pointer HID readiness follow-up

On 2026-08-21, the connected Nubia P0110 (`pacific`, Android 16 / SDK 36)
was checked again with the stricter native pointer HID
acceptance script. The script records `dumpsys input`, bounded Android `MA`
logcat, and the newly appended Host log window, and it requires all three
evidence layers before returning pass: Android `native pointer forwarded` lines
for `MOVE`, `BUTTON_PRESS`, and `BUTTON_RELEASE` from `MOUSE`,
`MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL`; Host `Pointer injected` lines for
`changed`, `began`, and `ended`; and an operator note describing the visible Mac
pointer/click result.

The connected P0110 was online, but no external Android input device with a
`MOUSE`, `MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL` source was attached. The
script therefore returned `blocked` (`exit_code=2`) and wrote empty Android/Host
observation windows rather than fabricating runtime evidence. This does not
close the native pointer move/click gate, and the result remains P0110/pacific
evidence, not Xiaomi 13/fuxi evidence.

Evidence:

- [`evidence/2026-08-21-p0110-native-pointer-hid-readiness/`](evidence/2026-08-21-p0110-native-pointer-hid-readiness/)

## P0110 native pointer HID current-base gate summary

On 2026-08-22, the connected Nubia P0110 (`pacific`, Android 16 / SDK 36)
was checked from current `origin/main` plus the native pointer HID gate-summary
tooling. The `make native-pointer-hid-acceptance` target invoked
`scripts/native_pointer_hid_acceptance.py`, recorded the real P0110 identity and
`dumpsys input`, and then ran the independent
`vibescreen_evidence.native_pointer_hid` summary over the generated
`result.json`.

No external Android input device with a `MOUSE`, `MOUSE_RELATIVE`, `TOUCHPAD`,
or `TRACKBALL` source was attached. The target therefore returned `blocked`
(`exit_code=2`), and `native-pointer-hid-summary.json` reports
`verdict=blocked` with `can_close_native_pointer_hid_gate=false`. This does not
close the native pointer move/click gate, and it remains P0110/pacific evidence,
not Xiaomi 13/fuxi evidence.

Evidence:

- [`evidence/2026-08-22-p0110-native-pointer-hid-current-gate/`](evidence/2026-08-22-p0110-native-pointer-hid-current-gate/)

After rebasing the PR branch onto `origin/main` commit
`4dc84505b0edcd76a820cb2ba219461312ba8b81`, the same target was run again
against the requested P0110 serial. A shared Android coordination lock was held
by another P0110 task, so the collector exited before running ADB, wrote
`blocked_device_coordination_lock`, and kept
`can_close_native_pointer_hid_gate=false`. This current-main rerun records only
readiness/blocking state; it does not replace the earlier P0110 identity
record and does not close the physical HID mouse gate.

- [`evidence/2026-08-22-p0110-native-pointer-hid-current-gate-main-4dc84505/`](evidence/2026-08-22-p0110-native-pointer-hid-current-gate-main-4dc84505/)

After the Android UI task reported releasing the shared P0110 lock, a short
manual preflight used the required `adb -s <redacted-pacific-serial>` endpoint to
read the device as Nubia P0110 / `pacific` / Android 16 / SDK 36 and inspect
`dumpsys input`. That input inventory still exposed no `MOUSE`,
`MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL` source. When the formal collector
started immediately afterward, a new shared Android coordination lock had been
created by `trusted-lan-p0110-pr261`, so the collector exited before running
ADB, wrote `blocked_device_coordination_lock`, and kept
`can_close_native_pointer_hid_gate=false`. The gate therefore remains open; no
synthetic ADB pointer input was used or counted as HID confirmation.

- [`evidence/2026-08-22-p0110-native-pointer-hid-after-lock-release/`](evidence/2026-08-22-p0110-native-pointer-hid-after-lock-release/)

A later 2026-08-22 refresh found no shared Android device lock, reached the
P0110 with `adb -s <redacted-pacific-serial>`, and recorded the device identity as
Nubia P0110 / `pacific` / Android 16 / SDK 36. The retained `dumpsys input`
inventory still had no external `MOUSE`, `MOUSE_RELATIVE`, `TOUCHPAD`, or
`TRACKBALL` source, so the collector wrote a `blocked` bundle with
`adb_was_run=true`, zero external mouse devices, and
`can_close_native_pointer_hid_gate=false`. This is the current no-HID-source
gate state and does not close native pointer move/click confirmation.

- [`evidence/2026-08-22-p0110-native-pointer-hid-no-source-refresh/`](evidence/2026-08-22-p0110-native-pointer-hid-no-source-refresh/)

## P0110 rotated host-display readiness follow-up

On 2026-08-20, the connected Nubia P0110 (pacific, Android 16 / SDK 36)
was checked for the rotated physical/virtual host-display
acceptance gate. The target device was online, and origin/main was current at
b9d768e55c75f03cd3cb5d20939576bc8d24ff27, but no real-device acceptance run
was started.

The final readiness check found /tmp/vibe-screen-device-android.lock occupied
by another P0110 task. The current-main Host also could not pass the stable
signed Host preflight because no valid codesigning identity was visible in the
keychain, ad-hoc signing is refused for local device reruns, and a read-only TCC
query returned no Screen Recording or Accessibility rows for
dev.telemachus.display. The target Android package was not installed on the
P0110 at readiness time.

The retained host-display-rotation.json therefore contains no completed
physical or virtual display run, and the offline gate output is status=failed
with missing physical and virtual rotated host-display evidence. This remains a
blocked/readiness record only; the rotated host-display acceptance gate is still
open.

Evidence:

- [`evidence/2026-08-20-p0110-host-display-rotation-blocked/`](evidence/2026-08-20-p0110-host-display-rotation-blocked/)

## P0110 rotated host-display preflight follow-up

On 2026-08-22, the connected Nubia P0110 (pacific, Android 16 / SDK 36,
serial <redacted-pacific-serial>) was checked again after the branch was rebased to
origin/main cb87c6afa94d54a928e873b1bb2d5f4a5d5d5a3b. The initial Android
coordination lock path existed as an empty stale marker with no lsof holder, so
the run recorded that state, acquired a non-blocking fcntl exclusive lock on the
same path, and kept the device lease for limited read-only sampling only.

The device-side USB smoke preconditions were healthy: adb reverse still mapped
tcp:54321, dev.telemachus.display was foreground, the device loopback
connection to 127.0.0.1:54321 was ESTABLISHED, stream_stats stayed around
55-60 fps, decoder dropped frames were 0, and PID-filtered E-level logcat search
found no current app errors. No install, launch, force-stop, reverse change,
host display rotation, or input injection was performed by this run.

The attempt remained blocked before rotated host-display acceptance because the
installed Host could not pass stable signing/TCC preflight: the `Vibe Screen Dev`
codesigning identity was not visible in the current keychain, ad-hoc signing is
refused for local device reruns, and a read-only TCC database query returned
authorization denied. The retained host-display-rotation.json therefore still
contains no completed physical or virtual display run; the offline gate output
is expected to remain status=failed with missing physical and virtual rotated
host-display evidence.

Evidence:

- [`evidence/2026-08-22-p0110-host-display-rotation-preflight-blocked/`](evidence/2026-08-22-p0110-host-display-rotation-preflight-blocked/)

## P0110 Android visual/UI E2E test-entry blocker

On 2026-08-23, a controller-side read-only Android visual/UI sampling run found
the connected Nubia P0110 (pacific, Android 16 / SDK 36, serial
<redacted-pacific-serial>) online with both dev.telemachus.display and
dev.telemachus.display.test installed, but the foreground Activity was the
system permission controller:

```text
com.android.permissioncontroller/.permissionplus.ui.InterceptJumpDialogActivity
```

The retained screenshot shows a firmware/system confirmation dialog asking
whether Vibe Screen should open dev.telemachus.display.test, with Cancel/Open
actions, over the launcher. This blocked the visual/UI E2E entry before the
test reached any Vibe Screen product surface.

This is classified as an external system UI / test-entry blocker, not a Vibe
Screen product UI regression. It does not require a product-code change by
itself. Future test harnesses should pre-acknowledge or bypass this
device-specific confirmation before starting visual/UI E2E, or record the same
permission-controller Activity as a blocked external-system state. This record
does not close any README acceptance gate.

Evidence:

- [`evidence/2026-08-23-p0110-test-entry-system-ui-blocked/`](evidence/2026-08-23-p0110-test-entry-system-ui-blocked/)

## P0110 Android visual/UI E2E test-entry confirmation handled

On 2026-08-23, the connected Nubia P0110 (pacific, Android 16 / SDK 36,
serial <redacted-pacific-serial>) was sampled again from the same system
permission-controller confirmation page. The main Android coordination lock and
soak lock were absent, so this task created the configured Android coordination
lock before issuing explicit serial-targeted ADB commands, then released the
lock after each bounded sample. The older test-specific lock path still existed
with content "pre-existing lock" and was retained as evidence.

The first tap did not hit the confirmation button, and the system dialog
remained focused. The retained UIAutomator XML then identified the positive
button as com.android.permissioncontroller:id/actionPositive with text
"打开" and bounds `[653,2548][1180,2716]`. A second tap at the button center
opened dev.telemachus.display.test/androidx.test.core.app.InstrumentationActivityInvoker$EmptyActivity,
confirming that the blocker belonged to the test-package entry path rather than
the product UI. A direct launch of dev.telemachus.display/.MainActivity then
reached the Vibe Screen product surface and captured the Internet development
preview UI.

This remains an external system UI / test-entry blocker with a documented
workaround. It does not require a product-code change by itself. Future
visual/UI E2E harnesses should detect this permission-controller Activity, tap
the positive action by resource id or bounds, and then explicitly launch the
intended product Activity before judging product UI. This record does not close
any README acceptance gate.

Evidence:

- [`evidence/2026-08-23-p0110-test-entry-system-ui-opened/`](evidence/2026-08-23-p0110-test-entry-system-ui-opened/)

## P0110 Android visual/UI E2E launcher-state update

On 2026-08-23 08:09 +08, a controller-side read-only Android state sample found
the same Nubia P0110 (pacific, Android 16 / SDK 36, serial
<redacted-pacific-serial>) online with the foreground Activity at the Nubia launcher:

```text
com.android.launcher3/com.obric.feature.ObricLauncher
```

The retained screenshot shows the launcher, not the earlier
permission-controller test-entry confirmation and not the Vibe Screen product
surface. The stale test-specific lock path still existed with content
"pre-existing lock". No device command was run for this classification step,
and the main Android coordination lock plus soak lock were absent when the
evidence was prepared.

This is a read-only idle-state update for the next UI/E2E attempt. Future
device interaction should set `REPO`, `EVIDENCE_DIR`, `ANDROID_SERIAL`,
`ADB_SERIAL="${ANDROID_SERIAL}"`, and the coordination-lock path variables,
acquire the Android coordination lock, and use `adb -s "$ADB_SERIAL"` before
launching the intended product or test Activity. This record does not require a
product-code change and does not close any README acceptance gate.

Evidence:

- [`evidence/2026-08-23-p0110-launcher-idle-state/`](evidence/2026-08-23-p0110-launcher-idle-state/)

## P0110 native pointer HID current-base blocked evidence

On 2026-08-23, the native pointer HID gate owner was refreshed on
`origin/main` commit `3d23de133adc4414b4c70430c619fadbe7d90207` using the
connected Nubia P0110 (pacific, Android 16 / SDK 36, serial
<redacted-pacific-serial>). The Android coordination lock was absent, so the collector
was allowed to run serial-scoped ADB reads against that device.

The run did not find any external Android input device with `MOUSE`,
`MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL` source. It therefore wrote
`status=blocked`; the independent summary reports `verdict=blocked` and
`can_close_native_pointer_hid_gate=false`. No Android native pointer
MOVE/BUTTON_PRESS/BUTTON_RELEASE forwarding lines, Host pointer changed/began/
ended injection lines, or visible Mac pointer/click result were captured. This
keeps the README native mouse pointer move/click gate open and does not treat
synthetic ADB pointer input as physical HID mouse evidence.

Evidence:

- [`evidence/2026-08-23-p0110-native-pointer-hid-current-base-blocked/`](evidence/2026-08-23-p0110-native-pointer-hid-current-base-blocked/)

## P0110 rotated host-display current-base follow-up

On 2026-08-23, the current-base owner record was refreshed for the
rotated physical/virtual host-display acceptance gate. The check ran from
current `origin/main` at `305205070adc8f9c3012b811223394bd63be90d4`, after
merged PR #272 had landed and with PR #243 confirmed unrelated to this gate.

The Android coordination lock was absent before sampling. Read-only ADB identity
commands used an explicit redacted serial and identified the connected device as
nubia P0110 / pacific / Android 16 / SDK 36. No install, launch, reverse
mutation, host display rotation, or input injection was performed.

The attempt remained blocked before real rotated host-display acceptance because
the stable signed Host preflight still failed: the expected `Vibe Screen Dev`
codesigning identity was not available to the preflight, and the task could not
prove Screen Recording or Accessibility grants for the signed Host bundle.

The retained `host-display-rotation.json` intentionally contains no completed
physical or virtual run. The offline evidence gate output is `status=failed`,
with missing physical and virtual host-display evidence and missing 90/180/270
coverage for both display kinds. The new current-base aggregate gate also
returns `verdict=blocked`, `can_close_current_base_aggregate=false`, and
`can_claim_real_device_pass=false`. This remains blocked/readiness evidence
only; the rotated host-display acceptance gate is still open.

Evidence:

- [`evidence/2026-08-23-p0110-host-display-rotation-current-base-blocked/`](evidence/2026-08-23-p0110-host-display-rotation-current-base-blocked/)


## P0110 native pointer HID deviceId gate refresh

On 2026-08-27, the native pointer HID gate owner was refreshed again from
current `origin/main` commit `3b2ba11e832a3618eaedfc67f92414b161423a00` plus
the deviceId hardening branch. The connected device was recorded as nubia P0110
/ pacific / Android 16 / SDK 36 with the Android serial redacted in retained
evidence. The collector used the required serial-scoped ADB endpoint, captured
the real device identity and `dumpsys input`, and found no external input
device with a `MOUSE`, `MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL` source.

The collector therefore wrote `status=blocked` and returned `exit_code=2`; the
independent gate summary reports `verdict=blocked` and
`can_close_native_pointer_hid_gate=false`. Re-running the summary through
`make native-pointer-hid-gate` with `--require-pass` is expected to return
non-zero for this blocked bundle; Make may print `Error 1` for the Python gate
process while the outer recorded make target exits non-zero. That is the
fail-closed result for missing hardware, not a successful device confirmation.

This refresh also tightens synthetic-input exclusion. Android forwarding logs
now include the originating `deviceId`, the collector only recognizes native
pointer forwarding lines with a positive `deviceId`, and the summary gate
requires each required event (`move`, `press`, and `release`) to match a
positive device id from the external mouse-like `dumpsys input` inventory.
Synthetic ADB pointer/touch events, including virtual-device events such as
`deviceId=-1`, cannot satisfy `android_forwarding_device_ids_match_external_mouse`
and cannot close the native mouse pointer move/click gate.

Evidence:

- [`evidence/2026-08-27-p0110-native-pointer-hid-current-base-blocked-deviceid/`](evidence/2026-08-27-p0110-native-pointer-hid-current-base-blocked-deviceid/)

## P0110 native pointer HID follow-up blocker

On 2026-08-27, the native pointer HID owner refreshed the PR branch after
`origin/main` remained at `3b2ba11e832a3618eaedfc67f92414b161423a00` and the
branch still contained that commit as its merge base. The connected Android
device was sampled again with a serial-scoped ADB command and recorded as nubia
P0110 / pacific / Android 16 / SDK 36, with the serial redacted from retained
evidence.

No external Android input device with a `MOUSE`, `MOUSE_RELATIVE`, `TOUCHPAD`,
or `TRACKBALL` source was attached. The collector therefore stopped before any
observation window, wrote `status=blocked`, and the independent summary reports
`verdict=blocked` with `can_close_native_pointer_hid_gate=false`. A strict
`make native-pointer-hid-gate` rerun rejected this blocked bundle as expected.

This follow-up does not close the README native mouse pointer move/click gate.
It also does not use synthetic ADB pointer motion as hover/native HID evidence;
the gate still requires forwarded move, press, and release logs whose positive
`deviceId` values match an external mouse-like Android input device.

Evidence:

- [`evidence/2026-08-27-p0110-native-pointer-hid-followup-blocked/`](evidence/2026-08-27-p0110-native-pointer-hid-followup-blocked/)
## P0110 rotated host-display current-base refresh

On 2026-08-27, the current-base owner record was refreshed again from clean
`origin/main` at `3b2ba11e832a3618eaedfc67f92414b161423a00`. Read-only ADB
identity and package probes used an explicit redacted serial and identified the
connected device as nubia P0110 / pacific / Android 16 / SDK 36 with
`dev.telemachus.display` and `dev.telemachus.display.test` installed.

The run remained blocked before any real rotated host-display attempt. The
installed Host bundle had identifier `dev.telemachus.display` and Authority
`Vibe Screen Dev`, but `security find-identity -v -p codesigning` returned zero
valid identities in the current shell, the installed Host lacked source
commit/tree provenance, and the preflight could not prove Screen Recording,
Accessibility, or signing/TCC match. No Android install, launch, ADB reverse
mutation, Host stream, macOS display rotation, or input injection was performed.

The retained `host-display-rotation.json` intentionally contains no completed
physical or virtual runs. The formal evidence gate output is `status=failed`,
with missing physical and virtual host-display evidence and missing 90/180/270
coverage for both display kinds. The current-base aggregate gate returns
`verdict=blocked`, `can_close_current_base_aggregate=false`, and
`can_claim_real_device_pass=false`. This remains blocked/readiness evidence
only; the rotated host-display acceptance gate is still open.

Evidence:

- [`evidence/2026-08-27-p0110-host-display-rotation-current-base-blocked/`](evidence/2026-08-27-p0110-host-display-rotation-current-base-blocked/)
## P0110 rotated host-display current-base readiness refresh

On 2026-08-28, the rotated physical/virtual host-display acceptance gate was
refreshed again from clean `origin/main` at
`27d2b0e493e807ae439fbd43b06b4c2f0ce9c503` before creating the
`codex/rotated-host-display-readiness-2026-08-28` evidence branch. The safety
precheck found no `sfltool` process, and the run did not execute `sfltool
dumpbtm` or any login-item opt-in diagnostic.

The connected Android device was sampled only under the
`/tmp/vibe-screen-android-EP0110PZ0B9110300B.lock` lease, and every ADB command
used the explicit P0110 serial before the public evidence was redacted. The
device identified as nubia P0110 / pacific / Android 16 / SDK 36, the Android
packages were installed, and `adb reverse --list` retained
`UsbFfs tcp:54321 tcp:54321`. No install, launch, force-stop, reverse mutation,
Host start/stop, display rotation, or input injection was performed.

The attempt remained blocked before any real rotated host-display acceptance
run because the strict Host preflight still could not prove the stable
`Vibe Screen Dev` signing identity, Screen Recording, Accessibility, or the
signed Host/TCC match. The Host readiness snapshot also found no process
listening on TCP port `54321`, so the P0110 could not establish a Protocol v1
stream for visual source orientation or inverse-touch probes.

The retained `host-display-rotation.json` therefore intentionally contains no
completed physical or virtual run. The offline evidence gate output remains
`status=failed` with missing physical and virtual host-display evidence and
missing 90/180/270 coverage. The current-base aggregate gate returns
`verdict=blocked`, `can_close_host_display_rotation_acceptance=false`,
`can_close_current_base_aggregate=false`, and
`can_claim_real_device_pass=false`. This is blocked/readiness evidence only;
the rotated host-display acceptance gate is still open.

Evidence:

- [`evidence/2026-08-28-p0110-host-display-rotation-current-base-blocked/`](evidence/2026-08-28-p0110-host-display-rotation-current-base-blocked/)
