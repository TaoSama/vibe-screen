import XCTest
@testable import Telemachus

final class RevokedInternetIdentityStoreTests: XCTestCase {
    private final class MemoryPersistence: RevokedInternetIdentityPersistence {
        var data: Data?
        var loadError: Error?
        var persistError: Error?

        func load() throws -> Data? {
            if let loadError { throw loadError }
            return data
        }

        func persist(_ data: Data) throws {
            if let persistError { throw persistError }
            self.data = data
        }
    }

    private struct LegacyRecord: Codable {
        let keyID: String
        let keyEpoch: UInt64
    }

    private func identity(
        deviceID: String,
        keyID: String,
        keyEpoch: UInt64
    ) -> PlatformPublicIdentity {
        PlatformPublicIdentity(
            deviceID: deviceID,
            keyID: keyID,
            keyEpoch: keyEpoch,
            signingPublicKey: Data(repeating: 7, count: 65)
        )
    }

    func testRevokedKeyCannotEscapeByMutatingDeviceID() throws {
        let store = RevokedInternetIdentityStore(
            persistence: MemoryPersistence()
        )
        try store.remember(identity(
            deviceID: "device-a", keyID: "revoked-key", keyEpoch: 4
        ))

        XCTAssertThrowsError(try store.validateReauthorization(identity(
            deviceID: "mutated-device-id", keyID: "revoked-key", keyEpoch: 999
        )))
        XCTAssertTrue(try store.isKeyRevoked("revoked-key"))
    }

    func testAllKeysRevokedForDeviceRemainDeniedAndNewKeyMustExceedFloor() throws {
        let store = RevokedInternetIdentityStore(
            persistence: MemoryPersistence()
        )
        try store.remember(identity(
            deviceID: "device-a", keyID: "key-a", keyEpoch: 4
        ))
        try store.remember(identity(
            deviceID: "device-a", keyID: "key-b", keyEpoch: 8
        ))

        XCTAssertThrowsError(try store.validateReauthorization(identity(
            deviceID: "device-a", keyID: "key-a", keyEpoch: 100
        )))
        XCTAssertThrowsError(try store.validateReauthorization(identity(
            deviceID: "device-a", keyID: "key-c", keyEpoch: 8
        )))
        XCTAssertNoThrow(try store.validateReauthorization(identity(
            deviceID: "device-a", keyID: "key-c", keyEpoch: 9
        )))
        XCTAssertEqual(try store.maximumRevokedEpoch(for: "device-a"), 8)
    }

    func testLowerEpochRevocationAddsKeyWithoutLoweringDeviceFloor() throws {
        let store = RevokedInternetIdentityStore(
            persistence: MemoryPersistence()
        )
        try store.remember(identity(
            deviceID: "device-a", keyID: "key-newer", keyEpoch: 8
        ))
        try store.remember(identity(
            deviceID: "device-a", keyID: "key-older", keyEpoch: 3
        ))

        XCTAssertEqual(try store.maximumRevokedEpoch(for: "device-a"), 8)
        XCTAssertTrue(try store.isKeyRevoked("key-newer"))
        XCTAssertTrue(try store.isKeyRevoked("key-older"))
    }

    func testDeviceEpochFloorsRemainIndependent() throws {
        let store = RevokedInternetIdentityStore(
            persistence: MemoryPersistence()
        )
        try store.remember(identity(
            deviceID: "device-a", keyID: "key-a", keyEpoch: 4
        ))
        try store.remember(identity(
            deviceID: "device-b", keyID: "key-b", keyEpoch: 9
        ))

        XCTAssertEqual(try store.maximumRevokedEpoch(for: "device-a"), 4)
        XCTAssertEqual(try store.maximumRevokedEpoch(for: "device-b"), 9)
    }

