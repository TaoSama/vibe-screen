# Pitfalls

- Do not infer glass-to-glass latency from unsynchronized Mac and device
  clocks. Use an external high-frame-rate camera and retain the raw samples.
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
  'security set-key-partition-list -S apple-tool:,apple: -l <identity>
  login.keychain-db'.
