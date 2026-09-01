from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAC_LEASE_ISSUER = (
    ROOT
    / "baseline/MacHost/Sources/Phase3/ProductSession/InternetSessionLeaseIssuer.swift"
)
MAC_LEASE_DELIVERY = (
    ROOT
    / "baseline/MacHost/Sources/Phase3/ProductSession/InternetSessionLeaseDelivery.swift"
)
MAC_APP_DELEGATE = ROOT / "baseline/MacHost/Sources/AppDelegate.swift"
ANDROID_MAIN_ACTIVITY = (
    ROOT
    / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt"
)
ANDROID_LEASE_RECEIVER = (
    ROOT
    / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet/AuthenticatedSessionLeaseReceiver.kt"
)
ANDROID_PROFILE_STORE = (
    ROOT
    / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet/InternetSessionProfileStore.kt"
)
AUTHORITY_SERVER = ROOT / "services/authority/internal/authority/server.go"
AUTHORITY_STORE = ROOT / "services/authority/internal/authority/store.go"
AUTHORITY_MIGRATION = ROOT / "services/authority/migrations/001_authority.sql"
AUTHORITY_README = ROOT / "services/authority/README.md"
SIGNALING_AUTHORITY_CLIENT = (
    ROOT / "services/signaling/internal/signaling/authority_client.go"
)

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


