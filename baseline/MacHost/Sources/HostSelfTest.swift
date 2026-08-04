import CoreGraphics
import Foundation

enum HostSelfTest {
    static func run() -> Bool {
        var failures: [String] = []

        let mapped = WindowPlacement.mappedFrame(
            CGRect(x: 100, y: 100, width: 800, height: 600),
            from: CGRect(x: 0, y: 0, width: 1920, height: 1080),
            to: CGRect(x: 1920, y: 0, width: 1200, height: 800)
        )
        if mapped.minX < 1920 || mapped.maxX > 3120 ||
            mapped.minY < 0 || mapped.maxY > 800 {
            failures.append("mapped window escaped target display")
        }

        let oversized = WindowPlacement.mappedFrame(
            CGRect(x: 0, y: 0, width: 3000, height: 2000),
            from: CGRect(x: 0, y: 0, width: 1920, height: 1080),
            to: CGRect(x: -1200, y: 0, width: 1200, height: 800)
        )
        if oversized != CGRect(x: -1200, y: 0, width: 1200, height: 800) {
            failures.append("oversized window was not clamped to target display")
        }

        let expectedDelays: [TimeInterval?] = [1, 2, 4, 8, 16, 30, 30, 30, nil]
        let actualDelays = (0...UnattendedRecoveryPolicy.maximumAttempts).map {
            UnattendedRecoveryPolicy.delay(afterFailure: $0)
        }
        if actualDelays != expectedDelays {
            failures.append("unattended recovery backoff differs from policy")
        }

        let displays = DisplayCatalog.onlineDisplays()
        if displays.isEmpty {
            failures.append("online display catalog is empty")
        }
        if DisplayCatalog.resolve(CGDirectDisplayID.max) != CGMainDisplayID() {
            failures.append("missing display did not fall back to main display")
        }

        if failures.isEmpty {
            print(
                "Host self-test: PASS (display catalog, window placement, " +
                "bounded recovery backoff)"
            )
            return true
        }
        print("Host self-test: FAIL (\(failures.joined(separator: "; ")))")
        return false
    }
}
