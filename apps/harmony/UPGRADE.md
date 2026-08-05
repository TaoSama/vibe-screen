# HarmonyOS install and upgrade policy

The bundle name is `dev.vibescreen.harmony`. Upgrade in place only with a higher
`versionCode` and the same signing identity. Changing the signing key normally
requires uninstalling the old app, which also removes local host and client
identity records.

## Release procedure

1. Update `AppScope/app.json5`, root `package.json`, entry `oh-package.json5`,
   and the Makefile release version together.
2. Run `pnpm install --frozen-lockfile` and `pnpm run verify`.
3. From a clean checkout with the recorded DevEco/Harmony SDK, run
   `make release`; it must find exactly one signed release HAP.
4. Record the HAP SHA-256, certificate identity, bundle/version, DevEco/Hvigor/
   OHPM/SDK versions, and dependency notices.
5. Install over the previous signed version and verify the host record survives,
   an unsupported record is safely removed, reconnect succeeds, and uninstall
   removes all records. Repeat the device matrix after any SDK or signing change.

Asset Store records carry an explicit version. Unknown versions fail closed and
are removed; adding a future migration requires portable tests plus upgrade and
rollback device evidence. Downgrades are unsupported unless the older build is
shown to understand every stored record version.
