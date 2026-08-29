from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.ios_device_acceptance_gate import (
    ACCEPTANCE_KIND,
    REQUIRED_GATES,
    evaluate,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.ios_device_acceptance_gate"
SCHEMA_PATH = REPOSITORY_ROOT / "tools" / "schemas" / "ios-device-acceptance-gate.schema.json"
INPUT_SCHEMA_PATH = REPOSITORY_ROOT / "tools" / "schemas" / "ios-device-acceptance.schema.json"
CURRENT_BASE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
SIGNED_ARTIFACT_SHA256 = "a" * 64
VIDEOTOOLBOX_ARTIFACTS = [
    "artifacts/videotoolbox_h264.txt",
    "artifacts/videotoolbox_hevc.txt",
    "artifacts/videotoolbox-output-frames.txt",
    "artifacts/videotoolbox-telemetry-power.txt",
]


def write_artifacts(directory: Path, names: list[str]) -> None:
    for name in names:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"artifact: {name}\n", encoding="utf-8")


def write_complete_artifacts(directory: Path) -> None:
    write_artifacts(
        directory, [f"artifacts/{name}.txt" for name in REQUIRED_GATES] + VIDEOTOOLBOX_ARTIFACTS
    )


def complete_document() -> dict:
    gates = {
        name: {"status": "complete", "evidence": [f"artifacts/{name}.txt"]}
        for name in REQUIRED_GATES
    }
    gates["videotoolbox_h264"]["evidence"] = [
        "artifacts/videotoolbox_h264.txt",
        "artifacts/videotoolbox-output-frames.txt",
        "artifacts/videotoolbox-telemetry-power.txt",
    ]
    gates["videotoolbox_hevc"]["evidence"] = [
        "artifacts/videotoolbox_hevc.txt",
        "artifacts/videotoolbox-output-frames.txt",
        "artifacts/videotoolbox-telemetry-power.txt",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": ACCEPTANCE_KIND,
        "platform": "ios",
        "status": "complete",
        "repository": {
            "commit": CURRENT_BASE_COMMIT,
            "branch": "codex/ios-device-acceptance-gate",
            "dirty": False,
        },
        "host": {
            "commit": "def456",
            "macos_version": "26.4.1",
            "permissions_changed_by_run": False,
        },
        "xcode": {
            "version": "16.4",
            "selected_developer_dir": "/Applications/Xcode.app",
            "ios_sdk": "18.5",
        },
        "trusted_lan": {
            "mode": "explicit_plaintext_legacy_fallback",
            "encrypted_lan_claimed": False,
        },
        "signing": {
            "status": "complete",
            "bundle_id": "dev.example.vibescreen.acceptance",
            "team_id_redacted": True,
            "certificate_common_name_redacted": True,
            "provisioning_profile_uuid_redacted": True,
            "archive_sha256": "sha256:" + SIGNED_ARTIFACT_SHA256,
        },
        "signing_readiness_gate": {
            "schema_version": SCHEMA_VERSION,
            "kind": "ios_app_signing_readiness_gate",
            "owner": {
                "role": "ios_app_signing_readiness_current_base_owner",
                "head_ref": "codex/ios-app-signing-readiness-current-base-20260829",
                "repository": "TaoSama/vibe-screen",
                "scope": "Phase 5 iOS app-signing readiness prerequisite only",
            },
            "source": {
                "readiness": "ios-app-signing-readiness.json",
                "evidence_root": ".",
            },
            "current_base": {
                "commit": CURRENT_BASE_COMMIT,
                "branch": "codex/ios-app-signing-readiness-current-base-20260829",
                "dirty": False,
            },
            "verdict": "pass",
            "signing_status": "complete",
            "signing_summary": {
                "status": "pass",
                "bundle_id": "dev.example.vibescreen.acceptance",
                "unique_bundle_id": True,
                "team_id_recorded": True,
                "codesign_identity_recorded": True,
                "provisioning_profile_recorded": True,
                "device_udid_hashes_recorded": True,
                "entitlements_recorded": True,
                "signed_artifact_sha256": SIGNED_ARTIFACT_SHA256,
            },
            "can_close_ios_app_signing_readiness": True,
            "can_close_ios_device_acceptance": False,
            "recorded_fields": {
                "team_id": True,
                "provisioning_profile": True,
                "bundle_id": True,
                "codesign_identity": True,
                "device_udid": True,
                "entitlements": True,
                "signed_artifact": True,
                "artifacts": True,
            },
            "missing": [],
            "failures": [],
            "evidence": [
                "logs/xcodebuild-archive.txt",
                "logs/codesign-entitlements.txt",
                "logs/profile-summary.txt",
            ],
            "interpretation": "Fixture app-signing readiness pass.",
        },
        "videotoolbox_readiness_gates": [
            videotoolbox_readiness_gate("physical_iphone"),
            videotoolbox_readiness_gate("physical_ipad"),
        ],
        "devices": [
            {
                "role": "iphone",
                "product_name": "iPhone 15",
                "hardware_model": "iPhone15,4",
                "os_version": "18.5",
                "build_number": "22F76",
                "install_status": "complete",
            },
            {
                "role": "ipad",
                "product_name": "iPad Pro",
                "hardware_model": "iPad14,5",
                "os_version": "18.5",
                "build_number": "22F76",
                "install_status": "complete",
            },
        ],
        "gates": gates,
        "android_evidence_used_for_ios_gates": False,
        "notes": [],
    }


