# Nubia P0110 Phase 1 Android evidence

Date: 2026-08-05
Endpoint: `100.72.246.116:5555`
Hardware serial: `[redacted]`
Device: Nubia P0110 (`pacific`), Android 16 / SDK 36

The device-run debug APK has SHA-256
`37e7c2b7e107443c298a8d59d054fac027ad32021bb5eeadcb87f73d649c3892`.
It installed at `2026-08-05 01:46:06 +08:00` with Android Debug signer
certificate SHA-256
`b108fb9e0c8e5544171d57eb3be57d9fb93f332fc4954e26d5f51b20b876aa0b`.
The install-time working tree was based on
`6f7ffbe0be872390144899642636dbb24d89f120`, but its Android changes had not
yet been committed; therefore no Git commit exactly identifies the installed
tree. The device APK hash above is its exact artifact identity.

Everything added after the lease is outside this device evidence: malformed
display validation; true 90°/270° Surface rotation and dimension exchange;
Fit/Fill input inverse mapping; callback-generation isolation; bounded,
coalescing, recovery-prioritized outbound writes; typed terminal failures;
Camera Settings-return recovery; atomic negotiated capability/input-sink
installation; and strict non-blocking saturation fail-close with asynchronous
cleanup, including serialized off-UI decoder teardown and reinitialization.
Later review also separated writer lock contention from true outbound capacity
and unified wireless post-auth startup under exactly-once termination cleanup.
Those changes have only JVM/lint/build evidence and were not reinstalled. The
final offline APK identity is recorded in the parent
[`TEST.md`](../../TEST.md) and must not be attributed to this device run.

## Retained files

| File | Purpose | SHA-256 |
| --- | --- | --- |
| `actionable-error.png` / `actionable-error-ui.xml` | pre-display EOF guidance | `414382426d88ee2cf2fb2d17b97468af64d67f5303e041ef627952d53f907e5b` / `d12fafb910167ee297f441b2ec12fd231005a298351ac38a7c3707fe83e558a1` |
| `camera-blocked.png` / `camera-blocked-ui.xml` | permanent denial and Settings recovery action | `49579eed88e77b62c920c4ae37d3e48d5a19cc49c9cfbadeef3415fd57082b2d` / `dbe533161089cfbeed949831f8bb6af92d310b51ab520f2f7d8eccd81838cc4f` |
| `usb-without-camera-ui.xml` | USB UI while Camera is denied | `6d7e83ade1c202d968497af2bd6ab243d4056e7f232f6df8a7d2c2d498cd5dce` |
| `logcat.txt` | application-tag-filtered final logcat capture | `50c4b3d8ae62c4cabe8cd2fe9ed9d59314013183baff893b5c84c3468b972ce0` |

The media source was the repository's existing synthetic HEVC StreamTest. The
Mac was locked and ScreenCaptureKit exposed no real display. These files prove
Android device behavior and transport packets only; they do not prove visible
Mac pointer/window results, physical peripherals, client-side Mac display
selection, or external-camera latency.

Private diagnostic timestamps were observed and summarized in the parent test
record. The raw private log was lost during post-run filtering and is not a
retained artifact.
