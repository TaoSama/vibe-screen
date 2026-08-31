# Trusted LAN smoke verification

Status: blocked before LAN stream
Date: 2026-08-20
Target device: Nubia P0110 (`pacific`), Android 16, serial
`<device-serial>`

## Goal

Collect a minimal real-device trusted-LAN smoke record for the current
macOS/Android TCP path: QR/token admission, Protocol v1 over LAN,
per-session AES-256-GCM application records, a short real stream, and reconnect.

## Result

The Android device lease was acquired and the Nubia P0110 identity was recorded,
but the LAN smoke could not start because the device had no Wi-Fi association,
no `wlan0` IPv4 address, and no route to the Mac LAN address candidate. The
current Mac environment also cannot install a current-source, stable-signed Host
bundle for evidence-grade device acceptance because the required `Vibe Screen
Dev` codesigning identity is absent.

No real trusted-LAN stream, secure-record negotiation, decoder output, or
reconnect was observed. This blocked record does not close any README
trusted-LAN stream, reconnect, latency, or stability gate.

Evidence: [`evidence/2026-08-20-p0110-lan-smoke/README.md`](evidence/2026-08-20-p0110-lan-smoke/README.md).

## 2026-08-21 recheck

The current `origin/main` worktree was rechecked on the same Nubia P0110 /
pacific / Android 16 device (`<device-serial>`). The device identity was
confirmed, but a real LAN smoke remained blocked before Host launch or pairing:
`wlan0` reported `NO-CARRIER` and `state DOWN`, `cmd wifi status` reported
`Wifi is not connected`, `ip route` returned no route, TCP `54321` had no Mac
listener, and `scripts/macos_dev_host.py preflight` still failed because the
`Vibe Screen Dev` codesigning identity was absent from the local keychain.

No trusted-LAN socket admission, secure-record negotiation, decoder output,
reconnect, or latency evidence was observed. The retained artifact bundle is
[`evidence/2026-08-21-p0110-lan-smoke-recheck/README.md`](evidence/2026-08-21-p0110-lan-smoke-recheck/README.md).

Additional current-source checks for this recheck:

