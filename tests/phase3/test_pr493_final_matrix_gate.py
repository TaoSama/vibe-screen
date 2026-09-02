from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
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
DEVICE_IDENTITY_PATH = VALIDATION_PATH.parent / "device-identity.txt"

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
        "xml_stable_state": False,
    }


def current_scenarios(*present_labels: str) -> list[dict[str, object]]:
    present = set(present_labels)
    return [
        scenario(label, "present" if label in present else "unavailable")
        for label, *_ in collector.SCENARIOS
    ]


def valid_restored() -> dict[str, bool]:
    return {key: True for key in collector.REQUIRED_RESTORE_KEYS}


def valid_instrumentation_cleanup() -> dict[str, object]:
    return {
        "schema": "dev.vibescreen.android-instrumentation-cleanup/v1",
        "package_name": collector.TEST_PACKAGE,
        "started_at_utc": "2026-09-02T00:00:00+00:00",
        "finished_at_utc": "2026-09-02T00:00:01+00:00",
        "force_stop_ok": True,
        "uninstall_ok": True,
        "package_absent_after_cleanup": True,
        "cleanup_scope": {
            "target": "instrumentation_test_package",
            "product_package": "not_targeted",
            "product_data": "not_targeted",
            "adb_reverse": "not_targeted",
        },
        "ok": True,
        "commands": [
            {
                "name": "force_stop_test_package",
                "package_name": collector.TEST_PACKAGE,
                "command": ["shell", "am", "force-stop", collector.TEST_PACKAGE],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            },
            {
                "name": "uninstall_test_package",
                "package_name": collector.TEST_PACKAGE,
                "command": ["uninstall", collector.TEST_PACKAGE],
                "returncode": 0,
                "stdout": "Success\n",
                "stderr": "",
            },
            {
                "name": "verify_test_package_absent",
                "package_name": collector.TEST_PACKAGE,
                "command": ["shell", "pm", "list", "packages", collector.TEST_PACKAGE],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            },
        ],
    }


def valid_summary() -> dict[str, object]:
    return {
        "apk_sha256": collector.EXPECTED_APK_SHA256,
        "android_test_apk_sha256": collector.EXPECTED_ANDROID_TEST_APK_SHA256,
        "device": dict(collector.EXPECTED_DEVICE_IDENTITY),
        "device_identity_evidence": collector.EXPECTED_DEVICE_IDENTITY_EVIDENCE,
        "xml_evidence_scope": collector.EXPECTED_XML_SEMANTIC_EVIDENCE_SCOPE,
        "instrumentation_p0110_landscape_large_text": True,
        "scenarios": current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        ),
        "restored": valid_restored(),
        "android_instrumentation_cleanup": valid_instrumentation_cleanup(),
    }


class FakeXmlDumpSession:
    def __init__(
        self,
        *,
        dump_results: list[dict[str, object]],
        stat_results: list[tuple[int | None, str]],
        device_epochs: list[int],
        validate_results: list[list[str]] | None = None,
    ) -> None:
        self.dump_results = dump_results
        self.stat_results = stat_results
        self.device_epochs = device_epochs
        self.validate_results = validate_results or []
        self.calls: list[tuple[str, ...]] = []
        self.pull_calls: list[tuple[str, ...]] = []
        self.sleep_delays: list[float] = []
        self._active_dump: dict[str, object] | None = None

    def adb(self, serial: str, *args: str) -> subprocess.CompletedProcess[str]:
        del serial
        self.calls.append(args)
        if args[:3] == ("shell", "rm", "-f"):
            return self._proc(args, 0, "", "")
        if args[:3] == ("shell", "uiautomator", "dump"):
            if not self.dump_results:
                raise AssertionError("unexpected uiautomator dump call")
            self._active_dump = self.dump_results.pop(0)
            return self._proc(
                args,
                int(self._active_dump.get("returncode", 0)),
                str(self._active_dump.get("stdout", "UI hierarchy dumped to remote.xml\n")),
                str(self._active_dump.get("stderr", "")),
            )
        if args[:1] == ("pull",):
            self.pull_calls.append(args)
            active_dump = self._active_dump or {}
            returncode = int(active_dump.get("pull_returncode", 0))
            if returncode == 0 and bool(active_dump.get("write_xml", True)):
                destination = Path(args[2])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(str(active_dump.get("xml", "<hierarchy />\n")), encoding="utf-8")
            return self._proc(args, returncode, str(active_dump.get("pull_stdout", "pulled\n")), "")
        raise AssertionError(f"unexpected adb call: {args}")

    def device_epoch(self, serial: str) -> int:
        del serial
        if not self.device_epochs:
            raise AssertionError("unexpected device clock read")
        return self.device_epochs.pop(0)

    def remote_mtime(self, serial: str, remote_xml: str) -> tuple[int | None, str]:
        del serial, remote_xml
        if not self.stat_results:
            raise AssertionError("unexpected remote mtime read")
        return self.stat_results.pop(0)

    def validate(self, local_xml: Path) -> list[str]:
        if not local_xml.exists():
            raise AssertionError("validator received a missing XML file")
        if not self.validate_results:
            return []
        return self.validate_results.pop(0)

    def sleep(self, delay: float) -> None:
        self.sleep_delays.append(delay)

    @staticmethod
    def _proc(args: tuple[str, ...], returncode: int, stdout: str, stderr: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(args), returncode, stdout, stderr)


