# Protocol contracts

`proto/vibescreen/protocol/v1/` is the source of truth for Vibe Screen control
messages and media metadata. Swift and Kotlin bindings will be generated from
the same schema when the legacy baseline adapters are integrated.

Run:

```bash
make protocol
```

The check formats, lints, compiles, and compares the schema with
`fixtures/v1.binpb`. The fixture is the initial Protocol v1 compatibility
baseline. Additive compatible changes keep it unchanged; intentional breaking
changes require a new protocol package/version rather than replacing the v1
fixture.

The native iOS bindings are checked in. After an additive schema change run:

```bash
apps/ios/Scripts/generate-protocol.sh
swift build --package-path apps/ios
swift run --package-path apps/ios vibescreen-ios-selftest
```

The generator pins SwiftProtobuf/protoc tooling by immutable revision. CI
regenerates bindings and fails if checked output drifts.

Compatibility policy:

- never reuse field numbers or enum values;
- reserve removed names and numbers;
- negotiate capabilities before sending optional behavior;
- use a new versioned package for an incompatible wire change.
