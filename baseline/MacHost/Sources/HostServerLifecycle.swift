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
    var isStopping: Bool {
        if case .stopping = state { return true }
        return false
    }

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

@MainActor
final class HostReconfigurationCoordinator<Configuration: Equatable> {
    typealias StopOperation = @MainActor () async -> Void
    typealias StartOperation = @MainActor (
        Configuration,
        @escaping @MainActor () -> Bool
    ) async -> Bool
    typealias SleepOperation = @MainActor (UInt64) async -> Void

    private let debounceNanoseconds: UInt64
    private let stopOperation: StopOperation
    private let startOperation: StartOperation
    private let sleepOperation: SleepOperation
    private var appliedConfiguration: Configuration?
    private var latestIntent: Configuration?
    private var worker: Task<Void, Never>?
    private var intentGeneration: UInt64 = 0
    private var acceptsRequests = false

    var acceptsRuntimeChanges: Bool {
        acceptsRequests && (appliedConfiguration != nil || worker != nil)
    }

    var hasPendingReconfiguration: Bool {
        acceptsRequests && worker != nil
    }

    var hasDesiredRunning: Bool {
        acceptsRequests && (latestIntent != nil || appliedConfiguration != nil || worker != nil)
    }

    init(
        debounceNanoseconds: UInt64,
        stop: @escaping StopOperation,
        start: @escaping StartOperation,
        sleep: @escaping SleepOperation = { nanoseconds in
            try? await Task.sleep(nanoseconds: nanoseconds)
        }
    ) {
        self.debounceNanoseconds = debounceNanoseconds
        self.stopOperation = stop
        self.startOperation = start
        self.sleepOperation = sleep
    }

    func recordApplied(_ configuration: Configuration?) {
        appliedConfiguration = configuration
        acceptsRequests = configuration != nil
    }

    func recordManualStop() {
        acceptsRequests = false
        intentGeneration &+= 1
        latestIntent = nil
        appliedConfiguration = nil
        worker?.cancel()
    }

    func requestStart(_ configuration: Configuration) {
        acceptsRequests = true
        request(configuration)
    }

    func updateIntent(_ transform: (Configuration) -> Configuration) {
        guard acceptsRequests,
              let base = latestIntent ?? appliedConfiguration else { return }
        request(transform(base))
    }

    func refreshIntentGeneration() {
        guard acceptsRequests,
              let base = latestIntent ?? appliedConfiguration else { return }
        request(base)
    }

    func request(_ configuration: Configuration) {
        guard acceptsRequests else { return }
        intentGeneration &+= 1
        latestIntent = configuration
        guard worker == nil else { return }
        worker = Task { [weak self] in
            await self?.applyLatestIntent()
        }
    }

    func waitUntilIdleForTesting() async {
        while let worker {
            await worker.value
        }
    }

    private func applyLatestIntent() async {
        defer {
            worker = nil
            if let latestIntent, latestIntent != appliedConfiguration {
                request(latestIntent)
            }
        }

        while true {
            guard let settled = await settledIntent() else { return }
            guard settled.configuration != appliedConfiguration else {
                latestIntent = nil
                return
            }

            if appliedConfiguration != nil {
                await stopOperation()
                appliedConfiguration = nil
            }

            // Teardown can suspend for ScreenCaptureKit. Wait for a complete
            // trailing-edge quiet window afterward so changes made while the
            // old stream stops cannot start an intermediate configuration.
            guard let finalIntent = await settledIntent() else { return }
            let started = await startOperation(
                finalIntent.configuration,
                { [weak self] in
                    guard let self else { return false }
                    return self.intentGeneration == finalIntent.generation
                        && self.latestIntent == finalIntent.configuration
                }
            )
            let remainedCurrent = intentGeneration == finalIntent.generation
                && latestIntent == finalIntent.configuration
            if started && remainedCurrent {
                appliedConfiguration = finalIntent.configuration
                latestIntent = nil
                return
            }

            if started {
                await stopOperation()
            }
            appliedConfiguration = nil
            if remainedCurrent {
                latestIntent = nil
                return
            }
        }
    }

    private func settledIntent() async -> (
        configuration: Configuration,
        generation: UInt64
    )? {
        while let configuration = latestIntent {
            let generation = intentGeneration
            await sleepOperation(debounceNanoseconds)
            guard !Task.isCancelled else { return nil }
            if generation == intentGeneration,
               latestIntent == configuration {
                return (configuration, generation)
            }
        }
        return nil
    }
}

