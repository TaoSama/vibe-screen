import Foundation

/// Real M150 host endpoint for Android M144 instrumentation interoperability.
/// Configuration is environment-only so credentials never appear in process arguments.
enum InternetProductExternalHostE2E {
    private static let timeout: TimeInterval = 60
    private static let keyframe = Data("VIBE-ANDROID-INTEROP-KEYFRAME".utf8)
    private static let delta = Data("VIBE-ANDROID-INTEROP-DELTA".utf8)

    static func run(environment: [String: String] = ProcessInfo.processInfo.environment) -> Bool {
        do {
            let values = try Environment(environment)
            let configuration = try values.configuration()
            let derived = try TrafficKeyDerivation.initial(
                sharedSecret: values.sharedSecret,
                bootstrapSecret: values.bootstrapSecret,
                context: configuration.boundTranscriptContext
            )
            defer { derived.zeroize() }
            guard derived.keyID == values.expectedTrafficKeyID else {
                throw Failure("traffic-key KAT mismatch")
            }
            guard configuration.boundTranscriptContext.hex == values.expectedBoundContext else {
                throw Failure("bound transcript KAT mismatch")
            }
            let identityStore = KeychainDeviceIdentityStore()
            let identity = try identityStore.createIfMissing(deviceID: values.hostID)
            let platformSecurity = PlatformSessionSecurity(
                deviceID: values.hostID,
                peerID: "interop.\(values.deviceID)",
                identityStore: identityStore
            )
            let session = InternetProductSession(
                engineFactory: { ProductionWebRTCEngine(signaling: HTTPSignalingClient()) },
                securitySessionFactory: { _ in
                    let active = try platformSecurity.startProtectedInternetSession(
                        sessionIdentifier: values.sessionID,
                        localRole: .host,
                        expectedIdentity: PairedHostIdentityBinding(
                            identity: identity.publicIdentity
                        ),
                        identityEpoch: 1,
                        sharedSecret: values.sharedSecret,
                        bootstrapSecret: values.bootstrapSecret,
                        transcriptContext: configuration.boundTranscriptContext,
                        agreedSessionEpoch: values.sessionEpoch
                    )
                    return InternetProductSecuritySession(
                        sessionEpoch: active.sessionEpoch,
                        packetCipher: active.packetCipher
                    )
                },
                revocationHandler: { _, _ in nil }
            )
            defer { session.close() }

            let streaming = DispatchSemaphore(value: 0)
            let keyframeRequired = DispatchSemaphore(value: 0)
            let touch = DispatchSemaphore(value: 0)
            let state = State()
            session.onStateChanged = { next in
                if case .streaming(let route) = next {
                    state.setRoute(route)
                    streaming.signal()
                }
            }
            session.onKeyframeRequired = { keyframeRequired.signal() }
            session.onAuthenticatedTouchEvent = { epoch, inputID, x, y, action, pointers, _, _ in
                let valid = epoch == values.sessionEpoch && inputID == 41 && x == 0.25 && y == 0.75
                    && action == 0 && pointers == 1
                if valid { state.setTouch(); touch.signal() }
                return valid
            }
            session.onError = { state.fail($0.localizedDescription) }

            try session.start(configuration: configuration)
            try wait(streaming, "Protocol v1 streaming")
            try wait(keyframeRequired, "keyframe request")
            session.sendFrame(keyframe, timestamp: 1_000, isKeyframe: true, sessionEpoch: values.sessionEpoch)
            try wait(keyframeRequired, "Android keyframe receipt acknowledgment")
            session.sendFrame(delta, timestamp: 2_000, isKeyframe: false, sessionEpoch: values.sessionEpoch)
            try wait(touch, "authenticated Android touch")
            guard state.route == values.expectedRoute, state.touchReceived, state.failures.isEmpty else {
                throw Failure("route/touch assertion failed: route=\(String(describing: state.route)) failures=\(state.failures)")
            }
            print("PHASE3_ANDROID_INTEROP_HOST_PASS route=\(values.routeLabel) epoch=\(values.sessionEpoch) kdf_kat=true transcript_kat=true video_config=true keyframe=true delta=true touch=true application_e2ee=true")
            return true
        } catch {
            print("PHASE3_ANDROID_INTEROP_HOST_FAIL \(error.localizedDescription)")
            return false
        }
    }

    private static func wait(_ semaphore: DispatchSemaphore, _ gate: String) throws {
        guard semaphore.wait(timeout: .now() + timeout) == .success else { throw Failure("timed out waiting for \(gate)") }
    }

    private struct Environment {
        let endpoint: URL
        let sessionID: String
        let hostToken: String
        let sessionEpoch: UInt64
        let hostID: String
        let deviceID: String
        let sharedSecret: Data
        let bootstrapSecret: Data
        let transcriptContext: Data
        let expectedBoundContext: String
        let expectedTrafficKeyID: String
        let iceURLs: [URL]
        let iceUsername: String?
        let iceCredential: String?
        let forceRelay: Bool

