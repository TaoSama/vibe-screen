# Third-party sources and design references

Audit date: 2026-08-04

This file distinguishes code that entered the repository from projects used
only as non-code design references. A reference does not grant permission to
copy its implementation.

## Source code present

| Project | Immutable source | License | Use and copy status |
| --- | --- | --- | --- |
| [SideScreen](https://github.com/tranvuongquocdat/SideScreen) | `a651a81b7d6468c7a564c038551872d3346a2d55` | MIT | Foundational virtual display, capture, encoding, ADB/TCP, Android decoding, pairing, and touch code enters indirectly through Telemachus. Copyright and MIT terms are retained. |
| [Telemachus](https://github.com/aaditagrawal/telemachus) | tag `v0.0.5-experimental-graceful-shutdown`, commit `a5dd1298870846d749175812f936ceebfd8b6b69` | MIT | Selected macOS/Android application sources were imported directly and then modified. Original `LICENSE`, `NOTICE`, and credits remain bundled. |

The retained upstream files are available at `baseline/LICENSE`,
`baseline/NOTICE`, and `third_party/telemachus/`. Android runtime dependency
notices are generated during the build and include the Apache License 2.0 text.

## Runtime dependencies

| Project | Immutable source | License | Use and copy status |
| --- | --- | --- | --- |
| [Gson](https://github.com/google/gson) | tag `gson-parent-2.13.1` (tag object `bec33dceb61708a514c675c4bcf6578345e4a888`, commit `257bee9eff81889893ca02a6925aa1b620378e9e`); Maven artifact SHA-256 `94855942d4992f112946d3de1c334e709237b8126d8130bf07807c018a4a2120` | Apache-2.0 | Android runtime dependency `com.google.code.gson:gson:2.13.1` (`pkg:maven/com.google.code.gson/gson@2.13.1`) for Phase 3 signaling JSON; no source is copied. Full license and machine-readable metadata are retained under `third_party/gson/`; upstream publishes no separate NOTICE file for this release. |
| [Protocol Buffers Java lite runtime](https://github.com/protocolbuffers/protobuf) | tag `v32.1`, commit `7fcfd66022455635fa29af92987cdc0967efd4f3`; Maven artifact SHA-256 `55b046d3213f1046a2172e28e32a2bc72bbd49aebc66a4e44b99db9fff6def8e` | BSD-3-Clause | Android runtime dependency `com.google.protobuf:protobuf-javalite:4.32.1` (`pkg:maven/com.google.protobuf/protobuf-javalite@4.32.1`) for generated Protocol v1 types; no source is copied. The exact license is retained at `third_party/protobuf/LICENSE` (SHA-256 `6e5e117324afd944dcf67f36cf329843bc1a92229a8cd9bb573d7a83130fea7d`) and bundled into Android notices. |
| [webrtc-sdk Android](https://github.com/webrtc-sdk/android) | tag `v144.7559.09`, release commit `a46e9a7f63ce2b531252313f4e81754998e78f9a`, WebRTC source commit `b1800a61db8320af5c14456c13622d8b85b1ed39`; AAR SHA-256 `34cf91dd7497e5fe88adb76ba29ccae35db42dd6614ce548b79ce037b6d634d5` | release wrapper MIT; WebRTC BSD-3-Clause; statically linked components carry the terms in the upstream notice bundle | Android runtime dependency `io.github.webrtc-sdk:android:144.7559.09` for Phase 3 ICE/DTLS/SCTP/DataChannel; no source is copied. Exact wrapper/WebRTC licenses, patent grant, metadata, and the release repository's combined third-party notice bundle are retained under `third_party/webrtc-android/` and bundled into Android notices. |
| [stasel WebRTC](https://github.com/stasel/WebRTC) | tag `150.0.0`, package commit `6ed87f05368632f71dc95c89c14c051561710925`, Google WebRTC source commit `1f975dfd761af6e5d76d28333191973b258d82a8`; XCFramework checksum `f9890492b0016e4c88ab20f07867b8b420054caedc8a692b2ec6ac041f3cf6b2` | BSD-3-Clause | macOS SwiftPM binary dependency for Phase 3 ICE/DTLS/SCTP/DataChannel; no source is copied. License and immutable provenance ship in the MacHost resource bundle. |
| [coturn](https://github.com/coturn/coturn) | tag `4.7.0`, source commit `678996a52954ddc7a44afd9f72f5b5c647e41083`; container `coturn/coturn:4.7.0-r0@sha256:99bf5bf6ab1c119862d0c3d2dfb2bbf805a86a131492cab18c148be64ae7d978`, image-build revision `aa685e2669bac662d553a3d8eef6412d95ba7664` | coturn BSD-3-Clause plus bundled container distribution licenses | External TURN/STUN data-plane image used by the Phase 3 Compose deployment; neither source nor image layers are copied into this repository. Operators must archive the image SBOM and bundled notices for each deployed digest. |
| [SwiftProtobuf](https://github.com/apple/swift-protobuf) | tag `1.32.0`, commit `c6fe6442e6a64250495669325044052e113e990c` | Apache-2.0 with runtime-library exception | macOS and iOS SwiftPM runtime for generated Protocol v1 types; runtime source is resolved rather than copied. The upstream license is retained at `apps/ios/ThirdPartyLicenses/SwiftProtobuf-LICENSE.txt` (SHA-256 `186c5f0192a754714a7e542233ddaaad28745626e0ad32e358d3f5af00afb84a`) and, with trailing whitespace normalized, at `baseline/MacHost/Sources/Phase3/InternetTransport/ThirdParty/SwiftProtobuf-LICENSE.txt` (SHA-256 `770af8291f708538d8ff885a0bbc4e045cd700531741c4f99528d435c14d7f55`); both projects bundle their respective copy. Upstream publishes no separate `NOTICE` file at this revision. |

## Build-time dependencies

| Project | Immutable source | License | Use and copy status |
| --- | --- | --- | --- |
| [Protocol Buffers compiler](https://github.com/protocolbuffers/protobuf) | tag `v32.1`, commit `7fcfd66022455635fa29af92987cdc0967efd4f3` | BSD-3-Clause | Build-time generator for iOS and MacHost Protocol v1 `*.pb.swift`; compiler source and binary are not copied. Generated files derive from this repository's schemas. |

## Non-code design references

No source, assets, or runtime dependencies from the following projects were
copied into this repository.

| Project | Reviewed revision | License | Limited use |
| --- | --- | --- | --- |
| [node-mac-virtual-display](https://github.com/enfp-dev-studio/node-mac-virtual-display) | tag `v1.0.11`, commit `f506dbf93b6534a5f43476931c7667ac464573d5` | MIT | Display identity, lifecycle, and HiDPI design research only. |
| [Sunshine](https://github.com/LizardByte/Sunshine) | tag `v2026.516.143833`, commit `14ffa6fdaa53f7b51512be2b3d24f3939695403c` | GPL-3.0-only | Low-latency media and input architecture research only. GPL source is not copied. |
| [Moonlight Qt](https://github.com/moonlight-stream/moonlight-qt) | tag `v6.1.0`, commit `f786e94c7b2f943e24e65d7d74deb539b827fc84` | GPL-3.0-only | Client decode and input experience research only. GPL source is not copied. |
| [Weylus](https://github.com/H-M-H/Weylus) | tag `v0.11.4`, commit `10a279b5ad203132b696f88b9596f91559e8e785` | AGPL-3.0-or-later for the project; some contributions separately marked BSD-3-Clause | Touch/stylus coordinate design research only. No source is copied; the project is treated as AGPL by default. |
| [RustDesk](https://github.com/rustdesk/rustdesk) | tag `1.4.9`, commit `6c578292e8ebbbec708b76986ba8c4bc7c509747` | AGPL-3.0-only | NAT traversal and relay operations research only. AGPL source is not copied. |

An earlier planning document mentioned “FreeDisplay” without recording a
canonical repository or immutable revision. No matching code was found in this
repository, the reference was removed from active architecture claims, and no
license or implementation may be inferred from that ambiguous name.

## Policy

- New copied code must record repository URL, immutable revision, license,
  copied scope, and retained notices before merging.
- GPL/AGPL source must not be copied unless the project owner explicitly
  approves the licensing model and completes compatibility review.
- Dependency-license reports do not replace source-level copyright notices.
