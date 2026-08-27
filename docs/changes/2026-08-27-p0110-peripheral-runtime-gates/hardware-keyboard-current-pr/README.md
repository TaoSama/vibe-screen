# Phase 2 hardware-keyboard readiness: blocked

Created: 2026-08-27T10:29:41Z
Run ID: 20260827T102941Z
Device: nubia P0110 / pacific / Android 16 / SDK 36 / serial <device-serial>
APK: dev.telemachus.display 0.0.0 (100000)
Android device lock acquired: true
External keyboard devices visible: 0
Host listener observed: true
Stable signed/TCC Host ready: false

## Keyboard devices

- none observed; synthetic ADB key events are not physical-keyboard evidence

## Missing requirements

- physical_keyboard_attached: attach and name a real external, non-virtual Android hardware keyboard
- android_keyboard_source_observed: observe a physical keyboard input source in Android input/log evidence
- protocol_keyboard_capability_negotiated: negotiate Protocol v1 keyboard capability on the active session
- protocol_usb_hid_modifier_capability_negotiated: negotiate the USB HID modifier-byte capability for standard modifier semantics
- android_production_forwarding_observed: observe MainActivity/StreamClient production keyboard forwarding, not only adb input dispatch
- android_focus_ime_boundary_observed: prove the Android Activity foreground/focus path accepts the hardware keyboard while IME or system-key boundaries do not masquerade as forwarded keys
- selected_display_stream_observed: prove the Protocol v1 session was actively streaming the selected display while the keyboard workflow ran
- host_stable_signed_tcc_ready: run a stable signed Host with Screen Recording and Accessibility permission ready
- key_press_release_observed: prove key-down and key-up semantics for the same HID usage
- modifier_press_release_observed: prove modifier key press and release semantics, not only a shortcut side effect
- shortcut_combo_observed: prove at least one shortcut/modifier combination reaches the Host
- modifier_release_no_leak_observed: prove modifiers clear after shortcut release and do not leak into a later plain key
- visible_mac_result_observed: record the visible Mac-side result of the hardware keyboard workflow
- host_logs_retained: retain Host logs covering the keyboard workflow
- android_logs_retained: retain Android logs/input snapshots covering the keyboard workflow
- host_key_injection_observed|host_ack_cgevent_log_observed: retain Host-side `Key injected:` CGEvent logs or Host acknowledgement/CGEvent logs for every claimed key and shortcut event

## Evidence files

- hardware-keyboard-readiness.json: structured preflight snapshot.
- hardware-keyboard-observations.json: boolean gate inputs for the summarizer.
- hardware-keyboard-summary.json: fail-closed gate summary.
- dumpsys-input.txt and adb-devices.txt: Android input and device snapshots when the lock allowed ADB.
- host-listener.txt, codesign-identities.txt, host-preflight-command.txt, and host-signing-and-permissions.txt: Host preflight artifacts.

This readiness bundle is not a hardware-keyboard workflow pass unless hardware-keyboard-summary.json has can_close_hardware_keyboard_gate=true.
