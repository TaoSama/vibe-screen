import Foundation
import XCTest
@testable import Telemachus

final class WebRTCInternetTransportTests: XCTestCase {
    private enum TestError: Error { case sendFailed }

    func testStartsEngineWithSeparatedControlAndMediaChannels() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: engine.localCipher)

        try transport.start(configuration: validConfiguration())

        XCTAssertEqual(engine.startedChannels, [
            WebRTCDataChannelConfiguration(
                label: "vibescreen.control.v1",
                isOrdered: true,
                maximumRetransmits: nil
            ),
            WebRTCDataChannelConfiguration(
                label: "vibescreen.media.v1",
                isOrdered: false,
                maximumRetransmits: 0
            )
        ])
    }

    func testRejectsTURNWithoutCredentials() {
        let configuration = WebRTCTransportConfiguration(
            iceServers: [WebRTCICEServer(urls: [URL(string: "turn:relay.example.com:3478")!])],
            peerIdentity: "device-key-id",
            sessionIdentifier: "session-1",
            forceRelay: false
        )

        XCTAssertThrowsError(try configuration.validate()) { error in
            XCTAssertEqual(
                error as? InternetTransportError,
                .invalidConfiguration("TURN servers require a username and credential.")
            )
        }
    }

    func testRejectsCleartextRemoteSignaling() {
        let configuration = WebRTCTransportConfiguration(
            iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.com:3478")!])],
            peerIdentity: "device-key-id",
            sessionIdentifier: "session-1",
            forceRelay: false,
            signaling: WebRTCSignalingConfiguration(
                endpoint: URL(string: "http://signaling.example.com")!,
                bearerToken: "role-token",
                role: .offerer
            )
        )

        XCTAssertThrowsError(try configuration.validate()) { error in
            guard case .invalidConfiguration(let reason) = error as? InternetTransportError else {
                return XCTFail("Expected signaling configuration rejection, got \(error)")
            }
            XCTAssertTrue(reason.contains("https://"))
        }
    }

    func testDefaultProductionEngineRequiresExplicitSignaling() {
        let ciphers = makeCipherPair()
        let transport = WebRTCInternetTransport(packetCipher: ciphers.host)

        XCTAssertThrowsError(try transport.start(configuration: validConfiguration())) { error in
            guard case .engineUnavailable(let reason) = error as? InternetTransportError else {
                return XCTFail("Expected explicit production configuration failure, got \(error)")
            }
            XCTAssertTrue(reason.contains("signaling"))
        }
        transport.close()
    }

    func testUnavailableEngineFailsExplicitly() {
        let ciphers = makeCipherPair()
        let transport = WebRTCInternetTransport(
            engine: UnavailableWebRTCEngine(),
            packetCipher: ciphers.host
        )

        XCTAssertThrowsError(try transport.start(configuration: validConfiguration())) { error in
            guard case .engineUnavailable = error as? InternetTransportError else {
                return XCTFail("Expected an explicit missing-engine error, got \(error)")
            }
        }
        guard case .failed = transport.snapshot().state else {
            return XCTFail("Missing production engine must move the transport to failed")
        }
    }

    func testReliableControlMessagesRemainOrderedWhileSendIsInFlight() throws {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let first = Data([1])
        let second = Data([2])
        let third = Data([3])

        XCTAssertSuccess(transport.sendControl(first))
        XCTAssertSuccess(transport.sendControl(second))
        XCTAssertSuccess(transport.sendControl(third))
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [first])

        engine.completeSend(at: 0)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [first, second])
        engine.completeSend(at: 1)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [first, second, third])
        engine.completeSend(at: 2)

        XCTAssertEqual(transport.snapshot().controlBytesSent, 3)
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
    }

    func testControlBacklogIsBounded() {
        let engine = FakeWebRTCEngine()
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 3,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: 100
        )
        let transport = connectedTransport(engine: engine, limits: limits)

        XCTAssertSuccess(transport.sendControl(Data([1, 2])))
        XCTAssertFailure(
            transport.sendControl(Data([3, 4])),
            expected: .controlBacklogExceeded(maximumBytes: 3)
        )
        guard case .failed = transport.snapshot().state else {
            return XCTFail("A reliable-control overflow must fail the session")
        }
        XCTAssertTrue(engine.didClose)
    }

    func testEmptyMessagesAreRejectedWithoutEnteringQueues() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)

        XCTAssertFailure(transport.sendControl(Data()), expected: .emptyPayload(channel: .control))
        XCTAssertFailure(
            transport.sendMedia(EncodedInternetFrame(payload: Data(), captureTimestamp: 1, isKeyframe: true)),
            expected: .emptyPayload(channel: .media)
        )
        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
    }

    func testFailedControlSendDoesNotDeliverLaterOrderedMessages() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        var reportedError: InternetTransportError?
        transport.onError = { reportedError = $0 }

        XCTAssertSuccess(transport.sendControl(Data([1])))
        XCTAssertSuccess(transport.sendControl(Data([2])))
        engine.completeSend(at: 0, result: .failure(TestError.sendFailed))

        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
        guard case .engineSendFailed = reportedError else {
            return XCTFail("Control failure was not reported")
        }
        guard case .failed = transport.snapshot().state else {
            return XCTFail("A failed reliable-control send must fail the session")
        }
    }

    func testMediaKeepsAtMostOneNewestPendingFrame() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let keyframe = frame(1, isKeyframe: true)
        let firstDelta = frame(2, isKeyframe: false)
        let newerDelta = frame(3, isKeyframe: false)

        XCTAssertSuccess(transport.sendMedia(keyframe))
        XCTAssertSuccess(transport.sendMedia(firstDelta))
        XCTAssertSuccess(transport.sendMedia(newerDelta))

        XCTAssertEqual(engine.sentPayloads.map(\.payload), [keyframe.payload])
        XCTAssertFalse(transport.snapshot().hasPendingMediaFrame)
        XCTAssertEqual(transport.snapshot().droppedMediaFrames, 2)
        XCTAssertEqual(engine.keyframeRequestCount, 2, "One request on connect and one after reference-chain invalidation")

        engine.completeSend(at: 0)
        XCTAssertEqual(engine.sentPayloads.count, 1)
        XCTAssertSuccess(transport.sendMedia(frame(4, isKeyframe: false)))
        XCTAssertEqual(engine.sentPayloads.count, 1, "Delta frames wait for the requested recovery point")
        XCTAssertSuccess(transport.sendMedia(frame(5, isKeyframe: true)))
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [keyframe.payload, Data([5])])
    }

    func testNewerKeyframeReplacesPendingDeltaFrame() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let firstKeyframe = frame(1, isKeyframe: true)
        let delta = frame(2, isKeyframe: false)
        let newerKeyframe = frame(3, isKeyframe: true)

        XCTAssertSuccess(transport.sendMedia(firstKeyframe))
        XCTAssertSuccess(transport.sendMedia(delta))
        XCTAssertSuccess(transport.sendMedia(newerKeyframe))
        engine.completeSend(at: 0)

        XCTAssertEqual(engine.sentPayloads.map(\.payload), [firstKeyframe.payload, newerKeyframe.payload])
        XCTAssertEqual(transport.snapshot().droppedMediaFrames, 1)
    }

    func testFailedMediaSendDropsPendingDeltaAndRequestsRecoveryPoint() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)

        XCTAssertSuccess(transport.sendMedia(frame(1, isKeyframe: true)))
        XCTAssertSuccess(transport.sendMedia(frame(2, isKeyframe: false)))
        engine.completeSend(at: 0, result: .failure(TestError.sendFailed))

        XCTAssertEqual(engine.sentPayloads.count, 1)
        XCTAssertFalse(transport.snapshot().hasPendingMediaFrame)
        XCTAssertEqual(transport.snapshot().droppedMediaFrames, 2)
        XCTAssertEqual(engine.keyframeRequestCount, 2)
    }

    func testNetworkSwitchRestartsICEAndRequiresFreshKeyframe() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        engine.emitPath(InternetNetworkPath(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        engine.emitPath(InternetNetworkPath(interface: .cellular, isSatisfied: true, fingerprint: "cell-b"))

        XCTAssertEqual(engine.restartICECount, 1)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(transport.snapshot().iceRestartCount, 1)
        XCTAssertFailure(
            transport.sendMedia(frame(2, isKeyframe: false)),
            expected: .notConnected
        )

        engine.emitConnection(.connected(path: .relay))
        XCTAssertEqual(transport.snapshot().state, .connected(.relay))
        XCTAssertEqual(engine.keyframeRequestCount, 2)
    }

    func testRepeatedDisconnectAndPathEventsDoNotCreateRestartStorm() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        engine.emitPath(InternetNetworkPath(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        engine.emitConnection(.disconnected)
        engine.emitConnection(.disconnected)
        engine.emitPath(InternetNetworkPath(interface: .cellular, isSatisfied: true, fingerprint: "cell-b"))

        XCTAssertEqual(engine.restartICECount, 1)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
    }

    func testNetworkSwitchInvalidatesOldSendCompletionsAndQueues() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        XCTAssertSuccess(transport.sendControl(Data([1])))
        XCTAssertSuccess(transport.sendControl(Data([2])))

        engine.emitPath(InternetNetworkPath(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        engine.emitPath(InternetNetworkPath(interface: .cellular, isSatisfied: true, fingerprint: "cell-b"))
        engine.completeSend(at: 0)

        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)

        engine.emitConnection(.connected(path: .direct))
        XCTAssertSuccess(transport.sendControl(Data([3])))
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1]), Data([3])])
    }

    func testRecoveryStateMachineStopsAfterConfiguredAttempts() {
        var recovery = NetworkRecoveryStateMachine(
            policy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )

        XCTAssertEqual(recovery.connectivityLost(), .restartICE)
        XCTAssertEqual(recovery.connectivityLost(), .restartICE)
        XCTAssertEqual(
            recovery.connectivityLost(),
            .fail("ICE recovery exhausted after 2 attempts.")
        )
    }

    func testAdaptivePolicyDowngradesQuicklyAndUpgradesConservatively() {
        let policy = AdaptiveMediaPolicy(
            observationsBeforeDowngrade: 2,
            observationsBeforeUpgrade: 3
        )
        let poor = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 500,
            packetLossFraction: 0.2,
            availableOutgoingBitrateBps: 2_000_000
        )
        let healthy = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 50,
            packetLossFraction: 0,
            availableOutgoingBitrateBps: 30_000_000
        )

        XCTAssertNil(policy.observe(poor))
        XCTAssertEqual(policy.observe(poor), AdaptiveMediaPolicy.constrained)
        XCTAssertNil(policy.observe(healthy))
        XCTAssertNil(policy.observe(healthy))
        XCTAssertEqual(policy.observe(healthy), AdaptiveMediaPolicy.highQuality)
    }

    func testRelayBudgetStopsMediaAndSnapshotSeparatesRelayBytes() {
        let engine = FakeWebRTCEngine()
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 8,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: 2
        )
        let transport = connectedTransport(engine: engine, limits: limits, path: .relay)
        XCTAssertSuccess(transport.sendMedia(frame(1, isKeyframe: true)))
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 1)

        XCTAssertFailure(
            transport.sendMedia(EncodedInternetFrame(
                payload: Data([2, 3]),
                captureTimestamp: 2,
                isKeyframe: true
            )),
            expected: .relayBudgetExceeded(maximumBytes: 2)
        )
        engine.completeSend(at: 0)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(transport.snapshot().relayBytesSent, 1)
    }

    private func validConfiguration() -> WebRTCTransportConfiguration {
        WebRTCTransportConfiguration(
            iceServers: [
                WebRTCICEServer(urls: [URL(string: "stun:stun.example.com:3478")!]),
                WebRTCICEServer(
                    urls: [URL(string: "turns:relay.example.com:5349")!],
                    username: "ephemeral-user",
                    credential: "ephemeral-secret"
                )
            ],
            peerIdentity: "device-key-id",
            sessionIdentifier: "session-1",
            forceRelay: false
        )
    }

    private func connectedTransport(
        engine: FakeWebRTCEngine,
        limits: InternetTransportLimits = .standard,
        path: InternetPathKind = .direct
    ) -> WebRTCInternetTransport {
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            limits: limits
        )
        try! transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: path))
        return transport
    }

    private func frame(_ byte: UInt8, isKeyframe: Bool) -> EncodedInternetFrame {
        EncodedInternetFrame(
            payload: Data([byte]),
            captureTimestamp: UInt64(byte),
            isKeyframe: isKeyframe
        )
    }

    private func makeCipherPair() -> (host: PlatformSessionPacketCipher, device: PlatformSessionPacketCipher) {
        try! PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "session-1",
            sharedSecret: Data(repeating: 0x51, count: 32),
            bootstrapSecret: Data(repeating: 0x52, count: 32),
            transcriptContext: Data(repeating: 0x53, count: 32)
        )
    }

    private func XCTAssertSuccess(
        _ result: Result<Void, InternetTransportError>,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        if case .failure(let error) = result {
            XCTFail("Expected success, got \(error)", file: file, line: line)
        }
    }

    private func XCTAssertFailure(
        _ result: Result<Void, InternetTransportError>,
        expected: InternetTransportError,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        switch result {
        case .success:
            XCTFail("Expected failure \(expected), got success", file: file, line: line)
        case .failure(let error):
            XCTAssertEqual(error, expected, file: file, line: line)
        }
    }
}

