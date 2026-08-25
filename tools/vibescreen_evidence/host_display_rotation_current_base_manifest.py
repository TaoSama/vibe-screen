"""Create a current-base readiness manifest for host display rotation.

The manifest is intentionally conservative. It records the owner and local
preflight state for the Phase 1 rotated host-display gate, but generated output
starts with the physical and virtual host-rotation acceptance gates blocked
until a real-device evidence package proves every required host rotation.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .manifest import ManifestError, repository_state

KIND = "host_display_rotation_current_base_manifest"
AGGREGATE_OWNER = "current-base-host-display-rotation"
AGGREGATE_OWNER_PR = "#262"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"

SCOPE_PRS = ["#162", "#243", "#262", "#272"]
SOURCE_DOCS = [
    "README.md",
    "docs/testing.md",
    "docs/runbook/host-display-rotation-acceptance.md",
    "docs/changes/2026-08-05-phase-1-android-client/TEST.md",
]

REQUIRED_HOST_ROTATIONS = [90, 180, 270]
DEVICE_FIELDS = [
    "manufacturer",
    "model",
    "codename",
    "android_release",
    "sdk",
    "adb_serial",
]
HOST_PREFLIGHT_CHECKS = {
    "signing_identity": "stable non-ad-hoc Host signing identity is available",
    "bundle_identifier": "installed Host bundle identifier matches dev.telemachus.display",
    "screen_recording_tcc": "Screen Recording grant is recorded for the signed Host bundle",
    "accessibility_tcc": "Accessibility grant is recorded for the signed Host bundle",
    "signing_tcc_match": "the signed bundle identity matches the TCC rows being used",
    "rotation_restoration_plan": "operator retained a restoration plan for original macOS display rotation",
}
FORMAL_GATES = {
    "physical_host_display_rotation": "physical Mac display rotated through 90/180/270 with retained real-device visual and inverse-touch evidence",
    "virtual_host_display_rotation": "virtual Mac display rotated through 90/180/270 with retained real-device visual and inverse-touch evidence",
}
SUPPORTING_GATES = {
    "client_local_fit_fill_rotation_matrix": "client-local Fit/Fill and Follow Mac/90/180/270 matrix stays separate from host display rotation",
}
CLIENT_LOCAL_EVIDENCE = (
    "docs/changes/2026-08-05-phase-1-android-client/evidence/"
    "2026-08-10-xiaomi13-viewport-input/"
)
DEFAULT_LIMITATIONS = [
    "This manifest does not claim rotated host-display acceptance by itself.",
    "Client-local Fit/Fill/rotation evidence with hostRotation=0 cannot close real host display rotation.",
    "Physical and virtual Mac displays must each have retained 90/180/270 real-device runs before this aggregate can pass.",
]

TARGET_BUNDLE_ID = "dev.telemachus.display"
TARGET_SIGNING_IDENTITY = "Vibe Screen Dev"
REDACTED_ADB_SERIAL = "<redacted-adb-serial>"
REDACTED_SOURCE_ROOT = "<repository-root>"
PATH_PATTERN = re.compile(
    r"(?:/" + "Users" + r"/[^\s<>\"']+|/home/[^\s<>\"']+|/Volumes/[^\s<>\"']+|[A-Za-z]:\\" + "Users" + r"\\[^\s<>\"']+)",
    re.IGNORECASE,
)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_probe(command: Sequence[str], cwd: Path | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": list(command), "status": "blocked", "detail": str(error)}
    output = (result.stdout.strip() or result.stderr.strip()).splitlines()
    return {
        "command": list(command),
        "status": "pass" if result.returncode == 0 else "blocked",
        "exit_code": result.returncode,
        "summary": output[:20],
    }


def _redact_string(value: str, adb_serial: str | None = None) -> str:
    redacted = value
    if adb_serial and adb_serial != REDACTED_ADB_SERIAL:
        redacted = redacted.replace(adb_serial, REDACTED_ADB_SERIAL)
    redacted = PATH_PATTERN.sub("[redacted-path]", redacted)
    return re.sub(
        r"unable to open database \"[^\"]+\"",
        "unable to open redacted database",
        redacted,
        flags=re.IGNORECASE,
    )


def _sanitize_public_manifest(value: Any, adb_serial: str | None = None) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_public_manifest(item, adb_serial) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_public_manifest(item, adb_serial) for item in value]
    if isinstance(value, str):
        return _redact_string(value, adb_serial)
    return value


def _normalize_pr(value: str) -> str:
    candidate = value.strip()
    digits = candidate[1:] if candidate.startswith("#") else candidate
    if not digits.isdigit():
        raise ManifestError("--aggregate-owner-pr must be a PR number such as #262")
    owner_pr = f"#{int(digits)}"
    if owner_pr != AGGREGATE_OWNER_PR:
        raise ManifestError(
            f"host display rotation current-base owner PR must remain {AGGREGATE_OWNER_PR}"
        )
    return owner_pr


def _ensure_source_docs(repo: Path, source_docs: Sequence[str]) -> list[str]:
    missing = [path for path in source_docs if not (repo / path).is_file()]
    if missing:
        raise ManifestError("missing source document(s): " + ", ".join(missing))
    return list(source_docs)


def _signing_probe() -> dict[str, Any]:
    result = _run_probe(["security", "find-identity", "-v", "-p", "codesigning"])
    summaries = result.get("summary", [])
    valid_identity_count = 0
    target_identity_available = False
    if isinstance(summaries, list):
        for line in summaries:
            if not isinstance(line, str):
                continue
            words = line.split()
            if line.lstrip()[:1].isdigit() and any(
                len(word) == 40 and all(character in "0123456789abcdefABCDEF" for character in word)
                for word in words
            ):
                valid_identity_count += 1
            if TARGET_SIGNING_IDENTITY in line:
                target_identity_available = True
    result["valid_identity_count"] = valid_identity_count
    result["target_identity"] = TARGET_SIGNING_IDENTITY
    result["target_identity_available"] = target_identity_available
    result["status"] = "pass" if target_identity_available else "blocked"
    return result


def _host_preflight_probe(repo: Path) -> dict[str, Any]:
    return _run_probe(
        [
            sys.executable,
            "scripts/macos_dev_host.py",
            "preflight",
            "--install-path",
            "/Applications/Vibe Screen.app",
        ],
        cwd=repo,
    )


def _installed_host_codesign_probe() -> dict[str, Any]:
    return _run_probe(["codesign", "-dv", "--verbose=4", "/Applications/Vibe Screen.app"])


def collect_environment(repo: Path) -> dict[str, Any]:
    return {
        "codesigning_identities": _signing_probe(),
        "installed_host_codesign": _installed_host_codesign_probe(),
        "tcc_dev_telemachus_display": {
            "command": ["host-readiness/preflight", "signed-host-tcc-check"],
            "status": "blocked",
            "summary": [
                "TCC grant evidence is not collected by this public current-base manifest",
            ],
        },
        "host_preflight": _host_preflight_probe(repo),
        "host_displays": _run_probe(["system_profiler", "SPDisplaysDataType"]),
    }


def _adb_getprop(serial: str, prop: str) -> dict[str, Any]:
    return _run_probe(["adb", "-s", serial, "shell", "getprop", prop])


def collect_device(serial: str | None) -> dict[str, Any]:
    if not serial:
        return {
            "status": "blocked",
            "runtime_class": "missing",
            "manufacturer": None,
            "model": None,
            "codename": None,
            "android_release": None,
            "sdk": None,
            "adb_serial": None,
            "package_status": "not_checked",
            "evidence": [],
            "probes": {},
        }

    probes = {
        "adb_get_state": _run_probe(["adb", "-s", serial, "get-state"]),
        "manufacturer": _adb_getprop(serial, "ro.product.manufacturer"),
        "model": _adb_getprop(serial, "ro.product.model"),
        "codename": _adb_getprop(serial, "ro.product.device"),
        "android_release": _adb_getprop(serial, "ro.build.version.release"),
        "sdk": _adb_getprop(serial, "ro.build.version.sdk"),
        "fingerprint": _adb_getprop(serial, "ro.build.fingerprint"),
        "package_path": _run_probe(["adb", "-s", serial, "shell", "pm", "path", TARGET_BUNDLE_ID]),
    }

    def first_summary(name: str) -> str | None:
        summary = probes[name].get("summary")
        if isinstance(summary, list) and summary and isinstance(summary[0], str):
            return summary[0].strip()
        return None

    sdk_value: int | None = None
    sdk_text = first_summary("sdk")
    if sdk_text and sdk_text.isdigit():
        sdk_value = int(sdk_text)
    state = first_summary("adb_get_state")
    package_probe = probes["package_path"]
    identity_complete = all(
        first_summary(name)
        for name in ("manufacturer", "model", "codename", "android_release")
    ) and sdk_value is not None

    return {
        "status": "pass" if state == "device" and identity_complete else "blocked",
        "runtime_class": "physical_android_device" if state == "device" else "missing",
        "manufacturer": first_summary("manufacturer"),
        "model": first_summary("model"),
        "codename": first_summary("codename"),
        "android_release": first_summary("android_release"),
        "sdk": sdk_value,
        "adb_serial": serial,
        "package_status": "installed" if package_probe.get("status") == "pass" else "not_installed",
        "evidence": ["device-identity.txt"],
        "probes": probes,
    }


def _check_record(
    *,
    status: str,
    category: str,
    requirement: str,
    blocking: bool,
    evidence: Sequence[str] | None = None,
    notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "category": category,
        "requirement": requirement,
        "blocking": blocking,
        "evidence": list(evidence or []),
        "notes": list(notes or []),
    }


def host_preflight_records(environment: dict[str, Any]) -> dict[str, dict[str, Any]]:
    signing = (
        environment.get("codesigning_identities")
        if isinstance(environment.get("codesigning_identities"), dict)
        else {}
    )
    target_identity_available = signing.get("target_identity_available") is True
    installed_codesign = (
        environment.get("installed_host_codesign")
        if isinstance(environment.get("installed_host_codesign"), dict)
        else {}
    )
    installed_summary = installed_codesign.get("summary", [])
    bundle_identifier_matches = isinstance(installed_summary, list) and any(
        line == f"Identifier={TARGET_BUNDLE_ID}" for line in installed_summary
    )
    return {
        "signing_identity": _check_record(
            status="pass" if target_identity_available else "blocked",
            category="host_preflight",
            requirement=HOST_PREFLIGHT_CHECKS["signing_identity"],
            blocking=True,
            evidence=["codesigning-identities.txt"],
            notes=[] if target_identity_available else ["Vibe Screen Dev signing identity was not visible"],
        ),
        "bundle_identifier": _check_record(
            status="pass" if bundle_identifier_matches else "blocked",
            category="host_preflight",
            requirement=HOST_PREFLIGHT_CHECKS["bundle_identifier"],
            blocking=True,
            evidence=["host-preflight.txt", "installed-host-codesign.txt"],
            notes=[] if bundle_identifier_matches else ["installed Host bundle identifier was not proven"],
        ),
        "screen_recording_tcc": _check_record(
            status="blocked",
            category="host_preflight",
            requirement=HOST_PREFLIGHT_CHECKS["screen_recording_tcc"],
            blocking=True,
            evidence=["tcc-dev-telemachus-display.txt"],
            notes=["TCC Screen Recording grant was not proven"],
        ),
        "accessibility_tcc": _check_record(
            status="blocked",
            category="host_preflight",
            requirement=HOST_PREFLIGHT_CHECKS["accessibility_tcc"],
            blocking=True,
            evidence=["tcc-dev-telemachus-display.txt"],
            notes=["TCC Accessibility grant was not proven"],
        ),
        "signing_tcc_match": _check_record(
            status="blocked",
            category="host_preflight",
            requirement=HOST_PREFLIGHT_CHECKS["signing_tcc_match"],
            blocking=True,
            evidence=["host-preflight.txt", "tcc-dev-telemachus-display.txt"],
            notes=["signed Host identity and TCC rows could not be matched"],
        ),
        "rotation_restoration_plan": _check_record(
            status="blocked",
            category="host_preflight",
            requirement=HOST_PREFLIGHT_CHECKS["rotation_restoration_plan"],
            blocking=True,
            evidence=["host-displays-before.txt"],
            notes=["no host display rotation run was started"],
        ),
    }


def default_gates() -> dict[str, dict[str, Any]]:
    gates = {
        "client_local_fit_fill_rotation_matrix": _check_record(
            status="pass",
            category="supporting_client_local",
            requirement=SUPPORTING_GATES["client_local_fit_fill_rotation_matrix"],
            blocking=False,
            evidence=[CLIENT_LOCAL_EVIDENCE],
            notes=["hostRotation=0 evidence only; not a host display rotation pass"],
        )
    }
    for name, requirement in FORMAL_GATES.items():
        gates[name] = _check_record(
            status="blocked",
            category="real_host_display_rotation",
            requirement=requirement,
            blocking=True,
            evidence=[],
            notes=["no retained physical or virtual 90/180/270 host-display run is present"],
        )
        gates[name]["required_host_rotations"] = list(REQUIRED_HOST_ROTATIONS)
        gates[name]["covered_host_rotations"] = []
    return gates


def build_manifest(
    *,
    command: Sequence[str],
    repo: Path,
    aggregate_owner_pr: str = AGGREGATE_OWNER_PR,
    adb_serial: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    owner_pr = _normalize_pr(aggregate_owner_pr)
    source_docs = _ensure_source_docs(repo, SOURCE_DOCS)
    environment = collect_environment(repo)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "run_id": str(uuid.uuid4()),
        "created_at": _utc_timestamp(),
        "command": list(command),
        "repository": repository_state(repo),
        "source_root": REDACTED_SOURCE_ROOT,
        "owner": {
            "aggregate": AGGREGATE_OWNER,
            "aggregate_pr": owner_pr,
            "repository": REPOSITORY_FULL_NAME,
        },
        "scope_prs": list(SCOPE_PRS),
        "source_docs": source_docs,
        "local_environment": environment,
        "device": collect_device(adb_serial),
        "host_preflight": host_preflight_records(environment),
        "gates": default_gates(),
        "client_local_matrix_used_for_host_rotation": False,
        "limitations": list(DEFAULT_LIMITATIONS),
        "notes": notes,
    }
    return _sanitize_public_manifest(manifest, adb_serial)


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(document, indent=2, sort_keys=True, allow_nan=False)
    temporary.write_text(payload + chr(10), encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--aggregate-owner-pr", default=AGGREGATE_OWNER_PR)
    parser.add_argument("--adb-serial", help="optional Android serial; probes use adb -s SERIAL only")
    parser.add_argument("--notes")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Exact evidence command, placed after -- (optional)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        manifest = build_manifest(
            command=command,
            repo=args.repo,
            aggregate_owner_pr=args.aggregate_owner_pr,
            adb_serial=args.adb_serial,
            notes=args.notes,
        )
        write_json(args.output, manifest)
    except (ManifestError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
