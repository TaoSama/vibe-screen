import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class ManagedPolicyTests: XCTestCase {
    func testNilAndEmptyManagedConfigurationAreUnmanaged() throws {
        XCTAssertEqual(try ManagedPolicy(managedConfiguration: nil), .unmanaged)
        XCTAssertEqual(try ManagedPolicy(managedConfiguration: [:]), .unmanaged)
    }

    func testManagedConfigurationParsesPolicyAndRestrictionResults() throws {
        let policy = try ManagedPolicy(managedConfiguration: [
            "ClipboardAllowed": true,
            "FileTransferAllowed": true,
            "AudioAllowed": false,
            "WakeAllowed": true,
            "CustomGesturesAllowed": false,
            "HostActionsAllowed": true,
            "MaximumFileBytes": NSNumber(value: 2_048),
            "AllowedHosts": [" Host.Local ", "", "CLIENT.local"],
            "DeniedHosts": [" Client.Local "]
        ])

        XCTAssertTrue(policy.isManaged)
        XCTAssertTrue(policy.clipboardAllowed)
        XCTAssertFalse(policy.audioAllowed)
        XCTAssertFalse(policy.customGesturesAllowed)
        XCTAssertEqual(policy.maximumFileBytes, 2_048)
        XCTAssertEqual(policy.allowedHosts, ["client.local", "host.local"])
        XCTAssertEqual(policy.deniedHosts, ["client.local"])
        XCTAssertFalse(policy.allows(hostID: "client.local"))
        XCTAssertTrue(policy.allows(hostID: "host.local"))
        XCTAssertEqual(Set(policy.restrictionResults.map(\.restriction)), ManagedPolicy.requiredRestrictionNames)
        XCTAssertEqual(Set(policy.restrictionResults.map(\.source)), ["managed_configuration"])
        XCTAssertTrue(ManagedPolicy.validateRestrictionResults(policy.protocolStatus))
    }

    func testManagedConfigurationMissingBooleansFailsClosed() throws {
        let policy = try ManagedPolicy(managedConfiguration: [
            "MaximumFileBytes": NSNumber(value: 1_024),
            "AllowedHosts": [String]()
        ])

        XCTAssertTrue(policy.isManaged)
        XCTAssertFalse(policy.clipboardAllowed)
        XCTAssertFalse(policy.fileTransferAllowed)
        XCTAssertFalse(policy.audioAllowed)
        XCTAssertFalse(policy.wakeAllowed)
        XCTAssertFalse(policy.customGesturesAllowed)
        XCTAssertFalse(policy.hostActionsAllowed)
        XCTAssertEqual(policy.maximumFileBytes, 1_024)
    }

    func testManagedConfigurationRejectsInvalidTypes() {
        XCTAssertThrowsError(try ManagedPolicy(managedConfiguration: [
            "ClipboardAllowed": "yes"
        ])) { error in
            XCTAssertEqual(error as? ManagedPolicyError, .invalidType("ClipboardAllowed"))
        }

        XCTAssertThrowsError(try ManagedPolicy(managedConfiguration: [
            "MaximumFileBytes": NSNumber(value: -1)
        ])) { error in
            XCTAssertEqual(error as? ManagedPolicyError, .invalidType("MaximumFileBytes"))
        }

        XCTAssertThrowsError(try ManagedPolicy(managedConfiguration: [
            "AllowedHosts": "host.local"
        ])) { error in
            XCTAssertEqual(error as? ManagedPolicyError, .invalidType("AllowedHosts"))
        }

        XCTAssertThrowsError(try ManagedPolicy(managedConfiguration: [
            "DeniedHosts": "host.local"
        ])) { error in
            XCTAssertEqual(error as? ManagedPolicyError, .invalidType("DeniedHosts"))
        }
    }

    func testDenyHostsOverrideAllowHostsAcrossLocalAndRemotePolicies() {
        let local = managedPolicy(allowedHosts: ["host.local", "other.local"], deniedHosts: ["other.local"])
        let remote = managedPolicy(allowedHosts: ["host.local", "remote.local"], deniedHosts: ["host.local"]).protocolStatus

        let effective = local.applying(remote: ManagedPolicy(remoteStatus: remote))

        XCTAssertTrue(effective.allowedHostsRestricted)
        XCTAssertEqual(effective.allowedHosts, [])
        XCTAssertEqual(effective.deniedHosts, ["host.local", "other.local"])
        XCTAssertFalse(effective.allows(hostID: "host.local"))
        XCTAssertFalse(effective.allows(hostID: "other.local"))
        XCTAssertFalse(effective.allows(hostID: "remote.local"))
        XCTAssertTrue(ManagedPolicy.validateRestrictionResults(effective.protocolStatus))
    }

    func testProviderReturnsFailClosedWhenConfigurationCannotParse() {
        let provider = ManagedConfigurationProvider(readConfiguration: {
            ["ClipboardAllowed": "yes"]
        })

        let policy = provider.loadPolicy()

        XCTAssertEqual(policy, .failClosed)
        XCTAssertTrue(policy.isManaged)
        XCTAssertFalse(policy.clipboardAllowed)
        XCTAssertFalse(policy.fileTransferAllowed)
        XCTAssertTrue(policy.allowedHostsRestricted)
        XCTAssertEqual(Set(policy.restrictionResults.map(\.source)), ["local_parse_error"])
        XCTAssertTrue(ManagedPolicy.validateRestrictionResults(policy.protocolStatus))
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
    }

    private func managedPolicy(
        clipboardAllowed: Bool = true,
        allowedHosts: Set<String> = [],
        deniedHosts: Set<String> = []
    ) -> ManagedPolicy {
        ManagedPolicy(
            isManaged: true,
            clipboardAllowed: clipboardAllowed,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: 1_024,
            allowedHosts: allowedHosts,
            deniedHosts: deniedHosts
        )
    }
}
