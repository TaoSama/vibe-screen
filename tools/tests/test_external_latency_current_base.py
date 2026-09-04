import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPOSITORY_ROOT / "docs"
EXPECTED_LATENCY_SOURCE_COMMIT = "dd6978cb5e8e36b6aa15995361ed28ee54cd6b3e"
EXPECTED_CAMERA_PREFLIGHT_SOURCE_COMMIT = "87e16d8bea4446c1ca449045678f1bafc7fd6cb2"
EXPECTED_LATENCY_PROFILES = {
    "usb-glass-to-glass-sub50",
    "lan-glass-to-glass-sub80",
    "input-p95-sub50",
}
LATENCY_EVIDENCE_FILENAMES = (
    "raw-camera.mov",
    "raw-camera.mp4",
    "raw-camera-fixture.mov",
    "latency-evidence-report.json",
    "latency-evidence.json",
)
BLOCKED_LATENCY_DIRS = (
    "docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-30-nubia-p0110-latency-camera-current-base-blocked",
    "docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-28-nubia-p0110-latency-current-base-blocked",
    "docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-27-nubia-p0110-latency-current-base-blocked",
)
RECONNECT_BLOCKED_DIRS = (
    "docs/changes/2026-08-21-phase1-reconnect-timing/evidence/2026-08-28-p0110-usb-reconnect-current-base-blocked",
)


class ExternalLatencyCurrentBaseOwnerTest(unittest.TestCase):
    def test_no_raw_camera_latency_packages_under_docs(self) -> None:
        for path in DOCS_ROOT.rglob("*"):
            if not path.is_file():
                continue
            if path.name not in LATENCY_EVIDENCE_FILENAMES:
                continue
            self.fail(
                f"unexpected committed latency evidence artifact: {path.relative_to(REPOSITORY_ROOT)}"
            )

    def test_latest_current_base_latency_preflight_remains_blocked(self) -> None:
        preflight_path = REPOSITORY_ROOT / BLOCKED_LATENCY_DIRS[0] / "latency-preflight.json"
        self.assertTrue(preflight_path.is_file(), preflight_path)
        document = json.loads(preflight_path.read_text(encoding="utf-8"))
        self.assertEqual(document["status"], "blocked")
        self.assertEqual(document["repository_revision"], EXPECTED_CAMERA_PREFLIGHT_SOURCE_COMMIT)
        self.assertEqual(
            {profile["profile"] for profile in document["gate_profiles"]},
            EXPECTED_LATENCY_PROFILES,
        )
        self.assertEqual(len(document["gate_profiles"]), 3)
        for profile in document["gate_profiles"]:
            self.assertFalse(profile["can_attempt_formal_gate"])
            self.assertFalse(profile["can_close_performance_gate"])
            self.assertTrue(profile["missing_requirements"])

    def test_retained_current_base_latency_preflights_remain_blocked(self) -> None:
        expected_revisions = {
            "2026-08-30-nubia-p0110-latency-camera-current-base-blocked": EXPECTED_CAMERA_PREFLIGHT_SOURCE_COMMIT,
            "2026-08-28-nubia-p0110-latency-current-base-blocked": EXPECTED_LATENCY_SOURCE_COMMIT,
        }
        for directory in BLOCKED_LATENCY_DIRS:
            with self.subTest(directory=directory):
                preflight_path = REPOSITORY_ROOT / directory / "latency-preflight.json"
                self.assertTrue(preflight_path.is_file(), preflight_path)
                document = json.loads(preflight_path.read_text(encoding="utf-8"))
                self.assertEqual(document["status"], "blocked")
                expected_revision = expected_revisions.get(Path(directory).name)
                if expected_revision is not None:
                    self.assertEqual(document["repository_revision"], expected_revision)
                for profile in document["gate_profiles"]:
                    self.assertFalse(profile["can_close_performance_gate"])

    def test_reconnect_timing_blocked_summary_does_not_close_gate(self) -> None:
        summary_path = REPOSITORY_ROOT / RECONNECT_BLOCKED_DIRS[0] / "reconnect-timing-summary.json"
        self.assertTrue(summary_path.is_file(), summary_path)
        document = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(document["verdict"], "blocked")
        self.assertFalse(document["can_close_timing_gate"])
        self.assertFalse(document["can_close_requested_scope"])
        self.assertIn("client-kill", document["full_gate_missing_disruptions"])
        self.assertIn("adb-reverse-disconnect", document["full_gate_missing_disruptions"])
        self.assertIn("lan-network-interrupt", document["full_gate_missing_disruptions"])


if __name__ == "__main__":
    unittest.main()
