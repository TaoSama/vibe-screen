from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from vibescreen_evidence.host_memory_analysis import INTERPRETATION, analyze_records
from vibescreen_evidence.host_memory_diagnostic import (
    DEFAULT_WATCHED_CLASSES,
    _heap_payload,
    _watched_classes,
    main,
)
from vibescreen_evidence.host_memory_parsers import (
    HeapClass,
    HeapSnapshot,
    MemoryToolParseError,
    parse_footprint_json,
    parse_heap_summary,
    parse_vmmap_summary,
)


MIB = 1024 * 1024
STARTED = datetime(2026, 8, 16, tzinfo=timezone.utc)
FINISHED = STARTED + timedelta(minutes=10)


def timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def telemetry(
    *,
    depth: int = 1,
    capacity: int = 2,
    encoder_in_flight: int = 1,
    encoder_capacity: int = 2,
) -> list[dict]:
    return [
        {
            "schema_version": 1,
            "event": "stream_stats",
            "monotonic_ns": offset * 1_000_000_000,
            "session_epoch": 1,
            "wall_time": timestamp(STARTED + timedelta(seconds=offset)),
            "attributes": {
                "fps": 60.0,
                "queue_depth": depth,
                "queue_capacity": capacity,
                "encoder_in_flight": encoder_in_flight,
                "encoder_in_flight_capacity": encoder_capacity,
            },
        }
        for offset in range(0, 601, 5)
    ]


def memory_records(kind: str) -> list[dict]:
    records = []
    for index in range(21):
        elapsed = index * 30.0
        progress = index / 20.0
        if kind == "retained":
            resident_growth = int(4 * MIB * progress)
            live_growth = int(2 * MIB * progress)
            fragmentation_growth = int(2 * MIB * progress)
            heap_byte_growth = int(2 * MIB * progress)
            heap_node_growth = int(2_000 * progress)
            observation_count = 1_000 + int(1_500 * progress)
        elif kind == "allocator":
            resident_growth = int(4 * MIB * progress)
            live_growth = 0
            fragmentation_growth = int(4 * MIB * progress)
            heap_byte_growth = 0
            heap_node_growth = 0
            observation_count = 1_000
        elif kind == "decreasing":
            resident_growth = int(-4 * MIB * progress)
            live_growth = int(-2 * MIB * progress)
            fragmentation_growth = int(-2 * MIB * progress)
            heap_byte_growth = int(-2 * MIB * progress)
            heap_node_growth = int(-2_000 * progress)
            observation_count = max(0, 1_000 - int(900 * progress))
        else:
            resident_growth = live_growth = fragmentation_growth = 0
            heap_byte_growth = heap_node_growth = 0
            observation_count = 1_000

        heap = None
        if index in (0, 10, 20):
            heap = {
                "node_count": 100_000 + heap_node_growth,
                "allocated_bytes": 100 * MIB + heap_byte_growth,
                "classes": [
                    {
                        "name": "ObservationRegistrar",
                        "count": observation_count,
                        "allocated_bytes": observation_count * 64,
                    }
                ],
            }
        records.append(
            {
                "sample_index": index,
                "elapsed_seconds": elapsed,
                "memory": {
                    "rss_bytes": 500 * MIB + resident_growth,
                    "physical_footprint_bytes": 480 * MIB + resident_growth,
                    "malloc_small_dirty_bytes": 350 * MIB + resident_growth,
                    "malloc_large_dirty_bytes": 84 * MIB,
                    "iosurface_dirty_bytes": 16 * MIB,
                    "malloc_zone_dirty_bytes": 360 * MIB + resident_growth,
                    "malloc_zone_allocated_bytes": 240 * MIB + live_growth,
                    "malloc_zone_fragmentation_bytes": (
                        120 * MIB + fragmentation_growth
                    ),
                },
                "heap": heap,
                "errors": [],
            }
        )
    return records


