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
MAC_LEASE_STARTUP_PIPELINE = (
    ROOT
    / "baseline/MacHost/Sources/Phase3/ProductSession/InternetSessionLeaseStartupPipeline.swift"
)
MAC_APP_DELEGATE = ROOT / "baseline/MacHost/Sources/AppDelegate.swift"
MAC_LEASE_STARTUP_PIPELINE_TESTS = (
    ROOT
    / "baseline/MacHost/Tests/TelemachusTests/InternetSessionLeaseStartupPipelineTests.swift"
)
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


def assert_ordered(source: str, markers: list[str]) -> None:
    cursor = -1
    for marker in markers:
        next_cursor = source.find(marker, cursor + 1)
        if next_cursor == -1:
            raise AssertionError(f"expected marker after offset {cursor}: {marker!r}")
        cursor = next_cursor


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
        self.assertIn('base64.StdEncoding.EncodeToString([]byte(admission.SessionID))', signaling_client)
        self.assertIn('"protocol_session_id":        protocolSessionID', store)

    def test_profile_issuance_records_digest_not_bearer_tokens(self) -> None:
        migration = read(AUTHORITY_MIGRATION)
        table = bracket_block(migration, "CREATE TABLE authority_session_profile_issuance", "(", ")")

        self.assertIn("request_sha256 bytea NOT NULL", table)
        self.assertNotIn("token", table.lower())
        self.assertNotIn("lease", table.lower())
        self.assertNotIn("credential", table.lower())

    def test_mac_authoritative_delivery_uses_local_lease_issuer_and_bulk_channel(self) -> None:
        delivery = read(MAC_LEASE_DELIVERY)
        issuer_source = read(MAC_LEASE_ISSUER)
        app_delegate = read(MAC_APP_DELEGATE)
        startup_pipeline = read(MAC_LEASE_STARTUP_PIPELINE)
        startup_tests = read(MAC_LEASE_STARTUP_PIPELINE_TESTS)

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

        issue = section_between(
            issuer_source,
            "static func issue(",
            "    static func validateAuthorityExpiry",
        )
        self.assertIn("maximumAuthorityExpiryWindow: TimeInterval = 900", issuer_source)
        self.assertIn("validateAuthorityExpiry", issue)
        self.assertIn("expiresAtUnixSeconds: requested.expiresAtUnixSeconds", issue)
        self.assertNotIn("validFor lifetime", issue)
        self.assertNotIn("nowSeconds + lifetime", issue)
        expiry_validator = bracket_block(
            issuer_source, "static func validateAuthorityExpiry", "{", "}"
        )
        self.assertIn("expiresAt > nowSeconds", expiry_validator)
        self.assertIn(
            "expiresAt <= nowSeconds + maximumAuthorityExpiryWindow",
            expiry_validator,
        )

        send = bracket_block(delivery, "static func send", "{", "}")
        self.assertIn("on session: InternetSessionLeaseSendable", delivery)
        self.assertIn("session.sendBulkRecord(result.payload, transferID: bulkTransferID)", send)
        self.assertIn("protocol InternetSessionLeaseSendable", delivery)
        self.assertIn("extension InternetProductSession: InternetSessionLeaseSendable", delivery)

        self.assertIn("internetAccountID", app_delegate)
        self.assertIn("internetSignalingIssuerTokenName", app_delegate)
        self.assertIn("InternetSessionLeaseProvisioner().createAuthoritativeLeaseDelivery", app_delegate)
        self.assertIn("var createInternetSessionLeaseDelivery", app_delegate)
        self.assertIn("makeInternetSessionProfileRequest", app_delegate)
        self.assertIn("PairedDeviceSecretNames.persistedPairing", app_delegate)
        self.assertIn("identityBinding.requireTarget", app_delegate)
        self.assertIn("loadVerifiedExisting(binding: identityBinding)", app_delegate)
        self.assertIn("sessionIdentifier: delivery.sessionID", app_delegate)
        self.assertIn("bearerToken: delivery.hostSignalingToken", app_delegate)
        self.assertIn("self.queueInternetSessionLeaseDelivery(", app_delegate)
        self.assertIn("delivery,", app_delegate)
        self.assertIn("internetSessionLeaseDeliveryLifecycle", app_delegate)
        self.assertIn("queueInternetSessionLeaseDelivery", app_delegate)
        self.assertIn("sendPendingInternetSessionLeaseDelivery", app_delegate)
        self.assertIn("handleInternetSessionLeaseStateChange", app_delegate)
        self.assertIn("if case .streaming = state", app_delegate)
        self.assertIn("InternetSessionLeaseDelivery.send(delivery, on: session)", app_delegate)
        self.assertIn("serverLifecycle.ownsSession(sessionToken)", app_delegate)
        self.assertIn("internetProductSession === session", app_delegate)
        startup = bracket_block(app_delegate, "private func startInternetProductSession", "{", "}")
        self.assertIn("let pipeline = InternetSessionLeaseStartupPipeline<InternetProductSession>", startup)
        self.assertIn("createDelivery: createInternetSessionLeaseDelivery", startup)
        self.assertIn("requireCurrentStart: { try self.requireCurrentStart(sessionToken) }", startup)
        self.assertIn("try self.internetProductSessionConfiguration(", startup)
        self.assertIn("try session.start(configuration: configuration)", startup)
        self.assertIn("self.queueInternetSessionLeaseDelivery(", startup)
        self.assertIn("screenCapture?.startStreaming", startup)
        self.assertIn("pipeline.start(with: startup.leasePlan)", startup)
        pipeline_start = bracket_block(startup_pipeline, "func start(with plan:", "{", "}")
        assert_ordered(
            pipeline_start,
            [
                "let delivery = try await createDelivery",
                "try requireCurrentStart()",
                "let configuration = try applyDelivery",
                "let session = makeSession()",
                "prepareSession(session, configuration)",
                "try startSession(session, configuration)",
                "guard queueDelivery(delivery, session) else",
                "try await startCapture(session, configuration)",
                "didStart()",
            ],
        )
        self.assertIn("InternetProductSessionError.securityFailure", pipeline_start)
        state_callback = section_between(
            app_delegate,
            "session.onStateChanged =",
            "        session.onError =",
        )
        self.assertIn("await self.handleInternetSessionLeaseStateChange", state_callback)
        startup_builder = bracket_block(
            app_delegate, "private func makeInternetProductSessionStartup", "{", "}"
        )
        assert_ordered(
            startup_builder,
            [
                "makeInternetProductSessionConfiguration",
                "makeInternetSessionProfileRequest",
                "internetIssuerToken()",
            ],
        )
        profile_request = bracket_block(
            app_delegate, "private func makeInternetSessionProfileRequest", "{", "}"
        )
        self.assertIn("guard !settings.internetAccountID.isEmpty else", profile_request)
        self.assertIn("PairedDeviceSecretNames.persistedPairing", profile_request)
        self.assertIn("guard let pairingIdentifier", profile_request)
        self.assertIn("guard let identityBindingName", profile_request)
        self.assertIn("identityBinding.requireTarget", profile_request)
        self.assertIn("loadVerifiedExisting(binding: identityBinding)", profile_request)
        issuer_token = bracket_block(app_delegate, "private func internetIssuerToken", "{", "}")
        self.assertIn("guard let tokenData", issuer_token)
        self.assertIn("!token.isEmpty", issuer_token)
        lifecycle = bracket_block(startup_pipeline, "final class InternetSessionLeaseDeliveryLifecycle", "{", "}")
        self.assertIn("private(set) var pendingDelivery", lifecycle)
        self.assertIn("private(set) var deliverySent = false", lifecycle)
        self.assertIn("pendingDelivery = result", lifecycle)
        self.assertIn("if case .streaming = sessionState()", lifecycle)
        self.assertIn("return true", lifecycle)
        self.assertIn("return deliverySent", lifecycle)
        self.assertIn("pendingDelivery = nil", lifecycle)
        self.assertIn("deliverySent = true", lifecycle)
        self.assertIn("await failClosed(Self.deliveryFailureReason)", lifecycle)
        queue = bracket_block(app_delegate, "private func queueInternetSessionLeaseDelivery", "{", "}")
        self.assertIn("internetSessionLeaseDeliveryLifecycle.queue", queue)
        self.assertIn("self.serverLifecycle.ownsSession(sessionToken)", queue)
        self.assertIn("self.internetProductSession === session", queue)
        self.assertIn("session.snapshotState()", queue)
        self.assertIn("InternetSessionLeaseDelivery.send(delivery, on: session)", queue)
        sender = bracket_block(app_delegate, "private func sendPendingInternetSessionLeaseDelivery", "{", "}")
        self.assertIn("internetSessionLeaseDeliveryLifecycle.sendPending", sender)
        self.assertIn("self.serverLifecycle.ownsSession(sessionToken)", sender)
        self.assertIn("self.internetProductSession === session", sender)
        self.assertIn("InternetSessionLeaseDelivery.send(delivery, on: session)", sender)
        state_change = bracket_block(app_delegate, "private func handleInternetSessionLeaseStateChange", "{", "}")
        self.assertIn("guard case .streaming = state else { return }", state_change)
        self.assertIn("sendPendingInternetSessionLeaseDelivery(", state_change)
        self.assertIn("InternetSessionLeaseDeliveryLifecycle.deliveryFailureReason", state_change)
        self.assertIn("await failClosedInternetSessionLeaseDelivery", state_change)
        fail_closed_delivery = bracket_block(
            app_delegate, "private func failClosedInternetSessionLeaseDelivery", "{", "}"
        )
        self.assertIn("settings.internetStatus = .failed", fail_closed_delivery)
        self.assertIn("await stopServer(preserveRecoveryState: true)", fail_closed_delivery)
        teardown = bracket_block(app_delegate, "private func teardownStreamingComponents", "{", "}")
        self.assertIn("internetSessionLeaseDeliveryLifecycle.reset()", teardown)

        self.assertIn(
            "testStartupPipelineQueuesLeaseAndLifecycleSendsWhenSessionStreams",
            startup_tests,
        )
        self.assertIn(
            "testStartupPipelineOrdersAuthorityDeliveryBeforeSessionStartQueueAndCapture",
            startup_tests,
        )
        self.assertIn(
            "testStartupPipelineFailsClosedWhenQueueRejectsStreamingDelivery",
            startup_tests,
        )
        self.assertIn(
            "testLeaseDeliveryLifecycleQueuesNonStreamingDeliveryAndSendsOnStreaming",
            startup_tests,
        )
        self.assertIn(
            "testLeaseDeliveryLifecycleRejectsStaleOwnershipWithoutMutatingState",
            startup_tests,
        )
        self.assertIn(
            "testLeaseDeliveryLifecycleFailsClosedWhenStreamingSendFails",
            startup_tests,
        )
        self.assertIn(
            "testLeaseDeliverySendForwardsPayloadOnBulkTransferID",
            startup_tests,
        )
        self.assertIn(
            "testLeaseDeliverySendReturnsSessionFailure",
            startup_tests,
        )

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
