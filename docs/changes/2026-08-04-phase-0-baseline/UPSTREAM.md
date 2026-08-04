# Upstream provenance and update policy

Audit date: 2026-08-04

## Pinned sources

| Project | Repository | Commit | License | Role |
| --- | --- | --- | --- | --- |
| SideScreen | `https://github.com/tranvuongquocdat/SideScreen` | `a651a81b7d6468c7a564c038551872d3346a2d55` | MIT | source enters indirectly through the Telemachus derivative |
| Telemachus | `https://github.com/aaditagrawal/telemachus` | `a5dd1298870846d749175812f936ceebfd8b6b69` | MIT | selected application sources imported directly, then modified |

SideScreen's latest release at audit time is `0.11.1`
(`50148bc2cdddf36d030f7b4021c87618808f91a9`). The pinned main commit is newer
and includes display sleep/wake capture recovery, so the release tag is not the
preferred engineering baseline.

The Telemachus pin is tagged `v0.0.5-experimental-graceful-shutdown`. Its
GitHub checks were green at audit time. Relevant reliability lineage includes
`a62020ef` (frame recovery), `485bc893` (frame-age/drop diagnostics),
`c907f266` (ADB retry), and `8dd8ee3a` (codec negotiation). These commits are
recorded for review; they are not cherry-picked independently because the
imported snapshot already contains them.

`baseline/` began as selected application sources from the pinned Telemachus
commit and has since been modified in this repository. Its MIT license, notice, and Apache
dependency license remain at their original relative paths for Android notice
generation and are duplicated under `third_party/telemachus/` for repository
inventory. SHA-256 comparison proves both copies match upstream.

The macOS window recovery manager, bounded unattended-restart policy, host
self-test, and release packaging script added in this repository are original
implementations for Vibe Screen. They do not copy code from
node-mac-virtual-display, FreeDisplay, Sunshine, Moonlight, Weylus, RustDesk,
or any other additional project, and they add no third-party runtime
dependency. The imported SideScreen/Telemachus copyright, MIT license, notice,
and Credits resources remain bundled in the generated `.app`.

## Why a snapshot now

This repository had no commits or remote at audit time, so it could not be
converted into or synchronized with a project-controlled fork during this
change. A snapshot makes the initial code reviewable without inventing a remote
or mutating external GitHub state. Before long-lived product development, the
team should create a controlled fork or import full upstream history.

## Update procedure

1. Fetch both repositories and resolve immutable candidate SHAs.
2. Review license/notice changes before copying source.
3. Diff MacHost and AndroidClient separately; classify behavior by module.
4. Run upstream tests at the old and new SHAs.
5. Update the snapshot in an isolated commit without product refactors.
6. Re-run Vibe Screen contract, characterization, integration, and device tests.
7. Update this document with SHA, audit date, notable changes, and exceptions.

Never update from a branch name without recording the resolved commit.
