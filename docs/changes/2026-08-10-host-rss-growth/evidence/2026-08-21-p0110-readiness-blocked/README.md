# 2026-08-21 P0110 Host RSS readiness: blocked

Created: 2026-08-20T16:45:00Z
Device: nubia P0110 / pacific / Android 16 / serial <redacted-adb-serial>
Repository: be9381179a7f5b6a9ea5e97d6a77ad486a026ca7 (origin/main)

## Verdict

Blocked before any Host RSS diagnostic window. This is readiness evidence only;
it does not close the short Host memory diagnostic gate and does not close the
formal two-hour Host RSS no-growth gate.

The target Android device was online and the Android coordination lock was
available for a read-only identity check. A current-source macOS Host executable
and Android debug APK were buildable, and the relevant evidence tools passed
their offline tests. The real stream and memory windows were not started because
the current-source Host could not be installed at the stable /Applications/Vibe
Screen.app path with the required stable signing identity. The existing
installed Host is signed and TCC-authorized, but its executable hash does not
match the current source build, so using it would not produce current-source
gate evidence.

## Readiness facts

- Worktree: <codex-worktrees>/1287/vibe-screen on branch
  codex/host-rss-readiness, synced to origin/main at
  be9381179a7f5b6a9ea5e97d6a77ad486a026ca7.
- Main worktree <workspace-root> was not modified.
- Device lock: /tmp/vibe-screen-device-android.lock was acquired with Python
  fcntl.flock(LOCK_EX | LOCK_NB) for read-only checks and released.
- Device: <redacted-adb-serial>, manufacturer nubia, model P0110, device pacific,
  Android 16, SDK 36, fingerprint
  nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys.
- Display/power: 1264x2800, density 560, boot completed, AC powered,
  battery 100%, temperature 33.0 C.
- ADB reverse already existed: UsbFfs tcp:54321 tcp:54321.
- Android package dev.telemachus.display was installed from a previous run,
  versionCode 100000, versionName 0.0.0, lastUpdateTime
  2026-08-20 20:39:22. It was not reinstalled in this readiness pass.
- Current-source Host executable:
  baseline/MacHost/.build/release/Vibe Screen, SHA-256
  2e65cf79f8a84d5739b8f92c331cf8eea1b03a121f8a1e7ec3dae603fc4863d1.
- Installed Host executable: /Applications/Vibe Screen.app/Contents/MacOS/Vibe
  Screen, SHA-256
  c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996.
- Installed Host signing: bundle id dev.telemachus.display, authority Vibe
  Screen Dev, CDHash 2fe65fd5cd69c80249140da3f139cfa68037c5c2, no
  entitlements.
- Read-only system TCC rows for dev.telemachus.display: Screen Capture allowed
  and Accessibility allowed. The user TCC database had no matching rows.
- Codesigning identities visible to this shell: 0 valid identities found.
- python3 scripts/macos_dev_host.py preflight failed before writing a report
  because Vibe Screen Dev is unavailable in the keychain and ad-hoc signing is
  refused for local device reruns.
- Active developer directory: /Library/Developer/CommandLineTools; xcodebuild
  -version fails because full Xcode is not active.

## What was not run

- No formal make soak-2h run was started.
- No 10-17 minute vibescreen_evidence.host_memory_diagnostic run was started.
- No Host process was launched for a current-source stream.
- No Android APK install, Activity launch, touch/input, reconnect, or destructive
  device operation was performed.

These omissions are intentional: without a current-source, stable-signed,
TCC-authorized Host, the resulting stream and memory evidence would not be
valid for the current source tree.

## Related fix

This pass found a separate executable-readiness issue: the repository soak-30m,
soak-2h, and soak-8h Makefile targets did not pass Host PID to
vibescreen_evidence.soak. Without --host-pid, samples.jsonl does not contain
host.rss_kb, so host_rss_gate would remain insufficient even after a
full-duration run. The Makefile now supports an optional HOST_PID variable for
the raw soak targets, adds a `host-rss-gate` target for evaluating an existing
two-hour evidence package, and adds `soak-2h-host-rss-gate` to fail fast when a
formal run is requested without HOST_PID. The Host RSS instructions were updated
to use those targets.

## Files

- README.md - human-readable readiness summary and non-claims.
- readiness.json - machine-readable blocked/readiness record.
- commands.txt - command ledger for this pass.
- host-preflight-output.txt - raw fail-closed macOS Host preflight output.
- SHA256SUMS - checksums for this evidence directory.

## Verification

- git fetch origin --prune and checkout of codex/host-rss-readiness from
  origin/main: passed.
- git rebase origin/main after origin/main advanced to
  0bf426dc657d2068f82cb93d897d89226b3c0524: passed.
  The Makefile conflict was resolved by keeping the Phase 2 tablet manifest
  variables/targets from main and the Host RSS `HOST_PID`, `require-host-pid`,
  `host-rss-gate`, and `soak-2h-host-rss-gate` readiness entries from this
  branch.
- git rebase origin/main after origin/main advanced to
  be9381179a7f5b6a9ea5e97d6a77ad486a026ca7: passed with no conflicts.
- make baseline-macos-build: passed; current-source Host SHA-256 recorded
  above.
- make baseline-macos-self-test: passed Host, transport, reliability, Protocol
  v1, and video-encoder self-tests.
- make baseline-android-apk: passed; APK SHA-256
  55768692252a81b3fd6c074cd3fe82c5abf5f0fca2963f1deb13014a9e8e0fcc.
- make protocol: passed; 36 contract tests OK.
- PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest discover -s
  tools/tests -v: passed; 191 tests OK.
- make -n soak-2h EVIDENCE_SERIAL=<redacted-adb-serial> EVIDENCE_DIR=.build/evidence
  HOST_PID=12345: dry-run now includes --host-pid 12345.
- make -n host-rss-gate EVIDENCE_DIR=.build/evidence: dry-run derives the
  exact-window report and then runs the fail-closed Host RSS gate evaluator.
- make -n soak-2h-host-rss-gate EVIDENCE_SERIAL=<redacted-adb-serial>
  EVIDENCE_DIR=.build/evidence HOST_PID=12345: dry-run now chains the two-hour
  soak and the fail-closed Host RSS gate target.
- make soak-2h-host-rss-gate EVIDENCE_SERIAL=<redacted-adb-serial>
  EVIDENCE_DIR=.build/evidence: exits before the two-hour run when HOST_PID is
  unset.
- git diff --check: passed.

## Required next step

Restore a stable local codesigning identity, then rebuild and install the
current-source Host at /Applications/Vibe Screen.app so the existing TCC grant
can be verified against the exact binary intended for the run:

    security find-identity -v -p codesigning | grep '"Vibe Screen Dev"'
    make baseline-macos-dev-install
    python3 scripts/macos_dev_host.py preflight --install-path "/Applications/Vibe Screen.app"

After preflight passes, start that installed Host with
VIBE_SCREEN_TELEMETRY_PATH, establish a stable P0110/pacific stream, and run a
10-17 minute short diagnostic. Only a later complete two-hour run evaluated by
vibescreen_evidence.host_rss_gate can close the Host RSS no-growth gate.
