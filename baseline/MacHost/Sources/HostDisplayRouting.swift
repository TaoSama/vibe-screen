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
    private struct ClientRoute {
        let epoch: UInt64
        var bindings: [UInt64: HostDisplayStreamBinding] = [:]
    }

    private let maximumClients: Int
    private let maximumStreamsPerClient: Int
    private let lock = NSLock()
    private var routes: [Data: ClientRoute] = [:]

    init(maximumClients: Int, maximumStreamsPerClient: Int) {
        self.maximumClients = max(1, maximumClients)
        self.maximumStreamsPerClient = max(1, maximumStreamsPerClient)
    }

    var activeClientCount: Int {
        lock.withLock { routes.count }
    }

    func register(_ key: HostClientSessionKey) throws {
        try lock.withLock {
            try validate(key)
            if let existing = routes[key.sessionID] {
                guard key.epoch > existing.epoch else { throw HostDisplayRouterError.invalidSession }
                routes[key.sessionID] = ClientRoute(epoch: key.epoch)
                return
            }
            guard routes.count < maximumClients else {
                throw HostDisplayRouterError.clientLimitReached(maximumClients)
            }
            routes[key.sessionID] = ClientRoute(epoch: key.epoch)
        }
    }

    func allocateStream(for displayID: String, in key: HostClientSessionKey) throws -> UInt64 {
        try lock.withLock {
            try validate(displayID: displayID, streamID: 1)
            var route = try registeredRoute(for: key)
            if let existing = route.bindings.values.first(where: { $0.displayID == displayID }) {
                return existing.streamID
            }
            guard route.bindings.count < maximumStreamsPerClient else {
                throw HostDisplayRouterError.streamLimitReached(maximumStreamsPerClient)
            }
            let streamID = nextStreamID(in: route)
            route.bindings[streamID] = HostDisplayStreamBinding(displayID: displayID, streamID: streamID)
            routes[key.sessionID] = route
            return streamID
        }
    }

    func bind(_ binding: HostDisplayStreamBinding, to key: HostClientSessionKey) throws {
        try lock.withLock {
            try validate(displayID: binding.displayID, streamID: binding.streamID)
            var route = try registeredRoute(for: key)
            if let existing = route.bindings[binding.streamID], existing == binding {
                return
            }
            if route.bindings.contains(where: { $0.key != binding.streamID && $0.value.displayID == binding.displayID }) {
                throw HostDisplayRouterError.duplicateDisplay(binding.displayID)
            }
            if route.bindings[binding.streamID] == nil {
                guard route.bindings.count < maximumStreamsPerClient else {
                    throw HostDisplayRouterError.streamLimitReached(maximumStreamsPerClient)
                }
            }
            route.bindings[binding.streamID] = binding
            routes[key.sessionID] = route
        }
    }

    func rebind(streamID: UInt64, toDisplayID displayID: String, in key: HostClientSessionKey) throws {
        try bind(HostDisplayStreamBinding(displayID: displayID, streamID: streamID), to: key)
    }

    func binding(streamID: UInt64, in key: HostClientSessionKey) -> HostDisplayStreamBinding? {
        lock.withLock {
            guard let route = routes[key.sessionID], route.epoch == key.epoch else { return nil }
            return route.bindings[streamID]
        }
    }

    func disconnect(_ key: HostClientSessionKey) {
        lock.withLock {
            guard let route = routes[key.sessionID], route.epoch == key.epoch else { return }
            routes.removeValue(forKey: key.sessionID)
        }
    }

    private func registeredRoute(for key: HostClientSessionKey) throws -> ClientRoute {
        try validate(key)
        guard let route = routes[key.sessionID], route.epoch == key.epoch else {
            throw HostDisplayRouterError.invalidSession
        }
        return route
    }

    private func validate(_ key: HostClientSessionKey) throws {
        guard !key.sessionID.isEmpty, key.epoch > 0 else {
            throw HostDisplayRouterError.invalidSession
        }
    }

    private func validate(displayID: String, streamID: UInt64) throws {
        guard !displayID.isEmpty, streamID > 0 else {
            throw HostDisplayRouterError.invalidBinding
        }
    }

    private func nextStreamID(in route: ClientRoute) -> UInt64 {
        for candidate in UInt64(1)...UInt64(maximumStreamsPerClient) {
            if route.bindings[candidate] == nil { return candidate }
        }
        return UInt64(maximumStreamsPerClient)
    }
}
