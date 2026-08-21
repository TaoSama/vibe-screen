# MatePad Mini acceptance package: blocked

Date: 2026-08-22 Asia/Shanghai
Source commit: `55a78526b7616a8bbb7631dcccde350bebc342d3`

This is a blocked readiness package for the HarmonyOS NEXT MatePad Mini
real-device acceptance gate. It does not claim HAP installation, AVCodec
hardware decode, HUKS-backed secure pairing, Host resume interoperability,
input/UI behavior, eight-hour soak, external-camera latency, or any real
MatePad Mini pass.

## Commands

```bash
EVIDENCE_DIR=docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-22-matepad-mini-acceptance-blocked
PYTHONDONTWRITEBYTECODE=1 python3 scripts/harmony_readiness.py \
  --output "$EVIDENCE_DIR/harmony-readiness.json"
PYTHONDONTWRITEBYTECODE=1 python3 scripts/harmony_matepad_acceptance.py \
  --evidence-dir "$EVIDENCE_DIR" \
  --write-blocked
python3 scripts/harmony_device_gate.py "$EVIDENCE_DIR/harmony-device-gates.json"
python3 scripts/harmony_device_gate.py --allow-blocked "$EVIDENCE_DIR/harmony-device-gates.json"
```

Exit codes recorded in this directory:

| Check | Exit code | Interpretation |
| --- | ---: | --- |
| `harmony_readiness.py` | 2 | Blocked: DevEco, Hvigor/OHPM/HDC, signed HAP, certificate hash, checksum manifest, Host commit, Host build hash, and MatePad Mini target are unavailable here |
| `harmony_matepad_acceptance.py --write-blocked` | 2 | Blocked package written; no acceptance pass |
| `harmony_device_gate.py` | 1 | Strict verifier rejected blocked evidence as required |
| `harmony_device_gate.py --allow-blocked` | 0 | Structure-only blocked manifest validation passed |

## Evidence files

- `harmony-readiness.json`: read-only readiness preflight result.
- `harmony-device-gates.json`: generated blocked device-gate manifest; every
  required real-device gate remains blocked.
- `harmony-matepad-acceptance.json`: aggregate acceptance package; verdict is
  `blocked` and every acceptance domain is blocked.
- `*-command.txt`, `*.err`, and `*.exit`: command stdout, stderr, and exit
  status for the rerunnable checks above.

No raw serials, pairing credentials, private network addresses, signing keys,
certificate archives, screenshots, screen video, HAP binaries, or device logs
are included in this committed readiness package.

## Open gates

- HAP install/signing lifecycle on a real MatePad Mini.
- AVCodec H.264 and HEVC hardware decode on the MatePad Mini surface.
- HUKS-backed secure pairing, authenticated records, revocation, and replay
  rejection on device.
- Protocol v1 Host resume interop across background/foreground, network roam,
  Host restart, and old-epoch rejection.
- UI/device identity evidence from Settings, HDC, screenshots, component tree,
  and input observations.
- Eight-hour soak and external-camera latency evidence.

Android evidence, including Nubia P0110/pacific/Android 16, is not accepted for
this HarmonyOS gate.
