import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence import host_socket_fd


LSOF_WITH_CLOSED = r"""$ bash -lc lsof -nP -iTCP:54321 | head -80
COMMAND     PID     USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
Vibe\x20S 92943 <user>    7u  IPv4 0xae6002c4c974911a      0t0  TCP 127.0.0.1:54321 (LISTEN)
Vibe\x20S 92943 <user>    8u  IPv4 0x76b74def0ce56e3c      0t0  TCP 127.0.0.1:54321->127.0.0.1:57649 (CLOSED)
Vibe\x20S 92943 <user>   52u  IPv4 0xd6f64fa7a6e5a8e4      0t0  TCP 127.0.0.1:54321->127.0.0.1:56321 (ESTABLISHED)
"""


LSOF_WITHOUT_CLOSED = r"""COMMAND     PID     USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
Vibe\x20S 92943 <user>    7u  IPv4 0xae6002c4c974911a      0t0  TCP 127.0.0.1:54321 (LISTEN)
Vibe\x20S 92943 <user>   52u  IPv4 0xd6f64fa7a6e5a8e4      0t0  TCP 127.0.0.1:54321->127.0.0.1:56321 (ESTABLISHED)
"""


class HostSocketFDTest(unittest.TestCase):
    def test_parse_lsof_counts_tcp_states(self):
        entries = host_socket_fd.parse_lsof(LSOF_WITH_CLOSED)
        summary = host_socket_fd.summarize(entries)

        self.assertEqual(summary["entry_count"], 3)
        self.assertEqual(summary["listen_count"], 1)
        self.assertEqual(summary["established_count"], 1)
        self.assertEqual(summary["closed_count"], 1)
        self.assertEqual(summary["closed_fds"], ["8u"])

    def test_report_fails_when_closed_socket_fd_is_present(self):
        report = host_socket_fd.build_report(
            [host_socket_fd.sample_from_text("saved-lsof", LSOF_WITH_CLOSED)]
        )

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["gate"]["can_close_host_rss_no_growth_gate"])
        self.assertIn("CLOSED", report["reasons"][0])

    def test_report_passes_without_closed_socket_fd(self):
        report = host_socket_fd.build_report(
            [host_socket_fd.sample_from_text("saved-lsof", LSOF_WITHOUT_CLOSED)]
        )

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["samples"][0]["summary"]["closed_count"], 0)

    def test_empty_lsof_sample_is_insufficient(self):
        report = host_socket_fd.build_report(
            [host_socket_fd.sample_from_text("empty-lsof", "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n")]
        )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn("no TCP entries", report["reasons"][0])

    def test_lsof_sampling_uses_pid_and_port_intersection(self):
        with patch.object(host_socket_fd.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = LSOF_WITHOUT_CLOSED
            run.return_value.stderr = ""

            output = host_socket_fd.run_lsof(pid=92943, port=54321)

        self.assertEqual(output, LSOF_WITHOUT_CLOSED)
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/sbin/lsof", "-nP", "-a", "-p", "92943", "-iTCP:54321"],
        )

    def test_cli_writes_json_from_saved_snapshot(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory) / "lsof.txt"
            path.write_text(LSOF_WITH_CLOSED, encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = host_socket_fd.main(["--input", str(path)])

        self.assertEqual(exit_code, 2)
        report = json.loads(out.getvalue())
        self.assertEqual(report["kind"], "host_socket_fd_diagnostic")
        self.assertEqual(report["samples"][0]["summary"]["closed_count"], 1)


if __name__ == "__main__":
    unittest.main()
