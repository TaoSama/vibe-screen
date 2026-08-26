from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.network_recovery_blocked_evidence import build_evidence, build_parser


class NetworkRecoveryBlockedEvidenceDedupeTests(unittest.TestCase):
    def test_duplicate_blockers_are_deduplicated_in_order(self) -> None:
        repeated_blocker = "no_public_internet_or_remote_turn_route"
        final_blocker = "no_automatic_authority_product_profile_invocation"
        args = build_parser().parse_args(
            [
                "--output-dir",
                "/tmp/unused",
                "--blocker",
                repeated_blocker,
                "--blocker",
                final_blocker,
            ]
        )
        evidence = build_evidence(
            args,
            {"commit": "b" * 40, "tree_status": "dirty", "status_sha256": "c" * 64},
        )

        self.assertEqual(evidence["blockers"].count(repeated_blocker), 1)
        self.assertEqual(evidence["blockers"][-1], final_blocker)


if __name__ == "__main__":
    unittest.main()
