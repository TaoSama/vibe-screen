import Darwin
import Foundation

enum SingleInstanceProcessLockError: Error, LocalizedError {
    case alreadyRunning
    case fileSystem(String)

    var errorDescription: String? {
        switch self {
        case .alreadyRunning: return "Another Telemachus process is already running."
        case .fileSystem(let reason): return "Could not acquire the Telemachus process lock: \(reason)"
        }
    }
}

final class SingleInstanceProcessLock {
    private let descriptor: Int32

    private init(descriptor: Int32) {
        self.descriptor = descriptor
    }

    static func acquireDefault() throws -> SingleInstanceProcessLock {
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Telemachus", isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        return try acquire(at: directory.appendingPathComponent("instance.lock"))
    }

    static func acquire(at url: URL) throws -> SingleInstanceProcessLock {
        let descriptor = open(url.path, O_CREAT | O_RDWR | O_CLOEXEC, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else {
            throw SingleInstanceProcessLockError.fileSystem(String(cString: strerror(errno)))
        }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            let failure = errno
            close(descriptor)
            if failure == EWOULDBLOCK {
                throw SingleInstanceProcessLockError.alreadyRunning
            }
            throw SingleInstanceProcessLockError.fileSystem(String(cString: strerror(failure)))
        }
        return SingleInstanceProcessLock(descriptor: descriptor)
    }

    deinit {
        _ = flock(descriptor, LOCK_UN)
        close(descriptor)
    }
}
