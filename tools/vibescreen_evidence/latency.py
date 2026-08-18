#!/usr/bin/env python3
"""Summarize externally measured Vibe Screen latency samples.

Glass-to-glass results are accepted only when they were measured on one
external-camera timebase. Host and device clocks are not assumed to be
synchronized and may not be used to claim glass-to-glass latency.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION


KIND_GLASS_TO_GLASS = "glass-to-glass"
KIND_INPUT = "input"
KIND_TELEMETRY_STAGE = "telemetry-stage"
METHOD_EXTERNAL_CAMERA = "external-camera"
METHOD_SYNCHRONIZED_CLOCK = "synchronized-clock"
METHOD_HOST_TELEMETRY = "host-telemetry"
METHOD_CLIENT_TELEMETRY = "client-telemetry"
METHOD_UNSYNCHRONIZED_CLOCKS = "unsynchronized-host-device-clocks"
TRANSPORT_USB = "usb"
TRANSPORT_LAN = "lan"
TELEMETRY_STAGE_METHODS = (METHOD_HOST_TELEMETRY, METHOD_CLIENT_TELEMETRY)
GATE_USB_GLASS_TO_GLASS_SUB50 = "usb-glass-to-glass-sub50"
GATE_LAN_GLASS_TO_GLASS_SUB80 = "lan-glass-to-glass-sub80"
GATE_INPUT_P95_SUB50 = "input-p95-sub50"
MIN_GATE_SAMPLE_COUNT = 5
GATE_PROFILES = {
    GATE_USB_GLASS_TO_GLASS_SUB50: {
        "kind": KIND_GLASS_TO_GLASS,
        "transport": TRANSPORT_USB,
        "threshold_ms": 50.0,
    },
    GATE_LAN_GLASS_TO_GLASS_SUB80: {
        "kind": KIND_GLASS_TO_GLASS,
        "transport": TRANSPORT_LAN,
        "threshold_ms": 80.0,
    },
    GATE_INPUT_P95_SUB50: {
        "kind": KIND_INPUT,
        "transport": None,
        "threshold_ms": 50.0,
    },
}


class LatencyInputError(ValueError):
    """Raised when raw latency evidence is invalid or misleading."""


def _finite_number(value: Any, field: str, sample_number: int) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise LatencyInputError(
            f"sample {sample_number}: {field} must be a number"
        ) from error
    if not math.isfinite(number):
        raise LatencyInputError(f"sample {sample_number}: {field} must be finite")
    return number


def _latency_from_sample(sample: Any, sample_number: int) -> float:
    if not isinstance(sample, dict):
        raise LatencyInputError(f"sample {sample_number}: expected an object/CSV row")

    has_latency = sample.get("latency_ms") not in (None, "")
    frame_fields = ("start_frame", "end_frame", "camera_fps")
    present_frame_fields = [field for field in frame_fields if sample.get(field) not in (None, "")]

    if has_latency and present_frame_fields:
        raise LatencyInputError(
            f"sample {sample_number}: provide latency_ms or frame fields, not both"
        )
    if has_latency:
        latency_ms = _finite_number(sample["latency_ms"], "latency_ms", sample_number)
    else:
        missing = [field for field in frame_fields if field not in present_frame_fields]
        if missing:
            raise LatencyInputError(
                f"sample {sample_number}: missing latency_ms or frame fields: "
                + ", ".join(missing)
            )
        start_frame = _finite_number(sample["start_frame"], "start_frame", sample_number)
        end_frame = _finite_number(sample["end_frame"], "end_frame", sample_number)
        camera_fps = _finite_number(sample["camera_fps"], "camera_fps", sample_number)
        if camera_fps <= 0:
            raise LatencyInputError(f"sample {sample_number}: camera_fps must be greater than zero")
        if end_frame < start_frame:
            raise LatencyInputError(
                f"sample {sample_number}: end_frame must not precede start_frame"
            )
        latency_ms = (end_frame - start_frame) * 1000.0 / camera_fps

    if latency_ms < 0:
        raise LatencyInputError(f"sample {sample_number}: latency_ms must not be negative")
    return latency_ms


def _stage_from_sample(sample: Any, sample_number: int) -> str:
    if not isinstance(sample, dict):
        raise LatencyInputError(f"sample {sample_number}: expected an object/CSV row")
    stage = sample.get("stage")
    if not isinstance(stage, str) or not stage.strip():
        raise LatencyInputError(
            f"sample {sample_number}: telemetry-stage samples require a non-empty stage"
        )
    return stage.strip()


def load_samples(stream: TextIO, input_format: str) -> list[dict[str, Any]]:
    """Load raw rows from CSV or JSON without assigning measurement semantics."""
    try:
        if input_format == "csv":
            rows = list(csv.DictReader(stream))
        elif input_format == "json":
            document = json.load(stream)
            rows = document.get("samples") if isinstance(document, dict) else document
        else:
            raise LatencyInputError(f"unsupported input format: {input_format}")
    except (csv.Error, json.JSONDecodeError) as error:
        raise LatencyInputError(f"invalid {input_format.upper()}: {error}") from error

    if not isinstance(rows, list):
        raise LatencyInputError(
            "JSON input must be an array or an object containing a samples array"
        )
    if not rows:
        raise LatencyInputError("input contains no samples")
    return rows


def percentile(values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated percentile (R-7 / inclusive endpoints)."""
    if not values:
        raise LatencyInputError("cannot calculate a percentile without samples")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return ordered[lower_index] + fraction * (ordered[upper_index] - ordered[lower_index])


