# Contributing

Vibe Screen is in active Phase 0 development. Before changing behavior, read
`README.md`, `AGENTS.md`, and the active change documents under `docs/changes/`.

Keep changes small and responsibility-focused. Preserve protocol compatibility,
bounded media queues, explicit error handling, and platform module boundaries.

Before submitting work, run the relevant protocol, macOS, Android, and device
checks documented in `docs/testing.md`. Report commands and outcomes, including
blocked or unproved checks.

Open a pull request against `main` using the repository template. Keep one
problem per pull request, explain compatibility and rollback risk, and include
the exact verification evidence. Public bug reports must use the issue form and
must remove credentials, device identifiers, private network details, and
personal screen content.

Security vulnerabilities do not belong in public issues. Follow `SECURITY.md`
and use the repository's private vulnerability-reporting channel.

Copied or adapted material must be license-compatible and recorded in
`THIRD_PARTY.md` with its repository URL, immutable revision, license, copied
scope, and retained notices. Do not copy GPL/AGPL source without explicit
project-owner approval and a completed compatibility review.
