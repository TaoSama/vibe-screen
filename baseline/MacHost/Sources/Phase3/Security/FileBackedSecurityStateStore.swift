import CryptoKit
import Foundation

/// File-backed durable security state store used only for cross-process
/// engineering tests that must exercise the real cross-process transaction
/// lock and the monotonic-epoch lifecycle without depending on securityd.
///
/// Production lease issuance always uses the Keychain-backed store; this store
/// is selected exclusively when `InternetSessionLeaseTestBackends` detects the
/// dedicated test environment variable. It reuses the same
/// `KeychainCrossProcessTransactionLock` flock so mutual exclusion and epoch
/// monotonicity are validated identically to production, while the in-lock work
/// is a small local JSON file instead of a securityd round-trip. On a headless
/// CI runner concurrent securityd access under the lock could stall one holder
/// and starve the rest; local file IO cannot.
struct FileBackedSecurityStateStore: SecurityStateStore {
    private let stateFileURL: URL
    private let lockService: String
    private let lockAccount: String

    init(directory: URL, scope: String) throws {
        guard !scope.isEmpty else {
            throw PlatformSecurityError.invalidInput(
                "A non-empty pairing scope is required for the file-backed security state store."
            )
        }
        let digest = SHA256.hash(data: Data(scope.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
        } catch {
            throw PlatformSecurityError.persistenceFailure(
                "Unable to prepare the file-backed security state directory: \(error.localizedDescription)"
            )
        }
        stateFileURL = directory.appendingPathComponent("\(digest).state.json", isDirectory: false)
        // Bind the cross-process lock to the same scope so every process that
        // shares this authority serializes on one flock, exactly as production
        // does for a shared Keychain account.
        lockService = "dev.telemachus.display.phase3-file-state"
        lockAccount = digest
    }

    func withExclusiveTransaction<T>(_ operation: () throws -> T) throws -> T {
        try KeychainCrossProcessTransactionLock.withLock(
            service: lockService,
            account: lockAccount,
            operation: operation
        )
    }

    func load() throws -> PersistedSecurityState {
        guard let data = try readStateData() else { return PersistedSecurityState() }
        do {
            return try JSONDecoder().decode(PersistedSecurityState.self, from: data)
        } catch {
            throw PlatformSecurityError.persistenceFailure(
                "Stored file-backed security state is invalid: \(error.localizedDescription)"
            )
        }
    }

    func persist(_ state: PersistedSecurityState) throws {
        let data: Data
        do {
            data = try JSONEncoder().encode(state)
        } catch {
            throw PlatformSecurityError.persistenceFailure(
                "Unable to encode file-backed security state: \(error.localizedDescription)"
            )
        }
        do {
            try data.write(to: stateFileURL, options: .atomic)
        } catch {
            throw PlatformSecurityError.persistenceFailure(
                "Unable to write file-backed security state: \(error.localizedDescription)"
            )
        }
    }

    private func readStateData() throws -> Data? {
        guard FileManager.default.fileExists(atPath: stateFileURL.path) else { return nil }
        do {
            return try Data(contentsOf: stateFileURL)
        } catch {
            throw PlatformSecurityError.persistenceFailure(
                "Unable to read file-backed security state: \(error.localizedDescription)"
            )
        }
    }
}

/// Resolves the durable state store backend for the lease issuer CLI.
///
/// Defaults to the Keychain-backed store. When `VIBE_LEASE_FILE_STATE_DIR` is
/// set (engineering cross-process tests only), it routes durable state to a
/// file under that directory. Nothing else about lease issuance changes: the
/// paired identity and secret bindings still come from the Keychain.
enum InternetSessionLeaseTestBackends {
    static let fileStateDirectoryEnvironmentKey = "VIBE_LEASE_FILE_STATE_DIR"

    static func stateStoreFactory(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> InternetSessionLeaseIssuer.StateStoreFactory {
        guard let directoryPath = environment[fileStateDirectoryEnvironmentKey],
              !directoryPath.isEmpty else {
            return { scope in
                KeychainSecurityStateStore(peerID: "lease-authority.\(scope)")
            }
        }
        let directory = URL(fileURLWithPath: directoryPath, isDirectory: true)
        return { scope in
            do {
                return try FileBackedSecurityStateStore(directory: directory, scope: scope)
            } catch {
                // Fail closed to the Keychain store rather than silently losing
                // durability if the file backend cannot be prepared.
                return KeychainSecurityStateStore(peerID: "lease-authority.\(scope)")
            }
        }
    }
}

