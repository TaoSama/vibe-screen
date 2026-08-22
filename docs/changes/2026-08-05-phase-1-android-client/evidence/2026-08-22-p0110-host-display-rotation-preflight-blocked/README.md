# P0110 rotated host-display acceptance: preflight blocked

Created: 2026-08-21T16:58:19Z
Device: nubia P0110 / pacific / Android 16 / SDK 36 / serial EP0110PZ0B9110300B
Repository: e948b96550a5e9288ea8fa6a04d9d9c6fc61251c
Base: origin/main cb87c6afa94d54a928e873b1bb2d5f4a5d5d5a3b

## Verdict

Blocked. This record keeps the rotated physical/virtual host-display acceptance
gate open. It does not claim a completed physical or virtual rotated macOS
display run.

The P0110 availability update reported a healthy USB smoke state: adb reverse
tcp:54321 was working, `dev.telemachus.display` was foreground, the device-side
connection to 127.0.0.1:54321 was established, `stream_stats` reported 55-61
fps, decoder dropped frames were 0, and the current process had no E-level
errors. The supplied screenshot was copied to
`upstream-usb-smoke-screenshot.png` and retained with SHA-256
`149160d30934af3bad5395012fdac7d51c34104dad8066fdbfd47b9690652c48`.

This task initially found `/tmp/vibe-screen-device-android.lock` already present
as an empty stale marker with no `lsof` owner. After recording that state, it
reassessed the marker by taking a non-blocking `fcntl.flock` exclusive lock,
wrote this task's owner metadata into the same lock file, and ran only read-only
preflight sampling under that lease. It did not install, launch, force-stop,
change ADB reverse mappings, rotate a host display, or send device input.

## Local Preconditions

- Worktree: `codex/host-display-rotation-readiness`, clean, rebased onto
  `origin/main` before this evidence was written.
- Display snapshot: `host-displays-before.txt` records Color LCD and DELL
  U2723QE online; DELL U2723QE reports Rotation: Supported.
- Host process: `/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen` was
  running as PID 92943 and listening on TCP 54321.
- Android sampling: held `/tmp/vibe-screen-device-android.lock` as
  `owner=codex-pr162-host-display-rotation`; `adb devices -l`, explicit
  `adb -s EP0110PZ0B9110300B` identity probes, reverse listing, foreground
  activity, loopback connection state, app log tail, and screenshot capture were
  recorded. The device was nubia P0110 / pacific / Android 16 / SDK 36.
- Lock release: `device-lock-release.txt` records that PID 77019 was terminated,
  no process retained `/tmp/vibe-screen-device-android.lock`, the remaining
  owner-matching stale file was removed, and
  `/tmp/vibe-screen-device-android-test.lock` was left untouched.
- Host preflight: blocked because `scripts/macos_dev_host.py preflight` could
  not find the stable `Vibe Screen Dev` codesigning identity. Ad-hoc signing is
  refused for local device reruns because it invalidates Screen Recording and
  Accessibility grants.
- TCC visibility: read-only sqlite access to the user TCC database returned
  `authorization denied`, so Screen Recording and Accessibility authorization
  for the installed Host could not be proven from this task.

## Gate Status

`host-display-rotation.json` intentionally contains no completed runs. Running
the offline gate with `--check-artifacts` must return `status=failed`, including
missing rotated physical and virtual host-display evidence. This preserves the
open gate until a fresh exclusive real-device pass retains both display kinds.

## Next Attempt

Restore the stable `Vibe Screen Dev` signing identity and a visible matching
TCC state, then rerun the runbook from
`docs/runbook/host-display-rotation-acceptance.md` during a fresh exclusive
device window. All ADB commands for this hardware must use
`adb -s EP0110PZ0B9110300B`, and the device identity must remain nubia P0110 /
pacific / Android 16 / SDK 36.
