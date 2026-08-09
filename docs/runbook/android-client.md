# Android client operation and acceptance

This runbook covers the runnable legacy Android client. It distinguishes local
client behavior from controls that still require a negotiated host protocol.

## Device ownership gate

Before any ADB command, check whether a coordinated device run owns the target:

```bash
test ! -e /tmp/vibe-screen-device-soak.lock
test ! -e /tmp/vibe-screen-device-android.lock
```

If either file exists, do not connect, install, launch, force-stop, change ADB
reverse mappings, probe the media port, or start a competing Mac host. Wait for
the owner to remove the lock. A concurrent install or port probe invalidates a
soak window even if the stream later recovers.

After coordination grants a short Android lease, atomically create
`/tmp/vibe-screen-device-android.lock` before the first ADB command. Remove it
immediately after stopping the test client/server and report the release so
other tasks can proceed.

## Offline gate

Run this without a device or Mac host:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug auditReleaseDependencies
```

The JVM suite covers Fit/Fill corners through all four rotations, viewport and
decoder-surface dimensions, common physical keyboard-to-HID sequences,
session-generation/capability gating, Camera settings-return policy, bounded
outbound ordering, typed connection guidance, reconnect backoff, framing, and
reliability. This proves code paths and packaging only; it is not device
acceptance.

## Install after acquiring the device

Resolve and record the exact device identity before changing it. Always pass
the explicit serial:

```bash
adb connect DEVICE_HOST:5555
adb -s DEVICE_HOST:5555 devices -l
adb -s DEVICE_HOST:5555 shell getprop ro.serialno
adb -s DEVICE_HOST:5555 shell getprop ro.product.manufacturer
adb -s DEVICE_HOST:5555 shell getprop ro.product.model
adb -s DEVICE_HOST:5555 shell getprop ro.build.fingerprint
adb -s DEVICE_HOST:5555 shell getprop ro.build.version.sdk
adb -s DEVICE_HOST:5555 install -r -t \
  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
```

The lease-controlled endpoint has previously identified as a
Nubia P0110, not Xiaomi 13 (2211133C). Recheck rather than assuming its identity.

## Viewport checks

Open the in-stream settings button:

1. Confirm **Fit** preserves the entire frame and letterboxes as needed.
2. Confirm **Fill** crops evenly and touches at the visible edges map inside
   the cropped video, not to the hidden frame edge.
3. Cycle rotation through Follow Mac, 90°, 180°, and 270°; tap all four corners
   after each change and correlate the Android event with the Mac pointer.
4. Disconnect and reconnect; confirm scale and rotation preferences persist.
5. Confirm the UI says the legacy stream is selected on the Mac. Do not report
   Android display enumeration or selection as implemented.

Connected windows use `FLAG_SECURE`, so ADB screenshots of the stream may be
black. Use diagnostic logs plus direct observation or an external camera.

## Input matrix

Use a non-sensitive Mac test window and grant Accessibility to the exact host
binary. Record Android diagnostic logs and the visible Mac result for each:

| Input | Expected legacy behavior |
| --- | --- |
| tap / double tap | left click / double click |
| long press | right click |
| long press then move | left-button drag |
| two-finger parallel move | scroll |
| two-finger distance change | command-scroll zoom |
| external mouse wheel | two-finger scroll adapter |
| external secondary button | long-press right-click adapter |
| physical keyboard / shortcut | compatibility message; no bytes sent |

ADB event injection can exercise Android dispatch but does not prove a physical
mouse or keyboard. Physical-peripheral acceptance requires the named hardware
and a visible Mac-side result. Native hover, pointer buttons, stylus fields,
keyboard forwarding, and shortcuts remain blocked until both applications use
a negotiated input channel.

## Permissions and lifecycle

- USB mode must work without Camera permission.
- For LAN QR pairing, exercise allow, first denial, permanent denial, the
  **Open Settings** recovery action, and a successful retry.
- Background the app while connected. New retry attempts and input must pause;
  keep-screen-on clears but screenshot protection remains. Return to the app
  and confirm the live session requests a keyframe or a disconnected session
  resumes bounded retry.
- Record Host PID, disconnect/admission epochs, first output frame, and elapsed
  recovery time. A build or lifecycle callback log alone is not a reconnect
  pass.

## Actionable failure checks

Exercise a missing Mac app, missing ADB reverse, unreachable route, timeout,
camera denial, incompatible message/display configuration, outbound
backpressure, and decoder failure. Each state must identify the failed layer
and tell the user what to do next. Retryable transport failures use bounded
automatic recovery; non-retryable protocol/input failures must stop the loop
and show a concrete recovery action.

Collect the private log with:

```bash
adb -s DEVICE_SERIAL exec-out run-as dev.telemachus.display sh -c \
  'cat files/diag.log.old 2>/dev/null; cat files/diag.log 2>/dev/null'
```

Never include pairing tokens, personal screen content, Wi-Fi credentials, or
public addresses in committed evidence.
