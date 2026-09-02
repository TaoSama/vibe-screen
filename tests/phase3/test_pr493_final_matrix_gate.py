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


class PR493FinalMatrixGateTests(unittest.TestCase):
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
                "restored": {key: True for key in collector.REQUIRED_RESTORE_KEYS},
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
                "restored": {key: True for key in collector.REQUIRED_RESTORE_KEYS},
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

    def test_restored_gate_rejects_missing_required_keys(self) -> None:
        errors = collector.restored_gate_errors({})

        self.assertTrue(any("missing restored keys: font_scale_1_0" in error for error in errors))
        self.assertTrue(any("restored.packages_stopped is not verified true: None" in error for error in errors))

    def test_restored_gate_rejects_unknown_keys(self) -> None:
        restored = {key: True for key in collector.REQUIRED_RESTORE_KEYS}
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

    def test_offline_validation_keeps_package_stop_fail_closed(self) -> None:
        validation = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))

        self.assertIs(validation["restored"]["packages_stopped"], False)
        self.assertFalse(all(validation["restored"].values()))


if __name__ == "__main__":
    unittest.main()
