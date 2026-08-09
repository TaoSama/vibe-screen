import Foundation
import Network
import VibeScreenProtocol

private enum WireMessage {
    static let legacyVideoFrame: UInt8 = 0
    static let displayConfig: UInt8 = 1
    static let touchEvent: UInt8 = 2
    static let ping: UInt8 = 4
    static let pong: UInt8 = 5
    static let videoFrameWithMetadata: UInt8 = 6
    static let keyframeRequest: UInt8 = 7
    static let clientSupportsFrameMetadata: UInt8 = 8
    /// Client→server Protocol v1 opt-in. The host acknowledges with [13, 1],
    /// after which this connection permanently uses framed Protocol v1.
    static let protocolV1Offer = ProtocolV1Upgrade.offer
    /// Client→server, payload-free (old hosts consume 1 byte safely):
    /// "this device has no HEVC decoder".
    static let clientAvcOnly: UInt8 = 9
    /// Server→client, 1-byte payload (StreamCodec.wireId). Sent ONLY to
    /// clients that sent clientAvcOnly — old clients disconnect on unknown
    /// message types, so this must never be sent unsolicited.
    static let codecSelected: UInt8 = 10
    /// Client→server, 66-byte message: type + 64-byte null-padded UTF-8 model
    /// name + 1-byte max refresh rate (Hz). Sent only after the host accepts
    /// via `hostAcceptsDeviceInfo` so older Macs never see the payload.
    static let clientDeviceInfo: UInt8 = 11
    /// Payload-free capability handshake. Client offers; host accepts only if
    /// it understands type 11. Older hosts consume the offer as 1 unknown byte
    /// and never reply, so the client skips the payload.
    static let deviceInfoCapability: UInt8 = 12
    /// Server→client, payload-free: server shutting down intentionally.
    /// Client should close without attempting reconnect.
    /// Uses the free slot 3 (between touch=2 and ping=4). Do not use 12 —
    /// that is `deviceInfoCapability` and would trigger device-info send.
    static let serverShutdown: UInt8 = 3
}

private extension NWEndpoint {
    var isLoopback: Bool {
        switch self {
        case .hostPort(let host, _):
            switch host {
            case .ipv4(let v4): return v4.isLoopback
            case .ipv6(let v6): return v6.isLoopback
            case .name(let name, _): return name == "localhost"
            @unknown default: return false
            }
        default:
            return false
        }
    }
}

enum StreamingServerError: LocalizedError {
    case startupTimedOut
    case listenerCancelled
    case protocolNotReady

    var errorDescription: String? {
        switch self {
        case .startupTimedOut:
            return "Timed out while opening the streaming port."
        case .listenerCancelled:
            return "The streaming listener was cancelled before it became ready."
        case .protocolNotReady:
            return "Protocol v1 media configuration is not ready."
        }
    }
}

enum StreamingServerMode {
    case usb
    case wireless(authToken: Data)
}

struct NegotiatedDisplayConfiguration: Equatable {
    let width: Int
    let height: Int
    let rotation: Int
}

final class ClientCallbackGenerationGate {
    private let lock = NSLock()
    private var currentGeneration: UInt64 = 0

    func advance(to generation: UInt64) {
        lock.withLock {
            currentGeneration = max(currentGeneration, generation)
        }
    }

    func isCurrent(_ generation: UInt64) -> Bool {
        lock.withLock { currentGeneration == generation }
    }

    func performIfCurrent(
        _ generation: UInt64,
        operation: () -> Void
    ) -> Bool {
        // The operation is deliberately linearized with generation changes.
        // It must not synchronously re-enter this gate or wait for networkQueue.
        lock.withLock {
            guard currentGeneration == generation else { return false }
            operation()
            return true
        }
    }
}

class StreamingServer: EncodedFrameSink {
    private static let networkQueueKey = DispatchSpecificKey<ObjectIdentifier>()
    // Wireless admission adds a full authentication round trip before the
    // client can offer Protocol v1. Keep the legacy fallback bounded while
    // allowing normal LAN scheduling jitter; USB has no authentication hop.
    private static let usbProtocolUpgradeGraceMilliseconds = 100
    private static let wirelessProtocolUpgradeGraceMilliseconds = 500
    private enum ConnectionProtocolMode: Equatable {
        case legacy
        case protocolV1
    }

    private let port: UInt16
    private let mode: StreamingServerMode
    private var listener: NWListener?
    private var connection: NWConnection?
    var onClientConnected: ((UInt64) -> Void)?
    var onClientDisconnected: ((UInt64) -> Void)?
    /// Fired once per connection during protocol startup, BEFORE the display
    /// config is sent, for every outcome (.hevc or .h264) — so the capture
    /// pipeline can also revert to HEVC after an AVC-only client goes away.
    var onCodecNegotiated: ((
        StreamCodec,
        UInt64,
        @escaping (NegotiatedDisplayConfiguration?) -> Void
    ) -> Void)?
    // Touch callback: (x1, y1, action, pointerCount, x2, y2)
    var onTouchEvent: ((Float, Float, Int, Int, Float, Float, UInt64) -> Void)?
    var onInputCancelled: ((UInt64) -> Void)?
    var onStats: ((Double, Double, UInt64) -> Void)?
    var onKeyframeRequested: ((Bool, UInt64) -> Void)?
    // Whether host wants to receive touch events from client. Ping/pong is
    // handled regardless. When false, incoming touch frames are dropped
    // immediately without parsing or dispatching to main queue.
    var touchEnabled: Bool = true

    var onWirelessClientPaired: ((String, UInt64) -> Void)?
    var onServerFailed: ((Error) -> Void)?
    /// Fired when the Android client reports Build.MODEL + max panel Hz.
    var onDeviceInfoReceived: ((String, UInt8, UInt64) -> Void)?
    var onPointerEvent: ((Float, Float, VSInputPhase, UInt32, UInt64) -> Void)?
    var onScrollEvent: ((Double, Double, UInt64) -> Void)?
    var onKeyEvent: ((UInt32, Bool, UInt32, String, UInt64) -> Void)?
    var onProtocolErrorReceived: ((VSProtocolError, UInt64) -> Void)?
    /// Fired on the network queue when a Protocol v1 client selects a different
    /// display. The AppDelegate hops to the main actor to switch the capture
    /// source and drive protocol re-negotiation.
    var onDisplaySelectionRequested: ((String) -> Void)?

    /// Fired on the network queue when a Protocol v1 client requests new video
    /// preferences. The AppDelegate hops to the main actor to apply them to the
    /// host encoder and live capture. The session defers the bumped-epoch
    /// VideoConfig renegotiation until the host confirms the encoder actually
    /// adopted the settings by calling completeProtocolV1VideoPreferences with
    /// the same token, so a client can never accept a new VideoConfig while the
    /// encoder still runs the previous configuration.
    var onVideoPreferencesRequested:
        ((_ token: UInt64,
          _ bitrateKbps: UInt32,
          _ framesPerSecond: UInt32,
          _ qualityPreset: VSVideoQualityPreset,
          _ resetQualityToAuto: Bool) -> Void)?

