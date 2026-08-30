# Phase 2 tablet soak preflight

Result: blocked.

This evidence record does not close the Phase 2 eight-hour tablet gate unless `phase2-soak-readiness.json` reports `can_close_phase2_gate=true` and the raw physical-tablet artifacts are present. This preflight run has no formal `soak-8h/phase2-tablet-gate.json` pass artifact, and it records missing APK identity as readiness-only blocker context rather than formal APK pass evidence.

## Command

    /opt/homebrew/opt/python@3.11/bin/python3.11 -m vibescreen_evidence.phase2_tablet_soak --serial <redacted-adb-serial> --output-dir docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-nubia-p0110-phase2-soak-preflight --mode preflight --package dev.telemachus.display --device-class android_substitute --stand-setup 'bench substitute phone, no 8-9 inch tablet stand' --charger 'unknown current charger' --cable-or-dock 'USB-C data cable' --transport usb --video-preferences 'preflight only' --host-identity 'Darwin MacBook-Pro-3.local 25.4.0 Darwin Kernel Version 25.4.0: Thu Mar 19 19:33:25 PDT 2026; root:xnu-12377.101.15~1/RELEASE_ARM64_T6041 arm64' --host-build 'not stable-signed formal Host for 8h gate' --duration 8h --preflight-duration 2s --interval 1s --thermal-limit-status 2

## Blockers
- APK identity was not provided; preflight cannot close the Phase 2 gate
- device_class is not physical_8_9_inch_tablet, so this run cannot close the tablet hardware gate
- host PID was not provided, so Host RSS cannot be sampled
- host telemetry JSONL path was not provided

## Android Log Metrics
- telemetry_events: 2
- reconnect_log_lines: 2
- frame_drop_log_lines: 0

## Artifacts
- device-info.json
- device.txt
- wm-size.txt
- wm-density.txt
- adb-battery-before.txt
- adb-power-before.txt
- thermal-before.txt
- thermal-before.err
- android-pid.txt
- host.txt
- apk-identity-missing.txt
- build.txt
- phase2-tablet-manifest.json
- soak-preflight/samples.jsonl
- soak-preflight/summary.json
- raw-logcat.txt
- decoder-telemetry.jsonl
- reconnects.log
- frame-drops.log
- adb-battery-after.txt
- adb-power-after.txt
- thermal-after.txt
- thermal-after.err
- android-pid-after.txt
