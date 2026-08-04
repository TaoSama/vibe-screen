import Foundation
import VibeScreenProtocol

/// Local evidence harness for the production product-session composition.
/// It uses synthetic encoded payloads so it never starts screen capture or a stream server.
enum InternetProductSessionSelfTest {
    static let keyframePlaintextSeed = "VIBE-PRODUCT-E2E-KEYFRAME-PLAINTEXT-SEED"
    static let deltaPlaintextSeed = "VIBE-PRODUCT-E2E-DELTA-PLAINTEXT-SEED"

    private static let timeout: TimeInterval = 20

    fileprivate enum SelfTestError: Error, LocalizedError {
        case missingEnvironment([String])
        case invalidEndpoint
        case invalidICEURLs
        case invalidForceRelay
        case start(String)
        case timedOut(String)
        case protocolFailure(String)

        var errorDescription: String? {
            switch self {
            case .missingEnvironment(let names):
                return "Missing environment: \(names.joined(separator: ", "))"
            case .invalidEndpoint: return "VIBE_SIGNALING_URL is invalid."
            case .invalidICEURLs: return "VIBE_WEBRTC_ICE_URLS contains an invalid ICE URL."
            case .invalidForceRelay: return "VIBE_WEBRTC_FORCE_RELAY must be true or false."
            case .start(let reason), .protocolFailure(let reason): return reason
            case .timedOut(let gate): return "Timed out waiting for \(gate)."
            }
        }
    }

    static func run(environment: [String: String] = ProcessInfo.processInfo.environment) -> Bool {
        let required = [
            "VIBE_SIGNALING_URL", "VIBE_SIGNALING_SESSION_ID",
            "VIBE_SIGNALING_HOST_TOKEN", "VIBE_SIGNALING_DEVICE_TOKEN",
        ]
        let missing = required.filter { environment[$0]?.isEmpty != false }
        guard missing.isEmpty else {
            return fail(.missingEnvironment(missing))
        }
        guard let endpoint = URL(string: environment["VIBE_SIGNALING_URL"] ?? "") else {
            return fail(.invalidEndpoint)
        }

        let sessionID = environment["VIBE_SIGNALING_SESSION_ID"]!
        do {
            let transport = try transportConfiguration(
                endpoint: endpoint,
                sessionID: sessionID,
                token: environment["VIBE_SIGNALING_HOST_TOKEN"]!,
                role: .offerer,
                environment: environment
            )
            let deviceTransport = try transportConfiguration(
                endpoint: endpoint,
                sessionID: sessionID,
                token: environment["VIBE_SIGNALING_DEVICE_TOKEN"]!,
                role: .answerer,
                environment: environment
            )
            let productConfiguration = productConfiguration(transport: transport)
            let ciphers = try PlatformSessionPacketCipher.selfTestPair(
                sessionIdentifier: sessionID,
                sharedSecret: Data(repeating: 0x71, count: 32),
                bootstrapSecret: Data(repeating: 0x72, count: 32),
                transcriptContext: productConfiguration.boundTranscriptContext
            )
            let harness = ProductDeviceHarness(
                engine: ProtectedWebRTCEngine(
                    engine: ProductionWebRTCEngine(signaling: HTTPSignalingClient()),
                    packetCipher: ciphers.device
                ),
                configuration: deviceTransport,
                sessionID: Data(sessionID.utf8)
            )
            let session = InternetProductSession(
                engineFactory: { ProductionWebRTCEngine(signaling: HTTPSignalingClient()) },
                securitySessionFactory: { _ in
                    InternetProductSecuritySession(sessionEpoch: 1, packetCipher: ciphers.host)
                },
                revocationHandler: { _, _ in nil }
            )
            defer {
                session.close()
                harness.close()
            }

            let streaming = DispatchSemaphore(value: 0)
            let input = DispatchSemaphore(value: 0)
            let keyframeRequested = DispatchSemaphore(value: 0)
            let state = ProductSelfTestState()
            session.onStateChanged = { productState in
                if case .streaming(let path) = productState {
                    state.setHostPath(path)
                    streaming.signal()
                }
            }
            session.onTouchEvent = { x, y, action, pointers, _, _ in
                if x == 0.25, y == 0.75, action == 0, pointers == 1 {
                    state.setInputReceived()
                    input.signal()
                }
            }
            session.onKeyframeRequired = { keyframeRequested.signal() }
            session.onError = { error in state.recordFailure(error.localizedDescription) }

            try harness.start()
            try session.start(configuration: productConfiguration)
            guard streaming.wait(timeout: .now() + timeout) == .success else {
                throw SelfTestError.protocolFailure(
                    "Product negotiation did not stream; hostState=\(session.snapshotState()), "
                        + "hostFailures=\(state.failures), deviceFailures=\(harness.failures)"
                )
            }
            try wait(keyframeRequested, gate: "the product keyframe request")
            try session.updateRotation(90)
            try wait(harness.rotationComplete, gate: "the versioned runtime rotation")
            try wait(streaming, gate: "streaming after rotation acknowledgment")
            try wait(keyframeRequested, gate: "the post-rotation keyframe request")

            session.sendFrame(
                Data(keyframePlaintextSeed.utf8),
                timestamp: 1_000,
                isKeyframe: true,
                sessionEpoch: 1
            )
            try wait(harness.keyframeComplete, gate: "the synthetic keyframe")
            session.sendFrame(
                Data(deltaPlaintextSeed.utf8),
                timestamp: 2_000,
                isKeyframe: false,
                sessionEpoch: 1
            )
            try wait(harness.mediaComplete, gate: "keyframe and delta media")
            try wait(input, gate: "the routed touch input")
            try wait(harness.candidatePairObserved, gate: "the selected ICE candidate pair")

            guard let evidence = harness.evidence(hostPath: state.hostPath),
                  evidence.epoch == session.currentSessionEpoch,
                  evidence.inputReceived && state.inputReceived,
                  state.failures.isEmpty else {
                throw SelfTestError.protocolFailure(
                    (state.failures + harness.failures).joined(separator: "; ")
                )
            }
            print(
                "Phase 3 product signaling self-test: PASS "
                    + "(productSession=true, protocolV1=true, route=\(pathLabel(evidence.route)), "
                    + "epoch=\(evidence.epoch), configEpoch=\(evidence.configEpoch), rotation=90, "
                    + "keyframe=true, delta=true, input=true, applicationE2EE=true, "
                    + "selectedCandidatePair=\(pathLabel(evidence.route))"
                    + "(local=\(evidence.localCandidateType),remote=\(evidence.remoteCandidateType),"
                    + "protocol=\(evidence.networkProtocol)), "
                    + "controlChannel=ordered-reliable, mediaChannel=unordered-zero-retransmit)"
            )
            return true
        } catch {
            return fail(.start(error.localizedDescription))
        }
    }

