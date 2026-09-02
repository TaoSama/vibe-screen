from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence.host_display_rotation_current_base_gate import derive_gate
from vibescreen_evidence.host_display_rotation_gate import (
    KIND as EVIDENCE_KIND,
    REQUIRED_INPUT_MAPPING_POINTS,
    evaluate as evaluate_rotation_gate,
)
from vibescreen_evidence.host_display_rotation_current_base_manifest import (
    FORMAL_GATES,
    HOST_PREFLIGHT_CHECKS,
    REDACTED_ADB_SERIAL,
    SOURCE_DOCS,
    build_manifest,
)


MODULE = "vibescreen_evidence.host_display_rotation_current_base_gate"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "host-display-rotation-current-base-gate.schema.json"
TEST_ADB_SERIAL = "TEST_ADB_SERIAL_001"


def make_docs(root: Path) -> None:
    for path in SOURCE_DOCS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture" + chr(10), encoding="utf-8")


def make_device() -> dict[str, object]:
    return {
        "status": "pass",
        "runtime_class": "physical_android_device",
        "manufacturer": "nubia",
        "model": "P0110",
        "codename": "pacific",
        "android_release": "16",
        "sdk": 36,
        "adb_serial": REDACTED_ADB_SERIAL,
        "package_status": "installed",
        "evidence": ["device-identity.txt"],
        "probes": {},
    }


def make_manifest(root: Path) -> dict[str, object]:
    make_docs(root)
    with patch("vibescreen_evidence.host_display_rotation_current_base_manifest.repository_state") as state, patch(
        "vibescreen_evidence.host_display_rotation_current_base_manifest.collect_environment"
    ) as environment, patch(
        "vibescreen_evidence.host_display_rotation_current_base_manifest.collect_device"
    ) as device:
        state.return_value = {"revision": "a" * 40, "dirty": False, "status_porcelain": []}
        environment.return_value = {"codesigning_identities": {"target_identity_available": False}}
        device.return_value = make_device()
        return build_manifest(command=[], repo=root, adb_serial=TEST_ADB_SERIAL)


def write_manifest(root: Path, manifest: dict[str, object]) -> Path:
    path = root / "host-display-rotation-current-base-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def complete_evidence_run(display_kind: str, rotation: int) -> dict[str, object]:
    points = []
    for index, name in enumerate(REQUIRED_INPUT_MAPPING_POINTS, start=1):
        expected_host_x = float(index * 10)
        expected_host_y = float(index * 10)
        observed_host_x = expected_host_x + 1
        observed_host_y = expected_host_y + 1
        points.append(
            {
                "name": name,
                "android_x": float(index),
                "android_y": float(index),
                "expected_host_x": expected_host_x,
                "expected_host_y": expected_host_y,
                "observed_host_x": observed_host_x,
                "observed_host_y": observed_host_y,
                "error_px": math.hypot(
                    observed_host_x - expected_host_x,
                    observed_host_y - expected_host_y,
                ),
                "within_tolerance": True,
            }
        )
    return {
        "evidence_source": {
            "capture_type": "real-device-run",
            "device_runtime_class": "physical_android_device",
            "synthetic_fixture": False,
            "artifact_retention": "per-display-kind-and-rotation",
        },
        "display_kind": display_kind,
        "display_id": f"{display_kind}-display-1",
        "transport": "usb",
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_release": "16",
            "sdk": 36,
            "adb_serial": REDACTED_ADB_SERIAL,
        },
        "host_preflight": {
            "host_signing_identity": "Vibe Screen Dev",
            "host_bundle_id": "dev.telemachus.display",
            "screen_recording_granted": True,
            "accessibility_granted": True,
            "signing_tcc_match": True,
            "host_display_rotation_restoration_plan": True,
        },
        "host_rotation_degrees": rotation,
        "original_host_rotation_degrees": 0,
        "client_rotation_degrees": 0,
        "client_transform_scope": "client-local-only",
        "host_rotation_combined_with_client_transform": False,
        "host_rotation_source": "macOS Displays settings",
        "probes": {
            "visual_source_orientation": True,
            "input_mapping": True,
            "stable_stream": True,
            "no_session_teardown": True,
            "restored_original_host_rotation": True,
        },
        "inverse_touch_mapping": {
            "coordinate_space": "host-logical-display",
            "tolerance_px": 8.0,
            "points": points,
            "all_points_within_tolerance": True,
        },
        "artifacts": {
            "device_identity": f"{display_kind}-{rotation}-device-and-artifact-identity.txt",
            "host_display_snapshot_before": f"{display_kind}-{rotation}-host-display-before.txt",
            "host_display_snapshot_rotated": f"{display_kind}-{rotation}-host-display-rotated.txt",
            "host_display_snapshot_restored": f"{display_kind}-{rotation}-host-display-restored.txt",
            "android_screenshot": f"{display_kind}-{rotation}-android-rotated-host-display.png",
            "touch_matrix": f"{display_kind}-{rotation}-touch-matrix.txt",
            "host_log": f"{display_kind}-{rotation}-host.log",
            "android_logcat": f"{display_kind}-{rotation}-logcat.txt",
            "restoration_plan": f"{display_kind}-{rotation}-restoration-plan.txt",
            "session_teardown_audit": f"{display_kind}-{rotation}-session-teardown-audit.txt",
        },
    }


