# 2026-09-10 Nubia P0110 No-Host Internet Profile Import A11y Refresh

## Scope

This evidence records a focused no-Host Android validation for the Internet
preview session profile import dialog after the review fix that limits the
6dp cursor-edge text-layout tolerance to `EditText` only. Ordinary `TextView`
readability checks retain the stricter 2 px subpixel tolerance.

The checked UX surface is the import dialog's large-text/accessibility behavior:
visible label semantics, protected multiline input, parent-owned scrolling,
polite error announcement, IME-constrained reachability, production
`MaterialAlertDialogBuilder` sizing, balanced error-text wrapping, and
non-duplicated accessibility naming.

This is not Host-backed product-session evidence. It does not claim Android/macOS
clipboard E2E, Android/macOS file-transfer E2E, Xiaomi 13/fuxi evidence, or any
macOS Host/TCC readiness result.

## Source

| Field | Value |
| --- | --- |
| Branch | `codex/internet-profile-import-a11y` |
| Source HEAD | `c27845fef44b7908bfd8a66567cd870ad2fb21c7` |
| `origin/main` | `9f72b96050c63b78ffab0bc510c54fc036c3bfaf` |
| Reviewed product files vs source HEAD | `0` changed files |

See `metadata/source-provenance.txt` for the captured source state. The evidence
commit is intentionally separate from the product/test commit, and
`source_head` points to that product/test commit.

## Device

| Field | Value |
| --- | --- |
| Manufacturer | Nubia |
| Model | P0110 |
| Codename | pacific |
| Android | 16 |
| API | 36 |
| ADB serial | `<redacted-adb-serial>` |

See `metadata/device-identity.txt` for retained device metadata. This record must
remain Nubia P0110/pacific evidence and must not be relabeled as Xiaomi 13/fuxi
evidence.

## Host Boundary

No macOS Host was started, installed, modified, re-signed, or granted Screen
Recording, Accessibility, Microphone, or other TCC permissions for this run. No
`adb reverse tcp:54321 tcp:54321` mapping was created. The only ADB reverse
operation recorded here is read-only `adb reverse --list`.

| Boundary check | Evidence | Result |
| --- | --- | --- |
| ADB reverse before tests | `logs/adb-reverse-before-tests.txt` | Empty |
| ADB reverse after tests | `logs/adb-reverse-after-tests.txt` | Empty |
| Local listener on `tcp:54321` before tests | `logs/no-host-boundary-lsof-54321-before-status.txt` | Exit status `1` |
| Local listener on `tcp:54321` after tests | `logs/no-host-boundary-lsof-54321-after-status.txt` | Exit status `1` |
| Instrumentation test process before tests | `logs/instrumentation-pid-before-status.txt` | Exit status `1` |
| Instrumentation test process after tests | `logs/instrumentation-pid-after-tests-status.txt` | Exit status `1` |

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Focused JVM contracts | `logs/focused-control-surface-jvm.log`, `unit-test-results/` | PASS, `BUILD SUCCESSFUL in 4s` |
| AndroidTest compile | `logs/compile-debug-android-test-kotlin.log` | PASS, `BUILD SUCCESSFUL in 4s` |
| Focused instrumentation on Nubia P0110/pacific | `logs/internet-profile-import-focused-instrumentation-rerun.log`, `android-test-results/`, `android-test-report/` | PASS, `Starting 6 tests on P0110 - 16`; `Finished 6 tests on P0110 - 16`; `BUILD SUCCESSFUL in 18s` |

The final layout assertions distinguish editable cursor allowance from ordinary
text shaping: `EditText` lines use `max(2 px, 6 dp)`, while non-editable
`TextView` lines use only the fixed 2 px subpixel tolerance. To keep the error
surface inside that stricter bound on narrow/large-text P0110 layouts, the
visible import error copy is shorter and the error `TextView` uses balanced line
breaking.

The per-test raw logcat files under `android-test-results/P0110 - 16/` were
redacted before commit because the device emitted unrelated system and
third-party network telemetry during instrumentation. The retained Gradle log,
JUnit XML, textproto, and report files preserve the focused instrumentation
verdict.

## Limits

- No product Host session was active or exercised.
- No Screen Recording, Accessibility, Microphone, signing, or TCC readiness is
  proven by this evidence.
- No Android ClipboardManager <-> macOS NSPasteboard E2E transfer is proven.
- No Android/macOS file-transfer product E2E bytes-landing path is proven.
- No Xiaomi 13/fuxi evidence is produced by this run.

## Integrity

Verify retained evidence from the repository root with:

```bash
shasum -a 256 -c docs/changes/2026-08-22-android-ui-ux-audit/evidence/2026-09-10-nubia-p0110-no-host-internet-profile-import-a11y/SHA256SUMS
```
