# Phase 3 provenance and dependency audit

Audit date: 2026-08-04

This inventory separates code actually copied into the repository, engineering
lineage inherited through that copy, standards used as design inputs, and projects
mentioned elsewhere as possible references. A mention is not a dependency or a
claim that its code was used.

## Copied source and inherited lineage

| Project | Repository | Immutable revision | License | Phase 3 use | Copied code? | Preserved attribution |
| --- | --- | --- | --- | --- | --- | --- |
| Telemachus | `https://github.com/aaditagrawal/telemachus` | commit `a5dd1298870846d749175812f936ceebfd8b6b69`; annotated tag `v0.0.5-experimental-graceful-shutdown` peels to this commit | MIT; bundled Android dependencies include Apache-2.0 notices | `baseline/` is the inherited macOS/Android tree in which the Phase 3 policy adapters are being developed; its existing USB/LAN, media, input, pairing-token, queue, reconnect, and telemetry behavior forms the integration baseline | **Yes**: source snapshot under `baseline/`; Phase 3 additions themselves were not found in the pinned upstream and are repository-local work | `baseline/LICENSE`, `baseline/NOTICE`, `baseline/licenses/Apache-2.0.txt`; byte-identical inventory copies under `third_party/telemachus/` |
| SideScreen | `https://github.com/tranvuongquocdat/SideScreen` | commit `a651a81b7d6468c7a564c038551872d3346a2d55`; release tag `0.11.1` is `50148bc2cdddf36d030f7b4021c87618808f91a9` | MIT | foundational virtual display, capture, encoding, ADB/TCP transport, Android decode, wireless pairing, and touch lineage inherited through the Telemachus derivative | **Indirectly yes**: the Telemachus snapshot contains SideScreen-derived code; this Phase 3 documentation/code audit found no separately copied SideScreen Phase 3 code | original SideScreen copyright and MIT terms are retained in `baseline/LICENSE`; origin and scope are retained in `baseline/NOTICE` and the Android/macOS credits |

The Telemachus tag object is
`1b02006403abe5e055bf697d13adf8191950ed62`; its peeled commit is the immutable
source pin above. Recording both avoids confusing an annotated tag object with
the source revision.

### Integrity evidence

At audit time:

| File pair / upstream file | SHA-256 |
| --- | --- |
| pinned Telemachus `LICENSE`, `baseline/LICENSE`, `third_party/telemachus/LICENSE` | `28cee4528221feebcdfde6fe80275faa22a6ff2b6d1f85f5a93bb9fb9f2ac3df` |
| pinned Telemachus `NOTICE`, `baseline/NOTICE`, `third_party/telemachus/NOTICE` | `a6ac28eb883cb975f0d2a8c0435de15e875c9f314b50d8618e3f43a3d0830a03` |
| `baseline/licenses/Apache-2.0.txt`, `third_party/telemachus/licenses/Apache-2.0.txt` | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |

The SideScreen license at the pinned revision hashes to
`72dcf545af4a8b2ff61c41926063b2357153db53ddc68d6e90aa7503766dee37`.
It is not expected to be byte-identical to the derivative's combined MIT file,
which also records Telemachus contributors; the original copyright and permission
terms remain present.

## Phase 3 implementation dependencies

| Component | External runtime dependency introduced by Phase 3 | License consequence |
| --- | --- | --- |
| `packages/security/` | none; Go standard library only | no new third-party code/license |
| `services/relay/` | none; Go standard library only | no new third-party code/license |
| `services/signaling/` | none; Go standard library only | no new third-party code/license |
| macOS Internet transport | stasel WebRTC M150 XCFramework through SwiftPM | BSD-3-Clause binary dependency; pinned source/binary provenance and license are retained in the target resource bundle |
| Android Internet transport | webrtc-sdk Android M144 AAR plus Gson 2.13.1 | binary/runtime dependencies; exact artifacts must be in SBOM and complete WebRTC/Gson license materials must ship in the APK notices |
| protocol and Python simulations | Buf/Protobuf tooling already used by the repository; Python standard library only for Phase 3 scripts | no copied implementation from an external streaming project |
| TURN data plane | coturn source tag `4.7.0`, commit `678996a52954ddc7a44afd9f72f5b5c647e41083`; Compose image `coturn/coturn:4.7.0-r0@sha256:99bf5bf6ab1c119862d0c3d2dfb2bbf805a86a131492cab18c148be64ae7d978`, image-build revision `aa685e2669bac662d553a3d8eef6412d95ba7664` | no source/image layer copied; runtime is coturn BSD-3-Clause plus bundled distribution licenses. Deployment must archive the image SBOM/notices for the exact digest |