| Check | Result | Notes |
| --- | --- | --- |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.LanSecureRecordAdapterTest --tests dev.telemachus.display.StreamClientWirelessSecurityTest --tests dev.telemachus.display.AuthHandshakeTest` | PASS | Output retained in the 2026-08-21 evidence bundle; covers Android token admission, secure-record negotiation, protected control/media records, and LAN Protocol v1 probe protection. |
| `make protocol` | PASS | Output retained in the 2026-08-21 evidence bundle; covers Protocol v1 schemas, fixtures, and security contract checks. |
| `python3 scripts/macos_dev_host.py preflight` | BLOCKED | Stable Host bundle validation cannot proceed without the configured `Vibe Screen Dev` signing identity. |

## 2026-08-22 current-base successor recheck

A fresh branch from `origin/main` (`codex/trusted-lan-p0110-current-base-successor`,
source commit `79ef30ac7d3b50d3e0129f88823e7be238417bc0`) rechecked the
same Nubia P0110 / pacific / Android 16 device (`<device-serial>`). The
check did not install, force-stop, or reconnect the Android app. It first
confirmed `/tmp/vibe-screen-device-android.lock` was absent, then acquired and
released that lock around read-only `adb -s <device-serial>` probes.

The real trusted-LAN smoke remained blocked before Host launch, pairing, or
streaming. The device was USB-reachable and its identity was recorded, but
`cmd wifi status` reported `Wifi is not connected`, `wlan0` reported
`NO-CARRIER` and `state DOWN`, `ip route` returned no route, and pinging the
Mac LAN candidate failed with `Network is unreachable`. The Mac had a local
Vibe Screen listener only on loopback TCP 54321, and
`scripts/macos_dev_host.py preflight` failed because the required stable
`Vibe Screen Dev` codesigning identity was still absent from the keychain.

No trusted-LAN socket admission, secure-record negotiation, decoder output,
reconnect, latency, stability, or Host RSS no-growth evidence was observed.
The retained artifact bundle is
[`evidence/2026-08-22-p0110-current-base-successor/README.md`](evidence/2026-08-22-p0110-current-base-successor/README.md).
This bundle is now historical blocker evidence because the later 2026-08-24
main preflight below records the newer current-main blocker state. It is kept
to exercise the fail-closed smoke evidence checker, not as the latest
authoritative trusted-LAN readiness record.

Additional current-base successor checks:

| Check | Result | Notes |
| --- | --- | --- |
| `make trusted-lan-smoke-evidence-check EVIDENCE_DIR=docs/changes/2026-08-20-trusted-lan-smoke/evidence/2026-08-22-p0110-current-base-successor` | PASS as `blocked` | Verifies the evidence package is explicitly blocked, cannot close stream/reconnect gates, and retains the Nubia P0110/pacific/Android 16 / SDK 36 identity boundary. |

## 2026-08-27 current-base rebase verification

After `git fetch origin --prune`, this PR was rebased onto `origin/main`
revision `e94d3a051e683d2a7d6f34fd03badd1b4ef264d0`. The retained
2026-08-22 P0110 evidence bundle remains historical blocked evidence only. The
current blocker facts are covered by the later 2026-08-24 main record below,
and no fresh trusted-LAN stream, reconnect, latency, soak, or Host RSS no-growth
evidence was collected for this rebase.
The fail-closed checker now requires the Device label to carry SDK 36 so future
P0110 blocked or passing records match the current Android identity contract.

Focused current-base checks were rerun on the rebased branch:

| Check | Result | Notes |
| --- | --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_trusted_lan_smoke -v` | PASS, 12 tests | Covers blocked/pass/insufficient classification, Nubia identity enforcement, serial and pairing-token rejection, legacy plaintext rejection, and contradictory encryption telemetry rejection. |
| `make trusted-lan-smoke-evidence-check EVIDENCE_DIR=docs/changes/2026-08-20-trusted-lan-smoke/evidence/2026-08-22-p0110-current-base-successor` | PASS as `blocked` | Confirms the retained artifact package still cannot close trusted-LAN stream or reconnect gates. |
| `make evidence-tools-test` | PASS, 851 tests | Keeps the evidence tooling suite green on the rebased branch. |
| `make protocol` | PASS, 37 tests | Covers current Protocol v1 schema, fixtures, TCP framing, and security contract checks. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.LanSecureRecordAdapterTest --tests dev.telemachus.display.StreamClientWirelessSecurityTest --tests dev.telemachus.display.AuthHandshakeTest` | PASS | Focused Android LAN secure-record, token admission, and handshake unit tests. |
| `git diff --check` | PASS | No whitespace errors in the PR diff. |

The public PR body and patch were scanned for the real device serial, local user
paths, TCC database paths, pairing payloads, token-like values, private IP
addresses, and MAC addresses before updating the PR. The only token-pattern
match in the patch is the checker's redaction regex literal, not a retained
credential or pairing payload.

## 2026-08-28 LAN smoke unblock readiness check

The `origin/main` revision `27d2b0e493e807ae439fbd43b06b4c2f0ce9c503` was
checked from a clean source state on the Nubia P0110 / pacific / Android 16 /
SDK 36 device (`<device-serial>`). The run first confirmed no `sfltool` process
was present, then acquired `/tmp/vibe-screen-android-<device-serial>.lock`
before any ADB/device operation. The preflight used only explicit
`adb -s <device-serial>` targeting and did not run `/usr/bin/sfltool dumpbtm`
or any sfltool opt-in path.

The device identity was confirmed, but the unblock readiness check remained
blocked before Host launch, pairing, or streaming: Wi-Fi was not associated,
`wlan0` had no carrier or IPv4 address, Android had no `wlan0` route to a Mac
LAN IPv4 candidate, and Host stable signing was blocked before trusted-LAN
evidence could start. The shared Host readiness snapshot also reported
`can_start_trusted_lan_gate=false`, with no TCP `54321` listener observed and
TCC verification not completed under the missing stable-signing prerequisite.

No real trusted-LAN stream, secure-record negotiation, decoder output,
reconnect, latency, stability, or Host RSS evidence was observed. The retained
artifact bundle is
[`evidence/2026-08-28-p0110-lan-smoke-unblock-check/README.md`](evidence/2026-08-28-p0110-lan-smoke-unblock-check/README.md).

Focused checks for this unblock owner record:

| Check | Result | Notes |
| --- | --- | --- |
| `make evidence-trusted-lan-preflight EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=/tmp/vibe-screen-lan-smoke-unblock-check-2026-08-28` | BLOCKED, exit 2 | Confirmed Nubia P0110/pacific identity, recorded Wi-Fi/wlan0/route blockers and Host signing blocker, and stopped before Host launch or pairing. |
| `make evidence-trusted-lan-preflight EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=/tmp/vibe-screen-lan-smoke-unblock-check-tool-verification` | BLOCKED, exit 2 | Verified the updated collector records `pgrep -x sfltool`, acquires and releases `/tmp/vibe-screen-android-<device-serial>.lock`, and redacts the serial in public JSON. |
| `make baseline-macos-host-readiness EVIDENCE_DIR=/tmp/vibe-screen-lan-smoke-unblock-check-2026-08-28` | BLOCKED, exit 2 | `can_start_trusted_lan_gate=false`; stable signing, TCC read, Host listener, virtual HID, and login/headless readiness remained blocked. |
| `make trusted-lan-smoke-evidence-check EVIDENCE_DIR=docs/changes/2026-08-20-trusted-lan-smoke/evidence/2026-08-28-p0110-lan-smoke-unblock-check` | PASS as `blocked` | Confirms the retained package is valid blocked evidence and cannot close trusted-LAN stream or reconnect gates. |

## 2026-08-29 current-base preflight recheck

The `codex/trusted-lan-current-base-evidence` branch was created from the latest
`origin/main`, then the trusted-LAN and Host readiness tools were hardened to
redact raw IPv4 endpoints and serial-derived local runtime lock paths from
public JSON. The final read-only preflight ran from clean commit
`2da3f86e24cf51c6966dcea7848f55623cb67a40` on the Nubia P0110 / pacific /
Android 16 / SDK 36 device (`<device-serial>`).

The real trusted-LAN smoke remains blocked before Host launch, pairing, or
streaming: Wi-Fi is not associated, `wlan0` has no carrier or IPv4 address,
Android has no `wlan0` route to a Mac LAN IPv4 candidate, and Host stable
signing is blocked before trusted-LAN evidence can start. The shared Host
readiness snapshot reports `can_start_trusted_lan_gate=false`; TCC was not
evaluated because stable signing failed, and the observed TCP `54321` listener
was loopback-only rather than LAN evidence.

No real trusted-LAN stream, secure-record negotiation, decoder output,
reconnect, latency, stability, or Host RSS evidence was observed. The retained
artifact bundle is
[`evidence/2026-08-29-p0110-lan-preflight-current-base-blocked/README.md`](evidence/2026-08-29-p0110-lan-preflight-current-base-blocked/README.md).

Focused checks for this current-base owner record:

| Check | Result | Notes |
| --- | --- | --- |
| `make evidence-trusted-lan-preflight EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=.build/evidence/trusted-lan-current-base-2026-08-29-clean` | BLOCKED, exit 2 | Confirmed Nubia P0110/pacific identity, recorded Wi-Fi/wlan0/route blockers and Host signing blocker, and stopped before Host launch or pairing. |
| `make baseline-macos-host-readiness EVIDENCE_DIR=.build/evidence/trusted-lan-current-base-2026-08-29-clean` | BLOCKED, exit 2 | `can_start_trusted_lan_gate=false`; stable signing, TCC verification, and evidence-grade Host readiness remained blocked. The default command did not probe login items. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools:scripts python3 -m unittest scripts.tests.test_macos_dev_host -v` | PASS, 79 tests | Covers Host readiness fail-closed behavior, default login-item probe skipping, and listener output redaction. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_trusted_lan_preflight tools.tests.test_trusted_lan_smoke tools.tests.test_adb -v` | PASS, 54 tests | Covers trusted-LAN preflight redaction, blocked/pass evidence classification, and explicit-serial ADB boundaries. |
| `make trusted-lan-smoke-evidence-check EVIDENCE_DIR=docs/changes/2026-08-20-trusted-lan-smoke/evidence/2026-08-29-p0110-lan-preflight-current-base-blocked` | PASS as `blocked` | Confirms the retained package is valid blocked evidence and cannot close trusted-LAN stream or reconnect gates. |

## 2026-08-30 current-base preflight recheck

The `codex/trusted-lan-owner-subagent-20260830` branch was created from the latest
`origin/main` commit `fe58cb6715cf203405820bd0eab352d0a93f56d9` in a clean
worktree. Open PRs were audited and no current open PR closes the trusted-LAN
stream/reconnect gate for this base. The read-only trusted-LAN preflight ran on
the Nubia P0110 / pacific / Android 16 / SDK 36 device (`<device-serial>`)
without launching Host, pairing, streaming, reconnect, or timing disruption.

The real trusted-LAN smoke remains blocked before Host launch or pairing:
Wi-Fi is enabled but not associated, `wlan0` has no carrier or IPv4 address,
Android has no `wlan0` route to a Mac LAN IPv4 candidate, and Host stable
signing is blocked because the `Vibe Screen Dev` codesigning identity is
unavailable. The shared Host readiness snapshot reports
`can_start_trusted_lan_gate=false`; TCC was not evaluated because stable
signing failed, and no TCP `54321` LAN listener was observed at preflight time.
A blocked reconnect timing summary was retained with `can_close_timing_gate=false`
and no required disruption exercised.

No real trusted-LAN stream, secure-record negotiation, decoder output,
reconnect, latency, stability, or Host RSS evidence was observed. The retained
artifact bundle is
[`evidence/2026-08-30-p0110-lan-preflight-current-base-blocked/README.md`](evidence/2026-08-30-p0110-lan-preflight-current-base-blocked/README.md).

Focused checks for this current-base owner record:

| Check | Result | Notes |
| --- | --- | --- |
| `make evidence-trusted-lan-preflight EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=/tmp/vibe-screen-lan-owner-20260830/lan` | BLOCKED, exit 2 | Confirmed Nubia P0110/pacific identity, recorded Wi-Fi/wlan0/route blockers and Host signing blocker, and stopped before Host launch or pairing. |
| `make baseline-macos-host-readiness EVIDENCE_DIR=/tmp/vibe-screen-lan-owner-20260830/host` | BLOCKED, exit 2 | `can_start_trusted_lan_gate=false`; stable signing, TCC evaluation, Host listener, and evidence-grade Host readiness remained blocked. The default command did not probe login items. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.reconnect_timing --blocked ...` | BLOCKED, exit 3 | Wrote `reconnect-timing-summary.json` with `can_close_timing_gate=false` and no disruption exercised. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_trusted_lan_preflight tools.tests.test_trusted_lan_smoke tools.tests.test_adb -v` | PASS | Independent after packaging; covers trusted-LAN preflight redaction, blocked/pass evidence classification, and explicit-serial ADB boundaries. |
| `make trusted-lan-smoke-evidence-check EVIDENCE_DIR=docs/changes/2026-08-20-trusted-lan-smoke/evidence/2026-08-30-p0110-lan-preflight-current-base-blocked` | PASS as `blocked` | Confirms the retained package is valid blocked evidence and cannot close trusted-LAN stream or reconnect gates. |

## 2026-08-30 current-base preflight recheck (trusted-lan-p0110)

The `codex/trusted-lan-p0110-current-base-20260830` branch was created from the
latest `origin/main` commit `87e16d8bea4446c1ca449045678f1bafc7fd6cb2` in a
clean worktree. Open PRs were audited and no current open PR closes the
trusted-LAN stream/reconnect gate for this base. The read-only trusted-LAN
preflight ran on the Nubia P0110 / pacific / Android 16 / SDK 36 device
(`<device-serial>`) without launching Host, pairing, streaming, reconnect, or
timing disruption.

The real trusted-LAN smoke remains blocked before Host launch or pairing:
Wi-Fi is enabled but not associated, `wlan0` has no carrier or IPv4 address,
Android has no `wlan0` route to a Mac LAN IPv4 candidate, and Host stable
signing is blocked because the `Vibe Screen Dev` codesigning identity is
unavailable. The shared Host readiness snapshot reports
`can_start_trusted_lan_gate=false`; TCC was not evaluated because stable
signing failed, and no TCP `54321` LAN listener was observed at preflight time.
A blocked reconnect timing summary was retained with `can_close_timing_gate=false`
and no required disruption exercised.

No real trusted-LAN stream, secure-record negotiation, decoder output,
reconnect, latency, stability, or Host RSS evidence was observed. The retained
artifact bundle is
[`evidence/2026-08-30-p0110-lan-preflight-current-base-blocked-20260830/README.md`](evidence/2026-08-30-p0110-lan-preflight-current-base-blocked-20260830/README.md).

Focused checks for this current-base owner record:

| Check | Result | Notes |
| --- | --- | --- |
| `make evidence-trusted-lan-preflight EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=/tmp/vibe-screen-trusted-lan-p0110-current-base-20260830/lan` | BLOCKED, exit 2 | Confirmed Nubia P0110/pacific identity, recorded Wi-Fi/wlan0/route blockers and Host signing blocker, and stopped before Host launch or pairing. |
| `make baseline-macos-host-readiness EVIDENCE_DIR=/tmp/vibe-screen-trusted-lan-p0110-current-base-20260830/host` | BLOCKED, exit 2 | `can_start_trusted_lan_gate=false`; stable signing, TCC evaluation, Host listener, and evidence-grade Host readiness remained blocked. The default command did not probe login items. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.reconnect_timing --blocked ...` | BLOCKED, exit 3 | Wrote `reconnect-timing-summary.json` with `can_close_timing_gate=false` and no disruption exercised. |
| `make trusted-lan-smoke-evidence-check EVIDENCE_DIR=docs/changes/2026-08-20-trusted-lan-smoke/evidence/2026-08-30-p0110-lan-preflight-current-base-blocked-20260830` | PASS as `blocked` | Confirms the retained package is valid blocked evidence and cannot close trusted-LAN stream or reconnect gates. |