def complete_evidence_document() -> dict[str, object]:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": EVIDENCE_KIND,
        "runs": [
            complete_evidence_run(display_kind, rotation)
            for display_kind in ("physical", "virtual")
            for rotation in (90, 180, 270)
        ],
    }


def retained_artifact_payload(run: dict[str, object], artifact_name: str) -> str:
    display_kind = str(run["display_kind"])
    display_id = str(run["display_id"])
    host_rotation = int(run["host_rotation_degrees"])
    original_rotation = int(run["original_host_rotation_degrees"])
    device = run["device"]
    assert isinstance(device, dict)
    if artifact_name == "device_identity":
        return "\n".join(
            [
                f"manufacturer={device['manufacturer']}",
                f"model={device['model']}",
                f"codename={device['codename']}",
                f"android_release={device['android_release']}",
                f"sdk={device['sdk']}",
                f"adb_serial={device['adb_serial']}",
            ]
        )
    if artifact_name == "host_display_snapshot_before":
        return "\n".join(
            [
                f"display_kind={display_kind}",
                f"display_id={display_id}",
                f"original_host_rotation_degrees={original_rotation}",
            ]
        )
    if artifact_name == "host_display_snapshot_rotated":
        return "\n".join(
            [
                f"display_kind={display_kind}",
                f"display_id={display_id}",
                f"host_rotation_degrees={host_rotation}",
            ]
        )
    if artifact_name == "host_display_snapshot_restored":
        return "\n".join(
            [
                f"display_kind={display_kind}",
                f"display_id={display_id}",
                f"original_host_rotation_degrees={original_rotation}",
                "restored_original_host_rotation=true",
            ]
        )
    if artifact_name == "touch_matrix":
        mapping = run["inverse_touch_mapping"]
        assert isinstance(mapping, dict)
        points = mapping["points"]
        assert isinstance(points, list)
        return "\n".join(
            [
                f"display_kind={display_kind}",
                f"host_rotation_degrees={host_rotation}",
                "coordinate_space=host-logical-display",
                "all_points_within_tolerance=true",
                *[str(point["name"]) for point in points if isinstance(point, dict)],
            ]
        )
    if artifact_name == "restoration_plan":
        return "\n".join(
            [
                f"display_kind={display_kind}",
                f"host_rotation_degrees={host_rotation}",
                f"original_host_rotation_degrees={original_rotation}",
                "host_display_rotation_restoration_plan=true",
            ]
        )
    if artifact_name == "session_teardown_audit":
        return "\n".join(
            [
                f"display_kind={display_kind}",
                f"host_rotation_degrees={host_rotation}",
                "no_session_teardown=true",
            ]
        )
    if artifact_name in ("host_log", "android_logcat"):
        return "\n".join(
            [
                f"display_kind={display_kind}",
                f"display_id={display_id}",
                f"host_rotation_degrees={host_rotation}",
                "stream remained stable during rotation",
            ]
        )
    return f"retained {artifact_name} for {display_kind} host_rotation_degrees={host_rotation}\n"


