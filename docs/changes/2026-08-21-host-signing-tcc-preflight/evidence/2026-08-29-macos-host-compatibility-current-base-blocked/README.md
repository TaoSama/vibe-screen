# 2026-08-29 macOS Host compatibility current-base blocked

## Scope

This package records a fail-closed current-base readiness pass for the macOS
Host compatibility matrix owner. It covers only the local Apple silicon
Mac16,8 / Apple M4 Pro host on macOS 26.4.1 build 25E253 with a multi-display
topology: the built-in Color LCD plus one external DELL U2723QE display
detected by `system_profiler`.

No Android runtime probe was started for this record. The row remains blocked
before stream, input, capture, and reconnect probes because the stable
source-bound Host/TCC prerequisites did not pass.

## Commands

```bash
pgrep -x sfltool || true
git fetch origin main --prune
git switch -c codex/macos-host-compatibility-current-base origin/main

EVIDENCE_TMP=.build/evidence/macos-host-compatibility-current-base-2026-08-29-clean
mkdir -p "$EVIDENCE_TMP"
sw_vers > "$EVIDENCE_TMP/host-identity.txt"
# host-identity.txt also retained uname, hw.model, CPU, git, Xcode, and Swift output.
system_profiler SPDisplaysDataType > "$EVIDENCE_TMP/display-topology.txt"
make baseline-macos-host-readiness EVIDENCE_DIR="$EVIDENCE_TMP"

EVIDENCE_PKG=docs/changes/2026-08-21-host-signing-tcc-preflight/evidence/2026-08-29-macos-host-compatibility-current-base-blocked
mkdir -p "$EVIDENCE_PKG"
cp "$EVIDENCE_TMP"/host-identity.txt "$EVIDENCE_PKG"/
cp "$EVIDENCE_TMP"/display-topology.txt "$EVIDENCE_PKG"/
cp "$EVIDENCE_TMP"/host-readiness.json "$EVIDENCE_PKG"/
cp "$EVIDENCE_TMP"/host-signing-and-permissions.txt "$EVIDENCE_PKG"/
make macos-hardware-compatibility-gate EVIDENCE_DIR="$EVIDENCE_PKG"
```

The first attempt wrote artifacts directly under the tracked evidence directory,
which correctly made readiness report a dirty source tree. That attempt was
discarded from the committed package. The retained readiness run above wrote to
`.build/evidence` first; `host-identity.txt` records a clean current-base
checkout with `HEAD == origin/main == b54ee0e929c53459e6ba7e060f2c9de0c846f408`.

The required safety check found no `sfltool` process before collection. This
run used the default readiness path and did not execute `/usr/bin/sfltool
dumpbtm`; it also did not pass `--include-login-item-diagnostic`,
`--inspect-login-items`, `--probe-login-item`, or `--probe-login-items`.

`make baseline-macos-host-readiness` exited `2`.
`make macos-hardware-compatibility-gate` wrote
`macos-hardware-compatibility-gate.json` and exited non-zero because the row is
blocked.

## Result

`host-readiness.json` reports:

- `status=blocked`
- `signing_tcc_status=blocked`
- `listener_status=ready` with `/Applications/Vibe Screen.app` listening on
  TCP port `54321`
- `virtual_hid_status=blocked`
- `login_headless_status=blocked`
- every `can_start_*` runtime gate flag is `false`

Observed blockers:

- The configured `Vibe Screen Dev` signing identity was not found in the
  keychain lookup used for rebuild/install readiness.
- The installed `/Applications/Vibe Screen.app` has bundle id
  `dev.telemachus.display`, a non-ad-hoc `Vibe Screen Dev` identity, and binary
  SHA-256 `c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996`,
  but it lacks embedded source commit/tree provenance.
- Screen Recording and Accessibility authorization could not be verified from
  the read-only TCC evidence path.
- The installed Host does not expose the virtual HID entitlement.
- Login/headless readiness is blocked because Launch at Login remains
  unverified in the default no-`sfltool` path.

The retained compatibility summary reports `verdict=blocked` and
`can_close_macos_host_compatibility_row=false`.

## Boundaries

This record cannot close the macOS Host compatibility matrix. It does not prove
Intel Mac support, any macOS version range, additional Apple silicon model
families, built-in-only operation, single-external-only operation,
dummy/headless operation, Screen Sharing, packaged Host launch from this
source, capture backend behavior, VideoToolbox runtime encoding, Protocol v1
stream, display selection, input smoke, reconnect, Host RSS, native-pointer
HID, stylus, controller, or trusted-LAN behavior.

The exact next prerequisites are: install or expose the stable `Vibe Screen Dev`
codesign identity; rebuild/package the Host from clean current-base source so
source commit/tree provenance is embedded; grant and verify Screen Recording
and Accessibility for that exact installed Host identity; retain full Xcode
build/test/self-test output from the same commit; then run the real USB or
trusted-LAN Android Protocol v1 stream, display, input, and reconnect probes for
this exact row.
