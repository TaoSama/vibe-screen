# 2026-08-21 Nubia P0110 USB smoke readiness

This record covers a readiness attempt for the connected Nubia P0110
(pacific) device, running Android 16 / SDK 36. It is P0110/pacific evidence
only; it is not Xiaomi 13/fuxi evidence. The exact device serial is retained
in the raw evidence files.

## Verdict

SUPERSEDED readiness blocker. At this collection time, the device-side
preconditions were present, but the USB smoke could not safely start because the
running macOS Host never opened the required 127.0.0.1:54321 listener after a
low-risk restart. The Host logs show the server start path was reached, Screen
Recording preflight passed, and ADB reverse/client launch were attempted, but
ScreenCaptureKit returned zero shareable displays and the Host failed before
creating the TCP listener.

This historical readiness record does not claim a successful USB connection,
first frame, decoder output, reconnect, input forwarding, latency, or soak
result. A later 2026-08-21 22:35 Asia/Shanghai short USB smoke on the same
Nubia P0110/pacific device did observe Host LISTEN, adb-to-Host ESTABLISHED
connections, stream telemetry, and zero decoder drops; see
../2026-08-21-nubia-p0110-root-usb-smoke/README.md. That later run clears the
specific Host-listener/connection-start blocker for a short smoke, but it is
not a full USB acceptance pass.

## 2026-08-21 controller refresh

After PR #168 merged, the main controller repeated the device-side USB
preflight on the same Nubia P0110/pacific Android 16 device. The device-side
preconditions are no longer blockers for this readiness slice: adb reverse was
configured successfully, adb reverse --list reported UsbFfs tcp:54321
tcp:54321, and dev.telemachus.display/.MainActivity was foreground with PID
11385 and mCurrentFocus pointing at dev.telemachus.display.MainActivity.

At that refresh, the remaining blocker was the macOS Host side. lsof -nP
-iTCP:54321 -sTCP:LISTEN still returned no listener, so the USB smoke still
could not be started in that pass. A read-only local rerun of make
baseline-macos-touch-preflight also failed with exit 2 because codesign identity
'Vibe Screen Dev' was not found in the keychain. Existing TCC rows for the
installed signed Host were recorded as allowed in the original evidence, but a
stable source-bound Host rerun still requires restoring the Vibe Screen Dev
identity so Screen Recording and Accessibility grants remain tied to a stable
signing identity.

## 2026-08-21 22:35 short-smoke follow-up

The controller later ran a 60-second root-orchestrated USB smoke on the same
Nubia P0110/pacific Android 16 device. In that run, adb reverse was present,
the installed Host PID 92943 listened on 127.0.0.1:54321, and every sample from
5 seconds through 60 seconds showed an adb-to-Host ESTABLISHED connection.
Filtered logcat retained 9 VibeScreenTelemetry stream_stats events with FPS
56.97-60.22 and Mbps 0.36-0.37, plus decoder stats with dropped=0 and no FATAL
or AndroidRuntime crash. The evidence is recorded in
../2026-08-21-nubia-p0110-root-usb-smoke/README.md.

The follow-up is intentionally narrow: it proves a short USB stream smoke and
removes the prior current blocker that Host 54321 did not listen or no
connection could start. It does not close long soak, host RSS no-growth,
external-camera latency, input-latency, Accessibility/input, UI foreground,
lifecycle, native pointer HID, physical stylus, controller runtime, LAN,
Internet, login-startup, or headless Mac gates. The screenshot and dumpsys
activity top showed the Nubia launcher in the foreground while the app process
continued streaming in the background, so UI/lifecycle remains a follow-up.

## Recorded facts

- Repository commit: cc26a84c829016fa61c721f73a128284fdf64f92, matching
  origin/main at collection time.
- Worktree: `<WORKTREE_ROOT>`; the exact collection path is retained in
  `readiness.json` as `<repo-root>` to avoid publishing machine-specific
  reproduction paths.
- Device: nubia P0110, codename/product pacific, Android 16, SDK 36, serial
  `<DEVICE_SERIAL>`. The exact serial is retained in raw evidence files.
- Device state: `adb -s "$DEVICE_SERIAL" get-state` returned device;
  `adb -s "$DEVICE_SERIAL" reverse --list` contained UsbFfs tcp:54321 tcp:54321.
- Android package: dev.telemachus.display; the app process was present as PID
  32263 during final readiness capture.
