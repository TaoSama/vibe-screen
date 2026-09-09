from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import datetime as _datetime
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.phase0_stable_release import (
    REQUIRED_GATE_IDS,
    Phase0StableReleaseError,
    _release_claim_checkout_reasons,
    _write_summary,
    evaluate_manifest,
)
from tools.tests.latency_test_helpers import minimal_mov
from tools.tests.test_host_rss_gate import (
    host_readiness_payload,
    write_host_readiness,
    write_exact_window_report,
    write_inputs as write_host_rss_inputs,
)
from vibescreen_evidence.host_rss_gate import derive_gate as derive_host_rss_gate
from vibescreen_evidence.file_transfer_android_smoke import (
    derive_gate as derive_file_transfer_android_smoke_gate,
)
from vibescreen_evidence.clipboard_e2e_gate import (
    derive_gate as derive_clipboard_e2e_gate,
)
from tools.tests.test_file_transfer_android_smoke import (
    write_pass_inputs as write_file_transfer_pass_inputs,
)
from tools.tests.test_clipboard_e2e_gate import (
    write_pass_inputs as write_clipboard_pass_inputs,
)
from tools.tests.test_macos_hardware_compatibility import (
    complete_record as complete_macos_hardware_compatibility_record,
)
from vibescreen_evidence.macos_hardware_compatibility import (
    summarize as summarize_macos_hardware_compatibility,
)
from vibescreen_evidence.native_pointer_hid import (
    summarize as summarize_native_pointer_hid,
)
from vibescreen_evidence.controller_runtime import (
    summarize as summarize_controller_runtime,
)


MODULE = "vibescreen_evidence.phase0_stable_release"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "phase0-stable-release.schema.json"
MANIFEST_SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "phase0-stable-release-manifest.schema.json"
)
REPO_ROOT = Path(__file__).parents[2]
GUARDED_README_TEXT = (
    "Phase 0 remains in progress and this is a development preview "
    "rather than a stable release. Do not treat roadmap items below "
    "as shipped features."
)
COMPLETE_MANIFEST_STRENGTHS = {
    "upstream_provenance_and_license": "current-source",
    "protocol_contract_ci": "current-ci",
    "android_clean_build": "current-ci",
    "macos_release_build_xcode_tests": "current-ci",
    "macos_host_hardware_compatibility_matrix": "current-real-device",
    "android_device_usb_stream_reconnect_codec": "current-real-device",
    "telemetry_and_latency_archive": "current-real-device",
    "host_rss_2h_no_growth": "current-real-device",
    "native_pointer_hid_mouse": "current-real-device",
    "controller_runtime_acceptance": "current-real-device",
    "clipboard_android_macos_product_e2e": "current-real-device",
    "file_transfer_android_product_e2e": "current-real-device",
    "module_ownership_extraction": "current-source",
}
MERGED_PR_COMMAND = (
    "gh pr list --repo TaoSama/vibe-screen --state merged --base main "
    "--limit 100 --json number,title,baseRefName,mergeCommit,url"
)


def gate_by_id(manifest: dict[str, object], gate_id: str) -> dict[str, object]:
    gates = manifest["required_gates"]
    assert isinstance(gates, list)
    for gate in gates:
        assert isinstance(gate, dict)
        if gate["id"] == gate_id:
            return gate
    raise AssertionError(f"missing gate {gate_id}")


def complete_manifest() -> dict[str, object]:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase0_stable_release_closure",
        "phase": "phase0",
        "source": {
            "base_commit": "abc123",
            "base_ref": "origin/main",
            "audit_date": "2026-08-22",
            "owner": "Vibe Screen core team",
            "audit_source": "docs/audit.md",
        },
        "open_pr_snapshot": {
            "repository": "TaoSama/vibe-screen",
            "command": "gh pr list --repo TaoSama/vibe-screen --state open --limit 200 --json number,title,headRefName,headRefOid,baseRefName,updatedAt,isDraft,mergeStateStatus,url",
            "queried_at": "2026-08-22",
            "state": "open",
            "open_pr_numbers": [],
        },
        "required_gates": [
            {
                "id": gate_id,
                "title": gate_id.replace("_", " "),
                "verdict": "pass",
                "required_for_stable_release": True,
                "evidence_strength": COMPLETE_MANIFEST_STRENGTHS[gate_id],
                "evidence_paths": [f"docs/evidence/{gate_id}.json"],
                "owner_prs": [],
                "blockers": [],
            }
            for gate_id in REQUIRED_GATE_IDS
        ],
    }


