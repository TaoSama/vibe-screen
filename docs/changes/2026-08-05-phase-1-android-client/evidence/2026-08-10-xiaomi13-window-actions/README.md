# Xiaomi 13 window actions and recovery

Date: 2026-08-10  
Device: Xiaomi 13 (`2211133C`, `fuxi`, Android 16)  
ADB serial used for this run: `bac5b092`  
Transport: USB through `adb reverse tcp:54321 tcp:54321`  
Application name on both platforms: `Vibe Screen`

## Scope

This record verifies the Protocol v1 `CAPABILITY_HOST_ACTIONS` path from the
Android control capsule to the macOS `WindowRecoveryManager`. The fixed action
ids are `move-window` and `return-windows`. It also covers the display-lifecycle
issues found while establishing a meaningful virtual-display target.

This was an interactive regression run, not a soak. No validation interval in
this pass exceeded 30 minutes. The historical two-hour stream result and its
failed host-RSS no-growth gate remain unchanged and open.

## Fixes exercised

- A `HostActionCatalog` may arrive before the display list promotes the Android
  session binding. The client now re-evaluates the cached catalog after
  capability promotion; the UI hierarchy then contains an enabled
  `controlHostActionsButton` with content description `Window actions`.
- A newly created virtual display can return `CGError 1001` while WindowServer
  is settling it. Cold start now uses the same bounded registration/mirror
  retry as runtime switching and continues only when the display is confirmed
  not mirrored. Display `34` registered, capture started, TCP listened, and the
  device negotiated Protocol v1 instead of entering unattended recovery.
- The managed virtual display remains alive while a physical display is being
  captured. The physical -> virtual -> physical -> virtual sequence created
  display `35` once, then logged `Reusing managed virtual display 35 for
  capture switch`; no `offline display 35` rejection occurred.

The final source also orders the current capture first in `ListDisplays`, while
`isPrimary` retains its macOS-main-display meaning, and uses the configured
2000x1200 geometry for a not-yet-created virtual entry. Android starts that
first entry rather than unconditionally replacing an active virtual stream with
the primary Mac display. Later Android follow-up changes also correlate applied
video preferences with an actual client request, preserve saved preferences on
ordinary connection/display configs, show actionable HostAction rejection
reasons, and ignore duplicate/late action results without dropping the stream.
The final APK reinstall/cold-start rerun below closes active-first selection and
the HostAction happy path on the exact clean artifact. Rejection-copy and
duplicate/late-result handling remain offline-covered rather than claimed as
device evidence.

## Window geometry proof

The virtual client display was online at:

```text
display35 bounds=(1512.0, 0.0, 2000.0, 1200.0) online=1
```

After revealing the Android controls, TextEdit was activated again so the
touch used to reveal the controls could not steal Mac focus. The focused
TextEdit window then moved into display 35 and returned to its exact original
frame:

```text
before-valid-move pos=181,102 size=586x488
after-valid-move pos=1846,179 size=586x488
after-return pos=181,102 size=586x488
```

The Host and Android records agreed:

```text
Moved focused window to client display 35 for client request
Restored 1 moved window(s)
capsule invokeHostAction id=move-window
onHostActionResult: accepted=true reason=
capsule invokeHostAction id=return-windows
onHostActionResult: accepted=true reason=
```

For disconnect recovery, the window was moved again, the Android process was
force-stopped, and the Host restored it automatically:

```text
before-disconnect pos=1846,179
after-disconnect pos=181,102
Moved focused window to client display 35 for client request
Restored 1 moved window(s)
```

During the accepted move/return sequence the pipeline returned to about 60 FPS
with zero sustained dropped frames. Transient display reconfiguration frames
are not treated as soak evidence.

## Final clean APK rerun

The clean APK SHA-256 was
`66eaa6f7175d102dad55a94f1c983aaff3ffbcc32365c581c222e7ec46b7ed71`.
It was installed on `bac5b092` at `2026-08-10 22:00:21 +08:00`.

After pinning the Host ADB target to `bac5b092` and cold-starting both sides
with `displaySource=extended`, the Host created virtual display `38`. The
first client directory and configuration were:

```text
onDisplaysAvailable: count=3 selected=38
38:Vibe Screen Virtual (扩展屏):2000x1200:primary=false
1:Built-in Retina Display:1512x982:primary=true
2:DELL U2723QE:1920x1080:primary=false
onVideoConfiguration: 2000x1200 @ 0° epoch=1
```

The control hierarchy exposed `Vibe Screen Virtu…` and an enabled
`controlHostActionsButton` with content description `Window actions`. The
final artifact repeated the move/return proof:

```text
before=181,102 586x488
after=1846,179 586x488
returned=181,102 586x488
capsule invokeHostAction id=move-window
onHostActionResult: accepted=true reason=
Moved focused window to client display 38 for client request
Restored 1 moved window(s)
```

A second move followed by `am force-stop dev.telemachus.display` logged another
`Restored 1 moved window(s)`. Relaunch opened a new session directly on display
`38`, configuration `2000x1200`, and returned to approximately 60 FPS.

## Excluded attempts

An earlier attempt revealed the control bar after activating TextEdit. That
video tap was also forwarded to macOS and changed the focused application, so
the Host correctly accepted an action for a different focused window. A
same-display move to display `1` likewise produced no geometry change. Neither
attempt is counted as window-migration acceptance; only the display-35 geometry
sequence above closes this gate.

## Offline gates

The final working tree passed:

- Android `testDebugUnitTest`, `lintDebug`, and `assembleDebug`;
- `make protocol` (Buf format/lint/build/breaking plus 18 contract tests);
- macOS release build plus host, transport, reliability, Protocol v1, and video
  encoder self-tests;
- 79 evidence-tool unit tests with `PYTHONPATH=tools`.

Full Xcode XCTest was not rerun locally because this machine exposes Command
Line Tools rather than a full Xcode toolchain. The historical CI XCTest result
remains the authoritative complete suite record.

The final signed macOS bundle was installed at `/Applications/Vibe Screen.app`,
passed deep signature verification, retained Screen Recording permission, and
listened on `127.0.0.1:54321`. The final Android APK was installed and its
active-first extended cold start, action-menu visibility, move/return, and
disconnect recovery were re-verified as described above. Video-preference
confirmation correlation and HostAction rejection/replay handling remain
covered by the final offline suite; this rerun did not fabricate negative-path
device evidence for them.