    private static func productConfiguration(
        transport: WebRTCTransportConfiguration
    ) -> InternetProductSessionConfiguration {
        InternetProductSessionConfiguration(
            transport: transport,
            hostDeviceID: "local-e2e-host",
            hostName: "Local E2E Mac",
            peerDeviceID: "local-e2e-device",
            peerIdentity: PlatformPublicIdentity(
                deviceID: "local-e2e-device",
                keyID: String(repeating: "d", count: 64),
                keyEpoch: 1,
                signingPublicKey: Data([0x04] + Array(repeating: 0x21, count: 64))
            ),
            authoritativeSessionEpoch: 1,
            sharedSecretName: "unused-local-e2e-shared-secret",
            bootstrapSecretName: "unused-local-e2e-bootstrap-secret",
            transcriptContext: Data(repeating: 0x73, count: 32),
            video: InternetProductVideoConfiguration(
                codec: .hevc,
                width: 1_920,
                height: 1_080,
                framesPerSecond: 60,
                bitrateKbps: 20_000
            ),
            heartbeatIntervalMilliseconds: 10_000,
            heartbeatTimeoutMilliseconds: 20_000
        )
    }

    private static func transportConfiguration(
        endpoint: URL,
        sessionID: String,
        token: String,
        role: WebRTCSignalingRole,
        environment: [String: String]
    ) throws -> WebRTCTransportConfiguration {
        let rawURLs = environment["VIBE_WEBRTC_ICE_URLS"] ?? "stun:127.0.0.1:9"
        let strings = rawURLs.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
        let urls = strings.compactMap(URL.init(string:))
        guard !urls.isEmpty, urls.count == strings.count else { throw SelfTestError.invalidICEURLs }
        let rawForceRelay = (environment["VIBE_WEBRTC_FORCE_RELAY"] ?? "false").lowercased()
        guard ["true", "false"].contains(rawForceRelay) else { throw SelfTestError.invalidForceRelay }
        let configuration = WebRTCTransportConfiguration(
            iceServers: [WebRTCICEServer(
                urls: urls,
                username: environment["VIBE_WEBRTC_ICE_USERNAME"],
                credential: environment["VIBE_WEBRTC_ICE_CREDENTIAL"]
            )],
            peerIdentity: role == .offerer
                ? String(repeating: "d", count: 64)
                : String(repeating: "h", count: 64),
            sessionIdentifier: sessionID,
            forceRelay: rawForceRelay == "true",
            signaling: WebRTCSignalingConfiguration(endpoint: endpoint, bearerToken: token, role: role)
        )
        try configuration.validate()
        return configuration
    }

