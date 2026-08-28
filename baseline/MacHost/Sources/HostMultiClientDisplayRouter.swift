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
    let maximumClients: Int
    let maximumStreamsPerClient: Int

    private struct ClientRoute {
        var key: HostClientSessionKey
        var bindingsByStream: [UInt64: HostDisplayStreamBinding] = [:]
        var streamByDisplay: [String: UInt64] = [:]
        var nextStreamID: UInt64 = 1
        var reservedStreamIDs: Set<UInt64> = []
    }

    private var routesBySessionID: [Data: ClientRoute] = [:]
    private let lock = NSLock()

    init(maximumClients: Int, maximumStreamsPerClient: Int) {
        self.maximumClients = max(1, maximumClients)
        self.maximumStreamsPerClient = max(1, maximumStreamsPerClient)
    }

    var activeClientCount: Int {
        withLock { routesBySessionID.count }
    }

    func register(_ key: HostClientSessionKey, reservedStreamIDs: Set<UInt64> = []) throws {
        try validate(key)
        try validateReservedStreamIDs(reservedStreamIDs)
        try withLock {
            if let existing = routesBySessionID[key.sessionID] {
                guard key.epoch >= existing.key.epoch else {
                    throw HostDisplayRouterError.invalidSession
                }
                guard key.epoch != existing.key.epoch else {
                    var route = existing
                    try applyReservedStreamIDs(reservedStreamIDs, to: &route)
                    routesBySessionID[key.sessionID] = route
                    return
                }
                var route = ClientRoute(key: key)
                try applyReservedStreamIDs(reservedStreamIDs, to: &route)
                routesBySessionID[key.sessionID] = route
                return
            }

            guard routesBySessionID.count < maximumClients else {
                throw HostDisplayRouterError.clientLimitReached(maximumClients)
            }
            var route = ClientRoute(key: key)
            try applyReservedStreamIDs(reservedStreamIDs, to: &route)
            routesBySessionID[key.sessionID] = route
        }
    }

    func reserveStreamIDs(_ streamIDs: Set<UInt64>, in key: HostClientSessionKey) throws {
        try validate(key)
        try validateReservedStreamIDs(streamIDs)
        try withLock {
            var route = try route(for: key)
            try applyReservedStreamIDs(streamIDs, to: &route)
            routesBySessionID[key.sessionID] = route
        }
    }

    func allocateStream(for displayID: String, in key: HostClientSessionKey) throws -> UInt64 {
        try withLock {
            try validate(displayID: displayID)
            var route = try route(for: key)
            if let existing = route.streamByDisplay[displayID] { return existing }
            guard route.bindingsByStream.count < maximumStreamsPerClient else {
                throw HostDisplayRouterError.streamLimitReached(maximumStreamsPerClient)
            }
            let streamID = nextAvailableStreamID(in: route)
            bindLocked(
                HostDisplayStreamBinding(displayID: displayID, streamID: streamID),
                route: &route
            )
            routesBySessionID[key.sessionID] = route
            return streamID
        }
    }

    func bind(_ binding: HostDisplayStreamBinding, to key: HostClientSessionKey) throws {
        try withLock {
            try validate(binding)
            var route = try route(for: key)
            guard !route.reservedStreamIDs.contains(binding.streamID) else {
                throw HostDisplayRouterError.invalidBinding
            }
            if let existingStream = route.streamByDisplay[binding.displayID], existingStream != binding.streamID {
                throw HostDisplayRouterError.duplicateDisplay(binding.displayID)
            }
            if route.bindingsByStream[binding.streamID] == nil,
               route.bindingsByStream.count >= maximumStreamsPerClient {
                throw HostDisplayRouterError.streamLimitReached(maximumStreamsPerClient)
            }
            bindLocked(binding, route: &route)
            routesBySessionID[key.sessionID] = route
        }
    }

    func rebind(streamID: UInt64, toDisplayID displayID: String, in key: HostClientSessionKey) throws {
        try bind(HostDisplayStreamBinding(displayID: displayID, streamID: streamID), to: key)
    }

    func binding(streamID: UInt64, in key: HostClientSessionKey) -> HostDisplayStreamBinding? {
        withLock {
            guard isValid(key), streamID > 0 else { return nil }
            guard routesBySessionID[key.sessionID]?.key == key else { return nil }
            return routesBySessionID[key.sessionID]?.bindingsByStream[streamID]
        }
    }

    func disconnect(_ key: HostClientSessionKey) {
        withLock {
            guard isValid(key) else { return }
            guard routesBySessionID[key.sessionID]?.key == key else { return }
            routesBySessionID.removeValue(forKey: key.sessionID)
        }
    }

    private func validate(_ key: HostClientSessionKey) throws {
        guard isValid(key) else { throw HostDisplayRouterError.invalidSession }
    }

    private func isValid(_ key: HostClientSessionKey) -> Bool {
        !key.sessionID.isEmpty && key.epoch > 0
    }

    private func validate(displayID: String) throws {
        guard !displayID.isEmpty else { throw HostDisplayRouterError.invalidBinding }
    }

    private func validate(_ binding: HostDisplayStreamBinding) throws {
        guard binding.streamID > 0 else { throw HostDisplayRouterError.invalidBinding }
        try validate(displayID: binding.displayID)
    }

    private func validateReservedStreamIDs(_ streamIDs: Set<UInt64>) throws {
        guard !streamIDs.contains(0) else { throw HostDisplayRouterError.invalidBinding }
    }

    private func applyReservedStreamIDs(_ streamIDs: Set<UInt64>, to route: inout ClientRoute) throws {
        guard !route.bindingsByStream.keys.contains(where: { streamIDs.contains($0) }) else {
            throw HostDisplayRouterError.invalidBinding
        }
        route.reservedStreamIDs = streamIDs
    }

    private func route(for key: HostClientSessionKey) throws -> ClientRoute {
        guard let route = routesBySessionID[key.sessionID], route.key == key else {
            throw HostDisplayRouterError.invalidSession
        }
        return route
    }

    private func bindLocked(_ binding: HostDisplayStreamBinding, route: inout ClientRoute) {
        if let previous = route.bindingsByStream[binding.streamID] {
            route.streamByDisplay.removeValue(forKey: previous.displayID)
        }
        route.bindingsByStream[binding.streamID] = binding
        route.streamByDisplay[binding.displayID] = binding.streamID
        if binding.streamID >= route.nextStreamID {
            route.nextStreamID = binding.streamID + 1
        }
    }

    private func nextAvailableStreamID(in route: ClientRoute) -> UInt64 {
        var streamID = route.nextStreamID
        while route.bindingsByStream[streamID] != nil || route.reservedStreamIDs.contains(streamID) {
            streamID += 1
        }
        return streamID
    }

    private func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try body()
    }
}
