# WebRTC binary provenance

- Distribution repository: <https://github.com/stasel/WebRTC>
- Swift package tag: `150.0.0`
- Immutable package revision: `6ed87f05368632f71dc95c89c14c051561710925`
- Binary artifact: `WebRTC-M150.xcframework.zip`
- SwiftPM checksum / SHA-256: `f9890492b0016e4c88ab20f07867b8b420054caedc8a692b2ec6ac041f3cf6b2`
- Upstream Google WebRTC source revision declared by the release:
  `1f975dfd761af6e5d76d28333191973b258d82a8`
- License: BSD-3-Clause plus statically linked third-party component terms.
  The unmodified distribution license is included as `WebRTC-LICENSE.md`.
  `WebRTC-M150-THIRD-PARTY-NOTICES.md` is an explicitly conservative superset
  generated from the license map at the exact Google WebRTC source revision;
  its SHA-256 is
  `896890245459abac28f8b7223f6c68090ffe3447ec95fa8ef99045e88737d3b7`.
  Both files are copied into the SwiftPM resource bundle.
- Notice generator: `scripts/generate_webrtc_m150_notices.py`, reproducing
  Google WebRTC's `tools_webrtc/libs/generate_licenses.py` at the source
  revision above (SHA-256
  `242497538da856ba1b7b50daedb59afb7f34a67439b94b69166bc8e9319e8604`).
- Ordered 32-component source manifest SHA-256:
  `8c6c2a3dc7a68fc1f86c768afa14641e71a0d279bfe9bad582a564af6560e75a`.
- Use: linked as a prebuilt macOS XCFramework implementing ICE, DTLS, SCTP,
  SDP, and data channels for the Phase 3 Internet transport.
- Code copying: no WebRTC source code was copied into Vibe Screen. The audited
  prebuilt binary is consumed through Swift Package Manager.
