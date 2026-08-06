# Development preview release

This runbook publishes source-derived development artifacts. It does not perform
Developer ID signing, Apple notarization, Android production signing, App Store
packaging, or physical-device acceptance.

## Release boundary

The tag workflow accepts only stable SemVer tags in the form `vMAJOR.MINOR.PATCH`
at the exact latest `origin/main` tip, after the `Phase 0 checks` push workflow
has succeeded for that commit, and creates a **draft prerelease**. Being an
ancestor of `main` is not sufficient. A draft must not be made public until a
maintainer replaces every TODO in its notes and verifies the artifacts.

The workflow produces:

- an ad-hoc signed, unnotarized macOS ZIP for the runner architecture;
- an APK signed by the workflow's ephemeral Android debug key;
- an unsigned iOS Simulator ZIP, not an IPA or device build;
- sorted SHA-256 checksums, an SPDX 2.3 runtime dependency SBOM, and a notices
  archive.

The debug APK's dependency license inventory and SBOM are generated from
`debugRuntimeClasspath`, matching the distributed APK. Before checksums are
written, the workflow decompresses every final APK/ZIP and scans its contents,
the final SBOM, and the notices archive for credential material, hardware
identifiers, and local user paths. Any finding blocks the draft.

These steps are repeatable from the tagged source and pinned dependencies. They
do not promise byte-for-byte identical compiler output; in particular, a fresh
Android debug key changes the APK and its digest. `SHA256SUMS` records digests
for integrity checks within that individual workflow run; it is not
cryptographically signed and does not authenticate file origin.

## Prepare the tag

1. Start from a clean checkout of the latest `main` and inspect the complete
   diff since the previous tag.
2. Run the gates in `docs/testing.md`. Record commands, results, real-device
   evidence, and unverified behavior for the release notes.
3. Push `main` and wait for its `Phase 0 checks` push workflow to succeed. Fetch
   `origin/main` again and verify the tag target is still exactly that tip.
4. Confirm `THIRD_PARTY.md`, `NOTICE`, dependency locks, bundled licenses, and
   the release notes template cover every distributed runtime dependency. For
   macOS WebRTC M150, verify the component notice bundle SHA-256 against
   `WEBRTC_PROVENANCE.md`; packaging and release assembly fail if it is absent
   or changed without review.
5. Confirm GitHub private vulnerability reporting is enabled. The public bug
   tracker is not an acceptable security-reporting channel.
6. Create and push a new annotated tag. Never move or reuse a published tag:

   ```bash
   git tag -a vMAJOR.MINOR.PATCH -m "chore(release): vMAJOR.MINOR.PATCH"
   git push origin vMAJOR.MINOR.PATCH
   ```

Pushing the tag is the only release trigger. It does not publish directly; the
workflow creates a draft prerelease after all platform jobs pass.

## Review the draft

1. Confirm all expected assets exist and their filenames identify the signing
   and platform boundaries described above.
2. Download every asset into one directory and run:

   ```bash
   shasum -a 256 -c SHA256SUMS
   ```

3. Inspect the SPDX JSON, notices archive, macOS bundle version, APK version,
   and iOS Simulator bundle version. They must all match the tag.
4. Replace every TODO in the draft notes. State actual CI/device evidence and
   retain the development-preview, security, signing, and notarization warnings.
5. Publish only as a prerelease while `README.md` and `SECURITY.md` describe the
   project as unsupported development software.

## Failed or withdrawn release

If a job fails, fix the source on `main` and create a new version/tag. Do not
replace an immutable public tag. A draft created from a bad run may be deleted;
record why before rerunning. If a published asset is unsafe, mark the release
withdrawn, remove the asset, document the affected hashes, and publish a new
version rather than silently replacing files.
