import Foundation

public struct ClientSessionKey: Hashable, Sendable {
    public let sessionID: Data
    public let epoch: UInt64

    public init(sessionID: Data, epoch: UInt64) {
        self.sessionID = sessionID
        self.epoch = epoch
    }
}

public struct DisplayStreamBinding: Equatable, Sendable {
    public let displayID: String
    public let streamID: UInt64

    public init(displayID: String, streamID: UInt64) {
        self.displayID = displayID
        self.streamID = streamID
    }
}

public enum SessionRegistryError: Error, Equatable {
    case invalidSession
    case clientLimitReached(Int)
    case streamLimitReached(Int)
    case duplicateStream(UInt64)
    case duplicateDisplay(String)
    case unknownSession
}

public struct MultiDisplaySessionRegistry: Sendable {
    public let maximumClients: Int
    public let maximumStreamsPerClient: Int
    private var sessions: [ClientSessionKey: [UInt64: DisplayStreamBinding]] = [:]

    public init(maximumClients: Int, maximumStreamsPerClient: Int) {
        self.maximumClients = max(1, maximumClients)
        self.maximumStreamsPerClient = max(1, maximumStreamsPerClient)
    }

    public mutating func register(_ key: ClientSessionKey) throws {
        guard !key.sessionID.isEmpty, key.epoch > 0 else { throw SessionRegistryError.invalidSession }
        if sessions[key] != nil { return }
        let oldKeys = sessions.keys.filter { $0.sessionID == key.sessionID && $0.epoch < key.epoch }
        for oldKey in oldKeys { sessions.removeValue(forKey: oldKey) }
        guard sessions.count < maximumClients else {
            throw SessionRegistryError.clientLimitReached(maximumClients)
        }
        sessions[key] = [:]
    }

    public mutating func bind(_ binding: DisplayStreamBinding, to key: ClientSessionKey) throws {
        guard binding.streamID > 0, !binding.displayID.isEmpty else {
            throw SessionRegistryError.duplicateStream(binding.streamID)
        }
        guard var streams = sessions[key] else { throw SessionRegistryError.unknownSession }
        guard streams[binding.streamID] == nil else {
            throw SessionRegistryError.duplicateStream(binding.streamID)
        }
        guard !streams.values.contains(where: { $0.displayID == binding.displayID }) else {
            throw SessionRegistryError.duplicateDisplay(binding.displayID)
        }
        guard streams.count < maximumStreamsPerClient else {
            throw SessionRegistryError.streamLimitReached(maximumStreamsPerClient)
        }
        streams[binding.streamID] = binding
        sessions[key] = streams
    }

    public func binding(streamID: UInt64, in key: ClientSessionKey) -> DisplayStreamBinding? {
        sessions[key]?[streamID]
    }

    public func bindings(in key: ClientSessionKey) -> [DisplayStreamBinding] {
        sessions[key]?.values.sorted { $0.streamID < $1.streamID } ?? []
    }

    @discardableResult
    public mutating func release(streamID: UInt64, in key: ClientSessionKey) -> Bool {
        guard var streams = sessions[key] else { return false }
        let removed = streams.removeValue(forKey: streamID) != nil
        sessions[key] = streams
        return removed
    }

    public mutating func disconnect(_ key: ClientSessionKey) {
        sessions.removeValue(forKey: key)
    }

    public var activeClientCount: Int { sessions.count }
}