    private static func wait(_ semaphore: DispatchSemaphore, gate: String) throws {
        guard semaphore.wait(timeout: .now() + timeout) == .success else {
            throw SelfTestError.timedOut(gate)
        }
    }

    private static func pathLabel(_ path: InternetPathKind) -> String {
        switch path {
        case .unknown: return "unknown"
        case .direct: return "direct"
        case .relay: return "relay"
        }
    }

    private static func fail(_ error: SelfTestError) -> Bool {
        print("Phase 3 product signaling self-test: FAIL (\(error.localizedDescription))")
        return false
    }
}

private struct ProductSelfTestEvidence {
    let route: InternetPathKind
    let epoch: UInt64
    let configEpoch: UInt64
    let inputReceived: Bool
    let localCandidateType: String
    let remoteCandidateType: String
    let networkProtocol: String
}

private final class ProductSelfTestState {
    private let lock = NSLock()
    private var storedHostPath: InternetPathKind?
    private var storedInputReceived = false
    private var storedFailures: [String] = []

    var hostPath: InternetPathKind? { lock.withProductSelfTestLock { storedHostPath } }
    var inputReceived: Bool { lock.withProductSelfTestLock { storedInputReceived } }
    var failures: [String] { lock.withProductSelfTestLock { storedFailures } }

    func setHostPath(_ path: InternetPathKind) {
        lock.withProductSelfTestLock { storedHostPath = path }
    }

    func setInputReceived() {
        lock.withProductSelfTestLock { storedInputReceived = true }
    }

    func recordFailure(_ reason: String) {
        lock.withProductSelfTestLock { storedFailures.append(reason) }
    }
}

private final class ProductDeviceHarness {
    let keyframeComplete = DispatchSemaphore(value: 0)
    let mediaComplete = DispatchSemaphore(value: 0)
    let candidatePairObserved = DispatchSemaphore(value: 0)
    let rotationComplete = DispatchSemaphore(value: 0)

    private let engine: WebRTCEnginePort
    private let configuration: WebRTCTransportConfiguration
    private let sessionID: Data
    private let lock = NSLock()
    private var nextMessageID: UInt64 = 1
    private var connectedPath: InternetPathKind?
    private var selectedCandidatePair: WebRTCSelectedCandidatePair?
    private var epoch: UInt64 = 0
    private var configEpoch: UInt64 = 0
    private var rotationDegrees: UInt32 = 0
    private var displayChangedRotation: UInt32 = 0
    private var keyframeReceived = false
    private var deltaReceived = false
    private var touchSent = false
    private var helloSent = false
    private var storedFailures: [String] = []

    var failures: [String] { lock.withProductSelfTestLock { storedFailures } }

    init(engine: WebRTCEnginePort, configuration: WebRTCTransportConfiguration, sessionID: Data) {
        self.engine = engine
        self.configuration = configuration
        self.sessionID = sessionID
    }

    func start() throws {
        engine.install(callbacks: WebRTCEngineCallbacks(
            connectionStateChanged: { [weak self] state in self?.handleConnection(state) },
            networkPathChanged: { _ in },
            networkQualitySampled: { _ in },
            messageReceived: { [weak self] payload, channel in self?.handle(payload, channel: channel) },
            selectedCandidatePairChanged: { [weak self] pair in
                self?.lock.withProductSelfTestLock { self?.selectedCandidatePair = pair }
                self?.candidatePairObserved.signal()
            }
        ))
        try engine.start(
            configuration: configuration,
            channels: InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
        )
    }

    func close() { engine.close() }

    func evidence(hostPath: InternetPathKind?) -> ProductSelfTestEvidence? {
        lock.withProductSelfTestLock {
            guard let pair = selectedCandidatePair,
                  pair.path == hostPath,
                  connectedPath == hostPath,
                  epoch == 1,
                  configEpoch == 2,
                  rotationDegrees == 90,
                  displayChangedRotation == 90,
                  keyframeReceived,
                  deltaReceived,
                  touchSent else { return nil }
            return ProductSelfTestEvidence(
                route: pair.path,
                epoch: epoch,
                configEpoch: configEpoch,
                inputReceived: touchSent,
                localCandidateType: pair.localCandidateType,
                remoteCandidateType: pair.remoteCandidateType,
                networkProtocol: pair.networkProtocol
            )
        }
    }

