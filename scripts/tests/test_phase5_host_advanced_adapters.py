from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase5_host_advanced_adapters


class Phase5HostAdvancedAdaptersTests(unittest.TestCase):
    def test_report_passes_current_repository_contract(self) -> None:
        report = phase5_host_advanced_adapters.build_report()

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["device_evidence"], "not_collected")
        self.assertEqual(report["device_gates_closed"], [])
        self.assertEqual(len(report["matrix"]), 8)
        self.assertIn("AVAudioEngine audible output", report["scope"])
        self.assertTrue(all(check["status"] == "pass" for check in report["checks"]))

    def test_detects_accidental_advanced_host_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            repo = Path(directory_name)
            for relative in (
                phase5_host_advanced_adapters.PROTOCOL_SESSION,
                phase5_host_advanced_adapters.PHASE5_TECH,
                phase5_host_advanced_adapters.PHASE5_TEST,
                phase5_host_advanced_adapters.README,
                phase5_host_advanced_adapters.IOS_README,
            ):
                (repo / relative).parent.mkdir(parents=True, exist_ok=True)
            (repo / phase5_host_advanced_adapters.PROTOCOL_SESSION).write_text(
                "static func productionHostCapabilities() {\n"
                "if fileTransferAllowed && managedPolicy.fileTransferAllowed {}\n"
                "if wakeHostAvailable && managedPolicy.wakeAllowed {}\n"
                "if managedPolicy.clipboardAllowed {}\n"
                "if touchEnabled && managedPolicy.hostActionsAllowed {}\n"
                "if hdrVideoAvailable {}\n"
                "if audioCaptureAvailable && managedPolicy.audioAllowed {}\n"
                ".colorManagement .multiDisplay .clientVideoControl .audioDataChannel\n"
                "return capabilities\n"
                "}\n",
                encoding="utf-8",
            )
            (repo / phase5_host_advanced_adapters.PHASE5_TECH).write_text(
                "Host-side advanced adapter readiness owner phase5-host-advanced-adapters-gate",
                encoding="utf-8",
            )
            (repo / phase5_host_advanced_adapters.PHASE5_TEST).write_text(
                "does not advertise `.multiClient` in production; does not close the "
                "multi-client/display routing boundary",
                encoding="utf-8",
            )
            (repo / phase5_host_advanced_adapters.README).write_text(
                "host-side advanced adapter readiness owner phase5-host-advanced-adapters-gate",
                encoding="utf-8",
            )
            (repo / phase5_host_advanced_adapters.IOS_README).write_text(
                "Advanced host integrations require independent per-client epochs "
                "and deny-wins managed policy",
                encoding="utf-8",
            )

            report = phase5_host_advanced_adapters.build_report(repo)

        self.assertEqual(report["verdict"], "fail")
        failed = [check for check in report["checks"] if check["status"] == "fail"]
        self.assertEqual(
            [check["name"] for check in failed],
            ["production-host-defaults-do-not-advertise-hdr-audio-multiclient"],
        )

    def test_detects_default_multi_client_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            repo = Path(directory_name)
            for relative in (
                phase5_host_advanced_adapters.PROTOCOL_SESSION,
                phase5_host_advanced_adapters.PHASE5_TECH,
                phase5_host_advanced_adapters.PHASE5_TEST,
                phase5_host_advanced_adapters.README,
                phase5_host_advanced_adapters.IOS_README,
            ):
                (repo / relative).parent.mkdir(parents=True, exist_ok=True)
            (repo / phase5_host_advanced_adapters.PROTOCOL_SESSION).write_text(
                "static func productionHostCapabilities(maximumClients: Int = 2) {\n"
                "if fileTransferAllowed && managedPolicy.fileTransferAllowed {}\n"
                "if wakeHostAvailable && managedPolicy.wakeAllowed {}\n"
                "if managedPolicy.clipboardAllowed {}\n"
                "if touchEnabled && managedPolicy.hostActionsAllowed {}\n"
                "if hdrVideoAvailable {}\n"
                "if audioCaptureAvailable && managedPolicy.audioAllowed {}\n"
                "if maximumClients > 1 { capabilities.insert(.multiClient) }\n"
                ".colorManagement .multiDisplay .clientVideoControl\n"
                "return capabilities\n"
                "}\n",
                encoding="utf-8",
            )
            (repo / phase5_host_advanced_adapters.PHASE5_TECH).write_text(
                "Host-side advanced adapter readiness owner phase5-host-advanced-adapters-gate",
                encoding="utf-8",
            )
            (repo / phase5_host_advanced_adapters.PHASE5_TEST).write_text(
                "does not advertise `.multiClient` in production; does not close the "
                "multi-client/display routing boundary",
                encoding="utf-8",
            )
            (repo / phase5_host_advanced_adapters.README).write_text(
                "host-side advanced adapter readiness owner phase5-host-advanced-adapters-gate",
                encoding="utf-8",
            )
            (repo / phase5_host_advanced_adapters.IOS_README).write_text(
                "Advanced host integrations require independent per-client epochs "
                "and deny-wins managed policy",
                encoding="utf-8",
            )

            report = phase5_host_advanced_adapters.build_report(repo)

        self.assertEqual(report["verdict"], "fail")
        failed = [check for check in report["checks"] if check["status"] == "fail"]
        self.assertEqual(
            [check["name"] for check in failed],
            ["production-host-defaults-do-not-advertise-hdr-audio-multiclient"],
        )

    def test_accepts_explicit_multi_client_opt_in_gate(self) -> None:
        capability_body = (
            "static func productionHostCapabilities(\n"
            "    touchEnabled: Bool,\n"
            "    maximumClients: Int = 1\n"
            ") -> Set<VSCapability> {\n"
            "if maximumClients > 1 { capabilities.insert(.multiClient) }\n"
            "return capabilities\n"
            "}\n"
        )

        result = phase5_host_advanced_adapters.check_default_advanced_capabilities(
            capability_body
        )

        self.assertEqual(result.status, "pass")

    def test_rejects_unguarded_multi_client_capability(self) -> None:
        capability_body = (
            "static func productionHostCapabilities(\n"
            "    touchEnabled: Bool,\n"
            "    maximumClients: Int = 1\n"
            ") -> Set<VSCapability> {\n"
            "capabilities.insert(.multiClient)\n"
            "return capabilities\n"
            "}\n"
        )

        result = phase5_host_advanced_adapters.check_default_advanced_capabilities(
            capability_body
        )

        self.assertEqual(result.status, "fail")

    def test_cli_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "report.json"
            exit_code = phase5_host_advanced_adapters.main(["--output", str(output)])
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["kind"], phase5_host_advanced_adapters.KIND)
        self.assertEqual(report["schema"], phase5_host_advanced_adapters.SCHEMA)


if __name__ == "__main__":
    unittest.main()
