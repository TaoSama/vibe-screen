import Foundation
import CoreMedia
import CoreVideo
import VibeScreenProtocol
import XCTest
@testable import Telemachus

final class InternetProductSessionTests: XCTestCase {
    func testInputCleanupScopeMapsAndAppliesEverySessionState() {
        let cases: [(InternetProductSessionState, InternetSessionInputCleanupScope)] = [
            (.idle, .fullSessionReset),
            (.connecting, .fullSessionReset),
            (.authenticating, .fullSessionReset),
            (.awaitingVideoConfiguration, .transientOnly),
            (.streaming(.direct), .preserve),
            (.streaming(.relay), .preserve),
            (.streaming(.unknown), .preserve),
            (.recovering(attempt: 1), .fullSessionReset),
            (.failed("reason"), .fullSessionReset),
            (.revoked, .fullSessionReset),
            (.closed, .fullSessionReset),
        ]

        for (state, expected) in cases {
            XCTAssertEqual(state.inputCleanupScope, expected, "state: \(state)")
            var transientResetCount = 0
            var fullResetCount = 0
            state.inputCleanupScope.apply(
                transientReset: { transientResetCount += 1 },
                fullSessionReset: { fullResetCount += 1 }
            )
            XCTAssertEqual(transientResetCount, expected == .transientOnly ? 1 : 0)
            XCTAssertEqual(fullResetCount, expected == .fullSessionReset ? 1 : 0)
        }
    }

    func testFreshSessionRecoveryBudgetPersistsUntilExplicitReset() {
        var budget = FreshSessionRecoveryBudget(
            policy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )

        XCTAssertEqual(budget.nextAttempt(), 1)
        XCTAssertEqual(budget.nextAttempt(), 2)
        XCTAssertNil(budget.nextAttempt())
        XCTAssertEqual(budget.attempt, 2)

        budget.reset()
        XCTAssertEqual(budget.nextAttempt(), 1)
    }

    func testBoundTranscriptContextMatchesCrossPlatformFixture() throws {
        let configuration = InternetProductSessionConfiguration(
            transport: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:127.0.0.1:9")!])],
                peerIdentity: String(repeating: "d", count: 64),
                sessionIdentifier: "session-1",
                forceRelay: false
            ),
            hostDeviceID: "host-1",
            hostName: "Mac",
            peerDeviceID: "device-1",
            peerIdentity: PlatformPublicIdentity(
                deviceID: "device-1",
                keyID: String(repeating: "d", count: 64),
                keyEpoch: 1,
                signingPublicKey: Data([UInt8(0x04)] + Array(repeating: UInt8(0x11), count: 64))
            ),
            authoritativeSessionEpoch: 7,
            sharedSecretName: "shared-device-1",
            bootstrapSecretName: "bootstrap-device-1",
            transcriptContext: Data((0..<32).map(UInt8.init)),
            video: InternetProductVideoConfiguration(
                codec: .hevc,
                width: 1920,
                height: 1080,
                framesPerSecond: 60,
                bitrateKbps: 20_000
            )
        )