    func testV1MapMigratesToGlobalDenySetAndDeviceFloors() throws {
        let persistence = MemoryPersistence()
        persistence.data = try JSONEncoder().encode([
            "device-a": LegacyRecord(keyID: "key-a", keyEpoch: 4),
            "device-b": LegacyRecord(keyID: "key-b", keyEpoch: 7)
        ])
        let store = RevokedInternetIdentityStore(persistence: persistence)

        XCTAssertThrowsError(try store.validateReauthorization(identity(
            deviceID: "mutated", keyID: "key-a", keyEpoch: 100
        )))
        XCTAssertEqual(try store.maximumRevokedEpoch(for: "device-b"), 7)
        let migrated = try JSONDecoder().decode(
            RevokedInternetIdentityState.self,
            from: XCTUnwrap(persistence.data)
        )
        XCTAssertEqual(migrated.schemaVersion, 2)
        XCTAssertEqual(migrated.revokedKeyIDs, ["key-a", "key-b"])
        XCTAssertEqual(
            migrated.maximumRevokedEpochByDeviceID,
            ["device-a": 4, "device-b": 7]
        )
    }

    func testInvalidV1MapFailsClosed() throws {
        let persistence = MemoryPersistence()
        persistence.data = try JSONEncoder().encode([
            "device-a": LegacyRecord(keyID: "key-a", keyEpoch: 0)
        ])
        let store = RevokedInternetIdentityStore(persistence: persistence)

        XCTAssertThrowsError(try store.validateReauthorization(identity(
            deviceID: "device-a", keyID: "new-key", keyEpoch: 1
        )))
    }

    func testV1MigrationPersistenceFailureFailsClosed() throws {
        let persistence = MemoryPersistence()
        persistence.data = try JSONEncoder().encode([
            "device-a": LegacyRecord(keyID: "key-a", keyEpoch: 4)
        ])
        persistence.persistError = PlatformSecurityError.persistenceFailure(
            "injected migration write failure"
        )
        let store = RevokedInternetIdentityStore(persistence: persistence)

        XCTAssertThrowsError(try store.validateReauthorization(identity(
            deviceID: "device-a", keyID: "new-key", keyEpoch: 5
        )))
    }

    func testInvalidV2StateFailsClosedWithoutLegacyFallback() throws {
        let persistence = MemoryPersistence()
        persistence.data = try JSONEncoder().encode(
            RevokedInternetIdentityState(
                revokedKeyIDs: ["key-a"],
                maximumRevokedEpochByDeviceID: ["device-a": 4]
            )
        )
        var object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: XCTUnwrap(persistence.data))
                as? [String: Any]
        )
        object["schemaVersion"] = 1
        persistence.data = try JSONSerialization.data(withJSONObject: object)
        let store = RevokedInternetIdentityStore(persistence: persistence)

        XCTAssertThrowsError(try store.validateReauthorization(identity(
            deviceID: "device-a", keyID: "new-key", keyEpoch: 5
        )))
    }

    func testRememberPersistenceFailureDoesNotCreateInMemoryAuthorization() {
        let persistence = MemoryPersistence()
        persistence.persistError = PlatformSecurityError.persistenceFailure(
            "injected revoked identity write failure"
        )
        let store = RevokedInternetIdentityStore(persistence: persistence)

        XCTAssertThrowsError(try store.remember(identity(
            deviceID: "device-a", keyID: "key-a", keyEpoch: 4
        )))
        XCTAssertNil(persistence.data)
    }

    func testPersistenceFailureDoesNotAuthorizeReauthentication() throws {
        let persistence = MemoryPersistence()
        persistence.loadError = PlatformSecurityError.persistenceFailure(
            "injected read failure"
        )
        let store = RevokedInternetIdentityStore(persistence: persistence)

        XCTAssertThrowsError(try store.validateReauthorization(identity(
            deviceID: "device-a", keyID: "new-key", keyEpoch: 5
        )))
    }

    func testRecordsSurviveStoreRecreation() throws {
        let persistence = MemoryPersistence()
        try RevokedInternetIdentityStore(persistence: persistence).remember(
            identity(deviceID: "device-a", keyID: "key-a", keyEpoch: 6)
        )

        let restored = RevokedInternetIdentityStore(persistence: persistence)
        XCTAssertEqual(try restored.maximumRevokedEpoch(for: "device-a"), 6)
        XCTAssertThrowsError(try restored.validateReauthorization(identity(
            deviceID: "device-a", keyID: "key-a", keyEpoch: 10
        )))
    }
}