## 2026-08-31 current-base preflight recheck

The `codex/trusted-lan-current-base-owner-20260831b` branch was created from the
`origin/main` commit `075dc157c36ba71df9f757e571015905881a7154` (the latest
`origin/main` at branch-creation time) in a clean worktree. `origin/main` has
since advanced to `967e05f4266916569f0898d7e2ed53e3a2602da9`, so this record is
a historical blocked snapshot retained in the current-base owner package and
remains fail-closed. Open PRs were audited with `git fetch origin --prune`; deleted
historical branches were pruned and no current open PR closes the trusted-LAN
stream/reconnect gate for this base. The read-only trusted-LAN preflight ran on
the Nubia P0110 / pacific / Android 16 / SDK 36 device (`<device-serial>`)
without launching Host, pairing, streaming, reconnect, or timing disruption.

The real trusted-LAN smoke remains blocked before Host launch or pairing:
Wi-Fi is enabled but not associated, `wlan0` has no carrier or IPv4 address,
Android has no `wlan0` route to a Mac LAN IPv4 candidate, and Host stable
signing is blocked because the `Vibe Screen Dev` codesigning identity is
unavailable. The shared Host readiness snapshot reports
`can_start_trusted_lan_gate=false`; TCC was not evaluated because stable
signing failed, the installed `/Applications/Vibe Screen.app` also failed
codesign resource inspection, and no TCP `54321` LAN listener was observed at
preflight time. A blocked reconnect timing summary was retained with
`can_close_timing_gate=false` and no required disruption exercised.

