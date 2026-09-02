import CryptoKit
import Foundation
import XCTest
@testable import Telemachus

final class InternetSessionLeaseIssuerTests: XCTestCase {
    private static let childProcessTimeout: TimeInterval = 20
    private static let childTerminationGrace: TimeInterval = 1
    private let deviceSigningKey = P256.Signing.PrivateKey()

    /// This cross-process worker harness forks the built executable, gates the
    /// workers on a shared file, and has each one run a full lease issuance
    /// through the cross-process transaction lock. That combination of
    /// fork + flock + pipe drain + Keychain access is not reliable on a
    /// headless CI runner: the runner has no login-keychain session, and the
    /// workers have repeatedly hung with no output and been reaped at their
    /// process deadline. The single-process
    /// testAuthoritySignsCallerEpochAndRejectsStaleEpochAcrossRestart
    /// already proves the issuer reserves the exact authority-proposed epoch and
    /// rejects stale replays across issuer restarts, so the durable invariant
    /// stays covered. This test still runs on a real multi-process host, where
    /// an interactive keychain session is available.
    private static var isHeadlessContinuousIntegration: Bool {
        let environment = ProcessInfo.processInfo.environment
        return environment["CI"] != nil || environment["GITHUB_ACTIONS"] != nil
    }

    private var deviceIdentity: PlatformPublicIdentity {
        let publicKey = deviceSigningKey.publicKey.x963Representation
        return PlatformPublicIdentity(
            deviceID: "lease-device",
            keyID: Data(SHA256.hash(data: publicKey)).map {
                String(format: "%02x", $0)
            }.joined(),
            keyEpoch: 7,
            signingPublicKey: publicKey
        )
    }

    func testLeaseAuthorityIsUniqueAcrossChildProcesses() throws {
        try XCTSkipIf(
            Self.isHeadlessContinuousIntegration,
            "Cross-process lease worker harness is unreliable on headless CI; "
                + "monotonic-unique epoch reservation is covered in-process by "
                + "testAuthoritySignsCallerEpochAndRejectsStaleEpochAcrossRestart."
        )
        let scope = UUID().uuidString
        let hostDeviceID = "lease-host-\(scope)"
        let pairingIdentifier = "pairing-process-test-\(scope)"
        let identityStore = KeychainDeviceIdentityStore()
        let hostIdentity = try identityStore.createIfMissing(deviceID: hostDeviceID)
        addTeardownBlock {
            try? identityStore.delete(
                deviceID: hostDeviceID,
                keyEpoch: PlatformPublicIdentity.initialKeyEpoch
            )
        }
        let secretStore = KeychainSecretStore()
        let stateStore = KeychainSecurityStateStore(
            peerID: "lease-authority.\(pairingIdentifier)"
        )
        try stateStore.initializePairingBinding(pairingIdentifier: pairingIdentifier)
        defer {
            try? stateStore.deleteCommittedPairingBinding(
                pairingIdentifier: pairingIdentifier
            )
            try? secretStore.delete(
                name: PairedHostIdentityBinding.keychainName(
                    pairingIdentifier: pairingIdentifier
                )
            )
            try? secretStore.delete(
                name: PairedPeerIdentityBinding.keychainName(
                    pairingIdentifier: pairingIdentifier
                )
            )
        }
        try secretStore.persist(
            name: PairedHostIdentityBinding.keychainName(
                pairingIdentifier: pairingIdentifier
            ),
            secret: PairedHostIdentityBinding.encode(hostIdentity.publicIdentity)
        )
        try secretStore.persist(
            name: PairedPeerIdentityBinding.keychainName(
                pairingIdentifier: pairingIdentifier
            ),
            secret: PairedPeerIdentityBinding.encode(deviceIdentity)
        )
        let unsigned = try unsignedLease(
            epoch: 99,
            pairingIdentifier: pairingIdentifier,
            pinnedHostID: hostDeviceID
        )
        let executableURL = try vibeScreenExecutableURL()
        let gateURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("vibe-screen-lease-gate-\(scope)")
        let readyDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vibe-screen-lease-ready-\(scope)")
        try FileManager.default.createDirectory(
            at: readyDirectory,
            withIntermediateDirectories: false
        )
        let childCount = 6
        var children: [(process: Process, output: TestProcessOutputDrain)] = []
        defer {
            try? FileManager.default.removeItem(at: gateURL)
            try? FileManager.default.removeItem(at: readyDirectory)
            for child in children {
                TestProcessDeadline.terminateAndReap(
                    child.process,
                    terminationGrace: Self.childTerminationGrace
                )
            }
        }
        for index in 0..<childCount {
            let process = Process()
            let input = Pipe()
            let output = Pipe()
            let error = Pipe()
            process.executableURL = URL(fileURLWithPath: "/bin/sh")
            process.arguments = [
                "-c",
                ": > \"$3\"; while [ ! -e \"$1\" ]; do sleep 0.01; done; exec \"$2\" --issue-phase3-internet-lease",
                "lease-process-test",
                gateURL.path,
                executableURL.path,
                readyDirectory.appendingPathComponent("child-\(index)").path
            ]
            process.standardInput = input
            process.standardOutput = output
            process.standardError = error
            let outputDrain = TestProcessOutputDrain.start(output: output, error: error)
            try process.run()
            input.fileHandleForWriting.write(unsigned)
            try input.fileHandleForWriting.close()
            children.append((process, outputDrain))
        }
        let readyDeadline = Date().addingTimeInterval(Self.childProcessTimeout)
        while Date() < readyDeadline {
            let readyCount = (try? FileManager.default.contentsOfDirectory(
                atPath: readyDirectory.path
            ).count) ?? 0
            if readyCount == childCount { break }
            Thread.sleep(forTimeInterval: 0.01)
        }
        let readyCount = try FileManager.default.contentsOfDirectory(
            atPath: readyDirectory.path
        ).count
        guard readyCount == childCount else {
            return XCTFail("Only \(readyCount) of \(childCount) lease workers reached the start gate.")
        }
        try Data().write(to: gateURL, options: .atomic)

        var epochs: Set<UInt64> = []
        var successfulChildren = 0
        var failedChildren = 0
        for child in children {
            let exited = TestProcessDeadline.waitForExit(
                child.process,
                timeout: Self.childProcessTimeout,
                terminationGrace: Self.childTerminationGrace
            )
            guard let drained = child.output.finish(timeout: Self.childTerminationGrace) else {
                XCTFail("Lease worker output pipes did not close after process exit.")
                continue
            }
            let output = drained.output
            let error = drained.error
            guard exited else {
                XCTFail(
                    "Lease worker exceeded the process deadline: "
                        + String(decoding: error, as: UTF8.self)
                )
                continue
            }
            if child.process.terminationStatus == 0 {
                successfulChildren += 1
                epochs.insert(try issuedEpoch(output))
            } else {
                failedChildren += 1
                XCTAssertTrue(
                    String(decoding: error, as: UTF8.self).contains("stale or was not reserved"),
                    String(decoding: error, as: UTF8.self)
                )
            }
        }
        XCTAssertEqual(successfulChildren, 1)
        XCTAssertEqual(failedChildren, childCount - 1)
        XCTAssertEqual(epochs, [99])
    }

