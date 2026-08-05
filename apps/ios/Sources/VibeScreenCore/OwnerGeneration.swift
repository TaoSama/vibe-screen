import Foundation

/// Identifies one concrete TCP connection lifetime.
///
/// A fresh value must be created for every connection attempt. The UUID keeps
/// an owner distinct even when a host, port, or logical session is reused.
public struct ConnectionOwner: Hashable, Sendable {
    private let identifier: UUID

    public init() {
        identifier = UUID()
    }
}

/// Identifies one negotiated session within a concrete connection lifetime.
public struct SessionOwner: Hashable, Sendable {
    public let connectionOwner: ConnectionOwner
    private let identifier: UUID

    public init(connectionOwner: ConnectionOwner) {
        self.connectionOwner = connectionOwner
        identifier = UUID()
    }
}

/// Identifies one decoder instance, including the configuration it owns.
public struct DecoderOwner: Hashable, Sendable {
    public let sessionOwner: SessionOwner
    public let streamID: UInt64
    public let configEpoch: UInt64
    private let identifier: UUID

    public init(sessionOwner: SessionOwner, streamID: UInt64, configEpoch: UInt64) {
        self.sessionOwner = sessionOwner
        self.streamID = streamID
        self.configEpoch = configEpoch
        identifier = UUID()
    }
}

/// A transport callback tied to the connection that produced it.
public struct OwnedDelivery<Payload: Sendable>: Sendable {
    public let owner: ConnectionOwner
    public let payload: Payload

    public init(owner: ConnectionOwner, payload: Payload) {
        self.owner = owner
        self.payload = payload
    }
}

/// Pure connection-owner gate for callbacks crossing an executor boundary.
public struct OwnedDeliveryGate: Sendable {
    public private(set) var owner: ConnectionOwner?

    public init(owner: ConnectionOwner? = nil) {
        self.owner = owner
    }

    public mutating func reset(to owner: ConnectionOwner? = nil) {
        self.owner = owner
    }

    public func accepts<Payload>(_ delivery: OwnedDelivery<Payload>) -> Bool {
        accepts(owner: delivery.owner)
    }

    public func accepts(owner candidate: ConnectionOwner) -> Bool {
        owner == candidate
    }
}

/// Pure final-delivery gate shared by the app and deterministic tests.
public enum DecoderDeliveryGate {
    public static func accepts(
        owner candidate: DecoderOwner,
        activeOwner: DecoderOwner?,
        sessionOwner: SessionOwner?,
        selectedStreamID: UInt64?
    ) -> Bool {
        guard let activeOwner, let sessionOwner, let selectedStreamID else { return false }
        return candidate == activeOwner &&
            candidate.sessionOwner == sessionOwner &&
            candidate.streamID == selectedStreamID &&
            candidate.configEpoch == activeOwner.configEpoch
    }
}