No real trusted-LAN stream, secure-record negotiation, decoder output,
reconnect, latency, stability, or Host RSS evidence was observed. The retained
artifact bundle is
[`evidence/2026-08-31-p0110-lan-preflight-current-base-blocked/README.md`](evidence/2026-08-31-p0110-lan-preflight-current-base-blocked/README.md).

Focused checks for this current-base owner record:

| Check | Result | Notes |
| --- | --- | --- |
| `make evidence-trusted-lan-preflight EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=/tmp/vibe-screen-lan-owner-20260831b/lan` | BLOCKED, exit 2 | Confirmed Nubia P0110/pacific identity, recorded Wi-Fi/wlan0/route blockers and Host signing blocker, and stopped before Host launch or pairing. |
| `make baseline-macos-host-readiness EVIDENCE_DIR=/tmp/vibe-screen-lan-owner-20260831b/host` | BLOCKED, exit 2 | `can_start_trusted_lan_gate=false`; stable signing, TCC evaluation, Host listener, and evidence-grade Host readiness remained blocked. The default command did not probe login items. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.reconnect_timing --blocked ...` | BLOCKED, exit 3 | Wrote `reconnect-timing-summary.json` with `can_close_timing_gate=false` and no disruption exercised. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_trusted_lan_preflight tools.tests.test_trusted_lan_smoke tools.tests.test_adb -v` | PASS, 55 tests | Covers trusted-LAN preflight redaction, blocked/pass evidence classification, and explicit-serial ADB boundaries. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.LanSecureRecordAdapterTest --tests dev.telemachus.display.StreamClientWirelessSecurityTest --tests dev.telemachus.display.AuthHandshakeTest` | PASS | Focused Android LAN secure-record, token admission, and handshake unit tests. |
| `make protocol` | PASS, 45 tests | Covers current Protocol v1 schema, fixtures, TCP framing, and security contract checks. |
| `make trusted-lan-smoke-evidence-check EVIDENCE_DIR=docs/changes/2026-08-20-trusted-lan-smoke/evidence/2026-08-31-p0110-lan-preflight-current-base-blocked` | PASS as `blocked` | Confirms the retained package is valid blocked evidence and cannot close trusted-LAN stream or reconnect gates. |

## 2026-08-31 Codex task current-base preflight recheck

The `codex/trusted-lan-codex-task-20260831` branch was created from
`origin/main` commit `28b9d1a59ef026b45ada3cd7e665ef09ea9a7523` in a clean
worktree. This retained bundle is a blocked snapshot for that collection
revision, even when the PR branch later merges newer `origin/main` revisions.
The read-only trusted-LAN preflight ran on the Nubia P0110 / pacific /
Android 16 / SDK 36 device (`<device-serial>`) without launching Host, pairing,
streaming, reconnect, changing Wi-Fi credentials, modifying TCC, or running any
login-item diagnostic. The collector first ran `pgrep -x sfltool` and observed
no process; it did not run `/usr/bin/sfltool dumpbtm`.

The real trusted-LAN smoke remains blocked before Host launch or pairing:
Wi-Fi is enabled but not associated, `wlan0` has no carrier or IPv4 address,
Android has no `wlan0` route to a Mac LAN IPv4 candidate, and Host stable
signing is blocked because the `Vibe Screen Dev` codesigning identity is
unavailable. The installed `/Applications/Vibe Screen.app` also failed codesign
resource inspection, no TCP `54321` listener was observed, and Screen Recording
and Accessibility TCC were not evaluated because stable signing failed. A
blocked reconnect timing summary was retained with `can_close_timing_gate=false`
and no required disruption exercised.

No real trusted-LAN stream, secure-record negotiation, decoder output,
reconnect, latency, stability, or Host RSS evidence was observed. The retained
artifact bundle is
[`evidence/2026-08-31-p0110-lan-preflight-codex-task-blocked/README.md`](evidence/2026-08-31-p0110-lan-preflight-codex-task-blocked/README.md).

Focused checks for this Codex task owner record:

| Check | Result | Notes |
| --- | --- | --- |
| `make evidence-trusted-lan-preflight EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=/private/tmp/vibe-screen-trusted-lan-codex-task-20260831/lan` | BLOCKED, exit 2 | Confirmed Nubia P0110/pacific identity, recorded Wi-Fi/wlan0/route blockers and Host signing blocker, and stopped before Host launch or pairing. |
| `make baseline-macos-host-readiness EVIDENCE_DIR=/private/tmp/vibe-screen-trusted-lan-codex-task-20260831/host` | BLOCKED, exit 2 | `can_start_trusted_lan_gate=false`; stable signing, TCC evaluation, Host listener, virtual HID, and evidence-grade Host readiness remained blocked. The default command did not probe login items. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.reconnect_timing --blocked ...` | BLOCKED, exit 3 | Wrote `reconnect-timing-summary.json` with `can_close_timing_gate=false` and no disruption exercised. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_trusted_lan_preflight tools.tests.test_trusted_lan_smoke tools.tests.test_adb tools.tests.test_reconnect_timing -v` | PASS, 89 tests | Covers trusted-LAN preflight redaction, blocked/pass smoke evidence classification, explicit-serial ADB boundaries, and blocked/pass reconnect timing classification. |
| `make protocol` | PASS, 45 tests | Covers current Protocol v1 schemas, fixtures, TCP framing, shared model manifest, and security contract checks. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.LanSecureRecordAdapterTest --tests dev.telemachus.display.StreamClientWirelessSecurityTest --tests dev.telemachus.display.AuthHandshakeTest` | PASS | Covers Android LAN secure-record framing, token admission, wireless security reporting, and authenticated handshake behavior. |
| `make trusted-lan-smoke-evidence-check EVIDENCE_DIR=docs/changes/2026-08-20-trusted-lan-smoke/evidence/2026-08-31-p0110-lan-preflight-codex-task-blocked` | PASS as `blocked` | Confirms the retained package is valid blocked evidence and cannot close trusted-LAN stream or reconnect gates. |

