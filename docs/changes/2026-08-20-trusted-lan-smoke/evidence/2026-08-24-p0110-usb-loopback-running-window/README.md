# Nubia P0110 USB loopback running-window observation

Date: 2026-08-24
Target branch: `codex/trusted-lan-p0110-preflight-20260824`
Observed commit: `d2b9698fbcac161e425d7288b29662bab1887189`
Origin/main at collection: `6bcf185094bb2a9c77abb7c642833b7ac03b5835`
Target device serial: `<device-serial>`

## Scope

This package captures the already-running Host and Android client window after
the trusted-LAN preflight remained blocked. It is a read-only USB/loopback
observation, not trusted-LAN evidence. It did not install or launch the Android
app, did not start or stop the Host, did not clear logcat, did not alter ADB
reverse rules, did not change Wi-Fi settings, and did not inject input.

## Result

`usb-live-smoke.json` records `verdict=pass` for the narrow USB live-stream
smoke scope only:

- Device identity: nubia P0110 / pacific / Android 16 / SDK 36.
- Android package: `dev.telemachus.display`, PID `15457`, foreground
  `dev.telemachus.display/.MainActivity`.
- Transport boundary: ADB reverse `UsbFfs tcp:54321 tcp:54321`.
- Host listener: `/Applications/Vibe Screen.app` PID `22385` listening only on
  `127.0.0.1:54321`.
- Host log: `Client connected via loopback (USB)`, `Protocol v1 selected`,
  continuing `Capture source (SCStream)` samples, and continuing `Pipeline`
  samples near 60 FPS.
- Android logcat: current PID `15457` emitted `first_frame_received`,
  `first_output_frame`, 85 `stream_stats` events, and decoder output counters.
  Latest parsed stream stats reported about 59.86 FPS; latest parsed decoder
  latency averaged 5.8 ms over 60 samples with dropped `0`.

The first default `make evidence-usb-live-smoke` run returned `insufficient`
because the default 1500-line tag-filtered logcat window did not include
current-process telemetry or decoder lines. The final retained
`usb-live-smoke.json` was produced by the same read-only collector with
`--logcat-lines 50000 --max-log-bytes 1048576` and returned `pass`.

## LAN boundary

This package must not be used as a LAN stream or reconnect pass. The retained
boundary probes show why:

- The Host listener was loopback-only: `127.0.0.1:54321`.
- The Android path was USB reverse: `UsbFfs tcp:54321 tcp:54321`.
- P0110 Wi-Fi was enabled but not connected.
- `wlan0` was `NO-CARRIER` / `state DOWN` and had no IPv4 address.
- Android had no retained LAN route output.
- `security find-identity -v -p codesigning` found `0 valid identities`, and
  `scripts/macos_dev_host.py preflight` still failed because the `Vibe Screen
  Dev` codesigning identity was absent.

The README trusted-LAN stream/reconnect, LAN latency, two-hour RSS, external
camera latency, native pointer HID, stylus, controller, and long-soak gates all
remain open unless their dedicated evidence packages pass.

## Captured artifacts

- `usb-live-smoke.json` and `usb-live-smoke.exit`: final read-only USB live
  smoke result.
- `android-logcat-pid15457-threadtime.txt`: current-process logcat with
  `first_frame_received`, `stream_stats`, `first_output_frame`, and decoder
  output lines.
- `android-diag-tail.txt`: app private diagnostic log context showing HEVC
  decoder setup and continuing frame counters.
- `host-log-tail-filtered.txt`: Host log excerpt showing USB loopback Protocol
  v1 connection and continuing pipeline samples.
- `host-54321-listener.txt`, `host-process.txt`, and `adb-reverse.txt`: Host
  and USB transport boundary.
- `android-wifi-status.txt`, `android-wlan0.txt`, and `android-ip-route.txt`:
  retained LAN blockers.
- `codesigning-identities.txt` and `macos-dev-host-preflight.txt`: retained
  Host signing blocker.
- `window-focus.txt`: sanitized Android foreground evidence for
  `dev.telemachus.display/.MainActivity`.
- `SHA256SUMS`: hashes for retained artifacts.

No pairing URL, QR payload, Wi-Fi credential, SSID, public address, or private
screen content was intentionally retained. A pre-commit sensitive-text scan only
matched only the literal search terms documented in `README.md` and
`commands.txt`. The discarded full Android window dump contained WindowManager
Binder/window token terminology, not a Vibe Screen pairing token or credential;
the retained window artifact is limited to foreground/focus lines.
