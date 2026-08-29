#!/usr/bin/env python3
"""Collect HarmonyOS NEXT / MatePad Mini readiness evidence.

This preflight is deliberately read-only. It records whether the local machine
has the proprietary DevEco/HarmonyOS command-line tools, a signed HAP artifact,
and an attached MatePad Mini-class HDC target. It does not build, install, pair,
stream, or mutate a connected device.

Exit codes are fail-closed for automation:

- 0: every readiness prerequisite is present; this is not device acceptance.
- 2: one or more prerequisites are blocked or missing.
- 1: the script itself could not create a trustworthy readiness report.
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
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from vibescreen_evidence import SCHEMA_VERSION  # noqa: E402
from vibescreen_evidence.manifest import ManifestError, repository_state  # noqa: E402

BLOCKED_EXIT = 2
KIND = "harmony_readiness_preflight"
DEFAULT_BUNDLE_NAME = "dev.vibescreen.harmony"
DEFAULT_HAP_GLOB = "apps/harmony/dist/*/*.hap"
HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
USER_HOME_PATH_RE = re.compile(r"(?:/Users|/home|/Volumes)/[^\s'\",]+")
WINDOWS_USER_PATH_RE = re.compile(r"[A-Za-z]:\\Users\\[^\s'\"]+")
TCC_PATH_RE = re.compile(r"Application Support/com\.apple\.TCC|\bTCC\.db\b", re.IGNORECASE)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|-----END [A-Z ]*PRIVATE KEY-----")

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
WhichRunner = Callable[[str], str | None]


class ReadinessError(RuntimeError):
    """Raised when a readiness report cannot be written reliably."""


@dataclass(frozen=True)
class Probe:
    name: str
    status: str
    path: str | None = None
    version: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class HdcTarget:
    target_hash: str
    state: str
    raw_summary: str


@dataclass(frozen=True)
class DeviceIdentity:
    platform: str
    manufacturer: str
    model: str
    product: str
    os_build: str
    sdk_api: str
    hdc_target_hash: str
    serial_hash: str
    is_matepad_mini: bool


@dataclass(frozen=True)
class ArtifactReadiness:
    hap_path: str | None
    hap_sha256: str | None
    hap_zip_readable: bool
    signature_markers: list[str]
    signature_certificate_sha256: str | None
    sha256sums_path: str | None
    sha256sums_sha256: str | None
    sha256sums_contains_hap: bool
    bundle_name: str
    version_name: str | None


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact_hdc_target(target: str) -> str:
    if not target:
        return ""
    return f"sha256:{sha256_text(target)[:12]}"


def sanitize_public_text(value: str) -> str:
    if not value:
        return ""
    text = value.replace(str(REPO_ROOT), "<repo>").replace(str(Path.home()), "<home>")
    text = TCC_PATH_RE.sub("<tcc-path>", text)
    text = USER_HOME_PATH_RE.sub("<user-path>", text)
    text = WINDOWS_USER_PATH_RE.sub("<user-path>", text)
    text = PRIVATE_KEY_RE.sub("<private-key-marker>", text)
    return text


def display_path(path: Path | str | None, *, repo: Path = REPO_ROOT) -> str | None:
    if path is None:
        return None
    value = Path(path)
    try:
        resolved = value.expanduser().resolve()
    except OSError:
        return sanitize_public_text(str(path)) if not value.is_absolute() else f"<external>/{value.name}"
    try:
        return str(resolved.relative_to(repo.resolve()))
    except (OSError, ValueError):
        pass
    if value.is_absolute() or resolved.is_absolute():
        return f"<external>/{resolved.name or value.name}"
    return sanitize_public_text(str(path))


def public_command(command: Sequence[str], *, repo: Path) -> list[str]:
    path_options = {"--output", "--repo", "--deveco-studio-app", "--hap", "--sha256sums"}
    target_options = {"--target"}
    result: list[str] = []
    skip: str | None = None
    for token in command:
        if skip == "path":
            result.append(display_path(token, repo=repo) or "")
            skip = None
            continue
        if skip == "target":
            result.append(redact_hdc_target(token))
            skip = None
            continue
        matched_inline = False
        for option in path_options:
            if token.startswith(option + "="):
                result.append(f"{option}={display_path(token.split('=', 1)[1], repo=repo)}")
                matched_inline = True
                break
        if matched_inline:
            continue
        for option in target_options:
            if token.startswith(option + "="):
                result.append(f"{option}={redact_hdc_target(token.split('=', 1)[1])}")
                matched_inline = True
                break
        if matched_inline:
            continue
        result.append(sanitize_public_text(token))
        if token in path_options:
            skip = "path"
        elif token in target_options:
            skip = "target"
    return result


def public_probe(probe: Probe, *, repo: Path) -> dict[str, str | None]:
    return {
        "name": probe.name,
        "status": probe.status,
        "path": display_path(probe.path, repo=repo),
        "version": sanitize_public_text(probe.version or "") or None,
        "detail": sanitize_public_text(probe.detail or "") or None,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(
    command: Sequence[str],
    *,
    timeout_seconds: float = 15.0,
    command_runner: CommandRunner = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    try:
        return command_runner(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise ReadinessError(f"command not found: {command[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise ReadinessError(f"command timed out: {' '.join(command)}") from error
    except OSError as error:
        raise ReadinessError(f"command could not start: {' '.join(command)}: {error}") from error


def first_line(value: str) -> str:
    for line in value.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def probe_tool(
    name: str,
    version_args: Sequence[str],
    *,
    which_runner: WhichRunner = shutil.which,
    command_runner: CommandRunner = subprocess.run,
) -> Probe:
    path = which_runner(name)
    if path is None:
        return Probe(name=name, status="blocked", detail=f"{name} not found on PATH")
    try:
        result = run_command([path, *version_args], command_runner=command_runner)
    except ReadinessError as error:
        return Probe(name=name, status="blocked", path=path, detail=str(error))
    output = first_line(result.stdout) or first_line(result.stderr)
    if result.returncode != 0:
        return Probe(
            name=name,
            status="blocked",
            path=path,
            version=output or None,
            detail=f"{name} version command exited {result.returncode}",
        )
    return Probe(name=name, status="pass", path=path, version=output or "version output empty")


def detect_deveco_studio(path_override: Path | None = None) -> Probe:
    candidates: list[Path] = []
    if path_override is not None:
        candidates.append(path_override)
    for env_name in ("DEVECO_STUDIO_APP", "DEVECO_STUDIO_HOME"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value))
    candidates.append(Path("/Applications/DevEco Studio.app"))
    candidates.append(Path("/Applications/DevEco-Studio.app"))

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        if not candidate.exists():
            continue
        version = None
        plist_path = candidate / "Contents" / "Info.plist"
        if plist_path.exists():
            try:
                info = plistlib.loads(plist_path.read_bytes())
                short = str(info.get("CFBundleShortVersionString", "")).strip()
                build = str(info.get("CFBundleVersion", "")).strip()
                version = " ".join(item for item in (short, build) if item) or None
            except (OSError, plistlib.InvalidFileException, ValueError):
                version = "present, version unreadable"
        return Probe(
            name="deveco_studio",
            status="pass",
            path=str(candidate),
            version=version or "present, version not detected",
        )

    return Probe(
        name="deveco_studio",
        status="blocked",
        detail="DevEco Studio app not found; set DEVECO_STUDIO_APP or --deveco-studio-app",
    )


def parse_hdc_targets(output: str) -> list[tuple[str, str, str]]:
    targets: list[tuple[str, str, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("list of"):
            continue
        fields = line.split()
        if not fields:
            continue
        target = fields[0]
        state = fields[1] if len(fields) > 1 else "unknown"
        if target.lower() in {"empty", "none"}:
            continue
        targets.append((target, state, line))
    return targets


def hdc_shell(
    hdc_path: str,
    target: str,
    arguments: Sequence[str],
    *,
    command_runner: CommandRunner = subprocess.run,
) -> str:
    result = run_command(
        [hdc_path, "-t", target, "shell", *arguments],
        timeout_seconds=15.0,
        command_runner=command_runner,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise ReadinessError(f"hdc shell {' '.join(arguments)} failed: {detail}")
    return result.stdout.strip()


def first_non_empty_property(
    hdc_path: str,
    target: str,
    property_names: Sequence[str],
    *,
    command_runner: CommandRunner = subprocess.run,
) -> str:
    for property_name in property_names:
        try:
            value = hdc_shell(hdc_path, target, ["param", "get", property_name], command_runner=command_runner)
        except ReadinessError:
            continue
        value = value.strip()
        if value and not value.lower().startswith("fail"):
            return value
    return "unknown"


def read_harmony_device_identity(
    hdc_path: str,
    target: str,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> DeviceIdentity:
    manufacturer = first_non_empty_property(
        hdc_path,
        target,
        ("const.product.manufacturer", "const.product.brand"),
        command_runner=command_runner,
    )
    model = first_non_empty_property(
        hdc_path,
        target,
        ("const.product.model", "const.product.hardwareprofile"),
        command_runner=command_runner,
    )
    product = first_non_empty_property(
        hdc_path,
        target,
        ("const.product.name", "const.product.devicetype"),
        command_runner=command_runner,
    )
    os_build = first_non_empty_property(
        hdc_path,
        target,
        (
            "const.ohos.fullname",
            "const.product.software.version",
            "const.ohos.version",
            "const.product.build.id",
        ),
        command_runner=command_runner,
    )
    sdk_api = first_non_empty_property(
        hdc_path,
        target,
        ("const.ohos.apiversion", "const.product.apiversion"),
        command_runner=command_runner,
    )
    serial = first_non_empty_property(
        hdc_path,
        target,
        ("const.product.serial", "ohos.boot.sn", "const.product.udid"),
        command_runner=command_runner,
    )
    identity_text = " ".join((manufacturer, model, product)).lower()
    return DeviceIdentity(
        platform="HarmonyOS NEXT" if "harmony" in os_build.lower() or sdk_api != "unknown" else "unknown",
        manufacturer=manufacturer,
        model=model,
        product=product,
        os_build=os_build,
        sdk_api=sdk_api,
        hdc_target_hash=sha256_text(target),
        serial_hash=sha256_text(serial if serial != "unknown" else target),
        is_matepad_mini="matepad" in identity_text and "mini" in identity_text,
    )


def _redact_target(line: str, target: str) -> str:
    return line.replace(target, redact_hdc_target(target))


def collect_hdc_status(
    hdc_probe: Probe,
    requested_target: str | None,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> tuple[list[HdcTarget], DeviceIdentity | None, list[str]]:
    reasons: list[str] = []
    if hdc_probe.status != "pass" or hdc_probe.path is None:
        return [], None, ["hdc is unavailable"]

    result = run_command([hdc_probe.path, "list", "targets", "-v"], command_runner=command_runner)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        return [], None, [f"hdc list targets -v failed: {detail}"]
    raw_targets = parse_hdc_targets(result.stdout)
    targets = [
        HdcTarget(target_hash=sha256_text(target), state=state, raw_summary=_redact_target(line, target))
        for target, state, line in raw_targets
    ]

    selected_target: str | None = requested_target.strip() if requested_target and requested_target.strip() else None
    if selected_target is None:
        ready_targets = [target for target, state, _line in raw_targets if state.lower() in {"device", "connected", "online", "unknown"}]
        if len(ready_targets) != 1:
            return targets, None, [f"expected exactly one HDC target or --target, found {len(ready_targets)}"]
        selected_target = ready_targets[0]
    elif selected_target not in [target for target, _state, _line in raw_targets]:
        reasons.append("requested HDC target is not present in hdc list targets -v")

    try:
        identity = read_harmony_device_identity(hdc_probe.path, selected_target, command_runner=command_runner)
    except ReadinessError as error:
        return targets, None, reasons + [str(error)]
    if identity.platform not in {"HarmonyOS", "HarmonyOS NEXT"}:
        reasons.append("selected target did not expose HarmonyOS platform properties")
    if not identity.is_matepad_mini:
        reasons.append("selected target identity is not MatePad Mini-class")
    return targets, identity, reasons


def find_default_hap(repo: Path) -> Path | None:
    matches = sorted(repo.glob(DEFAULT_HAP_GLOB))
    return matches[0] if len(matches) == 1 else None


def inspect_hap(
    repo: Path,
    hap_path: Path | None,
    sha256sums_path: Path | None,
    signature_certificate_sha256: str | None,
    bundle_name: str,
    version_name: str | None,
) -> tuple[ArtifactReadiness, list[str]]:
    reasons: list[str] = []
    resolved_hap = hap_path or find_default_hap(repo)
    hap_hash = None
    zip_readable = False
    signature_markers: list[str] = []
    if resolved_hap is None:
        reasons.append(f"signed HAP not found; pass --hap or create exactly one {DEFAULT_HAP_GLOB}")
    elif not resolved_hap.is_file():
        reasons.append(f"HAP does not exist: {display_path(resolved_hap, repo=repo)}")
    else:
        hap_hash = sha256_file(resolved_hap)
        try:
            with zipfile.ZipFile(resolved_hap) as archive:
                names = archive.namelist()
            zip_readable = True
            signature_markers = sorted(
                name for name in names if "signature" in name.lower() or name.upper().startswith("META-INF/")
            )[:20]
            if not signature_markers:
                reasons.append("HAP archive has no recognizable signature marker; verify signing output manually")
        except zipfile.BadZipFile:
            reasons.append(f"HAP is not a readable zip archive: {display_path(resolved_hap, repo=repo)}")

    cert_hash = signature_certificate_sha256.lower() if signature_certificate_sha256 else None
    if cert_hash is None or HASH_RE.fullmatch(cert_hash) is None or set(cert_hash) == {"0"}:
        reasons.append("signature certificate SHA-256 is required and must be non-zero 64-hex")

    resolved_sha256sums = sha256sums_path
    if resolved_sha256sums is None and resolved_hap is not None:
        candidate = resolved_hap.parent / "SHA256SUMS"
        if candidate.exists():
            resolved_sha256sums = candidate

    sha256sums_hash = None
    sha256sums_contains_hap = False
    if resolved_sha256sums is None:
        reasons.append("SHA256SUMS manifest not found beside the HAP; pass --sha256sums")
    elif not resolved_sha256sums.is_file():
        reasons.append(f"SHA256SUMS does not exist: {display_path(resolved_sha256sums, repo=repo)}")
    else:
        sha256sums_hash = sha256_file(resolved_sha256sums)
        if hap_hash is not None:
            try:
                sha256sums_contains_hap = hap_hash in resolved_sha256sums.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                sha256sums_contains_hap = False
            if not sha256sums_contains_hap:
                reasons.append("SHA256SUMS does not contain the selected HAP SHA-256")

    artifact = ArtifactReadiness(
        hap_path=display_path(resolved_hap, repo=repo) if resolved_hap is not None else None,
        hap_sha256=hap_hash,
        hap_zip_readable=zip_readable,
        signature_markers=signature_markers,
        signature_certificate_sha256=cert_hash,
        sha256sums_path=display_path(resolved_sha256sums, repo=repo) if resolved_sha256sums is not None else None,
        sha256sums_sha256=sha256sums_hash,
        sha256sums_contains_hap=sha256sums_contains_hap,
        bundle_name=bundle_name,
        version_name=version_name,
    )
    return artifact, reasons


def _git_tree(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def build_report(
    *,
    command: Sequence[str],
    repo: Path,
    deveco: Probe,
    hvigor: Probe,
    ohpm: Probe,
    hdc: Probe,
    hdc_targets: list[HdcTarget],
    device: DeviceIdentity | None,
    artifact: ArtifactReadiness,
    host_commit: str | None,
    host_build_sha256: str | None,
    blocking_reasons: list[str],
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    try:
        ignore_paths = [evidence_dir] if evidence_dir is not None else []
        repo_state = repository_state(repo.resolve(), ignore_paths=ignore_paths)
    except ManifestError as error:
        repo_state = {"revision": "unknown", "dirty": True, "status_porcelain": [str(error)]}
        blocking_reasons.append(str(error))

    if repo_state.get("dirty") is True:
        blocking_reasons.append("repository has uncommitted changes; final device evidence must bind a clean tree")

    if host_commit is None:
        blocking_reasons.append("Protocol v1 Host commit is required")
    elif re.fullmatch(r"[0-9a-f]{40}", host_commit) is None:
        blocking_reasons.append("host commit must be 40 lowercase hex")
    if host_build_sha256 is None:
        blocking_reasons.append("Protocol v1 Host build SHA-256 is required")
    elif HASH_RE.fullmatch(host_build_sha256) is None:
        blocking_reasons.append("host build SHA-256 must be 64 hex")

    toolchain_reasons = [
        sanitize_public_text(probe.detail or f"{probe.name} unavailable")
        for probe in (deveco, hvigor, ohpm, hdc)
        if probe.status != "pass"
    ]
    all_reasons = [*toolchain_reasons, *(sanitize_public_text(reason) for reason in blocking_reasons)]
    verdict = "pass" if not all_reasons else "blocked"

    final_manifest_prefill = {
        "repository": {
            "commit": repo_state.get("revision"),
            "tree": _git_tree(repo),
            "status": "clean" if repo_state.get("dirty") is False else "dirty",
        },
        "toolchain": {
            "deveco_studio_version": deveco.version,
            "harmony_sdk_api": device.sdk_api if device is not None else None,
            "harmony_sdk_version": device.os_build if device is not None else None,
            "hvigor_version": hvigor.version,
            "ohpm_version": ohpm.version,
            "hdc_version": hdc.version,
        },
        "artifact": {
            "bundle_name": artifact.bundle_name,
            "version_name": artifact.version_name,
            "hap_sha256": artifact.hap_sha256,
            "signature_certificate_sha256": artifact.signature_certificate_sha256,
            "sha256sums_sha256": artifact.sha256sums_sha256,
        },
        "device": {
            "platform": device.platform,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "product": device.product,
            "os_build": device.os_build,
            "hdc_target": f"sha256:{device.hdc_target_hash}",
            "serial_hash": device.serial_hash,
        } if device is not None else None,
        "host": {
            "commit": host_commit,
            "build_sha256": host_build_sha256,
            "protocol": "Protocol v1",
        },
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "created_at": utc_timestamp(),
        "command": public_command(command, repo=repo),
        "verdict": verdict,
        "blocking_reasons": all_reasons,
        "repository": repo_state,
        "toolchain": {
            "deveco_studio": public_probe(deveco, repo=repo),
            "hvigor": public_probe(hvigor, repo=repo),
            "ohpm": public_probe(ohpm, repo=repo),
            "hdc": public_probe(hdc, repo=repo),
        },
        "hdc": {
            "targets": [
                {**asdict(target), "raw_summary": sanitize_public_text(target.raw_summary)}
                for target in hdc_targets
            ],
        },
        "device": asdict(device) if device is not None else None,
        "artifact": asdict(artifact),
        "host": {
            "commit": host_commit,
            "build_sha256": host_build_sha256,
            "protocol": "Protocol v1",
        },
        "device_gate_prefill": final_manifest_prefill,
        "limitations": [
            "This readiness preflight is not HarmonyOS device acceptance evidence.",
            "It does not build, install, launch, pair, stream, decode, inject input, soak, or measure external-camera latency.",
        ],
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Path for harmony-readiness.json")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--deveco-studio-app", type=Path, help="DevEco Studio .app or install root")
    parser.add_argument("--target", help="Explicit HDC target. If omitted, exactly one target must be online.")
    parser.add_argument("--hap", type=Path, help=f"Signed HAP path. Defaults to exactly one {DEFAULT_HAP_GLOB}.")
    parser.add_argument("--sha256sums", type=Path, help="SHA256SUMS path for the HAP release directory.")
    parser.add_argument("--signature-certificate-sha256", help="Non-zero SHA-256 of the signing certificate used for the HAP.")
    parser.add_argument("--bundle-name", default=DEFAULT_BUNDLE_NAME)
    parser.add_argument("--version-name", default="0.1.0")
    parser.add_argument("--host-commit", help="Protocol v1 Mac Host commit used for device acceptance.")
    parser.add_argument("--host-build-sha256", help="SHA-256 of the Protocol v1 Mac Host build under test.")
    return parser


def collect_readiness(
    args: argparse.Namespace,
    *,
    command: Sequence[str] | None = None,
    command_runner: CommandRunner = subprocess.run,
    which_runner: WhichRunner = shutil.which,
) -> dict[str, Any]:
    deveco = detect_deveco_studio(args.deveco_studio_app)
    hvigor = probe_tool("hvigor", ("--version",), which_runner=which_runner, command_runner=command_runner)
    if hvigor.status != "pass":
        hvigorw = probe_tool("hvigorw", ("--version",), which_runner=which_runner, command_runner=command_runner)
        if hvigorw.status == "pass":
            hvigor = hvigorw
    ohpm = probe_tool("ohpm", ("--version",), which_runner=which_runner, command_runner=command_runner)
    hdc = probe_tool("hdc", ("-v",), which_runner=which_runner, command_runner=command_runner)

    target_rows, device, hdc_reasons = collect_hdc_status(hdc, args.target, command_runner=command_runner)
    artifact, artifact_reasons = inspect_hap(
        args.repo,
        args.hap,
        args.sha256sums,
        args.signature_certificate_sha256,
        args.bundle_name,
        args.version_name,
    )
    output = getattr(args, "output", None)
    evidence_dir = output.parent if isinstance(output, Path) else None
    return build_report(
        command=command or ["scripts/harmony_readiness.py"],
        repo=args.repo,
        deveco=deveco,
        hvigor=hvigor,
        ohpm=ohpm,
        hdc=hdc,
        hdc_targets=target_rows,
        device=device,
        artifact=artifact,
        host_commit=args.host_commit,
        host_build_sha256=args.host_build_sha256,
        blocking_reasons=[*hdc_reasons, *artifact_reasons],
        evidence_dir=evidence_dir,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = ["scripts/harmony_readiness.py", *(argv if argv is not None else sys.argv[1:])]
    try:
        report = collect_readiness(args, command=command)
        write_json(args.output, report)
    except (ReadinessError, ManifestError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"HarmonyOS readiness: {report['verdict']}")
    print(f"report: {args.output}")
    for reason in report["blocking_reasons"]:
        print(f"- {reason}")
    return 0 if report["verdict"] == "pass" else BLOCKED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
