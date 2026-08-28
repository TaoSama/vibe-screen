# AV1 real-stream acceptance blocked

Date: 2026-08-21
Status: blocked before AV1 real-stream run

## Device and Host evidence status

No AV1 stream was attempted or observed for this change. The current available
Android device identity, if used in a future Android run, must be recorded as:

- Manufacturer/model: Nubia P0110
- Codename: pacific
- Android: 16
- Serial: `<redacted-device-serial>`

Do not label any result from this device as Xiaomi 13/fuxi evidence.

## 2026-08-22 device capability probe

Before issuing device commands, `/tmp/vibe-screen-device-android.lock` was
checked and was absent. The following read-only ADB checks used the required
explicit device selector. The public command excerpts redact the device serial:

    adb -s <redacted-device-serial> get-state
    adb -s <redacted-device-serial> shell getprop ro.product.manufacturer
    adb -s <redacted-device-serial> shell getprop ro.product.model
    adb -s <redacted-device-serial> shell getprop ro.product.device
    adb -s <redacted-device-serial> shell getprop ro.build.version.release
    adb -s <redacted-device-serial> shell getprop ro.build.version.sdk
    adb -s <redacted-device-serial> shell cmd media.codec list
    adb -s <redacted-device-serial> shell 'grep -Rin "av1" /vendor/etc/*media*codec*.xml /vendor/etc/media_codecs*.xml 2>/dev/null | head -80'

The connected device reported `nubia / P0110 / pacific / Android 16 / SDK 36`.
`cmd media.codec list` failed with `Can't find service: media.codec`, so no
runtime MediaCodec query result is available from that command. The vendor XML
declares AV1 decoder entries such as `c2.qti.av1.decoder`,
`c2.qti.av1.decoder.low_latency`, `c2.qti.av1.decoder.secure`, and
`c2.android.av1.decoder`; these declarations are diagnostic only. They do not
prove a Vibe Screen AV1 negotiation, MediaCodec configuration, first decoded
output frame, or sustained AV1 stream.

## Blockers

- The current macOS Host implementation only has HEVC and H.264 stream encoder
  mappings and Annex-B parameter-set packaging.
- Android and iOS AV1 decode paths have no retained real-device output-frame
  evidence in this repository.
- No matching Host/device AV1 capability matrix, negotiated VideoConfig, first
  output frame, decoder name, frame counters, or reconnect sample is available.

## Required runbook to close the gate

1. Record repository commit, branch, dirty-tree status, macOS version, Xcode
   version, Host bundle signing identity, and Host binary SHA-256.
2. Record exact device identity before the run. For the current Android device,
   use Nubia P0110 / pacific / Android 16 / SDK 36 and redact the serial from
   public evidence.
3. Capture Host-side AV1 hardware encoder support and confirm the Host build has
   an AV1 encoder implementation, AV1 frame packaging, and an advertised
   CODEC_AV1 path gated by that support.
4. Capture client-side AV1 hardware decoder support and ensure the client offers
   CODEC_AV1 only when the decoder is usable for the target resolution/FPS.
5. Start a Protocol v1 session and retain Hello/HostHello/SessionAccepted,
   display start, VideoConfig(codec=CODEC_AV1), and positive VideoConfigResult
   records.
6. Retain first output frame, continuing frame counters, decoder name, dropped
   frame count, codec/runtime error logs, config epoch, stream ID, and a short
   disconnect/reconnect sample.
7. If any Host or client AV1 capability is absent, verify fallback to HEVC or
   H.264, or fail closed with an actionable diagnostic. Do not report the AV1
   gate as passed.

## Current conclusion

This directory documents that AV1 real-stream acceptance is still blocked. The
current change is limited to offline capability/admission/fallback coverage and
must not be cited as AV1 Host/device streaming evidence.
