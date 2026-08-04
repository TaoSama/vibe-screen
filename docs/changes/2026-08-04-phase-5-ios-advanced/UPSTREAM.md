# Phase 5 dependency provenance

Audit date: 2026-08-04

The authoritative iOS dependency table is
[`apps/ios/THIRD_PARTY.md`](../../../apps/ios/THIRD_PARTY.md). It records URL,
immutable tag/commit, license, use scope, and whether source was copied for
SwiftProtobuf, the Protocol Buffers compiler, SideScreen, and Telemachus.

The iOS implementation was written for this repository. No code was copied
from SideScreen, Telemachus, node-mac-virtual-display, FreeDisplay, Sunshine,
Moonlight, Weylus, RustDesk, Apple sample projects, or any GPL/AGPL project.
Generated `*.pb.swift` files derive solely from this repository's Protocol v1
schemas using the recorded compiler/plugin versions.

`Package.resolved` is checked in as the machine-readable runtime pin. The exact
SwiftProtobuf Apache-2.0 license and runtime exception are retained byte-for-
byte under `apps/ios/ThirdPartyLicenses/` and added to the app Resources phase.
