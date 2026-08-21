import Foundation
import Network

public enum TCPTransportError: Error, LocalizedError {
    case invalidPort(UInt16)
    case authenticationRequired
    case notConnected
    case connectionFailed(String)
    case connectionClosed
    case timedOut(String)

    public var errorDescription: String? {
        switch self {
        case let .invalidPort(port): "无效端口：\(port)"
        case .authenticationRequired: "可信局域网连接必须提供配对认证；测试环境需显式选择无认证模式"
        case .notConnected: "尚未连接主机"
        case let .connectionFailed(reason): "连接失败：\(reason)"
        case .connectionClosed: "主机已断开连接"
        case let .timedOut(stage): "连接在\(stage)阶段超时"
        }
    }
}

public enum TCPTransportStartup: Sendable {
    case trustedLAN(token: Data, deviceName: String)
    case trustedLANLegacyPlaintext(token: Data, deviceName: String)
    case usbNoAuthentication
}

public struct TransportDelivery: @unchecked Sendable {
    public let owner: ConnectionOwner
    public let result: Result<TransportFrame, Error>

    public init(owner: ConnectionOwner, result: Result<TransportFrame, Error>) {
        self.owner = owner
        self.result = result
    }
}

public final class TCPTransport: @unchecked Sendable {
    public typealias FrameHandler = @Sendable (TransportDelivery) -> Void

    private let queue = DispatchQueue(label: "dev.vibescreen.ios.transport", qos: .userInteractive)
    private let lock = NSLock()
    private var connection: NWConnection?
    private var connectionOwner: ConnectionOwner?
    private var startupCancellation: (@Sendable () -> Void)?
    private var framer = TransportFramer()
    private var lanRecordSession: LANSecureRecordSession?
    private var lanRecordFramer = LANSecureRecordStreamFramer()
    private var lanRecordProtectionState: LANRecordProtectionState = .notApplicable
    private let onFrame: FrameHandler

    public init(onFrame: @escaping FrameHandler) {
        self.onFrame = onFrame
    }

    public var recordProtectionState: LANRecordProtectionState {
        lock.withLock { lanRecordProtectionState }
    }

    public func connect(host: String, port: UInt16) async throws {
        throw TCPTransportError.authenticationRequired
    }

    public func connect(
        pairing: TrustedLANPairing,
        deviceName: String,
        owner: ConnectionOwner,
        timeout: TimeInterval = 3
    ) async throws {
        try await connect(
            host: pairing.host,
            port: pairing.port,
            startup: .trustedLAN(token: pairing.token, deviceName: deviceName),
            owner: owner,
            timeout: timeout
        )
    }

    public func connect(
        host: String,
        port: UInt16,
        startup: TCPTransportStartup,
        owner: ConnectionOwner,
        timeout: TimeInterval = 3
    ) async throws {
        guard let networkPort = NWEndpoint.Port(rawValue: port) else {
            throw TCPTransportError.invalidPort(port)
        }
        let timeout = max(timeout, 0.001)
        disconnect()
        let connection = NWConnection(host: NWEndpoint.Host(host), port: networkPort, using: .tcp)
        lock.withLock {
            self.connection = connection
            connectionOwner = owner
            framer = TransportFramer()
        }

        do {
            try await withTaskCancellationHandler {
                try await waitUntilReady(connection, timeout: timeout)
                try Task.checkCancellation()
                switch startup {
                case let .trustedLAN(token, deviceName):
                    let request = try TrustedLANHandshake.request(token: token, deviceName: deviceName)
                    try await sendRaw(request, on: connection, timeout: timeout, stage: "认证请求")
                    let response = try await readExactly(
                        TrustedLANHandshake.responseLength,
                        from: connection,
                        timeout: timeout,
                        stage: "认证响应"
                    )
                    try TrustedLANHandshake.validateResponse(response)
                    let negotiation = try await LANSecureRecordClient.negotiate(
                        token: token,
                        allowLegacyFallback: false,
                        send: { data, stage in
                            try await self.sendRaw(data, on: connection, timeout: timeout, stage: stage)
                        },
                        read: { count, stage in
                            try await self.readExactly(count, from: connection, timeout: timeout, stage: stage)
                        }
                    )
                    lock.withLock {
                        guard self.connection === connection else { return }
                        self.lanRecordSession = negotiation.session
                        self.lanRecordProtectionState = negotiation.state
                        self.lanRecordFramer = LANSecureRecordStreamFramer()
                    }
                case let .trustedLANLegacyPlaintext(token, deviceName):
                    let request = try TrustedLANHandshake.request(token: token, deviceName: deviceName)
                    try await sendRaw(request, on: connection, timeout: timeout, stage: "认证请求")
                    let response = try await readExactly(
                        TrustedLANHandshake.responseLength,
                        from: connection,
                        timeout: timeout,
                        stage: "认证响应"
                    )
                    try TrustedLANHandshake.validateResponse(response)
                    lock.withLock {
                        guard self.connection === connection else { return }
                        self.lanRecordSession = nil
                        self.lanRecordProtectionState = .explicitLegacyFallback
                        self.lanRecordFramer = LANSecureRecordStreamFramer()
                    }
                case .usbNoAuthentication:
                    lock.withLock {
                        guard self.connection === connection else { return }
                        self.lanRecordSession = nil
                        self.lanRecordProtectionState = .notApplicable
                        self.lanRecordFramer = LANSecureRecordStreamFramer()
                    }
                }
                try Task.checkCancellation()
                try await sendSessionPayload(
                    ProtocolV1Upgrade.offer,
                    channel: .control,
                    on: connection,
                    timeout: timeout,
                    stage: "协议升级请求"
                )
                let acknowledgement = try await readSessionPayload(
                    from: connection,
                    plaintextByteCount: ProtocolV1Upgrade.acknowledgement.count,
                    timeout: timeout,
                    stage: "协议升级响应"
                )
                try ProtocolV1Upgrade.validateAcknowledgement(acknowledgement)
                connection.stateUpdateHandler = { [weak self, weak connection] state in
                    guard let self, let connection,
                          self.lock.withLock({ self.connection === connection }) else { return }
                    switch state {
                    case let .failed(error):
                        self.onFrame(TransportDelivery(
                            owner: owner,
                            result: .failure(TCPTransportError.connectionFailed(error.localizedDescription))
                        ))
                        self.disconnect(connection)
                    case .cancelled:
                        self.onFrame(TransportDelivery(
                            owner: owner,
                            result: .failure(TCPTransportError.connectionClosed)
                        ))
                        self.disconnect(connection)
                    default:
                        break
                    }
                }
                receiveNext(on: connection, owner: owner)
            } onCancel: { [weak self, weak connection] in
                guard let self, let connection else { return }
                self.cancelStartup(for: connection)
                self.disconnect(connection)
            }
        } catch {
            disconnect(connection)
            throw error
        }
    }

