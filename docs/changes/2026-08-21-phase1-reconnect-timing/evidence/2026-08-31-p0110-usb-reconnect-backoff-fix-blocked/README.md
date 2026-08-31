# P0110 USB reconnect backoff fix blocked readiness

This directory records a blocked owner refresh for the Phase 1 reconnect-within-three-seconds
timing gate after the USB reconnect backoff fix. It is not a reconnect pass and must not be used
to close the README gate.

## Target

- Device target: nubia P0110 / pacific / Android 16 / SDK 36 / REDACTED_P0110_USB_SERIAL
- Gate profile: `phase1-reconnect-within-3s`
- Required full-gate disruption scenarios: `client-kill`, `adb-reverse-disconnect`, `lan-network-interrupt`
- Captured source commit: `bdd32e46bfff1b5a8aafedf7a6d7351094a112ad`; `origin/main` at collection time: `59c1813fc8fe99293202cee4ebd484fd542f690b`

## Fix applied

The USB reconnect path previously ignored the `ReconnectBackoff` delay (500 ms initial, bounded
exponential up to 3000 ms) computed by `StreamClient.completeConnectionEnd` and always used a
fixed 1500 ms delay in `scheduleAutomaticUsbConnect()`. This added ~1 s of unnecessary latency
on the first reconnect and broke bounded exponential backoff for USB.

The candidate fix wires the `ReconnectBackoff` delay through a single session retry coordinator:

- `StreamClient.onReconnectSuggested(delayMs)` feeds `SessionAutomaticRetryCoordinator` instead
  of scheduling a retry directly from the callback.
- The USB and wireless automatic-retry consumers receive the coordinator-selected delay and pass it
  to `scheduleAutomaticUsbConnect(delayMs)` or `scheduleWirelessReconnect(delayMs)`.
- If the coroutine `finally` block runs before the reconnect suggestion, the coordinator posts the
  default initial retry and lets the same scheduler owner replace it when the suggestion arrives.

## Readiness observations

- `device-info.json` records manufacturer `nubia`, model `P0110`, device/product `pacific`,
  Android `16`, SDK `36`.
- `adb-reverse-before.txt` records the existing USB reverse mapping `UsbFfs tcp:54321 tcp:54321`.
- `android-pid-before.txt` shows `dev.telemachus.display` was running.
- The Host listener prerequisite was not ready: `host-54321-listener.txt` is empty and
  `host-54321-listener.exit` is `1`. The `Vibe Screen.app` process was running but no TCP
  listener was observed on port `54321`, consistent with the Host requiring Screen Recording
  TCC permission and an explicit start action before it begins listening.

## Device-side observation limit (Host not listening)

The retained blocked-preflight artifacts show `adb reverse tcp:54321 tcp:54321` was in place and
the Android package process was running. Because no Host listener artifact exists for TCP `54321`,
this directory cannot prove a product reconnect attempt or any reconnect timing measurement.

No raw `reconnect_scheduled` logcat or private diagnostic artifact is retained in this directory,
so this blocked evidence does not prove device-side retry-delay telemetry for the candidate fix.
The retained evidence only proves the preflight state and the Host-listener blocker. It does not
constitute a full reconnect timing pass because no Host stream, display configuration, or first
decoded frame was observed.

## Summary

`reconnect-timing-summary.json` records `verdict=blocked`, `can_close_timing_gate=false`, and
all three full-gate disruptions missing. The Host listener was not observed on TCP `54321`, so
no `client-kill`, ADB reverse removal/restoration, or trusted-LAN network interruption was run.