def write_complete_evidence_gate(root: Path) -> None:
    document = complete_evidence_document()
    runs = document["runs"]
    assert isinstance(runs, list)
    for run in runs:
        assert isinstance(run, dict)
        artifacts = run["artifacts"]
        assert isinstance(artifacts, dict)
        for artifact_name, artifact in artifacts.items():
            path = root / str(artifact)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                retained_artifact_payload(run, str(artifact_name)) + "\n",
                encoding="utf-8",
            )
    (root / "host-display-rotation.json").write_text(
        json.dumps(document), encoding="utf-8"
    )
    gate = evaluate_rotation_gate(document, evidence_dir=root)
    assert gate["status"] == "complete", gate["errors"]
    (root / "host-display-rotation-gate.json").write_text(
        json.dumps(gate), encoding="utf-8"
    )


def write_forged_complete_evidence_gate(root: Path) -> None:
    gate = evaluate_rotation_gate(
        {
            "schema_version": "vibescreen.evidence/v1",
            "kind": EVIDENCE_KIND,
            "runs": [],
        }
    ) | {
        "status": "complete",
        "artifact_file_check": True,
        "covered_display_kinds": ["physical", "virtual"],
        "covered_host_rotations_by_display_kind": {
            "physical": [90, 180, 270],
            "virtual": [90, 180, 270],
        },
        "errors": [],
    }
    (root / "host-display-rotation-gate.json").write_text(
        json.dumps(gate), encoding="utf-8"
    )


def complete_manifest(root: Path) -> dict[str, object]:
    manifest = make_manifest(root)
    host_preflight = manifest["host_preflight"]
    assert isinstance(host_preflight, dict)
    for name in HOST_PREFLIGHT_CHECKS:
        record = host_preflight[name]
        assert isinstance(record, dict)
        record["status"] = "pass"
        record["evidence"] = [f"{name}.txt"]
    gates = manifest["gates"]
    assert isinstance(gates, dict)
    for name in FORMAL_GATES:
        gate = gates[name]
        assert isinstance(gate, dict)
        gate["status"] = "pass"
        gate["covered_host_rotations"] = [90, 180, 270]
        gate["evidence"] = [f"{name}.json"]
    return manifest