    private let frameQueue = DispatchQueue(label: "frameQueue", qos: .userInteractive)
    private let receiveQueue = DispatchQueue(label: "receiveQueue", qos: .userInteractive)
    private let networkQueue = DispatchQueue(label: "networkQueue", qos: .userInteractive)
    private struct PendingFrame {
        let data: Data
        let timestamp: UInt64
        let isKeyframe: Bool
        let connection: NWConnection
        let generation: UInt64
        let clientGeneration: UInt64
        let sessionEpoch: UInt64
    }
    /// At most one frame is inside Network.framework and one newer frame is
    /// retained. This prevents a transient USB/Wi-Fi slowdown from becoming a
    /// seconds-long FIFO of pictures the viewer no longer wants to see.
    private var sendInFlight = false
    private var pendingFrames: LatestFrameQueue<PendingFrame>
    private var framePipelineGeneration: UInt64 = 0
    private var bytesSent: UInt64 = 0
    private var frameCount: UInt64 = 0
    private var droppedFrames: UInt64 = 0
    private var lastStatsTime = DispatchTime.now()
    private var displayWidth = 1920
    private var displayHeight = 1080
    private var rotation = 0
    private var protocolV1FramesPerSecond: UInt32 = 60
    private var protocolV1BitrateKbps: UInt32 = 20_000
    private var protocolV1DisplayID = "active-display"
    private var protocolV1DisplayName = "Vibe Screen Display"
    private var protocolV1DisplayIsVirtual = true
    private var protocolV1Displays: [ProtocolV1DisplayInfo] = []
    private var isReceiving = false
    private var isStopped = false
    private var connectionReady = false
    private var activeConnectionGeneration: UInt64 = 0
    private let clientCallbackGeneration = ClientCallbackGenerationGate()
    private var activeConnectionIsWireless = false
    private var clientSupportsFrameMetadata = false
    private var clientIsAvcOnly = false
    private var codecNegotiationGeneration: UInt64?
    private var connectionProtocolMode = ConnectionProtocolMode.legacy
    private var protocolV1Framer = ProtocolV1Framer()
    private var protocolV1Session: ProtocolV1SessionCoordinator?
    private var protocolV1TouchAggregator = ProtocolV1TouchAggregator()
    private var inputBuffer = Data()
    private var expectedAuthToken: Data?
    private var pendingHandshakeTimeouts: [ObjectIdentifier: DispatchWorkItem] = [:]
    private var pendingWirelessConnections: [ObjectIdentifier: NWConnection] = [:]
    private let sessionEpochGate = SessionEpochGate()
    private var recoveryController = ConnectionRecoveryController(
        heartbeatTimeoutNs: 5_000_000_000
    )
    private var heartbeatTimer: DispatchSourceTimer?
    private var stopSequence: UInt64 = 0
    private var stopInProgress: UInt64?
    private let telemetry: TelemetryRecording?

    var currentSessionEpoch: UInt64 { sessionEpochGate.current }

    init(
        port: UInt16,
        mode: StreamingServerMode = .usb,
        telemetry: TelemetryRecording? = nil
    ) {
        self.port = port
        self.mode = mode
        if let telemetry {
            self.telemetry = telemetry
        } else if let path = ProcessInfo.processInfo.environment["VIBE_SCREEN_TELEMETRY_PATH"],
                  !path.isEmpty {
            do {
                self.telemetry = try JSONLTelemetrySink(
                    url: URL(fileURLWithPath: path)
                )
            } catch {
                debugLog("Unable to open telemetry JSONL sink at \(path): \(error)")
                self.telemetry = nil
            }
        } else {
            self.telemetry = nil
        }
        do {
            pendingFrames = try LatestFrameQueue(
                capacity: 1,
                isKeyframe: { $0.isKeyframe }
            )
        } catch {
            preconditionFailure("Invalid fixed frame queue capacity: \(error)")
        }
        if case .wireless(let authToken) = mode {
            expectedAuthToken = authToken
        }
        networkQueue.setSpecific(key: Self.networkQueueKey, value: ObjectIdentifier(self))
    }

    /// Starts the listener and returns only after Network.framework reports it
    /// ready. This prevents callers from presenting a false "Running" state
    /// when the port is occupied or listener creation fails.
    func start(timeout: TimeInterval = 3) throws {
        isStopped = false
        recoveryController = ConnectionRecoveryController(
            heartbeatTimeoutNs: 5_000_000_000
        )
        let params = NWParameters.tcp

        if let tcpOptions = params.defaultProtocolStack.transportProtocol as? NWProtocolTCP.Options {
            tcpOptions.noDelay = true
        }

        let newListener: NWListener
        switch mode {
        case .usb:
            // adb reverse reaches the Mac through loopback. Do not expose the
            // unauthenticated USB listener to the LAN.
            params.requiredLocalEndpoint = .hostPort(
                host: NWEndpoint.Host("127.0.0.1"),
                port: NWEndpoint.Port(rawValue: port)!
            )
            newListener = try NWListener(using: params)
        case .wireless:
            newListener = try NWListener(
                using: params,
                on: NWEndpoint.Port(rawValue: port)!
            )
        }
        listener = newListener

        let startupSignal = DispatchSemaphore(value: 0)
        let startupLock = NSLock()
        var startupResult: Result<Void, Error>?
        var startupFinished = false
        var listenerWasReady = false

        func completeStartup(_ result: Result<Void, Error>) {
            startupLock.lock()
            guard !startupFinished else {
                startupLock.unlock()
                return
            }
            startupFinished = true
            startupResult = result
            startupLock.unlock()
            startupSignal.signal()
        }

        newListener.newConnectionHandler = { [weak self] newConnection in
            self?.handleConnection(newConnection)
        }

        newListener.stateUpdateHandler = { [weak self, weak newListener] state in
            guard let self else { return }
            switch state {
            case .ready:
                listenerWasReady = true
                debugLog("TCP server listening on port \(self.port)")
                completeStartup(.success(()))
            case .failed(let error):
                debugLog("Server failed: \(error)")
                completeStartup(.failure(error))
                if listenerWasReady, newListener === self.listener {
                    self.onServerFailed?(error)
                }
            case .cancelled:
                completeStartup(.failure(StreamingServerError.listenerCancelled))
            default:
                break
            }
        }

        newListener.start(queue: networkQueue)
        guard startupSignal.wait(timeout: .now() + timeout) == .success else {
            newListener.cancel()
            listener = nil
            throw StreamingServerError.startupTimedOut
        }

        switch startupResult {
        case .success:
            return
        case .failure(let error):
            listener = nil
            throw error
        case .none:
            listener = nil
            throw StreamingServerError.startupTimedOut
        }
    }

    private func handleConnection(_ newConnection: NWConnection) {
        debugLog("New connection incoming...")
        newConnection.stateUpdateHandler = { [weak self] state in
            debugLog("Connection state: \(state)")
            switch state {
            case .ready:
                self?.onConnectionReady(newConnection)
            case .failed(let error):
                debugLog("Connection failed: \(error)")
                self?.connectionEnded(newConnection)
            case .cancelled:
                debugLog("Connection cancelled")
                self?.connectionEnded(newConnection)
            default:
                break
            }
        }

        newConnection.start(queue: networkQueue)
    }

    private func onConnectionReady(_ conn: NWConnection) {
        switch mode {
        case .usb:
            guard conn.endpoint.isLoopback else {
                debugLog("Rejecting non-loopback client in USB mode")
                conn.cancel()
                return
            }
            debugLog("Client connected via loopback (USB) — skipping auth")
            admitConnection(conn, isWireless: false, deviceName: nil)
        case .wireless:
            guard let expected = expectedAuthToken else {
                debugLog("Rejecting wireless client: no active authentication token")
                conn.cancel()
                return
            }
            // Wireless mode authenticates loopback clients as well. Otherwise
            // any local process could take over a wireless session.
            debugLog("Client connected via wireless listener — running auth handshake")
            runAuthHandshake(connection: conn, expectedToken: expected)
        }
    }