def _derive_gate_verdict(
    *,
    gate_profile: str,
    kind: str,
    transport: str,
    measurement_method: str,
    statistics_summary: dict[str, float | int],
) -> dict[str, Any]:
    profile = GATE_PROFILES.get(gate_profile)
    if profile is None:
        raise LatencyInputError(f"unsupported gate profile: {gate_profile}")
    if kind == KIND_TELEMETRY_STAGE:
        raise LatencyInputError("telemetry-stage samples cannot be used with a gate profile")
    expected_kind = profile["kind"]
    if kind != expected_kind:
        raise LatencyInputError(
            f"gate profile {gate_profile} requires --kind {expected_kind}, got {kind}"
        )
    expected_transport = profile["transport"]
    if expected_transport is not None and transport != expected_transport:
        raise LatencyInputError(
            f"gate profile {gate_profile} requires --transport {expected_transport}, got {transport}"
        )

    reasons: list[str] = []
    if kind == KIND_GLASS_TO_GLASS and measurement_method != METHOD_EXTERNAL_CAMERA:
        reasons.append("glass-to-glass gate requires external-camera measurement")
    sample_count = int(statistics_summary["count"])
    if sample_count < MIN_GATE_SAMPLE_COUNT:
        reasons.append(
            f"only {sample_count} samples provided; at least {MIN_GATE_SAMPLE_COUNT} are required"
        )
    threshold_ms = float(profile["threshold_ms"])
    p95_ms = float(statistics_summary["p95"])
    if reasons:
        verdict = "insufficient"
    elif p95_ms <= threshold_ms:
        verdict = "pass"
    else:
        verdict = "fail"
        reasons.append(f"p95 {p95_ms:.3f} ms exceeds threshold {threshold_ms:.3f} ms")

    return {
        "profile": gate_profile,
        "verdict": verdict,
        "metric": "p95",
        "threshold_ms": threshold_ms,
        "observed_ms": p95_ms,
        "min_sample_count": MIN_GATE_SAMPLE_COUNT,
        "sample_count": sample_count,
        "reasons": reasons,
    }


