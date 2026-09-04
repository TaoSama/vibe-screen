# Managed policy deny-wins technical design

## Protocol contract

ManagedPolicyStatus remains backward-compatible by appending fields. The field
restriction_results is field 11 and denied_hosts is field 12. Each
ManagedRestrictionResult contains restriction, allowed, source, and reason.

restriction_results is mandatory when managed=true and must contain exactly one
entry for each product restriction: clipboard, file_transfer, audio, wake,
custom_gestures, host_actions, maximum_file_bytes, allowed_hosts, and
denied_hosts. source and reason must be non-empty. The allowed value must match
the scalar or list policy fields in the same message.
denied_hosts.allowed is true only when the denied_hosts list is empty.

## Local policy parsing

macOS and iOS read Apple managed configuration from
UserDefaults.standard.dictionary(forKey: "com.apple.configuration.managed").
Android reads managed configuration from
RestrictionsManager.applicationRestrictions and snapshots the resulting product
policy before creating each USB/LAN StreamClient. Internet sessions use the same
Protocol v1 ManagedPolicyStatus shape and InternetManagedPolicy resolver.
The supported keys are:

| Key | Type | Missing value |
| --- | --- | --- |
| ClipboardAllowed | bool | denied |
| FileTransferAllowed | bool | denied |
| AudioAllowed | bool | denied |
| WakeAllowed | bool | denied |
| CustomGesturesAllowed | bool | denied |
| HostActionsAllowed | bool | denied |
| MaximumFileBytes | non-negative number | 0 |
| AllowedHosts | string array/list, or comma/newline separated string on Android | unrestricted unless allowed_hosts_restricted is set by policy construction |
| DeniedHosts | string array/list, or comma/newline separated string on Android | empty denylist |

Host IDs are trimmed and lowercased. Blank host entries are ignored. Any wrong
type or negative MaximumFileBytes fails closed: the local policy becomes
managed, all feature booleans are false, maximum file bytes is zero, host access
is restricted, and every restriction result uses source=local_parse_error.

## Deny-wins merge

An unmanaged remote status does not tighten local policy. When both sides have
managed configuration negotiated, effective policy is recomputed from the local
and latest remote policy on every update:

- feature booleans use local AND remote;
- maximum_file_bytes uses min(local, remote);
- unrestricted host policy remains unrestricted only when both sides are
  unrestricted;
- restricted host allowlists intersect;
- local and remote denied_hosts are unioned;
- denied_hosts is applied after allowlist merging, so a host present in both
  allowlist and denylist is denied.

allowed_hosts_restricted is derived as true when the explicit flag is true,
when allowed_hosts is non-empty, or when a managed status is restored with
incomplete restriction_results. The last case keeps low-level status conversion
host-fail-closed even before the session-layer validation rejects the malformed
peer message. If both sides are otherwise unrestricted, a non-empty denylist is
still enforced directly by host lookup; only non-denied hosts remain allowed.

The effective policy emits fresh restriction_results with
source=effective_deny_wins. The allowed_hosts result describes the final
allowlist after denylist subtraction, and the denied_hosts result is false when
the final denylist is non-empty.

## Session behavior

Host validates incoming ManagedPolicyStatus before storing the remote policy.
Incomplete, duplicate, empty-source/empty-reason, or mismatched restriction
results fail closed as a malformed managed policy message. The Host also fails
closed if the effective host policy no longer allows the connected client.

Android moves from AWAITING_SESSION to AWAITING_MANAGED_POLICY when
CAPABILITY_MANAGED_CONFIGURATION is negotiated. It sends its local status,
waits for the Host status, validates the full result set, applies deny-wins,
and only then sends ListDisplaysRequest. A denied Host action policy clears the
local catalog and pending invocations. A host identity denied by the final
allow/deny result fails closed.

Android also applies local policy to UI-only controls before the first peer
status arrives: local CustomGesturesAllowed and HostActionsAllowed are ANDed
with the latest remote/effective status callbacks so a remote allow cannot
restore a locally denied control. WakeHost uses the effective policy at request
creation and receive time; when a remote policy update removes wake capability,
pending wake requests are completed as managed_policy_denied and cleared, while
late results for a formerly negotiated wake capability are ignored. Internet
audio capability is removed when audio is denied, active playback is stopped
with managed_policy_audio_denied, and later audio records are not routed through
the raw callback fallback.

iOS validates restriction_results before applying a remote status. Invalid
managed policy terminates the session as permanent failure. Valid remote policy
is merged through the same resolver used by local reloads, so newer remote
statuses recompute from local policy rather than accumulating stale denials.

## Source values

Source values are explanatory labels for humans and audits. They are not a
security decision enum; validation only requires that managed peers provide a
complete, internally consistent, non-empty source and reason for each
restriction. Current local sources are:

- unmanaged: no local managed configuration is present.
- managed_configuration: parsed local managed configuration or policy fixture.
- local_parse_error: local managed configuration could not be parsed and all
  restrictions were denied.
- effective_deny_wins: final local-plus-remote policy after deny-wins merge.

## Compatibility

denied_hosts and restriction_results are appended fields. Older peers ignore
them. Current peers require complete restriction results only after
CAPABILITY_MANAGED_CONFIGURATION has been negotiated and managed=true, so
legacy unmanaged status remains permissive.