    private func admitConnection(
        _ conn: NWConnection,
        isWireless: Bool,
        deviceName: String?
    ) {
        guard !isStopped else {
            conn.cancel()
            return
        }

        cancelHandshakeTimeout(for: conn)
        heartbeatTimer?.cancel()
        heartbeatTimer = nil
        let oldConnection = connection
        let sessionEpoch: UInt64
        do {
            sessionEpoch = try sessionEpochGate.beginNextSession()
        } catch {
            debugLog("Unable to create a new session epoch: \(error)")
            recordTelemetry(
                "session_admission_failed",
                epoch: sessionEpochGate.current,
                attributes: ["error": .string(String(describing: error))]
            )
            conn.cancel()
            return
        }
        activeConnectionGeneration &+= 1
        let generation = activeConnectionGeneration
        clientCallbackGeneration.advance(to: generation)
        connection = conn
        activeConnectionIsWireless = isWireless
        connectionReady = false
        clientSupportsFrameMetadata = false
        clientIsAvcOnly = false
        codecNegotiationGeneration = nil
        connectionProtocolMode = .legacy
        protocolV1Framer = ProtocolV1Framer()
        protocolV1Session = nil
        protocolV1TouchAggregator.reset()
        inputBuffer.removeAll(keepingCapacity: true)
        isReceiving = false
        droppedFrames = 0

        frameQueue.async { [weak self] in
            guard let self else { return }
            self.framePipelineGeneration &+= 1
            self.sendInFlight = false
            _ = self.pendingFrames.reset(requiresKeyframe: true)
        }
        recordTelemetry(
            "session_admitted",
            epoch: sessionEpoch,
            attributes: ["transport": .string(isWireless ? "lan" : "usb")]
        )

        // Promote the authenticated candidate before cancelling the previous
        // session. Its stale cancellation callback then cannot mutate this one.
        if let oldConnection, oldConnection !== conn {
            oldConnection.cancel()
        }

        if let deviceName {
            onWirelessClientPaired?(deviceName, generation)
        }
        startReceivingTouch(on: conn, generation: generation)

        // Give new clients a short chance to opt in before the first frame.
        // Legacy clients send no capability message, so we continue shortly
        // after this window with the old frame type.
        let upgradeGraceMilliseconds = isWireless
            ? Self.wirelessProtocolUpgradeGraceMilliseconds
            : Self.usbProtocolUpgradeGraceMilliseconds
        networkQueue.asyncAfter(deadline: .now() + .milliseconds(upgradeGraceMilliseconds)) {
            [weak self, weak conn] in
            guard let self = self, let conn = conn else { return }
            self.requestProtocolStartup(on: conn, generation: generation)
        }
    }

    private func connectionEnded(_ conn: NWConnection) {
        cancelHandshakeTimeout(for: conn)
        pendingWirelessConnections.removeValue(forKey: ObjectIdentifier(conn))
        guard connection === conn else { return }
        connection = nil
        connectionReady = false
        isReceiving = false
        heartbeatTimer?.cancel()
        heartbeatTimer = nil
        activeConnectionGeneration &+= 1
        codecNegotiationGeneration = nil
        clientCallbackGeneration.advance(to: activeConnectionGeneration)
        inputBuffer.removeAll(keepingCapacity: true)
        connectionProtocolMode = .legacy
        protocolV1Framer = ProtocolV1Framer()
        protocolV1Session = nil
        protocolV1TouchAggregator.reset()
        let epoch = sessionEpochGate.current
        let nowNs = DispatchTime.now().uptimeNanoseconds
        let retryDelayNs: UInt64
        if case .waitingToReconnect(_, let deadlineNs) = recoveryController.state {
            retryDelayNs = deadlineNs > nowNs ? deadlineNs - nowNs : 0
        } else {
            retryDelayNs = recoveryController.scheduleReconnect(nowNs: nowNs)
        }
        recordTelemetry(
            "session_disconnected",
            epoch: epoch,
            attributes: ["suggested_retry_delay_ns": .unsigned(retryDelayNs)]
        )
        onClientDisconnected?(activeConnectionGeneration)
    }

    private func requestProtocolStartup(on conn: NWConnection, generation: UInt64) {
        networkQueue.async { [weak self, weak conn] in
            guard let self, let conn else { return }
            self.finishProtocolStartup(on: conn, generation: generation)
        }
    }

    /// Must execute on networkQueue so disconnect and heartbeat transitions
    /// cannot race protocol admission.
    private func finishProtocolStartup(on conn: NWConnection, generation: UInt64) {
        guard connection === conn,
              activeConnectionGeneration == generation,
              !isStopped,
              !connectionReady,
              codecNegotiationGeneration != generation,
              connectionProtocolMode == .legacy else { return }

        let clientCodecs: [StreamCodec] = clientIsAvcOnly ? [.h264] : [.hevc, .h264]
        let decision: CodecFallbackDecision
        do {
            decision = try CodecFallbackPolicy.select(
                preferred: .hevc,
                hostSupported: [.hevc, .h264],
                clientSupported: clientCodecs
            )
        } catch {
            debugLog("Codec negotiation failed: \(error)")
            recordTelemetry(
                "codec_negotiation_failed",
                epoch: sessionEpochGate.current,
                attributes: ["error": .string(String(describing: error))]
            )
            conn.cancel()
            return
        }
        let codec = decision.selected
        if clientIsAvcOnly {
            // Safe to send: this client opted in via type 9. Must precede the
            // display config so the client knows the codec before it sizes
            // and configures its decoder.
            let msg = Data([WireMessage.codecSelected, codec.wireId])
            conn.send(content: msg, completion: .contentProcessed { [weak self] error in
                if let error {
                    self?.recordTelemetry(
                        "control_send_failed",
                        epoch: self?.sessionEpochGate.current,
                        attributes: [
                            "message": .string("codec_selected"),
                            "error": .string(error.localizedDescription)
                        ]
                    )
                }
            })
            debugLog("Sent codecSelected: H.264")
        }
        recordTelemetry(
            "codec_selected",
            epoch: sessionEpochGate.current,
            attributes: [
                "codec": .string(codec == .hevc ? "hevc" : "h264"),
                "reason": .string(decision.reason.rawValue)
            ]
        )
        codecNegotiationGeneration = generation
        let completion: (NegotiatedDisplayConfiguration?) -> Void = {
            [weak self, weak conn] configuration in
            guard let self, let conn else { return }
            self.networkQueue.async {
                guard self.connection === conn,
                      self.activeConnectionGeneration == generation,
                      self.codecNegotiationGeneration == generation,
                      self.connectionProtocolMode == .legacy,
                      !self.isStopped else { return }
                self.codecNegotiationGeneration = nil
                guard let configuration else {
                    conn.cancel()
                    return
                }
                self.setDisplaySize(
                    width: configuration.width,
                    height: configuration.height,
                    rotation: configuration.rotation
                )
                self.completeProtocolStartup(
                    on: conn,
                    generation: generation,
                    codec: codec
                )
            }
        }
        if let onCodecNegotiated {
            onCodecNegotiated(codec, generation, completion)
        } else {
            completion(NegotiatedDisplayConfiguration(
                width: displayWidth,
                height: displayHeight,
                rotation: rotation
            ))
        }
    }

    private func completeProtocolStartup(
        on conn: NWConnection,
        generation: UInt64,
        codec: StreamCodec
    ) {
        guard connection === conn,
              activeConnectionGeneration == generation,
              connectionProtocolMode == .legacy,
              !isStopped,
              !connectionReady else { return }

        debugLog("Client connected - sending display config first")
        sendDisplaySize()
        connectionReady = true
        recoveryController.didConnect(
            epoch: sessionEpochGate.current,
            nowNs: DispatchTime.now().uptimeNanoseconds
        )
        startHeartbeatMonitor(connection: conn, epoch: sessionEpochGate.current)
        debugLog("Connection ready for frames (metadata=\(clientSupportsFrameMetadata ? "on" : "off"), codec=\(codec))")
        onClientConnected?(generation)
    }

