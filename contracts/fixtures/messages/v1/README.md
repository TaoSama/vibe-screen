# Protocol v1 cross-platform fixtures

These fixtures pin the bytes exchanged by the runnable macOS/Android Protocol
v1 adapter. JSON inputs use fixed message IDs, correlation IDs, session data,
epochs, and monotonic timestamps. `manifest.json` records the expected payload
case, transport channel, byte length, and SHA-256 digest for every binary.

Regenerate them with the repository-pinned Buf version:

```bash
python3 contracts/fixtures/messages/v1/generate.py
```

Verify that checked binaries still match their JSON sources:

```bash
python3 contracts/fixtures/messages/v1/generate.py --check
```

The `.binpb` control files contain raw serialized `Envelope` messages. A TCP
adapter wraps each in channel `1` plus a four-byte big-endian payload length.
`media_packet.bin` is the channel `2` payload: protobuf-varint header length,
serialized `MediaPacketHeader`, then the fixed Annex-B access unit recorded in
the manifest. `upgrade_offer.bin` (`0d`) and `upgrade_acknowledgement.bin`
(`0d01`) pin the legacy-to-v1 upgrade exchange that occurs before framed data.

Additive protobuf changes must preserve decoding of these bytes. Do not rewrite
an existing fixture to hide an incompatible change; add a new protocol package
for incompatible wire semantics.
