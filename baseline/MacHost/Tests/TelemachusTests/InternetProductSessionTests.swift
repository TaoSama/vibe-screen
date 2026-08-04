import Foundation
import VibeScreenCore
import VibeScreenProtocol
import XCTest
@testable import Telemachus

final class InternetProductSessionTests: XCTestCase {
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

        harness.session.onStateChanged = { state in
            if state == .authenticating { authenticating.fulfill() }
            if state == .streaming(.direct) { streaming.fulfill() }
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

        harness.session.sendFrame(
            Data([0, 0, 0, 1, 0x26]),
            timestamp: 99,
            isKeyframe: true,
            sessionEpoch: 1
        )
        XCTAssertTrue(harness.waitForSentMediaCount(1))
        let media = try MediaPacket(serializedFrame: harness.engine.sentPlaintext.first {
            $0.channel == .media
        }!.payload)
        XCTAssertEqual(media.header.captureTimestampNs, 99)
        XCTAssertTrue(media.header.keyframe)

        harness.receiveControl(harness.touch(messageID: 3))
        harness.receiveControl(harness.keyframeRequest(messageID: 4))
        harness.receiveControl(harness.ping(messageID: 5, sequence: 77))
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
        var persistedSequence: UInt64?
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
                XCTAssertFalse(harness.engine.didClose, "Tombstone must persist before active session closure")
                persistedSequence = sequence
                return tombstone
            }
        )
        session.onRevoked = { revoked.fulfill() }
        session.onRevocationPropagationRequired = { received in
            XCTAssertEqual(received, tombstone)
            XCTAssertFalse(harness.engine.didClose)
            propagation.fulfill()
        }

        try session.start(configuration: harness.configuration)
        try session.revoke(sequence: 8)
        wait(for: [propagation, revoked], timeout: 1)

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
    let session: InternetProductSession
    let configuration: InternetProductSessionConfiguration
    let securitySession: InternetProductSecuritySession
    private let deviceCipher: PlatformSessionPacketCipher

    init(negotiationTimeoutMilliseconds: UInt32 = 10_000) throws {
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
            negotiationTimeoutMilliseconds: negotiationTimeoutMilliseconds
        )
        let ciphers = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "product-session",
            sharedSecret: Data(repeating: 0x51, count: 32),
            bootstrapSecret: Data(repeating: 0x52, count: 32),
            transcriptContext: builtConfiguration.boundTranscriptContext
        )
        deviceCipher = ciphers.device
        securitySession = InternetProductSecuritySession(
            sessionEpoch: 1,
            packetCipher: ciphers.host
        )
        engine = ProductFakeWebRTCEngine(remoteCipher: deviceCipher)
        configuration = builtConfiguration
        session = InternetProductSession(
            engineFactory: { [engine] in engine },
            securitySessionFactory: { [securitySession] _ in securitySession },
            revocationHandler: { _, _ in nil }
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
        hello.capabilities = [.deviceIdentity, .endToEndEncryption, .replayProtection, .touch]
        hello.codecs = [.hevc]
        hello.transports = [.internet]
        var envelope = baseEnvelope(messageID: messageID)
        envelope.clientHello = hello
        return envelope
    }

    func videoAccepted(messageID: UInt64) -> VSEnvelope {
        var result = VSVideoConfigResult()
        result.configEpoch = 1
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
    private(set) var restartICECount = 0
    private(set) var didClose = false
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
    func start(configuration: WebRTCTransportConfiguration, channels: [WebRTCDataChannelConfiguration]) throws {}

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard let plaintext = remoteCipher.open(payload, channel: channel) else {
            completion(.failure(PlatformSecurityError.invalidInput("test decrypt failed")))
            return
        }
        lock.lock()
        storage.append(PlaintextItem(payload: plaintext, channel: channel))
        lock.unlock()
        completion(.success(()))
    }

    func restartICE() { restartICECount += 1 }
    func requestMediaKeyframe() {}
    func close() { didClose = true }
    func emitConnection(_ state: WebRTCEngineConnectionState) { callbacks?.connectionStateChanged(state) }
    func emitPath(_ path: InternetNetworkPath) { callbacks?.networkPathChanged(path) }
    func receive(_ record: Data, channel: InternetTransportChannel) {
        callbacks?.messageReceived(record, channel)
    }
}