    private func handleConnection(_ state: WebRTCEngineConnectionState) {
        switch state {
        case .connected(let path):
            let shouldSendHello = lock.withProductSelfTestLock { () -> Bool in
                connectedPath = path
                guard !helloSent else { return false }
                helloSent = true
                return true
            }
            if shouldSendHello { send(clientHello()) }
        case .failed(let reason): recordFailure(reason)
        default: break
        }
    }

    private func handle(_ payload: Data, channel: InternetTransportChannel) {
        do {
            switch channel {
            case .control: try handleControl(payload)
            case .media: try handleMedia(payload)
            }
        } catch {
            recordFailure(error.localizedDescription)
        }
    }

    private func handleControl(_ payload: Data) throws {
        let envelope = try VSEnvelope(serializedBytes: payload)
        switch envelope.payload {
        case .sessionAccepted(let accepted):
            lock.withProductSelfTestLock { epoch = accepted.sessionEpoch }
        case .videoConfig(let configuration):
            let completedRotation = lock.withProductSelfTestLock { () -> Bool in
                configEpoch = configuration.configEpoch
                rotationDegrees = configuration.rotationDegrees
                return configEpoch == 2 && rotationDegrees == 90 && displayChangedRotation == 90
            }
            send(videoAccepted(configuration))
            send(touch(sessionEpoch: envelope.sessionEpoch))
            if completedRotation { rotationComplete.signal() }
        case .displayChanged(let changed):
            lock.withProductSelfTestLock { displayChangedRotation = changed.rotationDegrees }
        case .hostHello, .ping, .pong: break
        default:
            throw InternetProductSessionSelfTest.SelfTestError.protocolFailure(
                "Synthetic device received an unexpected control message."
            )
        }
    }

    private func handleMedia(_ payload: Data) throws {
        let packet = try ProtocolV1MediaPacketCodec.decode(payload)
        lock.withProductSelfTestLock {
            if packet.header.keyframe,
               packet.payload == Data(InternetProductSessionSelfTest.keyframePlaintextSeed.utf8) {
                if !keyframeReceived { keyframeComplete.signal() }
                keyframeReceived = true
            }
            if !packet.header.keyframe,
               packet.payload == Data(InternetProductSessionSelfTest.deltaPlaintextSeed.utf8) {
                deltaReceived = true
            }
            if keyframeReceived && deltaReceived { mediaComplete.signal() }
        }
    }

    private func clientHello() -> VSEnvelope {
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "local-e2e-device"
        hello.deviceName = "Synthetic Protocol v1 Device"
        hello.capabilities = [.deviceIdentity, .endToEndEncryption, .replayProtection, .touch]
        hello.codecs = [.hevc]
        hello.transports = [.internet]
        var envelope = baseEnvelope(scoped: false)
        envelope.clientHello = hello
        return envelope
    }

    private func videoAccepted(_ configuration: VSVideoConfig) -> VSEnvelope {
        var result = VSVideoConfigResult()
        result.configEpoch = configuration.configEpoch
        result.streamID = configuration.streamID
        result.accepted = true
        var envelope = baseEnvelope(scoped: true)
        envelope.videoConfigResult = result
        return envelope
    }

    private func touch(sessionEpoch: UInt64) -> VSEnvelope {
        var point = VSNormalizedPoint()
        point.x = 0.25
        point.y = 0.75
        var event = VSTouchEvent()
        event.inputID = 1
        event.pointerID = 1
        event.phase = .began
        event.position = point
        var envelope = baseEnvelope(scoped: true, sessionEpoch: sessionEpoch)
        envelope.touchEvent = event
        lock.withProductSelfTestLock { touchSent = true }
        return envelope
    }

    private func baseEnvelope(scoped: Bool, sessionEpoch explicitEpoch: UInt64? = nil) -> VSEnvelope {
        lock.withProductSelfTestLock {
            var envelope = VSEnvelope()
            envelope.protocolVersion = 1
            envelope.messageID = nextMessageID
            nextMessageID += 1
            if scoped {
                envelope.sessionID = sessionID
                envelope.sessionEpoch = explicitEpoch ?? epoch
            }
            envelope.sentAtMonotonicNs = DispatchTime.now().uptimeNanoseconds
            return envelope
        }
    }

    private func send(_ envelope: VSEnvelope) {
        do {
            let data = try envelope.serializedData()
            engine.send(data, channel: .control) { [weak self] result in
                if case .failure(let error) = result { self?.recordFailure(error.localizedDescription) }
            }
        } catch {
            recordFailure(error.localizedDescription)
        }
    }

    private func recordFailure(_ reason: String) {
        lock.withProductSelfTestLock { storedFailures.append(reason) }
    }
}

private extension NSLock {
    func withProductSelfTestLock<T>(_ operation: () -> T) -> T {
        lock()
        defer { unlock() }
        return operation()
    }
}