def summarize(
    rows: Sequence[dict[str, Any]],
    *,
    kind: str,
    measurement_method: str,
    transport: str,
    run_id: str | None = None,
    gate_profile: str | None = None,
) -> dict[str, Any]:
    """Validate measurement provenance and compute latency statistics."""
    if measurement_method == METHOD_UNSYNCHRONIZED_CLOCKS:
        raise LatencyInputError(
            "unsynchronized host/device timestamps cannot establish end-to-end latency; "
            "use one external-camera timebase for glass-to-glass evidence"
        )
    if kind in (KIND_GLASS_TO_GLASS, KIND_INPUT) and measurement_method in TELEMETRY_STAGE_METHODS:
        raise LatencyInputError(
            "host/client telemetry can only be summarized with --kind telemetry-stage; "
            "it cannot establish glass-to-glass or input event latency"
        )
    if kind == KIND_GLASS_TO_GLASS and measurement_method != METHOD_EXTERNAL_CAMERA:
        raise LatencyInputError(
            "glass-to-glass latency requires an external-camera measurement on one timebase; "
            "host/device timestamps are not glass-to-glass evidence"
        )
    if kind == KIND_TELEMETRY_STAGE and measurement_method not in TELEMETRY_STAGE_METHODS:
        raise LatencyInputError(
            "telemetry-stage latency requires --measurement-method host-telemetry "
            "or client-telemetry; it is informational and cannot close end-to-end gates"
        )
    if kind not in (KIND_GLASS_TO_GLASS, KIND_INPUT, KIND_TELEMETRY_STAGE):
        raise LatencyInputError(f"unsupported latency kind: {kind}")
    if measurement_method not in (
        METHOD_EXTERNAL_CAMERA,
        METHOD_SYNCHRONIZED_CLOCK,
        METHOD_HOST_TELEMETRY,
        METHOD_CLIENT_TELEMETRY,
    ):
        raise LatencyInputError(f"unsupported measurement method: {measurement_method}")
    if transport not in (TRANSPORT_USB, TRANSPORT_LAN):
        raise LatencyInputError(f"unsupported transport: {transport}")

    latencies = [_latency_from_sample(row, index) for index, row in enumerate(rows, start=1)]
    statistics_summary = {
        "count": len(latencies),
        "min": min(latencies),
        "max": max(latencies),
        "mean": statistics.fmean(latencies),
        "median": statistics.median(latencies),
        "p95": percentile(latencies, 0.95),
    }
    if kind == KIND_GLASS_TO_GLASS:
        evidence_kind = "glass_to_glass"
        gate_summary = {
            "can_close_performance_gate": True,
            "requires_external_hardware": True,
            "reason": "all samples were measured on one external-camera timebase",
        }
        status = "complete"
    elif kind == KIND_INPUT:
        evidence_kind = "input_latency"
        gate_summary = {
            "can_close_performance_gate": True,
            "requires_external_hardware": measurement_method == METHOD_EXTERNAL_CAMERA,
            "reason": "input samples use an accepted single timebase",
        }
        status = "complete"
    else:
        evidence_kind = "telemetry_stage_latency"
        gate_summary = {
            "can_close_performance_gate": False,
            "requires_external_hardware": False,
            "reason": (
                "host/client telemetry measures one clock domain or pipeline stage only; "
                "it can diagnose latency sources but cannot prove glass-to-glass or input latency"
            ),
        }
        status = "informational"

    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id or str(uuid.uuid4()),
        "kind": evidence_kind,
        "status": status,
        "latency_kind": kind,
        "measurement_method": measurement_method,
        "transport": transport,
        "unit": "ms",
        "gate": gate_summary,
        "metrics": statistics_summary,
        "statistics": statistics_summary,
        "samples_ms": latencies,
    }
    if gate_profile is not None:
        gate_result = _derive_gate_verdict(
            gate_profile=gate_profile,
            kind=kind,
            transport=transport,
            measurement_method=measurement_method,
            statistics_summary=statistics_summary,
        )
        summary["verdict"] = gate_result["verdict"]
        summary["gate"].update(gate_result)
    if kind == KIND_TELEMETRY_STAGE:
        stage_latencies: dict[str, list[float]] = {}
        for index, row in enumerate(rows, start=1):
            stage_latencies.setdefault(_stage_from_sample(row, index), []).append(latencies[index - 1])
        summary["stages"] = {
            stage: {
                "count": len(stage_values),
                "min": min(stage_values),
                "max": max(stage_values),
                "mean": statistics.fmean(stage_values),
                "median": statistics.median(stage_values),
                "p95": percentile(stage_values, 0.95),
            }
            for stage, stage_values in sorted(stage_latencies.items())
        }
    return summary