    private func startHeartbeatMonitor(connection conn: NWConnection, epoch: UInt64) {
        heartbeatTimer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: networkQueue)
        timer.schedule(
            deadline: .now() + .seconds(1),
            repeating: .seconds(1),
            leeway: .milliseconds(100)
        )
        timer.setEventHandler { [weak self, weak conn] in
            guard let self, let conn,
                  self.connection === conn,
                  self.sessionEpochGate.accepts(epoch) else { return }
            let nowNs = DispatchTime.now().uptimeNanoseconds
            guard self.recoveryController.heartbeatTimedOut(nowNs: nowNs) else { return }
            self.recordTelemetry(
                "heartbeat_timed_out",
                epoch: epoch,
                attributes: ["timeout_ns": .unsigned(5_000_000_000)]
            )
            self.heartbeatTimer?.cancel()
            self.heartbeatTimer = nil
            conn.cancel()
        }
        heartbeatTimer = timer
        timer.resume()
    }

    private func runAuthHandshake(connection conn: NWConnection, expectedToken: Data) {
        pendingWirelessConnections[ObjectIdentifier(conn)] = conn
        let timeout = DispatchWorkItem { [weak self, weak conn] in
            guard let self, let conn else { return }
            guard self.pendingHandshakeTimeouts.removeValue(
                forKey: ObjectIdentifier(conn)
            ) != nil else { return }
            self.pendingWirelessConnections.removeValue(
                forKey: ObjectIdentifier(conn)
            )
            debugLog("Wireless authentication timed out")
            conn.cancel()
        }
        pendingHandshakeTimeouts[ObjectIdentifier(conn)] = timeout
        networkQueue.asyncAfter(deadline: .now() + .seconds(3), execute: timeout)

        // Read fixed prefix [magic 4][token 32][name_len 1] = 37 bytes.
        receiveExactly(
            HandshakeCodec.fixedPrefixLen,
            from: conn
        ) { [weak self] prefixData, error in
            guard let self = self else { return }
            guard self.pendingWirelessConnections[
                ObjectIdentifier(conn)
            ] === conn else { return }
            if let error = error {
                debugLog("Auth read error: \(error)")
                conn.cancel()
                return
            }
            guard let prefix = prefixData, prefix.count == HandshakeCodec.fixedPrefixLen else {
                self.sendAuthResponse(conn, status: .invalidMagic, thenClose: true)
                return
            }
            let prefixBytes = Array(prefix)
            guard Array(prefixBytes[0..<4]) == HandshakeCodec.requestMagic else {
                self.sendAuthResponse(conn, status: .invalidMagic, thenClose: true)
                return
            }
            let nameLen = Int(prefixBytes[36])
            guard (1...64).contains(nameLen) else {
                self.sendAuthResponse(conn, status: .invalidName, thenClose: true)
                return
            }
            // Read variable name.
            self.receiveExactly(nameLen, from: conn) { nameData, error in
                guard self.pendingWirelessConnections[
                    ObjectIdentifier(conn)
                ] === conn else { return }
                if let error = error {
                    debugLog("Auth name read error: \(error)")
                    conn.cancel()
                    return
                }
                guard let nameData = nameData, nameData.count == nameLen else {
                    self.sendAuthResponse(conn, status: .invalidName, thenClose: true)
                    return
                }
                let full = prefix + nameData
                do {
                    let parsed = try HandshakeCodec.parseRequest(full)
                    if WirelessAuth.validate(parsed.token, expected: expectedToken) {
                        debugLog("Wireless auth accepted")
                        self.sendAuthResponse(conn, status: .ok, thenClose: false)
                        self.admitConnection(
                            conn,
                            isWireless: true,
                            deviceName: parsed.deviceName
                        )
                    } else {
                        debugLog("Wireless auth rejected: token mismatch")
                        self.sendAuthResponse(conn, status: .invalidToken, thenClose: true)
                    }
                } catch HandshakeError.invalidMagic {
                    self.sendAuthResponse(conn, status: .invalidMagic, thenClose: true)
                } catch HandshakeError.invalidName {
                    self.sendAuthResponse(conn, status: .invalidName, thenClose: true)
                } catch {
                    self.sendAuthResponse(conn, status: .invalidMagic, thenClose: true)
                }
            }
        }
    }

    private func receiveExactly(
        _ count: Int,
        from conn: NWConnection,
        accumulated: Data = Data(),
        completion: @escaping (Data?, Error?) -> Void
    ) {
        guard accumulated.count < count else {
            completion(accumulated, nil)
            return
        }
        conn.receive(
            minimumIncompleteLength: 1,
            maximumLength: count - accumulated.count
        ) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let error {
                completion(nil, error)
                return
            }
            var next = accumulated
            if let data {
                next.append(data)
            }
            guard next.count < count else {
                completion(next, nil)
                return
            }
            guard !isComplete, data?.isEmpty == false else {
                completion(nil, NWError.posix(.ECONNRESET))
                return
            }
            self.receiveExactly(
                count,
                from: conn,
                accumulated: next,
                completion: completion
            )
        }
    }

    private func cancelHandshakeTimeout(for conn: NWConnection) {
        pendingHandshakeTimeouts.removeValue(
            forKey: ObjectIdentifier(conn)
        )?.cancel()
        pendingWirelessConnections.removeValue(forKey: ObjectIdentifier(conn))
    }

    private func sendAuthResponse(_ conn: NWConnection, status: HandshakeStatus, thenClose: Bool) {
        let bytes = HandshakeCodec.encodeResponse(status: status)
        conn.send(content: bytes, completion: .contentProcessed { _ in
            if thenClose {
                debugLog("Auth rejected (\(status)), closing connection")
                conn.cancel()
            }
        })
    }

    func setDisplaySize(width: Int, height: Int, rotation: Int = 0) {
        performOnNetworkQueue {
            self.displayWidth = width
            self.displayHeight = height
            self.rotation = rotation
            self.protocolV1Session?.updateDisplayGeometry(
                width: width,
                height: height,
                rotation: rotation
            )
        }
    }

    func setProtocolV1VideoConfiguration(
        framesPerSecond: Int,
        bitrateKbps: Int,
        displayID: String,
        displayName: String,
        isVirtual: Bool
    ) {
        performOnNetworkQueue {
            self.protocolV1FramesPerSecond = UInt32(clamping: framesPerSecond)
            self.protocolV1BitrateKbps = UInt32(clamping: bitrateKbps)
            self.protocolV1DisplayID = displayID
            self.protocolV1DisplayName = displayName
            self.protocolV1DisplayIsVirtual = isVirtual
        }
    }

    /// Supply the full display catalog advertised by ListDisplays. Passing an
    /// empty list keeps the single-display behavior (session synthesizes one).
    func setProtocolV1Displays(_ displays: [ProtocolV1DisplayInfo]) {
        performOnNetworkQueue {
            self.protocolV1Displays = displays
        }
    }

    /// Re-run the StartDisplay negotiation against a client-selected display
    /// once the host has switched its capture source. Called on the main actor
    /// via the network queue; safe no-op when the session is not streaming.
    func selectProtocolV1Display(_ displayID: String) {
        networkQueue.async { [weak self] in
            guard let self, !self.isStopped,
                  self.connectionProtocolMode == .protocolV1,
                  let session = self.protocolV1Session,
                  let conn = self.connection else { return }
            let generation = self.activeConnectionGeneration
            let actions = session.selectDisplayFromClient(displayID: displayID)
            guard !actions.isEmpty else { return }
            self.applyProtocolV1Actions(actions, connection: conn, generation: generation)
        }
    }

    /// Confirm a client video-preferences request after the host encoder and
    /// live capture have adopted the settings. Runs on the network queue and
    /// drives the deferred bumped-epoch VideoConfig renegotiation; a superseded
    /// token or a non-streaming session is a safe no-op that keeps the prior
    /// advertised configuration.
    func completeProtocolV1VideoPreferences(
        token: UInt64,
        accepted: Bool,
        appliedBitrateKbps: UInt32,
        appliedFramesPerSecond: UInt32
    ) {
        networkQueue.async { [weak self] in
            guard let self, !self.isStopped,
                  self.connectionProtocolMode == .protocolV1,
                  let session = self.protocolV1Session,
                  let conn = self.connection else { return }
            let generation = self.activeConnectionGeneration
            let actions = session.completeVideoPreferences(
                token: token,
                accepted: accepted,
                appliedBitrateKbps: appliedBitrateKbps,
                appliedFramesPerSecond: appliedFramesPerSecond
            )
            guard !actions.isEmpty else { return }
            self.applyProtocolV1Actions(actions, connection: conn, generation: generation)
        }
    }

    private func performOnNetworkQueue(_ operation: @escaping () -> Void) {
        if DispatchQueue.getSpecific(key: Self.networkQueueKey) == ObjectIdentifier(self) {
            operation()
        } else {
            networkQueue.sync(execute: operation)
        }
    }

    /// Update rotation and send to connected client
    func updateRotation(_ rotation: Int) {
        networkQueue.async { [weak self] in
            guard let self, !self.isStopped else { return }
            self.rotation = rotation
            self.protocolV1Session?.updateDisplayGeometry(
                width: self.displayWidth,
                height: self.displayHeight,
                rotation: rotation
            )
            guard self.connectionProtocolMode == .protocolV1,
                  let session = self.protocolV1Session,
                  let conn = self.connection else {
                self.sendDisplaySize()
                return
            }
            let generation = self.activeConnectionGeneration
            let actions = session.makeDisplayChanged()
            self.applyProtocolV1Actions(actions, connection: conn, generation: generation)
        }
    }

    /// Evidence-only queue barrier used by the production transport self-test
    /// to force control-operation interleavings deterministically.
    func suspendNetworkQueueForSelfTest(
        entered: DispatchSemaphore,
        resume: DispatchSemaphore
    ) {
        networkQueue.async {
            entered.signal()
            _ = resume.wait(timeout: .now() + .seconds(2))
        }
    }

    func sendDisplaySize() {
        guard connectionProtocolMode == .legacy,
              let connection = connection else { return }

        var data = Data()
        data.append(WireMessage.displayConfig) // Type: Display size + rotation
        data.append(contentsOf: withUnsafeBytes(of: Int32(displayWidth).bigEndian) { Data($0) })
        data.append(contentsOf: withUnsafeBytes(of: Int32(displayHeight).bigEndian) { Data($0) })
        data.append(contentsOf: withUnsafeBytes(of: Int32(rotation).bigEndian) { Data($0) })

        connection.send(content: data, completion: .contentProcessed { _ in })
        debugLog("Sent display config: \(displayWidth)x\(displayHeight) @ \(rotation)°")
    }

    private func startReceivingTouch(on conn: NWConnection, generation: UInt64) {
        isReceiving = true
        debugLog("Starting input receive loop... (touch=\(touchEnabled ? "on" : "off"))")

        receiveQueue.async { [weak self] in
            self?.touchReceiveLoop(on: conn, generation: generation)
        }
    }

    private func touchReceiveLoop(on conn: NWConnection, generation: UInt64) {
        guard connection === conn,
              activeConnectionGeneration == generation,
              isReceiving,
              !isStopped else { return }

        conn.receive(minimumIncompleteLength: 1, maximumLength: 256) { [weak self] data, _, isComplete, error in
            guard let self,
                  self.connection === conn,
                  self.activeConnectionGeneration == generation,
                  self.isReceiving,
                  !self.isStopped else { return }

            if error != nil || isComplete {
                self.isReceiving = false
                self.inputBuffer.removeAll(keepingCapacity: true)
                self.connectionEnded(conn)
                return
            }

            if let data = data, !data.isEmpty {
                self.inputBuffer.append(data)
                self.processInputBuffer(
                    connection: conn,
                    generation: generation
                )
            }

            self.receiveQueue.async {
                self.touchReceiveLoop(on: conn, generation: generation)
            }
        }
    }

    private func processInputBuffer(
        connection: NWConnection,
        generation: UInt64
    ) {
        if connectionProtocolMode == .protocolV1 {
            processProtocolV1Input(connection: connection, generation: generation)
            return
        }
        while let msgType = inputBuffer.first {
            switch msgType {
            case WireMessage.touchEvent:
                // Touch event: 1 type + 1 pointerCount + N*(4x+4y) + 4 action.
                // 1 finger: 14 bytes, 2 fingers: 22 bytes.
                guard inputBuffer.count >= 2 else { return }

                let pointerCount = Int(inputByte(at: 1))
                guard pointerCount == 1 || pointerCount == 2 else {
                    debugLog("Invalid touch pointer count: \(pointerCount)")
                    inputBuffer.removeAll(keepingCapacity: true)
                    connection.cancel()
                    return
                }

                let expectedSize = 2 + pointerCount * 8 + 4
                guard inputBuffer.count >= expectedSize else { return }

                let message = Data(inputBuffer.prefix(expectedSize))
                consumeInputBytes(expectedSize)

                // Drop early if host has touch disabled, after consuming exactly
                // this touch frame so coalesced ping/keyframe messages survive.
                if touchEnabled {
                    handleTouchMessage(
                        message,
                        pointerCount: pointerCount,
                        connection: connection,
                        generation: generation
                    )
                }

            case WireMessage.ping:
                // Ping from client: echo back as pong (type=5) with client's timestamp.
                guard inputBuffer.count >= 9 else { return }

                let clientTimestamp = Data(inputBuffer.dropFirst().prefix(8))
                consumeInputBytes(9)

                var pong = Data(capacity: 9)
                pong.append(WireMessage.pong) // Type: Pong
                pong.append(clientTimestamp)
                let epoch = sessionEpochGate.current
                let nowNs = DispatchTime.now().uptimeNanoseconds
                let accepted = recoveryController.observeHeartbeat(
                    epoch: epoch,
                    nowNs: nowNs
                )
                recordTelemetry(
                    "heartbeat_received",
                    epoch: epoch,
                    attributes: ["accepted": .boolean(accepted)]
                )
                connection.send(content: pong, completion: .contentProcessed { [weak self] error in
                    if let error {
                        self?.recordTelemetry(
                            "control_send_failed",
                            epoch: epoch,
                            attributes: [
                                "message": .string("pong"),
                                "error": .string(error.localizedDescription)
                            ]
                        )
                    }
                })

            case WireMessage.keyframeRequest:
                // Keyframe request from Android decoder. The client sends a
                // two-byte message: type + flags.
                guard inputBuffer.count >= 2 else { return }

                let flags = inputByte(at: 1)
                consumeInputBytes(2)
                onKeyframeRequested?((flags & 1) != 0, generation)

            case WireMessage.clientSupportsFrameMetadata:
                // One-byte opt-in from newer clients. Keeping this payload-free
                // lets older hosts safely ignore it without misaligning input.
                consumeInputBytes(1)
                networkQueue.async { [weak self, weak connection] in
                    guard let self, let connection,
                          self.connection === connection,
                          self.activeConnectionGeneration == generation else { return }
                    if !self.clientSupportsFrameMetadata {
                        self.clientSupportsFrameMetadata = true
                        debugLog("Client supports video frame metadata")
                    }
                    self.finishProtocolStartup(on: connection, generation: generation)
                }

            case WireMessage.clientAvcOnly:
                // Payload-free opt-in (same convention as type 8): the client
                // has no HEVC decoder, stream H.264 instead. Clients send this
                // BEFORE type 8, so it lands before finishProtocolStartup runs.
                consumeInputBytes(1)
                networkQueue.async { [weak self, weak connection] in
                    guard let self, let connection,
                          self.connection === connection,
                          self.activeConnectionGeneration == generation else { return }
                    if !self.clientIsAvcOnly {
                        self.clientIsAvcOnly = true
                        debugLog("Client is AVC-only — will negotiate H.264")
                    }
                }

            case WireMessage.deviceInfoCapability:
                // Payload-free offer from a client that can send type 11.
                // Reply with the same type so the client knows it is safe to
                // send the 66-byte payload. Older hosts never reach this case.
                consumeInputBytes(1)
                let accept = Data([WireMessage.deviceInfoCapability])
                connection.send(content: accept, completion: .contentProcessed { _ in })
                debugLog("Accepted device-info capability; waiting for type 11 payload")

            case WireMessage.protocolV1Offer:
                consumeInputBytes(1)
                beginProtocolV1(on: connection, generation: generation)
                if !inputBuffer.isEmpty {
                    processProtocolV1Input(connection: connection, generation: generation)
                }
                return

            case WireMessage.clientDeviceInfo:
                // 66 bytes: 1 type + 64 null-padded model name + 1 refresh rate.
                guard inputBuffer.count >= 66 else { return }
                let modelData = Data(inputBuffer.dropFirst().prefix(64))
                let model = String(data: modelData.prefix(while: { $0 != 0 }), encoding: .utf8) ?? "Unknown"
                let refreshRate = inputByte(at: 65)
                consumeInputBytes(66)
                debugLog("Received device info: model=\(model), refreshRate=\(refreshRate)Hz")
                onDeviceInfoReceived?(model, refreshRate, generation)

            default:
                debugLog("Unknown client input type: \(msgType)")
                consumeInputBytes(1)
            }
        }
    }

    private func beginProtocolV1(on conn: NWConnection, generation: UInt64) {
        guard connection === conn,
              activeConnectionGeneration == generation,
              connectionProtocolMode == .legacy,
              !connectionReady else { return }
        codecNegotiationGeneration = nil
        connectionProtocolMode = .protocolV1
        protocolV1Framer = ProtocolV1Framer()
        let sessionID: Data = withUnsafeBytes(of: UUID().uuid) { Data($0) }
        protocolV1Session = ProtocolV1SessionCoordinator(configuration: ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpochGate.current,
            displayWidth: displayWidth,
            displayHeight: displayHeight,
            rotation: rotation,
            framesPerSecond: protocolV1FramesPerSecond,
            bitrateKbps: protocolV1BitrateKbps,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: touchEnabled
            ),
            requiredClientCapabilities: touchEnabled ? [.touch] : [],
            supportedCodecs: [.hevc, .h264],
            hostID: "macos-host",
            hostName: Host.current().localizedName ?? "Mac",
            displayID: protocolV1DisplayID,
            displayName: protocolV1DisplayName,
            displayIsVirtual: protocolV1DisplayIsVirtual,
            displays: protocolV1Displays
        ))
        conn.send(content: ProtocolV1Upgrade.acknowledgement, completion: .contentProcessed { [weak self] error in
            if let error {
                self?.recordTelemetry(
                    "control_send_failed",
                    epoch: self?.sessionEpochGate.current,
                    attributes: [
                        "message": .string("protocol_v1_ack"),
                        "error": .string(error.localizedDescription)
                    ]
                )
            }
        })
        debugLog("Protocol v1 selected for connection epoch \(sessionEpochGate.current)")
    }

    private func processProtocolV1Input(connection conn: NWConnection, generation: UInt64) {
        guard connection === conn,
              activeConnectionGeneration == generation,
              connectionProtocolMode == .protocolV1,
              !isStopped,
              let session = protocolV1Session else { return }
        let bytes = inputBuffer
        inputBuffer.removeAll(keepingCapacity: true)
        do {
            for frame in try protocolV1Framer.append(bytes) {
                let actions: [ProtocolV1SessionAction]
                switch frame.channel {
                case .control:
                    actions = session.handleControl(frame.payload)
                case .video:
                    actions = session.rejectMalformedTransport(
                        "Client-to-host video frames are not valid in this session."
                    )
                }
                applyProtocolV1Actions(actions, connection: conn, generation: generation)
            }
        } catch {
            applyProtocolV1Actions(
                session.rejectMalformedTransport("Invalid Protocol v1 transport frame: \(error)"),
                connection: conn,
                generation: generation
            )
        }
    }

    private func applyProtocolV1Actions(
        _ actions: [ProtocolV1SessionAction],
        connection conn: NWConnection,
        generation: UInt64
    ) {
        dispatchPrecondition(condition: .onQueue(networkQueue))
        guard connection === conn,
              activeConnectionGeneration == generation,
              connectionProtocolMode == .protocolV1,
              !isStopped else { return }
        if let codec = actions.compactMap({ action -> StreamCodec? in
            if case .codecNegotiated(let codec) = action { return codec }
            return nil
        }).first {
            let remainingActions = actions.filter { action in
                if case .codecNegotiated = action { return false }
                return true
            }
            prepareProtocolV1Codec(
                codec,
                actionsAfterNegotiation: remainingActions,
                connection: conn,
                generation: generation
            )
            return
        }
        let controlPayloads = actions.compactMap { action -> Data? in
            if case .sendControl(let payload) = action { return payload }
            return nil
        }
        let shouldClose = actions.contains { action in
            if case .close = action { return true }
            return false
        }

        for (index, payload) in controlPayloads.enumerated() {
            do {
                let bytes = try ProtocolV1TransportFrame(channel: .control, payload: payload).encoded()
                let closesAfterSend = shouldClose && index == controlPayloads.count - 1
                conn.send(content: bytes, completion: .contentProcessed { error in
                    if closesAfterSend || error != nil { conn.cancel() }
                })
            } catch {
                debugLog("Unable to encode Protocol v1 control frame: \(error)")
                conn.cancel()
                return
            }
        }

        for action in actions {
            switch action {
            case .sendControl, .close:
                break
            case .codecNegotiated:
                assertionFailure("Protocol v1 codec negotiation must be handled before dispatch")
            case .connectionReady:
                connectionReady = true
                recoveryController.didConnect(
                    epoch: sessionEpochGate.current,
                    nowNs: DispatchTime.now().uptimeNanoseconds
                )
                startHeartbeatMonitor(connection: conn, epoch: sessionEpochGate.current)
                onClientConnected?(generation)
            case .touch(let pointerID, let x, let y, let phase):
                guard touchEnabled,
                      let touch = protocolV1TouchAggregator.handle(
                        pointerID: pointerID,
                        x: x,
                        y: y,
                        phase: phase
                      ) else { break }
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onTouchEvent?(
                        touch.x1,
                        touch.y1,
                        touch.action,
                        touch.pointerCount,
                        touch.x2,
                        touch.y2,
                        generation
                    )
                }
            case .pointer(let x, let y, let phase, let buttonMask):
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onPointerEvent?(x, y, phase, buttonMask, generation)
                }
            case .scroll(let deltaX, let deltaY):
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onScrollEvent?(deltaX, deltaY, generation)
                }
            case .key(let usage, let pressed, let modifiers, let text):
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onKeyEvent?(usage, pressed, modifiers, text, generation)
                }
            case .heartbeat:
                let accepted = recoveryController.observeHeartbeat(
                    epoch: sessionEpochGate.current,
                    nowNs: DispatchTime.now().uptimeNanoseconds
                )
                recordTelemetry(
                    "heartbeat_received",
                    epoch: sessionEpochGate.current,
                    attributes: ["accepted": .boolean(accepted)]
                )
            case .requestKeyframe(let force):
                onKeyframeRequested?(force, generation)
            case .selectDisplay(let displayID):
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onDisplaySelectionRequested?(displayID)
                }
            case .applyVideoPreferences(
                let token,
                let bitrateKbps,
                let framesPerSecond,
                let qualityPreset,
                let resetQualityToAuto
            ):
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onVideoPreferencesRequested?(
                        token,
                        bitrateKbps,
                        framesPerSecond,
                        qualityPreset,
                        resetQualityToAuto
                    )
                }
            case .peerError(let error):
                onProtocolErrorReceived?(error, generation)
            }
        }
        if shouldClose && controlPayloads.isEmpty { conn.cancel() }
    }

    private func prepareProtocolV1Codec(
        _ codec: StreamCodec,
        actionsAfterNegotiation: [ProtocolV1SessionAction],
        connection conn: NWConnection,
        generation: UInt64
    ) {
        codecNegotiationGeneration = generation
        let completion: (NegotiatedDisplayConfiguration?) -> Void = {
            [weak self, weak conn] configuration in
            guard let self, let conn else { return }
            self.networkQueue.async {
                guard self.connection === conn,
                      self.activeConnectionGeneration == generation,
                      self.codecNegotiationGeneration == generation,
                      self.connectionProtocolMode == .protocolV1,
                      !self.isStopped else { return }
                self.codecNegotiationGeneration = nil
                guard let configuration else {
                    conn.cancel()
                    return
                }
                self.setDisplaySize(
                    width: configuration.width,
                    height: configuration.height,
                    rotation: configuration.rotation
                )
                let completionActions = self.protocolV1Session?.completeCodecNegotiation() ?? []
                self.applyProtocolV1Actions(
                    actionsAfterNegotiation + completionActions,
                    connection: conn,
                    generation: generation
                )
            }
        }
        if let onCodecNegotiated {
            onCodecNegotiated(codec, generation, completion)
        } else {
            completion(NegotiatedDisplayConfiguration(
                width: displayWidth,
                height: displayHeight,
                rotation: rotation
            ))
        }
    }

    private func handleTouchMessage(
        _ data: Data,
        pointerCount: Int,
        connection: NWConnection,
        generation: UInt64
    ) {
        let x1 = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 2, as: Float.self) }
        let y1 = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 6, as: Float.self) }

        var x2: Float = 0
        var y2: Float = 0
        if pointerCount >= 2 {
            x2 = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 10, as: Float.self) }
            y2 = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 14, as: Float.self) }
        }

        let actionOffset = 2 + pointerCount * 8
        let action = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: actionOffset, as: Int32.self) }

        guard x1.isFinite, y1.isFinite,
              (0...1).contains(x1), (0...1).contains(y1),
              pointerCount == 1 ||
                (x2.isFinite && y2.isFinite &&
                 (0...1).contains(x2) && (0...1).contains(y2)),
              (0...2).contains(action) else {
            debugLog("Rejected malformed touch input")
            dispatchInputCancellation(generation: generation)
            return
        }

        DispatchQueue.main.async { [weak self] in
            guard let self,
                  self.clientCallbackGeneration.isCurrent(generation) else { return }
            self.onTouchEvent?(
                x1, y1, Int(action), pointerCount, x2, y2, generation
            )
        }
    }

    private func dispatchInputCancellation(generation: UInt64) {
        DispatchQueue.main.async { [weak self] in
            guard let self,
                  self.clientCallbackGeneration.isCurrent(generation) else { return }
            self.onInputCancelled?(generation)
        }
    }

    private func inputByte(at offset: Int) -> UInt8 {
        inputBuffer[inputBuffer.index(inputBuffer.startIndex, offsetBy: offset)]
    }

    private func consumeInputBytes(_ count: Int) {
        let endIndex = inputBuffer.index(inputBuffer.startIndex, offsetBy: count)
        inputBuffer.removeSubrange(inputBuffer.startIndex..<endIndex)
    }

    func sendFrame(
        _ data: Data,
        timestamp: UInt64,
        isKeyframe: Bool = false,
        sessionEpoch: UInt64
    ) {
        guard let connection = connection, !isStopped, connectionReady else { return }
        let clientGeneration = activeConnectionGeneration
        let frameEpoch = sessionEpoch
        guard sessionEpochGate.accepts(frameEpoch) else {
            recordTelemetry(
                "stale_frame_rejected",
                epoch: frameEpoch,
                attributes: ["active_epoch": .unsigned(sessionEpochGate.current)]
            )
            return
        }

        frameQueue.async { [weak self] in
            guard let self = self else { return }
            guard self.connection === connection,
                  !self.isStopped,
                  self.connectionReady,
                  self.sessionEpochGate.accepts(frameEpoch) else { return }

            let frame = PendingFrame(
                data: data,
                timestamp: timestamp,
                isKeyframe: isKeyframe,
                connection: connection,
                generation: self.framePipelineGeneration,
                clientGeneration: clientGeneration,
                sessionEpoch: frameEpoch
            )

            guard self.sendInFlight else {
                let admission = self.pendingFrames.enqueue(frame)
                self.observeQueueResult(
                    admission,
                    epoch: frameEpoch,
                    clientGeneration: clientGeneration
                )
                guard let admitted = self.pendingFrames.dequeue() else { return }
                self.transmit(admitted)
                return
            }

            let result = self.pendingFrames.enqueue(frame)
            self.observeQueueResult(
                result,
                epoch: frameEpoch,
                clientGeneration: clientGeneration
            )
        }
    }

    /// Must be called on frameQueue.
    private func observeQueueResult(
        _ result: LatestFrameEnqueueResult,
        epoch: UInt64,
        clientGeneration: UInt64
    ) {
        guard result.droppedCount > 0 else { return }
        droppedFrames += UInt64(result.droppedCount)
        recordTelemetry(
            "frame_queue_drop",
            epoch: epoch,
            attributes: [
                "dropped": .integer(Int64(result.droppedCount)),
                "depth": .integer(Int64(pendingFrames.count + (sendInFlight ? 1 : 0))),
                "capacity": .integer(2),
                "keyframe_required": .boolean(result.requiresKeyframe)
            ]
        )
        if result.requiresKeyframe {
            onKeyframeRequested?(true, clientGeneration)
        }
    }

    /// Must be called on frameQueue.
    private func transmit(_ frame: PendingFrame) {
        guard connection === frame.connection,
              frame.generation == framePipelineGeneration,
              sessionEpochGate.accepts(frame.sessionEpoch),
              !isStopped,
              connectionReady else { return }

        sendInFlight = true
        let packet: Data
        do {
            packet = try makeFramePacket(
                frame.data,
                timestamp: frame.timestamp,
                isKeyframe: frame.isKeyframe
            )
        } catch StreamingServerError.protocolNotReady {
            // The Protocol v1 session is mid re-negotiation (awaitingVideoConfig
            // after a runtime display switch). The session gate correctly
            // withholds media until the client accepts the new VideoConfig.
            // Silently hold this encoder frame back instead of tearing down the
            // connection: dropping the whole stream here is exactly the flap
            // that surfaced client-side as "Media received before VideoConfig
            // acceptance". A keyframe is requested so the first post-switch
            // streaming frame is decodable, and the pipeline stays alive.
            sendInFlight = false
            _ = pendingFrames.reset(requiresKeyframe: true)
            onKeyframeRequested?(false, frame.clientGeneration)
            return
        } catch {
            sendInFlight = false
            let dependentDrops = pendingFrames.reset(requiresKeyframe: true)
            droppedFrames += UInt64(dependentDrops + 1)
            recordTelemetry(
                "frame_encode_failed",
                epoch: frame.sessionEpoch,
                attributes: ["error": .string(error.localizedDescription)]
            )
            onKeyframeRequested?(true, frame.clientGeneration)
            frame.connection.cancel()
            return
        }

        frame.connection.send(content: packet, completion: .contentProcessed { [weak self] error in
            guard let self else { return }
            self.frameQueue.async {
                guard frame.generation == self.framePipelineGeneration,
                      self.connection === frame.connection else { return }

                self.sendInFlight = false
                if let error {
                    let dependentDrops = self.pendingFrames.reset(
                        requiresKeyframe: true
                    )
                    self.droppedFrames += UInt64(dependentDrops + 1)
                    self.recordTelemetry(
                        "frame_send_failed",
                        epoch: frame.sessionEpoch,
                        attributes: [
                            "error": .string(error.localizedDescription),
                            "dropped": .integer(Int64(dependentDrops + 1)),
                            "keyframe_required": .boolean(true)
                        ]
                    )
                    self.onKeyframeRequested?(true, frame.clientGeneration)
                    return
                }

                let sendAge = DispatchTime.now().uptimeNanoseconds - frame.timestamp
                self.updateStats(
                    bytes: frame.data.count,
                    frameAgeNs: sendAge,
                    clientGeneration: frame.clientGeneration
                )
                if let next = self.pendingFrames.dequeue() {
                    self.transmit(next)
                }
            }
        })
    }

    private func makeFramePacket(_ data: Data, timestamp: UInt64, isKeyframe: Bool) throws -> Data {
        if connectionProtocolMode == .protocolV1, let protocolV1Session {
            guard let mediaPayload = try protocolV1Session.makeMediaFrame(
                payload: data,
                timestamp: timestamp,
                keyframe: isKeyframe
            ) else {
                throw StreamingServerError.protocolNotReady
            }
            return try ProtocolV1TransportFrame(channel: .video, payload: mediaPayload).encoded()
        }
        if clientSupportsFrameMetadata {
            var packet = Data(capacity: data.count + 14)
            packet.append(WireMessage.videoFrameWithMetadata)
            appendFrameSize(data.count, to: &packet)
            packet.append(isKeyframe ? 1 : 0)
            var captureTimestamp = timestamp.bigEndian
            withUnsafeBytes(of: &captureTimestamp) { packet.append(contentsOf: $0) }
            packet.append(data)
            return packet
        }

        // Keep legacy frame type 0 for clients that do not advertise
        // metadata support; remove after legacy clients age out.
        var packet = Data(capacity: data.count + 5)
        packet.append(WireMessage.legacyVideoFrame)
        appendFrameSize(data.count, to: &packet)
        packet.append(data)
        return packet
    }

    private func appendFrameSize(_ size: Int, to packet: inout Data) {
        var frameSize = Int32(size).bigEndian
        withUnsafeBytes(of: &frameSize) { packet.append(contentsOf: $0) }
    }

    // Pipeline profiling: track frame age at send time
    private var totalFrameAgeNs: UInt64 = 0
    private var profiledFrameCount: UInt64 = 0

    func performIfCurrentClientGeneration(
        _ generation: UInt64,
        operation: () -> Void
    ) -> Bool {
        clientCallbackGeneration.performIfCurrent(
            generation,
            operation: operation
        )
    }

    private func updateStats(
        bytes: Int,
        frameAgeNs: UInt64 = 0,
        clientGeneration: UInt64
    ) {
        bytesSent += UInt64(bytes)
        frameCount += 1
        if frameAgeNs > 0 {
            totalFrameAgeNs += frameAgeNs
            profiledFrameCount += 1
        }

        let now = DispatchTime.now()
        let elapsed = Double(now.uptimeNanoseconds - lastStatsTime.uptimeNanoseconds) / 1_000_000_000

        if elapsed >= 1.0 {
            let mbps = Double(bytesSent * 8) / elapsed / 1_000_000
            let fps = Double(frameCount) / elapsed
            onStats?(fps, mbps, clientGeneration)

            // Log pipeline latency profile
            if profiledFrameCount > 0 {
                let avgAgeMs = Double(totalFrameAgeNs) / Double(profiledFrameCount) / 1_000_000.0
                debugLog("Pipeline: \(String(format: "%.1f", fps))fps, \(String(format: "%.1f", mbps))Mbps, avg frame age: \(String(format: "%.1f", avgAgeMs))ms, dropped: \(droppedFrames)")
                recordTelemetry(
                    "stream_stats",
                    epoch: sessionEpochGate.current,
                    attributes: [
                        "fps": .double(fps),
                        "mbps": .double(mbps),
                        "average_frame_age_ms": .double(avgAgeMs),
                        "dropped_frames": .unsigned(droppedFrames),
                        "queue_capacity": .integer(2)
                    ]
                )
            }

            bytesSent = 0
            frameCount = 0
            droppedFrames = 0
            totalFrameAgeNs = 0
            profiledFrameCount = 0
            lastStatsTime = now
        }
    }

    private func recordTelemetry(
        _ event: String,
        epoch: UInt64?,
        attributes: [String: TelemetryValue] = [:]
    ) {
        guard let telemetry else { return }
        do {
            try telemetry.record(
                TelemetryEvent(
                    event: event,
                    sessionEpoch: epoch,
                    attributes: attributes
                )
            )
        } catch {
            debugLog("Telemetry write failed for \(event): \(error)")
        }
    }

    /// Installs a new bearer token and immediately revokes every in-flight or
    /// authenticated wireless session that could have observed the old token.
    func rotateAuthToken(_ token: Data) {
        precondition(token.count == 32)
        networkQueue.async { [weak self] in
            guard let self else { return }
            self.expectedAuthToken = token
            for (_, timeout) in self.pendingHandshakeTimeouts {
                timeout.cancel()
            }
            self.pendingHandshakeTimeouts.removeAll()
            for (_, pendingConnection) in self.pendingWirelessConnections {
                pendingConnection.cancel()
            }
            self.pendingWirelessConnections.removeAll()
            if self.activeConnectionIsWireless {
                self.connection?.cancel()
            }
        }
    }

    func stop() {
        if DispatchQueue.getSpecific(key: Self.networkQueueKey) == ObjectIdentifier(self) {
            beginStopOnNetworkQueue(completion: nil)
            return
        }
        let completed = DispatchSemaphore(value: 0)
        networkQueue.async { [weak self] in
            guard let self else {
                completed.signal()
                return
            }
            self.beginStopOnNetworkQueue { completed.signal() }
        }
        _ = completed.wait(timeout: .now() + .milliseconds(700))
    }

    private func beginStopOnNetworkQueue(completion: (() -> Void)?) {
        dispatchPrecondition(condition: .onQueue(networkQueue))
        guard stopInProgress == nil else {
            completion?()
            return
        }
        isStopped = true
        isReceiving = false
        stopSequence &+= 1
        let token = stopSequence
        stopInProgress = token
        let conn = connection
        let generation = activeConnectionGeneration
        let shutdownMsg: Data?
        if let conn,
           connection === conn,
           connectionProtocolMode == .protocolV1,
           let session = protocolV1Session {
            do {
                shutdownMsg = try ProtocolV1TransportFrame(
                    channel: .control,
                    payload: session.makeDisconnectNotice()
                ).encoded()
            } catch {
                shutdownMsg = nil
                debugLog("Unable to encode Protocol v1 shutdown notice: \(error)")
            }
        } else if conn != nil && connectionReady {
            shutdownMsg = Data([WireMessage.serverShutdown])
        } else {
            shutdownMsg = nil
        }

        guard let conn, let shutdownMsg else {
            finishStopOnNetworkQueue(token: token, connection: conn, generation: generation, completion: completion)
            return
        }
        conn.send(content: shutdownMsg, completion: .contentProcessed { [weak self, weak conn] _ in
            guard let self else { return }
            self.networkQueue.asyncAfter(deadline: .now() + .milliseconds(50)) {
                self.finishStopOnNetworkQueue(
                    token: token,
                    connection: conn,
                    generation: generation,
                    completion: completion
                )
            }
        })
        networkQueue.asyncAfter(deadline: .now() + .milliseconds(500)) { [weak self, weak conn] in
            self?.finishStopOnNetworkQueue(
                token: token,
                connection: conn,
                generation: generation,
                completion: completion
            )
        }
    }

    private func finishStopOnNetworkQueue(
        token: UInt64,
        connection stoppedConnection: NWConnection?,
        generation: UInt64,
        completion: (() -> Void)?
    ) {
        dispatchPrecondition(condition: .onQueue(networkQueue))
        guard stopInProgress == token else { return }
        stopInProgress = nil
        connectionProtocolMode = .legacy
        protocolV1Framer = ProtocolV1Framer()
        protocolV1Session = nil
        protocolV1TouchAggregator.reset()
        if activeConnectionGeneration == generation {
            activeConnectionGeneration &+= 1
        }
        codecNegotiationGeneration = nil
        clientCallbackGeneration.advance(to: activeConnectionGeneration)
        for (_, timeout) in pendingHandshakeTimeouts {
            timeout.cancel()
        }
        pendingHandshakeTimeouts.removeAll()
        for (_, pendingConnection) in pendingWirelessConnections {
            pendingConnection.cancel()
        }
        pendingWirelessConnections.removeAll()
        heartbeatTimer?.cancel()
        heartbeatTimer = nil

        // Invalidate completions from the old connection and discard its newest
        // unsent frame before cancelling.
        frameQueue.sync {
            framePipelineGeneration &+= 1
            sendInFlight = false
            _ = pendingFrames.reset(requiresKeyframe: true)
        }
        recoveryController.stop()
        receiveQueue.sync {}

        stoppedConnection?.cancel()
        listener?.cancel()
        if connection === stoppedConnection {
            connection = nil
        }
        listener = nil
        connectionReady = false
        activeConnectionIsWireless = false
        completion?()
    }
}
