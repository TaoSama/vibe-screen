import Foundation
import XCTest
@testable import VibeScreen
import VibeScreenCore
import VibeScreenProtocol

private enum KeyEventRecorderError: Error {
    case timedOut
}

private final class KeyEventRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var events: [VSKeyEvent] = []

    func append(_ event: VSKeyEvent) {
        lock.withLock { events.append(event) }
    }

    func firstRelease(usbHIDUsage: UInt32) -> VSKeyEvent? {
        lock.withLock {
            events.first { $0.usbHidUsage == usbHIDUsage && !$0.pressed }
        }
    }

    var releaseEvents: [VSKeyEvent] {
        lock.withLock { events.filter { !$0.pressed } }
    }

    func waitForFirstRelease(usbHIDUsage: UInt32) async throws -> VSKeyEvent {
        for _ in 0..<50 {
            if let event = firstRelease(usbHIDUsage: usbHIDUsage) { return event }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for key release envelope")
        throw KeyEventRecorderError.timedOut
    }
}

@MainActor
final class StreamViewModelNativeInputTests: XCTestCase {
    func testManagedConfigurationReloadDoesNotChangeActiveSessionSnapshot() {
        let key = ManagedPolicy.ManagedConfigurationSchema.managedConfigurationKey
        let previous = UserDefaults.standard.dictionary(forKey: key)
        defer {
            if let previous {
                UserDefaults.standard.set(previous, forKey: key)
            } else {
                UserDefaults.standard.removeObject(forKey: key)
            }
        }

        UserDefaults.standard.set(Self.managedConfiguration(clipboardAllowed: true), forKey: key)
        let viewModel = StreamViewModel()
        viewModel.managedConfiguration.reload()
        viewModel.sessionLocalManagedPolicy = viewModel.managedConfiguration.policy
        viewModel.sessionManagedPolicy = viewModel.managedConfiguration.policy

        UserDefaults.standard.set(Self.managedConfiguration(clipboardAllowed: false), forKey: key)
        viewModel.managedConfiguration.reload()

        XCTAssertFalse(viewModel.managedConfiguration.policy.clipboardAllowed)
        XCTAssertTrue(viewModel.currentManagedPolicy.clipboardAllowed)
    }

    func testRemoteManagedPolicyUpdatesReplacePreviousRemoteAgainstLocalSnapshot() {
        let viewModel = StreamViewModel()
        let local = Self.managedPolicy(clipboardAllowed: true, maximumFileBytes: 1_024)
        viewModel.sessionLocalManagedPolicy = local
        viewModel.sessionManagedPolicy = local

        let firstRemote = Self.managedPolicy(clipboardAllowed: false, maximumFileBytes: 128)
        viewModel.sessionManagedPolicy = viewModel.managedConfiguration.applyRemote(
            firstRemote.protocolStatus,
            localSnapshot: viewModel.sessionLocalManagedPolicy ?? viewModel.managedConfiguration.policy
        )
        XCTAssertFalse(viewModel.currentManagedPolicy.clipboardAllowed)
        XCTAssertEqual(128, viewModel.currentManagedPolicy.maximumFileBytes)

        let secondRemote = Self.managedPolicy(clipboardAllowed: true, maximumFileBytes: 2_048)
        viewModel.sessionManagedPolicy = viewModel.managedConfiguration.applyRemote(
            secondRemote.protocolStatus,
            localSnapshot: viewModel.sessionLocalManagedPolicy ?? viewModel.managedConfiguration.policy
        )

        XCTAssertTrue(viewModel.currentManagedPolicy.clipboardAllowed)
        XCTAssertEqual(1_024, viewModel.currentManagedPolicy.maximumFileBytes)
    }

