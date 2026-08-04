"""Collect Android device identity and tool/application versions as JSON evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .adb import ADBClient, ADBError


def _package_version(client: ADBClient, package_name: str) -> dict[str, Any]:
    output = client.shell("dumpsys", "package", package_name)
    version_name_match = re.search(r"^\s*versionName=(.+)$", output, re.MULTILINE)
    version_code_match = re.search(r"^\s*versionCode=(\d+)", output, re.MULTILINE)
    if "Unable to find package" in output or not (version_name_match or version_code_match):
        raise ADBError(f"package is not installed or has no version metadata: {package_name}")
    return {
        "package": package_name,
        "version_name": version_name_match.group(1).strip() if version_name_match else None,
        "version_code": int(version_code_match.group(1)) if version_code_match else None,
    }


def collect_device_info(
    client: ADBClient, *, connect: bool = True, packages: Sequence[str] = ()
) -> dict[str, Any]:
    connection = client.connect() if connect else None
    if not connect:
        client.require_device()
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "android_device_info",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "connection": connection,
        "adb_version": client.adb_version(),
        "device": client.identity(),
        "packages": [_package_version(client, package) for package in packages],
    }


def _write_json(path: Path | None, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(encoded)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="exact ADB device serial")
    parser.add_argument("--adb", default="adb", help="ADB executable path")
    parser.add_argument("--adb-timeout", type=float, default=15.0)
    parser.add_argument("--no-connect", action="store_true", help="require an existing connection")
    parser.add_argument("--package", action="append", default=[], help="installed package to record; repeatable")
    parser.add_argument("--output", type=Path, help="JSON output file (default: stdout)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.adb_timeout <= 0:
        parser.error("--adb-timeout must be positive")
    try:
        client = ADBClient(
            arguments.serial,
            adb_path=arguments.adb,
            timeout_seconds=arguments.adb_timeout,
        )
        document = collect_device_info(
            client,
            connect=not arguments.no_connect,
            packages=arguments.package,
        )
        _write_json(arguments.output, document)
    except (ADBError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

