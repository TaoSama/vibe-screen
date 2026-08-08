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

final class TestProcessOutputDrain {
    private let group = DispatchGroup()
    private let lock = NSLock()
    private var output = Data()
    private var error = Data()

    static func start(output: Pipe, error: Pipe) -> TestProcessOutputDrain {
        let drain = TestProcessOutputDrain()
        drain.start(output: output.fileHandleForReading, error: error.fileHandleForReading)
        return drain
    }

    func finish(timeout: TimeInterval) -> (output: Data, error: Data)? {
        guard group.wait(timeout: .now() + max(0, timeout)) == .success else { return nil }
        lock.lock()
        defer { lock.unlock() }
        return (output, error)
    }

    private func start(output outputHandle: FileHandle, error errorHandle: FileHandle) {
        group.enter()
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let data = outputHandle.readDataToEndOfFile()
            self?.lock.lock()
            self?.output = data
            self?.lock.unlock()
            self?.group.leave()
        }
        group.enter()
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let data = errorHandle.readDataToEndOfFile()
            self?.lock.lock()
            self?.error = data
            self?.lock.unlock()
            self?.group.leave()
        }
    }
}
