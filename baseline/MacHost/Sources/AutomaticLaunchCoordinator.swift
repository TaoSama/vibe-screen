import Foundation

@MainActor
final class AutomaticLaunchCoordinator {
    enum State: Equatable {
        case disabled
        case pending
        case consumed
    }

    private(set) var state: State

    init(enabled: Bool) {
        state = enabled ? .pending : .disabled
    }

    func consumeIfEligible(_ eligible: Bool) -> Bool {
        guard state == .pending, eligible else { return false }
        state = .consumed
        return true
    }
}
