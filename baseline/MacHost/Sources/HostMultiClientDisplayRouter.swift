import Foundation

struct HostClientSessionKey: Hashable {
    let sessionID: Data
    let epoch: UInt64
}

struct HostDisplayStreamBinding: Equatable {
    let displayID: String
    let streamID: UInt64
}

enum HostDisplayRouterError: Error, Equatable {
    case invalidSession
    case invalidBinding
    case duplicateDisplay(String)
    case streamLimitReached(Int)
    case clientLimitReached(Int)
}

final class HostMultiClientDisplayRouter {
    private let maximumClients: Int
    private let maximumStreamsPerClient: Int
    private var clients: [Data: ClientRoute] = [:]
    private let lock = NSLock()

    init(maximumClients: Int, maximumStreamsPerClient: Int) {
        self.maximumClients = max(1, maximumClients)
        self.maximumStreamsPerClient = max(1, maximumStreamsPerClient)
    }

    var activeClientCount: Int {
        withLock { clients.count }
    }

    func register(_ key: HostClientSessionKey) throws {
        try withLock {
            try validate(key)
            if let existing = clients[key.sessionID] {
                guard key.epoch > existing.epoch else { throw HostDisplayRouterError.invalidSession }
                clients[key.sessionID] = ClientRoute(epoch: key.epoch, bindings: [:])
                return
            }
            guard clients.count < maximumClients else {
                throw HostDisplayRouterError.clientLimitReached(maximumClients)
            }
            clients[key.sessionID] = ClientRoute(epoch: key.epoch, bindings: [:])
        }
    }

    func allocateStream(for displayID: String, in key: HostClientSessionKey) throws -> UInt64 {
        try withLock {
            try validate(key)
            guard !displayID.isEmpty else { throw HostDisplayRouterError.invalidBinding }
            guard var route = clients[key.sessionID], route.epoch == key.epoch else {
                throw HostDisplayRouterError.invalidSession
            }
            if let existing = route.bindings.values.first(where: { $0.displayID == displayID }) {
                return existing.streamID
            }
            guard route.bindings.count < maximumStreamsPerClient else {
                throw HostDisplayRouterError.streamLimitReached(maximumStreamsPerClient)
            }
            let nextStreamID = UInt64(route.bindings.count + 1)
            route.bindings[nextStreamID] = HostDisplayStreamBinding(displayID: displayID, streamID: nextStreamID)
            clients[key.sessionID] = route
            return nextStreamID
        }
    }

    func bind(_ binding: HostDisplayStreamBinding, to key: HostClientSessionKey) throws {
        try withLock {
            try validate(key)
            try validate(binding)
            guard var route = clients[key.sessionID], route.epoch == key.epoch else {
                throw HostDisplayRouterError.invalidSession
            }
            if route.bindings.values.contains(where: { $0.displayID == binding.displayID && $0.streamID != binding.streamID }) {
                throw HostDisplayRouterError.duplicateDisplay(binding.displayID)
            }
            if route.bindings[binding.streamID] == nil {
                guard route.bindings.count < maximumStreamsPerClient else {
                    throw HostDisplayRouterError.streamLimitReached(maximumStreamsPerClient)
                }
            }
            route.bindings[binding.streamID] = binding
            clients[key.sessionID] = route
        }
    }

    func rebind(streamID: UInt64, toDisplayID displayID: String, in key: HostClientSessionKey) throws {
        try bind(HostDisplayStreamBinding(displayID: displayID, streamID: streamID), to: key)
    }

    func binding(streamID: UInt64, in key: HostClientSessionKey) -> HostDisplayStreamBinding? {
        withLock {
            guard let route = clients[key.sessionID], route.epoch == key.epoch else { return nil }
            return route.bindings[streamID]
        }
    }

    func disconnect(_ key: HostClientSessionKey) {
        withLock {
            guard let route = clients[key.sessionID], route.epoch == key.epoch else { return }
            clients.removeValue(forKey: key.sessionID)
        }
    }

    private func validate(_ key: HostClientSessionKey) throws {
        guard !key.sessionID.isEmpty, key.epoch > 0 else { throw HostDisplayRouterError.invalidSession }
    }

    private func validate(_ binding: HostDisplayStreamBinding) throws {
        guard !binding.displayID.isEmpty, binding.streamID > 0 else { throw HostDisplayRouterError.invalidBinding }
    }

    private func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try body()
    }

    private struct ClientRoute {
        let epoch: UInt64
        var bindings: [UInt64: HostDisplayStreamBinding]
    }
}
