# Security policy

There is no stable supported release yet. Security fixes should target the
active development branch and include regression evidence.

Do not publish pairing credentials, tokens, personal screen captures, device
identifiers, or private network details in a public issue. Use
[GitHub private vulnerability reporting](https://github.com/TaoSama/vibe-screen/security/advisories/new).
If that private form is unavailable, do not open a public issue; repository
owners must enable the channel before accepting a public preview release.

## Current boundary

- USB mode inherits ADB authorization; it is not product-level device identity.
- Trusted LAN uses authenticated but unencrypted TCP and must be limited to a
  private trusted network.
- Internet E2EE, production device revocation, TURN, and relay security are
  roadmap work, not shipped protections.
- The private `CGVirtualDisplay` API may change without notice and can affect
  compatibility and distribution.
