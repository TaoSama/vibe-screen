# Phase 4 technical design

The project lives in `apps/harmony/` and depends only on HarmonyOS NEXT platform
APIs. Portable TypeScript tests exercise the framework-independent core.

```text
ArkUI -> session orchestration -> Protocol v1 -> TCP control transport
   |              |                    |
 input mapper   epoch filter       AVCodec adapter -> Surface
```

The Protobuf codec is a small independent implementation limited to the Vibe
Screen schema, including unknown-field skipping. It avoids a runtime dependency
whose ArkTS compatibility and license could not be verified. Contract `.proto`
files remain the source of truth; wire golden tests must be expanded when host
bindings arrive.

The session state machine rejects invalid transitions and only renders media
whose epoch equals the accepted session. `LatestFrameQueue` holds at most one
pending encoded frame, replacing stale data rather than accumulating latency.
Transport and decoder adapters import Harmony APIs; core modules do not.

The current source includes the official TCP, Asset Store credential, and AVCodec
adapter seams. Full page/controller wiring and API-level compiler corrections
must be completed against an installed DevEco SDK because that toolchain was
not present during this change. This is not treated as a completed device port.
