# Vibe Screen {{VERSION}} — development preview

This is a development preview built from tag `{{TAG}}` at commit `{{COMMIT}}`.
It is not a stable or supported release. Review the current limitations in the
[README](https://github.com/TaoSama/vibe-screen/blob/{{TAG}}/README.md) and
[security policy](https://github.com/TaoSama/vibe-screen/blob/{{TAG}}/SECURITY.md)
before running it.

## Included artifacts

- `Telemachus-macos-{{VERSION}}-<arch>.zip`: macOS host with an ad-hoc signature.
  It is **not** Developer ID signed or notarized, so macOS may block it.
- `Telemachus-android-{{VERSION}}-debug.apk`: Android development APK signed with
  the workflow's ephemeral debug key. It is **not** a production-signed APK and
  is not upgrade-compatible with another debug or production signing key.
- `VibeScreen-ios-simulator-{{VERSION}}.zip`: unsigned simulator-only iOS
  build. It cannot be installed on a physical iPhone or iPad.
- `SHA256SUMS`: SHA-256 digests for every distributed archive, APK, notices
  bundle, and SBOM.
- `vibe-screen-{{VERSION}}.spdx.json`: SPDX 2.3 runtime dependency SBOM.
- `vibe-screen-{{VERSION}}-notices.zip`: project and third-party license notices.

Verify downloaded files from the directory containing them:

```bash
shasum -a 256 -c SHA256SUMS
```

## What changed

Summarize user-visible and engineering changes since the previous tag. Keep
roadmap work and unverified behavior out of this section.

- TODO before publishing this draft.

## Verification

Record the exact automated and real-device checks represented by this release.
Compilation alone is not device acceptance.

- CI build and test jobs: TODO before publishing this draft.
- Real-device evidence: TODO or explicitly state that none was collected.

## Known limitations

- Matching macOS/Android builds upgrade the main USB/LAN session to Protocol v1
  while retaining an explicit legacy fallback. Protocol v1 real-device
  acceptance, Xiaomi 12 acceptance, and the two-hour soak remain open gates.
- Trusted LAN mode is authenticated but unencrypted and must not be used on an
  untrusted network.
- Developer ID signing, Apple notarization, Android production signing, App
  Store distribution, and iOS device installation are not part of this draft.
