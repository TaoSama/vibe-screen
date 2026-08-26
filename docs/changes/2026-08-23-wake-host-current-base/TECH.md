# WakeHost current-base gate design

## Current baseline

PR #225 is already merged into `origin/main` and owns the implemented WakeHost
baseline: macOS and Android share the same HMAC-SHA256 authorization transcript,
reject missing or invalid authorization, bound the request to the negotiated
session device identity, reject nonce replay, validate broadcast targets, and
send a standard UDP Wake-on-LAN magic packet only after policy admits the
request.

The earlier #199 draft attempted a stricter pairing-bound ECDSA proof and
session-id/epoch transcript. It was based on an older mainline and conflicts
with #225 across the same WakeHost runtime files. For the current-base evidence
owner, the safe path is to leave the merged runtime baseline intact and add the
missing evidence boundary around it.

## Gate

`tools/vibescreen_evidence/wake_host_current_base.py` consumes a JSON evidence
record with explicit boolean observations and emits
`wake-host-current-base-gate.json`. Missing observations default to false. The
summary is intentionally conservative:

- `pass` only when every required observation is present and no wake failure is
  recorded.
- `blocked` when hardware or environment prerequisites are absent, including an
  identity-signed Host, Wake for network access/NIC WOL configuration, real Mac
  sleep state, router/direct WOL delivery, or observed wake.
- `insufficient` when the run has the blocking hardware prerequisites but still
  lacks non-blocking evidence such as retained logs or negative security cases.
- `fail` when a real or claimed WakeHost attempt failed.

The Makefile target writes a default blocked summary when no observations file
is supplied:

```bash
make wake-host-current-base-gate EVIDENCE_DIR=.build/evidence/wake-host-current-base
```

That default record is only a fail-closed placeholder: all evidence booleans
default to false, including current-main and offline-baseline observations. It
must not be used as sleeping-Mac wake evidence. A real run should pass an
explicit observations file with `WAKE_HOST_CURRENT_BASE_JSON=...`.

## Why #199 remains the owner

#199 remains useful as the current-base evidence owner because it is the open
follow-up that tracks WakeHost proof strictness and hardware acceptance after
#225. Its content is changed from a conflicting runtime replacement to a
machine-readable blocked gate and documentation owner. Future work can still
introduce pairing-bound asymmetric proofs, but that should happen as a
deliberate compatible hardening change rather than as a stale rebase of the
pre-#225 draft.
