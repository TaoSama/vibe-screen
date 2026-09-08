import json
import subprocess
import sys
import unittest

from vibescreen_evidence.controller_runtime import (
    BOOLEAN_FIELDS,
    ControllerRuntimeEvidenceError,
    summarize,
)


MODULE = "vibescreen_evidence.controller_runtime"


class ControllerRuntimeEvidenceTest(unittest.TestCase):
    def complete_record(self) -> dict[str, bool]:
        return {field: True for field in BOOLEAN_FIELDS}

    def complete_record_with_artifacts(self) -> dict[str, object]:
        record: dict[str, object] = dict(self.complete_record())
        artifact_paths = [
            "device-info.json",
            "adb-devices.txt",
            "dumpsys-package-apk.txt",
            "dumpsys-input.txt",
            "android-controller-logcat.txt",
            "protocol-controller-envelopes.jsonl",
            "controller-lifecycle.jsonl",
            "host-codesign.txt",
            "host-controller-availability.txt",
            "mac-controller-observer.txt",
            "neutral-release.txt",
        ]
        record["artifact_paths"] = artifact_paths
        record["observation_artifacts"] = {
            "device_identity_recorded": ["device-info.json", "adb-devices.txt"],
            "apk_identity_recorded": ["dumpsys-package-apk.txt"],
            "physical_controller_attached": ["dumpsys-input.txt"],
            "android_controller_source_observed": ["dumpsys-input.txt", "android-controller-logcat.txt"],
            "protocol_controller_capability_negotiated": ["protocol-controller-envelopes.jsonl"],
            "android_production_forwarding_observed": ["android-controller-logcat.txt"],
            "controller_connected_state_disconnected_observed": ["controller-lifecycle.jsonl"],
            "host_identity_signed": ["host-codesign.txt"],
            "host_virtual_hid_entitlement_present": ["host-codesign.txt"],
            "host_virtual_gamepad_available": ["host-controller-availability.txt"],
            "mac_side_controller_response_observed": ["mac-controller-observer.txt"],
            "neutral_release_on_disconnect_observed": ["neutral-release.txt"],
        }
        return record

    def test_blocks_when_physical_controller_is_missing(self) -> None:
        record = self.complete_record()
        record["physical_controller_attached"] = False

        summary = summarize(record, run_id="run-1")

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_runtime_gate"])
        self.assertEqual(
            [item["field"] for item in summary["blocking_reasons"]],
            ["physical_controller_attached"],
        )

    def test_blocks_when_entitled_host_runtime_is_missing(self) -> None:
        record = self.complete_record()
        record["host_identity_signed"] = False
        record["host_virtual_hid_entitlement_present"] = False
        record["host_virtual_gamepad_available"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {
                "host_identity_signed",
                "host_virtual_hid_entitlement_present",
                "host_virtual_gamepad_available",
            },
        )

    def test_insufficient_when_non_blocking_evidence_is_missing(self) -> None:
        record = self.complete_record()
        record["mac_side_controller_response_observed"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_close_runtime_gate"])

    def test_pass_requires_every_observation(self) -> None:
        summary = summarize(self.complete_record_with_artifacts())

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_runtime_gate"])
        self.assertEqual(summary["missing_requirements"], [])
        self.assertEqual(summary["inconsistent_observations"], [])

    def test_insufficient_when_all_observations_lack_retained_artifacts(self) -> None:
        summary = summarize(self.complete_record())

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_runtime_gate"])
        missing_fields = {item["field"] for item in summary["missing_requirements"]}
        self.assertIn("artifact_paths", missing_fields)
        self.assertIn("observation_artifacts.device_identity_recorded", missing_fields)

    def test_insufficient_when_true_observations_lack_field_artifacts(self) -> None:
        record: dict[str, object] = dict(self.complete_record())
        record["artifact_paths"] = ["controller-runtime-observer.txt"]

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_runtime_gate"])
        missing_fields = {item["field"] for item in summary["missing_requirements"]}
        self.assertIn("observation_artifacts.physical_controller_attached", missing_fields)
        self.assertIn("observation_artifacts.host_virtual_hid_entitlement_present", missing_fields)
        self.assertIn("observation_artifacts.neutral_release_on_disconnect_observed", missing_fields)

    def test_insufficient_when_generic_artifact_is_reused_for_every_observation(self) -> None:
        record: dict[str, object] = dict(self.complete_record())
        record["artifact_paths"] = ["controller-runtime-observer.txt"]
        record["observation_artifacts"] = {
            field: ["controller-runtime-observer.txt"] for field in BOOLEAN_FIELDS
        }

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn(
            {
                "field": "observation_artifacts.neutral_release_on_disconnect_observed",
                "requirement": "retain disconnect neutral-release evidence",
            },
            summary["missing_requirements"],
        )

    def test_insufficient_when_field_artifact_is_not_retained(self) -> None:
        record: dict[str, object] = dict(self.complete_record())
        record["artifact_paths"] = ["controller-runtime-observer.txt"]
        record["observation_artifacts"] = {
            field: ["controller-runtime-observer.txt"] for field in BOOLEAN_FIELDS
        }
        record["observation_artifacts"]["mac_side_controller_response_observed"] = [
            "missing-mac-observer.txt"
        ]

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn(
            {
                "field": "observation_artifacts.mac_side_controller_response_observed",
                "requirement": "list only paths also present in artifact_paths",
            },
            summary["missing_requirements"],
        )

    def test_insufficient_when_observations_are_inconsistent(self) -> None:
        record = self.complete_record()
        record["controller_connected_state_disconnected_observed"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_runtime_gate"])
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertEqual(
            summary["inconsistent_observations"],
            [
                {
                    "field": "neutral_release_on_disconnect_observed",
                    "requires": ["controller_connected_state_disconnected_observed"],
                    "requirement": (
                        "neutral release evidence requires connected, state, and disconnected "
                        "controller lifecycle samples"
                    ),
                }
            ],
        )

    def test_rejects_non_boolean_observations(self) -> None:
        record = self.complete_record()
        record["physical_controller_attached"] = "yes"

        with self.assertRaisesRegex(ControllerRuntimeEvidenceError, "must be true or false"):
            summarize(record)

    def test_rejects_unknown_observation_artifact_keys(self) -> None:
        record: dict[str, object] = dict(self.complete_record_with_artifacts())
        record["observation_artifacts"]["offline_mapper_passed"] = ["mapper.txt"]

        with self.assertRaisesRegex(ControllerRuntimeEvidenceError, "unknown observation_artifacts field"):
            summarize(record)


class ControllerRuntimeCliTest(unittest.TestCase):
    def complete_record(self) -> dict[str, bool]:
        return {field: True for field in BOOLEAN_FIELDS}

    def complete_record_with_artifacts(self) -> dict[str, object]:
        record: dict[str, object] = dict(self.complete_record())
        artifact_paths = [
            "device-info.json",
            "adb-devices.txt",
            "dumpsys-package-apk.txt",
            "dumpsys-input.txt",
            "android-controller-logcat.txt",
            "protocol-controller-envelopes.jsonl",
            "controller-lifecycle.jsonl",
            "host-codesign.txt",
            "host-controller-availability.txt",
            "mac-controller-observer.txt",
            "neutral-release.txt",
        ]
        record["artifact_paths"] = artifact_paths
        record["observation_artifacts"] = {
            "device_identity_recorded": ["device-info.json", "adb-devices.txt"],
            "apk_identity_recorded": ["dumpsys-package-apk.txt"],
            "physical_controller_attached": ["dumpsys-input.txt"],
            "android_controller_source_observed": ["dumpsys-input.txt", "android-controller-logcat.txt"],
            "protocol_controller_capability_negotiated": ["protocol-controller-envelopes.jsonl"],
            "android_production_forwarding_observed": ["android-controller-logcat.txt"],
            "controller_connected_state_disconnected_observed": ["controller-lifecycle.jsonl"],
            "host_identity_signed": ["host-codesign.txt"],
            "host_virtual_hid_entitlement_present": ["host-codesign.txt"],
            "host_virtual_gamepad_available": ["host-controller-availability.txt"],
            "mac_side_controller_response_observed": ["mac-controller-observer.txt"],
            "neutral_release_on_disconnect_observed": ["neutral-release.txt"],
        }
        return record

    def test_cli_outputs_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"android_production_forwarding_observed": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_runtime_gate"])

    def test_cli_returns_one_for_insufficient_summary(self) -> None:
        record = self.complete_record()
        record["mac_side_controller_response_observed"] = False
        record["artifact_paths"] = ["controller-runtime-observer.txt"]
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-insufficient"],
            input=json.dumps(record),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["verdict"], "insufficient")

    def test_cli_requires_retained_artifacts_for_pass(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-no-artifacts"],
            input=json.dumps(self.complete_record()),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_runtime_gate"])
        self.assertIn(
            {
                "field": "artifact_paths",
                "requirement": (
                    "retain raw or focused artifacts proving every true controller "
                    "runtime observation"
                ),
            },
            summary["missing_requirements"],
        )

    def test_cli_outputs_pass_summary_with_artifacts(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-pass"],
            input=json.dumps(self.complete_record_with_artifacts()),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_runtime_gate"])


if __name__ == "__main__":
    unittest.main()
