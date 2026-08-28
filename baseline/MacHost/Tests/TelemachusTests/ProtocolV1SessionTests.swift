import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class ProtocolV1SessionTests: XCTestCase {
    func testProductionHostCapabilitiesAreExact() {
        XCTAssertEqual(
            ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: true),
            [.touch, .stylus, .stylusExtended, .keyboard, .pointer, .clipboard, .colorManagement, .multiDisplay, .hostActions, .managedConfiguration, .clientVideoControl, .usbHidModifierByte]
        )
        XCTAssertEqual(
            ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: false),
            [.clipboard, .colorManagement, .multiDisplay, .managedConfiguration, .clientVideoControl]
        )
        XCTAssertFalse(
            ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: true).contains(.hdrVideo)
        )
        XCTAssertFalse(
            ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: true).contains(.peripheralInputFramework)
        )
        XCTAssertTrue(
            ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true,
                hdrVideoAvailable: true
            ).contains(.hdrVideo)
        )
    }

    func testProductionHostCapabilitiesIncludeWakeHostOnlyWhenAvailable() {
        XCTAssertFalse(
            ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: true).contains(.wakeHost)
        )
        XCTAssertTrue(ProtocolV1SessionConfiguration.productionHostCapabilities(
            touchEnabled: true,
            wakeHostAvailable: true
        ).contains(.wakeHost))
    }

    func testProductionHostCapabilitiesIncludeAudioOnlyWhenCaptureIsAvailableAndPolicyAllows() {
        XCTAssertFalse(
            ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: true).contains(.audio)
        )
        XCTAssertTrue(ProtocolV1SessionConfiguration.productionHostCapabilities(
            touchEnabled: true,
            audioCaptureAvailable: true
        ).contains(.audio))

        let policy = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: false,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes,
            allowedHosts: []
        )
        XCTAssertFalse(ProtocolV1SessionConfiguration.productionHostCapabilities(
            touchEnabled: true,
            managedPolicy: policy,
            audioCaptureAvailable: true
        ).contains(.audio))
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
        let remoteStatus = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: false,
            fileTransferAllowed: true,
            audioAllowed: false,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: false,
            maximumFileBytes: 1_024,
            allowedHosts: ["host"]
        ).protocolStatus

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
        XCTAssertEqual(Set(effective.restrictionResults.map(\.source)), ["effective_deny_wins"])
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
        let remoteStatus = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes,
            allowedHosts: ["remote-host"]
        ).protocolStatus

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
        XCTAssertEqual(hostHello.capabilities, [.touch, .keyboard, .pointer, .stylus, .clipboard, .colorManagement, .multiDisplay, .hostActions, .managedConfiguration, .clientVideoControl, .stylusExtended, .usbHidModifierByte])
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

    func testHostDisplayRouterIsolatesClientsEpochsAndStreamLimits() throws {
        let router = HostMultiClientDisplayRouter(maximumClients: 2, maximumStreamsPerClient: 2)
        let first = HostClientSessionKey(sessionID: Data([0x01]), epoch: 1)
        let second = HostClientSessionKey(sessionID: Data([0x02]), epoch: 1)
        let firstNextEpoch = HostClientSessionKey(sessionID: Data([0x01]), epoch: 2)

        XCTAssertThrowsError(try router.register(HostClientSessionKey(sessionID: Data(), epoch: 1))) { error in
            XCTAssertEqual(error as? HostDisplayRouterError, .invalidSession)
        }
        XCTAssertThrowsError(try router.register(HostClientSessionKey(sessionID: Data([0x09]), epoch: 0))) { error in
            XCTAssertEqual(error as? HostDisplayRouterError, .invalidSession)
        }

        try router.register(first)
        XCTAssertThrowsError(try router.allocateStream(for: "", in: first)) { error in
            XCTAssertEqual(error as? HostDisplayRouterError, .invalidBinding)
        }
        XCTAssertEqual(try router.allocateStream(for: "display-a", in: first), 1)
        XCTAssertEqual(try router.allocateStream(for: "display-b", in: first), 2)
        XCTAssertThrowsError(try router.rebind(streamID: 2, toDisplayID: "display-a", in: first)) { error in
            XCTAssertEqual(error as? HostDisplayRouterError, .duplicateDisplay("display-a"))
        }
        XCTAssertThrowsError(try router.allocateStream(for: "display-c", in: first)) { error in
            XCTAssertEqual(error as? HostDisplayRouterError, .streamLimitReached(2))
        }

        try router.register(second)
        XCTAssertEqual(try router.allocateStream(for: "display-a", in: second), 1)
        XCTAssertEqual(router.activeClientCount, 2)
        XCTAssertThrowsError(try router.register(HostClientSessionKey(sessionID: Data([0x03]), epoch: 1))) { error in
            XCTAssertEqual(error as? HostDisplayRouterError, .clientLimitReached(2))
        }

        try router.register(firstNextEpoch)
        XCTAssertNil(router.binding(streamID: 1, in: first))
        XCTAssertEqual(router.binding(streamID: 1, in: firstNextEpoch)?.displayID, nil)
        XCTAssertEqual(try router.allocateStream(for: "display-c", in: firstNextEpoch), 1)
        XCTAssertEqual(router.activeClientCount, 2)

        XCTAssertThrowsError(try router.register(first)) { error in
            XCTAssertEqual(error as? HostDisplayRouterError, .invalidSession)
        }
        router.disconnect(second)
        XCTAssertNil(router.binding(streamID: 1, in: second))
        XCTAssertEqual(router.binding(streamID: 1, in: firstNextEpoch)?.displayID, "display-c")
        XCTAssertEqual(router.activeClientCount, 1)
        router.disconnect(firstNextEpoch)
        XCTAssertEqual(router.activeClientCount, 0)
    }

    func testSharedHostRouterAdvertisesClientAndStreamCaps() throws {
        let router = HostMultiClientDisplayRouter(maximumClients: 2, maximumStreamsPerClient: 2)
        let session = makeMultiDisplaySession(
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: true).union([.multiClient]),
            displayRouter: router,
            maximumClients: 2,
            maximumVideoStreamsPerClient: 2
        )
        var hello = clientHello()
        hello.clientHello.capabilities.append(.multiClient)
        var limits = VSResourceLimits()
        limits.maximumClients = 2
        limits.maximumDisplays = 2
        limits.maximumVideoStreams = 2
        hello.clientHello.resourceLimits = limits

        _ = session.handleControl(try hello.serializedData())
        let responses = try controlEnvelopes(session.completeCodecNegotiation())

        guard case .hostHello(let hostHello)? = responses[0].payload,
              case .sessionAccepted(let accepted)? = responses[1].payload else {
            return XCTFail("Expected HostHello + SessionAccepted")
        }
        XCTAssertEqual(hostHello.resourceLimits.maximumClients, 2)
        XCTAssertEqual(hostHello.resourceLimits.maximumDisplays, 2)
        XCTAssertEqual(hostHello.resourceLimits.maximumVideoStreams, 2)
        XCTAssertTrue(hostHello.capabilities.contains(.multiClient))
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.multiClient))
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumClients, 2)
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumVideoStreams, 2)
    }

    func testMultiClientCapabilityRequiresSharedHostRouter() throws {
        let session = makeMultiDisplaySession(maximumClients: 2, maximumVideoStreamsPerClient: 2)
        var hello = clientHello()
        hello.clientHello.capabilities.append(.multiClient)
        var limits = VSResourceLimits()
        limits.maximumClients = 2
        limits.maximumDisplays = 2
        limits.maximumVideoStreams = 2
        hello.clientHello.resourceLimits = limits

        _ = session.handleControl(try hello.serializedData())
        let responses = try controlEnvelopes(session.completeCodecNegotiation())

        guard case .hostHello(let hostHello)? = responses[0].payload,
              case .sessionAccepted(let accepted)? = responses[1].payload else {
            return XCTFail("Expected HostHello + SessionAccepted")
        }
        XCTAssertFalse(hostHello.capabilities.contains(.multiClient))
        XCTAssertEqual(hostHello.resourceLimits.maximumClients, 1)
        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.multiClient))
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumClients, 1)
    }

    func testRuntimeDisplayRebindRejectsDuplicateDisplayAsInvalidState() throws {
        let router = HostMultiClientDisplayRouter(maximumClients: 2, maximumStreamsPerClient: 2)
        let session = makeMultiDisplaySession(
            displayRouter: router,
            maximumClients: 2,
            maximumVideoStreamsPerClient: 2
        )
        var hello = clientHello()
        hello.clientHello.capabilities.append(.multiClient)
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()
        _ = session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(displayRequest(sourceDisplayID: "active-display"))
        ).serializedData())
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
        _ = session.handleControl(try envelope(id: 3, payload: .videoConfigResult(result)).serializedData())
        try router.bind(
            HostDisplayStreamBinding(displayID: "second-display", streamID: 2),
            to: HostClientSessionKey(sessionID: sessionID, epoch: sessionEpoch)
        )

        let actions = session.handleControl(try envelope(
            id: 4,
            payload: .startDisplayRequest(displayRequest(sourceDisplayID: "second-display"))
        ).serializedData())

        XCTAssertEqual(try protocolError(from: actions).code, .invalidState)
        XCTAssertFalse(actions.contains { if case .selectDisplay = $0 { true } else { false } })
        XCTAssertTrue(actions.containsClose)
    }

    func testInputTargetCannotCrossSharedClientRoutes() throws {
        let router = HostMultiClientDisplayRouter(maximumClients: 2, maximumStreamsPerClient: 1)
        let first = try readySession(
            sessionID: Data([0x01]),
            sessionEpoch: 1,
            displayID: "first-display",
            displayRouter: router,
            maximumClients: 2
        )
        let second = try readySession(
            sessionID: Data([0x02]),
            sessionEpoch: 1,
            displayID: "second-display",
            displayRouter: router,
            maximumClients: 2
        )

        var target = VSInputTarget()
        target.displayID = "second-display"
        target.streamID = 1
        var touch = touchEvent()
        touch.target = target
        let rejected = first.handleControl(try envelope(
            id: 4,
            sessionID: Data([0x01]),
            sessionEpoch: 1,
            payload: .touchEvent(touch)
        ).serializedData())

        XCTAssertEqual(try protocolError(from: rejected).code, .invalidState)
        XCTAssertTrue(rejected.containsClose)

        var secondTouch = touchEvent()
        secondTouch.target = target
        XCTAssertTrue(second.handleControl(try envelope(
            id: 4,
            sessionID: Data([0x02]),
            sessionEpoch: 1,
            payload: .touchEvent(secondTouch)
        ).serializedData()).containsTouch)

        let keyRouter = HostMultiClientDisplayRouter(maximumClients: 2, maximumStreamsPerClient: 1)
        let firstKeySession = try readySession(
            sessionID: Data([0x03]),
            sessionEpoch: 1,
            displayID: "first-display",
            displayRouter: keyRouter,
            maximumClients: 2,
            clientCapabilities: [.touch, .multiDisplay, .multiClient, .keyboard, .usbHidModifierByte]
        )
        _ = try readySession(
            sessionID: Data([0x04]),
            sessionEpoch: 1,
            displayID: "second-display",
            displayRouter: keyRouter,
            maximumClients: 2,
            clientCapabilities: [.touch, .multiDisplay, .multiClient, .keyboard, .usbHidModifierByte]
        )

        var key = VSKeyEvent()
        key.inputID = 5
        key.usbHidUsage = 0x04
        key.pressed = true
        key.target = target
        let rejectedKey = firstKeySession.handleControl(try envelope(
            id: 4,
            sessionID: Data([0x03]),
            sessionEpoch: 1,
            payload: .keyEvent(key)
        ).serializedData())

        XCTAssertEqual(try protocolError(from: rejectedKey).code, .invalidState)
        XCTAssertTrue(rejectedKey.containsClose)
    }

    func testClientDisconnectReleasesSharedHostRoute() throws {
        let router = HostMultiClientDisplayRouter(maximumClients: 1, maximumStreamsPerClient: 1)
        let first = try readySession(
            sessionID: Data([0x01]),
            sessionEpoch: 1,
            displayRouter: router
        )
        XCTAssertEqual(router.activeClientCount, 1)
        var notice = VSDisconnectNotice()
        notice.reasonCode = "client_shutdown"
        notice.mayResume = false
        let actions = first.handleControl(try envelope(
            id: 4,
            sessionID: Data([0x01]),
            sessionEpoch: 1,
            payload: .disconnectNotice(notice)
        ).serializedData())

        XCTAssertTrue(actions.containsClose)
        XCTAssertEqual(router.activeClientCount, 0)

        let second = makeSession(
            sessionID: Data([0x02]),
            sessionEpoch: 1,
            displayRouter: router
        )
        _ = second.handleControl(try clientHello().serializedData())
        let responses = try controlEnvelopes(second.completeCodecNegotiation())
        XCTAssertTrue(responses.contains { if case .sessionAccepted = $0.payload { true } else { false } })
        XCTAssertEqual(router.activeClientCount, 1)
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
        XCTAssertEqual(hostHello.capabilities, [.touch, .keyboard, .pointer, .stylus, .clipboard, .colorManagement, .multiDisplay, .hostActions, .managedConfiguration, .clientVideoControl, .stylusExtended, .usbHidModifierByte])
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
        let session = makeSession(managedPolicy: localPolicy, fileTransferAvailable: true)
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .hostActions, .managedConfiguration, .fileTransfer]
        _ = session.handleControl(try hello.serializedData())
        let responses = try controlEnvelopes(session.completeCodecNegotiation())
        XCTAssertEqual(responses.count, 3)
        guard case .sessionAccepted(let accepted)? = responses[1].payload else {
            return XCTFail("Expected SessionAccepted")
        }
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumAudioStreams, 0)
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumClipboardBytes, 1 * 1_024 * 1_024)
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumFileBytes, 2_048)
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumFileChunkBytes, 64 * 1_024)
        guard case .managedPolicyStatus(let localStatus)? = responses[2].payload else {
            return XCTFail("Expected ManagedPolicyStatus")
        }
        XCTAssertTrue(localStatus.managed)
        XCTAssertTrue(localStatus.hostActionsAllowed)
        XCTAssertEqual(localStatus.maximumFileBytes, 2_048)
        XCTAssertEqual(localStatus.allowedHosts, ["host"])
        XCTAssertEqual(Set(localStatus.restrictionResults.map(\.restriction)), ManagedPolicy.requiredRestrictionNames)
        XCTAssertTrue(localStatus.restrictionResults.allSatisfy { $0.source == "managed_configuration" })

        let remote = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: false,
            maximumFileBytes: 4_096,
            allowedHosts: ["host"]
        ).protocolStatus
        let remotePolicyActions = session.handleControl(try envelope(
            id: 2,
            payload: .managedPolicyStatus(remote)
        ).serializedData())
        XCTAssertEqual(remotePolicyActions.count, 1)
        guard case .remoteManagedPolicyChanged(let effectiveRemotePolicy) = remotePolicyActions[0] else {
            return XCTFail("Expected remoteManagedPolicyChanged")
        }
        XCTAssertTrue(effectiveRemotePolicy.managed)
        XCTAssertFalse(effectiveRemotePolicy.hostActionsAllowed)
        XCTAssertEqual(Set(effectiveRemotePolicy.restrictionResults.map(\.source)), ["effective_deny_wins"])
        XCTAssertFalse(try controlEnvelopes(remotePolicyActions).contains { if case .hostActionCatalog = $0.payload { true } else { false } })

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

    func testManagedConfigurationBlocksOrdinaryRequestsUntilRemotePolicyStatus() throws {
        let session = makeSession(fileTransferAvailable: true)
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .managedConfiguration, .fileTransfer, .hostActions]
        _ = session.handleControl(try hello.serializedData())
        let responses = try controlEnvelopes(session.completeCodecNegotiation())
        XCTAssertEqual(responses.count, 3)
        XCTAssertFalse(responses.contains { if case .hostActionCatalog = $0.payload { true } else { false } })
        XCTAssertEqual(session.phase, .awaitingManagedPolicy)

        let listRejected = session.handleControl(try envelope(
            id: 2,
            payload: .listDisplaysRequest(VSListDisplaysRequest())
        ).serializedData())
        XCTAssertEqual(try protocolError(from: listRejected).code, .invalidState)
        XCTAssertTrue(listRejected.containsClose)

        let startRejected = makeSession(fileTransferAvailable: true)
        _ = startRejected.handleControl(try hello.serializedData())
        _ = startRejected.completeCodecNegotiation()
        let startActions = startRejected.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        XCTAssertEqual(try protocolError(from: startActions).code, .invalidState)
        XCTAssertTrue(startActions.containsClose)

        let fileRejected = makeSession(fileTransferAvailable: true)
        _ = fileRejected.handleControl(try hello.serializedData())
        _ = fileRejected.completeCodecNegotiation()
        var offer = VSFileOffer()
        offer.transferID = Data([1, 2, 3, 4])
        offer.fileName = "hello.txt"
        offer.mimeType = "text/plain"
        offer.byteLength = 0
        offer.sha256 = Data(repeating: 0, count: 32)
        let fileActions = fileRejected.handleControl(try envelope(
            id: 2,
            payload: .fileOffer(offer)
        ).serializedData())
        XCTAssertEqual(try protocolError(from: fileActions).code, .invalidState)
        XCTAssertTrue(fileActions.containsClose)
    }

    func testManagedConfigurationAdvertisesHostActionCatalogAfterRemotePolicyStatusAllowsIt() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .managedConfiguration, .hostActions]
        _ = session.handleControl(try hello.serializedData())
        let responses = try controlEnvelopes(session.completeCodecNegotiation())
        XCTAssertEqual(responses.count, 3)
        XCTAssertFalse(responses.contains { if case .hostActionCatalog = $0.payload { true } else { false } })

        let remote = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes,
            allowedHosts: ["host"]
        ).protocolStatus
        let actions = session.handleControl(try envelope(
            id: 2,
            payload: .managedPolicyStatus(remote)
        ).serializedData())
        let catalogEnvelopes = try controlEnvelopes(actions)
        guard case .hostActionCatalog(let catalog)? = catalogEnvelopes.first?.payload else {
            return XCTFail("Expected HostActionCatalog after valid remote policy")
        }
        XCTAssertEqual(catalog.actions.map(\.actionID), ["move-window", "return-windows"])
        XCTAssertEqual(session.phase, .awaitingDisplayStart)
    }

    func testManagedPolicyAllowedHostsFailsClosed() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .managedConfiguration]
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()

        let remote = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes,
            allowedHosts: ["different-host"]
        ).protocolStatus
        let actions = session.handleControl(try envelope(
            id: 2,
            payload: .managedPolicyStatus(remote)
        ).serializedData())

        XCTAssertEqual(try protocolError(from: actions).code, .unauthorized)
        XCTAssertTrue(actions.containsClose)
    }

    func testManagedPolicyStatusWithoutRestrictionResultsFailsClosed() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .managedConfiguration]
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()

        var remote = VSManagedPolicyStatus()
        remote.managed = true
        remote.clipboardAllowed = true
        remote.fileTransferAllowed = true
        remote.audioAllowed = true
        remote.wakeAllowed = true
        remote.customGesturesAllowed = true
        remote.hostActionsAllowed = true
        remote.maximumFileBytes = ManagedPolicy.defaultMaximumFileBytes
        let actions = session.handleControl(try envelope(
            id: 2,
            payload: .managedPolicyStatus(remote)
        ).serializedData())

        let error = try protocolError(from: actions)
        XCTAssertEqual(error.code, .malformedMessage)
        XCTAssertTrue(error.message.contains("restriction_results"))
        XCTAssertTrue(actions.containsClose)
    }

    func testManagedPolicyStatusWithMismatchedRestrictionResultFailsClosed() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .managedConfiguration]
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()

        var remote = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: false,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes,
            allowedHosts: ["host"]
        ).protocolStatus
        remote.restrictionResults[0].allowed = true
        let actions = session.handleControl(try envelope(
            id: 2,
            payload: .managedPolicyStatus(remote)
        ).serializedData())

        let error = try protocolError(from: actions)
        XCTAssertEqual(error.code, .malformedMessage)
        XCTAssertTrue(error.message.contains("restriction_results"))
        XCTAssertTrue(actions.containsClose)
    }

    func testClientColorFallbackRenegotiatesSDRWithoutHDRCapability() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .colorManagement, .multiDisplay]
        hello.clientHello.videoDecodeCapabilities = sdrDecodeCapabilities()
        _ = session.handleControl(try hello.serializedData())
        let responses = try controlEnvelopes(session.completeCodecNegotiation())
        guard case .sessionAccepted(let accepted)? = responses[1].payload else {
            return XCTFail("Expected SessionAccepted")
        }
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.colorManagement))
        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.hdrVideo))

        let startActions = session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        let startResponses = try controlEnvelopes(startActions)
        guard case .videoConfig(let firstConfig)? = startResponses[1].payload else {
            return XCTFail("Expected first VideoConfig")
        }
        assertLegacySDR(firstConfig.colorDescription)

        var result = VSVideoConfigResult()
        result.configEpoch = firstConfig.configEpoch
        result.streamID = firstConfig.streamID
        result.accepted = false
        result.rejectionReason = HostVideoColorNegotiator.unsupportedHDRFallbackReason
        result.selectedColorDescription = HostVideoColorNegotiator.legacySDRColor

        let fallbackActions = session.handleControl(try envelope(
            id: 3,
            payload: .videoConfigResult(result)
        ).serializedData())
        let fallbackResponses = try controlEnvelopes(fallbackActions)
        XCTAssertFalse(fallbackActions.containsConnectionReady)
        guard case .videoConfig(let fallbackConfig)? = fallbackResponses.first?.payload else {
            return XCTFail("Expected fallback VideoConfig")
        }
        XCTAssertEqual(fallbackConfig.configEpoch, firstConfig.configEpoch + 1)
        XCTAssertEqual(fallbackConfig.streamID, firstConfig.streamID)
        assertLegacySDR(fallbackConfig.colorDescription)
    }

    func testClientDecodeProfileRejectionWithoutSelectedColorFailsClosed() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .colorManagement, .multiDisplay]
        hello.clientHello.videoDecodeCapabilities = sdrDecodeCapabilities()
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()

        let startActions = session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        let startResponses = try controlEnvelopes(startActions)
        guard case .videoConfig(let firstConfig)? = startResponses[1].payload else {
            return XCTFail("Expected first VideoConfig")
        }

        var result = VSVideoConfigResult()
        result.configEpoch = firstConfig.configEpoch
        result.streamID = firstConfig.streamID
        result.accepted = false
        result.rejectionReason = HostVideoColorNegotiator.unsupportedHDRFallbackReason

        let failure = try protocolError(from: session.handleControl(try envelope(
            id: 3,
            payload: .videoConfigResult(result)
        ).serializedData()))

        XCTAssertEqual(failure.code, .invalidState)
        XCTAssertEqual(session.phase, .failed)
    }

    func testClientDecodeCapabilitiesSelectSDRCompatibleCodec() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .colorManagement, .multiDisplay]
        hello.clientHello.videoDecodeCapabilities = [sdrDecodeCapability(codec: .h264)]

        let helloActions = session.handleControl(try hello.serializedData())
        XCTAssertTrue(containsCodecNegotiated(helloActions, codec: .h264))
        let responses = try controlEnvelopes(session.completeCodecNegotiation())
        guard case .hostHello(let hostHello)? = responses.first?.payload else {
            return XCTFail("Expected HostHello")
        }
        XCTAssertEqual(hostHello.codecs, [.hevc, .h264])

        let startActions = session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        let startResponses = try controlEnvelopes(startActions)
        guard case .videoConfig(let config)? = startResponses[1].payload else {
            return XCTFail("Expected VideoConfig")
        }
        XCTAssertEqual(config.codec, .h264)
        assertLegacySDR(config.colorDescription)
    }

    func testAV1OfferFallsBackToLocallyEncodableCodec() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .colorManagement, .multiDisplay]
        hello.clientHello.codecs = [.av1, .hevc, .h264]
        hello.clientHello.videoDecodeCapabilities = [
            sdrDecodeCapability(codec: .av1),
            sdrDecodeCapability(codec: .hevc),
            sdrDecodeCapability(codec: .h264),
        ]

        let helloActions = session.handleControl(try hello.serializedData())
        XCTAssertTrue(containsCodecNegotiated(helloActions, codec: .hevc))
    }

    func testAV1OnlyOfferFailsClosedUntilHostEncoderExists() throws {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .colorManagement, .multiDisplay]
        hello.clientHello.codecs = [.av1]
        hello.clientHello.videoDecodeCapabilities = [sdrDecodeCapability(codec: .av1)]

        let error = try protocolError(from: session.handleControl(try hello.serializedData()))
        XCTAssertEqual(error.code, .unsupportedCapability)
        XCTAssertEqual(error.message, "Host and client have no common locally encodable SDR video codec.")
    }

    func testHDRColorConfigRequiresHostAndClientCapability() throws {
        let session = makeSession(
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true,
                hdrVideoAvailable: true
            ),
            preferredColorDescription: hdrColor()
        )
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .colorManagement, .multiDisplay, .hdrVideo]
        hello.clientHello.videoDecodeCapabilities = [hdrDecodeCapability(codec: .hevc)]

        let helloActions = session.handleControl(try hello.serializedData())
        XCTAssertTrue(containsCodecNegotiated(helloActions, codec: .hevc))
        let helloResponses = try controlEnvelopes(session.completeCodecNegotiation())
        guard case .sessionAccepted(let accepted)? = helloResponses[1].payload else {
            return XCTFail("Expected SessionAccepted")
        }
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.hdrVideo))

        let startResponses = try controlEnvelopes(session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData()))
        guard case .videoConfig(let config)? = startResponses[1].payload else {
            return XCTFail("Expected VideoConfig")
        }
        XCTAssertEqual(config.configEpoch, 1)
        XCTAssertEqual(config.colorDescription, hdrColor())
    }

    func testHDRPreferredColorFallsBackBeforeAdvertisingConfigWhenClientLacksHDR() throws {
        let session = makeSession(
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true,
                hdrVideoAvailable: true
            ),
            preferredColorDescription: hdrColor()
        )
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .colorManagement, .multiDisplay]
        hello.clientHello.videoDecodeCapabilities = sdrDecodeCapabilities()

        _ = session.handleControl(try hello.serializedData())
        let helloResponses = try controlEnvelopes(session.completeCodecNegotiation())
        guard case .sessionAccepted(let accepted)? = helloResponses[1].payload else {
            return XCTFail("Expected SessionAccepted")
        }
        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.hdrVideo))

        let startResponses = try controlEnvelopes(session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData()))
        guard case .videoConfig(let config)? = startResponses[1].payload else {
            return XCTFail("Expected VideoConfig")
        }
        XCTAssertEqual(config.configEpoch, 1)
        assertLegacySDR(config.colorDescription)
    }

    func testHDRPreferredColorFallsBackBeforeAdvertisingConfigWhenDecodeProfileIsSDROnly() throws {
        let session = makeSession(
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true,
                hdrVideoAvailable: true
            ),
            preferredColorDescription: hdrColor()
        )
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .colorManagement, .multiDisplay, .hdrVideo]
        hello.clientHello.videoDecodeCapabilities = sdrDecodeCapabilities()

        _ = session.handleControl(try hello.serializedData())
        let helloResponses = try controlEnvelopes(session.completeCodecNegotiation())
        guard case .sessionAccepted(let accepted)? = helloResponses[1].payload else {
            return XCTFail("Expected SessionAccepted")
        }
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.hdrVideo))

        let startResponses = try controlEnvelopes(session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData()))
        guard case .videoConfig(let config)? = startResponses[1].payload else {
            return XCTFail("Expected VideoConfig")
        }
        XCTAssertEqual(config.configEpoch, 1)
        assertLegacySDR(config.colorDescription)
    }

    func testHDRClientRejectionRenegotiatesSDRWithNewMediaEpoch() throws {
        let session = makeSession(
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true,
                hdrVideoAvailable: true
            ),
            preferredColorDescription: hdrColor()
        )
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .colorManagement, .multiDisplay, .hdrVideo]
        hello.clientHello.videoDecodeCapabilities = [hdrDecodeCapability(codec: .hevc)]

        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()
        let startResponses = try controlEnvelopes(session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData()))
        guard case .videoConfig(let firstConfig)? = startResponses[1].payload else {
            return XCTFail("Expected first VideoConfig")
        }
        XCTAssertEqual(firstConfig.colorDescription, hdrColor())

        var rejection = VSVideoConfigResult()
        rejection.configEpoch = firstConfig.configEpoch
        rejection.streamID = firstConfig.streamID
        rejection.accepted = false
        rejection.rejectionReason = HostVideoColorNegotiator.unsupportedHDRFallbackReason
        rejection.selectedColorDescription = HostVideoColorNegotiator.legacySDRColor

        let fallbackResponses = try controlEnvelopes(session.handleControl(try envelope(
            id: 3,
            payload: .videoConfigResult(rejection)
        ).serializedData()))
        guard case .videoConfig(let fallbackConfig)? = fallbackResponses.first?.payload else {
            return XCTFail("Expected fallback VideoConfig")
        }
        XCTAssertEqual(fallbackConfig.configEpoch, firstConfig.configEpoch + 1)
        assertLegacySDR(fallbackConfig.colorDescription)

        var accepted = VSVideoConfigResult()
        accepted.configEpoch = fallbackConfig.configEpoch
        accepted.streamID = fallbackConfig.streamID
        accepted.accepted = true
        _ = session.handleControl(try envelope(
            id: 4,
            payload: .videoConfigResult(accepted)
        ).serializedData())

        let media = try XCTUnwrap(session.makeMediaFrame(
            payload: Data([0, 0, 0, 1, 0x26]),
            timestamp: 99,
            keyframe: true
        ))
        let (header, _) = try decodeMedia(media)
        XCTAssertEqual(header.configEpoch, fallbackConfig.configEpoch)
        XCTAssertEqual(header.streamID, fallbackConfig.streamID)
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

        var streamOnlyTarget = VSInputTarget()
        streamOnlyTarget.streamID = 1
        var streamOnlyTargetTouch = touchEvent()
        streamOnlyTargetTouch.target = streamOnlyTarget
        XCTAssertTrue(session.handleControl(
            try envelope(id: 6, payload: .touchEvent(streamOnlyTargetTouch)).serializedData()
        ).containsTouch)

        var displayOnlyTarget = VSInputTarget()
        displayOnlyTarget.displayID = "active-display"
        var displayOnlyTargetTouch = touchEvent()
        displayOnlyTargetTouch.target = displayOnlyTarget
        XCTAssertTrue(session.handleControl(
            try envelope(id: 7, payload: .touchEvent(displayOnlyTargetTouch)).serializedData()
        ).containsTouch)

        var wrongDisplayTarget = VSInputTarget()
        wrongDisplayTarget.displayID = "wrong-display"
        var wrongDisplayTargetTouch = touchEvent()
        wrongDisplayTargetTouch.target = wrongDisplayTarget
        let rejectedDisplay = session.handleControl(
            try envelope(id: 8, payload: .touchEvent(wrongDisplayTargetTouch)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: rejectedDisplay).code, .invalidState)
        XCTAssertTrue(rejectedDisplay.containsClose)

        var wrongTarget = activeTarget
        wrongTarget.streamID = 2
        var wrongTargetTouch = touchEvent()
        wrongTargetTouch.target = wrongTarget
        let rejected = session.handleControl(
            try envelope(id: 9, payload: .touchEvent(wrongTargetTouch)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: rejected).code, .invalidState)
        XCTAssertTrue(rejected.containsClose)
    }

    func testPointerAndScrollTargetsAcceptActiveOrEmptyAndRejectWrongTarget() throws {
        let emptyTargetPointer = try readyPointerSession()
        var pointer = pointerEvent()
        pointer.target = VSInputTarget()
        XCTAssertTrue(emptyTargetPointer.handleControl(
            try envelope(id: 4, payload: .pointerEvent(pointer)).serializedData()
        ).containsPointer)

        let activeTargetPointer = try readyPointerSession()
        var activeTarget = VSInputTarget()
        activeTarget.displayID = "active-display"
        activeTarget.streamID = 1
        pointer.target = activeTarget
        XCTAssertTrue(activeTargetPointer.handleControl(
            try envelope(id: 4, payload: .pointerEvent(pointer)).serializedData()
        ).containsPointer)

        let wrongPointerSession = try readyPointerSession()
        var wrongTarget = activeTarget
        wrongTarget.streamID = 2
        pointer.target = wrongTarget
        let rejectedPointer = wrongPointerSession.handleControl(
            try envelope(id: 4, payload: .pointerEvent(pointer)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: rejectedPointer).code, .invalidState)
        XCTAssertTrue(rejectedPointer.containsClose)

        let emptyTargetScroll = try readyPointerSession()
        var scroll = scrollEvent()
        scroll.target = VSInputTarget()
        XCTAssertTrue(emptyTargetScroll.handleControl(
            try envelope(id: 4, payload: .scrollEvent(scroll)).serializedData()
        ).containsScroll)

        let activeTargetScroll = try readyPointerSession()
        scroll.target = activeTarget
        XCTAssertTrue(activeTargetScroll.handleControl(
            try envelope(id: 4, payload: .scrollEvent(scroll)).serializedData()
        ).containsScroll)

        let wrongScrollSession = try readyPointerSession()
        scroll.target = wrongTarget
        let rejectedScroll = wrongScrollSession.handleControl(
            try envelope(id: 4, payload: .scrollEvent(scroll)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: rejectedScroll).code, .invalidState)
        XCTAssertTrue(rejectedScroll.containsClose)
    }

    func testKeyTargetAcceptsActiveOrEmptyAndRejectsWrongTarget() throws {
        let emptyTargetSession = try readyKeyboardSession(standardModifierByte: true)
        var key = keyEvent(inputID: 4)
        key.target = VSInputTarget()
        XCTAssertTrue(emptyTargetSession.handleControl(
            try envelope(id: 4, payload: .keyEvent(key)).serializedData()
        ).containsKey)

        var activeTarget = VSInputTarget()
        activeTarget.displayID = "active-display"
        activeTarget.streamID = 1
        let activeTargetSession = try readyKeyboardSession(standardModifierByte: true)
        key = keyEvent(inputID: 4)
        key.target = activeTarget
        XCTAssertTrue(activeTargetSession.handleControl(
            try envelope(id: 4, payload: .keyEvent(key)).serializedData()
        ).containsKey)

        var wrongTarget = activeTarget
        wrongTarget.streamID = 2
        let wrongTargetSession = try readyKeyboardSession(standardModifierByte: true)
        key = keyEvent(inputID: 4)
        key.target = wrongTarget
        let rejected = wrongTargetSession.handleControl(
            try envelope(id: 4, payload: .keyEvent(key)).serializedData()
        )
        XCTAssertEqual(try protocolError(from: rejected).code, .invalidState)
        XCTAssertTrue(rejected.containsClose)
    }

    func testPointerRejectsUnsupportedButtonMaskBits() throws {
        let session = try readyPointerSession()
        var pointer = pointerEvent()
        pointer.buttonMask = 0b100

        let rejected = session.handleControl(
            try envelope(id: 4, payload: .pointerEvent(pointer)).serializedData()
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

    func testWakeHostRequestRequiresNegotiatedCapabilityStreamingAndHostMatch() throws {
        let ungated = try readySession()
        var request = wakeHostRequest(hostID: "host")
        XCTAssertEqual(
            try protocolError(from: ungated.handleControl(
                try envelope(id: 4, payload: .wakeHostRequest(request)).serializedData()
            )).code,
            .unsupportedCapability
        )

        let preStream = makeWakeHostSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .wakeHost]
        _ = preStream.handleControl(try hello.serializedData())
        _ = preStream.completeCodecNegotiation()
        XCTAssertEqual(
            try protocolError(from: preStream.handleControl(
                try envelope(id: 2, payload: .wakeHostRequest(request)).serializedData()
            )).code,
            .invalidState
        )

        let session = try readyWakeHostSession()
        let actions = session.handleControl(try envelope(id: 4, payload: .wakeHostRequest(request)).serializedData())
        XCTAssertTrue(actions.contains { action in
            if case .wakeHost(let context, let correlationID) = action {
                return context.requestID == Data([0x31])
                    && context.targetMACAddress == Data([1, 2, 3, 4, 5, 6])
                    && context.hostID == "host"
                    && correlationID == 4
            }
            return false
        })

        request.hostID = ""
        let missingHostSession = try readyWakeHostSession()
        XCTAssertEqual(
            try protocolError(from: missingHostSession.handleControl(
                try envelope(id: 5, payload: .wakeHostRequest(request)).serializedData()
            )).code,
            .invalidState
        )

        request.hostID = "other-host"
        let mismatchSession = try readyWakeHostSession()
        XCTAssertEqual(
            try protocolError(from: mismatchSession.handleControl(
                try envelope(id: 6, payload: .wakeHostRequest(request)).serializedData()
            )).code,
            .invalidState
        )

        request.hostID = "host"
        request.deviceID = ""
        let missingDeviceSession = try readyWakeHostSession()
        XCTAssertEqual(
            try protocolError(from: missingDeviceSession.handleControl(
                try envelope(id: 7, payload: .wakeHostRequest(request)).serializedData()
            )).code,
            .invalidState
        )

        request.deviceID = "other-device"
        let deviceMismatchSession = try readyWakeHostSession()
        XCTAssertEqual(
            try protocolError(from: deviceMismatchSession.handleControl(
                try envelope(id: 8, payload: .wakeHostRequest(request)).serializedData()
            )).code,
            .invalidState
        )
    }

    func testWakeHostCompletionEchoesRequestAndCorrelation() throws {
        let session = try readyWakeHostSession()
        _ = session.handleControl(try envelope(
            id: 4,
            payload: .wakeHostRequest(wakeHostRequest())
        ).serializedData())
        let responses = try controlEnvelopes(session.completeWakeHost(
            requestID: Data([0x31]),
            accepted: false,
            rejectionReason: "wake_host_policy_denied"
        ))

        XCTAssertEqual(responses.count, 1)
        XCTAssertEqual(responses.first?.correlationID, 4)
        guard case .wakeHostResult(let result)? = responses.first?.payload else {
            return XCTFail("Expected WakeHostResult")
        }
        XCTAssertEqual(result.requestID, Data([0x31]))
        XCTAssertFalse(result.accepted)
        XCTAssertEqual(result.rejectionReason, "wake_host_policy_denied")
    }

    func testWakeHostCompletionDefaultsRejectedReason() throws {
        let session = try readyWakeHostSession()
        _ = session.handleControl(try envelope(
            id: 4,
            payload: .wakeHostRequest(wakeHostRequest())
        ).serializedData())
        let responses = try controlEnvelopes(session.completeWakeHost(
            requestID: Data([0x31]),
            accepted: false,
            rejectionReason: ""
        ))

        guard case .wakeHostResult(let result)? = responses.first?.payload else {
            return XCTFail("Expected WakeHostResult")
        }
        XCTAssertEqual(result.rejectionReason, "wake_host_rejected")
    }

    func testWakeHostCompletionConsumesTrackedRequestAndAcceptedReasonIsEmpty() throws {
        let session = try readyWakeHostSession()
        _ = session.handleControl(try envelope(
            id: 4,
            payload: .wakeHostRequest(wakeHostRequest())
        ).serializedData())

        let responses = try controlEnvelopes(session.completeWakeHost(
            requestID: Data([0x31]),
            accepted: true,
            rejectionReason: "ignored"
        ))

        XCTAssertEqual(responses.count, 1)
        XCTAssertEqual(responses.first?.correlationID, 4)
        guard case .wakeHostResult(let result)? = responses.first?.payload else {
            return XCTFail("Expected WakeHostResult")
        }
        XCTAssertTrue(result.accepted)
        XCTAssertEqual(result.rejectionReason, "")
        XCTAssertTrue(session.completeWakeHost(
            requestID: Data([0x31]),
            accepted: true,
            rejectionReason: ""
        ).isEmpty)
    }

    func testWakeHostCapabilityAdvertisementHonorsManagedPolicy() {
        let policy = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: false,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes,
            allowedHosts: []
        )
        let capabilities = ProtocolV1SessionConfiguration.productionHostCapabilities(
            touchEnabled: true,
            managedPolicy: policy,
            wakeHostAvailable: true
        )

        XCTAssertFalse(capabilities.contains(.wakeHost))
    }

    func testAudioNegotiationRequestsConfigurationAfterVideoReady() throws {
        let session = makeAudioSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .audio]
        hello.clientHello.resourceLimits.maximumAudioStreams = 1

        _ = session.handleControl(try hello.serializedData())
        let responses = try controlEnvelopes(session.completeCodecNegotiation())
        guard case .hostHello(let hostHello)? = responses[0].payload,
              case .sessionAccepted(let accepted)? = responses[1].payload else {
            return XCTFail("Expected HostHello + SessionAccepted")
        }
        XCTAssertTrue(hostHello.capabilities.contains(.audio))
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.audio))
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumAudioStreams, 1)

        _ = session.handleControl(try envelope(
            id: 2,
            payload: .listDisplaysRequest(VSListDisplaysRequest())
        ).serializedData())
        let startActions = session.handleControl(try envelope(
            id: 3,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        guard case .videoConfig(let videoConfig)? = try controlEnvelopes(startActions).last?.payload else {
            return XCTFail("Expected VideoConfig")
        }

        var videoResult = VSVideoConfigResult()
        videoResult.configEpoch = videoConfig.configEpoch
        videoResult.streamID = videoConfig.streamID
        videoResult.accepted = true
        let readyActions = session.handleControl(try envelope(
            id: 4,
            payload: .videoConfigResult(videoResult)
        ).serializedData())

        let readyEnvelopes = try controlEnvelopes(readyActions)
        guard case .audioConfig(let audioConfig)? = readyEnvelopes.first?.payload else {
            return XCTFail("Expected AudioConfig before media ready actions")
        }
        XCTAssertEqual(audioConfig.streamID, 2)
        XCTAssertEqual(audioConfig.configEpoch, 1)
        XCTAssertEqual(audioConfig.codec, .pcmS16Le)
        XCTAssertEqual(audioConfig.sampleRateHz, 48_000)
        XCTAssertEqual(audioConfig.channelCount, 2)
        XCTAssertEqual(audioConfig.framesPerPacket, 480)
        XCTAssertTrue(readyActions.containsConnectionReady)
    }

    func testAudioConfigResultStartsAudioAndRejectsStaleEpochs() throws {
        let session = try readyAudioPendingSession()

        var accepted = VSAudioConfigResult()
        accepted.streamID = 2
        accepted.configEpoch = 1
        accepted.accepted = true
        let acceptedActions = session.handleControl(try envelope(
            id: 5,
            payload: .audioConfigResult(accepted)
        ).serializedData())

        guard case .startAudio(let config)? = acceptedActions.first else {
            return XCTFail("Expected startAudio")
        }
        XCTAssertEqual(config.streamID, 2)
        XCTAssertEqual(config.configEpoch, 1)

        let stale = try readyAudioPendingSession()
        var staleResult = VSAudioConfigResult()
        staleResult.streamID = 2
        staleResult.configEpoch = 2
        staleResult.accepted = true
        let staleActions = stale.handleControl(try envelope(
            id: 5,
            payload: .audioConfigResult(staleResult)
        ).serializedData())
        XCTAssertEqual(try protocolError(from: staleActions).code, .invalidState)
        XCTAssertTrue(staleActions.containsClose)
    }

    func testRejectedAudioConfigDoesNotRepeatOnVideoRenegotiation() throws {
        let session = try readyAudioPendingSession()

        var rejected = VSAudioConfigResult()
        rejected.streamID = 2
        rejected.configEpoch = 1
        rejected.accepted = false
        rejected.rejectionReason = "audio_track_create_failed"
        let rejectedActions = session.handleControl(try envelope(
            id: 5,
            payload: .audioConfigResult(rejected)
        ).serializedData())
        XCTAssertTrue(rejectedActions.containsAudioStop(reason: "audio_track_create_failed"))

        let reconfigure = session.handleControl(try envelope(
            id: 6,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        guard case .videoConfig(let videoConfig)? = try controlEnvelopes(reconfigure).last?.payload else {
            return XCTFail("Expected VideoConfig")
        }
        var videoResult = VSVideoConfigResult()
        videoResult.configEpoch = videoConfig.configEpoch
        videoResult.streamID = videoConfig.streamID
        videoResult.accepted = true
        let readyAgain = session.handleControl(try envelope(
            id: 7,
            payload: .videoConfigResult(videoResult)
        ).serializedData())
        XCTAssertFalse(try controlEnvelopes(readyAgain).contains {
            if case .audioConfig = $0.payload { return true }
            return false
        })
    }

    func testManagedPolicyDenyStopsConfiguredAudio() throws {
        let session = try readyAudioStreamingSession(managed: true)

        let remote = ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: false,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes,
            allowedHosts: ["host"]
        ).protocolStatus
        let actions = session.handleControl(try envelope(
            id: 6,
            payload: .managedPolicyStatus(remote)
        ).serializedData())

        XCTAssertTrue(actions.containsAudioStop(reason: "managed_policy_audio_denied"))
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

    func testPeripheralEventRequiresNegotiatedCapability() throws {
        let session = try readySession()
        let actions = session.handleControl(
            try envelope(id: 4, payload: .peripheralEvent(peripheralEvent())).serializedData()
        )
        XCTAssertEqual(try protocolError(from: actions).code, .unsupportedCapability)
    }

    func testPeripheralEventFailsClosedAfterNegotiation() throws {
        let session = try readyPeripheralSession()
        let actions = session.handleControl(
            try envelope(id: 4, payload: .peripheralEvent(peripheralEvent())).serializedData()
        )

        XCTAssertFalse(actions.contains { action in
            if case .touch = action { return true }
            if case .stylus = action { return true }
            if case .pointer = action { return true }
            if case .scroll = action { return true }
            if case .key = action { return true }
            if case .controller = action { return true }
            return false
        })
        let acknowledgementEnvelope = try XCTUnwrap(controlEnvelopes(actions).first)
        guard case .inputAck(let acknowledgement)? = acknowledgementEnvelope.payload else {
            return XCTFail("Expected PeripheralEvent InputAck")
        }
        XCTAssertEqual(acknowledgement.inputID, 1)
        XCTAssertFalse(acknowledgement.accepted)
        XCTAssertEqual(acknowledgement.rejectionReason, "unsupported_peripheral_kind")
        XCTAssertEqual(acknowledgementEnvelope.correlationID, 4)
        XCTAssertEqual(acknowledgementEnvelope.sessionID, sessionID)
        XCTAssertEqual(acknowledgementEnvelope.sessionEpoch, sessionEpoch)
    }

    func testPeripheralEventRejectsOversizedPayloadBeforePlaceholderAck() throws {
        let session = try readyPeripheralSession()
        var event = peripheralEvent()
        event.payload = Data(repeating: 0xAA, count: 64 * 1_024 + 1)
        let actions = session.handleControl(
            try envelope(id: 4, payload: .peripheralEvent(event)).serializedData()
        )

        XCTAssertEqual(try protocolError(from: actions).code, .invalidState)
    }

    func testPeripheralEventRejectsOversizedKindBeforePlaceholderAck() throws {
        let session = try readyPeripheralSession()
        var event = peripheralEvent()
        event.peripheralKind = String(repeating: "a", count: 129)
        let actions = session.handleControl(
            try envelope(id: 4, payload: .peripheralEvent(event)).serializedData()
        )

        XCTAssertEqual(try protocolError(from: actions).code, .invalidState)
    }

    func testPeripheralEventRejectsInactiveTargetBeforePlaceholderAck() throws {
        let session = try readyPeripheralSession()
        var target = VSInputTarget()
        target.displayID = "other-display"
        target.streamID = 1
        var event = peripheralEvent()
        event.target = target
        let actions = session.handleControl(
            try envelope(id: 4, payload: .peripheralEvent(event)).serializedData()
        )

        XCTAssertEqual(try protocolError(from: actions).code, .invalidState)
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

    private func makeSession(
        managedPolicy: ManagedPolicy = .unmanaged,
        fileTransferAvailable: Bool = false,
        hostCapabilities: Set<VSCapability>? = nil,
        preferredColorDescription: VSColorDescription = HostVideoColorNegotiator.legacySDRColor,
        sessionID: Data? = nil,
        sessionEpoch: UInt64? = nil,
        displayID: String = "active-display",
        displayRouter: HostMultiClientDisplayRouter? = nil,
        maximumClients: Int = 1,
        maximumVideoStreamsPerClient: Int = 1
    ) -> ProtocolV1SessionCoordinator {
        var configuration = ProtocolV1SessionConfiguration(
            sessionID: sessionID ?? self.sessionID,
            sessionEpoch: sessionEpoch ?? self.sessionEpoch,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 90,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: hostCapabilities ?? ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true,
                managedPolicy: managedPolicy,
                fileTransferAllowed: fileTransferAvailable && managedPolicy.fileTransferAllowed,
                maximumClients: maximumClients
            ),
            requiredClientCapabilities: [.touch],
            supportedCodecs: [.hevc, .h264],
            hostID: "host",
            hostName: "Mac",
            displayID: displayID,
            displayName: "Display",
            displayIsVirtual: true
        )
        configuration.managedPolicy = managedPolicy
        configuration.preferredColorDescription = preferredColorDescription
        configuration.maximumClients = maximumClients
        configuration.maximumVideoStreamsPerClient = maximumVideoStreamsPerClient
        configuration.displayRouter = displayRouter
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

    private func makePeripheralSession() -> ProtocolV1SessionCoordinator {
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
                peripheralInputFrameworkAvailable: true
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

    private func makeWakeHostSession() -> ProtocolV1SessionCoordinator {
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
                wakeHostAvailable: true
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

    private func makeAudioSession(managedPolicy: ManagedPolicy = .unmanaged) -> ProtocolV1SessionCoordinator {
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
                managedPolicy: managedPolicy,
                audioCaptureAvailable: true
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

    private func makeMultiDisplaySession(
        hostCapabilities: Set<VSCapability>? = nil,
        displayRouter: HostMultiClientDisplayRouter? = nil,
        maximumClients: Int = 1,
        maximumVideoStreamsPerClient: Int = 1
    ) -> ProtocolV1SessionCoordinator {
        var configuration = ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 90,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: hostCapabilities ?? ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true,
                maximumClients: maximumClients
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
        )
        configuration.maximumClients = maximumClients
        configuration.maximumVideoStreamsPerClient = maximumVideoStreamsPerClient
        configuration.displayRouter = displayRouter
        return ProtocolV1SessionCoordinator(configuration: configuration)
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

    private func sdrDecodeCapabilities() -> [VSVideoDecodeCapability] {
        [.hevc, .h264].map { codec in
            sdrDecodeCapability(codec: codec)
        }
    }

    private func sdrDecodeCapability(codec: VSCodec) -> VSVideoDecodeCapability {
        var capability = VSVideoDecodeCapability()
        capability.codec = codec
        capability.maximumWidth = 3_840
        capability.maximumHeight = 2_160
        capability.maximumFramesPerSecond = 120
        capability.bitDepths = [8]
        capability.transferFunctions = [.bt709, .srgb]
        return capability
    }

    private func hdrDecodeCapability(codec: VSCodec) -> VSVideoDecodeCapability {
        var capability = sdrDecodeCapability(codec: codec)
        capability.bitDepths = [8, 10]
        capability.transferFunctions = [.bt709, .srgb, .pq]
        return capability
    }

    private func hdrColor() -> VSColorDescription {
        var color = VSColorDescription()
        color.primaries = .bt2020
        color.transferFunction = .pq
        color.matrixCoefficients = .bt2020NonConstant
        color.bitDepth = 10
        return color
    }

    private func containsCodecNegotiated(
        _ actions: [ProtocolV1SessionAction],
        codec: StreamCodec
    ) -> Bool {
        actions.contains { action in
            if case .codecNegotiated(codec) = action { return true }
            return false
        }
    }

    private func assertLegacySDR(
        _ color: VSColorDescription,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(color.primaries, .bt709, file: file, line: line)
        XCTAssertEqual(color.transferFunction, .bt709, file: file, line: line)
        XCTAssertEqual(color.matrixCoefficients, .bt709, file: file, line: line)
        XCTAssertFalse(color.fullRange, file: file, line: line)
        XCTAssertEqual(color.bitDepth, 8, file: file, line: line)
    }

    private func envelope(
        id: UInt64,
        sessionID: Data? = nil,
        sessionEpoch: UInt64? = nil,
        payload: VSEnvelope.OneOf_Payload
    ) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = id
        envelope.sessionID = sessionID ?? self.sessionID
        envelope.sessionEpoch = sessionEpoch ?? self.sessionEpoch
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

    private func wakeHostRequest(hostID: String = "host") -> VSWakeHostRequest {
        var request = VSWakeHostRequest()
        request.requestID = Data([0x31])
        request.targetMacAddress = Data([1, 2, 3, 4, 5, 6])
        request.hostID = hostID
        request.deviceID = "device"
        return request
    }

    private func peripheralEvent() -> VSPeripheralEvent {
        var target = VSInputTarget()
        target.displayID = "active-display"
        target.streamID = 1
        var event = VSPeripheralEvent()
        event.inputID = 1
        event.peripheralKind = "generic-placeholder"
        event.payload = Data([0x01, 0x02])
        event.target = target
        return event
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

    private func pointerEvent() -> VSPointerEvent {
        var point = VSNormalizedPoint()
        point.x = 0.25
        point.y = 0.75
        var pointer = VSPointerEvent()
        pointer.inputID = 2
        pointer.phase = .changed
        pointer.position = point
        pointer.buttonMask = 0
        return pointer
    }

    private func scrollEvent() -> VSScrollEvent {
        var scroll = VSScrollEvent()
        scroll.inputID = 3
        scroll.deltaX = 1
        scroll.deltaY = -2
        return scroll
    }

    private func keyEvent(inputID: UInt64) -> VSKeyEvent {
        var key = VSKeyEvent()
        key.inputID = inputID
        key.usbHidUsage = 0x04
        key.pressed = true
        key.modifierMask = 0
        return key
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

    private func readySession(
        sessionID: Data? = nil,
        sessionEpoch: UInt64? = nil,
        displayID: String = "active-display",
        displayRouter: HostMultiClientDisplayRouter? = nil,
        maximumClients: Int = 1,
        maximumVideoStreamsPerClient: Int = 1,
        clientCapabilities: [VSCapability] = [.touch, .multiDisplay]
    ) throws -> ProtocolV1SessionCoordinator {
        let resolvedSessionID = sessionID ?? self.sessionID
        let resolvedSessionEpoch = sessionEpoch ?? self.sessionEpoch
        let session = makeSession(
            sessionID: resolvedSessionID,
            sessionEpoch: resolvedSessionEpoch,
            displayID: displayID,
            displayRouter: displayRouter,
            maximumClients: maximumClients,
            maximumVideoStreamsPerClient: maximumVideoStreamsPerClient
        )
        var hello = clientHello()
        hello.clientHello.capabilities = clientCapabilities
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()
        _ = session.handleControl(try envelope(
            id: 2,
            sessionID: resolvedSessionID,
            sessionEpoch: resolvedSessionEpoch,
            payload: .startDisplayRequest(displayRequest(sourceDisplayID: displayID))
        ).serializedData())
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
        _ = session.handleControl(try envelope(
            id: 3,
            sessionID: resolvedSessionID,
            sessionEpoch: resolvedSessionEpoch,
            payload: .videoConfigResult(result)
        ).serializedData())
        return session
    }

    private func readyAudioPendingSession(managed: Bool = false) throws -> ProtocolV1SessionCoordinator {
        let policy = managed ? ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes,
            allowedHosts: ["host"]
        ) : .unmanaged
        let session = makeAudioSession(managedPolicy: policy)
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .audio]
        if managed { hello.clientHello.capabilities.append(.managedConfiguration) }
        hello.clientHello.resourceLimits.maximumAudioStreams = 1
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()
        var nextID: UInt64 = 2
        if managed {
            _ = session.handleControl(try envelope(
                id: nextID,
                payload: .managedPolicyStatus(policy.protocolStatus)
            ).serializedData())
            nextID += 1
        }
        _ = session.handleControl(try envelope(
            id: nextID,
            payload: .startDisplayRequest(existingDisplayRequest())
        ).serializedData())
        nextID += 1
        var videoResult = VSVideoConfigResult()
        videoResult.configEpoch = 1
        videoResult.streamID = 1
        videoResult.accepted = true
        _ = session.handleControl(try envelope(id: nextID, payload: .videoConfigResult(videoResult)).serializedData())
        return session
    }

    private func readyAudioStreamingSession(managed: Bool = false) throws -> ProtocolV1SessionCoordinator {
        let session = try readyAudioPendingSession(managed: managed)
        var audioResult = VSAudioConfigResult()
        audioResult.streamID = 2
        audioResult.configEpoch = 1
        audioResult.accepted = true
        _ = session.handleControl(try envelope(id: 5, payload: .audioConfigResult(audioResult)).serializedData())
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

    private func readyPointerSession() throws -> ProtocolV1SessionCoordinator {
        let session = makeSession()
        var hello = clientHello()
        hello.clientHello.capabilities.append(.pointer)
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

    private func readyWakeHostSession() throws -> ProtocolV1SessionCoordinator {
        let session = makeWakeHostSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .wakeHost]
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

    private func readyPeripheralSession() throws -> ProtocolV1SessionCoordinator {
        let session = makePeripheralSession()
        var hello = clientHello()
        hello.clientHello.capabilities = [.touch, .multiDisplay, .peripheralInputFramework]
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
    var containsKey: Bool { contains { if case .key = $0 { true } else { false } } }
    var containsPointer: Bool { contains { if case .pointer = $0 { true } else { false } } }
    var containsScroll: Bool { contains { if case .scroll = $0 { true } else { false } } }
    var containsHeartbeat: Bool { contains { if case .heartbeat = $0 { true } else { false } } }
    var containsClose: Bool { contains { if case .close = $0 { true } else { false } } }
    func containsAudioStop(reason expectedReason: String) -> Bool {
        contains {
            if case .stopAudio(let reason) = $0 { return reason == expectedReason }
            return false
        }
    }
    var containsPeerErrorAndClose: Bool {
        contains { if case .peerError = $0 { true } else { false } } &&
            contains { if case .close = $0 { true } else { false } }
    }
}
