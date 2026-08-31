from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_REASON_LENGTH = 240
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:/@+ -]{1,160}$")

REQUIRED_ARTIFACT_TYPES = frozenset(
    {
        "deployed_config",
        "public_network_observation",
        "data_plane_observation",
        "coturn_disconnect_observation",
        "mixed_route_soak",
    }
)
ARTIFACT_SCHEMAS = {
    "deployed_config": "dev.vibescreen.phase3-production-deployed-config-observation/v1",
    "public_network_observation": "dev.vibescreen.phase3-production-public-network-observation/v1",
    "data_plane_observation": "dev.vibescreen.phase3-production-data-plane-observation/v1",
    "coturn_disconnect_observation": "dev.vibescreen.phase3-production-coturn-disconnect-observation/v1",
    "mixed_route_soak": "dev.vibescreen.phase3-production-mixed-route-soak-observation/v1",
}
LOCAL_ONLY_MARKERS = (
    "local_loopback_only",
    "local loopback only",
    "loopback-only",
    "synthetic_media",
    "synthetic media",
    "no_real_media",
    "no real media",
    "no_public_internet_path",
    "no public internet path",
    "synthetic_device",
    "synthetic device",
    "no_android_device",
    "no android device",
    "synthetic protocol v1 harness",
    "synthetic_protocol_v1_device",
    "synthetic peer",
    "deterministic",
    "simulation",
    "local coturn",
    "forced local coturn",
    "no_real_screen_capture",
    "no real screen capture",
)
LOCAL_ONLY_TRUE_FIELDS = frozenset(
    {
        "forced_local_coturn",
        "local_coturn",
        "local_loopback",
        "local_loopback_only",
        "no_android_device",
        "no_public_internet_path",
        "no_real_media",
        "no_real_screen_capture",
        "simulation",
        "synthetic_protocol_v1_device",
        "synthetic_device",
        "synthetic_media",
        "synthetic_peer",
        "deterministic",
    }
)
PRIVATE_DNS_SUFFIXES = (
    ".corp",
    ".home",
    ".internal",
    ".intranet",
    ".lan",
    ".local",
    ".private",
)


class EnforcementError(RuntimeError):
    """Raised for malformed manifests that cannot be evaluated safely."""


@dataclass(frozen=True)
class Reason:
    category: str
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"category": self.category, "field": self.field, "message": self.message}


def reason(category: str, field: str, message: str) -> Reason:
    if len(message) > MAX_REASON_LENGTH:
        message = message[: MAX_REASON_LENGTH - 3] + "..."
    return Reason(category=category, field=field, message=message)


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EnforcementError(f"{field} must be a JSON object")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EnforcementError(f"{field} must be a non-empty string")
    if not IDENTIFIER.fullmatch(value):
        raise EnforcementError(f"{field} contains unsupported characters")
    return value


