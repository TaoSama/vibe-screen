# Authority session-profile current-base slice - 2026-08-23

This evidence record covers a local, source-level Phase 3 control-plane slice on
the current base. It adds an admin-only Authority session-profile endpoint for
already registered account/device IDs, makes Authority role authorization return
the session expiry, lets Signaling adopt Authority-issued sessions as local
routing metadata only after successful remote role authorization, and makes the
Mac lease issuer reserve and sign the exact Authority-supplied `session_epoch`.

Commands run locally:

```bash
cd services/authority && go test -count=1 ./internal/authority
cd services/authority && go test -count=1 ./...
cd services/signaling && go test -count=1 ./...
python3 -m unittest tests.phase3.test_authority_session_profile_contract -v
python3 -m unittest discover -s tests/phase3 -p 'test_*.py'
GOCACHE=/tmp/vibe-screen-go-build-cache make phase3-test
cd baseline/MacHost && swift test --filter InternetSessionLeaseIssuerTests
```

Results:

- Authority focused package: passed.
- Authority full package set: passed.
- Signaling full package set: passed.
- Phase 3 Python session-profile contract: passed.
- Phase 3 Python discovery: 169 tests passed.
- `make phase3-test`: passed with a temporary `GOCACHE` after the default
  user Go build cache reported missing cached standard-library objects during
  the initial `go vet` step. The release-gate summary remained `OPEN`.
- MacHost targeted XCTest: blocked in this local environment because SwiftPM
  could not import `XCTest` (`no such module 'XCTest'`). No XCTest pass is
  claimed for this run.

Boundary:

This is unit/contract evidence only. It does not prove Mac/Android automatic
profile invocation, automatic account/device registration, Android UI import,
public Internet, real ScreenCaptureKit or CGDisplayStream capture, Android
MediaCodec decode, active PeerConnection or TURN allocation disconnect, network
handoff, latency, or soak. No Android device command was run for this record.
