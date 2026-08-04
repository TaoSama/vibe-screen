import CryptoKit
import Foundation
import Security
import XCTest
@testable import Telemachus

final class Phase3SecurityLifecycleTests: XCTestCase {
    func testSessionEpochIsPersistedBeforeItIsReturned() throws {
        let store = MemorySecurityStateStore()
        XCTAssertEqual(try SecurityLifecycle(store: store).beginSession(), 1)

        let afterRestart = SecurityLifecycle(store: store)
        XCTAssertEqual(try afterRestart.beginSession(), 2)
        XCTAssertEqual(store.state.sessionEpoch, 2)
    }

    func testAuthorityEpochMustFitAndroidSignedLong() throws {
        let store = MemorySecurityStateStore()
        XCTAssertThrowsError(
            try SecurityLifecycle(store: store).reserveSessionEpoch(UInt64(Int64.max) + 1)
        )
        XCTAssertEqual(store.state.sessionEpoch, 0)
        XCTAssertEqual(
            try SecurityLifecycle(store: store).reserveSessionEpoch(UInt64(Int64.max)),
            UInt64(Int64.max)
        )
    }

    func testLegacyMigrationCopiesOnlyCrashSafetyWatermarks() throws {
        let legacy = PersistedSecurityState(
            sessionEpoch: 9,
            revocationSequence: 4,
            revoked: false,
            nonceHighWatermarks: ["1:1:1": 7],
            usedRotationNonceHashes: [String(repeating: "a", count: 64)]
        )
        let migrated = try KeychainSecurityStateStore.migratedLegacyState(legacy)

        XCTAssertEqual(migrated.sessionEpoch, 9)
        XCTAssertEqual(migrated.nonceHighWatermarks, ["1:1:1": 7])
        XCTAssertEqual(migrated.revocationSequence, 0)
        XCTAssertFalse(migrated.revoked)
        XCTAssertNil(migrated.peerRevocation)
        XCTAssertTrue(migrated.usedRotationNonceHashes.isEmpty)
    }

    func testLegacyRevocationRequiresExplicitMigration() {
        let legacy = PersistedSecurityState(revocationSequence: 1, revoked: true)
        XCTAssertThrowsError(try KeychainSecurityStateStore.migratedLegacyState(legacy))
    }

    func testAgreedSessionEpochIsPersistedAndRejectsRollbackOrReuse() throws {
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)

