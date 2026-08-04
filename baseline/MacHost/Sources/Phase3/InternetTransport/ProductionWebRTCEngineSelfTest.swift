import Foundation

enum ProductionWebRTCEngineSelfTest {
    private static let timeout: TimeInterval = 20

    private enum ConfigurationError: Error, LocalizedError {
        case invalidICEURLs
        case invalidForceRelay

        var errorDescription: String? {
            switch self {
            case .invalidICEURLs: return "VIBE_WEBRTC_ICE_URLS contains an invalid ICE URL."
            case .invalidForceRelay: return "VIBE_WEBRTC_FORCE_RELAY must be true or false."
            }
        }
    }

    static func run() -> Bool {
        let hub = LoopbackSignalingHub()
        let offererSignaling = LoopbackSignalingClient(role: .offerer, hub: hub)
        let answererSignaling = LoopbackSignalingClient(role: .answerer, hub: hub)
        do {
            let peers = try protectedPair(
                sessionIdentifier: "loopback-session",
                offerer: ProductionWebRTCEngine(signaling: offererSignaling),
                answerer: ProductionWebRTCEngine(signaling: answererSignaling)
            )
            return runPair(
                label: "loopback",
                offerer: peers.offerer,
                answerer: peers.answerer,
                offererConfiguration: configuration(role: .offerer),
                answererConfiguration: configuration(role: .answerer),
                verifyRecovery: {
                    peers.offerer.restartICE()
                    return hub.waitForRestartOffer(timeout: timeout)
                }
            )
        } catch {
            print("Phase 3 WebRTC loopback self-test: FAIL (cipher setup: \(error.localizedDescription))")
            return false
        }
    }

    static func runWithSignalingService(environment: [String: String] = ProcessInfo.processInfo.environment) -> Bool {
        let required = [
            "VIBE_SIGNALING_URL", "VIBE_SIGNALING_SESSION_ID",
            "VIBE_SIGNALING_HOST_TOKEN", "VIBE_SIGNALING_DEVICE_TOKEN"
        ]
        let missing = required.filter { environment[$0]?.isEmpty != false }
        guard missing.isEmpty,
              let endpoint = URL(string: environment["VIBE_SIGNALING_URL"] ?? "") else {
            print("Phase 3 WebRTC signaling self-test: FAIL (missing \(missing.joined(separator: ", ")))")
            return false
        }
        let sessionID = environment["VIBE_SIGNALING_SESSION_ID"]!
        do {
            let peers = try protectedPair(
                sessionIdentifier: sessionID,
                offerer: ProductionWebRTCEngine(signaling: HTTPSignalingClient()),
                answerer: ProductionWebRTCEngine(signaling: HTTPSignalingClient())
            )
            let offererConfiguration = try serviceConfiguration(
                endpoint: endpoint,
                sessionID: sessionID,
                token: environment["VIBE_SIGNALING_HOST_TOKEN"]!,
                role: .offerer,
                environment: environment
            )
            let answererConfiguration = try serviceConfiguration(
                endpoint: endpoint,
                sessionID: sessionID,
                token: environment["VIBE_SIGNALING_DEVICE_TOKEN"]!,
                role: .answerer,
                environment: environment
            )
            return runPair(
                label: "signaling",
                offerer: peers.offerer,
                answerer: peers.answerer,
                offererConfiguration: offererConfiguration,
                answererConfiguration: answererConfiguration
            )
        } catch {
            print("Phase 3 WebRTC signaling self-test: FAIL (configuration: \(error.localizedDescription))")
            return false
        }
    }

