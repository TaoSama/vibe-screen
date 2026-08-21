import XCTest
@testable import VibeScreenCore

final class GestureMappingTests: XCTestCase {
    func testHostActionCatalogPolicyFiltersUnknownAndDuplicateIDs() {
        let actions = HostActionCatalogPolicy.supportedActionIDs(from: [
            "unknown-action",
            HostActionCatalogPolicy.moveWindowActionID,
            HostActionCatalogPolicy.moveWindowActionID,
            HostActionCatalogPolicy.returnWindowsActionID,
        ])

        XCTAssertEqual(actions, [
            HostActionCatalogPolicy.moveWindowActionID,
            HostActionCatalogPolicy.returnWindowsActionID,
        ])
    }

    func testHostActionGestureRequiresHostActionsPolicy() throws {
        let profile = GestureProfile(mappings: [
            GestureMapping(trigger: .doubleTap, action: .invokeHostAction(HostActionCatalogPolicy.moveWindowActionID)),
        ])
        let policy = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: false,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes,
            allowedHosts: []
        )

        XCTAssertThrowsError(try profile.validated(
            availableHostActions: [HostActionCatalogPolicy.moveWindowActionID],
            policy: policy
        )) { error in
            XCTAssertEqual(error as? GestureMappingError, .policyDenied)
        }
    }

    func testHostActionGestureRequiresKnownAvailableAction() throws {
        let profile = GestureProfile(mappings: [
            GestureMapping(trigger: .doubleTap, action: .invokeHostAction("custom-action")),
        ])

        XCTAssertThrowsError(try profile.validated(
            availableHostActions: ["custom-action"],
            policy: .unmanaged
        )) { error in
            XCTAssertEqual(error as? GestureMappingError, .unavailableHostAction("custom-action"))
        }
    }

    func testDuplicateGestureTriggersAreDenied() throws {
        let profile = GestureProfile(mappings: [
            GestureMapping(trigger: .doubleTap, action: .toggleControls),
            GestureMapping(trigger: .doubleTap, action: .showKeyboard),
        ])

        XCTAssertThrowsError(try profile.validated(
            availableHostActions: [],
            policy: .unmanaged
        )) { error in
            XCTAssertEqual(error as? GestureMappingError, .duplicateTrigger(.doubleTap))
        }
    }
}
