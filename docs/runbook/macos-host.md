# macOS host installation and operations

This runbook covers the current Telemachus host shipped from the Vibe Screen
baseline. It describes behavior that exists today, not the complete product
vision in the root README.

## Support and prerequisites

- Apple silicon Mac running macOS 13 or newer.
- Android device with the Telemachus client installed.
- Android Platform Tools (`adb`) for USB mode.
- A monitor attached during first setup. A headless Mac cannot grant its own
  Screen Recording or Accessibility permissions.

The virtual extension path uses private `CGVirtualDisplay` APIs. It may stop
working after a macOS update and is not suitable for Mac App Store delivery.
The **Current Main Display** path remains the supported fallback. A physical or
dummy display is required when macOS does not expose a usable headless display.

## Install a release artifact

1. Download the matching `Telemachus-macos-<version>-<architecture>.zip` and
   `.sha256` file from the release.
2. Verify it before opening:

   ```bash
   shasum -a 256 -c Telemachus-macos-<version>-<architecture>.sha256
   ```

3. Unzip it and move `Telemachus.app` to `/Applications`.
4. Open the app from Finder. Development artifacts are ad-hoc signed and are
   not notarized; only install an artifact you built or obtained from the
   project's official release channel.

The current bundle identifier is `dev.telemachus.display`. Keep the app at the
same path across upgrades so macOS has the best chance of retaining its privacy
grants.

## First-run permissions

Telemachus requests two independent permissions:

- **Screen & System Audio Recording** (called **Screen Recording** on older
  macOS): required for capture.
- **Accessibility**: required only for touch-derived pointer gestures and
  window migration/restoration. The legacy session does not yet carry
  keyboard or native-mouse messages.

Grant both in **System Settings → Privacy & Security**, then quit and reopen
Telemachus. The app rechecks permission while it is running, but a relaunch is
the most reliable path after a new grant. Never grant Accessibility to an
untrusted build: it can synthesize system-wide input.

## USB quick start

1. Enable Android developer options and USB debugging, authorize the Mac, and
   connect the device.
2. Verify the exact device identity:

   ```bash
   adb devices -l
   adb -s <serial> shell getprop ro.product.manufacturer
   adb -s <serial> shell getprop ro.product.model
   ```

3. Select **USB** in Telemachus, choose **Extended Display** or **Current Main
   Display**, then click **Start**.
4. The host configures `adb reverse tcp:54321 tcp:54321` and brings the Android
   client to the foreground. If automatic setup fails, run:

   ```bash
   adb -s <serial> reverse tcp:54321 tcp:54321
   adb -s <serial> shell am start \
     -n dev.telemachus.display/.MainActivity \
     --ez auto_connect true
   ```

When more than one ADB device is visible, always pass `-s <serial>` or choose
the desired serial in host settings.

## Display and window behavior

- **Extended Display** creates a private virtual display at the selected
  logical size, refresh rate, and optional HiDPI scale.
- **Current Main Display** captures the display macOS currently considers
  primary and aspect-fits it into the requested stream bounds.
- **Choose Existing Display** persists the display UUID, resolves its current
  runtime ID, and falls back to the current main display while the chosen
  display is unplugged without forgetting the selection.
- **Mirror Main Display** creates a private client display and configures it as
  a mirror of the current main display.
- Rotation is advertised to the client as 0°, 90°, 180°, or 270°.
- **Move Focused Window to Client Display** in the menu bar moves the current
  accessible window while preserving its relative placement.
- **Return Moved Windows** restores windows to their original display and
  frame. If that display is offline, it maps and clamps them onto the current
  main display. The same restore runs when the client disconnects, the server
  stops, startup fails, or the app terminates.

Window migration cannot move apps that do not expose standard Accessibility
window position/size attributes. Those failures are logged and do not prevent
streaming.

## Login startup and headless Mac mini

Perform these steps once with a monitor attached:

1. Grant Screen Recording and Accessibility.
2. Enable **Launch at Login**.
3. Enable **Start streaming automatically** and choose USB or Wireless startup.
4. Start a stream once and verify the Android client renders it.
5. Reboot and verify login startup before removing the monitor.

