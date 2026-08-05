# HarmonyOS privacy and data handling

This development preview sends the selected Mac screen to the tablet and input
events back to the Mac. Trusted-LAN transport is plaintext and unauthenticated;
do not use it on public or untrusted networks.

## Stored data

- A random client identifier is stored in HarmonyOS Asset Store.
- The selected host address, port, pairing-offer identifier, and record version
  are stored in Asset Store so the address can be restored after relaunch.
- One-time link credentials are parsed in memory and deliberately not persisted.
- Video frames and input events are processed in memory and are not recorded.
- The app contains no analytics, advertising SDK, cloud sync, or crash uploader.

Logs must never contain pairing links, credentials, device identifiers, private
addresses, or screen content. Release/device evidence must redact those values.

## User control and retention

“Forget host” removes the stored host record. Uninstalling removes all local
Asset Store records. The client identifier remains until uninstall so the same
installation is stable across upgrades. A malformed or unsupported-version host
record is deleted rather than guessed or silently migrated.

Before release, verify the permission list in the built HAP, publish a versioned
privacy notice, test denial/retry paths, and archive an SBOM plus third-party
notices from the exact signed artifact.
