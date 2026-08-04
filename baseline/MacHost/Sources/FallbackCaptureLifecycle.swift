import CoreGraphics
import Foundation

enum FallbackFrameDisposition: Equatable {
    case consume
    case ignore
    case clearFrame
    case terminalFailure
}

enum FallbackStoppedAction: Equatable {
    case rebuild(CGDirectDisplayID)
    case terminalFailure
}

enum FallbackStoppedPolicy {
    static func action(
        followsMainDisplay: Bool,
        capturedDisplayID: CGDirectDisplayID?,
        currentMainDisplayID: CGDirectDisplayID
    ) -> FallbackStoppedAction {
        guard followsMainDisplay,
              currentMainDisplayID != 0,
              currentMainDisplayID != capturedDisplayID else {
            return .terminalFailure
        }
        return .rebuild(currentMainDisplayID)
    }
}

final class FallbackCaptureLifecycle: @unchecked Sendable {
    enum BeginResult: Equatable {
        case started(UInt64)
        case alreadyActive
    }

    private struct State {
        var generation: UInt64 = 0
        var activeGeneration: UInt64?
        var terminalPendingGeneration: UInt64?
    }

    private let lock = NSLock()
    private var state = State()

    var isActive: Bool {
        lock.withLock { state.activeGeneration != nil }
    }

    func begin() -> BeginResult {
        lock.withLock {
            guard state.activeGeneration == nil else { return .alreadyActive }
            state.generation &+= 1
            state.activeGeneration = state.generation
            return .started(state.generation)
        }
    }

    func invalidate() {
        lock.withLock {
            state.generation &+= 1
            state.activeGeneration = nil
            state.terminalPendingGeneration = nil
        }
    }

    func disposition(
        status: CGDisplayStreamFrameStatus,
        generation: UInt64,
        hasSurface: Bool
    ) -> FallbackFrameDisposition {
        lock.withLock {
            guard state.activeGeneration == generation else { return .ignore }
            switch status {
            case .stopped:
                guard state.terminalPendingGeneration == nil else {
                    return .ignore
                }
                state.terminalPendingGeneration = generation
                return .terminalFailure
            case .frameComplete:
                return hasSurface ? .consume : .ignore
            case .frameBlank:
                return .clearFrame
            case .frameIdle:
                return .ignore
            @unknown default:
                return .ignore
            }
        }
    }

    func claimTerminal(generation: UInt64) -> Bool {
        lock.withLock {
            guard state.activeGeneration == generation,
                  state.terminalPendingGeneration == generation else {
                return false
            }
            state.activeGeneration = nil
            state.terminalPendingGeneration = nil
            return true
        }
    }
}
