import Foundation

struct HostClientSessionKey: Hashable, Sendable {
    let sessionID: Data
    let epoch: UInt64
}

struct HostDisplayStreamBinding: Equatable, Sendable {
    let displayID: String
    let streamID: UInt64
}

enum HostDisplayRouterError: Error, Equatable {
    case invalidSession
    case invalidBinding
    case clientLimitReached(Int)
    case streamLimitReached(Int)
    case duplicateStream(UInt64)
    case duplicateDisplay(String)
    case unknownSession
}

final class HostMultiClientDisplayRouter: @unchecked Sendable {
    let maximumClients: Int
    let maximumStreamsPerClient: Int

    private let lock = NSLock()
    private var sessions: [HostClientSessionKey: [UInt64: HostDisplayStreamBinding]] = [:]

    init(maximumClients: Int, maximumStreamsPerClient: Int) {
        self.maximumClients = max(1, maximumClients)
        self.maximumStreamsPerClient = max(1, maximumStreamsPerClient)
    }

    var activeClientCount: Int {
        lock.withLock { sessions.count }
    }

    func register(_ key: HostClientSessionKey) throws {
        try lock.withLock {
            try validate(key)
            if sessions[key] != nil { return }

            let matchingSessionIDs = sessions.keys.filter { $0.sessionID == key.sessionID }
            if matchingSessionIDs.contains(where: { $0.epoch > key.epoch }) {
                throw HostDisplayRouterError.invalidSession
            }
            for staleKey in matchingSessionIDs where staleKey.epoch < key.epoch {
                sessions.removeValue(forKey: staleKey)
            }

            guard sessions.count < maximumClients else {
                throw HostDisplayRouterError.clientLimitReached(maximumClients)
            }
            sessions[key] = [:]
        }
    }

    @discardableResult
    func allocateStream(for displayID: String, in key: HostClientSessionKey) throws -> UInt64 {
        try lock.withLock {
            try validateBinding(displayID: displayID, streamID: 1)
            var streams = try streamsForRegisteredSession(key)
            if let existing = streams.values.first(where: { binding in binding.displayID == displayID }) {
                return existing.streamID
            }
            guard streams.count < maximumStreamsPerClient else {
                throw HostDisplayRouterError.streamLimitReached(maximumStreamsPerClient)
            }
            let streamID = nextAvailableStreamID(in: streams)
            let binding = HostDisplayStreamBinding(displayID: displayID, streamID: streamID)
            streams[streamID] = binding
            sessions[key] = streams
            return streamID
        }
    }

    func bind(_ binding: HostDisplayStreamBinding, to key: HostClientSessionKey) throws {
        try lock.withLock {
            try validateBinding(displayID: binding.displayID, streamID: binding.streamID)
            var streams = try streamsForRegisteredSession(key)
            guard streams[binding.streamID] == nil else {
                throw HostDisplayRouterError.duplicateStream(binding.streamID)
            }
            guard !streams.values.contains(where: { $0.displayID == binding.displayID }) else {
                throw HostDisplayRouterError.duplicateDisplay(binding.displayID)
            }
            guard streams.count < maximumStreamsPerClient else {
                throw HostDisplayRouterError.streamLimitReached(maximumStreamsPerClient)
            }
            streams[binding.streamID] = binding
            sessions[key] = streams
        }
    }

    func rebind(streamID: UInt64, toDisplayID displayID: String, in key: HostClientSessionKey) throws {
        try lock.withLock {
            try validateBinding(displayID: displayID, streamID: streamID)
            var streams = try streamsForRegisteredSession(key)
            guard streams[streamID] != nil else {
                throw HostDisplayRouterError.unknownSession
            }
            guard !streams.values.contains(where: { $0.streamID != streamID && $0.displayID == displayID }) else {
                throw HostDisplayRouterError.duplicateDisplay(displayID)
            }
            streams[streamID] = HostDisplayStreamBinding(displayID: displayID, streamID: streamID)
            sessions[key] = streams
        }
    }

    func binding(streamID: UInt64, in key: HostClientSessionKey) -> HostDisplayStreamBinding? {
        lock.withLock { sessions[key]?[streamID] }
    }

    func disconnect(_ key: HostClientSessionKey) {
        lock.withLock {
            sessions.removeValue(forKey: key)
            return ()
        }
    }

    private func validate(_ key: HostClientSessionKey) throws {
        guard !key.sessionID.isEmpty, key.epoch > 0 else {
            throw HostDisplayRouterError.invalidSession
        }
    }

    private func validateBinding(displayID: String, streamID: UInt64) throws {
        guard !displayID.isEmpty, streamID > 0 else {
            throw HostDisplayRouterError.invalidBinding
        }
    }

    private func streamsForRegisteredSession(_ key: HostClientSessionKey) throws -> [UInt64: HostDisplayStreamBinding] {
        try validate(key)
        guard let streams = sessions[key] else { throw HostDisplayRouterError.unknownSession }
        return streams
    }

    private func nextAvailableStreamID(in streams: [UInt64: HostDisplayStreamBinding]) -> UInt64 {
        var candidate: UInt64 = 1
        while streams[candidate] != nil { candidate += 1 }
        return candidate
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
