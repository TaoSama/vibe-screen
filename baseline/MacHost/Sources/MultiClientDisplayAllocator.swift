import Foundation

struct MultiClientSessionKey: Hashable {
    let sessionID: Data
    let epoch: UInt64
}

struct MultiClientDisplayStreamBinding: Equatable {
    let displayID: String
    let streamID: UInt64
}

enum MultiClientDisplayAllocatorError: Error, Equatable {
    case invalidSession
    case invalidBinding
    case duplicateDisplay(String)
    case streamLimitReached(Int)
    case clientLimitReached(Int)
}

final class MultiClientDisplayAllocator {
    let maximumClients: Int
    let maximumStreamsPerClient: Int

    private struct ClientRoute {
        var key: MultiClientSessionKey
        var bindingsByStream: [UInt64: MultiClientDisplayStreamBinding] = [:]
        var streamByDisplay: [String: UInt64] = [:]
        var nextStreamID: UInt64 = 1
        var reservedStreamIDs: Set<UInt64> = []
    }

    private var routesBySessionID: [Data: ClientRoute] = [:]
    private var ownerByDisplay: [String: MultiClientSessionKey] = [:]
    private let lock = NSLock()

    init(maximumClients: Int, maximumStreamsPerClient: Int) {
        self.maximumClients = max(1, maximumClients)
        self.maximumStreamsPerClient = max(1, maximumStreamsPerClient)
    }

    var activeClientCount: Int {
        withLock { routesBySessionID.count }
    }

    func register(_ key: MultiClientSessionKey, reservedStreamIDs: Set<UInt64> = []) throws {
        try validate(key)
        try validateReservedStreamIDs(reservedStreamIDs)
        try withLock {
            if let existing = routesBySessionID[key.sessionID] {
                guard key.epoch >= existing.key.epoch else {
                    throw MultiClientDisplayAllocatorError.invalidSession
                }
                guard key.epoch != existing.key.epoch else {
                    var route = existing
                    try applyReservedStreamIDs(reservedStreamIDs, to: &route)
                    routesBySessionID[key.sessionID] = route
                    return
                }
                var route = ClientRoute(key: key)
                try applyReservedStreamIDs(reservedStreamIDs, to: &route)
                releaseDisplayOwners(for: existing)
                routesBySessionID[key.sessionID] = route
                return
            }

            guard routesBySessionID.count < maximumClients else {
                throw MultiClientDisplayAllocatorError.clientLimitReached(maximumClients)
            }
            var route = ClientRoute(key: key)
            try applyReservedStreamIDs(reservedStreamIDs, to: &route)
            routesBySessionID[key.sessionID] = route
        }
    }

    func reserveStreamIDs(_ streamIDs: Set<UInt64>, in key: MultiClientSessionKey) throws {
        try validate(key)
        try validateReservedStreamIDs(streamIDs)
        try withLock {
            var route = try route(for: key)
            try applyReservedStreamIDs(streamIDs, to: &route)
            routesBySessionID[key.sessionID] = route
        }
    }

    func allocateStream(for displayID: String, in key: MultiClientSessionKey) throws -> UInt64 {
        try withLock {
            try validate(displayID: displayID)
            var route = try route(for: key)
            try validateDisplayOwner(displayID, for: key)
            if let existing = route.streamByDisplay[displayID] {
                ownerByDisplay[displayID] = key
                return existing
            }
            guard route.bindingsByStream.count < maximumStreamsPerClient else {
                throw MultiClientDisplayAllocatorError.streamLimitReached(maximumStreamsPerClient)
            }
            guard let streamID = nextAvailableStreamID(in: route) else {
                throw MultiClientDisplayAllocatorError.streamLimitReached(maximumStreamsPerClient)
            }
            bindLocked(
                MultiClientDisplayStreamBinding(displayID: displayID, streamID: streamID),
                route: &route
            )
            routesBySessionID[key.sessionID] = route
            return streamID
        }
    }

    func bind(_ binding: MultiClientDisplayStreamBinding, to key: MultiClientSessionKey) throws {
        try withLock {
            try validate(binding)
            var route = try route(for: key)
            guard !route.reservedStreamIDs.contains(binding.streamID) else {
                throw MultiClientDisplayAllocatorError.invalidBinding
            }
            try validateDisplayOwner(binding.displayID, for: key)
            if let existingStream = route.streamByDisplay[binding.displayID], existingStream != binding.streamID {
                throw MultiClientDisplayAllocatorError.duplicateDisplay(binding.displayID)
            }
            if route.bindingsByStream[binding.streamID] == nil,
               route.bindingsByStream.count >= maximumStreamsPerClient {
                throw MultiClientDisplayAllocatorError.streamLimitReached(maximumStreamsPerClient)
            }
            bindLocked(binding, route: &route)
            routesBySessionID[key.sessionID] = route
        }
    }

    func rebind(streamID: UInt64, toDisplayID displayID: String, in key: MultiClientSessionKey) throws {
        try bind(MultiClientDisplayStreamBinding(displayID: displayID, streamID: streamID), to: key)
    }

