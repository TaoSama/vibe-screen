# macOS host installation and operations

This runbook covers the current Vibe Screen host. It describes behavior that
exists today, not the complete product vision in the root README.

## Support and prerequisites

- Apple silicon Mac running macOS 13 or newer.
- Android device with the Vibe Screen client installed.
- Android Platform Tools (`adb`) for USB mode.
- A monitor attached during first setup. A headless Mac cannot grant its own
  Screen Recording or Accessibility permissions.

The virtual extension path uses private `CGVirtualDisplay` APIs. It may stop
working after a macOS update and is not suitable for Mac App Store delivery.
The **Current Main Display** path remains the supported fallback. A physical or
dummy display is required when macOS does not expose a usable headless display.

## Install a release artifact

1. Download the matching `Vibe-Screen-macos-<version>-<architecture>.zip` and
   the aggregate `SHA256SUMS` file from the release.
2. Verify it before opening:

   ```bash
   grep '  Vibe-Screen-macos-<version>-<architecture>\.zip$' SHA256SUMS \
     | shasum -a 256 -c -
   ```

3. Unzip it and move `Vibe Screen.app` to `/Applications`.
4. Open the app from Finder. Development preview artifacts are not notarized;
   only install an artifact you built or obtained from the project's official
   release channel.

The current bundle identifier is `dev.telemachus.display`. Keep the app at the
same path across upgrades so macOS has the best chance of retaining its privacy
grants.

## Local development Host identity

For iterative Android device reruns, build and install the Host with one stable
local codesigning identity and one stable install path:

```bash
make baseline-macos-dev-install
```

The command uses `VIBE_SCREEN_SIGN_IDENTITY` when it is set, otherwise it uses
the default `Vibe Screen Dev` identity. It refuses ad-hoc signing for local
device reruns because ad-hoc signatures drift across rebuilds and invalidate the
macOS TCC grants. CI and release-preview packaging still pass `--sign-identity -`
explicitly where a throwaway signature is acceptable.

Create or select the stable identity in Keychain Access as a self-signed Code
Signing certificate named `Vibe Screen Dev`, then confirm it is visible to
codesign:

```bash
security find-identity -v -p codesigning | grep '"Vibe Screen Dev"'
```

Do not create multiple certificates with the same name. If more than one
`Vibe Screen Dev` identity exists, the build fails closed so the certificate
leaf hash cannot drift accidentally. The local install script writes the current
identity, certificate SHA-1, CDHash, binary SHA-256, designated requirement, and
read-only TCC state to:

```text
.build/dev-macos-host/host-signing-and-permissions.txt
```

The script does not import certificates, store passwords, update Keychain ACLs,
modify `TCC.db`, run `tccutil`, or grant permissions. If codesign cannot access
the private key, fix the Keychain item ownership/ACL for `/usr/bin/codesign` on
that machine instead of switching to ad-hoc signing.

## First-run permissions

Vibe Screen requests two independent permissions:

- **Screen & System Audio Recording** (called **Screen Recording** on older
  macOS): required for capture.
- **Accessibility**: required for touch-derived pointer gestures, Protocol v1
  keyboard/native-pointer injection, and window migration/restoration. The
  legacy fallback session still does not carry keyboard or native-mouse
  messages.

Grant both in **System Settings → Privacy & Security**, then quit and reopen
Vibe Screen. The app rechecks permission while it is running, but a relaunch is
the most reliable path after a new grant. Never grant Accessibility to an
untrusted build: it can synthesize system-wide input.

## Touch-rerun preflight

Before running the opt-in Android touch-gesture rerun, install the stable local
Host and require the preflight to pass:

```bash
make baseline-macos-dev-install
make baseline-macos-touch-preflight
```

`baseline-macos-touch-preflight` verifies `/Applications/Vibe Screen.app`, the
`dev.telemachus.display` bundle identity, strict codesign validation, a non
ad-hoc signing identity, the designated requirement, and read-only Screen
Recording plus Accessibility rows in the user's TCC database. It exits non-zero
if any check is missing. When blocked, open **System Settings → Privacy &
Security → Screen & System Audio Recording** and **Accessibility**, grant the
installed `/Applications/Vibe Screen.app`, quit and reopen Vibe Screen, then run
the preflight again.

## USB quick start

1. Enable Android developer options and USB debugging, authorize the Mac, and
   connect the device.
