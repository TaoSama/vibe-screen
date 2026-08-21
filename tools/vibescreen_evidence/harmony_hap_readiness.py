#!/usr/bin/env python3
"""Collect fail-closed HarmonyOS HAP lifecycle readiness evidence.

The collector records the local DevEco/OHPM/Hvigor/HDC environment, signing
inputs, signed HAP artifact state, selected HarmonyOS device pre-state, and
install/upgrade/rollback/uninstall observation references. It does not claim
MatePad acceptance by itself; use scripts/harmony_device_gate.py for the full
real-device gate manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import harmony_device_gate


SCHEMA = "dev.vibescreen.harmony-hap-readiness/v1"
BLOCKED_EXIT = 2
INSUFFICIENT_EXIT = 3
DEFAULT_APP_DIR = Path("apps/harmony")
DEFAULT_PACKAGE = "dev.vibescreen.harmony"
DEFAULT_VERSION = "0.1.0"
DEFAULT_HAP = DEFAULT_APP_DIR / "dist" / DEFAULT_VERSION / f"vibe-screen-harmony-{DEFAULT_VERSION}.hap"
DEFAULT_SHA256SUMS = DEFAULT_APP_DIR / "dist" / DEFAULT_VERSION / "SHA256SUMS"
LIFECYCLE_STEPS = ("install", "upgrade", "rollback", "uninstall_cleanup")
VALID_STEP_STATUS = {"pass", "blocked", "fail", "insufficient"}
PUBLIC_SIGNING_EXTENSIONS = {".cer", ".crt", ".csr", ".p7b"}


class ReadinessError(Exception):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Observation:
    field: str
    status: str
    requirement: str
    evidence: list[str]
    detail: str = ""


@dataclass(frozen=True)
class RepositoryState:
    commit: str
    tree: str
    status: str
    porcelain: str


@dataclass(frozen=True)
class ToolStatus:
    name: str
    path: str
    available: bool
    version: str
    returncode: int | None


@dataclass(frozen=True)
class ToolchainState:
    deveco_studio_path: str
    deveco_studio_version: str
    harmony_sdk_path: str
    harmony_sdk_api: str
    project_compatible_sdk: str
    ohpm: ToolStatus
    hvigor: ToolStatus
    hdc: ToolStatus


@dataclass(frozen=True)
class SigningState:
    build_profile: str
    signing_config_present: bool
    signing_material_paths: list[str]
    signature_certificate_sha256: str
    detail: str


@dataclass(frozen=True)
class ArtifactState:
    hap_path: str
    exists: bool
    sha256: str
    size_bytes: int
    zip_readable: bool
    signature_entries: list[str]
    sha256sums_path: str
    sha256sums_sha256: str


@dataclass(frozen=True)
class DeviceState:
    hdc_target: str
    target_selected: bool
    list_targets: str
    manufacturer: str
    model: str
    product: str
    os_build: str
    serial_hash: str
    package_prestate: str
    package_prestate_recorded: bool


@dataclass(frozen=True)
class LifecycleStep:
    name: str
    status: str
    evidence: list[str]
    detail: str


@dataclass(frozen=True)
class ReadinessResult:
    schema: str
    run_id: str
    created_at: str
    repository: RepositoryState
    toolchain: ToolchainState
    signing: SigningState
    artifact: ArtifactState
    device: DeviceState
    lifecycle: list[LifecycleStep]
    observations: list[Observation]
    summary: dict[str, Any]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_command(
    command: Sequence[str], *, cwd: Path | None = None, timeout: float = 20.0
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command), check=False, capture_output=True, text=True, cwd=cwd, timeout=timeout
        )
    except FileNotFoundError as error:
        raise ReadinessError(f"required command not found: {command[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise ReadinessError(f"command timed out: {' '.join(command)}") from error
    return CommandResult(list(command), completed.returncode, completed.stdout, completed.stderr)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path | str) -> str:
    value = Path(path)
    if not str(path):
        return ""
    try:
        resolved = value.resolve()
    except OSError:
        return str(path) if not value.is_absolute() else f"<external>/{value.name}"
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        pass
    try:
        return "~/" + str(resolved.relative_to(Path.home()))
    except ValueError:
        if value.is_absolute() or resolved.is_absolute():
            return f"<external>/{resolved.name or value.name}"
        return str(path)


def redact_hdc_target(target: str) -> str:
    if not target:
        return ""
    digest = hashlib.sha256(target.encode("utf-8")).hexdigest()
    return f"redacted-hdc-target-{digest[:12]}"


def redact_hdc_targets_output(output: str) -> str:
    lines: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("list of") or stripped.lower().startswith("empty") or stripped.startswith("#"):
            lines.append(line)
            continue
        prefix = line[: len(line) - len(line.lstrip())]
        parts = stripped.split(maxsplit=1)
        replacement = redact_hdc_target(parts[0])
        state = parts[1].split()[0] if len(parts) > 1 and parts[1].split() else "listed"
        lines.append(f"{prefix}{replacement} {state}")
    return "\n".join(lines) + ("\n" if output.endswith("\n") else "")


def hdc_executable() -> str:
    return shutil.which("hdc") or ""


def build_result_status(build_result: CommandResult | None) -> str:
    if build_result is None:
        return "insufficient"
    if build_result.returncode == 0:
        return "pass"
    output = f"{build_result.stdout}\n{build_result.stderr}".lower()
    if "harmonyos build blocked" in output or ("not found" in output and ("hvigor" in output or "ohpm" in output)):
        return "blocked"
    return "fail"


def repository_state(root: Path) -> RepositoryState:
    commit = run_command(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    tree = run_command(["git", "rev-parse", "HEAD^{tree}"], cwd=root).stdout.strip()
    porcelain = run_command(["git", "status", "--porcelain"], cwd=root).stdout
    return RepositoryState(commit, tree, "clean" if not porcelain.strip() else "dirty", porcelain)


def first_existing(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def read_deveco_version(app_path: Path | None) -> str:
    if app_path is None:
        return ""
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        return ""
    try:
        plist = plistlib.loads(plist_path.read_bytes())
    except Exception:
        return ""
    return str(plist.get("CFBundleShortVersionString") or plist.get("CFBundleVersion") or "")


def detect_deveco_studio() -> tuple[str, str]:
    candidates = [
        Path(value)
        for key in ("DEVECO_STUDIO_HOME", "DEVECO_HOME")
        for value in [os.environ.get(key, "")]
        if value
    ]
    candidates.extend([Path("/Applications/DevEco-Studio.app"), Path("/Applications/DevEco Studio.app")])
    app_path = first_existing(candidates)
    return (display_path(app_path) if app_path else "", read_deveco_version(app_path))


def command_version(name: str, command: Sequence[str]) -> ToolStatus:
    path = shutil.which(command[0])
    if path is None:
        return ToolStatus(name, "", False, "", None)
    result = run_command([path, *command[1:]], timeout=15.0)
    version = (result.stdout or result.stderr).strip()
    return ToolStatus(name, display_path(path), result.returncode == 0, version, result.returncode)


def project_compatible_sdk(app_dir: Path) -> str:
    profile = app_dir / "build-profile.json5"
    if not profile.exists():
        return ""
    match = re.search(r"compatibleSdkVersion\s*:\s*['\"]([^'\"]+)", profile.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def detect_harmony_sdk(explicit_path: str, explicit_api: str) -> tuple[str, str]:
    if explicit_path or explicit_api:
        return explicit_path, explicit_api
    candidates = [
        Path(value)
        for key in ("HARMONYOS_SDK_HOME", "OHOS_SDK_HOME", "DEVECO_SDK_HOME", "HOS_SDK_HOME")
        for value in [os.environ.get(key, "")]
        if value
    ]
    candidates.extend([Path.home() / "Library" / "Huawei" / "Sdk", Path.home() / "Library" / "OpenHarmony" / "Sdk"])
    sdk_path = first_existing(candidates)
    api = ""
    if sdk_path is not None:
        names = " ".join(child.name for child in sdk_path.iterdir() if child.is_dir())
        match = re.search(r"(?:api[-_ ]?)?(1[2-9]|[2-9][0-9])", names, re.IGNORECASE)
        api = f"API {match.group(1)}" if match else ""
    return display_path(sdk_path) if sdk_path else "", api


def harmony_sdk_api_is_supported(value: str) -> bool:
    return any(int(match.group(0)) >= 12 for match in re.finditer(r"\d+", value))


def collect_toolchain(app_dir: Path, args: argparse.Namespace) -> ToolchainState:
    deveco_path, deveco_version = detect_deveco_studio()
    if args.deveco_version:
        deveco_version = args.deveco_version
    sdk_path, sdk_api = detect_harmony_sdk(args.harmony_sdk_path or "", args.harmony_sdk_api or "")
    return ToolchainState(
        deveco_path,
        deveco_version,
        sdk_path,
        sdk_api,
        project_compatible_sdk(app_dir),
        command_version("ohpm", ["ohpm", "--version"]),
        command_version("hvigor", [shutil.which("hvigorw") or "hvigor", "--version"]),
        command_version("hdc", ["hdc", "-v"]),
    )


def collect_signing(app_dir: Path, certificate: Path | None, certificate_sha256: str) -> SigningState:
    if certificate is not None and certificate.suffix.lower() not in PUBLIC_SIGNING_EXTENSIONS:
        raise ReadinessError("--signature-certificate must reference a public certificate/profile file, not private key material")
    if certificate_sha256 and re.fullmatch(r"[0-9a-fA-F]{64}", certificate_sha256) is None:
        raise ReadinessError("--signature-certificate-sha256 must be a 64-character hex SHA-256 digest")
    profile = app_dir / "build-profile.json5"
    text_value = profile.read_text(encoding="utf-8") if profile.exists() else ""
    signing_config_present = bool(
        re.search(r"signingConfigs\s*:\s*\[[^\]]*\S[^\]]*\]", text_value, re.DOTALL)
        and not re.search(r"signingConfigs\s*:\s*\[\s*\]", text_value)
    )
    material_patterns = ("*.cer", "*.p7b", "*.csr")
    materials = sorted(str(path) for pattern in material_patterns for path in app_dir.rglob(pattern))
    digest = certificate_sha256.lower() if certificate_sha256 else ""
    if certificate is not None and certificate.exists():
        digest = sha256_file(certificate)
        materials.append(str(certificate))
    detail = "signingConfigs is empty" if profile.exists() and not signing_config_present else ""
    if not profile.exists():
        detail = "build-profile.json5 not found"
    return SigningState(display_path(profile), signing_config_present, sorted(set(display_path(path) for path in materials)), digest, detail)


def inspect_hap(hap_path: Path, sha256sums_path: Path) -> ArtifactState:
    if not hap_path.exists():
        return ArtifactState(display_path(hap_path), False, "", 0, False, [], display_path(sha256sums_path), "")
    signature_entries: list[str] = []
    zip_readable = False
    try:
        with zipfile.ZipFile(hap_path) as archive:
            zip_readable = True
            for name in archive.namelist():
                upper = name.upper()
                if upper.startswith("META-INF/") or upper.endswith((".SF", ".RSA", ".DSA", ".EC", ".P7B")):
                    signature_entries.append(name)
    except zipfile.BadZipFile:
        zip_readable = False
    sums_hash = sha256_file(sha256sums_path) if sha256sums_path.exists() else ""
    return ArtifactState(
        display_path(hap_path),
        True,
        sha256_file(hap_path),
        hap_path.stat().st_size,
        zip_readable,
        sorted(signature_entries),
        display_path(sha256sums_path),
        sums_hash,
    )


def list_hdc_targets(hdc: ToolStatus, hdc_command: str) -> CommandResult:
    if not hdc_command:
        return CommandResult(["hdc", "list", "targets", "-v"], 127, "", "hdc not found")
    return run_command([hdc_command, "list", "targets", "-v"], timeout=20.0)


def choose_hdc_target(list_output: str, requested: str) -> tuple[str, bool, str]:
    target_lines = [line.strip() for line in list_output.splitlines() if line.strip() and not line.lower().startswith("list of")]
    target_ids = [line.split()[0] for line in target_lines if not line.lower().startswith("empty")]
    if requested:
        return requested, requested in target_ids, "requested target not listed"
    if len(target_ids) == 1:
        return target_ids[0], True, ""
    if not target_ids:
        return "", False, "no HDC target listed"
    return "", False, "multiple HDC targets listed; pass --hdc-target explicitly"


def hdc_shell(hdc_command: str, target: str, args: Sequence[str]) -> CommandResult:
    return run_command([hdc_command, "-t", target, "shell", *args], timeout=20.0)


def collect_device(hdc: ToolStatus, requested_target: str, package_name: str, hdc_command: str) -> DeviceState:
    targets_result = list_hdc_targets(hdc, hdc_command)
    target, selected, detail = choose_hdc_target(targets_result.stdout, requested_target)
    manufacturer = model = product = os_build = package_prestate = ""
    prestate_recorded = False
    if hdc_command and selected and target:
        props = {
            "manufacturer": ["param", "get", "const.product.manufacturer"],
            "model": ["param", "get", "const.product.model"],
            "product": ["param", "get", "const.product.name"],
            "os_build": ["param", "get", "const.product.software.version"],
        }
        for key, command in props.items():
            result = hdc_shell(hdc_command, target, command)
            if result.returncode == 0:
                value = result.stdout.strip()
                if key == "manufacturer":
                    manufacturer = value
                elif key == "model":
                    model = value
                elif key == "product":
                    product = value
                else:
                    os_build = value
        package_result = hdc_shell(hdc_command, target, ["bm", "dump", "-n", package_name])
        package_prestate = (package_result.stdout + package_result.stderr).strip()
        prestate_recorded = bool(package_prestate)
    recorded_target = target if selected else ""
    serial_hash = hashlib.sha256(recorded_target.encode("utf-8")).hexdigest() if recorded_target else ""
    targets_text = redact_hdc_targets_output(targets_result.stdout + targets_result.stderr)
    if not selected and detail:
        targets_text += f"\n# {detail}\n"
    return DeviceState(
        redact_hdc_target(recorded_target),
        selected,
        targets_text,
        manufacturer,
        model,
        product,
        os_build,
        serial_hash,
        package_prestate,
        prestate_recorded,
    )


def load_lifecycle(path: Path | None) -> list[LifecycleStep]:
    if path is None:
        return [
            LifecycleStep(step, "insufficient", [], "no lifecycle observation manifest supplied")
            for step in LIFECYCLE_STEPS
        ]
    document = json.loads(path.read_text(encoding="utf-8"))
    steps = document.get("steps", document)
    if not isinstance(steps, dict):
        raise ReadinessError("lifecycle observations must be an object or contain a steps object")
    result: list[LifecycleStep] = []
    for step in LIFECYCLE_STEPS:
        raw = steps.get(step)
        if not isinstance(raw, dict):
            result.append(LifecycleStep(step, "insufficient", [], "step missing from lifecycle observations"))
            continue
        status = raw.get("status")
        evidence = raw.get("evidence", [])
        if status not in VALID_STEP_STATUS:
            raise ReadinessError(f"{step}.status must be one of {sorted(VALID_STEP_STATUS)}")
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(item, str) and item.strip() for item in evidence)
        ):
            raise ReadinessError(f"{step}.evidence must be a non-empty string array")
        result.append(LifecycleStep(step, status, evidence, str(raw.get("detail", ""))))
    return result


def build_observations(
    repository: RepositoryState,
    toolchain: ToolchainState,
    signing: SigningState,
    artifact: ArtifactState,
    device: DeviceState,
    lifecycle: Sequence[LifecycleStep],
    build_result: CommandResult | None,
) -> list[Observation]:
    release_build_status = build_result_status(build_result)
    device_identity = " ".join([device.manufacturer, device.model, device.product]).lower()
    matepad_identity_recorded = "matepad" in device_identity and "mini" in device_identity
    observations = [
        Observation(
            "repository_clean",
            "pass" if repository.status == "clean" else "blocked",
            "clean git source state",
            [repository.commit] if repository.status == "clean" else [],
            repository.porcelain.strip(),
        ),
        Observation(
            "deveco_studio_available",
            "pass" if bool(toolchain.deveco_studio_path or toolchain.deveco_studio_version) else "blocked",
            "DevEco Studio installed or version recorded",
            [toolchain.deveco_studio_path or toolchain.deveco_studio_version]
            if bool(toolchain.deveco_studio_path or toolchain.deveco_studio_version)
            else [],
            "",
        ),
        Observation(
            "harmony_sdk_api_recorded",
            "pass" if harmony_sdk_api_is_supported(toolchain.harmony_sdk_api) else "blocked",
            "HarmonyOS SDK API 12+ version recorded",
            [toolchain.harmony_sdk_api] if harmony_sdk_api_is_supported(toolchain.harmony_sdk_api) else [],
            f"project compatibleSdkVersion={toolchain.project_compatible_sdk}",
        ),
        Observation(
            "ohpm_available",
            "pass" if toolchain.ohpm.available else "blocked",
            "DevEco-managed ohpm is executable",
            [toolchain.ohpm.version] if toolchain.ohpm.available else [],
            toolchain.ohpm.path or "ohpm not found",
        ),
        Observation(
            "hvigor_available",
            "pass" if toolchain.hvigor.available else "blocked",
            "DevEco-managed hvigor/hvigorw is executable",
            [toolchain.hvigor.version] if toolchain.hvigor.available else [],
            toolchain.hvigor.path or "hvigor not found",
        ),
        Observation(
            "hdc_available",
            "pass" if toolchain.hdc.available else "blocked",
            "Harmony Device Connector is executable",
            [toolchain.hdc.version] if toolchain.hdc.available else [],
            toolchain.hdc.path or "hdc not found",
        ),
        Observation(
            "release_build_completed",
            release_build_status,
            "make release completed in apps/harmony",
            ["build-release.txt"] if release_build_status == "pass" else [],
            "build not requested" if build_result is None else (build_result.stdout + build_result.stderr).strip(),
        ),
        Observation(
            "signing_config_present",
            "pass" if signing.signing_config_present else "blocked",
            "non-empty Harmony signingConfigs present",
            [signing.build_profile] if signing.signing_config_present else [],
            signing.detail,
        ),
        Observation(
            "signed_hap_present",
            "pass" if artifact.exists and artifact.zip_readable and bool(artifact.signature_entries) else ("blocked" if not artifact.exists else "fail"),
            "signed release HAP archive with signature entries",
            [artifact.hap_path, *artifact.signature_entries]
            if artifact.exists and artifact.zip_readable and artifact.signature_entries
            else [],
            "HAP missing" if not artifact.exists else "signature entries missing or unreadable HAP",
        ),
        Observation(
            "signature_certificate_recorded",
            "pass" if bool(signing.signature_certificate_sha256) else "insufficient",
            "signing certificate SHA-256 recorded without private key material",
            [signing.signature_certificate_sha256] if signing.signature_certificate_sha256 else [],
            "pass --signature-certificate or --signature-certificate-sha256",
        ),
        Observation(
            "hdc_target_selected",
            "pass" if device.target_selected else "blocked",
            "exactly one HarmonyOS target selected or --hdc-target matched",
            [device.hdc_target] if device.target_selected else [],
            device.list_targets.strip(),
        ),
        Observation(
            "matepad_mini_identity_recorded",
            "pass" if matepad_identity_recorded else "blocked",
            "HarmonyOS MatePad Mini device identity recorded",
            [f"{device.manufacturer} {device.model} {device.product}".strip()]
            if matepad_identity_recorded
            else [],
            "HDC target unavailable"
            if not device.target_selected
            else f"recorded identity: {device.manufacturer} {device.model} {device.product}".strip(),
        ),
        Observation(
            "package_prestate_recorded",
            "pass" if device.package_prestate_recorded else ("blocked" if not device.target_selected else "insufficient"),
            "package state captured before install/upgrade/rollback/uninstall",
            ["package-prestate.txt"] if device.package_prestate_recorded else [],
            "HDC target unavailable" if not device.target_selected else "bm dump did not return package state",
        ),
    ]
    for step in lifecycle:
        observations.append(
            Observation(
                f"{step.name}_evidence_recorded",
                step.status,
                f"reviewed HDC/hilog/device evidence for {step.name.replace('_', ' ')}",
                step.evidence,
                step.detail,
            )
        )
    return observations


def summarize(observations: Sequence[Observation], run_id: str) -> dict[str, Any]:
    statuses = {observation.status for observation in observations}
    if "fail" in statuses:
        verdict = "fail"
    elif "blocked" in statuses:
        verdict = "blocked"
    elif "insufficient" in statuses:
        verdict = "insufficient"
    else:
        verdict = "pass"
    return {
        "run_id": run_id,
        "verdict": verdict,
        "can_close_hap_lifecycle_readiness": verdict == "pass",
        "missing_requirements": [asdict(observation) for observation in observations if observation.status != "pass"],
        "observed_fields": {observation.field: observation.status for observation in observations},
    }


def placeholder_hash(length: int) -> str:
    return "0" * length


def manifest_gate_status(summary: dict[str, Any], field: str) -> str:
    status = summary["observed_fields"].get(field, "blocked")
    return "blocked" if status == "insufficient" else status


def device_gate_manifest(result: ReadinessResult, package_name: str) -> dict[str, Any]:
    summary = result.summary
    toolchain = result.toolchain
    artifact = result.artifact
    signing = result.signing
    device = result.device
    device_identity = " ".join([device.manufacturer, device.model, device.product]).lower()
    matepad_identity_recorded = "matepad" in device_identity and "mini" in device_identity
    gate_evidence = {
        "deveco_sdk_and_api_checker": (
            "pass"
            if all(summary["observed_fields"].get(field) == "pass" for field in ("deveco_studio_available", "harmony_sdk_api_recorded", "ohpm_available", "hvigor_available"))
            else "blocked"
        ),
        "signed_release_hap": (
            "pass"
            if all(summary["observed_fields"].get(field) == "pass" for field in ("release_build_completed", "signing_config_present", "signed_hap_present", "signature_certificate_recorded"))
            else "blocked"
        ),
        "hap_install_launch": manifest_gate_status(summary, "install_evidence_recorded"),
        "hap_in_place_upgrade": manifest_gate_status(summary, "upgrade_evidence_recorded"),
        "hap_rollback_behavior": manifest_gate_status(summary, "rollback_evidence_recorded"),
        "hap_uninstall_cleanup": manifest_gate_status(summary, "uninstall_cleanup_evidence_recorded"),
    }
    gates = []
    for gate_id in harmony_device_gate.REQUIRED_GATE_IDS:
        status = gate_evidence.get(gate_id, "blocked")
        gates.append({"id": gate_id, "status": status, "evidence": ["harmony-hap-readiness.json"]})
    return {
        "schema": harmony_device_gate.SCHEMA,
        "repository": {
            "commit": result.repository.commit or placeholder_hash(40),
            "tree": result.repository.tree or placeholder_hash(40),
            "status": result.repository.status,
        },
        "toolchain": {
            "deveco_studio_version": toolchain.deveco_studio_version or "blocked: DevEco Studio not found",
            "harmony_sdk_api": toolchain.harmony_sdk_api or "blocked: HarmonyOS SDK API not recorded",
            "harmony_sdk_version": toolchain.harmony_sdk_api or "blocked: HarmonyOS SDK version not recorded",
            "hvigor_version": toolchain.hvigor.version or "blocked: hvigor not found",
            "ohpm_version": toolchain.ohpm.version or "blocked: ohpm not found",
            "hdc_version": toolchain.hdc.version or "blocked: hdc not found",
        },
        "artifact": {
            "bundle_name": package_name,
            "version_name": DEFAULT_VERSION,
            "hap_sha256": artifact.sha256 or placeholder_hash(64),
            "signature_certificate_sha256": signing.signature_certificate_sha256 or placeholder_hash(64),
            "sha256sums_sha256": artifact.sha256sums_sha256 or placeholder_hash(64),
        },
        "device": {
            "platform": "HarmonyOS NEXT" if matepad_identity_recorded else "blocked: HarmonyOS NEXT device identity not verified",
            "manufacturer": device.manufacturer if matepad_identity_recorded else "blocked: HDC MatePad Mini identity not recorded",
            "model": device.model if matepad_identity_recorded else "blocked: MatePad Mini identity not recorded",
            "product": device.product if matepad_identity_recorded else "blocked: MatePad Mini product not recorded",
            "os_build": device.os_build or "blocked: OS build not recorded",
            "hdc_target": device.hdc_target or "blocked: HDC target not selected",
            "serial_hash": device.serial_hash or placeholder_hash(64),
        },
        "host": {"commit": result.repository.commit or placeholder_hash(40), "build_sha256": placeholder_hash(64), "protocol": "Protocol v1"},
        "gates": gates,
        "notes": [
            "Generated by harmony_hap_readiness.py as readiness/blocking evidence.",
            "Validate with --allow-blocked unless every real-device gate has independent pass evidence.",
        ],
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_readme(path: Path, result: ReadinessResult) -> None:
    summary = result.summary
    lines = [
        f"# HarmonyOS HAP lifecycle readiness: {summary['verdict']}",
        "",
        f"Created: {result.created_at}",
        f"Run ID: {result.run_id}",
        f"Repository: {result.repository.commit} ({result.repository.status})",
        f"HAP: {result.artifact.hap_path}",
        f"HDC target: {result.device.hdc_target or 'not selected'}",
        "",
        "## Missing requirements",
        "",
    ]
    if summary["missing_requirements"]:
        lines.extend(
            f"- {item['field']}: {item['status']} - {item['requirement']}"
            for item in summary["missing_requirements"]
        )
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Captured artifacts",
        "",
        "- harmony-hap-readiness.json",
        "- harmony-hap-readiness-summary.json",
        "- harmony-device-gates.json (structure-only unless every gate is pass)",
        "- hdc-targets.txt",
        "- package-prestate.txt",
        "",
        "This readiness bundle does not close the HarmonyOS device gate unless harmony-hap-readiness-summary.json reports can_close_hap_lifecycle_readiness=true and the full harmony-device-gates.json passes without --allow-blocked.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_release_build(app_dir: Path, enabled: bool) -> CommandResult | None:
    if not enabled:
        return None
    return run_command(["make", "release"], cwd=app_dir, timeout=300.0)


def write_evidence_files(evidence_dir: Path, result: ReadinessResult, manifest: dict[str, Any], build_result: CommandResult | None) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    write_json(evidence_dir / "harmony-hap-readiness.json", asdict(result))
    write_json(evidence_dir / "harmony-hap-readiness-summary.json", result.summary)
    write_json(evidence_dir / "harmony-device-gates.json", manifest)
    (evidence_dir / "hdc-targets.txt").write_text(result.device.list_targets or "hdc target list unavailable\n", encoding="utf-8")
    (evidence_dir / "package-prestate.txt").write_text(result.device.package_prestate or "package pre-state unavailable\n", encoding="utf-8")
    if build_result is not None:
        (evidence_dir / "build-release.txt").write_text(build_result.stdout + build_result.stderr, encoding="utf-8")
    write_readme(evidence_dir / "README.md", result)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR, help=f"Harmony app directory. Default: {DEFAULT_APP_DIR}")
    parser.add_argument("--evidence-dir", type=Path, required=True, help="Directory where readiness evidence files will be written.")
    parser.add_argument("--hap", type=Path, default=DEFAULT_HAP, help=f"Expected signed release HAP path. Default: {DEFAULT_HAP}")
    parser.add_argument("--sha256sums", type=Path, default=DEFAULT_SHA256SUMS, help=f"Expected SHA256SUMS path. Default: {DEFAULT_SHA256SUMS}")
    parser.add_argument("--package", default=DEFAULT_PACKAGE, help=f"Harmony bundle name. Default: {DEFAULT_PACKAGE}")
    parser.add_argument("--hdc-target", default="", help="Exact HDC target to inspect when multiple devices are connected.")
    parser.add_argument("--run-build", action="store_true", help="Run make release in the Harmony app before inspecting artifacts.")
    parser.add_argument("--signature-certificate", type=Path, help="Public signing certificate/profile file to hash; private keys are never required.")
    parser.add_argument("--signature-certificate-sha256", default="", help="Precomputed signing certificate SHA-256 when the certificate file cannot be shared.")
    parser.add_argument("--deveco-version", default="", help="Manual DevEco Studio version override when CLI detection cannot read it.")
    parser.add_argument("--harmony-sdk-path", default="", help="Manual HarmonyOS SDK path override.")
    parser.add_argument("--harmony-sdk-api", default="", help="Manual HarmonyOS SDK API/version override, for example API 12.")
    parser.add_argument("--lifecycle-observations", type=Path, help="JSON with install/upgrade/rollback/uninstall_cleanup observation statuses and evidence paths.")
    parser.add_argument("--run-id", help="Identifier shared with generated evidence files.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    created_at = utc_timestamp()
    run_id = args.run_id or created_at.replace(":", "").replace("-", "")
    repo_root = REPO_ROOT
    try:
        app_dir = args.app_dir if args.app_dir.is_absolute() else repo_root / args.app_dir
        hap_path = args.hap if args.hap.is_absolute() else repo_root / args.hap
        sha256sums_path = args.sha256sums if args.sha256sums.is_absolute() else repo_root / args.sha256sums
        repository = repository_state(repo_root)
        toolchain = collect_toolchain(app_dir, args)
        build_result = run_release_build(app_dir, args.run_build)
        signing = collect_signing(app_dir, args.signature_certificate, args.signature_certificate_sha256)
        artifact = inspect_hap(hap_path, sha256sums_path)
        device = collect_device(toolchain.hdc, args.hdc_target, args.package, hdc_executable())
        lifecycle = load_lifecycle(args.lifecycle_observations)
        observations = build_observations(repository, toolchain, signing, artifact, device, lifecycle, build_result)
        summary = summarize(observations, run_id)
        result = ReadinessResult(
            SCHEMA, run_id, created_at, repository, toolchain, signing, artifact, device, lifecycle, observations, summary
        )
        manifest = device_gate_manifest(result, args.package)
        write_evidence_files(args.evidence_dir, result, manifest, build_result)
        verdict = summary["verdict"]
        print(f"HarmonyOS HAP lifecycle readiness: {verdict}")
        print(f"summary: {args.evidence_dir / 'harmony-hap-readiness-summary.json'}")
        if verdict == "pass":
            return 0
        if verdict == "blocked":
            return BLOCKED_EXIT
        if verdict == "insufficient":
            return INSUFFICIENT_EXIT
        return 1
    except (OSError, json.JSONDecodeError, ReadinessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
