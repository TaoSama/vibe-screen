# Two-hour soak blocked before formal timing

This record documents a preparation attempt on 2026-08-05 local time. It is
not soak evidence and does not change the Phase 0 or README acceptance status.

## Outcome

- Formal soak duration: **0 seconds**.
- Accepted samples: **0**.
- Two-hour stability gate: **open**.
- Device lease: **released**; `/tmp/vibe-screen-device-soak.lock` was deleted.

The macOS console session was locked. `CGPreflightScreenCaptureAccess()` still
reported permission, but `SCShareableContent` returned zero displays. The Host
therefore failed during pre-warm with `Virtual display with ID 1 not found after
5 attempts`. A real HEVC stream was never established, so the formal evidence
runner was not started. No pre-warm time is counted toward the two-hour target.

The corresponding machine-readable record is
[`two-hour-soak-blocked.json`](two-hour-soak-blocked.json).

## Frozen preparation context

- Repository commit: `6f7ffbe0be872390144899642636dbb24d89f120`
  (`origin/main` at preparation time).
- ADB endpoint: `100.72.246.116:5555`.
- Device: Nubia P0110 (`pacific`), Android 16 / SDK 36, hardware serial
  `[redacted]`.
- Device fingerprint:
  `nubia/pacific/pacific:16/2.5.2.0/20260804.003241:userdebug/test-keys`.
- Current-main debug APK SHA-256:
  `d3acd058c806108a747da853533c7ffa631347b3de64e4e367c1d8cb944328c6`.
- Current-main Host executable SHA-256:
  `98df1a5de55a8ee49b469febae36bcf9bc744dc9121ee64b23c795385847f5ff`.

The APK was installed once before any prospective formal window. No APK
installation, media-port probe, reconnect injection, or formal sampling was
performed after the pre-warm failure was identified.

## Reproduction and invalidation

The blocking state was confirmed with:

```bash
ioreg -n Root -d1 -a | plutil -p - | \
  rg 'CGSSession(ScreenIsLocked|OnConsoleKey|UserNameKey)'
```

The relevant result was `CGSSessionScreenIsLocked => true`. Host diagnostics
then recorded `SCShareableContent verification OK — 0 displays found` and the
bounded unattended retries. This preparation attempt is invalid for stability
claims because no capturable display, admitted HEVC stream, stream statistics,
or formal soak clock existed.

A future attempt must acquire a fresh device lock, start from an unlocked Mac
session, pre-warm until HEVC selection, first output, continuous stream stats,
and heartbeats are visible, and only then run the complete two-hour preset. It
must not reuse elapsed time or artifacts from this preparation attempt.

## Offline checks completed

The following checks passed independently of the blocked device window:

- Protocol format, lint, build, and v1 breaking check.
- macOS release build plus Host, transport, and reliability self-tests.
- Android unit tests, lint, debug APK build, and dependency audit.
- Evidence tools: 36 tests, including the exact-window report tests.
- `git diff --check`.

These checks validate the supporting code only. They do not close the two-hour
device stability gate.
