# AV1 current-base real-stream acceptance remains blocked

Date: 2026-08-27
Status: current-base owner refresh; real AV1 stream blocked

## Source state

- Base: `origin/main` at `32b05030cf4cff54029d9bffd4c9dd0cb7e1d6e3`.
- Worktree: clean before this evidence refresh.
- Scope: AV1 capability/admission audit only. No AV1 stream was attempted or
  observed.

## Code-path audit

- Protocol v1 reserves `CODEC_AV1`, but no AV1-specific media configuration,
  OBU packaging contract, or stream acceptance run is recorded.
- The macOS Host probes `kCMVideoCodecType_AV1` only as diagnostic capability
  state. `VideoCodecCapabilitySnapshot.protocolV1SupportedCodecs` still
  returns HEVC/H.264 only, and `VideoCodecAdmissionPolicy.streamCodec(for:)`
  returns nil for AV1.
- `StreamCodec` and `VideoEncoder` still implement only HEVC and H.264 stream
  paths; there is no AV1 frame packaging path.
- Android `CodecCapabilities.hasAv1Decoder` is diagnostic-only. Product codec
  offers map `StreamCodec.AV1` to nil, and the Android Internet product session
  rejects an incoming AV1 `VideoConfig` before media activation with
  `av1_decoder_unavailable`.
- iOS recognizes the protocol enum as known input but keeps decoder construction
  fail-closed without an AV1 implementation.

## Device diagnostic probe

The connected Android device was checked with explicit `adb -s` targeting. The
serial used locally is redacted from this public evidence.

Sanitized command excerpts:

    adb -s <redacted-device-serial> get-state
    adb -s <redacted-device-serial> shell getprop ro.product.manufacturer
    adb -s <redacted-device-serial> shell getprop ro.product.model
    adb -s <redacted-device-serial> shell getprop ro.product.device
    adb -s <redacted-device-serial> shell getprop ro.build.version.release
    adb -s <redacted-device-serial> shell getprop ro.build.version.sdk
    adb -s <redacted-device-serial> shell cmd media.codec list
    adb -s <redacted-device-serial> shell 'find /vendor/etc /odm/etc /system/etc -maxdepth 2 -type f -name "*codec*" 2>/dev/null | sort | head -80'
    adb -s <redacted-device-serial> shell 'for f in /vendor/etc/*media*codec*.xml /vendor/etc/media_codecs*.xml /odm/etc/*media*codec*.xml /system/etc/*media*codec*.xml; do [ -f "$f" ] && grep -HniE "video/av01|av01|av1" "$f"; done 2>/dev/null | head -80'

Observed identity:

- Manufacturer/model: nubia P0110
- Codename: pacific
- Android: 16
- SDK: 36

Probe summary:

- `cmd media.codec list` returned `Can't find service: media.codec`, so this
  command did not provide runtime MediaCodec enumeration.
- The media codec XML scan showed diagnostic AV1 declarations including
  `c2.qti.av1.decoder`, `c2.qti.av1.decoder.low_latency`,
  `c2.qti.av1.decoder.secure`, `c2.android.av1.decoder`, and
  `video/av01` entries.
- These XML declarations do not prove Vibe Screen AV1 negotiation,
  `MediaCodec` configuration, first output frame, sustained AV1 stream, or
  reconnect behavior.

## Blocking conditions

- The current Host does not advertise AV1 and has no AV1 stream encoder mapping.
- Android product sessions do not offer AV1 even when diagnostic decoder probing
  can observe AV1 declarations.
- No Host/device evidence records `VideoConfig(codec=CODEC_AV1)`, a positive
  config result, decoder name, first decoded output frame, frame counters, or
  sustained AV1 stream.

## Conclusion

The AV1 gate remains blocked/backlog on current base. This evidence may be used
only to show that AV1 admission remains fail-closed and that the connected nubia
P0110 / pacific / Android 16 / SDK 36 device exposes diagnostic AV1 codec
entries. It must not be cited as AV1 Host/device real-stream acceptance.
