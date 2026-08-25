import Foundation

enum NetworkRecoveryAction: Equatable {
    case restartICE
    case freshSession(String)
    case fail(String)
}

struct NetworkRecoveryPolicy: Equatable {
    static let standard = NetworkRecoveryPolicy(maximumAttempts: 5)

    let maximumAttempts: Int
}

struct NetworkRecoveryStateMachine {
    private(set) var attempt = 0
    private(set) var lastPath: InternetNetworkPath?
    let policy: NetworkRecoveryPolicy

    init(policy: NetworkRecoveryPolicy = .standard) {
        self.policy = policy
    }

    mutating func connected() {
        attempt = 0
    }

    mutating func observePath(_ path: InternetNetworkPath) {
        lastPath = path
    }

    mutating func connectivityLost() -> NetworkRecoveryAction {
        guard attempt < policy.maximumAttempts else {
            return .fail("Network recovery exhausted after \(attempt) attempts.")
        }
        attempt += 1
        return .restartICE
    }

    mutating func pathChanged(
        _ path: InternetNetworkPath,
        requiresFreshSession: Bool = false
    ) -> NetworkRecoveryAction? {
        defer { lastPath = path }
        guard path.isSatisfied else { return nil }
        guard let previous = lastPath else { return nil }
        guard previous.fingerprint != path.fingerprint else { return nil }
        guard attempt < policy.maximumAttempts else {
            return .fail("Network recovery exhausted after \(attempt) attempts.")
        }
        attempt += 1
        if requiresFreshSession {
            return .freshSession(
                "Network path changed from \(previous.fingerprint) to \(path.fingerprint); fresh signaling session required."
            )
        }
        return .restartICE
    }
}
