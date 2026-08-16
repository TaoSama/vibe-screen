import Foundation

public struct ReconnectSchedule: Equatable, Sendable {
    public let generation: UInt64
    public let attempt: Int
    public let delaySeconds: Double
}

public enum ReconnectFailure: Equatable, Sendable {
    case transientTransport
    case heartbeat
    case permanent

    public var isRetryable: Bool { self != .permanent }

    public static func classify(_ error: Error) -> ReconnectFailure {
        if let transportError = error as? TCPTransportError {
            switch transportError {
            case .notConnected, .connectionFailed, .connectionClosed, .timedOut:
                return .transientTransport
            case .invalidPort, .authenticationRequired:
                return .permanent
            }
        }
        if let outboxError = error as? ControlOutboxError,
           case .sendFailed = outboxError {
            return .transientTransport
        }
        if let heartbeatError = error as? HeartbeatMonitorError,
           heartbeatError == .timedOut {
            return .heartbeat
        }
        return .permanent
    }
}

public struct ReconnectCoordinator: Sendable {
    private let backoff: ReconnectBackoff
    private var generation: UInt64 = 0
    private var nextAttempt = 0
    private var enabled = false
    public let maximumAttempts: Int

    public init(
        backoff: ReconnectBackoff = ReconnectBackoff(),
        maximumAttempts: Int = 5
    ) {
        self.backoff = backoff
        self.maximumAttempts = max(0, maximumAttempts)
    }

    public mutating func start() -> UInt64 {
        generation &+= 1
        nextAttempt = 0
        enabled = true
        return generation
    }

    public mutating func stop() {
        generation &+= 1
        nextAttempt = 0
        enabled = false
    }

    public func accepts(generation candidate: UInt64) -> Bool {
        enabled && candidate == generation
    }

    public mutating func schedule(
        generation candidate: UInt64,
        failure: ReconnectFailure
    ) -> ReconnectSchedule? {
        guard accepts(generation: candidate) else { return nil }
        guard failure.isRetryable, nextAttempt < maximumAttempts else {
            enabled = false
            return nil
        }
        let attempt = nextAttempt
        nextAttempt += 1
        return ReconnectSchedule(
            generation: candidate,
            attempt: attempt,
            delaySeconds: backoff.delaySeconds(forAttempt: attempt)
        )
    }

    public mutating func markConnected(generation candidate: UInt64) {
        guard accepts(generation: candidate) else { return }
        nextAttempt = 0
    }
}
