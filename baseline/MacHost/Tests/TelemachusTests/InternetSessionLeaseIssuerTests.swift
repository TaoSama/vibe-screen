import Foundation
import XCTest
@testable import Telemachus

final class InternetSessionLeaseIssuerTests: XCTestCase {
    func testAuthorityIgnoresCallerEpochAndReservesMonotonicEpochAcrossRestartAndConcurrency() throws {
        let service = "dev.vibescreen.lease-tests.\(UUID().uuidString)"
        let identityStore = KeychainDeviceIdentityStore(service: service)
        _ = try identityStore.loadOrCreate(deviceID: "lease-host")
        addTeardownBlock {
            try identityStore.delete(deviceID: "lease-host", keyEpoch: 1)
        }
        let stateStore = LeaseMemoryStateStore()
        let untrustedHigh = try unsignedLease(epoch: UInt64(Int64.max) - 1)

        let first = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: untrustedHigh,
            identityStore: identityStore,
            stateStoreFactory: { scope in
                XCTAssertEqual(scope, "pairing-authority-test")
                return stateStore
            }
        )
        XCTAssertEqual(try issuedEpoch(first), 1)

        let restartedIssuerResult = try InternetSessionLeaseIssuer.issue(
            unsignedJSON: try unsignedLease(epoch: 1),
            identityStore: identityStore,
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

    private func unsignedLease(epoch: UInt64) throws -> Data {
        let root: [String: Any] = [
            "version": 1,
            "pairing_id": "pairing-authority-test",
            "pinned_host_id": "lease-host",
            "signaling_url": "https://signal.example.test",
            "signaling_session_id": "session-authority-test",
            "session_epoch": epoch,
            "identity_epoch": 1,
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
}

private final class LeaseMemoryStateStore: SecurityStateStore {
    var state = PersistedSecurityState()
    func load() throws -> PersistedSecurityState { state }
    func persist(_ state: PersistedSecurityState) throws { self.state = state }
}
