# HarmonyOS AVCodecKit H.264/HEVC preflight blocked

Date: 2026-08-21

This directory records a fail-closed local preflight for the HarmonyOS
AVCodecKit H.264/HEVC hardware-decode gate. It is not acceptance evidence and
does not close the README Phase 4 hardware decode gap.

## Command

```text
make harmony-avcodec-preflight EVIDENCE_DIR=docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-21-harmony-avcodec-preflight-blocked
  EXIT: 2
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.harmony_avcodec_preflight --allow-blocked --validate docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-21-harmony-avcodec-preflight-blocked/harmony-avcodec-preflight.json
  PASS: structurally valid blocked readiness manifest only
```

Captured command output:

- `harmony-avcodec-preflight-command.txt`
- `harmony-avcodec-preflight-command.err`
- `harmony-avcodec-preflight.exit`
- `harmony-avcodec-allow-blocked-validate.txt`

## Blockers

The preflight manifest reports:

- `hdc` not found; no HarmonyOS target could be enumerated.
- `ohpm` not found; DevEco-managed dependencies could not be synchronized.
- `hvigor`/`hvigorw` not found; no DevEco HAP build could be produced.
- DevEco CLI not found; ArkTS/API-checker provenance was unavailable.
- No explicit HarmonyOS HDC target was provided.
- No signed HarmonyOS release HAP was provided.
- No HarmonyOS AVCodecKit hardware run artifacts were provided.

Both codec records remain blocked for decoder capability, hardware decoder
identity, XComponent surface, buffer callback, Protocol v1 media header, PTS
preservation, input push, output render, output buffer free, flush, reconfigure,
EOS, and release. Android, emulator, simulator, portable source, and source-only
static results are not substitutes for this gate.
