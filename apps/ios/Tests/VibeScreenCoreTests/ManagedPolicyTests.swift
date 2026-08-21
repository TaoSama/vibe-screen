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
        XCTAssertEqual(Set(policy.protocolStatus.restrictionResults.map(\.restriction)), ManagedPolicy.requiredRestrictionNames)
        XCTAssertEqual(Set(policy.protocolStatus.restrictionResults.map(\.source)), ["managed_configuration"])
        XCTAssertTrue(ManagedPolicy.validateRestrictionResults(policy.protocolStatus))
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
        let hostActionsDenied = managedPolicy(hostActionsAllowed: false).protocolStatus
        let hostActionsPolicy = ManagedPolicy.unmanaged.applying(
            remote: ManagedPolicy(remoteStatus: hostActionsDenied)
        )
        XCTAssertTrue(hostActionsPolicy.customGesturesAllowed)
        XCTAssertFalse(hostActionsPolicy.hostActionsAllowed)
        XCTAssertEqual(Set(hostActionsPolicy.restrictionResults.map(\.source)), ["effective_deny_wins"])

        let customGesturesDenied = managedPolicy(customGesturesAllowed: false).protocolStatus
        let customGesturesPolicy = ManagedPolicy.unmanaged.applying(
            remote: ManagedPolicy(remoteStatus: customGesturesDenied)
        )
        XCTAssertFalse(customGesturesPolicy.customGesturesAllowed)
        XCTAssertTrue(customGesturesPolicy.hostActionsAllowed)
    }

    func testValidateRestrictionResultsRejectsMissingDuplicateAndMismatchedResults() {
        var missing = managedPolicy().protocolStatus
        missing.restrictionResults = []
        XCTAssertFalse(ManagedPolicy.validateRestrictionResults(missing))

        var duplicate = managedPolicy().protocolStatus
        duplicate.restrictionResults[1] = duplicate.restrictionResults[0]
        XCTAssertFalse(ManagedPolicy.validateRestrictionResults(duplicate))

        var mismatched = managedPolicy(clipboardAllowed: false).protocolStatus
        mismatched.restrictionResults[0].allowed = true
        XCTAssertFalse(ManagedPolicy.validateRestrictionResults(mismatched))

        var emptyReason = managedPolicy().protocolStatus
        emptyReason.restrictionResults[0].reason = ""
        XCTAssertFalse(ManagedPolicy.validateRestrictionResults(emptyReason))
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
        let status = managedPolicy(
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: false,
            maximumFileBytes: 4_096
        ).protocolStatus
        let policy = ManagedPolicy(remoteStatus: status)

        XCTAssertTrue(policy.clipboardAllowed)
        XCTAssertTrue(policy.fileTransferAllowed)
        XCTAssertFalse(policy.audioAllowed)
        XCTAssertEqual(policy.maximumFileBytes, 4_096)
    }

    func testFailClosedPolicyExplainsLocalParseErrors() {
        let policy = ManagedPolicy.failClosed

        XCTAssertTrue(policy.isManaged)
        XCTAssertFalse(policy.clipboardAllowed)
        XCTAssertFalse(policy.fileTransferAllowed)
        XCTAssertTrue(policy.allowedHostsRestricted)
        XCTAssertEqual(Set(policy.restrictionResults.map(\.restriction)), ManagedPolicy.requiredRestrictionNames)
        XCTAssertEqual(Set(policy.restrictionResults.map(\.source)), ["local_parse_error"])
        XCTAssertTrue(ManagedPolicy.validateRestrictionResults(policy.protocolStatus))
    }

    func testAllowedHostsAreNormalizedBeforeMatchingAndSerializing() {
        let policy = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: 4_096,
            allowedHosts: [" Mac.Local ", "REMOTE.local", " " ]
        )

        XCTAssertEqual(policy.allowedHosts, ["mac.local", "remote.local"])
        XCTAssertTrue(policy.allows(host: "mac.local"))
        XCTAssertTrue(policy.allows(host: " MAC.LOCAL "))
        XCTAssertFalse(policy.allows(host: "other.local"))
        XCTAssertEqual(policy.protocolStatus.allowedHosts, ["mac.local", "remote.local"])
    }

    func testDeniedHostsOverrideAllowedHostsAndRoundTrip() {
        let policy = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: 4_096,
            allowedHosts: ["mac.local", "other.local"],
            deniedHosts: [" MAC.local "]
        )

        XCTAssertEqual(policy.deniedHosts, ["mac.local"])
        XCTAssertFalse(policy.allows(host: "mac.local"))
        XCTAssertTrue(policy.allows(host: "other.local"))
        XCTAssertEqual(policy.protocolStatus.deniedHosts, ["mac.local"])
        XCTAssertTrue(ManagedPolicy.validateRestrictionResults(policy.protocolStatus))

        let roundTripped = ManagedPolicy(remoteStatus: policy.protocolStatus)
        XCTAssertFalse(roundTripped.allows(host: "mac.local"))
        XCTAssertTrue(roundTripped.allows(host: "other.local"))
    }

    func testRemoteDeniedHostsCannotBeOverriddenByLocalAllowlist() {
        let local = managedPolicy(allowedHosts: ["mac.local", "remote.local"], deniedHosts: ["remote.local"])
        let remote = managedPolicy(allowedHosts: ["mac.local", "other.local"], deniedHosts: ["mac.local"]).protocolStatus

        let effective = local.applying(remote: ManagedPolicy(remoteStatus: remote))

        XCTAssertTrue(effective.allowedHostsRestricted)
        XCTAssertTrue(effective.allowedHosts.isEmpty)
        XCTAssertEqual(effective.deniedHosts, ["mac.local", "remote.local"])
        XCTAssertFalse(effective.allows(host: "mac.local"))
        XCTAssertFalse(effective.allows(host: "remote.local"))
        XCTAssertFalse(effective.allows(host: "other.local"))
        XCTAssertTrue(ManagedPolicy.validateRestrictionResults(effective.protocolStatus))
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

        let deny = managedPolicy(clipboardAllowed: false, maximumFileBytes: 128).protocolStatus
        resolver.setRemote(ManagedPolicy(remoteStatus: deny))
        XCTAssertFalse(resolver.effectivePolicy.clipboardAllowed)
        XCTAssertEqual(resolver.effectivePolicy.maximumFileBytes, 128)

        let allow = managedPolicy(maximumFileBytes: 2_048).protocolStatus
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

        let allow = managedPolicy(maximumFileBytes: 2_048).protocolStatus
        resolver.setRemote(ManagedPolicy(remoteStatus: allow))

        XCTAssertFalse(resolver.effectivePolicy.clipboardAllowed)
        XCTAssertEqual(resolver.effectivePolicy.maximumFileBytes, 256)
    }

    func testDisjointAllowedHostsDenyAllHosts() {
        let local = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: 1_024,
            allowedHosts: ["local-host"]
        )
        let remote = managedPolicy(allowedHosts: ["remote-host"]).protocolStatus

        let effective = local.applying(remote: ManagedPolicy(remoteStatus: remote))

        XCTAssertTrue(effective.allowedHostsRestricted)
        XCTAssertTrue(effective.allowedHosts.isEmpty)
        XCTAssertFalse(effective.allows(host: "local-host"))
        XCTAssertFalse(effective.allows(host: "remote-host"))
    }

    func testRestrictedEmptyAllowedHostsRoundTripsThroughStatus() {
        let policy = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: 1_024,
            allowedHosts: [],
            allowedHostsRestricted: true
        )

        let roundTripped = ManagedPolicy(remoteStatus: policy.protocolStatus)

        XCTAssertTrue(roundTripped.allowedHostsRestricted)
        XCTAssertTrue(roundTripped.allowedHosts.isEmpty)
        XCTAssertFalse(roundTripped.allows(host: "any-host"))
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

        let deny = ManagedPolicy.failClosed.protocolStatus
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

    private func managedPolicy(
        clipboardAllowed: Bool = true,
        fileTransferAllowed: Bool = true,
        audioAllowed: Bool = true,
        wakeAllowed: Bool = true,
        customGesturesAllowed: Bool = true,
        hostActionsAllowed: Bool = true,
        maximumFileBytes: UInt64 = 1_024,
        allowedHosts: Set<String> = [],
        deniedHosts: Set<String> = []
    ) -> ManagedPolicy {
        ManagedPolicy(
            isManaged: true,
            clipboardAllowed: clipboardAllowed,
            fileTransferAllowed: fileTransferAllowed,
            audioAllowed: audioAllowed,
            wakeAllowed: wakeAllowed,
            customGesturesAllowed: customGesturesAllowed,
            hostActionsAllowed: hostActionsAllowed,
            maximumFileBytes: maximumFileBytes,
            allowedHosts: allowedHosts,
            deniedHosts: deniedHosts
        )
    }
}
