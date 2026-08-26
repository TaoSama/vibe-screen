import Foundation

public struct AudioPlaybackQueuePolicy: Equatable, Sendable {
    public static let defaultMaximumScheduledBuffers = 8

    public let maximumScheduledBuffers: Int

    public init(maximumScheduledBuffers: Int = Self.defaultMaximumScheduledBuffers) {
        self.maximumScheduledBuffers = max(1, maximumScheduledBuffers)
    }
}

public enum AudioPlaybackQueueResult: Equatable, Sendable {
    case scheduled
    case overrunDropped
}

public struct AudioPlaybackQueueSnapshot: Equatable, Sendable {
    public let isConfigured: Bool
    public let scheduledBufferCount: Int
    public let scheduledBufferTotal: UInt64
    public let playedBufferTotal: UInt64
    public let queueEmptyCount: UInt64
    public let lateCompletionCount: UInt64
    public let overrunDropCount: UInt64
    public let stopCount: UInt64
}

public struct AudioPlaybackQueueState: Sendable {
    public let policy: AudioPlaybackQueuePolicy
    public private(set) var isConfigured = false
    public private(set) var scheduledBufferCount = 0
    public private(set) var scheduledBufferTotal: UInt64 = 0
    public private(set) var playedBufferTotal: UInt64 = 0
    public private(set) var queueEmptyCount: UInt64 = 0
    public private(set) var lateCompletionCount: UInt64 = 0
    public private(set) var overrunDropCount: UInt64 = 0
    public private(set) var stopCount: UInt64 = 0

    public init(policy: AudioPlaybackQueuePolicy = AudioPlaybackQueuePolicy()) {
        self.policy = policy
    }

    public mutating func configure(format _: PCMStreamFormat) {
        isConfigured = true
        scheduledBufferCount = 0
    }

    public mutating func schedule(
        _ packet: AudioPacket,
        format: PCMStreamFormat
    ) throws -> AudioPlaybackQueueResult {
        guard isConfigured else { throw AudioPlaybackQueueError.notConfigured }
        guard packet.payload.count == format.bytesPerPacket,
              packet.header.frameCount == format.framesPerPacket else {
            throw AudioPlaybackQueueError.invalidPCMByteCount
        }
        guard hasScheduleCapacity else {
            recordOverrunDrop()
            return .overrunDropped
        }
        recordScheduledBuffer()
        return .scheduled
    }

    public var hasScheduleCapacity: Bool {
        scheduledBufferCount < policy.maximumScheduledBuffers
    }

    public mutating func recordOverrunDrop() {
        overrunDropCount += 1
    }

    public mutating func recordScheduledBuffer() {
        precondition(hasScheduleCapacity, "recordScheduledBuffer requires available capacity")
        scheduledBufferCount += 1
        scheduledBufferTotal += 1
    }

    public mutating func completeScheduledBuffer() {
        guard scheduledBufferCount > 0 else {
            lateCompletionCount += 1
            return
        }
        scheduledBufferCount -= 1
        playedBufferTotal += 1
        if scheduledBufferCount == 0 {
            queueEmptyCount += 1
        }
    }

    public mutating func stop() {
        let hadPlaybackState = isConfigured || scheduledBufferCount > 0
        isConfigured = false
        scheduledBufferCount = 0
        if hadPlaybackState { stopCount += 1 }
    }

    public var snapshot: AudioPlaybackQueueSnapshot {
        AudioPlaybackQueueSnapshot(
            isConfigured: isConfigured,
            scheduledBufferCount: scheduledBufferCount,
            scheduledBufferTotal: scheduledBufferTotal,
            playedBufferTotal: playedBufferTotal,
            queueEmptyCount: queueEmptyCount,
            lateCompletionCount: lateCompletionCount,
            overrunDropCount: overrunDropCount,
            stopCount: stopCount
        )
    }
}

public enum AudioPlaybackQueueError: Error, Equatable {
    case notConfigured
    case invalidPCMByteCount
}
