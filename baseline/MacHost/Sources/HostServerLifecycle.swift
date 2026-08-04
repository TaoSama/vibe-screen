import Foundation

@MainActor
final class HostServerLifecycle {
    enum State: Equatable {
        case idle
        case starting(UInt64)
        case running(UInt64)
        case stopping(UInt64)
    }

    private(set) var state: State = .idle
    private var generation: UInt64 = 0
    private var latestClientGeneration: [UInt64: UInt64] = [:]

    var canStart: Bool { state == .idle }

    func beginStart() -> UInt64? {
        guard state == .idle else { return nil }
        generation &+= 1
        state = .starting(generation)
        return generation
    }

    func isCurrentStart(_ token: UInt64) -> Bool {
        state == .starting(token)
    }

    func ownsSession(_ token: UInt64) -> Bool {
        state == .starting(token) || state == .running(token)
    }

    func acceptsCallback(
        _ token: UInt64,
        sourceMatches: Bool,
        clientGeneration: UInt64
    ) -> Bool {
        guard ownsSession(token), sourceMatches else { return false }
        let latest = latestClientGeneration[token] ?? 0
        guard clientGeneration >= latest else { return false }
        latestClientGeneration[token] = clientGeneration
        return true
    }

    func finishStart(_ token: UInt64) -> Bool {
        guard isCurrentStart(token) else { return false }
        state = .running(token)
        return true
    }

    func failStart(_ token: UInt64) {
        guard isCurrentStart(token) else { return }
        state = .idle
    }

    func beginStop() -> UInt64 {
        generation &+= 1
        state = .stopping(generation)
        return generation
    }

    func finishStop(_ token: UInt64) {
        guard state == .stopping(token) else { return }
        state = .idle
        latestClientGeneration.removeAll()
    }
}