class HostDisplayRotationCurrentBaseGateTests(unittest.TestCase):
    def test_default_manifest_is_blocked_even_with_client_local_pass(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, make_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_host_display_rotation_acceptance"])
        self.assertFalse(report["can_close_current_base_aggregate"])
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("blocked: signing_identity", report["reasons"])
        self.assertIn("blocked: physical_host_display_rotation", report["reasons"])
        self.assertIn("blocked: virtual_host_display_rotation", report["reasons"])

    def test_complete_manifest_with_recomputed_evidence_gate_passes(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            write_complete_evidence_gate(root)
            manifest_path = write_manifest(root, complete_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_host_display_rotation_acceptance"])
        self.assertTrue(report["can_close_current_base_aggregate"])
        self.assertTrue(report["can_claim_real_device_pass"])

    def test_forged_retained_evidence_gate_without_raw_evidence_blocks(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            write_forged_complete_evidence_gate(root)
            manifest_path = write_manifest(root, complete_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn(
            "blocked: host_display_rotation_evidence_gate", report["reasons"]
        )

    def test_retained_evidence_gate_must_match_recomputed_raw_evidence(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            write_complete_evidence_gate(root)
            raw_evidence = root / "host-display-rotation.json"
            document = json.loads(raw_evidence.read_text(encoding="utf-8"))
            runs = document["runs"]
            assert isinstance(runs, list)
            first_run = runs[0]
            assert isinstance(first_run, dict)
            first_run["host_rotation_degrees"] = 180
            raw_evidence.write_text(json.dumps(document), encoding="utf-8")
            manifest_path = write_manifest(root, complete_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        evidence_gate = report["checks"]["host_display_rotation_evidence_gate"]
        self.assertFalse(evidence_gate["retained_matches_recomputed"])

    def test_missing_one_required_rotation_blocks_gate(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            write_complete_evidence_gate(root)
            gates = manifest["gates"]
            assert isinstance(gates, dict)
            physical = gates["physical_host_display_rotation"]
            assert isinstance(physical, dict)
            physical["covered_host_rotations"] = [90, 270]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("blocked: physical_host_display_rotation", report["reasons"])

    def test_dirty_repository_blocks_current_base_gate(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            write_complete_evidence_gate(root)
            repository = manifest["repository"]
            assert isinstance(repository, dict)
            repository["revision"] = "a" * 40
            repository["dirty"] = True
            repository["status_porcelain"] = ["?? evidence/partial.txt"]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("metadata: repository_current_base", report["reasons"])

    def test_short_repository_revision_blocks_current_base_gate(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            write_complete_evidence_gate(root)
            repository = manifest["repository"]
            assert isinstance(repository, dict)
            repository["revision"] = "abc"
            repository["dirty"] = False
            repository["status_porcelain"] = []
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("metadata: repository_current_base", report["reasons"])

    def test_retained_origin_main_ancestor_check_allows_pr_head_source(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            write_complete_evidence_gate(root)
            manifest_path = write_manifest(root, manifest)
            (root / "git-origin-main.txt").write_text("b" * 40 + chr(10), encoding="utf-8")
            (root / "git-origin-main-ancestor.exit-code").write_text("0" + chr(10), encoding="utf-8")

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_claim_real_device_pass"])

    def test_retained_origin_main_non_ancestor_blocks_current_base_gate(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            write_complete_evidence_gate(root)
            manifest_path = write_manifest(root, manifest)
            (root / "git-origin-main.txt").write_text("b" * 40 + chr(10), encoding="utf-8")
            (root / "git-origin-main-ancestor.exit-code").write_text("1" + chr(10), encoding="utf-8")

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("metadata: repository_current_base", report["reasons"])

    def test_client_local_substitution_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            write_complete_evidence_gate(root)
            manifest["client_local_matrix_used_for_host_rotation"] = True
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["can_close_current_base_aggregate"])
        self.assertIn("fail: client_local_matrix_not_used_for_host_rotation", report["reasons"])

    def test_manifest_contract_violation_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            write_complete_evidence_gate(root)
            del manifest["source_root"]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("manifest schema violation", report["reasons"][0])

    def test_device_contract_requires_package_status_and_probes(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            write_complete_evidence_gate(root)
            device = manifest["device"]
            assert isinstance(device, dict)
            del device["package_status"]
            del device["probes"]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("package_status", report["reasons"][0])
        self.assertIn("probes", report["reasons"][0])

    def test_source_docs_resolve_from_manifest_source_root(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name) / "repo"
            output_dir = Path(directory_name) / "out"
            output_dir.mkdir()
            manifest = complete_manifest(root)
            write_complete_evidence_gate(output_dir)
            manifest_path = output_dir / "host-display-rotation-current-base-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                report = derive_gate(manifest_path)
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(report["verdict"], "pass")

    def test_report_matches_schema_required_top_level_fields(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            write_complete_evidence_gate(root)
            manifest_path = write_manifest(root, complete_manifest(root))
            report = derive_gate(manifest_path)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(report), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, report)

    def test_formal_gates_require_retained_evidence_gate_output(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, complete_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn(
            "blocked: host_display_rotation_evidence_gate", report["reasons"]
        )
        self.assertIn(
            "blocked: physical_host_display_rotation", report["reasons"]
        )
        self.assertIn("blocked: virtual_host_display_rotation", report["reasons"])

    def test_failed_evidence_gate_output_blocks_formal_gates(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            (root / "host-display-rotation-gate.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "kind": "host_display_rotation_acceptance",
                        "status": "failed",
                        "covered_host_rotations_by_display_kind": {
                            "physical": [90, 180, 270],
                            "virtual": [90, 180, 270],
                        },
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = write_manifest(root, complete_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn(
            "blocked: host_display_rotation_evidence_gate", report["reasons"]
        )

    def test_cli_writes_blocked_report_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, make_manifest(root))
            output_path = root / "host-display-rotation-current-base-gate.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
