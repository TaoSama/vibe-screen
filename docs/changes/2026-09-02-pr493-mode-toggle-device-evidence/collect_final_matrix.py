#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_ROOT = REPO_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from vibescreen_evidence.android_instrumentation_cleanup import (
    CleanupCommandResult,
    DEFAULT_TEST_PACKAGE,
    cleanup_android_instrumentation_test_package,
    instrumentation_cleanup_result_errors,
    require_instrumentation_cleanup_ok,
)


PACKAGE = "dev.telemachus.display"
TEST_PACKAGE = DEFAULT_TEST_PACKAGE
ACTIVITY = "dev.telemachus.display/.MainActivity"
EXPECTED_DEVICE_MANUFACTURER = "nubia"
EXPECTED_DEVICE_MODEL = "P0110"
EXPECTED_DEVICE_CODENAME = "pacific"
EXPECTED_ANDROID_RELEASE = "16"
EXPECTED_ANDROID_SDK = "36"
EXPECTED_REDACTED_SERIAL = "<redacted-adb-serial>"
EXPECTED_DEVICE_IDENTITY = {
    "manufacturer": EXPECTED_DEVICE_MANUFACTURER,
    "model": EXPECTED_DEVICE_MODEL,
    "codename": EXPECTED_DEVICE_CODENAME,
    "android_release": EXPECTED_ANDROID_RELEASE,
    "sdk": EXPECTED_ANDROID_SDK,
    "adb_serial": EXPECTED_REDACTED_SERIAL,
}
EXPECTED_APK_SHA256 = "076333b301475dfe3d949eab3c80f626053f3b68e95e500c4a8911ad669d4a87"
EXPECTED_ANDROID_TEST_APK_SHA256 = "0f2c36d433dc855f3b8b1407ba984887894f90025954963eded29d8aa66536b9"
REMOTE_PREFIX = "/sdcard/vibe_pr493_076333b"
TEXT_SUFFIXES = {".json", ".log", ".md", ".txt", ".xml"}
LOCAL_ADB_BINARY_PATTERN = re.compile(r"(^|[=\s])/\S*/(?:Library/Android/sdk|Android/Sdk)/platform-tools/adb")
XML_DUMP_ATTEMPTS_PER_MODE = 2
XML_DUMP_RETRY_DELAY_SECONDS = 1
EXPECTED_XML_SEMANTIC_EVIDENCE_SCOPE = "semantic_minimum_only_not_stable_state"
EXPECTED_DEVICE_IDENTITY_EVIDENCE = "metadata/device-identity.txt"
SCENARIOS = [
    ("phone-portrait-day-font1", 0, "1.0", "no", (1264, 2800)),
    ("phone-portrait-night-font1", 0, "1.0", "yes", (1264, 2800)),
    ("phone-portrait-day-font13", 0, "1.3", "no", (1264, 2800)),
    ("phone-portrait-night-font13", 0, "1.3", "yes", (1264, 2800)),
    ("phone-landscape-day-font1", 1, "1.0", "no", (2800, 1264)),
    ("phone-landscape-night-font1", 1, "1.0", "yes", (2800, 1264)),
    ("phone-landscape-day-font13", 1, "1.3", "no", (2800, 1264)),
    ("phone-landscape-night-font13", 1, "1.3", "yes", (2800, 1264)),
]
MIN_SEMANTIC_XML_PRESENT_COUNT = 2
REQUIRED_SEMANTIC_XML_LABELS = (
    "phone-portrait-day-font1",
    "phone-portrait-night-font1",
)
EXPECTED_SCENARIO_LABELS = tuple(label for label, *_ in SCENARIOS)
KNOWN_XML_STATUSES = {"present", "unavailable", "rejected"}
REQUIRED_RESTORE_KEYS = (
    "font_scale_1_0",
    "night_no",
    "rotation_0",
    "accelerometer_rotation_0",
    "no_override_size",
    "packages_stopped",
)