The host keeps the listener alive across normal client disconnects. If the
listener itself fails, unattended mode retries up to eight times with bounded
1, 2, 4, 8, 16, 30, 30, and 30 second delays. It never loops at full speed.
First login, FileVault unlock, macOS updates, expired TCC grants, and a machine
with no usable physical/dummy/Screen Sharing display still require local or
remote administrator intervention.

If macOS reports that the login item requires approval, open **System Settings
→ General → Login Items** and approve Telemachus. Registration alone is not
treated as proof that login launch is active.

## Upgrade and rollback

1. Stop streaming and quit Telemachus.
2. Keep the previous ZIP until the new version is verified.
3. Replace `/Applications/Telemachus.app` with the new app; do not run it from
   a changing Downloads path.
4. Reopen it, verify the displayed version, permissions, display mode, and one
   USB connection.
5. If capture or input stopped after replacement, remove the stale Telemachus
   entry from the relevant Privacy & Security pane, add the new app again, and
   relaunch. Toggling the old entry off/on may preserve a stale code identity.

Settings are stored in macOS user defaults and are not removed by replacing the
app. To roll back, quit the new version and restore the previous verified app
at the same path.

## Troubleshooting

### ADB is missing or reverse forwarding disappeared

```bash
command -v adb
adb devices -l
adb -s <serial> reverse --list
adb -s <serial> reverse tcp:54321 tcp:54321
```

The running host checks the reverse rule periodically and recreates it when a
selected device is present.

### Port 54321 is already in use

```bash
lsof -nP -iTCP:54321 -sTCP:LISTEN
```

Quit the conflicting process or choose another port in both host and client.
USB mode binds loopback only. Wireless mode listens on the LAN and must be used
only on a trusted private network; the video/input session is not end-to-end
encrypted in this baseline.

### Capture is black, frozen, or unavailable

- Recheck Screen Recording permission and relaunch.
- Switch from Extended Display to Current Main Display.
- Attach a physical or dummy display for a headless Mac.
- After a macOS update, assume the private virtual-display API may have changed
  until verified on that exact release.

### Touch or window migration does nothing

Recheck Accessibility permission. Remove and re-add the current app if it was
rebuilt, re-signed, or replaced. Input is posted system-wide; test with a
non-sensitive window first.

### Logs and diagnostics

Runtime logs rotate at 1 MiB and are stored with owner-only permissions:

```text
~/Library/Logs/Telemachus/telemachus.log
~/Library/Logs/Telemachus/telemachus.log.1
```

Review logs before sharing them. Device names, addresses, window titles, and
other environment details may be sensitive.

## Build and package from source

A release build needs Swift 6-compatible Apple tools. XCTest additionally
requires full Xcode to be selected with `xcode-select`; Command Line Tools
alone can build the executable but cannot run this package's XCTest suite.

```bash
make baseline-macos-build
make baseline-macos-self-test
make baseline-macos-test
make baseline-macos-app
```

`make baseline-macos-app` creates an ad-hoc signed `.app`, versioned ZIP, and
SHA-256 file under `.build/release-artifacts/`. Public distribution still
requires a project-controlled Developer ID signature and Apple notarization.

## Known limitations

- Existing-display UUID fallback is implemented and unit/self-tested, but
  selected-display hot-plug still needs a real streaming integration run.
  Mirror mode still depends on the private virtual-display API. Runtime symbol
  presence is diagnostic only; create/apply/online/capture must all succeed on
  the exact macOS build before the feature is accepted.
- Protocol v1 integration is in progress; legacy clients do not receive all
  negotiated session and input capabilities.
- The legacy product session has no keyboard or native-mouse message entry
  point. Touch-derived click, drag, right-click, scroll, and zoom are present;
  keyboard/native-mouse forwarding is not an implemented product capability.
- Adaptive bitrate/resolution policy, external glass-to-glass latency, Xiaomi
  12 acceptance, two-hour Phase 1 soak, and eight-hour Phase 2 soak remain
  unverified.
- The current development ZIP is ad-hoc signed and not notarized.