def is_public_host(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        lowered = host.lower().rstrip(".")
        if lowered in {"localhost"} or "." not in lowered:
            return False
        return not lowered.endswith(PRIVATE_DNS_SUFFIXES)
    return bool(address.is_global)


def _source_commit(manifest: dict[str, Any]) -> str:
    source = _object(manifest["source"], "source")
    return _string(source.get("commit"), "source.commit")


def _artifact_binding_reasons(payload: dict[str, Any], artifact_type: str, manifest: dict[str, Any]) -> list[Reason]:
    reasons: list[Reason] = []
    expected_schema = ARTIFACT_SCHEMAS.get(artifact_type)
    if payload.get("schema") != expected_schema:
        reasons.append(
            reason(
                "fail",
                f"evidence.artifacts[{artifact_type}].schema",
                f"artifact schema must be {expected_schema}",
            )
        )
    if payload.get("run_id") != manifest["run_id"]:
        reasons.append(
            reason(
                "fail",
                f"evidence.artifacts[{artifact_type}].run_id",
                "artifact run_id must match the enforcement manifest",
            )
        )
    source = payload.get("source")
    if not isinstance(source, dict) or source.get("commit") != _source_commit(manifest):
        reasons.append(
            reason(
                "fail",
                f"evidence.artifacts[{artifact_type}].source.commit",
                "artifact source commit must match the enforcement manifest",
            )
        )
    return reasons


def _expect_payload_bool(
    payload: dict[str, Any], artifact_type: str, field: str, expected: bool, category: str
) -> list[Reason]:
    if payload.get(field) is expected:
        return []
    return [
        reason(
            category,
            f"evidence.artifacts[{artifact_type}].{field}",
            f"expected {expected}",
        )
    ]


def _validate_pass_artifact(artifact_type: str, payload: dict[str, Any], manifest: dict[str, Any]) -> list[Reason]:
    if artifact_type not in ARTIFACT_SCHEMAS:
        return [reason("fail", f"evidence.artifacts[{artifact_type}].type", "unsupported artifact type")]
    reasons: list[Reason] = []
    if artifact_type == "deployed_config":
        if payload.get("production_config") != manifest["production_config"]:
            reasons.append(
                reason(
                    "fail",
                    "evidence.artifacts[deployed_config].production_config",
                    "deployed config artifact must match the enforcement manifest",
                )
            )
        if payload.get("policy") != manifest["policy"]:
            reasons.append(
                reason(
                    "fail",
                    "evidence.artifacts[deployed_config].policy",
                    "deployed config artifact policy must match the enforcement manifest",
                )
            )
        return reasons

    if artifact_type == "public_network_observation":
        reasons.extend(_expect_payload_bool(payload, artifact_type, "local_loopback", False, "fail"))
        reasons.extend(_expect_payload_bool(payload, artifact_type, "synthetic_peer", False, "fail"))
        reasons.extend(_expect_payload_bool(payload, artifact_type, "public_route_observed", True, "blocked"))
        reasons.extend(_expect_payload_bool(payload, artifact_type, "remote_turn_observed", True, "blocked"))
        if payload.get("classification") != "public_internet":
            reasons.append(
                reason(
                    "fail",
                    "evidence.artifacts[public_network_observation].classification",
                    "classification must be public_internet",
                )
            )
        observed_hosts = payload.get("public_endpoint_hosts")
        manifest_hosts = _object(manifest["topology"], "topology").get("public_endpoint_hosts")
        if not isinstance(observed_hosts, list) or not observed_hosts:
            reasons.append(
                reason(
                    "blocked",
                    "evidence.artifacts[public_network_observation].public_endpoint_hosts",
                    "public endpoint observations are required",
                )
            )
        elif observed_hosts != manifest_hosts:
            reasons.append(
                reason(
                    "fail",
                    "evidence.artifacts[public_network_observation].public_endpoint_hosts",
                    "observed public endpoints must match the enforcement manifest",
                )
            )
        else:
            for index, host_value in enumerate(observed_hosts):
                host = _string(
                    host_value,
                    f"evidence.artifacts[public_network_observation].public_endpoint_hosts[{index}]",
                )
                if not is_public_host(host):
                    reasons.append(
                        reason(
                            "fail",
                            f"evidence.artifacts[public_network_observation].public_endpoint_hosts[{index}]",
                            "host is not public-routable evidence",
                        )
                    )
        return reasons

    if artifact_type == "data_plane_observation":
        for field in (
            "real_screencapturekit_capture",
            "android_mediacodec_decode",
            "application_aead_verified",
            "coturn_allocation_observed",
            "authority_admission_observed",
            "signaling_authorization_observed",
        ):
            reasons.extend(_expect_payload_bool(payload, artifact_type, field, True, "blocked"))
        reasons.extend(_expect_payload_bool(payload, artifact_type, "local_loopback", False, "fail"))
        reasons.extend(_expect_payload_bool(payload, artifact_type, "synthetic_peer", False, "fail"))
        return reasons

    if artifact_type == "coturn_disconnect_observation":
        for field in ("coturn_disconnect_observed", "active_allocation_removed", "remote_turn_observed"):
            reasons.extend(_expect_payload_bool(payload, artifact_type, field, True, "blocked"))
        reasons.extend(_expect_payload_bool(payload, artifact_type, "local_coturn", False, "fail"))
        return reasons

    if artifact_type == "mixed_route_soak":
        for field in ("real_android_device", "real_screencapturekit_capture", "android_mediacodec_decode"):
            reasons.extend(_expect_payload_bool(payload, artifact_type, field, True, "blocked"))
        reasons.extend(_expect_payload_bool(payload, artifact_type, "synthetic_peer", False, "fail"))
        for field in ("duration_minutes", "public_route_minutes", "turn_route_minutes"):
            value = payload.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                reasons.append(
                    reason(
                        "blocked",
                        f"evidence.artifacts[mixed_route_soak].{field}",
                        "positive minute count is required",
                    )
                )
        duration = payload.get("duration_minutes")
        if isinstance(duration, int) and not isinstance(duration, bool) and duration < 120:
            reasons.append(
                reason(
                    "blocked",
                    "evidence.artifacts[mixed_route_soak].duration_minutes",
                    "mixed-route production soak must be at least 120 minutes",
                )
            )
    return reasons


def scan_artifact(path: Path, artifact_type: str, manifest: dict[str, Any]) -> list[Reason]:
    reasons: list[Reason] = []
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise EnforcementError(f"cannot read evidence artifact {path}: {exc}") from exc
    lowered = content.decode("utf-8", errors="ignore").lower()
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        reasons.extend(_local_only_text_reasons(lowered, artifact_type))
        reasons.append(reason("fail", f"evidence.artifacts[{artifact_type}]", "artifact must be JSON"))
        return reasons
    if not isinstance(payload, dict):
        reasons.append(reason("fail", f"evidence.artifacts[{artifact_type}]", "artifact must be a JSON object"))
        return reasons
    reasons.extend(_local_only_text_value_reasons(payload, artifact_type))
    reasons.extend(_local_only_truthy_field_reasons(payload, artifact_type))
    reasons.extend(_artifact_binding_reasons(payload, artifact_type, manifest))
    status = payload.get("status", payload.get("result"))
    if status == "pass":
        reasons.extend(_validate_pass_artifact(artifact_type, payload, manifest))
    elif status == "blocked":
        reasons.append(reason("blocked", f"evidence.artifacts[{artifact_type}]", "artifact reports blocked"))
    elif status == "fail":
        reasons.append(reason("fail", f"evidence.artifacts[{artifact_type}]", "artifact reports fail"))
    else:
        reasons.append(
            reason(
                "blocked",
                f"evidence.artifacts[{artifact_type}]",
                "artifact does not report pass",
            )
        )
    if payload.get("schema") == "dev.vibescreen.phase3-webrtc-e2e/v1":
        reasons.append(
            reason(
                "fail",
                f"evidence.artifacts[{artifact_type}].schema",
                "local WebRTC E2E schema cannot close production enforcement",
            )
        )
    return reasons


def _local_only_text_reasons(text: str, artifact_type: str) -> list[Reason]:
    reasons: list[Reason] = []
    for marker in LOCAL_ONLY_MARKERS:
        if marker in text:
            reasons.append(
                reason(
                    "fail",
                    f"evidence.artifacts[{artifact_type}]",
                    f"artifact contains local/synthetic limitation marker: {marker}",
                )
            )
    return reasons


def _local_only_text_value_reasons(payload: Any, artifact_type: str) -> list[Reason]:
    reasons: list[Reason] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            reasons.extend(_local_only_text_reasons(value.lower(), artifact_type))

    visit(payload)
    return reasons


def _local_only_truthy_field_reasons(payload: Any, artifact_type: str) -> list[Reason]:
    reasons: list[Reason] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key in LOCAL_ONLY_TRUE_FIELDS and child is True:
                    reasons.append(
                        reason(
                            "fail",
                            f"evidence.artifacts[{artifact_type}]",
                            f"artifact contains local/synthetic limitation field: {child_path}",
                        )
                    )
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(payload, "artifact")
    return reasons
