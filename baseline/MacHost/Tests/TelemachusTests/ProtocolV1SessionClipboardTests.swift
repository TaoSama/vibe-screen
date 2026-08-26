import CryptoKit
import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class ProtocolV1SessionClipboardTests: XCTestCase {
    private let sessionID = Data(repeating: 0xAB, count: 16)
    private let sessionEpoch: UInt64 = 7
    private let hostID = "host"
    private let clientDeviceID = "device"

    private func makeSession() -> ProtocolV1SessionCoordinator {
        ProtocolV1SessionCoordinator(configuration: ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 90,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true
            ),
            requiredClientCapabilities: [.touch],
            supportedCodecs: [.hevc, .h264],
            hostID: hostID,
            hostName: "Mac",
            displayID: "active-display",
            displayName: "Display",
            displayIsVirtual: true
        ))
    }

    private func clientHello(
        capabilities: [VSCapability] = [.touch, .multiDisplay, .clipboard],
        maximumClipboardBytes: UInt64 = 0
    ) -> VSEnvelope {
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = clientDeviceID
        hello.deviceName = "Tablet"
        hello.capabilities = capabilities
        hello.codecs = [.hevc, .h264]
        if maximumClipboardBytes > 0 {
            var limits = VSResourceLimits()
            limits.maximumClipboardBytes = maximumClipboardBytes
            hello.resourceLimits = limits
        }
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = 1
        envelope.clientHello = hello
        return envelope
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

    /// Drives a session to STREAMING with clipboard negotiated.
    private func readyClipboardSession(
        maximumClipboardBytes: UInt64 = 0,
        managed: Bool = false
    ) throws -> ProtocolV1SessionCoordinator {
        let session = makeSession()
        var capabilities: [VSCapability] = [.touch, .multiDisplay, .clipboard]
        if managed { capabilities.append(.managedConfiguration) }
        _ = session.handleControl(try clientHello(
            capabilities: capabilities,
            maximumClipboardBytes: maximumClipboardBytes
        ).serializedData())
        _ = session.completeCodecNegotiation()
        var nextID: UInt64 = 2
        if managed {
            _ = session.handleControl(try envelope(
                id: nextID,
                payload: .managedPolicyStatus(ManagedPolicy.unmanaged.protocolStatus)
            ).serializedData())
            nextID += 1
        }
        _ = session.handleControl(try envelope(
            id: nextID,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        nextID += 1
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
        _ = session.handleControl(try envelope(
            id: nextID,
            payload: .videoConfigResult(result)
        ).serializedData())
        return session
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

    // MARK: - Capability absent

    func testClipboardOfferRejectedWhenCapabilityNotNegotiated() throws {
        let session = makeSession()
        // Client does not offer .clipboard.
        _ = session.handleControl(try clientHello(capabilities: [.touch, .multiDisplay]).serializedData())
        _ = session.completeCodecNegotiation()
        _ = session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
        _ = session.handleControl(try envelope(
            id: 3,
            payload: .videoConfigResult(result)
        ).serializedData())

        var offer = VSClipboardOffer()
        offer.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        offer.originDeviceID = clientDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = 4
        offer.sha256 = Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount)

        let actions = session.handleControl(try envelope(
            id: 4,
            payload: .clipboardOffer(offer)
        ).serializedData())

        let error = try protocolError(from: actions)
        XCTAssertEqual(error.code, .unsupportedCapability)
        XCTAssertTrue(actions.containsClose)
        XCTAssertEqual(session.phase, .failed)
    }

    // MARK: - Envelope session/epoch validation

    func testClipboardOfferRejectedForWrongSessionID() throws {
        let session = try readyClipboardSession()

        var offer = VSClipboardOffer()
        offer.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        offer.originDeviceID = clientDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = 4
        offer.sha256 = Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount)

        var badEnvelope = envelope(id: 4, payload: .clipboardOffer(offer))
        badEnvelope.sessionID = Data(repeating: 0xCD, count: 16)

        let actions = session.handleControl(try badEnvelope.serializedData())
        let error = try protocolError(from: actions)
        XCTAssertEqual(error.code, .unauthorized)
        XCTAssertTrue(actions.containsClose)
        XCTAssertEqual(session.phase, .failed)
    }

    func testClipboardOfferRejectedForWrongSessionEpoch() throws {
        let session = try readyClipboardSession()

        var offer = VSClipboardOffer()
        offer.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        offer.originDeviceID = clientDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = 4
        offer.sha256 = Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount)

        var badEnvelope = envelope(id: 4, payload: .clipboardOffer(offer))
        badEnvelope.sessionEpoch = sessionEpoch + 1

        let actions = session.handleControl(try badEnvelope.serializedData())
        let error = try protocolError(from: actions)
        XCTAssertEqual(error.code, .unauthorized)
        XCTAssertTrue(actions.containsClose)
        XCTAssertEqual(session.phase, .failed)
    }

    // MARK: - Normal bidirectional flow

    func testHostShareEmitsClipboardOffer() throws {
        let session = try readyClipboardSession()
        let text = "shared from mac"

        let actions = session.shareClipboard(text: text)
        let envelopes = try controlEnvelopes(actions)
        XCTAssertEqual(envelopes.count, 1)
        guard case .clipboardOffer(let offer)? = envelopes.first?.payload else {
            return XCTFail("Expected clipboardOffer")
        }
        XCTAssertEqual(offer.originDeviceID, hostID)
        XCTAssertEqual(offer.mimeType, ClipboardCore.supportedMIMEType)
        XCTAssertEqual(offer.byteLength, UInt64(Data(text.utf8).count))
        XCTAssertEqual(offer.sha256, sha256(Data(text.utf8)))
        XCTAssertEqual(offer.changeID.count, ClipboardCore.changeIDByteCount)
    }

    func testRemoteManagedPolicyDenyDisablesClipboardAndClearsSnapshot() throws {
        let session = try readyClipboardSession(managed: true)
        let firstShare = session.shareClipboard(text: "will be denied")
        let firstEnvelope = try controlEnvelopes(firstShare).first
        guard case .clipboardOffer(let firstOffer)? = firstEnvelope?.payload else {
            return XCTFail("Expected initial clipboardOffer")
        }

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
        ).protocolStatus
        let policyActions = session.handleControl(try envelope(
            id: 4,
            payload: .managedPolicyStatus(denied)
        ).serializedData())
        XCTAssertEqual(policyActions.count, 1)
        guard case .remoteManagedPolicyChanged(let effectivePolicy) = policyActions[0] else {
            return XCTFail("Expected remoteManagedPolicyChanged")
        }
        XCTAssertTrue(effectivePolicy.managed)
        XCTAssertFalse(effectivePolicy.clipboardAllowed)
        XCTAssertEqual(Set(effectivePolicy.restrictionResults.map(\.source)), ["effective_deny_wins"])
        XCTAssertFalse(session.hasClipboardCapability)
        XCTAssertTrue(session.shareClipboard(text: "after deny").isEmpty)
        XCTAssertTrue(session.requestClipboardContent(changeID: firstOffer.changeID).isEmpty)

        var request = VSClipboardRequest()
        request.changeID = firstOffer.changeID
        let requestActions = session.handleControl(try envelope(
            id: 5,
            payload: .clipboardRequest(request)
        ).serializedData())
        let error = try protocolError(from: requestActions)
        XCTAssertEqual(error.code, .unsupportedCapability)
        XCTAssertTrue(requestActions.containsClose)
    }

    func testClientOfferThenHostRequestThenClientContentSolicitedFlow() throws {
        let session = try readyClipboardSession()
        let text = "from android"
        let bytes = Data(text.utf8)
        let cid = Data(repeating: 0x0A, count: ClipboardCore.changeIDByteCount)

        // 1. Client offers.
        var offer = VSClipboardOffer()
        offer.changeID = cid
        offer.originDeviceID = clientDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64(bytes.count)
        offer.sha256 = sha256(bytes)
        let offerActions = session.handleControl(try envelope(
            id: 4,
            payload: .clipboardOffer(offer)
        ).serializedData())
        XCTAssertEqual(offerActions.count, 1)
        guard case .clipboardOffer(let metadata) = offerActions[0] else {
            return XCTFail("Expected clipboardOffer action")
        }
        XCTAssertEqual(metadata.changeID, cid)

        // 2. Host requests the content.
        let requestActions = session.requestClipboardContent(changeID: cid)
        let requestEnvelopes = try controlEnvelopes(requestActions)
        XCTAssertEqual(requestEnvelopes.count, 1)
        guard case .clipboardRequest(let request)? = requestEnvelopes.first?.payload else {
            return XCTFail("Expected clipboardRequest")
        }
        XCTAssertEqual(request.changeID, cid)

        // 3. Client sends the content; it matches the pending request and
        //    offer, so it is treated as solicited.
        var content = VSClipboardContent()
        content.changeID = cid
        content.originDeviceID = clientDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        let contentActions = session.handleControl(try envelope(
            id: 5,
            payload: .clipboardContent(content)
        ).serializedData())
        XCTAssertEqual(contentActions.count, 1)
        guard case .clipboardContent(let validated) = contentActions[0] else {
            return XCTFail("Expected clipboardContent action")
        }
        XCTAssertEqual(validated.text, text)
        XCTAssertEqual(validated.originDeviceID, clientDeviceID)
    }

    func testClientDirectContentIsFlaggedAsDirect() throws {
        let session = try readyClipboardSession()
        let text = "unsolicited"
        let bytes = Data(text.utf8)
        let cid = Data(repeating: 0x0B, count: ClipboardCore.changeIDByteCount)

        var content = VSClipboardContent()
        content.changeID = cid
        content.originDeviceID = clientDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        let actions = session.handleControl(try envelope(
            id: 4,
            payload: .clipboardContent(content)
        ).serializedData())
        XCTAssertEqual(actions.count, 1)
        guard case .clipboardDirectContent(let validated) = actions[0] else {
            return XCTFail("Expected clipboardDirectContent action")
        }
        XCTAssertEqual(validated.text, text)
    }

    func testPeerClipboardByteLimitConstrainsNegotiatedMaximum() throws {
        let session = try readyClipboardSession(maximumClipboardBytes: 64)
        // A 100-byte offer must be rejected because the peer advertised a
        // 64-byte ceiling.
        var offer = VSClipboardOffer()
        offer.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        offer.originDeviceID = clientDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = 100
        offer.sha256 = Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount)

        let actions = session.handleControl(try envelope(
            id: 4,
            payload: .clipboardOffer(offer)
        ).serializedData())
        let error = try protocolError(from: actions)
        XCTAssertEqual(error.code, .invalidState)
        XCTAssertTrue(actions.containsClose)
    }

    // MARK: - Local invalid share/request must not close the session

    func testShareEmptyTextDoesNotCloseSession() throws {
        let session = try readyClipboardSession()
        let actions = session.shareClipboard(text: "")
        XCTAssertTrue(actions.isEmpty)
        XCTAssertEqual(session.phase, .streaming(configEpoch: 1, streamID: 1))
    }

    func testShareOversizedTextDoesNotCloseSession() throws {
        let session = try readyClipboardSession()
        let oversized = String(repeating: "a", count: ClipboardCore.localMaximumBytes + 1)
        let actions = session.shareClipboard(text: oversized)
        XCTAssertTrue(actions.isEmpty)
        XCTAssertEqual(session.phase, .streaming(configEpoch: 1, streamID: 1))
    }

    func testRequestUnknownChangeIDDoesNotCloseSession() throws {
        let session = try readyClipboardSession()
        let actions = session.requestClipboardContent(
            changeID: Data(repeating: 0xEE, count: ClipboardCore.changeIDByteCount)
        )
        XCTAssertTrue(actions.isEmpty)
        XCTAssertEqual(session.phase, .streaming(configEpoch: 1, streamID: 1))
    }

    func testExpiredRequestCanRetryAndLateContentRequiresDirectApproval() throws {
        let session = try readyClipboardSession()
        let text = "late content"
        let bytes = Data(text.utf8)
        let cid = Data(repeating: 0x0C, count: ClipboardCore.changeIDByteCount)
        var offer = VSClipboardOffer()
        offer.changeID = cid
        offer.originDeviceID = clientDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64(bytes.count)
        offer.sha256 = sha256(bytes)
        _ = session.handleControl(try envelope(
            id: 4,
            payload: .clipboardOffer(offer)
        ).serializedData())
        XCTAssertFalse(session.requestClipboardContent(changeID: cid).isEmpty)

        XCTAssertFalse(session.expireClipboardRequest(
            changeID: Data(repeating: 0xEE, count: ClipboardCore.changeIDByteCount)
        ))
        XCTAssertTrue(session.expireClipboardRequest(changeID: cid))

        var content = VSClipboardContent()
        content.changeID = cid
        content.originDeviceID = clientDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        let actions = session.handleControl(try envelope(
            id: 5,
            payload: .clipboardContent(content)
        ).serializedData())
        guard case .clipboardDirectContent? = actions.first else {
            return XCTFail("Expected late content to require direct approval")
        }
        XCTAssertFalse(session.requestClipboardContent(changeID: cid).isEmpty)
    }

    func testShareClipboardRequiresStreamingState() throws {
        let session = makeSession()
        // Not yet streaming.
        let actions = session.shareClipboard(text: "too early")
        XCTAssertTrue(actions.isEmpty)
    }
}

private extension Array where Element == ProtocolV1SessionAction {
    var containsClose: Bool {
        contains { if case .close = $0 { true } else { false } }
    }
}