2. Verify the exact device identity:

   ```bash
   adb devices -l
   adb -s <serial> shell getprop ro.product.manufacturer
   adb -s <serial> shell getprop ro.product.model
   ```

3. Select **USB** in Vibe Screen, choose **Extended Display** or **Current Main
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
- Rotation is advertised to the client as 0°, 90°, 180°, or 270°. This updates
  display geometry and client orientation; it is not evidence that the Host
  rotated captured source pixels. Rotated physical and virtual host displays
  need their own visual and input acceptance record.
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
→ General → Login Items** and approve Vibe Screen. Registration alone is not
treated as proof that login launch is active.

### Acceptance gate matrix

Use this matrix when turning the login-startup/headless path from source-level
support into accepted evidence. Offline tests can prove policy decisions and
bounded retries, but they cannot prove macOS launched the app after a reboot or
that a headless machine still exposes a capturable display.

| Gate | Covered by offline checks | Required integration evidence | Blocking conditions |
| --- | --- | --- | --- |
| Login item registration state | `DaemonManager` distinguishes enabled, approval-required, unavailable, and unregistered states. | Reboot after enabling **Launch at Login**; capture a timestamped app launch log and System Settings state showing the item is enabled, not approval-required. | Login item awaiting approval, app moved to a different path, ad-hoc rebuild/resign changing macOS privacy identity. |
| Automatic startup policy | `HostStartupPolicy` and `AutomaticLaunchCoordinator` prove auto-start waits for Screen Recording/onboarding and consumes one launch intent once. | After login launch, verify the configured Startup mode starts without user interaction and the Android client can connect/render. | Screen Recording missing or stale, onboarding incomplete outside explicit benchmark mode, no reachable USB/LAN client path. |
| Unattended listener recovery | `UnattendedRecoveryPolicy` proves retry delays of 1, 2, 4, 8, 16, 30, 30, and 30 seconds, and stops after eight attempts. | Force a listener/capture failure during an unattended run; preserve logs showing scheduled retries, no full-speed loop, and either successful restart or bounded exhaustion. | Auto-start disabled, Screen Recording unavailable, interactive/manual run, repeated port conflict, ADB/LAN unavailable. |
| Window restoration on disconnect/failure | `WindowPlacement` tests prove frame mapping and fallback to the main display when the original display is offline. | Move a real focused window to the client display, disconnect or stop the client, and record that it returns to the original frame or main-display fallback. | Accessibility missing/stale, target app lacks standard AX position/size attributes. |
| Headless Mac mini reboot | Startup/display policy self-tests cover decision logic only. | With a monitor attached for setup, reboot, confirm login launch, streaming, and recovery; then repeat with the intended dummy/physical/Screen Sharing display configuration and record display identity plus successful capture. | FileVault/first-login prompt, expired TCC grants, no usable physical/dummy/Screen Sharing display, macOS update changing private virtual-display behavior. |

For login-startup evidence, preserve `~/Library/Logs/Telemachus/telemachus.log`
from before and after the reboot. The accepted record should include the app
launch timestamp, the **Launch at Login** state, the configured Startup mode,
permission state, and the first successful server start or a bounded recovery
exhaustion log. Do not count a manual Finder/Dock launch as login-startup
evidence.

Before a headless run, complete onboarding while a monitor is attached. Record
that Screen Recording is granted, whether Accessibility is granted, and that
`hasCompletedOnboarding` has been set by completing the app onboarding flow.
Then record the exact display setup used for the headless pass: physical
display, dummy plug, or Screen Sharing virtual display, including display UUID
and logical/physical dimensions from the host logs.

For unattended recovery evidence, the trigger must be stated in the evidence
record: listener startup failure, capture stop, client disconnect, selected
display disappearance, or another explicit failure. Keep the log segment that
shows each scheduled retry delay. For display-removal window recovery, record
the original window frame and display, remove or disable that display during the
run, then record the restored frame on the current main display.

Summarize the retained evidence with the fail-closed startup/recovery gate:

```bash
make macos-startup-recovery-gate EVIDENCE_DIR=<evidence-dir>
```

The input `macos-startup-recovery-observations.json` must use explicit boolean
observations. Missing fields default to false, so a readiness preflight, a
manual app launch, or an Android-only reconnect record cannot accidentally close
the macOS login item, automatic startup, headless startup, or unattended
listener recovery gate. Nubia P0110/pacific/Android 16 evidence may support only
the Android reconnect endpoint; it is not macOS login or headless evidence.

