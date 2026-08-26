# Apple managed configuration evidence: blocked

Verdict: BLOCKED
Date: 2026-08-21

## Blocker

This worktree has no real Apple MDM enrollment/profile delivery path and no
approved local managed App Configuration injection mechanism for
com.apple.configuration.managed. Without that environment, the change cannot
prove that macOS or iOS receives the managed payload from Apple configuration
infrastructure.

## Verified instead

Offline source and unit/self-test coverage verifies the product policy behavior
that can be exercised without a real MDM profile:

- Apple managed configuration dictionaries parse the supported keys and fail
  closed on invalid types.
- AllowedHosts and DeniedHosts are normalized; DeniedHosts wins after local and
  remote allowlist merging.
- ManagedPolicyStatus carries complete restriction_results for all nine product
  restrictions.
- Host, Android, and iOS reject incomplete or inconsistent managed restriction
  results.
- Android does not proceed from managed-policy negotiation to display listing
  until a valid Host policy status is received.

## Not proved

- A real macOS MDM profile populating com.apple.configuration.managed.
- A real iOS managed App Configuration payload reaching the app sandbox.
- Android USB or LAN managed-policy interop on nubia P0110 / pacific / Android
  16 / SDK 36.
- Any Xiaomi 13 / fuxi evidence for this change.

This evidence does not close the README Phase 5 managed-configuration device
gate.
