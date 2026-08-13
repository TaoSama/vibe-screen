import Foundation

public struct ReconnectSchedule: Equatable, Sendable {
    public let generation: UInt64
    public let attempt: Int
    public let delaySeconds: Double
}

public struct ReconnectCoordinator: Sendable {
    private let backoff: ReconnectBackoff
    private var generation: UInt64 = 0
    private var nextAttempt = 0
    private var enabled = false

    public init(backoff: ReconnectBackoff = ReconnectBackoff()) {
        self.backoff = backoff
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

    public mutating func schedule(generation candidate: UInt64) -> ReconnectSchedule? {
        guard accepts(generation: candidate) else { return nil }
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