def section_between(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


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

    def test_signaling_admission_can_embed_unsigned_session_profile(self) -> None:
        server = read(AUTHORITY_SERVER)
        store = read(AUTHORITY_STORE)
        signaling_client = read(SIGNALING_AUTHORITY_CLIENT)

        self.assertIn("SessionProfile *SignalingSessionProfileRequest", read(ROOT / "services/authority/internal/authority/model.go"))
        self.assertIn("SessionProfile *SessionProfileResponse", read(ROOT / "services/authority/internal/authority/model.go"))

        create_signaling = bracket_block(server, "func (s *Server) createSignaling", "{", "}")
        self.assertIn("sessionProfileRequestFromSignaling", create_signaling)
        self.assertIn("validateSessionProfileRequest", create_signaling)

        self.assertIn("attachSignalingSessionProfileTx", store)
        self.assertIn("signalingProfileRequestID", store)
        self.assertIn("sessionProfileResponse", store)
        self.assertIn("authority_session_profile_issuance", store)
        self.assertIn("ErrConflict", bracket_block(store, "func (s *PostgresStore) attachSignalingSessionProfileTx", "{", "}"))

        binding = bracket_block(store, "func sessionProfileRequestFromSignaling", "{", "}")
        self.assertIn("HostIdentity.DeviceID != request.HostDeviceID", binding)
        self.assertIn("ClientIdentity.DeviceID != request.ClientDeviceID", binding)

        comparator = bracket_block(store, "func sameSignalingAdmissionRequest", "{", "}")
        self.assertNotIn("SessionProfile", comparator)

        self.assertIn('\"signaling-profile-%x\"', store)
        self.assertIn('\"profile-%x\"', store)

        self.assertIn(
            "SessionProfile *SessionProfileRequest",
            bracket_block(signaling_client, "type authoritySignalingRequest", "{", "}"),
        )
        self.assertIn(
            "SessionProfile *SessionProfileResponse",
            bracket_block(signaling_client, "type authoritySignalingAdmission", "{", "}"),
        )
        self.assertIn("validAuthoritySessionProfile", signaling_client)
        self.assertIn("decodeAuthorityUnsignedAndroidLease", signaling_client)

        unsigned_lease = bracket_block(
            signaling_client, "type authorityUnsignedAndroidLease", "{", "}"
        )
        self.assertTrue(SIGNED_ONLY_KEYS.isdisjoint(string_literals(unsigned_lease)))
        signaling_keys = string_literals(
            section_between(
                signaling_client,
                "var authorityUnsignedAndroidLeaseKeys",
                "var authorityUnsignedAndroidLeaseICEKeys",
            )
        )
        self.assertEqual(signaling_keys, EXPECTED_UNSIGNED_KEYS)
        self.assertIn("sameJSONKeys(root, authorityUnsignedAndroidLeaseKeys)", signaling_client)
        self.assertIn('sameICEKeys(root["ice_servers"])', signaling_client)
        self.assertIn("lease.SignalingToken == admission.ClientToken", signaling_client)
        self.assertIn("lease.LeaseDeviceKeyID == request.SessionProfile.ClientIdentity.KeyID", signaling_client)

    def test_profile_issuance_records_digest_not_bearer_tokens(self) -> None:
        migration = read(AUTHORITY_MIGRATION)
        table = bracket_block(migration, "CREATE TABLE authority_session_profile_issuance", "(", ")")

        self.assertIn("request_sha256 bytea NOT NULL", table)
        self.assertNotIn("token", table.lower())
        self.assertNotIn("lease", table.lower())
        self.assertNotIn("credential", table.lower())

    def test_mac_authoritative_delivery_uses_local_lease_issuer_and_bulk_channel(self) -> None:
        delivery = read(MAC_LEASE_DELIVERY)
        app_delegate = read(MAC_APP_DELEGATE)

        signature_start = delivery.index("func createAuthoritativeLeaseDelivery")
        signature = delivery[
            signature_start : delivery.index(") async throws", signature_start)
        ]
        provisioner = section_between(
            delivery,
            "func createAuthoritativeLeaseDelivery",
            "\n\n    func makeCreateSessionRequest",
        )
        self.assertIn("InternetSessionLeaseDelivery.deliveryResult", provisioner)
        self.assertIn("matching: request", provisioner)
        self.assertNotIn("leaseHostKeyID", signature)
        self.assertNotIn("signer:", signature)
        self.assertNotIn("signedLeaseIssuer", delivery)
        self.assertNotIn("func createSignedLeaseDelivery", delivery)
        self.assertNotIn("static func signUnsignedLease", delivery)
        self.assertNotIn("forUnsignedLease unsignedLease", delivery)

        safe_delivery = bracket_block(delivery, "static func deliveryResult", "{", "}")
        self.assertIn("issueSignedLease(decoded.unsignedAndroidLeaseData)", safe_delivery)
        self.assertIn("deliveryPayload(forSignedLease: signedLease)", safe_delivery)
        issuer = bracket_block(delivery, "private static func issueSignedLease", "{", "}")
        self.assertIn("InternetSessionLeaseIssuer.issue(unsignedJSON: unsignedLease)", issuer)

        send = bracket_block(delivery, "static func send", "{", "}")
        self.assertIn("session.sendBulkRecord(result.payload, transferID: bulkTransferID)", send)

        self.assertIn("pendingInternetSessionLeaseDelivery", app_delegate)
        self.assertIn("queueInternetSessionLeaseDelivery", app_delegate)
        self.assertIn("sendPendingInternetSessionLeaseDelivery", app_delegate)
        self.assertIn("if case .streaming = state", app_delegate)
        self.assertIn("InternetSessionLeaseDelivery.send(delivery, on: session)", app_delegate)
        self.assertIn("serverLifecycle.ownsSession(sessionToken)", app_delegate)
        self.assertIn("internetProductSession === session", app_delegate)

    def test_android_product_session_imports_authenticated_session_lease_bulk(self) -> None:
        receiver = read(ANDROID_LEASE_RECEIVER)
        main_activity = read(ANDROID_MAIN_ACTIVITY)

        constructor = section_between(
            receiver,
            "class AuthenticatedSessionLeaseReceiver(",
            ") {",
        )
        self.assertIn("isActive: () -> Boolean = { true }", constructor)
        self.assertIn('check(isActive()) { "Stale Internet session cannot import a lease" }', receiver)
        self.assertIn("if (hasSessionLeasePurpose && !receiver.isActiveSession()) return", receiver)

        connect = bracket_block(main_activity, "private fun connectInternet(", "{", "}")
        self.assertIn("AuthenticatedSessionLeaseReceiver(", connect)
        self.assertIn("internetProfileStore,", connect)
        self.assertIn("internetStoredSessionFactory,", connect)
        self.assertIn("internetRevocationCoordinator,", connect)
        self.assertIn("isActive = ::isCurrentInternetSession", connect)
        self.assertIn("val productCallbacks = authenticatedSessionLeaseReceiver.importingCallbacks(callbacks)", connect)
        self.assertIn("codec,\n                    productCallbacks,", connect)

    def test_authority_documents_endpoint_signing_key_boundary(self) -> None:
        readme = read(AUTHORITY_README).lower()

        self.assertIn("does not persist or prove", readme)
        self.assertIn("signing public keys", readme)
        self.assertIn("endpoint binding", readme)
        self.assertIn("paired local keychain identity", readme)
        self.assertIn("android-importable lease without the host private key", readme)
        self.assertIn("must not fall\nback to local lease issuance", readme)


if __name__ == "__main__":
    unittest.main()
