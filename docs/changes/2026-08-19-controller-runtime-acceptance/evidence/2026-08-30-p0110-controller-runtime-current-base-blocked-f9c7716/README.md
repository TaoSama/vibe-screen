# Controller runtime readiness: blocked

Created: 2026-08-30T04:50:23Z
Run ID: 20260830Tcurrentbasef9c7716
Source commit: f9c7716785921776021680ab7e5af0c01e55121d
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

No physical Android gamepad/joystick source is visible in dumpsys input. This is readiness evidence only; a pass still requires live controller samples, Protocol v1 controller negotiation, Mac-side response, and neutral release on disconnect.

This readiness bundle is not a controller runtime pass unless controller-runtime-summary.json has can_close_runtime_gate=true.