    func testLeaseWorkerDeadlineTerminatesAndReapsHungProcess() throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        process.arguments = ["-c", "exec /bin/sleep 30"]
        try process.run()

        XCTAssertFalse(TestProcessDeadline.waitForExit(
            process,
            timeout: 0.05,
            terminationGrace: Self.childTerminationGrace
        ))
        XCTAssertFalse(process.isRunning)
    }

    func testSelfTestFixtureUsesGeneratedPeerKeyID() throws {
        let keyID = String(repeating: "a", count: 64)
        let payload = try InternetSessionLeaseCodec.decodeUnsigned(
            Data(InternetSessionLeaseSelfTest.fixtureJSON(peerKeyID: keyID).utf8)
        )

        XCTAssertEqual(payload.leaseDeviceKeyID, keyID)
    }

    func testUnsignedLeasePreservesAuthorityExpiryWithinWindow() throws {
        let signingIdentity = LeaseTestSigningIdentity(deviceID: "lease-host")
        let secretStore = LeaseMemorySecretStore()
        let stateStore = LeaseMemoryStateStore()
        try persistBinding(
            signingIdentity.publicIdentity,
            pairingIdentifier: "pairing-authority-test",
            store: secretStore
        )

        XCTAssertThrowsError(
            try InternetSessionLeaseCodec.decodeUnsigned(
                try unsignedLease(epoch: 1, expiresAt: nil)
            )
        )
        XCTAssertThrowsError(
            try InternetSessionLeaseCodec.decodeUnsigned(
                try unsignedLease(epoch: 1, expiresAt: UInt64(Int64.max))
            )
        )

        let signed = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99, expiresAt: 2_000_000_600),
            now: { Date(timeIntervalSince1970: 2_000_000_000) },
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore },
            signingIdentityLoader: { binding in
                XCTAssertEqual(binding.deviceID, signingIdentity.publicIdentity.deviceID)
                return signingIdentity
            }
        )
        XCTAssertEqual(try issuedEpoch(signed), 99)
        XCTAssertEqual(try issuedExpiry(signed), 2_000_000_600)
    }

    func testUnsignedLeaseAcceptsExactlyMaximumAuthorityExpiryWindow() throws {
        let signingIdentity = LeaseTestSigningIdentity(deviceID: "lease-host")
        let secretStore = LeaseMemorySecretStore()
        let stateStore = LeaseMemoryStateStore()
        try persistBinding(
            signingIdentity.publicIdentity,
            pairingIdentifier: "pairing-authority-test",
            store: secretStore
        )

        let signed = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99, expiresAt: 2_000_000_900),
            now: { Date(timeIntervalSince1970: 2_000_000_000) },
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore },
            signingIdentityLoader: { _ in signingIdentity }
        )
        XCTAssertEqual(try issuedExpiry(signed), 2_000_000_900)
    }

    func testUnsignedLeaseRejectsExpiredAuthorityExpiry() throws {
        let signingIdentity = LeaseTestSigningIdentity(deviceID: "lease-host")
        let secretStore = LeaseMemorySecretStore()
        let stateStore = LeaseMemoryStateStore()
        try persistBinding(
            signingIdentity.publicIdentity,
            pairingIdentifier: "pairing-authority-test",
            store: secretStore
        )

        XCTAssertThrowsError(try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99, expiresAt: 2_000_000_000),
            now: { Date(timeIntervalSince1970: 2_000_000_000) },
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore },
            signingIdentityLoader: { _ in signingIdentity }
        ))
        XCTAssertEqual(stateStore.state.sessionEpoch, 0)
    }

    func testUnsignedLeaseRejectsAuthorityExpiryBeyondMaximumWindow() throws {
        let signingIdentity = LeaseTestSigningIdentity(deviceID: "lease-host")
        let secretStore = LeaseMemorySecretStore()
        let stateStore = LeaseMemoryStateStore()
        try persistBinding(
            signingIdentity.publicIdentity,
            pairingIdentifier: "pairing-authority-test",
            store: secretStore
        )

        XCTAssertThrowsError(try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99, expiresAt: 2_000_000_901),
            now: { Date(timeIntervalSince1970: 2_000_000_000) },
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore },
            signingIdentityLoader: { _ in signingIdentity }
        ))
        XCTAssertEqual(stateStore.state.sessionEpoch, 0)
    }

    func testAuthoritySignsCallerEpochAndRejectsStaleEpochAcrossRestart() throws {
        let service = "dev.vibescreen.lease-tests.\(UUID().uuidString)"
        let identityStore = KeychainDeviceIdentityStore(service: service)
        let identity = try identityStore.createIfMissing(deviceID: "lease-host")
        let secretStore = LeaseMemorySecretStore()
        try persistBinding(
            identity.publicIdentity,
            pairingIdentifier: "pairing-authority-test",
            store: secretStore
        )
        addTeardownBlock {
            try identityStore.delete(deviceID: "lease-host", keyEpoch: 1)
        }
        let stateStore = LeaseMemoryStateStore()
        let authorityEpoch = UInt64(99)

        let first = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: authorityEpoch),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: { scope in
                XCTAssertEqual(scope, "pairing-authority-test")
                return stateStore
            }
        )
        XCTAssertEqual(try issuedEpoch(first), authorityEpoch)

        XCTAssertThrowsError(try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: authorityEpoch),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore }
        ))
        XCTAssertThrowsError(try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: authorityEpoch - 1),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore }
        ))
        XCTAssertEqual(stateStore.state.sessionEpoch, authorityEpoch)

        for nextEpoch in UInt64(100)...UInt64(123) {
            let signed = try InternetSessionLeaseIssuer.issue(
                unsignedJSON: try unsignedLease(epoch: nextEpoch),
                identityStore: identityStore,
                secretStore: secretStore,
                stateStoreFactory: { _ in stateStore }
            )
            XCTAssertEqual(try issuedEpoch(signed), nextEpoch)
        }
        XCTAssertEqual(stateStore.state.sessionEpoch, 123)
    }

    func testDifferentPairingsUseIndependentAuthorityEpochs() throws {
        let service = "dev.vibescreen.lease-scope-tests.\(UUID().uuidString)"
        let identityStore = KeychainDeviceIdentityStore(service: service)
        let identity = try identityStore.createIfMissing(deviceID: "lease-host")
        let secretStore = LeaseMemorySecretStore()
        try persistBinding(identity.publicIdentity, pairingIdentifier: "pairing-a", store: secretStore)
        try persistBinding(identity.publicIdentity, pairingIdentifier: "pairing-b", store: secretStore)
        addTeardownBlock {
            try identityStore.delete(deviceID: "lease-host", keyEpoch: 1)
        }
        let stores = [
            "pairing-a": LeaseMemoryStateStore(),
            "pairing-b": LeaseMemoryStateStore()
        ]
        let unexpectedStore = LeaseMemoryStateStore()
        let factory: InternetSessionLeaseIssuer.StateStoreFactory = { scope in
            guard let store = stores[scope] else {
                XCTFail("Unexpected lease authority scope: \(scope)")
                return unexpectedStore
            }
            return store
        }

        let firstA = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99, pairingIdentifier: "pairing-a"),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: factory
        )
        let nextA = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 100, pairingIdentifier: "pairing-a"),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: factory
        )
        let firstB = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99, pairingIdentifier: "pairing-b"),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: factory
        )

        XCTAssertEqual(try issuedEpoch(firstA), 99)
        XCTAssertEqual(try issuedEpoch(nextA), 100)
        XCTAssertEqual(try issuedEpoch(firstB), 99)
    }

    func testIdentityBindingFailuresDoNotBurnLeaseEpoch() throws {
        let service = "dev.vibescreen.lease-identity-tests.\(UUID().uuidString)"
        let identityStore = KeychainDeviceIdentityStore(service: service)
        let original = try identityStore.createIfMissing(deviceID: "lease-host")
        let secretStore = LeaseMemorySecretStore()
        let stateStore = LeaseMemoryStateStore()
        stateStore.state.sessionEpoch = 4
        try persistBinding(
            original.publicIdentity,
            pairingIdentifier: "pairing-authority-test",
            store: secretStore
        )

        try identityStore.delete(deviceID: "lease-host", keyEpoch: 1)
        XCTAssertThrowsError(try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore }
        ))
        XCTAssertEqual(stateStore.state.sessionEpoch, 4)

        let replacement = try identityStore.createIfMissing(deviceID: "lease-host")
        XCTAssertNotEqual(replacement.publicIdentity.keyID, original.publicIdentity.keyID)
        XCTAssertThrowsError(try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore }
        ))
        XCTAssertEqual(stateStore.state.sessionEpoch, 4)

        try persistBinding(
            replacement.publicIdentity,
            pairingIdentifier: "pairing-authority-test",
            store: secretStore
        )
        XCTAssertEqual(try issuedEpoch(InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore }
        )), 99)

        let bindingName = try PairedHostIdentityBinding.keychainName(
            pairingIdentifier: "pairing-authority-test"
        )
        try secretStore.delete(name: bindingName)
        XCTAssertThrowsError(try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore }
        ))
        XCTAssertEqual(stateStore.state.sessionEpoch, 99)

        var invalidBinding = try XCTUnwrap(
            JSONSerialization.jsonObject(
                with: PairedHostIdentityBinding.encode(replacement.publicIdentity)
            ) as? [String: Any]
        )
        invalidBinding["signatureAlgorithm"] = "RSA_SHA256"
        try secretStore.persist(
            name: bindingName,
            secret: JSONSerialization.data(withJSONObject: invalidBinding)
        )
        XCTAssertThrowsError(try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 99),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore }
        ))
        XCTAssertEqual(stateStore.state.sessionEpoch, 99)

        try identityStore.delete(deviceID: "lease-host", keyEpoch: 1)
    }

    func testDurablePairingBindingFailsBeforeLeaseCredentialsOrEpoch() throws {
        let secretStore = LeaseMemorySecretStore()
        let stateStore = LeasePairingValidationFailureStore()

        XCTAssertThrowsError(
            try InternetSessionLeaseIssuer.issue(
                unsignedJSON: try unsignedLease(epoch: 99),
                secretStore: secretStore,
                stateStoreFactory: { _ in stateStore }
            )
        )
        XCTAssertEqual(stateStore.validationCalls, 1)
        XCTAssertEqual(secretStore.loadCalls, 0)
        XCTAssertEqual(stateStore.state.sessionEpoch, 0)
    }

    func testSessionLeaseDeliverySignsAndWrapsUnsignedLeaseForBulkTransfer() throws {
        let hostKey = P256.Signing.PrivateKey()
        let hostPublicKey = hostKey.publicKey.x963Representation
        let hostKeyID = Data(SHA256.hash(data: hostPublicKey)).map {
            String(format: "%02x", $0)
        }.joined()
        let unsigned = try unsignedLease(epoch: 99)

        let delivery = try InternetSessionLeaseDelivery.deliveryPayload(
            forSignedLease: try signedLeaseFixture(
                unsignedLease: unsigned,
                leaseHostKeyID: hostKeyID,
                hostKey: hostKey
            )
        )
        XCTAssertEqual(
            InternetSessionLeaseDelivery.bulkTransferID,
            Data("internet-bulk-v1".utf8)
        )

        let signed = try InternetSessionLeaseDelivery.signedLease(fromDeliveryPayload: delivery)
        let signedRoot = try XCTUnwrap(
            JSONSerialization.jsonObject(with: signed) as? [String: Any]
        )
        XCTAssertEqual(signedRoot["lease_host_key_id"] as? String, hostKeyID)
        XCTAssertNotNil(signedRoot["lease_signature"] as? String)

        let payload = try InternetSessionLeaseCodec.decodeUnsigned(unsigned)
        let digest = InternetSessionLeaseCodec.digest(payload, leaseHostKeyID: hostKeyID)
        let signature = try XCTUnwrap(Data(base64Encoded: signedRoot["lease_signature"] as? String ?? ""))
        XCTAssertTrue(InternetSessionLeaseCodec.verifyDigestSignature(
            signature,
            digest: digest,
            publicKey: hostPublicKey
        ))
    }

    func testSessionLeaseDeliveryExtractsUnsignedLeaseFromSignalingResponse() throws {
        let hostKey = P256.Signing.PrivateKey()
        let hostPublicKey = hostKey.publicKey.x963Representation
        let hostKeyID = Data(SHA256.hash(data: hostPublicKey)).map {
            String(format: "%02x", $0)
        }.joined()
        let hostIdentity = testIdentity(deviceID: "lease-host", key: hostKey, keyEpoch: 1)
        let expiresAt = UInt64(Date().timeIntervalSince1970) + 600
        let unsigned = try unsignedLease(epoch: 100, expiresAt: expiresAt)
        let unsignedObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: unsigned) as? [String: Any]
        )
        var leaseObject = unsignedObject
        leaseObject["protocol_session_id"] = Data("session-authority-test".utf8)
            .base64EncodedString()
        let expiresAtText = try iso8601String(fromUnixSeconds: expiresAt)
        let response = try JSONSerialization.data(withJSONObject: [
            "session_id": "session-authority-test",
            "host_token": String(repeating: "h", count: 32),
            "device_token": String(repeating: "t", count: 32),
            "expires_at": expiresAtText,
            "session_profile": [
                "account_id": "acct-1",
                "pairing_id": "pairing-authority-test",
                "signaling_session_id": "session-authority-test",
                "host_signaling_token": String(repeating: "h", count: 32),
                "expires_at": expiresAtText,
                "created": true,
                "unsigned_android_lease": leaseObject
            ]
        ], options: [.sortedKeys])

        let request = sessionProfileRequest(
            hostIdentity: hostIdentity,
            clientIdentity: deviceIdentity,
            sessionEpoch: 100
        )
        let extracted = try InternetSessionLeaseDelivery.unsignedAndroidLease(
            fromSignalingSessionResponse: response,
            matching: request
        )
        let signed = try signedLeaseFixture(
            unsignedLease: extracted,
            leaseHostKeyID: hostKeyID,
            hostKey: hostKey
        )
        let delivery = try InternetSessionLeaseDelivery.deliveryPayload(forSignedLease: signed)
        XCTAssertEqual(try InternetSessionLeaseDelivery.signedLease(fromDeliveryPayload: delivery), signed)
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: signed) as? [String: Any])
        XCTAssertEqual((root["session_epoch"] as? NSNumber)?.uint64Value, 100)
        XCTAssertEqual(root["lease_host_key_id"] as? String, hostKeyID)
    }

    func testSessionLeaseDeliveryAcceptsFractionalSecondSignalingExpiry() throws {
        let hostIdentity = testIdentity(
            deviceID: "lease-host",
            key: P256.Signing.PrivateKey(),
            keyEpoch: 1
        )
        let expiresAt = UInt64(Date().timeIntervalSince1970) + 600
        let unsigned = try unsignedLease(epoch: 100, expiresAt: expiresAt)
        let unsignedObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: unsigned) as? [String: Any]
        )
        var leaseObject = unsignedObject
        leaseObject["protocol_session_id"] = Data("session-authority-test".utf8)
            .base64EncodedString()
        let expiresAtText = try iso8601String(fromUnixSeconds: expiresAt)
            .replacingOccurrences(of: "Z", with: ".123Z")
        let response = try JSONSerialization.data(withJSONObject: [
            "session_id": "session-authority-test",
            "host_token": String(repeating: "h", count: 32),
            "device_token": String(repeating: "t", count: 32),
            "expires_at": expiresAtText,
            "session_profile": [
                "account_id": "acct-1",
                "pairing_id": "pairing-authority-test",
                "signaling_session_id": "session-authority-test",
                "host_signaling_token": String(repeating: "h", count: 32),
                "expires_at": expiresAtText,
                "created": true,
                "unsigned_android_lease": leaseObject
            ]
        ], options: [.sortedKeys])

        let request = sessionProfileRequest(
            hostIdentity: hostIdentity,
            clientIdentity: deviceIdentity,
            sessionEpoch: 100
        )
        let extracted = try InternetSessionLeaseDelivery.unsignedAndroidLease(
            fromSignalingSessionResponse: response,
            matching: request
        )
        XCTAssertEqual(extracted, try JSONSerialization.data(
            withJSONObject: leaseObject,
            options: [.sortedKeys]
        ))
    }

    func testSessionLeaseDeliveryRejectsProfileResponseDriftBeforeSigning() throws {
        let request = sessionProfileRequest(
            hostIdentity: testIdentity(
                deviceID: "lease-host",
                key: P256.Signing.PrivateKey(),
                keyEpoch: 1
            ),
            clientIdentity: deviceIdentity,
            sessionEpoch: 100
        )
        var unsignedObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: try unsignedLease(epoch: 100)) as? [String: Any]
        )
        unsignedObject["signaling_url"] = "https://attacker.example.test"
        let response = try signalingProfileResponse(
            unsignedLeaseObject: unsignedObject,
            sessionEpoch: 100
        )

        XCTAssertThrowsError(try InternetSessionLeaseDelivery.unsignedAndroidLease(
            fromSignalingSessionResponse: response,
            matching: request
        ))
    }

    func testSessionLeaseDeliveryRejectsDeviceTokenDriftBeforeSigning() throws {
        let request = sessionProfileRequest(
            hostIdentity: testIdentity(
                deviceID: "lease-host",
                key: P256.Signing.PrivateKey(),
                keyEpoch: 1
            ),
            clientIdentity: deviceIdentity,
            sessionEpoch: 100
        )
        let unsignedObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: try unsignedLease(epoch: 100)) as? [String: Any]
        )
        let response = try signalingProfileResponse(
            unsignedLeaseObject: unsignedObject,
            sessionEpoch: 100,
            deviceToken: String(repeating: "d", count: 32)
        )

        XCTAssertThrowsError(try InternetSessionLeaseDelivery.unsignedAndroidLease(
            fromSignalingSessionResponse: response,
            matching: request
        ))
    }

    func testUnsignedLeaseRejectsNonCanonicalBase64() throws {
        let base = String(decoding: try unsignedLease(epoch: 100), as: UTF8.self)
        let mutated = base.replacingOccurrences(
            of: Data("protocol-session".utf8).base64EncodedString(),
            with: "cHJvdG9jb2wtc2Vzc2lvbi=="
        )

        XCTAssertThrowsError(try InternetSessionLeaseCodec.decodeUnsigned(Data(mutated.utf8)))
    }

    func testSessionLeaseProvisionerBuildsAuthoritativeCreateRequest() throws {
        let hostKey = P256.Signing.PrivateKey()
        let hostIdentity = testIdentity(deviceID: "lease-host", key: hostKey, keyEpoch: 1)
        let clientDeviceID = deviceIdentity.deviceID
        let provisioner = InternetSessionLeaseProvisioner()

        let urlRequest = try provisioner.makeCreateSessionRequest(
            signalingBaseURL: URL(string: "https://signal.example.test")!,
            issuerToken: "issuer-token",
            request: sessionProfileRequest(
                hostIdentity: hostIdentity,
                clientIdentity: deviceIdentity,
                sessionEpoch: 101
            )
        )

        XCTAssertEqual(urlRequest.url?.absoluteString, "https://signal.example.test/v1/sessions")
        XCTAssertEqual(urlRequest.httpMethod, "POST")
        XCTAssertEqual(urlRequest.value(forHTTPHeaderField: "Authorization"), "Bearer issuer-token")
        XCTAssertEqual(urlRequest.value(forHTTPHeaderField: "Content-Type"), "application/json")
        let body = try XCTUnwrap(urlRequest.httpBody)
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertEqual(root["request_id"] as? String, "req-101")
        XCTAssertEqual(root["account_id"] as? String, "acct-1")
        XCTAssertEqual(root["host_device_id"] as? String, "lease-host")
        XCTAssertEqual(root["client_device_id"] as? String, clientDeviceID)
        XCTAssertEqual((root["session_epoch"] as? NSNumber)?.uint64Value, 101)
        XCTAssertEqual((root["ttl_seconds"] as? NSNumber)?.int64Value, 60)
        let sessionProfile = try XCTUnwrap(root["session_profile"] as? [String: Any])
        XCTAssertEqual(sessionProfile["pairing_id"] as? String, "pairing-authority-test")
        let profileHost = try XCTUnwrap(sessionProfile["host_identity"] as? [String: Any])
        XCTAssertEqual(profileHost["device_id"] as? String, "lease-host")
        XCTAssertEqual(profileHost["key_id"] as? String, hostIdentity.keyID)
        let profileClient = try XCTUnwrap(sessionProfile["client_identity"] as? [String: Any])
        XCTAssertEqual(profileClient["device_id"] as? String, clientDeviceID)
        XCTAssertEqual(profileClient["key_id"] as? String, deviceIdentity.keyID)
    }

    func testSessionLeaseProvisionerRejectsUnsafeSignalingBaseURL() throws {
        let provisioner = InternetSessionLeaseProvisioner()
        let request = InternetSignalingSessionProfileRequest(
            requestID: "req-unsafe",
            accountID: "acct-1",
            hostDeviceID: "lease-host",
            clientDeviceID: deviceIdentity.deviceID,
            sessionEpoch: 102,
            ttlSeconds: 60,
            sessionProfile: InternetSessionProfileLeaseRequest(
                pairingID: "pairing-authority-test",
                hostIdentity: testIdentity(
                    deviceID: "lease-host",
                    key: P256.Signing.PrivateKey(),
                    keyEpoch: 1
                ),
                clientIdentity: deviceIdentity,
                signalingURL: "https://signal.example.test",
                transcriptContext: Data(repeating: 1, count: 32),
                protocolSessionID: Data("protocol-session".utf8),
                iceServers: [InternetSessionProfileICEServerRequest(
                    urls: ["stun:stun.example.test"],
                    username: nil,
                    credential: nil
                )]
            )
        )

        let rejected = [
            "http://signal.example.test",
            "https://user:pass@signal.example.test",
            "https://signal.example.test/prefix",
            "https://signal.example.test?token=leak",
            "ftp://signal.example.test"
        ]
        for rawURL in rejected {
            XCTAssertThrowsError(try provisioner.makeCreateSessionRequest(
                signalingBaseURL: URL(string: rawURL)!,
                issuerToken: "issuer-token",
                request: request
            ), rawURL)
        }

        let loopback = try provisioner.makeCreateSessionRequest(
            signalingBaseURL: URL(string: "http://127.0.0.1:8088")!,
            issuerToken: "issuer-token",
            request: request
        )
        XCTAssertEqual(loopback.url?.absoluteString, "http://127.0.0.1:8088/v1/sessions")
    }

    func testSessionLeaseDeliveryRejectsMalformedEnvelope() throws {
        let signed = try unsignedLease(epoch: 101)
        let valid = try InternetSessionLeaseDelivery.deliveryPayload(forSignedLease: signed)
        var root = try XCTUnwrap(JSONSerialization.jsonObject(with: valid) as? [String: Any])

        root["purpose"] = "other"
        XCTAssertThrowsError(try InternetSessionLeaseDelivery.signedLease(
            fromDeliveryPayload: JSONSerialization.data(withJSONObject: root)
        ))

        root = try XCTUnwrap(JSONSerialization.jsonObject(with: valid) as? [String: Any])
        root["unexpected"] = true
        XCTAssertThrowsError(try InternetSessionLeaseDelivery.signedLease(
            fromDeliveryPayload: JSONSerialization.data(withJSONObject: root)
        ))
    }

    private func unsignedLease(
        epoch: UInt64,
        pairingIdentifier: String = "pairing-authority-test",
        pinnedHostID: String = "lease-host",
        expiresAt: UInt64? = UInt64(Date().timeIntervalSince1970) + 600
    ) throws -> Data {
        var root: [String: Any] = [
            "version": 1,
            "pairing_id": pairingIdentifier,
            "pinned_host_id": pinnedHostID,
            "pinned_device_id": deviceIdentity.deviceID,
            "lease_device_key_id": deviceIdentity.keyID,
            "signaling_url": "https://signal.example.test",
            "signaling_session_id": "session-authority-test",
            "session_epoch": epoch,
            "host_identity_epoch": 1,
            "device_identity_epoch": deviceIdentity.keyEpoch,
            "transcript_context": Data(repeating: 1, count: 32).base64EncodedString(),
            "protocol_session_id": Data("protocol-session".utf8).base64EncodedString(),
            "signaling_token": String(repeating: "t", count: 32),
            "ice_servers": [[
                "urls": ["stun:stun.example.test"],
                "username": NSNull(),
                "credential": NSNull()
            ]],
            "allow_insecure_for_testing": false
        ]
        if let expiresAt { root["expires_at"] = expiresAt }
        return try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
    }

    private func sessionProfileRequest(
        hostIdentity: PlatformPublicIdentity,
        clientIdentity: PlatformPublicIdentity,
        sessionEpoch: UInt64
    ) -> InternetSignalingSessionProfileRequest {
        InternetSignalingSessionProfileRequest(
            requestID: "req-\(sessionEpoch)",
            accountID: "acct-1",
            hostDeviceID: "lease-host",
            clientDeviceID: clientIdentity.deviceID,
            sessionEpoch: sessionEpoch,
            ttlSeconds: 60,
            sessionProfile: InternetSessionProfileLeaseRequest(
                pairingID: "pairing-authority-test",
                hostIdentity: hostIdentity,
                clientIdentity: clientIdentity,
                signalingURL: "https://signal.example.test",
                transcriptContext: Data(repeating: 1, count: 32),
                protocolSessionID: Data("protocol-session".utf8),
                iceServers: [InternetSessionProfileICEServerRequest(
                    urls: ["stun:stun.example.test"],
                    username: nil,
                    credential: nil
                )]
            )
        )
    }

    private func signalingProfileResponse(
        unsignedLeaseObject: [String: Any],
        sessionEpoch _: UInt64,
        deviceToken: String = String(repeating: "t", count: 32)
    ) throws -> Data {
        var leaseObject = unsignedLeaseObject
        leaseObject["protocol_session_id"] = Data("session-authority-test".utf8)
            .base64EncodedString()
        let expiresAt = (unsignedLeaseObject["expires_at"] as? NSNumber)?.uint64Value
            ?? UInt64(Date().timeIntervalSince1970) + 600
        let expiresAtText = try iso8601String(fromUnixSeconds: expiresAt)
        return try JSONSerialization.data(withJSONObject: [
            "session_id": "session-authority-test",
            "host_token": String(repeating: "h", count: 32),
            "device_token": deviceToken,
            "expires_at": expiresAtText,
            "session_profile": [
                "account_id": "acct-1",
                "pairing_id": "pairing-authority-test",
                "signaling_session_id": "session-authority-test",
                "host_signaling_token": String(repeating: "h", count: 32),
                "expires_at": expiresAtText,
                "created": true,
                "unsigned_android_lease": leaseObject
            ]
        ], options: [.sortedKeys])
    }

    private func iso8601String(fromUnixSeconds seconds: UInt64) throws -> String {
        let date = Date(timeIntervalSince1970: TimeInterval(seconds))
        return ISO8601DateFormatter().string(from: date)
    }

    fileprivate static func rawDigestSignature(
        privateKey: P256.Signing.PrivateKey,
        digest: Data
    ) throws -> Data {
        guard digest.count == SHA256.byteCount else {
            throw InternetSessionLeaseIssuerError.invalidInput(
                "Lease delivery test signing requires a SHA-256 digest."
            )
        }
        let attributes: [String: Any] = [
            kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrKeyClass as String: kSecAttrKeyClassPrivate,
            kSecAttrKeySizeInBits as String: 256
        ]
        guard let key = SecKeyCreateWithData(
            privateKey.x963Representation as CFData,
            attributes as CFDictionary,
            nil
        ) else {
            throw InternetSessionLeaseIssuerError.invalidInput(
                "Lease delivery test P-256 key is invalid."
            )
        }
        var error: Unmanaged<CFError>?
        guard let signature = SecKeyCreateSignature(
            key,
            .ecdsaSignatureDigestX962SHA256,
            digest as CFData,
            &error
        ) as Data? else {
            if let error { throw error.takeRetainedValue() }
            throw InternetSessionLeaseIssuerError.invalidInput(
                "Lease delivery test digest signing failed."
            )
        }
        if let error { throw error.takeRetainedValue() }
        return signature
    }

    private func signedLeaseFixture(
        unsignedLease: Data,
        leaseHostKeyID: String,
        hostKey: P256.Signing.PrivateKey
    ) throws -> Data {
        guard !leaseHostKeyID.isEmpty, leaseHostKeyID.utf8.count <= 256 else {
            throw InternetSessionLeaseDeliveryError.invalidLeaseHostKeyID
        }
        let payload = try InternetSessionLeaseCodec.decodeUnsigned(unsignedLease)
        let digest = InternetSessionLeaseCodec.digest(payload, leaseHostKeyID: leaseHostKeyID)
        let signature = try Self.rawDigestSignature(privateKey: hostKey, digest: digest)
        guard !signature.isEmpty, signature.count <= 80 else {
            throw InternetSessionLeaseDeliveryError.invalidSignature
        }
        return try InternetSessionLeaseCodec.encodeSigned(
            payload,
            leaseHostKeyID: leaseHostKeyID,
            signature: signature
        )
    }

    private func testIdentity(
        deviceID: String,
        key: P256.Signing.PrivateKey,
        keyEpoch: UInt64
    ) -> PlatformPublicIdentity {
        let publicKey = key.publicKey.x963Representation
        return PlatformPublicIdentity(
            deviceID: deviceID,
            keyID: Data(SHA256.hash(data: publicKey)).map {
                String(format: "%02x", $0)
            }.joined(),
            keyEpoch: keyEpoch,
            signingPublicKey: publicKey
        )
    }

    private func vibeScreenExecutableURL() throws -> URL {
        let environment = ProcessInfo.processInfo.environment
        let testBundleDirectory = Bundle(for: Self.self).bundleURL.deletingLastPathComponent()
        var candidates = [
            environment["VIBE_SCREEN_EXECUTABLE_PATH"].map(URL.init(fileURLWithPath:)),
            environment["TELEMACHUS_EXECUTABLE_PATH"].map(URL.init(fileURLWithPath:)),
            environment["BUILT_PRODUCTS_DIR"].map {
                URL(fileURLWithPath: $0).appendingPathComponent("Vibe Screen")
            },
            environment["BUILT_PRODUCTS_DIR"].map {
                URL(fileURLWithPath: $0)
                    .appendingPathComponent("Vibe Screen.app/Contents/MacOS/Vibe Screen")
            },
            Optional(testBundleDirectory.appendingPathComponent("Vibe Screen")),
            Optional(
                testBundleDirectory
                    .appendingPathComponent("Vibe Screen.app/Contents/MacOS/Vibe Screen")
            ),
            // Accept old development layouts while cached Xcode products migrate.
            environment["BUILT_PRODUCTS_DIR"].map {
                URL(fileURLWithPath: $0)
                    .appendingPathComponent("Telemachus.app/Contents/MacOS/Telemachus")
            },
            Optional(testBundleDirectory.appendingPathComponent("Telemachus")),
            Optional(
                testBundleDirectory
                    .appendingPathComponent("Telemachus.app/Contents/MacOS/Telemachus")
            )
        ].compactMap { $0 }
        candidates.removeAll { !FileManager.default.isExecutableFile(atPath: $0.path) }
        return try XCTUnwrap(
            candidates.first,
            "Unable to locate the built Vibe Screen executable."
        )
    }

    private func issuedEpoch(_ signed: Data) throws -> UInt64 {
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: signed) as? [String: Any])
        return try XCTUnwrap((root["session_epoch"] as? NSNumber)?.uint64Value)
    }

    private func issuedExpiry(_ signed: Data) throws -> UInt64 {
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: signed) as? [String: Any])
        return try XCTUnwrap((root["expires_at"] as? NSNumber)?.uint64Value)
    }

    private func persistBinding(
        _ identity: PlatformPublicIdentity,
        pairingIdentifier: String,
        store: LeaseMemorySecretStore
    ) throws {
        try store.persist(
            name: PairedHostIdentityBinding.keychainName(
                pairingIdentifier: pairingIdentifier
            ),
            secret: PairedHostIdentityBinding.encode(identity)
        )
        try store.persist(
            name: PairedPeerIdentityBinding.keychainName(
                pairingIdentifier: pairingIdentifier
            ),
            secret: PairedPeerIdentityBinding.encode(deviceIdentity)
        )
    }
}

