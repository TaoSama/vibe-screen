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
  private trusted network. It is separate from Internet mode and must not be
  presented as end-to-end encrypted.
- Internet mode includes development-preview Protocol v1 AES-256-GCM application
  records for control and media plus locally verified direct and forced-coturn
  paths. A historical Nubia P0110 run additionally covers Android/macOS
  interoperability with synthetic media on its recorded source commit. These
  results are implemented protections, not a shipped or stable security
  guarantee, and do not prove real screen capture, public-network traversal,
  recovery, latency, or soak behavior. They provide no iOS or HarmonyOS
  real-device security evidence.
- Public NAT/TURN deployment, production account/session authority and automatic
  pairing/profile issuance, cross-service revocation propagation, active TURN
  allocation termination, authoritative coturn usage accounting, multi-node
  signaling/relay state, and real-capture public-network and soak evidence remain
  release gates.
- The private `CGVirtualDisplay` API may change without notice and can affect
  compatibility and distribution.
