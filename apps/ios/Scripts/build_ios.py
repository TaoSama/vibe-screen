#!/usr/bin/env python3
"""Build, test, and create an unsigned archive for the iOS application."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


IOS_ROOT = Path(__file__).resolve().parents[1]
PROJECT = IOS_ROOT / "VibeScreen.xcodeproj"
OUTPUT_ROOT = IOS_ROOT / ".build" / "xcode"
DERIVED_DATA_ROOT = OUTPUT_ROOT / "DerivedData"
ARCHIVE = OUTPUT_ROOT / "VibeScreen.xcarchive"
COMMON_ARGUMENTS = [
    "-project",
    str(PROJECT),
    "-scheme",
    "VibeScreen",
    "CODE_SIGNING_ALLOWED=NO",
    "CODE_SIGNING_REQUIRED=NO",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run reproducible unsigned iOS simulator and archive gates."
    )
    parser.add_argument(
        "--action",
        choices=("all", "simulator-build", "simulator-test", "archive"),
        default="all",
        help="gate to run (default: all)",
    )
    return parser.parse_args()


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=IOS_ROOT, check=True)


# The iPhone UITests launch the app in the simulator, which occasionally wedges
# on hosted runners ("Timed out while launching application via Xcode" /
# "Failed to get background assertion"). That is simulator-launch flakiness, not
# a product regression, so retry the test action a bounded number of times after
# resetting simulator state, mirroring the CI test-retry the Android client uses.
SIMULATOR_TEST_ATTEMPTS = 2


def reset_simulators() -> None:
    # Shut down any wedged simulator so the retry boots cleanly. Avoid 'erase'
    # here: shutting down clears the launch-hang state without the extra cost of
    # wiping and re-provisioning every device.
    subprocess.run(
        ["xcrun", "simctl", "shutdown", "all"],
        cwd=IOS_ROOT,
        check=False,
    )


def action_arguments(name: str) -> list[str]:
    return [
        *COMMON_ARGUMENTS,
        "-derivedDataPath",
        str(DERIVED_DATA_ROOT / name),
    ]


def require_xcode() -> None:
    try:
        run(["xcodebuild", "-version"])
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise SystemExit(
            "Full Xcode with an iOS SDK is required; Command Line Tools alone are insufficient."
        ) from error


def available_iphone_destination() -> str:
    result = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "available", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    devices_by_runtime = json.loads(result.stdout)["devices"]
    for runtime, devices in sorted(devices_by_runtime.items(), reverse=True):
        if "iOS" not in runtime:
            continue
        for device in devices:
            if device.get("isAvailable") and device.get("name", "").startswith("iPhone"):
                return f"platform=iOS Simulator,id={device['udid']}"
    raise SystemExit("No available iPhone simulator runtime was found.")


def simulator_build() -> None:
    run([
        "xcodebuild",
        *action_arguments("simulator-build"),
        "-destination",
        "generic/platform=iOS Simulator",
        "build",
    ])


def simulator_test() -> None:
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, SIMULATOR_TEST_ATTEMPTS + 1):
        if attempt > 1:
            print(
                f"Simulator test attempt {attempt - 1} failed; "
                "resetting simulator state and retrying.",
                flush=True,
            )
            reset_simulators()
        try:
            run([
                "xcodebuild",
                *action_arguments("simulator-test"),
                "-destination",
                available_iphone_destination(),
                "ONLY_ACTIVE_ARCH=YES",
                "test",
            ])
            return
        except subprocess.CalledProcessError as error:
            last_error = error
    raise SystemExit(
        f"iOS simulator tests failed after {SIMULATOR_TEST_ATTEMPTS} attempts: {last_error}"
    )


def unsigned_archive() -> None:
    if ARCHIVE.exists():
        shutil.rmtree(ARCHIVE)
    run([
        "xcodebuild",
        *action_arguments("archive"),
        "-configuration",
        "Release",
        "-destination",
        "generic/platform=iOS",
        "-archivePath",
        str(ARCHIVE),
        "archive",
    ])
    app = ARCHIVE / "Products" / "Applications" / "VibeScreen.app"
    required_files = [app, app / "VibeScreen", app / "SwiftProtobuf-LICENSE.txt"]
    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        raise SystemExit(f"Unsigned archive is incomplete; missing: {', '.join(missing)}")
    print(ARCHIVE)


def main() -> None:
    args = parse_args()
    require_xcode()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    actions = {
        "simulator-build": simulator_build,
        "simulator-test": simulator_test,
        "archive": unsigned_archive,
    }
    if args.action == "all":
        for action in actions.values():
            action()
    else:
        actions[args.action]()


if __name__ == "__main__":
    main()
