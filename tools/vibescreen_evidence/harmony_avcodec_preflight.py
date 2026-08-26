"""Create and validate HarmonyOS AVCodec hardware-decode evidence.

The preflight is intentionally conservative. It can document that the current
environment is blocked, but a pass requires a real HarmonyOS NEXT MatePad Mini,
DevEco/HDC/Hvigor/OHPM provenance, a signed HAP, and per-codec AVCodecKit
observations for H.264 and HEVC. Android, simulator, portable, or source-only
records are rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import SCHEMA_VERSION
from .manifest import ManifestError, repository_state


KIND = "harmony_avcodec_hardware_decode_preflight"
HARMONY_PLATFORMS = {"HarmonyOS", "HarmonyOS NEXT"}
REQUIRED_CODECS = ("h264", "hevc")
REQUIRED_TOOLCHAIN_KEYS = (
    "deveco_studio_version",
    "harmony_sdk_api",
    "harmony_sdk_version",
    "hvigor_version",
    "ohpm_version",
    "hdc_version",
)
REQUIRED_ARTIFACT_KEYS = (
    "bundle_name",
    "version_name",
    "hap_sha256",
    "signature_certificate_sha256",
)
REQUIRED_DEVICE_KEYS = (
    "platform",
    "manufacturer",
    "model",
    "product",
    "os_build",
    "hdc_target",
    "serial_hash",
)
REQUIRED_HOST_KEYS = ("commit", "build_sha256", "protocol")
REQUIRED_CODEC_GATE_KEYS = (
    "decoder_capability",
    "hardware_decoder",
    "xcomponent_surface",
    "buffer_callback",
    "protocol_media_header",
    "pts_preserved",
    "input_buffer_pushed",
    "output_rendered",
    "output_buffer_freed",
    "flush_completed",
    "reconfigure_completed",
    "eos_completed",
    "release_completed",
)
CODEC_RUN_BLOCKER = "no HarmonyOS AVCodecKit hardware run artifacts were provided"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ToolProbe:
    name: str
    path: str | None
    version: str | None
    error: str | None = None


def _run(
    command: Sequence[str],
    *,
    timeout_seconds: float = 15.0,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=cwd,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(list(command), 127, "", str(error))


def _tool_probe(name: str, version_args: Sequence[str]) -> ToolProbe:
    path = shutil.which(name)
    if path is None:
        return ToolProbe(name=name, path=None, version=None, error="not found")
    result = _run([path, *version_args])
    version = (result.stdout.strip() or result.stderr.strip()).splitlines()[:3]
    if result.returncode != 0:
        return ToolProbe(name=name, path=path, version=None, error="; ".join(version) or f"exit {result.returncode}")
    return ToolProbe(name=name, path=path, version="; ".join(version) if version else "available")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _non_empty(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{path}: expected non-empty string")
    return value.strip()


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{path}: expected object")
    return value


def _require_keys(document: dict[str, Any], keys: Iterable[str], path: str) -> None:
    for key in keys:
        if key not in document:
            raise ManifestError(f"{path}.{key}: missing")
        _non_empty(document[key], f"{path}.{key}")


def _hex(value: Any, path: str, pattern: re.Pattern[str], *, allow_placeholder: bool = False) -> str:
    text = _non_empty(value, path).lower()
    if pattern.fullmatch(text) is None:
        raise ManifestError(f"{path}: expected {pattern.pattern}")
    if not allow_placeholder and set(text) == {"0"}:
        raise ManifestError(f"{path}: placeholder zero value is not evidence")
    return text


def _require_status_pass(value: Any, path: str, *, allow_blocked: bool, warnings: list[str]) -> None:
    if value == "pass":
        return
    if allow_blocked and value == "blocked":
        warnings.append(f"{path}: blocked")
        return
    if value == "fail":
        raise ManifestError(f"{path}: fail")
    raise ManifestError(f"{path}: expected pass" + (" or blocked" if allow_blocked else ""))


def _validate_codec(codec: dict[str, Any], expected_codec: str, *, allow_blocked: bool, warnings: list[str]) -> None:
    if codec.get("codec") != expected_codec:
        raise ManifestError(f"codecs.{expected_codec}.codec: expected {expected_codec}")
    _require_status_pass(codec.get("status"), f"codecs.{expected_codec}.status", allow_blocked=allow_blocked, warnings=warnings)

    decoder_name = _non_empty(codec.get("decoder_name"), f"codecs.{expected_codec}.decoder_name")
    if not allow_blocked and any(token in decoder_name.lower() for token in ("software", "sw", "simulator", "emulator")):
        raise ManifestError(f"codecs.{expected_codec}.decoder_name: expected hardware decoder identity")

    gates = _mapping(codec.get("gates"), f"codecs.{expected_codec}.gates")
    for gate in REQUIRED_CODEC_GATE_KEYS:
        _require_status_pass(gates.get(gate), f"codecs.{expected_codec}.gates.{gate}", allow_blocked=allow_blocked, warnings=warnings)

    media = _mapping(codec.get("media_header"), f"codecs.{expected_codec}.media_header")
    for key in ("stream_id", "session_epoch", "config_epoch", "first_frame_id", "payload_length"):
        if not isinstance(media.get(key), int) or media[key] <= 0:
            raise ManifestError(f"codecs.{expected_codec}.media_header.{key}: expected positive integer")
    if media.get("codec") != expected_codec:
        raise ManifestError(f"codecs.{expected_codec}.media_header.codec: expected {expected_codec}")
    if media.get("fragment_count") != 1 or media.get("fragment_index") != 0:
        raise ManifestError(f"codecs.{expected_codec}.media_header: expected unfragmented first-frame evidence")

    artifacts = codec.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or not all(isinstance(item, str) and item.strip() for item in artifacts):
        raise ManifestError(f"codecs.{expected_codec}.artifacts: expected non-empty string array")


def validate_manifest(document: dict[str, Any], *, allow_blocked: bool = False) -> list[str]:
    warnings: list[str] = []
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"schema_version: expected {SCHEMA_VERSION}")
    if document.get("kind") != KIND:
        raise ManifestError(f"kind: expected {KIND}")
    _non_empty(document.get("run_id"), "run_id")
    try:
        uuid.UUID(str(document["run_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ManifestError("run_id: expected UUID") from error
    created_at = _non_empty(document.get("created_at"), "created_at")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ManifestError("created_at: expected ISO date-time") from error

    repository = _mapping(document.get("repository"), "repository")
    for key in ("revision", "tree", "dirty", "status_porcelain"):
        if key not in repository:
            raise ManifestError(f"repository.{key}: missing")
    _hex(repository["revision"], "repository.revision", HEX_40, allow_placeholder=allow_blocked)
    _hex(repository["tree"], "repository.tree", HEX_40, allow_placeholder=allow_blocked)
    if not isinstance(repository["dirty"], bool):
        raise ManifestError("repository.dirty: expected boolean")
    if repository["dirty"] is not False and not allow_blocked:
        raise ManifestError("repository.dirty: expected false for acceptance evidence")
    if not isinstance(repository["status_porcelain"], list) or not all(isinstance(item, str) for item in repository["status_porcelain"]):
        raise ManifestError("repository.status_porcelain: expected string array")

    toolchain = _mapping(document.get("toolchain"), "toolchain")
    _require_keys(toolchain, REQUIRED_TOOLCHAIN_KEYS, "toolchain")
    if not re.search(r"(?:^|\D)(?:12|1[3-9]|[2-9][0-9])(?:\D|$)", str(toolchain["harmony_sdk_api"])):
        raise ManifestError("toolchain.harmony_sdk_api: expected API 12 or newer")

    artifact = _mapping(document.get("artifact"), "artifact")
    _require_keys(artifact, REQUIRED_ARTIFACT_KEYS, "artifact")
    if artifact["bundle_name"] != "dev.vibescreen.harmony":
        raise ManifestError("artifact.bundle_name: expected dev.vibescreen.harmony")
    _hex(artifact["hap_sha256"], "artifact.hap_sha256", HEX_64, allow_placeholder=allow_blocked)
    _hex(artifact["signature_certificate_sha256"], "artifact.signature_certificate_sha256", HEX_64, allow_placeholder=allow_blocked)

    device = _mapping(document.get("device"), "device")
    _require_keys(device, REQUIRED_DEVICE_KEYS, "device")
    if device["platform"] not in HARMONY_PLATFORMS:
        raise ManifestError("device.platform: Android or simulator evidence cannot close HarmonyOS AVCodec gates")
    identity_text = " ".join(str(device.get(key, "")) for key in ("manufacturer", "model", "product"))
    if "matepad" not in identity_text.lower() or "mini" not in identity_text.lower():
        raise ManifestError("device: expected the primary MatePad Mini target identity")
    if any(token in identity_text.lower() for token in ("emulator", "simulator", "android", "p0110", "pacific")):
        raise ManifestError("device: Android or simulator identity cannot close HarmonyOS AVCodec gates")
    _hex(device["serial_hash"], "device.serial_hash", HEX_64, allow_placeholder=allow_blocked)

    host = _mapping(document.get("host"), "host")
    _require_keys(host, REQUIRED_HOST_KEYS, "host")
    _hex(host["commit"], "host.commit", HEX_40, allow_placeholder=allow_blocked)
    _hex(host["build_sha256"], "host.build_sha256", HEX_64, allow_placeholder=allow_blocked)
    if host["protocol"] != "Protocol v1":
        raise ManifestError("host.protocol: expected Protocol v1")

    codecs_value = document.get("codecs")
    if not isinstance(codecs_value, list):
        raise ManifestError("codecs: expected array")
    by_codec: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(codecs_value):
        codec = _mapping(item, f"codecs[{index}]")
        codec_name = _non_empty(codec.get("codec"), f"codecs[{index}].codec")
        if codec_name in by_codec:
            raise ManifestError(f"codecs[{index}].codec: duplicate {codec_name}")
        by_codec[codec_name] = codec
    for codec in REQUIRED_CODECS:
        if codec not in by_codec:
            raise ManifestError(f"codecs.{codec}: missing")
        _validate_codec(by_codec[codec], codec, allow_blocked=allow_blocked, warnings=warnings)

    blockers = document.get("blockers", [])
    if blockers is not None and (not isinstance(blockers, list) or not all(isinstance(item, str) and item.strip() for item in blockers)):
        raise ManifestError("blockers: expected string array")
    if blockers and not allow_blocked:
        raise ManifestError("blockers: expected empty for acceptance evidence")
    notes = document.get("notes", [])
    if notes is not None and (not isinstance(notes, list) or not all(isinstance(item, str) for item in notes)):
        raise ManifestError("notes: expected string array")
    return warnings


def template_manifest() -> dict[str, Any]:
    placeholder_hash = "0" * 64
    placeholder_commit = "0" * 40
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repository": {"revision": placeholder_commit, "tree": placeholder_commit, "dirty": False, "status_porcelain": []},
        "toolchain": {
            "deveco_studio_version": "recorded from DevEco Studio",
            "harmony_sdk_api": "API 12",
            "harmony_sdk_version": "recorded SDK version",
            "hvigor_version": "recorded hvigor --version",
            "ohpm_version": "recorded ohpm --version",
            "hdc_version": "recorded hdc -v",
        },
        "artifact": {
            "bundle_name": "dev.vibescreen.harmony",
            "version_name": "0.1.0",
            "hap_sha256": placeholder_hash,
            "signature_certificate_sha256": placeholder_hash,
        },
        "device": {
            "platform": "HarmonyOS NEXT",
            "manufacturer": "Huawei",
            "model": "MatePad Mini",
            "product": "MatePad Mini",
            "os_build": "recorded Settings build",
            "hdc_target": "recorded hdc list targets -v target",
            "serial_hash": placeholder_hash,
        },
        "host": {"commit": placeholder_commit, "build_sha256": placeholder_hash, "protocol": "Protocol v1"},
        "codecs": [_blocked_codec(codec, "replace with real AVCodecKit artifact paths") for codec in REQUIRED_CODECS],
        "blockers": [],
        "notes": ["Do not commit raw serials, credentials, IP addresses, hilog screen contents, or private network data."],
    }


def _blocked_codec(codec: str, artifact: str) -> dict[str, Any]:
    return {
        "codec": codec,
        "status": "blocked",
        "decoder_name": "blocked: not collected from HarmonyOS hardware",
        "gates": {gate: "blocked" for gate in REQUIRED_CODEC_GATE_KEYS},
        "media_header": {
            "codec": codec,
            "stream_id": 1,
            "session_epoch": 1,
            "config_epoch": 1,
            "first_frame_id": 1,
            "fragment_index": 0,
            "fragment_count": 1,
            "payload_length": 1,
        },
        "artifacts": [artifact],
    }


def _repository_with_tree(repo: Path) -> dict[str, Any]:
    state = repository_state(repo)
    result = _run(["git", "rev-parse", "HEAD^{tree}"], timeout_seconds=15.0, cwd=repo)
    state["tree"] = result.stdout.strip() if result.returncode == 0 else "0" * 40
    return state


def collect_preflight(*, repo: Path, hdc_target: str | None, hap: Path | None) -> dict[str, Any]:
    probes = {
        "hvigor": _tool_probe("hvigor", ["--version"]),
        "hvigorw": _tool_probe("hvigorw", ["--version"]),
        "ohpm": _tool_probe("ohpm", ["--version"]),
        "hdc": _tool_probe("hdc", ["-v"]),
        "deveco": _tool_probe("deveco", ["--version"]),
    }
    blockers: list[str] = []
    if probes["hdc"].path is None:
        blockers.append("hdc not found; no HarmonyOS target can be enumerated")
    if probes["ohpm"].path is None:
        blockers.append("ohpm not found; DevEco-managed dependencies cannot be synchronized")
    if probes["hvigor"].path is None and probes["hvigorw"].path is None:
        blockers.append("hvigor/hvigorw not found; no DevEco HAP build can be produced")
    if probes["deveco"].path is None:
        blockers.append("DevEco CLI not found; ArkTS/API checker provenance is unavailable")
    if hdc_target is None:
        blockers.append("no explicit HarmonyOS HDC target was provided")
    if hap is None:
        blockers.append("no signed HarmonyOS release HAP was provided")
    elif not hap.is_file():
        blockers.append(f"signed HAP not found: {hap}")
    blockers.append(CODEC_RUN_BLOCKER)

    hdc_targets: str | None = None
    hdc_error: str | None = None
    if probes["hdc"].path is not None:
        result = _run([probes["hdc"].path or "hdc", "list", "targets", "-v"], timeout_seconds=15.0)
        hdc_targets = result.stdout.strip()
        if result.returncode != 0:
            hdc_error = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            blockers.append(f"hdc target enumeration failed: {hdc_error}")
        elif hdc_target is not None and hdc_target not in result.stdout:
            blockers.append("explicit HDC target was not present in hdc list targets -v output")

    placeholder_hash = "0" * 64
    placeholder_commit = "0" * 40
    repository = _repository_with_tree(repo.resolve())
    revision = repository.get("revision")
    if not isinstance(revision, str) or HEX_40.fullmatch(revision) is None:
        repository["revision"] = placeholder_commit
    if "tree" not in repository or HEX_40.fullmatch(str(repository["tree"])) is None:
        repository["tree"] = placeholder_commit

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repository": repository,
        "toolchain": {
            "deveco_studio_version": probes["deveco"].version or "blocked: DevEco CLI not found",
            "harmony_sdk_api": "API 12 required; blocked until DevEco SDK is available",
            "harmony_sdk_version": "blocked: DevEco SDK not inspected",
            "hvigor_version": probes["hvigor"].version or probes["hvigorw"].version or "blocked: hvigor/hvigorw not found",
            "ohpm_version": probes["ohpm"].version or "blocked: ohpm not found",
            "hdc_version": probes["hdc"].version or "blocked: hdc not found",
        },
        "artifact": {
            "bundle_name": "dev.vibescreen.harmony",
            "version_name": "0.1.0",
            "hap_sha256": _sha256(hap) if hap is not None and hap.is_file() else placeholder_hash,
            "signature_certificate_sha256": placeholder_hash,
        },
        "device": {
            "platform": "HarmonyOS NEXT",
            "manufacturer": "blocked: not collected from HarmonyOS hardware",
            "model": "MatePad Mini",
            "product": "MatePad Mini",
            "os_build": "blocked: not collected from HarmonyOS hardware",
            "hdc_target": hdc_target or "blocked: no target",
            "serial_hash": placeholder_hash,
        },
        "host": {"commit": placeholder_commit, "build_sha256": placeholder_hash, "protocol": "Protocol v1"},
        "codecs": [_blocked_codec(codec, "blocked preflight: no HarmonyOS AVCodecKit hardware run") for codec in REQUIRED_CODECS],
        "blockers": blockers,
        "tool_probe": {name: probe.__dict__ for name, probe in probes.items()},
        "hdc_targets": hdc_targets,
        "hdc_error": hdc_error,
        "notes": [
            "This blocked preflight is not HarmonyOS hardware decode acceptance evidence.",
            "Android, emulator, simulator, and portable source results cannot close the H.264/HEVC AVCodecKit gate.",
        ],
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ManifestError("manifest: expected object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write a local blocked/ready preflight manifest.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--hdc-target", help="Exact HarmonyOS target from hdc list targets -v.")
    parser.add_argument("--hap", type=Path, help="Signed release HAP to hash for provenance.")
    parser.add_argument("--template", action="store_true", help="Print a redaction-safe acceptance manifest template and exit.")
    parser.add_argument("--validate", type=Path, help="Validate an existing AVCodec evidence manifest.")
    parser.add_argument("--allow-blocked", action="store_true", help="Allow blocked status for readiness records; never closes the gate.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.template:
            print(json.dumps(template_manifest(), indent=2, sort_keys=True))
            return 0
        if arguments.validate is not None:
            warnings = validate_manifest(_load_manifest(arguments.validate), allow_blocked=arguments.allow_blocked)
            if arguments.allow_blocked:
                print("HarmonyOS AVCodec manifest is structurally valid but not acceptance evidence:")
                for warning in warnings or ["allow-blocked mode does not close AVCodec hardware gates"]:
                    print(f"- {warning}")
            else:
                print("HarmonyOS AVCodec manifest passes H.264/HEVC hardware decode gates.")
            return 0
        if arguments.output is None:
            raise ManifestError("--output is required unless --template or --validate is used")
        document = collect_preflight(repo=arguments.repo, hdc_target=arguments.hdc_target, hap=arguments.hap)
        _write_json(arguments.output, document)
        warnings = validate_manifest(document, allow_blocked=True)
        result = "blocked" if document["blockers"] or warnings else "ready"
        print(f"HarmonyOS AVCodec preflight wrote {arguments.output} with result {result}")
        return 2 if result == "blocked" else 0
    except (json.JSONDecodeError, ManifestError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
