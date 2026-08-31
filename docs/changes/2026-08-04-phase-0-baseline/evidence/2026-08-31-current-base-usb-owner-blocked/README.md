# Nubia P0110 USB current-base owner: blocked

Date: 2026-08-31 (Asia/Shanghai; UTC 2026-08-30T21:13Z)
Repository base: `origin/main` at `0d58960970c7b8f1e1a8b3671a79752a4bf8470a`
Branch: `codex/usb-current-base-owner-20260831b`
Target serial label: `<P0110_USB_SERIAL>`
Expected identity: nubia P0110 / pacific / Android 16 / SDK 36

## Verdict

Status: blocked. README Android USB current-base / Protocol v1 gate closed:
false.

This package is a fail-closed current-base owner record for the general Android
USB/Protocol v1 gate on Nubia P0110/pacific. It does not prove USB streaming,
reconnect, input, latency, soak, Host RSS no-growth, native pointer HID,
stylus, controller, rotated host-display, LAN, Internet, or Xiaomi 13/fuxi
behavior.

The retained Host readiness is a blocked historical snapshot reused for this
owner record. Because its original `current_source_dirty` state denoted a
non-clean collection worktree, this record is blocked and that Host readiness
cannot be used as pass provenance for a current-base USB stream pass.

## Lock handling

An empty serial-scoped lock at `/tmp/vibe-screen-android-REDACTED_P0110_USB_SERIAL.lock`
was present at collection start. It was not held by a live process and had no
content, so this owner task treated it as a stale/owned local lease, used the
read-only preflight collector with `--held-lock`, and did not start a competing
Host or Android session. The final owner record remains blocked.

## What the run observed

- The repository worktree HEAD matched `origin/main` at
  `0d58960970c7b8f1e1a8b3671a79752a4bf8470a`.
- The target ADB serial was used explicitly and redacted in public artifacts.
- The device matched nubia P0110 / pacific / Android 16 / SDK 36.
- `adb reverse --list` retained `UsbFfs tcp:54321 tcp:54321`.
- The Android package was installed but was not running and was not foreground.
- The Mac Host was not listening on TCP `54321`.
- The macOS Host stable-signing/TCC preflight failed before a current-source
  USB smoke could be admitted.
- The read-only USB live-smoke collector returned `insufficient` with no
  current-process `stream_stats`, no positive FPS, and no decoder output.

## Blockers

- Android app process is not running.
- Android app is not foreground.
- Mac Host is not listening on TCP `54321`.
- macOS Host stable-signing/TCC preflight failed.
- No current-process USB live smoke evidence was collected.

## Artifacts

- `usb-current-base.json` and `usb-current-base-gate.json` - blocked owner gate.
- `usb-smoke-preflight.json` and its exit code - blocked USB preflight.
- `usb-live-smoke.json` and its exit code - insufficient live-smoke snapshot.
- `host-readiness.json` and `host-signing-and-permissions.txt` - blocked Host
  readiness.
- `device-info.json` - redacted Nubia P0110/pacific identity.
- `source-baseline.txt`, `git-head.txt`, `git-origin-main.txt` - source
  provenance.
- `usb-smoke-preflight.command.txt` - redacted command ledger.
- `SHA256SUMS` - retained checksums.

## Gate paths

Strict gate:

```bash
make usb-current-base-owner-record EVIDENCE_DIR=docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-31-current-base-usb-owner-blocked
```

That strict path returns nonzero because the record is blocked. To preserve the
fail-closed owner record in a workflow that accepts blocked evidence, use
`USB_CURRENT_BASE_ALLOW_BLOCKED=1`; doing so does not close the README gate.
