# macOS host installation and operations

This runbook covers the current Vibe Screen host. It describes behavior that
exists today, not the complete product vision in the root README.

## Support and prerequisites

- macOS 13 or newer. Apple silicon is the currently locally exercised Host
  class; Intel Macs, additional macOS builds, and distinct display topologies
  require the separate
  [macOS Host compatibility matrix gate](macos-host-compatibility.md) before
  they are listed as supported.
- Android device with the Vibe Screen client installed.
- Android Platform Tools (`adb`) for USB mode.
- A monitor attached during first setup. A headless Mac cannot grant its own
  Screen Recording or Accessibility permissions.

The virtual extension path uses private `CGVirtualDisplay` APIs. It may stop
working after a macOS update and is not suitable for Mac App Store delivery.
The **Current Main Display** path remains the supported fallback. A physical or
dummy display is required when macOS does not expose a usable headless display.
HDR/EDR capture or output must not be claimed from the host until the
[HDR/color acceptance runbook](hdr-color-acceptance.md) has retained hardware
evidence. Current fallback and encoder metadata tests prove SDR fail-closed
readiness only.

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

In Keychain Access, use **Certificate Assistant -> Create a Certificate**, set
the name to `Vibe Screen Dev`, identity type to **Self Signed Root**, and
certificate type to **Code Signing**. Missing this identity blocks rebuilding or
installing a new stable Host, but a read-only preflight can still inspect an
already-installed bundle and report its actual signing/TCC state.

Do not create multiple certificates with the same name. If more than one
`Vibe Screen Dev` identity exists, the build fails closed so the certificate
leaf hash cannot drift accidentally. The local install script writes the current
identity, certificate SHA-1, CDHash, binary SHA-256, designated requirement,
embedded source commit/tree/dirty state, and read-only TCC state to:

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

## Host-backed device gate preflight

Before running any Host-backed Android gate, install the stable local Host and
require the source-bound Host preflight to pass:

```bash
make baseline-macos-dev-install
make baseline-macos-host-preflight
```

`baseline-macos-host-preflight` verifies `/Applications/Vibe Screen.app`, the
`dev.telemachus.display` bundle identity, strict codesign validation, a non
ad-hoc signing identity matching `VIBE_SCREEN_SIGN_IDENTITY` or `Vibe Screen Dev`,
the designated requirement, source commit/tree provenance embedded by
`scripts/package_macos.py`, a clean current source tree, and read-only Screen
Recording plus Accessibility rows in the user's and system TCC databases. It
does not require the signing identity to still be present in the current
Keychain; that requirement belongs to `baseline-macos-dev-install`, where a
missing `Vibe Screen Dev` identity means the Host cannot be rebuilt or
reinstalled as a stable signed binary. `baseline-macos-touch-preflight` is a
compatibility alias for the same check. Both targets exit non-zero if any
installed-bundle, source-provenance, or permission check is missing. When
blocked, keep the generated report as readiness evidence, open **System Settings
-> Privacy & Security -> Screen & System Audio Recording** and
**Accessibility**, grant the installed `/Applications/Vibe Screen.app`, quit and
reopen Vibe Screen, then run the preflight again. A report produced without a
stable installed Host identity, TCC authorization, or matching source provenance
cannot close USB, LAN, Host RSS, native-pointer, stylus, controller, rotation,
login/headless, or compatibility gates.

## Shared Host readiness snapshot

Before a LAN stream/reconnect, controller runtime, Host RSS, native-pointer,
stylus, physical-keyboard, login/headless, or compatibility run consumes a
local Host, collect the shared read-only readiness snapshot for the evidence
directory that will own the run:

```bash
make baseline-macos-host-readiness EVIDENCE_DIR=<evidence-dir>
```

The target writes both files below without launching the Host or mutating the
machine:

```text
<evidence-dir>/host-signing-and-permissions.txt
<evidence-dir>/host-readiness.json
```

`host-readiness.json` records the installed bundle path, signing identity,
codesign provenance, embedded source commit/tree/dirty state, current checkout
commit/tree/dirty state, read-only Screen Recording and Accessibility TCC rows,
TCP listener observation for port `54321`, and whether the bundle carries the
virtual HID entitlement needed by controller runtime acceptance. The command is
read-only: it does not start Vibe Screen, import certificates, change Keychain
settings, modify `TCC.db`, request macOS privacy grants, configure ADB, or touch
Android state.