        XCTAssertEqual(try lifecycle.reserveSessionEpoch(42), 42)
        XCTAssertEqual(store.state.sessionEpoch, 42)
        XCTAssertThrowsError(try SecurityLifecycle(store: store).reserveSessionEpoch(42))
        XCTAssertThrowsError(try SecurityLifecycle(store: store).reserveSessionEpoch(41))
        XCTAssertEqual(try SecurityLifecycle(store: store).advanceSessionEpoch(), 43)
    }

    func testNonceReservationRejectsAStaleSessionEpoch() throws {
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)
        try lifecycle.reserveSessionEpoch(7)

        XCTAssertNoThrow(
            try lifecycle.reserveNonce(sessionEpoch: 7, channel: 1, senderRole: 1, keyEpoch: 1)
        )
        try lifecycle.reserveSessionEpoch(9)
        XCTAssertThrowsError(
            try lifecycle.reserveNonce(sessionEpoch: 7, channel: 1, senderRole: 1, keyEpoch: 1)
        )
    }

    func testNonceSequenceCannotRepeatAcrossRestart() throws {
        let store = MemorySecurityStateStore()
        let first = try SecurityLifecycle(store: store).reserveNonce(channel: 1, senderRole: 1, keyEpoch: 4)
        let second = try SecurityLifecycle(store: store).reserveNonce(channel: 1, senderRole: 1, keyEpoch: 4)

        XCTAssertEqual(first.hex, "000000010000000000000001")
        XCTAssertEqual(second.hex, "000000010000000000000002")
    }

    func testRevocationFailsClosedAfterRestart() throws {
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)
        try lifecycle.applyRevocation(sequence: 8)

        XCTAssertThrowsError(try SecurityLifecycle(store: store).beginSession()) { error in
            XCTAssertEqual(error as? PlatformSecurityError, .revoked)
        }
        XCTAssertThrowsError(try lifecycle.applyRevocation(sequence: 8))
    }

    func testSignedPeerRevocationPersistsTargetedTombstone() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let authority = authorityKey.identity
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 3).identity
        let tombstone = try signedTombstone(
            authorityKey: authorityKey,
            authority: authority,
            peer: peer,
            sequence: 11
        )
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)

        try lifecycle.applyPeerRevocation(
            tombstone,
            expectedAuthority: authority,
            expectedPeer: peer
        )

        XCTAssertEqual(store.state.peerRevocation, tombstone)
        XCTAssertEqual(store.state.revocationSequence, 11)
        XCTAssertThrowsError(try SecurityLifecycle(store: store).advanceSessionEpoch()) { error in
            XCTAssertEqual(error as? PlatformSecurityError, .revoked)
        }
    }

    func testPeerRevocationRejectsTamperAndSequenceReuse() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let authority = authorityKey.identity
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 1).identity
        let valid = try signedTombstone(
            authorityKey: authorityKey,
            authority: authority,
            peer: peer,
            sequence: 4
        )
        let tampered = PairedDeviceRevocationTombstone(
            peerIdentity: valid.peerIdentity,
            sequence: valid.sequence,
            revokedAtUnixSeconds: valid.revokedAtUnixSeconds,
            nonce: valid.nonce,
            reasonCode: "tampered",
            authority: valid.authority,
            authoritySignature: valid.authoritySignature
        )
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)

        XCTAssertThrowsError(
            try lifecycle.applyPeerRevocation(
                tampered,
                expectedAuthority: authority,
                expectedPeer: peer
            )
        )
        XCTAssertNil(store.state.peerRevocation)
        try lifecycle.applyPeerRevocation(valid, expectedAuthority: authority, expectedPeer: peer)
        XCTAssertNoThrow(
            try lifecycle.applyPeerRevocation(valid, expectedAuthority: authority, expectedPeer: peer)
        )
        let conflicting = try signedTombstone(
            authorityKey: authorityKey,
            authority: authority,
            peer: peer,
            sequence: valid.sequence
        )
        XCTAssertThrowsError(
            try lifecycle.applyPeerRevocation(conflicting, expectedAuthority: authority, expectedPeer: peer)
        )
    }

    func testPeerRevocationDeletesOnlyPairedSecretsAfterTombstoneCommit() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let authority = authorityKey.identity
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 1).identity
        let tombstone = try signedTombstone(
            authorityKey: authorityKey,
            authority: authority,
            peer: peer,
            sequence: 1
        )
        let stateStore = MemorySecurityStateStore()
        let secretStore = MemoryPairedDeviceSecretStore()
        let security = PlatformSessionSecurity(
            deviceID: "mac-host",
            peerID: PairedDeviceSecurityScope.identifier(peer),
            stateStore: stateStore
        )
        let names = try PairedDeviceSecretNames(
            sharedSecret: "tablet.shared",
            bootstrapSecret: "tablet.bootstrap"
        )

        try security.revokePeer(
            tombstone,
            expectedAuthority: authority,
            expectedPeer: peer,
            secretNames: names,
            secretStore: secretStore
        )

        XCTAssertEqual(secretStore.deletedNames, ["tablet.shared", "tablet.bootstrap"])
        XCTAssertEqual(stateStore.state.peerRevocation, tombstone)
        XCTAssertNil(stateStore.state.revocationSecretCleanup)
    }

    func testPeerRevocationRemainsFailClosedWhenSecretDeletionMustRetry() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 1).identity
        let tombstone = try signedTombstone(
            authorityKey: authorityKey,
            authority: authorityKey.identity,
            peer: peer,
            sequence: 2
        )
        let stateStore = MemorySecurityStateStore()
        let secretStore = MemoryPairedDeviceSecretStore(failingName: "tablet.bootstrap")
        let security = PlatformSessionSecurity(
            deviceID: "mac-host",
            peerID: PairedDeviceSecurityScope.identifier(peer),
            stateStore: stateStore
        )
        let names = try PairedDeviceSecretNames(
            sharedSecret: "tablet.shared",
            bootstrapSecret: "tablet.bootstrap"
        )

        XCTAssertThrowsError(
            try security.revokePeer(
                tombstone,
                expectedAuthority: authorityKey.identity,
                expectedPeer: peer,
                secretNames: names,
                secretStore: secretStore
            )
        )
        XCTAssertEqual(stateStore.state.peerRevocation, tombstone)
        XCTAssertEqual(
            stateStore.state.revocationSecretCleanup?.remainingSecretNames,
            ["tablet.bootstrap"]
        )
        XCTAssertThrowsError(try security.advanceSessionEpoch()) { error in
            XCTAssertEqual(error as? PlatformSecurityError, .revoked)
        }

        secretStore.failingName = nil
        XCTAssertNoThrow(
            try security.revokePeer(
                tombstone,
                expectedAuthority: authorityKey.identity,
                expectedPeer: peer,
                secretNames: names,
                secretStore: secretStore
            )
        )
        XCTAssertEqual(secretStore.deletedNames.last, "tablet.bootstrap")
        XCTAssertNil(stateStore.state.revocationSecretCleanup)
    }

    func testPeerRevocationCleanupAggregatesFailuresAndResumesAfterRestart() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 1).identity
        let tombstone = try signedTombstone(
            authorityKey: authorityKey,
            authority: authorityKey.identity,
            peer: peer,
            sequence: 3
        )
        let stateStore = MemorySecurityStateStore()
        let secretStore = MemoryPairedDeviceSecretStore(
            failingNames: ["tablet.shared"]
        )
        let peerID = PairedDeviceSecurityScope.identifier(peer)
        let names = try PairedDeviceSecretNames(
            sharedSecret: "tablet.shared",
            bootstrapSecret: "tablet.bootstrap"
        )

        XCTAssertThrowsError(
            try PlatformSessionSecurity(
                deviceID: "mac-host",
                peerID: peerID,
                stateStore: stateStore
            ).revokePeer(
                tombstone,
                expectedAuthority: authorityKey.identity,
                expectedPeer: peer,
                secretNames: names,
                secretStore: secretStore
            )
        )
        XCTAssertEqual(
            secretStore.attemptedNames,
            ["tablet.shared", "tablet.bootstrap"],
            "A shared-secret failure must not skip bootstrap-secret cleanup."
        )
        XCTAssertEqual(secretStore.deletedNames, ["tablet.bootstrap"])
        XCTAssertEqual(
            stateStore.state.revocationSecretCleanup?.remainingSecretNames,
            ["tablet.shared"]
        )

        let afterRestart = PlatformSessionSecurity(
            deviceID: "mac-host",
            peerID: peerID,
            stateStore: stateStore
        )
        XCTAssertTrue(try afterRestart.hasPendingRevocationSecretCleanup())
        secretStore.failingNames = []
        try afterRestart.retryRevocationSecretCleanup(secretStore: secretStore)

        XCTAssertFalse(try afterRestart.hasPendingRevocationSecretCleanup())
        XCTAssertNil(stateStore.state.revocationSecretCleanup)
        XCTAssertEqual(secretStore.deletedNames.last, "tablet.shared")
    }

    func testCleanupProgressPersistenceFailureKeepsMarkerForRestart() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 1).identity
        let tombstone = try signedTombstone(
            authorityKey: authorityKey,
            authority: authorityKey.identity,
            peer: peer,
            sequence: 4
        )
        let stateStore = MemorySecurityStateStore()
        // Call 1 atomically commits tombstone + marker. Call 2 attempts to
        // remove the already-deleted shared secret from that marker.
        stateStore.failPersistCalls = [2]
        let secretStore = MemoryPairedDeviceSecretStore()
        let peerID = PairedDeviceSecurityScope.identifier(peer)

        XCTAssertThrowsError(
            try PlatformSessionSecurity(
                deviceID: "mac-host",
                peerID: peerID,
                stateStore: stateStore
            ).revokePeer(
                tombstone,
                expectedAuthority: authorityKey.identity,
                expectedPeer: peer,
                secretNames: try PairedDeviceSecretNames(
                    sharedSecret: "tablet.shared",
                    bootstrapSecret: "tablet.bootstrap"
                ),
                secretStore: secretStore
            )
        )
        XCTAssertEqual(secretStore.deletedNames, ["tablet.shared", "tablet.bootstrap"])
        XCTAssertEqual(
            stateStore.state.revocationSecretCleanup?.remainingSecretNames,
            ["tablet.shared"]
        )

        let afterRestart = PlatformSessionSecurity(
            deviceID: "mac-host",
            peerID: peerID,
            stateStore: stateStore
        )
        try afterRestart.retryRevocationSecretCleanup(secretStore: secretStore)
        XCTAssertNil(stateStore.state.revocationSecretCleanup)
        XCTAssertEqual(secretStore.deletedNames.last, "tablet.shared")
    }

    func testPeerScopedKeychainAccountsAreDistinctAndDoNotExposePeerID() {
        let first = KeychainSecurityStateStore.accountName(peerID: "tablet-a")
        let second = KeychainSecurityStateStore.accountName(peerID: "tablet-b")

        XCTAssertNotEqual(first, second)
        XCTAssertTrue(first.hasPrefix("durable-state-v2.peer."))
        XCTAssertFalse(first.contains("tablet-a"))
        XCTAssertNotEqual(first, "durable-state-v1")
    }

    func testRevocationScopeDistinguishesNewSigningIdentityForSameDeviceID() {
        let oldIdentity = PlatformPublicIdentity(
            deviceID: "tablet",
            keyID: String(repeating: "a", count: 64),
            keyEpoch: 1,
            signingPublicKey: Data([UInt8(0x04)] + Array(repeating: UInt8(1), count: 64))
        )
        let newIdentity = PlatformPublicIdentity(
            deviceID: "tablet",
            keyID: String(repeating: "b", count: 64),
            keyEpoch: 2,
            signingPublicKey: Data([UInt8(0x04)] + Array(repeating: UInt8(2), count: 64))
        )

        XCTAssertNotEqual(
            PairedDeviceSecurityScope.identifier(oldIdentity),
            PairedDeviceSecurityScope.identifier(newIdentity)
        )
        XCTAssertNotEqual(
            KeychainSecurityStateStore.accountName(
                peerID: PairedDeviceSecurityScope.identifier(oldIdentity)
            ),
            KeychainSecurityStateStore.accountName(
                peerID: PairedDeviceSecurityScope.identifier(newIdentity)
            )
        )
    }

    func testPersistenceFailureNeverReleasesReservedValue() {
        let store = MemorySecurityStateStore()
        store.failPersist = true

        XCTAssertThrowsError(try SecurityLifecycle(store: store).beginSession())
        XCTAssertEqual(store.state.sessionEpoch, 0)
        XCTAssertThrowsError(
            try SecurityLifecycle(store: store).reserveNonce(channel: 1, senderRole: 1, keyEpoch: 1)
        )
        XCTAssertTrue(store.state.nonceHighWatermarks.isEmpty)
        XCTAssertThrowsError(try SecurityLifecycle(store: store).consumeRotationNonceHash(Data(repeating: 1, count: 32)))
        XCTAssertTrue(store.state.usedRotationNonceHashes.isEmpty)
    }

    func testRotationNonceTombstoneMatchesGoAndSurvivesRestart() throws {
        let identity = PlatformPublicIdentity(
            deviceID: "host",
            keyID: String(repeating: "a", count: 64),
            keyEpoch: 1,
            signingPublicKey: Data([UInt8(0x04)] + (0..<64).map(UInt8.init))
        )
        let hash = try identity.rotationNonceHash(nonce: Data((0..<16).map(UInt8.init)))
        XCTAssertEqual(hash.hex, "d5f91aab0a4c23c4c710b25146f2350906ea19fac62c79dda0f61fda6f4308c9")

        let store = MemorySecurityStateStore()
        try SecurityLifecycle(store: store).consumeRotationNonceHash(hash)
        XCTAssertThrowsError(try SecurityLifecycle(store: store).consumeRotationNonceHash(hash))
        XCTAssertEqual(store.state.usedRotationNonceHashes, [hash.hex])
    }

    func testInitialDerivationMatchesCrossPlatformFixedVector() throws {
        let keys = try TrafficKeyDerivation.initial(
            sharedSecret: Data((1...32).map(UInt8.init)),
            bootstrapSecret: Data((32...63).map(UInt8.init)),
            context: Data(hex: "d6f7dfe489e792765bcabd79578ec8d1eb95891a459a8414dfcf668a592dd670")
        )

        XCTAssertEqual(keys.keyID, "d249fc90df874566874890c85690ec42cdb979fa1cf7601ce112f7f261b88eda")
        XCTAssertEqual(
            (keys.hostControl + keys.deviceControl + keys.hostMedia + keys.deviceMedia).hex,
            "2813943a29749dde00d152db6822da75c742819cc0ada7d0f71c597123531c70" +
                "88f8b6f39161e266db1b899871e7505a3675f9a7c5c88c213b91042ebd3a1244" +
                "cf62a7f3926e10308e0402d5e51397afc1c6d666dd2dc6a856bf2ebd0106307f3" +
                "f014c1e536fdd26670c84a0737526b2fc6052ca0b08be2e5d5197fc126e4c46"
        )
    }

    func testRotationRequiresNextEpochAndSeparatesKeys() throws {
        let current = try TrafficKeyDerivation.initial(
            sharedSecret: Data((1...32).map(UInt8.init)),
            bootstrapSecret: Data((32...63).map(UInt8.init)),
            context: Data(repeating: 7, count: 32)
        )
        let rotated = try TrafficKeyDerivation.rotate(
            current: current,
            nextEpoch: 2,
            updateNonce: Data((64...79).map(UInt8.init))
        )

        XCTAssertEqual(rotated.keyEpoch, 2)
        XCTAssertNotEqual(rotated.keyID, current.keyID)
        XCTAssertEqual(Set([rotated.hostControl, rotated.deviceControl, rotated.hostMedia, rotated.deviceMedia]).count, 4)
        XCTAssertThrowsError(try TrafficKeyDerivation.rotate(current: current, nextEpoch: 3, updateNonce: Data((64...79).map(UInt8.init))))
    }

    func testTrafficPacketAESGCMAuthenticatesHeader() throws {
        let key = Data(repeating: 0, count: 32)
        let nonce = Data(repeating: 0, count: 12)
        let header = Data("header".utf8)
        let knownCiphertext = try TrafficPacketCryptography.seal(
            plaintext: Data(), key: key, nonce: nonce, authenticatedHeader: Data()
        )
        XCTAssertEqual(knownCiphertext.hex, "530f8afbc74536b9a963b4f1c4cb738b")
        let ciphertext = try TrafficPacketCryptography.seal(
            plaintext: Data(), key: key, nonce: nonce, authenticatedHeader: header
        )
        XCTAssertEqual(
            try TrafficPacketCryptography.open(
                ciphertextAndTag: ciphertext, key: key, nonce: nonce, authenticatedHeader: header
            ),
            Data()
        )
        XCTAssertThrowsError(
            try TrafficPacketCryptography.open(
                ciphertextAndTag: ciphertext, key: key, nonce: nonce, authenticatedHeader: Data("tampered".utf8)
            )
        )
    }
}

