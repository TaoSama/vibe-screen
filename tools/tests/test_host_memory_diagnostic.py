from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import vibescreen_evidence.host_memory_diagnostic as host_memory_diagnostic
from vibescreen_evidence.host_memory_analysis import (
    EvidenceInputError,
    INTERPRETATION,
    SUFFICIENCY_FIELDS,
    _validate_final_state,
    analyze_records,
)
from vibescreen_evidence.host_memory_diagnostic import (
    DEFAULT_WATCHED_CLASSES,
    DiagnosticInterrupted,
    _commit_sample,
    _heap_payload,
    _run_command,
    _signals_as_interruption,
    _watched_classes,
    collect,
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


SIGNAL_CLI_CODE = r"""
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

import vibescreen_evidence.host_memory_diagnostic as diagnostic

phase, telemetry_path, samples_path, output_path, marker_path = sys.argv[1:]
marker = Path(marker_path)
record = {
    "schema_version": 1,
    "kind": "host_memory_sample",
    "sample_index": 0,
    "captured_at": "2026-08-17T00:00:00Z",
    "elapsed_seconds": 0.0,
    "memory": {},
    "heap": None,
    "errors": [],
}
real_analyze = diagnostic.analyze_records
real_collect = diagnostic.collect
real_write_json = diagnostic._write_json

def gated_analyze(*args, **kwargs):
    if phase == "analysis" and not marker.exists():
        marker.write_text("ready", encoding="utf-8")
        time.sleep(30)
    return real_analyze(*args, **kwargs)

def gated_write_json(path, value):
    if phase == "write" and not marker.exists():
        marker.write_text("ready", encoding="utf-8")
        time.sleep(30)
    return real_write_json(path, value)

def collect_for_test(**kwargs):
    if phase == "sampling":
        def gated_sleep(_seconds):
            marker.write_text("ready", encoding="utf-8")
            time.sleep(30)
        return real_collect(**kwargs, monotonic=lambda: 0.0, sleep=gated_sleep)
    clock = iter((0.0, 600.0, 600.0))
    return real_collect(
        **kwargs,
        monotonic=lambda: next(clock, 600.0),
        sleep=lambda _seconds: None,
    )

with patch.object(diagnostic, "_run_command", return_value="123\n"), patch.object(
    diagnostic, "_capture_sample", return_value=record
), patch.object(diagnostic, "analyze_records", side_effect=gated_analyze), patch.object(
    diagnostic, "_write_json", side_effect=gated_write_json
), patch.object(
    diagnostic, "collect", side_effect=collect_for_test
):
    raise SystemExit(
        diagnostic.main(
            [
                "--host-pid", "123",
                "--duration-seconds", "600",
                "--interval-seconds", "30",
                "--telemetry-jsonl", telemetry_path,
                "--samples", samples_path,
                "--output", output_path,
            ]
        )
    )
"""


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

    def test_vmmap_keeps_zone_named_total_and_skips_aggregate_before_trailing_rows(self):
        snapshot = parse_vmmap_summary(
            """
Physical footprint:         944K
MALLOC ZONE                         SIZE       SIZE       SIZE       SIZE      COUNT  ALLOCATED  FRAG SIZE  % FRAG   COUNT
===========                      =======  =========  =========  =========  =========  =========  =========  ======  ======
TOTAL                                1M        64K        64K         0K         10        32K        32K     50%       1
DefaultMallocZone_0x1                2M       128K       128K         0K         20        64K        64K     50%       2
TOTAL                                3M       192K       192K         0K         30        96K        96K     50%       3
TrailingZone_0x2                     4M       256K       256K         0K         40       128K       128K     50%       4
"""
        )

        self.assertEqual(snapshot.malloc_zone_dirty_bytes, 192 * 1024)
        self.assertEqual(snapshot.malloc_zone_allocated_bytes, 96 * 1024)
        self.assertEqual(snapshot.malloc_zone_fragmentation_bytes, 96 * 1024)

    def test_vmmap_supports_a_zone_table_without_aggregate_total(self):
        snapshot = parse_vmmap_summary(
            """
Physical footprint:         944K
MALLOC ZONE                         SIZE       SIZE       SIZE       SIZE      COUNT  ALLOCATED  FRAG SIZE  % FRAG   COUNT
-----------                      -------  ---------  ---------  ---------  ---------  ---------  ---------  ------  ------
DefaultMallocZone_0x1                2M       128K       128K         0K         20        64K        64K     50%       2
"""
        )

        self.assertEqual(snapshot.malloc_zone_dirty_bytes, 128 * 1024)
        self.assertEqual(snapshot.malloc_zone_allocated_bytes, 64 * 1024)
        self.assertEqual(snapshot.malloc_zone_fragmentation_bytes, 64 * 1024)

    def test_vmmap_rejects_malformed_content_before_first_zone(self):
        with self.assertRaisesRegex(
            MemoryToolParseError, "malformed malloc-zone table"
        ):
            parse_vmmap_summary(
                """
Physical footprint:         944K
MALLOC ZONE                         SIZE       SIZE       SIZE       SIZE      COUNT  ALLOCATED  FRAG SIZE  % FRAG   COUNT
===========                      =======  =========  =========  =========  =========  =========  =========  ======  ======
DefaultMallocZone_0x1              missing fields
NanoMallocZone_0x2                   16M       128K       128K         0K        200        64K        64K     50%       2
"""
            )

    def test_vmmap_stops_at_first_non_row_after_zone_rows(self):
        snapshot = parse_vmmap_summary(
            """
Physical footprint:         944K
MALLOC ZONE                         SIZE       SIZE       SIZE       SIZE      COUNT  ALLOCATED  FRAG SIZE  % FRAG   COUNT
===========                      =======  =========  =========  =========  =========  =========  =========  ======  ======
DefaultMallocZone_0x1                2M       128K       128K         0K         20        64K        64K     50%       2
table ended here
NanoMallocZone_0x2                   16M       128K       128K         0K        200        64K        64K     50%       2
"""
        )

        self.assertEqual(snapshot.malloc_zone_dirty_bytes, 128 * 1024)
        self.assertEqual(snapshot.malloc_zone_allocated_bytes, 64 * 1024)
        self.assertEqual(snapshot.malloc_zone_fragmentation_bytes, 64 * 1024)

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

    def test_optional_surface_growth_prevents_short_window_pass(self):
        records = memory_records("flat")
        for index, record in enumerate(records):
            record["memory"]["iosurface_dirty_bytes"] += int(2 * MIB * index / 20)

        result = self.analyze("flat", records=records)

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn("iosurface_dirty_bytes", result["metrics"])

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
        for record in incomplete:
            record["attributes"].pop("encoder_in_flight")
            record["attributes"].pop("encoder_in_flight_capacity")

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
        self.assertIn(
            "encoder_in_flight_capacity",
            result["telemetry"]["missing_optional_fields"],
        )
        self.assertTrue(result["sufficiency"]["stream_telemetry"])

    def test_stream_telemetry_requires_encoder_in_flight_pair_when_present(self):
        for missing in ("encoder_in_flight", "encoder_in_flight_capacity"):
            with self.subTest(missing=missing):
                incomplete = telemetry()
                incomplete[10]["attributes"].pop(missing)

                result = analyze_records(
                    memory_records("retained"),
                    incomplete,
                    started_at=timestamp(STARTED),
                    finished_at=timestamp(FINISHED),
                )

                self.assertEqual(result["attribution"], "inconclusive")
                self.assertEqual(result["verdict"], "insufficient")
                self.assertEqual(result["telemetry"]["invalid_record_count"], 1)
                self.assertEqual(result["telemetry"]["stream_stats_count"], 120)
                self.assertIn(
                    missing,
                    result["telemetry"]["missing_optional_fields"],
                )
                self.assertFalse(result["sufficiency"]["stream_telemetry"])

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
        self.assertEqual(result["telemetry"]["stream_stats_count"], 120)
        self.assertEqual(result["telemetry"]["total_stream_stats_count"], 121)
        self.assertEqual(result["telemetry"]["out_of_window_record_count"], 0)
        self.assertFalse(result["sufficiency"]["stream_telemetry"])

    def test_invalid_stream_record_is_counted_once_and_cannot_pollute_analysis(self):
        invalid = telemetry()
        invalid_record = invalid[10]
        invalid_record.update(
            schema_version=2,
            monotonic_ns=-1,
            session_epoch=99,
        )
        invalid_record["attributes"] = {
            "fps": 0,
            "queue_depth": 99,
            "queue_capacity": 1,
        }

        result = analyze_records(
            memory_records("retained"),
            invalid,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["verdict"], "insufficient")
        self.assertEqual(result["telemetry"]["invalid_record_count"], 1)
        self.assertEqual(result["telemetry"]["stream_stats_count"], 120)
        self.assertEqual(result["telemetry"]["total_stream_stats_count"], 121)
        self.assertEqual(result["telemetry"]["out_of_window_record_count"], 0)
        self.assertEqual(result["telemetry"]["session_epochs"], [1])
        self.assertEqual(result["telemetry"]["anomalies"], [])
        self.assertEqual(result["telemetry"]["missing_required_fields"], [])

    def test_each_core_stream_record_field_is_validated_before_admission(self):
        invalid_values = (
            ("schema_version", True),
            ("schema_version", 1.0),
            ("schema_version", 2),
            ("monotonic_ns", True),
            ("monotonic_ns", -1),
            ("session_epoch", True),
            ("session_epoch", 0),
        )
        for field, value in invalid_values:
            with self.subTest(field=field, value=value):
                records = telemetry()
                records[10][field] = value
                records[10]["attributes"] = {
                    "fps": 0,
                    "queue_depth": 99,
                    "queue_capacity": 1,
                }

                result = analyze_records(
                    memory_records("retained"),
                    records,
                    started_at=timestamp(STARTED),
                    finished_at=timestamp(FINISHED),
                )

                self.assertEqual(result["telemetry"]["invalid_record_count"], 1)
                self.assertEqual(result["telemetry"]["stream_stats_count"], 120)
                self.assertEqual(result["telemetry"]["session_epochs"], [1])
                self.assertEqual(result["telemetry"]["anomalies"], [])

    def test_stream_record_counts_are_mutually_exclusive_and_reconcile(self):
        records = telemetry()
        records.append(
            {
                "schema_version": 1,
                "event": "stream_stats",
                "wall_time": timestamp(STARTED - timedelta(seconds=1)),
                "monotonic_ns": 1,
                "session_epoch": 1,
                "attributes": {
                    "fps": 60,
                    "queue_depth": 1,
                    "queue_capacity": 2,
                },
            }
        )
        invalid = telemetry()[0]
        invalid["wall_time"] = timestamp(STARTED - timedelta(seconds=2))
        invalid["attributes"] = {"fps": "bad", "queue_depth": 99}
        records.append(invalid)

        result = analyze_records(
            memory_records("retained"),
            records,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["telemetry"]["invalid_record_count"], 1)
        self.assertEqual(result["telemetry"]["stream_stats_count"], 121)
        self.assertEqual(result["telemetry"]["out_of_window_record_count"], 1)
        self.assertEqual(result["telemetry"]["total_stream_stats_count"], 123)
        self.assertEqual(result["telemetry"]["session_epochs"], [1])
        self.assertEqual(result["telemetry"]["anomalies"], [])
        self.assertIn("fps", result["telemetry"]["missing_required_fields"])
        self.assertIn("queue_capacity", result["telemetry"]["missing_required_fields"])

    def test_attribute_type_failure_is_invalid_and_not_admitted(self):
        records = telemetry()
        records[10]["attributes"] = []

        result = analyze_records(
            memory_records("retained"),
            records,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["telemetry"]["total_stream_stats_count"], 121)
        self.assertEqual(result["telemetry"]["stream_stats_count"], 120)
        self.assertEqual(result["telemetry"]["invalid_record_count"], 1)
        self.assertEqual(result["telemetry"]["out_of_window_record_count"], 0)
        self.assertEqual(result["telemetry"]["minimum_fps"], 60.0)
        self.assertEqual(result["telemetry"]["maximum_queue_depth"], 1.0)
        self.assertEqual(
            result["telemetry"]["missing_optional_fields"],
            ["encoder_in_flight", "encoder_in_flight_capacity"],
        )

    def test_invalid_present_optional_field_rejects_record(self):
        records = telemetry()
        records[10]["attributes"]["encoder_in_flight"] = -1

        result = analyze_records(
            memory_records("retained"),
            records,
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["telemetry"]["total_stream_stats_count"], 121)
        self.assertEqual(result["telemetry"]["stream_stats_count"], 120)
        self.assertEqual(result["telemetry"]["invalid_record_count"], 1)
        self.assertIn(
            "encoder_in_flight",
            result["telemetry"]["missing_optional_fields"],
        )

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

    def test_memory_samples_must_cover_report_window_finish(self):
        result = analyze_records(
            memory_records("flat"),
            telemetry(),
            started_at=timestamp(STARTED),
            finished_at=timestamp(STARTED + timedelta(minutes=15)),
        )

        self.assertEqual(result["attribution"], "inconclusive")
        self.assertEqual(result["verdict"], "insufficient")
        self.assertFalse(result["sufficiency"]["memory_window_coverage"])
        self.assertFalse(result["sufficiency"]["heap_window_coverage"])

    def test_zero_memory_records_fail_every_completeness_check(self):
        result = analyze_records(
            [],
            telemetry(),
            started_at=timestamp(STARTED),
            finished_at=timestamp(FINISHED),
        )

        self.assertEqual(result["verdict"], "insufficient")
        self.assertFalse(result["sufficiency"]["collection_complete"])
        self.assertFalse(result["sufficiency"]["error_free"])
        self.assertFalse(result["sufficiency"]["memory_samples"])
        for key, value in result["sufficiency"].items():
            if key.endswith("_complete"):
                self.assertFalse(value, key)

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

    def test_final_state_validation_uses_explicit_evidence_input_errors(self):
        with self.assertRaisesRegex(EvidenceInputError, "attribution"):
            _validate_final_state("unsupported", "pass")
        with self.assertRaisesRegex(EvidenceInputError, "verdict"):
            _validate_final_state("inconclusive", "unsupported")

    def test_final_state_validation_is_active_under_optimized_python(self):
        code = """
from vibescreen_evidence.host_memory_analysis import EvidenceInputError, _validate_final_state
try:
    _validate_final_state('unsupported', 'pass')
except EvidenceInputError:
    raise SystemExit(0)
raise SystemExit(1)
"""
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        completed = subprocess.run(
            [sys.executable, "-O", "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=environment,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_run_command_error_contains_full_shell_quoted_context(self):
        command = [
            "/usr/bin/footprint",
            "-j",
            "/tmp/path with spaces/footprint.json",
            "-p",
            "42",
        ]
        completed = subprocess.CompletedProcess(
            command,
            3,
            stdout="",
            stderr="permission denied",
        )
        with patch(
            "vibescreen_evidence.host_memory_diagnostic.subprocess.run",
            return_value=completed,
        ), self.assertRaisesRegex(RuntimeError, "exited with 3") as raised:
            _run_command(command)
        self.assertIn(
            "/usr/bin/footprint -j '/tmp/path with spaces/footprint.json' -p 42",
            str(raised.exception),
        )
        self.assertNotIn("permission denied", str(raised.exception))

    def _collect_with_keyboard_interrupt(self, phase: str) -> tuple[dict, list[str]]:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            telemetry_path = root / "telemetry.jsonl"
            samples_path = root / "samples.jsonl"
            output_path = root / "diagnostic.json"
            telemetry_path.write_text(
                "\n".join(json.dumps(record) for record in telemetry()) + "\n",
                encoding="utf-8",
            )
            captured = memory_records("flat")[0]
            real_analyze = host_memory_diagnostic.analyze_records
            real_write_json = host_memory_diagnostic._write_json
            analyze_interrupted = False
            write_interrupted = False

            def analyze_once(*args, **kwargs):
                nonlocal analyze_interrupted
                if phase == "analysis" and not analyze_interrupted:
                    analyze_interrupted = True
                    raise KeyboardInterrupt
                return real_analyze(*args, **kwargs)

            def write_once(path, value):
                nonlocal write_interrupted
                if phase == "write" and not write_interrupted:
                    write_interrupted = True
                    raise KeyboardInterrupt
                return real_write_json(path, value)

            sleep = (
                (lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
                if phase == "sampling"
                else (lambda _: None)
            )
            if phase == "sampling":
                monotonic = lambda: 0.0
            else:
                clock = iter([0.0, 600.0, 600.0])
                monotonic = lambda: next(clock, 600.0)
            with patch.object(
                host_memory_diagnostic, "_run_command", return_value="123\n"
            ), patch.object(
                host_memory_diagnostic, "_capture_sample", return_value=captured
            ), patch.object(
                host_memory_diagnostic, "analyze_records", side_effect=analyze_once
            ), patch.object(
                host_memory_diagnostic, "_write_json", side_effect=write_once
            ), patch.object(
                host_memory_diagnostic,
                "_utc_now",
                side_effect=[
                    timestamp(STARTED),
                    timestamp(STARTED + timedelta(seconds=30)),
                ],
            ):
                report = collect(
                    pid=123,
                    duration_seconds=600,
                    interval_seconds=30,
                    telemetry_path=telemetry_path,
                    samples_path=samples_path,
                    output_path=output_path,
                    watched_classes=DEFAULT_WATCHED_CLASSES,
                    monotonic=monotonic,
                    sleep=sleep,
                )
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            sample_lines = samples_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(report, persisted)
        return report, sample_lines

    def test_keyboard_interrupt_writes_partial_report_in_every_phase(self):
        for phase in ("sampling", "analysis", "write"):
            with self.subTest(phase=phase):
                report, sample_lines = self._collect_with_keyboard_interrupt(phase)
                self.assertEqual(report["derivation_status"], "partial")
                self.assertEqual(report["verdict"], "insufficient")
                self.assertEqual(report["attribution"], "inconclusive")
                self.assertEqual(report["interruption_signal"], "SIGINT")
                self.assertEqual(report["window"]["sample_count"], len(sample_lines))
                self.assertFalse(report["sufficiency"]["collection_complete"])

    def test_sample_commit_rolls_disk_back_when_interrupted(self):
        with tempfile.TemporaryDirectory() as raw:
            samples_path = Path(raw) / "samples.jsonl"
            records = [memory_records("flat")[0]]
            host_memory_diagnostic._write_samples(samples_path, records)
            real_write_samples = host_memory_diagnostic._write_samples
            interrupted = False

            def interrupt_once(path, value):
                nonlocal interrupted
                if not interrupted:
                    interrupted = True
                    path.write_text("partial", encoding="utf-8")
                    raise KeyboardInterrupt
                return real_write_samples(path, value)

            with patch.object(
                host_memory_diagnostic,
                "_write_samples",
                side_effect=interrupt_once,
            ), self.assertRaises(KeyboardInterrupt):
                _commit_sample(samples_path, records, memory_records("flat")[1])

            persisted = [
                json.loads(line)
                for line in samples_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(records, persisted)

    def test_signal_handler_requires_main_thread(self):
        errors = []
        run_command_calls = []

        def run() -> None:
            try:
                with tempfile.TemporaryDirectory() as raw, patch.object(
                    host_memory_diagnostic,
                    "_run_command",
                    side_effect=lambda command: run_command_calls.append(command),
                ):
                    collect(
                        pid=123,
                        duration_seconds=600,
                        interval_seconds=30,
                        telemetry_path=Path(raw) / "telemetry.jsonl",
                        samples_path=Path(raw) / "samples.jsonl",
                        output_path=Path(raw) / "diagnostic.json",
                        watched_classes=DEFAULT_WATCHED_CLASSES,
                    )
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("requires the main thread", str(errors[0]))
        self.assertEqual(run_command_calls, [])

    def test_cli_returns_one_for_interrupted_partial_report(self):
        import contextlib
        import io
        import tempfile

        report = {"verdict": "insufficient", "interruption_signal": "SIGINT"}
        with tempfile.TemporaryDirectory() as raw, patch(
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

        self.assertEqual(exit_code, 1)

    def test_signal_handlers_are_restored_after_partial_request(self):
        previous = {
            signum: signal.getsignal(signum)
            for signum in (signal.SIGINT, signal.SIGTERM)
        }
        with self.assertRaisesRegex(DiagnosticInterrupted, "SIGTERM"):
            with _signals_as_interruption():
                handler = signal.getsignal(signal.SIGTERM)
                self.assertTrue(callable(handler))
                handler(signal.SIGTERM, None)
        for signum, handler in previous.items():
            self.assertIs(signal.getsignal(signum), handler)

    def test_real_cli_signals_write_partial_report_in_every_phase(self):
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            for phase in ("sampling", "analysis", "write"):
                with self.subTest(signal=signal_number, phase=phase):
                    with tempfile.TemporaryDirectory() as raw:
                        root = Path(raw)
                        telemetry_path = root / "telemetry.jsonl"
                        samples_path = root / "samples.jsonl"
                        output_path = root / "diagnostic.json"
                        marker_path = root / "ready"
                        telemetry_path.write_text("", encoding="utf-8")
                        environment = dict(os.environ)
                        environment["PYTHONPATH"] = str(
                            Path(__file__).resolve().parents[1]
                        )
                        process = subprocess.Popen(
                            [
                                sys.executable,
                                "-c",
                                SIGNAL_CLI_CODE,
                                phase,
                                str(telemetry_path),
                                str(samples_path),
                                str(output_path),
                                str(marker_path),
                            ],
                            env=environment,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                        )
                        try:
                            deadline = time.monotonic() + 10
                            while (
                                not marker_path.exists()
                                and time.monotonic() < deadline
                            ):
                                if process.poll() is not None:
                                    break
                                time.sleep(0.01)
                            if not marker_path.exists():
                                process.terminate()
                                stdout, stderr = process.communicate(timeout=5)
                                self.fail(
                                    f"subprocess did not reach {phase}: "
                                    f"{stdout} {stderr}"
                                )
                            os.kill(process.pid, signal_number)
                            stdout, stderr = process.communicate(timeout=5)
                            self.assertEqual(
                                process.returncode, 1, (stdout, stderr)
                            )
                        finally:
                            if process.poll() is None:
                                process.kill()
                                process.wait(timeout=5)
                        report = json.loads(output_path.read_text(encoding="utf-8"))
                        sample_lines = samples_path.read_text(encoding="utf-8").splitlines()

                    self.assertEqual(report["derivation_status"], "partial")
                    self.assertEqual(report["verdict"], "insufficient")
                    self.assertEqual(report["attribution"], "inconclusive")
                    self.assertEqual(
                        report["interruption_signal"],
                        signal.Signals(signal_number).name,
                    )
                    self.assertEqual(report["window"]["sample_count"], len(sample_lines))
                    self.assertFalse(report["sufficiency"]["collection_complete"])

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
        self.assertTrue(report["sufficiency"])
        self.assertEqual(set(report["sufficiency"]), set(SUFFICIENCY_FIELDS))
        self.assertTrue(
            all(value is False for value in report["sufficiency"].values())
        )

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