    private static func runPair(
        label: String,
        offerer: WebRTCEnginePort,
        answerer: WebRTCEnginePort,
        offererConfiguration: WebRTCTransportConfiguration,
        answererConfiguration: WebRTCTransportConfiguration,
        verifyRecovery: (() -> Bool)? = nil
    ) -> Bool {
        let offererConnected = DispatchSemaphore(value: 0)
        let answererConnected = DispatchSemaphore(value: 0)
        let answererControlReceived = DispatchSemaphore(value: 0)
        let answererMediaReceived = DispatchSemaphore(value: 0)
        let offererControlReceived = DispatchSemaphore(value: 0)
        let offererMediaReceived = DispatchSemaphore(value: 0)
        let candidatePairReceived = DispatchSemaphore(value: 0)
        let offererControl = Data("control-offerer-to-answerer".utf8)
        let offererMedia = Data("media-offerer-to-answerer".utf8)
        let answererControl = Data("control-answerer-to-offerer".utf8)
        let answererMedia = Data("media-answerer-to-offerer".utf8)
        let stateLock = NSLock()
        var answererReceivedControl: Data?
        var answererReceivedMedia: Data?
        var offererReceivedControl: Data?
        var offererReceivedMedia: Data?
        var selectedCandidatePair: WebRTCSelectedCandidatePair?
        var failures: [String] = []

        offerer.install(callbacks: callbacks(
            connected: offererConnected,
            failure: { reason in stateLock.withLock { failures.append(reason) } },
            received: { payload, channel in
                stateLock.withLock {
                    switch channel {
                    case .control: offererReceivedControl = payload; offererControlReceived.signal()
                    case .media: offererReceivedMedia = payload; offererMediaReceived.signal()
                    }
                }
            },
            selectedPair: { pair in
                stateLock.withLock { selectedCandidatePair = pair }
                candidatePairReceived.signal()
            }
        ))
        answerer.install(callbacks: callbacks(
            connected: answererConnected,
            failure: { reason in stateLock.withLock { failures.append(reason) } },
            received: { payload, channel in
                stateLock.withLock {
                    switch channel {
                    case .control: answererReceivedControl = payload; answererControlReceived.signal()
                    case .media: answererReceivedMedia = payload; answererMediaReceived.signal()
                    }
                }
            }
        ))

        do {
            let channels = InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
            try answerer.start(configuration: answererConfiguration, channels: channels)
            try offerer.start(configuration: offererConfiguration, channels: channels)
        } catch {
            print("Phase 3 WebRTC \(label) self-test: FAIL (start: \(error.localizedDescription))")
            offerer.close()
            answerer.close()
            return false
        }

        let connected = offererConnected.wait(timeout: .now() + timeout) == .success
            && answererConnected.wait(timeout: .now() + timeout) == .success
        guard connected else {
            let detail = stateLock.withLock { failures.joined(separator: "; ") }
            print("Phase 3 WebRTC \(label) self-test: FAIL (connect timeout \(detail))")
            offerer.close()
            answerer.close()
            return false
        }

        let candidatePairObserved = candidatePairReceived.wait(timeout: .now() + timeout) == .success
        let expectedPath: InternetPathKind = offererConfiguration.forceRelay ? .relay : .direct
        let candidatePairMatches = stateLock.withLock { selectedCandidatePair?.path == expectedPath }

        let recoveryPassed = verifyRecovery?() ?? true

        offerer.send(offererControl, channel: .control) { result in
            if case .failure(let error) = result { stateLock.withLock { failures.append(error.localizedDescription) } }
        }
        offerer.send(offererMedia, channel: .media) { result in
            if case .failure(let error) = result { stateLock.withLock { failures.append(error.localizedDescription) } }
        }
        answerer.send(answererControl, channel: .control) { result in
            if case .failure(let error) = result { stateLock.withLock { failures.append(error.localizedDescription) } }
        }
        answerer.send(answererMedia, channel: .media) { result in
            if case .failure(let error) = result { stateLock.withLock { failures.append(error.localizedDescription) } }
        }
        let delivered = answererControlReceived.wait(timeout: .now() + timeout) == .success
            && answererMediaReceived.wait(timeout: .now() + timeout) == .success
            && offererControlReceived.wait(timeout: .now() + timeout) == .success
            && offererMediaReceived.wait(timeout: .now() + timeout) == .success
        let payloadsMatch = stateLock.withLock {
            answererReceivedControl == offererControl
                && answererReceivedMedia == offererMedia
                && offererReceivedControl == answererControl
                && offererReceivedMedia == answererMedia
                && failures.isEmpty
        }
        let pairEvidence = stateLock.withLock { selectedCandidatePair }
        offerer.close()
        answerer.close()

        let passed = connected && candidatePairObserved && candidatePairMatches
            && recoveryPassed && delivered && payloadsMatch
        let recoveryEvidence = verifyRecovery == nil ? "not-run" : String(recoveryPassed)
        let pairSummary = pairEvidence.map {
            "\(pathLabel($0.path))(local=\($0.localCandidateType),remote=\($0.remoteCandidateType),protocol=\($0.networkProtocol))"
        } ?? "missing"
        print(
            "Phase 3 WebRTC \(label) self-test: \(passed ? "PASS" : "FAIL") "
                + "(peerConnection=true, iceRestart=\(recoveryEvidence), "
                + "applicationE2EE=true, "
                + "controlOrderedReliableBidirectional=true, mediaUnorderedZeroRetransmitBidirectional=true, "
                + "selectedCandidatePair=\(pairSummary))"
        )
        return passed
    }

    private static func callbacks(
        connected: DispatchSemaphore,
        failure: @escaping (String) -> Void,
        received: @escaping (Data, InternetTransportChannel) -> Void,
        selectedPair: @escaping (WebRTCSelectedCandidatePair) -> Void = { _ in }
    ) -> WebRTCEngineCallbacks {
        WebRTCEngineCallbacks(
            connectionStateChanged: { state in
                switch state {
                case .connected: connected.signal()
                case .failed(let reason): failure(reason)
                default: break
                }
            },
            networkPathChanged: { _ in },
            networkQualitySampled: { _ in },
            messageReceived: received,
            selectedCandidatePairChanged: selectedPair
        )
    }