private func signedTombstone(
    authorityKey: TestSigningKey,
    authority: PlatformPublicIdentity,
    peer: PlatformPublicIdentity,
    sequence: UInt64
) throws -> PairedDeviceRevocationTombstone {
    let unsigned = PairedDeviceRevocationTombstone(
        peerIdentity: peer,
        sequence: sequence,
        revokedAtUnixSeconds: 1_800_000_000,
        nonce: Data((0..<16).map(UInt8.init)),
        reasonCode: "user_requested",
        authority: authority,
        authoritySignature: Data()
    )
    return PairedDeviceRevocationTombstone(
        peerIdentity: peer,
        sequence: sequence,
        revokedAtUnixSeconds: unsigned.revokedAtUnixSeconds,
        nonce: unsigned.nonce,
        reasonCode: unsigned.reasonCode,
        authority: authority,
        authoritySignature: try authorityKey.sign(unsigned.signingDigest())
    )
}

private final class TestSigningKey {
    let identity: PlatformPublicIdentity
    private let privateKey: SecKey

    init(deviceID: String, keyEpoch: UInt64) throws {
        var creationError: Unmanaged<CFError>?
        guard let privateKey = SecKeyCreateRandomKey([
            kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrKeySizeInBits as String: 256
        ] as CFDictionary, &creationError),
        let publicKey = SecKeyCopyPublicKey(privateKey) else {
            throw creationError?.takeRetainedValue()
                ?? PlatformSecurityError.persistenceFailure("Unable to create test signing key.")
        }
        var exportError: Unmanaged<CFError>?
        guard let encoded = SecKeyCopyExternalRepresentation(publicKey, &exportError) as Data? else {
            throw exportError?.takeRetainedValue()
                ?? PlatformSecurityError.persistenceFailure("Unable to export test signing key.")
        }
        self.privateKey = privateKey
        self.identity = PlatformPublicIdentity(
            deviceID: deviceID,
            keyID: SHA256.hash(data: encoded).map { String(format: "%02x", $0) }.joined(),
            keyEpoch: keyEpoch,
            signingPublicKey: encoded
        )
    }

