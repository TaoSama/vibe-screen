import Cocoa
import XCTest
@testable import Telemachus

@MainActor
final class SettingsWindowLifecycleTests: XCTestCase {
    func testClosingWindowReleasesHostingViewAndNotifiesOwnerOnce() {
        let controller = SettingsWindowController(settings: DisplaySettings())
        var closeCount = 0
        controller.onWindowClosed = {
            closeCount += 1
        }

        XCTAssertNotNil(controller.window?.contentView)

        controller.window?.close()
        controller.window?.close()

        XCTAssertNil(controller.window?.contentView)
        XCTAssertNil(controller.window?.delegate)
        XCTAssertEqual(closeCount, 1)
    }
}
