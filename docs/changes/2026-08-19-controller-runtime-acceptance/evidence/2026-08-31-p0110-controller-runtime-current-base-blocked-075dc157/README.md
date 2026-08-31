# Controller runtime readiness: blocked

Created: 2026-08-30T21:24:57Z
Local run date: 2026-08-31 Asia/Shanghai; retained JSON timestamps use UTC.
Run ID: 20260831-p0110-controller-runtime-current-base-blocked
Source commit at collection time: 075dc157c36ba71df9f757e571015905881a7154
Package note: this is a historical blocked snapshot retained by the current-base
owner package after origin/main advanced through
967e05f4266916569f0898d7e2ed53e3a2602da9,
d610553d9c81bf1eae4342abc0dfcf02051696cb, and the refreshed PR base
c79fad2c554db9fbaf912d28aefa5b5d2007fb83; it is not evidence that any later
PR base closed controller runtime acceptance.
Device: nubia P0110 / pacific / Android 16 / SDK 36 / serial <device-serial>
APK: dev.telemachus.display 0.0.0 (100000)
Physical controller devices: 0
Host identity signed: false
Host virtual HID entitlement: false
Host virtual gamepad available: false

## Missing requirements

- physical_controller_attached: attach and name a physical Android controller
- android_controller_source_observed: observe SOURCE_GAMEPAD or SOURCE_JOYSTICK in Android logs
- protocol_controller_capability_negotiated: negotiate Protocol v1 controller capability
- android_production_forwarding_observed: observe MainActivity/StreamClient production controller forwarding
- controller_connected_state_disconnected_observed: record connected, state, and disconnected samples
- host_identity_signed: run an Apple identity-signed Host build, not ad-hoc
- host_virtual_hid_entitlement_present: include the approved virtual HID entitlement
- host_virtual_gamepad_available: record Host virtual-gamepad runtime availability
- mac_side_controller_response_observed: observe the virtual controller in a Mac-side target
- neutral_release_on_disconnect_observed: record neutral release on disconnect

## Notes

Shared Host readiness reports can_start_controller_runtime_gate=false. Shared Host readiness recorded can_start_controller_runtime_gate=false, so matching direct Host checks are recorded conservatively as false. Shared Host readiness blockers recorded: 5 (codesign identity 'Vibe Screen Dev' not found in the keychain. Create the 'Vibe Screen Dev' self-signed identity (or set $VIBE_SCREEN_SIGN_IDENTITY to an existing identity), or pass '--sign-identity -' for an ad-hoc build. Ad-hoc signing changes the code-signing hash on every rebuild and invalidates macOS Screen Recording/Accessibility grants.; codesign inspection failed for /Applications/Vibe Screen.app: --prepared:/Applications/Vibe Screen.app/Contents/Frameworks/WebRTC.framework/Versions/Current/.; Host listener is not observed on TCP port 54321; Host is missing com.apple.developer.hid.virtual.device entitlement; login/headless readiness: Launch at Login is not verified enabled: unverified); see host-readiness.json for full details. No physical Android gamepad/joystick source is visible in dumpsys input. This is readiness evidence only; a pass still requires live controller samples, Protocol v1 controller negotiation, Mac-side response, and neutral release on disconnect.

This readiness bundle is not a controller runtime pass unless controller-runtime-summary.json has can_close_runtime_gate=true.
