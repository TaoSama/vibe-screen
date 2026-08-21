# macOS signing identity preflight

Status: blocked
Created: 2026-08-21T16:06:13Z

## Requested identity

- Name: Vibe Screen Dev
- Environment override: not set
- Valid codesigning identities reported by Keychain: 0

## Matching identities

- none

## Blockers

- codesign identity 'Vibe Screen Dev' not found in the keychain

## Installed Host snapshot

- Path: /Applications/Vibe Screen.app
- Inspected: true
- Identifier: dev.telemachus.display
- Identity: Vibe Screen Dev
- Certificate SHA-1: 9AAE572BF6D764E3436A6109197D345B5A87998C
- CDHash: 2fe65fd5cd69c80249140da3f139cfa68037c5c2
- Binary SHA-256: c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996
- TeamIdentifier: not set
- TCC interpretation: unverified (current-user TCC database: unable to open database file; system TCC database: unable to open database file)

## Next steps

1. Create a self-signed Code Signing certificate named Vibe Screen Dev in Keychain Access, or set VIBE_SCREEN_SIGN_IDENTITY to one existing stable codesign identity.
2. Confirm the selected identity with: security find-identity -v -p codesigning | grep '"Vibe Screen Dev"'.
3. Run make baseline-macos-dev-install, grant Screen Recording and Accessibility to /Applications/Vibe Screen.app, relaunch it, then run make baseline-macos-touch-preflight.

## Command

    /usr/bin/security find-identity -v -p codesigning

This preflight is read-only. It does not import certificates, change Keychain
ACLs, install or sign the Host, modify TCC.db, call tccutil, or grant macOS
privacy permissions. Passing it only proves the requested stable codesigning
identity is selectable; Android/macOS device gates still require a matching
installed Host bundle, Screen Recording, Accessibility, and live device evidence.
