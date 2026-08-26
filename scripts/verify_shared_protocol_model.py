#!/usr/bin/env python3
"""Verify the cross-platform Protocol v1 model manifest fails closed."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "contracts" / "shared-models" / "v1" / "manifest.json"
FIXTURE_MANIFEST = REPO_ROOT / "contracts" / "fixtures" / "messages" / "v1" / "manifest.json"
ENVELOPE_METADATA_FIELDS = {
    "protocol_version",
    "message_id",
    "correlation_id",
    "session_id",
    "session_epoch",
    "sent_at_monotonic_ns",
}


class VerificationError(Exception):
    pass


def read_text(relative_path: str) -> str:
    path = REPO_ROOT / relative_path
    if not path.is_file():
        raise VerificationError(f"missing file: {relative_path}")
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise VerificationError(f"missing file: {display_path(path)}")
    return json.loads(path.read_text(encoding="utf-8"))


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise VerificationError(f"{label}: expected {expected!r}, found {actual!r}")


def strip_proto_comments(text: str) -> str:
    return re.sub(r"//.*", "", text)


def parse_proto_message_fields(proto_text: str, message_name: str) -> dict[str, int]:
    text = strip_proto_comments(proto_text)
    match = re.search(rf"\bmessage\s+{re.escape(message_name)}\s*{{", text)
    if not match:
        raise VerificationError(f"message {message_name} not found")
    start = match.end()
    depth = 1
    index = start
    while index < len(text) and depth:
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
        index += 1
    if depth:
        raise VerificationError(f"message {message_name} has unbalanced braces")
    body = text[start : index - 1]
    fields: dict[str, int] = {}
    for field_match in re.finditer(
        r"(?:optional\s+)?(?:repeated\s+)?[A-Za-z_][A-Za-z0-9_.<>]*\s+([a-z][a-z0-9_]*)\s*=\s*(\d+)\s*;",
        body,
    ):
        fields[field_match.group(1)] = int(field_match.group(2))
    return fields


def parse_proto_enum_values(proto_text: str, enum_name: str) -> dict[str, int]:
    text = strip_proto_comments(proto_text)
    match = re.search(rf"\benum\s+{re.escape(enum_name)}\s*{{", text)
    if not match:
        raise VerificationError(f"enum {enum_name} not found")
    start = match.end()
    end = text.find("}", start)
    if end == -1:
        raise VerificationError(f"enum {enum_name} has unbalanced braces")
    body = text[start:end]
    return {
        enum_match.group(1): int(enum_match.group(2))
        for enum_match in re.finditer(r"\b([A-Z][A-Z0-9_]*)\s*=\s*(\d+)\s*;", body)
    }


def verify_proto_contract(manifest: dict[str, object]) -> None:
    for message_name, details in manifest["messages"].items():
        if not isinstance(details, dict):
            raise VerificationError(f"messages.{message_name} must be an object")
        proto_path = details["proto"]
        expected = details["fields"]
        if not isinstance(proto_path, str) or not isinstance(expected, dict):
            raise VerificationError(f"messages.{message_name} has invalid shape")
        actual = parse_proto_message_fields(read_text(proto_path), message_name)
        assert_equal(actual, expected, f"{message_name} fields")

    envelope_values = parse_proto_message_fields(
        read_text("contracts/proto/vibescreen/protocol/v1/envelope.proto"),
        "Envelope",
    )
    envelope_payload_values = {
        name: number
        for name, number in envelope_values.items()
        if name not in ENVELOPE_METADATA_FIELDS
    }
    assert_equal(
        envelope_payload_values,
        manifest["envelopePayloads"],
        "Envelope payload field numbers",
    )

    capability_values = parse_proto_enum_values(
        read_text("contracts/proto/vibescreen/protocol/v1/session.proto"),
        "Capability",
    )
    manifest_capability_values = {
        capability: details["value"]
        for capability, details in manifest["capabilities"].items()
    }
    assert_equal(capability_values, manifest_capability_values, "Capability enum values")


def capability_requires_production_check(details: object, platform: str) -> bool:
    if not isinstance(details, dict):
        raise VerificationError("capability manifest entries must be objects")
    description = details.get(f"{platform}Production", "")
    return isinstance(description, str) and description.startswith("required")


def verify_fixtures(manifest: dict[str, object]) -> None:
    fixtures = load_json(FIXTURE_MANIFEST)
    fixture_names = {entry["name"] for entry in fixtures["controlFixtures"]}
    missing = sorted(set(manifest["requiredFixtureNames"]) - fixture_names)
    if missing:
        raise VerificationError(f"required Protocol v1 fixtures missing: {', '.join(missing)}")
    assert_equal(fixtures["protocolVersion"], manifest["protocolVersion"], "fixture protocolVersion")


def normalized_hosts(policy: dict[str, object]) -> set[str]:
    hosts = policy.get("allowed_hosts", [])
    if not isinstance(hosts, list):
        raise VerificationError("managed policy allowed_hosts must be a list")
    return {host.strip().lower() for host in hosts if isinstance(host, str) and host.strip()}


def normalize_policy(policy: dict[str, object]) -> dict[str, object]:
    normalized = dict(policy)
    normalized["allowed_hosts"] = sorted(normalized_hosts(policy))
    if normalized["managed"] and (normalized["allowed_hosts_restricted"] or normalized["allowed_hosts"]):
        normalized["allowed_hosts_restricted"] = True
    return normalized


def apply_remote_policy(local: dict[str, object], remote: dict[str, object]) -> dict[str, object]:
    local = normalize_policy(local)
    remote = normalize_policy(remote)
    if not remote["managed"]:
        return local
    local_restricted = bool(local["allowed_hosts_restricted"])
    remote_restricted = bool(remote["allowed_hosts_restricted"])
    if local_restricted and remote_restricted:
        hosts = sorted(set(local["allowed_hosts"]).intersection(remote["allowed_hosts"]))
    elif local_restricted:
        hosts = local["allowed_hosts"]
    elif remote_restricted:
        hosts = remote["allowed_hosts"]
    else:
        hosts = []
    return {
        "managed": bool(local["managed"] or remote["managed"]),
        "clipboard_allowed": bool(local["clipboard_allowed"] and remote["clipboard_allowed"]),
        "file_transfer_allowed": bool(local["file_transfer_allowed"] and remote["file_transfer_allowed"]),
        "audio_allowed": bool(local["audio_allowed"] and remote["audio_allowed"]),
        "wake_allowed": bool(local["wake_allowed"] and remote["wake_allowed"]),
        "custom_gestures_allowed": bool(local["custom_gestures_allowed"] and remote["custom_gestures_allowed"]),
        "host_actions_allowed": bool(local["host_actions_allowed"] and remote["host_actions_allowed"]),
        "maximum_file_bytes": min(int(local["maximum_file_bytes"]), int(remote["maximum_file_bytes"])),
        "allowed_hosts": hosts,
        "allowed_hosts_restricted": bool(local_restricted or remote_restricted),
    }


def verify_managed_policy_cases(manifest: dict[str, object]) -> None:
    cases = manifest.get("managedPolicyCases", [])
    if not isinstance(cases, list) or not cases:
        raise VerificationError("managedPolicyCases must contain at least one case")
    for case in cases:
        name = case["name"]
        actual = apply_remote_policy(case["local"], case["remote"])
        expected = normalize_policy(case["effective"])
        assert_equal(actual, expected, f"managedPolicyCases.{name}")


def verify_generated_binding_sources(manifest: dict[str, object]) -> None:
    android_build = read_text(manifest["platforms"]["android"]["generatedBindingSource"])
    if "contracts/proto" not in android_build or "com.google.protobuf" not in android_build:
        raise VerificationError("Android build no longer generates protobuf bindings from contracts/proto")
    session_proto = read_text("contracts/proto/vibescreen/protocol/v1/session.proto")
    expected_package = manifest["platforms"]["android"]["generatedBindingPackage"]
    if f'option java_package = "{expected_package}";' not in session_proto:
        raise VerificationError("Android protobuf java_package drifted from the shared model manifest")

    ios_verify = read_text(manifest["platforms"]["ios"]["generatedBindingVerifier"])
    if "generate-protocol.sh" not in ios_verify or "baseline/MacHost/Protocol/Sources/VibeScreenProtocol" not in ios_verify:
        raise VerificationError("iOS generated-binding verifier no longer checks regenerated Swift bindings and MacHost parity")
    ios_generated_root = REPO_ROOT / manifest["platforms"]["ios"]["generatedBindingSource"]
    for proto_name in ("session", "display", "video", "input", "advanced", "envelope"):
        generated = ios_generated_root / "vibescreen" / "protocol" / "v1" / f"{proto_name}.pb.swift"
        if not generated.is_file():
            raise VerificationError(f"missing checked-in iOS generated binding: {generated.relative_to(REPO_ROOT)}")


def verify_android_production_model(manifest: dict[str, object]) -> None:
    source = read_text(manifest["platforms"]["android"]["productionModelSource"])
    tests = read_text(manifest["platforms"]["android"]["productionTestSource"])
    for capability, details in manifest["capabilities"].items():
        if not capability_requires_production_check(details, "android"):
            continue
        if capability not in source and capability not in tests:
            raise VerificationError(f"Android production boundary does not mention {capability}")
    for required in (
        "BASE_ADVERTISED_CAPABILITIES",
        "withCapabilityDependenciesApplied",
        "CAPABILITY_STYLUS_EXTENDED",
        "CAPABILITY_USB_HID_MODIFIER_BYTE",
        "CAPABILITY_CLIENT_VIDEO_CONTROL",
        "CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK",
        "addAllVideoDecodeCapabilities",
        "addAllRequiredCapabilities(requiredCapabilities)",
    ):
        if required not in source:
            raise VerificationError(f"Android production model missing {required}")
    if "clientHelloPinsVersionAndExactProductionCapabilities" not in tests:
        raise VerificationError("Android focused ClientHello capability pin test is missing")
    for required in ("fun applying(remote: ManagedPolicy)", "fun fromStatus(status: ManagedPolicyStatus)", "fun toStatus(): ManagedPolicyStatus"):
        if required not in source:
            raise VerificationError(f"Android managed policy model missing {required}")


def verify_ios_production_model(manifest: dict[str, object]) -> None:
    source = read_text(manifest["platforms"]["ios"]["productionModelSource"])
    tests = read_text(manifest["platforms"]["ios"]["productionTestSource"])
    session_state = read_text("apps/ios/Sources/VibeScreenCore/SessionState.swift")
    native_input = read_text("apps/ios/Sources/VibeScreenCore/NativeInput.swift")
    for required in (
        "advertisedCapabilities(policy:",
        ".managedConfiguration",
        ".hostActions",
        ".audio",
        ".clipboard",
        ".fileTransfer",
        ".wakeHost",
        "sdrDecodeCapabilities",
    ):
        if required not in source:
            raise VerificationError(f"iOS production model missing {required}")
    for required in (".keyboard", ".usbHidModifierByte", ".pointer", ".touch"):
        if required not in native_input:
            raise VerificationError(f"iOS native input capability boundary missing {required}")
    for required in ("negotiated.remove(.usbHidModifierByte)", "negotiated.remove(.stylusExtended)"):
        if required not in session_state:
            raise VerificationError(f"iOS SessionState dependency filter missing {required}")
    managed_policy = read_text("apps/ios/Sources/VibeScreenCore/ManagedPolicy.swift")
    for required in ("public init(remoteStatus: VSManagedPolicyStatus)", "public var protocolStatus", "public func applying(remote: ManagedPolicy)"):
        if required not in managed_policy:
            raise VerificationError(f"iOS managed policy model missing {required}")
    for fixture_name in manifest["iosSelfTestFixtureNames"]:
        if fixture_name not in tests:
            raise VerificationError(f"iOS self-test does not mention required fixture {fixture_name}")


def verify_manifest(manifest_path: Path) -> None:
    manifest = load_json(manifest_path)
    assert_equal(manifest["schema"], "dev.vibescreen.shared-protocol-model/v1", "schema")
    assert_equal(manifest["protocolVersion"], 1, "protocolVersion")
    verify_proto_contract(manifest)
    verify_fixtures(manifest)
    verify_managed_policy_cases(manifest)
    verify_generated_binding_sources(manifest)
    verify_android_production_model(manifest)
    verify_ios_production_model(manifest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        verify_manifest(args.manifest)
    except VerificationError as error:
        print(f"shared protocol model verification failed: {error}", file=sys.stderr)
        return 1
    print(f"shared protocol model verified: {display_path(args.manifest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
