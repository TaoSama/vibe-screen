# Nubia P0110 Clipboard Current-Base Gate Blocked

Date: 2026-08-29 (local, Asia/Shanghai)
Last refreshed: 2026-08-30 against current `origin/main`
Source base: `origin/main` at `4884d80813a7f674a10d574a96f8dfcf5723c6e7`
Branch: `codex/clipboard-e2e-current-base`
Device target: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: blocked. Gate closed: false.

This package records a fail-closed current-base gate/tooling refresh for the
real Android `ClipboardManager` <-> macOS `NSPasteboard` Protocol v1 USB/LAN E2E
gate. It does not prove either clipboard transfer direction.

## What Changed

- The `clipboard-e2e-gate` product evidence contract now requires exact
  `source_system_clipboard` and `destination_system_clipboard` endpoint names
  for each direction.
- Each direction must also retain protocol-integrity fields: positive
  `session_epoch`, `session_epoch_verified=true`, `origin_device_id_verified=true`,
  16-byte `change_id_hex`, 64-character SHA-256, `final_sha256_match=true`, and
  a positive `byte_length` no larger than 1 MiB.
- The two transfer directions must use distinct final markers so one local
  smoke, one protocol replay, or one product transfer cannot satisfy both
  directions.
- If USB, trusted-LAN, and product evidence all omit real device identity, the
  device identity check is now blocked rather than defaulting to P0110.

## Evidence Boundary

The upstream owner confirmed a read-only Android probe saw a nubia P0110 /
pacific / Android 16 / API 36 device online, but that probe did not install or
start the app and did not modify `adb reverse`. This package therefore does not
record current-run Android local ClipboardManager instrumentation, USB preflight,
trusted-LAN preflight, or product-transfer evidence.

The gate remains blocked because Host readiness is blocked, no current USB or
trusted-LAN preflight JSON is present in this package, no current Android
`ClipboardManagerInstrumentedTest` log is present in this package, and no
`product-e2e.json` exists for either direction. Existing earlier P0110 records
remain local smoke or readiness evidence only and must not be relabeled as
Xiaomi 13/fuxi evidence.

## Blockers

- Host readiness is blocked by missing stable signing identity, invalid installed
  Host code signature, no Host listener on TCP 54321, missing virtual HID
  entitlement, and unverified login/headless state.
- No real P0110 device identity evidence was captured by this package gate
  inputs.
- No USB preflight, trusted-LAN preflight, or Android local ClipboardManager
  instrumentation log was captured by this package.
- No retained Android `ClipboardManager` -> macOS `NSPasteboard` or macOS
  `NSPasteboard` -> Android `ClipboardManager` product transfer evidence exists.

## Artifacts

- `clipboard-e2e-gate.json` - sanitized fail-closed gate output, verdict
  `blocked`.
- `host-readiness.json` - shared Host readiness JSON, verdict `blocked`.
- `host-signing-and-permissions.txt` - sanitized Host readiness report.
- `pgrep-sfltool-start.txt` / `.exit` - startup safety check output. Exit `1`
  means no `sfltool` process was running.
- `commands.txt` - sanitized commands used for this current-base gate refresh.
- `privacy-scan.json` - public evidence privacy scan.
- `SHA256SUMS` - artifact checksums.