        XCTAssertEqual(
            configuration.boundTranscriptContext.map { String(format: "%02x", $0) }.joined(),
            "dd7e26a6d119e9d8d62e3f967d311c7c0ef78357a985947e33083b8c2c683735"
        )
    }

    func testHelloVideoAckGateThenRoutesMediaTouchKeyframeAndHeartbeat() throws {
        let harness = try Harness()
        let authenticating = expectation(description: "authenticating")
        let streaming = expectation(description: "streaming")
        let touch = expectation(description: "touch")
        let keyframe = expectation(description: "keyframe")
        var keyframeCount = 0
        var streamingObserved = false

        harness.session.onStateChanged = { state in
            if state == .authenticating { authenticating.fulfill() }
            if state == .streaming(.direct), !streamingObserved {
                streamingObserved = true
                streaming.fulfill()
            }
        }
        harness.session.onAuthenticatedTouchEvent = {
            sessionEpoch, inputID, x, y, action, pointers, _, _ in
            XCTAssertEqual(sessionEpoch, 1)
            XCTAssertEqual(inputID, 1)
            XCTAssertEqual(x, 0.25)
            XCTAssertEqual(y, 0.75)
            XCTAssertEqual(action, 0)
            XCTAssertEqual(pointers, 1)
            touch.fulfill()
            return true
        }
        harness.session.onKeyframeRequired = {
            keyframeCount += 1
            if keyframeCount == 2 { keyframe.fulfill() }
        }

        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        wait(for: [authenticating], timeout: 1)
        harness.receiveControl(harness.clientHello(messageID: 1))

        XCTAssertTrue(harness.waitForSentControlCount(3))
        let outbound = try harness.engine.sentPlaintext
            .filter { $0.channel == .control }
            .prefix(3)
            .map { try VSEnvelope(serializedBytes: $0.payload) }
        XCTAssertEqual(outbound.count, 3)
        guard case .hostHello = outbound[0].payload,
              case .sessionAccepted = outbound[1].payload,
              case .videoConfig = outbound[2].payload else {
            return XCTFail("Host negotiation messages were not ordered correctly")
        }

        harness.receiveControl(harness.videoAccepted(messageID: 2))
        wait(for: [streaming], timeout: 1)
        XCTAssertEqual(harness.session.currentSessionEpoch, 1)

        try harness.session.updateRotation(90)
        XCTAssertTrue(harness.waitForSentControlCount(5))
        let rotationControls = try harness.engine.sentPlaintext
            .filter { $0.channel == .control }
            .suffix(2)
            .map { try VSEnvelope(serializedBytes: $0.payload) }
        guard case .displayChanged(let displayChanged) = rotationControls[0].payload,
              case .videoConfig(let rotatedVideo) = rotationControls[1].payload else {
            return XCTFail("Runtime rotation must send DisplayChanged followed by VideoConfig")
        }
        XCTAssertEqual(displayChanged.rotationDegrees, 90)
        XCTAssertEqual(rotatedVideo.rotationDegrees, 90)
        XCTAssertEqual(rotatedVideo.configEpoch, 2)
        harness.receiveControl(harness.videoAccepted(messageID: 3, configEpoch: 2))

        harness.session.sendFrame(
            Data([0, 0, 0, 1, 0x26]),
            timestamp: 99,
            isKeyframe: true,
            sessionEpoch: 1
        )
        XCTAssertTrue(harness.waitForSentMediaCount(1))
        let media = try ProtocolV1MediaPacketCodec.decode(
            harness.engine.sentPlaintext.first { $0.channel == .media }!.payload
        )
        XCTAssertEqual(media.header.captureTimestampNs, 99)
        XCTAssertTrue(media.header.keyframe)

        harness.receiveControl(harness.touch(messageID: 4))
        harness.receiveControl(harness.keyframeRequest(messageID: 5))
        harness.receiveControl(harness.ping(messageID: 6, sequence: 77))
        wait(for: [touch, keyframe], timeout: 1)
        XCTAssertTrue(harness.waitForPong(sequence: 77))
    }

    func testInternetNegotiatesAndRoutesValidatedStylusWithoutTouchFallback() throws {
        let harness = try Harness()
        let routed = expectation(description: "stylus routed")
        harness.session.onAuthenticatedStylusEvent = {
            epoch, inputID, pointerID, x, y, phase, pressure, tiltX, tiltY,
            toolKind, buttonMask, contactState in
            XCTAssertEqual(epoch, 1)
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
            routed.fulfill()
            return true
        }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsStylus: true))
        XCTAssertTrue(harness.waitForSentControlCount(3))
        let controls = try harness.engine.sentPlaintext
            .filter { $0.channel == .control }
            .prefix(2)
            .map { try VSEnvelope(serializedBytes: $0.payload) }
        XCTAssertTrue(controls[0].hostHello.capabilities.contains(.stylus))
        XCTAssertTrue(controls[1].sessionAccepted.negotiatedCapabilities.contains(.stylus))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        var androidTargetedStylus = harness.stylus(messageID: 3)
        var androidTarget = VSInputTarget()
        androidTarget.streamID = 1
        androidTargetedStylus.stylusEvent.target = androidTarget
        harness.receiveControl(androidTargetedStylus)
        wait(for: [routed], timeout: 1)
    }

    func testInternetRejectsUnnegotiatedAndMalformedStylus() throws {
        let unnegotiated = try Harness()
        try unnegotiated.session.start(configuration: unnegotiated.configuration)
        unnegotiated.engine.emitConnection(.connected(path: .direct))
        unnegotiated.receiveControl(unnegotiated.clientHello(messageID: 1))
        unnegotiated.receiveControl(unnegotiated.videoAccepted(messageID: 2))
        unnegotiated.receiveControl(unnegotiated.stylus(messageID: 3))
        XCTAssertTrue(unnegotiated.waitForFailure())

        for mutation in ["combinedTilt", "terminalPressure", "wrongStream", "wrongDisplay"] {
            let harness = try Harness()
            try harness.session.start(configuration: harness.configuration)
            harness.engine.emitConnection(.connected(path: .direct))
            harness.receiveControl(harness.clientHello(messageID: 1, supportsStylus: true))
            harness.receiveControl(harness.videoAccepted(messageID: 2))
            var envelope = harness.stylus(messageID: 3)
            switch mutation {
            case "combinedTilt":
                envelope.stylusEvent.tiltXDegrees = 90
                envelope.stylusEvent.tiltYDegrees = 90
            case "terminalPressure":
                envelope.stylusEvent.phase = .ended
                envelope.stylusEvent.pressure = 0.1
            case "wrongStream":
                var target = VSInputTarget()
                target.streamID = 2
                envelope.stylusEvent.target = target
            default:
                var target = VSInputTarget()
                target.displayID = "wrong-display"
                target.streamID = 1
                envelope.stylusEvent.target = target
            }
            harness.receiveControl(envelope)
            XCTAssertTrue(harness.waitForFailure())
        }

        let mismatch = try Harness()
        try mismatch.session.start(configuration: mismatch.configuration)
        mismatch.engine.emitConnection(.connected(path: .direct))
        mismatch.receiveControl(mismatch.clientHello(messageID: 1, supportsStylus: true))
        mismatch.receiveControl(mismatch.videoAccepted(messageID: 2))
        mismatch.receiveControl(mismatch.stylus(messageID: 3))
        var changed = mismatch.stylus(messageID: 4)
        changed.stylusEvent.pointerID = 4
        changed.stylusEvent.phase = .changed
        mismatch.receiveControl(changed)
        XCTAssertTrue(mismatch.waitForFailure())
    }

    func testInternetNegotiatesAndRoutesExtendedHoverEraserWithButtons() throws {
        let harness = try Harness()
        let routed = expectation(description: "extended stylus routed")
        harness.session.onAuthenticatedStylusEvent = {
            epoch, inputID, pointerID, x, y, phase, pressure, tiltX, tiltY,
            toolKind, buttonMask, contactState in
            XCTAssertEqual(epoch, 1)
            XCTAssertEqual(inputID, 8)
            XCTAssertEqual(pointerID, 3)
            XCTAssertEqual(x, 0.25)
            XCTAssertEqual(y, 0.75)
            XCTAssertEqual(phase, .began)
            XCTAssertEqual(pressure, 0)
            XCTAssertEqual(tiltX, 45)
            XCTAssertEqual(tiltY, -45)
            XCTAssertEqual(toolKind, .eraser)
            XCTAssertEqual(buttonMask, 0b11)
            XCTAssertEqual(contactState, .proximity)
            routed.fulfill()
            return true
        }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(
            messageID: 1,
            supportsStylus: true,
            supportsStylusExtended: true
        ))
        XCTAssertTrue(harness.waitForSentControlCount(3))
        let controls = try harness.engine.sentPlaintext
            .filter { $0.channel == .control }
            .prefix(2)
            .map { try VSEnvelope(serializedBytes: $0.payload) }
        XCTAssertTrue(controls[0].hostHello.capabilities.contains(.stylusExtended))
        XCTAssertTrue(controls[1].sessionAccepted.negotiatedCapabilities.contains(.stylusExtended))

        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.receiveControl(harness.extendedStylus(
            messageID: 3,
            toolKind: .eraser,
            buttonMask: 0b11,
            contactState: .proximity,
            pressure: 0
        ))
        wait(for: [routed], timeout: 1)
    }

    func testInternetFailsClosedForInvalidExtendedStylusNegotiationAndFields() throws {
        let cases: [(String, Bool, (inout VSStylusEvent) -> Void)] = [
            ("unnegotiated extension", false, {
                $0.toolKind = .eraser
                $0.contactState = .proximity
                $0.pressure = 0
            }),
            ("reserved button bit", true, {
                $0.toolKind = .pen
                $0.contactState = .contact
                $0.buttonMask = 0b100
            }),
            ("hover pressure", true, {
                $0.toolKind = .pen
                $0.contactState = .proximity
                $0.pressure = 0.25
            }),
        ]

        for (name, supportsExtended, mutate) in cases {
            let harness = try Harness()
            try harness.session.start(configuration: harness.configuration)
            harness.engine.emitConnection(.connected(path: .direct))
            harness.receiveControl(harness.clientHello(
                messageID: 1,
                supportsStylus: true,
                supportsStylusExtended: supportsExtended
            ))
            harness.receiveControl(harness.videoAccepted(messageID: 2))
            var envelope = harness.stylus(messageID: 3)
            var stylus = envelope.stylusEvent
            mutate(&stylus)
            envelope.stylusEvent = stylus
            harness.receiveControl(envelope)
            XCTAssertTrue(harness.waitForFailure(), name)
        }
    }

    func testInternetNegotiatesRoutesAndSoftRejectsControllers() throws {
        let harness = try Harness(controllerAvailable: true)
        let routed = expectation(description: "controllers routed")
        routed.expectedFulfillmentCount = 7
        let routedEvents = TestLockedArray<GameControllerInputEvent>()
        harness.session.onAuthenticatedControllerEvent = { epoch, _, event in
            XCTAssertEqual(epoch, 1)
            routedEvents.append(event)
            routed.fulfill()
            return true
        }

        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        XCTAssertTrue(harness.waitForSentControlCount(3))
        let negotiation = try harness.engine.sentPlaintext
            .filter { $0.channel == .control }
            .prefix(2)
            .map { try VSEnvelope(serializedBytes: $0.payload) }
        XCTAssertTrue(negotiation[0].hostHello.capabilities.contains(.controller))
        XCTAssertTrue(negotiation[1].sessionAccepted.negotiatedCapabilities.contains(.controller))
        harness.receiveControl(harness.videoAccepted(messageID: 2))

        for index in 0..<4 {
            harness.receiveControl(harness.controller(
                messageID: UInt64(index + 3),
                inputID: UInt64(index + 1),
                controllerID: "pad-\(index + 1)",
                kind: .connected
            ))
            XCTAssertTrue(harness.waitForInputAck(inputID: UInt64(index + 1)))
            let acceptedEnvelope = try XCTUnwrap(
                harness.sentInputAckEnvelope(inputID: UInt64(index + 1))
            )
            XCTAssertTrue(acceptedEnvelope.inputAck.accepted)
            XCTAssertTrue(acceptedEnvelope.inputAck.rejectionReason.isEmpty)
            XCTAssertEqual(acceptedEnvelope.correlationID, UInt64(index + 3))
            XCTAssertEqual(acceptedEnvelope.sessionID, Data("product-session".utf8))
            XCTAssertEqual(acceptedEnvelope.sessionEpoch, 1)
        }
        harness.receiveControl(harness.controller(
            messageID: 7,
            inputID: 5,
            controllerID: "pad-5",
            kind: .connected
        ))
        XCTAssertTrue(harness.waitForInputAck(inputID: 5))
        let acknowledgement = try XCTUnwrap(harness.sentInputAck(inputID: 5))
        XCTAssertFalse(acknowledgement.accepted)
        XCTAssertEqual(
            acknowledgement.rejectionReason,
            "maximum_active_controllers_exceeded"
        )
        XCTAssertEqual(
            try XCTUnwrap(harness.sentInputAckEnvelope(inputID: 5)).correlationID,
            7
        )
        let rejectedEnvelope = try XCTUnwrap(harness.sentInputAckEnvelope(inputID: 5))
        XCTAssertEqual(rejectedEnvelope.sessionID, Data("product-session".utf8))
        XCTAssertEqual(rejectedEnvelope.sessionEpoch, 1)
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))

        harness.receiveControl(harness.controller(
            messageID: 8,
            inputID: 6,
            controllerID: "pad-1",
            kind: .state,
            buttonMask: 1
        ))
        harness.receiveControl(harness.controller(
            messageID: 9,
            inputID: 7,
            controllerID: "pad-2",
            kind: .disconnected
        ))
        harness.receiveControl(harness.controller(
            messageID: 10,
            inputID: 8,
            controllerID: "pad-5",
            controllerEpoch: 2,
            kind: .connected
        ))
        wait(for: [routed], timeout: 1)
        XCTAssertNil(harness.sentInputAck(inputID: 6))
        XCTAssertNil(harness.sentInputAck(inputID: 7))
        for inputID in UInt64(1)...4 {
            XCTAssertEqual(harness.sentInputAckCount(inputID: inputID), 1)
        }

        let events = routedEvents.snapshot()
        XCTAssertEqual(events.count, 7)
        XCTAssertEqual(events[4].state.buttonMask, 1)
        XCTAssertEqual(events[5].kind, .disconnected)
        XCTAssertEqual(events[6].controllerID, "pad-5")
        XCTAssertEqual(events[6].controllerEpoch, 2)
    }

    func testInternetControllerInjectionFailureClosesSession() throws {
        let harness = try Harness(controllerAvailable: true)
        harness.session.onAuthenticatedControllerEvent = { _, _, _ in false }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))

        XCTAssertTrue(harness.waitForProtocolError())
        let errorEnvelope = try XCTUnwrap(harness.sentProtocolErrorEnvelope())
        XCTAssertEqual(errorEnvelope.protocolError.code, .invalidState)
        XCTAssertTrue(errorEnvelope.protocolError.message.contains("Controller injection failed"))
        XCTAssertFalse(errorEnvelope.protocolError.retryable)
        XCTAssertEqual(errorEnvelope.protocolError.component, "macos-host-internet-session")
        XCTAssertEqual(errorEnvelope.correlationID, 3)
        XCTAssertEqual(errorEnvelope.sessionID, Data("product-session".utf8))
        XCTAssertEqual(errorEnvelope.sessionEpoch, 1)
        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertNil(harness.sentInputAck(inputID: 1))
    }

    func testInternetControllerInjectionFailureDrainsProtocolErrorBeforeClose() throws {
        let harness = try Harness(controllerAvailable: true)
        harness.session.onAuthenticatedControllerEvent = { _, _, _ in false }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.engine.deferNextControlSendCompletion()

        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))

        XCTAssertFalse(harness.waitForProtocolError(timeout: 0.05))
        XCTAssertFalse(harness.engine.didClose)
        XCTAssertNil(harness.sentInputAck(inputID: 1))
        harness.engine.completeDeferredControlSend(succeeded: true)
        XCTAssertTrue(harness.waitForProtocolError())
        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
    }

    func testInternetControllerProtocolErrorSendFailureStillClosesSession() throws {
        let harness = try Harness(controllerAvailable: true)
        harness.session.onAuthenticatedControllerEvent = { _, _, _ in false }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.engine.failNextControlSend()

        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))

        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertNil(harness.sentProtocolErrorEnvelope())
        XCTAssertNil(harness.sentInputAck(inputID: 1))
    }

    func testInternetControllerProtocolErrorAdmissionFailureStillClosesSession() throws {
        let harness = try Harness(controllerAvailable: true)
        harness.session.onAuthenticatedControllerEvent = { _, _, _ in
            harness.engine.emitConnection(.closed)
            return false
        }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))

        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))

        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertNil(harness.sentProtocolErrorEnvelope())
        XCTAssertNil(harness.sentInputAck(inputID: 1))
    }

    func testInternetControllerProtocolErrorDeferredSendFailureStillClosesSession() throws {
        let harness = try Harness(controllerAvailable: true)
        harness.session.onAuthenticatedControllerEvent = { _, _, _ in false }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.engine.deferNextControlSendCompletion()

        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))

        XCTAssertTrue(harness.waitForDeferredControlSend())
        XCTAssertFalse(harness.waitForFailure(timeout: 0.05))
        XCTAssertFalse(harness.engine.didClose)
        harness.engine.completeDeferredControlSend(succeeded: false)
        XCTAssertTrue(harness.waitForFailure(timeout: 2))
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertNil(harness.sentProtocolErrorEnvelope())
        XCTAssertNil(harness.sentInputAck(inputID: 1))
    }

    func testInternetControllerProtocolErrorDrainTimeoutFailsClosed() throws {
        let harness = try Harness(controllerAvailable: true)
        harness.session.onAuthenticatedControllerEvent = { _, _, _ in false }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.engine.deferNextControlSendCompletion()

        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))

        XCTAssertTrue(harness.waitForDeferredControlSend())
        XCTAssertTrue(harness.waitForFailure(timeout: 2))
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertNil(harness.sentProtocolErrorEnvelope())
        XCTAssertNil(harness.sentInputAck(inputID: 1))
    }

    func testInternetControllerProtocolErrorDrainRejectsFreshSessionRecovery() throws {
        let harness = try Harness(controllerAvailable: true)
        let recoveryRequests = TestLockedArray<Int>()
        harness.session.onFreshSessionRecoveryRequired = { recoveryRequests.append($0) }
        harness.session.onAuthenticatedControllerEvent = { _, _, _ in false }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.engine.deferNextControlSendCompletion()

        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))
        XCTAssertTrue(harness.waitForDeferredControlSend())
        harness.engine.emitPath(.init(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "controller-drain-wifi"
        ))
        harness.engine.emitPath(.init(
            interface: .wiredEthernet,
            isSatisfied: true,
            fingerprint: "controller-drain-ethernet"
        ))

        XCTAssertTrue(harness.waitForFailure(timeout: 2))
        XCTAssertTrue(recoveryRequests.snapshot().isEmpty)
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertNil(harness.sentInputAck(inputID: 1))
    }

    func testInternetControllerProtocolErrorDrainIgnoresRemoteCloseUntilFailure() throws {
        let harness = try Harness(controllerAvailable: true)
        harness.session.onAuthenticatedControllerEvent = { _, _, _ in false }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.engine.deferNextControlSendCompletion()

        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))
        XCTAssertTrue(harness.waitForDeferredControlSend())
        harness.engine.emitConnection(.closed)

        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertNil(harness.sentInputAck(inputID: 1))
    }

    func testInternetControllerReentrantCloseDoesNotSendAcceptedAck() throws {
        let harness = try Harness(controllerAvailable: true)
        harness.session.onAuthenticatedControllerEvent = { _, _, _ in
            harness.session.close()
            return true
        }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))

        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))

        XCTAssertEqual(harness.session.snapshotState(), .closed)
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertNil(harness.sentProtocolErrorEnvelope())
        XCTAssertNil(harness.sentInputAck(inputID: 1))
    }

    func testInternetControllerReentrantReplacementDoesNotSendAcceptedAck() throws {
        let harness = try Harness(engineCount: 2, controllerAvailable: true)
        let replacement = try XCTUnwrap(harness.replacementEngine)
        let replacementConfiguration = try XCTUnwrap(harness.replacementConfiguration)
        let handledGeneration = TestLockedValue<UInt64>()
        harness.session.onAuthenticatedControllerEvent = { _, generation, _ in
            handledGeneration.store(generation)
            harness.session.close()
            do {
                try harness.session.start(configuration: replacementConfiguration)
            } catch {
                XCTFail("Replacing the Internet product session failed: \(error)")
            }
            return false
        }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))

        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))

        XCTAssertEqual(harness.session.snapshotState(), .connecting)
        XCTAssertEqual(handledGeneration.load(), 1)
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertTrue(replacement.didStart)
        XCTAssertNil(harness.sentProtocolErrorEnvelope())
        XCTAssertNil(harness.sentInputAck(inputID: 1))
        XCTAssertNil(harness.sentInputAck(inputID: 1, engineIndex: 1))
    }

    func testInternetMissingControllerHandlerClosesSession() throws {
        let harness = try Harness(controllerAvailable: true)
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))

        XCTAssertTrue(harness.waitForProtocolError())
        let errorEnvelope = try XCTUnwrap(harness.sentProtocolErrorEnvelope())
        XCTAssertEqual(errorEnvelope.protocolError.code, .invalidState)
        XCTAssertTrue(errorEnvelope.protocolError.message.contains("Controller injection failed"))
        XCTAssertFalse(errorEnvelope.protocolError.retryable)
        XCTAssertEqual(errorEnvelope.protocolError.component, "macos-host-internet-session")
        XCTAssertEqual(errorEnvelope.correlationID, 3)
        XCTAssertEqual(errorEnvelope.sessionID, Data("product-session".utf8))
        XCTAssertEqual(errorEnvelope.sessionEpoch, 1)
        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertNil(harness.sentInputAck(inputID: 1))
    }

    func testInternetControllerForeignTargetClosesSession() throws {
        let harness = try Harness(controllerAvailable: true)
        harness.session.onAuthenticatedControllerEvent = { _, _, _ in true }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        var envelope = harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        )
        var target = VSInputTarget()
        target.displayID = "wrong-display"
        target.streamID = 1
        envelope.controllerEvent.target = target

        harness.receiveControl(envelope)

        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
    }

    func testInternetControllerSurvivesCompletedVideoReconfiguration() throws {
        let harness = try Harness(controllerAvailable: true)
        let stateRouted = expectation(description: "controller state routed after reconfiguration")
        harness.session.onAuthenticatedControllerEvent = { _, _, event in
            if event.kind == .state { stateRouted.fulfill() }
            return true
        }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))
        XCTAssertTrue(harness.waitForInputAck(inputID: 1))

        try harness.session.updateRotation(90)
        harness.receiveControl(harness.videoAccepted(messageID: 4, configEpoch: 2))
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
        harness.receiveControl(harness.controller(
            messageID: 5,
            inputID: 2,
            controllerID: "pad-1",
            kind: .state,
            buttonMask: 1
        ))

        wait(for: [stateRouted], timeout: 1)
        XCTAssertFalse(harness.engine.didClose)
    }

    func testInternetAllowsControllerDisconnectDuringVideoReconfiguration() throws {
        let harness = try Harness(controllerAvailable: true)
        let disconnected = expectation(description: "controller disconnected during reconfiguration")
        harness.session.onAuthenticatedControllerEvent = { _, _, event in
            if event.kind == .disconnected { disconnected.fulfill() }
            return true
        }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1, supportsController: true))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        harness.receiveControl(harness.controller(
            messageID: 3,
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        ))
        XCTAssertTrue(harness.waitForInputAck(inputID: 1))
        try harness.session.updateRotation(90)
        XCTAssertEqual(harness.session.snapshotState(), .awaitingVideoConfiguration)

        harness.receiveControl(harness.controller(
            messageID: 4,
            inputID: 2,
            controllerID: "pad-1",
            kind: .disconnected
        ))
        wait(for: [disconnected], timeout: 1)
        XCTAssertNil(harness.sentInputAck(inputID: 2))
        XCTAssertEqual(harness.session.snapshotState(), .awaitingVideoConfiguration)
        XCTAssertFalse(harness.engine.didClose)
    }

    func testNetworkChangeRequestsFreshSessionInsteadOfSecondOffer() throws {
        let harness = try Harness()
        let authenticating = expectation(description: "authenticating")
        let recovery = expectation(description: "fresh recovery")
        harness.session.onStateChanged = { state in
            if state == .authenticating { authenticating.fulfill() }
        }
        harness.session.onFreshSessionRecoveryRequired = { attempt in
            XCTAssertEqual(attempt, 1)
            recovery.fulfill()
        }

        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        wait(for: [authenticating], timeout: 1)
        harness.engine.emitPath(.init(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        harness.engine.emitPath(.init(interface: .wiredEthernet, isSatisfied: true, fingerprint: "ethernet-b"))

        wait(for: [recovery], timeout: 1)
        XCTAssertEqual(harness.engine.restartICECount, 0)
        XCTAssertEqual(harness.session.snapshotState(), .recovering(attempt: 1))
    }

    func testRecoveringStateCallbackCanSynchronouslyInstallFreshSession() throws {
        let harness = try Harness(
            engineCount: 2,
            freshSessionRecoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        let replacement = try XCTUnwrap(harness.replacementEngine)
        let replacementInstalled = expectation(description: "replacement installed")
        let secondRecoveryRequested = expectation(description: "second recovery requested")
        var installedReplacement = false
        var freshSessionAttempts: [Int] = []
        harness.session.onStateChanged = { state in
            guard state == .recovering(attempt: 1), !installedReplacement else { return }
            installedReplacement = true
            do {
                try harness.session.provideFreshSession(configuration: harness.configuration)
                replacementInstalled.fulfill()
            } catch {
                XCTFail("Installing the fresh session failed: \(error)")
            }
        }
        harness.session.onFreshSessionRecoveryRequired = { attempt in
            freshSessionAttempts.append(attempt)
            if attempt == 2 { secondRecoveryRequested.fulfill() }
        }

        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.engine.emitPath(.init(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        harness.engine.emitPath(.init(interface: .wiredEthernet, isSatisfied: true, fingerprint: "ethernet-b"))

        wait(for: [replacementInstalled], timeout: 1)
        XCTAssertTrue(installedReplacement)
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertTrue(replacement.didStart)
        XCTAssertFalse(replacement.didClose)
        XCTAssertFalse(replacement.startedAfterClose)
        XCTAssertEqual(harness.session.snapshotState(), .connecting)
        XCTAssertTrue(freshSessionAttempts.isEmpty)

        replacement.emitConnection(.connected(path: .direct))
        XCTAssertEqual(harness.session.snapshotState(), .authenticating)
        replacement.emitPath(.init(interface: .wifi, isSatisfied: true, fingerprint: "wifi-c"))
        replacement.emitPath(.init(interface: .wiredEthernet, isSatisfied: true, fingerprint: "ethernet-d"))

        wait(for: [secondRecoveryRequested], timeout: 1)
        XCTAssertEqual(harness.session.snapshotState(), .recovering(attempt: 2))
        XCTAssertEqual(freshSessionAttempts, [2])
        XCTAssertTrue(replacement.didClose)
    }

    func testRecoveringCallbackClosePreventsFreshProfileRequest() throws {
        let harness = try Harness()
        var recoveryRequests = 0
        harness.session.onStateChanged = { state in
            if case .recovering = state { harness.session.close() }
        }
        harness.session.onFreshSessionRecoveryRequired = { _ in recoveryRequests += 1 }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))

        harness.engine.emitConnection(.disconnected)

        XCTAssertEqual(harness.session.snapshotState(), .closed)
        XCTAssertEqual(recoveryRequests, 0)
        XCTAssertEqual(harness.engine.closeCount, 1)
    }

    func testConnectingCallbackCannotCloseBeforeTransportStarts() throws {
        let harness = try Harness()
        harness.session.onStateChanged = { state in
            if state == .connecting { harness.session.close() }
        }

        try harness.session.start(configuration: harness.configuration)

        XCTAssertTrue(harness.engine.didStart)
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertFalse(harness.engine.startedAfterClose)
        XCTAssertEqual(harness.session.snapshotState(), .closed)
    }

    func testTouchCallbackCannotRestoreCodecAfterReentrantClose() throws {
        let harness = try Harness()
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
        harness.session.onAuthenticatedTouchEvent = { _, _, _, _, _, _, _, _ in
            harness.session.close()
            return true
        }

        harness.receiveControl(harness.touch(messageID: 3))

        XCTAssertEqual(harness.session.snapshotState(), .closed)
        XCTAssertEqual(harness.session.currentSessionEpoch, 0)
    }

    func testFrameAdmissionKeepsOnlyLatestQueuedFrame() throws {
        let harness = try Harness()
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        let touchEntered = DispatchSemaphore(value: 0)
        let releaseTouch = DispatchSemaphore(value: 0)
        harness.session.onAuthenticatedTouchEvent = { _, _, _, _, _, _, _, _ in
            touchEntered.signal()
            _ = releaseTouch.wait(timeout: .now() + 1)
            return true
        }
        DispatchQueue.global().async {
            harness.receiveControl(harness.touch(messageID: 3))
        }
        XCTAssertEqual(touchEntered.wait(timeout: .now() + 1), .success)

        harness.session.sendFrame(Data([1]), timestamp: 1, isKeyframe: true, sessionEpoch: 1)
        harness.session.sendFrame(Data([2]), timestamp: 2, isKeyframe: true, sessionEpoch: 1)
        harness.session.sendFrame(Data([3]), timestamp: 3, isKeyframe: true, sessionEpoch: 1)
        releaseTouch.signal()

        XCTAssertTrue(harness.waitForSentMediaCount(1))
        let mediaPayloads = try harness.engine.sentPlaintext
            .filter { $0.channel == .media }
            .map { try ProtocolV1MediaPacketCodec.decode($0.payload).payload }
        XCTAssertEqual(mediaPayloads, [Data([3])])
    }

    func testStaleSessionEpochCannotReplacePendingFrameOrFailCurrentSession() throws {
        let harness = try Harness()
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        let touchEntered = DispatchSemaphore(value: 0)
        let releaseTouch = DispatchSemaphore(value: 0)
        harness.session.onAuthenticatedTouchEvent = { _, _, _, _, _, _, _, _ in
            touchEntered.signal()
            _ = releaseTouch.wait(timeout: .now() + 1)
            return true
        }
        DispatchQueue.global().async { harness.receiveControl(harness.touch(messageID: 3)) }
        XCTAssertEqual(touchEntered.wait(timeout: .now() + 1), .success)

        harness.session.sendFrame(Data([7]), timestamp: 7, isKeyframe: true, sessionEpoch: 1)
        harness.session.sendFrame(Data([8]), timestamp: 8, isKeyframe: true, sessionEpoch: 0)
        harness.session.sendFrame(
            Data(repeating: 9, count: harness.configuration.limits.maximumMediaFrameBytes + 1),
            timestamp: 9,
            isKeyframe: true,
            sessionEpoch: 0
        )
        releaseTouch.signal()

        XCTAssertTrue(harness.waitForSentMediaCount(1))
        let payload = try ProtocolV1MediaPacketCodec.decode(
            harness.engine.sentPlaintext.first { $0.channel == .media }!.payload
        ).payload
        XCTAssertEqual(payload, Data([7]))
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
    }

    func testCloseIsIdempotentAndReentrantClosedCallbackPublishesOnce() throws {
        let harness = try Harness()
        var closedCount = 0
        harness.session.onStateChanged = { state in
            guard state == .closed else { return }
            closedCount += 1
            harness.session.close()
        }
        try harness.session.start(configuration: harness.configuration)

        harness.session.close()
        harness.session.close()

        XCTAssertEqual(closedCount, 1)
        XCTAssertEqual(harness.engine.closeCount, 1)
    }

    func testInboundControlAdmissionFailsClosedBeforeQueueGrowth() throws {
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 1_024,
            maximumBufferedControlBytes: 4_096,
            maximumBufferedControlMessages: 2,
            maximumMediaFrameBytes: 1_024,
            maximumRelayBytesPerSession: 1_000_000
        )
        let harness = try Harness(limits: limits)
        let streaming = expectation(description: "streaming")
        harness.session.onStateChanged = { state in
            if state == .streaming(.direct) { streaming.fulfill() }
        }
        let touchEntered = DispatchSemaphore(value: 0)
        let releaseTouch = DispatchSemaphore(value: 0)
        harness.session.onAuthenticatedTouchEvent = { _, _, _, _, _, _, _, _ in
            touchEntered.signal()
            _ = releaseTouch.wait(timeout: .now() + 1)
            return true
        }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1))
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        wait(for: [streaming], timeout: 1)
        DispatchQueue.global().async {
            harness.receiveControl(harness.touch(messageID: 3))
        }
        XCTAssertEqual(touchEntered.wait(timeout: .now() + 1), .success)

        harness.receiveControl(harness.ping(messageID: 4, sequence: 1))
        harness.receiveControl(harness.ping(messageID: 5, sequence: 2))
        releaseTouch.signal()

        let deadline = Date().addingTimeInterval(1)
        while Date() < deadline {
            if case .failed = harness.session.snapshotState() { break }
            Thread.sleep(forTimeInterval: 0.005)
        }
        guard case .failed(let reason) = harness.session.snapshotState() else {
            return XCTFail("Inbound control overload must fail closed")
        }
        XCTAssertTrue(reason.contains("backlog"))
    }

    func testLegacyClientMissingRequiredTransportBoundaryFailsBeforeHostControls() throws {
        for removedCapability in [
            VSCapability.mediaRecordFragmentation,
            .audioDataChannel,
            .bulkDataChannel,
        ] {
            let harness = try Harness()
            let authenticating = expectation(description: "authenticating \(removedCapability)")
            let failed = expectation(description: "legacy client rejected \(removedCapability)")
            harness.session.onStateChanged = { state in
                if state == .authenticating { authenticating.fulfill() }
                if case .failed = state { failed.fulfill() }
            }

            try harness.session.start(configuration: harness.configuration)
            harness.engine.emitConnection(.connected(path: .direct))
            wait(for: [authenticating], timeout: 1)
            var legacyHello = harness.clientHello(messageID: 1)
            legacyHello.clientHello.capabilities.removeAll { $0 == removedCapability }
            legacyHello.clientHello.requiredCapabilities.removeAll { $0 == removedCapability }
            if removedCapability == .mediaRecordFragmentation {
                legacyHello.clientHello.resourceLimits.maximumEncryptedMediaRecordBytes = 0
            }
            harness.receiveControl(legacyHello)

            wait(for: [failed], timeout: 1)
            XCTAssertTrue(harness.engine.sentPlaintext.filter { $0.channel == .control }.isEmpty)
            XCTAssertTrue(harness.engine.didClose)
        }
    }

    func testSecurityFactoryEpochMismatchClosesTemporaryCipherAndReportsCleanupFailure() throws {
        let harness = try Harness()
        var cleanupCalled = false
        let mismatched = InternetProductSecuritySession(
            sessionEpoch: 2,
            packetCipher: harness.securitySession.packetCipher,
            cleanup: {
                cleanupCalled = true
                throw PlatformSecurityError.persistenceFailure("injected cleanup failure")
            }
        )
        let session = InternetProductSession(
            engineFactory: { harness.engine },
            securitySessionFactory: { _ in mismatched },
            revocationHandler: { _, _ in nil }
        )

        XCTAssertThrowsError(try session.start(configuration: harness.configuration)) { error in
            let message = error.localizedDescription
            XCTAssertTrue(message.contains("authority-agreed session epoch"))
            XCTAssertTrue(message.contains("injected cleanup failure"))
        }
        XCTAssertTrue(cleanupCalled)
        XCTAssertFalse(harness.engine.didClose)
    }

    func testAuthenticationNegotiationDeadlineFailsAndClosesTransport() throws {
        let harness = try Harness(negotiationTimeoutMilliseconds: 20)
        let failed = expectation(description: "negotiation failed")
        harness.session.onStateChanged = { state in
            if case .failed(let reason) = state,
               reason.contains("negotiation before the deadline") {
                failed.fulfill()
            }
        }

        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))

        wait(for: [failed], timeout: 1)
        XCTAssertTrue(harness.engine.didClose)
    }

    func testUnknownCandidatePathNeverPublishesDirectProductState() throws {
        let harness = try Harness()
        let failed = expectation(description: "unknown candidate path failed closed")
        harness.session.onStateChanged = { state in
            if case .failed = state { failed.fulfill() }
        }
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .unknown))

        wait(for: [failed], timeout: 1)
        guard case .failed(let reason) = harness.session.snapshotState() else {
            return XCTFail("Unknown route must fail closed")
        }
        XCTAssertTrue(reason.contains("selected ICE candidate"))
        XCTAssertTrue(harness.engine.didClose)
    }

    func testVideoConfigurationNegotiationDeadlineIsRearmed() throws {
        let harness = try Harness(negotiationTimeoutMilliseconds: 40)
        let awaiting = expectation(description: "awaiting video")
        let failed = expectation(description: "video negotiation failed")
        harness.session.onStateChanged = { state in
            if state == .awaitingVideoConfiguration { awaiting.fulfill() }
            if case .failed = state { failed.fulfill() }
        }

        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1))

        wait(for: [awaiting, failed], timeout: 1)
        XCTAssertTrue(harness.engine.didClose)
    }

    func testRevocationPersistsBeforeClosingAndRejectsFurtherFrames() throws {
        let harness = try Harness()
        let revoked = expectation(description: "revoked")
        let propagation = expectation(description: "revocation propagation")
        let revokeFinished = expectation(description: "revoke finished")
        let revocationHandlerEntered = DispatchSemaphore(value: 0)
        let releaseRevocationHandler = DispatchSemaphore(value: 0)
        var persistedSequence: UInt64?
        var sessionReference: InternetProductSession?
        let tombstone = PairedDeviceRevocationTombstone(
            peerIdentity: harness.configuration.peerIdentity,
            sequence: 8,
            revokedAtUnixSeconds: 1,
            nonce: Data(repeating: 1, count: 32),
            reasonCode: "user_revoked",
            authority: PlatformPublicIdentity(
                deviceID: "host-1",
                keyID: String(repeating: "b", count: 64),
                keyEpoch: 1,
                signingPublicKey: Data([UInt8(0x04)] + Array(repeating: UInt8(0x22), count: 64))
            ),
            authoritySignature: Data([1])
        )
        let session = InternetProductSession(
            engineFactory: { harness.engine },
            securitySessionFactory: { _ in harness.securitySession },
            revocationHandler: { _, sequence in
                XCTAssertTrue(harness.engine.didClose)
                XCTAssertEqual(sessionReference?.snapshotState(), .revoked)
                XCTAssertThrowsError(try sessionReference?.start(configuration: harness.configuration))
                persistedSequence = sequence
                revocationHandlerEntered.signal()
                _ = releaseRevocationHandler.wait(timeout: .now() + 1)
                return tombstone
            }
        )
        sessionReference = session
        session.onRevoked = { revoked.fulfill() }
        session.onRevocationPropagationRequired = { received in
            XCTAssertEqual(received, tombstone)
            XCTAssertTrue(harness.engine.didClose)
            XCTAssertEqual(session.snapshotState(), .revoked)
            propagation.fulfill()
        }

        try session.start(configuration: harness.configuration)
        DispatchQueue.global().async {
            do {
                try session.revoke(sequence: 8)
            } catch {
                XCTFail("Revoking the session failed: \(error)")
            }
            revokeFinished.fulfill()
        }
        XCTAssertEqual(revocationHandlerEntered.wait(timeout: .now() + 1), .success)
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertEqual(session.snapshotState(), .revoked)
        releaseRevocationHandler.signal()
        wait(for: [propagation, revoked, revokeFinished], timeout: 1)

        XCTAssertEqual(persistedSequence, 8)
        XCTAssertEqual(session.snapshotState(), .revoked)
        XCTAssertTrue(harness.engine.didClose)
        let count = harness.engine.sentPlaintext.count
        session.sendFrame(Data([1]), timestamp: 1, isKeyframe: true, sessionEpoch: 1)
        Thread.sleep(forTimeInterval: 0.05)
        XCTAssertEqual(harness.engine.sentPlaintext.count, count)
    }

    func testProductSelfTestControlQueueResumesWhenTransmissionContextReturns() throws {
        let engine = ProductHarnessTransmissionEngine()
        let harness = ProductDeviceHarness(
            engine: engine,
            configuration: WebRTCTransportConfiguration(
                iceServers: [],
                peerIdentity: "device-key",
                sessionIdentifier: "product-harness-context-restore",
                forceRelay: false
            ),
            sessionID: Data("product-harness-context-restore".utf8)
        )
        try harness.start()

        engine.emitConnection(.connected(path: .direct))
        XCTAssertTrue(engine.sentPayloads.isEmpty)

        engine.emitTransmissionContext(
            WebRTCEngineTransmissionContext(epoch: 1, path: .direct)
        )

        let sent = try XCTUnwrap(engine.sentPayloads.first)
        let envelope = try VSEnvelope(serializedBytes: sent)
        guard case .clientHello = envelope.payload else {
            return XCTFail("Restored context must resume the queued ClientHello.")
        }
        XCTAssertTrue(harness.failures.isEmpty)
    }

    // MARK: - Adaptive video state machine

    private func constrainedSample() -> InternetNetworkQualitySample {
        InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 500,
            packetLossFraction: 0.2,
            availableOutgoingBitrateBps: 1_000_000
        )
    }

    private func balancedSample() -> InternetNetworkQualitySample {
        InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 300,
            packetLossFraction: 0.06,
            availableOutgoingBitrateBps: 5_000_000
        )
    }
    private func goodSample() -> InternetNetworkQualitySample {
        InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 100,
            packetLossFraction: 0.01,
            availableOutgoingBitrateBps: 10_000_000
        )
    }

    private func appliedVideo(
        width: Int = 960,
        height: Int = 540,
        framesPerSecond: Int = 20,
        bitrateKbps: Int = 3_000
    ) -> InternetProductVideoConfiguration {
        InternetProductVideoConfiguration(
            codec: .hevc,
            width: width,
            height: height,
            framesPerSecond: framesPerSecond,
            bitrateKbps: bitrateKbps
        )
    }

    private func reachStreaming(_ harness: Harness) throws {
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1))
        harness.receiveControl(harness.videoAccepted(
            messageID: 2,
            configEpoch: harness.configuration.video.configEpoch
        ))
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
    }

    func testInitialVideoAckWithWrongEpochFailsClosed() throws {
        let harness = try Harness()
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1))
        XCTAssertTrue(harness.waitForSentControlCount(3))

        harness.receiveControl(harness.videoAccepted(messageID: 2, configEpoch: 2))

        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
    }

    func testRuntimeRotationPartialControlSendFailsClosed() throws {
        let harness = try Harness()
        try reachStreaming(harness)
        harness.engine.invalidateTransmissionContextOnNextControlSend()

        XCTAssertThrowsError(try harness.session.updateRotation(90))

        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
        let runtimeControls = try harness.engine.sentPlaintext
            .filter { $0.channel == .control }
            .suffix(1)
            .map { try VSEnvelope(serializedBytes: $0.payload) }
        guard case .displayChanged = runtimeControls.first?.payload else {
            return XCTFail("The first rotation control should be sent before the second is rejected")
        }
    }

    func testAdaptivePendingAndAwaitingGateMediaFrames() throws {
        let harness = try Harness()
        let requested = expectation(description: "adaptive profile requested")
        var capturedToken: InternetAdaptiveRequestToken?
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            capturedToken = token
            requested.fulfill()
        }

        try reachStreaming(harness)

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        let token = try XCTUnwrap(capturedToken)

        // Pending adaptive request must gate outbound media.
        let beforePending = harness.engine.sentPlaintext.filter { $0.channel == .media }.count
        harness.session.sendFrame(Data([0xAA]), timestamp: 1, isKeyframe: true, sessionEpoch: 1)
        Thread.sleep(forTimeInterval: 0.05)
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .media }.count,
            beforePending,
            "Frames must be dropped while an adaptive request is pending"
        )

        // Completing the profile moves the session into awaitingVideoConfiguration,
        // which must keep gating media until the peer acknowledges the new config.
        try harness.session.completeAdaptiveProfile(token: token, appliedVideo: appliedVideo())
        let beforeAwaiting = harness.engine.sentPlaintext.filter { $0.channel == .media }.count
        harness.session.sendFrame(Data([0xBB]), timestamp: 2, isKeyframe: true, sessionEpoch: 1)
        Thread.sleep(forTimeInterval: 0.05)
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .media }.count,
            beforeAwaiting,
            "Frames must be dropped while awaiting the peer video configuration ACK"
        )

        harness.receiveControl(harness.videoAccepted(messageID: 3, configEpoch: 2))
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))

        // After the ACK commits the configuration, media flows again.
        harness.session.sendFrame(Data([0xCC]), timestamp: 3, isKeyframe: true, sessionEpoch: 1)
        XCTAssertTrue(harness.waitForSentMediaCount(beforeAwaiting + 1))
    }

    func testAdaptiveAckCommitsConfigurationAndRequestsKeyframe() throws {
        let harness = try Harness()
        let requested = expectation(description: "adaptive profile requested")
        let committed = expectation(description: "adaptive profile committed")
        var capturedToken: InternetAdaptiveRequestToken?
        var keyframeCount = 0
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            capturedToken = token
            requested.fulfill()
        }
        harness.session.onAdaptiveProfileCommitted = { token, video in
            XCTAssertEqual(token, capturedToken)
            XCTAssertEqual(video.width, 960)
            XCTAssertEqual(video.height, 540)
            committed.fulfill()
        }
        harness.session.onKeyframeRequired = { keyframeCount += 1 }

        try reachStreaming(harness)
        let keyframesBeforeAdaptive = keyframeCount

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        let token = try XCTUnwrap(capturedToken)

        try harness.session.completeAdaptiveProfile(token: token, appliedVideo: appliedVideo())
        harness.receiveControl(harness.videoAccepted(messageID: 3, configEpoch: 2))

        wait(for: [committed], timeout: 1)
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
        XCTAssertGreaterThan(keyframeCount, keyframesBeforeAdaptive)
    }

    func testClientRejectionTriggersHostRollbackThatRestoresPreviousStream() throws {
        let harness = try Harness()
        let requested = expectation(description: "adaptive profile requested")
        let rollback = expectation(description: "adaptive rollback requested")
        let retried = expectation(description: "peer-rejected profile retried")
        var capturedToken: InternetAdaptiveRequestToken?
        var rollbackToken: InternetAdaptiveRequestToken?
        var requestCount = 0
        harness.session.onAdaptiveProfileRequested = { token, profile, _, _ in
            XCTAssertEqual(profile, AdaptiveMediaPolicy.constrained)
            requestCount += 1
            if requestCount == 1 {
                capturedToken = token
                requested.fulfill()
            } else if requestCount == 2 {
                retried.fulfill()
            }
        }
        harness.session.onAdaptiveProfileRollbackRequested = { token, committed, proposed in
            rollbackToken = token
            XCTAssertEqual(committed.width, 1920)
            XCTAssertEqual(proposed.width, 960)
            rollback.fulfill()
        }

        try reachStreaming(harness)

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        let token = try XCTUnwrap(capturedToken)

        try harness.session.completeAdaptiveProfile(token: token, appliedVideo: appliedVideo())
        harness.receiveControl(harness.videoRejected(messageID: 3, configEpoch: 2))

        wait(for: [rollback], timeout: 1)
        XCTAssertEqual(rollbackToken, token)

        let succeeded = harness.session.completeAdaptiveRollback(token: token, succeeded: true)
        XCTAssertTrue(succeeded)
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))

        // The previous (committed) stream must continue to flow after rollback.
        let before = harness.engine.sentPlaintext.filter { $0.channel == .media }.count
        harness.session.sendFrame(Data([0xDD]), timestamp: 4, isKeyframe: true, sessionEpoch: 1)
        XCTAssertTrue(harness.waitForSentMediaCount(before + 1))

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [retried], timeout: 1)
        XCTAssertEqual(requestCount, 2)
    }

    func testAdaptiveRollbackFailureFailsClosed() throws {
        let harness = try Harness()
        let requested = expectation(description: "adaptive profile requested")
        let rollback = expectation(description: "adaptive rollback requested")
        var capturedToken: InternetAdaptiveRequestToken?
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            capturedToken = token
            requested.fulfill()
        }
        harness.session.onAdaptiveProfileRollbackRequested = { _, _, _ in rollback.fulfill() }

        try reachStreaming(harness)

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        let token = try XCTUnwrap(capturedToken)

        try harness.session.completeAdaptiveProfile(token: token, appliedVideo: appliedVideo())
        harness.receiveControl(harness.videoRejected(messageID: 3, configEpoch: 2))
        wait(for: [rollback], timeout: 1)

        let succeeded = harness.session.completeAdaptiveRollback(token: token, succeeded: false)
        XCTAssertTrue(succeeded)
        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
    }

    func testAdaptiveAckTimeoutFailsClosedBecausePeerCommitIsUnknown() throws {
        let harness = try Harness(negotiationTimeoutMilliseconds: 30)
        let requested = expectation(description: "adaptive profile requested")
        let didCompleteHostApply = TestLockedValue<Bool>()
        let stateAfterHostApply = TestLockedValue<InternetProductSessionState>()
        let hostApplyError = TestLockedValue<Error>()
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            do {
                didCompleteHostApply.store(try harness.session.completeAdaptiveProfile(
                    token: token,
                    appliedVideo: self.appliedVideo()
                ))
                stateAfterHostApply.store(harness.session.snapshotState())
            } catch {
                hostApplyError.store(error)
            }
            requested.fulfill()
        }

        try reachStreaming(harness)

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        if let hostApplyError = hostApplyError.load() {
            return XCTFail("Adaptive host apply failed: " + String(describing: hostApplyError))
        }
        XCTAssertEqual(didCompleteHostApply.load(), true)
        XCTAssertEqual(stateAfterHostApply.load(), .awaitingVideoConfiguration)

        // The peer may have committed the new decoder epoch before its ACK was
        // delayed. Continuing on the old epoch would split host/client state,
        // so an ambiguous timeout must close the session.
        XCTAssertTrue(harness.waitForFailure())
        guard case .failed(let reason) = harness.session.snapshotState() else {
            return XCTFail("Expected the adaptive ACK deadline to fail the session.")
        }
        XCTAssertTrue(
            reason.contains("peer did not acknowledge"),
            "Expected peer-ACK timeout, got: " + reason
        )
        XCTAssertTrue(harness.engine.didClose)
    }

    func testAdaptiveHostApplyTimeoutFailsClosed() throws {
        let harness = try Harness(negotiationTimeoutMilliseconds: 30)
        let requested = expectation(description: "adaptive profile requested")
        harness.session.onAdaptiveProfileRequested = { _, _, _, _ in
            requested.fulfill()
        }

        try reachStreaming(harness)
        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)

        // The composition callback intentionally never completes or rejects the
        // request. The pending host apply gates media, so it must have the same
        // bounded fail-closed behavior as peer ACK and rollback waits.
        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
    }

    func testAdaptiveAckDeadlineStartsAfterHostApplyCompletes() throws {
        let testTimeoutMilliseconds: UInt32 = 200
        let hostApplyDelay: TimeInterval = 0.14
        let acknowledgmentDelay: TimeInterval = 0.10
        let harness = try Harness(
            negotiationTimeoutMilliseconds: testTimeoutMilliseconds
        )
        let workerReady = expectation(description: "adaptive deadline worker ready")
        let requested = expectation(description: "adaptive profile requested")
        let workerFinished = expectation(description: "adaptive deadline worker finished")
        let adaptiveStreaming = expectation(description: "adaptive video configuration accepted")
        let beginHostApply = DispatchSemaphore(value: 0)
        let worker = DispatchQueue(
            label: "dev.vibescreen.tests.adaptive-deadline",
            qos: .userInteractive
        )
        let capturedToken = TestLockedValue<InternetAdaptiveRequestToken>()
        let didCompleteHostApply = TestLockedValue<Bool>()
        let workerError = TestLockedValue<Error>()
        let stateBeforeAcknowledgment = TestLockedValue<InternetProductSessionState>()
        harness.session.onAdaptiveProfileCommitted = { _, _ in
            adaptiveStreaming.fulfill()
        }
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            capturedToken.store(token)
            requested.fulfill()
            beginHostApply.signal()
        }
        worker.async {
            workerReady.fulfill()
            beginHostApply.wait()
            // Each phase stays within the injected deadline, while their
            // combined duration exceeds it. A prewarmed high-priority worker
            // and monotonic waits avoid scheduler-dependent sleep overshoot.
            waitForMonotonicDuration(hostApplyDelay)
            do {
                guard let token = capturedToken.load() else {
                    throw InternetProductSessionError.invalidConfiguration(
                        "The adaptive request token was not published to the deadline worker."
                    )
                }
                let completed = try harness.session.completeAdaptiveProfile(
                    token: token,
                    appliedVideo: self.appliedVideo()
                )
                didCompleteHostApply.store(completed)
                guard completed else {
                    throw InternetProductSessionError.invalidConfiguration(
                        "The adaptive host apply did not complete on the deadline worker."
                    )
                }
                waitForMonotonicDuration(acknowledgmentDelay)
                stateBeforeAcknowledgment.store(harness.session.snapshotState())
                harness.receiveControl(
                    harness.videoAccepted(messageID: 3, configEpoch: 2)
                )
            } catch {
                workerError.store(error)
            }
            workerFinished.fulfill()
        }

        wait(for: [workerReady], timeout: 1)
        try reachStreaming(harness)
        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested, workerFinished], timeout: 5)
        if let workerError = workerError.load() {
            return XCTFail("Adaptive deadline worker failed: " + String(describing: workerError))
        }
        XCTAssertEqual(didCompleteHostApply.load(), true)
        wait(for: [adaptiveStreaming], timeout: 1)
        XCTAssertEqual(stateBeforeAcknowledgment.load(), .awaitingVideoConfiguration)
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
    }

    func testAdaptiveCodecFailureClearsPendingApplyAndFailsClosed() throws {
        let harness = try Harness(videoConfigEpoch: UInt64.max)
        let requested = expectation(description: "adaptive profile requested")
        var capturedToken: InternetAdaptiveRequestToken?
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            capturedToken = token
            requested.fulfill()
        }

        try reachStreaming(harness)
        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        let token = try XCTUnwrap(capturedToken)

        XCTAssertThrowsError(try harness.session.completeAdaptiveProfile(
            token: token,
            appliedVideo: appliedVideo()
        ))
        XCTAssertFalse(harness.session.rejectAdaptiveProfile(token: token))
        XCTAssertTrue(harness.waitForFailure())
        XCTAssertTrue(harness.engine.didClose)
    }

    func testInvalidAdaptiveApplyResumesDeferredRotationAfterLocalReject() throws {
        let harness = try Harness()
        let first = expectation(description: "first adaptive profile requested")
        let retried = expectation(description: "invalid apply retried")
        var requestCount = 0
        var firstToken: InternetAdaptiveRequestToken?
        harness.session.onAdaptiveProfileRequested = { token, profile, _, _ in
            XCTAssertEqual(profile, AdaptiveMediaPolicy.constrained)
            requestCount += 1
            if requestCount == 1 {
                firstToken = token
                first.fulfill()
            } else if requestCount == 2 {
                retried.fulfill()
            }
        }

        try reachStreaming(harness)
        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [first], timeout: 1)
        let controlCountBeforeRotation = harness.engine.sentPlaintext
            .filter { $0.channel == .control }.count
        try harness.session.updateRotation(90)
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .control }.count,
            controlCountBeforeRotation,
            "Rotation must remain deferred while host apply is pending"
        )

        XCTAssertThrowsError(try harness.session.completeAdaptiveProfile(
            token: try XCTUnwrap(firstToken),
            appliedVideo: appliedVideo(width: 1_922)
        ))
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .control }.count,
            controlCountBeforeRotation,
            "Rotation must remain deferred until the host restores committed state"
        )
        XCTAssertTrue(harness.session.rejectAdaptiveProfile(token: try XCTUnwrap(firstToken)))
        XCTAssertTrue(harness.waitForSentControlCount(controlCountBeforeRotation + 2))
        let rotationControls = try harness.engine.sentPlaintext
            .filter { $0.channel == .control }
            .suffix(2)
            .map { try VSEnvelope(serializedBytes: $0.payload) }
        guard case .displayChanged(let rotatedDisplay) = rotationControls[0].payload,
              case .videoConfig(let rotatedVideo) = rotationControls[1].payload else {
            return XCTFail("Invalid apply must resume the deferred rotation transaction")
        }
        XCTAssertEqual(rotatedDisplay.rotationDegrees, 90)
        XCTAssertEqual(rotatedVideo.rotationDegrees, 90)
        XCTAssertEqual(rotatedVideo.configEpoch, 2)
        XCTAssertEqual(harness.session.snapshotState(), .awaitingVideoConfiguration)
        harness.receiveControl(harness.videoAccepted(messageID: 3, configEpoch: 2))
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [retried], timeout: 1)
        XCTAssertEqual(requestCount, 2)
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
        XCTAssertFalse(harness.engine.didClose)
    }

    func testInvalidAdaptiveApplyResumesLatestQueuedProfile() throws {
        let harness = try Harness()
        let firstRequested = expectation(description: "first adaptive profile requested")
        let queuedRequested = expectation(description: "latest queued profile requested")
        var firstToken: InternetAdaptiveRequestToken?
        var queuedProfile: AdaptiveMediaProfile?
        harness.session.onAdaptiveProfileRequested = { token, profile, _, _ in
            if firstToken == nil {
                XCTAssertEqual(profile, AdaptiveMediaPolicy.constrained)
                firstToken = token
                firstRequested.fulfill()
            } else {
                queuedProfile = profile
                queuedRequested.fulfill()
            }
        }

        try reachStreaming(harness)
        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [firstRequested], timeout: 1)

        for _ in 0..<4 { harness.engine.emitNetworkQuality(goodSample()) }
        Thread.sleep(forTimeInterval: 0.05)
        XCTAssertNil(queuedProfile, "Queued profile must wait for the pending host apply")

        XCTAssertThrowsError(try harness.session.completeAdaptiveProfile(
            token: try XCTUnwrap(firstToken),
            appliedVideo: appliedVideo(width: 1_922)
        ))
        XCTAssertTrue(harness.session.rejectAdaptiveProfile(token: try XCTUnwrap(firstToken)))
        wait(for: [queuedRequested], timeout: 1)
        XCTAssertEqual(queuedProfile, AdaptiveMediaPolicy.good)
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
        XCTAssertFalse(harness.engine.didClose)
    }

    func testAdaptiveLocalRejectStopsHostApplyDeadline() throws {
        let harness = try Harness(negotiationTimeoutMilliseconds: 30)
        let requested = expectation(description: "adaptive profile requested")
        let didRejectHostApply = TestLockedValue<Bool>()
        let stateAfterReject = TestLockedValue<InternetProductSessionState>()
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            didRejectHostApply.store(harness.session.rejectAdaptiveProfile(token: token))
            stateAfterReject.store(harness.session.snapshotState())
            requested.fulfill()
        }

        try reachStreaming(harness)
        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)

        XCTAssertEqual(didRejectHostApply.load(), true)
        XCTAssertEqual(stateAfterReject.load(), .streaming(.direct))
        Thread.sleep(forTimeInterval: 0.08)
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
        XCTAssertFalse(harness.engine.didClose)
    }

    func testAdaptiveLocalRejectAllowsSameProfileToRetry() throws {
        let harness = try Harness()
        let first = expectation(description: "first adaptive profile requested")
        let retried = expectation(description: "rejected profile requested again")
        var requestCount = 0
        var firstToken: InternetAdaptiveRequestToken?
        harness.session.onAdaptiveProfileRequested = { token, profile, _, _ in
            XCTAssertEqual(profile, AdaptiveMediaPolicy.constrained)
            requestCount += 1
            if requestCount == 1 {
                firstToken = token
                first.fulfill()
            } else if requestCount == 2 {
                retried.fulfill()
            }
        }

        try reachStreaming(harness)
        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [first], timeout: 1)
        XCTAssertTrue(harness.session.rejectAdaptiveProfile(token: try XCTUnwrap(firstToken)))

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [retried], timeout: 1)
        XCTAssertEqual(requestCount, 2)
        XCTAssertFalse(harness.engine.didClose)
    }

    func testAdaptiveHostRollbackTimeoutFailsClosed() throws {
        let harness = try Harness(negotiationTimeoutMilliseconds: 30)
        let requested = expectation(description: "adaptive profile requested")
        let rollback = expectation(description: "adaptive rollback requested")
        let didCompleteHostApply = TestLockedValue<Bool>()
        let hostApplyError = TestLockedValue<Error>()
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            do {
                didCompleteHostApply.store(try harness.session.completeAdaptiveProfile(
                    token: token,
                    appliedVideo: self.appliedVideo()
                ))
            } catch {
                hostApplyError.store(error)
            }
            requested.fulfill()
        }
        harness.session.onAdaptiveProfileRollbackRequested = { _, _, _ in
            rollback.fulfill()
        }

        try reachStreaming(harness)
        harness.session.onStateChanged = { state in
            guard state == .awaitingVideoConfiguration else { return }
            harness.receiveControl(harness.videoRejected(messageID: 3, configEpoch: 2))
        }
        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        if let hostApplyError = hostApplyError.load() {
            return XCTFail("Adaptive host apply failed: " + String(describing: hostApplyError))
        }
        XCTAssertEqual(didCompleteHostApply.load(), true)
        wait(for: [rollback], timeout: 1)

        XCTAssertTrue(harness.waitForFailure())
        guard case .failed(let reason) = harness.session.snapshotState() else {
            return XCTFail("Expected the adaptive rollback deadline to fail the session.")
        }
        XCTAssertTrue(
            reason.contains("host did not finish adaptive video rollback"),
            "Expected host-rollback timeout, got: " + reason
        )
        XCTAssertTrue(harness.engine.didClose)
    }

    func testAdaptiveQueuedLatestProfileReplacesPendingQueue() throws {
        let harness = try Harness()
        let firstRequested = expectation(description: "first adaptive profile requested")
        let secondRequested = expectation(description: "second adaptive profile requested")
        var firstToken: InternetAdaptiveRequestToken?
        var secondProfile: AdaptiveMediaProfile?
        harness.session.onAdaptiveProfileRequested = { token, profile, _, _ in
            if firstToken == nil {
                firstToken = token
                firstRequested.fulfill()
            } else {
                secondProfile = profile
                secondRequested.fulfill()
            }
        }

        try reachStreaming(harness)

        // First profile downgrade (constrained). Downgrade threshold is 2.
        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [firstRequested], timeout: 1)
        let token = try XCTUnwrap(firstToken)

        // While the first request is pending, queue a balanced upgrade. The
        // upgrade threshold is 4 consecutive observations.
        for _ in 0..<4 { harness.engine.emitNetworkQuality(balancedSample()) }
        Thread.sleep(forTimeInterval: 0.05)
        XCTAssertNil(secondProfile, "A second profile must not start while one is pending")

        // A later good upgrade overwrites the queued balanced profile. Only the
        // latest queued profile is retained.
        for _ in 0..<4 { harness.engine.emitNetworkQuality(goodSample()) }
        Thread.sleep(forTimeInterval: 0.05)
        XCTAssertNil(secondProfile, "Queued profiles must not start while a transaction is pending")

        try harness.session.completeAdaptiveProfile(token: token, appliedVideo: appliedVideo())
        harness.receiveControl(harness.videoAccepted(messageID: 3, configEpoch: 2))

        // After the first transaction commits, the latest queued profile (good)
        // runs, not the earlier balanced one.
        wait(for: [secondRequested], timeout: 1)
        XCTAssertEqual(secondProfile, AdaptiveMediaPolicy.good)
    }

    func testAdaptiveStaleTokenAndCloseDoNotAffectActiveState() throws {
        let harness = try Harness()
        let requested = expectation(description: "adaptive profile requested")
        var capturedToken: InternetAdaptiveRequestToken?
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            capturedToken = token
            requested.fulfill()
        }

        try reachStreaming(harness)

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        let token = try XCTUnwrap(capturedToken)

        harness.session.close()
        XCTAssertEqual(harness.session.snapshotState(), .closed)

        // Tokens from a prior session generation must be rejected without
        // mutating the closed session.
        let completed = try? harness.session.completeAdaptiveProfile(
            token: token,
            appliedVideo: appliedVideo()
        )
        XCTAssertEqual(completed, false)
        XCTAssertFalse(harness.session.rejectAdaptiveProfile(token: token))
        XCTAssertEqual(harness.session.snapshotState(), .closed)
    }

    func testRotationIsDeferredUntilAdaptiveTransactionCompletes() throws {
        let harness = try Harness()
        let requested = expectation(description: "adaptive profile requested")
        var capturedToken: InternetAdaptiveRequestToken?
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            capturedToken = token
            requested.fulfill()
        }

        try reachStreaming(harness)

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        let token = try XCTUnwrap(capturedToken)

        // Rotation must be deferred while an adaptive request is in flight.
        let controlCountBeforeRotation = harness.engine.sentPlaintext
            .filter { $0.channel == .control }.count
        try harness.session.updateRotation(90)
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .control }.count,
            controlCountBeforeRotation,
            "Rotation must not emit controls while an adaptive transaction is pending"
        )

        try harness.session.completeAdaptiveProfile(token: token, appliedVideo: appliedVideo())

        let adaptiveControls = try harness.engine.sentPlaintext
            .filter { $0.channel == .control }
            .suffix(2)
            .map { try VSEnvelope(serializedBytes: $0.payload) }
        guard case .displayChanged(let displayChanged) = adaptiveControls[0].payload,
              case .videoConfig(let videoConfig) = adaptiveControls[1].payload else {
            return XCTFail("Adaptive apply must send DisplayChanged then VideoConfig")
        }
        XCTAssertEqual(displayChanged.rotationDegrees, 0)
        XCTAssertEqual(videoConfig.rotationDegrees, 0)
        XCTAssertEqual(videoConfig.configEpoch, 2)

        let controlCountAfterAdaptive = harness.engine.sentPlaintext
            .filter { $0.channel == .control }.count
        harness.receiveControl(harness.videoAccepted(messageID: 3, configEpoch: 2))
        XCTAssertTrue(harness.waitForSentControlCount(controlCountAfterAdaptive + 2))

        let rotationControls = try harness.engine.sentPlaintext
            .filter { $0.channel == .control }
            .suffix(2)
            .map { try VSEnvelope(serializedBytes: $0.payload) }
        guard case .displayChanged(let rotatedDisplay) = rotationControls[0].payload,
              case .videoConfig(let rotatedVideo) = rotationControls[1].payload else {
            return XCTFail("Deferred rotation must start after the adaptive ACK")
        }
        XCTAssertEqual(rotatedDisplay.rotationDegrees, 90)
        XCTAssertEqual(rotatedVideo.rotationDegrees, 90)
        XCTAssertEqual(rotatedVideo.configEpoch, 3)
        harness.receiveControl(harness.videoAccepted(messageID: 4, configEpoch: 3))
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
    }

    func testInvalidRotationIsRejectedBeforeAdaptiveDeferral() throws {
        let harness = try Harness()
        let requested = expectation(description: "adaptive profile requested")
        var capturedToken: InternetAdaptiveRequestToken?
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            capturedToken = token
            requested.fulfill()
        }

        try reachStreaming(harness)
        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        let token = try XCTUnwrap(capturedToken)
        let controlCount = harness.engine.sentPlaintext.filter { $0.channel == .control }.count

        XCTAssertThrowsError(try harness.session.updateRotation(45)) { error in
            guard let sessionError = error as? InternetProductSessionError,
                  case .invalidConfiguration = sessionError else {
                return XCTFail("Expected invalidConfiguration, got \(error)")
            }
        }
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .control }.count,
            controlCount
        )

        try harness.session.completeAdaptiveProfile(token: token, appliedVideo: appliedVideo())
        harness.receiveControl(harness.videoAccepted(messageID: 3, configEpoch: 2))
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
        XCTAssertFalse(harness.engine.didClose)
    }

    func testInitialVideoAckDrainsOnlyLatestValidRotationOnce() throws {
        let harness = try Harness()
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1))
        XCTAssertTrue(harness.waitForSentControlCount(3))
        XCTAssertEqual(harness.session.snapshotState(), .awaitingVideoConfiguration)

        try harness.session.updateRotation(90)
        try harness.session.updateRotation(180)
        XCTAssertThrowsError(try harness.session.updateRotation(45)) { error in
            guard let sessionError = error as? InternetProductSessionError,
                  case .invalidConfiguration = sessionError else {
                return XCTFail("Expected invalidConfiguration, got \(error)")
            }
        }
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .control }.count,
            3,
            "Rotations must remain queued until the initial video config is accepted"
        )

        harness.receiveControl(harness.videoAccepted(messageID: 2))
        XCTAssertTrue(harness.waitForSentControlCount(5))
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .control }.count,
            5,
            "The initial ACK must drain exactly one rotation transaction"
        )
        let controls = try harness.engine.sentPlaintext
            .filter { $0.channel == .control }
            .suffix(2)
            .map { try VSEnvelope(serializedBytes: $0.payload) }
        guard case .displayChanged(let changed) = controls[0].payload,
              case .videoConfig(let video) = controls[1].payload else {
            return XCTFail("Queued rotation must start as its own transaction")
        }
        XCTAssertEqual(changed.rotationDegrees, 180)
        XCTAssertEqual(video.rotationDegrees, 180)
        XCTAssertEqual(video.configEpoch, 2)
        harness.receiveControl(harness.videoAccepted(messageID: 3, configEpoch: 2))
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .control }.count,
            5
        )
    }

    func testFreshSessionOwnerAndEpochDiscardStaleInitialRotationAndAck() throws {
        let harness = try Harness(
            engineCount: 2,
            freshSessionRecoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2),
            replacementSessionEpoch: 2
        )
        let replacement = try XCTUnwrap(harness.replacementEngine)
        let replacementConfiguration = try XCTUnwrap(harness.replacementConfiguration)
        let replacementInstalled = expectation(description: "replacement session installed")
        let replacementAuthenticating = expectation(description: "replacement authenticating")
        harness.session.onStateChanged = { state in
            if state == .recovering(attempt: 1) {
                do {
                    try harness.session.provideFreshSession(
                        configuration: replacementConfiguration
                    )
                    replacementInstalled.fulfill()
                } catch {
                    XCTFail("Installing the replacement session failed: \(error)")
                }
            } else if state == .authenticating, replacement.didStart {
                replacementAuthenticating.fulfill()
            }
        }

        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.receiveControl(harness.clientHello(messageID: 1))
        XCTAssertTrue(harness.waitForSentControlCount(3))
        try harness.session.updateRotation(270)
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .control }.count,
            3
        )

        harness.engine.emitPath(.init(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-before-owner-change"
        ))
        harness.engine.emitPath(.init(
            interface: .wiredEthernet,
            isSatisfied: true,
            fingerprint: "ethernet-after-owner-change"
        ))
        wait(for: [replacementInstalled], timeout: 1)
        XCTAssertEqual(harness.session.snapshotState(), .connecting)
        XCTAssertTrue(harness.engine.didClose)
        XCTAssertEqual(harness.session.currentSessionEpoch, 2)

        // The retired owner may still deliver its epoch-1 ACK callback. It must
        // not mutate the replacement session or drain the retired rotation.
        harness.receiveControl(harness.videoAccepted(messageID: 2))
        XCTAssertEqual(harness.session.snapshotState(), .connecting)
        XCTAssertEqual(harness.session.currentSessionEpoch, 2)
        XCTAssertEqual(
            harness.engine.sentPlaintext.filter { $0.channel == .control }.count,
            3
        )
        XCTAssertTrue(replacement.sentPlaintext.isEmpty)

        replacement.emitConnection(.connected(path: .direct))
        wait(for: [replacementAuthenticating], timeout: 1)
        harness.receiveControl(
            harness.clientHello(messageID: 1, sessionEpoch: 2),
            engineIndex: 1
        )
        XCTAssertTrue(harness.waitForSentControlCount(3, engineIndex: 1))
        XCTAssertEqual(harness.session.snapshotState(), .awaitingVideoConfiguration)
        harness.receiveControl(
            harness.videoAccepted(messageID: 2, sessionEpoch: 2),
            engineIndex: 1
        )
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))
        XCTAssertEqual(harness.session.currentSessionEpoch, 2)
        XCTAssertEqual(
            replacement.sentPlaintext.filter { $0.channel == .control }.count,
            3,
            "A new owner and session epoch must not inherit a retired rotation"
        )
    }

    func testLocalRejectKeepsPreviousStream() throws {
        let harness = try Harness()
        let requested = expectation(description: "adaptive profile requested")
        var capturedToken: InternetAdaptiveRequestToken?
        harness.session.onAdaptiveProfileRequested = { token, _, _, _ in
            capturedToken = token
            requested.fulfill()
        }

        try reachStreaming(harness)

        harness.engine.emitNetworkQuality(constrainedSample())
        harness.engine.emitNetworkQuality(constrainedSample())
        wait(for: [requested], timeout: 1)
        let token = try XCTUnwrap(capturedToken)

        let rejected = harness.session.rejectAdaptiveProfile(token: token)
        XCTAssertTrue(rejected)
        XCTAssertEqual(harness.session.snapshotState(), .streaming(.direct))

        // The previous configuration remains committed and media keeps flowing.
        let before = harness.engine.sentPlaintext.filter { $0.channel == .media }.count
        harness.session.sendFrame(Data([0xEE]), timestamp: 5, isKeyframe: true, sessionEpoch: 1)
        XCTAssertTrue(harness.waitForSentMediaCount(before + 1))
    }


    func testRealVideoToolboxHEVCFrameRoundsThroughProtocolV1MediaPath() throws {
        let harness = try Harness()
        try reachStreaming(harness)

        let frames: InternetProductRealEncodedMediaFrames
        do {
            frames = try InternetProductRealEncodedMediaSource.makeHEVCFrames()
        } catch InternetProductRealEncodedMediaSource.Failure.compressionSessionUnavailable {
            throw XCTSkip("VideoToolbox HEVC compression session is unavailable on this host")
        } catch {
            throw error
        }
        XCTAssertFalse(frames.keyframe.isEmpty)
        XCTAssertFalse(frames.delta.isEmpty)
        // Annex-B HEVC keyframes begin with a start code followed by a VPS/SPS/PPS or IDR NAL unit.
        XCTAssertTrue(frames.keyframe.starts(with: Data([0x00, 0x00, 0x00, 0x01])))

        let sessionEpoch = harness.session.currentSessionEpoch
        harness.session.sendFrame(
            frames.keyframe,
            timestamp: 1_000,
            isKeyframe: true,
            sessionEpoch: sessionEpoch
        )
        XCTAssertTrue(harness.waitForSentMediaCount(1))
        harness.session.sendFrame(
            frames.delta,
            timestamp: 2_000,
            isKeyframe: false,
            sessionEpoch: sessionEpoch
        )

        XCTAssertTrue(harness.waitForSentMediaCount(2))
        let mediaRecords = harness.engine.sentPlaintext
            .filter { $0.channel == .media }
            .map { $0.payload }
        XCTAssertEqual(mediaRecords.count, 2)

        var fragments: [(header: VSMediaPacketHeader, payload: Data)] = []
        for record in mediaRecords {
            let decoded = try ProtocolV1MediaPacketCodec.decode(record)
            fragments.append(decoded)
        }

        let keyframe = try XCTUnwrap(fragments.first { $0.header.keyframe })
        XCTAssertEqual(keyframe.header.sessionEpoch, sessionEpoch)
        XCTAssertEqual(keyframe.header.captureTimestampNs, 1_000)
        XCTAssertEqual(keyframe.header.codec, .hevc)
        XCTAssertEqual(keyframe.header.fragmentIndex, 0)
        XCTAssertEqual(keyframe.header.fragmentCount, 1)
        XCTAssertEqual(keyframe.payload, frames.keyframe)

        let delta = try XCTUnwrap(fragments.first { !$0.header.keyframe })
        XCTAssertEqual(delta.header.sessionEpoch, sessionEpoch)
        XCTAssertEqual(delta.header.captureTimestampNs, 2_000)
        XCTAssertEqual(delta.header.codec, .hevc)
        XCTAssertEqual(delta.header.fragmentIndex, 0)
        XCTAssertEqual(delta.header.fragmentCount, 1)
        XCTAssertEqual(delta.payload, frames.delta)
        XCTAssertNotEqual(delta.payload, Data(InternetProductSessionSelfTest.deltaPlaintextSeed.utf8))
    }

    func testRealVideoToolboxHEVCFramePacketReassemblesThroughProtocolV1MediaPath() throws {
        let harness = try Harness()
        try reachStreaming(harness)

        let frames: InternetProductRealEncodedMediaFrames
        do {
            frames = try InternetProductRealEncodedMediaSource.makeHEVCFrames()
        } catch InternetProductRealEncodedMediaSource.Failure.compressionSessionUnavailable {
            throw XCTSkip("VideoToolbox HEVC compression session is unavailable on this host")
        } catch {
            throw error
        }

        harness.session.sendFrame(
            frames.keyframe,
            timestamp: 1_000,
            isKeyframe: true,
            sessionEpoch: harness.session.currentSessionEpoch
        )

        XCTAssertTrue(harness.waitForSentMediaCount(1))
        let mediaRecords = harness.engine.sentPlaintext
            .filter { $0.channel == .media }
            .map { $0.payload }
        XCTAssertFalse(mediaRecords.isEmpty)

        let decodedFragments = try mediaRecords.map { try ProtocolV1MediaPacketCodec.decode($0) }
        let frameID = try XCTUnwrap(decodedFragments.first?.header.frameID)
        XCTAssertTrue(decodedFragments.allSatisfy { $0.header.frameID == frameID })
        XCTAssertEqual(decodedFragments[0].header.sessionEpoch, harness.session.currentSessionEpoch)
        XCTAssertTrue(decodedFragments[0].header.keyframe)
        XCTAssertEqual(decodedFragments[0].header.codec, .hevc)

        let sorted = decodedFragments.sorted { $0.header.fragmentIndex < $1.header.fragmentIndex }
        XCTAssertEqual(sorted.count, Int(sorted[0].header.fragmentCount))
        for (index, fragment) in sorted.enumerated() {
            XCTAssertEqual(fragment.header.fragmentIndex, UInt32(index))
        }

        let reassembled = sorted.reduce(into: Data()) { $0.append($1.payload) }
        XCTAssertEqual(reassembled, frames.keyframe, "Reassembled Protocol v1 media payload must match the original VideoToolbox HEVC keyframe")
    }

}

