import CryptoKit
import Foundation
import XCTest
@testable import Telemachus

final class InternetSessionLeaseIssuerTests: XCTestCase {
    private static let childProcessTimeout: TimeInterval = 20
    private static let childTerminationGrace: TimeInterval = 1
    private let deviceSigningKey = P256.Signing.PrivateKey()

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
        let executableURL = try telemachusExecutableURL()
        let gateURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("vibe-screen-lease-gate-\(scope)")
        let childCount = 6
        var children: [(process: Process, output: Pipe, error: Pipe)] = []
        defer {
            try? FileManager.default.removeItem(at: gateURL)
            for child in children {
                TestProcessDeadline.terminateAndReap(
                    child.process,
                    terminationGrace: Self.childTerminationGrace
                )
            }
        }
        for _ in 0..<childCount {
            let process = Process()
            let input = Pipe()
            let output = Pipe()
            let error = Pipe()
            process.executableURL = URL(fileURLWithPath: "/bin/sh")
            process.arguments = [
                "-c",
                "while [ ! -e \"$1\" ]; do sleep 0.01; done; exec \"$2\" --issue-phase3-internet-lease",
                "lease-process-test",
                gateURL.path,
                executableURL.path
            ]
            process.standardInput = input
            process.standardOutput = output
            process.standardError = error
            try process.run()
            input.fileHandleForWriting.write(unsigned)
            try input.fileHandleForWriting.close()
            children.append((process, output, error))
        }
        try Data().write(to: gateURL, options: .atomic)

        var epochs: Set<UInt64> = []
        for child in children {
            let exited = TestProcessDeadline.waitForExit(
                child.process,
                timeout: Self.childProcessTimeout,
                terminationGrace: Self.childTerminationGrace
            )
            let output = child.output.fileHandleForReading.readDataToEndOfFile()
            let error = child.error.fileHandleForReading.readDataToEndOfFile()
            guard exited else {
                XCTFail(
                    "Lease worker exceeded the process deadline: "
                        + String(decoding: error, as: UTF8.self)
                )
                continue
            }
            XCTAssertEqual(
                child.process.terminationStatus,
                0,
                String(decoding: error, as: UTF8.self)
            )
            if child.process.terminationStatus == 0 {
                epochs.insert(try issuedEpoch(output))
            }
        }
        XCTAssertEqual(epochs, Set(UInt64(1)...UInt64(childCount)))
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
    func testAuthorityIgnoresCallerEpochAndReservesMonotonicEpochAcrossRestartAndConcurrency() throws {
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
        let untrustedHigh = try unsignedLease(epoch: UInt64(Int64.max) - 1)

        let first = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: untrustedHigh,
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: { scope in
                XCTAssertEqual(scope, "pairing-authority-test")
                return stateStore
            }
        )
        XCTAssertEqual(try issuedEpoch(first), 1)

        let restartedIssuerResult = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 1),
            identityStore: identityStore,
            secretStore: secretStore,
            stateStoreFactory: { _ in stateStore }
        )
        XCTAssertEqual(try issuedEpoch(restartedIssuerResult), 2)

        let lock = NSLock()
        var epochs: [UInt64] = []
        var failures: [Error] = []
        DispatchQueue.concurrentPerform(iterations: 24) { index in
            do {
                let signed = try InternetSessionLeaseIssuer.issue(
                    unsignedJSON: try unsignedLease(epoch: UInt64(index + 1)),
                    identityStore: identityStore,
                    secretStore: secretStore,
                    stateStoreFactory: { _ in stateStore }
                )
                let epoch = try issuedEpoch(signed)
                lock.lock(); epochs.append(epoch); lock.unlock()
            } catch {
                lock.lock(); failures.append(error); lock.unlock()
            }
        }
        XCTAssertTrue(failures.isEmpty)
        XCTAssertEqual(Set(epochs), Set(UInt64(3)...UInt64(26)))
        XCTAssertEqual(stateStore.state.sessionEpoch, 26)
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
        let secondA = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 1, pairingIdentifier: "pairing-a"),
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

        XCTAssertEqual(try issuedEpoch(firstA), 1)
        XCTAssertEqual(try issuedEpoch(secondA), 2)
        XCTAssertEqual(try issuedEpoch(firstB), 1)
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
        )), 5)

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
        XCTAssertEqual(stateStore.state.sessionEpoch, 5)

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
        XCTAssertEqual(stateStore.state.sessionEpoch, 5)

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

    private func unsignedLease(
        epoch: UInt64,
        pairingIdentifier: String = "pairing-authority-test",
        pinnedHostID: String = "lease-host"
    ) throws -> Data {
        let root: [String: Any] = [
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
        return try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
    }

    private func telemachusExecutableURL() throws -> URL {
        let environment = ProcessInfo.processInfo.environment
        let testBundleDirectory = Bundle(for: Self.self).bundleURL.deletingLastPathComponent()
        var candidates = [
            environment["TELEMACHUS_EXECUTABLE_PATH"].map(URL.init(fileURLWithPath:)),
            environment["BUILT_PRODUCTS_DIR"].map {
                URL(fileURLWithPath: $0).appendingPathComponent("Telemachus")
            },
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
            "Unable to locate the built Telemachus executable."
        )
    }

    private func issuedEpoch(_ signed: Data) throws -> UInt64 {
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: signed) as? [String: Any])
        return try XCTUnwrap((root["session_epoch"] as? NSNumber)?.uint64Value)
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