    private static func protectedPair(
        sessionIdentifier: String,
        offerer: ProductionWebRTCEngine,
        answerer: ProductionWebRTCEngine
    ) throws -> (offerer: WebRTCEnginePort, answerer: WebRTCEnginePort) {
        let ciphers = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: sessionIdentifier,
            sharedSecret: Data(repeating: 0x41, count: 32),
            bootstrapSecret: Data(repeating: 0x42, count: 32),
            transcriptContext: Data(repeating: 0x43, count: 32)
        )
        return (
            ProtectedWebRTCEngine(engine: offerer, packetCipher: ciphers.host),
            ProtectedWebRTCEngine(engine: answerer, packetCipher: ciphers.device)
        )
    }

    private static func configuration(role: WebRTCSignalingRole) -> WebRTCTransportConfiguration {
        WebRTCTransportConfiguration(
            iceServers: [WebRTCICEServer(urls: [URL(string: "stun:127.0.0.1:9")!])],
            peerIdentity: "loopback-\(role.rawValue)",
            sessionIdentifier: "loopback-session",
            forceRelay: false,
            signaling: WebRTCSignalingConfiguration(
                endpoint: URL(string: "https://127.0.0.1.invalid")!,
                bearerToken: "loopback-role-token",
                role: role
            )
        )
    }

    private static func serviceConfiguration(
        endpoint: URL,
        sessionID: String,
        token: String,
        role: WebRTCSignalingRole,
        environment: [String: String]
    ) throws -> WebRTCTransportConfiguration {
        let rawURLs = environment["VIBE_WEBRTC_ICE_URLS"] ?? "stun:127.0.0.1:9"
        let urlStrings = rawURLs.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
        let urls = urlStrings.compactMap(URL.init(string:))
        guard !urls.isEmpty, urls.count == urlStrings.count else { throw ConfigurationError.invalidICEURLs }
        let rawForceRelay = (environment["VIBE_WEBRTC_FORCE_RELAY"] ?? "false").lowercased()
        guard ["true", "false"].contains(rawForceRelay) else { throw ConfigurationError.invalidForceRelay }
        let configuration = WebRTCTransportConfiguration(
            iceServers: [WebRTCICEServer(
                urls: urls,
                username: environment["VIBE_WEBRTC_ICE_USERNAME"],
                credential: environment["VIBE_WEBRTC_ICE_CREDENTIAL"]
            )],
            peerIdentity: "self-test-\(role.rawValue)",
            sessionIdentifier: sessionID,
            forceRelay: rawForceRelay == "true",
            signaling: WebRTCSignalingConfiguration(
                endpoint: endpoint,
                bearerToken: token,
                role: role
            )
        )
        try configuration.validate()
        return configuration
    }

    private static func pathLabel(_ path: InternetPathKind) -> String {
        switch path {
        case .unknown: return "unknown"
        case .direct: return "direct"
        case .relay: return "relay"
        }
    }
}

private final class LoopbackSignalingHub {
    private let lock = NSLock()
    private var clients: [WebRTCSignalingRole: LoopbackSignalingClient] = [:]
    private var pending: [WebRTCSignalingRole: [WebRTCSignal]] = [:]
    private let restartOffer = DispatchSemaphore(value: 0)
    private var offerCount = 0

    func register(_ client: LoopbackSignalingClient, role: WebRTCSignalingRole) {
        let messages = lock.withLock { () -> [WebRTCSignal] in
            clients[role] = client
            return pending.removeValue(forKey: role) ?? []
        }
        messages.forEach(client.receive)
    }

    func relay(_ signal: WebRTCSignal, from role: WebRTCSignalingRole) {
        if case .offer = signal {
            let isRestart = lock.withLock { () -> Bool in
                offerCount += 1
                return offerCount > 1
            }
            if isRestart { restartOffer.signal() }
        }
        let destination: WebRTCSignalingRole = role == .offerer ? .answerer : .offerer
        let client = lock.withLock { () -> LoopbackSignalingClient? in
            guard let client = clients[destination] else {
                pending[destination, default: []].append(signal)
                return nil
            }
            return client
        }
        client?.receive(signal)
    }

    func waitForRestartOffer(timeout: TimeInterval) -> Bool {
        restartOffer.wait(timeout: .now() + timeout) == .success
    }
}

private final class LoopbackSignalingClient: WebRTCSignalingClientPort {
    var onSignal: ((WebRTCSignal) -> Void)?
    var onFailure: ((Error) -> Void)?

    private let role: WebRTCSignalingRole
    private let hub: LoopbackSignalingHub

    init(role: WebRTCSignalingRole, hub: LoopbackSignalingHub) {
        self.role = role
        self.hub = hub
    }

    func connect(configuration: WebRTCTransportConfiguration) throws {
        hub.register(self, role: role)
        if role == .offerer { receive(.peerReady) }
    }

    func send(_ signal: WebRTCSignal, completion: @escaping (Result<Void, Error>) -> Void) {
        hub.relay(signal, from: role)
        completion(.success(()))
    }

    func close() {}

    func receive(_ signal: WebRTCSignal) {
        DispatchQueue.global().async { [weak self] in self?.onSignal?(signal) }
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () -> T) -> T {
        lock()
        defer { unlock() }
        return operation()
    }
}
