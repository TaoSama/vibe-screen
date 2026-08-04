import Foundation
import XCTest
@testable import Telemachus

final class SingleInstanceProcessLockTests: XCTestCase {
    func testSecondLockFailsClosedUntilFirstIsReleased() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("telemachus-lock-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("instance.lock")

        var first: SingleInstanceProcessLock? = try .acquire(at: url)
        XCTAssertThrowsError(try SingleInstanceProcessLock.acquire(at: url)) { error in
            guard case SingleInstanceProcessLockError.alreadyRunning = error else {
                return XCTFail("Expected an already-running failure, got \(error)")
            }
        }
        first = nil
        XCTAssertNoThrow(try SingleInstanceProcessLock.acquire(at: url))
    }
}
