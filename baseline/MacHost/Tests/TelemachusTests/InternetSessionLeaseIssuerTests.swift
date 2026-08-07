import CryptoKit
import Darwin
import Foundation
import XCTest
@testable import Telemachus

final class InternetSessionLeaseIssuerTests: XCTestCase {
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
        let identityService = "dev.vibescreen.lease-process.identity.\(UUID().uuidString)"
        let secretService = "dev.vibescreen.lease-process.secret.\(UUID().uuidString)"
        let stateService = "dev.vibescreen.lease-process.state.\(UUID().uuidString)"
        let pairingIdentifier = "pairing-process-test"
        let identityStore = KeychainDeviceIdentityStore(service: identityService)
        let hostIdentity = try identityStore.createIfMissing(deviceID: "lease-host")
        let secretStore = KeychainSecretStore(service: secretService)
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
        let unsigned = try unsignedLease(epoch: 99, pairingIdentifier: pairingIdentifier)
        let childCount = 6
        var readers: [Int32] = []
        var children: [pid_t] = []

        for _ in 0..<childCount {
            var descriptors: [Int32] = [0, 0]
            XCTAssertEqual(pipe(&descriptors), 0)
            let child = fork()
            XCTAssertGreaterThanOrEqual(child, 0)
            if child == 0 {
                close(descriptors[0])
                do {
                    let signed = try InternetSessionLeaseIssuer.issue(
                        unsignedJSON: unsigned,
                        identityStore: KeychainDeviceIdentityStore(
                            service: identityService
                        ),
                        secretStore: KeychainSecretStore(service: secretService),
                        stateStoreFactory: { _ in
                            KeychainSecurityStateStore(
                                service: stateService,
                                account: "authority"
                            )
                        }
                    )
                    var epoch = try self.issuedEpoch(signed).bigEndian
                    _ = withUnsafeBytes(of: &epoch) {
                        write(descriptors[1], $0.baseAddress, $0.count)
                    }
                    close(descriptors[1])
                    _exit(0)
                } catch {
                    close(descriptors[1])
                    _exit(1)
                }
            }
            close(descriptors[1])
            readers.append(descriptors[0])
            children.append(child)
        }

        var epochs: Set<UInt64> = []
        for reader in readers {
            var bytes = [UInt8](repeating: 0, count: 8)
            let count = bytes.withUnsafeMutableBytes {
                read(reader, $0.baseAddress, $0.count)
            }
            close(reader)
            XCTAssertEqual(count, 8)
            if count == 8 {
                epochs.insert(bytes.reduce(UInt64(0)) { ($0 << 8) | UInt64($1) })
            }
        }
        for child in children {
            var status: Int32 = 0
            XCTAssertEqual(waitpid(child, &status, 0), child)
            XCTAssertEqual(status, 0)
        }
        XCTAssertEqual(epochs, Set(UInt64(1)...UInt64(childCount)))
        try identityStore.delete(deviceID: "lease-host", keyEpoch: 1)
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
        pairingIdentifier: String = "pairing-authority-test"
    ) throws -> Data {
        let root: [String: Any] = [
            "version": 1,
            "pairing_id": pairingIdentifier,
            "pinned_host_id": "lease-host",
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
    private var values: [String: Data] = [:]
    private(set) var loadCalls = 0

    func load(name: String) throws -> Data? {
        loadCalls += 1
        return values[name]
    }
    func persist(name: String, secret: Data) throws { values[name] = secret }
    func delete(name: String) throws { values.removeValue(forKey: name) }
}
