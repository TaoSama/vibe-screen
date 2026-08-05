import Foundation
import VibeScreenProtocol

public enum SessionPhase: Equatable, Sendable {
    case idle
    case connecting
    case negotiating
    case ready
    case streaming(streamID: UInt64)
    case reconnecting(attempt: Int)
    case failed(reason: String)
}

public enum SessionStateError: Error, Equatable {
    case invalidTransition(from: SessionPhase, event: String)
    case unsupportedProtocol(UInt32)
    case staleEpoch(received: UInt64, current: UInt64)
    case invalidSessionIdentifier
    case invalidSessionEpoch(UInt64)
}

public struct SessionState: Sendable {
    public static let protocolVersion: UInt32 = 1

    public private(set) var phase: SessionPhase = .idle
    public private(set) var sessionID = Data()
    public private(set) var sessionEpoch: UInt64 = 0
    public private(set) var negotiatedCapabilities: Set<VSCapability> = []

    public init() {}

    public mutating func beginConnection() throws {
        guard phase == .idle || isRecoverablePhase else {
            throw SessionStateError.invalidTransition(from: phase, event: "beginConnection")
        }
        phase = .connecting
    }

    public mutating func transportConnected() throws {
        guard phase == .connecting || isReconnectPhase else {
            throw SessionStateError.invalidTransition(from: phase, event: "transportConnected")
        }
        phase = .negotiating
    }

    public mutating func accept(
        selectedProtocol: UInt32,
        sessionID: Data,
        epoch: UInt64,
        localCapabilities: Set<VSCapability>,
        hostCapabilities: Set<VSCapability>
    ) throws {
        guard phase == .negotiating else {
            throw SessionStateError.invalidTransition(from: phase, event: "accept")
        }
        guard selectedProtocol == Self.protocolVersion else {
            throw SessionStateError.unsupportedProtocol(selectedProtocol)
        }
        guard !sessionID.isEmpty else { throw SessionStateError.invalidSessionIdentifier }
        guard epoch > 0 else { throw SessionStateError.invalidSessionEpoch(epoch) }
        self.sessionID = sessionID
        sessionEpoch = epoch
        negotiatedCapabilities = localCapabilities.intersection(hostCapabilities)
        phase = .ready
    }

    public mutating func startStreaming(streamID: UInt64) throws {
        guard phase == .ready else {
            throw SessionStateError.invalidTransition(from: phase, event: "startStreaming")
        }
        phase = .streaming(streamID: streamID)
    }

    public func accepts(epoch: UInt64) -> Bool {
        epoch == sessionEpoch
    }

    public mutating func disconnected(retryAttempt: Int) {
        phase = .reconnecting(attempt: retryAttempt)
    }

    public mutating func fail(_ reason: String) {
        phase = .failed(reason: reason)
    }

    public mutating func reset() {
        phase = .idle
        sessionID = Data()
        sessionEpoch = 0
        negotiatedCapabilities = []
    }

    private var isReconnectPhase: Bool {
        if case .reconnecting = phase { return true }
        return false
    }

    private var isRecoverablePhase: Bool {
        isReconnectPhase || {
            if case .failed = phase { return true }
            return false
        }()
    }
}

public struct ReconnectBackoff: Sendable {
    public static let maximumDelaySeconds = 3.0
    private static let baseDelaySeconds = 0.25

    public init() {}

    public func delaySeconds(forAttempt attempt: Int) -> Double {
        let exponent = min(max(attempt, 0), 4)
        return min(Self.baseDelaySeconds * pow(2.0, Double(exponent)), Self.maximumDelaySeconds)
    }
}