        init(_ environment: [String: String]) throws {
            func required(_ name: String) throws -> String {
                guard let value = environment[name], !value.isEmpty else { throw Failure("missing \(name)") }
                return value
            }
            guard let endpoint = URL(string: try required("VIBE_SIGNALING_URL")) else { throw Failure("invalid signaling URL") }
            self.endpoint = endpoint
            sessionID = try required("VIBE_SIGNALING_SESSION_ID")
            hostToken = try required("VIBE_SIGNALING_HOST_TOKEN")
            guard let epoch = UInt64(try required("VIBE_PRODUCT_SESSION_EPOCH")), epoch > 0 else { throw Failure("invalid session epoch") }
            sessionEpoch = epoch
            hostID = try required("VIBE_PRODUCT_HOST_ID")
            deviceID = try required("VIBE_PRODUCT_DEVICE_ID")
            sharedSecret = try Self.base64(required("VIBE_PRODUCT_SHARED_SECRET_BASE64"), count: nil)
            bootstrapSecret = try Self.base64(required("VIBE_PRODUCT_BOOTSTRAP_SECRET_BASE64"), count: 32)
            transcriptContext = try Self.base64(required("VIBE_PRODUCT_TRANSCRIPT_CONTEXT_BASE64"), count: 32)
            expectedBoundContext = try required("VIBE_PRODUCT_BOUND_CONTEXT_HEX")
            expectedTrafficKeyID = try required("VIBE_PRODUCT_TRAFFIC_KEY_ID")
            let strings = try required("VIBE_WEBRTC_ICE_URLS").split(separator: ",").map(String.init)
            iceURLs = try strings.map { value in
                guard let url = URL(string: value) else { throw Failure("invalid ICE URL") }
                return url
            }
            iceUsername = environment["VIBE_WEBRTC_ICE_USERNAME"]
            iceCredential = environment["VIBE_WEBRTC_ICE_CREDENTIAL"]
            guard let relay = Bool(environment["VIBE_WEBRTC_FORCE_RELAY"] ?? "false") else { throw Failure("invalid relay flag") }
            forceRelay = relay
        }

        var expectedRoute: InternetPathKind { forceRelay ? .relay : .direct }
        var routeLabel: String { forceRelay ? "relay" : "direct" }

        func configuration() throws -> InternetProductSessionConfiguration {
            let peerKeyID = String(repeating: "d", count: 64)
            return InternetProductSessionConfiguration(
                transport: WebRTCTransportConfiguration(
                    iceServers: [WebRTCICEServer(urls: iceURLs, username: iceUsername, credential: iceCredential)],
                    peerIdentity: peerKeyID,
                    sessionIdentifier: sessionID,
                    forceRelay: forceRelay,
                    signaling: WebRTCSignalingConfiguration(endpoint: endpoint, bearerToken: hostToken, role: .offerer)
                ),
                hostDeviceID: hostID,
                hostName: "Phase 3 Android Interop Host",
                peerDeviceID: deviceID,
                peerIdentity: PlatformPublicIdentity(
                    deviceID: deviceID,
                    keyID: peerKeyID,
                    keyEpoch: 1,
                    signingPublicKey: Data([0x04] + Array(repeating: 0x22, count: 64))
                ),
                authoritativeSessionEpoch: sessionEpoch,
                sharedSecretName: "interop-unused-shared",
                bootstrapSecretName: "interop-unused-bootstrap",
                transcriptContext: transcriptContext,
                video: InternetProductVideoConfiguration(codec: .hevc, width: 1_920, height: 1_080, framesPerSecond: 60, bitrateKbps: 20_000),
                heartbeatIntervalMilliseconds: 10_000,
                heartbeatTimeoutMilliseconds: 30_000,
                negotiationTimeoutMilliseconds: 30_000
            )
        }

        private static func base64(_ value: @autoclosure () throws -> String, count: Int?) throws -> Data {
            guard let decoded = Data(base64Encoded: try value()), !decoded.isEmpty, count == nil || decoded.count == count else {
                throw Failure("invalid base64 test material")
            }
            return decoded
        }
    }

    private final class State {
        private let lock = NSLock()
        private var storedRoute: InternetPathKind?
        private var storedTouch = false
        private var storedFailures: [String] = []
        var route: InternetPathKind? { lock.withLock { storedRoute } }
        var touchReceived: Bool { lock.withLock { storedTouch } }
        var failures: [String] { lock.withLock { storedFailures } }
        func setRoute(_ value: InternetPathKind) { lock.withLock { storedRoute = value } }
        func setTouch() { lock.withLock { storedTouch = true } }
        func fail(_ value: String) { lock.withLock { storedFailures.append(value) } }
    }

    private struct Failure: Error, LocalizedError {
        let reason: String
        init(_ reason: String) { self.reason = reason }
        var errorDescription: String? { reason }
    }
}

private extension Data {
    var hex: String { map { String(format: "%02x", $0) }.joined() }
}

private extension NSLock {
    func withLock<T>(_ operation: () -> T) -> T { lock(); defer { unlock() }; return operation() }
}
