import Foundation

enum GestureHostActionTrigger: Equatable {
    case threeFingerSwipeUp
    case threeFingerSwipeDown
}

enum GestureHostActionMappingAction: Equatable {
    case `default`
    case deny
    case invokeHostAction(String)
}

struct GestureHostActionMapping: Equatable {
    let trigger: GestureHostActionTrigger
    let action: GestureHostActionMappingAction

    init(trigger: GestureHostActionTrigger, action: GestureHostActionMappingAction) {
        self.trigger = trigger
        self.action = action
    }
}

struct GestureHostActionProfile: Equatable {
    var mappings: [GestureHostActionMapping]

    init(mappings: [GestureHostActionMapping] = []) {
        self.mappings = mappings
    }

    static let `default` = GestureHostActionProfile()
}

struct GestureHostActionPolicyContext: Equatable {
    var customGesturesAllowed: Bool
    var hostActionsAllowed: Bool
    var hostActionsNegotiated: Bool
    var availableHostActionIds: Set<String>

    init(
        customGesturesAllowed: Bool,
        hostActionsAllowed: Bool,
        hostActionsNegotiated: Bool,
        availableHostActionIds: Set<String>
    ) {
        self.customGesturesAllowed = customGesturesAllowed
        self.hostActionsAllowed = hostActionsAllowed
        self.hostActionsNegotiated = hostActionsNegotiated
        self.availableHostActionIds = availableHostActionIds
    }
}

enum GestureHostActionDecision: Equatable {
    case `default`
    case denied
    case invokeHostAction(String)
}

enum GestureHostActionPolicy {
    static func shouldInterceptThreeFingerGestures(profile: GestureHostActionProfile) -> Bool {
        profile.mappings.contains { mapping in
            switch mapping.action {
            case .default:
                return false
            case .deny, .invokeHostAction:
                return true
            }
        }
    }

    static func resolve(
        trigger: GestureHostActionTrigger,
        profile: GestureHostActionProfile,
        context: GestureHostActionPolicyContext
    ) -> GestureHostActionDecision {
        let matches = profile.mappings.filter { $0.trigger == trigger }
        guard matches.count <= 1 else { return .denied }
        guard let mapping = matches.first else {
            return .default
        }

        switch mapping.action {
        case .default:
            return .default
        case .deny:
            return .denied
        case .invokeHostAction(let actionID):
            guard context.customGesturesAllowed,
                  context.hostActionsAllowed,
                  context.hostActionsNegotiated,
                  context.availableHostActionIds.contains(actionID) else {
                return .denied
            }
            return .invokeHostAction(actionID)
        }
    }
}
