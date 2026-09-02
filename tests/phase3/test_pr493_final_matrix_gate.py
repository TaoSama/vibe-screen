from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / "docs/changes/2026-09-02-pr493-mode-toggle-device-evidence"
COLLECTOR_PATH = EVIDENCE_ROOT / "collect_final_matrix.py"
VALIDATION_PATH = (
    EVIDENCE_ROOT
    / "final-076333b-real-rotation-matrix"
    / "metadata"
    / "validation.json"
)

spec = importlib.util.spec_from_file_location("pr493_collect_final_matrix", COLLECTOR_PATH)
assert spec is not None
collector = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(collector)


def scenario(label: str, xml_status: str = "unavailable") -> dict[str, object]:
    return {
        "label": label,
        "png_ok": True,
        "state_ok": True,
        "xml_status": xml_status,
        "xml_errors": [],
    }


def current_scenarios(*present_labels: str) -> list[dict[str, object]]:
    present = set(present_labels)
    return [
        scenario(label, "present" if label in present else "unavailable")
        for label, *_ in collector.SCENARIOS
    ]


def valid_restored() -> dict[str, bool]:
    return {key: True for key in collector.REQUIRED_RESTORE_KEYS}


def valid_summary() -> dict[str, object]:
    return {
        "apk_sha256": collector.EXPECTED_APK_SHA256,
        "android_test_apk_sha256": collector.EXPECTED_ANDROID_TEST_APK_SHA256,
        "device_model": collector.EXPECTED_DEVICE_MODEL,
        "instrumentation_p0110_landscape_large_text": True,
        "scenarios": current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        ),
        "restored": valid_restored(),
    }