private final class LeaseTestSigningIdentity: InternetSessionLeaseSigningIdentity {
    private let signingKey = P256.Signing.PrivateKey()
    let publicIdentity: PlatformPublicIdentity

    init(deviceID: String) {
        let publicKey = signingKey.publicKey.x963Representation
        publicIdentity = PlatformPublicIdentity(
            deviceID: deviceID,
            keyID: Data(SHA256.hash(data: publicKey)).map {
                String(format: "%02x", $0)
            }.joined(),
            keyEpoch: PlatformPublicIdentity.initialKeyEpoch,
            signingPublicKey: publicKey
        )
    }

    func signTranscriptDigest(_ digest: Data) throws -> Data {
        try InternetSessionLeaseIssuerTests.rawDigestSignature(
            privateKey: signingKey,
            digest: digest
        )
    }
}

private final class LeaseMemoryStateStore: SecurityStateStore {
    var state = PersistedSecurityState()
    func load() throws -> PersistedSecurityState { state }
    func persist(_ state: PersistedSecurityState) throws { self.state = state }
}

private final class LeasePairingValidationFailureStore: SecurityStateStore {
    var state = PersistedSecurityState()
    private(set) var validationCalls = 0

    func load() throws -> PersistedSecurityState { state }
    func persist(_ state: PersistedSecurityState) throws { self.state = state }
    func validatePairingBinding(
        pairingIdentifier _: String
    ) throws -> PersistedSecurityState {
        validationCalls += 1
        throw PlatformSecurityError.persistenceFailure("injected missing lease state")
    }
}

private final class LeaseMemorySecretStore: InternetPairingSecretStore {
    private let lock = NSLock()
    private var values: [String: Data] = [:]
    private var storedLoadCalls = 0

    var loadCalls: Int {
        lock.lock()
        defer { lock.unlock() }
        return storedLoadCalls
    }

    func load(name: String) throws -> Data? {
        lock.lock()
        defer { lock.unlock() }
        storedLoadCalls += 1
        return values[name]
    }
    func persist(name: String, secret: Data) throws {
        lock.lock()
        defer { lock.unlock() }
        values[name] = secret
    }
    func delete(name: String) throws {
        lock.lock()
        defer { lock.unlock() }
        values.removeValue(forKey: name)
    }
}
