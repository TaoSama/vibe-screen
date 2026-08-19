# Phase 2 tablet productization slice

## Product requirement

Phase 2 targets an 8–9 inch tablet used in portrait or landscape, including a
stand-mounted, powered session that may remain active throughout a workday. The
complete phase also requires physical stylus and keyboard workflows, login and
headless Mac startup, unattended reconnect, and an eight-hour stability run with
device memory, thermal, and power evidence.

This slice covers the part that can be implemented and proved without claiming
external hardware results:

- show battery level and whether the tablet is charging;
- show Android power-saver and thermal severity as current product state;
- make low battery and elevated/severe heat actionable without silently changing
  the user's video preferences;
- observe only while the Activity is foregrounded, deduplicate updates, and drop
  late callbacks after stop;
- retain readable status text in 600dp portrait and landscape windows, including
  the settings dialog's existing scroll behavior.

## Acceptance boundaries

Automated tests may prove state classification, callback lifecycle, and layout.
They cannot prove a particular tablet's sensors, charging stability, temperature,
power draw, decoder throttling, or recovery behavior. Those results require the
named physical device and the eight-hour run in [TEST.md](TEST.md), executed
with the evidence package described in [RUNBOOK.md](RUNBOOK.md).

The slice deliberately reports health rather than applying an automatic FPS or
bitrate override. An override needs a separate protocol/product policy that can
restore user intent consistently across USB, LAN, and Internet sessions.
