# Protocol v1 AUDIO/BULK channel-security fixtures

These fixtures pin the AES-256-GCM record layer for the AUDIO and BULK secure
channels. Both the macOS (Swift/CryptoKit) and Android (Kotlin/JCA)
implementations derive the same directional traffic keys from fixed
key-derivation inputs and seal the same plaintext with the same nonce, so the
sealed records must match byte-for-byte.

`audio-bulk-records.json` contains:

- `session`: fixed session identifier, epoch, key epoch, key-derivation inputs
  (`shared_secret`, `bootstrap_secret`, `context`), the derived directional
  keys, and the 16-byte session-id hash.
- `record_format`: the on-wire layout (magic, version, header/nonce/tag byte
  counts, nonce and header layouts, AEAD algorithm, record layout).
- `records`: one entry per `(channel, sender)` direction with the fixed
  sequence number, plaintext, nonce, header, ciphertext+tag, and full record.

Regenerate the fixture with:

```bash
python3 contracts/fixtures/channel-security/v1/generate.py
```

The generator uses OpenSSL's `EVP_aes_256_gcm` and validates its output against
the project's known empty-plaintext AES-GCM vector
(`530f8afbc74536b9a963b4f1c4cb738b`) before writing the file.

Cross-platform tests that consume this fixture:

- Swift: `baseline/MacHost/Tests/TelemachusTests/ChannelSecurityAudioBulkFixtureTests.swift`
- Android: `baseline/AndroidClient/app/src/test/java/dev/telemachus/display/internet/security/ChannelSecurityAudioBulkFixtureTest.kt`

Each test derives the traffic keys from the fixture's key-derivation inputs,
constructs the session packet cipher, seals the plaintext for every
`(channel, sender)` direction, and asserts the sealed record equals the
fixture record. It also opens the fixture record and asserts the plaintext is
recovered, and that a record sealed on one channel is rejected when opened on
the other.

Do not rewrite an existing fixture to hide an incompatible change; the record
format is a cross-platform contract.
