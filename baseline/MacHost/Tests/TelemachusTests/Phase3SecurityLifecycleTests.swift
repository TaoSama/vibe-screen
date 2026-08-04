import Foundation
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

private final class MemorySecurityStateStore: SecurityStateStore {
    var state = PersistedSecurityState()
    var failPersist = false
    func load() throws -> PersistedSecurityState { state }
    func persist(_ state: PersistedSecurityState) throws {
        if failPersist { throw PlatformSecurityError.persistenceFailure("injected") }
        self.state = state
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
