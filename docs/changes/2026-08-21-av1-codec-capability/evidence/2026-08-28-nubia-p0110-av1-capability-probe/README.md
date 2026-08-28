# Nubia P0110 AV1 decoder capability probe

Date: 2026-08-28
Status: capability snapshot captured; real AV1 stream still blocked

## Device identity

The read-only ADB probes used the explicit serial <redacted-device-serial> after
acquiring /tmp/vibe-screen-android-<redacted-device-serial>.lock.

- Manufacturer/model: Nubia P0110
- Codename: pacific
- Android: 16
- SDK: 36
- Serial: <redacted-device-serial>
- Product name: pacific

Do not label any result from this device as Xiaomi 13/fuxi evidence.

## Commands

The probe started from origin/main commit
27d2b0e493e807ae439fbd43b06b4c2f0ce9c503 on branch
codex/av1-android-decode-capability-probe. The command outputs are retained
beside this README.

    pgrep -x sfltool || true
    adb -s <redacted-device-serial> devices -l
    adb -s <redacted-device-serial> get-state
    adb -s <redacted-device-serial> shell getprop ro.product.manufacturer
    adb -s <redacted-device-serial> shell getprop ro.product.model
    adb -s <redacted-device-serial> shell getprop ro.product.device
    adb -s <redacted-device-serial> shell getprop ro.product.name
    adb -s <redacted-device-serial> shell getprop ro.build.version.release
    adb -s <redacted-device-serial> shell getprop ro.build.version.sdk
    adb -s <redacted-device-serial> shell getprop ro.build.fingerprint
    adb -s <redacted-device-serial> shell dumpsys media.codec
    adb -s <redacted-device-serial> shell cmd media.codec list
    adb -s <redacted-device-serial> shell 'service list | grep -i -E "media|codec"'
    adb -s <redacted-device-serial> shell 'dumpsys -l | grep -i -E "media|codec"'
    adb -s <redacted-device-serial> shell 'grep -Rin "av1" /vendor/etc/*media*codec*.xml /vendor/etc/media_codecs*.xml /system/etc/*media*codec*.xml /system/etc/media_codecs*.xml 2>/dev/null | head -160'

pgrep -x sfltool || true returned no output before any device command was run,
so no stale sfltool process was observed. No /usr/bin/sfltool dumpbtm command
was executed.

## Captured results

- adb-devices-l.txt reports product:pacific model:P0110 device:pacific for
  serial <redacted-device-serial>.
- device-identity.txt reports nubia / P0110 / pacific / Android 16 / SDK 36.
- dumpsys media.codec returned no stdout and stderr
  'Can't find service: media.codec' with exit code 0.
- cmd media.codec list returned no stdout and stderr
  'cmd: Can't find service: media.codec' with exit code 20.
- service-list-media-codec.txt and dumpsys-l-media-codec.txt show media and
  codec-related services, including android.hardware.media.c2.IComponentStore
  entries, but no service named media.codec.
- dumpsys-media-codec-av1-lines.txt is empty because the service-level
  dumpsys media.codec probe was unavailable.
- media-codec-xml-av1.txt records vendor/system XML declarations for
  video/av01, including c2.qti.av1.decoder,
  c2.qti.av1.decoder.low_latency, c2.qti.av1.decoder.secure,
  c2.android.av1.decoder, and c2.android.av1-dav1d.decoder entries.
- SHA256SUMS.txt records hashes for the retained raw outputs.

## Interpretation

This is an Android decoder capability/readiness snapshot only. The P0110 vendor
codec XML declares AV1 decoder entries, but the service-level MediaCodec shell
queries were unavailable through dumpsys media.codec and cmd media.codec list.
This evidence does not prove Vibe Screen AV1 negotiation, MediaCodec
configuration, first decoded output frame, sustained AV1 playback, reconnect
behavior, or any macOS Host AV1 encoder path.

The AV1 real-stream gate remains blocked until a matching Host/device AV1 path
is implemented and accepted with negotiated CODEC_AV1, decoder name, first
output frame, frame counters, runtime logs, and reconnect evidence.
