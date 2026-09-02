import Foundation

enum InternetSessionProfileAutomationError: Error, Equatable, LocalizedError {
    case invalidRequestID
    case exhaustedEpoch

    var errorDescription: String? {
        switch self {
        case .invalidRequestID:
            return "The generated Authority session-profile request ID is invalid."
        case .exhaustedEpoch:
            return "The authoritative session epoch is exhausted. Pair the device again."
        }
    }
}

struct InternetSessionProfileAutomation {
    typealias RequestIDFactory = () -> String

    private let requestIDFactory: RequestIDFactory

    init(requestIDFactory: @escaping RequestIDFactory = Self.defaultRequestID) {
        self.requestIDFactory = requestIDFactory
    }

    func initialRequest(
        persistedRequestID: String,
        persistedEpoch: UInt64,
        durableEpoch: UInt64
    ) throws -> InternetSessionProfileAutomationPlan {
        let persistedRequestID = persistedRequestID.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        let baseline = max(persistedEpoch, durableEpoch)
        guard baseline <= SecurityLifecycle.maximumCrossPlatformSessionEpoch else {
            throw InternetSessionProfileAutomationError.exhaustedEpoch
        }
        if Self.isValidAuthorityIdentifier(persistedRequestID),
           persistedEpoch > durableEpoch {
            return InternetSessionProfileAutomationPlan(
                requestID: persistedRequestID,
                authoritativeSessionEpoch: persistedEpoch
            )
        }
        return try nextRequest(after: baseline)
    }

    func refreshRequest(
        currentEpoch: UInt64,
        persistedEpoch: UInt64,
        durableEpoch: UInt64
    ) throws -> InternetSessionProfileAutomationPlan {
        try nextRequest(after: max(currentEpoch, persistedEpoch, durableEpoch))
    }

    private func nextRequest(after baseline: UInt64) throws -> InternetSessionProfileAutomationPlan {
        guard baseline < SecurityLifecycle.maximumCrossPlatformSessionEpoch else {
            throw InternetSessionProfileAutomationError.exhaustedEpoch
        }
        let requestID = requestIDFactory().trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        guard Self.isValidAuthorityIdentifier(requestID) else {
            throw InternetSessionProfileAutomationError.invalidRequestID
        }
        return InternetSessionProfileAutomationPlan(
            requestID: requestID,
            authoritativeSessionEpoch: baseline + 1
        )
    }

    private static func defaultRequestID() -> String {
        "authority-" + UUID().uuidString.lowercased()
    }

    private static func isValidAuthorityIdentifier(_ value: String) -> Bool {
        guard (1...128).contains(value.utf8.count) else { return false }
        return value.unicodeScalars.allSatisfy { scalar in
            switch scalar.value {
            case 45, 46, 48...57, 65...90, 95, 97...122:
                return true
            default:
                return false
            }
        }
    }
}

struct InternetSessionProfileAutomationPlan: Equatable {
    let requestID: String
    let authoritativeSessionEpoch: UInt64
}