## 2026-08-22 fail-closed preflight

The current `origin/main` revision `a8346626f07de98a54508c2d05ba138d0c969ef0`
was checked with the new read-only trusted-LAN preflight on the same Nubia P0110
/ pacific / Android 16 device (`<device-serial>`). Wi-Fi was enabled with
`adb -s <device-serial> shell svc wifi enable`, but the device still reported
no Wi-Fi association, `wlan0` remained `NO-CARRIER` / `state DOWN` with no IPv4
address, and Android had no wlan0 route to the Mac LAN candidate. Host stable
signing was also blocked before TCC evaluation because the
`scripts/macos_dev_host.py preflight` command could not find the configured
`Vibe Screen Dev` codesigning identity.

The preflight stopped before Host launch, QR/token admission, secure-record
negotiation, Protocol v1 LAN upgrade, decoder output, reconnect, latency, or
soak evidence. The retained artifact bundle is
[`evidence/2026-08-22-p0110-lan-preflight-blocked/README.md`](evidence/2026-08-22-p0110-lan-preflight-blocked/README.md).

## 2026-08-23 main preflight recheck

After PR #261 merged the fail-closed trusted-LAN preflight to `origin/main`,
commit `392b86882869f9bf431cfd35be834f6cdc15fd37` was rechecked on the same
Nubia P0110 / pacific / Android 16 device (`<device-serial>`). The device
identity was confirmed, but the real LAN smoke remained blocked before Host
launch or pairing: Wi-Fi was enabled but not associated, `wlan0` remained
`NO-CARRIER` / `state DOWN` with no IPv4 address, Android had no `wlan0` route
to the Mac LAN candidate, and Host stable signing was blocked because the
`Vibe Screen Dev` codesigning identity was unavailable.