The `can_start_*` fields are prerequisite flags only. They say whether a run may
begin collecting runtime evidence from the current Host identity; they never
close README-facing runtime gates by themselves. The top-level `status` covers
every reported prerequisite, so it can be `blocked` because the controller-only
virtual HID entitlement is absent while `can_start_trusted_lan_gate` or another
non-controller flag is still true. For each runtime attempt, use the matching
`can_start_*` field and keep the JSON plus text report as readiness evidence.
If that gate's prerequisite flag is false, leave the downstream runtime stages
as not-run and fix the missing signing identity, source provenance, TCC grant,
listener, or gate-specific entitlement before claiming LAN, reconnect, Host RSS,
native-pointer, stylus, controller, login/headless, or compatibility acceptance.

For Android acceptance runs, archive the unified session readiness record before
starting soak, latency, reconnect, or input work:

```bash
make evidence-real-device-gate-preflight \
  EVIDENCE_SERIAL=<adb-serial> \
  REAL_DEVICE_GATE_DIR=<evidence-dir>
```

That runner wraps this Host preflight with the Android device identity, ADB
reverse state, foreground app state, Host TCP listener, and stream telemetry
checks. It writes `<evidence-dir>/real-device-gate.json` and reports
`result=blocked` if the stable signing identity, Screen Recording, Accessibility,
listener, or fresh structured stream telemetry is missing. It does not launch
the Host or modify macOS privacy state.

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

Before scheduling a reboot or headless pass, collect the shared read-only
readiness snapshot:

```bash
make baseline-macos-host-readiness EVIDENCE_DIR=<evidence-dir>
```

The `login_headless` section in `host-readiness.json` records the local blockers
for setup readiness. Exit code 2 means the run is blocked and should be kept as
readiness evidence. A passing readiness snapshot is still only a preflight: it
does not prove login launch after reboot, headless capture, Android rendering,
or recovery from a controlled listener/capture/display failure.

### Acceptance gate matrix

Use this matrix when turning the login-startup/headless path from source-level
support into accepted evidence. Offline tests can prove policy decisions and
bounded retries, but they cannot prove macOS launched the app after a reboot or
that a headless machine still exposes a capturable display.

| Gate | Covered by offline checks | Required integration evidence | Blocking conditions |
| --- | --- | --- | --- |
| Host identity and source provenance | `scripts/package_macos.py` embeds source commit/tree metadata and `baseline-macos-host-readiness` records signing/TCC state. | Identity-signed installed Host whose retained source commit/tree match the evidence `source_commit`, with `source_dirty=false`, current Screen Recording, and Accessibility grants. | Missing stable signing identity, missing source provenance, dirty or mismatched source, stale TCC grant, unreadable TCC stores. |
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

After collecting the retained artifacts, summarize the run in
`macos-startup-recovery-evidence.json` and run the passive gate:

```bash
make phase2-macos-startup-recovery-gate EVIDENCE_DIR="$RUN_DIR"
```

The gate writes `macos-startup-recovery-gate.json`, which can be passed to the
Phase 2 aggregate owner as `PHASE2_LOGIN_HEADLESS`. It exits nonzero and keeps
`can_close_login_headless_gate=false` unless every integration boundary in the
matrix above is backed by retained real-machine evidence. This is expected for
readiness or blocked packages gathered without a rebootable Mac mini, stable
signing/TCC grants, installed Host source provenance matching the evidence
commit, approved Login Item, dummy/headless or Screen Sharing display,
client-rendered first frame, bounded recovery logs, window restoration artifacts,
and a reachable administrator intervention path.

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

The Phase 1 actionable-error owner matrix is tracked in
docs/changes/2026-08-23-actionable-error-states/actionable-error-states.json.
Run make actionable-error-states-gate before changing Host permission, ADB,
listener, capture, virtual-display, LAN, or Internet recovery copy. The gate is
offline only and does not prove Host alert rendering or device acceptance.

When producing README-facing evidence, retain an
`actionable-error-current-base.json` manifest and run:

