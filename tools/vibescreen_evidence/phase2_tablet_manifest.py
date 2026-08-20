"""Create a Phase 2 tablet sustained-use evidence manifest."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .manifest import ManifestError, repository_state

KIND = "phase2_tablet_sustained_use_manifest"
MINIMUM_DURATION_SECONDS = 8 * 60 * 60
REQUIRED_IDENTITY_FIELDS = [
    "adb_serial",
    "device_serial",
    "manufacturer",
    "model",
    "codename",
    "android_release",
    "sdk",
    "build_fingerprint",
    "abi",
]

REQUIRED_GATES = [
    "physical_8_9_inch_tablet",
    "stand_mounted_charging",
    "thermal_power_sampling",
    "foreground_background_recovery",
    "transport_reconnect_recovery",
    "login_startup_or_headless_recovery",
    "eight_hour_sustained_stream",
]

REQUIRED_ARTIFACTS = [
    "README.md",
    "phase2-tablet-manifest.json",
    "device-info.json",
    "device.txt",
    "host.txt",
    "build.txt",
    "apk-sha256.txt",
    "samples.jsonl",
    "summary.json",
    "adb-battery-before.txt",
    "adb-battery-after.txt",
    "adb-power-before.txt",
    "adb-power-after.txt",
    "thermal-before.txt",
    "thermal-before.err",
    "thermal-after.txt",
    "thermal-after.err",
    "raw-logcat.txt",
    "host.log",
    "reconnects.log",
    "frame-drops.log",
    "decoder-telemetry.jsonl",
]

DEFAULT_LIMITATIONS = [
    "This manifest is preparation metadata and does not close the Phase 2 gate without raw physical-device evidence.",
    "Nubia P0110/pacific/Android 16 may be recorded as a general Android substitute only and must not be relabeled as Xiaomi 13/fuxi or as 8-9 inch tablet evidence.",
]


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"failed to read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object: {path}")
    return value


def _require_non_empty(value: str | None, option: str) -> str:
    if value is None or not value.strip():
        raise ManifestError(f"{option} is required")
    return value.strip()


def _split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _device_identity(device_info: dict[str, Any]) -> dict[str, Any]:
    device = device_info.get("device")
    if not isinstance(device, dict):
        raise ManifestError("device-info.json does not contain a device object")
    identity = {
        key: device.get(key)
        for key in (
            "adb_serial",
            "device_serial",
            "manufacturer",
            "model",
            "codename",
            "android_release",
            "sdk",
            "build_fingerprint",
            "abi",
        )
        if device.get(key) is not None
    }
    if "codename" not in identity and device.get("device") is not None:
        identity["codename"] = device["device"]
    missing = [field for field in REQUIRED_IDENTITY_FIELDS if identity.get(field) in (None, "")]
    if missing:
        raise ManifestError(
            "device-info.json is missing required identity field(s): "
            + ", ".join(missing)
        )
    return identity


def build_manifest(
    *,
    command: Sequence[str],
    repo: Path,
    device_info: dict[str, Any],
    device_class: str,
    tablet_size_inches: str | None,
    stand_setup: str,
    charger: str,
    cable_or_dock: str,
    ambient_temperature_celsius: float | None,
    transport: str,
    video_preferences: str,
    duration_seconds: int,
    sample_interval_seconds: int,
    thermal_limit_status: int,
    battery_temperature_limit_celsius: float | None,
    maximum_net_battery_drain_percent: int | None,
    recovery_scenarios: Sequence[str],
    host_identity: str,
    host_build: str,
    apk_sha256: str,
    notes: str | None,
) -> dict[str, Any]:
    if duration_seconds < MINIMUM_DURATION_SECONDS:
        raise ManifestError("--duration-seconds must be at least 28800 for a Phase 2 8h manifest")
    if sample_interval_seconds <= 0 or sample_interval_seconds > 60:
        raise ManifestError("--sample-interval-seconds must be in the range 1..60")
    if thermal_limit_status < 0:
        raise ManifestError("--thermal-limit-status must be non-negative")
    if maximum_net_battery_drain_percent is not None and maximum_net_battery_drain_percent < 0:
        raise ManifestError("--maximum-net-battery-drain-percent must be non-negative")

    limitations = list(DEFAULT_LIMITATIONS)
    normalized_class = device_class.strip()
    if normalized_class != "physical_8_9_inch_tablet":
        limitations.append(
            "The recorded device class is not a physical 8-9 inch tablet, so this manifest cannot close the tablet hardware gate."
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": list(command),
        "repository": repository_state(repo.resolve()),
        "device": {
            "identity": _device_identity(device_info),
            "device_class": normalized_class,
            "tablet_size_inches": tablet_size_inches,
        },
        "physical_setup": {
            "stand_setup": stand_setup.strip(),
            "charger": charger.strip(),
            "cable_or_dock": cable_or_dock.strip(),
            "ambient_temperature_celsius": ambient_temperature_celsius,
        },
        "host": {
            "identity": host_identity.strip(),
            "build": host_build.strip(),
        },
        "android_artifact": {
            "apk_sha256": apk_sha256.strip(),
        },
        "session": {
            "transport": transport.strip(),
            "video_preferences": video_preferences.strip(),
            "duration_seconds": duration_seconds,
            "sample_interval_seconds": sample_interval_seconds,
        },
        "thresholds": {
            "thermal_limit_status": thermal_limit_status,
            "battery_temperature_limit_celsius": battery_temperature_limit_celsius,
            "maximum_net_battery_drain_percent": maximum_net_battery_drain_percent,
        },
        "recovery_scenarios": list(recovery_scenarios),
        "required_gates": REQUIRED_GATES,
        "required_artifacts": REQUIRED_ARTIFACTS,
        "limitations": limitations,
        "notes": notes,
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--device-info",
        type=Path,
        required=True,
        help="device-info.json from make evidence-device-info",
    )
    parser.add_argument("--device-class", required=True, choices=["physical_8_9_inch_tablet", "android_substitute"])
    parser.add_argument("--tablet-size-inches")
    parser.add_argument("--stand-setup", required=True)
    parser.add_argument("--charger", required=True)
    parser.add_argument("--cable-or-dock", required=True)
    parser.add_argument("--ambient-temperature-celsius", type=float)
    parser.add_argument("--transport", required=True, choices=["usb", "lan"])
    parser.add_argument("--video-preferences", required=True)
    parser.add_argument("--duration-seconds", type=int, default=MINIMUM_DURATION_SECONDS)
    parser.add_argument("--sample-interval-seconds", type=int, default=30)
    parser.add_argument("--thermal-limit-status", type=int, default=2)
    parser.add_argument("--battery-temperature-limit-celsius", type=float)
    parser.add_argument("--maximum-net-battery-drain-percent", type=int)
    parser.add_argument("--recovery-scenarios", help="comma-separated planned recovery scenarios")
    parser.add_argument("--host-identity", required=True)
    parser.add_argument("--host-build", required=True)
    parser.add_argument("--apk-sha256", required=True)
    parser.add_argument("--notes")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Exact evidence command, placed after -- (optional)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    command = arguments.command
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        device_info = _read_json(arguments.device_info, "device info")
        document = build_manifest(
            command=command,
            repo=arguments.repo,
            device_info=device_info,
            device_class=arguments.device_class,
            tablet_size_inches=arguments.tablet_size_inches,
            stand_setup=_require_non_empty(arguments.stand_setup, "--stand-setup"),
            charger=_require_non_empty(arguments.charger, "--charger"),
            cable_or_dock=_require_non_empty(arguments.cable_or_dock, "--cable-or-dock"),
            ambient_temperature_celsius=arguments.ambient_temperature_celsius,
            transport=arguments.transport,
            video_preferences=_require_non_empty(arguments.video_preferences, "--video-preferences"),
            duration_seconds=arguments.duration_seconds,
            sample_interval_seconds=arguments.sample_interval_seconds,
            thermal_limit_status=arguments.thermal_limit_status,
            battery_temperature_limit_celsius=arguments.battery_temperature_limit_celsius,
            maximum_net_battery_drain_percent=arguments.maximum_net_battery_drain_percent,
            recovery_scenarios=_split_csv(arguments.recovery_scenarios),
            host_identity=_require_non_empty(arguments.host_identity, "--host-identity"),
            host_build=_require_non_empty(arguments.host_build, "--host-build"),
            apk_sha256=_require_non_empty(arguments.apk_sha256, "--apk-sha256"),
            notes=arguments.notes,
        )
        _write_json(arguments.output, document)
    except (ManifestError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