No trusted-LAN socket admission, secure-record negotiation, Protocol v1 LAN
upgrade, decoder output, reconnect, latency, or soak evidence was observed. The
retained artifact bundle is
[`evidence/2026-08-23-p0110-lan-preflight-main-blocked/README.md`](evidence/2026-08-23-p0110-lan-preflight-main-blocked/README.md).

## 2026-08-24 main preflight recheck

After `git fetch origin --prune`, commit
`34b75ac7d945dfa6697ff311fd0a821fb75532ef` from `origin/main` was rechecked on
the same Nubia P0110 / pacific / Android 16 / SDK 36 device
(`<device-serial>`). Open PRs #286, #246, and #191 were audited as related
trusted-LAN work: they contain blocker records and older checker/evidence
attempts, but no current-main real LAN stream/reconnect pass that can close this
gate.

Wi-Fi was enabled with `adb -s <device-serial> shell svc wifi enable`, but
the preflight remained blocked before Host launch or pairing: Wi-Fi was not
associated, `wlan0` had no carrier, no IPv4 address, and no route to the Mac LAN
candidate. Host stable signing also remained blocked because the `Vibe Screen
Dev` codesigning identity was unavailable, so Screen Recording and
Accessibility TCC could not be evaluated for an evidence-grade Host bundle.