def run(args, *, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def command_output(proc):
    return proc.stdout + proc.stderr


def require_success(proc, description):
    if proc.returncode != 0:
        raise RuntimeError(f"{description} failed: {command_output(proc)}")
    return proc


def require_success_text(proc, description):
    require_success(proc, description)
    return proc.stdout


def adb(serial, *args):
    adb_bin = os.environ.get("ADB", str(Path.home() / "Library/Android/sdk/platform-tools/adb"))
    return run([adb_bin, "-s", serial, *args])


def adb_required(serial, *args, description=None):
    return require_success(adb(serial, *args), description or "adb " + " ".join(args))


def adb_text(serial, *args, description=None):
    return require_success_text(adb(serial, *args), description or "adb " + " ".join(args))


def redact(text, serial):
    redacted = text.replace(serial, "<redacted-adb-serial>")
    return LOCAL_ADB_BINARY_PATTERN.sub(r"\1adb", redacted)


def write_text(path, text, serial):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact(text, serial), encoding="utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_sha(path, expected_sha, label):
    actual_sha = sha256(path)
    if actual_sha != expected_sha:
        raise SystemExit(f"unexpected {label} sha256: {actual_sha}")
    return actual_sha


def log(log_file, message):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")


def parse_png_size(path):
    with path.open("rb") as f:
        header = f.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def assert_no_serial_leak(out_dir, serial):
    leaked_paths = []
    for path in out_dir.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if serial in path.read_text(encoding="utf-8", errors="ignore"):
            leaked_paths.append(str(path.relative_to(out_dir)))
    if leaked_paths:
        raise SystemExit("raw device serial remained in evidence: " + ", ".join(leaked_paths))


def assert_reverse_empty(serial, metadata_dir, label):
    proc = adb(serial, "reverse", "--list")
    output = command_output(proc)
    write_text(metadata_dir / f"adb-reverse-{label}.txt", output, serial)
    require_success(proc, f"adb reverse --list {label}")
    if output.strip():
        raise SystemExit(f"adb reverse --list was not empty at {label}")


def collect_state(serial):
    size = adb_text(serial, "shell", "wm", "size", description="wm size")
    density = adb_text(serial, "shell", "wm", "density", description="wm density")
    font = adb_text(serial, "shell", "settings", "get", "system", "font_scale", description="font scale").strip()
    night = adb_text(serial, "shell", "cmd", "uimode", "night", description="night mode")
    rotation = adb_text(serial, "shell", "cmd", "window", "user-rotation", description="user rotation")
    accel = adb_text(
        serial,
        "shell",
        "settings",
        "get",
        "system",
        "accelerometer_rotation",
        description="accelerometer rotation",
    ).strip()
    user_rotation = adb_text(serial, "shell", "settings", "get", "system", "user_rotation", description="system rotation").strip()
    window = adb_text(serial, "shell", "dumpsys", "window", description="dumpsys window")
    summary_lines = []
    for line in window.splitlines():
        if (
            "mCurrentFocus=" in line
            or "mFocusedApp=" in line
            or "mDisplayRotation=" in line
            or "DisplayFrames" in line
            or "mGlobalConfiguration=" in line
            or "overrideConfig=" in line
        ):
            summary_lines.append(line)
    return (
        size
        + density
        + f"font_scale: {font}\n"
        + f"Night mode: {night.strip()}\n"
        + rotation
        + f"accelerometer_rotation: {accel}\n"
        + f"user_rotation: {user_rotation}\n"
        + "--- window summary ---\n"
        + "\n".join(summary_lines)
        + "\n"
    )


def state_matches(state, expected_rotation, expected_font, expected_night, *, require_activity):
    expected_orientation = "land" if expected_rotation == 1 else "port"
    expected_display_rotation = "ROTATION_90" if expected_rotation == 1 else "ROTATION_0"
    checks = [
        f"font_scale: {expected_font}" in state,
        f"Night mode: Night mode: {expected_night}" in state,
        f"user_rotation: {expected_rotation}" in state,
        "accelerometer_rotation: 0" in state,
        expected_display_rotation in state,
        expected_orientation in state,
        "Override size" not in state,
    ]
    if require_activity:
        checks.append(f"{PACKAGE}/.MainActivity" in state)
    return all(checks)


def wait_for_state(serial, expected_rotation, expected_font, expected_night, *, require_activity=True, timeout=12):
    deadline = time.time() + timeout
    last_state = ""
    while time.time() < deadline:
        last_state = collect_state(serial)
        if state_matches(last_state, expected_rotation, expected_font, expected_night, require_activity=require_activity):
            return last_state
        time.sleep(1)
    return last_state


def configure_visual_settings(serial, font, night):
    adb_required(serial, "shell", "settings", "put", "system", "font_scale", font, description="set font scale")
    adb_required(serial, "shell", "cmd", "uimode", "night", night, description="set night mode")
    adb_required(
        serial,
        "shell",
        "settings",
        "put",
        "system",
        "accelerometer_rotation",
        "0",
        description="disable accelerometer rotation",
    )


def lock_rotation(serial, rotation):
    adb_required(serial, "shell", "cmd", "window", "user-rotation", "lock", str(rotation), description="lock rotation")
    adb_required(serial, "shell", "settings", "put", "system", "user_rotation", str(rotation), description="set user_rotation")


def restore_device(serial):
    adb_required(serial, "shell", "settings", "put", "system", "font_scale", "1.0", description="restore font scale")
    adb_required(serial, "shell", "cmd", "uimode", "night", "no", description="restore night mode")
    adb_required(
        serial,
        "shell",
        "settings",
        "put",
        "system",
        "accelerometer_rotation",
        "0",
        description="restore accelerometer rotation",
    )
    lock_rotation(serial, 0)


def force_stop_apps(serial):
    adb_required(serial, "shell", "am", "force-stop", PACKAGE, description="force-stop app")


def cleanup_instrumentation_test_package(serial, metadata_dir):
    def runner(name, package_name, command):
        proc = adb(serial, *command)
        return CleanupCommandResult(
            name=name,
            package_name=package_name,
            command=tuple(command),
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    result = cleanup_android_instrumentation_test_package(runner, test_package=TEST_PACKAGE)
    write_text(
        metadata_dir / "android-instrumentation-cleanup.json",
        json.dumps(result.to_dict(), indent=2) + "\n",
        serial,
    )
    require_instrumentation_cleanup_ok(result)
    return result


def assert_packages_stopped(serial):
    for package_name in (PACKAGE, TEST_PACKAGE):
        proc = adb(serial, "shell", "pidof", package_name)
        if proc.returncode == 0 and proc.stdout.strip():
            raise SystemExit(f"package still running after restore: {package_name}")


def launch_activity(serial):
    proc = adb(serial, "shell", "am", "start", "-S", "-W", "-n", ACTIVITY, "--ez", "auto_connect", "true")
    require_success(proc, "launch MainActivity")
    time.sleep(3)
    return proc


def normalized_identity_value(value):
    if value is None:
        return None
    return str(value).strip().lower()


def public_device_identity(identity):
    return {key: identity[key] for key in EXPECTED_DEVICE_IDENTITY}


def device_identity_errors(device):
    if not isinstance(device, dict):
        return [f"device must be an object: {type(device).__name__}"]
    errors = []
    for key, expected in EXPECTED_DEVICE_IDENTITY.items():
        actual = device.get(key)
        if key == "adb_serial" and actual != EXPECTED_REDACTED_SERIAL:
            errors.append(f"device.{key} must be redacted: {actual!r}")
            continue
        if normalized_identity_value(actual) != normalized_identity_value(expected):
            errors.append(f"device.{key} mismatch: {actual!r}")
    return errors


def collect_device_identity(serial, metadata_dir, *, adb_text_func=adb_text):
    devices_output = adb_text_func(serial, "devices", description="adb devices")
    properties = (
        ("manufacturer", "ro.product.manufacturer"),
        ("model", "ro.product.model"),
        ("device", "ro.product.device"),
        ("vendor_codename", "ro.product.vendor.device"),
        ("build_product", "ro.build.product"),
        ("android_release", "ro.build.version.release"),
        ("sdk", "ro.build.version.sdk"),
    )
    identity = {
        key: adb_text_func(serial, "shell", "getprop", prop, description=f"device identity {prop}").strip()
        for key, prop in properties
    }
    identity["codename"] = identity["device"]
    identity["adb_serial"] = EXPECTED_REDACTED_SERIAL
    write_text(metadata_dir / "device-manufacturer.txt", identity["manufacturer"] + "\n", serial)
    write_text(metadata_dir / "device-model.txt", identity["model"] + "\n", serial)
    write_text(metadata_dir / "device-codename.txt", identity["device"] + "\n", serial)
    write_text(metadata_dir / "android-version.txt", identity["android_release"] + "\n", serial)
    write_text(metadata_dir / "android-api.txt", identity["sdk"] + "\n", serial)

    lines = [
        "Android device identity from independent read-only adb commands",
        f"Recorded at: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        (
            "Scope: device identity only; no Host, GUI, product binary, adb reverse creation, "
            "adb reverse modification, or adb reverse deletion was used."
        ),
        "",
        "adb devices",
        devices_output.rstrip("\n"),
    ]
    for key, prop in properties:
        lines.extend(
            [
                "",
                f"adb -s {EXPECTED_REDACTED_SERIAL} shell getprop {prop}",
                identity[key],
            ]
        )
    write_text(metadata_dir / "device-identity.txt", "\n".join(lines) + "\n", serial)
    return identity


def bounds_are_nonzero(bounds):
    try:
        left_top, right_bottom = bounds.strip().split("][")
        left, top = (int(value) for value in left_top.lstrip("[").split(","))
        right, bottom = (int(value) for value in right_bottom.rstrip("]").split(","))
    except (AttributeError, ValueError):
        return False
    return right > left and bottom > top


def node_texts_and_checks(xml_path):
    root = ElementTree.parse(xml_path).getroot()
    texts = []
    mode_checks = {"modeUSB": [], "modeWireless": [], "modeInternet": []}
    progress_visible = False
    for node in root.iter("node"):
        resource_id = node.attrib.get("resource-id", "")
        text = node.attrib.get("text", "")
        if text:
            texts.append(text)
        for mode_id in ("modeUSB", "modeWireless", "modeInternet"):
            if resource_id.endswith(f":id/{mode_id}"):
                mode_checks[mode_id].append(node.attrib.get("checked", ""))
        if resource_id.endswith(":id/connectionProgress"):
            progress_visible = progress_visible or bounds_are_nonzero(node.attrib.get("bounds", ""))
    return texts, mode_checks, progress_visible


def is_xml_stable_state(xml_path):
    texts, _mode_checks, progress_visible = node_texts_and_checks(xml_path)
    text_blob = "\n".join(texts)
    has_terminal_error_ui = "TRY AGAIN" in text_blob or "USB route unavailable" in text_blob
    return not (progress_visible and has_terminal_error_ui)


def validate_scenario_xml(xml_path):
    texts, mode_checks, _progress_visible = node_texts_and_checks(xml_path)
    text_blob = "\n".join(texts)
    errors = []
    if mode_checks.get("modeUSB") != ["true"]:
        errors.append("USB mode is not checked")
    if mode_checks.get("modeWireless") != ["false"]:
        errors.append("LAN mode is not unchecked")
    if mode_checks.get("modeInternet") != ["false"]:
        errors.append("Internet mode is not unchecked")
    expected_fragments = [
        "USB",
        "LAN",
        "Internet",
        "Waiting for your Mac",
        "Keep the USB cable connected",
        "TRY AGAIN",
        "USB route unavailable",
        "The Android-to-Mac route is unavailable",
        "USB repair action",
    ]
    for fragment in expected_fragments:
        if fragment not in text_blob:
            errors.append(f"missing XML text: {fragment}")
    return errors


def xml_coverage_errors(results):
    if not isinstance(results, list):
        return [f"scenarios must be a list: {type(results).__name__}"]
    type_errors = []
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            type_errors.append(f"scenario[{index}] must be an object: {type(result).__name__}")
    if type_errors:
        return type_errors
    labels = [result.get("label", "<unknown>") for result in results]
    present_labels = {
        result.get("label")
        for result in results
        if result.get("xml_status") == "present"
    }
    rejected_labels = [
        result.get("label", "<unknown>")
        for result in results
        if result.get("xml_status") == "rejected"
    ]
    errors = []
    unknown_statuses = [
        f"{label}={result.get('xml_status')!r}"
        for label, result in zip(labels, results)
        if result.get("xml_status") not in KNOWN_XML_STATUSES
    ]
    missing_xml_errors = [
        label
        for label, result in zip(labels, results)
        if result.get("xml_status") == "present" and "xml_errors" not in result
    ]
    missing_xml_stable_state = [
        label
        for label, result in zip(labels, results)
        if result.get("xml_status") == "present" and "xml_stable_state" not in result
    ]
    invalid_xml_stable_state = [
        f"{label}={type(result.get('xml_stable_state')).__name__}"
        for label, result in zip(labels, results)
        if result.get("xml_status") == "present"
        and "xml_stable_state" in result
        and not isinstance(result.get("xml_stable_state"), bool)
    ]
    invalid_xml_errors = [
        f"{label}={type(result.get('xml_errors')).__name__}"
        for label, result in zip(labels, results)
        if result.get("xml_status") == "present"
        and "xml_errors" in result
        and not isinstance(result.get("xml_errors"), list)
    ]
    present_with_errors = [
        label
        for label, result in zip(labels, results)
        if result.get("xml_status") == "present"
        and isinstance(result.get("xml_errors"), list)
        and result.get("xml_errors")
    ]
    if unknown_statuses:
        errors.append("unknown XML status: " + ", ".join(unknown_statuses))
    if missing_xml_errors:
        errors.append("present XML missing xml_errors: " + ", ".join(missing_xml_errors))
    if missing_xml_stable_state:
        errors.append("present XML missing xml_stable_state: " + ", ".join(missing_xml_stable_state))
    if invalid_xml_errors:
        errors.append("present XML xml_errors must be a list: " + ", ".join(invalid_xml_errors))
    if invalid_xml_stable_state:
        errors.append("present XML xml_stable_state must be a bool: " + ", ".join(invalid_xml_stable_state))
    if present_with_errors:
        errors.append("present XML has validation errors: " + ", ".join(present_with_errors))
    if rejected_labels:
        errors.append("XML rejected for: " + ", ".join(rejected_labels))
    if len(present_labels) < MIN_SEMANTIC_XML_PRESENT_COUNT:
        errors.append(
            "semantic XML coverage below minimum: "
            f"{len(present_labels)}/{MIN_SEMANTIC_XML_PRESENT_COUNT} present"
        )
    missing_required = [
        label for label in REQUIRED_SEMANTIC_XML_LABELS if label not in present_labels
    ]
    if missing_required:
        errors.append("required semantic XML missing: " + ", ".join(missing_required))
    return errors


def scenario_label_errors(results):
    if not isinstance(results, list):
        return [f"scenarios must be a list: {type(results).__name__}"]
    type_errors = []
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            type_errors.append(f"scenario[{index}] must be an object: {type(result).__name__}")
    if type_errors:
        return type_errors
    labels = [result.get("label", "<unknown>") for result in results]
    expected_labels = set(EXPECTED_SCENARIO_LABELS)
    actual_labels = set(labels)
    errors = []
    duplicate_labels = sorted({label for label in labels if labels.count(label) > 1})
    missing_labels = [label for label in EXPECTED_SCENARIO_LABELS if label not in actual_labels]
    unknown_labels = sorted(actual_labels - expected_labels)
    if duplicate_labels:
        errors.append("duplicate scenario labels: " + ", ".join(duplicate_labels))
    if missing_labels:
        errors.append("missing scenario labels: " + ", ".join(missing_labels))
    if unknown_labels:
        errors.append("unknown scenario labels: " + ", ".join(unknown_labels))
    return errors


def restored_gate_errors(restored):
    errors = []
    if not isinstance(restored, dict):
        return [f"restored must be an object: {type(restored).__name__}"]
    actual_keys = set(restored)
    expected_keys = set(REQUIRED_RESTORE_KEYS)
    missing_keys = [key for key in REQUIRED_RESTORE_KEYS if key not in actual_keys]
    unknown_keys = sorted(actual_keys - expected_keys)
    if missing_keys:
        errors.append("missing restored keys: " + ", ".join(missing_keys))
    if unknown_keys:
        errors.append("unknown restored keys: " + ", ".join(unknown_keys))
    for key in REQUIRED_RESTORE_KEYS:
        value = restored.get(key)
        if value is not True:
            errors.append(f"restored.{key} is not verified true: {value!r}")
    return errors


def instrumentation_cleanup_gate_errors(cleanup):
    return instrumentation_cleanup_result_errors(cleanup, expected_package=TEST_PACKAGE)


def summary_gate_errors(summary):
    errors = []
    if not isinstance(summary, dict):
        return [f"summary must be an object: {type(summary).__name__}"]
    if summary.get("apk_sha256") != EXPECTED_APK_SHA256:
        errors.append(f"apk_sha256 mismatch: {summary.get('apk_sha256')!r}")
    if summary.get("android_test_apk_sha256") != EXPECTED_ANDROID_TEST_APK_SHA256:
        errors.append(f"android_test_apk_sha256 mismatch: {summary.get('android_test_apk_sha256')!r}")
    errors.extend(device_identity_errors(summary.get("device")))
    if "device_model" in summary and summary.get("device_model") != EXPECTED_DEVICE_MODEL:
        errors.append(f"device_model mismatch: {summary.get('device_model')!r}")
    if summary.get("xml_evidence_scope") != EXPECTED_XML_SEMANTIC_EVIDENCE_SCOPE:
        errors.append(f"xml_evidence_scope mismatch: {summary.get('xml_evidence_scope')!r}")
    if summary.get("device_identity_evidence") != EXPECTED_DEVICE_IDENTITY_EVIDENCE:
        errors.append(f"device_identity_evidence mismatch: {summary.get('device_identity_evidence')!r}")
    if summary.get("instrumentation_p0110_landscape_large_text") is not True:
        errors.append("instrumentation p0110 landscape large-text layout failed")
    errors.extend(instrumentation_cleanup_gate_errors(summary.get("android_instrumentation_cleanup")))
    results = summary.get("scenarios", [])
    scenario_errors = scenario_label_errors(results)
    errors.extend(scenario_errors)
    scenarios_are_well_formed = isinstance(results, list) and all(isinstance(result, dict) for result in results)
    if scenarios_are_well_formed:
        for result in results:
            label = result.get("label", "<unknown>")
            if result.get("png_ok") is not True:
                errors.append(f"{label} PNG size validation failed")
            if result.get("state_ok") is not True:
                errors.append(f"{label} state validation failed")
        errors.extend(xml_coverage_errors(results))
    errors.extend(restored_gate_errors(summary.get("restored", {})))
    return errors


def remote_file_mtime(serial, remote_path):
    proc = adb(serial, "shell", "stat", "-c", "%Y", remote_path)
    if proc.returncode != 0:
        return None, command_output(proc)
    try:
        return int(proc.stdout.strip()), command_output(proc)
    except ValueError:
        return None, command_output(proc)


def device_epoch_seconds(serial):
    proc = adb(serial, "shell", "date", "+%s")
    require_success(proc, "read device clock")
    return int(proc.stdout.strip())


def append_process_evidence(lines, prefix, proc):
    lines.append(f"{prefix}_returncode={proc.returncode}")
    lines.append(f"{prefix}_stdout_begin")
    lines.append(proc.stdout.rstrip("\n"))
    lines.append(f"{prefix}_stdout_end")
    lines.append(f"{prefix}_stderr_begin")
    lines.append(proc.stderr.rstrip("\n"))
    lines.append(f"{prefix}_stderr_end")


def write_xml_attempt_evidence(metadata_dir, label, lines, serial):
    write_text(metadata_dir / f"{label}.pull-xml.txt", "\n".join(lines).rstrip() + "\n", serial)


def append_remote_stat_evidence(lines, prefix, remote_mtime, remote_stat_output):
    lines.append(f"{prefix}_stat_begin")
    lines.append(remote_stat_output.rstrip("\n"))
    lines.append(f"{prefix}_stat_end")
    lines.append(f"{prefix}_mtime={remote_mtime}")


def uiautomator_dump_args(remote_xml, compressed):
    if compressed:
        return ("shell", "uiautomator", "dump", "--compressed", remote_xml)
    return ("shell", "uiautomator", "dump", remote_xml)


def capture_ui_xml(
    serial,
    metadata_dir,
    label,
    remote_xml,
    local_xml,
    *,
    attempts_per_mode=XML_DUMP_ATTEMPTS_PER_MODE,
    retry_delay_seconds=XML_DUMP_RETRY_DELAY_SECONDS,
    adb_func=adb,
    device_epoch_func=device_epoch_seconds,
    remote_mtime_func=remote_file_mtime,
    validate_func=validate_scenario_xml,
    sleep_func=time.sleep,
):
    if attempts_per_mode < 1:
        raise ValueError("attempts_per_mode must be positive")

    local_xml.unlink(missing_ok=True)
    attempt_lines = []
    rejected_errors = []
    attempt_number = 0
    total_attempts = attempts_per_mode * 2

    for compressed in (False, True):
        mode = "compressed" if compressed else "normal"
        for mode_attempt in range(1, attempts_per_mode + 1):
            attempt_number += 1
            attempt_lines.append(f"attempt={attempt_number}")
            attempt_lines.append(f"mode={mode}")
            attempt_lines.append(f"mode_attempt={mode_attempt}")
            local_xml.unlink(missing_ok=True)

            remove_remote = adb_func(serial, "shell", "rm", "-f", remote_xml)
            append_process_evidence(attempt_lines, "remote_delete", remove_remote)
            if remove_remote.returncode != 0:
                attempt_lines.append("result=remote_delete_failed")
                write_xml_attempt_evidence(metadata_dir, label, attempt_lines, serial)
                raise RuntimeError(f"remote XML delete failed before dump attempt: {label} {mode} #{mode_attempt}")

            pre_dump_mtime, pre_dump_stat_output = remote_mtime_func(serial, remote_xml)
            append_remote_stat_evidence(attempt_lines, "pre_dump_remote", pre_dump_mtime, pre_dump_stat_output)
            if pre_dump_mtime is not None:
                attempt_lines.append("result=remote_delete_left_file")
                write_xml_attempt_evidence(metadata_dir, label, attempt_lines, serial)
                raise RuntimeError(f"remote XML remained after delete before dump attempt: {label} {mode} #{mode_attempt}")

            dump_started_at = device_epoch_func(serial)
            dump = adb_func(serial, *uiautomator_dump_args(remote_xml, compressed))
            dump_output = command_output(dump)
            remote_mtime, remote_stat_output = remote_mtime_func(serial, remote_xml)
            remote_fresh = remote_mtime is not None and remote_mtime >= dump_started_at

            attempt_lines.append(f"dump_started_at={dump_started_at}")
            append_process_evidence(attempt_lines, "dump", dump)
            append_remote_stat_evidence(attempt_lines, "post_dump_remote", remote_mtime, remote_stat_output)
            attempt_lines.append(f"remote_fresh={str(remote_fresh).lower()}")

            if dump.returncode == 0 and "ERROR" not in dump_output and remote_fresh:
                pull_xml = adb_func(serial, "pull", remote_xml, str(local_xml))
                append_process_evidence(attempt_lines, "pull", pull_xml)
                if pull_xml.returncode != 0:
                    local_xml.unlink(missing_ok=True)
                    attempt_lines.append("result=pull_failed")
                elif not local_xml.exists():
                    attempt_lines.append("result=pull_missing_local")
                    write_xml_attempt_evidence(metadata_dir, label, attempt_lines, serial)
                    raise SystemExit(f"XML pull reported success but local XML is missing: {label}")
                else:
                    try:
                        xml_errors = validate_func(local_xml)
                    except Exception as exc:
                        xml_errors = [f"parse failed: {exc}"]
                    if xml_errors:
                        rejected_errors.extend(xml_errors)
                        local_xml.unlink(missing_ok=True)
                        attempt_lines.append("result=rejected")
                        attempt_lines.append("xml_errors=" + "; ".join(xml_errors))
                    else:
                        attempt_lines.append("result=present")
                        write_xml_attempt_evidence(metadata_dir, label, attempt_lines, serial)
                        return "present", []
            else:
                local_xml.unlink(missing_ok=True)
                if dump.returncode == 0 and "ERROR" not in dump_output:
                    attempt_lines.append("result=remote_xml_missing_or_stale")
                else:
                    attempt_lines.append("result=dump_invalid")

            write_xml_attempt_evidence(metadata_dir, label, attempt_lines, serial)
            if attempt_number < total_attempts:
                sleep_func(retry_delay_seconds)

    local_xml.unlink(missing_ok=True)
    if rejected_errors:
        attempt_lines.append("final_status=rejected")
        attempt_lines.append("fresh XML was captured but rejected; no later valid XML was accepted")
        attempt_lines.append("final_xml_errors=" + "; ".join(rejected_errors))
        write_xml_attempt_evidence(metadata_dir, label, attempt_lines, serial)
        return "rejected", rejected_errors
    attempt_lines.append("final_status=unavailable")
    attempt_lines.append("no fresh valid XML captured; not pulling stale XML")
    write_xml_attempt_evidence(metadata_dir, label, attempt_lines, serial)
    return "unavailable", []


def capture_scenario(serial, out_dir, log_file, label, rotation, font, night, expected_size):
    log(log_file, f"scenario {label} rotation={rotation} font={font} night={night}")
    screenshots = out_dir / "screenshots"
    metadata = out_dir / "metadata"
    logs = out_dir / "logs"
    timestamp_ms = int(time.time() * 1000)
    remote_png = f"{REMOTE_PREFIX}_{timestamp_ms}_{label}.png"
    remote_xml = f"{REMOTE_PREFIX}_{timestamp_ms}_{label}.xml"
    local_xml = metadata / f"{label}.xml"
    local_xml.unlink(missing_ok=True)
    adb_required(serial, "shell", "rm", "-f", remote_png, remote_xml, description="clear remote capture files")

    configure_visual_settings(serial, font, night)
    if rotation == 0:
        lock_rotation(serial, 0)
    start = launch_activity(serial)
    write_text(logs / f"{label}.am-start.txt", command_output(start), serial)
    if rotation == 1:
        lock_rotation(serial, 1)
        ready_state = wait_for_state(serial, rotation, font, night)
        if not state_matches(ready_state, rotation, font, night, require_activity=True):
            write_text(metadata / f"{label}.wait-state-failed.txt", ready_state, serial)
            raise SystemExit(f"scenario state did not reach expected landscape rotation: {label}")

    state_before = wait_for_state(serial, rotation, font, night)
    write_text(metadata / f"{label}.state-before.txt", state_before, serial)

    cap = adb(serial, "shell", "screencap", "-p", remote_png)
    write_text(metadata / f"{label}.screencap.txt", command_output(cap), serial)
    require_success(cap, f"screencap {label}")
    pull_png = adb(serial, "pull", remote_png, str(screenshots / f"{label}.png"))
    write_text(metadata / f"{label}.pull-png.txt", command_output(pull_png), serial)
    require_success(pull_png, f"pull screenshot {label}")

    xml_status, xml_errors = capture_ui_xml(serial, metadata, label, remote_xml, local_xml)
    xml_stable_state = False
    if xml_status == "present" and local_xml.exists():
        xml_stable_state = is_xml_stable_state(local_xml)

    state_after = collect_state(serial)
    write_text(metadata / f"{label}.state-after.txt", state_after, serial)
    adb_required(serial, "shell", "rm", "-f", remote_png, remote_xml, description="remove remote capture files")

    actual_size = parse_png_size(screenshots / f"{label}.png")
    return {
        "label": label,
        "png_size": actual_size,
        "expected_size": expected_size,
        "png_ok": actual_size == expected_size,
        "state_ok": state_matches(state_after, rotation, font, night, require_activity=True),
        "xml_status": xml_status,
        "xml_errors": xml_errors,
        "xml_stable_state": xml_stable_state,
    }


def run_instrumentation(serial, out_dir):
    test_class = (
        "dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest#"
        "p0110LandscapeLargeTextKeepsUsbRetryFirstAndGuidanceScrollable"
    )
    proc = adb(
        serial,
        "shell",
        "am",
        "instrument",
        "-w",
        "-r",
        "-e",
        "class",
        test_class,
        "dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner",
    )
    write_text(out_dir / "logs" / "instrumentation-p0110-landscape-large-text.txt", command_output(proc), serial)
    return proc.returncode == 0 and "FAILURES!!!" not in proc.stdout and "OK (1 test)" in proc.stdout


def assert_install_succeeded(proc, label):
    output = command_output(proc)
    if proc.returncode != 0 or "Success" not in output:
        raise SystemExit(f"{label} install failed: {output}")


def write_summary(out_dir, serial, summary):
    write_text(out_dir / "metadata" / "validation.json", json.dumps(summary, indent=2) + "\n", serial)
    lines = [
        "Final PR493 device matrix validation",
        f"APK SHA-256: {summary['apk_sha256']}",
        f"AndroidTest APK SHA-256: {summary['android_test_apk_sha256']}",
        f"Device: {summary['device']}",
        f"Device identity evidence: {summary['device_identity_evidence']}",
        f"Instrumentation p0110 landscape large-text layout: {'PASS' if summary['instrumentation_p0110_landscape_large_text'] else 'FAIL'}",
        "Scenarios:",
    ]
    for result in summary["scenarios"]:
        line = (
            "- {label}: {png_size[0]}x{png_size[1]}; expected {expected_size[0]}x{expected_size[1]}; "
            "png_ok={png_ok}; state_ok={state_ok}; xml={xml_status}; "
            "xml_stable_state={xml_stable_state}".format(**result)
        )
        if result.get("xml_errors"):
            line += "; xml_errors=" + "; ".join(result["xml_errors"])
        lines.append(line)
    xml_statuses = {result["xml_status"] for result in summary["scenarios"]}
    xml_counts = {status: sum(1 for result in summary["scenarios"] if result["xml_status"] == status) for status in xml_statuses}
    lines.append(f"XML status counts: {xml_counts}")
    lines.append(f"XML evidence scope: {summary['xml_evidence_scope']}")
    xml_errors = xml_coverage_errors(summary["scenarios"])
    lines.append(f"XML semantic coverage: {'PASS' if not xml_errors else 'FAIL'}")
    if xml_errors:
        lines.extend(f"- {error}" for error in xml_errors)
    lines.append(f"Restored: {summary['restored']}")
    cleanup = summary.get("android_instrumentation_cleanup")
    if cleanup is not None:
        lines.append(f"Android instrumentation cleanup: {cleanup}")
    write_text(out_dir / "metadata" / "final-validation-summary.txt", "\n".join(lines) + "\n", serial)


def run_final_cleanup(serial, log_file, *, original_failure=None, metadata_dir=None):
    cleanup_steps = (
        ("restore_device", restore_device),
        ("force_stop_apps", force_stop_apps),
        (
            "cleanup_instrumentation_test_package",
            lambda serial: cleanup_instrumentation_test_package(serial, metadata_dir or log_file.parent),
        ),
        ("assert_packages_stopped", assert_packages_stopped),
    )
    first_cleanup_failure = None
    for step_name, cleanup_step in cleanup_steps:
        try:
            cleanup_step(serial)
        except BaseException as cleanup_failure:
            log(log_file, f"cleanup step {step_name} failed: {cleanup_failure}")
            if first_cleanup_failure is None:
                first_cleanup_failure = cleanup_failure
    if original_failure is None and first_cleanup_failure is not None:
        raise first_cleanup_failure


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve()
    android_dir = repo / "baseline" / "AndroidClient"
    apk = android_dir / "app/build/outputs/apk/debug/app-debug.apk"
    test_apk = android_dir / "app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
    actual_sha = assert_sha(apk, EXPECTED_APK_SHA256, "app APK")
    actual_test_sha = assert_sha(test_apk, EXPECTED_ANDROID_TEST_APK_SHA256, "androidTest APK")

    out_dir = args.out.resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "screenshots").mkdir(parents=True)
    (out_dir / "metadata").mkdir(parents=True)
    (out_dir / "logs").mkdir(parents=True)
    log_file = out_dir / "logs" / "run.log"
    metadata = out_dir / "metadata"

    serial = args.serial
    original_failure = None
    cleanup_completed = False
    try:
        log(log_file, "adb devices")
        write_text(metadata / "adb-devices.txt", adb_text(serial, "devices", description="adb devices"), serial)
        assert_reverse_empty(serial, metadata, "before")
        write_text(metadata / "apk-sha256.txt", f"{actual_sha}  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk\n", serial)
        write_text(
            metadata / "androidTest-apk-sha256.txt",
            f"{actual_test_sha}  baseline/AndroidClient/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk\n",
            serial,
        )
        identity = collect_device_identity(serial, metadata)
        identity_errors = device_identity_errors(public_device_identity(identity))
        if identity_errors:
            raise SystemExit("unexpected device identity: " + "; ".join(identity_errors))

        log(log_file, "install app and test apks")
        install = adb(serial, "install", "-r", str(apk))
        write_text(out_dir / "logs" / "install.txt", command_output(install), serial)
        assert_install_succeeded(install, "app")
        install_test = adb(serial, "install", "-r", str(test_apk))
        write_text(out_dir / "logs" / "install-android-test.txt", command_output(install_test), serial)
        assert_install_succeeded(install_test, "androidTest")
        assert_reverse_empty(serial, metadata, "after")

        log(log_file, "run target instrumentation")
        instrumentation_ok = run_instrumentation(serial, out_dir)

        results = []
        for scenario in SCENARIOS:
            results.append(capture_scenario(serial, out_dir, log_file, *scenario))

        log(log_file, "restore device")
        restore_device(serial)
        force_stop_apps(serial)
        instrumentation_cleanup = cleanup_instrumentation_test_package(serial, metadata)
        restored = wait_for_state(serial, 0, "1.0", "no", require_activity=False)
        write_text(metadata / "final-restored.state-after.txt", restored, serial)
        assert_packages_stopped(serial)
        assert_reverse_empty(serial, metadata, "final")
        cleanup_completed = True

        summary = {
            "apk_sha256": actual_sha,
            "android_test_apk_sha256": actual_test_sha,
            "device": public_device_identity(identity),
            "device_identity_evidence": EXPECTED_DEVICE_IDENTITY_EVIDENCE,
            "xml_evidence_scope": EXPECTED_XML_SEMANTIC_EVIDENCE_SCOPE,
            "instrumentation_p0110_landscape_large_text": instrumentation_ok,
            "scenarios": results,
            "restored": {
                "font_scale_1_0": "font_scale: 1.0" in restored,
                "night_no": "Night mode: Night mode: no" in restored,
                "rotation_0": "user_rotation: 0" in restored and "ROTATION_0" in restored,
                "accelerometer_rotation_0": "accelerometer_rotation: 0" in restored,
                "no_override_size": "Override size" not in restored,
                "packages_stopped": True,
            },
            "android_instrumentation_cleanup": instrumentation_cleanup.to_dict(),
        }
        write_summary(out_dir, serial, summary)
        assert_no_serial_leak(out_dir, serial)

        gate_errors = summary_gate_errors(summary)
        if gate_errors:
            for error in gate_errors:
                log(log_file, f"validation gate failed: {error}")
            raise SystemExit(1)
    except BaseException as failure:
        original_failure = failure
        raise
    finally:
        if not cleanup_completed:
            run_final_cleanup(serial, log_file, original_failure=original_failure, metadata_dir=metadata)


if __name__ == "__main__":
    main()
