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
| reconnect/errors | per-session generation gates all client/decoder callbacks; typed retryability preserves failure reasons and stops protocol-error loops; wireless post-connect startup has exactly-once socket/stream ownership | stale/no-display endpoint and synthetic cold reconnect passed on device; stale-generation, ready-session, invalid-local-credential, and post-auth startup-failure paths pass on JVM |
| permissions/lifecycle | Camera permission is re-evaluated after returning from Settings; background pauses input/retries and keep-awake, foreground resumes/rekeys | original camera deny/settings launch passed on device; Settings-return state machine passes on JVM; post-review device rerun pending |
| outbound input | bounded single writer reserves recovery capacity, uses non-blocking atomic ingress under lock contention, coalesces MOVE/ping/keyframe, preserves admitted touch-boundary FIFO, gracefully drains releases, and fails closed only on true capacity saturation | contention/capacity/close-race/order/write-failure/graceful-close tests pass on JVM; physical-peripheral device check pending |

No unsupported keyboard, pointer, or display-selection bytes are added to the
legacy wire format. A compatible negotiated application session remains the
gate for those controls.

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

The same APK was installed on Xiaomi 13 `bac5b092` at
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
that records both display kinds:

1. Rotate an existing physical Mac display, stream it over a Protocol v1 USB or
   LAN session, capture visual source orientation, corner/center input mapping,
   stable stream state, no session teardown, and restoration of the original
   macOS rotation.
2. Repeat the same probes for a virtual display in its rotated host-display
   state.
3. Keep client rotation as an explicit client-local setting, usually Follow Mac
   or 0 for the host-display run, and do not treat the existing client-local
   90/180/270 matrix as host-display rotation evidence.
4. Record retained artifacts for device identity, before/rotated host display
   snapshots, Android screenshot, touch matrix, Host log, and Android logcat.

Summarize the retained evidence in a JSON file and run the offline gate. This
command validates the record only; it does not rotate displays, start the Host,
touch ADB, or perform device actions:

```bash
python3 -m tools.vibescreen_evidence.host_display_rotation_gate \
  docs/changes/2026-08-05-phase-1-android-client/evidence/<run>/host-display-rotation.json \
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
was then installed on `bac5b092`. With the Host pinned to that serial and
configured for `extended`, a clean Host/client launch created virtual display
38 and advertised it first: `selected=38`, `2000x1200`, `config epoch=1`.
The control hierarchy showed `Vibe Screen Virtu…` plus an enabled `Window
actions` button. The final build repeated the exact TextEdit move/return
geometry `(181,102) 586x488 -> (1846,179) 586x488 -> (181,102) 586x488`,
and force-stopping Android again produced `Restored 1 moved window(s)` before
the next cold launch returned directly to display 38 at about 60 FPS.

Two connected fuxi devices can otherwise fight over the Host's single-client
listener. The rerun isolated `bac5b092`, stopped the client on `8a023e3a`, and
set `Telemachus_adbDeviceSerial=bac5b092`; without that isolation, each new
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