No trusted-LAN socket admission, secure-record negotiation, Protocol v1 LAN
upgrade, decoder output, reconnect, latency, or soak evidence was observed. A
blocked reconnect timing summary was retained with `can_close_timing_gate=false`
and no required disruption marked as exercised. The retained artifact bundle is
[`evidence/2026-08-24-p0110-lan-preflight-main-blocked/README.md`](evidence/2026-08-24-p0110-lan-preflight-main-blocked/README.md).

## 2026-08-24 USB/loopback running-window observation

After the blocked trusted-LAN preflight, an already-running `/Applications/Vibe
Screen.app` instance was observed without changing device or Host state. The
Host process `22385` was listening only on `127.0.0.1:54321`, ADB reverse still
reported `UsbFfs tcp:54321 tcp:54321`, and the Nubia P0110 / pacific / Android
16 / SDK 36 client process `15457` was foregrounded as
`dev.telemachus.display/.MainActivity`. The read-only USB live-smoke collector
returned `verdict=pass` when run with a wider current-process logcat window:
85 positive `stream_stats` events, latest FPS about 59.86, first output frame
observed, continuing decoder output counters, and dropped frames `0`.

This is USB/loopback evidence only. It does not close the trusted-LAN stream or
reconnect gate because no LAN listener, Wi-Fi association, `wlan0` IPv4 route,
trusted-LAN secure-record negotiation, or LAN reconnect disruption was observed;
the Host stable-signing preflight also remained blocked by the missing `Vibe
Screen Dev` codesigning identity. The retained artifact bundle is
[`evidence/2026-08-24-p0110-usb-loopback-running-window/README.md`](evidence/2026-08-24-p0110-usb-loopback-running-window/README.md).

## 2026-08-27 current-main preflight recheck

After `git fetch origin --prune`, commit
`3b2ba11e832a3618eaedfc67f92414b161423a00` from `origin/main` was rechecked on
the same Nubia P0110 / pacific / Android 16 / SDK 36 device
(`<device-serial>`). The local checkout matched `origin/main`, and the
machine-readable trusted-LAN preflight was run against a clean detached
`origin/main` worktree so the retained evidence files did not affect repository
provenance.

The real trusted-LAN smoke remains blocked before Host launch or pairing:
Wi-Fi is enabled but not associated, `wlan0` has no carrier or IPv4 address,
Android has no `wlan0` route to the Mac LAN candidate, and Host stable signing
is not ready for evidence-grade trusted-LAN acceptance. The Mac firewall was
disabled, but the only observed TCP `54321` listener was on loopback, which is
not LAN evidence.

No trusted-LAN socket admission, secure-record negotiation, Protocol v1 LAN
upgrade, decoder output, reconnect, latency, soak, or Host RSS no-growth
evidence was observed. A blocked reconnect timing summary was retained with
`can_close_timing_gate=false` and no required disruption exercised. The retained
artifact bundle is
[`evidence/2026-08-27-p0110-lan-preflight-main-blocked/README.md`](evidence/2026-08-27-p0110-lan-preflight-main-blocked/README.md).

## Fail-closed preflight

Use the shared Host readiness snapshot and the machine-readable trusted-LAN
preflight before starting the Host, generating a QR/token, or attempting
stream/reconnect evidence:

    make baseline-macos-host-readiness \
      EVIDENCE_DIR=<evidence-dir>

    make evidence-trusted-lan-preflight \
      EVIDENCE_SERIAL=<device-serial> \
      EVIDENCE_DIR=<evidence-dir>

