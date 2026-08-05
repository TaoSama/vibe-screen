import Foundation
import VibeScreenProtocol

public enum ControlOutboxError: Error, LocalizedError, Sendable {
    case inactive
    case sessionOwnerMismatch
    case connectionOwnerMismatch
    case superseded
    case sendFailed(String)
    case cancelled

    public var errorDescription: String? {
        switch self {
        case .inactive:
            "控制消息发送队列尚未激活"
        case .sessionOwnerMismatch:
            "控制消息属于过期会话"
        case .connectionOwnerMismatch:
            "控制消息属于过期连接"
        case .superseded:
            "控制消息因连接或会话切代而丢弃"
        case .sendFailed(let reason):
            "控制消息发送失败：\(reason)"
        case .cancelled:
            "控制消息发送已取消"
        }
    }
}

public struct ControlOutboxFailure: Sendable {
    public let owner: SessionOwner
    public let messageID: UInt64
    public let error: ControlOutboxError
}

private final class ControlSendCompletion: @unchecked Sendable {
    private let lock = NSLock()
    private var result: Result<UInt64, ControlOutboxError>?
    private var waiters: [CheckedContinuation<UInt64, Error>] = []

    func wait() async throws -> UInt64 {
        try await withCheckedThrowingContinuation { continuation in
            lock.lock()
            if let result {
                lock.unlock()
                continuation.resume(with: result.mapError { $0 as Error })
            } else {
                waiters.append(continuation)
                lock.unlock()
            }
        }
    }

    func finish(_ result: Result<UInt64, ControlOutboxError>) {
        lock.lock()
        guard self.result == nil else {
            lock.unlock()
            return
        }
        self.result = result
        let waiters = self.waiters
        self.waiters.removeAll(keepingCapacity: false)
        lock.unlock()
        for waiter in waiters {
            waiter.resume(with: result.mapError { $0 as Error })
        }
    }
}

public struct ControlSendTicket: Sendable {
    public let messageID: UInt64
    private let completion: ControlSendCompletion
    private let cancelRequest: @Sendable () -> Void

    fileprivate init(
        messageID: UInt64,
        completion: ControlSendCompletion,
        cancelRequest: @escaping @Sendable () -> Void
    ) {
        self.messageID = messageID
        self.completion = completion
        self.cancelRequest = cancelRequest
    }

    @discardableResult
    public func wait() async throws -> UInt64 {
        try await withTaskCancellationHandler {
            try await completion.wait()
        } onCancel: {
            cancelRequest()
        }
    }
}

/// The single serialization domain for all outbound Protocol v1 control messages.
///
/// Callers must enter this MainActor-isolated API before allocating a message ID.
/// The outbox deliberately owns `EnvelopeFactory`, so independently scheduled
/// producers cannot allocate IDs in one order and reach the TCP connection in
/// another order.
@MainActor
public final class ControlOutbox {
    public typealias Sender = @Sendable (
        _ owner: ConnectionOwner,
        _ frame: TransportFrame,
        _ timeout: TimeInterval
    ) async throws -> Void

    public typealias FailureHandler = @MainActor @Sendable (ControlOutboxFailure) -> Void

    private struct Activation: Equatable {
        let token: UUID
        let owner: SessionOwner
    }

    private final class PendingSend {
        let requestID: UUID
        let activation: Activation
        let messageID: UInt64
        let frame: TransportFrame
        let timeout: TimeInterval
        let completion: ControlSendCompletion

        init(
            requestID: UUID,
            activation: Activation,
            messageID: UInt64,
            frame: TransportFrame,
            timeout: TimeInterval,
            completion: ControlSendCompletion
        ) {
            self.requestID = requestID
            self.activation = activation
            self.messageID = messageID
            self.frame = frame
            self.timeout = timeout
            self.completion = completion
        }

        func finish(_ result: Result<UInt64, ControlOutboxError>) {
            completion.finish(result)
        }
    }

    private static let minimumTimeout: TimeInterval = 0.001

    private let sender: Sender
    private let onFailure: FailureHandler
    private var activation: Activation?
    private var envelopeFactory: EnvelopeFactory?
    private var pending: [PendingSend] = []
    private var pendingHead = 0
    private var inFlight: PendingSend?
    private var drainTask: Task<Void, Never>?

    public init(
        sender: @escaping Sender,
        onFailure: @escaping FailureHandler = { _ in }
    ) {
        self.sender = sender
        self.onFailure = onFailure
    }

    public var activeOwner: SessionOwner? {
        activation?.owner
    }

    public func activate(
        owner: SessionOwner,
        firstMessageID: UInt64 = 1
    ) {
        replaceActivation(with: Activation(
            token: UUID(),
            owner: owner
        ))
        envelopeFactory = EnvelopeFactory(firstMessageID: firstMessageID)
    }

    public func rotate(
        owner: SessionOwner,
        firstMessageID: UInt64 = 1
    ) {
        activate(
            owner: owner,
            firstMessageID: firstMessageID
        )
    }

    public func deactivate() {
        replaceActivation(with: nil)
    }