    @discardableResult
    func release(streamID: UInt64, in key: MultiClientSessionKey) -> Bool {
        withLock {
            guard isValid(key), streamID > 0 else { return false }
            guard var route = routesBySessionID[key.sessionID], route.key == key else { return false }
            guard let binding = route.bindingsByStream.removeValue(forKey: streamID) else { return false }
            route.streamByDisplay.removeValue(forKey: binding.displayID)
            releaseDisplayOwner(binding.displayID, for: key)
            routesBySessionID[key.sessionID] = route
            return true
        }
    }

    func binding(streamID: UInt64, in key: MultiClientSessionKey) -> MultiClientDisplayStreamBinding? {
        withLock {
            guard isValid(key), streamID > 0 else { return nil }
            guard routesBySessionID[key.sessionID]?.key == key else { return nil }
            return routesBySessionID[key.sessionID]?.bindingsByStream[streamID]
        }
    }

    func disconnect(_ key: MultiClientSessionKey) {
        withLock {
            guard isValid(key) else { return }
            guard let route = routesBySessionID[key.sessionID], route.key == key else { return }
            releaseDisplayOwners(for: route)
            routesBySessionID.removeValue(forKey: key.sessionID)
        }
    }

    private func validate(_ key: MultiClientSessionKey) throws {
        guard isValid(key) else { throw MultiClientDisplayAllocatorError.invalidSession }
    }

    private func isValid(_ key: MultiClientSessionKey) -> Bool {
        !key.sessionID.isEmpty && key.epoch > 0
    }

    private func validate(displayID: String) throws {
        guard !displayID.isEmpty else { throw MultiClientDisplayAllocatorError.invalidBinding }
    }

    private func validate(_ binding: MultiClientDisplayStreamBinding) throws {
        guard binding.streamID > 0 else { throw MultiClientDisplayAllocatorError.invalidBinding }
        try validate(displayID: binding.displayID)
    }

    private func validateReservedStreamIDs(_ streamIDs: Set<UInt64>) throws {
        guard !streamIDs.contains(0) else { throw MultiClientDisplayAllocatorError.invalidBinding }
    }

    private func applyReservedStreamIDs(_ streamIDs: Set<UInt64>, to route: inout ClientRoute) throws {
        let mergedStreamIDs = route.reservedStreamIDs.union(streamIDs)
        guard !route.bindingsByStream.keys.contains(where: { mergedStreamIDs.contains($0) }) else {
            throw MultiClientDisplayAllocatorError.invalidBinding
        }
        route.reservedStreamIDs = mergedStreamIDs
    }

    private func route(for key: MultiClientSessionKey) throws -> ClientRoute {
        guard let route = routesBySessionID[key.sessionID], route.key == key else {
            throw MultiClientDisplayAllocatorError.invalidSession
        }
        return route
    }

    private func bindLocked(_ binding: MultiClientDisplayStreamBinding, route: inout ClientRoute) {
        if let previous = route.bindingsByStream[binding.streamID] {
            route.streamByDisplay.removeValue(forKey: previous.displayID)
            releaseDisplayOwner(previous.displayID, for: route.key)
        }
        route.bindingsByStream[binding.streamID] = binding
        route.streamByDisplay[binding.displayID] = binding.streamID
        ownerByDisplay[binding.displayID] = route.key
        if binding.streamID >= route.nextStreamID {
            route.nextStreamID = binding.streamID == UInt64.max ? UInt64.max : binding.streamID + 1
        }
    }

    private func nextAvailableStreamID(in route: ClientRoute) -> UInt64? {
        var streamID = route.nextStreamID
        let maximumAttempts = max(
            1,
            route.reservedStreamIDs.count + route.bindingsByStream.count + 1
        )
        for _ in 0..<maximumAttempts {
            if route.bindingsByStream[streamID] == nil, !route.reservedStreamIDs.contains(streamID) {
                return streamID
            }
            guard streamID < UInt64.max else { return nil }
            streamID += 1
        }
        return nil
    }

    private func validateDisplayOwner(_ displayID: String, for key: MultiClientSessionKey) throws {
        guard let owner = ownerByDisplay[displayID], owner != key else { return }
        throw MultiClientDisplayAllocatorError.duplicateDisplay(displayID)
    }

    private func releaseDisplayOwners(for route: ClientRoute) {
        for binding in route.bindingsByStream.values {
            releaseDisplayOwner(binding.displayID, for: route.key)
        }
    }

    private func releaseDisplayOwner(_ displayID: String, for key: MultiClientSessionKey) {
        guard ownerByDisplay[displayID] == key else { return }
        ownerByDisplay.removeValue(forKey: displayID)
    }

    private func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try body()
    }
}

typealias HostClientSessionKey = MultiClientSessionKey
typealias HostDisplayStreamBinding = MultiClientDisplayStreamBinding
typealias HostDisplayRouterError = MultiClientDisplayAllocatorError
typealias HostMultiClientDisplayRouter = MultiClientDisplayAllocator
