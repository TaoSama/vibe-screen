# Protocol contracts

`proto/vibescreen/protocol/v1/` is the source of truth for Vibe Screen control
messages and media metadata. Swift and Kotlin bindings are generated from the
same schema by their platform builds.

Run:

```bash
make protocol
```

The check formats, lints, compiles, compares the schema with
`fixtures/v1.binpb`. The fixture is the initial Protocol v1 compatibility
baseline. Additive compatible changes keep it unchanged; intentional breaking
changes require a new protocol package/version rather than replacing the v1
fixture. It also runs the deterministic business-message and transport fixture
tests under `tests/`.

## Security fixtures

`fixtures/security/v1/channel-records.json` fixes the 256-byte initial and
legacy-compatible rotated key material, both key IDs, and four AES-256-GCM
records: host-control, device-media, host-audio, and device-bulk. The records
cover all four channels and both sender directions. `make protocol` independently
recomputes HKDF-SHA256, key IDs, the rotation transcript, and every record with
a Go standard-library verifier. The Android and macOS tests also round-trip all
eight sender/channel key selections.
These are offline record-layer vectors, not WebRTC DataChannel or public-network
end-to-end evidence.

The Go reference implementation under `packages/security` intentionally remains
the Phase 3 control/media implementation. The four-channel fixture describes the
Android and macOS record layers; it does not imply Go audio/bulk support or an
audio/bulk transport API.

## Baseline TCP framing

The legacy-compatible TCP adapter starts in legacy mode. A Protocol v1 client
sends the single-byte upgrade offer `0x0d`; a supporting host replies with
`0x0d 0x01`. Only after that acknowledgement do both peers switch to Protocol
v1 framing. A missing or invalid acknowledgement leaves the connection on the
legacy adapter; Protocol v1 bytes must never be guessed from a legacy payload.

Every Protocol v1 TCP frame is:

```text
channel: uint8 | payload_length: uint32 big-endian | payload
```

Control is channel `1` and contains one serialized `Envelope`. Video is channel
`2` and contains a protobuf-varint header length, the serialized
`MediaPacketHeader`, and exactly `payload_length` bytes of Annex-B video. Audio
is channel `3` and contains a protobuf-varint header length, the serialized
`AudioPacketHeader`, and exactly `payload_length` bytes of PCM audio for
negotiated Protocol v1 sessions. Bulk file-transfer data is channel `4`. The
maximum framed payload is 16 MiB. Control is reliable and ordered; video and
audio keep independent low-latency queues even when all channels share one TCP
connection.

`fixtures/messages/v1/` contains fixed cross-platform protobuf and framing
vectors. See its README and machine-readable manifest for regeneration and
expected metadata.

The native iOS bindings are checked in. After an additive schema change run:

```bash
apps/ios/Scripts/generate-protocol.sh
swift build --package-path apps/ios
swift run --package-path apps/ios vibescreen-ios-selftest
```

The generator pins SwiftProtobuf/protoc tooling by immutable revision. CI
regenerates bindings and fails if checked output drifts.

`fixtures/client-hello-v1.hex` is a control-message wire fixture rather than a
schema descriptor. The HarmonyOS encoder must reproduce every byte, and the
generated Swift binding must decode the same Protocol v1 semantics. This
allows an independent codec and a generated binding to share one audited
compatibility case even though protobuf permits more than one valid encoding
for packed repeated scalar fields.

Compatibility policy:

- never reuse field numbers or enum values;
- reserve removed names and numbers;
- negotiate capabilities before sending optional behavior;
- binary decoders must accept additive unknown fields, but JSON projections may
  discard them and are not a field-preserving relay format;
- use a new versioned package for an incompatible wire change.

`KeyEvent.modifier_mask` keeps its original field and uses capability-gated
interpretation. Capability `27` selects the standard USB HID modifier byte
(`Control=0x01`, `Shift=0x02`, `Alt=0x04`, `GUI=0x08`, right-side variants in
`0x10...0x80`). Without it, peers retain the legacy four-bit layout
(`Shift=0x01`, `Control=0x02`, `Alt=0x04`, `GUI=0x08`). New clients collapse
right-side modifiers to the equivalent left-side legacy bit; new hosts reject
legacy high-nibble bits rather than guessing their meaning.
