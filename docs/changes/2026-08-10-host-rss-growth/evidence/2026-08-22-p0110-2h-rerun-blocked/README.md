# 2026-08-22 Nubia P0110 Host RSS 2h Rerun Blocked

This record documents a current-origin/main preparation attempt for the formal
two-hour Host RSS no-growth gate. It is not soak evidence and does not change
the Phase 0 or README acceptance status.

## Outcome

- Formal soak duration: 0 seconds.
- Accepted samples: 0.
- host_rss_gate verdict from this attempt: not run.
- Two-hour Host RSS no-growth gate: open.
- Device lease: no production Android or soak lock was present at preflight; no
  lock was created for this blocked attempt.

The gate was blocked before formal timing because the macOS console session was
locked and Screen Recording permission for dev.telemachus.display had just been
reset. A connected Android device and a listening installed Host process were
present, but no current-source, TCC-authorized Host capture session with a fresh
VIBE_SCREEN_TELEMETRY_PATH was established. The formal soak runner was therefore
not started.

## Frozen Preparation Context

- Repository commit: baaec28a2a47bd9c2ff38a32eaacdbf1880f1e38
  (origin/main after git fetch origin --prune).
- Working branch for this evidence: codex/host-rss-2h-rerun-blocked.
- macOS: 26.4.1 build 25E253 on arm64.
- Xcode selection: /Library/Developer/CommandLineTools.
- Codesigning identities: security find-identity -p codesigning -v reported
  0 valid identities found.
- Installed Host executable: /Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen,
  SHA-256 c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996.
- Installed Host signature: bundle identifier dev.telemachus.display, authority
  Vibe Screen Dev, signed on 2026-08-15.
- Running installed Host: PID 92943, listening on 127.0.0.1:54321.
- Current worktree build artifacts: no local release Host executable and no
  debug APK were present during the preflight.
- Android device: nubia P0110, codename/product pacific, Android 16 / SDK 36,
  serial EP0110PZ0B9110300B. This is Nubia P0110/pacific evidence only and must
  not be reported as Xiaomi 13/fuxi evidence.
- Android package: dev.telemachus.display, version name 0.0.0, version code
  100000, process PID 27526 at preflight.
- ADB reverse: UsbFfs tcp:54321 tcp:54321. A second emulator was connected, so
  every device command used adb -s EP0110PZ0B9110300B explicitly.

## Blocking Conditions

1. The macOS console session was locked: CGSSessionScreenIsLocked => true. A
   locked session invalidates the display-capture pre-warm condition for this
   gate because ScreenCaptureKit can return no capturable displays in that state.
2. Screen Recording permission for dev.telemachus.display was reset during
   preflight. The TCC log recorded a Delete event for kTCCServiceScreenCapture
   and identifier dev.telemachus.display at local time 2026-08-22 02:27:27.
   This was an accidental state modification by the preflight worker and
   requires user repair before another formal run.
3. There was no evidence-grade current-source Host pre-warm. The running Host
   was the installed /Applications binary, not a freshly built current-source
   executable started with VIBE_SCREEN_TELEMETRY_PATH for this gate.
4. No stable local codesigning identity was available. Without a usable Vibe
   Screen Dev identity or a fresh user-approved TCC grant for the exact
   current-source Host binary, a rebuilt Host cannot inherit the installed
   app's Screen Recording/Accessibility permissions.

These blockers make any two-hour timing window invalid. No elapsed time from
this preflight may be reused for the formal gate.

## Reproducible Formal Command Path

After the Mac is unlocked, Screen Recording is re-granted to the exact Host
binary that will run the test, Accessibility is confirmed if input is part of
the same session, and a stable HEVC stream is visible on the Nubia P0110, run
the current-main official tools directly so Host RSS is collected:

```bash
export EVIDENCE_SERIAL=EP0110PZ0B9110300B
export EVIDENCE_DIR=docs/changes/2026-08-10-host-rss-growth/evidence/<new-run-id>
export VIBE_SCREEN_TELEMETRY_PATH="$EVIDENCE_DIR/soak-2h/host-telemetry.jsonl"
mkdir -p "$EVIDENCE_DIR/soak-2h"

# Start the exact current-source, TCC-authorized Host with the environment
# above, establish USB streaming, then record its PID.
export HOST_PID=<running-vibe-screen-host-pid>

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m vibescreen_evidence.soak \
  --serial "$EVIDENCE_SERIAL" \
  --preset 2h \
  --interval 30s \
  --package dev.telemachus.display \
  --host-pid "$HOST_PID" \
  --telemetry-jsonl "$EVIDENCE_DIR/soak-2h/host-telemetry.jsonl" \
  --require-stream-telemetry \
  --output-jsonl "$EVIDENCE_DIR/soak-2h/samples.jsonl" \
  --summary-json "$EVIDENCE_DIR/soak-2h/summary.json"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m vibescreen_evidence.soak_report \
  --summary "$EVIDENCE_DIR/soak-2h/summary.json" \
  --samples "$EVIDENCE_DIR/soak-2h/samples.jsonl" \
  --host-telemetry "$EVIDENCE_DIR/soak-2h/host-telemetry.jsonl" \
  --output "$EVIDENCE_DIR/soak-2h/exact-window-report.json"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m vibescreen_evidence.host_rss_gate \
  --summary "$EVIDENCE_DIR/soak-2h/summary.json" \
  --samples "$EVIDENCE_DIR/soak-2h/samples.jsonl" \
  --output "$EVIDENCE_DIR/soak-2h/host-rss-gate.json"
```

The existing make soak-2h target on this origin/main revision does not pass
HOST_PID through to vibescreen_evidence.soak, so the direct command above is
the current-main way to collect host.rss_kb. Open PR #158 contains a Makefile
wrapper for this path, but it was not merged at this preflight.

## Non-claims

- This record does not prove any Host RSS stability result.
- This record does not prove ScreenCaptureKit capture, HEVC encode/decode,
  stream stats, input, reconnect, latency, LAN, Internet, iOS, or HarmonyOS
  behavior.
- This record does not close the README Host RSS no-growth gate.
- This record is not Xiaomi 13/fuxi evidence.