private final class Harness {
    let engine: ProductFakeWebRTCEngine
    let replacementEngine: ProductFakeWebRTCEngine?
    let replacementConfiguration: InternetProductSessionConfiguration?
    let session: InternetProductSession
    let configuration: InternetProductSessionConfiguration
    let securitySession: InternetProductSecuritySession
    private let deviceCiphers: [PlatformSessionPacketCipher]

    init(
        negotiationTimeoutMilliseconds: UInt32 = 10_000,
        limits: InternetTransportLimits = .standard,
        engineCount: Int = 1,
        freshSessionRecoveryPolicy: NetworkRecoveryPolicy = .standard,
        videoConfigEpoch: UInt64 = 1,
        replacementSessionEpoch: UInt64? = nil,
        controllerAvailable: Bool = false
    ) throws {
        let configurationCount = max(1, engineCount)
        let configurations = (0..<configurationCount).map { index in
            Self.makeConfiguration(
                sessionEpoch: index == 0 ? 1 : replacementSessionEpoch ?? 1,
                videoConfigEpoch: videoConfigEpoch,
                negotiationTimeoutMilliseconds: negotiationTimeoutMilliseconds,
                limits: limits,
                controllerAvailable: controllerAvailable
            )
        }
        let pairs = try configurations.map { configuration in
            try PlatformSessionPacketCipher.selfTestPair(
                sessionIdentifier: "product-session",
                sharedSecret: Data(repeating: 0x51, count: 32),
                bootstrapSecret: Data(repeating: 0x52, count: 32),
                transcriptContext: configuration.boundTranscriptContext,
                sessionEpoch: configuration.authoritativeSessionEpoch
            )
        }
        let securitySessions = zip(configurations, pairs).map { configuration, pair in
            InternetProductSecuritySession(
                sessionEpoch: configuration.authoritativeSessionEpoch,
                packetCipher: pair.host
            )
        }
        let engines = pairs.map { ProductFakeWebRTCEngine(remoteCipher: $0.device) }
        deviceCiphers = pairs.map(\.device)
        securitySession = securitySessions[0]
        engine = engines[0]
        replacementEngine = engines.count > 1 ? engines[1] : nil
        configuration = configurations[0]
        replacementConfiguration = configurations.count > 1 ? configurations[1] : nil
        var factoryIndex = 0
        var securityIndex = 0
        session = InternetProductSession(
            engineFactory: {
                defer { factoryIndex += 1 }
                return engines[min(factoryIndex, engines.count - 1)]
            },
            securitySessionFactory: { _ in
                defer { securityIndex += 1 }
                return securitySessions[min(securityIndex, securitySessions.count - 1)]
            },
            revocationHandler: { _, _ in nil },
            freshSessionRecoveryPolicy: freshSessionRecoveryPolicy
        )
    }

