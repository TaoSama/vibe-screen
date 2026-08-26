# HarmonyOS NEXT / MatePad Mini device acceptance

Never substitute Android results for this runbook.

Keep a redacted structured manifest beside the raw evidence and validate it
before claiming the HarmonyOS gate is closed:

```bash
make harmony-readiness EVIDENCE_DIR=/path/to/evidence
python3 scripts/harmony_device_gate.py --template > /tmp/harmony-device-gates.json
python3 scripts/harmony_secure_pairing_gate.py --template > /tmp/harmony-secure-pairing.json
# Fill every field from the exact DevEco build, signed HAP, MatePad Mini,
# Protocol v1 Mac host, HUKS run, Authority/Signaling services, logs,
# metrics, and external-camera evidence.
make harmony-secure-pairing-gate EVIDENCE_DIR=/path/to/evidence
make harmony-device-gate EVIDENCE_DIR=/path/to/evidence
make harmony-current-base-gate EVIDENCE_DIR=/path/to/evidence
make harmony-matepad-acceptance EVIDENCE_DIR=/path/to/evidence
```

`make harmony-readiness` writes `/path/to/evidence/harmony-readiness.json` and
returns exit code 2 while DevEco Studio, `hvigor`/`ohpm`, `hdc`, the signed HAP,
the signing-certificate hash, the checksum manifest, the Protocol v1 Host build
hash, or the MatePad Mini target is missing. That blocked output is useful for
readiness tracking only. It does not build, install, launch, pair, stream,
decode, inject input, soak, or measure latency, and it cannot close the
HarmonyOS gate.

For a readiness or blocked dry run, `--allow-blocked` may validate the final
manifest shape, but the resulting output is not acceptance evidence and must not
close the README gate.
Strict `make harmony-device-gate` validation also resolves every `pass` gate's
evidence references under `EVIDENCE_DIR`; absolute paths, URLs, `..` traversal,
directories, and missing files fail closed. Direct strict script invocations use
the manifest directory as the evidence root. Keep all referenced logs, summaries,
metrics, and checksums inside the evidence package before asking the gate to pass.
`make harmony-current-base-gate` is the aggregate owner check for the current
README Phase 4 DevEco/HAP/decode/HUKS/transport/resume/MatePad surface, and it
must stay blocked until the strict device gate and readiness preflight both pass.
`make harmony-matepad-acceptance` writes the final redacted
`harmony-matepad-acceptance.json` package after readiness, strict device-gate,
and current-base owner manifests exist. It may also write a blocked package for
readiness tracking, but that package is not acceptance evidence and does not
replace the current-base owner gate.

1. Record repository commit, DevEco/Harmony SDK versions, `hdc -v`, HAP SHA-256,
   tablet model, OS build, free storage, battery, thermal state, and network.
2. Run `pnpm verify` and `make release`; verify the signed HAP and
   `dist/*/SHA256SUMS`. `pnpm verify` alone is not ArkTS/HAP evidence.
3. Run `hdc list targets -v`; match the serial in Settings before installing.
4. Install the signed HAP, launch it, and capture `hdc hilog` filtered to the
   VibeScreen domain. Verify permission copy and denial/retry behavior.
5. Pair with a one-time QR credential using the completed cryptographic pairing
   flow (address-link import is not sufficient). Record HUKS key creation, the
   failed private-key export attempt, PairingOffer/Request/Result transcripts
   after redaction, Host proof verification, credential installation, expiry
   rejection, replay rejection, old-peer rejection, no-HUKS rejection, and
   Authority/Signaling admission. Then connect over LAN and verify the device
   can be revoked and cannot reuse the credential.
6. Stream both H.264 and HEVC. Record negotiated codec/resolution/FPS, hardware
   decoder name, dropped frames, queue depth, RSS, temperature, and power.
7. Exercise tap, drag, multi-touch, right click, wheel/trackpad scroll, hardware
   keyboard/modifiers, mouse buttons, and stylus pressure in both orientations.
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
The current-base owner and merge-order audit for overlapping HarmonyOS gate PRs
is maintained in `docs/changes/2026-08-04-phase-4-harmony/CURRENT_BASE_AUDIT.md`.
