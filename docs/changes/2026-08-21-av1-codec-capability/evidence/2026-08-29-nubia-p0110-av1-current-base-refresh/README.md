# Nubia P0110 AV1 current-base refresh

Date: 2026-08-29
Status: current-base refresh; real AV1 stream still blocked

## Source State

- Base: `origin/main` at `b54ee0e929c53459e6ba7e060f2c9de0c846f408`.
- Branch: `codex/av1-current-base-evidence`.
- Scope: AV1 Host/device readiness and fail-closed admission only. No AV1
  stream was attempted or observed.

## Device Identity

The read-only Android probes used an explicit `adb -s <redacted-device-serial>`
selector after acquiring `/tmp/vibe-screen-android-<redacted-device-serial>.lock`.

- Manufacturer/model: nubia P0110
- Codename: pacific
- Product name: pacific
- Android: 16
- SDK: 36
- ABI: arm64-v8a
- Hardware/platform: qcom / sun
- Serial: <redacted-device-serial>

Do not label any result from this device as Xiaomi 13/fuxi evidence.

## Commands

The retained outputs beside this README were captured with these sanitized
commands:

    pgrep -x sfltool || true
    adb -s <redacted-device-serial> devices -l
    adb -s <redacted-device-serial> get-state
    adb -s <redacted-device-serial> shell getprop ro.product.manufacturer
    adb -s <redacted-device-serial> shell getprop ro.product.model
    adb -s <redacted-device-serial> shell getprop ro.product.device
    adb -s <redacted-device-serial> shell getprop ro.product.name
    adb -s <redacted-device-serial> shell getprop ro.build.version.release
    adb -s <redacted-device-serial> shell getprop ro.build.version.sdk
    adb -s <redacted-device-serial> shell getprop ro.hardware
    adb -s <redacted-device-serial> shell getprop ro.board.platform
    adb -s <redacted-device-serial> shell getprop ro.product.cpu.abi
    adb -s <redacted-device-serial> shell getprop ro.build.fingerprint
    adb -s <redacted-device-serial> shell dumpsys media.player
    adb -s <redacted-device-serial> shell dumpsys media.codec
    adb -s <redacted-device-serial> shell cmd media.codec list
    adb -s <redacted-device-serial> shell 'service list | grep -i -E "media|codec"'
    adb -s <redacted-device-serial> shell 'dumpsys -l | grep -i -E "media|codec"'
    adb -s <redacted-device-serial> shell 'grep -Rin "av1\|av01" /vendor/etc/*media*codec*.xml /vendor/etc/media_codecs*.xml /odm/etc/*media*codec*.xml /odm/etc/media_codecs*.xml /system/etc/*media*codec*.xml /system/etc/media_codecs*.xml 2>/dev/null | head -180'
    swift -e <VideoToolbox AV1 compression-session probe>

`pgrep -x sfltool || true` returned no output before device probing and again
after evidence capture. No `/usr/bin/sfltool dumpbtm` command was executed, and
no login-item diagnostic opt-in argument was used.

## Captured Results

- `adb-devices-l.txt` reports product `pacific`, model `P0110`, and device
  `pacific` for `<redacted-device-serial>`.
- `device-identity.txt` reports `nubia / P0110 / pacific / Android 16 / SDK 36`
  with `arm64-v8a` and Qualcomm `qcom` / `sun` platform metadata.
- `dumpsys-media-player-av1-lines.txt` reports registered `video/av01` decoders:
  `c2.qti.av1.decoder`, `c2.qti.av1.decoder.low_latency`,
  `c2.qti.av1.decoder.secure`, `c2.android.av1-dav1d.decoder`, and
  `c2.android.av1.decoder`. It also reports the Android software
  `c2.android.av1.encoder`, which is not a macOS Host stream encoder.
- `dumpsys media.codec` returned no stdout and stderr
  `Can't find service: media.codec` with exit code 0.
- `cmd media.codec list` returned no stdout and stderr
  `cmd: Can't find service: media.codec` with exit code 20.
- `media-codec-xml-av1.txt` records vendor/system XML declarations for
  `video/av01`, including Qualcomm AV1 decoder entries and Android software
  AV1 decoder entries.
- `host-videotoolbox-av1-probe.txt` records macOS VideoToolbox AV1 compression
  session probes returning `status=-12908 session=false` for both
  hardware-required and default encoder specifications.
- `SHA256SUMS.txt` records hashes for the retained raw outputs.

## Interpretation

The connected nubia P0110 / pacific / Android 16 / SDK 36 device exposes AV1
decoder capability signals through `dumpsys media.player` and codec XML. This
does not close AV1 real-stream acceptance because the current macOS Host cannot
create a VideoToolbox AV1 encoder session and the product code still has no AV1
`StreamCodec`, encoder mapping, frame packaging, Host advertisement, or Android
product offer path.

The AV1 gate remains fail-closed and blocked on current base. This evidence may
be used only to show current-base readiness diagnostics and fail-closed behavior.
It must not be cited as AV1 Host/device real-stream acceptance.