    private static func makeConfiguration(
        sessionEpoch: UInt64,
        videoConfigEpoch: UInt64,
        negotiationTimeoutMilliseconds: UInt32,
        limits: InternetTransportLimits,
        controllerAvailable: Bool
    ) -> InternetProductSessionConfiguration {
        InternetProductSessionConfiguration(
            transport: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:127.0.0.1:9")!])],
                peerIdentity: String(repeating: "a", count: 64),
                sessionIdentifier: "product-session",
                forceRelay: false
            ),
            hostDeviceID: "host-1",
            hostName: "Mac",
            peerDeviceID: "device-1",
            peerIdentity: PlatformPublicIdentity(
                deviceID: "device-1",
                keyID: String(repeating: "a", count: 64),
                keyEpoch: 1,
                signingPublicKey: Data([UInt8(0x04)] + Array(repeating: UInt8(0x11), count: 64))
            ),
            authoritativeSessionEpoch: sessionEpoch,
            sharedSecretName: "shared-device-1",
            bootstrapSecretName: "bootstrap-device-1",
            transcriptContext: Data(repeating: 0x53, count: 32),
            video: InternetProductVideoConfiguration(
                codec: .hevc,
                width: 1920,
                height: 1080,
                framesPerSecond: 60,
                bitrateKbps: 20_000,
                configEpoch: videoConfigEpoch
            ),
            controllerAvailable: controllerAvailable,
            heartbeatIntervalMilliseconds: 10_000,
            heartbeatTimeoutMilliseconds: 20_000,
            negotiationTimeoutMilliseconds: negotiationTimeoutMilliseconds,
            limits: limits
        )
    }

    func receiveControl(_ envelope: VSEnvelope, engineIndex: Int = 0) {
        let plaintext = try! envelope.serializedData()
        let record = try! deviceCiphers[engineIndex].seal(plaintext, channel: .control)
        selectedEngine(engineIndex).receive(record, channel: .control)
    }

    func clientHello(
        messageID: UInt64,
        supportsStylus: Bool = false,
        supportsStylusExtended: Bool = false,
        supportsController: Bool = false,
        sessionEpoch: UInt64 = 1
    ) -> VSEnvelope {
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "device-1"
        hello.deviceName = "Android"
        hello.capabilities = Array(InternetProductProtocolCodec.requiredCapabilities) + [.touch]
        if supportsStylus { hello.capabilities.append(.stylus) }
        if supportsStylusExtended { hello.capabilities.append(.stylusExtended) }
        if supportsController { hello.capabilities.append(.controller) }
        hello.requiredCapabilities = Array(InternetProductProtocolCodec.requiredCapabilities)
        hello.codecs = [.hevc]
        hello.transports = [.internet]
        var limits = VSResourceLimits()
        limits.maximumEncryptedMediaRecordBytes = UInt32(
            InternetMediaRecordContract.maximumEncryptedRecordBytes
        )
        hello.resourceLimits = limits
        var envelope = baseEnvelope(messageID: messageID, sessionEpoch: sessionEpoch)
        envelope.clientHello = hello
        return envelope
    }

    func controller(
        messageID: UInt64,
        inputID: UInt64,
        controllerID: String,
        controllerEpoch: UInt64 = 1,
        kind: VSControllerEventKind,
        buttonMask: UInt32 = 0
    ) -> VSEnvelope {
        var event = VSControllerEvent()
        event.inputID = inputID
        event.controllerID = controllerID
        event.controllerEpoch = controllerEpoch
        event.kind = kind
        event.buttonMask = buttonMask
        var envelope = baseEnvelope(messageID: messageID)
        envelope.controllerEvent = event
        return envelope
    }

    func videoAccepted(
        messageID: UInt64,
        configEpoch: UInt64 = 1,
        sessionEpoch: UInt64 = 1
    ) -> VSEnvelope {
        var result = VSVideoConfigResult()
        result.configEpoch = configEpoch
        result.streamID = 1
        result.accepted = true
        var envelope = baseEnvelope(messageID: messageID, sessionEpoch: sessionEpoch)
        envelope.videoConfigResult = result
        return envelope
    }

    func videoRejected(messageID: UInt64, configEpoch: UInt64 = 1, reason: String = "test rejection") -> VSEnvelope {
        var result = VSVideoConfigResult()
        result.configEpoch = configEpoch
        result.streamID = 1
        result.accepted = false
        result.rejectionReason = reason
        var envelope = baseEnvelope(messageID: messageID)
        envelope.videoConfigResult = result
        return envelope
    }

    func touch(messageID: UInt64) -> VSEnvelope {
        var point = VSNormalizedPoint()
        point.x = 0.25
        point.y = 0.75
        var touch = VSTouchEvent()
        touch.inputID = 1
        touch.pointerID = 1
        touch.phase = .began
        touch.position = point
        var envelope = baseEnvelope(messageID: messageID)
        envelope.touchEvent = touch
        return envelope
    }

    func stylus(messageID: UInt64) -> VSEnvelope {
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
        var envelope = baseEnvelope(messageID: messageID)
        envelope.stylusEvent = stylus
        return envelope
    }

    func extendedStylus(
        messageID: UInt64,
        toolKind: VSStylusToolKind,
        buttonMask: UInt32,
        contactState: VSStylusContactState,
        pressure: Double
    ) -> VSEnvelope {
        var envelope = stylus(messageID: messageID)
        envelope.stylusEvent.toolKind = toolKind
        envelope.stylusEvent.buttonMask = buttonMask
        envelope.stylusEvent.contactState = contactState
        envelope.stylusEvent.pressure = pressure
        return envelope
    }

    func keyframeRequest(messageID: UInt64) -> VSEnvelope {
        var request = VSRequestKeyframe()
        request.streamID = 1
        var envelope = baseEnvelope(messageID: messageID)
        envelope.requestKeyframe = request
        return envelope
    }

    func ping(messageID: UInt64, sequence: UInt64) -> VSEnvelope {
        var ping = VSPing()
        ping.sequence = sequence
        var envelope = baseEnvelope(messageID: messageID)
        envelope.ping = ping
        return envelope
    }

    func waitForSentControlCount(_ count: Int, engineIndex: Int = 0) -> Bool {
        waitUntil {
            self.selectedEngine(engineIndex).sentPlaintext
                .filter { $0.channel == .control }.count >= count
        }
    }

    func waitForFailure(timeout: TimeInterval = 1) -> Bool {
        waitUntil(timeout: timeout) {
            if case .failed = self.session.snapshotState() { return true }
            return false
        }
    }

    func waitForSentMediaCount(_ count: Int) -> Bool {
        waitUntil { self.engine.sentPlaintext.filter { $0.channel == .media }.count >= count }
    }

    func waitForPong(sequence: UInt64) -> Bool {
        waitUntil {
            self.engine.sentPlaintext.contains { item in
                guard item.channel == .control,
                      let envelope = try? VSEnvelope(serializedBytes: item.payload),
                      case .pong(let pong) = envelope.payload else { return false }
                return pong.sequence == sequence
            }
        }
    }

    func waitForInputAck(inputID: UInt64, engineIndex: Int = 0) -> Bool {
        waitUntil { self.sentInputAck(inputID: inputID, engineIndex: engineIndex) != nil }
    }

    func sentInputAck(inputID: UInt64, engineIndex: Int = 0) -> VSInputAck? {
        selectedEngine(engineIndex).sentPlaintext.lazy.compactMap { item -> VSInputAck? in
            guard item.channel == .control,
                  let envelope = try? VSEnvelope(serializedBytes: item.payload),
                  case .inputAck(let acknowledgement) = envelope.payload,
                  acknowledgement.inputID == inputID else { return nil }
            return acknowledgement
        }.first
    }

    func sentInputAckEnvelope(inputID: UInt64, engineIndex: Int = 0) -> VSEnvelope? {
        selectedEngine(engineIndex).sentPlaintext.lazy.compactMap { item -> VSEnvelope? in
            guard item.channel == .control,
                  let envelope = try? VSEnvelope(serializedBytes: item.payload),
                  case .inputAck(let acknowledgement) = envelope.payload,
                  acknowledgement.inputID == inputID else { return nil }
            return envelope
        }.first
    }

    func sentInputAckCount(inputID: UInt64, engineIndex: Int = 0) -> Int {
        selectedEngine(engineIndex).sentPlaintext.reduce(into: 0) { count, item in
            guard item.channel == .control,
                  let envelope = try? VSEnvelope(serializedBytes: item.payload),
                  case .inputAck(let acknowledgement) = envelope.payload,
                  acknowledgement.inputID == inputID else { return }
            count += 1
        }
    }

    func waitForProtocolError(
        engineIndex: Int = 0,
        timeout: TimeInterval = 1
    ) -> Bool {
        waitUntil(timeout: timeout) {
            self.sentProtocolErrorEnvelope(engineIndex: engineIndex) != nil
        }
    }

    func waitForDeferredControlSend() -> Bool {
        waitUntil { self.engine.hasDeferredControlSend }
    }

    func sentProtocolErrorEnvelope(engineIndex: Int = 0) -> VSEnvelope? {
        selectedEngine(engineIndex).sentPlaintext.lazy.compactMap { item -> VSEnvelope? in
            guard item.channel == .control,
                  let envelope = try? VSEnvelope(serializedBytes: item.payload),
                  case .protocolError = envelope.payload else { return nil }
            return envelope
        }.first
    }

    private func baseEnvelope(messageID: UInt64, sessionEpoch: UInt64 = 1) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = messageID
        envelope.sessionID = Data("product-session".utf8)
        envelope.sessionEpoch = sessionEpoch
        return envelope
    }

    private func selectedEngine(_ index: Int) -> ProductFakeWebRTCEngine {
        if index == 0 { return engine }
        return replacementEngine!
    }

    private func waitUntil(
        timeout: TimeInterval = 1,
        _ predicate: () -> Bool
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if predicate() { return true }
            Thread.sleep(forTimeInterval: 0.005)
        }
        return predicate()
    }
}