@MainActor
enum HostTeardownOrdering {
    static func perform(
        stopListener: () -> Void,
        stopCapture: () async -> Void,
        destroyDisplay: () -> Void
    ) async {
        stopListener()
        await stopCapture()
        destroyDisplay()
    }
}

@MainActor
final class HostStopOperationCoordinator {
    struct Result: Equatable {
        let generation: UInt64
        let performedOperation: Bool
    }

    typealias AfterReleaseHook = @MainActor () async -> Void

    private var operationTask: Task<Void, Never>?
    private var operationGeneration: UInt64 = 0
    private let afterReleaseHook: AfterReleaseHook?

    init(afterReleaseHook: AfterReleaseHook? = nil) {
        self.afterReleaseHook = afterReleaseHook
    }

    @discardableResult
    func perform(
        _ operation: @escaping @MainActor () async -> Void,
        finalize: @escaping @MainActor (UInt64) -> Void = { _ in }
    ) async -> Result {
        if let operationTask {
            let generation = operationGeneration
            await operationTask.value
            return Result(generation: generation, performedOperation: false)
        }

        operationGeneration &+= 1
        let generation = operationGeneration
        let task = Task { @MainActor [weak self] in
            await operation()
            guard let self else { return }
            finalize(generation)
            if self.operationGeneration == generation {
                self.operationTask = nil
            }
            await self.afterReleaseHook?()
        }
        operationTask = task
        await task.value
        return Result(generation: generation, performedOperation: true)
    }
}

@MainActor
final class HostTerminationCoordinator {
    enum Decision: Equatable {
        case beginDeferredCleanup
        case waitForDeferredCleanup
        case terminateNow
    }

    private enum State {
        case idle
        case cleaningUp
        case readyToTerminate
    }

    private var state: State = .idle

    func requestTermination() -> Decision {
        switch state {
        case .idle:
            state = .cleaningUp
            return .beginDeferredCleanup
        case .cleaningUp:
            return .waitForDeferredCleanup
        case .readyToTerminate:
            return .terminateNow
        }
    }

    func completeCleanup() {
        guard state == .cleaningUp else { return }
        state = .readyToTerminate
    }
}

@MainActor
final class StopRecoveryPreservationAccumulator {
    private var pending = false

    func request(preserveRecoveryState: Bool) {
        pending = pending || preserveRecoveryState
    }

    func consume() -> Bool {
        let result = pending
        pending = false
        return result
    }
}

@MainActor
final class StopFollowUpSuppressionAccumulator {
    private var pending = false

    func request(suppressFollowUp: Bool) {
        pending = pending || suppressFollowUp
    }

    func consume() -> Bool {
        let result = pending
        pending = false
        return result
    }
}

enum HostStopFollowUpPolicy {
    static func shouldApply(
        performedOperation: Bool,
        requestedGeneration: UInt64,
        lastCompletedGeneration: UInt64,
        lifecycleIsIdle: Bool,
        hasActiveConfiguration: Bool,
        hasDesiredRunning: Bool,
        followUpWasSuppressed: Bool,
        permitsDesiredRunning: Bool = false
    ) -> Bool {
        performedOperation
            && !followUpWasSuppressed
            && requestedGeneration == lastCompletedGeneration
            && lifecycleIsIdle
            && !hasActiveConfiguration
            && (permitsDesiredRunning || !hasDesiredRunning)
    }
}

final class AsyncStopBarrier: @unchecked Sendable {
    private final class Entry: @unchecked Sendable {
        let task: Task<Void, Never>

        init(task: Task<Void, Never>) {
            self.task = task
        }
    }

    private let lock = NSLock()
    private var current: Entry?

    func enqueue(_ operation: @escaping @Sendable () async -> Void) {
        lock.lock()
        let preceding = current
        let entry = Entry(task: Task {
            await preceding?.task.value
            await operation()
        })
        current = entry
        lock.unlock()
    }

    func waitForAll() async {
        while true {
            let captured = lock.withLock { current }
            guard let captured else { return }
            await captured.task.value
            lock.withLock {
                if current === captured {
                    current = nil
                }
            }
        }
    }
}
