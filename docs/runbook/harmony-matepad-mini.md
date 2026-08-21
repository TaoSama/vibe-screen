# HarmonyOS NEXT / MatePad Mini device acceptance

Never substitute Android results for this runbook.

Keep a redacted structured manifest beside the raw evidence and validate it
before claiming the HarmonyOS gate is closed:

```bash
python3 scripts/harmony_device_gate.py --template > /tmp/harmony-device-gates.json
# Fill every field from the exact DevEco build, signed HAP, MatePad Mini,
# Protocol v1 Mac host, logs, metrics, and external-camera evidence.
python3 scripts/harmony_device_gate.py /path/to/evidence/harmony-device-gates.json
```

For a readiness or blocked dry run, `--allow-blocked` may validate the manifest
shape, but the resulting output is not acceptance evidence and must not close
the README gate.

1. Record repository commit, DevEco/Harmony SDK versions, `hdc -v`, HAP SHA-256,
   tablet model, OS build, free storage, battery, thermal state, and network.
2. Run `pnpm verify` and `make release`; verify the signed HAP and
   `dist/*/SHA256SUMS`. `pnpm verify` alone is not ArkTS/HAP evidence.
3. Run `hdc list targets -v`; match the serial in Settings before installing.
4. Install the signed HAP, launch it, and capture `hdc hilog` filtered to the
   VibeScreen domain. Verify permission copy and denial/retry behavior.
5. Pair with a one-time QR credential using the completed cryptographic pairing
   flow (address-link import is not sufficient), connect over LAN, and verify the device
   can be revoked and cannot reuse the credential.
6. Stream both H.264 and HEVC. Record negotiated codec/resolution/FPS, hardware
   decoder name, dropped frames, queue depth, RSS, temperature, and power.
7. Exercise tap, drag, multi-touch, right click, wheel/trackpad scroll, hardware
   keyboard/modifiers, mouse buttons, stylus pressure, and controller input
   (button mask, left/right stick axes, left/right triggers, hat,
   CONNECTED/STATE/DISCONNECTED lifecycle, up to four active controllers, and
   all-zero neutral release on disconnect) in both orientations.
8. Background/foreground the app, turn Wi-Fi off/on, roam access points, sleep
   and wake the Mac, and restart the host. Confirm reconnect within the target
   and that no prior-epoch frame renders.
9. Run eight hours at the target mode. Archive timestamped logs and metrics;
   reject any unbounded latency, queue, RSS, or thermal throttling trend.
10. Measure glass-to-glass and input latency with an external high-frame-rate
    camera; do not compare unsynchronized host/device clocks.

Store raw evidence under an ignored local directory or attach it to the release;
do not commit device identifiers, pairing credentials, or private network data.
The committed evidence summary, if any, should reference only redacted artifact
paths or reviewed release attachments.
