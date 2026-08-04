import AppKit
import ApplicationServices

enum WindowRecoveryError: LocalizedError {
    case accessibilityPermissionRequired
    case noFocusedWindow
    case displayUnavailable(CGDirectDisplayID)
    case attributeRead(String, AXError)
    case attributeWrite(String, AXError)

    var errorDescription: String? {
        switch self {
        case .accessibilityPermissionRequired:
            return "Accessibility permission is required to move Mac windows."
        case .noFocusedWindow:
            return "No movable focused window was found."
        case .displayUnavailable(let displayID):
            return "Display \(displayID) is no longer available."
        case .attributeRead(let attribute, let error):
            return "Could not read \(attribute) from the window (AX error \(error.rawValue))."
        case .attributeWrite(let attribute, let error):
            return "Could not update \(attribute) on the window (AX error \(error.rawValue))."
        }
    }
}

struct WindowRecoveryReport {
    let restoredCount: Int
    let failedDescriptions: [String]
}

/// Owns window placement only. Display lifecycle and connection state remain in
/// their respective adapters; callers explicitly invoke recovery before a
/// client display disappears or immediately after the client disconnects.
final class WindowRecoveryManager {
    private struct ManagedWindow {
        let element: AXUIElement
        let originalFrame: CGRect
        let originalDisplayBounds: CGRect
        let originalDisplayUUID: String?
    }

    private var managedWindows: [CFHashCode: ManagedWindow] = [:]

    func moveFocusedWindow(to displayID: CGDirectDisplayID) throws {
        guard AXIsProcessTrusted() else {
            throw WindowRecoveryError.accessibilityPermissionRequired
        }
        guard CGDisplayIsOnline(displayID) != 0 else {
            throw WindowRecoveryError.displayUnavailable(displayID)
        }

        let systemWide = AXUIElementCreateSystemWide()
        let application = try elementAttribute(
            kAXFocusedApplicationAttribute as CFString,
            from: systemWide
        )
        let window = try elementAttribute(
            kAXFocusedWindowAttribute as CFString,
            from: application
        )
        let originalFrame = try frame(of: window)
        let sourceDisplay = displayTarget(containing: originalFrame.center)
            ?? DisplayRecoveryTarget(
                persistentUUID: DisplayCatalog.persistentUUID(
                    for: CGMainDisplayID()
                ),
                bounds: CGDisplayBounds(CGMainDisplayID())
            )
        let sourceBounds = sourceDisplay.bounds
        let key = CFHash(window)
        if managedWindows[key] == nil {
            managedWindows[key] = ManagedWindow(
                element: window,
                originalFrame: originalFrame,
                originalDisplayBounds: sourceBounds,
                originalDisplayUUID: sourceDisplay.persistentUUID
            )
        }

        let targetBounds = CGDisplayBounds(displayID)
        try setFrame(
            WindowPlacement.mappedFrame(
                originalFrame,
                from: sourceBounds,
                to: targetBounds
            ),
            for: window
        )
    }

    func restoreManagedWindows() -> WindowRecoveryReport {
        var restoredCount = 0
        var failures: [String] = []
        let onlineDisplays = allOnlineDisplayTargets()
        let mainBounds = CGDisplayBounds(CGMainDisplayID())
        for (_, managedWindow) in managedWindows {
            do {
                let recoveryFrame = WindowPlacement.recoveryFrame(
                    managedWindow.originalFrame,
                    originalDisplayBounds: managedWindow.originalDisplayBounds,
                    originalDisplayUUID: managedWindow.originalDisplayUUID,
                    onlineDisplays: onlineDisplays,
                    mainDisplayBounds: mainBounds
                )
                try setFrame(recoveryFrame, for: managedWindow.element)
                restoredCount += 1
            } catch {
                failures.append(error.localizedDescription)
            }
        }
        managedWindows.removeAll()
        return WindowRecoveryReport(
            restoredCount: restoredCount,
            failedDescriptions: failures
        )
    }

