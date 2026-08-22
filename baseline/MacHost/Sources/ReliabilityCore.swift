import Foundation

enum LatestFrameQueueError: Error, Equatable {
    case invalidCapacity(Int)
}

struct LatestFrameEnqueueResult: Equatable {
    let accepted: Bool
    let droppedCount: Int
    let requiresKeyframe: Bool
}

/// A bounded queue for encoded video. It never retains a dependent frame after
/// dropping another dependent frame from the same prediction chain.
struct LatestFrameQueue<Element> {
    let capacity: Int
    private let isKeyframe: (Element) -> Bool
    private(set) var requiresKeyframe: Bool
    private var elements: [Element] = []

    init(
        capacity: Int,
        requiresKeyframe: Bool = true,
        isKeyframe: @escaping (Element) -> Bool
    ) throws {
        guard (1...2).contains(capacity) else {
            throw LatestFrameQueueError.invalidCapacity(capacity)
        }
        self.capacity = capacity
        self.requiresKeyframe = requiresKeyframe
        self.isKeyframe = isKeyframe
    }

    var count: Int { elements.count }

    mutating func enqueue(_ element: Element) -> LatestFrameEnqueueResult {
        let incomingIsKeyframe = isKeyframe(element)
        if requiresKeyframe && !incomingIsKeyframe {
            return LatestFrameEnqueueResult(
                accepted: false,
                droppedCount: 1,
                requiresKeyframe: true
            )
        }

        if incomingIsKeyframe {
            let dropped = elements.count
            elements = [element]
            requiresKeyframe = false
            return LatestFrameEnqueueResult(
                accepted: true,
                droppedCount: dropped,
                requiresKeyframe: false
            )
        }

        guard elements.count < capacity else {
            if elements.contains(where: isKeyframe) {
                return LatestFrameEnqueueResult(
                    accepted: false,
                    droppedCount: 1,
                    requiresKeyframe: false
                )
            }

            let dropped = elements.count + 1
            elements.removeAll(keepingCapacity: true)
            requiresKeyframe = true
            return LatestFrameEnqueueResult(
                accepted: false,
                droppedCount: dropped,
                requiresKeyframe: true
            )
        }

        elements.append(element)
        return LatestFrameEnqueueResult(
            accepted: true,
            droppedCount: 0,
            requiresKeyframe: false
        )
    }

    mutating func dequeue() -> Element? {
        guard !elements.isEmpty else { return nil }
        return elements.removeFirst()
    }

    mutating func reset(requiresKeyframe: Bool = true) -> Int {
        let dropped = elements.count
        elements.removeAll(keepingCapacity: true)
        self.requiresKeyframe = requiresKeyframe
        return dropped
    }
}

enum SessionEpochError: Error, Equatable {
    case nonIncreasingEpoch(current: UInt64, proposed: UInt64)
    case exhausted
}

final class SessionEpochGate {
    private let lock = NSLock()
    private var activeEpoch: UInt64 = 0

    var current: UInt64 {
        lock.withLock { activeEpoch }
    }

    @discardableResult
    func beginNextSession() throws -> UInt64 {
        try lock.withLock {
            guard activeEpoch < UInt64.max else {
                throw SessionEpochError.exhausted
            }
            activeEpoch += 1
            return activeEpoch
        }
    }

    func activate(_ epoch: UInt64) throws {
        try lock.withLock {
            guard epoch > activeEpoch else {
                throw SessionEpochError.nonIncreasingEpoch(
                    current: activeEpoch,
                    proposed: epoch
                )
            }
            activeEpoch = epoch
        }
    }

    func accepts(_ epoch: UInt64) -> Bool {
        lock.withLock { epoch != 0 && epoch == activeEpoch }
    }
}

struct ReconnectBackoff: Equatable {
    let initialDelayNs: UInt64
    let maximumDelayNs: UInt64
    private(set) var attempt = 0

    init(initialDelayNs: UInt64 = 250_000_000, maximumDelayNs: UInt64 = 3_000_000_000) {
        precondition(initialDelayNs > 0)
        precondition(maximumDelayNs >= initialDelayNs)
        self.initialDelayNs = initialDelayNs
        self.maximumDelayNs = maximumDelayNs
    }

    mutating func nextDelayNs() -> UInt64 {
        let exponent = min(attempt, 62)
        let multiplier = UInt64(1) << UInt64(exponent)
        let multiplied = initialDelayNs.multipliedReportingOverflow(by: multiplier)
        let delay = multiplied.overflow ? maximumDelayNs : min(multiplied.partialValue, maximumDelayNs)
        if attempt < Int.max {
            attempt += 1
        }
        return delay
    }

    mutating func reset() {
        attempt = 0
    }
}

enum ConnectionRecoveryState: Equatable {
    case disconnected
    case connecting(attempt: Int)
    case connected(epoch: UInt64, lastHeartbeatNs: UInt64)
    case waitingToReconnect(attempt: Int, deadlineNs: UInt64)
    case stopped
}

struct ConnectionRecoveryController {
    let heartbeatTimeoutNs: UInt64
    private(set) var state: ConnectionRecoveryState = .disconnected
    private var backoff: ReconnectBackoff

    init(
        heartbeatTimeoutNs: UInt64 = 3_000_000_000,
        backoff: ReconnectBackoff = ReconnectBackoff()
    ) {
        precondition(heartbeatTimeoutNs > 0)
        self.heartbeatTimeoutNs = heartbeatTimeoutNs
        self.backoff = backoff
    }

    mutating func startConnecting() {
        guard state != .stopped else { return }
        let nextAttempt = backoff.attempt == Int.max
            ? Int.max
            : backoff.attempt + 1
        state = .connecting(attempt: nextAttempt)
    }

