import Darwin
import Foundation

enum TestProcessDeadline {
    private static let pollInterval: TimeInterval = 0.01

    static func waitForExit(
        _ process: Process,
        timeout: TimeInterval,
        terminationGrace: TimeInterval
    ) -> Bool {
        if waitUntilStopped(process, timeout: timeout) {
            process.waitUntilExit()
            return true
        }
        _ = terminateAndReap(process, terminationGrace: terminationGrace)
        return false
    }

    @discardableResult
    static func terminateAndReap(
        _ process: Process,
        terminationGrace: TimeInterval
    ) -> Bool {
        if process.isRunning {
            process.terminate()
        }
        if !waitUntilStopped(process, timeout: terminationGrace), process.isRunning {
            _ = Darwin.kill(process.processIdentifier, SIGKILL)
        }
        guard waitUntilStopped(process, timeout: terminationGrace) else {
            return false
        }
        process.waitUntilExit()
        return true
    }

    private static func waitUntilStopped(
        _ process: Process,
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(max(0, timeout))
        while process.isRunning, Date() < deadline {
            Thread.sleep(forTimeInterval: pollInterval)
        }
        return !process.isRunning
    }
}
