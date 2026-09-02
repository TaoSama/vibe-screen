import Foundation

struct BoundedSessionEpochLog {
    static let defaultCapacity = 8

    private let capacity: Int
    private var epochs: [UInt64] = []
    private var epochSet: Set<UInt64> = []

    init(capacity: Int = Self.defaultCapacity) {
        precondition(capacity > 0)
        self.capacity = capacity
    }

    var count: Int { epochSet.count }

    mutating func insertIfNew(_ epoch: UInt64) -> Bool {
        guard !epochSet.contains(epoch) else { return false }

        epochs.append(epoch)
        epochSet.insert(epoch)

        while epochs.count > capacity {
            let removed = epochs.removeFirst()
            epochSet.remove(removed)
        }

        return true
    }

    mutating func removeAll() {
        epochs.removeAll(keepingCapacity: true)
        epochSet.removeAll(keepingCapacity: true)
    }
}

final class CaptureAsyncWorkGate: @unchecked Sendable {
    struct Token: Equatable {
        fileprivate let generation: UInt64
    }

    private struct State {
        var generation: UInt64 = 0
        var activeHealthCheckGeneration: UInt64?
        var activeWorkCount = 0
        var isInvalidating = false
    }

    private let condition = NSCondition()
    private var state = State()

    var currentToken: Token {
        condition.lock()
        while state.isInvalidating {
            condition.wait()
        }
        let token = Token(generation: state.generation)
        condition.unlock()
        return token
    }

    @discardableResult
    func invalidate() -> Token {
        invalidate { () }.token
    }

    /// Advances the generation and runs teardown while new work is paused.
    /// The teardown closure must not call back into this gate.
    @discardableResult
    func invalidate<T>(_ work: () throws -> T) rethrows -> (token: Token, value: T) {
        condition.lock()
        while state.isInvalidating {
            condition.wait()
        }
        state.generation &+= 1
        state.activeHealthCheckGeneration = nil
        state.isInvalidating = true
        let token = Token(generation: state.generation)
        while state.activeWorkCount > 0 {
            condition.wait()
        }
        condition.unlock()

        defer { finishInvalidation() }
        return (token, try work())
    }

    @discardableResult
    func invalidateIfCurrent<T>(
        _ token: Token,
        _ work: () throws -> T
    ) rethrows -> (token: Token, value: T)? {
        condition.lock()
        guard !state.isInvalidating, state.generation == token.generation else {
            condition.unlock()
            return nil
        }
        state.generation &+= 1
        state.activeHealthCheckGeneration = nil
        state.isInvalidating = true
        let nextToken = Token(generation: state.generation)
        while state.activeWorkCount > 0 {
            condition.wait()
        }
        condition.unlock()

        defer { finishInvalidation() }
        return (nextToken, try work())
    }

    @discardableResult
    func performIfCurrent<T>(_ token: Token, _ work: () throws -> T) rethrows -> T? {
        condition.lock()
        guard !state.isInvalidating, state.generation == token.generation else {
            condition.unlock()
            return nil
        }
        state.activeWorkCount += 1
        condition.unlock()

        defer {
            condition.lock()
            state.activeWorkCount -= 1
            if state.activeWorkCount == 0 {
                condition.broadcast()
            }
            condition.unlock()
        }

        return try work()
    }

    @discardableResult
    func performHealthCheckCompletion<T>(
        _ token: Token,
        _ work: () throws -> T
    ) rethrows -> T? {
        condition.lock()
        guard !state.isInvalidating,
              state.activeHealthCheckGeneration == token.generation,
              state.generation == token.generation else {
            if state.activeHealthCheckGeneration == token.generation {
                state.activeHealthCheckGeneration = nil
            }
            condition.unlock()
            return nil
        }
        state.activeHealthCheckGeneration = nil
        state.activeWorkCount += 1
        condition.unlock()

        defer {
            condition.lock()
            state.activeWorkCount -= 1
            if state.activeWorkCount == 0 {
                condition.broadcast()
            }
            condition.unlock()
        }

        return try work()
    }

    func beginHealthCheck() -> Token? {
        condition.withLock {
            guard !state.isInvalidating,
                  state.activeHealthCheckGeneration == nil else { return nil }
            state.activeHealthCheckGeneration = state.generation
            return Token(generation: state.generation)
        }
    }

    var hasActiveHealthCheck: Bool {
        condition.withLock { state.activeHealthCheckGeneration != nil }
    }

    private func finishInvalidation() {
        condition.lock()
        state.isInvalidating = false
        condition.broadcast()
        condition.unlock()
    }
}

private extension NSCondition {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
