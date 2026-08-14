# HarmonyOS privacy and data handling

This development preview sends the selected Mac screen to the tablet and input
events back to the Mac. Trusted-LAN transport is plaintext and unauthenticated;
do not use it on public or untrusted networks.

## Stored data

- A random, stable client identifier is stored in HarmonyOS Asset Store. It is
  sent to the user-selected Mac in every Protocol v1 `ClientHello` so the Mac
  can distinguish this installation. In the current trusted-LAN development
  mode that identifier, the rest of the control channel, screen frames, and
  input events travel without authentication or encryption and can be observed
  or modified by another party on the network.
- The selected host address, port, pairing-offer identifier, and record version
  are stored in Asset Store so the address can be restored after relaunch.
- One-time link credentials are parsed in memory and deliberately not persisted.
- The secure-pairing lifecycle has a separate Asset Store record for a verified
  device credential, pinned host identity, session-key metadata, and accepted
  control-sequence high-water. Revocation replaces the credential with a
  tombstone; it does not retain the revoked secret.
- Video frames and input events are processed in memory and are not recorded.
- The app contains no analytics, advertising SDK, cloud sync, or crash uploader.

Logs must never contain pairing links, credentials, device identifiers, private
addresses, or screen content. Release/device evidence must redact those values.

## User control and retention

“Forget host” asks Asset Store to remove both the host profile and secure-pairing
record. HarmonyOS is expected to preserve the host, security, and client-identity records across a same-signing
in-place upgrade and remove application-owned records on uninstall. Those are
platform expectations, not verified MatePad Mini results; release acceptance
must test and record both behaviors. Until uninstall or an explicit future
identity-reset control, the client identifier is retained so the installation
remains stable. A malformed or unsupported-version host record is rejected and
scheduled for deletion rather than guessed or silently migrated.

Before release, verify the permission list in the built HAP, publish a versioned
privacy notice, test denial/retry paths, and archive an SBOM plus third-party
notices from the exact signed artifact.