## Upgrade and rollback

1. Stop streaming and quit Vibe Screen.
2. Keep the previous ZIP until the new version is verified.
3. Remove the legacy `/Applications/Telemachus.app` if present, then install the
   new `/Applications/Vibe Screen.app`; do not keep both bundles or run from a
   changing Downloads path.
4. Reopen it, verify the displayed version, permissions, display mode, and one
   USB connection.
5. If capture or input stopped after replacement, remove the stale Vibe Screen
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
only on a trusted private network. Current macOS and Android peers protect the
token-admitted LAN session with per-session AES-256-GCM application records;
explicit legacy fallback remains plaintext and must be called out separately if
it is ever used.

### Capture is black, frozen, or unavailable

- Recheck Screen Recording permission and relaunch.
- Switch from Extended Display to Current Main Display.
- Attach a physical or dummy display for a headless Mac.
- After a macOS update, assume the private virtual-display API may have changed
  until verified on that exact release.

### Touch, native input, or window migration does nothing

Recheck Accessibility permission. Remove and re-add the current app if it was
rebuilt, re-signed, or replaced. Input is posted system-wide; test with a
non-sensitive window first. Protocol v1 keyboard and native pointer events are
expected only after the client and host negotiate those capabilities; a legacy
session can still stream and handle touch while rejecting native input.

### Virtual controller is unavailable

The host advertises Protocol v1 controller support only when the running app can
create an `IOHIDUserDevice` gamepad. Development ad-hoc builds normally cannot
do this: they need an Apple identity-signed build with the approved
`com.apple.developer.hid.virtual.device` entitlement in the provisioning
profile. Android production controller forwarding is wired and offline-tested,
but a physical Android controller run proves runtime acceptance only when the
host logs controller availability and a Mac-side test target sees the virtual
controller input. If the physical controller or entitled Host is unavailable,
record a blocked summary with `vibescreen_evidence.controller_runtime` instead
of treating the mapper/protocol tests as a pass.

For a fixed-binary touch rerun, collect the read-only preflight before launching
the opt-in Android gesture driver:

```bash
make evidence-touch-rerun-preflight \
  EVIDENCE_SERIAL=<adb-serial> \
  EVIDENCE_DIR=<evidence-dir> \
  TOUCH_RERUN_EXPECTED_HOST_SHA256=<fixed-host-binary-sha256>
```

The preflight must report the expected Host binary SHA-256 and authorized
Screen Recording plus Accessibility for `dev.telemachus.display`. If it reports
`blocked`, keep that JSON as the evidence output and do not reset TCC, reset
Keychain state, clear Android app data, or run a long soak to force the gate.

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

`make baseline-macos-app` creates a stable-signed local `.app` by default,
versioned ZIP, and SHA-256 file under `.build/release-artifacts/`. Set
`VIBE_SCREEN_SIGN_IDENTITY` to use another existing identity. Passing
`--sign-identity -` directly to `scripts/package_macos.py` creates an ad-hoc
preview artifact and should not be used for iterative device reruns. Public
distribution still requires a project-controlled Developer ID signature and
Apple notarization.

## Known limitations

- Existing-display UUID fallback is implemented and unit/self-tested, but
  selected-display hot-plug still needs a real streaming integration run.
  Mirror mode still depends on the private virtual-display API. Runtime symbol
  presence is diagnostic only; create/apply/online/capture must all succeed on
  the exact macOS build before the feature is accepted.
- Protocol v1 keyboard and native-pointer forwarding are implemented in the
  current host/client path, with keyboard and scroll verified on device. Native
  mouse move/click still require physical Android HID-mouse confirmation.
- Controller protocol models, Android mapping/state, Android production event
  forwarding, Host state machines, and Mac virtual-gamepad injection are
  source- and self-tested. Mac virtual-gamepad runtime acceptance still requires
  an identity-signed, entitled build and physical Android controller evidence.
- The legacy product session has no keyboard or native-mouse message entry
  point. Touch-derived click, drag, right-click, scroll, and zoom are present
  only as compatibility behavior.
- Adaptive bitrate/resolution policy, external glass-to-glass latency, Xiaomi
  12 acceptance, two-hour Phase 1 soak, and eight-hour Phase 2 soak remain
  unverified.
- The current development ZIP is not notarized. CI preview artifacts are ad-hoc
  signed; local device-rerun builds should use the stable development identity.