    @discardableResult
    public func enqueue(
        owner: SessionOwner,
        timeout: TimeInterval = 3,
        build: (inout EnvelopeFactory) throws -> VSEnvelope
    ) throws -> ControlSendTicket {
        let requestID = UUID()
        let item = try enqueueInternal(
            requestID: requestID,
            owner: owner,
            timeout: timeout,
            build: build
        )
        return ControlSendTicket(
            messageID: item.messageID,
            completion: item.completion,
            cancelRequest: { [weak self] in
                Task { @MainActor in self?.cancel(requestID: requestID) }
            }
        )
    }

    @discardableResult
    public func sendAndWait(
        owner: SessionOwner,
        timeout: TimeInterval = 3,
        build: (inout EnvelopeFactory) throws -> VSEnvelope
    ) async throws -> UInt64 {
        let ticket = try enqueue(owner: owner, timeout: timeout, build: build)
        return try await ticket.wait()
    }

    private func enqueueInternal(
        requestID: UUID,
        owner: SessionOwner,
        timeout: TimeInterval,
        build: (inout EnvelopeFactory) throws -> VSEnvelope
    ) throws -> PendingSend {
        guard let activation, var factory = envelopeFactory else {
            throw ControlOutboxError.inactive
        }
        guard activation.owner == owner else {
            if activation.owner.connectionOwner != owner.connectionOwner {
                throw ControlOutboxError.connectionOwnerMismatch
            }
            throw ControlOutboxError.sessionOwnerMismatch
        }

        let envelope = try build(&factory)
        let payload = try EnvelopeCodec.serialize(envelope)
        let frame = TransportFrame(channel: .control, payload: payload)
        _ = try frame.encoded()
        envelopeFactory = factory

        let item = PendingSend(
            requestID: requestID,
            activation: activation,
            messageID: envelope.messageID,
            frame: frame,
            timeout: Self.normalizedTimeout(timeout),
            completion: ControlSendCompletion()
        )
        pending.append(item)
        startDrain(for: activation)
        return item
    }

    private func startDrain(for activation: Activation) {
        guard drainTask == nil else { return }
        drainTask = Task { [weak self] in
            await self?.drain(activation: activation)
        }
    }

    private func drain(activation expectedActivation: Activation) async {
        defer { finishDrain(expectedActivation) }
        while activation == expectedActivation, !Task.isCancelled {
            guard pendingHead < pending.count else {
                pending.removeAll(keepingCapacity: true)
                pendingHead = 0
                return
            }

            let item = pending[pendingHead]
            pendingHead += 1
            guard item.activation == expectedActivation else {
                item.finish(.failure(ControlOutboxError.superseded))
                continue
            }
            inFlight = item

            do {
                try Task.checkCancellation()
                try await sender(item.activation.owner.connectionOwner, item.frame, item.timeout)
                try Task.checkCancellation()
            } catch {
                guard activation == expectedActivation else { return }
                let sendError = ControlOutboxError.sendFailed(error.localizedDescription)
                item.finish(.failure(sendError))
                inFlight = nil
                failCurrentActivation(expectedActivation, error: sendError, failedMessageID: item.messageID)
                return
            }

            guard activation == expectedActivation else { return }
            inFlight = nil
            item.finish(.success(item.messageID))
            compactPendingStorageIfNeeded()
        }
    }

    private func replaceActivation(with replacement: Activation?) {
        drainTask?.cancel()
        let superseded = ControlOutboxError.superseded
        inFlight?.finish(.failure(superseded))
        inFlight = nil
        for item in pending.dropFirst(pendingHead) {
            item.finish(.failure(superseded))
        }
        pending.removeAll(keepingCapacity: true)
        pendingHead = 0
        activation = replacement
        envelopeFactory = nil
    }

    private func failCurrentActivation(
        _ failedActivation: Activation,
        error: ControlOutboxError,
        failedMessageID: UInt64
    ) {
        guard activation == failedActivation else { return }
        for item in pending.dropFirst(pendingHead) {
            item.finish(.failure(error))
        }
        pending.removeAll(keepingCapacity: true)
        pendingHead = 0
        activation = nil
        envelopeFactory = nil
        onFailure(ControlOutboxFailure(
            owner: failedActivation.owner,
            messageID: failedMessageID,
            error: error
        ))
    }

    private func cancel(requestID: UUID) {
        if let inFlight, inFlight.requestID == requestID {
            inFlight.finish(.failure(ControlOutboxError.cancelled))
            return
        }
        guard let index = pending[pendingHead...].firstIndex(where: { $0.requestID == requestID }) else {
            return
        }
        pending[index].finish(.failure(ControlOutboxError.cancelled))
        pending.remove(at: index)
    }

    private func compactPendingStorageIfNeeded() {
        guard pendingHead >= 64, pendingHead * 2 >= pending.count else { return }
        pending.removeFirst(pendingHead)
        pendingHead = 0
    }

    /// A cancelled `NWConnection.send` may still complete later. Keep the old
    /// drain as the lane owner until that await returns; only then may a
    /// replacement activation begin sending, including on the same TCP owner.
    private func finishDrain(_ finishedActivation: Activation) {
        drainTask = nil
        guard let activation, activation != finishedActivation,
              pendingHead < pending.count else { return }
        startDrain(for: activation)
    }

    private static func normalizedTimeout(_ timeout: TimeInterval) -> TimeInterval {
        guard timeout.isFinite else { return minimumTimeout }
        return max(timeout, minimumTimeout)
    }
}
