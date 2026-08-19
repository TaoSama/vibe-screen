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
- Trusted LAN keeps the QR/token admission gate and now negotiates per-session
  AES-256-GCM application records for matching current macOS/Android peers.
  Nonce/replay checks are fail-closed for both control and media records. Old
  peers can continue only through an explicit plaintext legacy fallback and UI
  or logs must not describe that fallback as encrypted. Trusted LAN remains a
  private-network mode, separate from Internet mode, and must not be presented
  as public-network or TURN-relayed end-to-end encryption evidence.
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
