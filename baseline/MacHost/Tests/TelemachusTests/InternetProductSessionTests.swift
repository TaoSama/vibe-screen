import Foundation
import VibeScreenProtocol
import XCTest
@testable import Telemachus

final class InternetProductSessionTests: XCTestCase {
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
        var installedReplacement = false
        var freshSessionAttempts: [Int] = []
        harness.session.onStateChanged = { state in
            guard state == .recovering(attempt: 1), !installedReplacement else { return }
            installedReplacement = true
            do {
                try harness.session.provideFreshSession(configuration: harness.configuration)
            } catch {
                XCTFail("Installing the fresh session failed: \(error)")
            }
        }
        harness.session.onFreshSessionRecoveryRequired = { freshSessionAttempts.append($0) }

        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        harness.engine.emitPath(.init(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        harness.engine.emitPath(.init(interface: .wiredEthernet, isSatisfied: true, fingerprint: "ethernet-b"))

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

    func testLegacyClientWithoutMediaRecordNegotiationFailsBeforeHostControls() throws {
        let harness = try Harness()
        let authenticating = expectation(description: "authenticating")
        let failed = expectation(description: "legacy client rejected")
        harness.session.onStateChanged = { state in
            if state == .authenticating { authenticating.fulfill() }
            if case .failed = state { failed.fulfill() }
        }

        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .direct))
        wait(for: [authenticating], timeout: 1)
        var legacyHello = harness.clientHello(messageID: 1)
        legacyHello.clientHello.capabilities.removeAll { $0 == .mediaRecordFragmentation }
        legacyHello.clientHello.requiredCapabilities.removeAll { $0 == .mediaRecordFragmentation }
        legacyHello.clientHello.resourceLimits.maximumEncryptedMediaRecordBytes = 0
        harness.receiveControl(legacyHello)

        wait(for: [failed], timeout: 1)
        XCTAssertTrue(harness.engine.sentPlaintext.filter { $0.channel == .control }.isEmpty)
        XCTAssertTrue(harness.engine.didClose)
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
        try harness.session.start(configuration: harness.configuration)
        harness.engine.emitConnection(.connected(path: .unknown))

        guard case .failed(let reason) = harness.session.snapshotState() else {
            return XCTFail("Unknown route must fail closed")
        }
        XCTAssertTrue(reason.contains("before selecting an ICE candidate pair"))
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
}

private final class Harness {
    let engine: ProductFakeWebRTCEngine
    let replacementEngine: ProductFakeWebRTCEngine?
    let session: InternetProductSession
    let configuration: InternetProductSessionConfiguration
    let securitySession: InternetProductSecuritySession
    private let deviceCipher: PlatformSessionPacketCipher

    init(
        negotiationTimeoutMilliseconds: UInt32 = 10_000,
        limits: InternetTransportLimits = .standard,
        engineCount: Int = 1,
        freshSessionRecoveryPolicy: NetworkRecoveryPolicy = .standard
    ) throws {
        let builtConfiguration = InternetProductSessionConfiguration(
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
            authoritativeSessionEpoch: 1,
            sharedSecretName: "shared-device-1",
            bootstrapSecretName: "bootstrap-device-1",
            transcriptContext: Data(repeating: 0x53, count: 32),
            video: InternetProductVideoConfiguration(
                codec: .hevc,
                width: 1920,
                height: 1080,
                framesPerSecond: 60,
                bitrateKbps: 20_000
            ),
            heartbeatIntervalMilliseconds: 10_000,
            heartbeatTimeoutMilliseconds: 20_000,
            negotiationTimeoutMilliseconds: negotiationTimeoutMilliseconds,
            limits: limits
        )
        let pairs = try (0..<max(1, engineCount)).map { _ in
            try PlatformSessionPacketCipher.selfTestPair(
                sessionIdentifier: "product-session",
                sharedSecret: Data(repeating: 0x51, count: 32),
                bootstrapSecret: Data(repeating: 0x52, count: 32),
                transcriptContext: builtConfiguration.boundTranscriptContext
            )
        }
        let securitySessions = pairs.map {
            InternetProductSecuritySession(sessionEpoch: 1, packetCipher: $0.host)
        }
        let engines = pairs.map { ProductFakeWebRTCEngine(remoteCipher: $0.device) }
        deviceCipher = pairs[0].device
        securitySession = securitySessions[0]
        engine = engines[0]
        replacementEngine = engines.count > 1 ? engines[1] : nil
        configuration = builtConfiguration
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

    func receiveControl(_ envelope: VSEnvelope) {
        let plaintext = try! envelope.serializedData()
        let record = try! deviceCipher.seal(plaintext, channel: .control)
        engine.receive(record, channel: .control)
    }

    func clientHello(messageID: UInt64) -> VSEnvelope {
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "device-1"
        hello.deviceName = "Android"
        hello.capabilities = [
            .deviceIdentity, .endToEndEncryption, .mediaRecordFragmentation, .replayProtection, .touch,
        ]
        hello.requiredCapabilities = [
            .deviceIdentity, .endToEndEncryption, .mediaRecordFragmentation, .replayProtection,
        ]
        hello.codecs = [.hevc]
        hello.transports = [.internet]
        var limits = VSResourceLimits()
        limits.maximumEncryptedMediaRecordBytes = UInt32(
            InternetMediaRecordContract.maximumEncryptedRecordBytes
        )
        hello.resourceLimits = limits
        var envelope = baseEnvelope(messageID: messageID)
        envelope.clientHello = hello
        return envelope
    }

    func videoAccepted(messageID: UInt64, configEpoch: UInt64 = 1) -> VSEnvelope {
        var result = VSVideoConfigResult()
        result.configEpoch = configEpoch
        result.streamID = 1
        result.accepted = true
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

    func waitForSentControlCount(_ count: Int) -> Bool {
        waitUntil { self.engine.sentPlaintext.filter { $0.channel == .control }.count >= count }
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

    private func baseEnvelope(messageID: UInt64) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = messageID
        envelope.sessionID = Data("product-session".utf8)
        envelope.sessionEpoch = 1
        return envelope
    }

    private func waitUntil(_ predicate: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(1)
        while Date() < deadline {
            if predicate() { return true }
            Thread.sleep(forTimeInterval: 0.005)
        }
        return predicate()
    }
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
    private(set) var restartICECount = 0
    private(set) var didClose = false
    private(set) var closeCount = 0
    private(set) var didStart = false
    private(set) var startedAfterClose = false
    private var storage: [PlaintextItem] = []

    var sentPlaintext: [PlaintextItem] {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }

    init(remoteCipher: PlatformSessionPacketCipher) {
        self.remoteCipher = remoteCipher
    }

    func install(callbacks: WebRTCEngineCallbacks) { self.callbacks = callbacks }
    func start(configuration: WebRTCTransportConfiguration, channels: [WebRTCDataChannelConfiguration]) throws {
        didStart = true
        startedAfterClose = didClose
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
        lock.lock()
        storage.append(PlaintextItem(payload: plaintext, channel: channel))
        lock.unlock()
        completion(.success(()))
    }

    func restartICE() -> WebRTCEngineRecoveryDisposition {
        invalidateTransmissionContext()
        restartICECount += 1
        callbacks?.connectionStateChanged(.connecting)
        return .peerReplacementStarted
    }
    func requestMediaKeyframe() {}
    func close() {
        invalidateTransmissionContext()
        closeCount += 1
        didClose = true
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
