# 2026-08-25 current-base Host readiness blocked

## Scope

This record exercises the shared macOS Host readiness preflight from the
current branch head after the readiness tooling change. It is a fail-closed
prerequisite record only. It does not start a LAN session, controller runtime
run, Host RSS soak, native-pointer HID run, stylus run, login/headless run, or
macOS compatibility acceptance row.

## Source

- Source commit recorded by `host-readiness.json`:
  `af3c02beee23b680f56b0bdc211c714df52b1119`
- Source tree recorded by `host-readiness.json`:
  `5642b4cdb8f59cb3fdb05fd503a6d4f81d5dabb6`
- Current checkout dirty: `false`

The command first wrote artifacts in `.build/evidence/host-readiness-current-base-clean`
so the source identity check could run before this committed evidence directory
existed. The retained artifacts were then copied unchanged into this directory.

## Command

```bash
make baseline-macos-host-readiness \
  EVIDENCE_DIR=.build/evidence/host-readiness-current-base-clean
```

Exit code: `2`

## Result

`host-readiness.json` reports `status=blocked`,
`signing_tcc_status=blocked`, `listener_status=ready`, and
`virtual_hid_status=blocked`. All `can_start_*` fields are `false`, including
`can_start_trusted_lan_gate=false` and
`can_start_controller_runtime_gate=false`.

Observed blockers:

- The configured `Vibe Screen Dev` codesigning identity could not be resolved
  by the local keychain lookup.
- The installed `/Applications/Vibe Screen.app` lacks embedded source
  commit/tree provenance.
- Read-only access to both the user and system TCC databases failed, so Screen
  Recording and Accessibility grants could not be verified.
- The installed Host bundle did not expose the
  `com.apple.developer.hid.virtual.device` entitlement.

The local TCP listener check observed `127.0.0.1:54321 (LISTEN)`, but that does
not override the blocked signing, source, TCC, or virtual HID prerequisites.
The `lsof` user column is redacted in the retained JSON/output.

## Boundaries

This record does not close trusted-LAN stream/reconnect, controller runtime,
Host RSS, native-pointer HID, stylus, hardware-keyboard, login/headless, or
macOS compatibility gates. It only proves the current readiness command writes
retained fail-closed artifacts instead of allowing runtime evidence to start
from an unverifiable Host identity.
