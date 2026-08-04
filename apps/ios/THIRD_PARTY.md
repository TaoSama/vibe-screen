# iOS dependency and provenance record

Audit date: 2026-08-04

| Project | Immutable source | License | Use in this directory | Code copied into repository |
| --- | --- | --- | --- | --- |
| SwiftProtobuf | <https://github.com/apple/swift-protobuf>, tag `1.32.0`, commit `c6fe6442e6a64250495669325044052e113e990c` | Apache-2.0 with runtime-library exception | Swift Package runtime used by generated Protocol v1 types | Runtime source: no, resolved and linked by SwiftPM; exact upstream license: copied and bundled |
| Protocol Buffers compiler | <https://github.com/protocolbuffers/protobuf>, tag `v32.1`, peeled commit `7fcfd66022455635fa29af92987cdc0967efd4f3` | BSD-3-Clause | Build-time generator used to produce `Sources/VibeScreenProtocol/**/*.pb.swift` | No compiler source/binary copied; generated output is derived from this repository's schemas |
| SideScreen | <https://github.com/tranvuongquocdat/SideScreen>, commit `a651a81b7d6468c7a564c038551872d3346a2d55` | MIT | Existing repository architecture/protocol baseline reviewed; no iOS source existed or was copied | No |
| Telemachus | <https://github.com/aaditagrawal/telemachus>, commit/tag `a5dd1298870846d749175812f936ceebfd8b6b69` / `v0.0.5-experimental-graceful-shutdown` | MIT | Existing host/Android reliability behavior and repository Protocol v1 requirements reviewed | No iOS code; the separate repository snapshot under `baseline/` is covered by its retained LICENSE/NOTICE |

SwiftUI, UIKit, Foundation, Network, AVFoundation, CryptoKit, CoreMedia,
CoreVideo, CoreImage, UniformTypeIdentifiers, and VideoToolbox are Apple SDK
system frameworks. They are linked from the user's Xcode installation and are
not redistributed source dependencies. No Apple sample code was copied.

No node-mac-virtual-display, FreeDisplay, Sunshine, Moonlight, Weylus, RustDesk,
GPL, or AGPL code was used or copied for the iOS implementation.

The exact upstream SwiftProtobuf license (including its runtime-library
exception) is preserved at
`ThirdPartyLicenses/SwiftProtobuf-LICENSE.txt`, SHA-256
`186c5f0192a754714a7e542233ddaaad28745626e0ad32e358d3f5af00afb84a`,
and is included in the application Resources phase. The audited upstream
revision does not contain a separate `NOTICE.txt`.
