from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import io
import json
import math
from pathlib import Path
import tempfile
import unittest

from tools.tests.test_soak_report import write_inputs
from vibescreen_evidence.soak_report import (
    PUBLICATION_PROFILE,
    PUBLIC_DERIVATION_ERROR_MESSAGE,
    PUBLIC_ERROR_DERIVATION_FAILED,
    PUBLIC_OUTPUT_ERROR_MESSAGE,
    derive_public_report,
    derive_report,
    main,
    write_public_report,
)


SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$defs",
        "$id",
        "$ref",
        "$schema",
        "additionalProperties",
        "const",
        "exclusiveMinimum",
        "format",
        "minimum",
        "oneOf",
        "properties",
        "required",
        "title",
        "type",
    }
)


def expected_public_failure() -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "soak_exact_window_report",
        "publication_profile": "privacy-minimized-v1",
        "derivation_status": "failed",
        "error_code": "evidence_derivation_failed",
    }


class SoakPublicReportTest(unittest.TestCase):
    def _assert_supported_schema_keywords(self, node, path="$"):
        unsupported = set(node) - SUPPORTED_SCHEMA_KEYWORDS
        self.assertFalse(
            unsupported,
            f"{path}: unsupported schema keywords {sorted(unsupported)}",
        )
        if "additionalProperties" in node:
            self.assertIsInstance(
                node["additionalProperties"],
                bool,
                f"{path}: additionalProperties only supports boolean values",
            )
        for name, child in node.get("$defs", {}).items():
            self._assert_supported_schema_keywords(child, f"{path}.$defs.{name}")
        for index, child in enumerate(node.get("oneOf", [])):
            self._assert_supported_schema_keywords(child, f"{path}.oneOf[{index}]")
        for name, child in node.get("properties", {}).items():
            self._assert_supported_schema_keywords(child, f"{path}.properties.{name}")

    def _matches_json_type(self, value, expected_type):
        matches = {
            "null": value is None,
            "object": isinstance(value, dict),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value)),
        }
        return matches.get(expected_type, False)

    def _assert_schema_node(self, value, node, root, path="$"):
        self._assert_supported_schema_keywords(node, path)
        if "$ref" in node:
            reference = node["$ref"]
            self.assertTrue(reference.startswith("#/$defs/"), reference)
            node = root["$defs"][reference.removeprefix("#/$defs/")]
            self._assert_supported_schema_keywords(node, path)
        if "oneOf" in node:
            candidates = [
                candidate
                for candidate in node["oneOf"]
                if self._matches_json_type(value, candidate.get("type"))
            ]
            self.assertEqual(len(candidates), 1, f"{path}: no unique oneOf branch")
            self._assert_schema_node(value, candidates[0], root, path)
            return
        if "const" in node:
            self.assertEqual(value, node["const"], path)
        expected_types = node.get("type")
        if expected_types is not None:
            if isinstance(expected_types, str):
                expected_types = [expected_types]
            self.assertTrue(
                any(self._matches_json_type(value, item) for item in expected_types),
                f"{path}: invalid type",
            )
        if "format" in node:
            self.assertEqual(node["format"], "date-time", f"{path}: unsupported format")
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            self.assertIsNotNone(parsed.tzinfo, path)
        if "minimum" in node:
            self.assertGreaterEqual(value, node["minimum"], path)
        if "exclusiveMinimum" in node:
            self.assertGreater(value, node["exclusiveMinimum"], path)
        if isinstance(value, dict):
            required = set(node.get("required", []))
            properties = node.get("properties", {})
            self.assertTrue(required.issubset(value), f"{path}: missing required keys")
            if node.get("additionalProperties") is False:
                self.assertEqual(set(value), set(properties), path)
            for name, child in value.items():
                if name in properties:
                    self._assert_schema_node(child, properties[name], root, f"{path}.{name}")

    def _assert_public_schema(self, instance):
        schema_path = Path(__file__).parents[1] / "schemas" / "soak-public-report.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self._assert_supported_schema_keywords(schema)
        branches = [
            branch
            for branch in schema["oneOf"]
            if branch["properties"]["derivation_status"]["const"]
            == instance.get("derivation_status")
        ]
        self.assertEqual(len(branches), 1)
        self._assert_schema_node(instance, branches[0], schema)

    def test_dependency_free_schema_validator_rejects_unknown_keywords(self):
        with self.assertRaisesRegex(AssertionError, "unsupported schema keywords"):
            self._assert_schema_node(
                None,
                {"type": "null", "unknownValidationKeyword": True},
                {},
                "$.fixture",
            )
        with self.assertRaisesRegex(AssertionError, "additionalProperties"):
            self._assert_schema_node(
                {},
                {
                    "type": "object",
                    "additionalProperties": {
                        "type": "string",
                        "unknownNestedKeyword": True,
                    },
                },
                {},
                "$.fixture",
            )

    def _assert_public_cli_failure(self, summary, samples, telemetry):
        output = summary.parent / "public-failure.json"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(
                [
                    "--summary", str(summary),
                    "--samples", str(samples),
                    "--host-telemetry", str(telemetry),
                    "--public-output", str(output),
                ]
            )
        persisted = json.loads(
            output.read_text(encoding="utf-8"),
            parse_constant=lambda value: self.fail(
                f"public JSON contains non-standard number {value}"
            ),
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), PUBLIC_DERIVATION_ERROR_MESSAGE + "\n")
        self.assertEqual(persisted, expected_public_failure())
        self.assertNotIn("Traceback", stderr.getvalue())
        diagnostics = stdout.getvalue() + stderr.getvalue() + json.dumps(persisted)
        self.assertNotIn(str(summary.parent), diagnostics)
        self.assertNotIn("preserved source warning", diagnostics)
        self._assert_public_schema(persisted)
        return persisted

    def test_public_writer_projects_internal_report_before_serializing(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            summary_record = json.loads(summary.read_text(encoding="utf-8"))
            summary_record["errors"] = []
            summary.write_text(json.dumps(summary_record), encoding="utf-8")
            internal = derive_report(summary, samples, telemetry)
            internal["private_extension"] = {
                "source_error": "private source error",
                "sensor": "private-sensor-orchid",
            }
            output = Path(raw_directory) / "public.json"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = write_public_report(output, internal)
            persisted = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(persisted["derivation_status"], "complete")
        self.assertNotIn("run_id", persisted)
        self.assertNotIn("errors", persisted)
        self.assertEqual(persisted["source_summary"], {"status": "complete"})
        self.assertNotIn("sensors_celsius", persisted["metrics"]["thermal"])
        encoded = json.dumps(persisted, allow_nan=False, sort_keys=True)
        for private_value in (
            "run-1",
            "private source error",
            "private-sensor-orchid",
            "private_extension",
        ):
            self.assertNotIn(private_value, encoded)
        self._assert_public_schema(persisted)

    def test_public_writer_rejects_public_like_input_with_fixed_failure(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            summary_record = json.loads(summary.read_text(encoding="utf-8"))
            summary_record["errors"] = []
            summary.write_text(json.dumps(summary_record), encoding="utf-8")
            public_like = derive_public_report(
                derive_report(summary, samples, telemetry)
            )
            public_like.update(
                {
                    "run_id": "private-run-id",
                    "errors": [],
                    "private_errors": ["private source error"],
                    "private_sensor": "private-sensor-name",
                }
            )
            output = Path(raw_directory) / "public.json"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = write_public_report(output, public_like)
            persisted = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), PUBLIC_DERIVATION_ERROR_MESSAGE + "\n")
        self.assertEqual(persisted, expected_public_failure())
        encoded = json.dumps(persisted, allow_nan=False, sort_keys=True)
        for private_value in (
            "private-run-id",
            "private source error",
            "private-sensor-name",
        ):
            self.assertNotIn(private_value, encoded)
        self._assert_public_schema(persisted)

    def test_public_cli_summary_contract_failures_are_fixed_and_private(self):
        cases = (
            ("schema_version", "vibescreen.evidence/v999"),
            ("kind", "input_latency"),
            ("run_id", ""),
            ("status", "unknown"),
        )
        for field, value in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as raw_dir:
                directory = Path(raw_dir) / "private-summary-source"
                directory.mkdir()
                summary, samples, telemetry = write_inputs(directory)
                record = json.loads(summary.read_text(encoding="utf-8"))
                record["errors"] = []
                record[field] = value
                summary.write_text(json.dumps(record), encoding="utf-8")
                self._assert_public_cli_failure(summary, samples, telemetry)

    def test_public_cli_sample_contract_failures_are_fixed_and_private(self):
        cases = (
            ("schema_version", lambda rows: rows[0].update(
                {"schema_version": "vibescreen.evidence/v999"})),
            ("run_id", lambda rows: rows[0].update({"run_id": "private-run"})),
            ("negative_index", lambda rows: rows[0].update({"sample_index": -1})),
            ("duplicate_index", lambda rows: rows[1].update({"sample_index": 0})),
            ("reverse_index", lambda rows: rows[2].update({"sample_index": 0})),
            ("negative_elapsed", lambda rows: rows[1].update(
                {"elapsed_seconds": -1})),
            ("decreasing_elapsed", lambda rows: rows[2].update(
                {"elapsed_seconds": 30})),
        )
        for name, mutate in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as raw_dir:
                directory = Path(raw_dir) / "private-sample-source"
                directory.mkdir()
                summary, samples, telemetry = write_inputs(directory)
                summary_record = json.loads(summary.read_text(encoding="utf-8"))
                summary_record["errors"] = []
                summary.write_text(json.dumps(summary_record), encoding="utf-8")
                rows = [
                    json.loads(line)
                    for line in samples.read_text(encoding="utf-8").splitlines()
                ]
                mutate(rows)
                samples.write_text(
                    "\n".join(json.dumps(row) for row in rows) + "\n",
                    encoding="utf-8",
                )
                self._assert_public_cli_failure(summary, samples, telemetry)

    def test_public_cli_telemetry_contract_failures_are_fixed_and_private(self):
        cases = (
            ("schema_version", lambda row: row.update({"schema_version": 2})),
            ("boolean_schema_version", lambda row: row.update(
                {"schema_version": True})),
            ("event", lambda row: row.update({"event": ""})),
            ("monotonic_ns", lambda row: row.update({"monotonic_ns": -1})),
            ("attributes", lambda row: row.update({"attributes": []})),
            ("session_epoch", lambda row: row.update({"session_epoch": -1})),
        )
        for name, mutate in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as raw_dir:
                directory = Path(raw_dir) / "private-telemetry-source"
                directory.mkdir()
                summary, samples, telemetry = write_inputs(directory)
                summary_record = json.loads(summary.read_text(encoding="utf-8"))
                summary_record["errors"] = []
                summary.write_text(json.dumps(summary_record), encoding="utf-8")
                records = [
                    json.loads(line)
                    for line in telemetry.read_text(encoding="utf-8").splitlines()
                ]
                mutate(records[1])
                telemetry.write_text(
                    "\n".join(json.dumps(record) for record in records) + "\n",
                    encoding="utf-8",
                )
                self._assert_public_cli_failure(summary, samples, telemetry)

    def test_public_cli_finite_overflow_is_fixed_and_private(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory) / "private-overflow-source"
            directory.mkdir()
            summary, samples, telemetry = write_inputs(directory)
            summary_record = json.loads(summary.read_text(encoding="utf-8"))
            summary_record["errors"] = []
            summary.write_text(json.dumps(summary_record), encoding="utf-8")
            records = [
                json.loads(line)
                for line in telemetry.read_text(encoding="utf-8").splitlines()
            ]
            records[1]["attributes"]["fps"] = 1e308
            records[3]["attributes"]["fps"] = 1e308
            telemetry.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            self._assert_public_cli_failure(summary, samples, telemetry)

    def test_non_standard_json_numbers_fail_closed_without_leaking(self):
        for token in ("NaN", "Infinity", "-Infinity", "1e309", "-1e309"):
            for source_name in ("summary", "samples", "telemetry"):
                with self.subTest(token=token, source=source_name), tempfile.TemporaryDirectory() as raw_dir:
                    directory = Path(raw_dir) / "fictional-private-source-731"
                    directory.mkdir()
                    summary, samples, telemetry = write_inputs(directory)
                    record = json.loads(summary.read_text(encoding="utf-8"))
                    record["errors"] = []
                    summary.write_text(json.dumps(record), encoding="utf-8")
                    if source_name == "summary":
                        record["unexpected_number"] = "NON_FINITE_PLACEHOLDER"
                        summary.write_text(
                            json.dumps(record).replace(
                                '"NON_FINITE_PLACEHOLDER"', token
                            ),
                            encoding="utf-8",
                        )
                    elif source_name == "samples":
                        lines = samples.read_text(encoding="utf-8").splitlines()
                        record = json.loads(lines[0])
                        record["host"]["rss_kb"] = "NON_FINITE_PLACEHOLDER"
                        lines[0] = json.dumps(record).replace(
                            '"NON_FINITE_PLACEHOLDER"', token
                        )
                        samples.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    else:
                        lines = telemetry.read_text(encoding="utf-8").splitlines()
                        record = json.loads(lines[1])
                        record["attributes"]["fps"] = "NON_FINITE_PLACEHOLDER"
                        lines[1] = json.dumps(record).replace(
                            '"NON_FINITE_PLACEHOLDER"', token
                        )
                        telemetry.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    persisted = self._assert_public_cli_failure(
                        summary, samples, telemetry
                    )
                    self.assertNotIn(
                        "fictional-private-source-731",
                        json.dumps(persisted, allow_nan=False),
                    )

    def test_public_projection_rejects_non_finite_numbers(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            record = json.loads(summary.read_text(encoding="utf-8"))
            record["errors"] = []
            summary.write_text(json.dumps(record), encoding="utf-8")
            report = derive_report(summary, samples, telemetry)

        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                report["metrics"]["stream"]["fps"]["mean"] = value
                public = derive_public_report(report)
                self.assertEqual(public, expected_public_failure())
                json.dumps(public, allow_nan=False)

    def test_public_report_has_exact_allowlisted_keys_and_normalized_dimensions(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            summary_record = json.loads(summary.read_text(encoding="utf-8"))
            summary_record["errors"] = []
            summary_record["started_at"] = " 2026-08-05T02:00:00+02:00 "
            summary_record["finished_at"] = " 2026-08-05T02:04:00+02:00 "
            summary.write_text(json.dumps(summary_record), encoding="utf-8")
            rows = [
                json.loads(line)
                for line in samples.read_text(encoding="utf-8").splitlines()
            ]
            for index, record in enumerate(rows):
                record["device"]["thermal"]["temperatures"].append(
                    {"name": "private-device-sensor-name", "celsius": 30.0 + index}
                )
                record["device"]["power"]["private_power_rail"] = index
            samples.write_text(
                "\n".join(json.dumps(record) for record in rows) + "\n",
                encoding="utf-8",
            )
            with telemetry.open("a", encoding="utf-8") as output:
                output.write(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "wall_time": "2026-08-05T00:03:45Z",
                            "monotonic_ns": 7,
                            "event": "private-device-event-name",
                            "attributes": {"private_path": "/Users/private/device"},
                        }
                    )
                    + "\n"
                )
            internal = derive_report(summary, samples, telemetry)
            public = derive_public_report(internal)
            internal["metrics"]["thermal"]["sensors_celsius"] = {}
            public_without_sensors = derive_public_report(internal)

        self.assertEqual(
            set(public),
            {
                "schema_version", "kind", "publication_profile",
                "derivation_status", "window", "source_summary",
                "metrics", "interpretation",
            },
        )
        self.assertEqual(public["publication_profile"], PUBLICATION_PROFILE)
        self.assertEqual(public["derivation_status"], "complete")
        self.assertEqual(public["source_summary"], {"status": "complete"})
        self.assertEqual(public["window"]["started_at"], "2026-08-05T00:00:00Z")
        self.assertEqual(public["window"]["finished_at"], "2026-08-05T00:04:00Z")
        self.assertEqual(
            set(public["metrics"]),
            {"stream", "telemetry", "memory_kib", "thermal", "battery"},
        )
        self.assertEqual(
            public["metrics"]["telemetry"]["event_counts"],
            {
                "session_admission_failed": 0,
                "session_admitted": 0,
                "session_disconnected": 0,
                "heartbeat_received": 2,
                "frame_queue_drop": 0,
                "stream_stats": 2,
            },
        )
        self.assertEqual(
            public["metrics"]["thermal"]["sensors_celsius_aggregate"],
            {"sensor_count": 2, "min": 30.0, "max": 40.0},
        )
        self.assertEqual(
            public_without_sensors["metrics"]["thermal"]["sensors_celsius_aggregate"],
            {"sensor_count": 0, "min": None, "max": None},
        )
        encoded = json.dumps(public, sort_keys=True)
        for private_value in ("private-device", "private_power_rail", "power", "run-1"):
            self.assertNotIn(private_value, encoded)
        self.assertEqual(public["metrics"]["battery"]["plugged"]["min"], 1.0)
        self.assertEqual(public["metrics"]["battery"]["status"]["max"], 2.0)
        self._assert_public_schema(public)

    def test_public_report_rejects_partial_and_source_errors_with_fixed_codes(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            report = derive_report(summary, samples, telemetry)
            failures = [derive_public_report(report)]
            report["source_summary"] = {"status": "partial", "errors": []}
            failures.append(derive_public_report(report))
            report["derivation_status"] = "partial"
            report["errors"] = ["private path /Users/private/device"]
            failures.append(derive_public_report(report))

        expected_keys = set(expected_public_failure())
        for failure in failures:
            self.assertEqual(set(failure), expected_keys)
            self.assertEqual(failure["error_code"], PUBLIC_ERROR_DERIVATION_FAILED)
            self.assertNotIn("private", json.dumps(failure))
            self._assert_public_schema(failure)

    def test_public_cli_is_silent_and_does_not_leak_input_paths(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory) / "private-device-serial"
            directory.mkdir()
            invalid = directory / "summary.json"
            invalid.write_text("{}", encoding="utf-8")
            persisted = self._assert_public_cli_failure(
                invalid,
                directory / "samples.jsonl",
                directory / "telemetry.jsonl",
            )
        self.assertNotIn("private-device-serial", json.dumps(persisted))

    def test_public_cli_fail_closed_for_invalid_utf8_in_every_source(self):
        for source_name in ("summary", "samples", "telemetry"):
            with self.subTest(source=source_name), tempfile.TemporaryDirectory() as raw_dir:
                directory = Path(raw_dir) / "fictional-user-orchid-90210"
                directory.mkdir()
                summary, samples, telemetry = write_inputs(directory)
                record = json.loads(summary.read_text(encoding="utf-8"))
                record["errors"] = []
                summary.write_text(json.dumps(record), encoding="utf-8")
                {"summary": summary, "samples": samples, "telemetry": telemetry}[
                    source_name
                ].write_bytes(b"\xffprivate-source")
                persisted = self._assert_public_cli_failure(
                    summary, samples, telemetry
                )
                encoded = json.dumps(persisted)
                self.assertNotIn("UnicodeDecodeError", encoded)
                self.assertNotIn("/Users/", encoded)
                self.assertNotIn("fictional-user-orchid-90210", encoded)

    def test_public_cli_success_is_silent(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            record = json.loads(summary.read_text(encoding="utf-8"))
            record["errors"] = []
            summary.write_text(json.dumps(record), encoding="utf-8")
            output = Path(raw_directory) / "public.json"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(samples),
                        "--host-telemetry", str(telemetry),
                        "--public-output", str(output),
                    ]
                )
            persisted = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self._assert_public_schema(persisted)

    def test_public_cli_output_error_is_fixed_and_does_not_leak_path(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            record = json.loads(summary.read_text(encoding="utf-8"))
            record["errors"] = []
            summary.write_text(json.dumps(record), encoding="utf-8")
            private_parent = Path(raw_directory) / "private-device-output"
            private_parent.write_text("not a directory", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(samples),
                        "--host-telemetry", str(telemetry),
                        "--public-output", str(private_parent / "public.json"),
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), PUBLIC_OUTPUT_ERROR_MESSAGE + "\n")
        self.assertNotIn("private-device-output", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
