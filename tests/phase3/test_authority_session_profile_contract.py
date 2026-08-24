from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAC_LEASE_ISSUER = (
    ROOT
    / "baseline/MacHost/Sources/Phase3/ProductSession/InternetSessionLeaseIssuer.swift"
)
ANDROID_PROFILE_STORE = (
    ROOT
    / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet/InternetSessionProfileStore.kt"
)
AUTHORITY_SERVER = ROOT / "services/authority/internal/authority/server.go"
AUTHORITY_STORE = ROOT / "services/authority/internal/authority/store.go"
AUTHORITY_MIGRATION = ROOT / "services/authority/migrations/001_authority.sql"

SIGNED_ONLY_KEYS = {"lease_host_key_id", "lease_signature"}
EXPECTED_UNSIGNED_KEYS = {
    "version",
    "pairing_id",
    "pinned_host_id",
    "pinned_device_id",
    "lease_device_key_id",
    "signaling_url",
    "signaling_session_id",
    "session_epoch",
    "host_identity_epoch",
    "device_identity_epoch",
    "expires_at",
    "transcript_context",
    "protocol_session_id",
    "signaling_token",
    "ice_servers",
    "allow_insecure_for_testing",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def string_literals(block: str) -> set[str]:
    return set(re.findall(r'"([a-z0-9_]+)"', block))


def bracket_block(source: str, marker: str, open_char: str, close_char: str) -> str:
    start = source.index(marker)
    open_index = source.index(open_char, start)
    depth = 0
    for index in range(open_index, len(source)):
        char = source[index]
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return source[open_index : index + 1]
    raise AssertionError(f"unterminated block after {marker}")


class AuthoritySessionProfileContractTests(unittest.TestCase):
    def test_unsigned_lease_keys_match_mac_decoder_and_android_signed_profile(self) -> None:
        swift = read(MAC_LEASE_ISSUER)
        android = read(ANDROID_PROFILE_STORE)
        authority = read(AUTHORITY_STORE)

        mac_keys = string_literals(bracket_block(swift, "private static let rootKeys", "[", "]"))
        android_keys = string_literals(bracket_block(android, "private val ROOT_KEYS", "(", ")"))
        authority_keys = string_literals(bracket_block(authority, "root := map[string]any", "{", "}"))

        self.assertEqual(mac_keys, EXPECTED_UNSIGNED_KEYS)
        self.assertEqual(authority_keys, mac_keys)
        self.assertEqual(android_keys - mac_keys, SIGNED_ONLY_KEYS)
        self.assertTrue(SIGNED_ONLY_KEYS.isdisjoint(authority_keys))

    def test_profile_issuance_endpoint_is_admin_only_and_schema_backed(self) -> None:
        server = read(AUTHORITY_SERVER)
        store = read(AUTHORITY_STORE)
        migration = read(AUTHORITY_MIGRATION)

        self.assertIn(
            'mux.HandleFunc("POST /v1/session-authority/profiles", s.issueSessionProfile)',
            server,
        )
        endpoint = bracket_block(server, "func (s *Server) issueSessionProfile", "{", "}")
        self.assertIn("if !s.admin(w, r)", endpoint)
        self.assertNotIn("s.signaling", endpoint)

        self.assertIn("CREATE TABLE authority_session_profile_issuance", migration)
        self.assertIn("authority_session_profile_issuance", store)
        self.assertIn("IssueSessionProfile", store)

    def test_profile_issuance_records_digest_not_bearer_tokens(self) -> None:
        migration = read(AUTHORITY_MIGRATION)
        table = bracket_block(migration, "CREATE TABLE authority_session_profile_issuance", "(", ")")

        self.assertIn("request_sha256 bytea NOT NULL", table)
        self.assertNotIn("token", table.lower())
        self.assertNotIn("lease", table.lower())
        self.assertNotIn("credential", table.lower())


if __name__ == "__main__":
    unittest.main()
