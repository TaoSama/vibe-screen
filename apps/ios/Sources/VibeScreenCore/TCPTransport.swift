import Foundation
import Network

public enum TCPTransportError: Error, LocalizedError {
    case invalidPort(UInt16)
    case notConnected
    case connectionFailed(String)
    case connectionClosed

    public var errorDescription: String? {
        switch self {
        case let .invalidPort(port): "无效端口：\(port)"
        case .notConnected: "尚未连接主机"
        case let .connectionFailed(reason): "连接失败：\(reason)"
        case .connectionClosed: "主机已断开连接"
        }
    }
}

public final class TCPTransport: @unchecked Sendable {
    public typealias FrameHandler = @Sendable (Result<TransportFrame, Error>) -> Void

    private let queue = DispatchQueue(label: "dev.vibescreen.ios.transport", qos: .userInteractive)
    private let lock = NSLock()
    private var connection: NWConnection?
    private var framer = TransportFramer()
    private let onFrame: FrameHandler

    public init(onFrame: @escaping FrameHandler) {
        self.onFrame = onFrame
    }

    public func connect(host: String, port: UInt16) async throws {
        guard let networkPort = NWEndpoint.Port(rawValue: port) else {
            throw TCPTransportError.invalidPort(port)
        }
        disconnect()
        let connection = NWConnection(host: NWEndpoint.Host(host), port: networkPort, using: .tcp)
        lock.withLock {
            self.connection = connection
            framer = TransportFramer()
        }

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let gate = ContinuationGate()
            connection.stateUpdateHandler = { [weak self] state in
                switch state {
                case .ready:
                    guard gate.claim() else { return }
                    continuation.resume()
                    self?.receiveNext(on: connection)
                case let .failed(error):
                    guard gate.claim() else { return }
                    continuation.resume(throwing: TCPTransportError.connectionFailed(error.localizedDescription))
                    self?.disconnect(connection)
                case .cancelled:
                    guard gate.claim() else { return }
                    continuation.resume(throwing: TCPTransportError.connectionClosed)
                default:
                    break
                }
            }
            connection.start(queue: queue)
        }
    }

    public func send(_ frame: TransportFrame) async throws {
        let data = try frame.encoded()
        let connection = lock.withLock { self.connection }
        guard let connection else { throw TCPTransportError.notConnected }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connection.send(content: data, completion: .contentProcessed { error in
                if let error {
                    continuation.resume(throwing: TCPTransportError.connectionFailed(error.localizedDescription))
                } else {
                    continuation.resume()
                }
            })
        }
    }

    public func disconnect() {
        let connection = lock.withLock { () -> NWConnection? in
            defer { self.connection = nil }
            framer = TransportFramer()
            return self.connection
        }
        connection?.stateUpdateHandler = nil
        connection?.cancel()
    }

    private func receiveNext(on connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1_024) { [weak self] data, _, complete, error in
            guard let self else { return }
            guard lock.withLock({ self.connection === connection }) else { return }
            if let data, !data.isEmpty {
                do {
                    for frame in try lock.withLock({ try framer.append(data) }) {
                        onFrame(.success(frame))
                    }
                } catch {
                    onFrame(.failure(error))
                    disconnect(connection)
                    return
                }
            }
            if let error {
                onFrame(.failure(TCPTransportError.connectionFailed(error.localizedDescription)))
                disconnect(connection)
            } else if complete {
                onFrame(.failure(TCPTransportError.connectionClosed))
                disconnect(connection)
            } else {
                receiveNext(on: connection)
            }
        }
    }

    private func disconnect(_ expected: NWConnection) {
        let connection = lock.withLock { () -> NWConnection? in
            guard self.connection === expected else { return nil }
            self.connection = nil
            framer = TransportFramer()
            return expected
        }
        connection?.stateUpdateHandler = nil
        connection?.cancel()
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

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