    public func send(
        _ frame: TransportFrame,
        owner: ConnectionOwner,
        timeout: TimeInterval = 3
    ) async throws {
        let connection = lock.withLock {
            connectionOwner == owner ? self.connection : nil
        }
        guard let connection else { throw TCPTransportError.notConnected }
        let data = try sessionBytes(for: frame)
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let gate = ContinuationGate()
            let timeoutWork = SendableWorkItem { [weak self, weak connection] in
                guard gate.claim() else { return }
                if let self, let connection { self.disconnect(connection) }
                continuation.resume(throwing: TCPTransportError.timedOut("发送 Protocol v1 帧"))
            }
            queue.asyncAfter(deadline: .now() + max(timeout, 0.001), execute: timeoutWork.workItem)
            connection.send(content: data, completion: .contentProcessed { error in
                guard gate.claim() else { return }
                timeoutWork.cancel()
                if let error {
                    continuation.resume(throwing: TCPTransportError.connectionFailed(error.localizedDescription))
                } else {
                    continuation.resume()
                }
            })
        }
    }

    public func disconnect() {
        let snapshot = lock.withLock { () -> (NWConnection?, (@Sendable () -> Void)?) in
            defer { self.connection = nil }
            defer { connectionOwner = nil }
            defer { startupCancellation = nil }
            defer { lanRecordSession?.close() }
            defer { lanRecordSession = nil }
            defer { lanRecordProtectionState = .notApplicable }
            defer { lanRecordFramer = LANSecureRecordStreamFramer() }
            framer = TransportFramer()
            return (self.connection, startupCancellation)
        }
        snapshot.1?()
        snapshot.0?.stateUpdateHandler = nil
        snapshot.0?.cancel()
    }

    private func receiveNext(on connection: NWConnection, owner: ConnectionOwner) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1_024) { [weak self] data, _, complete, error in
            guard let self else { return }
            guard lock.withLock({ self.connection === connection && connectionOwner == owner }) else { return }
            if let data, !data.isEmpty {
                do {
                    for frame in try lock.withLock({ try appendSessionBytes(data) }) {
                        onFrame(TransportDelivery(owner: owner, result: .success(frame)))
                    }
                } catch {
                    onFrame(TransportDelivery(owner: owner, result: .failure(error)))
                    disconnect(connection)
                    return
                }
            }
            if let error {
                onFrame(TransportDelivery(
                    owner: owner,
                    result: .failure(TCPTransportError.connectionFailed(error.localizedDescription))
                ))
                disconnect(connection)
            } else if complete {
                onFrame(TransportDelivery(owner: owner, result: .failure(TCPTransportError.connectionClosed)))
                disconnect(connection)
            } else {
                receiveNext(on: connection, owner: owner)
            }
        }
    }

    private func waitUntilReady(_ connection: NWConnection, timeout: TimeInterval) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let gate = ContinuationGate()
            let timeoutWork = SendableWorkItem { [weak self, weak connection] in
                guard gate.claim() else { return }
                if let self, let connection { self.disconnect(connection) }
                continuation.resume(throwing: TCPTransportError.timedOut("建立 TCP 连接"))
            }
            let cancellation: @Sendable () -> Void = {
                guard gate.claim() else { return }
                timeoutWork.cancel()
                continuation.resume(throwing: CancellationError())
            }
            guard registerStartupCancellation(cancellation, for: connection) else {
                cancellation()
                return
            }
            connection.stateUpdateHandler = { [weak self, weak connection] state in
                switch state {
                case .ready:
                    guard gate.claim() else { return }
                    timeoutWork.cancel()
                    if let self, let connection { self.clearStartupCancellation(for: connection) }
                    continuation.resume()
                case let .failed(error):
                    guard gate.claim() else { return }
                    timeoutWork.cancel()
                    if let self, let connection { self.clearStartupCancellation(for: connection) }
                    continuation.resume(throwing: TCPTransportError.connectionFailed(error.localizedDescription))
                    if let self, let connection { self.disconnect(connection) }
                case .cancelled:
                    guard gate.claim() else { return }
                    timeoutWork.cancel()
                    if let self, let connection { self.clearStartupCancellation(for: connection) }
                    continuation.resume(throwing: TCPTransportError.connectionClosed)
                default:
                    break
                }
            }
            queue.asyncAfter(deadline: .now() + timeout, execute: timeoutWork.workItem)
            connection.start(queue: queue)
        }
    }

    private func registerStartupCancellation(
        _ cancellation: @escaping @Sendable () -> Void,
        for expected: NWConnection
    ) -> Bool {
        lock.withLock {
            guard connection === expected else { return false }
            startupCancellation = cancellation
            return true
        }
    }

    private func clearStartupCancellation(for expected: NWConnection) {
        lock.withLock {
            guard connection === expected else { return }
            startupCancellation = nil
        }
    }

    private func cancelStartup(for expected: NWConnection) {
        let cancellation = lock.withLock { () -> (@Sendable () -> Void)? in
            guard connection === expected else { return nil }
            defer { startupCancellation = nil }
            return startupCancellation
        }
        cancellation?()
    }

    private func sendRaw(
        _ data: Data,
        on connection: NWConnection,
        timeout: TimeInterval,
        stage: String
    ) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let gate = ContinuationGate()
            let timeoutWork = SendableWorkItem { [weak self, weak connection] in
                guard gate.claim() else { return }
                if let self, let connection { self.disconnect(connection) }
                continuation.resume(throwing: TCPTransportError.timedOut(stage))
            }
            queue.asyncAfter(deadline: .now() + timeout, execute: timeoutWork.workItem)
            connection.send(content: data, completion: .contentProcessed { error in
                guard gate.claim() else { return }
                timeoutWork.cancel()
                if let error {
                    continuation.resume(throwing: TCPTransportError.connectionFailed(error.localizedDescription))
                } else {
                    continuation.resume()
                }
            })
        }
    }

    private func sendSessionPayload(
        _ payload: Data,
        channel: LogicalChannel,
        on connection: NWConnection,
        timeout: TimeInterval,
        stage: String
    ) async throws {
        let data = try protectedSessionPayload(payload, channel: channel)
        try await sendRaw(data, on: connection, timeout: timeout, stage: stage)
    }

    private func readSessionPayload(
        from connection: NWConnection,
        plaintextByteCount: Int,
        timeout: TimeInterval,
        stage: String
    ) async throws -> Data {
        let protection = lock.withLock { lanRecordProtectionState }
        switch protection {
        case .encrypted:
            let prefix = try await readExactly(
                LANSecureRecordStreamFramer.lengthPrefixBytes,
                from: connection,
                timeout: timeout,
                stage: stage
            )
            let length = Int(prefix.reduce(UInt32.zero) { ($0 << 8) | UInt32($1) })
            guard length > 0, length <= LANSecureRecordStreamFramer.maximumRecordBytes else {
                throw LANSecureRecordError.invalidRecordLength
            }
            let record = try await readExactly(length, from: connection, timeout: timeout, stage: stage)
            return try lock.withLock {
                guard let session = lanRecordSession else { throw LANSecureRecordError.encryptionRequired }
                let opened = try session.openDeclaredChannel(record)
                guard opened.channel == .control else { throw LANSecureRecordError.recordOpenFailed }
                return opened.payload
            }
        case .explicitLegacyFallback, .notApplicable:
            return try await readExactly(plaintextByteCount, from: connection, timeout: timeout, stage: stage)
        case .negotiating:
            throw LANSecureRecordError.encryptionRequired
        }
    }

    private func protectedSessionPayload(_ payload: Data, channel: LogicalChannel) throws -> Data {
        try lock.withLock {
            switch lanRecordProtectionState {
            case .encrypted:
                guard let session = lanRecordSession else { throw LANSecureRecordError.encryptionRequired }
                return try LANSecureRecordStreamFramer.encode(try session.seal(payload, channel: channel))
            case .explicitLegacyFallback, .notApplicable:
                return payload
            case .negotiating:
                throw LANSecureRecordError.encryptionRequired
            }
        }
    }

    private func sessionBytes(for frame: TransportFrame) throws -> Data {
        let encoded = try frame.encoded()
        return try protectedSessionPayload(encoded, channel: frame.channel)
    }

    private func appendSessionBytes(_ bytes: Data) throws -> [TransportFrame] {
        switch lanRecordProtectionState {
        case .encrypted:
            guard let session = lanRecordSession else { throw LANSecureRecordError.encryptionRequired }
            let plaintextFrames = try lanRecordFramer.append(bytes) { record in
                try session.openDeclaredChannel(record)
            }
            var frames: [TransportFrame] = []
            for plaintext in plaintextFrames {
                let decodedFrames = try framer.append(plaintext.payload)
                guard decodedFrames.count == 1, decodedFrames[0].channel == plaintext.channel else {
                    throw LANSecureRecordError.recordOpenFailed
                }
                frames.append(decodedFrames[0])
            }
            return frames
        case .explicitLegacyFallback, .notApplicable:
            return try framer.append(bytes)
        case .negotiating:
            throw LANSecureRecordError.encryptionRequired
        }
    }

    private func readExactly(
        _ count: Int,
        from connection: NWConnection,
        timeout: TimeInterval,
        stage: String
    ) async throws -> Data {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Data, Error>) in
            let gate = ContinuationGate()
            let timeoutWork = SendableWorkItem { [weak self, weak connection] in
                guard gate.claim() else { return }
                if let self, let connection { self.disconnect(connection) }
                continuation.resume(throwing: TCPTransportError.timedOut(stage))
            }
            queue.asyncAfter(deadline: .now() + timeout, execute: timeoutWork.workItem)
            receiveExactly(count, from: connection) { data, error in
                guard gate.claim() else { return }
                timeoutWork.cancel()
                if let error {
                    continuation.resume(throwing: error)
                } else if let data {
                    continuation.resume(returning: data)
                } else {
                    continuation.resume(throwing: TCPTransportError.connectionClosed)
                }
            }
        }
    }

    private func receiveExactly(
        _ count: Int,
        from connection: NWConnection,
        accumulated: Data = Data(),
        completion: @escaping @Sendable (Data?, Error?) -> Void
    ) {
        guard accumulated.count < count else {
            completion(accumulated, nil)
            return
        }
        connection.receive(
            minimumIncompleteLength: 1,
            maximumLength: count - accumulated.count
        ) { [weak self, weak connection] data, _, complete, error in
            guard let self, let connection else {
                completion(nil, TCPTransportError.connectionClosed)
                return
            }
            if let error {
                completion(nil, TCPTransportError.connectionFailed(error.localizedDescription))
                return
            }
            var next = accumulated
            if let data { next.append(data) }
            if next.count == count {
                completion(next, nil)
            } else if complete || data?.isEmpty != false {
                completion(nil, TCPTransportError.connectionClosed)
            } else {
                self.receiveExactly(count, from: connection, accumulated: next, completion: completion)
            }
        }
    }

    private func disconnect(_ expected: NWConnection) {
        let snapshot = lock.withLock { () -> (NWConnection?, (@Sendable () -> Void)?) in
            guard self.connection === expected else { return (nil, nil) }
            self.connection = nil
            connectionOwner = nil
            let cancellation = startupCancellation
            startupCancellation = nil
            framer = TransportFramer()
            lanRecordSession?.close()
            lanRecordSession = nil
            lanRecordProtectionState = .notApplicable
            lanRecordFramer = LANSecureRecordStreamFramer()
            return (expected, cancellation)
        }
        snapshot.1?()
        snapshot.0?.stateUpdateHandler = nil
        snapshot.0?.cancel()
    }
}

private final class ContinuationGate: @unchecked Sendable {
    private let lock = NSLock()
    private var claimed = false

    func claim() -> Bool {
        lock.withLock {
            guard !claimed else { return false }
            claimed = true
            return true
        }
    }
}

private final class SendableWorkItem: @unchecked Sendable {
    let workItem: DispatchWorkItem

    init(operation: @escaping @Sendable () -> Void) {
        workItem = DispatchWorkItem(block: operation)
    }

    func cancel() {
        workItem.cancel()
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