class HostMemoryParserTests(unittest.TestCase):
    def test_parses_real_footprint_shape_and_scales_units(self):
        snapshot = parse_footprint_json(
            {
                "bytes per unit": 2,
                "processes": [
                    {
                        "pid": 123,
                        "auxiliary": {"phys_footprint": 400},
                        "categories": {
                            "MALLOC_SMALL": {"dirty": 100},
                            "MALLOC_LARGE": {"dirty": 50},
                        },
                    }
                ],
                "errors": [],
            },
            pid=123,
        )

        self.assertEqual(snapshot.physical_footprint_bytes, 800)
        self.assertEqual(snapshot.category_dirty_bytes["MALLOC_SMALL"], 200)

    def test_footprint_errors_fail_closed(self):
        with self.assertRaises(MemoryToolParseError):
            parse_footprint_json(
                {"bytes per unit": 1, "processes": [], "errors": ["denied"]},
                pid=123,
            )

    def test_footprint_requires_malloc_small_category(self):
        with self.assertRaises(MemoryToolParseError):
            parse_footprint_json(
                {
                    "bytes per unit": 1,
                    "processes": [
                        {
                            "pid": 123,
                            "auxiliary": {"phys_footprint": 400},
                            "categories": {"MALLOC_LARGE": {"dirty": 50}},
                        }
                    ],
                    "errors": [],
                },
                pid=123,
            )

    def test_vmmap_parses_zone_totals_without_double_counting_total_row(self):
        snapshot = parse_vmmap_summary(
            """
Physical footprint:         944K
MALLOC ZONE                         SIZE       SIZE       SIZE       SIZE      COUNT  ALLOCATED  FRAG SIZE  % FRAG   COUNT
===========                      =======  =========  =========  =========  =========  =========  =========  ======  ======
DefaultMallocZone_0x1              12.8M       336K       336K         0K        186        12K       324K     97%       5
NanoMallocZone_0x2                   16M       128K       128K         0K        200        64K        64K     50%       2
TOTAL                              28.8M       464K       464K         0K        386        76K       388K     83%       7
"""
        )

        self.assertEqual(snapshot.physical_footprint_bytes, 944 * 1024)
        self.assertEqual(snapshot.malloc_zone_dirty_bytes, 464 * 1024)
        self.assertEqual(snapshot.malloc_zone_allocated_bytes, 76 * 1024)
        self.assertEqual(snapshot.malloc_zone_fragmentation_bytes, 388 * 1024)

    def test_heap_parses_typed_and_non_object_rows(self):
        snapshot = parse_heap_summary(
            """
All zones: 186 nodes malloced - Sizes: 32[186]
-----------------------------------------------------------------------
All zones: 186 nodes (12K)

   COUNT      BYTES       AVG   CLASS_NAME                                        TYPE    BINARY
   =====      =====       ===   ==========                                        ====    ======
      24         5K     196.7   non-object
     136         4K      32.0   Class.data (class_rw_t)                           C       libobjc.A.dylib
       4       1024     256.0   ObservationRegistrar.Storage<Any Key>             Swift   SwiftUI
"""
        )

        self.assertEqual(snapshot.node_count, 186)
        self.assertEqual(snapshot.allocated_bytes, 12 * 1024)
        self.assertEqual(snapshot.classes[0].name, "non-object")
        self.assertEqual(snapshot.classes[1].type_name, "C")
        self.assertEqual(snapshot.classes[2].type_name, "Swift")

    def test_heap_parses_average_with_human_readable_unit(self):
        snapshot = parse_heap_summary(
            """
All zones: 1 nodes (4K)
   COUNT      BYTES       AVG   CLASS_NAME                                        TYPE    BINARY
   =====      =====       ===   ==========                                        ====    ======
       1         4K      4.0K   @autoreleasepool content                          C       libobjc.A.dylib
"""
        )

        self.assertEqual(len(snapshot.classes), 1)
        self.assertEqual(snapshot.classes[0].name, "@autoreleasepool content")

    def test_heap_payload_keeps_watched_autorelease_class_outside_top_twenty(self):
        classes = tuple(
            HeapClass(f"LargeClass{index}", 1, (100 - index) * 1024, "Swift")
            for index in range(20)
        ) + (HeapClass("@autoreleasepool content", 3, 64, "C"),)

        payload = _heap_payload(
            HeapSnapshot(node_count=23, allocated_bytes=MIB, classes=classes),
            ("AutoreleasePool",),
        )

        self.assertIn(
            "@autoreleasepool content",
            [item["name"] for item in payload["classes"]],
        )


