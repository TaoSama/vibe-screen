# Imported application baseline

This directory started from selected application sources at Telemachus commit
`a5dd1298870846d749175812f936ceebfd8b6b69`, imported on 2026-08-04, and has
since been modified in this repository. Telemachus is a SideScreen derivative;
both projects' MIT notices remain under `baseline/` and
`third_party/telemachus/`.

The imported baseline consumes the stable Protocol v1 schemas from `contracts/`
through generated Swift and Java-lite bindings. Matching host/client builds
upgrade the main TCP session to Protocol v1; the inherited byte protocol remains
as a tested mixed-version fallback. The directory still preserves the buildable
vertical slice while responsibilities are extracted. Do not perform broad
renames or module moves without first protecting the affected behavior with
tests.

Build entry points:

```bash
make baseline-macos-build
make baseline-macos-test
make baseline-android-test
make baseline-android-apk
```

See `docs/changes/2026-08-04-phase-0-baseline/UPSTREAM.md` for provenance and
the update policy.
