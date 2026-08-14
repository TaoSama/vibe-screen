# HarmonyOS install and upgrade policy

The bundle name is `dev.vibescreen.harmony`. Upgrade in place only with a higher
`versionCode` and the same signing identity. HarmonyOS is expected to retain
Asset Store records for that path. A signing-key change is expected to require
uninstalling the old app, and uninstall is expected to remove application-owned
host, security, and client-identity records. Neither retention behavior has been verified
on MatePad Mini and neither is release evidence until the device matrix passes.

## Release procedure

1. Update `AppScope/app.json5`, root `package.json`, entry `oh-package.json5`,
   and the Makefile release version together.
2. Run `pnpm install --frozen-lockfile` and `pnpm run verify`.
3. From a clean checkout with the recorded DevEco/Harmony SDK, run
   `make release`; it must find exactly one signed release HAP.
4. Record the HAP SHA-256, certificate identity, bundle/version, DevEco/Hvigor/
   OHPM/SDK versions, and dependency notices.
5. Install over the previous signed version and verify the host and versioned
   client-identity records survive, an unsupported record is safely removed,
   security-record/revocation semantics remain fail-closed, reconnect succeeds,
   and uninstall removes all records. Record these as
   observed device results rather than relying on the platform expectation.
   Repeat the device matrix after any SDK or signing change.

Asset Store records carry an explicit version. An unknown host-record version
fails closed and is removed. An unknown client-identity version fails closed
without silently replacing the stable identity; recovery therefore requires an
explicit product decision. Adding a future migration requires portable tests
plus upgrade and rollback device evidence. Downgrades are unsupported unless
the older build is shown to understand every stored record version.

An unknown or corrupt security-record version also fails closed, but is not
silently deleted: removal could erase a revocation tombstone and revive an old
credential. Recovery requires an explicit forget-and-repair flow.

The pre-versioning development build stored the same validated `harmony-UUID`
as a bare string. On first read the current client atomically wraps that value
in the version-1 identity record without changing the identifier. Migration
failure leaves the old value intact and surfaces the Asset Store error; this
path still requires an in-place upgrade test on the target device.
