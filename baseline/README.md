# Imported application baseline

This directory started from selected application sources at Telemachus commit
`a5dd1298870846d749175812f936ceebfd8b6b69`, imported on 2026-08-04, and has
since been modified in this repository. Telemachus is a SideScreen derivative;
both projects' MIT notices remain under `baseline/` and
`third_party/telemachus/`.

The imported baseline is intentionally kept separate from the stable contracts in
`contracts/`. It exists to preserve a buildable host/client vertical slice
while characterization tests are added and responsibilities are extracted.
Do not perform broad renames or module moves without first protecting the
affected behavior with tests.

Build entry points:

```bash
make baseline-macos-build
make baseline-macos-test
make baseline-android-test
make baseline-android-apk
```

See `docs/changes/2026-08-04-phase-0-baseline/UPSTREAM.md` for provenance and
the update policy.
