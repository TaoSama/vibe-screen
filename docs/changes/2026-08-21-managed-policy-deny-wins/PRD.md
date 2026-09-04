# Managed policy deny-wins

Status: offline implementation and verification complete; real Apple MDM, iOS
managed App Configuration, and Android Enterprise delivery remain blocked
Owner: Phase 5 managed configuration
Started: 2026-08-21

## Goal

Make managed configuration a product-level Protocol v1 policy boundary instead
of a clipboard-only hint. A local administrator or a peer policy can deny an
advanced feature, and no allowlist entry from the other side may re-enable a
denied result. Every effective decision must be explainable through structured
restriction results that travel with ManagedPolicyStatus.

## Scope

- Read Apple managed configuration from com.apple.configuration.managed on
  macOS and iOS.
- Read Android managed configuration from
  RestrictionsManager.applicationRestrictions, the Android Enterprise app
  restrictions surface exposed to the app process.
- Parse the supported product keys: ClipboardAllowed, FileTransferAllowed,
  AudioAllowed, WakeAllowed, CustomGesturesAllowed, HostActionsAllowed,
  MaximumFileBytes, AllowedHosts, and DeniedHosts.
- Carry product restrictions over Protocol v1 as policy fields plus
  restriction_results entries for clipboard, file_transfer, audio, wake,
  custom_gestures, host_actions, maximum_file_bytes, allowed_hosts, and
  denied_hosts.
- Apply deny-wins merging on Host, Android, and iOS: booleans are local AND
  remote, file bytes are the minimum, allowlists are intersected when both sides
  restrict, and denylist hosts are removed after the allowlist result.
- Fail closed when local managed configuration has an invalid type, when a peer
  sends incomplete or inconsistent restriction results, or when effective host
  policy excludes the connected peer.

## Semantics

| Input | Result |
| --- | --- |
| No local managed configuration | Local policy is unmanaged and does not tighten peer policy. |
| Managed boolean key missing | The matching feature is denied. |
| Managed numeric/file limit missing | The limit is zero and the matching resource is denied. |
| Invalid local managed value type | All product restrictions deny with source=local_parse_error. |
| Local allow + remote deny | Deny wins. |
| Local deny + remote allow | Deny wins. |
| Local and remote restricted allowlists | Intersection wins. |
| Allowlist and denylist overlap | Denylist wins; overlapping hosts are not effective allowed hosts. |
| Peer omits or corrupts managed restriction results | Session fails closed before feature activation. |

## Non-goals

- Do not claim real Apple MDM profile or managed App Configuration acceptance.
- Do not claim real Android Enterprise app-restrictions delivery acceptance.
- Do not close README Phase 5 managed-configuration gates without real profile
  or enterprise-policy delivery evidence.
- Do not add a device acceptance claim; no Android or iOS device command is part
  of this change record.
- Do not expose vendor-specific MDM payloads over the protocol.

## Acceptance criteria

1. Protocol v1 keeps old fields compatible and appends product restriction
   explanations.
2. Host, Android, and iOS all compute the same deny-wins result for booleans,
   file limits, allowlists, and denylists.
3. A peer with CAPABILITY_MANAGED_CONFIGURATION must send complete and
   consistent restriction results before the client proceeds to ordinary feature
   requests.
4. Local parse errors on Apple or Android managed configuration produce
   fail-closed policy.
5. Documentation records the offline verification and blocked real-MDM evidence
   boundary.
