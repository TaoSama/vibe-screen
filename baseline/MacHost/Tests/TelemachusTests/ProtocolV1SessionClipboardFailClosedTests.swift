import CryptoKit
import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class ProtocolV1SessionClipboardFailClosedTests: XCTestCase {
    private let sessionID = Data(repeating: 0xAB, count: 16)
    private let sessionEpoch: UInt64 = 7
    private let hostID = "host"
    private let clientDeviceID = "device"

    func testClipboardPayloadsWithWrongSessionEpochFailClosed() throws {
        for (name, payload) in [
            ("offer", VSEnvelope.OneOf_Payload.clipboardOffer(clipboardOffer())),
            ("request", VSEnvelope.OneOf_Payload.clipboardRequest(clipboardRequest())),
            ("content", VSEnvelope.OneOf_Payload.clipboardContent(clipboardContent()))
        ] {
            let session = try readyClipboardSession()
            var message = envelope(id: 4, payload: payload)
            message.sessionEpoch = sessionEpoch + 1

            let actions = session.handleControl(try message.serializedData())

            let error = try protocolError(from: actions)
            XCTAssertEqual(error.code, .unauthorized, "\(name) should fail closed on stale epoch")
            XCTAssertTrue(actions.containsCloseAction, "\(name) should close the violating session")
            XCTAssertEqual(session.phase, .failed)
        }
    }

    func testClipboardPayloadsBeforeStreamingFailClosed() throws {
        for (name, payload) in [
            ("offer", VSEnvelope.OneOf_Payload.clipboardOffer(clipboardOffer())),
            ("request", VSEnvelope.OneOf_Payload.clipboardRequest(clipboardRequest())),
            ("content", VSEnvelope.OneOf_Payload.clipboardContent(clipboardContent()))
        ] {
            let session = negotiatedButNotStreamingSession()

            let actions = session.handleControl(try envelope(id: 4, payload: payload).serializedData())

            let error = try protocolError(from: actions)
            XCTAssertEqual(error.code, .invalidState, "\(name) should fail closed before streaming")
            XCTAssertTrue(actions.containsCloseAction, "\(name) should close the violating session")
            XCTAssertEqual(session.phase, .failed)
        }
    }

    func testManagedPolicyDenyRejectsEveryIncomingClipboardPayloadType() throws {
        for (name, payload) in [
            ("offer", VSEnvelope.OneOf_Payload.clipboardOffer(clipboardOffer())),
            ("request", VSEnvelope.OneOf_Payload.clipboardRequest(clipboardRequest())),
            ("content", VSEnvelope.OneOf_Payload.clipboardContent(clipboardContent()))
        ] {
            let session = try readyClipboardSession(managed: true)
            let denyActions = session.handleControl(try envelope(
                id: 5,
                payload: .managedPolicyStatus(managedPolicyStatus(clipboardAllowed: false))
            ).serializedData())
            XCTAssertEqual(denyActions.count, 1)
            XCTAssertFalse(session.hasClipboardCapability)

            let actions = session.handleControl(try envelope(id: 6, payload: payload).serializedData())

            let error = try protocolError(from: actions)
            XCTAssertEqual(error.code, .unsupportedCapability, "\(name) should fail closed after clipboard deny")
            XCTAssertTrue(actions.containsCloseAction, "\(name) should close the violating session")
            XCTAssertEqual(session.phase, .failed)
        }
    }

    func testClipboardRequestWithInvalidChangeIDLengthFailsSession() throws {
        let session = try readyClipboardSession()
        var request = VSClipboardRequest()
        request.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount - 1)

        let actions = session.handleControl(try envelope(
            id: 4,
            payload: .clipboardRequest(request)
        ).serializedData())

        let error = try protocolError(from: actions)
        XCTAssertEqual(error.code, .invalidState)
        XCTAssertTrue(actions.containsCloseAction)
        XCTAssertEqual(session.phase, .failed)
    }

    func testClipboardRequestForUnknownChangeIDIsAuthenticatedNoOp() throws {
        let session = try readyClipboardSession()
        var request = VSClipboardRequest()
        request.changeID = Data(repeating: 0xEE, count: ClipboardCore.changeIDByteCount)

        let actions = session.handleControl(try envelope(
            id: 4,
            payload: .clipboardRequest(request)
        ).serializedData())

        XCTAssertTrue(actions.isEmpty)
        XCTAssertEqual(session.phase, .streaming(configEpoch: 1, streamID: 1))
    }

    func testLocalManagedPolicyDenyRemovesClipboardFromHostCapabilities() throws {
        let denied = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: false,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes,
            allowedHosts: []
        )
        let capabilities = ProtocolV1SessionConfiguration.productionHostCapabilities(
            touchEnabled: true,
            managedPolicy: denied
        )

        XCTAssertFalse(capabilities.contains(.clipboard))
        XCTAssertTrue(capabilities.contains(.managedConfiguration))
    }

    private func makeSession() -> ProtocolV1SessionCoordinator {
        ProtocolV1SessionCoordinator(configuration: ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 90,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: true),
            requiredClientCapabilities: [.touch],
            supportedCodecs: [.hevc, .h264],
            hostID: hostID,
            hostName: "Mac",
            displayID: "active-display",
            displayName: "Display",
            displayIsVirtual: true
        ))
    }

    private func negotiatedButNotStreamingSession(managed: Bool = false) -> ProtocolV1SessionCoordinator {
        let session = makeSession()
        _ = session.handleControl(clientHello(managed: managed))
        _ = session.completeCodecNegotiation()
        if managed {
            _ = session.handleControl(try! envelope(
                id: 2,
                payload: .managedPolicyStatus(managedPolicyStatus(clipboardAllowed: true))
            ).serializedData())
        }
        return session
    }

    private func readyClipboardSession(managed: Bool = false) throws -> ProtocolV1SessionCoordinator {
        let session = negotiatedButNotStreamingSession(managed: managed)
        let startMessageID: UInt64 = managed ? 3 : 2
        _ = session.handleControl(try envelope(
            id: startMessageID,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
        _ = session.handleControl(try envelope(
            id: startMessageID + 1,
            payload: .videoConfigResult(result)
        ).serializedData())
        return session
    }

    private func clientHello(managed: Bool = false) -> Data {
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = clientDeviceID
        hello.deviceName = "Tablet"
        hello.capabilities = [.touch, .multiDisplay, .clipboard]
        if managed { hello.capabilities.append(.managedConfiguration) }
        hello.codecs = [.hevc, .h264]
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = 1
        envelope.clientHello = hello
        return try! envelope.serializedData()
    }

    private func envelope(id: UInt64, payload: VSEnvelope.OneOf_Payload) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = id
        envelope.sessionID = sessionID
        envelope.sessionEpoch = sessionEpoch
        envelope.payload = payload
        return envelope
    }

    private func existingDisplayRequest() -> VSStartDisplayRequest {
        var request = VSStartDisplayRequest()
        request.mode = .existing
        request.sourceDisplayID = "active-display"
        return request
    }

    private func clipboardOffer(
        changeID: Data = Data(repeating: 0x10, count: ClipboardCore.changeIDByteCount),
        text: String = "from android"
    ) -> VSClipboardOffer {
        let bytes = Data(text.utf8)
        var offer = VSClipboardOffer()
        offer.changeID = changeID
        offer.originDeviceID = clientDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64(bytes.count)
        offer.sha256 = sha256(bytes)
        return offer
    }

    private func clipboardRequest(
        changeID: Data = Data(repeating: 0x10, count: ClipboardCore.changeIDByteCount)
    ) -> VSClipboardRequest {
        var request = VSClipboardRequest()
        request.changeID = changeID
        return request
    }

    private func clipboardContent(
        changeID: Data = Data(repeating: 0x10, count: ClipboardCore.changeIDByteCount),
        text: String = "from android"
    ) -> VSClipboardContent {
        let bytes = Data(text.utf8)
        var content = VSClipboardContent()
        content.changeID = changeID
        content.originDeviceID = clientDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        return content
    }

    private func managedPolicyStatus(clipboardAllowed: Bool) -> VSManagedPolicyStatus {
        let allowedHosts = [hostID]
        let deniedHosts: [String] = []
        var status = VSManagedPolicyStatus()
        status.managed = true
        status.clipboardAllowed = clipboardAllowed
        status.fileTransferAllowed = true
        status.audioAllowed = true
        status.wakeAllowed = true
        status.customGesturesAllowed = true
        status.hostActionsAllowed = true
        status.maximumFileBytes = ManagedPolicy.defaultMaximumFileBytes
        status.allowedHosts = allowedHosts
        status.allowedHostsRestricted = true
        status.deniedHosts = deniedHosts
        status.restrictionResults = [
            restrictionResult("clipboard", clipboardAllowed),
            restrictionResult("file_transfer", true),
            restrictionResult("audio", true),
            restrictionResult("wake", true),
            restrictionResult("custom_gestures", true),
            restrictionResult("host_actions", true),
            restrictionResult("maximum_file_bytes", true),
            restrictionResult("allowed_hosts", true),
            restrictionResult("denied_hosts", true)
        ]
        return status
    }

    private func restrictionResult(_ restriction: String, _ allowed: Bool) -> VSManagedRestrictionResult {
        var result = VSManagedRestrictionResult()
        result.restriction = restriction
        result.allowed = allowed
        result.source = "managed_configuration"
        result.reason = "Test managed policy result."
        return result
    }

    private func controlEnvelopes(_ actions: [ProtocolV1SessionAction]) throws -> [VSEnvelope] {
        try actions.compactMap { action in
            guard case .sendControl(let data) = action else { return nil }
            return try VSEnvelope(serializedBytes: data)
        }
    }

    private func protocolError(from actions: [ProtocolV1SessionAction]) throws -> VSProtocolError {
        let envelopes = try controlEnvelopes(actions)
        guard case .protocolError(let error)? = envelopes.first?.payload else {
            throw TestError.missingProtocolError
        }
        return error
    }

    private func sha256(_ data: Data) -> Data {
        Data(SHA256.hash(data: data))
    }

    private enum TestError: Error { case missingProtocolError }
}

private extension Array where Element == ProtocolV1SessionAction {
    var containsCloseAction: Bool {
        contains { if case .close = $0 { true } else { false } }
    }
}
