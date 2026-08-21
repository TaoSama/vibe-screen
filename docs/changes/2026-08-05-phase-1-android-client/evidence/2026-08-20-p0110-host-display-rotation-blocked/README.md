# P0110 rotated host-display acceptance: blocked

Created: 2026-08-20T12:27:45Z
Device: nubia P0110 / pacific / Android 16 / serial EP0110PZ0B9110300B
Repository: b9d768e55c75f03cd3cb5d20939576bc8d24ff27 (origin/main)

## Verdict

Blocked. This is readiness evidence only; it does not close the Phase 1 rotated
physical/virtual host-display acceptance gate.

The target P0110 was online and reachable with explicit
adb -s EP0110PZ0B9110300B, but the real-device run was not started because the
Android device coordination lock became occupied before the acceptance sequence,
and the current-main Host could not pass the stable signed Host preflight.

## Readiness facts

- Worktree state before this evidence write: detached HEAD at
  b9d768e55c75f03cd3cb5d20939576bc8d24ff27, equal to origin/main, with no
  source diff.
- Device: adb devices -l reported
  EP0110PZ0B9110300B device usb:1-1 product:pacific model:P0110 device:pacific.
- Identity: nubia / P0110 / pacific, Android 16, SDK 36, fingerprint
  nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys.
- Display and power: 1264x2800, density 560, boot completed, AC powered,
  battery 100%.
- ADB reverse already existed: UsbFfs tcp:54321 tcp:54321.
- Final lock check found /tmp/vibe-screen-device-android.lock occupied by
  owner=codex-touch-fixed-binary-readiness, PID 29081, in worktree
  /Users/luwentao/Workspaces/dotfiles/codex/worktrees/9b47/vibe-screen.
- No Host listener was observed on TCP 54321 during the final readiness check.
- adb -s EP0110PZ0B9110300B shell dumpsys package dev.telemachus.display
  returned Unable to find package: dev.telemachus.display.

## Host preflight blocker

python3 scripts/macos_dev_host.py preflight --install-path "/Applications/Vibe Screen.app"
failed before a current-main Host rerun could be claimed:

    codesign identity 'Vibe Screen Dev' not found in the keychain. Create the 'Vibe Screen Dev' self-signed identity (or set $VIBE_SCREEN_SIGN_IDENTITY to an existing identity), or pass '--sign-identity -' for an ad-hoc build. Ad-hoc signing changes the code-signing hash on every rebuild and invalidates macOS Screen Recording/Accessibility grants.

security find-identity -v -p codesigning reported 0 valid identities found.
Passing --sign-identity - was also rejected by the preflight because local
device reruns require a stable signing identity. A read-only TCC query for
dev.telemachus.display returned no Screen Recording or Accessibility rows.

The installed /Applications/Vibe Screen.app is signed as Vibe Screen Dev, bundle
id dev.telemachus.display, CDHash
2fe65fd5cd69c80249140da3f139cfa68037c5c2, but this evidence does not treat that
older installed app as the current origin/main Host.

## Gate status

The retained host-display-rotation.json intentionally contains no completed
physical or virtual run. Running the offline gate produced
host-display-rotation-gate.json with status=failed and errors including missing
rotated physical and virtual host-display evidence.
At 2026-08-20T23:43:45Z the gate output was regenerated with the stricter
readiness fields and input-schema checks; the verdict remains failed/open.

This record does not rotate any macOS display, does not launch or install the
Android app, does not start the Host, and does not send input to the device
after the coordination lock was observed.

## Re-run

After the device lock is released, restore the stable local signing setup and
grant the exact installed Host bundle Screen Recording and Accessibility. Then
build and install the current main artifacts and run the real acceptance pass:

    security find-identity -v -p codesigning | grep '"Vibe Screen Dev"'
    make baseline-macos-dev-install
    python3 scripts/macos_dev_host.py preflight --install-path "/Applications/Vibe Screen.app"
    make baseline-android-apk
    adb -s EP0110PZ0B9110300B reverse tcp:54321 tcp:54321
    adb -s EP0110PZ0B9110300B install -r -t baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
    adb -s EP0110PZ0B9110300B shell am start -S -W -n dev.telemachus.display/.MainActivity --ez auto_connect true

For both an existing physical Mac display and a virtual display, rotate the host
display itself to 90, 180, or 270 degrees, keep the client transform
client-local, and retain device identity, before/rotated host display snapshots,
Android screenshot, corner/center touch matrix, Host log, Android logcat, stable
stream/no-teardown result, and proof that the original macOS rotation was
restored. Then summarize those artifacts in host-display-rotation.json and run:

    PYTHONPATH=tools python3 -m vibescreen_evidence.host_display_rotation_gate \
      docs/changes/2026-08-05-phase-1-android-client/evidence/<run>/host-display-rotation.json \
      --output docs/changes/2026-08-05-phase-1-android-client/evidence/<run>/host-display-rotation-gate.json \
      --check-artifacts