def _infer_input_format(path: str, explicit_format: str | None) -> str:
    if explicit_format:
        return explicit_format
    if path == "-":
        raise LatencyInputError("--input-format is required when reading from stdin")
    suffix = Path(path).suffix.lower()
    if suffix in (".csv", ".json"):
        return suffix[1:]
    raise LatencyInputError("cannot infer input format; use --input-format csv or json")


def _write_summary(summary: dict[str, Any], output_format: str, stream: TextIO) -> None:
    if output_format == "json":
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
        return

    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        ("schema_version", "run_id", "latency_kind", "transport", "measurement_method", "unit", "metric", "value")
    )
    for metric, value in summary["statistics"].items():
        writer.writerow(
            (
                summary["schema_version"],
                summary["run_id"],
                summary["latency_kind"],
                summary["transport"],
                summary["measurement_method"],
                summary["unit"],
                metric,
                value,
            )
        )
    if "verdict" in summary:
        for metric in (
            "profile",
            "verdict",
            "threshold_ms",
            "observed_ms",
            "min_sample_count",
            "sample_count",
        ):
            writer.writerow(
                (
                    summary["schema_version"],
                    summary["run_id"],
                    summary["latency_kind"],
                    summary["transport"],
                    summary["measurement_method"],
                    summary["unit"],
                    f"gate.{metric}",
                    summary["gate"][metric],
                )
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize raw glass-to-glass or input latency samples.",
        epilog=(
            "CSV/JSON samples contain either latency_ms, or start_frame, end_frame, "
            "and camera_fps. Telemetry-stage samples also require stage. "
            "Glass-to-glass claims require --measurement-method external-camera."
        ),
    )
    parser.add_argument("input", help="raw .csv/.json file, or - for stdin")
    parser.add_argument(
        "--kind", choices=(KIND_GLASS_TO_GLASS, KIND_INPUT, KIND_TELEMETRY_STAGE), required=True
    )
    parser.add_argument("--transport", choices=(TRANSPORT_USB, TRANSPORT_LAN), required=True)
    parser.add_argument(
        "--measurement-method",
        choices=(
            METHOD_EXTERNAL_CAMERA,
            METHOD_SYNCHRONIZED_CLOCK,
            METHOD_HOST_TELEMETRY,
            METHOD_CLIENT_TELEMETRY,
            METHOD_UNSYNCHRONIZED_CLOCKS,
        ),
        required=True,
    )
    parser.add_argument("--input-format", choices=("csv", "json"))
    parser.add_argument("--output-format", choices=("json", "csv"), default="json")
    parser.add_argument("--output", help="output file (default: stdout)")
    parser.add_argument("--run-id", help="identifier shared with the evidence manifest")
    parser.add_argument(
        "--gate-profile",
        choices=tuple(GATE_PROFILES),
        help=(
            "optional performance gate to evaluate: usb-glass-to-glass-sub50, "
            "lan-glass-to-glass-sub80, or input-p95-sub50"
        ),
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        input_format = _infer_input_format(args.input, args.input_format)
        if args.input == "-":
            rows = load_samples(sys.stdin, input_format)
        else:
            try:
                with Path(args.input).open("r", encoding="utf-8", newline="") as stream:
                    rows = load_samples(stream, input_format)
            except OSError as error:
                raise LatencyInputError(f"cannot read {args.input}: {error}") from error

        summary = summarize(
            rows,
            kind=args.kind,
            measurement_method=args.measurement_method,
            transport=args.transport,
            run_id=args.run_id,
            gate_profile=args.gate_profile,
        )
        if args.output:
            try:
                with Path(args.output).open("w", encoding="utf-8", newline="") as stream:
                    _write_summary(summary, args.output_format, stream)
            except OSError as error:
                raise LatencyInputError(f"cannot write {args.output}: {error}") from error
        else:
            _write_summary(summary, args.output_format, sys.stdout)
    except LatencyInputError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