private final class FakeWebRTCEngine: WebRTCEnginePort {
    struct SentPayload {
        let payload: Data
        let channel: InternetTransportChannel
        let completion: (Result<Void, Error>) -> Void
    }

    private var callbacks: WebRTCEngineCallbacks?
    let localCipher: PlatformSessionPacketCipher
    private let remoteCipher: PlatformSessionPacketCipher
    private(set) var startedChannels: [WebRTCDataChannelConfiguration] = []
    private(set) var sentPayloads: [SentPayload] = []
    private(set) var restartICECount = 0
    private(set) var keyframeRequestCount = 0
    private(set) var didClose = false

    init() {
        let ciphers = try! PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "session-1",
            sharedSecret: Data(repeating: 0x51, count: 32),
            bootstrapSecret: Data(repeating: 0x52, count: 32),
            transcriptContext: Data(repeating: 0x53, count: 32)
        )
        localCipher = ciphers.host
        remoteCipher = ciphers.device
    }

    func install(callbacks: WebRTCEngineCallbacks) {
        self.callbacks = callbacks
    }

    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws {
        startedChannels = channels
    }

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard let plaintext = remoteCipher.open(payload, channel: channel) else {
            completion(.failure(PlatformSecurityError.invalidInput("Test record authentication failed.")))
            return
        }
        sentPayloads.append(SentPayload(payload: plaintext, channel: channel, completion: completion))
    }

    func restartICE() {
        restartICECount += 1
    }

    func requestMediaKeyframe() {
        keyframeRequestCount += 1
    }

    func close() {
        didClose = true
        remoteCipher.close()
    }

    func completeSend(at index: Int, result: Result<Void, Error> = .success(())) {
        sentPayloads[index].completion(result)
    }

    func emitConnection(_ state: WebRTCEngineConnectionState) {
        callbacks?.connectionStateChanged(state)
    }

    func emitPath(_ path: InternetNetworkPath) {
        callbacks?.networkPathChanged(path)
    }
}
