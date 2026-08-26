# iOS trusted-LAN secure records

Date: 2026-08-21
Workspace: independent Codex worktree
Base: `origin/main` at `8aad98f14b3be5bf14478c3d29d04e6d3f78c919`

## Scope

This record covers the iOS Core trusted-LAN security path against the baseline
MacHost loopback harness. It verifies that the default iOS startup path requires
the `SSWA`/`SSWR` admission, negotiates `VSLS`/`VSLR` AES-256-GCM
application records, carries `0D`/`0D01` and Protocol v1 frames inside the
record stream, and reports plaintext only when the explicit legacy fallback path
is selected.

The evidence is local Core/transport evidence. It is not an iOS-device run, UI
run, hardware VideoToolbox decode run, external-camera latency run, or
real-network LAN stream/reconnect run.

## Commands

```bash
swift build --package-path apps/ios -c debug
swift run --package-path apps/ios -c release vibescreen-ios-selftest
python3 -m unittest apps/ios/Scripts/tests/test_run_machost_loopback.py
python3 -m py_compile apps/ios/Scripts/run_machost_loopback.py apps/ios/Scripts/tests/test_run_machost_loopback.py
swift build --package-path apps/ios -c release --product vibescreen-mac-host-loopback
swift build --package-path baseline/MacHost -c release --product "Vibe Screen"
apps/ios/Scripts/run_machost_loopback.py --skip-build --startup-timeout 30 --test-timeout 30
apps/ios/Scripts/run_machost_loopback.py --skip-build --legacy-plaintext --startup-timeout 30 --test-timeout 30
```

## Expected secure-record signal

The default loopback run must include both lifecycle and invalid-target passes
with:

```text
iOS Core MacHost loopback: PASS (port=58699, auth=SSWA/SSWR, upgrade=0D/0D01, encryptedRecords=true, explicitLegacyFallback=false, hello=true, displays=true, videoAck=true, media=true, pong=true, targetedTouch=true, disconnect=true)
iOS Core MacHost loopback: PASS (scenario=invalid-target, port=58700, encryptedRecords=true, explicitLegacyFallback=false, protocolError=invalidState)
MacHost loopback: PASS (external lifecycle + invalid-target production-process integration, encryptedRecords:true,explicitLegacyFallback:false,ports=lifecycle:58699,invalid-target:58700)
```

The explicit old-peer fallback run must include both scenarios with:

```text
iOS Core MacHost loopback: PASS (port=58701, auth=SSWA/SSWR, upgrade=0D/0D01, encryptedRecords=false, explicitLegacyFallback=true, hello=true, displays=true, videoAck=true, media=true, pong=true, targetedTouch=true, disconnect=true)
iOS Core MacHost loopback: PASS (scenario=invalid-target, port=58702, encryptedRecords=false, explicitLegacyFallback=true, protocolError=invalidState)
MacHost loopback: PASS (external lifecycle + invalid-target production-process integration, encryptedRecords:false,explicitLegacyFallback:true,ports=lifecycle:58701,invalid-target:58702)
```

## Contract coverage

The iOS self-test and XCTest target cover the trusted-LAN record contract:

- shared `contracts/fixtures/security/v1/channel-records.json` records open
  across host/device directions and control/video/audio/bulk channels;
- P-256 ECDH session ID and transcript context match the macOS/Android record
  layer domains;
- HKDF-derived directional keys split into host/device control, video, audio,
  and bulk keys;
- record nonces are `channel:uint32 || sequence:uint64` and carry the session
  epoch in the authenticated `VSCR` header;
- control and bulk reject out-of-order replay, while video and audio allow
  bounded reordering and still reject duplicates;
- tampered records, wrong sessions, wrong declared channels, and mismatched
  encrypted-record versus inner Protocol v1 frame channels fail closed;
- plaintext legacy fallback requires an explicit startup mode and is reported
  separately.

## Blocked device evidence

No iPhone or iPad with signing prerequisites was available in this environment.
The following Phase 5 gates remain open until a real iOS run records device and
host identifiers, Local Network permission behavior, negotiated protection
state, decoded video, touch/input acknowledgement, disconnect/reconnect, and
hardware VideoToolbox behavior:

- signed iPhone/iPad installation;
- iOS app UI end-to-end trusted-LAN connection;
- hardware H.264/HEVC decode and sustained thermal/power behavior;
- real-network trusted-LAN stream/reconnect behavior;
- external-camera latency or synchronized-clock input latency evidence.

Android evidence is not iOS evidence. If Android diagnostics are collected for
adjacent LAN work, use an explicit ADB target serial locally and record the
device as Nubia P0110 / pacific / Android 16 / SDK 36.