### WebRTC and signaling runtime dependencies

| Project | Repository/artifact | Immutable version | License | Use and copy status |
| --- | --- | --- | --- | --- |
| stasel WebRTC | `https://github.com/stasel/WebRTC` | tag `150.0.0`, package commit `6ed87f05368632f71dc95c89c14c051561710925`, declared Google WebRTC source `1f975dfd761af6e5d76d28333191973b258d82a8`, XCFramework SHA-256/SwiftPM checksum `f9890492b0016e4c88ab20f07867b8b420054caedc8a692b2ec6ac041f3cf6b2` | BSD-3-Clause | prebuilt macOS ICE/DTLS/SCTP/SDP/DataChannel runtime linked by SwiftPM; no source copied; license and provenance retained under `baseline/MacHost/Sources/Phase3/InternetTransport/ThirdParty/` |
| webrtc-sdk Android | release repository `https://github.com/webrtc-sdk/android`, Maven `io.github.webrtc-sdk:android:144.7559.09` | tag `v144.7559.09`, release commit `a46e9a7f63ce2b531252313f4e81754998e78f9a`, WebRTC source `b1800a61db8320af5c14456c13622d8b85b1ed39`, AAR SHA-256 `34cf91dd7497e5fe88adb76ba29ccae35db42dd6614ce548b79ce037b6d634d5` | release wrapper MIT; WebRTC BSD-3-Clause; upstream bundle contains additional licenses/notices/patent material in `Licenses/WEBRTC.md` | prebuilt Android PeerConnection/DataChannel runtime distributed inside APK; no source copied |
| Gson | `https://github.com/google/gson`, Maven `com.google.code.gson:gson:2.13.1` | tag `gson-parent-2.13.1`, peeled commit `257bee9eff81889893ca02a6925aa1b620378e9e`, artifact SHA-256 `94855942d4992f112946d3de1c334e709237b8126d8130bf07807c018a4a2120` | Apache-2.0 | Android signaling JSON runtime; no source copied; license/metadata retained under `third_party/gson/` |

The Android WebRTC AAR does not embed license files itself. The repository now
retains the fixed release wrapper MIT license, WebRTC BSD-3-Clause license,
PATENTS, machine-readable metadata and the release repository's combined
third-party notice bundle under `third_party/webrtc-android/`; Gradle verifies
their hashes and packages them in application notices. The combined bundle is
the publisher-supplied inventory for this release and is not represented as an
independently regenerated M144 source-tree audit.

The broader concurrent repository also declares Swift Protobuf for the iOS
Protocol v1 package:

| Project | Repository | Immutable revision | License | Use | Copied code? |
| --- | --- | --- | --- | --- | --- |
| Swift Protobuf | `https://github.com/apple/swift-protobuf.git` | commit `c6fe6442e6a64250495669325044052e113e990c`, tag `1.32.0` | Apache-2.0 | iOS generated Protocol v1 models and runtime | generated `.pb.swift` sources plus runtime dependency; no hand-copied implementation |

It was not introduced by the Phase 3 documentation change, but it is part of the
current release dependency inventory and is now included in root `THIRD_PARTY.md`
and `NOTICE`; its exact license remains bundled by the iOS project.

The relay control service implements TURN REST-style credential derivation and
the Phase 3 Compose profile runs the pinned external coturn data plane beside it.
Neither source nor image layers are vendored. Local coturn 4.16.0 execution is
integration evidence for configuration/protocol behavior; it is not evidence
that the pinned 4.7.0-r0 container or a public deployment was executed here.

## Ecosystem projects reviewed for actual use