    func sign(_ digest: Data) throws -> Data {
        var signingError: Unmanaged<CFError>?
        guard let signature = SecKeyCreateSignature(
            privateKey,
            .ecdsaSignatureDigestX962SHA256,
            digest as CFData,
            &signingError
        ) as Data? else {
            throw signingError?.takeRetainedValue()
                ?? PlatformSecurityError.persistenceFailure("Unable to sign test revocation.")
        }
        return signature
    }
}

private final class MemorySecurityStateStore: SecurityStateStore {
    var state = PersistedSecurityState()
    var failPersist = false
    var failPersistCalls: Set<Int> = []
    private var persistCallCount = 0
    func load() throws -> PersistedSecurityState { state }
    func persist(_ state: PersistedSecurityState) throws {
        persistCallCount += 1
        if failPersist || failPersistCalls.contains(persistCallCount) {
            throw PlatformSecurityError.persistenceFailure("injected")
        }
        self.state = state
    }
}

private final class MemoryPairedDeviceSecretStore: PairedDeviceSecretStore {
    private(set) var deletedNames: [String] = []
    private(set) var attemptedNames: [String] = []
    var failingNames: Set<String>

    var failingName: String? {
        get { failingNames.first }
        set { failingNames = newValue.map { Set([$0]) } ?? [] }
    }

    init(failingName: String? = nil, failingNames: Set<String> = []) {
        self.failingNames = failingName.map { Set([$0]) } ?? failingNames
    }

    func delete(name: String) throws {
        attemptedNames.append(name)
        if failingNames.contains(name) {
            throw PlatformSecurityError.persistenceFailure("injected secret deletion failure")
        }
        deletedNames.append(name)
    }
}

private extension Data {
    init(hex: String) {
        self.init(stride(from: 0, to: hex.count, by: 2).map { index in
            let start = hex.index(hex.startIndex, offsetBy: index)
            let end = hex.index(start, offsetBy: 2)
            return UInt8(hex[start..<end], radix: 16)!
        })
    }

    var hex: String { map { String(format: "%02x", $0) }.joined() }
}