    func testRemoteManagedPolicyCanRestoreCapabilityFromInitialNegotiatedSessionSet() throws {
        let sessionID = Data([0x49, 0x6F, 0x53])
        let sessionEpoch: UInt64 = 7
        let initialCapabilities: Set<VSCapability> = [.managedConfiguration, .clipboard, .fileTransfer]
        let local = Self.managedPolicy(clipboardAllowed: true, maximumFileBytes: 1_024)
        let viewModel = try makeNegotiatedPolicySession(
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            capabilities: initialCapabilities,
            localPolicy: local
        )

        try viewModel.handleControl(Self.managedPolicyStatusEnvelope(
            messageID: 3,
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            policy: Self.managedPolicy(clipboardAllowed: false, maximumFileBytes: 1_024)
        ))

        XCTAssertFalse(viewModel.negotiatedCapabilities.contains(.clipboard))
        XCTAssertTrue(viewModel.negotiatedCapabilities.contains(.managedConfiguration))

        try viewModel.handleControl(Self.managedPolicyStatusEnvelope(
            messageID: 4,
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            policy: Self.managedPolicy(clipboardAllowed: true, maximumFileBytes: 1_024)
        ))

        XCTAssertTrue(viewModel.negotiatedCapabilities.contains(.clipboard))
        XCTAssertTrue(viewModel.negotiatedCapabilities.contains(.managedConfiguration))
        XCTAssertEqual(viewModel.state.negotiatedCapabilities, initialCapabilities)
    }