- Host process: /Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen was
  running as PID 66481 after the app restart, but lsof -nP -iTCP:54321
  -sTCP:LISTEN returned no listener.
- Installed Host signing/TCC: /Applications/Vibe Screen.app is signed with
  Vibe Screen Dev, bundle id dev.telemachus.display, and system TCC rows show
  Screen Capture and Accessibility authorized.
- Source-bound Host preflight: python3 scripts/macos_dev_host.py preflight
  failed because the current keychain exposes zero valid code-signing
  identities, so Vibe Screen Dev could not be resolved for a stable
  source-bound install/preflight.

## Historical blocker

At this collection time, the active blocker was Host listener and stable Host
signing readiness, not USB device reachability or Android foreground state. The
later short-smoke follow-up above supersedes the Host-listener/connection-start
part of this blocker for a short USB smoke only.
Recent Host log lines show repeated automatic start attempts:

    Screen recording permission granted (CGPreflight)
    startServer() invoked. Check permission: true
    setupADBReverse() invoked for port 54321...
    Android client launched for automatic USB connection
    SCShareableContent returned 0 displays: []
    Virtual display 1 not found in attempt 1, retrying...
    Unattended startup failed: Virtual display with ID 1 not found after 5 attempts

The same failure reproduced after switching the persisted display source to
currentMain: logs changed to Using existing main display 1, but
SCShareableContent returned 0 displays: [] and Virtual display with ID 1 not
found after 5 attempts still prevented the listener from appearing. The
temporary displaySource preference change was restored to selectedDisplay after
the readiness capture; see restored-host-defaults.txt.

Because the Host never listened on 54321 during this readiness capture, the E2E
smoke was not run in this record. The later 22:35 short smoke should be used for
the current USB stream-start status, with its explicit 60-second scope and
UI/lifecycle caveats.

## Files

- readiness.json - machine-readable blocked readiness summary.
- device-info.json, device-state.txt, environment.txt - device and local
  environment identity; Android APK signing identity and install timestamp were
  not collected for this readiness record.
- host-preflight-console.txt, codesign-identities.txt,
  installed-host-identity.txt, tcc-dev-telemachus-display.txt - signing,
  installed Host, and TCC evidence.
- current-source-host-build.txt, android-build.txt, artifact-sha256.txt -
  current-source build and artifact hashes.
- final-readiness-state-v4.txt, live-state-after-stale-lock.txt,
  final-cleanup-state.txt - listener/process/device/reverse snapshots.
- host-log-focused.txt, host-log-tail.txt - Host log excerpts explaining the
  listener blocker.
- Android logcat was sampled during the readiness check, but the captured tail
  was not retained because it contained unrelated third-party application
  traffic and no Vibe Screen connection evidence could be claimed while the
  Host listener was absent.
- stale-lock-cleanup.txt, device-lock.txt, device-lock-active.txt,
  device-lock-released.txt, final-lock-status-v4.txt - device lock handling
  records; the final lock status demonstrates the lock was released after the
  later holder PID `49848` acquired it.
- restored-host-defaults.txt - local Host displaySource cleanup after the
  currentMain fallback check.

## Re-run

Use the same device identity and serial, and keep every adb command explicit:

    cd <WORKTREE_ROOT>
    set -euo pipefail
    export DEVICE_SERIAL=<DEVICE_SERIAL>
    security find-identity -v -p codesigning | grep '"Vibe Screen Dev"'
    python3 scripts/macos_dev_host.py preflight --install-path "/Applications/Vibe Screen.app"
    osascript -e 'quit app "Vibe Screen"' || true
    open "/Applications/Vibe Screen.app"
    for attempt in $(seq 1 30); do
      if lsof -nP -iTCP@127.0.0.1:54321 -sTCP:LISTEN; then
        break
      fi
      sleep 1
    done
    lsof -nP -iTCP@127.0.0.1:54321 -sTCP:LISTEN
    adb -s "$DEVICE_SERIAL" reverse tcp:54321 tcp:54321
    adb -s "$DEVICE_SERIAL" shell am start -S -W -n dev.telemachus.display/.MainActivity --ez auto_connect true

If SCShareableContent still returns zero displays, resolve the macOS display
enumeration/TCC/runtime state first and rerun only after lsof shows the Host
listening on 127.0.0.1:54321.
