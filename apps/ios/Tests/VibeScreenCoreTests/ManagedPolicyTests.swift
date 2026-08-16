import XCTest
@testable import VibeScreenCore
import VibeScreenProtocol

final class ManagedPolicyTests: XCTestCase {
    func testManagedConfigurationCanDenyHostActionsWithoutDenyingCustomGestures() throws {
        let policy = try ManagedPolicy(managedConfiguration: configuration(
            customGesturesAllowed: true,
            hostActionsAllowed: false
        ))

        XCTAssertTrue(policy.customGesturesAllowed)
        XCTAssertFalse(policy.hostActionsAllowed)
        XCTAssertTrue(policy.protocolStatus.customGesturesAllowed)
        XCTAssertFalse(policy.protocolStatus.hostActionsAllowed)
    }

    func testManagedConfigurationCanDenyCustomGesturesWithoutDenyingHostActions() throws {
        let policy = try ManagedPolicy(managedConfiguration: configuration(
            customGesturesAllowed: false,
            hostActionsAllowed: true
        ))

        XCTAssertFalse(policy.customGesturesAllowed)
        XCTAssertTrue(policy.hostActionsAllowed)
        XCTAssertFalse(policy.protocolStatus.customGesturesAllowed)
        XCTAssertTrue(policy.protocolStatus.hostActionsAllowed)
    }

    func testRemoteStatusAppliesIndependentDenyWins() {
        var hostActionsDenied = permissiveRemoteStatus()
        hostActionsDenied.hostActionsAllowed = false
        let hostActionsPolicy = ManagedPolicy.unmanaged.applying(
            remote: ManagedPolicy(remoteStatus: hostActionsDenied)
        )
        XCTAssertTrue(hostActionsPolicy.customGesturesAllowed)
        XCTAssertFalse(hostActionsPolicy.hostActionsAllowed)

        var customGesturesDenied = permissiveRemoteStatus()
        customGesturesDenied.customGesturesAllowed = false
        let customGesturesPolicy = ManagedPolicy.unmanaged.applying(
            remote: ManagedPolicy(remoteStatus: customGesturesDenied)
        )
        XCTAssertFalse(customGesturesPolicy.customGesturesAllowed)
        XCTAssertTrue(customGesturesPolicy.hostActionsAllowed)
    }

    private func configuration(
        customGesturesAllowed: Bool,
        hostActionsAllowed: Bool
    ) -> [String: Any] {
        [
            "ClipboardAllowed": true,
            "FileTransferAllowed": true,
            "AudioAllowed": true,
            "WakeAllowed": true,
            "CustomGesturesAllowed": customGesturesAllowed,
            "HostActionsAllowed": hostActionsAllowed,
            "MaximumFileBytes": 1_024,
            "AllowedHosts": [String](),
        ]
    }

    private func permissiveRemoteStatus() -> VSManagedPolicyStatus {
        var status = ManagedPolicy.unmanaged.protocolStatus
        status.managed = true
        return status
    }
}
