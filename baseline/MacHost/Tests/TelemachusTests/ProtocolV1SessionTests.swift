import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class ProtocolV1SessionTests: XCTestCase {
    func testProductionHostCapabilitiesAreExact() {
        XCTAssertEqual(
            ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: true),
            [.touch, .keyboard, .pointer, .multiDisplay]
        )
        XCTAssertEqual(
            ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: false),
            [.multiDisplay]
        )
    }

    func testFramerHandlesSplitAndCoalescedFrames() throws {
        let first = try ProtocolV1TransportFrame(channel: .control, payload: Data([1, 2])).encoded()
        let second = try ProtocolV1TransportFrame(channel: .video, payload: Data([3])).encoded()
        var framer = ProtocolV1Framer()

        XCTAssertTrue(try framer.append(first.prefix(3)).isEmpty)
        XCTAssertEqual(
            try framer.append(Data(first.dropFirst(3)) + second),
            [
                ProtocolV1TransportFrame(channel: .control, payload: Data([1, 2])),
                ProtocolV1TransportFrame(channel: .video, payload: Data([3]))
            ]
        )
    }

    func testFramerRejectsUnknownChannelAndOversize() {
        var unknown = ProtocolV1Framer()
        XCTAssertThrowsError(try unknown.append(Data([9, 0, 0, 0, 0]))) { error in
            XCTAssertEqual(error as? ProtocolV1FramerError, .unknownChannel(9))
        }

        var oversized = ProtocolV1Framer()
        let length = UInt32(ProtocolV1Framer.maximumPayloadBytes + 1)
        let bytes = Data([1]) + withUnsafeBytes(of: length.bigEndian) { Data($0) }
        XCTAssertThrowsError(try oversized.append(bytes)) { error in
            XCTAssertEqual(
                error as? ProtocolV1FramerError,
                .payloadTooLarge(ProtocolV1Framer.maximumPayloadBytes + 1)
            )
        }
    }

    func testContractGoldenPingEnvelopeBytes() throws {
        var ping = VSPing()
        ping.sequence = 7
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = 1
        envelope.ping = ping

        XCTAssertEqual(
            try envelope.serializedData(),
            Data([0x08, 0x01, 0x10, 0x01, 0xC2, 0x01, 0x02, 0x08, 0x07])
        )
    }

    func testSharedCrossPlatformGoldenFixturesRoundTripExactly() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("contracts/fixtures/messages/v1/bin")
        let controls = [
            "client_hello", "host_hello", "session_accepted",
            "list_displays_request", "list_displays_response",
            "start_display_request", "start_display_response", "video_config",
            "video_config_result", "touch", "ping", "pong", "protocol_error"
        ]
        for name in controls {
            let expected = try Data(contentsOf: root.appendingPathComponent("\(name).binpb"))
            XCTAssertEqual(try VSEnvelope(serializedBytes: expected).serializedData(), expected, name)
        }
        let headerBytes = try Data(contentsOf: root.appendingPathComponent("media_packet_header.binpb"))
        let header = try VSMediaPacketHeader(serializedBytes: headerBytes)
        XCTAssertEqual(try header.serializedData(), headerBytes)
        let annexB = Data([0, 0, 0, 1, 0x40, 0x01, 0x0C, 0x01, 0xFF, 0, 0xAA, 0x55])
        XCTAssertEqual(
            try ProtocolV1MediaPacketCodec.encode(header: header, payload: annexB),
            try Data(contentsOf: root.appendingPathComponent("media_packet.bin"))
        )
        XCTAssertEqual(
            try Data(contentsOf: root.appendingPathComponent("upgrade_offer.bin")),
            Data([ProtocolV1Upgrade.offer])
        )
        XCTAssertEqual(
            try Data(contentsOf: root.appendingPathComponent("upgrade_acknowledgement.bin")),
            ProtocolV1Upgrade.acknowledgement
        )
    }

    func testHandshakeAndDisplayVideoAcknowledgementGateMedia() throws {
        let session = makeSession()
        let helloActions = session.handleControl(try clientHello().serializedData())
        XCTAssertTrue(helloActions.contains { if case .codecNegotiated = $0 { true } else { false } })
        let responses = try controlEnvelopes(session.completeCodecNegotiation())
        XCTAssertEqual(responses.count, 2)
        guard case .hostHello(let hostHello)? = responses[0].payload else {
            return XCTFail("Expected HostHello")
        }
        XCTAssertEqual(hostHello.selectedProtocol, 1)
        XCTAssertEqual(hostHello.capabilities, [.touch, .keyboard, .pointer, .multiDisplay])
        guard case .sessionAccepted(let accepted)? = responses[1].payload else {
            return XCTFail("Expected SessionAccepted")
        }
        XCTAssertEqual(accepted.sessionID, sessionID)
        // The client hello only offers touch + multiDisplay, so negotiation
        // (host caps intersect client caps) stays [.touch, .multiDisplay] even
        // though the host advertises keyboard/pointer in hostHello.
        XCTAssertEqual(accepted.negotiatedCapabilities, [.touch, .multiDisplay])
        XCTAssertNil(try session.makeMediaFrame(payload: Data([1]), timestamp: 1, keyframe: true))

        let listActions = session.handleControl(try envelope(
            id: 2,
            payload: .listDisplaysRequest(VSListDisplaysRequest())
        ).serializedData())
        guard case .listDisplaysResponse(let displays)? = try controlEnvelopes(listActions).first?.payload else {
            return XCTFail("Expected ListDisplaysResponse")
        }
        XCTAssertEqual(displays.displays.count, 1)

        let startActions = session.handleControl(try envelope(
            id: 3,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        let startResponses = try controlEnvelopes(startActions)
        XCTAssertEqual(startResponses.count, 2)
        guard case .videoConfig(let config)? = startResponses[1].payload else {
            return XCTFail("Expected VideoConfig")
        }
        XCTAssertEqual(config.codec, .hevc)
        XCTAssertNil(try session.makeMediaFrame(payload: Data([1]), timestamp: 1, keyframe: true))

        var result = VSVideoConfigResult()
        result.configEpoch = config.configEpoch
        result.streamID = config.streamID
        result.accepted = true
        let ready = session.handleControl(try envelope(id: 4, payload: .videoConfigResult(result)).serializedData())
        XCTAssertTrue(ready.containsConnectionReady)
        XCTAssertNotNil(try session.makeMediaFrame(payload: Data([1]), timestamp: 1, keyframe: true))
    }

    func testMultiDisplayEnumerationAndSelection() throws {
        let session = makeMultiDisplaySession()
        _ = session.handleControl(try clientHello().serializedData())
        _ = session.completeCodecNegotiation()

        let listActions = session.handleControl(try envelope(
            id: 2,
            payload: .listDisplaysRequest(VSListDisplaysRequest())
        ).serializedData())
        guard case .listDisplaysResponse(let displays)? = try controlEnvelopes(listActions).first?.payload else {
            return XCTFail("Expected ListDisplaysResponse")
        }
        XCTAssertEqual(displays.displays.count, 2)
        XCTAssertEqual(displays.displays[0].displayID, "active-display")
        XCTAssertTrue(displays.displays[0].isPrimary)
        XCTAssertEqual(displays.displays[1].displayID, "second-display")
        XCTAssertFalse(displays.displays[1].isPrimary)
        XCTAssertEqual(displays.displays[1].logicalSize.width, 3840)
        XCTAssertEqual(displays.displays[1].logicalSize.height, 2160)

        let startActions = session.handleControl(try envelope(
            id: 3,
            payload: .startDisplayRequest(displayRequest(sourceDisplayID: "second-display"))
        ).serializedData())
        XCTAssertTrue(startActions.contains {
            if case .selectDisplay(let id) = $0 { return id == "second-display" }
            return false
        })
        let startResponses = try controlEnvelopes(startActions)
        XCTAssertEqual(startResponses.count, 2)
        guard case .startDisplayResponse(let response)? = startResponses[0].payload,
              case .videoConfig(let config)? = startResponses[1].payload else {
            return XCTFail("Expected StartDisplayResponse + VideoConfig")
        }
        XCTAssertTrue(response.accepted)
        XCTAssertEqual(response.display.displayID, "second-display")
        XCTAssertFalse(response.display.isPrimary)
        XCTAssertEqual(config.encodedSize.width, 3840)
        XCTAssertEqual(config.encodedSize.height, 2160)

        let unknownSession = makeMultiDisplaySession()
        _ = unknownSession.handleControl(try clientHello().serializedData())
        _ = unknownSession.completeCodecNegotiation()
        let unknown = unknownSession.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(displayRequest(sourceDisplayID: "does-not-exist"))
        ).serializedData())
        XCTAssertEqual(try protocolError(from: unknown).code, .invalidState)
    }

    func testHandshakeRejectsVersionAndUnsupportedRequiredCapability() throws {
        let wrongVersion = makeSession()
        var hello = clientHello()
        hello.clientHello.supportedProtocols.minimum = 2
        hello.clientHello.supportedProtocols.maximum = 2
        XCTAssertEqual(try protocolError(from: wrongVersion.handleControl(hello.serializedData())).code, .unsupportedVersion)

        let unsupported = makeSession()
        var required = clientHello()
        // telemetry is advertised by neither host nor negotiation, so requiring
        // it must be rejected. (keyboard/pointer are now supported inputs.)
        required.clientHello.requiredCapabilities = [.telemetry]
        XCTAssertEqual(
            try protocolError(from: unsupported.handleControl(required.serializedData())).code,
            .unsupportedCapability
        )
    }

    func testUnimplementedTelemetryIsNotAdvertisedOrNegotiated() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities.append(.telemetry)

        _ = session.handleControl(try hello.serializedData())
        let responses = try controlEnvelopes(session.completeCodecNegotiation())
        guard case .hostHello(let hostHello)? = responses[0].payload,
              case .sessionAccepted(let accepted)? = responses[1].payload else {
            return XCTFail("Expected HostHello + SessionAccepted")
        }
        XCTAssertEqual(hostHello.capabilities, [.touch, .keyboard, .pointer, .multiDisplay])
        XCTAssertEqual(accepted.negotiatedCapabilities, [.touch, .multiDisplay])
    }

    func testInvalidDisplayAndStaleEpochFailClosed() throws {
        let invalidDisplay = makeSession()
        _ = invalidDisplay.handleControl(try clientHello().serializedData())
        _ = invalidDisplay.completeCodecNegotiation()
        var request = existingDisplayRequest()
        request.sourceDisplayID = "not-active"
        XCTAssertEqual(
            try protocolError(from: invalidDisplay.handleControl(
                try envelope(id: 2, payload: .startDisplayRequest(request)).serializedData()
            )).code,
            .invalidState
        )

        let stale = makeSession()
        _ = stale.handleControl(try clientHello().serializedData())
        _ = stale.completeCodecNegotiation()
        var ping = VSPing()
        ping.sequence = 1
        var staleEnvelope = envelope(id: 2, payload: .ping(ping))
        staleEnvelope.sessionEpoch = sessionEpoch - 1
        XCTAssertEqual(
            try protocolError(from: stale.handleControl(staleEnvelope.serializedData())).code,
            .unauthorized
        )
    }

    func testInputHeartbeatPeerErrorAndMediaHeader() throws {
        let session = try readySession()

        var point = VSNormalizedPoint()
        point.x = 0.25
        point.y = 0.75
        var touch = VSTouchEvent()
        touch.inputID = 1
        touch.pointerID = 1
        touch.phase = .began
        touch.position = point
        let touchActions = session.handleControl(
            try envelope(id: 4, payload: .touchEvent(touch)).serializedData()
        )
        XCTAssertTrue(touchActions.containsTouch)

        var ping = VSPing()
        ping.sequence = 42
        let pingActions = session.handleControl(try envelope(id: 5, payload: .ping(ping)).serializedData())
        XCTAssertTrue(pingActions.containsHeartbeat)
        let pongResponses = try controlEnvelopes(pingActions)
        guard case .pong(let pong)? = pongResponses.first?.payload else { return XCTFail("Expected Pong") }
        XCTAssertEqual(pong.sequence, 42)

        let annexB = Data([0, 0, 0, 1, 0x26])
        let media = try XCTUnwrap(session.makeMediaFrame(payload: annexB, timestamp: 99, keyframe: true))
        let (header, payload) = try decodeMedia(media)
        XCTAssertEqual(header.sessionEpoch, sessionEpoch)
        XCTAssertEqual(header.configEpoch, 1)
        XCTAssertEqual(header.streamID, 1)
        XCTAssertEqual(header.frameID, 1)
        XCTAssertTrue(header.keyframe)
        XCTAssertEqual(payload, annexB)

        var peerError = VSProtocolError()
        peerError.code = .invalidState
        let peerActions = session.handleControl(
            try envelope(id: 6, payload: .protocolError(peerError)).serializedData()
        )
        XCTAssertTrue(peerActions.containsPeerErrorAndClose)
    }

    func testUnnegotiatedPointerInputIsRejected() throws {
        let session = try readySession()
        var point = VSNormalizedPoint()
        point.x = 0.5
        point.y = 0.5
        var pointer = VSPointerEvent()
        pointer.inputID = 1
        pointer.phase = .changed
        pointer.position = point
        XCTAssertEqual(
            try protocolError(from: session.handleControl(
                try envelope(id: 4, payload: .pointerEvent(pointer)).serializedData()
            )).code,
            .unsupportedCapability
        )
    }

    func testClientDisconnectNoticeClosesWithoutProtocolError() throws {
        let session = try readySession()
        var notice = VSDisconnectNotice()
        notice.reasonCode = "client_shutdown"
        notice.mayResume = true

        let actions = session.handleControl(
            try envelope(id: 4, payload: .disconnectNotice(notice)).serializedData()
        )

        XCTAssertEqual(session.phase, .closed)
        XCTAssertTrue(actions.containsClose)
        XCTAssertTrue(try controlEnvelopes(actions).isEmpty)
        XCTAssertFalse(actions.contains { if case .peerError = $0 { true } else { false } })
    }

    func testTouchTargetAcceptsActiveOrEmptyAndRejectsWrongTarget() throws {
        let session = try readySession()

        var emptyTargetTouch = touchEvent()
        emptyTargetTouch.target = VSInputTarget()
        XCTAssertTrue(session.handleControl(
            try envelope(id: 4, payload: .touchEvent(emptyTargetTouch)).serializedData()
        ).containsTouch)

        var activeTarget = VSInputTarget()
        activeTarget.displayID = "active-display"
        activeTarget.streamID = 1
        var activeTargetTouch = touchEvent()
        activeTargetTouch.target = activeTarget
        XCTAssertTrue(session.handleControl(
            try envelope(id: 5, payload: .touchEvent(activeTargetTouch)).serializedData()
        ).containsTouch)

        var wrongTarget = activeTarget
        wrongTarget.streamID = 2
        var wrongTargetTouch = touchEvent()
        wrongTargetTouch.target = wrongTarget
        let rejected = session.handleControl(
            try envelope(id: 6, payload: .touchEvent(wrongTargetTouch)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: rejected).code, .invalidState)
        XCTAssertTrue(rejected.containsClose)
    }

    private let sessionID = Data(repeating: 0xAB, count: 16)
    private let sessionEpoch: UInt64 = 7

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
            hostID: "host",
            hostName: "Mac",
            displayID: "active-display",
            displayName: "Display",
            displayIsVirtual: true
        ))
    }

    private func makeMultiDisplaySession() -> ProtocolV1SessionCoordinator {
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
            hostID: "host",
            hostName: "Mac",
            displayID: "active-display",
            displayName: "Display",
            displayIsVirtual: true,
            displays: [
                ProtocolV1DisplayInfo(
                    id: "active-display", name: "Built-in Display",
                    width: 1920, height: 1080, isPrimary: true, isVirtual: false
                ),
                ProtocolV1DisplayInfo(
                    id: "second-display", name: "External 4K",
                    width: 3840, height: 2160, isPrimary: false, isVirtual: false
                )
            ]
        ))
    }

    private func clientHello() -> VSEnvelope {
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "device"
        hello.deviceName = "Tablet"
        hello.capabilities = [.touch, .multiDisplay]
        hello.codecs = [.hevc, .h264]
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

    private func displayRequest(sourceDisplayID: String) -> VSStartDisplayRequest {
        var request = VSStartDisplayRequest()
        request.mode = .existing
        request.sourceDisplayID = sourceDisplayID
        return request
    }

    private func touchEvent() -> VSTouchEvent {
        var point = VSNormalizedPoint()
        point.x = 0.25
        point.y = 0.75
        var touch = VSTouchEvent()
        touch.inputID = 1
        touch.pointerID = 1
        touch.phase = .began
        touch.position = point
        return touch
    }

    private func readySession() throws -> ProtocolV1SessionCoordinator {
        let session = makeSession()
        _ = session.handleControl(try clientHello().serializedData())
        _ = session.completeCodecNegotiation()
        _ = session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
        _ = session.handleControl(try envelope(id: 3, payload: .videoConfigResult(result)).serializedData())
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

    private func decodeMedia(_ data: Data) throws -> (VSMediaPacketHeader, Data) {
        var cursor = 0
        var headerLength = 0
        var shift = 0
        while cursor < data.count {
            let byte = data[cursor]
            cursor += 1
            headerLength |= Int(byte & 0x7f) << shift
            if byte & 0x80 == 0 { break }
            shift += 7
        }
        let headerEnd = cursor + headerLength
        return (
            try VSMediaPacketHeader(serializedBytes: data[cursor..<headerEnd]),
            Data(data.dropFirst(headerEnd))
        )
    }

    private enum TestError: Error { case missingProtocolError }
}

private extension Array where Element == ProtocolV1SessionAction {
    var containsConnectionReady: Bool { contains { if case .connectionReady = $0 { true } else { false } } }
    var containsTouch: Bool { contains { if case .touch = $0 { true } else { false } } }
    var containsHeartbeat: Bool { contains { if case .heartbeat = $0 { true } else { false } } }
    var containsClose: Bool { contains { if case .close = $0 { true } else { false } } }
    var containsPeerErrorAndClose: Bool {
        contains { if case .peerError = $0 { true } else { false } } &&
            contains { if case .close = $0 { true } else { false } }
    }
}