class FakeDeviceIdentitySession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.outputs = {
            ("devices",): "List of devices attached\nserial-1\tdevice\n",
            ("shell", "getprop", "ro.product.manufacturer"): "nubia\n",
            ("shell", "getprop", "ro.product.model"): "P0110\n",
            ("shell", "getprop", "ro.product.device"): "pacific\n",
            ("shell", "getprop", "ro.product.vendor.device"): "pacific\n",
            ("shell", "getprop", "ro.build.product"): "qssi_64\n",
            ("shell", "getprop", "ro.build.version.release"): "16\n",
            ("shell", "getprop", "ro.build.version.sdk"): "36\n",
        }

    def adb_text(self, serial: str, *args: str, description: str | None = None) -> str:
        del serial, description
        self.calls.append(args)
        return self.outputs[args]


def capture_xml_with_fake(fake: FakeXmlDumpSession, tmp_path: Path, *, attempts_per_mode: int = 2) -> tuple[str, list[str], Path, Path]:
    metadata = tmp_path / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    local_xml = metadata / "scenario.xml"
    status, errors = collector.capture_ui_xml(
        "serial-1",
        metadata,
        "scenario",
        "/sdcard/scenario.xml",
        local_xml,
        attempts_per_mode=attempts_per_mode,
        retry_delay_seconds=0.25,
        adb_func=fake.adb,
        device_epoch_func=fake.device_epoch,
        remote_mtime_func=fake.remote_mtime,
        validate_func=fake.validate,
        sleep_func=fake.sleep,
    )
    return status, errors, local_xml, metadata / "scenario.pull-xml.txt"


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
            ("device_identity_evidence", "device_identity_evidence mismatch: 'tampered'"),
            ("xml_evidence_scope", "xml_evidence_scope mismatch: 'tampered'"),
        ):
            with self.subTest(key=key):
                summary = valid_summary()
                summary[key] = "tampered"

                self.assertIn(expected, collector.summary_gate_errors(summary))

    def test_device_identity_mismatch_fails_for_each_required_field(self) -> None:
        for key in collector.EXPECTED_DEVICE_IDENTITY:
            with self.subTest(key=key):
                summary = valid_summary()
                summary["device"][key] = "tampered"

                errors = collector.summary_gate_errors(summary)

                if key == "adb_serial":
                    self.assertIn("device.adb_serial must be redacted: 'tampered'", errors)
                else:
                    self.assertIn(f"device.{key} mismatch: 'tampered'", errors)

    def test_identity_fields_missing_and_non_string_types_fail(self) -> None:
        for key, expected_prefix in (
            ("apk_sha256", "apk_sha256 mismatch"),
            ("android_test_apk_sha256", "android_test_apk_sha256 mismatch"),
            ("device_identity_evidence", "device_identity_evidence mismatch"),
            ("xml_evidence_scope", "xml_evidence_scope mismatch"),
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

    def test_device_identity_missing_and_non_string_types_fail(self) -> None:
        for value in (None, [], "device", 1):
            with self.subTest(value=value):
                summary = valid_summary()
                summary["device"] = value

                self.assertIn(
                    f"device must be an object: {type(value).__name__}",
                    collector.summary_gate_errors(summary),
                )

        for key in collector.EXPECTED_DEVICE_IDENTITY:
            with self.subTest(key=key, variant="missing"):
                summary = valid_summary()
                del summary["device"][key]

                self.assertTrue(
                    any(error.startswith(f"device.{key}") for error in collector.summary_gate_errors(summary))
                )

            with self.subTest(key=key, variant="non-string"):
                summary = valid_summary()
                summary["device"][key] = 1

                self.assertTrue(
                    any(error.startswith(f"device.{key}") for error in collector.summary_gate_errors(summary))
                )

    def test_device_identity_requires_redacted_serial(self) -> None:
        summary = valid_summary()
        summary["device"]["adb_serial"] = "unredacted-adb-serial-example"

        self.assertIn(
            "device.adb_serial must be redacted: 'unredacted-adb-serial-example'",
            collector.summary_gate_errors(summary),
        )

    def test_collect_device_identity_writes_detailed_redacted_transcript(self) -> None:
        fake = FakeDeviceIdentitySession()
        with tempfile.TemporaryDirectory() as tmp_dir:
            metadata = Path(tmp_dir) / "metadata"
            identity = collector.collect_device_identity(
                "serial-1",
                metadata,
                adb_text_func=fake.adb_text,
            )
            transcript = (metadata / "device-identity.txt").read_text(encoding="utf-8")

        self.assertEqual(collector.public_device_identity(identity), collector.EXPECTED_DEVICE_IDENTITY)
        self.assertEqual(
            fake.calls,
            [
                ("devices",),
                ("shell", "getprop", "ro.product.manufacturer"),
                ("shell", "getprop", "ro.product.model"),
                ("shell", "getprop", "ro.product.device"),
                ("shell", "getprop", "ro.product.vendor.device"),
                ("shell", "getprop", "ro.build.product"),
                ("shell", "getprop", "ro.build.version.release"),
                ("shell", "getprop", "ro.build.version.sdk"),
            ],
        )
        self.assertIn("adb devices\nList of devices attached\n<redacted-adb-serial>\tdevice", transcript)
        self.assertIn("adb -s <redacted-adb-serial> shell getprop ro.product.manufacturer\nnubia", transcript)
        self.assertIn("adb -s <redacted-adb-serial> shell getprop ro.build.version.sdk\n36", transcript)
        self.assertNotIn("serial-1", transcript)
        self.assertNotIn("ro.product.manufacturer=nubia", transcript)

    def test_redact_normalizes_local_adb_binary_paths(self) -> None:
        raw = "command=/Users/example/Library/Android/sdk/platform-tools/adb -s serial-1 reverse --list\n"

        self.assertEqual(
            collector.redact(raw, "serial-1"),
            "command=adb -s <redacted-adb-serial> reverse --list\n",
        )

    def test_final_cleanup_preserves_original_failure(self) -> None:
        original_restore = collector.restore_device
        original_force_stop = collector.force_stop_apps
        original_cleanup_test_package = collector.cleanup_instrumentation_test_package
        original_assert_stopped = collector.assert_packages_stopped
        calls: list[str] = []

        def failing_restore(serial: str) -> None:
            calls.append(f"restore:{serial}")
            raise RuntimeError("restore failed")

        def failing_assert_stopped(serial: str) -> None:
            calls.append(f"pidof:{serial}")
            raise RuntimeError("pidof failed")

        try:
            collector.restore_device = failing_restore
            collector.force_stop_apps = lambda serial: calls.append(f"force-stop:{serial}")
            collector.cleanup_instrumentation_test_package = lambda serial, metadata: calls.append(f"cleanup-test:{serial}")
            collector.assert_packages_stopped = failing_assert_stopped
            with tempfile.TemporaryDirectory() as tmp_dir:
                log_file = Path(tmp_dir) / "run.log"
                metadata = Path(tmp_dir) / "metadata"

                collector.run_final_cleanup(
                    "serial-1",
                    log_file,
                    original_failure=RuntimeError("primary failed"),
                    metadata_dir=metadata,
                )

                self.assertEqual(
                    calls,
                    ["restore:serial-1", "force-stop:serial-1", "cleanup-test:serial-1", "pidof:serial-1"],
                )
                log_text = log_file.read_text(encoding="utf-8")
                self.assertIn("cleanup step restore_device failed: restore failed", log_text)
                self.assertIn("cleanup step assert_packages_stopped failed: pidof failed", log_text)
        finally:
            collector.restore_device = original_restore
            collector.force_stop_apps = original_force_stop
            collector.cleanup_instrumentation_test_package = original_cleanup_test_package
            collector.assert_packages_stopped = original_assert_stopped

    def test_final_cleanup_raises_cleanup_failure_without_original_failure(self) -> None:
        original_restore = collector.restore_device
        original_force_stop = collector.force_stop_apps
        original_cleanup_test_package = collector.cleanup_instrumentation_test_package
        original_assert_stopped = collector.assert_packages_stopped
        calls: list[str] = []

        def failing_restore(serial: str) -> None:
            calls.append(f"restore:{serial}")
            raise RuntimeError("restore failed")

        def passing_force_stop(serial: str) -> None:
            calls.append(f"force-stop:{serial}")

        def failing_assert_stopped(serial: str) -> None:
            calls.append(f"pidof:{serial}")
            raise RuntimeError("pidof failed")

        try:
            collector.restore_device = failing_restore
            collector.force_stop_apps = passing_force_stop
            collector.cleanup_instrumentation_test_package = lambda serial, metadata: calls.append(f"cleanup-test:{serial}")
            collector.assert_packages_stopped = failing_assert_stopped
            with tempfile.TemporaryDirectory() as tmp_dir:
                log_file = Path(tmp_dir) / "run.log"

                with self.assertRaisesRegex(RuntimeError, "restore failed"):
                    collector.run_final_cleanup("serial-1", log_file)

                self.assertEqual(
                    calls,
                    ["restore:serial-1", "force-stop:serial-1", "cleanup-test:serial-1", "pidof:serial-1"],
                )
                log_text = log_file.read_text(encoding="utf-8")
                self.assertIn("cleanup step restore_device failed: restore failed", log_text)
                self.assertIn("cleanup step assert_packages_stopped failed: pidof failed", log_text)
        finally:
            collector.restore_device = original_restore
            collector.force_stop_apps = original_force_stop
            collector.cleanup_instrumentation_test_package = original_cleanup_test_package
            collector.assert_packages_stopped = original_assert_stopped

    def test_summary_requires_successful_android_instrumentation_cleanup(self) -> None:
        summary = valid_summary()
        summary["android_instrumentation_cleanup"] = {
            **valid_instrumentation_cleanup(),
            "package_absent_after_cleanup": False,
            "ok": False,
        }

        errors = collector.summary_gate_errors(summary)

        self.assertIn("android_instrumentation_cleanup.ok is not verified true: False", errors)
        self.assertIn(
            "android_instrumentation_cleanup.package_absent_after_cleanup is not verified true: False",
            errors,
        )

    def test_summary_rejects_android_instrumentation_cleanup_scope_drift(self) -> None:
        summary = valid_summary()
        cleanup = valid_instrumentation_cleanup()
        cleanup["cleanup_scope"] = {
            "target": "instrumentation_test_package",
            "product_package": "not_targeted",
            "product_data": "not_targeted",
            "adb_reverse": "modified",
        }
        summary["android_instrumentation_cleanup"] = cleanup

        errors = collector.summary_gate_errors(summary)

        self.assertTrue(
            any(error.startswith("android_instrumentation_cleanup.cleanup_scope mismatch") for error in errors)
        )

    def test_summary_rejects_android_instrumentation_cleanup_command_drift(self) -> None:
        summary = valid_summary()
        cleanup = valid_instrumentation_cleanup()
        cleanup["commands"][1]["command"] = ["uninstall", collector.PACKAGE]
        summary["android_instrumentation_cleanup"] = cleanup

        errors = collector.summary_gate_errors(summary)

        self.assertIn("android_instrumentation_cleanup.commands[1].command mismatch: ['uninstall', 'dev.telemachus.display']", errors)

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

    def test_required_default_portrait_xml_pair_passes_even_when_not_stable_state(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        scenarios[0]["xml_stable_state"] = False
        scenarios[1]["xml_stable_state"] = False

        self.assertEqual(collector.xml_coverage_errors(scenarios), [])

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

    def test_present_xml_requires_xml_stable_state_key(self) -> None:
        scenarios = current_scenarios(
            "phone-portrait-day-font1",
            "phone-portrait-night-font1",
        )
        del scenarios[0]["xml_stable_state"]

        errors = collector.xml_coverage_errors(scenarios)

        self.assertIn("present XML missing xml_stable_state: phone-portrait-day-font1", errors)

    def test_present_xml_requires_xml_stable_state_bool(self) -> None:
        for value in ("false", 0, [], None):
            with self.subTest(value=value):
                scenarios = current_scenarios(
                    "phone-portrait-day-font1",
                    "phone-portrait-night-font1",
                )
                scenarios[0]["xml_stable_state"] = value

                errors = collector.xml_coverage_errors(scenarios)

                self.assertIn(
                    f"present XML xml_stable_state must be a bool: phone-portrait-day-font1={type(value).__name__}",
                    errors,
                )

    def test_xml_stable_state_detects_progress_error_overlap(self) -> None:
        transient_xml = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node resource-id="dev.telemachus.display:id/connectionProgress" text="" bounds="[1,1][10,10]" />
  <node resource-id="dev.telemachus.display:id/connectButton" text="TRY AGAIN" bounds="[1,20][10,30]" />
</hierarchy>
"""
        stable_error_xml = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node resource-id="dev.telemachus.display:id/connectionProgress" text="" bounds="[0,0][0,0]" />
  <node resource-id="dev.telemachus.display:id/connectButton" text="TRY AGAIN" bounds="[1,20][10,30]" />
</hierarchy>
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            transient = Path(tmp_dir) / "transient.xml"
            stable_error = Path(tmp_dir) / "stable-error.xml"
            transient.write_text(transient_xml, encoding="utf-8")
            stable_error.write_text(stable_error_xml, encoding="utf-8")

            self.assertFalse(collector.is_xml_stable_state(transient))
            self.assertTrue(collector.is_xml_stable_state(stable_error))

    def test_current_retained_portrait_xml_is_marked_non_stable(self) -> None:
        metadata = VALIDATION_PATH.parent

        self.assertFalse(collector.is_xml_stable_state(metadata / "phone-portrait-day-font1.xml"))
        self.assertFalse(collector.is_xml_stable_state(metadata / "phone-portrait-night-font1.xml"))

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
        self.assertNotIn("device_model", validation)
        self.assertEqual(validation["device"], collector.EXPECTED_DEVICE_IDENTITY)
        self.assertEqual(validation["device_identity_evidence"], collector.EXPECTED_DEVICE_IDENTITY_EVIDENCE)
        self.assertEqual(validation["xml_evidence_scope"], collector.EXPECTED_XML_SEMANTIC_EVIDENCE_SCOPE)
        self.assertEqual(collector.summary_gate_errors(validation), [])

    def test_retained_device_identity_evidence_uses_collector_transcript_format(self) -> None:
        evidence = DEVICE_IDENTITY_PATH.read_text(encoding="utf-8")

        self.assertIn("Android device identity from independent read-only adb commands", evidence)
        self.assertIn("adb devices\nList of devices attached\n<redacted-adb-serial>\tdevice", evidence)
        for prop, expected in (
            ("ro.product.manufacturer", "nubia"),
            ("ro.product.model", "P0110"),
            ("ro.product.device", "pacific"),
            ("ro.product.vendor.device", "pacific"),
            ("ro.build.product", "qssi_64"),
            ("ro.build.version.release", "16"),
            ("ro.build.version.sdk", "36"),
        ):
            with self.subTest(prop=prop):
                self.assertIn(f"adb -s <redacted-adb-serial> shell getprop {prop}\n{expected}", evidence)
        self.assertNotIn("unredacted-adb-serial-example", evidence)

    def test_offline_package_stop_without_runtime_evidence_fails_closed(self) -> None:
        summary = valid_summary()
        summary["restored"]["packages_stopped"] = False

        self.assertIn(
            "restored.packages_stopped is not verified true: False",
            collector.summary_gate_errors(summary),
        )

    def test_capture_ui_xml_retries_normal_and_accepts_same_second_fresh_xml(self) -> None:
        fake = FakeXmlDumpSession(
            dump_results=[
                {"stdout": "ERROR: could not get idle\n"},
                {"stdout": "UI hierarchy dumped to /sdcard/scenario.xml\n"},
            ],
            stat_results=[
                (None, "stat: missing\n"),
                (None, "stat: missing\n"),
                (None, "stat: missing\n"),
                (100, "100\n"),
            ],
            device_epochs=[100, 100],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            status, errors, local_xml, evidence_path = capture_xml_with_fake(fake, Path(tmp_dir))
            local_xml_exists = local_xml.exists()
            evidence = evidence_path.read_text(encoding="utf-8")

        dump_calls = [call for call in fake.calls if call[:3] == ("shell", "uiautomator", "dump")]
        self.assertEqual(status, "present")
        self.assertEqual(errors, [])
        self.assertTrue(local_xml_exists)
        self.assertEqual(dump_calls, [("shell", "uiautomator", "dump", "/sdcard/scenario.xml")] * 2)
        self.assertIn("attempt=1", evidence)
        self.assertIn("result=dump_invalid", evidence)
        self.assertIn("attempt=2", evidence)
        self.assertIn("post_dump_remote_mtime=100", evidence)
        self.assertIn("remote_fresh=true", evidence)
        self.assertIn("result=present", evidence)

    def test_capture_ui_xml_tries_compressed_after_normal_attempts_fail(self) -> None:
        fake = FakeXmlDumpSession(
            dump_results=[
                {"stdout": "ERROR: first normal failure\n"},
                {"returncode": 1, "stderr": "second normal failure\n"},
                {"stdout": "UI hierarchy dumped to /sdcard/scenario.xml\n"},
            ],
            stat_results=[
                (None, "stat: missing\n"),
                (None, "stat: missing\n"),
                (None, "stat: missing\n"),
                (None, "stat: missing\n"),
                (None, "stat: missing\n"),
                (201, "201\n"),
            ],
            device_epochs=[200, 200, 201],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            status, errors, _, evidence_path = capture_xml_with_fake(fake, Path(tmp_dir))
            evidence = evidence_path.read_text(encoding="utf-8")

        dump_calls = [call for call in fake.calls if call[:3] == ("shell", "uiautomator", "dump")]
        self.assertEqual(status, "present")
        self.assertEqual(errors, [])
        self.assertEqual(dump_calls[2], ("shell", "uiautomator", "dump", "--compressed", "/sdcard/scenario.xml"))
        self.assertIn("mode=compressed", evidence)
        self.assertIn("result=present", evidence)

    def test_capture_ui_xml_does_not_pull_stale_remote_xml(self) -> None:
        fake = FakeXmlDumpSession(
            dump_results=[
                {"stdout": "UI hierarchy dumped to /sdcard/scenario.xml\n"},
                {"stdout": "UI hierarchy dumped to /sdcard/scenario.xml\n"},
            ],
            stat_results=[
                (None, "stat: missing\n"),
                (199, "199\n"),
                (None, "stat: missing\n"),
                (209, "209\n"),
            ],
            device_epochs=[200, 210],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            status, errors, local_xml, evidence_path = capture_xml_with_fake(fake, Path(tmp_dir), attempts_per_mode=1)
            local_xml_exists = local_xml.exists()
            evidence = evidence_path.read_text(encoding="utf-8")

        self.assertEqual(status, "unavailable")
        self.assertEqual(errors, [])
        self.assertEqual(fake.pull_calls, [])
        self.assertFalse(local_xml_exists)
        self.assertIn("remote_fresh=false", evidence)
        self.assertIn("final_status=unavailable", evidence)

    def test_capture_ui_xml_continues_after_rejected_xml_and_accepts_later_valid_xml(self) -> None:
        fake = FakeXmlDumpSession(
            dump_results=[
                {"stdout": "UI hierarchy dumped to /sdcard/scenario.xml\n"},
                {"stdout": "UI hierarchy dumped to /sdcard/scenario.xml\n"},
            ],
            stat_results=[
                (None, "stat: missing\n"),
                (300, "300\n"),
                (None, "stat: missing\n"),
                (301, "301\n"),
            ],
            device_epochs=[300, 301],
            validate_results=[["missing USB"], []],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            status, errors, local_xml, evidence_path = capture_xml_with_fake(fake, Path(tmp_dir))
            local_xml_exists = local_xml.exists()
            evidence = evidence_path.read_text(encoding="utf-8")

        self.assertEqual(status, "present")
        self.assertEqual(errors, [])
        self.assertTrue(local_xml_exists)
        self.assertIn("result=rejected", evidence)
        self.assertIn("xml_errors=missing USB", evidence)
        self.assertIn("result=present", evidence)

    def test_capture_ui_xml_returns_rejected_when_no_later_valid_xml_is_accepted(self) -> None:
        fake = FakeXmlDumpSession(
            dump_results=[
                {"stdout": "UI hierarchy dumped to /sdcard/scenario.xml\n"},
                {"stdout": "ERROR: compressed failed\n"},
            ],
            stat_results=[
                (None, "stat: missing\n"),
                (400, "400\n"),
                (None, "stat: missing\n"),
                (None, "stat: missing\n"),
            ],
            device_epochs=[400, 401],
            validate_results=[["missing USB"]],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            status, errors, local_xml, evidence_path = capture_xml_with_fake(fake, Path(tmp_dir), attempts_per_mode=1)
            local_xml_exists = local_xml.exists()
            evidence = evidence_path.read_text(encoding="utf-8")

        self.assertEqual(status, "rejected")
        self.assertEqual(errors, ["missing USB"])
        self.assertFalse(local_xml_exists)
        self.assertIn("final_status=rejected", evidence)
        self.assertIn("fresh XML was captured but rejected; no later valid XML was accepted", evidence)

    def test_capture_ui_xml_returns_all_rejected_errors_when_no_valid_xml_is_accepted(self) -> None:
        fake = FakeXmlDumpSession(
            dump_results=[
                {"stdout": "UI hierarchy dumped to /sdcard/scenario.xml\n"},
                {"stdout": "UI hierarchy dumped to /sdcard/scenario.xml\n"},
            ],
            stat_results=[
                (None, "stat: missing\n"),
                (500, "500\n"),
                (None, "stat: missing\n"),
                (501, "501\n"),
            ],
            device_epochs=[500, 501],
            validate_results=[["missing USB"], ["missing retry action"]],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            status, errors, local_xml, evidence_path = capture_xml_with_fake(fake, Path(tmp_dir), attempts_per_mode=1)
            local_xml_exists = local_xml.exists()
            evidence = evidence_path.read_text(encoding="utf-8")

        self.assertEqual(status, "rejected")
        self.assertEqual(errors, ["missing USB", "missing retry action"])
        self.assertFalse(local_xml_exists)
        self.assertIn("xml_errors=missing USB", evidence)
        self.assertIn("xml_errors=missing retry action", evidence)
        self.assertIn("final_xml_errors=missing USB; missing retry action", evidence)

    def test_capture_ui_xml_fails_when_remote_delete_leaves_file_behind(self) -> None:
        fake = FakeXmlDumpSession(
            dump_results=[],
            stat_results=[(499, "499\n")],
            device_epochs=[],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            metadata = Path(tmp_dir) / "metadata"
            local_xml = metadata / "scenario.xml"
            with self.assertRaisesRegex(RuntimeError, "remote XML remained after delete"):
                collector.capture_ui_xml(
                    "serial-1",
                    metadata,
                    "scenario",
                    "/sdcard/scenario.xml",
                    local_xml,
                    attempts_per_mode=1,
                    adb_func=fake.adb,
                    device_epoch_func=fake.device_epoch,
                    remote_mtime_func=fake.remote_mtime,
                    validate_func=fake.validate,
                    sleep_func=fake.sleep,
                )

            evidence = (metadata / "scenario.pull-xml.txt").read_text(encoding="utf-8")
            self.assertIn("pre_dump_remote_mtime=499", evidence)
            self.assertIn("result=remote_delete_left_file", evidence)

    def test_capture_ui_xml_rejects_non_positive_attempt_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaisesRegex(ValueError, "attempts_per_mode must be positive"):
                collector.capture_ui_xml(
                    "serial-1",
                    Path(tmp_dir) / "metadata",
                    "scenario",
                    "/sdcard/scenario.xml",
                    Path(tmp_dir) / "metadata" / "scenario.xml",
                    attempts_per_mode=0,
                )


if __name__ == "__main__":
    unittest.main()