    mutating func didConnect(epoch: UInt64, nowNs: UInt64) {
        precondition(epoch > 0)
        backoff.reset()
        state = .connected(epoch: epoch, lastHeartbeatNs: nowNs)
    }

    @discardableResult
    mutating func observeHeartbeat(epoch: UInt64, nowNs: UInt64) -> Bool {
        guard case .connected(let activeEpoch, _) = state,
              epoch == activeEpoch else { return false }
        state = .connected(epoch: epoch, lastHeartbeatNs: nowNs)
        return true
    }

    mutating func heartbeatTimedOut(nowNs: UInt64) -> Bool {
        guard case .connected(_, let lastHeartbeatNs) = state,
              nowNs >= lastHeartbeatNs,
              nowNs - lastHeartbeatNs >= heartbeatTimeoutNs else { return false }
        scheduleReconnect(nowNs: nowNs)
        return true
    }

    @discardableResult
    mutating func scheduleReconnect(nowNs: UInt64) -> UInt64 {
        guard state != .stopped else { return 0 }
        let delay = backoff.nextDelayNs()
        let deadline = nowNs.addingReportingOverflow(delay)
        state = .waitingToReconnect(
            attempt: backoff.attempt,
            deadlineNs: deadline.overflow ? UInt64.max : deadline.partialValue
        )
        return delay
    }

    mutating func stop() {
        state = .stopped
    }
}

enum CodecFallbackReason: String, Codable, Equatable {
    case preferredSupported = "preferred_supported"
    case preferredUnavailable = "preferred_unavailable"
}

struct CodecFallbackDecision: Equatable {
    let selected: StreamCodec
    let reason: CodecFallbackReason
}

enum CodecFallbackError: Error, Equatable {
    case noMutuallySupportedCodec
}

enum CodecFallbackPolicy {
    static func select(
        preferred: StreamCodec,
        hostSupported: [StreamCodec],
        clientSupported: [StreamCodec]
    ) throws -> CodecFallbackDecision {
        let mutual = hostSupported.filter(clientSupported.contains)
        guard !mutual.isEmpty else {
            throw CodecFallbackError.noMutuallySupportedCodec
        }
        if mutual.contains(preferred) {
            return CodecFallbackDecision(
                selected: preferred,
                reason: .preferredSupported
            )
        }
        return CodecFallbackDecision(
            selected: mutual[0],
            reason: .preferredUnavailable
        )
    }
}

enum TelemetryValue: Codable, Equatable {
    case string(String)
    case integer(Int64)
    case unsigned(UInt64)
    case double(Double)
    case boolean(Bool)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        do {
            self = .boolean(try container.decode(Bool.self))
            return
        } catch DecodingError.typeMismatch {
            // Try the next supported primitive type.
        }
        do {
            self = .integer(try container.decode(Int64.self))
            return
        } catch DecodingError.typeMismatch {
            // Try the next supported primitive type.
        }
        do {
            self = .unsigned(try container.decode(UInt64.self))
            return
        } catch DecodingError.typeMismatch {
            // Try the next supported primitive type.
        }
        do {
            self = .double(try container.decode(Double.self))
            return
        } catch DecodingError.typeMismatch {
            // The final supported primitive type is String.
        }
        self = .string(try container.decode(String.self))
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .integer(let value): try container.encode(value)
        case .unsigned(let value): try container.encode(value)
        case .double(let value): try container.encode(value)
        case .boolean(let value): try container.encode(value)
        }
    }
}

enum TelemetryTimestamp {
    private static let lock = NSLock()
    private static let formatter = ISO8601DateFormatter()

    static func string(from date: Date) -> String {
        lock.withLock { formatter.string(from: date) }
    }
}

struct TelemetryEvent: Codable, Equatable {
    let schemaVersion: UInt8
    let event: String
    let wallTime: String
    let monotonicNs: UInt64
    let sessionEpoch: UInt64?
    let attributes: [String: TelemetryValue]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case event
        case wallTime = "wall_time"
        case monotonicNs = "monotonic_ns"
        case sessionEpoch = "session_epoch"
        case attributes
    }

    init(
        event: String,
        sessionEpoch: UInt64? = nil,
        attributes: [String: TelemetryValue] = [:],
        wallTime: String = TelemetryTimestamp.string(from: Date()),
        monotonicNs: UInt64 = DispatchTime.now().uptimeNanoseconds
    ) {
        schemaVersion = 1
        self.event = event
        self.wallTime = wallTime
        self.monotonicNs = monotonicNs
        self.sessionEpoch = sessionEpoch
        self.attributes = attributes
    }
}

protocol TelemetryRecording: AnyObject {
    func record(_ event: TelemetryEvent) throws
}

enum JSONLTelemetryError: Error {
    case cannotCreateFile(URL)
    case sinkClosed
}

final class JSONLTelemetrySink: TelemetryRecording {
    private let lock = NSLock()
    private let encoder: JSONEncoder
    private var handle: FileHandle?

    init(url: URL) throws {
        let manager = FileManager.default
        if !manager.fileExists(atPath: url.path),
           !manager.createFile(atPath: url.path, contents: nil) {
            throw JSONLTelemetryError.cannotCreateFile(url)
        }
        handle = try FileHandle(forWritingTo: url)
        try handle?.seekToEnd()
        encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
    }

    func record(_ event: TelemetryEvent) throws {
        try lock.withLock {
            guard let handle else { throw JSONLTelemetryError.sinkClosed }
            var line = try encoder.encode(event)
            line.append(0x0A)
            try handle.write(contentsOf: line)
        }
    }

    func close() throws {
        try lock.withLock {
            guard let handle else { return }
            try handle.synchronize()
            try handle.close()
            self.handle = nil
        }
    }
}