class HostMemoryAnalysisTests(unittest.TestCase):
    def analyze(self, kind: str, *, depth: int = 1, records=None):
        return analyze_records(
            records if records is not None else memory_records(kind),
            telemetry(depth=depth),
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

    def test_attributes_synchronized_live_growth_to_retained_objects(self):
        result = self.analyze("retained")

        self.assertEqual(result["attribution"], "retained_growth")
        self.assertEqual(result["verdict"], "fail")
        self.assertTrue(all(result["sufficiency"].values()))
        self.assertEqual(
            result["metrics"]["heap_class_growth"][0]["name"],
            "ObservationRegistrar",
        )

    def test_custom_heap_watch_extends_required_diagnostic_classes(self):
        watched = _watched_classes(
            ["  CustomCache ", "", "ObservationRegistrar"]
        )

        self.assertEqual(watched[: len(DEFAULT_WATCHED_CLASSES)], DEFAULT_WATCHED_CLASSES)
        self.assertEqual(watched.count("ObservationRegistrar"), 1)
        self.assertIn("CustomCache", watched)

    def test_invalid_cli_arguments_use_pipeline_failure_exit_code(self):
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
            SystemExit
        ) as raised:
            main([])

        self.assertEqual(raised.exception.code, 1)

    def test_cli_rejects_interval_that_cannot_meet_sample_minimum(self):
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
            SystemExit
        ) as raised:
            main(
                [
                    "--host-pid", "1",
                    "--interval-seconds", "31",
                    "--telemetry-jsonl", "telemetry.jsonl",
                    "--samples", "samples.jsonl",
                    "--output", "diagnostic.json",
                ]
            )

        self.assertEqual(raised.exception.code, 1)

    def test_attributes_fragmentation_with_flat_live_heap_to_allocator_high_water(self):
        result = self.analyze("allocator")

        self.assertEqual(result["attribution"], "allocator_high_water")
        self.assertEqual(result["verdict"], "fail")
        self.assertTrue(all(result["sufficiency"].values()))

    def test_stable_short_run_passes_short_window_but_cannot_close_two_hour_gate(self):
        result = self.analyze("flat")

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "pass")
        self.assertIn("cannot close", INTERPRETATION)

    def test_queue_capacity_overage_fails_even_when_attribution_inconclusive(self):
        result = self.analyze("retained", depth=3)

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(len(result["telemetry"]["anomalies"]), 1)
        self.assertIn("queue depth exceeded", result["telemetry"]["anomalies"][0])

    def test_queue_capacity_change_fails_even_when_attribution_inconclusive(self):
        changed = telemetry()
        changed[-1]["attributes"]["queue_capacity"] = 3

        result = analyze_records(
            memory_records("retained"),
            changed,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "fail")
        self.assertIn(
            "capacity was invalid or changed",
            result["telemetry"]["anomalies"][-1],
        )

    def test_encoder_capacity_overage_fails_even_when_attribution_inconclusive(self):
        result = analyze_records(
            memory_records("retained"),
            telemetry(encoder_in_flight=3),
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "fail")
        self.assertIn("in-flight count exceeded", result["telemetry"]["anomalies"][-1])

    def test_stream_telemetry_treats_encoder_in_flight_fields_as_optional(self):
        incomplete = telemetry()
        incomplete[10]["attributes"].pop("encoder_in_flight")

        result = analyze_records(
            memory_records("retained"),
            incomplete,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["attribution"], "retained_growth")
        self.assertEqual(result["verdict"], "fail")
        self.assertIn(
            "encoder_in_flight",
            result["telemetry"]["missing_optional_fields"],
        )
        self.assertTrue(result["sufficiency"]["stream_telemetry"])

    def test_stream_telemetry_gap_fails_closed(self):
        sparse = telemetry()[::20]
        result = analyze_records(
            memory_records("retained"),
            sparse,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "insufficient")
        self.assertFalse(result["telemetry"]["coverage_complete"])
        self.assertFalse(result["sufficiency"]["stream_telemetry"])

    def test_stream_telemetry_requires_fields_on_every_record(self):
        incomplete = telemetry()
        incomplete[10]["attributes"].pop("queue_depth")

        result = analyze_records(
            memory_records("retained"),
            incomplete,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn("queue_depth", result["telemetry"]["missing_required_fields"])
        self.assertFalse(result["sufficiency"]["stream_telemetry"])

    def test_stream_telemetry_requires_one_continuous_session_epoch(self):
        reconnected = telemetry()
        for record in reconnected[len(reconnected) // 2 :]:
            record["session_epoch"] = 2

        result = analyze_records(
            memory_records("retained"),
            reconnected,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "insufficient")
        self.assertEqual(result["telemetry"]["session_epochs"], [1, 2])
        self.assertFalse(result["telemetry"]["single_session"])
        self.assertFalse(result["sufficiency"]["stream_telemetry"])

    def test_stream_telemetry_schema_mismatch_fails_closed(self):
        incompatible = telemetry()
        incompatible[10]["schema_version"] = 2

        result = analyze_records(
            memory_records("retained"),
            incompatible,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "insufficient")
        self.assertEqual(result["telemetry"]["invalid_record_count"], 1)
        self.assertFalse(result["sufficiency"]["stream_telemetry"])

    def test_non_positive_stream_fps_is_pipeline_anomaly(self):
        stalled = telemetry()
        stalled[10]["attributes"]["fps"] = 0

        result = analyze_records(
            memory_records("retained"),
            stalled,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "fail")
        self.assertIn("non-positive FPS", result["telemetry"]["anomalies"][-1])

    def test_missing_memory_metric_fails_closed(self):
        records = memory_records("retained")
        records[4]["memory"].pop("malloc_zone_allocated_bytes")

        result = self.analyze("retained", records=records)

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "insufficient")
        self.assertFalse(
            result["sufficiency"]["malloc_zone_allocated_bytes_complete"]
        )

    def test_short_window_fails_closed(self):
        records = memory_records("retained")[:10]

        result = self.analyze("retained", records=records)

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "insufficient")
        self.assertFalse(result["sufficiency"]["duration"])

    def test_decreasing_required_signals_still_pass_short_window(self):
        result = self.analyze("decreasing")

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(all(result["sufficiency"].values()))
        for field in (
            "rss_bytes",
            "physical_footprint_bytes",
            "malloc_small_dirty_bytes",
            "malloc_zone_dirty_bytes",
            "malloc_zone_allocated_bytes",
            "malloc_zone_fragmentation_bytes",
            "heap_allocated_bytes",
        ):
            self.assertLess(result["metrics"][field]["endpoint_median_drift"], 0)

    def test_cli_writes_inconclusive_failure_report(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "diagnostic.json"
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--host-pid",
                        "999999",
                        "--duration-seconds",
                        "600",
                        "--telemetry-jsonl",
                        str(Path(raw) / "missing.jsonl"),
                        "--samples",
                        str(Path(raw) / "samples.jsonl"),
                        "--output",
                        str(output),
                    ]
                )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertEqual(report["attribution"], "inconclusive")

    def test_cli_catches_unexpected_exception_and_writes_failure_report(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "diagnostic.json"
            with patch(
                "vibescreen_evidence.host_memory_diagnostic.collect",
                side_effect=KeyError("unexpected parser shape"),
            ), contextlib.redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--host-pid",
                        "1",
                        "--duration-seconds",
                        "600",
                        "--telemetry-jsonl",
                        str(Path(raw) / "telemetry.jsonl"),
                        "--samples",
                        str(Path(raw) / "samples.jsonl"),
                        "--output",
                        str(output),
                    ]
                )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertEqual(report["attribution"], "inconclusive")

    def test_cli_uses_distinct_exit_code_for_attributed_growth(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            report = {
                "attribution": "retained_growth",
                "verdict": "fail",
                "sufficiency": {"complete": True},
                "telemetry": {"anomalies": []},
            }
            with patch(
                "vibescreen_evidence.host_memory_diagnostic.collect",
                return_value=report,
            ), contextlib.redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--host-pid", "1",
                        "--duration-seconds", "600",
                        "--telemetry-jsonl", str(Path(raw) / "telemetry.jsonl"),
                        "--samples", str(Path(raw) / "samples.jsonl"),
                        "--output", str(Path(raw) / "diagnostic.json"),
                    ]
                )

        self.assertEqual(exit_code, 2)

    def test_cli_zero_only_means_complete_without_attribution(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            report = {
                "attribution": "inconclusive",
                "verdict": "pass",
                "sufficiency": {"complete": True},
                "telemetry": {"anomalies": []},
            }
            with patch(
                "vibescreen_evidence.host_memory_diagnostic.collect",
                return_value=report,
            ), contextlib.redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--host-pid", "1",
                        "--duration-seconds", "600",
                        "--telemetry-jsonl", str(Path(raw) / "telemetry.jsonl"),
                        "--samples", str(Path(raw) / "samples.jsonl"),
                        "--output", str(Path(raw) / "diagnostic.json"),
                    ]
                )

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
