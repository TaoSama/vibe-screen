import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class ProtocolV1SessionTests: XCTestCase {
    func testProductionHostCapabilitiesAreExact() {
        XCTAssertEqual(
            ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: true),
            [.touch, .stylus, .stylusExtended, .keyboard, .pointer, .clipboard, .multiDisplay, .hostActions, .managedConfiguration, .clientVideoControl, .usbHidModifierByte]
        )
        XCTAssertEqual(
            ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: false),
            [.clipboard, .multiDisplay, .managedConfiguration, .clientVideoControl]
        )
    }

    func testManagedPolicyAppliesDenyWinsAndAllowedHosts() {
        let local = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: 4_096,
            allowedHosts: ["host", "other"]
        )
        var remoteStatus = ManagedPolicy.unmanaged.protocolStatus
        remoteStatus.managed = true
        remoteStatus.clipboardAllowed = false
        remoteStatus.fileTransferAllowed = true
        remoteStatus.audioAllowed = false
        remoteStatus.wakeAllowed = true
        remoteStatus.customGesturesAllowed = true
        remoteStatus.hostActionsAllowed = false
        remoteStatus.maximumFileBytes = 1_024
        remoteStatus.allowedHosts = ["host"]

        let effective = local.applying(remote: ManagedPolicy(remoteStatus: remoteStatus))

        XCTAssertFalse(effective.clipboardAllowed)
        XCTAssertTrue(effective.fileTransferAllowed)
        XCTAssertFalse(effective.audioAllowed)
        XCTAssertTrue(effective.wakeAllowed)
        XCTAssertTrue(effective.customGesturesAllowed)
        XCTAssertFalse(effective.hostActionsAllowed)
        XCTAssertEqual(effective.maximumFileBytes, 1_024)
        XCTAssertEqual(effective.allowedHosts, ["host"])
        XCTAssertTrue(effective.allows(hostID: "host"))
        XCTAssertFalse(effective.allows(hostID: "other"))
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
            maximumFileBytes: 4_096,
            allowedHosts: ["local-host"]
        )
        var remoteStatus = ManagedPolicy.unmanaged.protocolStatus
        remoteStatus.managed = true
        remoteStatus.allowedHosts = ["remote-host"]

        let effective = local.applying(remote: ManagedPolicy(remoteStatus: remoteStatus))

        XCTAssertTrue(effective.allowedHostsRestricted)
        XCTAssertTrue(effective.allowedHosts.isEmpty)
        XCTAssertFalse(effective.allows(hostID: "local-host"))
        XCTAssertFalse(effective.allows(hostID: "remote-host"))
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
            maximumFileBytes: 4_096,
            allowedHosts: [],
            allowedHostsRestricted: true
        )

        let roundTripped = ManagedPolicy(remoteStatus: policy.protocolStatus)

        XCTAssertTrue(roundTripped.allowedHostsRestricted)
        XCTAssertTrue(roundTripped.allowedHosts.isEmpty)
        XCTAssertFalse(roundTripped.allows(hostID: "any-host"))
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
        XCTAssertTrue(policy.allows(hostID: "mac.local"))
        XCTAssertTrue(policy.allows(hostID: " MAC.LOCAL "))
        XCTAssertFalse(policy.allows(hostID: "other.local"))
        XCTAssertEqual(policy.protocolStatus.allowedHosts, ["mac.local", "remote.local"])
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
        XCTAssertTrue(policy.allowedHosts.isEmpty)
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
            "video_config_result", "touch", "stylus", "clipboard_offer",
            "clipboard_request", "clipboard_content", "ping", "pong", "protocol_error",
            "controller_connected", "controller_state", "controller_disconnected"
        ]
        for name in controls {
            let expected = try Data(contentsOf: root.appendingPathComponent("\(name).binpb"))
            XCTAssertEqual(try VSEnvelope(serializedBytes: expected).serializedData(), expected, name)
        }
        // The three controller fixtures form one controller lifecycle on the
        // same negotiated stream: they share controller_id, controller_epoch,
        // and target, while input_id strictly increases across the
        // CONNECTED -> STATE -> DISCONNECTED sequence.
        let controllerNames = ["controller_connected", "controller_state", "controller_disconnected"]
        let controllerEvents = try controllerNames.map { name -> VSControllerEvent in
            let bytes = try Data(contentsOf: root.appendingPathComponent("\(name).binpb"))
            let envelope = try VSEnvelope(serializedBytes: bytes)
            guard case .controllerEvent(let event)? = envelope.payload else {
                throw TestError.missingProtocolError
            }
            return event
        }
        let connected = controllerEvents[0]
        let state = controllerEvents[1]
        let disconnected = controllerEvents[2]
        XCTAssertEqual(connected.controllerID, state.controllerID)
        XCTAssertEqual(state.controllerID, disconnected.controllerID)
        XCTAssertEqual(connected.controllerEpoch, state.controllerEpoch)
        XCTAssertEqual(state.controllerEpoch, disconnected.controllerEpoch)
        XCTAssertTrue(connected.hasTarget && state.hasTarget && disconnected.hasTarget)
        XCTAssertEqual(connected.target.displayID, state.target.displayID)
        XCTAssertEqual(state.target.displayID, disconnected.target.displayID)
        XCTAssertEqual(connected.target.streamID, state.target.streamID)
        XCTAssertEqual(state.target.streamID, disconnected.target.streamID)
        XCTAssertTrue(connected.inputID < state.inputID)
        XCTAssertTrue(state.inputID < disconnected.inputID)
        XCTAssertEqual(controllerState(connected), .neutral)
        XCTAssertEqual(controllerState(disconnected), .neutral)
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
        XCTAssertEqual(hostHello.capabilities, [.touch, .keyboard, .pointer, .stylus, .clipboard, .multiDisplay, .hostActions, .managedConfiguration, .clientVideoControl, .stylusExtended, .usbHidModifierByte])
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

        let omittedFromOffer = makeSession()
        var inconsistent = clientHello()
        inconsistent.clientHello.capabilities.append(.stylus)
        inconsistent.clientHello.requiredCapabilities = [.stylusExtended]
        XCTAssertEqual(
            try protocolError(from: omittedFromOffer.handleControl(inconsistent.serializedData())).code,
            .unsupportedCapability
        )

        let modifierWithoutKeyboard = makeSession()
        var invalidModifierOffer = clientHello()
        invalidModifierOffer.clientHello.capabilities.append(.usbHidModifierByte)
        XCTAssertEqual(
            try protocolError(from: modifierWithoutKeyboard.handleControl(
                invalidModifierOffer.serializedData()
            )).code,
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
        XCTAssertEqual(hostHello.capabilities, [.touch, .keyboard, .pointer, .stylus, .clipboard, .multiDisplay, .hostActions, .managedConfiguration, .clientVideoControl, .stylusExtended, .usbHidModifierByte])
        XCTAssertEqual(accepted.negotiatedCapabilities, [.touch, .multiDisplay])
    }

    func testManagedPolicyStatusIsSentAndRemoteDenyGatesHostActions() throws {
        let localPolicy = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: false,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: 2_048,
            allowedHosts: ["host"]
        )
        let session = makeSession(managedPolicy: localPolicy)
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .hostActions, .managedConfiguration]
        _ = session.handleControl(try hello.serializedData())
        let responses = try controlEnvelopes(session.completeCodecNegotiation())
        XCTAssertEqual(responses.count, 4)
        guard case .sessionAccepted(let accepted)? = responses[1].payload else {
            return XCTFail("Expected SessionAccepted")
        }
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumAudioStreams, 0)
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumClipboardBytes, 1 * 1_024 * 1_024)
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumFileBytes, 2_048)
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumFileChunkBytes, 64 * 1_024)
        guard case .managedPolicyStatus(let localStatus)? = responses[3].payload else {
            return XCTFail("Expected ManagedPolicyStatus")
        }
        XCTAssertTrue(localStatus.managed)
        XCTAssertTrue(localStatus.hostActionsAllowed)
        XCTAssertEqual(localStatus.maximumFileBytes, 2_048)
        XCTAssertEqual(localStatus.allowedHosts, ["host"])

        var remote = VSManagedPolicyStatus()
        remote.managed = true
        remote.clipboardAllowed = true
        remote.fileTransferAllowed = true
        remote.audioAllowed = true
        remote.wakeAllowed = true
        remote.customGesturesAllowed = true
        remote.hostActionsAllowed = false
        remote.maximumFileBytes = 4_096
        remote.allowedHosts = ["host"]
        XCTAssertTrue(session.handleControl(try envelope(
            id: 2,
            payload: .managedPolicyStatus(remote)
        ).serializedData()).isEmpty)

        _ = session.handleControl(try envelope(id: 3, payload: .listDisplaysRequest(VSListDisplaysRequest())).serializedData())
        _ = session.handleControl(try envelope(id: 4, payload: .startDisplayRequest(existingDisplayRequest())).serializedData())
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
        _ = session.handleControl(try envelope(id: 5, payload: .videoConfigResult(result)).serializedData())

        var invoke = VSHostActionInvoke()
        invoke.actionID = "move-window"
        invoke.invocationID = Data([0x01])
        XCTAssertEqual(try protocolError(from: session.handleControl(
            try envelope(id: 6, payload: .hostActionInvoke(invoke)).serializedData()
        )).code, .unsupportedCapability)
    }

    func testManagedPolicyAllowedHostsFailsClosed() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .managedConfiguration]
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()

        var remote = ManagedPolicy.unmanaged.protocolStatus
        remote.managed = true
        remote.allowedHosts = ["different-host"]
        let actions = session.handleControl(try envelope(
            id: 2,
            payload: .managedPolicyStatus(remote)
        ).serializedData())

        XCTAssertEqual(try protocolError(from: actions).code, .unauthorized)
        XCTAssertTrue(actions.containsClose)
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

    func testModifierCompatibilityMatrixUsesNegotiatedLayout() throws {
        let standard = try readyKeyboardSession(standardModifierByte: true)
        XCTAssertEqual(try keyModifiers(from: standard, id: 4, wireMask: 0x01), 0x01)
        XCTAssertEqual(try keyModifiers(from: standard, id: 5, wireMask: 0x02), 0x02)
        XCTAssertEqual(try keyModifiers(from: standard, id: 6, wireMask: 0xF0), 0xF0)
        var reserved = VSKeyEvent()
        reserved.inputID = 7
        reserved.usbHidUsage = 0x04
        reserved.pressed = true
        reserved.modifierMask = 0x100
        XCTAssertEqual(
            try protocolError(from: standard.handleControl(
                try envelope(id: 7, payload: .keyEvent(reserved)).serializedData()
            )).code,
            .invalidState
        )

        let legacy = try readyKeyboardSession(standardModifierByte: false)
        XCTAssertEqual(try keyModifiers(from: legacy, id: 4, wireMask: 0x02), 0x01)
        XCTAssertEqual(try keyModifiers(from: legacy, id: 5, wireMask: 0x01), 0x02)

        var invalid = VSKeyEvent()
        invalid.inputID = 3
        invalid.usbHidUsage = 0x04
        invalid.pressed = true
        invalid.modifierMask = 0x10
        XCTAssertEqual(
            try protocolError(from: legacy.handleControl(
                try envelope(id: 6, payload: .keyEvent(invalid)).serializedData()
            )).code,
            .invalidState
        )
    }

    func testTerminalInputSurvivesVideoReconfigurationButNewInputDoesNot() throws {
        let session = try readyKeyboardSession(standardModifierByte: true)
        _ = session.handleControl(try envelope(
            id: 4,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        guard case .awaitingVideoConfig = session.phase else {
            return XCTFail("expected video reconfiguration")
        }

        var release = VSKeyEvent()
        release.inputID = 5
        release.usbHidUsage = 0x04
        release.pressed = false
        release.modifierMask = StreamInputWire.modifierShift
        XCTAssertTrue(session.handleControl(try envelope(
            id: 5,
            payload: .keyEvent(release)
        ).serializedData()).contains {
            if case .key(let usage, let pressed, let modifiers, _) = $0 {
                return usage == 0x04 && !pressed && modifiers == StreamInputWire.modifierShift
            }
            return false
        })

        var touch = touchEvent()
        touch.inputID = 7
        touch.phase = .cancelled
        XCTAssertTrue(session.handleControl(try envelope(
            id: 7,
            payload: .touchEvent(touch)
        ).serializedData()).contains {
            if case .touch(_, _, _, let phase) = $0 { return phase == .cancelled }
            return false
        })

        let stylusSession = try readyStylusSession()
        XCTAssertTrue(stylusSession.handleControl(try envelope(
            id: 4,
            payload: .stylusEvent(stylusEvent())
        ).serializedData()).contains {
            if case .stylus(_, _, _, _, let phase, _, _, _, _, _, _) = $0 {
                return phase == .began
            }
            return false
        })
        _ = stylusSession.handleControl(try envelope(
            id: 5,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        var stylusEnd = stylusEvent()
        stylusEnd.phase = .ended
        stylusEnd.pressure = 0
        XCTAssertTrue(stylusSession.handleControl(try envelope(
            id: 6,
            payload: .stylusEvent(stylusEnd)
        ).serializedData()).contains {
            if case .stylus(_, _, _, _, let phase, _, _, _, _, _, _) = $0 {
                return phase == .ended
            }
            return false
        })

        release.pressed = true
        XCTAssertEqual(
            try protocolError(from: session.handleControl(try envelope(
                id: 8,
                payload: .keyEvent(release)
            ).serializedData())).code,
            .invalidState
        )
    }

    func testStylusRequiresNegotiationAndRoutesValidatedSample() throws {
        let unnegotiated = try readySession()
        XCTAssertEqual(
            try protocolError(from: unnegotiated.handleControl(
                try envelope(id: 4, payload: .stylusEvent(stylusEvent())).serializedData()
            )).code,
            .unsupportedCapability
        )

        let session = try readyStylusSession()
        let actions = session.handleControl(
            try envelope(id: 4, payload: .stylusEvent(stylusEvent())).serializedData()
        )
        guard case .stylus(
            let inputID, let pointerID, let x, let y, let phase,
            let pressure, let tiltX, let tiltY, let toolKind, let buttonMask, let contactState
        ) = actions.first else { return XCTFail("Expected a stylus action") }
        XCTAssertEqual(inputID, 8)
        XCTAssertEqual(pointerID, 3)
        XCTAssertEqual(x, 0.25)
        XCTAssertEqual(y, 0.75)
        XCTAssertEqual(phase, .began)
        XCTAssertEqual(pressure, 0.625)
        XCTAssertEqual(tiltX, 45)
        XCTAssertEqual(tiltY, -45)
        XCTAssertEqual(toolKind, .pen)
        XCTAssertEqual(buttonMask, 0)
        XCTAssertEqual(contactState, .contact)
    }

    func testStylusRejectsMalformedPressureTiltAndTarget() throws {
        let mutations: [(inout VSStylusEvent) -> Void] = [
            { $0.inputID = 0 },
            { $0.position.x = .nan },
            { $0.pressure = .infinity },
            { $0.pressure = 1.01 },
            { $0.tiltXDegrees = 91 },
            { $0.tiltXDegrees = 90; $0.tiltYDegrees = 90 },
            { $0.phase = .ended; $0.pressure = 0.1 },
            {
                var target = VSInputTarget()
                target.displayID = "wrong-display"
                target.streamID = 1
                $0.target = target
            },
        ]
        for mutate in mutations {
            let session = try readyStylusSession()
            var stylus = stylusEvent()
            mutate(&stylus)
            XCTAssertEqual(
                try protocolError(from: session.handleControl(
                    try envelope(id: 4, payload: .stylusEvent(stylus)).serializedData()
                )).code,
                .invalidState
            )
        }
    }

    func testStylusRejectsOutOfOrderAndMismatchedPointerSequence() throws {
        let missingBegin = try readyStylusSession()
        var changed = stylusEvent()
        changed.phase = .changed
        XCTAssertEqual(try protocolError(from: missingBegin.handleControl(
            try envelope(id: 4, payload: .stylusEvent(changed)).serializedData()
        )).code, .invalidState)

        let mismatch = try readyStylusSession()
        XCTAssertTrue(mismatch.handleControl(
            try envelope(id: 4, payload: .stylusEvent(stylusEvent())).serializedData()
        ).contains { if case .stylus = $0 { return true }; return false })
        changed.pointerID = 4
        XCTAssertEqual(try protocolError(from: mismatch.handleControl(
            try envelope(id: 5, payload: .stylusEvent(changed)).serializedData()
        )).code, .invalidState)
    }

    func testExtendedStylusRequiresIndependentCapabilityAndRoutesHoverEraser() throws {
        var extended = stylusEvent()
        extended.phase = .began
        extended.pressure = 0
        extended.toolKind = .eraser
        extended.contactState = .proximity
        extended.buttonMask = 0b10

        XCTAssertEqual(try protocolError(from: try readyStylusSession().handleControl(
            try envelope(id: 4, payload: .stylusEvent(extended)).serializedData()
        )).code, .invalidState)

        let actions = try readyExtendedStylusSession().handleControl(
            try envelope(id: 4, payload: .stylusEvent(extended)).serializedData()
        )
        guard case .stylus(
            _, _, _, _, .began, 0, _, _, .eraser, 0b10, .proximity
        ) = actions.first else { return XCTFail("Expected extended hover eraser action") }
    }

    func testExtendedStylusRequiresTerminalHoverBeforeContact() throws {
        let session = try readyExtendedStylusSession()
        var hover = stylusEvent()
        hover.pressure = 0
        hover.toolKind = .pen
        hover.contactState = .proximity
        XCTAssertTrue(session.handleControl(
            try envelope(id: 4, payload: .stylusEvent(hover)).serializedData()
        ).contains { if case .stylus = $0 { return true }; return false })

        var contact = stylusEvent()
        contact.toolKind = .pen
        contact.contactState = .contact
        XCTAssertEqual(try protocolError(from: session.handleControl(
            try envelope(id: 5, payload: .stylusEvent(contact)).serializedData()
        )).code, .invalidState)
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

    func testHostActionCatalogIsAdvertisedOnlyWhenNegotiated() throws {
        // A HOST_ACTIONS client learns the catalog right after SessionAccepted.
        let negotiated = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .hostActions]
        _ = negotiated.handleControl(try hello.serializedData())
        let responses = try controlEnvelopes(negotiated.completeCodecNegotiation())
        XCTAssertEqual(responses.count, 3)
        guard case .hostActionCatalog(let catalog)? = responses[2].payload else {
            return XCTFail("Expected HostActionCatalog after SessionAccepted")
        }
        XCTAssertEqual(catalog.actions.map(\.actionID), ["move-window", "return-windows"])
        XCTAssertEqual(catalog.actions.map(\.localizedName), ["Move Focused Window", "Return Moved Windows"])
        XCTAssertTrue(catalog.actions.allSatisfy { $0.requiresConfirmation == false })

        // A client that does not offer HOST_ACTIONS never receives a catalog.
        let ungated = makeSession()
        let ungatedResponses = try controlEnvelopes(ungated.handleControl(
            try clientHello().serializedData()
        )) + (try controlEnvelopes(ungated.completeCodecNegotiation()))
        XCTAssertFalse(ungatedResponses.contains { if case .hostActionCatalog = $0.payload { true } else { false } })
    }

    func testHostActionInvokeForwardsIntentAndResultRidesSessionFIFO() throws {
        let session = try readyHostActionSession()
        let invocationID = Data([0xA1, 0xB2, 0xC3])
        var invoke = VSHostActionInvoke()
        invoke.actionID = "move-window"
        invoke.invocationID = invocationID
        let actions = session.handleControl(
            try envelope(id: 4, payload: .hostActionInvoke(invoke)).serializedData()
        )
        let intents: [(String, Data)] = actions.compactMap {
            if case .hostAction(let id, let invocation, _) = $0 { return (id, invocation) }
            return nil
        }
        XCTAssertEqual(intents.count, 1)
        XCTAssertEqual(intents.first?.0, "move-window")
        XCTAssertEqual(intents.first?.1, invocationID)
        // No result is emitted until the host confirms.
        XCTAssertTrue(try controlEnvelopes(actions).isEmpty)

        // A duplicate in-flight invocation is a safe no-op.
        XCTAssertTrue(session.handleControl(
            try envelope(id: 5, payload: .hostActionInvoke(invoke)).serializedData()
        ).isEmpty)

        // The host confirms; one session-scoped accepted result is emitted.
        let accepted = session.completeHostAction(
            invocationID: invocationID,
            accepted: true,
            rejectionReason: "ignored"
        )
        let acceptedResponses = try controlEnvelopes(accepted)
        XCTAssertEqual(acceptedResponses.count, 1)
        XCTAssertEqual(acceptedResponses.first?.sessionID, sessionID)
        XCTAssertEqual(acceptedResponses.first?.sessionEpoch, sessionEpoch)
        // The result rides the request's message_id as the Envelope
        // correlation_id (the invoke used message_id 4).
        XCTAssertEqual(acceptedResponses.first?.correlationID, 4)
        guard case .hostActionResult(let result)? = acceptedResponses.first?.payload else {
            return XCTFail("Expected HostActionResult")
        }
        XCTAssertEqual(result.invocationID, invocationID)
        XCTAssertTrue(result.accepted)
        XCTAssertTrue(result.rejectionReason.isEmpty)

        // Completing the same invocation again does nothing.
        XCTAssertTrue(session.completeHostAction(
            invocationID: invocationID,
            accepted: true,
            rejectionReason: ""
        ).isEmpty)
    }

    func testHostActionCompletionDeliversDuringVideoReconfig() throws {
        // A completion that lands while the session is renegotiating an
        // in-place display/video reconfiguration must still deliver the tracked
        // result instead of dropping it.
        let session = try readyHostActionSession()
        let invocationID = Data([0x77, 0x77])
        var invoke = VSHostActionInvoke()
        invoke.actionID = "move-window"
        invoke.invocationID = invocationID
        _ = session.handleControl(
            try envelope(id: 4, payload: .hostActionInvoke(invoke)).serializedData()
        )
        // Re-selecting the active display renegotiates in place and moves the
        // session to AWAITING_VIDEO_CONFIG (media stays gated).
        _ = session.handleControl(
            try envelope(id: 5, payload: .startDisplayRequest(existingDisplayRequest())).serializedData()
        )
        XCTAssertNil(try session.makeMediaFrame(payload: Data([1]), timestamp: 1, keyframe: true))

        let completion = session.completeHostAction(
            invocationID: invocationID,
            accepted: true,
            rejectionReason: ""
        )
        let responses = try controlEnvelopes(completion)
        XCTAssertEqual(responses.count, 1)
        XCTAssertEqual(responses.first?.correlationID, 4)
        guard case .hostActionResult(let result)? = responses.first?.payload else {
            return XCTFail("Expected HostActionResult during reconfig")
        }
        XCTAssertEqual(result.invocationID, invocationID)
        XCTAssertTrue(result.accepted)
    }

    func testHostActionRejectionKeepsSessionAliveWithReason() throws {
        let session = try readyHostActionSession()
        let invocationID = Data([0x07])
        var invoke = VSHostActionInvoke()
        invoke.actionID = "return-windows"
        invoke.invocationID = invocationID
        _ = session.handleControl(
            try envelope(id: 4, payload: .hostActionInvoke(invoke)).serializedData()
        )
        let rejected = session.completeHostAction(
            invocationID: invocationID,
            accepted: false,
            rejectionReason: "No movable focused window was found."
        )
        XCTAssertFalse(rejected.containsClose)
        guard case .hostActionResult(let result)? = try controlEnvelopes(rejected).first?.payload else {
            return XCTFail("Expected HostActionResult")
        }
        XCTAssertFalse(result.accepted)
        XCTAssertEqual(result.rejectionReason, "No movable focused window was found.")
    }

    func testHostActionRejectsUnknownActionUngatedAndPreStream() throws {
        // Unknown action id on a negotiated streaming session -> invalidState.
        let session = try readyHostActionSession()
        var unknown = VSHostActionInvoke()
        unknown.actionID = "explode"
        unknown.invocationID = Data([0x01])
        XCTAssertEqual(
            try protocolError(from: session.handleControl(
                try envelope(id: 4, payload: .hostActionInvoke(unknown)).serializedData()
            )).code,
            .invalidState
        )

        // A client without HOST_ACTIONS is rejected as unsupported.
        let ungated = try readySession()
        var ungatedInvoke = VSHostActionInvoke()
        ungatedInvoke.actionID = "move-window"
        ungatedInvoke.invocationID = Data([0x02])
        XCTAssertEqual(
            try protocolError(from: ungated.handleControl(
                try envelope(id: 4, payload: .hostActionInvoke(ungatedInvoke)).serializedData()
            )).code,
            .unsupportedCapability
        )

        // An invoke before streaming is rejected with invalidState.
        let preStream = makeSession()
        var preHello = clientHello()
        preHello.clientHello.capabilities = [.touch, .multiDisplay, .hostActions]
        _ = preStream.handleControl(try preHello.serializedData())
        _ = preStream.completeCodecNegotiation()
        var earlyInvoke = VSHostActionInvoke()
        earlyInvoke.actionID = "move-window"
        earlyInvoke.invocationID = Data([0x03])
        XCTAssertEqual(
            try protocolError(from: preStream.handleControl(
                try envelope(id: 2, payload: .hostActionInvoke(earlyInvoke)).serializedData()
            )).code,
            .invalidState
        )
    }

    func testHostActionTargetMustMatchActiveStream() throws {
        let session = try readyHostActionSession()

        // A foreign target is rejected with invalidState so a stale target
        // never acts on the active display.
        var foreignTarget = VSInputTarget()
        foreignTarget.displayID = "some-other-display"
        foreignTarget.streamID = 99
        var foreignInvoke = VSHostActionInvoke()
        foreignInvoke.actionID = "move-window"
        foreignInvoke.invocationID = Data([0x55])
        foreignInvoke.target = foreignTarget
        XCTAssertEqual(
            try protocolError(from: session.handleControl(
                try envelope(id: 4, payload: .hostActionInvoke(foreignInvoke)).serializedData()
            )).code,
            .invalidState
        )

        // A matching target is forwarded as an intent. Fresh session because the
        // rejection above transitioned this one to .failed.
        let matched = try readyHostActionSession()
        var activeTarget = VSInputTarget()
        activeTarget.displayID = "active-display"
        activeTarget.streamID = 1
        var matchedInvoke = VSHostActionInvoke()
        matchedInvoke.actionID = "move-window"
        matchedInvoke.invocationID = Data([0x56])
        matchedInvoke.target = activeTarget
        XCTAssertTrue(matched.handleControl(
            try envelope(id: 4, payload: .hostActionInvoke(matchedInvoke)).serializedData()
        ).contains { if case .hostAction = $0 { true } else { false } })
    }

    func testHostActionPendingSetIsBounded() throws {
        let session = try readyHostActionSession()
        for index in 0..<16 {
            var invoke = VSHostActionInvoke()
            invoke.actionID = "move-window"
            invoke.invocationID = Data([UInt8(index)])
            XCTAssertTrue(session.handleControl(
                try envelope(id: UInt64(4 + index), payload: .hostActionInvoke(invoke)).serializedData()
            ).contains { if case .hostAction = $0 { true } else { false } })
        }
        var overflow = VSHostActionInvoke()
        overflow.actionID = "move-window"
        overflow.invocationID = Data([0xFF])
        let actions = session.handleControl(
            try envelope(id: 20, payload: .hostActionInvoke(overflow)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: actions).code, .invalidState)
        XCTAssertTrue(actions.containsClose)
        XCTAssertEqual(session.phase, .failed)
    }

    func testProductionHostCapabilitiesIncludeControllerOnlyWhenAvailable() {
        let withoutController = ProtocolV1SessionConfiguration.productionHostCapabilities(
            touchEnabled: true,
            controllerAvailable: false
        )
        XCTAssertFalse(withoutController.contains(.controller))

        let withController = ProtocolV1SessionConfiguration.productionHostCapabilities(
            touchEnabled: true,
            controllerAvailable: true
        )
        XCTAssertTrue(withController.contains(.controller))

        // Controller is independent of the touch input toggle: even when
        // touch/keyboard/pointer are disabled, an available controller is
        // still advertised so the client can negotiate it.
        let inputDisabled = ProtocolV1SessionConfiguration.productionHostCapabilities(
            touchEnabled: false,
            controllerAvailable: true
        )
        XCTAssertTrue(inputDisabled.contains(.controller))
    }

    func testControllerEventRequiresNegotiatedCapability() throws {
        let session = try readySession()
        let actions = session.handleControl(
            try envelope(id: 4, payload: .controllerEvent(controllerEvent(kind: .connected))).serializedData()
        )
        XCTAssertEqual(try protocolError(from: actions).code, .unsupportedCapability)
    }

    func testControllerLifecycleRoutesConnectedStateDisconnected() throws {
        let session = try readyControllerSession()

        let connected = session.handleControl(
            try envelope(id: 4, payload: .controllerEvent(controllerEvent(kind: .connected))).serializedData()
        )
        guard case .controller(let connectedEvent, let connectedCorrelationID)? = connected.first else {
            return XCTFail("Expected a connected controller action")
        }
        XCTAssertEqual(connectedEvent.kind, .connected)
        XCTAssertEqual(connectedEvent.controllerID, "pad-1")
        XCTAssertEqual(connectedEvent.controllerEpoch, 1)
        XCTAssertEqual(connectedCorrelationID, 4)
        XCTAssertTrue(try controlEnvelopes(connected).isEmpty)

        let acknowledgementActions = session.completeControllerConnection(connectedEvent)
        let acknowledgementEnvelope = try XCTUnwrap(
            controlEnvelopes(acknowledgementActions).first
        )
        guard case .inputAck(let acknowledgement)? = acknowledgementEnvelope.payload else {
            return XCTFail("Expected CONNECTED InputAck")
        }
        XCTAssertEqual(acknowledgement.inputID, connectedEvent.inputID)
        XCTAssertTrue(acknowledgement.accepted)
        XCTAssertTrue(acknowledgement.rejectionReason.isEmpty)
        XCTAssertEqual(acknowledgementEnvelope.correlationID, 4)
        XCTAssertEqual(acknowledgementEnvelope.sessionID, sessionID)
        XCTAssertEqual(acknowledgementEnvelope.sessionEpoch, sessionEpoch)
        XCTAssertTrue(session.completeControllerConnection(connectedEvent).isEmpty)

        var stateEvent = controllerEvent(kind: .state)
        stateEvent.inputID = 2
        stateEvent.buttonMask = 1
        stateEvent.leftStickX = 0.5
        let stateActions = session.handleControl(
            try envelope(id: 5, payload: .controllerEvent(stateEvent)).serializedData()
        )
        guard case .controller(let routedState, let stateCorrelationID)? = stateActions.first else {
            return XCTFail("Expected a state controller action")
        }
        XCTAssertEqual(routedState.kind, .state)
        XCTAssertEqual(routedState.state.buttonMask, 1)
        XCTAssertEqual(routedState.state.leftX, 0.5)
        XCTAssertEqual(stateCorrelationID, 5)
        XCTAssertTrue(try controlEnvelopes(stateActions).isEmpty)

        var disconnected = controllerEvent(kind: .disconnected)
        disconnected.inputID = 3
        let disconnectActions = session.handleControl(
            try envelope(id: 6, payload: .controllerEvent(disconnected)).serializedData()
        )
        guard case .controller(let disconnectedEvent, let disconnectCorrelationID)? = disconnectActions.first else {
            return XCTFail("Expected a disconnected controller action")
        }
        XCTAssertEqual(disconnectedEvent.kind, .disconnected)
        XCTAssertEqual(disconnectCorrelationID, 6)
        XCTAssertTrue(try controlEnvelopes(disconnectActions).isEmpty)
    }

    func testControllerStateBeforeConnectedAcknowledgementFailsClosed() throws {
        let session = try readyControllerSession()
        _ = session.handleControl(
            try envelope(
                id: 4,
                payload: .controllerEvent(controllerEvent(kind: .connected))
            ).serializedData()
        )
        var state = controllerEvent(kind: .state)
        state.inputID = 2
        state.buttonMask = 1

        let actions = session.handleControl(
            try envelope(id: 5, payload: .controllerEvent(state)).serializedData()
        )

        let error = try protocolError(from: actions)
        XCTAssertEqual(error.code, .invalidState)
        XCTAssertTrue(error.message.contains("before CONNECTED was acknowledged"))
        XCTAssertTrue(actions.containsClose)
    }

    func testControllerDisconnectedBeforeConnectedAcknowledgementFailsClosed() throws {
        let session = try readyControllerSession()
        _ = session.handleControl(
            try envelope(
                id: 4,
                payload: .controllerEvent(controllerEvent(kind: .connected))
            ).serializedData()
        )
        var disconnected = controllerEvent(kind: .disconnected)
        disconnected.inputID = 2

        let actions = session.handleControl(
            try envelope(id: 5, payload: .controllerEvent(disconnected)).serializedData()
        )

        let error = try protocolError(from: actions)
        XCTAssertEqual(error.code, .invalidState)
        XCTAssertTrue(error.message.contains("before CONNECTED was acknowledged"))
        XCTAssertTrue(actions.containsClose)
    }

    func testControllerCompletionAfterSessionClosedDoesNotSendAck() throws {
        let session = try readyControllerSession()
        let connectedActions = session.handleControl(
            try envelope(
                id: 4,
                payload: .controllerEvent(controllerEvent(kind: .connected))
            ).serializedData()
        )
        guard case .controller(let connected, _)? = connectedActions.first else {
            return XCTFail("Expected CONNECTED delivery")
        }
        var notice = VSDisconnectNotice()
        notice.reasonCode = "test"
        _ = session.handleControl(
            try envelope(id: 5, payload: .disconnectNotice(notice)).serializedData()
        )

        XCTAssertTrue(session.completeControllerConnection(connected).isEmpty)
    }

    func testControllerCompletionAfterSessionFailedDoesNotSendAck() throws {
        let session = try readyControllerSession()
        let connectedActions = session.handleControl(
            try envelope(
                id: 4,
                payload: .controllerEvent(controllerEvent(kind: .connected))
            ).serializedData()
        )
        guard case .controller(let connected, let correlationID)? = connectedActions.first else {
            return XCTFail("Expected CONNECTED delivery")
        }
        let failureActions = session.rejectControllerInjection(
            "test failure",
            correlationID: correlationID
        )

        let failureEnvelope = try XCTUnwrap(controlEnvelopes(failureActions).first)
        XCTAssertEqual(failureEnvelope.protocolError.code, .invalidState)
        XCTAssertEqual(failureEnvelope.protocolError.message, "test failure")
        XCTAssertFalse(failureEnvelope.protocolError.retryable)
        XCTAssertEqual(failureEnvelope.protocolError.component, "macos-host-session")
        XCTAssertEqual(failureEnvelope.correlationID, 4)
        XCTAssertEqual(failureEnvelope.sessionID, sessionID)
        XCTAssertEqual(failureEnvelope.sessionEpoch, sessionEpoch)
        XCTAssertTrue(failureActions.containsClose)
        XCTAssertTrue(session.completeControllerConnection(connected).isEmpty)
    }

    func testControllerForeignTargetIsRejected() throws {
        let session = try readyControllerSession()

        var foreign = controllerEvent(kind: .connected)
        var target = VSInputTarget()
        target.displayID = "some-other-display"
        target.streamID = 99
        foreign.target = target
        let actions = session.handleControl(
            try envelope(id: 4, payload: .controllerEvent(foreign)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: actions).code, .invalidState)

        // A target that names the active display/stream is accepted.
        let matched = try readyControllerSession()
        var activeTarget = VSInputTarget()
        activeTarget.displayID = "active-display"
        activeTarget.streamID = 1
        var matchedEvent = controllerEvent(kind: .connected)
        matchedEvent.target = activeTarget
        XCTAssertTrue(matched.handleControl(
            try envelope(id: 4, payload: .controllerEvent(matchedEvent)).serializedData()
        ).contains { if case .controller = $0 { true } else { false } })
    }

    func testControllerFailClosedForInvalidStateAndTransitions() throws {
        // Reserved button bits (bit 13 and above) are invalid.
        let reservedBits = try readyControllerSession()
        let reservedConnectedActions = reservedBits.handleControl(
            try envelope(id: 4, payload: .controllerEvent(controllerEvent(kind: .connected))).serializedData()
        )
        guard case .controller(let reservedConnected, _)? = reservedConnectedActions.first else {
            return XCTFail("Expected CONNECTED delivery")
        }
        _ = reservedBits.completeControllerConnection(reservedConnected)
        var reserved = controllerEvent(kind: .state)
        reserved.inputID = 2
        reserved.buttonMask = 1 << 13
        XCTAssertEqual(
            try protocolError(from: reservedBits.handleControl(
                try envelope(id: 5, payload: .controllerEvent(reserved)).serializedData()
            )).code,
            .invalidState
        )

        // STATE before CONNECTED is an invalid lifecycle transition.
        let stateBeforeConnected = try readyControllerSession()
        var earlyState = controllerEvent(kind: .state)
        earlyState.buttonMask = 1
        XCTAssertEqual(
            try protocolError(from: stateBeforeConnected.handleControl(
                try envelope(id: 4, payload: .controllerEvent(earlyState)).serializedData()
            )).code,
            .invalidState
        )

        // CONNECTED must carry a neutral state.
        let nonNeutralConnected = try readyControllerSession()
        var nonNeutral = controllerEvent(kind: .connected)
        nonNeutral.buttonMask = 1
        XCTAssertEqual(
            try protocolError(from: nonNeutralConnected.handleControl(
                try envelope(id: 4, payload: .controllerEvent(nonNeutral)).serializedData()
            )).code,
            .invalidState
        )

        // Reusing the same epoch for a second CONNECTED on the same controller
        // is invalid: epochs must strictly increase per controller_id.
        let reusedEpoch = try readyControllerSession()
        _ = reusedEpoch.handleControl(
            try envelope(id: 4, payload: .controllerEvent(controllerEvent(kind: .connected))).serializedData()
        )
        var secondConnected = controllerEvent(kind: .connected)
        secondConnected.inputID = 2
        XCTAssertEqual(
            try protocolError(from: reusedEpoch.handleControl(
                try envelope(id: 5, payload: .controllerEvent(secondConnected)).serializedData()
            )).code,
            .invalidState
        )
    }

    func testControllerFailClosedForOutOfRangeScalars() throws {
        let cases: [(String, (inout VSControllerEvent) -> Void)] = [
            ("stick", { $0.leftStickX = 1.01 }),
            ("trigger", { $0.rightTrigger = -0.01 }),
            ("hat", { $0.hatX = 2 }),
        ]

        for (name, mutate) in cases {
            let session = try readyControllerSession()
            let connectedActions = session.handleControl(
                try envelope(
                    id: 4,
                    payload: .controllerEvent(controllerEvent(kind: .connected))
                ).serializedData()
            )
            guard case .controller(let connected, _)? = connectedActions.first else {
                return XCTFail("Expected CONNECTED delivery for \(name)")
            }
            _ = session.completeControllerConnection(connected)
            var invalid = controllerEvent(kind: .state)
            invalid.inputID = 2
            mutate(&invalid)
            let error = try protocolError(from: session.handleControl(
                try envelope(id: 5, payload: .controllerEvent(invalid)).serializedData()
            ))
            XCTAssertEqual(error.code, .invalidState, name)
        }
    }

    func testControllerFifthConnectedRejectedWithInputAckWithoutClosingSession() throws {
        let session = try readyControllerSession()

        // Connect four controllers. Each uses a distinct controller_id and a
        // strictly increasing input_id.
        for index in 0..<4 {
            var event = controllerEvent(kind: .connected)
            event.inputID = UInt64(index + 1)
            event.controllerID = "pad-\(index + 1)"
            let actions = session.handleControl(
                try envelope(id: UInt64(4 + index), payload: .controllerEvent(event)).serializedData()
            )
            guard case .controller(let connected, _) = actions.first else {
                return XCTFail("Expected controller \(index + 1) to connect")
            }
            _ = session.completeControllerConnection(connected)
        }

        // The fifth CONNECTED must be rejected with a session-scoped InputAck
        // whose accepted is false and rejection_reason is the exact protocol
        // string. The session must stay open and the four admitted controllers
        // must remain active.
        var fifth = controllerEvent(kind: .connected)
        fifth.inputID = 5
        fifth.controllerID = "pad-5"
        let rejectionActions = session.handleControl(
            try envelope(id: 8, payload: .controllerEvent(fifth)).serializedData()
        )
        let envelopes = try controlEnvelopes(rejectionActions)
        guard case .inputAck(let ack)? = envelopes.first?.payload else {
            return XCTFail("Expected an InputAck for the fifth controller")
        }
        XCTAssertEqual(ack.inputID, 5)
        XCTAssertFalse(ack.accepted)
        XCTAssertEqual(ack.rejectionReason, "maximum_active_controllers_exceeded")
        XCTAssertEqual(envelopes.first?.correlationID, 8)
        XCTAssertEqual(envelopes.first?.sessionID, sessionID)
        XCTAssertEqual(envelopes.first?.sessionEpoch, sessionEpoch)
        XCTAssertFalse(rejectionActions.containsClose)
        XCTAssertEqual(session.phase, .streaming(configEpoch: 1, streamID: 1))

        // The rejected input_id was consumed: a subsequent STATE for an
        // existing controller must use a strictly greater input_id, and the
        // existing controller's lifecycle is untouched.
        var existingState = controllerEvent(kind: .state)
        existingState.inputID = 6
        existingState.controllerID = "pad-1"
        existingState.buttonMask = 1
        let stateActions = session.handleControl(
            try envelope(id: 9, payload: .controllerEvent(existingState)).serializedData()
        )
        guard case .controller(let stateEvent, _)? = stateActions.first else {
            return XCTFail("Expected the existing controller to keep receiving STATE")
        }
        XCTAssertEqual(stateEvent.controllerID, "pad-1")
        XCTAssertEqual(stateEvent.state.buttonMask, 1)

        // Reusing the rejected input_id (5) is now a monotonic violation.
        var reusedRejected = controllerEvent(kind: .state)
        reusedRejected.inputID = 5
        reusedRejected.controllerID = "pad-1"
        reusedRejected.buttonMask = 1
        XCTAssertEqual(
            try protocolError(from: session.handleControl(
                try envelope(id: 10, payload: .controllerEvent(reusedRejected)).serializedData()
            )).code,
            .invalidState
        )
    }

    func testControllerFifthCanEnterAfterSlotFreed() throws {
        let session = try readyControllerSession()

        for index in 0..<4 {
            var event = controllerEvent(kind: .connected)
            event.inputID = UInt64(index + 1)
            event.controllerID = "pad-\(index + 1)"
            let actions = session.handleControl(
                try envelope(id: UInt64(4 + index), payload: .controllerEvent(event)).serializedData()
            )
            guard case .controller(let connected, _)? = actions.first else {
                return XCTFail("Expected controller \(index + 1) to connect")
            }
            _ = session.completeControllerConnection(connected)
        }

        // Fifth is rejected while all four slots are occupied.
        var fifth = controllerEvent(kind: .connected)
        fifth.inputID = 5
        fifth.controllerID = "pad-5"
        let rejection = session.handleControl(
            try envelope(id: 8, payload: .controllerEvent(fifth)).serializedData()
        )
        let ackEnvelopes = try controlEnvelopes(rejection)
        guard case .inputAck(let ack)? = ackEnvelopes.first?.payload else {
            return XCTFail("Expected InputAck")
        }
        XCTAssertFalse(ack.accepted)

        // Disconnect pad-1 to free a slot.
        var disconnect = controllerEvent(kind: .disconnected)
        disconnect.inputID = 6
        disconnect.controllerID = "pad-1"
        let disconnectActions = session.handleControl(
            try envelope(id: 9, payload: .controllerEvent(disconnect)).serializedData()
        )
        guard case .controller(let disconnected, _)? = disconnectActions.first else {
            return XCTFail("Expected pad-1 to disconnect")
        }
        XCTAssertEqual(disconnected.kind, .disconnected)

        // Now the fifth controller can connect.
        var retry = controllerEvent(kind: .connected)
        retry.inputID = 7
        retry.controllerID = "pad-5"
        let retryActions = session.handleControl(
            try envelope(id: 10, payload: .controllerEvent(retry)).serializedData()
        )
        guard case .controller(let connected, _)? = retryActions.first else {
            return XCTFail("Expected pad-5 to connect after a slot freed up")
        }
        XCTAssertEqual(connected.controllerID, "pad-5")
    }

    func testControllerNonTerminalEventsFailClosedDuringVideoReconfiguration() throws {
        let connectedSession = try controllerSessionAwaitingVideoReconfiguration()
        var secondConnected = controllerEvent(kind: .connected)
        secondConnected.inputID = 2
        secondConnected.controllerID = "pad-2"
        let connectedActions = connectedSession.handleControl(
            try envelope(id: 5, payload: .controllerEvent(secondConnected)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: connectedActions).code, .invalidState)
        XCTAssertTrue(connectedActions.containsClose)
        XCTAssertEqual(connectedSession.phase, .failed)

        // A hard protocol rejection closes its session, so STATE needs an
        // independent session to prove the second non-terminal case.
        let stateSession = try controllerSessionAwaitingVideoReconfiguration()
        var state = controllerEvent(kind: .state)
        state.inputID = 2
        state.controllerID = "pad-1"
        state.buttonMask = 1
        let stateActions = stateSession.handleControl(
            try envelope(id: 5, payload: .controllerEvent(state)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: stateActions).code, .invalidState)
        XCTAssertTrue(stateActions.containsClose)
        XCTAssertEqual(stateSession.phase, .failed)
    }

    func testControllerDisconnectedAllowedDuringVideoReconfiguration() throws {
        let session = try controllerSessionAwaitingVideoReconfiguration()
        var disconnected = controllerEvent(kind: .disconnected)
        disconnected.inputID = 2
        disconnected.controllerID = "pad-1"
        let disconnectActions = session.handleControl(
            try envelope(id: 5, payload: .controllerEvent(disconnected)).serializedData()
        )
        guard case .controller(let disconnectedEvent, _)? = disconnectActions.first else {
            return XCTFail("Expected DISCONNECTED to be accepted during video reconfiguration")
        }
        XCTAssertEqual(disconnectedEvent.kind, .disconnected)
    }

    func testControllerInputIdMustStrictlyIncrease() throws {
        let duplicateSession = try readyControllerSession()
        let duplicateConnectedActions = duplicateSession.handleControl(
            try envelope(id: 4, payload: .controllerEvent(controllerEvent(kind: .connected))).serializedData()
        )
        guard case .controller(let duplicateConnected, _)? = duplicateConnectedActions.first else {
            return XCTFail("Expected CONNECTED delivery")
        }
        _ = duplicateSession.completeControllerConnection(duplicateConnected)
        var duplicate = controllerEvent(kind: .state)
        duplicate.inputID = 1
        duplicate.buttonMask = 1
        let duplicateActions = duplicateSession.handleControl(
            try envelope(id: 5, payload: .controllerEvent(duplicate)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: duplicateActions).code, .invalidState)
        XCTAssertTrue(duplicateActions.containsClose)
        XCTAssertEqual(duplicateSession.phase, .failed)

        // A hard protocol rejection closes its session, so use a fresh one to
        // prove a decreasing non-zero input_id independently.
        let decreasingSession = try readyControllerSession()
        var connected = controllerEvent(kind: .connected)
        connected.inputID = 5
        let decreasingConnectedActions = decreasingSession.handleControl(
            try envelope(id: 4, payload: .controllerEvent(connected)).serializedData()
        )
        guard case .controller(let decreasingConnected, _)? = decreasingConnectedActions.first else {
            return XCTFail("Expected CONNECTED delivery")
        }
        _ = decreasingSession.completeControllerConnection(decreasingConnected)
        var decreasing = controllerEvent(kind: .state)
        decreasing.inputID = 4
        decreasing.buttonMask = 1
        let decreasingActions = decreasingSession.handleControl(
            try envelope(id: 5, payload: .controllerEvent(decreasing)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: decreasingActions).code, .invalidState)
        XCTAssertTrue(decreasingActions.containsClose)
        XCTAssertEqual(decreasingSession.phase, .failed)
    }

    private let sessionID = Data(repeating: 0xAB, count: 16)
    private let sessionEpoch: UInt64 = 7

    private func makeSession(managedPolicy: ManagedPolicy = .unmanaged) -> ProtocolV1SessionCoordinator {
        var configuration = ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 90,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true,
                managedPolicy: managedPolicy
            ),
            requiredClientCapabilities: [.touch],
            supportedCodecs: [.hevc, .h264],
            hostID: "host",
            hostName: "Mac",
            displayID: "active-display",
            displayName: "Display",
            displayIsVirtual: true
        )
        configuration.managedPolicy = managedPolicy
        return ProtocolV1SessionCoordinator(configuration: configuration)
    }

    private func makeControllerSession() -> ProtocolV1SessionCoordinator {
        ProtocolV1SessionCoordinator(configuration: ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 90,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true,
                controllerAvailable: true
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

    private func stylusEvent() -> VSStylusEvent {
        var point = VSNormalizedPoint()
        point.x = 0.25
        point.y = 0.75
        var stylus = VSStylusEvent()
        stylus.inputID = 8
        stylus.pointerID = 3
        stylus.phase = .began
        stylus.position = point
        stylus.pressure = 0.625
        stylus.tiltXDegrees = 45
        stylus.tiltYDegrees = -45
        return stylus
    }

    private func controllerEvent(kind: VSControllerEventKind) -> VSControllerEvent {
        var event = VSControllerEvent()
        event.inputID = 1
        event.controllerID = "pad-1"
        event.controllerEpoch = 1
        event.kind = kind
        return event
    }

    private func controllerState(_ event: VSControllerEvent) -> GameControllerState {
        GameControllerState(
            buttonMask: event.buttonMask,
            leftX: event.leftStickX,
            leftY: event.leftStickY,
            rightX: event.rightStickX,
            rightY: event.rightStickY,
            leftTrigger: event.leftTrigger,
            rightTrigger: event.rightTrigger,
            hatX: event.hatX,
            hatY: event.hatY
        )
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

    private func readyKeyboardSession(standardModifierByte: Bool) throws -> ProtocolV1SessionCoordinator {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities.append(.keyboard)
        if standardModifierByte {
            hello.clientHello.capabilities.append(.usbHidModifierByte)
        }
        _ = session.handleControl(try hello.serializedData())
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

    private func keyModifiers(
        from session: ProtocolV1SessionCoordinator,
        id: UInt64,
        wireMask: UInt32
    ) throws -> UInt32 {
        var key = VSKeyEvent()
        key.inputID = id
        key.usbHidUsage = 0x04
        key.pressed = true
        key.modifierMask = wireMask
        let actions = session.handleControl(try envelope(id: id, payload: .keyEvent(key)).serializedData())
        for action in actions {
            if case .key(_, _, let modifiers, _) = action { return modifiers }
        }
        throw TestError.missingProtocolError
    }

    private func readyStylusSession() throws -> ProtocolV1SessionCoordinator {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities.append(.stylus)
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()
        _ = session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
        _ = session.handleControl(
            try envelope(id: 3, payload: .videoConfigResult(result)).serializedData()
        )
        return session
    }

    private func readyExtendedStylusSession() throws -> ProtocolV1SessionCoordinator {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities.append(contentsOf: [.stylus, .stylusExtended])
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()
        _ = session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
        _ = session.handleControl(
            try envelope(id: 3, payload: .videoConfigResult(result)).serializedData()
        )
        return session
    }

    /// Drives a session to STREAMING with a client that also negotiates
    /// HOST_ACTIONS, so host-action invocations can be exercised.
    private func readyHostActionSession() throws -> ProtocolV1SessionCoordinator {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .hostActions]
        _ = session.handleControl(try hello.serializedData())
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

    private func readyControllerSession() throws -> ProtocolV1SessionCoordinator {
        let session = makeControllerSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .controller]
        _ = session.handleControl(try hello.serializedData())
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

    private func controllerSessionAwaitingVideoReconfiguration() throws
        -> ProtocolV1SessionCoordinator {
        let session = try readyControllerSession()
        var connected = controllerEvent(kind: .connected)
        connected.inputID = 1
        connected.controllerID = "pad-1"
        _ = session.handleControl(
            try envelope(id: 4, payload: .controllerEvent(connected)).serializedData()
        )
        _ = session.completeControllerConnection(
            GameControllerInputEvent(wireEvent: connected)!
        )
        let switchActions = session.selectDisplayFromClient(displayID: "active-display")
        XCTAssertTrue(switchActions.contains {
            if case .sendControl = $0 { return true }
            return false
        })
        guard case .awaitingVideoConfig = session.phase else {
            throw TestError.missingVideoReconfiguration
        }
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

    private enum TestError: Error {
        case missingProtocolError
        case missingVideoReconfiguration
    }
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