def videotoolbox_readiness_gate(runtime_class: str) -> dict:
    artifact_checks = [
        {
            "path": artifact,
            "exists": True,
            "non_empty": True,
            "under_evidence_dir": True,
            "valid_ios_videotoolbox_source": True,
        }
        for artifact in VIDEOTOOLBOX_ARTIFACTS
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"{runtime_class}-run",
        "kind": "ios_hardware_videotoolbox_readiness",
        "profile": "ios-hardware-videotoolbox-readiness",
        "runtime_class": runtime_class,
        "verdict": "pass",
        "can_close_device_family_videotoolbox_gate": True,
        "can_close_phase5_hardware_videotoolbox_gate": False,
        "artifact_paths": list(VIDEOTOOLBOX_ARTIFACTS),
        "artifact_checks": artifact_checks,
    }


class IOSDeviceAcceptanceGateTest(unittest.TestCase):
    def test_accepts_complete_iphone_and_ipad_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)

            result = evaluate(complete_document(), evidence_root)

        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["covered_devices"], ["ipad", "iphone"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["failures"], [])

    def test_result_shape_matches_schema_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            result = evaluate(complete_document(), evidence_root)

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(result), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, result)

    def test_input_schema_requires_embedded_signing_readiness_gate(self) -> None:
        schema = json.loads(INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIn("signing_readiness_gate", schema["required"])
        signing_gate = schema["properties"]["signing_readiness_gate"]
        self.assertIn("owner", signing_gate["required"])
        self.assertIn("current_base", signing_gate["required"])
        self.assertIn("signing_summary", signing_gate["required"])
        self.assertIn("recorded_fields", signing_gate["required"])
        summary = signing_gate["properties"]["signing_summary"]
        self.assertIn("codesign_identity_recorded", summary["required"])
        self.assertIn("device_udid_hashes_recorded", summary["required"])
        self.assertIn("entitlements_recorded", summary["required"])

    def test_input_schema_declares_host_advanced_adapter_broader_gate(self) -> None:
        schema = json.loads(INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))

        broader_gates = schema["properties"]["broader_gates"]["properties"]
        self.assertIn("host_advanced_adapters", broader_gates)
        self.assertEqual(
            broader_gates["host_advanced_adapters"],
            {"$ref": "#/$defs/evidence_gate"},
        )

    def test_input_schema_requires_embedded_videotoolbox_readiness_gates(self) -> None:
        schema = json.loads(INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIn("videotoolbox_readiness_gates", schema["required"])
        readiness_gate = schema["properties"]["videotoolbox_readiness_gates"]["items"]
        self.assertIn("artifact_checks", readiness_gate["required"])
        self.assertEqual(readiness_gate["properties"]["runtime_class"]["enum"], ["physical_iphone", "physical_ipad"])

    def test_missing_ipad_and_open_gate_are_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["devices"] = [document["devices"][0]]
            document["gates"]["reconnect"]["status"] = "open"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn("devices: missing ipad hardware evidence", result["missing"])
        self.assertIn("gates.reconnect.status: must be complete", result["missing"])

    def test_failed_required_gate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["gates"]["reconnect"]["status"] = "failed"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("gates.reconnect.status: is failed", result["failures"])

    def test_android_identity_or_android_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["android_evidence_used_for_ios_gates"] = True
            document["devices"][0]["product_name"] = "Nubia P0110 Android 16"
            document["gates"]["input"]["evidence"] = ["artifacts/android-input.txt"]
            write_artifacts(evidence_root, ["artifacts/android-input.txt"])

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("android_evidence_used_for_ios_gates: must be false", result["failures"])
        self.assertIn("devices[0].product_name: looks like Android evidence", result["failures"])
        self.assertIn(
            "gates.input.evidence[0]: must not reference Android evidence for an iOS gate",
            result["failures"],
        )

    def test_short_android_markers_require_token_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["gates"]["device_install"]["evidence"] = ["artifacts/ipadbuild.log"]
            write_artifacts(evidence_root, ["artifacts/ipadbuild.log"])

            valid_result = evaluate(document, evidence_root)

            document["gates"]["device_install"]["evidence"] = ["artifacts/adb-log.txt"]
            write_artifacts(evidence_root, ["artifacts/adb-log.txt"])
            invalid_result = evaluate(document, evidence_root)

        self.assertEqual(valid_result["verdict"], "pass")
        self.assertEqual(invalid_result["verdict"], "fail")
        self.assertIn(
            "gates.device_install.evidence[0]: must not reference Android evidence for an iOS gate",
            invalid_result["failures"],
        )

    def test_non_string_status_is_reported_as_null(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["status"] = {"bad": "shape"}

            result = evaluate(document, evidence_root)

        self.assertIsNone(result["acceptance_status"])
        self.assertEqual(result["verdict"], "insufficient")

    def test_simulator_identity_or_encrypted_lan_claim_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["trusted_lan"]["encrypted_lan_claimed"] = True
            document["devices"][0]["product_name"] = "iPhone 17 Pro Simulator"
            document["signing"]["archive_sha256"] = "unsigned-simulator.zip"
            document["gates"]["protocol_session"]["evidence"] = ["artifacts/simulator-session.txt"]
            write_artifacts(evidence_root, ["artifacts/simulator-session.txt"])

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("trusted_lan.encrypted_lan_claimed: must be false", result["failures"])
        self.assertIn(
            "devices[0].product_name: must be physical iOS hardware, not Simulator",
            result["failures"],
        )
        self.assertIn(
            "signing.archive_sha256: must not reference unsigned, Simulator, or ad-hoc artifacts",
            result["failures"],
        )
        self.assertIn(
            "gates.protocol_session.evidence[0]: must not reference Simulator evidence for an iOS gate",
            result["failures"],
        )
        self.assertIn(
            "signing.archive_sha256: must be a SHA-256 digest",
            result["missing"],
        )

    def test_placeholder_archive_hash_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing"]["archive_sha256"] = "sha256:1234"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "signing.archive_sha256: must be a SHA-256 digest",
            result["missing"],
        )
        self.assertIn(
            "signing.archive_sha256: must match signing_readiness_gate signed artifact digest",
            result["missing"],
        )

    def test_missing_signing_readiness_gate_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            del document["signing_readiness_gate"]

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn("signing_readiness_gate: must be an object", result["missing"])

    def test_missing_videotoolbox_readiness_gates_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            del document["videotoolbox_readiness_gates"]

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "videotoolbox_readiness_gates: must include physical iPhone and iPad readiness summaries",
            result["missing"],
        )

    def test_videotoolbox_readiness_requires_physical_iphone_and_ipad_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["videotoolbox_readiness_gates"] = [
                videotoolbox_readiness_gate("physical_iphone"),
                {**videotoolbox_readiness_gate("physical_ipad"), "verdict": "blocked"},
            ]

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "videotoolbox_readiness_gates[1].verdict: must be pass",
            result["missing"],
        )

    def test_videotoolbox_readiness_rejects_simulator_or_phase5_close_claim(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["videotoolbox_readiness_gates"] = [
                {
                    **videotoolbox_readiness_gate("physical_iphone"),
                    "runtime_class": "simulator",
                    "can_close_phase5_hardware_videotoolbox_gate": True,
                },
                videotoolbox_readiness_gate("physical_ipad"),
            ]

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn(
            "videotoolbox_readiness_gates[0].runtime_class: must be physical_iphone or physical_ipad",
            result["missing"],
        )
        self.assertIn(
            "videotoolbox_readiness_gates[0].can_close_phase5_hardware_videotoolbox_gate: must remain false",
            result["failures"],
        )

    def test_videotoolbox_codec_gates_must_link_to_readiness_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["gates"]["videotoolbox_h264"]["evidence"] = ["artifacts/standalone-h264.txt"]
            write_artifacts(evidence_root, ["artifacts/standalone-h264.txt"])

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "gates.videotoolbox_h264.evidence: must reference retained artifacts from videotoolbox_readiness_gates",
            result["missing"],
        )

    def test_failed_signing_readiness_gate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing_readiness_gate"]["verdict"] = "fail"
            document["signing_readiness_gate"]["failures"] = [
                "signing.codesign_identity: must be a real Apple signing identity, not ad-hoc"
            ]

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("signing_readiness_gate.verdict: is fail", result["failures"])
        self.assertIn(
            "signing_readiness_gate.failures: must be an empty array",
            result["failures"],
        )

    def test_blocked_signing_readiness_gate_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing_readiness_gate"]["verdict"] = "blocked"
            document["signing_readiness_gate"]["can_close_ios_app_signing_readiness"] = False
            document["signing_readiness_gate"]["missing"] = [
                "signing.device_udids: at least one physical device UDID hash is required"
            ]

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn("signing_readiness_gate.verdict: must be pass", result["missing"])
        self.assertIn(
            "signing_readiness_gate.can_close_ios_app_signing_readiness: must be true",
            result["missing"],
        )
        self.assertIn(
            "signing_readiness_gate.missing: must be an empty array",
            result["missing"],
        )

    def test_signing_readiness_gate_requires_dedicated_owner(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing_readiness_gate"]["owner"]["head_ref"] = "main"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn(
            "signing_readiness_gate.owner.head_ref: must be codex/ios-app-signing-readiness-current-base-20260829",
            result["failures"],
        )

    def test_signing_readiness_gate_requires_current_commit_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing_readiness_gate"]["current_base"]["commit"] = "b" * 40

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "signing_readiness_gate.current_base.commit: must match repository.commit",
            result["missing"],
        )

    def test_signing_readiness_gate_requires_udids_entitlements_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            summary = document["signing_readiness_gate"]["signing_summary"]
            summary["codesign_identity_recorded"] = False
            summary["device_udid_hashes_recorded"] = False
            summary["entitlements_recorded"] = False
            recorded = document["signing_readiness_gate"]["recorded_fields"]
            recorded["codesign_identity"] = False
            recorded["device_udid"] = False
            recorded["entitlements"] = False

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "signing_readiness_gate.signing_summary.codesign_identity_recorded: must be true",
            result["missing"],
        )
        self.assertIn(
            "signing_readiness_gate.signing_summary.device_udid_hashes_recorded: must be true",
            result["missing"],
        )
        self.assertIn(
            "signing_readiness_gate.signing_summary.entitlements_recorded: must be true",
            result["missing"],
        )
        self.assertIn(
            "signing_readiness_gate.recorded_fields.codesign_identity: must be true",
            result["missing"],
        )
        self.assertIn(
            "signing_readiness_gate.recorded_fields.device_udid: must be true",
            result["missing"],
        )
        self.assertIn(
            "signing_readiness_gate.recorded_fields.entitlements: must be true",
            result["missing"],
        )

    def test_signing_readiness_gate_cannot_claim_device_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing_readiness_gate"]["can_close_ios_device_acceptance"] = True

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn(
            "signing_readiness_gate.can_close_ios_device_acceptance: must be false",
            result["failures"],
        )

    def test_signing_readiness_gate_requires_pass_summary_and_unique_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            summary = document["signing_readiness_gate"]["signing_summary"]
            summary["status"] = "blocked"
            summary["unique_bundle_id"] = False

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "signing_readiness_gate.signing_summary.status: must be pass",
            result["missing"],
        )
        self.assertIn(
            "signing_readiness_gate.signing_summary.unique_bundle_id: must be true",
            result["missing"],
        )

    def test_signing_readiness_gate_requires_retained_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing_readiness_gate"]["evidence"] = []

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "signing_readiness_gate.evidence: must include retained signing artifacts",
            result["missing"],
        )

    def test_signing_readiness_gate_requires_signed_artifact_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing_readiness_gate"]["signing_summary"][
                "signed_artifact_sha256"
            ] = "1234"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "signing_readiness_gate.signing_summary.signed_artifact_sha256: must be a SHA-256 digest",
            result["missing"],
        )
        self.assertIn(
            "signing.archive_sha256: must match signing_readiness_gate signed artifact digest",
            result["missing"],
        )

    def test_all_recorded_fields_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            recorded = document["signing_readiness_gate"]["recorded_fields"]
            for field in (
                "team_id",
                "provisioning_profile",
                "bundle_id",
                "signed_artifact",
                "artifacts",
            ):
                recorded[field] = False

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        for field in (
            "team_id",
            "provisioning_profile",
            "bundle_id",
            "signed_artifact",
            "artifacts",
        ):
            self.assertIn(
                f"signing_readiness_gate.recorded_fields.{field}: must be true",
                result["missing"],
            )

    def test_signing_summary_must_match_legacy_signing_row(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing"]["bundle_id"] = "dev.example.other"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "signing.bundle_id: must match signing_readiness_gate summary",
            result["missing"],
        )

    def test_signing_archive_hash_must_match_readiness_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing"]["archive_sha256"] = "sha256:" + "b" * 64

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "signing.archive_sha256: must match signing_readiness_gate signed artifact digest",
            result["missing"],
        )

    def test_ad_hoc_archive_marker_fails_in_legacy_signing_row(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["signing"]["archive_sha256"] = "ad-hoc-signed-app.zip"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn(
            "signing.archive_sha256: must not reference unsigned, Simulator, or ad-hoc artifacts",
            result["failures"],
        )

    def test_missing_or_escaping_artifact_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["gates"]["audio_playback"]["evidence"] = ["missing-audio.log"]
            document["gates"]["reconnect"]["evidence"] = ["../outside.log"]

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "gates.audio_playback.evidence[0]: missing retained artifact missing-audio.log",
            result["missing"],
        )
        self.assertIn(
            "gates.reconnect.evidence[0]: must stay within the evidence root",
            result["missing"],
        )

    def test_failed_status_or_unredacted_signing_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["status"] = "failed"
            document["signing"]["team_id_redacted"] = False
            document["host"]["permissions_changed_by_run"] = True

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("status: is failed", result["failures"])
        self.assertIn("signing.team_id_redacted: must be true in committed sanitized evidence", result["failures"])
        self.assertIn("host.permissions_changed_by_run: must be false for this acceptance runbook", result["failures"])


class IOSDeviceAcceptanceGateCliTest(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_writes_pass_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            input_path = evidence_root / "acceptance.json"
            output_path = evidence_root / "ios-device-acceptance-gate.json"
            input_path.write_text(json.dumps(complete_document()), encoding="utf-8")

            result = self.run_cli(
                "--acceptance", str(input_path), "--output", str(output_path)
            )
            persisted = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(persisted["verdict"], "pass")

    def test_cli_returns_insufficient_for_open_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_complete_artifacts(evidence_root)
            document = complete_document()
            document["status"] = "open"
            input_path = evidence_root / "acceptance.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")

            result = self.run_cli("--acceptance", str(input_path))

        self.assertEqual(result.returncode, 1)
        self.assertIn("status: must be complete", result.stderr)
        self.assertEqual(json.loads(result.stdout)["verdict"], "insufficient")

    def test_cli_returns_error_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            input_path = Path(raw_directory) / "acceptance.json"
            input_path.write_text("not-json", encoding="utf-8")

            result = self.run_cli("--acceptance", str(input_path))

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
