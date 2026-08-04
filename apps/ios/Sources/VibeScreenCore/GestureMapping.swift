import Foundation

public enum GestureTrigger: String, Codable, CaseIterable, Sendable {
    case doubleTap
    case longPress
    case twoFingerTap
    case threeFingerSwipeUp
    case threeFingerSwipeDown
}

public enum GestureAction: Codable, Equatable, Sendable {
    case toggleControls
    case showKeyboard
    case switchDisplay
    case invokeHostAction(String)
}

public struct GestureMapping: Codable, Equatable, Sendable {
    public let trigger: GestureTrigger
    public let action: GestureAction

    public init(trigger: GestureTrigger, action: GestureAction) {
        self.trigger = trigger
        self.action = action
    }
}

public enum GestureMappingError: Error, Equatable {
    case policyDenied
    case duplicateTrigger(GestureTrigger)
    case unavailableHostAction(String)
}

public struct GestureProfile: Codable, Equatable, Sendable {
    public var mappings: [GestureMapping]

    public init(mappings: [GestureMapping]) {
        self.mappings = mappings
    }

    public func validated(
        availableHostActions: Set<String>,
        policy: ManagedPolicy
    ) throws -> GestureProfile {
        guard policy.customGesturesAllowed else { throw GestureMappingError.policyDenied }
        var seen: Set<GestureTrigger> = []
        for mapping in mappings {
            guard seen.insert(mapping.trigger).inserted else {
                throw GestureMappingError.duplicateTrigger(mapping.trigger)
            }
            if case let .invokeHostAction(identifier) = mapping.action,
               !availableHostActions.contains(identifier) {
                throw GestureMappingError.unavailableHostAction(identifier)
            }
        }
        return self
    }

    public static let defaults = GestureProfile(mappings: [
        GestureMapping(trigger: .doubleTap, action: .toggleControls),
        GestureMapping(trigger: .twoFingerTap, action: .showKeyboard),
        GestureMapping(trigger: .threeFingerSwipeUp, action: .switchDisplay),
    ])
}
