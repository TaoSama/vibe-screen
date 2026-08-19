# Pitfalls

- Do not infer glass-to-glass latency from unsynchronized Mac and device
  clocks. Use an external high-frame-rate camera and retain the raw samples.
- Do not treat a stable on-device stream as proof of the two-hour no-growth
  gate. On 2026-08-09 a valid 2h Xiaomi Fuxi soak held 60 FPS with only 25
  dropped frames total, yet host RSS still climbed ~+96 KiB/min in the second
  half (net ~+18 MB / +3.7%). `leaks` reported only ~4.3 KB of true leaks, so
  the growth is reachable, slowly accumulating small-heap (MALLOC_SMALL) state,
  not a classic leak. Verify the host no-growth criterion from host RSS slope
  over the full window, and root-cause reachable growth by relaunching the host
  with MallocStackLogging and sampling `malloc_history`/`heap` (a disruptive
  relaunch that ends the current session), not by trusting FPS/drop stability.
- Do not let media backlog grow to preserve old frames. Bound the queue and
  request a keyframe when inter-frame dependencies are no longer usable.
- Do not treat private `CGVirtualDisplay` availability as guaranteed. Keep a
  physical-display capture path and document a dummy-display fallback.
- Do not reuse or renumber Protobuf fields. Reserve removed field numbers and
  names permanently.
- Do not ship the macOS host with an ad-hoc signature during iterative device
  work. Ad-hoc signing changes the code-signing hash on every rebuild, so macOS
  TCC drops the Screen Recording and Accessibility grants and forces the user to
  re-authorize after each build. Sign with a stable self-signed identity
  ('Vibe Screen Dev') so the hash stays constant and one grant survives rebuilds;
  'package_macos.py' now defaults to it (override with $VIBE_SCREEN_SIGN_IDENTITY
  or '--sign-identity'). A missing named identity fails fast. CI and intentional
  local preview builds must request ad-hoc signing explicitly with
  '--sign-identity -'. When creating the stable identity, import its private key
  with '/usr/bin/codesign' in the key ACL. If codesign still fails with
  'errSecInternalComponent', authorize the private key for non-interactive use
  once via
  'security set-key-partition-list -S apple-tool:,apple: -s -k "$KEYCHAIN_PASSWORD"
  "$HOME/Library/Keychains/login.keychain-db"' (supply the keychain password
  through the '$KEYCHAIN_PASSWORD' variable rather than embedding it, and
  verify the exact 'security(1)' syntax on the target macOS version). Do not
  reset or replace a keychain whose password is unknown; import a fresh identity
  into the current unlocked login keychain instead. Before an Android touch
  rerun, use `make baseline-macos-dev-install` followed by
  `make baseline-macos-touch-preflight`; the generated
  `.build/dev-macos-host/host-signing-and-permissions.txt` records the leaf
  certificate SHA-1, CDHash, designated requirement, binary SHA-256, and
  read-only TCC state. If the leaf certificate SHA-1 changes, treat the Host as
  a new macOS privacy identity and ask the user to grant Screen Recording and
  Accessibility to `/Applications/Vibe Screen.app` again through System
  Settings.
