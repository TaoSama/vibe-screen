from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.security_vectors import VectorError, load_vectors, run_vectors


class SecurityVectorTests(unittest.TestCase):
    def test_reference_policy_exercises_all_attack_vectors(self) -> None:
        vectors = load_vectors(Path(__file__).parent / "vectors" / "security.json")
        report = run_vectors(vectors)
        self.assertTrue(report["passed"])
        self.assertEqual(report["mode"], "reference-policy-model")
        self.assertGreaterEqual(len(report["cases"]), 10)

    def test_duplicate_vector_name_is_rejected(self) -> None:
        vector = {"name": "same", "action": "enroll", "expect": {"accepted": True, "reason": "enrolled"}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(json.dumps([vector, vector]), encoding="utf-8")
            with self.assertRaises(VectorError):
                load_vectors(path)

    def test_external_sut_protocol_is_executable(self) -> None:
        vectors = load_vectors(Path(__file__).parent / "vectors" / "security.json")[:1]
        responder = "import json,sys\nfor line in sys.stdin:\n print(json.dumps({'accepted':True,'reason':'enrolled'}),flush=True)"
        report = run_vectors(vectors, [sys.executable, "-c", responder])
        self.assertTrue(report["passed"])
        self.assertEqual(report["mode"], "external-sut")

    def test_external_sut_cannot_read_name_or_expected_oracle(self) -> None:
        vectors = load_vectors(Path(__file__).parent / "vectors" / "security.json")[:1]
        responder = (
            "import json,sys\n"
            "for line in sys.stdin:\n"
            " request=json.loads(line)\n"
            " print(json.dumps({'accepted':True,'reason':'enrolled',"
            "'saw_name':'name' in request,'saw_expect':'expect' in request}),flush=True)"
        )
        report = run_vectors(vectors, [sys.executable, "-c", responder])
        actual = report["cases"][0]["actual"]
        self.assertTrue(report["passed"])
        self.assertFalse(actual["saw_name"])
        self.assertFalse(actual["saw_expect"])

    def test_oracle_copying_attack_no_longer_passes(self) -> None:
        vectors = load_vectors(Path(__file__).parent / "vectors" / "security.json")[:2]
        responder = (
            "import json,sys\n"
            "for line in sys.stdin:\n"
            " request=json.loads(line)\n"
            " print(json.dumps(request.get('expect',"
            "{'accepted':False,'reason':'oracle_unavailable'})),flush=True)"
        )
        report = run_vectors(vectors, [sys.executable, "-c", responder])
        self.assertFalse(report["passed"])

    def test_cross_direction_reflection_and_global_revocation_attacks_are_reproduced(self) -> None:
        vectors = load_vectors(Path(__file__).parent / "vectors" / "security.json")
        report = run_vectors(vectors)
        cases = {case["name"]: case for case in report["cases"]}
        self.assertTrue(cases["reject-cross-direction-reflection"]["passed"])
        self.assertEqual(cases["reject-cross-direction-reflection"]["actual"]["reason"], "reflected_sender_role")
        self.assertTrue(cases["reject-reused-authority-sequence-for-other-device"]["passed"])
        self.assertEqual(
            cases["reject-reused-authority-sequence-for-other-device"]["actual"]["reason"],
            "stale_revocation_sequence",
        )


if __name__ == "__main__":
    unittest.main()