    private func elementAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) throws -> AXUIElement {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, attribute, &value)
        guard result == .success, let value else {
            if result == .noValue || result == .attributeUnsupported {
                throw WindowRecoveryError.noFocusedWindow
            }
            throw WindowRecoveryError.attributeRead(attribute as String, result)
        }
        return unsafeBitCast(value, to: AXUIElement.self)
    }

    private func frame(of window: AXUIElement) throws -> CGRect {
        var positionValue: CFTypeRef?
        var sizeValue: CFTypeRef?
        let positionResult = AXUIElementCopyAttributeValue(
            window,
            kAXPositionAttribute as CFString,
            &positionValue
        )
        guard positionResult == .success,
              let positionValue,
              CFGetTypeID(positionValue) == AXValueGetTypeID() else {
            throw WindowRecoveryError.attributeRead(kAXPositionAttribute, positionResult)
        }
        let sizeResult = AXUIElementCopyAttributeValue(
            window,
            kAXSizeAttribute as CFString,
            &sizeValue
        )
        guard sizeResult == .success,
              let sizeValue,
              CFGetTypeID(sizeValue) == AXValueGetTypeID() else {
            throw WindowRecoveryError.attributeRead(kAXSizeAttribute, sizeResult)
        }

        var position = CGPoint.zero
        var size = CGSize.zero
        guard AXValueGetValue(positionValue as! AXValue, .cgPoint, &position),
              AXValueGetValue(sizeValue as! AXValue, .cgSize, &size) else {
            throw WindowRecoveryError.noFocusedWindow
        }
        return CGRect(origin: position, size: size)
    }

    private func setFrame(_ frame: CGRect, for window: AXUIElement) throws {
        var position = frame.origin
        var size = frame.size
        guard let positionValue = AXValueCreate(.cgPoint, &position),
              let sizeValue = AXValueCreate(.cgSize, &size) else {
            throw WindowRecoveryError.noFocusedWindow
        }
        let sizeResult = AXUIElementSetAttributeValue(
            window,
            kAXSizeAttribute as CFString,
            sizeValue
        )
        guard sizeResult == .success else {
            throw WindowRecoveryError.attributeWrite(kAXSizeAttribute, sizeResult)
        }
        let positionResult = AXUIElementSetAttributeValue(
            window,
            kAXPositionAttribute as CFString,
            positionValue
        )
        guard positionResult == .success else {
            throw WindowRecoveryError.attributeWrite(kAXPositionAttribute, positionResult)
        }
    }

    private func displayTarget(containing point: CGPoint) -> DisplayRecoveryTarget? {
        allOnlineDisplayTargets().first(where: { $0.bounds.contains(point) })
    }

    private func allOnlineDisplayTargets() -> [DisplayRecoveryTarget] {
        var displayCount: UInt32 = 0
        guard CGGetOnlineDisplayList(0, nil, &displayCount) == .success,
              displayCount > 0 else { return [] }
        var displayIDs = [CGDirectDisplayID](repeating: 0, count: Int(displayCount))
        guard CGGetOnlineDisplayList(
            displayCount,
            &displayIDs,
            &displayCount
        ) == .success else { return [] }
        return displayIDs
            .prefix(Int(displayCount))
            .map { displayID in
                DisplayRecoveryTarget(
                    persistentUUID: DisplayCatalog.persistentUUID(
                        for: displayID
                    ),
                    bounds: CGDisplayBounds(displayID)
                )
            }
    }
}

struct DisplayRecoveryTarget: Equatable {
    let persistentUUID: String?
    let bounds: CGRect
}

enum WindowPlacement {
    static func recoveryFrame(
        _ originalFrame: CGRect,
        originalDisplayBounds: CGRect,
        originalDisplayUUID: String?,
        onlineDisplays: [DisplayRecoveryTarget],
        mainDisplayBounds: CGRect
    ) -> CGRect {
        let originalDisplay: DisplayRecoveryTarget?
        if let originalDisplayUUID {
            originalDisplay = onlineDisplays.first(where: {
                $0.persistentUUID == originalDisplayUUID
            })
        } else {
            originalDisplay = onlineDisplays.first(where: {
                $0.bounds.intersects(originalFrame) &&
                    $0.bounds.intersects(originalDisplayBounds)
            })
        }
        if let originalDisplay {
            if originalDisplay.bounds == originalDisplayBounds {
                return originalFrame
            }
            return mappedFrame(
                originalFrame,
                from: originalDisplayBounds,
                to: originalDisplay.bounds
            )
        }
        return mappedFrame(
            originalFrame,
            from: originalDisplayBounds,
            to: mainDisplayBounds
        )
    }

    static func mappedFrame(
        _ frame: CGRect,
        from source: CGRect,
        to target: CGRect
    ) -> CGRect {
        guard source.width > 0, source.height > 0,
              target.width > 0, target.height > 0 else { return frame }

        let width = min(frame.width, target.width)
        let height = min(frame.height, target.height)
        let relativeX = (frame.midX - source.minX) / source.width
        let relativeY = (frame.midY - source.minY) / source.height
        let desiredOrigin = CGPoint(
            x: target.minX + relativeX * target.width - width / 2,
            y: target.minY + relativeY * target.height - height / 2
        )
        return CGRect(
            x: min(max(desiredOrigin.x, target.minX), target.maxX - width),
            y: min(max(desiredOrigin.y, target.minY), target.maxY - height),
            width: width,
            height: height
        )
    }
}

private extension CGRect {
    var center: CGPoint {
        CGPoint(x: midX, y: midY)
    }
}
