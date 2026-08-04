import Foundation

enum InternetTransportSelfTest {
    static func run() -> Bool {
        let ciphers: (host: PlatformSessionPacketCipher, device: PlatformSessionPacketCipher)
        do {
            ciphers = try PlatformSessionPacketCipher.selfTestPair(
                sessionIdentifier: "session-test",
                sharedSecret: Data(repeating: 0x11, count: 32),
                bootstrapSecret: Data(repeating: 0x22, count: 32),
                transcriptContext: Data(repeating: 0x33, count: 32)
            )
        } catch {
            print("Phase 3 Internet self-test: FAIL (cipher setup: \(error))")
            return false
        }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 32,
            maximumBufferedControlBytes: 64,
            maximumMediaFrameBytes: 64,
            maximumRelayBytesPerSession: 100
        )
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            limits: limits,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2),
            adaptivePolicy: AdaptiveMediaPolicy(
                observationsBeforeDowngrade: 1,
                observationsBeforeUpgrade: 1
            )
        )

        var requestedKeyframes = 0
        var adaptiveProfile: AdaptiveMediaProfile?
        var receivedControl: [Data] = []
        transport.onKeyframeRequired = { requestedKeyframes += 1 }
        transport.onAdaptiveProfileChanged = { adaptiveProfile = $0 }
        transport.onControlReceived = { receivedControl.append($0) }

        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [
                    WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!]),
                    WebRTCICEServer(
                        urls: [URL(string: "turns:relay.example.test:5349")!],
                        username: "short-lived-user",
                        credential: "short-lived-secret"
                    )
                ],
                peerIdentity: "device-test",
                sessionIdentifier: "session-test",
                forceRelay: true
            ))
        } catch {
            print("Phase 3 Internet self-test: FAIL (start: \(error))")
            return false
        }

        engine.connect(path: .relay)
        let inboundControl = try? ciphers.device.seal(Data("encrypted-inbound".utf8), channel: .control)
        if let inboundControl {
            engine.receive(inboundControl, channel: .control)
            engine.receive(inboundControl, channel: .control)
        }
        let keyframe = EncodedInternetFrame(
            payload: Data(repeating: 0x01, count: 30),
            captureTimestamp: 1,
            isKeyframe: true
        )
        let staleFrame = EncodedInternetFrame(
            payload: Data(repeating: 0x02, count: 30),
            captureTimestamp: 2,
            isKeyframe: true
        )
        let latestFrame = EncodedInternetFrame(
            payload: Data(repeating: 0x04, count: 30),
            captureTimestamp: 3,
            isKeyframe: true
        )
        let overBudgetFrame = EncodedInternetFrame(
            payload: Data(repeating: 0x05, count: 64),
            captureTimestamp: 4,
            isKeyframe: false
        )

        let controlAccepted = transport.sendControl(Data(repeating: 0x03, count: 10)).isSuccess
        let emptyControlRejected = transport.sendControl(Data()).isEmptyPayloadFailure
        let keyframeAccepted = transport.sendMedia(keyframe).isSuccess
        let staleFrameAccepted = transport.sendMedia(staleFrame).isSuccess
        let latestFrameAccepted = transport.sendMedia(latestFrame).isSuccess
        let overBudgetRejected = transport.sendMedia(overBudgetFrame).isRelayBudgetFailure
        engine.completeAllSends()

        engine.changePath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))
        engine.changePath(InternetNetworkPath(
            interface: .cellular,
            isSatisfied: true,
            fingerprint: "cellular-b"
        ))
        engine.sample(InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 500,
            packetLossFraction: 0.2,
            availableOutgoingBitrateBps: 1_000_000
        ))

        let snapshot = transport.snapshot()
        let missingSignalingRejected = productionRejectsMissingSignaling()
        let backlogFailsClosed = controlBacklogFailsClosed()
        let legacyCleanupCrashSafe = LegacyGlobalRevocationCleanupSelfTest.run()
        let unknownCandidatePathFailsClosed =
            SelectedCandidatePathResolver.resolve(
                localCandidateType: nil,
                remoteCandidateType: "host"
            ) == .unknown &&
            SelectedCandidatePathResolver.resolve(
                localCandidateType: "host",
                remoteCandidateType: "srflx"
            ) == .direct &&
            SelectedCandidatePathResolver.mustFailClosed(
                publishedPath: .direct,
                observedPath: .unknown
            ) &&
            SelectedCandidatePathResolver.mustFailClosed(
                publishedPath: .relay,
                observedPath: nil
            )
        let passed = controlAccepted && emptyControlRejected && keyframeAccepted && staleFrameAccepted
            && latestFrameAccepted && overBudgetRejected
            && engine.channelConfigurations == [
                InternetTransportChannel.control.dataChannelConfiguration,
                InternetTransportChannel.media.dataChannelConfiguration
            ]
            && engine.restartCount == 1
            && snapshot.relayBytesSent == 70
            && snapshot.relayBytesReserved == 0
            && snapshot.droppedMediaFrames == 1
            && engine.mediaPayloads == [keyframe.payload, latestFrame.payload]
            && receivedControl == [Data("encrypted-inbound".utf8)]
            && requestedKeyframes >= 1
            && adaptiveProfile == AdaptiveMediaPolicy.constrained
            && missingSignalingRejected
            && backlogFailsClosed
            && legacyCleanupCrashSafe
            && unknownCandidatePathFailsClosed

        transport.close()
        print(
            "Phase 3 Internet self-test: \(passed ? "PASS" : "FAIL") "
                + "(channels=\(engine.channelConfigurations.count), relayBytes=\(snapshot.relayBytesSent), "
                + "reserved=\(snapshot.relayBytesReserved), latestFrameDrops=\(snapshot.droppedMediaFrames), "
                + "iceRestarts=\(engine.restartCount), legacyCleanupCrashSafe=\(legacyCleanupCrashSafe), "
                + "unknownCandidatePathFailsClosed=\(unknownCandidatePathFailsClosed))"
        )
        return passed
    }

    private static func productionRejectsMissingSignaling() -> Bool {
        let engine = ProductionWebRTCEngine()
        defer { engine.close() }
        do {
            try engine.start(
                configuration: WebRTCTransportConfiguration(
                    iceServers: [WebRTCICEServer(urls: [URL(string: "stun:127.0.0.1:9")!])],
                    peerIdentity: "missing-signaling",
                    sessionIdentifier: "missing-signaling-session",
                    forceRelay: false
                ),
                channels: InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
            )
            return false
        } catch WebRTCSignalingError.missingConfiguration {
            return true
        } catch {
            return false
        }
    }

    private static func controlBacklogFailsClosed() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "backlog-session",
            sharedSecret: Data(repeating: 0x61, count: 32),
            bootstrapSecret: Data(repeating: 0x62, count: 32),
            transcriptContext: Data(repeating: 0x63, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 8,
                maximumBufferedControlBytes: 1,
                maximumMediaFrameBytes: 8,
                maximumRelayBytesPerSession: 8
            )
        )
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "backlog-peer",
                sessionIdentifier: "backlog-session",
                forceRelay: false
            ))
        } catch {
            return false
        }
        engine.connect(path: .direct)
        guard transport.sendControl(Data([1])).isSuccess else { return false }
        guard transport.sendControl(Data([2])).isControlBacklogFailure else { return false }
        if case .failed = transport.snapshot().state { return true }
        return false
    }
}

