import Foundation

enum UnattendedRecoveryPolicy {
    static let maximumAttempts = 8
    private static let maximumDelay: TimeInterval = 30

    static func delay(afterFailure attempt: Int) -> TimeInterval? {
        guard attempt >= 0, attempt < maximumAttempts else { return nil }
        return min(pow(2, Double(attempt)), maximumDelay)
    }
}
