import CryptoKit
import Foundation
import Network
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class StreamingServerLifecycleTests: XCTestCase {
    private let queue = DispatchQueue(
        label: "StreamingServerLifecycleTests",
        qos: .userInitiated
    )

    func testSecondListenerReportsPortConflict() throws {
        let first = StreamingServer(port: 0)
        defer {
            first.stop()
        }

        try first.start()
        let port = try XCTUnwrap(first.listeningPort)
        let second = StreamingServer(port: port)
        defer { second.stop() }

        XCTAssertThrowsError(try second.start(timeout: 1))
    }

    func testAppliedVideoRatesSeedTheNextProtocolSession() {
        let server = StreamingServer(port: 0)
        server.setProtocolV1VideoConfiguration(
            framesPerSecond: 60,
            bitrateKbps: 13_000,
            displayID: "display",
            displayName: "Display",
            isVirtual: false
        )

        server.setProtocolV1VideoRates(
            framesPerSecond: 30,
            bitrateKbps: 5_000
        )

        var snapshot = server.protocolV1VideoConfigurationForSelfTest()
        XCTAssertEqual(snapshot.bitrateKbps, 5_000)
        XCTAssertEqual(snapshot.framesPerSecond, 30)

        server.setProtocolV1VideoRates(
            framesPerSecond: 120,
            bitrateKbps: 95_000
        )

        snapshot = server.protocolV1VideoConfigurationForSelfTest()
        XCTAssertEqual(snapshot.bitrateKbps, 95_000)
        XCTAssertEqual(snapshot.framesPerSecond, 120)

        server.completeProtocolV1VideoPreferences(
            token: 2,
            accepted: true,
            appliedBitrateKbps: 5_000,
            appliedFramesPerSecond: 30
        )
        waitForNetworkQueue(server)

        snapshot = server.protocolV1VideoConfigurationForSelfTest()
        XCTAssertEqual(snapshot.bitrateKbps, 95_000)
        XCTAssertEqual(snapshot.framesPerSecond, 120)
    }

    func testFragmentedWirelessHandshakeIsAccepted() throws {
        let token = Data(repeating: 0xA5, count: 32)
        let (server, port) = try startServer(mode: .wireless(authToken: token))
        defer { server.stop() }

        let paired = expectation(description: "fragmented handshake accepted")
        server.onWirelessClientPaired = { name, _ in
            XCTAssertEqual(name, "Test tablet")
            paired.fulfill()
        }
        let client = try readyClient(port: port)
        defer { client.cancel() }
        let request = handshakeRequest(token: token, name: "Test tablet")
        let negotiation = try secureRecordNegotiationRequest()
        let bytes = request + negotiation.request
        for (index, byte) in bytes.enumerated() {
            queue.asyncAfter(deadline: .now() + .milliseconds(index)) {
                client.send(
                    content: Data([byte]),
                    completion: .contentProcessed { _ in }
                )
            }
        }

        wait(for: [paired], timeout: 2)
    }

    func testUnauthenticatedCandidateDoesNotEvictActiveClient() throws {
        let token = Data(repeating: 0x5A, count: 32)
        let (server, port) = try startServer(mode: .wireless(authToken: token))
        defer { server.stop() }

        let connected = expectation(description: "legitimate client connected")
        let disconnected = expectation(description: "active client disconnected")
        disconnected.isInverted = true
        server.onClientConnected = { _ in connected.fulfill() }
        server.onClientDisconnected = { _ in disconnected.fulfill() }
        let legitimate = try readySecureWirelessClient(port: port, token: token, name: "Legitimate")
        defer { legitimate.cancel() }
        _ = try readySecureWirelessProtocolSession(
            client: legitimate,
            deviceID: "legitimate-active-client"
        )
        wait(for: [connected], timeout: 2)

        let rogue = try readyClient(port: port)
        defer { rogue.cancel() }
        rogue.send(content: Data([0x00]), completion: .contentProcessed { _ in })

        wait(for: [disconnected], timeout: 0.5)
    }

    func testIncompleteHandshakeTimesOut() throws {
        let (server, port) = try startServer(mode: .wireless(authToken: Data(repeating: 0x45, count: 32)))
        defer { server.stop() }

        let client = try readyClient(port: port)
        defer { client.cancel() }
        let closed = expectation(description: "incomplete handshake closed")
        client.receive(minimumIncompleteLength: 1, maximumLength: 1) {
            _, _, isComplete, error in
            if isComplete || error != nil {
                closed.fulfill()
            }
        }
        wait(for: [closed], timeout: 4)
    }

    func testTokenRotationDisconnectsAuthenticatedClient() throws {
        let token = Data(repeating: 0x12, count: 32)
        let (server, port) = try startServer(mode: .wireless(authToken: token))
        defer { server.stop() }

        let connected = expectation(description: "client connected")
        let disconnected = expectation(description: "client revoked")
        server.onClientConnected = { _ in connected.fulfill() }
        server.onClientDisconnected = { _ in disconnected.fulfill() }
        let client = try readySecureWirelessClient(port: port, token: token, name: "Revoked")
        defer { client.cancel() }
        _ = try readySecureWirelessProtocolSession(
            client: client,
            deviceID: "revoked-active-client"
        )
        wait(for: [connected], timeout: 2)

        server.rotateAuthToken(Data(repeating: 0x34, count: 32))
        wait(for: [disconnected], timeout: 2)
    }

    func testReplacingConnectionIgnoresStaleCancellationCallback() throws {
        let token = Data(repeating: 0x77, count: 32)
        let (server, port) = try startServer(mode: .wireless(authToken: token))
        defer { server.stop() }

        let firstConnected = expectation(description: "first connected")
        let secondConnected = expectation(description: "second connected")
        var connectionCount = 0
        server.onClientConnected = { _ in
            connectionCount += 1
            if connectionCount == 1 {
                firstConnected.fulfill()
            } else if connectionCount == 2 {
                secondConnected.fulfill()
            }
        }
        let disconnected = expectation(description: "new session disconnected")
        disconnected.isInverted = true
        server.onClientDisconnected = { _ in disconnected.fulfill() }
        let first = try readySecureWirelessClient(port: port, token: token, name: "First")
        defer { first.cancel() }
        _ = try readySecureWirelessProtocolSession(
            client: first,
            deviceID: "replacement-first"
        )
        wait(for: [firstConnected], timeout: 2)

        let second = try readySecureWirelessClient(port: port, token: token, name: "Second")
        defer { second.cancel() }
        _ = try readySecureWirelessProtocolSession(
            client: second,
            deviceID: "replacement-second"
        )
        wait(for: [secondConnected], timeout: 2)
        wait(for: [disconnected], timeout: 0.5)
    }

    func testInvalidPointerCountClosesConnectionWithoutResynchronizing() throws {
        let (server, port) = try startServer()
        defer { server.stop() }
        let connected = expectation(description: "client connected")
        let disconnected = expectation(description: "malformed client disconnected")
        server.onClientConnected = { _ in connected.fulfill() }
        server.onClientDisconnected = { _ in disconnected.fulfill() }
        let client = try readyClient(port: port)
        defer { client.cancel() }
        wait(for: [connected], timeout: 2)
        client.send(
            content: Data([2, 3]),
            completion: .contentProcessed { _ in }
        )
        wait(for: [disconnected], timeout: 2)
    }

    func testClosedUSBConnectionsReleaseServerSocketWrappers() throws {
        let server = StreamingServer(port: 0)
        defer { server.stop() }
        var serverConnections: [WeakServerConnection] = []
        server.observeAcceptedConnectionsForSelfTest { connection in
            serverConnections.append(WeakServerConnection(connection))
        }
        try server.start()
        let port = try XCTUnwrap(server.listeningPort)

        for index in 0..<8 {
            let connected = expectation(description: "client connected \(index)")
            let disconnected = expectation(description: "client disconnected \(index)")
            server.onClientConnected = { _ in connected.fulfill() }
            server.onClientDisconnected = { _ in disconnected.fulfill() }

            try autoreleasepool {
                let client = try readyClient(port: port)
                wait(for: [connected], timeout: 2)
                client.cancel()
            }
            wait(for: [disconnected], timeout: 2)
            waitForNetworkQueue(server)
        }

        server.onClientConnected = nil
        server.onClientDisconnected = nil
        server.observeAcceptedConnectionsForSelfTest(nil)
        XCTAssertEqual(serverConnections.count, 8)
        XCTAssertTrue(
            waitUntilReleased(serverConnections),
            "Closed server-side NWConnection instances must not retain their TCP file descriptors"
        )
    }

    func testDisconnectResetsFramePipelineState() throws {
        let server = StreamingServer(port: 0)
        defer { server.stop() }
        let connected = expectation(description: "client connected")
        let disconnected = expectation(description: "client disconnected")
        server.onClientConnected = { _ in connected.fulfill() }
        server.onClientDisconnected = { _ in disconnected.fulfill() }
        try server.start()
        let port = try XCTUnwrap(server.listeningPort)

        let client = try readyClient(port: port)
        wait(for: [connected], timeout: 2)
        let active = server.framePipelineSnapshotForSelfTest()
        XCTAssertTrue(server.stageFramePipelineBacklogForSelfTest())
        let backedUp = server.framePipelineSnapshotForSelfTest()
        XCTAssertTrue(backedUp.sendInFlight)
        XCTAssertEqual(backedUp.pendingFrameCount, 1)
        XCTAssertFalse(backedUp.requiresKeyframe)
        client.cancel()

        wait(for: [disconnected], timeout: 2)
        waitForNetworkQueue(server)
        let afterDisconnect = server.framePipelineSnapshotForSelfTest()

        XCTAssertGreaterThan(afterDisconnect.generation, active.generation)
        XCTAssertFalse(afterDisconnect.sendInFlight)
        XCTAssertEqual(afterDisconnect.pendingFrameCount, 0)
        XCTAssertTrue(afterDisconnect.requiresKeyframe)
    }

    func testStopKeepsStatsCallbacksAndTelemetryReusable() {
        let telemetry = RecordingTelemetryRecorder()
        let server = StreamingServer(port: 0, telemetry: telemetry)
        var statsCallCount = 0
        server.onStats = { _, _, _ in statsCallCount += 1 }
        var encoderStatsCallCount = 0
        server.encoderStatsProvider = {
            encoderStatsCallCount += 1
            return (inFlight: 1, capacity: 2, frameRegistryCount: 1)
        }
        var frameLifecycleStatsCallCount = 0
        server.frameLifecycleStatsProvider = {
            frameLifecycleStatsCallCount += 1
            return StreamFrameLifecycleStats(
                latestPixelBufferRetained: 1,
                latestPixelBufferCapacity: 1,
                fallbackCaptureActive: false,
                encoderPresent: true
            )
        }

        server.stop()

        server.onStats?(60, 10, 1)
        _ = server.encoderStatsProvider?()
        _ = server.frameLifecycleStatsProvider?()
        XCTAssertEqual(statsCallCount, 1)
        XCTAssertEqual(encoderStatsCallCount, 1)
        XCTAssertEqual(frameLifecycleStatsCallCount, 1)
        XCTAssertNoThrow(try telemetry.record(TelemetryEvent(event: "after_stop")))
        XCTAssertEqual(telemetry.recordedEvents(), ["after_stop"])
    }

    func testProtocolV1UpgradeInvalidatesPendingLegacyCodecCompletion() throws {
        let server = StreamingServer(port: 0)
        defer { server.stop() }

        let legacyNegotiationStarted = expectation(description: "legacy codec negotiation started")
        let completionLock = NSLock()
        var legacyCompletion: ((NegotiatedDisplayConfiguration?) -> Void)?
        server.onCodecNegotiated = { _, _, completion in
            completionLock.withLock { legacyCompletion = completion }
            legacyNegotiationStarted.fulfill()
        }
        let incorrectlyConnected = expectation(description: "stale legacy completion connected")
        incorrectlyConnected.isInverted = true
        server.onClientConnected = { _ in incorrectlyConnected.fulfill() }
        try server.start()
        let port = try XCTUnwrap(server.listeningPort)

        let client = try readyClient(port: port)
        defer { client.cancel() }
        wait(for: [legacyNegotiationStarted], timeout: 2)

        let upgradeAcknowledged = expectation(description: "protocol v1 upgrade acknowledged")
        client.receive(minimumIncompleteLength: 2, maximumLength: 2) { data, _, _, error in
            XCTAssertNil(error)
            XCTAssertEqual(data, ProtocolV1Upgrade.acknowledgement)
            upgradeAcknowledged.fulfill()
        }
        client.send(
            content: Data([ProtocolV1Upgrade.offer]),
            completion: .contentProcessed { error in XCTAssertNil(error) }
        )
        wait(for: [upgradeAcknowledged], timeout: 2)

        let completion = completionLock.withLock { legacyCompletion }
        completion?(NegotiatedDisplayConfiguration(width: 1_920, height: 1_080, rotation: 0))
        wait(for: [incorrectlyConnected], timeout: 0.25)
    }

    func testWirelessProtocolUpgradeAcceptsOfferAfterLANRoundTripDelay() throws {
        let token = Data(repeating: 0x91, count: 32)
        let (server, port) = try startServer(
            mode: .wireless(authToken: token),
            protocolUpgradeGraceMillisecondsOverride: 2_000
        )
        defer { server.stop() }

        let client = try readySecureWirelessClient(port: port, token: token, name: "Delayed Android")
        defer { client.cancel() }

        let delayElapsed = expectation(description: "representative LAN scheduling delay")
        queue.asyncAfter(deadline: .now() + .milliseconds(300)) { delayElapsed.fulfill() }
        wait(for: [delayElapsed], timeout: 1)

        let upgraded = expectation(description: "delayed protocol v1 offer accepted")
        try send(Data([ProtocolV1Upgrade.offer]), on: client)
        let acknowledgement = try receiveExactly(2, from: client)
        XCTAssertEqual(
            acknowledgement,
            ProtocolV1Upgrade.acknowledgement,
            "Expected Protocol v1 ack, got \(hex(acknowledgement))"
        )
        upgraded.fulfill()
        wait(for: [upgraded], timeout: 2)
    }

    func testSecureWirelessProtocolV1AdvertisesEncryptionAndEncryptsMediaFrames() throws {
        let token = Data(repeating: 0xA9, count: 32)
        let server = StreamingServer(port: 0, mode: .wireless(authToken: token))
        let connected = expectation(description: "secure wireless protocol v1 streaming")
        server.onClientConnected = { _ in connected.fulfill() }
        defer { server.stop() }
        try server.start()
        let port = try XCTUnwrap(server.listeningPort)

        let client = try readySecureWirelessClient(port: port, token: token, name: "Encrypted Android")
        defer { client.cancel() }
        try send(Data([ProtocolV1Upgrade.offer]), on: client)
        XCTAssertEqual(try receiveExactly(2, from: client), ProtocolV1Upgrade.acknowledgement)

        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "secure-wireless-media"
        hello.deviceName = "Secure wireless media"
        hello.capabilities = [.touch, .multiDisplay, .endToEndEncryption, .replayProtection]
        hello.requiredCapabilities = [.endToEndEncryption, .replayProtection]
        hello.codecs = [.hevc]
        hello.transports = [.lan]
        try sendEnvelope(envelope(id: 1, payload: .clientHello(hello), scoped: false), on: client)

        let hostHelloEnvelope = try receiveEnvelope(from: client)
        let hostHello = try XCTUnwrap(hostHelloEnvelope.hostHello)
        XCTAssertTrue(hostHello.capabilities.contains(.endToEndEncryption))
        XCTAssertTrue(hostHello.capabilities.contains(.replayProtection))
        let accepted = try XCTUnwrap(try receiveEnvelope(from: client).sessionAccepted)
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.endToEndEncryption))
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.replayProtection))

        var start = VSStartDisplayRequest()
        start.mode = .existing
        try sendEnvelope(envelope(
            id: 2,
            payload: .startDisplayRequest(start),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        _ = try receiveEnvelope(from: client)
        let videoEnvelope = try receiveEnvelope(from: client)
        let video = try XCTUnwrap(videoEnvelope.videoConfig)
        var result = VSVideoConfigResult()
        result.configEpoch = video.configEpoch
        result.streamID = video.streamID
        result.accepted = true
        try sendEnvelope(envelope(
            id: 3,
            payload: .videoConfigResult(result),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        wait(for: [connected], timeout: 2)

        let payload = Data([0, 0, 0, 1, 0x26])
        server.sendFrame(
            payload,
            timestamp: 123,
            isKeyframe: true,
            sessionEpoch: accepted.sessionEpoch
        )

        let mediaPlaintext = try receiveSecurePlaintext(from: client, expectedChannel: .media)
        var framer = ProtocolV1Framer()
        let frames = try framer.append(mediaPlaintext)
        XCTAssertEqual(frames.count, 1)
        let frame = try XCTUnwrap(frames.first)
        XCTAssertEqual(frame.channel, .video)
        let media = try ProtocolV1MediaPacketCodec.decode(frame.payload)
        XCTAssertEqual(media.header.sessionEpoch, accepted.sessionEpoch)
        XCTAssertEqual(media.header.configEpoch, video.configEpoch)
        XCTAssertEqual(media.header.streamID, video.streamID)
        XCTAssertTrue(media.header.keyframe)
        XCTAssertEqual(media.payload, payload)
    }

    func testExplicitLegacyFallbackHostStillNegotiatesSecureRecordsWithNewPeer() throws {
        let token = Data(repeating: 0xB1, count: 32)
        let (server, port) = try startServer(
            mode: .wireless(authToken: token),
            allowPlaintextWirelessLegacyFallback: true
        )
        defer { server.stop() }

        let client = try readySecureWirelessClient(port: port, token: token, name: "New secure peer")
        defer { client.cancel() }
        try send(Data([ProtocolV1Upgrade.offer]), on: client)
        XCTAssertEqual(try receiveExactly(2, from: client), ProtocolV1Upgrade.acknowledgement)
    }

    func testExplicitLegacyFallbackDoesNotAdvertiseEncryptionCapabilities() throws {
        let token = Data(repeating: 0xB2, count: 32)
        let (server, port) = try startServer(
            mode: .wireless(authToken: token),
            allowPlaintextWirelessLegacyFallback: true
        )
        defer { server.stop() }

        let client = try readyLegacyWirelessClient(port: port, token: token, name: "Legacy peer")
        defer { client.cancel() }
        try send(Data([ProtocolV1Upgrade.offer]), on: client)
        XCTAssertEqual(try receiveExactly(2, from: client), ProtocolV1Upgrade.acknowledgement)

        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "legacy-fallback"
        hello.deviceName = "Legacy fallback"
        hello.capabilities = [.touch, .multiDisplay]
        hello.requiredCapabilities = [.touch]
        hello.codecs = [.hevc]
        hello.transports = [.lan]
        try sendEnvelope(envelope(id: 1, payload: .clientHello(hello), scoped: false), on: client)

        let hostHello = try XCTUnwrap(try receiveEnvelope(from: client).hostHello)
        XCTAssertFalse(hostHello.capabilities.contains(.endToEndEncryption))
        XCTAssertFalse(hostHello.capabilities.contains(.replayProtection))
        let accepted = try XCTUnwrap(try receiveEnvelope(from: client).sessionAccepted)
        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.endToEndEncryption))
        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.replayProtection))
    }

    func testProtocolV1ControllerFailureDropsLaterQueuedDelivery() throws {
        let server = StreamingServer(port: 0)
        server.controllerAvailable = true
        let streamingReady = expectation(description: "controller session streaming")
        let initialKeyframeRequested = expectation(description: "initial keyframe requested")
        let controllerCallbacksDrained = expectation(description: "queued controller callbacks drained")
        let networkBarrierCompleted = expectation(description: "network barrier completed")
        let controllerBatchParsed = DispatchSemaphore(value: 0)
        let resumeNetworkQueue = DispatchSemaphore(value: 0)
        let callbackState = StreamingServerLifecycleCallbackState()
        server.onControllerEvent = { event, _ in
            let deliveryCount = callbackState.recordControllerDelivery()
            if deliveryCount == 2 {
                XCTAssertEqual(
                    controllerBatchParsed.wait(timeout: .now() + 2),
                    .success
                )
            }
            return event.kind == .connected && deliveryCount == 1
        }
        server.onClientConnected = { _ in streamingReady.fulfill() }
        server.onKeyframeRequested = { _, _ in
            if callbackState.recordKeyframeRequest() == 1 {
                initialKeyframeRequested.fulfill()
            } else {
                controllerBatchParsed.signal()
                DispatchQueue.main.async {
                    controllerCallbacksDrained.fulfill()
                    resumeNetworkQueue.signal()
                }
                let result = resumeNetworkQueue.wait(timeout: .now() + 2)
                callbackState.storeNetworkBarrierResult(result)
                networkBarrierCompleted.fulfill()
            }
        }
        server.onCodecNegotiated = { _, _, completion in
            completion(NegotiatedDisplayConfiguration(
                width: 1_920,
                height: 1_080,
                rotation: 0
            ))
        }
        defer { server.stop() }
        try server.start()
        let port = try XCTUnwrap(server.listeningPort)

        let client = try readyClient(port: port)
        defer { client.cancel() }
        try send(Data([ProtocolV1Upgrade.offer]), on: client)
        XCTAssertEqual(try receiveExactly(2, from: client), ProtocolV1Upgrade.acknowledgement)

        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "controller-fail-closed"
        hello.deviceName = "Controller fail-closed"
        hello.capabilities = [.touch, .multiDisplay, .controller]
        hello.requiredCapabilities = [.touch]
        hello.codecs = [.hevc]
        hello.transports = [.usb]
        try sendEnvelope(
            envelope(id: 1, payload: .clientHello(hello), scoped: false),
            on: client
        )
        _ = try receiveEnvelope(from: client)
        let acceptedEnvelope = try receiveEnvelope(from: client)
        let accepted = try XCTUnwrap(acceptedEnvelope.sessionAccepted)
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.controller))

        try sendEnvelope(envelope(
            id: 2,
            payload: .listDisplaysRequest(VSListDisplaysRequest()),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        _ = try receiveEnvelope(from: client)
        var start = VSStartDisplayRequest()
        start.mode = .existing
        try sendEnvelope(envelope(
            id: 3,
            payload: .startDisplayRequest(start),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        _ = try receiveEnvelope(from: client)
        let videoEnvelope = try receiveEnvelope(from: client)
        let video = try XCTUnwrap(videoEnvelope.videoConfig)
        var result = VSVideoConfigResult()
        result.configEpoch = video.configEpoch
        result.streamID = video.streamID
        result.accepted = true
        try sendEnvelope(envelope(
            id: 4,
            payload: .videoConfigResult(result),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        wait(for: [streamingReady, initialKeyframeRequested], timeout: 2)

        var connected = VSControllerEvent()
        connected.inputID = 1
        connected.controllerID = "pad-1"
        connected.controllerEpoch = 1
        connected.kind = .connected
        try sendEnvelope(envelope(
            id: 5,
            payload: .controllerEvent(connected),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        let acceptedControllerEnvelope = try receiveEnvelope(from: client)
        XCTAssertTrue(acceptedControllerEnvelope.inputAck.accepted)
        XCTAssertEqual(acceptedControllerEnvelope.inputAck.inputID, 1)
        XCTAssertEqual(acceptedControllerEnvelope.correlationID, 5)

        var state = connected
        state.inputID = 2
        state.kind = .state
        state.leftStickX = 0.5
        let stateFrame = try encodedEnvelope(envelope(
            id: 6,
            payload: .controllerEvent(state),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ))
        var laterConnected = connected
        laterConnected.inputID = 3
        laterConnected.controllerID = "pad-2"
        let laterConnectedFrame = try encodedEnvelope(envelope(
            id: 7,
            payload: .controllerEvent(laterConnected),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ))
        var requestKeyframe = VSRequestKeyframe()
        requestKeyframe.streamID = video.streamID
        requestKeyframe.reasonCode = "controller-test-barrier"
        let barrierFrame = try encodedEnvelope(envelope(
            id: 8,
            payload: .requestKeyframe(requestKeyframe),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ))
        try send(stateFrame + laterConnectedFrame + barrierFrame, on: client)

        let errorEnvelope = try receiveEnvelope(from: client)
        XCTAssertEqual(errorEnvelope.protocolError.code, .invalidState)
        XCTAssertTrue(errorEnvelope.protocolError.message.contains("Controller injection failed"))
        XCTAssertFalse(errorEnvelope.protocolError.retryable)
        XCTAssertEqual(errorEnvelope.protocolError.component, "macos-host-session")
        XCTAssertEqual(errorEnvelope.correlationID, 6)
        XCTAssertEqual(errorEnvelope.sessionID, accepted.sessionID)
        XCTAssertEqual(errorEnvelope.sessionEpoch, accepted.sessionEpoch)
        wait(for: [controllerCallbacksDrained, networkBarrierCompleted], timeout: 2)
        XCTAssertEqual(callbackState.networkBarrierResult(), .success)
        XCTAssertEqual(callbackState.controllerDeliveryCount(), 2)
    }

    func testProtocolV1ControllerConnectedAckAndLifecycleNoAck() throws {
        let server = StreamingServer(port: 0)
        server.controllerAvailable = true
        let routed = expectation(description: "controller lifecycle routed")
        routed.expectedFulfillmentCount = 3
        server.onControllerEvent = { _, _ in
            routed.fulfill()
            return true
        }
        defer { server.stop() }

        let (client, accepted, videoEnvelope) = try readyControllerProtocolSession(
            server: server,
            deviceID: "controller-ack"
        )
        defer { client.cancel() }

        var connected = VSControllerEvent()
        connected.inputID = 1
        connected.controllerID = "pad-1"
        connected.controllerEpoch = 1
        connected.kind = .connected
        try sendEnvelope(envelope(
            id: 5,
            payload: .controllerEvent(connected),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)

        let acknowledgementEnvelope = try receiveEnvelope(from: client)
        guard case .inputAck(let acknowledgement)? = acknowledgementEnvelope.payload else {
            return XCTFail("Expected CONNECTED InputAck")
        }
        XCTAssertEqual(acknowledgement.inputID, 1)
        XCTAssertTrue(acknowledgement.accepted)
        XCTAssertTrue(acknowledgement.rejectionReason.isEmpty)
        XCTAssertEqual(acknowledgementEnvelope.correlationID, 5)
        XCTAssertEqual(acknowledgementEnvelope.sessionID, accepted.sessionID)
        XCTAssertEqual(acknowledgementEnvelope.sessionEpoch, accepted.sessionEpoch)
        XCTAssertGreaterThan(acknowledgementEnvelope.messageID, videoEnvelope.messageID)

        var state = connected
        state.inputID = 2
        state.kind = .state
        state.leftStickX = 0.5
        var disconnected = connected
        disconnected.inputID = 3
        disconnected.kind = .disconnected
        var ping = VSPing()
        ping.sequence = 99
        let stateFrame = try encodedEnvelope(envelope(
            id: 6,
            payload: .controllerEvent(state),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ))
        let disconnectedFrame = try encodedEnvelope(envelope(
            id: 7,
            payload: .controllerEvent(disconnected),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ))
        let barrierFrame = try encodedEnvelope(envelope(
            id: 8,
            payload: .ping(ping),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ))
        try send(stateFrame + disconnectedFrame + barrierFrame, on: client)

        let barrierEnvelope = try receiveEnvelope(from: client)
        guard case .pong(let pong)? = barrierEnvelope.payload else {
            return XCTFail("STATE or DISCONNECTED unexpectedly produced a control response")
        }
        XCTAssertEqual(pong.sequence, 99)
        XCTAssertEqual(barrierEnvelope.correlationID, 8)
        XCTAssertGreaterThan(barrierEnvelope.messageID, acknowledgementEnvelope.messageID)
        wait(for: [routed], timeout: 2)
    }

    func testProtocolV1StaleControllerGenerationDoesNotSendAcceptedAck() throws {
        let server = StreamingServer(port: 0)
        server.controllerAvailable = true
        let routed = expectation(description: "stale controller handler completed")
        server.onControllerEvent = { _, generation in
            server.advanceClientGenerationForSelfTest(to: generation &+ 1)
            routed.fulfill()
            return true
        }
        defer { server.stop() }

        let (client, accepted, _) = try readyControllerProtocolSession(
            server: server,
            deviceID: "controller-stale-generation"
        )
        defer { client.cancel() }

        var connected = VSControllerEvent()
        connected.inputID = 1
        connected.controllerID = "pad-1"
        connected.controllerEpoch = 1
        connected.kind = .connected
        try sendEnvelope(envelope(
            id: 5,
            payload: .controllerEvent(connected),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        wait(for: [routed], timeout: 2)

        var ping = VSPing()
        ping.sequence = 100
        try sendEnvelope(envelope(
            id: 6,
            payload: .ping(ping),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)

        let barrierEnvelope = try receiveEnvelope(from: client)
        guard case .pong(let pong)? = barrierEnvelope.payload else {
            return XCTFail("Stale generation must not emit an accepted InputAck")
        }
        XCTAssertEqual(pong.sequence, 100)
        XCTAssertEqual(barrierEnvelope.correlationID, 6)
    }

    func testProtocolV1StaleConnectionOwnerDoesNotSendAcceptedAck() throws {
        let server = StreamingServer(port: 0)
        server.controllerAvailable = true
        let secondReady = expectation(description: "replacement connection ready")
        let firstClosed = expectation(description: "stale connection closed")
        let releaseHandler = DispatchSemaphore(value: 0)
        let socketState = StreamingServerLifecycleSocketState()
        var second: NWConnection?
        defer { server.stop() }

        let (first, firstAccepted, _) = try readyControllerProtocolSession(
            server: server,
            deviceID: "controller-stale-owner-a"
        )
        defer { first.cancel() }
        let replacementPort = try XCTUnwrap(server.listeningPort)
        second = NWConnection(
            host: NWEndpoint.Host("127.0.0.1"),
            port: NWEndpoint.Port(rawValue: replacementPort)!,
            using: .tcp
        )
        second?.stateUpdateHandler = { state in
            switch state {
            case .ready:
                secondReady.fulfill()
            case .failed(let error):
                socketState.storeFailure(error)
                secondReady.fulfill()
            default:
                break
            }
        }
        server.onControllerEvent = { _, _ in
            second?.start(queue: self.queue)
            XCTAssertEqual(releaseHandler.wait(timeout: .now() + 2), .success)
            return true
        }
        defer { second?.cancel() }
        receiveUntilClosed(
            first,
            received: { socketState.appendReceivedBytes($0) },
            completion: {
                releaseHandler.signal()
                firstClosed.fulfill()
            }
        )

        var connected = VSControllerEvent()
        connected.inputID = 1
        connected.controllerID = "pad-1"
        connected.controllerEpoch = 1
        connected.kind = .connected
        try sendEnvelope(envelope(
            id: 5,
            payload: .controllerEvent(connected),
            sessionID: firstAccepted.sessionID,
            sessionEpoch: firstAccepted.sessionEpoch
        ), on: first)

        wait(for: [secondReady, firstClosed], timeout: 3)
        if let failure = socketState.failure() { throw failure }
        XCTAssertTrue(socketState.receivedBytes().isEmpty)
        waitForNetworkQueue(server)

        let replacement = try XCTUnwrap(second)
        let (secondAccepted, _) = try negotiateControllerProtocolSession(
            client: replacement,
            deviceID: "controller-stale-owner-b"
        )
        var ping = VSPing()
        ping.sequence = 200
        try sendEnvelope(envelope(
            id: 5,
            payload: .ping(ping),
            sessionID: secondAccepted.sessionID,
            sessionEpoch: secondAccepted.sessionEpoch
        ), on: replacement)

        let barrierEnvelope = try receiveEnvelope(from: replacement)
        guard case .pong(let pong)? = barrierEnvelope.payload else {
            return XCTFail("Stale completion must not emit InputAck on the replacement connection")
        }
        XCTAssertEqual(pong.sequence, 200)
        XCTAssertEqual(barrierEnvelope.correlationID, 5)
    }

    private func startServer(
        mode: StreamingServerMode = .usb,
        allowPlaintextWirelessLegacyFallback: Bool = false,
        protocolUpgradeGraceMillisecondsOverride: Int? = nil,
        configure: (StreamingServer) -> Void = { _ in }
    ) throws -> (server: StreamingServer, port: UInt16) {
        // Let Network.framework choose the port so parallel CI jobs cannot collide
        // with this integration suite's loopback and wireless listeners.
        let server = StreamingServer(
            port: 0,
            mode: mode,
            allowPlaintextWirelessLegacyFallback: allowPlaintextWirelessLegacyFallback,
            protocolUpgradeGraceMillisecondsOverride: protocolUpgradeGraceMillisecondsOverride
        )
        configure(server)
        try server.start()
        guard let port = server.listeningPort, port != 0 else {
            server.stop()
            throw TestError.invalidListeningPort
        }
        return (server, port)
    }

    private func readyClient(port: UInt16) throws -> NWConnection {
        let ready = expectation(description: "client ready")
        var failure: Error?
        let client = NWConnection(
            host: NWEndpoint.Host("127.0.0.1"),
            port: NWEndpoint.Port(rawValue: port)!,
            using: .tcp
        )
        client.stateUpdateHandler = { state in
            switch state {
            case .ready:
                ready.fulfill()
            case .failed(let error):
                failure = error
                ready.fulfill()
            default:
                break
            }
        }
        client.start(queue: queue)
        wait(for: [ready], timeout: 2)
        if let failure { throw failure }
        return client
    }

    private func readySecureWirelessClient(
        port: UInt16,
        token: Data,
        name: String
    ) throws -> SecureTestClient {
        let client = try readyClient(port: port)
        try send(handshakeRequest(token: token, name: name), on: client)
        XCTAssertEqual(try receiveExactly(5, from: client), HandshakeCodec.encodeResponse(status: .ok))
        let negotiation = try secureRecordNegotiationRequest()
        try send(negotiation.request, on: client)
        let response = try LANSecureRecordNegotiation.decodeResponse(
            receiveExactly(LANSecureRecordNegotiation.responseBytes, from: client)
        )
        XCTAssertTrue(response.encrypted)
        XCTAssertFalse(response.legacy)
        let sessionID = LANSecureRecordSession.sessionIdentifier(
            hostPublicKey: response.publicKey,
            devicePublicKey: negotiation.devicePublicKey
        )
        let context = LANSecureRecordSession.transcriptContext(
            sessionIdentifier: sessionID,
            hostPublicKey: response.publicKey,
            devicePublicKey: negotiation.devicePublicKey
        )
        let session = try LANSecureRecordSession(
            role: .device,
            sessionIdentifier: sessionID,
            sessionEpoch: LANSecureRecordSession.recordSessionEpoch,
            sharedSecret: try negotiation.devicePrivateKey.sharedSecretData(with: response.publicKey),
            bootstrapToken: token,
            context: context
        )
        return SecureTestClient(connection: client, session: session, owner: self)
    }

    private func readyLegacyWirelessClient(
        port: UInt16,
        token: Data,
        name: String
    ) throws -> NWConnection {
        let client = try readyClient(port: port)
        try send(handshakeRequest(token: token, name: name), on: client)
        XCTAssertEqual(try receiveExactly(5, from: client), HandshakeCodec.encodeResponse(status: .ok))
        return client
    }

    private func secureRecordNegotiationRequest() throws -> (
        request: Data,
        devicePrivateKey: P256.KeyAgreement.PrivateKey,
        devicePublicKey: Data
    ) {
        let privateKey = P256.KeyAgreement.PrivateKey()
        let publicKey = privateKey.publicKey.x963Representation
        let request = try LANSecureRecordNegotiation.encodeRequest(
            publicKey: publicKey,
            allowLegacyFallback: false
        )
        return (request, privateKey, publicKey)
    }

    private func readyControllerProtocolSession(
        server: StreamingServer,
        deviceID: String
    ) throws -> (client: NWConnection, accepted: VSSessionAccepted, video: VSEnvelope) {
        server.onCodecNegotiated = { _, _, completion in
            completion(NegotiatedDisplayConfiguration(
                width: 1_920,
                height: 1_080,
                rotation: 0
            ))
        }
        try server.start()
        let port = try XCTUnwrap(server.listeningPort)

        let client = try readyClient(port: port)
        let (accepted, videoEnvelope) = try negotiateControllerProtocolSession(
            client: client,
            deviceID: deviceID
        )
        return (client, accepted, videoEnvelope)
    }

    private func readySecureWirelessProtocolSession(
        client: SecureTestClient,
        deviceID: String
    ) throws -> (accepted: VSSessionAccepted, video: VSEnvelope) {
        try send(Data([ProtocolV1Upgrade.offer]), on: client)
        XCTAssertEqual(try receiveExactly(2, from: client), ProtocolV1Upgrade.acknowledgement)

        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = deviceID
        hello.deviceName = deviceID
        hello.capabilities = [.touch, .multiDisplay, .endToEndEncryption, .replayProtection]
        hello.requiredCapabilities = [.touch, .endToEndEncryption, .replayProtection]
        hello.codecs = [.hevc]
        hello.transports = [.lan]
        try sendEnvelope(envelope(id: 1, payload: .clientHello(hello), scoped: false), on: client)
        _ = try receiveEnvelope(from: client)
        let accepted = try XCTUnwrap(try receiveEnvelope(from: client).sessionAccepted)
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.endToEndEncryption))
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.replayProtection))

        var start = VSStartDisplayRequest()
        start.mode = .existing
        try sendEnvelope(envelope(
            id: 2,
            payload: .startDisplayRequest(start),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        _ = try receiveEnvelope(from: client)
        let videoEnvelope = try receiveEnvelope(from: client)
        let video = try XCTUnwrap(videoEnvelope.videoConfig)
        var result = VSVideoConfigResult()
        result.configEpoch = video.configEpoch
        result.streamID = video.streamID
        result.accepted = true
        try sendEnvelope(envelope(
            id: 3,
            payload: .videoConfigResult(result),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        return (accepted, videoEnvelope)
    }

    private func negotiateControllerProtocolSession(
        client: NWConnection,
        deviceID: String
    ) throws -> (accepted: VSSessionAccepted, video: VSEnvelope) {
        try send(Data([ProtocolV1Upgrade.offer]), on: client)
        XCTAssertEqual(try receiveExactly(2, from: client), ProtocolV1Upgrade.acknowledgement)

        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = deviceID
        hello.deviceName = deviceID
        hello.capabilities = [.touch, .multiDisplay, .controller]
        hello.requiredCapabilities = [.touch]
        hello.codecs = [.hevc]
        hello.transports = [.usb]
        try sendEnvelope(envelope(id: 1, payload: .clientHello(hello), scoped: false), on: client)
        _ = try receiveEnvelope(from: client)
        let accepted = try XCTUnwrap(try receiveEnvelope(from: client).sessionAccepted)
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.controller))

        try sendEnvelope(envelope(
            id: 2,
            payload: .listDisplaysRequest(VSListDisplaysRequest()),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        _ = try receiveEnvelope(from: client)
        var start = VSStartDisplayRequest()
        start.mode = .existing
        try sendEnvelope(envelope(
            id: 3,
            payload: .startDisplayRequest(start),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        _ = try receiveEnvelope(from: client)
        let videoEnvelope = try receiveEnvelope(from: client)
        let video = try XCTUnwrap(videoEnvelope.videoConfig)
        var result = VSVideoConfigResult()
        result.configEpoch = video.configEpoch
        result.streamID = video.streamID
        result.accepted = true
        try sendEnvelope(envelope(
            id: 4,
            payload: .videoConfigResult(result),
            sessionID: accepted.sessionID,
            sessionEpoch: accepted.sessionEpoch
        ), on: client)
        return (accepted, videoEnvelope)
    }

    private func receiveUntilClosed(
        _ client: NWConnection,
        received: @escaping (Data) -> Void,
        completion: @escaping () -> Void
    ) {
        client.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1_024) {
            [weak self, weak client] data, _, isComplete, error in
            if let data, !data.isEmpty { received(data) }
            guard error == nil, !isComplete, let self, let client else {
                completion()
                return
            }
            self.receiveUntilClosed(client, received: received, completion: completion)
        }
    }

    private func envelope(
        id: UInt64,
        payload: VSEnvelope.OneOf_Payload,
        sessionID: Data = Data(),
        sessionEpoch: UInt64 = 0,
        scoped: Bool = true
    ) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = id
        if scoped {
            envelope.sessionID = sessionID
            envelope.sessionEpoch = sessionEpoch
        }
        envelope.sentAtMonotonicNs = id
        envelope.payload = payload
        return envelope
    }

    private func sendEnvelope(_ envelope: VSEnvelope, on client: NWConnection) throws {
        try send(try encodedEnvelope(envelope), on: client)
    }

    private func sendEnvelope(_ envelope: VSEnvelope, on client: SecureTestClient) throws {
        try send(try encodedEnvelope(envelope), on: client)
    }

    private func encodedEnvelope(_ envelope: VSEnvelope) throws -> Data {
        try ProtocolV1TransportFrame(
            channel: .control,
            payload: try envelope.serializedData()
        ).encoded()
    }

    private func send(_ data: Data, on client: NWConnection) throws {
        let sent = expectation(description: "client send")
        var failure: Error?
        client.send(content: data, completion: .contentProcessed { error in
            failure = error
            sent.fulfill()
        })
        wait(for: [sent], timeout: 2)
        if let failure { throw failure }
    }

    private func send(_ data: Data, on client: SecureTestClient) throws {
        try send(try client.seal(data, channel: .control), on: client.connection)
    }

    private func receiveEnvelope(from client: NWConnection) throws -> VSEnvelope {
        let header = try receiveExactly(5, from: client)
        XCTAssertEqual(header.first, ProtocolV1LogicalChannel.control.rawValue)
        let length = header.dropFirst().reduce(UInt32.zero) { ($0 << 8) | UInt32($1) }
        return try VSEnvelope(serializedBytes: receiveExactly(Int(length), from: client))
    }

    private func receiveEnvelope(from client: SecureTestClient) throws -> VSEnvelope {
        let header = try receiveExactly(5, from: client)
        XCTAssertEqual(header.first, ProtocolV1LogicalChannel.control.rawValue)
        let length = header.dropFirst().reduce(UInt32.zero) { ($0 << 8) | UInt32($1) }
        return try VSEnvelope(serializedBytes: receiveExactly(Int(length), from: client))
    }

    private func receiveExactly(_ count: Int, from client: NWConnection) throws -> Data {
        var result = Data()
        while result.count < count {
            let received = expectation(description: "client receive")
            var chunk: Data?
            var failure: Error?
            var complete = false
            client.receive(
                minimumIncompleteLength: 1,
                maximumLength: count - result.count
            ) { data, _, isComplete, error in
                chunk = data
                failure = error
                complete = isComplete
                received.fulfill()
            }
            wait(for: [received], timeout: 2)
            if let failure { throw failure }
            if let chunk { result.append(chunk) }
            if complete && result.count < count { throw TestError.connectionClosed }
        }
        return result
    }

    private func receiveExactly(_ count: Int, from client: SecureTestClient) throws -> Data {
        while client.buffer.count < count {
            client.buffer.append(try receiveSecurePlaintext(from: client))
        }
        let result = client.buffer.prefix(count)
        client.buffer.removeFirst(count)
        return Data(result)
    }

    private func hex(_ data: Data) -> String {
        data.map { String(format: "%02x", $0) }.joined()
    }

    private func receiveSecurePlaintext(
        from client: SecureTestClient,
        expectedChannel: InternetTransportChannel? = nil
    ) throws -> Data {
        let prefix = try receiveExactly(4, from: client.connection)
        let recordLength = prefix.reduce(UInt32.zero) { ($0 << 8) | UInt32($1) }
        let record = try receiveExactly(Int(recordLength), from: client.connection)
        if let expectedChannel {
            XCTAssertEqual(PlatformSessionPacketCipher.declaredInternetChannel(in: record), expectedChannel)
        }
        return try client.session.openDeclaredChannel(record)
    }

    private func handshakeRequest(token: Data, name: String) -> Data {
        let nameData = Data(name.utf8)
        var request = Data(HandshakeCodec.requestMagic)
        request.append(token)
        request.append(UInt8(nameData.count))
        request.append(nameData)
        return request
    }

    private func waitForNetworkQueue(_ server: StreamingServer) {
        let entered = DispatchSemaphore(value: 0)
        let resume = DispatchSemaphore(value: 0)
        server.suspendNetworkQueueForSelfTest(entered: entered, resume: resume)
        XCTAssertEqual(entered.wait(timeout: .now() + 2), .success)
        resume.signal()
    }

    private func waitUntilReleased(
        _ connections: [WeakServerConnection],
        timeout: TimeInterval = 2
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            autoreleasepool {
                RunLoop.current.run(until: Date().addingTimeInterval(0.02))
            }
            if connections.allSatisfy({ $0.connection == nil }) {
                return true
            }
        }
        return connections.allSatisfy { $0.connection == nil }
    }

    private enum TestError: Error {
        case connectionClosed
        case invalidListeningPort
    }
}

private final class WeakServerConnection {
    weak var connection: NWConnection?

    init(_ connection: NWConnection) {
        self.connection = connection
    }
}

private final class SecureTestClient {
    let connection: NWConnection
    let session: LANSecureRecordSession
    fileprivate var buffer = Data()

    private weak var owner: StreamingServerLifecycleTests?

    init(
        connection: NWConnection,
        session: LANSecureRecordSession,
        owner: StreamingServerLifecycleTests
    ) {
        self.connection = connection
        self.session = session
        self.owner = owner
    }

    func cancel() {
        session.close()
        connection.cancel()
    }

    func seal(_ data: Data, channel: InternetTransportChannel) throws -> Data {
        try LANSecureRecordStreamFramer.encode(try session.seal(data, channel: channel))
    }
}

private final class StreamingServerLifecycleCallbackState: @unchecked Sendable {
    private let lock = NSLock()
    private var controllerDeliveries = 0
    private var keyframeRequests = 0
    private var barrierResult: DispatchTimeoutResult?

    func recordControllerDelivery() -> Int {
        lock.withLock {
            controllerDeliveries += 1
            return controllerDeliveries
        }
    }

    func controllerDeliveryCount() -> Int {
        lock.withLock { controllerDeliveries }
    }

    func recordKeyframeRequest() -> Int {
        lock.withLock {
            keyframeRequests += 1
            return keyframeRequests
        }
    }

    func storeNetworkBarrierResult(_ result: DispatchTimeoutResult) {
        lock.withLock { barrierResult = result }
    }

    func networkBarrierResult() -> DispatchTimeoutResult? {
        lock.withLock { barrierResult }
    }
}

private final class StreamingServerLifecycleSocketState: @unchecked Sendable {
    private let lock = NSLock()
    private var storedFailure: Error?
    private var storedReceivedBytes = Data()

    func storeFailure(_ failure: Error) {
        lock.withLock { storedFailure = failure }
    }

    func failure() -> Error? {
        lock.withLock { storedFailure }
    }

    func appendReceivedBytes(_ bytes: Data) {
        lock.withLock { storedReceivedBytes.append(bytes) }
    }

    func receivedBytes() -> Data {
        lock.withLock { storedReceivedBytes }
    }
}

private final class RecordingTelemetryRecorder: TelemetryRecording {
    private let lock = NSLock()
    private var events: [String] = []

    func record(_ event: TelemetryEvent) throws {
        lock.withLock { events.append(event.event) }
    }

    func recordedEvents() -> [String] {
        lock.withLock { events }
    }
}