    func testKeyReleaseUsesCurrentModifierMaskNotPressTimeStaleMask() async throws {
        let viewModel = makeStreamingViewModel()
        let recorder = attachRecorder(to: viewModel)

        let shiftUsage: UInt32 = 0xE1
        let aUsage: UInt32 = 0x04
        let shiftMask = USBHIDModifierWire.leftShift

        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: shiftUsage,
            pressed: true,
            standardModifierMask: shiftMask,
            text: ""
        ))
        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: aUsage,
            pressed: true,
            standardModifierMask: shiftMask,
            text: "a"
        ))
        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: shiftUsage,
            pressed: false,
            standardModifierMask: 0,
            text: ""
        ))
        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: aUsage,
            pressed: false,
            standardModifierMask: 0,
            text: ""
        ))

        let aRelease = try await recorder.waitForFirstRelease(usbHIDUsage: aUsage)
        XCTAssertEqual(aRelease.modifierMask, 0)
    }

    func testReleaseActiveInputClearsKeysWithZeroModifierMask() async throws {
        let viewModel = makeStreamingViewModel()
        let recorder = attachRecorder(to: viewModel)

        let shiftUsage: UInt32 = 0xE1
        let aUsage: UInt32 = 0x04
        let shiftMask = USBHIDModifierWire.leftShift

        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: shiftUsage,
            pressed: true,
            standardModifierMask: shiftMask,
            text: ""
        ))
        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: aUsage,
            pressed: true,
            standardModifierMask: shiftMask,
            text: "a"
        ))

        let batch = viewModel.releaseActiveInput()

        XCTAssertTrue(batch.allAdmitted)
        await batch.waitForAdmittedReleases()
        XCTAssertEqual(recorder.releaseEvents.map(\.modifierMask), [0, 0])
    }
    private func makeStreamingViewModel() -> StreamViewModel {
        let viewModel = StreamViewModel()
        viewModel.isStreaming = true
        viewModel.negotiatedCapabilities = [.keyboard, .usbHidModifierByte]
        viewModel.selectedStreamID = 1

        let owner = SessionOwner(connectionOwner: ConnectionOwner())
        viewModel.sessionOwner = owner
        viewModel.decoderOwners[1] = DecoderOwner(
            sessionOwner: owner,
            streamID: 1,
            configEpoch: 0
        )
        viewModel.displayBindings = [DisplayStreamBinding(displayID: "display-1", streamID: 1)]
        return viewModel
    }

    private func attachRecorder(to viewModel: StreamViewModel) -> KeyEventRecorder {
        let recorder = KeyEventRecorder()
        let outbox = ControlOutbox(
            sender: { _, frame, _ in
                let envelope = try EnvelopeCodec.deserialize(frame.payload)
                if case .keyEvent(let event)? = envelope.payload {
                    recorder.append(event)
                }
            },
            onFailure: { _ in }
        )
        outbox.activate(owner: viewModel.sessionOwner!)
        viewModel.controlOutbox = outbox
        return recorder
    }

    private func makeNegotiatedPolicySession(
        sessionID: Data,
        sessionEpoch: UInt64,
        capabilities: Set<VSCapability>,
        localPolicy: ManagedPolicy
    ) throws -> StreamViewModel {
        let viewModel = StreamViewModel()
        let owner = SessionOwner(connectionOwner: ConnectionOwner())
        viewModel.sessionOwner = owner
        let outbox = ControlOutbox(sender: { _, _, _ in }, onFailure: { _ in })
        outbox.activate(owner: owner)
        viewModel.controlOutbox = outbox
        viewModel.sessionLocalManagedPolicy = localPolicy
        viewModel.sessionManagedPolicy = localPolicy
        try viewModel.state.beginConnection()
        try viewModel.state.transportConnected()
        try viewModel.state.accept(
            selectedProtocol: SessionState.protocolVersion,
            sessionID: sessionID,
            epoch: sessionEpoch,
            localCapabilities: capabilities,
            hostCapabilities: capabilities
        )
        viewModel.negotiatedCapabilities = viewModel.state.negotiatedCapabilities
        try viewModel.controlValidator.validate(Self.hostHelloEnvelope(messageID: 1, capabilities: capabilities))
        try viewModel.controlValidator.validate(Self.sessionAcceptedEnvelope(
            messageID: 2,
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            capabilities: capabilities
        ))
        try viewModel.controlValidator.awaitManagedPolicyStatus()
        return viewModel
    }

    private static func managedConfiguration(clipboardAllowed: Bool) -> [String: Any] {
        [
            "ClipboardAllowed": clipboardAllowed,
            "FileTransferAllowed": true,
            "AudioAllowed": true,
            "WakeAllowed": true,
            "CustomGesturesAllowed": true,
            "HostActionsAllowed": true,
            "MaximumFileBytes": NSNumber(value: 1_024),
            "AllowedHosts": [String](),
            "DeniedHosts": [String]()
        ]
    }

    private static func managedPolicy(
        clipboardAllowed: Bool,
        maximumFileBytes: UInt64
    ) -> ManagedPolicy {
        ManagedPolicy(
            isManaged: true,
            clipboardAllowed: clipboardAllowed,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: maximumFileBytes,
            allowedHosts: [],
            deniedHosts: []
        )
    }

    private static func hostHelloEnvelope(messageID: UInt64, capabilities: Set<VSCapability>) -> VSEnvelope {
        var hello = VSHostHello()
        hello.selectedProtocol = SessionState.protocolVersion
        hello.capabilities = capabilities.sorted { $0.rawValue < $1.rawValue }

        var envelope = VSEnvelope()
        envelope.protocolVersion = SessionState.protocolVersion
        envelope.messageID = messageID
        envelope.hostHello = hello
        return envelope
    }

    private static func sessionAcceptedEnvelope(
        messageID: UInt64,
        sessionID: Data,
        sessionEpoch: UInt64,
        capabilities: Set<VSCapability>
    ) -> VSEnvelope {
        var accepted = VSSessionAccepted()
        accepted.sessionID = sessionID
        accepted.sessionEpoch = sessionEpoch
        accepted.negotiatedCapabilities = capabilities.sorted { $0.rawValue < $1.rawValue }

        var envelope = VSEnvelope()
        envelope.protocolVersion = SessionState.protocolVersion
        envelope.messageID = messageID
        envelope.sessionID = sessionID
        envelope.sessionEpoch = sessionEpoch
        envelope.sessionAccepted = accepted
        return envelope
    }

    private static func managedPolicyStatusEnvelope(
        messageID: UInt64,
        sessionID: Data,
        sessionEpoch: UInt64,
        policy: ManagedPolicy
    ) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = SessionState.protocolVersion
        envelope.messageID = messageID
        envelope.sessionID = sessionID
        envelope.sessionEpoch = sessionEpoch
        envelope.managedPolicyStatus = policy.protocolStatus
        return envelope
    }
}