private final class TestLockedValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value?

    func store(_ value: Value) {
        lock.lock()
        self.value = value
        lock.unlock()
    }

    func load() -> Value? {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

private final class TestLockedArray<Element>: @unchecked Sendable {
    private let lock = NSLock()
    private var elements: [Element] = []

    func append(_ element: Element) {
        lock.lock()
        elements.append(element)
        lock.unlock()
    }

    func snapshot() -> [Element] {
        lock.lock()
        defer { lock.unlock() }
        return elements
    }
}

private func waitForMonotonicDuration(_ duration: TimeInterval) {
    let durationNanoseconds = UInt64(duration * 1_000_000_000)
    let deadline = DispatchTime.now().uptimeNanoseconds + durationNanoseconds
    while DispatchTime.now().uptimeNanoseconds < deadline {}
}

private final class ProductFakeWebRTCEngine: WebRTCEnginePort {
    struct PlaintextItem {
        let payload: Data
        let channel: InternetTransportChannel
    }

    private let lock = NSLock()
    private let remoteCipher: PlatformSessionPacketCipher
    private var callbacks: WebRTCEngineCallbacks?
    private var transmissionEpoch: UInt64 = 0
    private var activeTransmissionPath: InternetPathKind?
    private var lastNetworkPathFingerprint: String?
    private var storedRestartICECount = 0
    private var storedDidClose = false
    private var storedCloseCount = 0
    private var storedDidStart = false
    private var storedStartedAfterClose = false
    private var storage: [PlaintextItem] = []
    private var shouldInvalidateTransmissionContextOnNextControlSend = false
    private var shouldFailNextControlSend = false
    private var shouldDeferNextControlSendCompletion = false
    private var deferredControlSendCompletion: ((Result<Void, Error>) -> Void)?
    private var deferredControlSendPlaintext: PlaintextItem?

    var sentPlaintext: [PlaintextItem] {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }

    var restartICECount: Int { lock.withLock { storedRestartICECount } }
    var didClose: Bool { lock.withLock { storedDidClose } }
    var closeCount: Int { lock.withLock { storedCloseCount } }
    var didStart: Bool { lock.withLock { storedDidStart } }
    var startedAfterClose: Bool { lock.withLock { storedStartedAfterClose } }
    var hasDeferredControlSend: Bool {
        lock.withLock { deferredControlSendCompletion != nil }
    }

    init(remoteCipher: PlatformSessionPacketCipher) {
        self.remoteCipher = remoteCipher
    }

    func invalidateTransmissionContextOnNextControlSend() {
        lock.lock()
        shouldInvalidateTransmissionContextOnNextControlSend = true
        lock.unlock()
    }

    func failNextControlSend() {
        lock.withLock { shouldFailNextControlSend = true }
    }

    func deferNextControlSendCompletion() {
        lock.withLock { shouldDeferNextControlSendCompletion = true }
    }

    func completeDeferredControlSend(succeeded: Bool) {
        let deferred = lock.withLock {
            () -> (((Result<Void, Error>) -> Void)?, PlaintextItem?) in
            defer {
                deferredControlSendCompletion = nil
                deferredControlSendPlaintext = nil
            }
            return (deferredControlSendCompletion, deferredControlSendPlaintext)
        }
        if succeeded {
            if let plaintext = deferred.1 {
                lock.withLock { storage.append(plaintext) }
            }
            deferred.0?(.success(()))
        } else {
            deferred.0?(.failure(
                PlatformSecurityError.invalidInput("deferred control send failed")
            ))
        }
    }

    func install(callbacks: WebRTCEngineCallbacks) { self.callbacks = callbacks }
    func start(configuration: WebRTCTransportConfiguration, channels: [WebRTCDataChannelConfiguration]) throws {
        lock.withLock {
            storedDidStart = true
            storedStartedAfterClose = storedDidClose
        }
    }

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        expectedContext: WebRTCEngineTransmissionContext,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard expectedContext == currentTransmissionContext else {
            completion(.failure(PlatformSecurityError.invalidInput("stale test transmission context")))
            return
        }
        guard let plaintext = remoteCipher.open(payload, channel: channel) else {
            completion(.failure(PlatformSecurityError.invalidInput("test decrypt failed")))
            return
        }
        var shouldInvalidateTransmissionContext = false
        var shouldFail = false
        var shouldDefer = false
        lock.lock()
        if channel == .control, shouldFailNextControlSend {
            shouldFailNextControlSend = false
            shouldFail = true
        } else if channel == .control, shouldDeferNextControlSendCompletion {
            shouldDeferNextControlSendCompletion = false
            shouldDefer = true
            deferredControlSendCompletion = completion
            deferredControlSendPlaintext = PlaintextItem(
                payload: plaintext,
                channel: channel
            )
        }
        if !shouldFail, !shouldDefer {
            storage.append(PlaintextItem(payload: plaintext, channel: channel))
        }
        if channel == .control, shouldInvalidateTransmissionContextOnNextControlSend {
            shouldInvalidateTransmissionContextOnNextControlSend = false
            shouldInvalidateTransmissionContext = true
        }
        lock.unlock()
        if shouldInvalidateTransmissionContext {
            callbacks?.transmissionContextChanged(nil)
        }
        if shouldFail {
            completion(.failure(
                PlatformSecurityError.invalidInput("test control send failed")
            ))
            return
        }
        if shouldDefer { return }
        completion(.success(()))
    }

    func restartICE() -> WebRTCEngineRecoveryDisposition {
        invalidateTransmissionContext()
        lock.withLock { storedRestartICECount += 1 }
        callbacks?.connectionStateChanged(.connecting)
        return .peerReplacementStarted
    }
    func requestMediaKeyframe() {}
    func close() {
        invalidateTransmissionContext()
        lock.withLock {
            storedCloseCount += 1
            storedDidClose = true
        }
    }
    func emitConnection(_ state: WebRTCEngineConnectionState) {
        switch state {
        case .connected(let path):
            if activeTransmissionPath != path {
                invalidateTransmissionContext()
                activeTransmissionPath = path
            }
            callbacks?.transmissionContextChanged(currentTransmissionContext)
        case .connecting, .disconnected, .failed, .closed:
            invalidateTransmissionContext()
        }
        callbacks?.connectionStateChanged(state)
    }
    func emitPath(_ path: InternetNetworkPath) {
        let changed = lastNetworkPathFingerprint.map { $0 != path.fingerprint } ?? false
        lastNetworkPathFingerprint = path.fingerprint
        if changed { invalidateTransmissionContext() }
        callbacks?.networkPathChanged(path)
    }
    func emitNetworkQuality(_ sample: InternetNetworkQualitySample) {
        callbacks?.networkQualitySampled(sample)
    }
    func receive(_ record: Data, channel: InternetTransportChannel) {
        callbacks?.messageReceived(record, channel)
    }

    private var currentTransmissionContext: WebRTCEngineTransmissionContext? {
        guard let activeTransmissionPath else { return nil }
        return WebRTCEngineTransmissionContext(epoch: transmissionEpoch, path: activeTransmissionPath)
    }

    private func invalidateTransmissionContext() {
        guard activeTransmissionPath != nil else { return }
        activeTransmissionPath = nil
        transmissionEpoch &+= 1
        callbacks?.transmissionContextChanged(nil)
    }
}

private final class ProductHarnessTransmissionEngine: WebRTCEnginePort {
    private var callbacks: WebRTCEngineCallbacks?
    private var context: WebRTCEngineTransmissionContext?
    private(set) var sentPayloads: [Data] = []

    func install(callbacks: WebRTCEngineCallbacks) {
        self.callbacks = callbacks
    }

    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws {}

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        expectedContext: WebRTCEngineTransmissionContext,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard channel == .control, expectedContext == context else {
            completion(.failure(
                PlatformSecurityError.invalidInput("stale harness transmission context")
            ))
            return
        }
        sentPayloads.append(payload)
        completion(.success(()))
    }

    func restartICE() -> WebRTCEngineRecoveryDisposition {
        .failed("not used")
    }

    func requestMediaKeyframe() {}
    func close() {}

    func emitConnection(_ state: WebRTCEngineConnectionState) {
        callbacks?.connectionStateChanged(state)
    }

    func emitTransmissionContext(_ context: WebRTCEngineTransmissionContext?) {
        self.context = context
        callbacks?.transmissionContextChanged(context)
    }
}