def commit_all(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Phase 0 Test",
            "-c",
            "user.email=phase0@example.invalid",
            "commit",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()


def commit_tree(repo: Path, commit: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", f"{commit}^{{tree}}"], cwd=repo, text=True
    ).strip()


def with_temporary_repo(callback: Callable[[Path, str], None]) -> None:
    with tempfile.TemporaryDirectory() as directory_name:
        repo = Path(directory_name)
        subprocess.run(
            ["git", "init", "--initial-branch=main"],
            cwd=repo,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        (repo / "README.md").write_text(GUARDED_README_TEXT, encoding="utf-8")
        base_commit = commit_all(repo, "base")
        callback(repo, base_commit)


def add_merged_pr_snapshot(
    manifest: dict[str, object],
    repo: Path,
    audited_source_commit: str,
    *,
    merge_commit: str | None = None,
    entry_base: str = "main",
    excluded_pr_numbers: list[int] | None = None,
    maximum: int = 158,
    path: str = "merged-prs.jsonl",
) -> None:
    snapshot_path = repo / path
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps({
            "number": 158,
            "title": "Merged owner",
            "baseRefName": entry_base,
            "mergeCommit": {"oid": merge_commit or audited_source_commit},
            "url": "https://github.com/TaoSama/vibe-screen/pull/158",
        })
        + "\n",
        encoding="utf-8",
    )
    manifest["merged_pr_snapshot"] = {
        "repository": "TaoSama/vibe-screen",
        "command": MERGED_PR_COMMAND,
        "state": "merged",
        "base": "main",
        "range": {"min": 158, "max": maximum},
        "path": path,
        "audited_source_commit": audited_source_commit,
        "excluded_pr_numbers": excluded_pr_numbers or [],
    }


def write_latency_archive_evidence(
    repo: Path,
    *,
    latency_path: str = "docs/evidence/latency-evidence-usb.json",
    live_smoke_path: str = "docs/evidence/android-usb-live-smoke.json",
) -> list[str]:
    evidence_dir = repo / "docs" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    raw_video_file = evidence_dir / "raw-camera-capture.mov"
    samples_file = evidence_dir / "samples.csv"
    usb_artifact_file = evidence_dir / "usb-connection.txt"
    manifest_file = evidence_dir / "latency-manifest.json"
    raw_video_file.write_bytes(minimal_mov(b"phase0-aggregate-real-shaped-video"))
    samples_file.write_text(
        "start_frame,end_frame,camera_fps\n"
        "10,18,240\n110,119,240\n210,219,240\n"
        "310,319,240\n410,419,240\n",
        encoding="utf-8",
    )
    usb_artifact_file.write_text(
        "adb reverse tcp:54321 tcp:54321\nactive usb stream observed on real device\n",
        encoding="utf-8",
    )
    manifest_file.write_text(
        json.dumps(
            {
                "schema_version": "vibescreen.evidence/v1",
                "run_id": "phase0-aggregate-latency-package",
                "latency_kind": "glass-to-glass",
                "transport": "usb",
                "measurement_method": "external-camera",
                "gate_profile": "usb-glass-to-glass-sub50",
                "evidence_provenance": {
                    "source": "real-device-capture",
                    "collection_context": "bench capture in the current latency lab",
                    "operator_assertion": "This package records a retained device capture run.",
                    "current_base": {
                        "repository_revision": "b9070c0b558aaf9dbe6f3e39a98359ea53f7ad71",
                        "source_tree": "c1a2b3c4d5e6f7890abcdeffedcba09876543210",
                        "dirty": False,
                    },
                },
                "camera": {
                    "manufacturer": "Bench Camera Co",
                    "model": "Retained 240",
                    "mode": "1080p240",
                    "frame_rate_fps": 240,
                    "shutter_mode": "fixed",
                },
                "recording": {
                    "raw_video": raw_video_file.name,
                    "recorded_at": "2026-08-21T00:00:00Z",
                    "operator": "bench operator",
                    "sha256": hashlib.sha256(raw_video_file.read_bytes()).hexdigest(),
                    "container": "mov",
                    "file_size_bytes": raw_video_file.stat().st_size,
                    "frame_count": 600,
                    "duration_ms": 2500,
                },
                "samples": {
                    "file": samples_file.name,
                    "format": "csv",
                    "sha256": hashlib.sha256(samples_file.read_bytes()).hexdigest(),
                    "annotation_method": "manual-frame-count",
                    "annotator": "bench annotator",
                },
                "device": {
                    "manufacturer": "nubia",
                    "model": "P0110",
                    "codename": "pacific",
                    "os_version": "Android 16 / SDK 36",
                    "sdk": 36,
                    "build_fingerprint": "nubia/pacific/pacific:16/test-keys",
                },
                "host": {"model": "Mac16,8", "macos_version": "26.4.1"},
                "build": {
                    "repository_revision": "b9070c0b558aaf9dbe6f3e39a98359ea53f7ad71",
                    "source_tree": "c1a2b3c4d5e6f7890abcdeffedcba09876543210",
                    "source_dirty": False,
                    "host_artifact": "Vibe Screen.app sha256 retained in commands.txt",
                    "host_artifact_sha256": "a" * 64,
                    "host_artifact_provenance": "codesign and sha256 retained in commands.txt",
                    "client_artifact": "app-debug.apk sha256 retained in commands.txt",
                    "client_artifact_sha256": "b" * 64,
                    "client_artifact_provenance": "APK sha256 retained in commands.txt",
                },
                "measurement_setup": {
                    "stimulus": "mac display flash visible to the camera",
                    "start_event_definition": "first camera frame where the Mac stimulus changes",
                    "end_event_definition": "first camera frame where the Android render shows the same change",
                    "lighting": "stable indoor light",
                    "mounting": "fixed tripod framing both screens",
                    "clock_domain": "single-external-camera-timebase",
                    "max_frame_annotation_uncertainty_ms": 4.2,
                    "notes": "Bench validation package with retained artifacts.",
                },
                "gate_artifacts": {
                    "usb_connection": {
                        "file": usb_artifact_file.name,
                        "sha256": hashlib.sha256(usb_artifact_file.read_bytes()).hexdigest(),
                        "description": "USB active-stream proof.",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    latency_file = repo / latency_path
    latency_file.parent.mkdir(parents=True, exist_ok=True)
    latency_file.write_text(
        json.dumps(
            {
                "schema_version": "vibescreen.evidence/v1",
                "kind": "latency_evidence_gate",
                "status": "complete",
                "derivation_status": "complete",
                "verdict": "pass",
                "latency_kind": "glass-to-glass",
                "transport": "usb",
                "measurement_method": "external-camera",
                "gate": {
                    "profile": "usb-glass-to-glass-sub50",
                    "can_close_performance_gate": True,
                    "summary_verdict": "pass",
                    "threshold_ms": 50.0,
                    "observed_ms": 37.5,
                    "observed_with_uncertainty_ms": 45.9,
                    "sample_count": 5,
                    "min_sample_count": 5,
                    "requires_external_hardware": True,
                    "reasons": [],
                },
                "source": {"manifest": "docs/evidence/latency-manifest.json"},
            }
        ),
        encoding="utf-8",
    )

    live_smoke_file = repo / live_smoke_path
    live_smoke_file.parent.mkdir(parents=True, exist_ok=True)
    live_smoke_file.write_text(
        json.dumps(
            {
                "schema_version": "vibescreen.evidence/v1",
                "kind": "android_usb_live_smoke",
                "verdict": "pass",
                "device": {
                    "identity": {
                        "manufacturer": "nubia",
                        "model": "P0110",
                        "device": "pacific",
                    }
                },
                "claims": {"live_usb_stream_observed": True},
                "logs": {
                    "telemetry": {
                        "session_epochs": [9],
                        "stream_stats": {
                            "count": 3,
                            "positive_fps_count": 3,
                            "non_positive_fps_count": 0,
                            "latest": {
                                "session_epoch": 9,
                                "fps": 60.0,
                                "dropped_frames": 0,
                            },
                        },
                        "frame_drops": {"max_dropped_total": 0},
                    },
                    "decoder": {
                        "latest_output_counter": 180,
                        "latest_decode_stats": {"output": 180, "dropped": 0},
                        "latest_output_latency": {
                            "avg_ms": 6.1,
                            "max_ms": 11.0,
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return [latency_path, live_smoke_path]


def write_synchronized_clock_latency_evidence(
    repo: Path,
    *,
    include_sync_artifact: bool = True,
    mutate_manifest: Callable[[dict[str, object]], None] | None = None,
    latency_path: str = "docs/evidence/latency-evidence-usb.json",
) -> str:
    evidence_dir = repo / "docs" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    samples_file = evidence_dir / "sync-samples.csv"
    input_artifact_file = evidence_dir / "input-actuation.txt"
    sync_artifact_file = evidence_dir / "synchronization-record.txt"
    manifest_file = evidence_dir / "sync-latency-manifest.json"
    samples_file.write_text(
        "latency_ms\n13.1\n18.3\n15.1\n22.4\n19.7\n",
        encoding="utf-8",
    )
    input_artifact_file.write_text(
        "physical input actuation visible; visible mac-side result recorded\n",
        encoding="utf-8",
    )
    sync_artifact_file.write_text(
        "clock synchronization proof: before skew, after skew, drift, "
        "input timestamp uncertainty, result timestamp uncertainty, "
        "total error budget\n",
        encoding="utf-8",
    )
    gate_artifacts: dict[str, object] = {
        "input_actuation_record": {
            "file": input_artifact_file.name,
            "sha256": hashlib.sha256(input_artifact_file.read_bytes()).hexdigest(),
            "description": "Physical input proof.",
        }
    }
    if include_sync_artifact:
        gate_artifacts["synchronization_record"] = {
            "file": sync_artifact_file.name,
            "sha256": hashlib.sha256(sync_artifact_file.read_bytes()).hexdigest(),
            "description": "Clock synchronization proof.",
        }
    manifest_document: dict[str, object] = {
        "schema_version": "vibescreen.evidence/v1",
        "run_id": "phase0-sync-input-package",
        "latency_kind": "input",
        "transport": "usb",
        "measurement_method": "synchronized-clock",
        "gate_profile": "input-p95-sub50",
        "evidence_provenance": {
            "source": "real-device-capture",
            "collection_context": "bench input capture with synchronized clocks",
            "operator_assertion": "This package records retained physical input evidence.",
            "current_base": {
                "repository_revision": "b9070c0b558aaf9dbe6f3e39a98359ea53f7ad71",
                "source_tree": "c1a2b3c4d5e6f7890abcdeffedcba09876543210",
                "dirty": False,
            },
        },
        "synchronization": {
            "host_clock_source": "macOS monotonic clock",
            "device_clock_source": "Android elapsedRealtimeNanos",
            "sync_procedure": "retained round-trip calibration",
            "before_skew_ms": 1.2,
            "after_skew_ms": 1.5,
            "max_drift_ms": 0.8,
            "input_timestamp_uncertainty_ms": 0.4,
            "result_timestamp_uncertainty_ms": 0.0,
            "total_error_budget_ms": 4.5,
            "input_timestamp_method": (
                "Android MotionEvent eventTime plus physical acquisition bound"
            ),
            "result_timestamp_method": "macOS visible result timestamp",
        },
        "samples": {
            "file": samples_file.name,
            "format": "csv",
            "sha256": hashlib.sha256(samples_file.read_bytes()).hexdigest(),
            "annotation_method": "direct-latency-ms",
            "annotator": "bench annotator",
        },
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "os_version": "Android 16 / SDK 36",
            "sdk": 36,
            "build_fingerprint": "nubia/pacific/pacific:16/test-keys",
        },
        "host": {"model": "Mac16,8", "macos_version": "26.4.1"},
        "build": {
            "repository_revision": "b9070c0b558aaf9dbe6f3e39a98359ea53f7ad71",
            "source_tree": "c1a2b3c4d5e6f7890abcdeffedcba09876543210",
            "source_dirty": False,
            "host_artifact": "Vibe Screen.app sha256 retained in commands.txt",
            "host_artifact_sha256": "a" * 64,
            "host_artifact_provenance": "codesign and sha256 retained in commands.txt",
            "client_artifact": "app-debug.apk sha256 retained in commands.txt",
            "client_artifact_sha256": "b" * 64,
            "client_artifact_provenance": "APK sha256 retained in commands.txt",
        },
        "measurement_setup": {
            "stimulus": "physical touch on Android screen",
            "start_event_definition": "Android physical input timestamp",
            "end_event_definition": "visible Mac-side result timestamp",
            "lighting": "n/a",
            "mounting": "n/a",
            "clock_domain": "synchronized-host-device-clocks",
            "notes": "Synchronized-clock input package.",
        },
        "gate_artifacts": gate_artifacts,
    }
    if mutate_manifest is not None:
        mutate_manifest(manifest_document)
    manifest_file.write_text(json.dumps(manifest_document), encoding="utf-8")

    latency_file = repo / latency_path
    latency_file.parent.mkdir(parents=True, exist_ok=True)
    latency_file.write_text(
        json.dumps(
            {
                "schema_version": "vibescreen.evidence/v1",
                "kind": "latency_evidence_gate",
                "status": "complete",
                "derivation_status": "complete",
                "verdict": "pass",
                "latency_kind": "input",
                "transport": "usb",
                "measurement_method": "synchronized-clock",
                "gate": {
                    "profile": "input-p95-sub50",
                    "can_close_performance_gate": True,
                    "summary_verdict": "pass",
                    "threshold_ms": 50.0,
                    "observed_ms": 22.4,
                    "observed_with_uncertainty_ms": 26.9,
                    "sample_count": 5,
                    "min_sample_count": 5,
                    "requires_external_hardware": True,
                    "reasons": [],
                },
                "source": {"manifest": "docs/evidence/sync-latency-manifest.json"},
            }
        ),
        encoding="utf-8",
    )
    return latency_path


def write_host_rss_gate_evidence(
    repo: Path,
    *,
    output_path: str = "docs/evidence/host-rss-gate.json",
    source_directory: str = "docs/evidence/host-rss",
) -> str:
    source_dir = repo / source_directory
    source_dir.mkdir(parents=True, exist_ok=True)
    summary_path, samples_path = write_host_rss_inputs(
        source_dir,
        rss_at_minute=lambda minute: 120_000.0
        + (128.0 if int(minute * 2) % 2 else -128.0),
    )
    exact_window_path = write_exact_window_report(source_dir)
    host_readiness_path = write_host_readiness(source_dir)
    report = derive_host_rss_gate(
        summary_path,
        samples_path,
        exact_window_path,
        host_readiness_path,
    )
    report["source"] = {
        "summary": f"{source_directory}/summary.json",
        "samples": f"{source_directory}/samples.jsonl",
        "exact_window_report": f"{source_directory}/exact-window-report.json",
        "host_readiness": f"{source_directory}/host-readiness.json",
    }
    output_file = repo / output_path
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report), encoding="utf-8")
    return output_path


def write_clipboard_gate_evidence(
    repo: Path,
    *,
    output_path: str = "docs/evidence/clipboard-e2e-gate.json",
    source_directory: str = "docs/evidence/clipboard-e2e",
    mutate_product_source: Callable[[dict[str, object]], None] | None = None,
    mutate: Callable[[dict[str, object]], None] | None = None,
) -> str:
    source_dir = repo / source_directory
    paths = write_clipboard_pass_inputs(source_dir)
    product_record = json.loads(paths["product"].read_text(encoding="utf-8"))
    if mutate_product_source is not None:
        mutate_product_source(product_record)
        paths["product"].write_text(json.dumps(product_record), encoding="utf-8")
    report = derive_clipboard_e2e_gate(
        host_readiness=paths["host"],
        usb_preflight=paths["usb"],
        trusted_lan_preflight=paths["lan"],
        android_clipboard_instrumentation_log=paths["android_log"],
        product_e2e=paths["product"],
        repo_root=repo,
    )
    if mutate is not None:
        mutate(report)
    output_file = repo / output_path
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report), encoding="utf-8")
    return output_path


def mutate_clipboard_product_source(
    repo: Path,
    report_path: str,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    report = json.loads((repo / report_path).read_text(encoding="utf-8"))
    source = report["source"]
    assert isinstance(source, dict)
    product_ref = source["product_e2e"]
    assert isinstance(product_ref, str)
    product_path = repo / product_ref
    product = json.loads(product_path.read_text(encoding="utf-8"))
    mutate(product)
    product_path.write_text(json.dumps(product), encoding="utf-8")


def write_file_transfer_android_gate_evidence(
    repo: Path,
    *,
    output_path: str = "docs/evidence/file-transfer-android-smoke-gate.json",
    source_directory: str = "docs/evidence/file-transfer-android-smoke",
    mutate_report: Callable[[dict[str, object]], None] | None = None,
) -> str:
    source_dir = repo / source_directory
    paths = write_file_transfer_pass_inputs(source_dir)
    report = derive_file_transfer_android_smoke_gate(
        host_readiness=paths["host"],
        usb_preflight=paths["usb"],
        trusted_lan_preflight=paths["lan"],
        android_file_transfer_instrumentation_log=paths["android_log"],
        product_e2e=paths["product"],
        repo_root=repo,
    )
    if mutate_report is not None:
        mutate_report(report)
    output_file = repo / output_path
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report), encoding="utf-8")
    return output_path


def write_macos_hardware_compatibility_evidence(
    repo: Path,
    *,
    repository_commit: str,
    repository_tree: str | None = None,
    source_directory: str = "docs/evidence/macos-host-compatibility",
    output_path: str | None = None,
    mutate_input: Callable[[dict[str, object]], None] | None = None,
    mutate_report: Callable[[dict[str, object]], None] | None = None,
) -> str:
    if output_path is None:
        output_path = f"{source_directory}/macos-hardware-compatibility-gate.json"
    source_dir = repo / source_directory
    source_dir.mkdir(parents=True, exist_ok=True)
    record = complete_macos_hardware_compatibility_record()
    if repository_tree is None:
        repository_tree = commit_tree(repo, repository_commit)
    record.update({
        "repository_commit": repository_commit,
        "repository_tree": repository_tree,
        "host_source_commit": repository_commit,
        "host_source_tree": repository_tree,
        "host_self_test_commit": repository_commit,
        "current_base_commit": repository_commit,
        "current_base_tree": repository_tree,
    })
    if mutate_input is not None:
        mutate_input(record)
    for artifact_path in record["artifact_paths"]:
        (source_dir / str(artifact_path)).write_text(
            f"{artifact_path} evidence\n", encoding="utf-8"
        )
    input_path = source_dir / "macos-hardware-compatibility.json"
    input_path.write_text(json.dumps(record), encoding="utf-8")
    report = summarize_macos_hardware_compatibility(record, evidence_dir=source_dir)
    if mutate_report is not None:
        mutate_report(report)
    output_file = repo / output_path
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report), encoding="utf-8")
    return output_path


def write_native_pointer_hid_evidence(
    repo: Path,
    *,
    output_path: str = "docs/evidence/native-pointer-hid/native-pointer-hid-summary.json",
    mutate_report: Callable[[dict[str, object]], None] | None = None,
) -> str:
    evidence_dir = (repo / output_path).parent
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for artifact_name in (
        "result.json",
        "dumpsys-input.txt",
        "android-logcat-native-pointer.txt",
        "host-log-appended.txt",
    ):
        (evidence_dir / artifact_name).write_text(
            f"{artifact_name} evidence\n", encoding="utf-8"
        )
    record: dict[str, object] = {
        "status": "passed",
        "reason": "All required native pointer evidence was observed.",
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "device": "pacific",
            "android_release": "16",
            "sdk": "36",
        },
        "external_mouse_devices": [
            {
                "device_id": 11,
                "name": "USB Mouse",
                "sources": "MOUSE",
                "is_external": "true",
            }
        ],
        "required_pointer_events": ["move", "press", "release"],
        "observed_android_pointer_events": ["move", "press", "release"],
        "observed_android_pointer_device_ids_by_event": {
            "move": [11],
            "press": [11],
            "release": [11],
        },
        "observed_host_pointer_events": ["move", "press", "release"],
        "host_stable_signed_tcc_ready": True,
        "visible_mac_result": "Mac cursor moved and primary click focused TextEdit.",
        "android_logcat_bytes": 200,
        "host_log_appended_bytes": 180,
        "host_log": "host-log-appended.txt",
    }
    report = summarize_native_pointer_hid(
        record, run_id="phase0-native-pointer", source_path=Path("result.json")
    )
    if mutate_report is not None:
        mutate_report(report)
    output_file = repo / output_path
    output_file.write_text(json.dumps(report), encoding="utf-8")
    return output_path


def write_controller_runtime_evidence(
    repo: Path,
    *,
    output_path: str = "docs/evidence/controller-runtime/controller-runtime-summary.json",
    mutate_report: Callable[[dict[str, object]], None] | None = None,
) -> str:
    evidence_dir = (repo / output_path).parent
    evidence_dir.mkdir(parents=True, exist_ok=True)
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
    for artifact_path in artifact_paths:
        (evidence_dir / artifact_path).write_text(
            f"{artifact_path} evidence\n", encoding="utf-8"
        )
    record: dict[str, object] = {field: True for field in (
        "device_identity_recorded",
        "apk_identity_recorded",
        "physical_controller_attached",
        "android_controller_source_observed",
        "protocol_controller_capability_negotiated",
        "android_production_forwarding_observed",
        "controller_connected_state_disconnected_observed",
        "host_identity_signed",
        "host_virtual_hid_entitlement_present",
        "host_virtual_gamepad_available",
        "mac_side_controller_response_observed",
        "neutral_release_on_disconnect_observed",
    )}
    record["artifact_paths"] = artifact_paths
    record["observation_artifacts"] = {
        "device_identity_recorded": ["device-info.json", "adb-devices.txt"],
        "apk_identity_recorded": ["dumpsys-package-apk.txt"],
        "physical_controller_attached": ["dumpsys-input.txt"],
        "android_controller_source_observed": [
            "dumpsys-input.txt",
            "android-controller-logcat.txt",
        ],
        "protocol_controller_capability_negotiated": [
            "protocol-controller-envelopes.jsonl"
        ],
        "android_production_forwarding_observed": ["android-controller-logcat.txt"],
        "controller_connected_state_disconnected_observed": [
            "controller-lifecycle.jsonl"
        ],
        "host_identity_signed": ["host-codesign.txt"],
        "host_virtual_hid_entitlement_present": ["host-codesign.txt"],
        "host_virtual_gamepad_available": ["host-controller-availability.txt"],
        "mac_side_controller_response_observed": ["mac-controller-observer.txt"],
        "neutral_release_on_disconnect_observed": ["neutral-release.txt"],
    }
    report = summarize_controller_runtime(
        record, run_id="phase0-controller-runtime"
    )
    if mutate_report is not None:
        mutate_report(report)
    output_file = repo / output_path
    output_file.write_text(json.dumps(report), encoding="utf-8")
    return output_path


def attach_file_transfer_android_gate_evidence(manifest: dict[str, object], repo: Path) -> None:
    gate_by_id(manifest, "file_transfer_android_product_e2e")["evidence_paths"] = [
        write_file_transfer_android_gate_evidence(repo)
    ]


def attach_hardware_runtime_gate_evidence(manifest: dict[str, object], repo: Path) -> None:
    gate_by_id(manifest, "native_pointer_hid_mouse")["evidence_paths"] = [
        write_native_pointer_hid_evidence(repo)
    ]
    gate_by_id(manifest, "controller_runtime_acceptance")["evidence_paths"] = [
        write_controller_runtime_evidence(repo)
    ]


def file_transfer_gate_issues(summary: dict[str, object]) -> list[str]:
    blocking_gates = summary["blocking_required_gates"]
    assert isinstance(blocking_gates, list)
    blocking_gate = next(
        item
        for item in blocking_gates
        if isinstance(item, dict) and item["id"] == "file_transfer_android_product_e2e"
    )
    issues = blocking_gate["issues"]
    assert isinstance(issues, list)
    assert all(isinstance(issue, str) for issue in issues)
    return issues


def mutate_file_transfer_product_source(
    repo: Path,
    report_path: str,
    mutate_product: Callable[[dict[str, object]], None],
) -> None:
    report = json.loads((repo / report_path).read_text(encoding="utf-8"))
    source = report["source"]
    assert isinstance(source, dict)
    product_e2e_ref = source["product_e2e"]
    assert isinstance(product_e2e_ref, str)
    product_path = repo / product_e2e_ref
    product = json.loads(product_path.read_text(encoding="utf-8"))
    mutate_product(product)
    product_path.write_text(json.dumps(product), encoding="utf-8")


def complete_manifest_for_repo(repo: Path, audited_source_commit: str) -> dict[str, object]:
    manifest = complete_manifest()
    manifest["source"]["base_commit"] = audited_source_commit
    gate_by_id(manifest, "telemetry_and_latency_archive")["evidence_paths"] = (
        write_latency_archive_evidence(repo)
    )
    gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")[
        "evidence_paths"
    ] = [
        write_macos_hardware_compatibility_evidence(
            repo, repository_commit=audited_source_commit
        )
    ]
    gate_by_id(manifest, "host_rss_2h_no_growth")["evidence_paths"] = [
        write_host_rss_gate_evidence(repo)
    ]
    gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
        write_clipboard_gate_evidence(repo)
    ]
    attach_hardware_runtime_gate_evidence(manifest, repo)
    attach_file_transfer_android_gate_evidence(manifest, repo)
    add_merged_pr_snapshot(manifest, repo, audited_source_commit)
    return manifest


class Phase0StableReleaseTest(unittest.TestCase):
    def test_pass_requires_all_required_gates(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)

            summary = evaluate_manifest(
                manifest,
                readme_text="Phase 0 stable-release summary",
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "pass")
            self.assertTrue(summary["can_mark_phase0_stable_release"])
            self.assertEqual(summary["blocking_required_gates"], [])
            self.assertEqual(summary["source_guard"]["verdict"], "pass")
            self.assertEqual(summary["owner_pr_guard"]["verdict"], "pass")
            self.assertEqual(summary["merged_pr_guard"]["verdict"], "pass")

        with_temporary_repo(run)

    def test_open_sub_gate_blocks_aggregate_without_failing_readme_guard(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "host_rss_2h_no_growth")
            gate["verdict"] = "blocked"
            gate["evidence_strength"] = "readiness"
            gate["evidence_paths"] = []
            gate["blockers"] = ["host_rss_gate has no current-source pass"]

            summary = evaluate_manifest(
                manifest, readme_text=GUARDED_README_TEXT, repo_root=repo
            )

            self.assertEqual(summary["aggregate_verdict"], "blocked")
            self.assertFalse(summary["can_mark_phase0_stable_release"])
            self.assertEqual(
                [gate["id"] for gate in summary["blocking_required_gates"]],
                ["host_rss_2h_no_growth"],
            )
            self.assertEqual(summary["readme_guard"]["verdict"], "pass")
            self.assertIn(
                "host_rss_2h_no_growth: host_rss_gate has no current-source pass",
                summary["reasons"],
            )

        with_temporary_repo(run)

    def test_readme_guard_fails_on_premature_shipped_claim(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "native_pointer_hid_mouse")
        gate["verdict"] = "open"
        gate["evidence_strength"] = "readiness"

        summary = evaluate_manifest(
            manifest,
            readme_text="Phase 0 is complete and ready as a stable release.",
        )

        self.assertEqual(summary["aggregate_verdict"], "fail")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["readme_guard"]["verdict"], "fail")
        self.assertTrue(summary["readme_guard"]["forbidden_matches"])

    def test_pass_with_readiness_strength_is_insufficient(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "upstream_provenance_and_license")
        gate["evidence_strength"] = "readiness"

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertIn(
            "closing evidence strength",
            summary["gate_summaries"][0]["issues"][0],
        )

    def test_pass_requires_allowlisted_closing_evidence_strength(self) -> None:
        non_closing_strengths = (
            "partial",
            "historical-fail",
            "partial-current-source",
        )
        for evidence_strength in non_closing_strengths:
            with self.subTest(evidence_strength=evidence_strength):
                def run(repo: Path, base_commit: str) -> None:
                    manifest = complete_manifest_for_repo(repo, base_commit)
                    gate = gate_by_id(manifest, "host_rss_2h_no_growth")
                    gate["evidence_strength"] = evidence_strength

                    summary = evaluate_manifest(
                        manifest, readme_text=GUARDED_README_TEXT, repo_root=repo
                    )

                    self.assertEqual(summary["aggregate_verdict"], "insufficient")
                    self.assertFalse(summary["can_mark_phase0_stable_release"])
                    self.assertEqual(
                        [gate["id"] for gate in summary["blocking_required_gates"]],
                        ["host_rss_2h_no_growth"],
                    )

                with_temporary_repo(run)

    def test_runtime_gate_requires_gate_specific_closing_strength(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "native_pointer_hid_mouse")
            gate["evidence_strength"] = "current-source"

            summary = evaluate_manifest(
                manifest, readme_text=GUARDED_README_TEXT, repo_root=repo
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            self.assertFalse(summary["can_mark_phase0_stable_release"])
            self.assertEqual(
                [gate["id"] for gate in summary["blocking_required_gates"]],
                ["native_pointer_hid_mouse"],
            )
            self.assertIn(
                "closing evidence strength for this gate",
                summary["blocking_required_gates"][0]["issues"][0],
            )

        with_temporary_repo(run)

    def test_retained_real_device_strength_only_closes_android_baseline_gate(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "android_device_usb_stream_reconnect_codec")
            gate["evidence_strength"] = "real-device"

            summary = evaluate_manifest(
                manifest,
                readme_text="Phase 0 stable-release summary",
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "pass")
            self.assertTrue(summary["can_mark_phase0_stable_release"])

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_pass_requires_formal_gate_report(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            summary_path = repo / "docs" / "evidence" / "no-host-transfer-controls-summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps(
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "kind": "file_transfer_no_host_ui_summary",
                        "verdict": "pass",
                        "no_host_ui_only": True,
                    }
                ),
                encoding="utf-8",
            )
            gate = gate_by_id(manifest, "file_transfer_android_product_e2e")
            gate["evidence_paths"] = ["docs/evidence/no-host-transfer-controls-summary.json"]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            blocking_gate = next(
                item for item in summary["blocking_required_gates"] if item["id"] == "file_transfer_android_product_e2e"
            )
            self.assertTrue(
                any("formal android_macos_file_transfer_smoke gate report" in issue for issue in blocking_gate["issues"]),
                blocking_gate["issues"],
            )
            self.assertTrue(
                any("formal file-transfer report kind must be android_macos_file_transfer_smoke" in issue for issue in blocking_gate["issues"]),
                blocking_gate["issues"],
            )

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_pass_requires_safety_closure_and_passing_checks(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_file_transfer_android_gate_evidence(
                repo,
                output_path="docs/evidence/file-transfer-mutated-gate.json",
                mutate_report=lambda report: (
                    report["safety"].pop("no_host_ui_evidence_do_not_close_gate"),
                    report["product_e2e_closure"].pop("same_session_id_required"),
                    next(
                        check for check in report["checks"] if check["name"] == "bidirectional_product_e2e"
                    ).update({"status": "blocked", "reasons": ["missing retained product bytes"]}),
                ),
            )
            gate = gate_by_id(manifest, "file_transfer_android_product_e2e")
            gate["evidence_paths"] = [report_path]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            blocking_gate = next(
                item for item in summary["blocking_required_gates"] if item["id"] == "file_transfer_android_product_e2e"
            )
            self.assertIn(
                "docs/evidence/file-transfer-mutated-gate.json: formal file-transfer report safety.no_host_ui_evidence_do_not_close_gate must be true",
                blocking_gate["issues"],
            )
            self.assertIn(
                "docs/evidence/file-transfer-mutated-gate.json: formal file-transfer report product_e2e_closure.same_session_id_required must be true",
                blocking_gate["issues"],
            )
            self.assertIn(
                "docs/evidence/file-transfer-mutated-gate.json: formal file-transfer report bidirectional_product_e2e.status must be pass",
                blocking_gate["issues"],
            )
            self.assertIn(
                "docs/evidence/file-transfer-mutated-gate.json: formal file-transfer report bidirectional_product_e2e.reasons must be empty",
                blocking_gate["issues"],
            )

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_report_must_reference_product_source(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_file_transfer_android_gate_evidence(
                repo,
                output_path="docs/evidence/file-transfer-missing-source-gate.json",
                mutate_report=lambda report: report["source"].pop("product_e2e"),
            )
            gate_by_id(manifest, "file_transfer_android_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = file_transfer_gate_issues(summary)
            self.assertTrue(
                any("formal file-transfer report source.product_e2e must be present" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_source_path_must_exist(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_file_transfer_android_gate_evidence(
                repo,
                output_path="docs/evidence/file-transfer-missing-product-source-gate.json",
                mutate_report=lambda report: report["source"].update(
                    {"product_e2e": "docs/evidence/missing-file-transfer-product-e2e.json"}
                ),
            )
            gate_by_id(manifest, "file_transfer_android_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = file_transfer_gate_issues(summary)
            self.assertTrue(
                any("source.product_e2e docs/evidence/missing-file-transfer-product-e2e.json must exist" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_source_must_be_product_e2e_kind(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_file_transfer_android_gate_evidence(
                repo,
                output_path="docs/evidence/file-transfer-wrong-product-kind-gate.json",
            )
            mutate_file_transfer_product_source(
                repo,
                report_path,
                lambda product: product.update({"kind": "file_transfer_no_host_ui_summary"}),
            )
            gate_by_id(manifest, "file_transfer_android_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = file_transfer_gate_issues(summary)
            self.assertTrue(
                any("kind must be android_macos_file_transfer_product_e2e" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_source_rejects_non_product_context(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_file_transfer_android_gate_evidence(
                repo,
                output_path="docs/evidence/file-transfer-non-product-context-gate.json",
            )
            mutate_file_transfer_product_source(
                repo,
                report_path,
                lambda product: product.update(
                    {
                        "host_backed_product_session": False,
                        "no_host_ui_only": True,
                    }
                ),
            )
            gate_by_id(manifest, "file_transfer_android_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = file_transfer_gate_issues(summary)
            self.assertTrue(
                any("host_backed_product_session must be true" in issue for issue in issues),
                issues,
            )
            self.assertTrue(
                any("no_host_ui_only must be false" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_source_rejects_synthetic_or_offline_evidence(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_file_transfer_android_gate_evidence(
                repo,
                output_path="docs/evidence/file-transfer-synthetic-product-gate.json",
            )
            mutate_file_transfer_product_source(
                repo,
                report_path,
                lambda product: product.update({"synthetic": True, "offline_only": True}),
            )
            gate_by_id(manifest, "file_transfer_android_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = file_transfer_gate_issues(summary)
            self.assertTrue(
                any("synthetic or offline-only evidence cannot close this gate" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_source_requires_distinct_direction_evidence(self) -> None:
        def duplicate_macos_direction(product: dict[str, object]) -> None:
            directions = product["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_to_macos_file_transfer"]
            macos_to_android = directions["macos_to_android_file_transfer"]
            assert isinstance(android_to_macos, dict)
            assert isinstance(macos_to_android, dict)
            for field in ("transfer_id_hex", "sha256", "file_name"):
                macos_to_android[field] = android_to_macos[field]

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_file_transfer_android_gate_evidence(
                repo,
                output_path="docs/evidence/file-transfer-duplicate-directions-gate.json",
            )
            mutate_file_transfer_product_source(repo, report_path, duplicate_macos_direction)
            gate_by_id(manifest, "file_transfer_android_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = file_transfer_gate_issues(summary)
            self.assertTrue(any("direction transfer IDs must be distinct" in issue for issue in issues), issues)
            self.assertTrue(any("direction SHA-256 digests must be distinct" in issue for issue in issues), issues)
            self.assertTrue(any("direction file names must be distinct" in issue for issue in issues), issues)

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_source_requires_cancel_cleanup(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_file_transfer_android_gate_evidence(
                repo,
                output_path="docs/evidence/file-transfer-missing-cancel-cleanup-gate.json",
            )
            mutate_file_transfer_product_source(
                repo,
                report_path,
                lambda product: product.pop("cancel_cleanup"),
            )
            gate_by_id(manifest, "file_transfer_android_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = file_transfer_gate_issues(summary)
            self.assertTrue(any("missing cancel_cleanup evidence" in issue for issue in issues), issues)

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_source_requires_direction_retained_artifacts(self) -> None:
        def remove_direction_artifacts(product: dict[str, object]) -> None:
            directions = product["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_to_macos_file_transfer"]
            assert isinstance(android_to_macos, dict)
            android_to_macos.pop("retained_artifacts")

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_file_transfer_android_gate_evidence(
                repo,
                output_path="docs/evidence/file-transfer-missing-direction-artifacts-gate.json",
            )
            mutate_file_transfer_product_source(repo, report_path, remove_direction_artifacts)
            gate_by_id(manifest, "file_transfer_android_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = file_transfer_gate_issues(summary)
            self.assertTrue(
                any(
                    "android_to_macos_file_transfer.retained_artifacts must retain product evidence artifacts"
                    in issue
                    for issue in issues
                ),
                issues,
            )

        with_temporary_repo(run)

    def test_file_transfer_product_e2e_source_requires_cancel_cleanup_artifacts(self) -> None:
        def remove_cancel_artifacts(product: dict[str, object]) -> None:
            cancel_cleanup = product["cancel_cleanup"]
            assert isinstance(cancel_cleanup, dict)
            cancel_cleanup["retained_artifacts"] = [
                {"role": "cancel_request", "path": "cancel-cleanup/missing-cancel-request.txt"}
            ]

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_file_transfer_android_gate_evidence(
                repo,
                output_path="docs/evidence/file-transfer-missing-cancel-artifacts-gate.json",
            )
            mutate_file_transfer_product_source(repo, report_path, remove_cancel_artifacts)
            gate_by_id(manifest, "file_transfer_android_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = file_transfer_gate_issues(summary)
            self.assertTrue(
                any(
                    "cancel_cleanup.retained_artifacts[0].path missing retained artifact "
                    "for cancel_request cancel-cleanup/missing-cancel-request.txt" in issue
                    for issue in issues
                ),
                issues,
            )
            self.assertTrue(
                any("cancel_cleanup.retained_artifacts missing cleanup_state artifact" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_pass_requires_structured_reports(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "telemetry_and_latency_archive")
            gate["evidence_paths"] = ["README.md", "tools/vibescreen_evidence/latency.py"]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            self.assertEqual(
                [gate["id"] for gate in summary["blocking_required_gates"]],
                ["telemetry_and_latency_archive"],
            )
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any(
                    "formal latency_evidence_gate report whose source.manifest "
                    "revalidates retained raw external-camera media or "
                    "synchronized-clock physical-input proof"
                    in issue
                    for issue in issues
                ),
                issues,
            )
            self.assertIn(
                "telemetry_and_latency_archive pass requires at least one passing android_usb_live_smoke report with stream telemetry and decoder counters in evidence_paths",
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_rejects_summary_only_latency_artifact(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            summary_path = Path("docs/evidence/latency-summary-only.json")
            summary_file = repo / summary_path
            summary_file.write_text(
                json.dumps(
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "kind": "glass_to_glass",
                        "status": "complete",
                        "latency_kind": "glass-to-glass",
                        "measurement_method": "external-camera",
                        "gate": {"can_close_performance_gate": True},
                    }
                ),
                encoding="utf-8",
            )
            gate = gate_by_id(manifest, "telemetry_and_latency_archive")
            gate["evidence_paths"] = [
                summary_path.as_posix(),
                "docs/evidence/android-usb-live-smoke.json",
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any("latency summary artifacts are summary-only" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_rejects_diagnostic_only_telemetry(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            diagnostic_path = Path("docs/evidence/host-stage-telemetry.json")
            diagnostic_file = repo / diagnostic_path
            diagnostic_file.write_text(
                json.dumps(
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "kind": "telemetry_stage_latency",
                        "status": "informational",
                        "latency_kind": "telemetry-stage",
                        "measurement_method": "host-telemetry",
                        "gate": {"can_close_performance_gate": False},
                    }
                ),
                encoding="utf-8",
            )
            gate = gate_by_id(manifest, "telemetry_and_latency_archive")
            gate["evidence_paths"] = [
                diagnostic_path.as_posix(),
                "docs/evidence/android-usb-live-smoke.json",
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any(
                    "telemetry diagnostic artifacts are informational only" in issue
                    for issue in issues
                ),
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_rejects_blocked_preflight_as_pass(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            preflight_path = Path("docs/evidence/latency-preflight.json")
            preflight_file = repo / preflight_path
            preflight_file.parent.mkdir(parents=True, exist_ok=True)
            preflight_file.write_text(
                json.dumps(
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "kind": "latency_gate_preflight",
                        "gate_profiles": [
                            {
                                "profile": "usb-glass-to-glass-sub50",
                                "can_close_performance_gate": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gate = gate_by_id(manifest, "telemetry_and_latency_archive")
            gate["evidence_paths"] = [preflight_path.as_posix()]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any("formal latency_evidence_gate report" in issue for issue in issues)
            )
            self.assertTrue(
                any(
                    "latency preflight artifacts record readiness only" in issue
                    for issue in issues
                ),
                issues,
            )
            self.assertTrue(
                any("android_usb_live_smoke report" in issue for issue in issues)
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_rejects_invalid_utf8_evidence(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            bad_path = Path("docs/evidence/bad-latency.json")
            bad_file = repo / bad_path
            bad_file.parent.mkdir(parents=True, exist_ok=True)
            bad_file.write_bytes(b"{\xff\xfe}")
            gate = gate_by_id(manifest, "telemetry_and_latency_archive")
            gate["evidence_paths"] = [
                bad_path.as_posix(),
                "docs/evidence/android-usb-live-smoke.json",
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any(
                    "could not read telemetry_and_latency_archive evidence" in issue
                    for issue in issues
                )
            )
            self.assertTrue(
                any("formal latency_evidence_gate report" in issue for issue in issues)
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_requires_positive_latency_sample_counts(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            latency_path = Path("docs/evidence/latency-evidence-usb.json")
            latency_file = repo / latency_path
            record = json.loads(latency_file.read_text(encoding="utf-8"))
            record["gate"]["sample_count"] = 0
            record["gate"]["min_sample_count"] = 0
            latency_file.write_text(json.dumps(record), encoding="utf-8")

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertIn(
                "docs/evidence/latency-evidence-usb.json: formal latency report "
                "min_sample_count must equal 5 and sample_count must be at least 5",
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_requires_formal_latency_gate_sample_floor(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            latency_path = Path("docs/evidence/latency-evidence-usb.json")
            latency_file = repo / latency_path
            record = json.loads(latency_file.read_text(encoding="utf-8"))
            record["gate"]["sample_count"] = 4
            record["gate"]["min_sample_count"] = 1
            latency_file.write_text(json.dumps(record), encoding="utf-8")

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertIn(
                "docs/evidence/latency-evidence-usb.json: formal latency report "
                "min_sample_count must equal 5 and sample_count must be at least 5",
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_rejects_malformed_latency_report_fields(self) -> None:
        cases = (
            (
                "fractional_sample_count",
                lambda record: record["gate"].__setitem__("sample_count", 5.5),
                "formal latency report min_sample_count must equal 5",
            ),
            (
                "fractional_min_sample_count",
                lambda record: record["gate"].__setitem__("min_sample_count", 5.0),
                "formal latency report min_sample_count must equal 5",
            ),
            (
                "empty_source_manifest",
                lambda record: record["source"].__setitem__("manifest", ""),
                "formal latency report source.manifest must be present",
            ),
            (
                "missing_observed_with_uncertainty",
                lambda record: record["gate"].pop("observed_with_uncertainty_ms"),
                "formal latency report gate.observed_with_uncertainty_ms must be a finite non-negative number",
            ),
            (
                "observed_with_uncertainty_over_threshold",
                lambda record: record["gate"].__setitem__("observed_with_uncertainty_ms", 50.1),
                "formal latency report gate.observed_with_uncertainty_ms must not exceed gate.threshold_ms",
            ),
            (
                "does_not_require_external_hardware",
                lambda record: record["gate"].__setitem__("requires_external_hardware", False),
                "formal latency report gate.requires_external_hardware must be true",
            ),
        )
        for _name, mutate, expected_issue in cases:
            with self.subTest(_name):
                def run(repo: Path, base_commit: str) -> None:
                    manifest = complete_manifest_for_repo(repo, base_commit)
                    latency_path = Path("docs/evidence/latency-evidence-usb.json")
                    latency_file = repo / latency_path
                    record = json.loads(latency_file.read_text(encoding="utf-8"))
                    mutate(record)
                    latency_file.write_text(json.dumps(record), encoding="utf-8")

                    summary = evaluate_manifest(
                        manifest,
                        readme_text=GUARDED_README_TEXT,
                        repo_root=repo,
                    )

                    self.assertEqual(summary["aggregate_verdict"], "insufficient")
                    issues = summary["blocking_required_gates"][0]["issues"]
                    self.assertTrue(
                        any(expected_issue in issue for issue in issues),
                        issues,
                    )

                with_temporary_repo(run)

    def test_telemetry_latency_archive_requires_source_manifest_to_exist(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            (repo / "docs/evidence/latency-manifest.json").unlink()

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertIn(
                "docs/evidence/latency-evidence-usb.json: formal latency report "
                "source.manifest docs/evidence/latency-manifest.json must exist",
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_rejects_missing_raw_camera_media(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            (repo / "docs/evidence/raw-camera-capture.mov").unlink()

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any(
                    "retained raw external-camera media or synchronized-clock physical-input proof"
                    in issue
                    and "recording.raw_video does not exist" in issue
                    for issue in issues
                ),
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_rejects_missing_synchronized_clock_proof(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            write_synchronized_clock_latency_evidence(
                repo,
                include_sync_artifact=False,
            )

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any(
                    "synchronized-clock physical-input proof" in issue
                    and "gate_artifacts.synchronization_record is required" in issue
                    for issue in issues
                ),
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_accepts_synchronized_clock_input_proof(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            write_synchronized_clock_latency_evidence(repo)

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "pass")
            telemetry_gate = next(
                gate
                for gate in summary["gate_summaries"]
                if gate["id"] == "telemetry_and_latency_archive"
            )
            self.assertEqual(telemetry_gate["issues"], [])
            self.assertTrue(telemetry_gate["can_close"])

        with_temporary_repo(run)

    def test_telemetry_latency_archive_rejects_synchronized_clock_large_budget(self) -> None:
        def set_large_budget(document: dict[str, object]) -> None:
            synchronization = document["synchronization"]
            assert isinstance(synchronization, dict)
            synchronization["total_error_budget_ms"] = 5.0

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            write_synchronized_clock_latency_evidence(
                repo,
                mutate_manifest=set_large_budget,
            )

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any("total_error_budget_ms must be less than 5 ms" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_rejects_zero_motionevent_uncertainty(self) -> None:
        def clear_motion_event_uncertainty(document: dict[str, object]) -> None:
            synchronization = document["synchronization"]
            assert isinstance(synchronization, dict)
            synchronization["input_timestamp_uncertainty_ms"] = 0.0

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            write_synchronized_clock_latency_evidence(
                repo,
                mutate_manifest=clear_motion_event_uncertainty,
            )

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any("non-zero physical touch acquisition uncertainty" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_revalidates_source_manifest_artifacts(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            (repo / "docs/evidence/samples.csv").write_text(
                "start_frame,end_frame,camera_fps\n10,18,240\n",
                encoding="utf-8",
            )

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any(
                    "source.manifest must revalidate as a passing latency evidence package" in issue
                    and "samples.sha256 does not match its referenced file" in issue
                    for issue in issues
                ),
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_rejects_malformed_android_stream_fields(self) -> None:
        def mutate_android_smoke(
            record: dict[str, object], path: tuple[str, ...], value: object
        ) -> None:
            target = record
            for key in path[:-1]:
                child = target[key]
                assert isinstance(child, dict)
                target = child
            target[path[-1]] = value

        cases = (
            (
                "non_integer_session_epoch",
                ("logs", "telemetry", "session_epochs"),
                ["not-an-int"],
                "telemetry must include integer session_epochs",
            ),
            (
                "fractional_stream_count",
                ("logs", "telemetry", "stream_stats", "count"),
                3.5,
                "telemetry.stream_stats.count must be a positive integer",
            ),
            (
                "fractional_positive_fps_count",
                ("logs", "telemetry", "stream_stats", "positive_fps_count"),
                2.5,
                "telemetry must include positive integer FPS stream_stats",
            ),
            (
                "positive_fps_count_exceeds_count",
                ("logs", "telemetry", "stream_stats", "positive_fps_count"),
                4,
                "telemetry.stream_stats.positive_fps_count must not exceed stream_stats.count",
            ),
            (
                "negative_frame_drop_summary",
                ("logs", "telemetry", "frame_drops", "max_dropped_total"),
                -1,
                "telemetry.frame_drops.max_dropped_total must be a non-negative integer",
            ),
            (
                "string_decoder_output_counter",
                ("logs", "decoder", "latest_output_counter"),
                "60",
                "decoder.latest_output_counter must be a positive integer",
            ),
            (
                "empty_decode_stats",
                ("logs", "decoder", "latest_decode_stats"),
                {},
                "decoder.latest_decode_stats must include a positive integer counter",
            ),
            (
                "negative_decoder_latency",
                ("logs", "decoder", "latest_output_latency", "avg_ms"),
                -0.1,
                "decoder latency metrics must be present",
            ),
            (
                "decoder_latency_average_above_maximum",
                ("logs", "decoder", "latest_output_latency", "avg_ms"),
                12.0,
                "decoder latest_output_latency.avg_ms must not exceed max_ms",
            ),
        )
        for _name, path, value, expected_issue in cases:
            with self.subTest(_name):
                def run(repo: Path, base_commit: str) -> None:
                    manifest = complete_manifest_for_repo(repo, base_commit)
                    smoke_path = Path("docs/evidence/android-usb-live-smoke.json")
                    smoke_file = repo / smoke_path
                    record = json.loads(smoke_file.read_text(encoding="utf-8"))
                    mutate_android_smoke(record, path, value)
                    smoke_file.write_text(json.dumps(record), encoding="utf-8")

                    summary = evaluate_manifest(
                        manifest,
                        readme_text=GUARDED_README_TEXT,
                        repo_root=repo,
                    )

                    self.assertEqual(summary["aggregate_verdict"], "insufficient")
                    issues = summary["blocking_required_gates"][0]["issues"]
                    self.assertTrue(
                        any(expected_issue in issue for issue in issues),
                        issues,
                    )

                with_temporary_repo(run)

    def test_telemetry_latency_archive_requires_android_device_identity(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            smoke_path = Path("docs/evidence/android-usb-live-smoke.json")
            smoke_file = repo / smoke_path
            record = json.loads(smoke_file.read_text(encoding="utf-8"))
            record.pop("device")
            smoke_file.write_text(json.dumps(record), encoding="utf-8")

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertIn(
                "docs/evidence/android-usb-live-smoke.json: Android USB live smoke device must be an object",
                issues,
            )

        with_temporary_repo(run)

    def test_telemetry_latency_archive_accepts_structured_latency_and_stream_reports(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "telemetry_and_latency_archive")
            self.assertEqual(
                gate["evidence_paths"],
                [
                    "docs/evidence/latency-evidence-usb.json",
                    "docs/evidence/android-usb-live-smoke.json",
                ],
            )

            summary = evaluate_manifest(
                manifest,
                readme_text="Phase 0 stable-release summary",
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "pass")
            self.assertTrue(summary["can_mark_phase0_stable_release"])
            telemetry_gate = next(
                gate
                for gate in summary["gate_summaries"]
                if gate["id"] == "telemetry_and_latency_archive"
            )
            self.assertEqual(telemetry_gate["issues"], [])
            self.assertTrue(telemetry_gate["can_close"])

        with_temporary_repo(run)

    def test_host_rss_pass_requires_structured_formal_gate_report(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "host_rss_2h_no_growth")
            gate["evidence_paths"] = ["README.md"]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            self.assertEqual(
                [gate["id"] for gate in summary["blocking_required_gates"]],
                ["host_rss_2h_no_growth"],
            )
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertIn(
                "host_rss_2h_no_growth pass requires at least one passing formal "
                "host_rss_no_growth_gate report in evidence_paths",
                issues,
            )

        with_temporary_repo(run)

    def test_host_rss_pass_revalidates_source_inputs(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            samples_path = repo / "docs/evidence/host-rss/samples.jsonl"
            rows = [
                json.loads(line)
                for line in samples_path.read_text(encoding="utf-8").splitlines()
            ]
            for row in rows:
                elapsed_minutes = row["elapsed_seconds"] / 60.0
                row["host"]["rss_kb"] = 120_000.0 + 96.5 * elapsed_minutes
            samples_path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any(
                    "source inputs must rederive as a passing host_rss_gate report"
                    in issue
                    and "criterion failed: second_half_ols_slope_ci_upper_kib_per_minute"
                    in issue
                    for issue in issues
                ),
                issues,
            )

        with_temporary_repo(run)

    def test_host_rss_pass_rejects_old_report_without_source_inputs(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = repo / "docs/evidence/host-rss-gate.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report.pop("source")
            report_path.write_text(json.dumps(report), encoding="utf-8")

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertIn(
                "docs/evidence/host-rss-gate.json: formal Host RSS report source must be an object",
                issues,
            )

        with_temporary_repo(run)

    def test_host_rss_pass_rejects_report_without_host_readiness_source(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = repo / "docs/evidence/host-rss-gate.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["source"].pop("host_readiness")
            report_path.write_text(json.dumps(report), encoding="utf-8")

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertIn(
                "docs/evidence/host-rss-gate.json: formal Host RSS report source.host_readiness must be present",
                issues,
            )

        with_temporary_repo(run)

    def test_host_rss_pass_revalidates_host_readiness_source(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            readiness_path = repo / "docs/evidence/host-rss/host-readiness.json"
            readiness_path.write_text(
                json.dumps(
                    host_readiness_payload(
                        can_start_host_rss_gate=False,
                        signing_tcc_status="blocked",
                        listener_observed=False,
                    )
                ),
                encoding="utf-8",
            )

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = summary["blocking_required_gates"][0]["issues"]
            self.assertTrue(
                any(
                    "source inputs must rederive as a passing host_rss_gate report"
                    in issue
                    and "can_start_host_rss_gate" in issue
                    for issue in issues
                ),
                issues,
            )

        with_temporary_repo(run)

    def test_native_pointer_hid_pass_requires_formal_summary(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "native_pointer_hid_mouse")
            gate["evidence_paths"] = ["README.md"]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            native_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "native_pointer_hid_mouse"
            )
            self.assertIn(
                "native_pointer_hid_mouse pass requires at least one passing formal "
                "native_pointer_hid_acceptance report in evidence_paths",
                native_gate["issues"],
            )

        with_temporary_repo(run)

    def test_native_pointer_hid_pass_requires_passing_report_and_retained_artifacts(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_native_pointer_hid_evidence(
                repo,
                output_path="docs/evidence/native-pointer-missing-artifact/native-pointer-hid-summary.json",
                mutate_report=lambda report: (
                    report.__setitem__("verdict", "blocked"),
                    report.__setitem__("can_close_native_pointer_hid_gate", False),
                    report.__setitem__(
                        "artifact_paths",
                        [
                            "dumpsys-input.txt",
                            "android-logcat-native-pointer.txt",
                            "missing-host-log.txt",
                        ],
                    ),
                ),
            )
            gate_by_id(manifest, "native_pointer_hid_mouse")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            native_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "native_pointer_hid_mouse"
            )
            self.assertIn(
                f"{report_path}: formal native pointer HID report verdict must be pass",
                native_gate["issues"],
            )
            self.assertIn(
                f"{report_path}: formal native pointer HID report can_close_native_pointer_hid_gate must be true",
                native_gate["issues"],
            )
            self.assertTrue(
                any("missing retained artifact missing-host-log.txt" in issue for issue in native_gate["issues"]),
                native_gate["issues"],
            )

        with_temporary_repo(run)

    def test_native_pointer_hid_pass_requires_host_log_artifact(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_native_pointer_hid_evidence(
                repo,
                output_path="docs/evidence/native-pointer-no-host-log/native-pointer-hid-summary.json",
                mutate_report=lambda report: report.__setitem__(
                    "artifact_paths",
                    ["result.json", "dumpsys-input.txt", "android-logcat-native-pointer.txt"],
                ),
            )
            gate_by_id(manifest, "native_pointer_hid_mouse")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            native_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "native_pointer_hid_mouse"
            )
            self.assertIn(
                f"{report_path}: formal native pointer HID report artifact_paths missing host-log-appended.txt",
                native_gate["issues"],
            )

        with_temporary_repo(run)

    def test_native_pointer_hid_pass_requires_complete_observations(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_native_pointer_hid_evidence(
                repo,
                output_path="docs/evidence/native-pointer-missing-observation/native-pointer-hid-summary.json",
                mutate_report=lambda report: report.__setitem__("observations", {}),
            )
            gate_by_id(manifest, "native_pointer_hid_mouse")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            native_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "native_pointer_hid_mouse"
            )
            self.assertTrue(
                any(
                    "formal native pointer HID report observations missing required field(s):" in issue
                    and "android_move_forwarded" in issue
                    for issue in native_gate["issues"]
                ),
                native_gate["issues"],
            )

        with_temporary_repo(run)

    def test_controller_runtime_pass_requires_formal_summary(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "controller_runtime_acceptance")
            gate["evidence_paths"] = ["README.md"]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            controller_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "controller_runtime_acceptance"
            )
            self.assertIn(
                "controller_runtime_acceptance pass requires at least one passing "
                "formal controller_runtime_acceptance report in evidence_paths",
                controller_gate["issues"],
            )

        with_temporary_repo(run)

    def test_controller_runtime_pass_requires_passing_report_and_retained_artifacts(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_controller_runtime_evidence(
                repo,
                output_path="docs/evidence/controller-missing-artifact/controller-runtime-summary.json",
                mutate_report=lambda report: (
                    report.__setitem__("verdict", "insufficient"),
                    report.__setitem__("can_close_runtime_gate", False),
                    report.__setitem__("artifact_paths", ["device-info.json", "missing-controller-log.txt"]),
                    report.__setitem__(
                        "observation_artifacts",
                        {"android_production_forwarding_observed": ["missing-controller-log.txt"]},
                    ),
                ),
            )
            gate_by_id(manifest, "controller_runtime_acceptance")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            controller_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "controller_runtime_acceptance"
            )
            self.assertIn(
                f"{report_path}: formal controller runtime report verdict must be pass",
                controller_gate["issues"],
            )
            self.assertIn(
                f"{report_path}: formal controller runtime report can_close_runtime_gate must be true",
                controller_gate["issues"],
            )
            self.assertTrue(
                any("missing retained artifact missing-controller-log.txt" in issue for issue in controller_gate["issues"]),
                controller_gate["issues"],
            )

        with_temporary_repo(run)

    def test_controller_runtime_pass_requires_observation_artifacts_to_be_retained(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_controller_runtime_evidence(
                repo,
                output_path="docs/evidence/controller-unretained-observation/controller-runtime-summary.json",
                mutate_report=lambda report: report.__setitem__(
                    "observation_artifacts",
                    {"android_production_forwarding_observed": ["unretained-controller-log.txt"]},
                ),
            )
            gate_by_id(manifest, "controller_runtime_acceptance")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            controller_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "controller_runtime_acceptance"
            )
            self.assertIn(
                f"{report_path}: formal controller runtime report observation_artifacts.android_production_forwarding_observed must reference retained artifact_paths: unretained-controller-log.txt",
                controller_gate["issues"],
            )

        with_temporary_repo(run)

    def test_host_rss_pass_rejects_malformed_report_sections(self) -> None:
        cases = (
            (
                "wrong_kind",
                lambda record: record.__setitem__("kind", "soak"),
                "formal Host RSS report kind must be host_rss_no_growth_gate",
            ),
            (
                "failed_verdict",
                lambda record: record.__setitem__("verdict", "fail"),
                "formal Host RSS report verdict must be pass",
            ),
            (
                "short_window",
                lambda record: record["window"].__setitem__("duration_seconds", 900),
                "formal Host RSS report window.duration_seconds must be at least 7056",
            ),
            (
                "sparse_samples",
                lambda record: record["window"].__setitem__("host_rss_sample_count", 12),
                "formal Host RSS report window.host_rss_sample_count must be at least 230",
            ),
            (
                "failed_sufficiency",
                lambda record: record["sufficiency"]["duration"].__setitem__("passed", False),
                "formal Host RSS report sufficiency must have all checks passed: duration",
            ),
            (
                "failed_telemetry_criterion",
                lambda record: record["telemetry_criteria"]["encoder_present_through_window"].__setitem__("passed", False),
                "formal Host RSS report telemetry_criteria must have all checks passed: encoder_present_through_window",
            ),
            (
                "failed_host_readiness_criterion",
                lambda record: record["host_readiness_criteria"]["stable_signing_identity"].__setitem__("passed", False),
                "formal Host RSS report host_readiness_criteria must have all checks passed: stable_signing_identity",
            ),
            (
                "unresolved_reason",
                lambda record: record.__setitem__("reasons", ["still growing"]),
                "formal Host RSS report pass must not include unresolved reasons",
            ),
            (
                "source_summary_error",
                lambda record: record["source_summary"].__setitem__(
                    "errors", ["collector stopped"]
                ),
                "formal Host RSS report source_summary.errors must be empty",
            ),
            (
                "boolean_error_count",
                lambda record: record["source_summary"].__setitem__(
                    "error_count", False
                ),
                "formal Host RSS report source_summary.error_count must be 0",
            ),
            (
                "float_error_count",
                lambda record: record["source_summary"].__setitem__(
                    "error_count", 0.0
                ),
                "formal Host RSS report source_summary.error_count must be 0",
            ),
        )
        for name, mutate, expected_issue in cases:
            with self.subTest(name):
                def run(repo: Path, base_commit: str) -> None:
                    manifest = complete_manifest_for_repo(repo, base_commit)
                    report_path = repo / "docs/evidence/host-rss-gate.json"
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    mutate(report)
                    report_path.write_text(json.dumps(report), encoding="utf-8")

                    summary = evaluate_manifest(
                        manifest,
                        readme_text=GUARDED_README_TEXT,
                        repo_root=repo,
                    )

                    self.assertEqual(summary["aggregate_verdict"], "insufficient")
                    issues = summary["blocking_required_gates"][0]["issues"]
                    self.assertTrue(
                        any(expected_issue in issue for issue in issues),
                        issues,
                    )

                with_temporary_repo(run)

    def test_pass_gate_with_blockers_is_insufficient(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "host_rss_2h_no_growth")
            gate["blockers"] = ["host RSS still grows"]

            summary = evaluate_manifest(
                manifest, readme_text=GUARDED_README_TEXT, repo_root=repo
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            self.assertFalse(summary["can_mark_phase0_stable_release"])
            self.assertEqual(
                [gate["id"] for gate in summary["blocking_required_gates"]],
                ["host_rss_2h_no_growth"],
            )
            self.assertIn(
                "pass gate must not list unresolved blockers",
                summary["blocking_required_gates"][0]["issues"],
            )

        with_temporary_repo(run)

    def test_non_pass_required_gate_must_explain_blocker(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "host_rss_2h_no_growth")
            gate["verdict"] = "blocked"
            gate["blockers"] = []

            summary = evaluate_manifest(
                manifest, readme_text=GUARDED_README_TEXT, repo_root=repo
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            self.assertIn(
                "non-pass required gate must list at least one blocker",
                summary["blocking_required_gates"][0]["issues"],
            )
            self.assertIn(
                "host_rss_2h_no_growth: non-pass required gate must list at least one blocker",
                summary["reasons"],
            )

        with_temporary_repo(run)

    def test_required_gate_cannot_be_marked_optional_to_close_aggregate(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "host_rss_2h_no_growth")
            gate["required_for_stable_release"] = False

            summary = evaluate_manifest(
                manifest, readme_text=GUARDED_README_TEXT, repo_root=repo
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            self.assertFalse(summary["can_mark_phase0_stable_release"])
            self.assertEqual(
                [gate["id"] for gate in summary["blocking_required_gates"]],
                ["host_rss_2h_no_growth"],
            )
            self.assertIn(
                "required Phase 0 gate cannot set required_for_stable_release=false",
                summary["blocking_required_gates"][0]["issues"],
            )

        with_temporary_repo(run)

    def test_missing_required_gate_is_insufficient(self) -> None:
        manifest = complete_manifest()
        manifest["required_gates"] = manifest["required_gates"][:-1]

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["missing_required_gate_ids"], ["module_ownership_extraction"])

    def test_expected_source_commit_must_match_manifest_base_commit(self) -> None:
        summary = evaluate_manifest(
            complete_manifest(),
            readme_text=GUARDED_README_TEXT,
            expected_source_commit="def456",
        )

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
        self.assertIn("source.base_commit", summary["reasons"][0])
        self.assertEqual(summary["readme_guard"]["verdict"], "pass")

    def test_owner_prs_require_open_pr_snapshot(self) -> None:
        manifest = complete_manifest()
        manifest.pop("open_pr_snapshot")
        gate_by_id(manifest, "host_rss_2h_no_growth")["owner_prs"] = [158]

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["owner_pr_guard"]["verdict"], "insufficient")
        self.assertEqual(summary["owner_pr_guard"]["stale_owner_prs"], [158])
        self.assertIn(
            "owner_prs require open_pr_snapshot",
            summary["owner_pr_guard"]["reasons"][0],
        )

    def test_owner_prs_must_match_current_open_pr_snapshot(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "host_rss_2h_no_growth")["owner_prs"] = [158]
        manifest["open_pr_snapshot"]["open_pr_numbers"] = []

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["owner_pr_guard"]["verdict"], "insufficient")
        self.assertEqual(summary["owner_pr_guard"]["owner_prs"], [158])
        self.assertEqual(summary["owner_pr_guard"]["stale_owner_prs"], [158])
        self.assertIn("#158", summary["owner_pr_guard"]["reasons"][0])

    def test_owner_prs_can_match_current_open_pr_snapshot(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate_by_id(manifest, "host_rss_2h_no_growth")["owner_prs"] = [158]
            manifest["open_pr_snapshot"]["open_pr_numbers"] = [158, 232]

            summary = evaluate_manifest(
                manifest,
                readme_text="Phase 0 stable-release summary",
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "pass")
            self.assertEqual(summary["owner_pr_guard"]["verdict"], "pass")
            self.assertEqual(
                summary["owner_pr_guard"]["repository"], "TaoSama/vibe-screen"
            )
            self.assertEqual(summary["owner_pr_guard"]["stale_owner_prs"], [])

        with_temporary_repo(run)

    def test_merged_pr_snapshot_accepts_main_ancestor_merge_commit(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            feature = repo / "feature.txt"
            feature.write_text("feature\n", encoding="utf-8")
            merge_commit = commit_all(repo, "merge pr 158")
            manifest = complete_manifest()
            manifest["source"]["base_commit"] = merge_commit
            gate_by_id(manifest, "telemetry_and_latency_archive")["evidence_paths"] = (
                write_latency_archive_evidence(repo)
            )
            gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")[
                "evidence_paths"
            ] = [
                write_macos_hardware_compatibility_evidence(
                    repo, repository_commit=merge_commit
                )
            ]
            gate_by_id(manifest, "host_rss_2h_no_growth")["evidence_paths"] = [
                write_host_rss_gate_evidence(repo)
            ]
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                write_clipboard_gate_evidence(repo)
            ]
            attach_hardware_runtime_gate_evidence(manifest, repo)
            attach_file_transfer_android_gate_evidence(manifest, repo)
            add_merged_pr_snapshot(manifest, repo, merge_commit)

            summary = evaluate_manifest(
                manifest,
                readme_text="Phase 0 stable-release summary",
                repo_root=repo,
            )

            self.assertEqual(summary["merged_pr_guard"]["verdict"], "pass")
            self.assertEqual(summary["merged_pr_guard"]["merged_pr_numbers"], [158])
            self.assertEqual(summary["aggregate_verdict"], "pass")

        with_temporary_repo(run)

    def test_merged_pr_snapshot_is_required(self) -> None:
        manifest = complete_manifest()

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["merged_pr_guard"]["verdict"], "insufficient")
        self.assertIn(
            "merged_pr_snapshot is required",
            summary["merged_pr_guard"]["reasons"][0],
        )

    def test_merged_pr_snapshot_rejects_invalid_utf8_snapshot(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            snapshot = manifest["merged_pr_snapshot"]
            assert isinstance(snapshot, dict)
            snapshot_path = snapshot["path"]
            assert isinstance(snapshot_path, str)
            (repo / snapshot_path).write_bytes(b"{\xff\xfe}")

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            self.assertEqual(summary["merged_pr_guard"]["verdict"], "insufficient")
            self.assertTrue(
                any(
                    "could not read merged_pr_snapshot.path" in reason
                    for reason in summary["merged_pr_guard"]["reasons"]
                )
            )

        with_temporary_repo(run)

    def test_merged_pr_snapshot_requires_base_main_and_merge_commit_projection(self) -> None:
        manifest = complete_manifest()
        manifest["source"]["base_commit"] = "a" * 40
        manifest["merged_pr_snapshot"] = {
            "repository": "TaoSama/vibe-screen",
            "command": "gh pr list --repo TaoSama/vibe-screen --state merged --limit 100 --json number,title,url",
            "state": "merged",
            "base": "main",
            "range": {"min": 158, "max": 158},
            "path": "merged-prs.jsonl",
            "audited_source_commit": "a" * 40,
            "excluded_pr_numbers": [],
        }

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "with --base main and mergeCommit"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_merged_pr_snapshot_requires_explicit_excluded_pr_numbers(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            feature = repo / "feature.txt"
            feature.write_text("feature\n", encoding="utf-8")
            merge_commit = commit_all(repo, "merge pr 158")
            manifest = complete_manifest()
            manifest["source"]["base_commit"] = merge_commit
            add_merged_pr_snapshot(manifest, repo, merge_commit)
            del manifest["merged_pr_snapshot"]["excluded_pr_numbers"]

            with self.assertRaisesRegex(
                Phase0StableReleaseError,
                "merged_pr_snapshot.excluded_pr_numbers is required",
            ):
                evaluate_manifest(
                    manifest,
                    readme_text=GUARDED_README_TEXT,
                    repo_root=repo,
                )

        with_temporary_repo(run)

    def test_merged_pr_snapshot_rejects_non_ancestor_merge_commit(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            good_path = repo / "good.txt"
            good_path.write_text("good\n", encoding="utf-8")
            audited_commit = commit_all(repo, "audited main")
            subprocess.run(
                ["git", "checkout", "--detach", base_commit],
                cwd=repo,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            side_path = repo / "side.txt"
            side_path.write_text("side\n", encoding="utf-8")
            side_commit = commit_all(repo, "side commit")
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=repo,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            manifest = complete_manifest()
            manifest["source"]["base_commit"] = audited_commit
            add_merged_pr_snapshot(
                manifest, repo, audited_commit, merge_commit=side_commit
            )

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["merged_pr_guard"]["verdict"], "insufficient")
            self.assertEqual(summary["merged_pr_guard"]["non_ancestor_prs"], [158])
            self.assertIn("mergeCommit", summary["merged_pr_guard"]["reasons"][0])
            self.assertEqual(summary["aggregate_verdict"], "insufficient")

        with_temporary_repo(run)

    def test_merged_pr_snapshot_rejects_wrong_entry_base(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            feature = repo / "feature.txt"
            feature.write_text("feature\n", encoding="utf-8")
            merge_commit = commit_all(repo, "merge pr 158")
            manifest = complete_manifest()
            manifest["source"]["base_commit"] = merge_commit
            add_merged_pr_snapshot(manifest, repo, merge_commit, entry_base="release")

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["merged_pr_guard"]["verdict"], "insufficient")
            self.assertIn("baseRefName", summary["merged_pr_guard"]["reasons"][0])
            self.assertEqual(summary["aggregate_verdict"], "insufficient")

        with_temporary_repo(run)

    def test_merged_pr_snapshot_requires_complete_declared_range(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            feature = repo / "feature.txt"
            feature.write_text("feature\n", encoding="utf-8")
            merge_commit = commit_all(repo, "merge pr 158")
            manifest = complete_manifest()
            manifest["source"]["base_commit"] = merge_commit
            add_merged_pr_snapshot(
                manifest, repo, merge_commit, excluded_pr_numbers=[159], maximum=160
            )

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["merged_pr_guard"]["verdict"], "insufficient")
            self.assertIn(
                "merged_pr_snapshot.path is missing PR numbers from the declared range #158-#160: #160",
                summary["merged_pr_guard"]["reasons"],
            )
            self.assertEqual(summary["aggregate_verdict"], "insufficient")

        with_temporary_repo(run)

    def test_merged_pr_snapshot_accepts_explicit_excluded_range_numbers(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            feature = repo / "feature.txt"
            feature.write_text("feature\n", encoding="utf-8")
            merge_commit = commit_all(repo, "merge pr 158")
            manifest = complete_manifest()
            manifest["source"]["base_commit"] = merge_commit
            gate_by_id(manifest, "telemetry_and_latency_archive")["evidence_paths"] = (
                write_latency_archive_evidence(repo)
            )
            gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")[
                "evidence_paths"
            ] = [
                write_macos_hardware_compatibility_evidence(
                    repo, repository_commit=merge_commit
                )
            ]
            gate_by_id(manifest, "host_rss_2h_no_growth")["evidence_paths"] = [
                write_host_rss_gate_evidence(repo)
            ]
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                write_clipboard_gate_evidence(repo)
            ]
            attach_hardware_runtime_gate_evidence(manifest, repo)
            attach_file_transfer_android_gate_evidence(manifest, repo)
            add_merged_pr_snapshot(
                manifest, repo, merge_commit, excluded_pr_numbers=[159, 160], maximum=160
            )

            summary = evaluate_manifest(
                manifest,
                readme_text="Phase 0 stable-release summary",
                repo_root=repo,
            )

            self.assertEqual(summary["merged_pr_guard"]["verdict"], "pass")
            self.assertEqual(summary["merged_pr_guard"]["merged_pr_numbers"], [158])
            self.assertEqual(summary["merged_pr_guard"]["excluded_pr_numbers"], [159, 160])
            self.assertEqual(summary["aggregate_verdict"], "pass")

        with_temporary_repo(run)

    def test_owner_prs_reject_bool_values(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "host_rss_2h_no_growth")["owner_prs"] = [True]
        manifest["open_pr_snapshot"]["open_pr_numbers"] = [1]

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "owner_prs must be a list of integers"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_rejects_bool_pr_numbers(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "host_rss_2h_no_growth")["owner_prs"] = [1]
        manifest["open_pr_snapshot"]["open_pr_numbers"] = [True]

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "open_pr_numbers must be a list of integers"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_rejects_wrong_repository(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["repository"] = "TaoSama/other"

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "open_pr_snapshot.repository"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_command_must_target_repository(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["command"] = (
            "gh pr list --repo TaoSama/other --state open --limit 200 --json number"
        )

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "must list open PRs for TaoSama/vibe-screen"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_rejects_missing_repo_option(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["command"] = (
            "gh pr list --state open --limit 200 --json number"
        )

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "must list open PRs for TaoSama/vibe-screen"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_accepts_gh_short_options(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["command"] = (
            "gh pr list -R TaoSama/vibe-screen -s open --limit 200 --json number"
        )

        summary = evaluate_manifest(
            manifest,
            readme_text="Phase 0 stable-release summary",
            evaluation_date=_datetime.date(2026, 8, 22),
        )

        self.assertEqual(summary["owner_pr_guard"]["verdict"], "pass")

    def test_open_pr_snapshot_rejects_malformed_command(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["command"] = (
            "gh pr list --repo 'TaoSama/vibe-screen --state open"
        )

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "must list open PRs for TaoSama/vibe-screen"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_rejects_future_queried_at(self) -> None:
        manifest = complete_manifest()
        manifest["source"]["audit_date"] = "2026-08-23"
        manifest["open_pr_snapshot"]["queried_at"] = "2026-08-23"

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "queried_at must not be in the future"
        ):
            evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                evaluation_date=_datetime.date(2026, 8, 22),
            )

    def test_open_pr_snapshot_date_must_match_audit_date(self) -> None:
        manifest = complete_manifest()
        stale_owner = gate_by_id(manifest, "host_rss_2h_no_growth")
        stale_owner["owner_prs"] = [158]
        manifest["open_pr_snapshot"]["open_pr_numbers"] = [158]
        manifest["open_pr_snapshot"]["queried_at"] = "2026-08-21"

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "must match manifest source.audit_date"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_date_must_not_be_after_audit_date(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["queried_at"] = "2026-08-23"

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "must match manifest source.audit_date"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_manifest_source_requires_traceable_fields(self) -> None:
        manifest = complete_manifest()
        manifest["source"] = {"base_commit": "abc123", "audit_date": "20260822"}

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
        self.assertIn("manifest source.base_ref must be a non-empty string", summary["reasons"])
        self.assertIn("manifest source.owner must be a non-empty string", summary["reasons"])
        self.assertIn("manifest source.audit_source must be a non-empty string", summary["reasons"])
        self.assertIn("manifest source.audit_date must use YYYY-MM-DD format", summary["reasons"])

    def test_manifest_source_rejects_future_audit_date(self) -> None:
        manifest = complete_manifest()
        manifest["source"]["audit_date"] = "2026-08-23"
        manifest.pop("open_pr_snapshot")

        summary = evaluate_manifest(
            manifest,
            readme_text=GUARDED_README_TEXT,
            evaluation_date=_datetime.date(2026, 8, 22),
        )

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
        self.assertIn(
            "manifest source.audit_date must not be in the future",
            summary["reasons"],
        )

    def test_stale_manifest_requires_readme_guard_even_when_sub_gates_pass(self) -> None:
        summary = evaluate_manifest(
            complete_manifest(),
            readme_text="Phase 0 is stable.",
            expected_source_commit="def456",
        )

        self.assertEqual(summary["aggregate_verdict"], "fail")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
        self.assertEqual(summary["readme_guard"]["verdict"], "fail")

    def test_blocked_aggregate_accepts_aggregate_only_successor_commit(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            aggregate_dir = repo / "docs/changes/2026-08-22-phase0-stable-release-aggregate"
            aggregate_dir.mkdir(parents=True)
            (aggregate_dir / "README.md").write_text(
                "Aggregate refresh.\n", encoding="utf-8"
            )
            test_path = repo / "tools/tests/test_phase0_stable_release.py"
            test_path.parent.mkdir(parents=True)
            test_path.write_text("# aggregate refresh fixture update\n", encoding="utf-8")
            successor_commit = commit_all(repo, "aggregate refresh")
            manifest = complete_manifest()
            manifest["source"]["base_commit"] = base_commit
            gate_by_id(manifest, "telemetry_and_latency_archive")["evidence_paths"] = (
                write_latency_archive_evidence(repo)
            )
            gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")[
                "evidence_paths"
            ] = [
                write_macos_hardware_compatibility_evidence(
                    repo, repository_commit=base_commit
                )
            ]
            gate_by_id(manifest, "host_rss_2h_no_growth")["evidence_paths"] = [
                write_host_rss_gate_evidence(repo)
            ]
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                write_clipboard_gate_evidence(repo)
            ]
            attach_hardware_runtime_gate_evidence(manifest, repo)
            attach_file_transfer_android_gate_evidence(manifest, repo)
            add_merged_pr_snapshot(manifest, repo, base_commit)
            gate_by_id(manifest, "host_rss_2h_no_growth")["verdict"] = "blocked"
            gate_by_id(manifest, "host_rss_2h_no_growth")["blockers"] = [
                "host_rss_gate has no current-source pass"
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                expected_source_commit=successor_commit,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "blocked")
            self.assertEqual(summary["source_guard"]["verdict"], "pass")
            self.assertTrue(
                summary["source_guard"]["accepted_aggregate_only_successor"]
            )
            self.assertFalse(summary["can_mark_phase0_stable_release"])

        with_temporary_repo(run)

    def test_aggregate_only_successor_cannot_support_stable_release_claim(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            aggregate_dir = repo / "docs/changes/2026-08-22-phase0-stable-release-aggregate"
            aggregate_dir.mkdir(parents=True)
            (aggregate_dir / "README.md").write_text(
                "Aggregate refresh.\n", encoding="utf-8"
            )
            successor_commit = commit_all(repo, "aggregate refresh")
            manifest = complete_manifest()
            manifest["source"]["base_commit"] = base_commit
            gate_by_id(manifest, "telemetry_and_latency_archive")["evidence_paths"] = (
                write_latency_archive_evidence(repo)
            )
            gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")[
                "evidence_paths"
            ] = [
                write_macos_hardware_compatibility_evidence(
                    repo, repository_commit=base_commit
                )
            ]
            gate_by_id(manifest, "host_rss_2h_no_growth")["evidence_paths"] = [
                write_host_rss_gate_evidence(repo)
            ]
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                write_clipboard_gate_evidence(repo)
            ]
            attach_hardware_runtime_gate_evidence(manifest, repo)
            attach_file_transfer_android_gate_evidence(manifest, repo)
            add_merged_pr_snapshot(manifest, repo, base_commit)

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                expected_source_commit=successor_commit,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            self.assertFalse(summary["can_mark_phase0_stable_release"])
            self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
            self.assertTrue(
                summary["source_guard"]["accepted_aggregate_only_successor"]
            )
            self.assertIn(
                "aggregate-only successor commits cannot support a Phase 0 stable-release claim",
                summary["source_guard"]["reasons"][0],
            )

        with_temporary_repo(run)

    def test_expected_source_commit_rejects_non_aggregate_successor_changes(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            source_dir = repo / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display"
            source_dir.mkdir(parents=True)
            (source_dir / "Product.kt").write_text("class Product\n", encoding="utf-8")
            successor_commit = commit_all(repo, "product change")
            manifest = complete_manifest()
            manifest["source"]["base_commit"] = base_commit

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                expected_source_commit=successor_commit,
                repo_root=repo,
            )

            self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
            self.assertFalse(
                summary["source_guard"]["accepted_aggregate_only_successor"]
            )
            self.assertIn(
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/Product.kt",
                summary["source_guard"]["reasons"][1],
            )

        with_temporary_repo(run)

    def test_expected_source_commit_rejects_checker_successor_changes(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            checker_path = repo / "tools/vibescreen_evidence/phase0_stable_release.py"
            checker_path.parent.mkdir(parents=True)
            checker_path.write_text("# checker changed\n", encoding="utf-8")
            successor_commit = commit_all(repo, "checker change")
            manifest = complete_manifest()
            manifest["source"]["base_commit"] = base_commit
            gate_by_id(manifest, "host_rss_2h_no_growth")["verdict"] = "blocked"
            gate_by_id(manifest, "host_rss_2h_no_growth")["blockers"] = [
                "host_rss_gate has no current-source pass"
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                expected_source_commit=successor_commit,
                repo_root=repo,
            )

            self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
            self.assertFalse(
                summary["source_guard"]["accepted_aggregate_only_successor"]
            )
            self.assertIn(
                "tools/vibescreen_evidence/phase0_stable_release.py",
                summary["source_guard"]["reasons"][1],
            )

        with_temporary_repo(run)

    def test_expected_source_commit_allows_matching_manifest_base_commit(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)

            summary = evaluate_manifest(
                manifest,
                readme_text="Phase 0 stable-release summary",
                expected_source_commit=base_commit,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "pass")
            self.assertTrue(summary["can_mark_phase0_stable_release"])
            self.assertEqual(summary["source_guard"]["verdict"], "pass")

        with_temporary_repo(run)

    def test_hardware_compatibility_matrix_is_required(self) -> None:
        manifest = complete_manifest()
        manifest["required_gates"] = [
            gate
            for gate in manifest["required_gates"]
            if gate["id"] != "macos_host_hardware_compatibility_matrix"
        ]

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(
            summary["missing_required_gate_ids"],
            ["macos_host_hardware_compatibility_matrix"],
        )

    def test_hardware_compatibility_matrix_pass_requires_formal_row_report(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
            gate["evidence_paths"] = ["docs/evidence/macos-host-compatibility-summary.json"]
            summary_file = repo / "docs/evidence/macos-host-compatibility-summary.json"
            summary_file.parent.mkdir(parents=True, exist_ok=True)
            summary_file.write_text(
                json.dumps({
                    "schema_version": "vibescreen.evidence/v1",
                    "kind": "macos_host_compatibility_readiness",
                    "verdict": "pass",
                }),
                encoding="utf-8",
            )

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            macos_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "macos_host_hardware_compatibility_matrix"
            )
            self.assertIn(
                "macos_host_hardware_compatibility_matrix pass requires at least one passing formal macos_host_compatibility_matrix_row report that revalidates a retained gate_input artifact from the same evidence bundle",
                macos_gate["issues"],
            )
            self.assertIn(
                "docs/evidence/macos-host-compatibility-summary.json: formal macOS Host compatibility report kind must be macos_host_compatibility_matrix_row",
                macos_gate["issues"],
            )

        with_temporary_repo(run)

    def test_hardware_compatibility_matrix_pass_rejects_blocked_row_report(self) -> None:
        def block_runtime(record: dict[str, object]) -> None:
            record["packaged_host_launch_observed"] = False
            record["protocol_v1_stream_observed"] = False

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
            gate["evidence_paths"] = [
                write_macos_hardware_compatibility_evidence(
                    repo, repository_commit=base_commit, mutate_input=block_runtime
                )
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            macos_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "macos_host_hardware_compatibility_matrix"
            )
            self.assertIn(
                "docs/evidence/macos-host-compatibility/macos-hardware-compatibility-gate.json: formal macOS Host compatibility report verdict must be pass",
                macos_gate["issues"],
            )
            self.assertIn(
                "docs/evidence/macos-host-compatibility/macos-hardware-compatibility-gate.json: formal macOS Host compatibility report can_close_macos_host_compatibility_row must be true",
                macos_gate["issues"],
            )
            self.assertTrue(
                any(
                    "gate_input artifact must rederive as a passing macos_host_compatibility_matrix_row report"
                    in issue
                    and "launch the packaged Host on the recorded Mac row" in issue
                    for issue in macos_gate["issues"]
                ),
                macos_gate["issues"],
            )

        with_temporary_repo(run)

    def test_hardware_compatibility_matrix_pass_revalidates_gate_input(self) -> None:
        def alter_report(report: dict[str, object]) -> None:
            row_scope = report["row_scope"]
            assert isinstance(row_scope, dict)
            row_scope["host_model_identifier"] = "Mac999,1"

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
            gate["evidence_paths"] = [
                write_macos_hardware_compatibility_evidence(
                    repo, repository_commit=base_commit, mutate_report=alter_report
                )
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            macos_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "macos_host_hardware_compatibility_matrix"
            )
            self.assertIn(
                "docs/evidence/macos-host-compatibility/macos-hardware-compatibility-gate.json: formal macOS Host compatibility report must match its rederived gate_input artifact for row_scope",
                macos_gate["issues"],
            )

        with_temporary_repo(run)

    def test_hardware_compatibility_matrix_revalidates_gate_input_without_run_id_drift(self) -> None:
        def remove_input_run_id(record: dict[str, object]) -> None:
            record.pop("run_id", None)

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
            gate["evidence_paths"] = [
                write_macos_hardware_compatibility_evidence(
                    repo,
                    repository_commit=base_commit,
                    source_directory="docs/evidence/macos-host-compatibility-without-run-id",
                    mutate_input=remove_input_run_id,
                )
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text="Phase 0 stable-release summary",
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "pass")
            self.assertTrue(summary["can_mark_phase0_stable_release"])

        with_temporary_repo(run)

    def test_hardware_compatibility_matrix_reports_invalid_gate_input_claim_detail(self) -> None:
        def mark_ci_only(record: dict[str, object]) -> None:
            record["ci_runner_only"] = True

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
            gate["evidence_paths"] = [
                write_macos_hardware_compatibility_evidence(
                    repo,
                    repository_commit=base_commit,
                    source_directory="docs/evidence/ci-only-macos-host-compatibility",
                    mutate_input=mark_ci_only,
                )
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            macos_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "macos_host_hardware_compatibility_matrix"
            )
            self.assertTrue(
                any(
                    "CI runner build/test output cannot close a real Host hardware compatibility row"
                    in issue
                    for issue in macos_gate["issues"]
                ),
                macos_gate["issues"],
            )

        with_temporary_repo(run)

    def test_hardware_compatibility_matrix_rejects_failed_artifact_file_check(self) -> None:
        def mark_missing_artifact(report: dict[str, object]) -> None:
            artifact_file_check = report["artifact_file_check"]
            assert isinstance(artifact_file_check, dict)
            artifact_file_check["enabled"] = False
            artifact_file_check["missing_paths"] = ["host-launch.log"]

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
            gate["evidence_paths"] = [
                write_macos_hardware_compatibility_evidence(
                    repo,
                    repository_commit=base_commit,
                    source_directory="docs/evidence/macos-host-compatibility-bad-files",
                    mutate_report=mark_missing_artifact,
                )
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            macos_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "macos_host_hardware_compatibility_matrix"
            )
            self.assertIn(
                "docs/evidence/macos-host-compatibility-bad-files/macos-hardware-compatibility-gate.json: formal macOS Host compatibility report artifact_file_check.enabled must be true",
                macos_gate["issues"],
            )
            self.assertIn(
                "docs/evidence/macos-host-compatibility-bad-files/macos-hardware-compatibility-gate.json: formal macOS Host compatibility report artifact_file_check.missing_paths must be empty",
                macos_gate["issues"],
            )

        with_temporary_repo(run)

    def test_hardware_compatibility_matrix_rejects_failed_artifact_role_check(self) -> None:
        def mark_unknown_role(report: dict[str, object]) -> None:
            artifact_role_check = report["artifact_role_check"]
            assert isinstance(artifact_role_check, dict)
            artifact_role_check["unknown_roles"] = ["README.md:summary"]
            artifact_role_check["roles_by_path"] = {"README.md": ["summary"]}

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
            gate["evidence_paths"] = [
                write_macos_hardware_compatibility_evidence(
                    repo,
                    repository_commit=base_commit,
                    source_directory="docs/evidence/macos-host-compatibility-bad-roles",
                    mutate_report=mark_unknown_role,
                )
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            macos_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "macos_host_hardware_compatibility_matrix"
            )
            self.assertIn(
                "docs/evidence/macos-host-compatibility-bad-roles/macos-hardware-compatibility-gate.json: formal macOS Host compatibility report artifact_role_check.unknown_roles must be empty",
                macos_gate["issues"],
            )
            self.assertIn(
                "docs/evidence/macos-host-compatibility-bad-roles/macos-hardware-compatibility-gate.json: formal macOS Host compatibility report artifact_role_check must identify exactly one gate_input artifact",
                macos_gate["issues"],
            )

        with_temporary_repo(run)

    def test_hardware_compatibility_matrix_rejects_unsafe_gate_input_path(self) -> None:
        def point_outside_bundle(report: dict[str, object]) -> None:
            artifact_role_check = report["artifact_role_check"]
            assert isinstance(artifact_role_check, dict)
            artifact_role_check["roles_by_path"] = {
                "../macos-hardware-compatibility.json": ["gate_input"]
            }

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
            gate["evidence_paths"] = [
                write_macos_hardware_compatibility_evidence(
                    repo,
                    repository_commit=base_commit,
                    source_directory="docs/evidence/macos-host-compatibility-unsafe-input",
                    mutate_report=point_outside_bundle,
                )
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            macos_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "macos_host_hardware_compatibility_matrix"
            )
            self.assertIn(
                "docs/evidence/macos-host-compatibility-unsafe-input/macos-hardware-compatibility-gate.json: formal macOS Host compatibility report gate_input artifact must be evidence-relative",
                macos_gate["issues"],
            )

        with_temporary_repo(run)

    def test_hardware_compatibility_matrix_rejects_unreadable_gate_input_json(self) -> None:
        def point_to_corrupt_input(report: dict[str, object]) -> None:
            artifact_role_check = report["artifact_role_check"]
            assert isinstance(artifact_role_check, dict)
            artifact_role_check["roles_by_path"] = {
                "corrupt-gate-input.json": ["gate_input"]
            }

        def run(repo: Path, base_commit: str) -> None:
            source_dir = repo / "docs/evidence/macos-host-compatibility-corrupt-input"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "corrupt-gate-input.json").write_text("{", encoding="utf-8")
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
            gate["evidence_paths"] = [
                write_macos_hardware_compatibility_evidence(
                    repo,
                    repository_commit=base_commit,
                    source_directory="docs/evidence/macos-host-compatibility-corrupt-input",
                    mutate_report=point_to_corrupt_input,
                )
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            macos_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "macos_host_hardware_compatibility_matrix"
            )
            self.assertTrue(
                any(
                    "gate_input artifact could not be read" in issue
                    and "corrupt-gate-input.json" in issue
                    for issue in macos_gate["issues"]
                ),
                macos_gate["issues"],
            )

        with_temporary_repo(run)

    def test_hardware_compatibility_matrix_pass_must_match_manifest_base_commit(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            feature = repo / "feature.txt"
            feature.write_text("feature\n", encoding="utf-8")
            current_commit = commit_all(repo, "current source")
            manifest = complete_manifest_for_repo(repo, current_commit)
            gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
            gate["evidence_paths"] = [
                write_macos_hardware_compatibility_evidence(
                    repo,
                    repository_commit=base_commit,
                    source_directory="docs/evidence/stale-macos-host-compatibility",
                )
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            macos_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "macos_host_hardware_compatibility_matrix"
            )
            self.assertIn(
                "docs/evidence/stale-macos-host-compatibility/macos-hardware-compatibility-gate.json: formal macOS Host compatibility report row_scope.repository_commit must match manifest source.base_commit",
                macos_gate["issues"],
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_is_required(self) -> None:
        manifest = complete_manifest()
        manifest["required_gates"] = [
            gate
            for gate in manifest["required_gates"]
            if gate["id"] != "clipboard_android_macos_product_e2e"
        ]

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(
            summary["missing_required_gate_ids"],
            ["clipboard_android_macos_product_e2e"],
        )

    def test_clipboard_product_e2e_pass_requires_formal_gate_report(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "clipboard_android_macos_product_e2e")
            gate["evidence_paths"] = ["docs/evidence/clipboard-summary-only.json"]
            summary_file = repo / "docs/evidence/clipboard-summary-only.json"
            summary_file.parent.mkdir(parents=True, exist_ok=True)
            summary_file.write_text(
                json.dumps(
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "kind": "android_clipboard_local_smoke",
                        "verdict": "pass",
                    }
                ),
                encoding="utf-8",
            )

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            clipboard_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertIn(
                "clipboard_android_macos_product_e2e pass requires at least one passing formal android_macos_clipboard_e2e_gate report in evidence_paths",
                clipboard_gate["issues"],
            )
            self.assertIn(
                "docs/evidence/clipboard-summary-only.json: formal clipboard report kind must be android_macos_clipboard_e2e_gate",
                clipboard_gate["issues"],
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_pass_rejects_blocked_gate_report(self) -> None:
        def mark_blocked(report: dict[str, object]) -> None:
            report["verdict"] = "blocked"
            report["result"] = "blocked"
            report["gate_closed"] = False
            report["can_close_android_macos_clipboard_e2e_gate"] = False
            report["blockers"] = ["missing Host-backed bidirectional clipboard product E2E"]
            report["not_proven"] = ["Android ClipboardManager -> macOS NSPasteboard over Protocol v1 USB/LAN"]

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "clipboard_android_macos_product_e2e")
            gate["evidence_paths"] = [write_clipboard_gate_evidence(repo, mutate=mark_blocked)]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            clipboard_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertTrue(
                any("formal clipboard report verdict and result must be pass" in issue for issue in clipboard_gate["issues"]),
                clipboard_gate["issues"],
            )
            self.assertTrue(
                any("can_close_android_macos_clipboard_e2e_gate must be true" in issue for issue in clipboard_gate["issues"]),
                clipboard_gate["issues"],
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_pass_requires_formal_gate_checks(self) -> None:
        def remove_checks(report: dict[str, object]) -> None:
            report.pop("checks")

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "clipboard_android_macos_product_e2e")
            gate["evidence_paths"] = [write_clipboard_gate_evidence(repo, mutate=remove_checks)]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            clipboard_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertIn(
                "docs/evidence/clipboard-e2e-gate.json: formal clipboard report checks must be a list",
                clipboard_gate["issues"],
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_pass_rejects_non_pass_formal_gate_check(self) -> None:
        def block_product_check(report: dict[str, object]) -> None:
            checks = report["checks"]
            assert isinstance(checks, list)
            product_check = checks[-1]
            assert isinstance(product_check, dict)
            product_check["status"] = "blocked"

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "clipboard_android_macos_product_e2e")
            gate["evidence_paths"] = [write_clipboard_gate_evidence(repo, mutate=block_product_check)]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            clipboard_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertIn(
                "docs/evidence/clipboard-e2e-gate.json: formal clipboard report check bidirectional_product_e2e must be pass",
                clipboard_gate["issues"],
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_pass_requires_source_product_e2e(self) -> None:
        def remove_source(report: dict[str, object]) -> None:
            report.pop("source")

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "clipboard_android_macos_product_e2e")
            gate["evidence_paths"] = [write_clipboard_gate_evidence(repo, mutate=remove_source)]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            clipboard_gate = next(
                item
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertIn(
                "docs/evidence/clipboard-e2e-gate.json: formal clipboard report source must be an object",
                clipboard_gate["issues"],
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_pass_revalidates_product_source(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "clipboard_android_macos_product_e2e")
            gate["evidence_paths"] = [write_clipboard_gate_evidence(repo)]

            summary = evaluate_manifest(
                manifest,
                readme_text="Phase 0 stable-release summary",
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "pass")
            self.assertTrue(summary["can_mark_phase0_stable_release"])

        with_temporary_repo(run)

    def test_clipboard_product_e2e_source_path_must_exist(self) -> None:
        def point_to_missing_source(report: dict[str, object]) -> None:
            source = report["source"]
            assert isinstance(source, dict)
            source["product_e2e"] = "docs/evidence/missing-clipboard-product-e2e.json"

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_clipboard_gate_evidence(repo, mutate=point_to_missing_source)
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = next(
                item["issues"]
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertTrue(
                any("source.product_e2e docs/evidence/missing-clipboard-product-e2e.json must exist" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_source_rejects_missing_retained_artifact(self) -> None:
        def remove_source_artifact(product: dict[str, object]) -> None:
            directions = product["directions"]
            assert isinstance(directions, dict)
            direction = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(direction, dict)
            artifacts = direction["retained_artifacts"]
            assert isinstance(artifacts, list)
            first_artifact = artifacts[0]
            assert isinstance(first_artifact, dict)
            first_artifact["path"] = "android-to-macos/missing-source-read.txt"

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_clipboard_gate_evidence(repo)
            mutate_clipboard_product_source(repo, report_path, remove_source_artifact)
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = next(
                item["issues"]
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertTrue(
                any("source_clipboard_read" in issue and "missing retained artifact" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_source_rejects_mismatched_session_ids(self) -> None:
        def mismatch_session(product: dict[str, object]) -> None:
            directions = product["directions"]
            assert isinstance(directions, dict)
            direction = directions["macos_nspasteboard_to_android_clipboardmanager"]
            assert isinstance(direction, dict)
            direction["session_id_hex"] = "11111111111111111111111111111111"

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_clipboard_gate_evidence(repo)
            mutate_clipboard_product_source(repo, report_path, mismatch_session)
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = next(
                item["issues"]
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertTrue(
                any("direction session IDs must match" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_source_rejects_mismatched_session_epoch(self) -> None:
        def mismatch_session_epoch(product: dict[str, object]) -> None:
            directions = product["directions"]
            assert isinstance(directions, dict)
            direction = directions["macos_nspasteboard_to_android_clipboardmanager"]
            assert isinstance(direction, dict)
            direction["session_epoch"] = 2

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_clipboard_gate_evidence(repo)
            mutate_clipboard_product_source(repo, report_path, mismatch_session_epoch)
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = next(
                item["issues"]
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertTrue(
                any("direction session_epoch values must match" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_source_rejects_malformed_protocol_packets(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_clipboard_gate_evidence(repo)
            report = json.loads((repo / report_path).read_text(encoding="utf-8"))
            source = report["source"]
            assert isinstance(source, dict)
            product_ref = source["product_e2e"]
            assert isinstance(product_ref, str)
            product_path = repo / product_ref
            product = json.loads(product_path.read_text(encoding="utf-8"))
            directions = product["directions"]
            assert isinstance(directions, dict)
            direction = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(direction, dict)
            artifacts = direction["retained_artifacts"]
            assert isinstance(artifacts, list)
            for artifact in artifacts:
                assert isinstance(artifact, dict)
                if artifact.get("role") == "protocol_packets":
                    artifact["byte_length"] = len(b"dummy\n")
                    artifact["sha256"] = hashlib.sha256(b"dummy\n").hexdigest()
                    break
            product_path.write_text(json.dumps(product), encoding="utf-8")
            protocol_path = product_path.parent / "android-to-macos/protocol-packets.jsonl"
            protocol_path.write_text("dummy\n", encoding="utf-8")
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = next(
                item["issues"]
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertTrue(
                any("protocol_packets artifact must be JSONL" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_source_rejects_cross_direction_artifact_reuse(self) -> None:
        def reuse_artifact(product: dict[str, object]) -> None:
            directions = product["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            macos_to_android = directions["macos_nspasteboard_to_android_clipboardmanager"]
            assert isinstance(android_to_macos, dict)
            assert isinstance(macos_to_android, dict)
            android_artifacts = android_to_macos["retained_artifacts"]
            macos_artifacts = macos_to_android["retained_artifacts"]
            assert isinstance(android_artifacts, list)
            assert isinstance(macos_artifacts, list)
            android_sender = next(
                item
                for item in android_artifacts
                if isinstance(item, dict) and item.get("role") == "sender_action"
            )
            macos_sender = next(
                item
                for item in macos_artifacts
                if isinstance(item, dict) and item.get("role") == "sender_action"
            )
            assert isinstance(android_sender, dict)
            assert isinstance(macos_sender, dict)
            macos_sender["path"] = android_sender["path"]
            macos_sender["byte_length"] = android_sender["byte_length"]
            macos_sender["sha256"] = android_sender["sha256"]

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_clipboard_gate_evidence(repo)
            mutate_clipboard_product_source(repo, report_path, reuse_artifact)
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = next(
                item["issues"]
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertTrue(
                any("path for sender_action must be distinct from" in issue for issue in issues),
                issues,
            )

        with_temporary_repo(run)

    def test_clipboard_product_e2e_source_rejects_marker_reuse_and_artifact_direction_drift(self) -> None:
        def drift_marker_and_direction(product: dict[str, object]) -> None:
            directions = product["directions"]
            assert isinstance(directions, dict)
            direction = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(direction, dict)
            direction["deny_marker"] = direction["marker"]
            artifacts = direction["retained_artifacts"]
            assert isinstance(artifacts, list)
            first_artifact = artifacts[0]
            assert isinstance(first_artifact, dict)
            first_artifact["direction"] = "macos_nspasteboard_to_android_clipboardmanager"

        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            report_path = write_clipboard_gate_evidence(repo)
            mutate_clipboard_product_source(repo, report_path, drift_marker_and_direction)
            gate_by_id(manifest, "clipboard_android_macos_product_e2e")["evidence_paths"] = [
                report_path
            ]

            summary = evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                repo_root=repo,
            )

            self.assertEqual(summary["aggregate_verdict"], "insufficient")
            issues = next(
                item["issues"]
                for item in summary["blocking_required_gates"]
                if item["id"] == "clipboard_android_macos_product_e2e"
            )
            self.assertTrue(any("deny_marker must be distinct from marker" in issue for issue in issues), issues)
            self.assertTrue(
                any(
                    ".retained_artifacts[0].direction must be android_clipboardmanager_to_macos_nspasteboard" in issue
                    for issue in issues
                ),
                issues,
            )

        with_temporary_repo(run)

    def test_readme_guard_fails_on_phase0_has_shipped_claim(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "native_pointer_hid_mouse")["verdict"] = "open"

        summary = evaluate_manifest(
            manifest,
            readme_text="Phase 0 has shipped while this text omits the guard.",
        )

        self.assertEqual(summary["aggregate_verdict"], "fail")
        self.assertEqual(summary["readme_guard"]["verdict"], "fail")
        self.assertTrue(summary["readme_guard"]["forbidden_matches"])

    def test_readme_guard_fails_on_stable_production_ready_or_ga_claim(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "native_pointer_hid_mouse")["verdict"] = "open"
        guarded_text = GUARDED_README_TEXT + " "
        claims = (
            "Phase 0 is now stable.",
            "Phase 0 is production-ready.",
            "Phase 0 has reached stable.",
            "Phase 0 GA.",
            "Phase 0 is generally available.",
        )
        for claim in claims:
            with self.subTest(claim=claim):
                summary = evaluate_manifest(manifest, readme_text=guarded_text + claim)

                self.assertEqual(summary["aggregate_verdict"], "fail")
                self.assertEqual(summary["readme_guard"]["verdict"], "fail")
                self.assertTrue(summary["readme_guard"]["forbidden_matches"])

    def test_non_required_gate_issue_still_enforces_readme_guard(self) -> None:
        manifest = complete_manifest()
        manifest["required_gates"].append(
            {
                "id": "future_release_gate",
                "title": "Future release gate",
                "verdict": "pass",
                "required_for_stable_release": False,
                "evidence_strength": "readiness",
                "evidence_paths": ["docs/evidence/future.json"],
                "owner_prs": [],
                "blockers": [],
            }
        )

        summary = evaluate_manifest(manifest, readme_text="Phase 0 status summary")

        self.assertEqual(summary["aggregate_verdict"], "fail")
        self.assertEqual(summary["readme_guard"]["verdict"], "fail")
        self.assertTrue(summary["readme_guard"]["missing_required_phrases"])

    def test_missing_readme_guard_cannot_pass_aggregate(self) -> None:
        summary = evaluate_manifest(complete_manifest(), readme_text=None)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["readme_guard"]["verdict"], "insufficient")

    def test_empty_readme_guard_config_cannot_disable_default_guard(self) -> None:
        manifest = complete_manifest()
        manifest["readme_guard"] = {
            "required_phrases": [],
            "forbidden_regexes": [],
        }
        gate_by_id(manifest, "native_pointer_hid_mouse")["verdict"] = "open"

        summary = evaluate_manifest(manifest, readme_text="Phase 0 is now stable.")

        self.assertEqual(summary["aggregate_verdict"], "fail")
        self.assertEqual(summary["readme_guard"]["verdict"], "fail")
        self.assertTrue(summary["readme_guard"]["missing_required_phrases"])
        self.assertTrue(summary["readme_guard"]["forbidden_matches"])

    def test_invalid_readme_guard_regex_reports_manifest_error(self) -> None:
        manifest = complete_manifest()
        manifest["readme_guard"] = {"forbidden_regexes": ["("]}
        gate_by_id(manifest, "native_pointer_hid_mouse")["verdict"] = "open"

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "invalid regex"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_rejects_invalid_manifest_shape(self) -> None:
        with self.assertRaisesRegex(Phase0StableReleaseError, "kind must be"):
            evaluate_manifest({"schema_version": "vibescreen.evidence/v1", "kind": "wrong"})

    def test_summary_matches_schema_required_fields(self) -> None:
        summary = evaluate_manifest(
            complete_manifest(), readme_text="Phase 0 stable-release summary"
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(summary), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, summary)

    def test_manifest_schema_gate_ids_match_checker(self) -> None:
        schema = json.loads(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
        gate_ids = schema["$defs"]["gate"]["properties"]["id"]["enum"]

        self.assertEqual(gate_ids, list(REQUIRED_GATE_IDS))

    def test_checked_in_manifest_keeps_phase0_open(self) -> None:
        manifest_path = (
            REPO_ROOT
            / "docs/changes/2026-08-22-phase0-stable-release-aggregate/phase0-stable-release-manifest.json"
        )
        readme_path = REPO_ROOT / "README.md"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        summary = evaluate_manifest(
            manifest,
            readme_text=readme_path.read_text(encoding="utf-8"),
            repo_root=REPO_ROOT,
        )

        self.assertEqual(summary["aggregate_verdict"], "blocked")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["readme_guard"]["verdict"], "pass")
        self.assertEqual(summary["closed_required_gate_count"], 6)
        self.assertEqual(summary["owner_pr_guard"]["verdict"], "pass")
        self.assertEqual(summary["owner_pr_guard"]["owner_prs"], [])
        self.assertEqual(
            summary["owner_pr_guard"]["open_pr_numbers"],
            manifest["open_pr_snapshot"]["open_pr_numbers"],
        )
        self.assertEqual(summary["owner_pr_guard"]["stale_owner_prs"], [])
        self.assertEqual(summary["merged_pr_guard"]["verdict"], "pass")
        self.assertEqual(
            summary["merged_pr_guard"]["excluded_pr_numbers"],
            manifest["merged_pr_snapshot"]["excluded_pr_numbers"],
        )
        self.assertEqual(
            summary["source_guard"]["manifest_base_commit"],
            manifest["source"]["base_commit"],
        )
        self.assertEqual(
            summary["merged_pr_guard"]["range"],
            manifest["merged_pr_snapshot"]["range"],
        )
        self.assertEqual(summary["merged_pr_guard"]["non_ancestor_prs"], [])
        macos_gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
        self.assertEqual(macos_gate["verdict"], "open")
        self.assertIn(
            "docs/changes/2026-08-21-host-signing-tcc-preflight/evidence/2026-08-31-macos-host-compatibility-current-base-codex-task-blocked/macos-hardware-compatibility-gate.json",
            macos_gate["evidence_paths"],
        )
        self.assertIn(
            "docs/changes/2026-08-21-host-signing-tcc-preflight/evidence/2026-08-31-macos-host-compatibility-current-base-codex-task-blocked/README.md",
            macos_gate["evidence_paths"],
        )


class Phase0StableReleaseCliTest(unittest.TestCase):
    def test_cli_allows_open_aggregate_by_default_but_writes_summary(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate = gate_by_id(manifest, "host_rss_2h_no_growth")
            gate["verdict"] = "blocked"
            gate["blockers"] = ["host_rss_gate has no current-source pass"]
            manifest_path = repo / "manifest.json"
            readme_path = repo / "README.md"
            output_path = repo / "summary.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            readme_path.write_text(GUARDED_README_TEXT, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest_path),
                    "--readme",
                    str(readme_path),
                    "--repo-root",
                    str(repo),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output_path.read_text())["aggregate_verdict"], "blocked")

        with_temporary_repo(run)

    def test_cli_require_pass_exits_nonzero_for_open_aggregate(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest = complete_manifest_for_repo(repo, base_commit)
            gate_by_id(manifest, "host_rss_2h_no_growth")["verdict"] = "blocked"
            manifest_path = repo / "manifest.json"
            readme_path = repo / "README.md"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            readme_path.write_text(GUARDED_README_TEXT, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest_path),
                    "--readme",
                    str(readme_path),
                    "--repo-root",
                    str(repo),
                    "--expected-source-commit",
                    base_commit,
                    "--require-pass",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("aggregate_verdict", result.stdout)

        with_temporary_repo(run)

    def test_cli_require_pass_requires_expected_source_commit(self) -> None:
        manifest = complete_manifest()
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manifest_path = directory / "manifest.json"
            readme_path = directory / "README.md"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            readme_path.write_text("Phase 0 stable-release summary", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest_path),
                    "--readme",
                    str(readme_path),
                    "--require-pass",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("--require-pass requires --expected-source-commit", result.stderr)

    def test_release_claim_checkout_rejects_dirty_guard_paths(self) -> None:
        def run(repo: Path, base_commit: str) -> None:
            manifest_path = repo / "manifest.json"
            manifest_path.write_text("{}\n", encoding="utf-8")
            clean_commit = commit_all(repo, "manifest")

            self.assertEqual(
                _release_claim_checkout_reasons(
                    repo_root=repo,
                    expected_source_commit=clean_commit,
                    manifest_path=manifest_path,
                    readme_path=repo / "README.md",
                ),
                [],
            )

            (repo / "README.md").write_text(
                f"{GUARDED_README_TEXT}\nDirty but still guarded.\n",
                encoding="utf-8",
            )

            reasons = _release_claim_checkout_reasons(
                repo_root=repo,
                expected_source_commit=clean_commit,
                manifest_path=manifest_path,
                readme_path=repo / "README.md",
            )

            self.assertIn(
                "release-claim guard paths contain uncommitted changes",
                reasons[0],
            )
            self.assertIn("README.md", reasons[0])

        with_temporary_repo(run)

    def test_summary_writer_uses_unique_atomic_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output_path = directory / "phase0-summary.json"

            def write_summary(index: int) -> None:
                _write_summary(
                    output_path,
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "kind": "phase0_stable_release_closure_summary",
                        "writer": index,
                    },
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(write_summary, range(40)))

            summary = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn(summary["writer"], range(40))
            self.assertFalse((directory / "phase0-summary.json.tmp").exists())
            self.assertEqual(list(directory.glob(".phase0-summary.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