`host-readiness.json` must show `can_start_trusted_lan_gate=true`, and the
trusted-LAN JSON result must be ready before the real smoke can proceed. If any
stage reports blocked, retain `host-readiness.json`,
`host-signing-and-permissions.txt`, and `trusted-lan-preflight.json`, keep the
downstream admission/secure-record/Protocol v1/decoder/reconnect/latency stages
as `not_run`, and do not describe the run as a trusted-LAN pass. The preflights
are read-only: they do not launch the Host, write a pairing token or QR payload,
modify TCC, alter Keychain, clear Android app data, or change saved Wi-Fi
credentials. The default Host readiness target also skips the macOS login-item
database probe; use
`scripts/macos_dev_host.py readiness --include-login-item-diagnostic` only for
an explicit interactive manual diagnostic.

## Source-level checks

The current code path was still checked offline so the next device owner has a
clear pass/fail baseline for LAN record protection.

| Check | Result | Notes |
| --- | --- | --- |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.LanSecureRecordAdapterTest --tests dev.telemachus.display.StreamClientWirelessSecurityTest --tests dev.telemachus.display.AuthHandshakeTest` | PASS | Confirms Android token admission codec, secure-record negotiation, control/media record protection, replay/tamper failure, and that the default wireless Protocol v1 probe travels inside a secure LAN record. |
| `make baseline-macos-self-test` | PASS | Builds the release Host and passes host, transport, reliability, Protocol v1, and video encoder self-tests. |
| `cd baseline/MacHost && swift test --filter LANSecureRecordAdapterTests` | BLOCKED | The local developer directory is `/Library/Developer/CommandLineTools`; `xcodebuild` reports that full Xcode is not selected, and the test target fails at `import XCTest` with `no such module 'XCTest'`. |
| `python3 scripts/macos_dev_host.py preflight` | BLOCKED | No `Vibe Screen Dev` codesigning identity is available in the current keychain, so a current-source stable-signed Host bundle cannot be installed or verified for TCC-backed device evidence. |
| `adb -s <device-serial> shell svc wifi enable` followed by Wi-Fi/route probes | BLOCKED | Wi-Fi remained disconnected, `wlan0` had no IPv4 address, and the device could not route to the Mac LAN candidate. |

## Next real-device runbook

Run this only after `/tmp/vibe-screen-device-soak.lock` and
`/tmp/vibe-screen-device-android.lock` are absent and the current task has
atomically created `/tmp/vibe-screen-device-android.lock`. Always use the exact
serial `<device-serial>`.

1. Capture environment: `sw_vers`, `swift --version`, `xcodebuild -version`,
   `git rev-parse HEAD`, `ifconfig`, `lsof -nP -iTCP:54321 -sTCP:LISTEN`,
   and `adb -s <device-serial> devices -l`.
2. Record device identity from `getprop`: serial, manufacturer, model, device
   codename, Android release, SDK, build fingerprint, display size/density,
   battery, and boot state. Label the run only as Nubia P0110 / pacific.
3. Confirm the Android device has a `wlan0` IPv4 address and can route to the
   Mac LAN IPv4 from step 1 before starting the Host.
4. Verify `make baseline-macos-host-readiness EVIDENCE_DIR=<evidence-dir>`
   writes `host-readiness.json` with `can_start_trusted_lan_gate=true` for a
   current-source Host bundle installed at `/Applications/Vibe Screen.app`. If
   the `Vibe Screen Dev` signing identity, source-bound bundle, TCC grants, or
   TCP `54321` listener is missing, recreate/select/fix it before generating
   device acceptance evidence.
5. Build/install the matching Android debug APK if needed. Do not clear app data
   unless the run explicitly records why the previous pairing state was invalid.
6. Start the macOS Host in Wireless mode on a trusted private LAN. Retain
   `~/Library/Logs/Telemachus/telemachus.log` and any `VIBE_SCREEN_TELEMETRY_PATH`
   JSONL.
7. Pair with the Host QR URL or an equivalent captured `telemachus://host:54321`
   URL using the actual Mac LAN IPv4 from step 1. Do not commit the 32-byte
   token or QR payload.
8. Require these non-legacy LAN markers before treating the run as encrypted:
   Host log `Trusted LAN secure records negotiated`; Android diag
   `Wireless connected ... (trusted LAN encrypted records)`; Android telemetry
   `trusted_lan_encrypted=true` and `trusted_lan_legacy_plaintext=false`;
   Protocol v1 upgrade accepted with transport `TRANSPORT_KIND_LAN`.
9. Record first output frame, continuing frame counters, decoder name, no fatal
   codec error, Host PID, and a short disconnect/reconnect sequence with the
   Host PID preserved.

## Open gates

- Current-worktree real macOS/Android trusted-LAN stream on Nubia P0110/pacific.
- Trusted-LAN reconnect with preserved Host PID.
- LAN glass-to-glass latency with external-camera evidence.
- Any long soak or host RSS no-growth claim.