| Project | Repository | License | Phase 3 audit result | Copied code? |
| --- | --- | --- | --- | --- |
| node-mac-virtual-display | `https://github.com/enfp-dev-studio/node-mac-virtual-display` | tag `v1.0.11`, commit `f506dbf93b6534a5f43476931c7667ac464573d5` | MIT | display identity/lifecycle/HiDPI research; no Phase 3 Internet/security use | No |
| FreeDisplay | no canonical repository/revision selected | unknown | an earlier planning mention was removed from active architecture claims because it was ambiguous | No; no license or implementation may be inferred |
| Sunshine | `https://github.com/LizardByte/Sunshine` | tag `v2026.516.143833`, commit `14ffa6fdaa53f7b51512be2b3d24f3939695403c` | GPL-3.0-only | low-latency media/input architecture research only | No |
| Moonlight Qt | `https://github.com/moonlight-stream/moonlight-qt` | tag `v6.1.0`, commit `f786e94c7b2f943e24e65d7d74deb539b827fc84` | GPL-3.0-only | client decode/input experience research only | No |
| Weylus | `https://github.com/H-M-H/Weylus` | tag `v0.11.4`, commit `10a279b5ad203132b696f88b9596f91559e8e785` | AGPL-3.0-or-later; some contributions separately marked BSD-3-Clause | touch/stylus coordinate research only | No |
| RustDesk | `https://github.com/rustdesk/rustdesk` | tag `1.4.9`, commit `6c578292e8ebbbec708b76986ba8c4bc7c509747` | AGPL-3.0-only | NAT traversal/relay operations research only | No |

The revisions above are the stable reviewed revisions recorded by the repository's
root `THIRD_PARTY.md`. FreeDisplay remains deliberately unresolved and is not an
active reference. If a future change consults or copies any project, it must
record the exact reviewed revision and files. GPL/AGPL code may not be copied into
this MIT-derived source tree without an explicit project licensing decision and
complete compliance work.

## Standards and algorithms

The Phase 3 design uses public specifications including WebRTC, ICE, STUN, TURN,
ECDSA-P256, ECDH-P256, HKDF-SHA-256, and AES-GCM. Referencing a public protocol or algorithm does
not copy an implementation. The code uses platform/Go standard-library primitives
where present and must use an audited implementation rather than translating code
from a copyleft project.

## Audit procedure for future changes

1. Before adding a WebRTC SDK, coturn image, crypto library, signaling framework,
   or copied example, resolve its immutable source revision and distribution
   artifact digest.
2. Record repository URL, revision/tag, package coordinate, license/SPDX,
   copyright/NOTICE, modified files, exact use, static/dynamic/service boundary,
   and whether any source was copied.
3. Preserve upstream files and source headers; regenerate Android/macOS/server
   notices and SBOMs from release dependencies.
4. Compare implementation files against GPL/AGPL references before public release
   and remove or reimplement any unapproved copied material.
5. Re-run license, notice, artifact, and secret checks for every release.

## Verification commands

```bash
git ls-remote https://github.com/tranvuongquocdat/SideScreen.git refs/heads/main refs/tags/0.11.1
git ls-remote https://github.com/aaditagrawal/telemachus.git 'refs/heads/main' 'refs/tags/v0.0.5-experimental-graceful-shutdown*'
shasum -a 256 baseline/LICENSE baseline/NOTICE \
  third_party/telemachus/LICENSE third_party/telemachus/NOTICE \
  baseline/licenses/Apache-2.0.txt third_party/telemachus/licenses/Apache-2.0.txt
rg -n 'github\.com|copyright|license|Sunshine|Moonlight|Weylus|RustDesk|FreeDisplay|node-mac-virtual-display' \
  baseline/MacHost/Sources/Phase3 \
  baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet \
  packages/security services/relay contracts
```

This audit found no Phase 3 copied code requiring a new `third_party/phase3/`
source snapshot. Phase 3 now does introduce binary runtime dependencies, so their
license payloads must be retained in an appropriate `third_party/` inventory and
included in application notices even though no source was copied.

## Public-release blockers found by this audit

- The repository root currently has a `NOTICE` and `THIRD_PARTY.md` but no
  `LICENSE`. The Telemachus MIT file covers the imported baseline but does not
  automatically license new Vibe Screen code.
- The macOS target retains the distribution and Google BSD text, but the upstream
  binary/header distribution's applicable AUTHORS/PATENTS/third-party inventory
  still needs a release-package audit rather than assuming one BSD file is the
  complete binary notice set.
- Android's dependency/SBOM audit is a release prerequisite and the debug APK
  passes 16 KiB alignment checks; signed release APK/AAB alignment and store
  packaging remain unproved.
- The pinned coturn image's complete SBOM and bundled notices still need to be
  archived from a working container engine before public deployment.