private final class SelfTestWebRTCEngine: WebRTCEnginePort {
    private let remoteCipher: PlatformSessionPacketCipher
    private var callbacks: WebRTCEngineCallbacks?
    private var pendingCompletions: [(Result<Void, Error>) -> Void] = []
    private(set) var channelConfigurations: [WebRTCDataChannelConfiguration] = []
    private(set) var mediaPayloads: [Data] = []
    private(set) var restartCount = 0

    init(remoteCipher: PlatformSessionPacketCipher) {
        self.remoteCipher = remoteCipher
    }

    func install(callbacks: WebRTCEngineCallbacks) {
        self.callbacks = callbacks
    }

    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws {
        channelConfigurations = channels
    }

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard let plaintext = remoteCipher.open(payload, channel: channel) else {
            completion(.failure(PlatformSecurityError.invalidInput("Self-test record authentication failed.")))
            return
        }
        if channel == .media { mediaPayloads.append(plaintext) }
        pendingCompletions.append(completion)
    }

    func restartICE() { restartCount += 1 }
    func requestMediaKeyframe() {}
    func close() { remoteCipher.close() }

    func receive(_ record: Data, channel: InternetTransportChannel) {
        callbacks?.messageReceived(record, channel)
    }

    func connect(path: InternetPathKind) {
        callbacks?.connectionStateChanged(.connected(path: path))
    }

    func changePath(_ path: InternetNetworkPath) {
        callbacks?.networkPathChanged(path)
    }

    func sample(_ sample: InternetNetworkQualitySample) {
        callbacks?.networkQualitySampled(sample)
    }

    func completeAllSends() {
        while !pendingCompletions.isEmpty {
            pendingCompletions.removeFirst()(.success(()))
        }
    }
}

private extension Result where Success == Void, Failure == InternetTransportError {
    var isSuccess: Bool {
        if case .success = self { return true }
        return false
    }

    var isRelayBudgetFailure: Bool {
        if case .failure(.relayBudgetExceeded) = self { return true }
        return false
    }

    var isEmptyPayloadFailure: Bool {
        if case .failure(.emptyPayload) = self { return true }
        return false
    }

    var isControlBacklogFailure: Bool {
        if case .failure(.controlBacklogExceeded) = self { return true }
        return false
    }
}
