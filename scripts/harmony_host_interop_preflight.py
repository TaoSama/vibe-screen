#!/usr/bin/env python3
"""Collect or validate HarmonyOS -> Host resume interop readiness evidence.

This tool is intentionally fail-closed. A normal validation pass requires a
redacted manifest from a real HarmonyOS NEXT MatePad Mini run that exercised the
resume-capable Protocol v1 Host flow. A local preflight without DevEco/HDC/HAP
or a HarmonyOS device writes a blocked evidence bundle and must not be used as
acceptance evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA = "dev.vibescreen.harmony-host-interop/v1"
BLOCKED_EXIT = 2
HARMONY_PLATFORMS = {"HarmonyOS", "HarmonyOS NEXT"}
REQUIRED_TOOLCHAIN_KEYS = ("deveco_studio_version", "harmony_sdk_api", "hvigor_version", "ohpm_version", "hdc_version")
REQUIRED_REPOSITORY_KEYS = ("commit", "tree", "status")
REQUIRED_HOST_KEYS = ("commit", "build_sha256", "protocol", "resume_registry")
REQUIRED_ARTIFACT_KEYS = ("hap_sha256", "signature_certificate_sha256")
REQUIRED_DEVICE_KEYS = ("platform", "manufacturer", "model", "product", "os_build", "hdc_target", "serial_hash")
REQUIRED_FLOW_IDS = (
    "host_hello_session_display_video",
    "control_channel_after_resume",
    "media_channel_after_resume",
    "background_foreground_resume",
    "wifi_loss_restore_resume",
    "bounded_reconnect",
    "host_restart_fresh_session",
    "resume_result_success_reported",
    "resume_result_failure_reported",
    "old_epoch_control_rejected",
    "old_epoch_media_rejected",
)
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


class InteropManifestError(ValueError):
    pass


@dataclass(frozen=True)
class CommandProbe:
    name: str
    path: str | None
    version: str


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InteropManifestError(f"{path}: expected object")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InteropManifestError(f"{path}: expected non-empty string")
    return value


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise InteropManifestError(f"{path}: expected boolean")
    return value


def _number(value: Any, path: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise InteropManifestError(f"{path}: expected number")
    return value


def _hex(value: Any, path: str, pattern: re.Pattern[str], *, allow_placeholder: bool = False) -> str:
    text = _string(value, path).lower()
    if pattern.fullmatch(text) is None:
        raise InteropManifestError(f"{path}: expected {pattern.pattern}")
    if not allow_placeholder and set(text) == {"0"}:
        raise InteropManifestError(f"{path}: placeholder zero value is not evidence")
    return text


def _require_keys(document: dict[str, Any], keys: Iterable[str], path: str) -> None:
    for key in keys:
        if key not in document:
            raise InteropManifestError(f"{path}.{key}: missing")
        _string(document[key], f"{path}.{key}")


def _string_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise InteropManifestError(f"{path}: expected non-empty string array")
    return value


def _validate_evidence_reference(reference: str, root: Path, path: str) -> None:
    if URL_RE.match(reference):
        raise InteropManifestError(f"{path}: expected repository-local evidence path, got URL")
    reference_path = Path(reference)
    if reference_path.is_absolute():
        raise InteropManifestError(f"{path}: expected path relative to evidence root")
    if any(part == ".." for part in reference_path.parts):
        raise InteropManifestError(f"{path}: must not escape evidence root")
    resolved_root = root.resolve()
    resolved_path = (resolved_root / reference_path).resolve()
    if resolved_path == resolved_root:
        raise InteropManifestError(f"{path}: expected an evidence artifact below evidence root")
    if resolved_root not in resolved_path.parents:
        raise InteropManifestError(f"{path}: must stay within evidence root")
    if not resolved_path.exists():
        raise InteropManifestError(f"{path}: missing evidence artifact {reference}")
    if not resolved_path.is_file():
        raise InteropManifestError(f"{path}: expected evidence artifact file {reference}")


def validate_manifest(
    document: dict[str, Any],
    *,
    allow_blocked: bool = False,
    evidence_root: Path | None = None,
) -> list[str]:
    warnings: list[str] = []
    if document.get("schema") != SCHEMA:
        raise InteropManifestError(f"schema: expected {SCHEMA}")

    repository = _mapping(document.get("repository"), "repository")
    _require_keys(repository, REQUIRED_REPOSITORY_KEYS, "repository")
    _hex(repository["commit"], "repository.commit", HEX_40, allow_placeholder=allow_blocked)
    _hex(repository["tree"], "repository.tree", HEX_40, allow_placeholder=allow_blocked)
    if repository["status"] != "clean":
        raise InteropManifestError("repository.status: expected clean")

    toolchain = _mapping(document.get("toolchain"), "toolchain")
    _require_keys(toolchain, REQUIRED_TOOLCHAIN_KEYS, "toolchain")
    if re.search(r"(?:^|\D)(?:12|1[3-9]|[2-9][0-9])(?:\D|$)", toolchain["harmony_sdk_api"]) is None:
        raise InteropManifestError("toolchain.harmony_sdk_api: expected API 12 or newer")

    artifact = _mapping(document.get("artifact"), "artifact")
    _require_keys(artifact, ("bundle_name", "version_name"), "artifact")
    if artifact["bundle_name"] != "dev.vibescreen.harmony":
        raise InteropManifestError("artifact.bundle_name: expected dev.vibescreen.harmony")
    for key in REQUIRED_ARTIFACT_KEYS:
        _hex(artifact.get(key), f"artifact.{key}", HEX_64, allow_placeholder=allow_blocked)

    device = _mapping(document.get("device"), "device")
    _require_keys(device, REQUIRED_DEVICE_KEYS, "device")
    if device["platform"] not in HARMONY_PLATFORMS:
        raise InteropManifestError("device.platform: Android evidence cannot close HarmonyOS Host interop gates")
    identity_text = " ".join(str(device.get(key, "")) for key in ("manufacturer", "model", "product"))
    if "matepad" not in identity_text.lower() or "mini" not in identity_text.lower():
        raise InteropManifestError("device: expected the primary MatePad Mini target identity")
    _hex(device["serial_hash"], "device.serial_hash", HEX_64, allow_placeholder=allow_blocked)

    host = _mapping(document.get("host"), "host")
    _require_keys(host, REQUIRED_HOST_KEYS, "host")
    _hex(host["commit"], "host.commit", HEX_40, allow_placeholder=allow_blocked)
    _hex(host["build_sha256"], "host.build_sha256", HEX_64, allow_placeholder=allow_blocked)
    if host["protocol"] != "Protocol v1":
        raise InteropManifestError("host.protocol: expected Protocol v1")
    if host["resume_registry"] != "resume-capable":
        raise InteropManifestError("host.resume_registry: expected resume-capable")

    transport = _mapping(document.get("transport"), "transport")
    mode = _string(transport.get("mode"), "transport.mode")
    if mode not in {"trusted_lan", "usb_reverse"}:
        raise InteropManifestError("transport.mode: expected trusted_lan or usb_reverse")
    _bool(transport.get("encrypted_records"), "transport.encrypted_records")
    if mode == "trusted_lan" and not transport["encrypted_records"]:
        raise InteropManifestError("transport.encrypted_records: trusted_lan evidence must use authenticated records")

    reconnect = _mapping(document.get("reconnect"), "reconnect")
    attempts = _number(reconnect.get("maximum_attempts"), "reconnect.maximum_attempts")
    delay_ms = _number(reconnect.get("maximum_delay_ms"), "reconnect.maximum_delay_ms")
    recovered_ms = _number(reconnect.get("maximum_observed_recovery_ms"), "reconnect.maximum_observed_recovery_ms")
    if attempts < 1 or delay_ms <= 0 or recovered_ms <= 0:
        raise InteropManifestError("reconnect: expected positive bounded values")
    if recovered_ms > 3000:
        raise InteropManifestError("reconnect.maximum_observed_recovery_ms: expected <= 3000")

    flows = document.get("flows")
    if not isinstance(flows, list):
        raise InteropManifestError("flows: expected array")
    by_id: dict[str, dict[str, Any]] = {}
    for index, flow_value in enumerate(flows):
        flow = _mapping(flow_value, f"flows[{index}]")
        flow_id = _string(flow.get("id"), f"flows[{index}].id")
        if flow_id in by_id:
            raise InteropManifestError(f"flows[{index}].id: duplicate {flow_id}")
        by_id[flow_id] = flow
        status = flow.get("status")
        if status not in {"pass", "blocked", "fail"}:
            raise InteropManifestError(f"flows[{index}].status: expected pass, blocked, or fail")
        evidence = _string_list(flow.get("evidence"), f"flows[{index}].evidence")
        if flow_id in REQUIRED_FLOW_IDS and status != "pass":
            message = f"{flow_id}: {status}"
            if allow_blocked and status == "blocked":
                warnings.append(message)
            else:
                raise InteropManifestError(message)
        if evidence_root is not None and not allow_blocked and status == "pass":
            for evidence_index, reference in enumerate(evidence):
                _validate_evidence_reference(
                    reference,
                    evidence_root,
                    f"flows[{index}].evidence[{evidence_index}]",
                )

    missing = [flow_id for flow_id in REQUIRED_FLOW_IDS if flow_id not in by_id]
    if missing:
        raise InteropManifestError("missing required flows: " + ", ".join(missing))

    notes = document.get("notes", [])
    if notes is not None and (not isinstance(notes, list) or not all(isinstance(item, str) for item in notes)):
        raise InteropManifestError("notes: expected string array")
    return warnings


def template_manifest() -> dict[str, Any]:
    placeholder_hash = "0" * 64
    placeholder_commit = "0" * 40
    return {
        "schema": SCHEMA,
        "repository": {"commit": placeholder_commit, "tree": placeholder_commit, "status": "clean"},
        "toolchain": {
            "deveco_studio_version": "recorded from DevEco Studio",
            "harmony_sdk_api": "API 12",
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
        "host": {
            "commit": placeholder_commit,
            "build_sha256": placeholder_hash,
            "protocol": "Protocol v1",
            "resume_registry": "resume-capable",
        },
        "transport": {"mode": "trusted_lan", "encrypted_records": True},
        "reconnect": {"maximum_attempts": 8, "maximum_delay_ms": 8000, "maximum_observed_recovery_ms": 3000},
        "flows": [
            {"id": flow_id, "status": "blocked", "evidence": ["replace with redacted log, trace, or artifact reference"]}
            for flow_id in REQUIRED_FLOW_IDS
        ],
        "notes": ["Do not commit raw serials, credentials, IP addresses, or screen content."],
    }


def run_command(command: Sequence[str], *, timeout: float = 10.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(list(command), check=False, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    return completed.returncode, output[:2000]


def probe_command(name: str, version_args: Sequence[str]) -> CommandProbe:
    path = shutil.which(name)
    if path is None:
        return CommandProbe(name, None, "not found")
    code, output = run_command([path, *version_args])
    first_line = output.splitlines()[0] if output else f"exit {code}"
    return CommandProbe(name, path, first_line)


def local_preflight(run_id: str) -> dict[str, Any]:
    probes = [
        probe_command("hvigor", ["--version"]),
        probe_command("hvigorw", ["--version"]),
        probe_command("ohpm", ["--version"]),
        probe_command("hdc", ["-v"]),
    ]
    by_name = {probe.name: probe for probe in probes}
    missing = []
    if by_name["hvigor"].path is None and by_name["hvigorw"].path is None:
        missing.append("hvigor or hvigorw")
    missing.extend(name for name in ("ohpm", "hdc") if by_name[name].path is None)
    blocking = [
        {"field": "signed_hap", "reason": "a DevEco-built signed HAP and signature hash must be recorded"},
        {"field": "harmony_device", "reason": "hdc and a HarmonyOS NEXT MatePad Mini are required for Host interop evidence"},
        {"field": "host_resume_registry", "reason": "a resume-capable Mac Host run must be recorded before this gate can pass"},
    ]
    if missing:
        blocking.append({"field": "missing_commands", "reason": ", ".join(missing)})
    return {
        "schema": SCHEMA + "/preflight",
        "run_id": run_id,
        "created_at": utc_timestamp(),
        "verdict": "blocked",
        "can_close_harmony_host_interop_gate": False,
        "command_probes": [redacted_command_probe(probe) for probe in probes],
        "required_flows": list(REQUIRED_FLOW_IDS),
        "blocking_reasons": blocking,
    }


def redacted_command_probe(probe: CommandProbe) -> dict[str, str | None]:
    path = Path(probe.path).name if probe.path is not None else None
    return {"name": probe.name, "path": path, "version": probe.version}


def write_preflight_bundle(evidence_dir: Path, run_id: str) -> int:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    summary = local_preflight(run_id)
    (evidence_dir / "harmony-host-interop-preflight.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (evidence_dir / "harmony-host-interop-manifest-template.json").write_text(
        json.dumps(template_manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (evidence_dir / "README.md").write_text(render_readme(summary), encoding="utf-8")
    return BLOCKED_EXIT


def render_readme(summary: dict[str, Any]) -> str:
    missing = ", ".join(reason["field"] for reason in summary["blocking_reasons"])
    return (
        "# HarmonyOS Host resume interop preflight - BLOCKED\n\n"
        f"Run ID: {summary['run_id']}\n"
        f"Created: {summary['created_at']}\n\n"
        "## Verdict\n\n"
        "BLOCKED. This package is readiness evidence only and not acceptance evidence. It does not prove a HarmonyOS NEXT HAP, "
        "MatePad Mini behavior, or resume-capable Host interoperability.\n\n"
        "## Blocking fields\n\n"
        f"{missing}\n\n"
        "## Required successful run\n\n"
        "A future passing manifest must come from a signed dev.vibescreen.harmony HAP on the "
        "primary HarmonyOS NEXT MatePad Mini target, connected to a resume-capable Protocol v1 Mac Host. "
        "It must include HostHello/session/display/video/control/media flow evidence, successful and "
        "rejected ResumeSessionResult observations, background/foreground recovery, Wi-Fi loss/restore, "
        "host restart fresh-session behavior, bounded reconnect timing, and rejection of old-epoch "
        "control and media. Android evidence is not a substitute.\n"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate or collect HarmonyOS Host resume interop evidence.")
    parser.add_argument("manifest", nargs="?", type=Path, help="Path to a completed interop manifest JSON.")
    parser.add_argument("--allow-blocked", action="store_true", help="Validate blocked readiness manifests without closing the gate.")
    parser.add_argument("--template", action="store_true", help="Print a redaction-safe interop manifest template.")
    parser.add_argument("--evidence-dir", type=Path, help="Write a local blocked preflight evidence bundle.")
    parser.add_argument("--evidence-root", type=Path, help="Directory that contains referenced acceptance artifacts.")
    parser.add_argument("--run-id", default="harmony-host-interop-preflight", help="Run identifier for --evidence-dir output.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        print(json.dumps(template_manifest(), indent=2, sort_keys=True))
        return 0
    if args.evidence_dir is not None:
        return write_preflight_bundle(args.evidence_dir, args.run_id)
    if args.manifest is None:
        raise SystemExit("manifest is required unless --template or --evidence-dir is used")
    document = json.loads(args.manifest.read_text(encoding="utf-8"))
    evidence_root = args.evidence_root if args.evidence_root is not None else args.manifest.parent
    warnings = validate_manifest(_mapping(document, "manifest"), allow_blocked=args.allow_blocked, evidence_root=evidence_root)
    if args.allow_blocked:
        print("HarmonyOS Host interop manifest is structurally valid but not acceptance evidence:")
        for warning in warnings or ["allow-blocked mode does not close the Host interop gate"]:
            print(f"- {warning}")
    else:
        print("HarmonyOS Host interop manifest passes all required resume-capable Host gates.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, InteropManifestError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
