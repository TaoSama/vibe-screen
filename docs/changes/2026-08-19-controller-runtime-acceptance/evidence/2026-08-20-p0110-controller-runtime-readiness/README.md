# Controller runtime readiness: blocked

Created: 2026-08-20T17:29:50Z
Run ID: 2026-08-20-p0110-controller-runtime-readiness
Device: nubia P0110 / pacific / Android 16 / serial <redacted-adb-serial>
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

No physical Android gamepad/joystick source is visible in dumpsys input. Latest Host controller availability line: 2026-08-20T10:00:28Z Controller forwarding unavailable: use an Apple identity-signed build with the approved virtual HID entitlement; unsigned and ad-hoc builds cannot create virtual controllers This is readiness evidence only; a pass still requires live controller samples, Protocol v1 controller negotiation, Mac-side response, and neutral release on disconnect.

This readiness bundle is not a controller runtime pass unless controller-runtime-summary.json has can_close_runtime_gate=true.
