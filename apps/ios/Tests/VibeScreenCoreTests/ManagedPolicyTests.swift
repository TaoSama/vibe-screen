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

    // MARK: - Remote status semantics

    func testUnmanagedRemoteStatusIsPermissive() {
        var status = VSManagedPolicyStatus()
        status.managed = false
        let policy = ManagedPolicy(remoteStatus: status)

        XCTAssertEqual(policy, .unmanaged)
        XCTAssertTrue(policy.clipboardAllowed)
        XCTAssertTrue(policy.fileTransferAllowed)
        XCTAssertTrue(policy.audioAllowed)
        XCTAssertTrue(policy.wakeAllowed)
        XCTAssertTrue(policy.customGesturesAllowed)
        XCTAssertTrue(policy.hostActionsAllowed)
        XCTAssertEqual(policy.maximumFileBytes, ManagedPolicy.defaultMaximumFileBytes)
    }

    func testManagedRemoteStatusWithUnsetFieldsFailsClosed() {
        var status = VSManagedPolicyStatus()
        status.managed = true
        let policy = ManagedPolicy(remoteStatus: status)

        XCTAssertTrue(policy.isManaged)
        XCTAssertFalse(policy.clipboardAllowed)
        XCTAssertFalse(policy.fileTransferAllowed)
        XCTAssertFalse(policy.audioAllowed)
        XCTAssertFalse(policy.wakeAllowed)
        XCTAssertFalse(policy.customGesturesAllowed)
        XCTAssertFalse(policy.hostActionsAllowed)
        XCTAssertEqual(policy.maximumFileBytes, 0)
    }

    func testManagedRemoteStatusHonorsExplicitAllows() {
        var status = VSManagedPolicyStatus()
        status.managed = true
        status.clipboardAllowed = true
        status.fileTransferAllowed = true
        status.maximumFileBytes = 4_096
        let policy = ManagedPolicy(remoteStatus: status)

        XCTAssertTrue(policy.clipboardAllowed)
        XCTAssertTrue(policy.fileTransferAllowed)
        XCTAssertFalse(policy.audioAllowed)
        XCTAssertEqual(policy.maximumFileBytes, 4_096)
    }

    // MARK: - Resolver updates

    func testResolverRestoresAllowAfterRemoteDeny() {
        let local = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: 1_024,
            allowedHosts: []
        )
        var resolver = ManagedPolicyResolver(localPolicy: local)

        var deny = VSManagedPolicyStatus()
        deny.managed = true
        deny.clipboardAllowed = false
        deny.fileTransferAllowed = true
        deny.audioAllowed = true
        deny.wakeAllowed = true
        deny.customGesturesAllowed = true
        deny.hostActionsAllowed = true
        deny.maximumFileBytes = 128
        resolver.setRemote(ManagedPolicy(remoteStatus: deny))
        XCTAssertFalse(resolver.effectivePolicy.clipboardAllowed)
        XCTAssertEqual(resolver.effectivePolicy.maximumFileBytes, 128)

        var allow = VSManagedPolicyStatus()
        allow.managed = true
        allow.clipboardAllowed = true
        allow.fileTransferAllowed = true
        allow.audioAllowed = true
        allow.wakeAllowed = true
        allow.customGesturesAllowed = true
        allow.hostActionsAllowed = true
        allow.maximumFileBytes = 2_048
        resolver.setRemote(ManagedPolicy(remoteStatus: allow))
        XCTAssertTrue(resolver.effectivePolicy.clipboardAllowed)
        // Local maximumFileBytes (1024) is the binding constraint.
        XCTAssertEqual(resolver.effectivePolicy.maximumFileBytes, 1_024)
    }

    func testResolverLocalDenyCannotBeOverriddenByRemoteAllow() {
        let local = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: false,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: 256,
            allowedHosts: []
        )
        var resolver = ManagedPolicyResolver(localPolicy: local)

        var allow = VSManagedPolicyStatus()
        allow.managed = true
        allow.clipboardAllowed = true
        allow.fileTransferAllowed = true
        allow.audioAllowed = true
        allow.wakeAllowed = true
        allow.customGesturesAllowed = true
        allow.hostActionsAllowed = true
        allow.maximumFileBytes = 2_048
        resolver.setRemote(ManagedPolicy(remoteStatus: allow))

        XCTAssertFalse(resolver.effectivePolicy.clipboardAllowed)
        XCTAssertEqual(resolver.effectivePolicy.maximumFileBytes, 256)
    }

    func testResolverUnmanagedRemoteDoesNotRestrictLocal() {
        let local = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: false,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes + 1,
            allowedHosts: []
        )
        var resolver = ManagedPolicyResolver(localPolicy: local)

        var status = VSManagedPolicyStatus()
        status.managed = false
        resolver.setRemote(ManagedPolicy(remoteStatus: status))

        XCTAssertEqual(resolver.effectivePolicy, local)
        XCTAssertTrue(resolver.effectivePolicy.clipboardAllowed)
        XCTAssertFalse(resolver.effectivePolicy.fileTransferAllowed)
    }

    func testResolverRecomputesFromLocalWhenRemoteCleared() {
        let local = ManagedPolicy.unmanaged
        var resolver = ManagedPolicyResolver(localPolicy: local)

        var deny = VSManagedPolicyStatus()
        deny.managed = true
        deny.clipboardAllowed = false
        deny.fileTransferAllowed = false
        deny.audioAllowed = false
        deny.wakeAllowed = false
        deny.customGesturesAllowed = false
        deny.hostActionsAllowed = false
        deny.maximumFileBytes = 0
        resolver.setRemote(ManagedPolicy(remoteStatus: deny))
        XCTAssertFalse(resolver.effectivePolicy.clipboardAllowed)

        resolver.clearRemote()
        XCTAssertEqual(resolver.effectivePolicy, local)
        XCTAssertTrue(resolver.effectivePolicy.clipboardAllowed)
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
