# HarmonyOS HAP lifecycle readiness: blocked

Created: 2026-08-21T05:26:22Z
Run ID: 2026-08-21-hap-readiness-blocked
Repository: 30e72dfb898d0aec1795ea9bd7f1a23f94137246 (dirty)
HAP: apps/harmony/dist/0.1.0/vibe-screen-harmony-0.1.0.hap
HDC target: not selected

## Missing requirements

- repository_clean: blocked - clean git source state
- deveco_studio_available: blocked - DevEco Studio installed or version recorded
- harmony_sdk_api_recorded: blocked - HarmonyOS SDK API 12+ version recorded
- ohpm_available: blocked - DevEco-managed ohpm is executable
- hvigor_available: blocked - DevEco-managed hvigor/hvigorw is executable
- hdc_available: blocked - Harmony Device Connector is executable
- release_build_completed: insufficient - make release completed in apps/harmony
- signing_config_present: blocked - non-empty Harmony signingConfigs present
- signed_hap_present: blocked - signed release HAP archive with signature entries
- signature_certificate_recorded: insufficient - signing certificate SHA-256 recorded without private key material
- hdc_target_selected: blocked - exactly one HarmonyOS target selected or --hdc-target matched
- matepad_mini_identity_recorded: blocked - HarmonyOS MatePad Mini device identity recorded
- package_prestate_recorded: blocked - package state captured before install/upgrade/rollback/uninstall
- install_evidence_recorded: insufficient - reviewed HDC/hilog/device evidence for install
- upgrade_evidence_recorded: insufficient - reviewed HDC/hilog/device evidence for upgrade
- rollback_evidence_recorded: insufficient - reviewed HDC/hilog/device evidence for rollback
- uninstall_cleanup_evidence_recorded: insufficient - reviewed HDC/hilog/device evidence for uninstall cleanup

## Captured artifacts

- harmony-hap-readiness.json
- harmony-hap-readiness-summary.json
- harmony-device-gates.json (structure-only unless every gate is pass)
- hdc-targets.txt
- package-prestate.txt

This readiness bundle does not close the HarmonyOS device gate unless harmony-hap-readiness-summary.json reports can_close_hap_lifecycle_readiness=true and the full harmony-device-gates.json passes without --allow-blocked.
