# Vibe Screen for HarmonyOS NEXT

Native ArkTS/ArkUI client for HarmonyOS NEXT tablets. The code implements the
shared Vibe Screen Protocol v1 independently; it has no Kotlin Multiplatform or
Android runtime dependency.

## Requirements

- DevEco Studio with HarmonyOS NEXT SDK API 12 or newer;
- Node.js 20+ and pnpm 9+ for portable core tests;
- a HarmonyOS NEXT tablet for installation and decoder/input verification;
- a Mac host that implements Vibe Screen Protocol v1.

The repository does not redistribute the proprietary HarmonyOS SDK or signing
credentials. Install those through DevEco Studio and use a certificate owned
by your developer account.

## Build and test

```bash
cd apps/harmony
pnpm install --frozen-lockfile
pnpm verify
make build-debug
```

If `hvigorw` is not on `PATH`, import `apps/harmony` in DevEco Studio, allow it
to synchronize the SDK, then select **entry > default > debug > Build HAP**.
The unsigned/debug HAP is emitted below `entry/build/`. For a versioned signed
artifact, configure a release signing profile and run `make release`; the HAP
and `SHA256SUMS` are copied to `dist/0.1.0/`.

## Install and run

1. Enable developer mode and USB debugging on the tablet.
2. Connect it and confirm that `hdc list targets -v` shows the expected serial.
3. Install with `hdc -t SERIAL install entry/build/.../entry-default-signed.hap`.
4. Open Vibe Screen and enter the LAN address of a Protocol v1 host. One-time
   QR scanning is not wired into the initial page yet.
5. Grant network/background permission when prompted. Background operation is
   used only to resume a recently interrupted session; the app does not bypass
   HarmonyOS background limits.

Upgrade by installing a newer HAP with the same bundle name and signing key.
Pairing data is retained. Changing the signing key requires uninstalling the
old app, which also removes locally stored pairing credentials.

## Architecture

- `core/protocol`: hand-written, dependency-free Protocol v1 wire codec;
- `core/session`: strict connection state, session epochs, and backoff;
- `core/media`: capacity-one latest-frame queue;
- `core/input`: pixel/letterbox/rotation normalization;
- `platform`: Harmony TCP, Asset Store, and AVCodec hardware adapters;
- `pages`: 8–9 inch landscape/portrait ArkUI experience.

Control messages are length-delimited Protobuf envelopes. Media is kept out of
the control model and filtered by `session_epoch` before hardware decode. The
decoder accepts only H.264/HEVC selected by an explicit `VideoConfig` exchange.

## Permissions and privacy

- `INTERNET`: connect directly to the selected Mac;
- `GET_NETWORK_INFO`: give actionable offline/LAN errors;
- `KEEP_BACKGROUND_RUNNING`: recover a session after a brief app switch.

Pairing credentials stay in HarmonyOS Asset Store rather than plain Preferences. Protocol v1
pairing reserves device credentials, but production Internet E2EE is a Phase 3
host prerequisite and is not claimed by this client over a plaintext LAN.

## Troubleshooting

- **Host never accepts:** the current imported Telemachus host uses a legacy
  byte protocol and is not Protocol v1 compatible yet. Use a v1-enabled host.
- **Black video:** confirm the host selected H.264/HEVC supported by the device,
  then request a keyframe. AV1 is advertised only after device capability
  detection is added.
- **Reconnect loop:** revoke the device on the Mac and pair again; check both
  devices are on the same trusted LAN.
- **HAP does not build:** check the SDK API level, signing profile, and that the
  DevEco-provided `hvigorw` is on `PATH`.

See the [device runbook](../../docs/runbook/harmony-matepad-mini.md) and the
[Phase 4 verification record](../../docs/changes/2026-08-04-phase-4-harmony/TEST.md).

## Known limitations

- No HarmonyOS device or DevEco SDK was available for the initial implementation,
  so HAP compilation and MatePad Mini behavior remain unverified.
- The repository host has not implemented Protocol v1, preventing stream/input
  interoperability testing today.
- Protocol v1 represents stylus pressure but not tilt/azimuth, and has no
  controller-specific message. Those inputs cannot be claimed until an additive
  contract revision lands.
- QR camera scanning UI and pairing-store page wiring, Internet transport,
  audio, clipboard, and multi-client
  streaming are not included in this change.
