import CryptoKit
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

    @discardableResult
    func invalidateIfCurrent(_ generation: UInt64) -> Bool {
        lock.withLock {
            guard currentGeneration == generation else { return false }
            currentGeneration &+= 1
            return true
        }
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

final class LatestFrameMailbox<Element> {
    struct Drain {
        let element: Element?
        let droppedCount: Int
        let requiresKeyframe: Bool
    }

    private struct State {
        var generation: UInt64 = 0
        var sessionEpoch: UInt64 = 0
        var accepting = false
        var drainScheduled = false
        var pending: Element?
        var droppedCount = 0
        var requiresKeyframe = true
    }

    private let lock = NSLock()
    private let isKeyframe: (Element) -> Bool
    private var state = State()

    init(isKeyframe: @escaping (Element) -> Bool) {
        self.isKeyframe = isKeyframe
    }

    func reset(generation: UInt64, sessionEpoch: UInt64, accepting: Bool) {
        lock.withLock {
            state = State(
                generation: generation,
                sessionEpoch: sessionEpoch,
                accepting: accepting
            )
        }
    }

    /// Returns true only when the caller must schedule a drain operation.
    func submit(
        _ element: Element,
        generation: UInt64,
        sessionEpoch: UInt64
    ) -> Bool {
        lock.withLock {
            guard state.accepting,
                  state.generation == generation,
                  state.sessionEpoch == sessionEpoch else { return false }

            let incomingIsKeyframe = isKeyframe(element)
            if state.requiresKeyframe && !incomingIsKeyframe {
                state.droppedCount += 1
            } else if incomingIsKeyframe {
                if state.pending != nil {
                    state.droppedCount += 1
                }
                state.pending = element
                state.requiresKeyframe = false
            } else if let pending = state.pending {
                if isKeyframe(pending) {
                    state.droppedCount += 1
                } else {
                    state.pending = nil
                    state.droppedCount += 2
                    state.requiresKeyframe = true
                }
            } else {
                state.pending = element
            }
            guard !state.drainScheduled else { return false }
            state.drainScheduled = true
            return true
        }
    }

    func take(generation: UInt64, sessionEpoch: UInt64) -> Drain? {
        lock.withLock {
            guard state.generation == generation,
                  state.sessionEpoch == sessionEpoch else { return nil }
            let drain = Drain(
                element: state.pending,
                droppedCount: state.droppedCount,
                requiresKeyframe: state.requiresKeyframe
            )
            state.pending = nil
            state.droppedCount = 0
            return drain
        }
    }

    /// Reconciles a frame removed by take but rejected before enqueueing.
    /// A newer keyframe can restart the chain; dependent pending frames cannot.
    func discardTaken(
        generation: UInt64,
        sessionEpoch: UInt64
    ) -> LatestFrameEnqueueResult? {
        lock.withLock {
            guard state.accepting,
                  state.generation == generation,
                  state.sessionEpoch == sessionEpoch else { return nil }

            var droppedCount = 1
            if let pending = state.pending, isKeyframe(pending) {
                state.requiresKeyframe = false
            } else {
                if state.pending != nil {
                    state.pending = nil
                    droppedCount += 1
                }
                state.requiresKeyframe = true
            }

            return LatestFrameEnqueueResult(
                accepted: false,
                droppedCount: droppedCount,
                requiresKeyframe: state.requiresKeyframe
            )
        }
    }

    /// Returns true when another frame arrived during the preceding drain.
    func finishDrain(generation: UInt64, sessionEpoch: UInt64) -> Bool {
        lock.withLock {
            guard state.generation == generation,
                  state.sessionEpoch == sessionEpoch else { return false }
            guard state.pending == nil, state.droppedCount == 0 else { return true }
            state.drainScheduled = false
            return false
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
    private static let wirelessAuthTimeoutSeconds = 3
    private static let wirelessSecureRecordTimeoutSeconds = 5

    private static func fileTransferStagingDirectory(sessionID: Data) -> URL {
        let digest = sessionID.map { String(format: "%02x", $0) }.joined()
        return FileManager.default.temporaryDirectory
            .appendingPathComponent("vibescreen-file-transfer", isDirectory: true)
            .appendingPathComponent(digest, isDirectory: true)
    }

    private static func rejectedFileAccept(transferID: Data, reasonCode: String) -> VSFileAccept {
        var response = VSFileAccept()
        response.transferID = transferID
        response.accepted = false
        response.rejectionReason = reasonCode
        return response
    }

    static func requestFileTransferApproval(
        offer: VSFileOffer,
        approval: ((VSFileOffer) -> Bool)?,
        completion: @escaping (Bool) -> Void
    ) {
        guard let approval else {
            completion(false)
            return
        }
        DispatchQueue.main.async {
            completion(approval(offer))
        }
    }

    private enum ConnectionProtocolMode: Equatable {
        case legacy
        case protocolV1
    }

    private let port: UInt16
    private let mode: StreamingServerMode
    private let protocolUpgradeGraceMillisecondsOverride: Int?
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
    /// Supplies the live VideoToolbox in-flight frame count and its fixed
    /// capacity for the `stream_stats` telemetry record. The short-window host
    /// memory diagnostic uses these to assert the encoder never exceeds its
    /// admission budget. Optional so tests and non-capture builds can omit it.
    var encoderStatsProvider: (() -> (inFlight: Int, capacity: Int)?)?
    var onKeyframeRequested: ((Bool, UInt64) -> Void)?
    // Whether host wants to receive touch events from client. Ping/pong is
    // handled regardless. When false, incoming touch frames are dropped
    // immediately without parsing or dispatching to main queue.
    var touchEnabled: Bool = true
    /// Enabled only after signature, entitlement, and IOHID runtime checks.
    var controllerAvailable: Bool = false

    var onWirelessClientPaired: ((String, UInt64) -> Void)?
    var onServerFailed: ((Error) -> Void)?
    /// Fired when the Android client reports Build.MODEL + max panel Hz.
    var onDeviceInfoReceived: ((String, UInt8, UInt64) -> Void)?
    var onPointerEvent: ((Float, Float, VSInputPhase, UInt32, UInt64) -> Void)?
    var onStylusEvent: ((
        UInt64, UInt32, Float, Float, VSInputPhase, Double, Double, Double,
        VSStylusToolKind, UInt32, VSStylusContactState, UInt64
    ) -> Void)?
    var onScrollEvent: ((Double, Double, UInt64) -> Void)?
    var onKeyEvent: ((UInt32, Bool, UInt32, String, UInt64) -> Void)?
    var onControllerEvent: GameControllerEventHandler?
    var onProtocolErrorReceived: ((VSProtocolError, UInt64) -> Void)?
    /// Fired on the main actor when a Protocol v1 client selects a different
    /// display so capture switching preserves the network queue's request order.
    var onDisplaySelectionRequested: (@MainActor (String) -> Void)?

    /// Fired on the main actor when a Protocol v1 client requests new video
    /// preferences. The session defers the bumped-epoch
    /// VideoConfig renegotiation until the host confirms the encoder actually
    /// adopted the settings by calling completeProtocolV1VideoPreferences with
    /// the same token, so a client can never accept a new VideoConfig while the
    /// encoder still runs the previous configuration.
    var onVideoPreferencesRequested:
        (@MainActor (_ token: UInt64,
          _ bitrateKbps: UInt32,
          _ framesPerSecond: UInt32,
          _ qualityPreset: VSVideoQualityPreset,
          _ resetQualityToAuto: Bool) -> Void)?

    /// Fired on the main actor when a negotiated Protocol v1 client invokes a
    /// host action from the advertised catalog. The host runs the
    /// AppKit/Accessibility work and reports the outcome back with
    /// completeProtocolV1HostAction using the same invocation id, which emits
    /// the single HostActionResult on the session FIFO.
    var onHostActionRequested:
        (@MainActor (_ actionID: String, _ invocationID: Data, _ target: VSInputTarget?) -> Void)?

    /// Fired on the main actor when a negotiated client offers clipboard
    /// content. The UI decides whether to request the full content via
    /// requestClipboardContent. The generation is the active connection
    /// generation; the UI should drop the callback if it no longer matches.
    var onClipboardOfferReceived:
        (@MainActor (_ offer: ClipboardOfferMetadata, _ generation: UInt64) -> Void)?

    /// Fired on the main actor when a requested clipboard content arrives and
    /// passes validation. The UI writes the validated text to the pasteboard.
    var onClipboardContentReceived:
        (@MainActor (_ content: ValidatedClipboardContent, _ generation: UInt64) -> Void)?

    /// Fired on the main actor when a client sends clipboard content without a
    /// matching pending offer/request. The UI must obtain explicit user
    /// approval before writing to the pasteboard; the core never writes it.
    var onClipboardDirectContentReceived:
        (@MainActor (_ content: ValidatedClipboardContent, _ generation: UInt64) -> Void)?

    /// File transfers are opt-in at the host boundary. A nil approval callback
    /// rejects every incoming offer before any staging file is created.
    var onFileTransferApprovalRequested: ((VSFileOffer) -> Bool)?
    var onIncomingFileCompleted: ((ProtocolV1CompletedIncomingFile) -> Void)?

    private let frameQueue = DispatchQueue(label: "frameQueue", qos: .userInteractive)
    private let receiveQueue = DispatchQueue(label: "receiveQueue", qos: .userInteractive)
    private let networkQueue = DispatchQueue(label: "networkQueue", qos: .userInteractive)
    private let wakeHostQueue = DispatchQueue(label: "wakeHostQueue", qos: .utility)
    private struct FrameSubmission {
        let data: Data
        let timestamp: UInt64
        let isKeyframe: Bool
        let connection: NWConnection
        let clientGeneration: UInt64
        let sessionEpoch: UInt64
    }
    private struct PendingFrame {
        let data: Data
        let timestamp: UInt64
        let isKeyframe: Bool
        let connection: NWConnection
        let generation: UInt64
        let clientGeneration: UInt64
        let sessionEpoch: UInt64
        let packetChannel: InternetTransportChannel
    }
    private struct PendingAudioPacket {
        let serializedFrame: Data
        let timestamp: UInt64
        let connection: NWConnection
        let generation: UInt64
        let audioGeneration: UInt64
        let sessionEpoch: UInt64
    }
    /// At most one frame is inside Network.framework and one newer frame is
    /// retained. This prevents a transient USB/Wi-Fi slowdown from becoming a
    /// seconds-long FIFO of pictures the viewer no longer wants to see.
    private var sendInFlight = false
    private var pendingFrames: LatestFrameQueue<PendingFrame>
    private var audioSendInFlight = false
    private var audioGeneration: UInt64 = 0
    private var pendingAudioPackets: [PendingAudioPacket] = []
    private let maximumPendingAudioPackets = 2
    private let audioStream: MacHostAudioStream
    private let frameMailbox = LatestFrameMailbox<FrameSubmission>(
        isKeyframe: { $0.isKeyframe }
    )
    private var framePipelineGeneration: UInt64 = 0
    private var bytesSent: UInt64 = 0
    private var frameCount: UInt64 = 0
    private var droppedFrames: UInt64 = 0
    private var firstFrameSentTelemetryEpoch: UInt64?
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
    private var lanRecordProtectionState = LANRecordProtectionState.notApplicable
    private var lanSecureRecordSession: LANSecureRecordSession?
    private var protocolV1Framer = ProtocolV1Framer()
    private var protocolV1Session: ProtocolV1SessionCoordinator?
    private var protocolV1TouchAggregator = ProtocolV1TouchAggregator()
    private var lanSecureRecordFramer = LANSecureRecordStreamFramer()
    private var protocolV1IncomingFiles: ProtocolV1IncomingFileTransferManager?
    private var protocolV1PendingIncomingFileApprovals: Set<Data> = []
    private var protocolV1ApprovedIncomingFileOffers: Set<Data> = []
    private var protocolV1OutgoingFiles: [Data: ProtocolV1OutgoingFileTransfer] = [:]
    private var protocolV1RemoteManagedPolicy: ProtocolV1RemoteManagedPolicy = .unmanaged
    private let protocolV1FileTransferPolicy = ProtocolV1FileTransferPolicy.default
    private var inputBuffer = Data()
    private var expectedAuthToken: Data?
    private var pendingAcceptedConnections: [ObjectIdentifier: NWConnection] = [:]
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
    private let wakeHostAuthorizer: any WakeHostAuthorizing
    private let wakeHostPacketSender: any WakeHostPacketSending
    private var acceptedConnectionObserverForSelfTest: ((NWConnection) -> Void)?

    var currentSessionEpoch: UInt64 { sessionEpochGate.current }

    init(
        port: UInt16,
        mode: StreamingServerMode = .usb,
        telemetry: TelemetryRecording? = nil,
        allowPlaintextWirelessLegacyFallback: Bool = false,
        protocolUpgradeGraceMillisecondsOverride: Int? = nil,
        wakeHostAuthorizer: any WakeHostAuthorizing = DenyWakeHostAuthorizer(),
        wakeHostPacketSender: any WakeHostPacketSending = UDPWakeHostPacketSender(),
        audioStream: MacHostAudioStream = MacHostAudioStream()
    ) {
        self.port = port
        self.mode = mode
        self.allowPlaintextWirelessLegacyFallback = allowPlaintextWirelessLegacyFallback
        self.protocolUpgradeGraceMillisecondsOverride = protocolUpgradeGraceMillisecondsOverride
        self.wakeHostAuthorizer = wakeHostAuthorizer
        self.wakeHostPacketSender = wakeHostPacketSender
        self.audioStream = audioStream
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

    private let allowPlaintextWirelessLegacyFallback: Bool

    var listeningPort: UInt16? {
        if DispatchQueue.getSpecific(key: Self.networkQueueKey) == ObjectIdentifier(self) {
            return listener?.port?.rawValue
        }
        return networkQueue.sync { listener?.port?.rawValue }
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
                if let listeningPort = newListener?.port?.rawValue, listeningPort != 0 {
                    debugLog("TCP server listening on port \(listeningPort)")
                } else {
                    debugLog("TCP server ready without a reported listening port")
                }
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
        pendingAcceptedConnections[ObjectIdentifier(newConnection)] = newConnection
        newConnection.stateUpdateHandler = { [weak self, weak newConnection] state in
            guard let newConnection else { return }
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
        pendingAcceptedConnections.removeValue(forKey: ObjectIdentifier(conn))
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
        deviceName: String?,
        lanRecordSession: LANSecureRecordSession? = nil,
        lanRecordProtectionState: LANRecordProtectionState? = nil,
        initialPlaintext: Data = Data()
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
        acceptedConnectionObserverForSelfTest?(conn)
        activeConnectionIsWireless = isWireless
        self.lanSecureRecordSession?.close()
        self.lanSecureRecordSession = lanRecordSession
        self.lanSecureRecordFramer = LANSecureRecordStreamFramer()
        self.lanRecordProtectionState = lanRecordProtectionState ?? (isWireless ? .negotiating : .notApplicable)
        connectionReady = false
        clientSupportsFrameMetadata = false
        clientIsAvcOnly = false
        codecNegotiationGeneration = nil
        connectionProtocolMode = .legacy
        stopProtocolV1Audio(reason: "connection_admitted")
        protocolV1Framer = ProtocolV1Framer()
        protocolV1Session = nil
        protocolV1TouchAggregator.reset()
        protocolV1IncomingFiles?.cancelAll()
        protocolV1IncomingFiles = nil
        protocolV1PendingIncomingFileApprovals.removeAll()
        protocolV1ApprovedIncomingFileOffers.removeAll()
        protocolV1OutgoingFiles.values.forEach { $0.cancel() }
        protocolV1OutgoingFiles.removeAll()
        protocolV1RemoteManagedPolicy = .unmanaged
        inputBuffer.removeAll(keepingCapacity: true)
        inputBuffer.append(initialPlaintext)
        isReceiving = false
        droppedFrames = 0

        dispatchTakeoverInputCancellation(
            oldConnectionWasPresent: oldConnection != nil && oldConnection !== conn,
            generation: generation
        )

        frameMailbox.reset(
            generation: generation,
            sessionEpoch: sessionEpoch,
            accepting: true
        )

        frameQueue.async { [weak self] in
            guard let self else { return }
            self.framePipelineGeneration &+= 1
            self.sendInFlight = false
            self.firstFrameSentTelemetryEpoch = nil
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
            oldConnection.stateUpdateHandler = nil
            oldConnection.cancel()
        }

        if let deviceName {
            onWirelessClientPaired?(deviceName, generation)
        }
        startReceivingTouch(on: conn, generation: generation)
        if !inputBuffer.isEmpty {
            processInputBuffer(connection: conn, generation: generation)
        }

        // Give new clients a short chance to opt in before the first frame.
        // Legacy clients send no capability message, so we continue shortly
        // after this window with the old frame type.
        let upgradeGraceMilliseconds = protocolUpgradeGraceMillisecondsOverride
            ?? (isWireless
                ? Self.wirelessProtocolUpgradeGraceMilliseconds
                : Self.usbProtocolUpgradeGraceMilliseconds)
        networkQueue.asyncAfter(deadline: .now() + .milliseconds(upgradeGraceMilliseconds)) {
            [weak self, weak conn] in
            guard let self = self, let conn = conn else { return }
            self.requestProtocolStartup(on: conn, generation: generation)
        }
    }

    private func connectionEnded(_ conn: NWConnection) {
        pendingAcceptedConnections.removeValue(forKey: ObjectIdentifier(conn))
        cancelHandshakeTimeout(for: conn)
        pendingWirelessConnections.removeValue(forKey: ObjectIdentifier(conn))
        conn.stateUpdateHandler = nil
        conn.cancel()
        guard connection === conn else { return }
        connection = nil
        connectionReady = false
        isReceiving = false
        activeConnectionIsWireless = false
        lanSecureRecordSession?.close()
        lanSecureRecordSession = nil
        lanSecureRecordFramer = LANSecureRecordStreamFramer()
        lanRecordProtectionState = .notApplicable
        heartbeatTimer?.cancel()
        heartbeatTimer = nil
        activeConnectionGeneration &+= 1
        frameMailbox.reset(
            generation: activeConnectionGeneration,
            sessionEpoch: sessionEpochGate.current,
            accepting: false
        )
        codecNegotiationGeneration = nil
        clientCallbackGeneration.advance(to: activeConnectionGeneration)
        inputBuffer.removeAll(keepingCapacity: true)
        connectionProtocolMode = .legacy
        stopProtocolV1Audio(reason: "connection_ended")
        protocolV1Framer = ProtocolV1Framer()
        protocolV1Session = nil
        protocolV1TouchAggregator.reset()
        protocolV1IncomingFiles?.cancelAll()
        protocolV1IncomingFiles = nil
        protocolV1PendingIncomingFileApprovals.removeAll()
        protocolV1ApprovedIncomingFileOffers.removeAll()
        protocolV1OutgoingFiles.values.forEach { $0.cancel() }
        protocolV1OutgoingFiles.removeAll()
        protocolV1RemoteManagedPolicy = .unmanaged
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
            sendSessionBytes(msg, on: conn, completion: .contentProcessed { [weak self] error in
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
        schedulePendingWirelessTimeout(
            for: conn,
            seconds: Self.wirelessAuthTimeoutSeconds,
            reason: "Wireless authentication timed out"
        )

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
                        self.sendAuthResponse(conn, status: .ok, thenClose: false) {
                            self.schedulePendingWirelessTimeout(
                                for: conn,
                                seconds: Self.wirelessSecureRecordTimeoutSeconds,
                                reason: "Trusted LAN secure-record negotiation timed out"
                            )
                            self.negotiateWirelessRecordProtection(
                                connection: conn,
                                token: parsed.token,
                                deviceName: parsed.deviceName
                            )
                        }
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

    private func schedulePendingWirelessTimeout(
        for conn: NWConnection,
        seconds: Int,
        reason: String
    ) {
        pendingHandshakeTimeouts.removeValue(
            forKey: ObjectIdentifier(conn)
        )?.cancel()
        let timeout = DispatchWorkItem { [weak self, weak conn] in
            guard let self, let conn else { return }
            guard self.pendingHandshakeTimeouts.removeValue(
                forKey: ObjectIdentifier(conn)
            ) != nil else { return }
            self.pendingWirelessConnections.removeValue(
                forKey: ObjectIdentifier(conn)
            )
            debugLog(reason)
            conn.cancel()
        }
        pendingHandshakeTimeouts[ObjectIdentifier(conn)] = timeout
        networkQueue.asyncAfter(deadline: .now() + .seconds(seconds), execute: timeout)
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

    private func sendAuthResponse(
        _ conn: NWConnection,
        status: HandshakeStatus,
        thenClose: Bool,
        completion: (() -> Void)? = nil
    ) {
        let bytes = HandshakeCodec.encodeResponse(status: status)
        conn.send(content: bytes, completion: .contentProcessed { [weak conn] _ in
            if thenClose {
                debugLog("Auth rejected (\(status)), closing connection")
                conn?.cancel()
            } else {
                completion?()
            }
        })
    }

    private func sendSessionBytes(
        _ bytes: Data,
        channel: InternetTransportChannel = .control,
        on conn: NWConnection,
        completion: NWConnection.SendCompletion
    ) {
        do {
            let outbound: Data
            if activeConnectionIsWireless {
                switch lanRecordProtectionState {
                case .encrypted:
                    guard let recordSession = lanSecureRecordSession else {
                        throw LANSecureRecordError.encryptionRequired
                    }
                    outbound = try LANSecureRecordStreamFramer.encode(
                        try recordSession.seal(bytes, channel: channel)
                    )
                case .explicitLegacyFallback:
                    outbound = bytes
                case .notApplicable, .negotiating:
                    throw LANSecureRecordError.encryptionRequired
                }
            } else {
                outbound = bytes
            }
            conn.send(content: outbound, completion: completion)
        } catch {
            recordTelemetry(
                "trusted_lan_record_send_failed",
                epoch: sessionEpochGate.current,
                attributes: ["error": .string(String(describing: error))]
            )
            conn.cancel()
        }
    }

    private func negotiateWirelessRecordProtection(
        connection conn: NWConnection,
        token: Data,
        deviceName: String
    ) {
        if allowPlaintextWirelessLegacyFallback {
            receiveExactly(1, from: conn) { [weak self] firstByte, error in
                self?.finishWirelessRecordProtectionProbe(
                    connection: conn,
                    token: token,
                    deviceName: deviceName,
                    firstByte: firstByte,
                    error: error
                )
            }
            return
        }
        receiveExactly(
            LANSecureRecordNegotiation.requestBytes,
            from: conn
        ) { [weak self] requestData, error in
            self?.finishWirelessRecordProtectionNegotiation(
                connection: conn,
                token: token,
                deviceName: deviceName,
                requestData: requestData,
                error: error
            )
        }
    }

    private func finishWirelessRecordProtectionProbe(
        connection conn: NWConnection,
        token: Data,
        deviceName: String,
        firstByte: Data?,
        error: Error?
    ) {
        guard pendingWirelessConnections[ObjectIdentifier(conn)] === conn else { return }
        if let error {
            debugLog("Trusted LAN protection probe failed: \(error)")
            conn.cancel()
            return
        }
        guard let firstByte, firstByte.count == 1, let byte = firstByte.first else {
            recordTrustedLANProtectionFailure(LANSecureRecordError.invalidHandshake)
            conn.cancel()
            return
        }
        if byte == LANSecureRecordNegotiation.requestMagic.first {
            receiveExactly(
                LANSecureRecordNegotiation.requestBytes,
                from: conn,
                accumulated: firstByte
            ) { [weak self] requestData, error in
                self?.finishWirelessRecordProtectionNegotiation(
                    connection: conn,
                    token: token,
                    deviceName: deviceName,
                    requestData: requestData,
                    error: error
                )
            }
        } else {
            admitPlaintextWirelessLegacyFallback(
                connection: conn,
                deviceName: deviceName,
                initialPlaintext: firstByte
            )
        }
    }

    private func admitPlaintextWirelessLegacyFallback(
        connection conn: NWConnection,
        deviceName: String,
        initialPlaintext: Data
    ) {
        recordTelemetry(
            "trusted_lan_record_protection",
            epoch: sessionEpochGate.current,
            attributes: [
                "encrypted": .boolean(false),
                "legacy_fallback": .boolean(true)
            ]
        )
        debugLog("Trusted LAN continuing with explicit plaintext legacy fallback")
        admitConnection(
            conn,
            isWireless: true,
            deviceName: deviceName,
            lanRecordProtectionState: .explicitLegacyFallback,
            initialPlaintext: initialPlaintext
        )
    }

    private func finishWirelessRecordProtectionNegotiation(
        connection conn: NWConnection,
        token: Data,
        deviceName: String,
        requestData: Data?,
        error: Error?
    ) {
        guard pendingWirelessConnections[ObjectIdentifier(conn)] === conn else { return }
        if let error {
            debugLog("Trusted LAN secure-record negotiation read failed: \(error)")
            recordTrustedLANProtectionFailure(error)
            conn.cancel()
            return
        }
        guard let requestData else {
            recordTrustedLANProtectionFailure(LANSecureRecordError.invalidHandshake)
            conn.cancel()
            return
        }
        do {
            let request = try LANSecureRecordNegotiation.decodeRequest(requestData)
            let hostPrivateKey = P256.KeyAgreement.PrivateKey()
            let hostPublicKey = hostPrivateKey.publicKey.x963Representation
            let sessionIdentifier = LANSecureRecordSession.sessionIdentifier(
                hostPublicKey: hostPublicKey,
                devicePublicKey: request.publicKey
            )
            let context = LANSecureRecordSession.transcriptContext(
                sessionIdentifier: sessionIdentifier,
                hostPublicKey: hostPublicKey,
                devicePublicKey: request.publicKey
            )
            let sharedSecret = try hostPrivateKey.sharedSecretData(with: request.publicKey)
            let recordSession = try LANSecureRecordSession(
                role: .host,
                sessionIdentifier: sessionIdentifier,
                sessionEpoch: LANSecureRecordSession.recordSessionEpoch,
                sharedSecret: sharedSecret,
                bootstrapToken: token,
                context: context
            )
            let response = try LANSecureRecordNegotiation.encodeResponse(
                publicKey: hostPublicKey,
                encrypted: true,
                explicitLegacyFallback: false
            )
            conn.send(content: response, completion: .contentProcessed { [weak self, weak conn] error in
                guard let self, let conn else { return }
                if let error {
                    debugLog("Trusted LAN secure-record negotiation response failed: \(error)")
                    conn.cancel()
                    return
                }
                self.recordTelemetry(
                    "trusted_lan_record_protection",
                    epoch: self.sessionEpochGate.current,
                    attributes: ["encrypted": .boolean(true)]
                )
                debugLog("Trusted LAN secure records negotiated")
                self.admitConnection(
                    conn,
                    isWireless: true,
                    deviceName: deviceName,
                    lanRecordSession: recordSession,
                    lanRecordProtectionState: .encrypted
                )
            })
        } catch {
            debugLog("Trusted LAN secure records required; rejecting malformed peer: \(error)")
            recordTrustedLANProtectionFailure(error)
            conn.cancel()
        }
    }

    private func recordTrustedLANProtectionFailure(_ error: Error) {
        recordTelemetry(
            "trusted_lan_record_protection_failed",
            epoch: sessionEpochGate.current,
            attributes: ["error": .string(String(describing: error))]
        )
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

    /// Commit rates that the live encoder has already adopted. These values
    /// seed the next Protocol v1 session, independently of whether the client
    /// that requested them remains connected long enough for its acknowledgement.
    func setProtocolV1VideoRates(
        framesPerSecond: Int,
        bitrateKbps: Int
    ) {
        performOnNetworkQueue {
            self.protocolV1FramesPerSecond = UInt32(clamping: framesPerSecond)
            self.protocolV1BitrateKbps = UInt32(clamping: bitrateKbps)
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

    /// Report the outcome of a client-invoked host action after the host has
    /// run the AppKit/Accessibility work. Runs on the network queue so the
    /// resulting HostActionResult is serialized behind any in-flight control
    /// frames on the active session; an unknown invocation id or a
    /// non-streaming session is a safe no-op.
    func completeProtocolV1HostAction(
        invocationID: Data,
        accepted: Bool,
        rejectionReason: String
    ) {
        networkQueue.async { [weak self] in
            guard let self, !self.isStopped,
                  self.connectionProtocolMode == .protocolV1,
                  let session = self.protocolV1Session,
                  let conn = self.connection else { return }
            let generation = self.activeConnectionGeneration
            let actions = session.completeHostAction(
                invocationID: invocationID,
                accepted: accepted,
                rejectionReason: rejectionReason
            )
            guard !actions.isEmpty else { return }
            self.applyProtocolV1Actions(actions, connection: conn, generation: generation)
        }
    }

    func offerProtocolV1File(fileURL: URL, mimeType: String = "application/octet-stream") throws {
        var creationResult: Result<ProtocolV1OutgoingFileTransfer, Error>!
        performOnNetworkQueue {
            creationResult = Result {
                let effectivePolicy = self.protocolV1Session?.negotiatedFileTransferPolicySnapshot()
                    ?? self.protocolV1FileTransferPolicy
                return try ProtocolV1OutgoingFileTransfer(
                    fileURL: fileURL,
                    mimeType: mimeType,
                    policy: effectivePolicy,
                    remotePolicy: self.protocolV1RemoteManagedPolicy
                )
            }
        }
        let transfer = try creationResult.get()
        networkQueue.async { [weak self] in
            guard let self, !self.isStopped,
                  self.connectionProtocolMode == .protocolV1,
                  let session = self.protocolV1Session,
                  let conn = self.connection else {
                transfer.cancel()
                return
            }
            let generation = self.activeConnectionGeneration
            guard session.canTransferFiles else {
                transfer.cancel()
                return
            }
            guard self.protocolV1OutgoingFiles.isEmpty else {
                transfer.cancel()
                self.applyProtocolV1Actions(
                    session.makeFileTransferCancel(
                        transferID: transfer.offer.transferID,
                        reasonCode: ProtocolV1FileTransferError.concurrentLimitReached.reasonCode
                    ),
                    connection: conn,
                    generation: generation
                )
                return
            }
            self.protocolV1OutgoingFiles[transfer.offer.transferID] = transfer
            self.applyProtocolV1Actions(
                session.makeFileOffer(transfer.offer),
                connection: conn,
                generation: generation
            )
        }
    }

    /// The Protocol v1 state machine accepted this controller event, but the
    /// native HID boundary could not apply it. Fail closed on the originating
    /// connection so the peer never assumes input is still being delivered.
    func failProtocolV1ControllerInput(
        generation: UInt64,
        correlationID: UInt64,
        reason: String
    ) {
        networkQueue.async { [weak self] in
            guard let self, !self.isStopped,
                  self.activeConnectionGeneration == generation,
                  self.connectionProtocolMode == .protocolV1,
                  let session = self.protocolV1Session,
                  let conn = self.connection else { return }
            self.applyProtocolV1Actions(
                session.rejectControllerInjection(
                    "Controller injection failed: \(reason)",
                    correlationID: correlationID
                ),
                connection: conn,
                generation: generation
            )
        }
    }

    private func completeProtocolV1ControllerConnection(
        _ event: GameControllerInputEvent,
        session expectedSession: ProtocolV1SessionCoordinator,
        connection expectedConnection: NWConnection,
        generation: UInt64
    ) {
        networkQueue.async { [weak self, weak expectedConnection] in
            guard let self, let expectedConnection, !self.isStopped,
                  self.connection === expectedConnection,
                  self.activeConnectionGeneration == generation,
                  self.clientCallbackGeneration.isCurrent(generation),
                  self.connectionProtocolMode == .protocolV1,
                  self.protocolV1Session === expectedSession else { return }
            let actions = expectedSession.completeControllerConnection(event)
            guard !actions.isEmpty else { return }
            self.applyProtocolV1Actions(
                actions,
                connection: expectedConnection,
                generation: generation
            )
        }
    }

    /// Share a string from the Mac pasteboard. The caller must read the
    /// pasteboard on the main thread before calling this. The core caches one
    /// snapshot and sends a ClipboardOffer; it never re-reads the pasteboard.
    /// Returns true when the offer was sent; false when clipboard was not
    /// negotiated, the session is not streaming, or the content failed
    /// validation (empty/oversized). Runs synchronously on the network queue
    /// so the UI gets a deterministic success/failure without a callback.
    @discardableResult
    func shareClipboard(_ text: String) -> Bool {
        withNetworkQueue {
            guard !isStopped,
                  connectionProtocolMode == .protocolV1,
                  let session = protocolV1Session,
                  let conn = connection else { return false }
            let generation = activeConnectionGeneration
            let actions = session.shareClipboard(text: text)
            guard !actions.isEmpty else { return false }
            applyProtocolV1Actions(actions, connection: conn, generation: generation)
            return true
        }
    }

    /// Request the full content for a previously received clipboard offer.
    /// The UI calls this after the user approves the receive. Returns true
    /// when the request was sent; false when the change ID is unknown,
    /// clipboard was not negotiated, or the session is not streaming.
    @discardableResult
    func requestClipboard(changeID: Data) -> Bool {
        withNetworkQueue {
            guard !isStopped,
                  connectionProtocolMode == .protocolV1,
                  let session = protocolV1Session,
                  let conn = connection else { return false }
            let generation = activeConnectionGeneration
            let actions = session.requestClipboardContent(changeID: changeID)
            guard !actions.isEmpty else { return false }
            applyProtocolV1Actions(actions, connection: conn, generation: generation)
            return true
        }
    }

    /// Release an exact in-flight clipboard request after the UI timeout. The
    /// session core retains the offer so the user may retry. Running this on
    /// the network queue also orders expiry against concurrently arriving
    /// content.
    @discardableResult
    func expireClipboardRequest(changeID: Data) -> Bool {
        withNetworkQueue {
            guard !isStopped,
                  connectionProtocolMode == .protocolV1,
                  let session = protocolV1Session,
                  connection != nil else { return false }
            return session.expireClipboardRequest(changeID: changeID)
        }
    }

    // MARK: - ClipboardServer conformance

    /// True when the connected peer negotiated the clipboard capability on an
    /// active Protocol v1 session. The clipboard menu items are disabled while
    /// this is false so the user cannot attempt clipboard operations against a
    /// peer that did not agree to them.
    var clipboardAvailable: Bool {
        withNetworkQueue {
            connectionProtocolMode == .protocolV1
                && (protocolV1Session?.hasClipboardCapability ?? false)
        }
    }

    var fileTransferAvailable: Bool {
        withNetworkQueue {
            connectionProtocolMode == .protocolV1
                && (protocolV1Session?.canTransferFiles ?? false)
        }
    }

    /// The clipboard UI calls this through the `ClipboardServer` protocol.
    /// Returns the underlying `shareClipboard` result so the caller knows
    /// whether the offer was actually sent.
    @discardableResult
    func shareClipboardText(_ text: String) -> Bool {
        shareClipboard(text)
    }

    /// The clipboard UI calls this through the `ClipboardServer` protocol.
    /// Returns the underlying `requestClipboard` result so the caller knows
    /// whether the request was actually sent.
    @discardableResult
    func sendClipboardRequest(_ request: VSClipboardRequest) -> Bool {
        requestClipboard(changeID: request.changeID)
    }

    private func withNetworkQueue<T>(_ operation: () -> T) -> T {
        if DispatchQueue.getSpecific(key: Self.networkQueueKey) == ObjectIdentifier(self) {
            return operation()
        }
        return networkQueue.sync(execute: operation)
    }

    private func performOnNetworkQueue(_ operation: @escaping () -> Void) {
        withNetworkQueue(operation)
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

    /// Snapshot used by lifecycle tests after a network-queue barrier.
    func protocolV1VideoConfigurationForSelfTest() -> (
        framesPerSecond: UInt32,
        bitrateKbps: UInt32
    ) {
        var snapshot: (framesPerSecond: UInt32, bitrateKbps: UInt32) = (0, 0)
        performOnNetworkQueue {
            snapshot = (
                self.protocolV1FramesPerSecond,
                self.protocolV1BitrateKbps
            )
        }
        return snapshot
    }

    func observeAcceptedConnectionsForSelfTest(
        _ observer: ((NWConnection) -> Void)?
    ) {
        performOnNetworkQueue {
            self.acceptedConnectionObserverForSelfTest = observer
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

        sendSessionBytes(data, on: connection, completion: .contentProcessed { _ in })
        debugLog("Sent display config: \(displayWidth)x\(displayHeight) @ \(rotation)°")
    }

    private func startReceivingTouch(on conn: NWConnection, generation: UInt64) {
        isReceiving = true
        debugLog("Starting input receive loop... (touch=\(touchEnabled ? "on" : "off"))")

        receiveQueue.async { [weak self, weak conn] in
            guard let conn else { return }
            self?.touchReceiveLoop(on: conn, generation: generation)
        }
    }

    private func touchReceiveLoop(on conn: NWConnection, generation: UInt64) {
        guard connection === conn,
              activeConnectionGeneration == generation,
              isReceiving,
              !isStopped else { return }

        conn.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { [weak self, weak conn] data, _, isComplete, error in
            guard let self,
                  let conn,
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
                do {
                    let plaintextChunks = try self.decodeInboundSessionBytes(data)
                    for plaintext in plaintextChunks where !plaintext.isEmpty {
                        self.inputBuffer.append(plaintext)
                        self.processInputBuffer(
                            connection: conn,
                            generation: generation
                        )
                    }
                } catch {
                    self.recordTelemetry(
                        "trusted_lan_record_open_failed",
                        epoch: self.sessionEpochGate.current,
                        attributes: ["error": .string(String(describing: error))]
                    )
                    conn.cancel()
                    return
                }
            }

            self.receiveQueue.async { [weak self, weak conn] in
                guard let self, let conn else { return }
                self.touchReceiveLoop(on: conn, generation: generation)
            }
        }
    }

    private func decodeInboundSessionBytes(_ bytes: Data) throws -> [Data] {
        guard activeConnectionIsWireless else { return [bytes] }
        switch lanRecordProtectionState {
        case .encrypted:
            guard let recordSession = lanSecureRecordSession else {
                throw LANSecureRecordError.encryptionRequired
            }
            return try lanSecureRecordFramer.append(bytes) { record in
                try recordSession.openDeclaredChannel(record)
            }
        case .explicitLegacyFallback:
            return [bytes]
        case .notApplicable, .negotiating:
            throw LANSecureRecordError.encryptionRequired
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
                sendSessionBytes(pong, on: connection, completion: .contentProcessed { [weak self] error in
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
                sendSessionBytes(accept, on: connection, completion: .contentProcessed { _ in })
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
        let filePolicy = protocolV1FileTransferPolicy
        let incomingFiles: ProtocolV1IncomingFileTransferManager?
        do {
            incomingFiles = try ProtocolV1IncomingFileTransferManager(
                policy: filePolicy,
                directory: Self.fileTransferStagingDirectory(sessionID: sessionID),
                // UI approval is requested asynchronously before accept(), so
                // the network queue never synchronously waits on the main actor.
                approval: { [weak self] offer in
                    guard let self,
                          DispatchQueue.getSpecific(key: Self.networkQueueKey) == ObjectIdentifier(self) else {
                        return false
                    }
                    return self.protocolV1ApprovedIncomingFileOffers.remove(offer.transferID) != nil
                }
            )
        } catch {
            incomingFiles = nil
            debugLog("File transfer staging unavailable; not advertising file transfer: \(error)")
        }
        protocolV1IncomingFiles = incomingFiles
        protocolV1RemoteManagedPolicy = .unmanaged
        let managedPolicy = ManagedPolicy.unmanaged
        var hostCapabilities = ProtocolV1SessionConfiguration.productionHostCapabilities(
            touchEnabled: touchEnabled,
            controllerAvailable: controllerAvailable,
            managedPolicy: managedPolicy,
            fileTransferAllowed: incomingFiles != nil && filePolicy.allowed,
            audioCaptureAvailable: audioStream.canAdvertiseCapture,
            wakeHostAvailable: wakeHostAuthorizer.wakeAllowed
        )
        if activeConnectionIsWireless && lanRecordProtectionState == .encrypted {
            hostCapabilities.insert(.endToEndEncryption)
            hostCapabilities.insert(.replayProtection)
        }
        protocolV1Session = ProtocolV1SessionCoordinator(configuration: ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpochGate.current,
            displayWidth: displayWidth,
            displayHeight: displayHeight,
            rotation: rotation,
            framesPerSecond: protocolV1FramesPerSecond,
            bitrateKbps: protocolV1BitrateKbps,
            hostCapabilities: hostCapabilities,
            requiredClientCapabilities: touchEnabled ? [.touch] : [],
            supportedCodecs: [.hevc, .h264],
            hostID: "macos-host",
            hostName: Host.current().localizedName ?? "Mac",
            displayID: protocolV1DisplayID,
            displayName: protocolV1DisplayName,
            displayIsVirtual: protocolV1DisplayIsVirtual,
            displays: protocolV1Displays,
            managedPolicy: managedPolicy,
            fileTransferPolicy: filePolicy
        ))
        sendSessionBytes(ProtocolV1Upgrade.acknowledgement, on: conn, completion: .contentProcessed { [weak self] error in
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
                case .audio:
                    actions = session.rejectMalformedTransport(
                        "Client-to-host audio frames are not valid in this session."
                    )
                case .bulk:
                    actions = handleProtocolV1BulkFrame(frame.payload, session: session)
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

    private func handleProtocolV1BulkFrame(
        _ payload: Data,
        session: ProtocolV1SessionCoordinator
    ) -> [ProtocolV1SessionAction] {
        let chunk: ProtocolV1FileChunk
        do {
            chunk = try ProtocolV1FileChunk(serializedFrame: payload)
        } catch {
            return session.rejectMalformedTransport("Invalid file transfer bulk frame: \(error)")
        }
        guard session.canTransferFiles, let incomingFiles = protocolV1IncomingFiles else {
            return session.makeFileTransferCancel(
                transferID: chunk.header.transferID,
                reasonCode: ProtocolV1FileTransferError.policyDenied.reasonCode
            )
        }
        do {
            let received = try incomingFiles.append(chunk, sessionEpoch: sessionEpochGate.current)
            var actions = session.makeFileTransferProgress(
                transferID: chunk.header.transferID,
                receivedBytes: received
            )
            if chunk.header.final {
                let completed = try incomingFiles.finish(transferID: chunk.header.transferID)
                actions += session.makeFileTransferComplete(
                    transferID: completed.transferID,
                    accepted: true,
                    sha256: completed.sha256,
                    rejectionReason: ""
                )
                onIncomingFileCompleted?(completed)
            }
            return actions
        } catch let error as ProtocolV1FileTransferError {
            incomingFiles.cancel(transferID: chunk.header.transferID)
            protocolV1PendingIncomingFileApprovals.remove(chunk.header.transferID)
            return session.makeFileTransferCancel(
                transferID: chunk.header.transferID,
                reasonCode: error.reasonCode
            )
        } catch {
            incomingFiles.cancel(transferID: chunk.header.transferID)
            protocolV1PendingIncomingFileApprovals.remove(chunk.header.transferID)
            return session.makeFileTransferCancel(
                transferID: chunk.header.transferID,
                reasonCode: ProtocolV1FileTransferError.ioFailure(error.localizedDescription).reasonCode
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
        let bulkPayloads = actions.compactMap { action -> Data? in
            if case .sendBulk(let payload) = action { return payload }
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
                sendSessionBytes(bytes, on: conn, completion: .contentProcessed { [weak conn] error in
                    if closesAfterSend || error != nil { conn?.cancel() }
                })
            } catch {
                debugLog("Unable to encode Protocol v1 control frame: \(error)")
                conn.cancel()
                return
            }
        }

        for payload in bulkPayloads {
            do {
                let bytes = try ProtocolV1TransportFrame(channel: .bulk, payload: payload).encoded()
                sendSessionBytes(bytes, channel: .bulk, on: conn, completion: .contentProcessed { [weak self] error in
                    if let error {
                        self?.recordTelemetry(
                            "control_send_failed",
                            epoch: self?.sessionEpochGate.current,
                            attributes: [
                                "message": .string("file_bulk"),
                                "error": .string(error.localizedDescription)
                            ]
                        )
                        conn.cancel()
                    }
                })
            } catch {
                debugLog("Unable to encode Protocol v1 bulk frame: \(error)")
                conn.cancel()
                return
            }
        }

        for action in actions {
            switch action {
            case .sendControl, .sendBulk, .close:
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
            case .stylus(
                let inputID,
                let pointerID,
                let x,
                let y,
                let phase,
                let pressure,
                let tiltXDegrees,
                let tiltYDegrees,
                let toolKind,
                let buttonMask,
                let contactState
            ):
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onStylusEvent?(
                        inputID,
                        pointerID,
                        x,
                        y,
                        phase,
                        pressure,
                        tiltXDegrees,
                        tiltYDegrees,
                        toolKind,
                        buttonMask,
                        contactState,
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
            case .controller(let event, let correlationID):
                guard let session = protocolV1Session else { break }
                DispatchQueue.main.async { [weak self, weak conn] in
                    guard let self,
                          let conn,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    guard GameControllerEventDelivery.deliver(
                        event,
                        generation: generation,
                        using: self.onControllerEvent
                    ) else {
                        // Stop later input actions already queued on the main
                        // actor before the network queue closes the failed
                        // session.
                        self.clientCallbackGeneration.invalidateIfCurrent(generation)
                        self.failProtocolV1ControllerInput(
                            generation: generation,
                            correlationID: correlationID,
                            reason: "native controller handler was unavailable or rejected the event"
                        )
                        return
                    }
                    if event.kind == .connected {
                        self.completeProtocolV1ControllerConnection(
                            event,
                            session: session,
                            connection: conn,
                            generation: generation
                        )
                    }
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
            case .hostAction(let actionID, let invocationID, let target):
                // Hop to the main actor to run AppKit/Accessibility work. The
                // clientCallbackGeneration guard drops the callback if the
                // connection generation advanced (a reconnect) before it runs,
                // exactly like the touch/pointer/key/video-preferences paths, so
                // a stale invocation from a previous connection can never drive
                // the current one. The invocation_id is echoed verbatim, and the
                // host reports the outcome through completeProtocolV1HostAction,
                // which is a safe no-op if the session is no longer tracking it.
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onHostActionRequested?(actionID, invocationID, target)
                }
            case .clipboardOffer(let metadata):
                // Forward the offer metadata to the UI so the user can decide
                // whether to request the full content. The generation guard
                // drops stale offers from a previous connection.
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onClipboardOfferReceived?(metadata, generation)
                }
            case .clipboardContent(let content):
                // A requested clipboard content passed validation. The UI
                // writes it to the pasteboard. Stale content from a previous
                // connection is dropped by the generation guard.
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onClipboardContentReceived?(content, generation)
                }
            case .clipboardDirectContent(let content):
                // Unsolicited clipboard content. The UI must obtain explicit
                // user approval before writing to the pasteboard; the core
                // never writes it. Stale content is dropped by the generation
                // guard.
                DispatchQueue.main.async { [weak self] in
                    guard let self,
                          self.clientCallbackGeneration.isCurrent(generation) else { return }
                    self.onClipboardDirectContentReceived?(content, generation)
                }
            case .fileOffer(let offer, _):
                handleProtocolV1FileOffer(offer, connection: conn, generation: generation)
            case .fileAccept(let response):
                guard response.accepted,
                      let transfer = protocolV1OutgoingFiles[response.transferID],
                      let session = protocolV1Session else {
                    protocolV1OutgoingFiles.removeValue(forKey: response.transferID)?.cancel()
                    break
                }
                transfer.applyAcceptedMaximumChunkBytes(Int(response.maximumChunkBytes))
                sendNextProtocolV1FileChunk(
                    transfer,
                    session: session,
                    connection: conn,
                    generation: generation
                )
            case .fileTransferProgress(let progress):
                guard let transfer = protocolV1OutgoingFiles[progress.transferID],
                      let session = protocolV1Session else { break }
                do {
                    try transfer.validateAcknowledgedOffset(progress.receivedBytes)
                } catch let error as ProtocolV1FileTransferError {
                    protocolV1OutgoingFiles.removeValue(forKey: progress.transferID)?.cancel()
                    applyProtocolV1Actions(
                        session.makeFileTransferCancel(
                            transferID: progress.transferID,
                            reasonCode: error.reasonCode
                        ),
                        connection: conn,
                        generation: generation
                    )
                    break
                } catch {
                    protocolV1OutgoingFiles.removeValue(forKey: progress.transferID)?.cancel()
                    applyProtocolV1Actions(
                        session.makeFileTransferCancel(
                            transferID: progress.transferID,
                            reasonCode: ProtocolV1FileTransferError.ioFailure(error.localizedDescription).reasonCode
                        ),
                        connection: conn,
                        generation: generation
                    )
                    break
                }
                sendNextProtocolV1FileChunk(
                    transfer,
                    session: session,
                    connection: conn,
                    generation: generation
                )
            case .fileTransferCancel(let cancellation):
                protocolV1IncomingFiles?.cancel(transferID: cancellation.transferID)
                protocolV1PendingIncomingFileApprovals.remove(cancellation.transferID)
                protocolV1ApprovedIncomingFileOffers.remove(cancellation.transferID)
                protocolV1OutgoingFiles.removeValue(forKey: cancellation.transferID)?.cancel()
            case .fileTransferComplete(let result):
                guard let session = protocolV1Session,
                      let transfer = protocolV1OutgoingFiles.removeValue(forKey: result.transferID) else { break }
                defer { transfer.cancel() }
                guard result.accepted else {
                    debugLog("File transfer rejected by peer: \(result.rejectionReason)")
                    break
                }
                do {
                    try transfer.validateCompletionDigest(result.sha256)
                } catch let error as ProtocolV1FileTransferError {
                    debugLog("File transfer completion rejected for \(transfer.offer.fileName): \(error.reasonCode)")
                    applyProtocolV1Actions(
                        session.makeFileTransferCancel(
                            transferID: result.transferID,
                            reasonCode: error.reasonCode
                        ),
                        connection: conn,
                        generation: generation
                    )
                } catch {
                    debugLog("File transfer completion rejected for \(transfer.offer.fileName): \(error.localizedDescription)")
                    applyProtocolV1Actions(
                        session.makeFileTransferCancel(
                            transferID: result.transferID,
                            reasonCode: ProtocolV1FileTransferError.ioFailure(error.localizedDescription).reasonCode
                        ),
                        connection: conn,
                        generation: generation
                    )
                }
            case .remoteManagedPolicyChanged(let status):
                protocolV1RemoteManagedPolicy = ProtocolV1RemoteManagedPolicy(status: status)
                if !protocolV1RemoteManagedPolicy.fileTransferAllowed {
                    cancelProtocolV1ActiveFileTransfers()
                }
            case .startAudio(let config):
                startProtocolV1Audio(config: config, connection: conn, generation: generation)
            case .stopAudio(let reason):
                stopProtocolV1Audio(reason: reason)
            case .wakeHost(let request, let correlationID):
                dispatchWakeHostRequest(
                    request,
                    correlationID: correlationID,
                    connection: conn,
                    generation: generation
                )
            }
        }
        if shouldClose && controlPayloads.isEmpty { conn.cancel() }
    }

    private func handleProtocolV1FileOffer(
        _ offer: VSFileOffer,
        connection conn: NWConnection,
        generation: UInt64
    ) {
        guard let incomingFiles = protocolV1IncomingFiles,
              let session = protocolV1Session else { return }
        do {
            guard !protocolV1PendingIncomingFileApprovals.contains(offer.transferID) else {
                throw ProtocolV1FileTransferError.duplicateTransfer
            }
            _ = try incomingFiles.validateOfferForApproval(
                offer,
                remotePolicy: protocolV1RemoteManagedPolicy,
                negotiatedPolicy: session.negotiatedFileTransferPolicySnapshot(),
                pendingTransferCount: protocolV1PendingIncomingFileApprovals.count
            )
        } catch let error as ProtocolV1FileTransferError {
            applyProtocolV1Actions(
                session.makeFileAccept(Self.rejectedFileAccept(
                    transferID: offer.transferID,
                    reasonCode: error.reasonCode
                )),
                connection: conn,
                generation: generation
            )
            return
        } catch {
            applyProtocolV1Actions(
                session.makeFileAccept(Self.rejectedFileAccept(
                    transferID: offer.transferID,
                    reasonCode: ProtocolV1FileTransferError.ioFailure(error.localizedDescription).reasonCode
                )),
                connection: conn,
                generation: generation
            )
            return
        }
        protocolV1PendingIncomingFileApprovals.insert(offer.transferID)
        Self.requestFileTransferApproval(
            offer: offer,
            approval: onFileTransferApprovalRequested
        ) { [weak self, weak conn] accepted in
            guard let self, let conn else { return }
            self.networkQueue.async { [weak self, weak conn] in
                guard let self, let conn,
                      self.connection === conn,
                      self.activeConnectionGeneration == generation,
                      self.connectionProtocolMode == .protocolV1,
                      !self.isStopped,
                      let incomingFiles = self.protocolV1IncomingFiles,
                      let session = self.protocolV1Session,
                      self.protocolV1PendingIncomingFileApprovals.remove(offer.transferID) != nil else { return }
                guard self.clientCallbackGeneration.isCurrent(generation) else { return }
                let response: VSFileAccept
                if accepted {
                    do {
                        self.protocolV1ApprovedIncomingFileOffers.insert(offer.transferID)
                        defer { self.protocolV1ApprovedIncomingFileOffers.remove(offer.transferID) }
                        response = try incomingFiles.accept(
                            offer,
                            remotePolicy: self.protocolV1RemoteManagedPolicy,
                            negotiatedPolicy: session.negotiatedFileTransferPolicySnapshot(),
                            sessionEpoch: self.sessionEpochGate.current
                        )
                    } catch let error as ProtocolV1FileTransferError {
                        response = Self.rejectedFileAccept(transferID: offer.transferID, reasonCode: error.reasonCode)
                    } catch {
                        response = Self.rejectedFileAccept(
                            transferID: offer.transferID,
                            reasonCode: ProtocolV1FileTransferError.ioFailure(error.localizedDescription).reasonCode
                        )
                    }
                } else {
                    response = Self.rejectedFileAccept(
                        transferID: offer.transferID,
                        reasonCode: ProtocolV1FileTransferError.userDenied.reasonCode
                    )
                }
                self.applyProtocolV1Actions(
                    session.makeFileAccept(response),
                    connection: conn,
                    generation: generation
                )
            }
        }
    }

    private func dispatchWakeHostRequest(
        _ request: WakeHostRequestContext,
        correlationID: UInt64,
        connection conn: NWConnection,
        generation: UInt64
    ) {
        let authorizer = wakeHostAuthorizer
        let packetSender = wakeHostPacketSender
        wakeHostQueue.async { [weak self, weak conn] in
            let result = Self.performWakeHostRequest(
                request,
                authorizer: authorizer,
                packetSender: packetSender
            )
            self?.networkQueue.async { [weak self, weak conn] in
                guard let self, let conn else { return }
                guard self.connection === conn,
                      self.activeConnectionGeneration == generation,
                      self.connectionProtocolMode == .protocolV1,
                      !self.isStopped else { return }
                let followUp = self.protocolV1Session?.completeWakeHost(
                    requestID: request.requestID,
                    accepted: result.accepted,
                    rejectionReason: result.reason
                ) ?? []
                if !followUp.isEmpty {
                    self.applyProtocolV1Actions(followUp, connection: conn, generation: generation)
                }
            }
        }
    }

    private func sendNextProtocolV1FileChunk(
        _ transfer: ProtocolV1OutgoingFileTransfer,
        session: ProtocolV1SessionCoordinator,
        connection conn: NWConnection,
        generation: UInt64
    ) {
        guard protocolV1OutgoingFiles[transfer.offer.transferID] != nil else { return }
        do {
            guard let chunk = try transfer.nextChunk(
                maximumBytes: transfer.maximumChunkBytes(default: protocolV1FileTransferPolicy.maximumChunkBytes),
                sessionEpoch: sessionEpochGate.current
            ) else { return }
            applyProtocolV1Actions(
                session.makeBulkFrame(try chunk.serializedFrame()),
                connection: conn,
                generation: generation
            )
        } catch let error as ProtocolV1FileTransferError {
            protocolV1OutgoingFiles.removeValue(forKey: transfer.offer.transferID)?.cancel()
            applyProtocolV1Actions(
                session.makeFileTransferCancel(
                    transferID: transfer.offer.transferID,
                    reasonCode: error.reasonCode
                ),
                connection: conn,
                generation: generation
            )
        } catch {
            protocolV1OutgoingFiles.removeValue(forKey: transfer.offer.transferID)?.cancel()
            applyProtocolV1Actions(
                session.makeFileTransferCancel(
                    transferID: transfer.offer.transferID,
                    reasonCode: ProtocolV1FileTransferError.ioFailure(error.localizedDescription).reasonCode
                ),
                connection: conn,
                generation: generation
            )
        }
    }

    private func startProtocolV1Audio(
        config: VSAudioConfig,
        connection conn: NWConnection,
        generation: UInt64
    ) {
        guard connection === conn,
              activeConnectionGeneration == generation,
              connectionProtocolMode == .protocolV1,
              !isStopped else { return }
        stopProtocolV1Audio(reason: "audio_reconfigure")
        audioGeneration &+= 1
        let currentAudioGeneration = audioGeneration
        do {
            try audioStream.start(
                config: config,
                sessionEpoch: sessionEpochGate.current,
                onPacket: { [weak self, weak conn] packet in
                    guard let self, let conn else { return }
                    self.networkQueue.async {
                        self.enqueueProtocolV1AudioPacket(
                            packet,
                            connection: conn,
                            generation: generation,
                            audioGeneration: currentAudioGeneration
                        )
                    }
                },
                onError: { [weak self] error in
                    self?.networkQueue.async {
                        guard let self,
                              self.connection === conn,
                              self.activeConnectionGeneration == generation,
                              self.audioGeneration == currentAudioGeneration else { return }
                        self.recordTelemetry(
                            "audio_capture_failed",
                            epoch: self.sessionEpochGate.current,
                            attributes: ["error": .string(error.localizedDescription)]
                        )
                        self.failProtocolV1Audio(
                            reason: "audio_capture_failed",
                            message: "Audio capture failed: \(error.localizedDescription)",
                            connection: conn,
                            generation: generation,
                            audioGeneration: currentAudioGeneration
                        )
                    }
                }
            )
            recordTelemetry(
                "audio_capture_started",
                epoch: sessionEpochGate.current,
                attributes: [
                    "stream_id": .unsigned(config.streamID),
                    "config_epoch": .unsigned(config.configEpoch),
                    "sample_rate_hz": .unsigned(UInt64(config.sampleRateHz)),
                    "channel_count": .unsigned(UInt64(config.channelCount)),
                    "frames_per_packet": .unsigned(UInt64(config.framesPerPacket))
                ]
            )
        } catch {
            recordTelemetry(
                "audio_capture_start_failed",
                epoch: sessionEpochGate.current,
                attributes: ["error": .string(error.localizedDescription)]
            )
            failProtocolV1Audio(
                reason: "audio_capture_start_failed",
                message: "Audio capture failed to start: \(error.localizedDescription)",
                connection: conn,
                generation: generation,
                audioGeneration: currentAudioGeneration
            )
        }
    }

    private func enqueueProtocolV1AudioPacket(
        _ packet: MacHostAudioPacket,
        connection conn: NWConnection,
        generation: UInt64,
        audioGeneration expectedAudioGeneration: UInt64
    ) {
        dispatchPrecondition(condition: .onQueue(networkQueue))
        guard connection === conn,
              activeConnectionGeneration == generation,
              audioGeneration == expectedAudioGeneration,
              connectionProtocolMode == .protocolV1,
              sessionEpochGate.accepts(packet.header.sessionEpoch),
              !isStopped else { return }
        pendingAudioPackets.append(PendingAudioPacket(
            serializedFrame: packet.serializedFrame,
            timestamp: packet.timestampMonotonicNs,
            connection: conn,
            generation: generation,
            audioGeneration: expectedAudioGeneration,
            sessionEpoch: packet.header.sessionEpoch
        ))
        var dropped = 0
        while pendingAudioPackets.count > maximumPendingAudioPackets {
            pendingAudioPackets.removeFirst()
            dropped += 1
        }
        if dropped > 0 {
            recordTelemetry(
                "audio_queue_drop",
                epoch: packet.header.sessionEpoch,
                attributes: [
                    "dropped": .integer(Int64(dropped)),
                    "depth": .integer(Int64(pendingAudioPackets.count)),
                    "capacity": .integer(Int64(maximumPendingAudioPackets))
                ]
            )
        }
        drainProtocolV1AudioQueue()
    }

    private func drainProtocolV1AudioQueue() {
        dispatchPrecondition(condition: .onQueue(networkQueue))
        guard !audioSendInFlight, !pendingAudioPackets.isEmpty else { return }
        let packet = pendingAudioPackets.removeFirst()
        guard connection === packet.connection,
              activeConnectionGeneration == packet.generation,
              audioGeneration == packet.audioGeneration,
              connectionProtocolMode == .protocolV1,
              sessionEpochGate.accepts(packet.sessionEpoch),
              !isStopped else { return }
        let frame: Data
        do {
            frame = try ProtocolV1TransportFrame(channel: .audio, payload: packet.serializedFrame).encoded()
        } catch {
            recordTelemetry(
                "audio_frame_encode_failed",
                epoch: packet.sessionEpoch,
                attributes: ["error": .string(error.localizedDescription)]
            )
            stopProtocolV1Audio(reason: "audio_frame_encode_failed")
            return
        }
        audioSendInFlight = true
        sendSessionBytes(frame, channel: .audio, on: packet.connection, completion: .contentProcessed { [weak self] error in
            guard let self else { return }
            self.networkQueue.async {
                guard self.connection === packet.connection,
                      self.activeConnectionGeneration == packet.generation,
                      self.audioGeneration == packet.audioGeneration else { return }
                self.audioSendInFlight = false
                if let error {
                    self.recordTelemetry(
                        "audio_send_failed",
                        epoch: packet.sessionEpoch,
                        attributes: ["error": .string(error.localizedDescription)]
                    )
                    self.stopProtocolV1Audio(reason: "audio_send_failed")
                    return
                }
                self.drainProtocolV1AudioQueue()
            }
        })
    }

    private func stopProtocolV1Audio(reason: String) {
        dispatchPrecondition(condition: .onQueue(networkQueue))
        let wasRunning = audioStream.isRunning || !pendingAudioPackets.isEmpty || audioSendInFlight
        audioGeneration &+= 1
        audioStream.stop()
        pendingAudioPackets.removeAll(keepingCapacity: true)
        audioSendInFlight = false
        guard wasRunning else { return }
        recordTelemetry(
            "audio_capture_stopped",
            epoch: sessionEpochGate.current,
            attributes: ["reason": .string(reason)]
        )
    }

    private func failProtocolV1Audio(
        reason: String,
        message: String,
        connection conn: NWConnection,
        generation: UInt64,
        audioGeneration expectedAudioGeneration: UInt64
    ) {
        dispatchPrecondition(condition: .onQueue(networkQueue))
        guard connection === conn,
              activeConnectionGeneration == generation,
              audioGeneration == expectedAudioGeneration,
              connectionProtocolMode == .protocolV1,
              !isStopped else { return }
        stopProtocolV1Audio(reason: reason)
        guard let session = protocolV1Session else {
            conn.cancel()
            return
        }
        applyProtocolV1Actions(
            session.failAudioRuntime(message),
            connection: conn,
            generation: generation
        )
    }

    static func performWakeHostRequest(
        _ request: WakeHostRequestContext,
        authorizer: any WakeHostAuthorizing,
        packetSender: any WakeHostPacketSending
    ) -> (accepted: Bool, reason: String) {
        do {
            let packet = try WakeHostDecision.magicPacket(
                for: request,
                authorizer: authorizer
            )
            try packetSender.sendWakeHostPacket(packet)
            return (true, "")
        } catch WakeHostRequestError.policyDenied {
            return (false, "wake_host_policy_denied")
        } catch WakeHostRequestError.invalidRequestID {
            return (false, "invalid_request_id")
        } catch WakeHostRequestError.invalidMACAddress {
            return (false, "invalid_mac_address")
        } catch WakeHostRequestError.invalidSecureOnPassword {
            return (false, "invalid_secure_on_password")
        } catch WakeHostRequestError.invalidAuthorization {
            return (false, "wake_host_unauthorized")
        } catch WakeHostRequestError.expiredAuthorization {
            return (false, "wake_host_authorization_expired")
        } catch WakeHostRequestError.replayedRequest {
            return (false, "wake_host_replay")
        } catch WakeHostPacketSenderError.invalidBroadcastAddress {
            return (false, "invalid_broadcast_target")
        } catch WakeHostPacketSenderError.invalidPort {
            return (false, "invalid_broadcast_target")
        } catch WakeHostPacketSenderError.timedOut {
            return (false, "wake_packet_send_timeout")
        } catch {
            return (false, "wake_packet_send_failed")
        }
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

    func dispatchTakeoverInputCancellation(
        oldConnectionWasPresent: Bool,
        generation: UInt64
    ) {
        guard oldConnectionWasPresent else { return }
        dispatchInputCancellation(generation: generation)
    }

    private func dispatchInputCancellation(generation: UInt64) {
        DispatchQueue.main.async { [weak self] in
            guard let self,
                  self.clientCallbackGeneration.isCurrent(generation) else { return }
            self.onInputCancelled?(generation)
        }
    }

    func advanceClientGenerationForSelfTest(to generation: UInt64) {
        clientCallbackGeneration.advance(to: generation)
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

        let submission = FrameSubmission(
            data: data,
            timestamp: timestamp,
            isKeyframe: isKeyframe,
            connection: connection,
            clientGeneration: clientGeneration,
            sessionEpoch: frameEpoch
        )
        guard frameMailbox.submit(
            submission,
            generation: clientGeneration,
            sessionEpoch: frameEpoch
        ) else { return }
        frameQueue.async { [weak self] in
            self?.drainLatestFrameSubmission(
                generation: clientGeneration,
                sessionEpoch: frameEpoch
            )
        }
    }

    private func drainLatestFrameSubmission(generation: UInt64, sessionEpoch: UInt64) {
        guard let drain = frameMailbox.take(
            generation: generation,
            sessionEpoch: sessionEpoch
        ) else {
            finishFrameSubmissionDrain(generation: generation, sessionEpoch: sessionEpoch)
            return
        }
        if drain.droppedCount > 0 {
            observeQueueResult(
                LatestFrameEnqueueResult(
                    accepted: drain.element != nil,
                    droppedCount: drain.droppedCount,
                    requiresKeyframe: drain.requiresKeyframe
                ),
                epoch: sessionEpoch,
                clientGeneration: generation
            )
        }
        guard let submission = drain.element else {
            finishFrameSubmissionDrain(generation: generation, sessionEpoch: sessionEpoch)
            return
        }
        guard connection === submission.connection,
              !isStopped,
              connectionReady,
              sessionEpochGate.accepts(submission.sessionEpoch) else {
            if let result = frameMailbox.discardTaken(
                generation: generation,
                sessionEpoch: sessionEpoch
            ) {
                observeQueueResult(
                    result,
                    epoch: submission.sessionEpoch,
                    clientGeneration: submission.clientGeneration
                )
            }
            finishFrameSubmissionDrain(generation: generation, sessionEpoch: sessionEpoch)
            return
        }

        let frame = PendingFrame(
            data: submission.data,
            timestamp: submission.timestamp,
            isKeyframe: submission.isKeyframe,
            connection: submission.connection,
            generation: framePipelineGeneration,
            clientGeneration: submission.clientGeneration,
            sessionEpoch: submission.sessionEpoch,
            packetChannel: connectionProtocolMode == .protocolV1 ? .media : .control
        )
        let result = pendingFrames.enqueue(frame)
        observeQueueResult(
            result,
            epoch: submission.sessionEpoch,
            clientGeneration: submission.clientGeneration
        )
        if !sendInFlight, let admitted = pendingFrames.dequeue() {
            transmit(admitted)
        }
        finishFrameSubmissionDrain(generation: generation, sessionEpoch: sessionEpoch)
    }

    private func finishFrameSubmissionDrain(generation: UInt64, sessionEpoch: UInt64) {
        guard frameMailbox.finishDrain(
            generation: generation,
            sessionEpoch: sessionEpoch
        ) else { return }
        frameQueue.async { [weak self] in
            self?.drainLatestFrameSubmission(
                generation: generation,
                sessionEpoch: sessionEpoch
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
                "capacity": .integer(Int64(pendingFrames.capacity + 1)),
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

        sendSessionBytes(packet, channel: frame.packetChannel, on: frame.connection, completion: .contentProcessed { [weak self] error in
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
                if self.firstFrameSentTelemetryEpoch != frame.sessionEpoch {
                    self.firstFrameSentTelemetryEpoch = frame.sessionEpoch
                    self.recordTelemetry(
                        "first_frame_sent",
                        epoch: frame.sessionEpoch,
                        attributes: [
                            "bytes": .integer(Int64(frame.data.count)),
                            "keyframe": .boolean(frame.isKeyframe),
                            "packet_channel": .string(frame.packetChannel.telemetryLabel),
                            "client_generation": .unsigned(frame.clientGeneration)
                        ]
                    )
                }
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
                var attributes: [String: TelemetryValue] = [
                    "fps": .double(fps),
                    "mbps": .double(mbps),
                    "average_frame_age_ms": .double(avgAgeMs),
                    "dropped_frames": .unsigned(droppedFrames),
                    "queue_depth": .integer(
                        Int64(pendingFrames.count + (sendInFlight ? 1 : 0))
                    ),
                    "queue_capacity": .integer(
                        Int64(pendingFrames.capacity + 1)
                    )
                ]
                if let encoderStatsProvider, let stats = encoderStatsProvider() {
                    attributes["encoder_in_flight"] = .integer(Int64(stats.inFlight))
                    attributes["encoder_in_flight_capacity"] = .integer(Int64(stats.capacity))
                }
                recordTelemetry(
                    "stream_stats",
                    epoch: sessionEpochGate.current,
                    attributes: attributes
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
            for (_, pendingConnection) in self.pendingAcceptedConnections {
                pendingConnection.stateUpdateHandler = nil
                pendingConnection.cancel()
            }
            self.pendingAcceptedConnections.removeAll()
            for (_, pendingConnection) in self.pendingWirelessConnections {
                pendingConnection.stateUpdateHandler = nil
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
        sendSessionBytes(shutdownMsg, on: conn, completion: .contentProcessed { [weak self, weak conn] _ in
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
        activeConnectionIsWireless = false
        lanSecureRecordSession?.close()
        lanSecureRecordSession = nil
        lanSecureRecordFramer = LANSecureRecordStreamFramer()
        lanRecordProtectionState = .notApplicable
        protocolV1Framer = ProtocolV1Framer()
        protocolV1Session = nil
        protocolV1TouchAggregator.reset()
        clearProtocolV1FileTransfers()
        stopProtocolV1Audio(reason: "server_stop")
        if activeConnectionGeneration == generation {
            activeConnectionGeneration &+= 1
        }
        codecNegotiationGeneration = nil
        clientCallbackGeneration.advance(to: activeConnectionGeneration)
        for (_, timeout) in pendingHandshakeTimeouts {
            timeout.cancel()
        }
        pendingHandshakeTimeouts.removeAll()
        for (_, pendingConnection) in pendingAcceptedConnections {
            pendingConnection.stateUpdateHandler = nil
            pendingConnection.cancel()
        }
        pendingAcceptedConnections.removeAll()
        for (_, pendingConnection) in pendingWirelessConnections {
            pendingConnection.stateUpdateHandler = nil
            pendingConnection.cancel()
        }
        pendingWirelessConnections.removeAll()
        heartbeatTimer?.cancel()
        heartbeatTimer = nil

        // Invalidate completions from the old connection and discard its newest
        // unsent frame before cancelling.
        frameMailbox.reset(
            generation: activeConnectionGeneration,
            sessionEpoch: sessionEpochGate.current,
            accepting: false
        )
        frameQueue.sync {
            framePipelineGeneration &+= 1
            sendInFlight = false
            _ = pendingFrames.reset(requiresKeyframe: true)
        }
        recoveryController.stop()
        receiveQueue.sync {}

        stoppedConnection?.stateUpdateHandler = nil
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

    private func clearProtocolV1FileTransfers() {
        cancelProtocolV1ActiveFileTransfers()
        protocolV1IncomingFiles = nil
    }

    private func cancelProtocolV1ActiveFileTransfers() {
        protocolV1IncomingFiles?.cancelAll()
        protocolV1PendingIncomingFileApprovals.removeAll()
        protocolV1ApprovedIncomingFileOffers.removeAll()
        protocolV1OutgoingFiles.values.forEach { $0.cancel() }
        protocolV1OutgoingFiles.removeAll()
    }
}

// MARK: - ClipboardServer conformance

extension StreamingServer: ClipboardServer {}
extension StreamingServer: FileTransferServer {}

private extension InternetTransportChannel {
    var telemetryLabel: String {
        switch self {
        case .control: return "control"
        case .media: return "media"
        case .audio: return "audio"
        case .bulk: return "bulk"
        }
    }
}