```bash
make actionable-error-current-base-gate EVIDENCE_DIR=<evidence-dir>
```

This gate validates exact retained artifacts and prevents blocked or not-run
states from being counted as a real-device matrix pass; it exits non-zero unless
the report is a pass. Use `make actionable-error-current-base-owner-record
EVIDENCE_DIR=<evidence-dir>` to refresh a blocked current-base owner report. Do
not induce Screen Recording or Accessibility denial by modifying TCC on a shared
machine; record the environment as blocked unless a safe, stable-signed
denied-permission run is already available.

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

### Trusted LAN evidence preflight

Before a real-device trusted-LAN stream or reconnect run, collect the read-only
preflight package while the Android device is USB-attached and identified by its
exact serial:

```sh
make evidence-trusted-lan-preflight EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=<evidence-dir>
```

The preflight confirms the Nubia P0110/pacific/Android 16 identity, Android
Wi-Fi association, wlan0 IPv4, route to the Mac LAN candidate, and the stable
Host signing/TCC preflight. It does not launch the Host, generate a QR code,
write a pairing token, modify Keychain, reset TCC, or change saved Wi-Fi
credentials. If the JSON reports blocked, keep it as the evidence output and
stop before Host launch, pairing, streaming, reconnect, or latency measurement.
Loopback-only TCP 54321 listeners are not LAN evidence.

### Capture is black, frozen, or unavailable

- Recheck Screen Recording permission and relaunch.
- Switch from Extended Display to Current Main Display.
- Attach a physical or dummy display for a headless Mac.
- After a macOS update, assume the private virtual-display API may have changed
  until verified on that exact release.

`CGPreflightScreenCaptureAccess()` reporting granted is necessary but not
sufficient for ScreenCaptureKit. If logs show `Screen recording permission
granted (CGPreflight)` followed by `SCShareableContent verification OK — 0
displays found` or `SCShareableContent returned 0 displays`, record the run as a
ScreenCaptureKit display-inventory blocker and do not claim that the Host is
listening unless `lsof -nP -iTCP:54321 -sTCP:LISTEN` proves it. Current Main
Display startup attempts the existing `CGDisplayStream` fallback when
ScreenCaptureKit cannot enumerate displays, but a pass still requires a real
listener and rising frame evidence.

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
  TOUCH_RERUN_EXPECTED_HOST_SHA256=<fixed-host-binary-sha256> \
  TOUCH_RERUN_EXPECTED_ANDROID_MANUFACTURER=<manufacturer> \
  TOUCH_RERUN_EXPECTED_ANDROID_MODEL=<model> \
  TOUCH_RERUN_EXPECTED_ANDROID_DEVICE=<codename> \
  TOUCH_RERUN_EXPECTED_ANDROID_RELEASE=<android-release> \
  TOUCH_RERUN_EXPECTED_ANDROID_SDK=<api-level>
```

The preflight must report the expected Host binary SHA-256 and authorized
Screen Recording plus Accessibility for `dev.telemachus.display`. If it reports
`blocked`, keep that JSON as the evidence output and do not reset TCC, reset
Keychain state, clear Android app data, or run a long soak to force the gate.
After a rerun, use `make evidence-touch-rerun-summary EVIDENCE_DIR=<evidence-dir>`
with the same expected Android identity variables to verify that the retained
preflight, instrumentation, Host log, and listen-only event-tap log can close the
touch rerun gate.

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
Run the XCTest toolchain preflight before `swift test` when recording local
MacHost test evidence. It writes `.build/dev-macos-host/xctest-toolchain.txt`
and fails closed with the selected developer directory, Swift path/version, and
`xcodebuild` status when the machine is still using Command Line Tools.

```bash
make baseline-macos-build
make baseline-macos-self-test
make baseline-macos-xctest-preflight
make baseline-macos-test
make baseline-macos-app
```

If the preflight reports `/Library/Developer/CommandLineTools`, install full
Xcode if needed and switch the active developer directory before rerunning the
test gate:

```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
xcodebuild -version
make baseline-macos-test
```

Do not record `make baseline-macos-test` as failed product behavior when this
preflight blocks first; record it as an XCTest toolchain blocker and keep the
affected README gate open until the full-Xcode run executes.

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
