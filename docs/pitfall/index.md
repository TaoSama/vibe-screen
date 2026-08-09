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
  ('Telemachus Dev') so the hash stays constant and one grant survives rebuilds;
  'package_macos.py' now defaults to it (override with $TELEMACHUS_SIGN_IDENTITY
  or '--sign-identity -'). If codesign fails with 'errSecInternalComponent',
  authorize the private key for non-interactive use once via
  'security set-key-partition-list -S apple-tool:,apple: -s -k "$KEYCHAIN_PASSWORD"
  "$HOME/Library/Keychains/login.keychain-db"' (supply the keychain password
  through the '$KEYCHAIN_PASSWORD' variable rather than embedding it, and
  verify the exact 'security(1)' syntax on the target macOS version). CI runners
  lack the self-signed identity, so 'package_macos.py' now falls back to an
  ad-hoc signature there automatically.