class PR493FinalMatrixGateTests(unittest.TestCase):
    def test_valid_summary_passes_gate(self) -> None:
        self.assertEqual(collector.summary_gate_errors(valid_summary()), [])

    def test_summary_rejects_wrong_type_without_traceback(self) -> None:
        for value in (None, [], "summary", 1):
            with self.subTest(value=value):
                self.assertEqual(
                    collector.summary_gate_errors(value),
                    [f"summary must be an object: {type(value).__name__}"],
                )

    def test_identity_and_hash_mismatch_fail(self) -> None:
        for key, expected in (
            ("apk_sha256", "apk_sha256 mismatch: 'tampered'"),
            ("android_test_apk_sha256", "android_test_apk_sha256 mismatch: 'tampered'"),
            ("device_model", "device_model mismatch: 'tampered'"),
        ):
            with self.subTest(key=key):
                summary = valid_summary()
                summary[key] = "tampered"

                self.assertIn(expected, collector.summary_gate_errors(summary))

    def test_identity_fields_missing_and_non_string_types_fail(self) -> None:
        for key, expected_prefix in (
            ("apk_sha256", "apk_sha256 mismatch"),
            ("android_test_apk_sha256", "android_test_apk_sha256 mismatch"),
            ("device_model", "device_model mismatch"),
        ):
            with self.subTest(key=key, variant="missing"):
                summary = valid_summary()
                del summary[key]
                self.assertTrue(
                    any(error.startswith(expected_prefix) for error in collector.summary_gate_errors(summary))
                )

            with self.subTest(key=key, variant="non-string"):
                summary = valid_summary()
                summary[key] = 1
                self.assertTrue(
                    any(error.startswith(expected_prefix) for error in collector.summary_gate_errors(summary))
                )

    def test_strict_boolean_gates_reject_truthy_non_bool_values(self) -> None:
        summary = valid_summary()
        summary["instrumentation_p0110_landscape_large_text"] = 1
        summary["scenarios"][0]["png_ok"] = "false"
        summary["scenarios"][1]["state_ok"] = 1

        errors = collector.summary_gate_errors(summary)

        self.assertIn("instrumentation p0110 landscape large-text layout failed", errors)
        self.assertIn("phone-portrait-day-font1 PNG size validation failed", errors)
        self.assertIn("phone-portrait-night-font1 state validation failed", errors)

    def test_strict_boolean_gates_reject_explicit_false(self) -> None:
        summary = valid_summary()
        summary["instrumentation_p0110_landscape_large_text"] = False
        summary["scenarios"][0]["png_ok"] = False
        summary["scenarios"][1]["state_ok"] = False

        errors = collector.summary_gate_errors(summary)

        self.assertIn("instrumentation p0110 landscape large-text layout failed", errors)
        self.assertIn("phone-portrait-day-font1 PNG size validation failed", errors)
        self.assertIn("phone-portrait-night-font1 state validation failed", errors)

    def test_missing_instrumentation_key_fails_closed(self) -> None:
        summary = valid_summary()
        del summary["instrumentation_p0110_landscape_large_text"]

        self.assertIn(
            "instrumentation p0110 landscape large-text layout failed",
            collector.summary_gate_errors(summary),
        )

    def test_scenarios_wrong_type_fails_without_traceback(self) -> None:
        for value in (None, {}, "scenarios", 1):
            with self.subTest(value=value):
                summary = valid_summary()
                summary["scenarios"] = value

                errors = collector.summary_gate_errors(summary)

                self.assertIn(f"scenarios must be a list: {type(value).__name__}", errors)

    def test_missing_scenarios_key_fails_label_gate(self) -> None:
        summary = valid_summary()
        del summary["scenarios"]

        errors = collector.summary_gate_errors(summary)

        self.assertTrue(any(error.startswith("missing scenario labels:") for error in errors))

    def test_scenario_entry_wrong_type_fails_without_traceback(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        scenarios[0] = "not-an-object"

        errors = collector.summary_gate_errors({**valid_summary(), "scenarios": scenarios})

        self.assertIn("scenario[0] must be an object: str", errors)

    def test_scenarios_must_include_expected_labels_without_duplicates(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        scenarios = scenarios[:-1]
        errors = collector.summary_gate_errors(
            {
                "instrumentation_p0110_landscape_large_text": True,
                "scenarios": scenarios,
                "restored": valid_restored(),
            }
        )

        self.assertTrue(any("missing scenario labels: phone-landscape-night-font13" in error for error in errors))

        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        scenarios[-1] = scenario("phone-portrait-day-font1", "present")
        errors = collector.summary_gate_errors(
            {
                "instrumentation_p0110_landscape_large_text": True,
                "scenarios": scenarios,
                "restored": valid_restored(),
            }
        )

        self.assertTrue(any("duplicate scenario labels: phone-portrait-day-font1" in error for error in errors))
        self.assertTrue(any("missing scenario labels: phone-landscape-night-font13" in error for error in errors))

    def test_scenarios_reject_unknown_labels(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        scenarios.append(scenario("unexpected-scenario"))

        self.assertEqual(
            collector.scenario_label_errors(scenarios),
            ["unknown scenario labels: unexpected-scenario"],
        )

    def test_scenario_without_label_key_reported_as_unknown(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        del scenarios[0]["label"]

        errors = collector.scenario_label_errors(scenarios)

        self.assertIn("unknown scenario labels: <unknown>", errors)

    def test_zero_present_xml_fails_semantic_coverage(self) -> None:
        errors = collector.xml_coverage_errors(current_scenarios())

        self.assertTrue(any("below minimum: 0/2" in error for error in errors))
        self.assertTrue(any("phone-portrait-day-font1" in error for error in errors))
        self.assertTrue(any("phone-portrait-night-font1" in error for error in errors))

    def test_one_present_xml_fails_semantic_coverage(self) -> None:
        errors = collector.xml_coverage_errors(
            current_scenarios("phone-portrait-day-font1")
        )

        self.assertTrue(any("below minimum: 1/2" in error for error in errors))
        self.assertTrue(any("phone-portrait-night-font1" in error for error in errors))

    def test_required_default_portrait_xml_pair_passes(self) -> None:
        errors = collector.xml_coverage_errors(
            current_scenarios(
                "phone-portrait-day-font1",
                "phone-portrait-night-font1",
            )
        )

        self.assertEqual(errors, [])

    def test_rejected_xml_fails_even_with_required_pair_present(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        scenarios[2]["xml_status"] = "rejected"

        errors = collector.xml_coverage_errors(scenarios)

        self.assertTrue(any("XML rejected for: phone-portrait-day-font13" in error for error in errors))

    def test_rejected_xml_fails_without_requiring_xml_errors_shape(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        scenarios[2]["xml_status"] = "rejected"
        del scenarios[2]["xml_errors"]

        errors = collector.xml_coverage_errors(scenarios)

        self.assertTrue(any("XML rejected for: phone-portrait-day-font13" in error for error in errors))

    def test_unknown_xml_status_fails(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        scenarios[2]["xml_status"] = "skipped"

        errors = collector.xml_coverage_errors(scenarios)

        self.assertTrue(any("phone-portrait-day-font13='skipped'" in error for error in errors))

    def test_present_xml_with_errors_fails(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        scenarios[0]["xml_errors"] = ["missing USB"]

        errors = collector.xml_coverage_errors(scenarios)

        self.assertTrue(any("present XML has validation errors: phone-portrait-day-font1" in error for error in errors))

    def test_present_xml_requires_xml_errors_key(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        del scenarios[0]["xml_errors"]

        errors = collector.xml_coverage_errors(scenarios)

        self.assertIn("present XML missing xml_errors: phone-portrait-day-font1", errors)

    def test_present_xml_requires_xml_errors_list(self) -> None:
        for value in ("missing USB", {"error": "missing USB"}, 1, None):
            with self.subTest(value=value):
                scenarios = current_scenarios(
                    "phone-portrait-day-font1",
                    "phone-portrait-night-font1",
                )
                scenarios[0]["xml_errors"] = value

                errors = collector.xml_coverage_errors(scenarios)

                self.assertIn(
                    f"present XML xml_errors must be a list: phone-portrait-day-font1={type(value).__name__}",
                    errors,
                )

    def test_restored_gate_rejects_missing_required_keys(self) -> None:
        errors = collector.restored_gate_errors({})

        self.assertTrue(any("missing restored keys: font_scale_1_0" in error for error in errors))
        self.assertTrue(any("restored.packages_stopped is not verified true: None" in error for error in errors))

    def test_restored_wrong_type_fails_without_traceback(self) -> None:
        for value in (None, [], "restored", 1):
            with self.subTest(value=value):
                self.assertEqual(
                    collector.restored_gate_errors(value),
                    [f"restored must be an object: {type(value).__name__}"],
                )

    def test_missing_restored_key_fails_restored_gate(self) -> None:
        summary = valid_summary()
        del summary["restored"]

        errors = collector.summary_gate_errors(summary)

        self.assertTrue(any(error.startswith("missing restored keys:") for error in errors))

    def test_restored_gate_rejects_non_true_for_each_required_key(self) -> None:
        for key in collector.REQUIRED_RESTORE_KEYS:
            with self.subTest(key=key):
                restored = valid_restored()
                restored[key] = False

                self.assertIn(
                    f"restored.{key} is not verified true: False",
                    collector.restored_gate_errors(restored),
                )

    def test_restored_gate_rejects_unknown_keys(self) -> None:
        restored = valid_restored()
        restored["unexpected"] = True

        self.assertEqual(
            collector.restored_gate_errors(restored),
            ["unknown restored keys: unexpected"],
        )

    def test_restored_gate_rejects_non_true_package_stop_status(self) -> None:
        restored = {
            "font_scale_1_0": True,
            "night_no": True,
            "rotation_0": True,
            "accelerometer_rotation_0": True,
            "no_override_size": True,
            "packages_stopped": "not_reverified",
        }

        self.assertTrue(all(restored.values()))
        self.assertEqual(
            collector.restored_gate_errors(restored),
            ["restored.packages_stopped is not verified true: 'not_reverified'"],
        )

    def test_current_validation_passes_after_cleanup_reverification(self) -> None:
        validation = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))

        self.assertIs(validation["restored"]["packages_stopped"], True)
        self.assertEqual(collector.summary_gate_errors(validation), [])

    def test_offline_package_stop_without_runtime_evidence_fails_closed(self) -> None:
        summary = valid_summary()
        summary["restored"]["packages_stopped"] = False

        self.assertIn(
            "restored.packages_stopped is not verified true: False",
            collector.summary_gate_errors(summary),
        )


if __name__ == "__main__":
    unittest.main()
