import CryptoKit
import Foundation
import VibeScreenProtocol

struct ProtocolV1FileTransferPolicy: Equatable {
    static let defaultMaximumFileBytes: UInt64 = 512 * 1_024 * 1_024
    static let `default` = ProtocolV1FileTransferPolicy()

    let allowed: Bool
    let maximumFileBytes: UInt64
    let maximumChunkBytes: Int
    let maximumConcurrentTransfers: Int
    let maximumTotalTemporaryBytes: UInt64

    init(
        allowed: Bool = true,
        maximumFileBytes: UInt64 = Self.defaultMaximumFileBytes,
        maximumChunkBytes: Int = 64 * 1_024,
        maximumConcurrentTransfers: Int = 1,
        maximumTotalTemporaryBytes: UInt64 = 768 * 1_024 * 1_024
    ) {
        precondition(maximumChunkBytes > 0)
        precondition(maximumConcurrentTransfers > 0)
        self.allowed = allowed
        self.maximumFileBytes = maximumFileBytes
        self.maximumChunkBytes = maximumChunkBytes
        self.maximumConcurrentTransfers = maximumConcurrentTransfers
        self.maximumTotalTemporaryBytes = maximumTotalTemporaryBytes
    }

    var resourceLimits: VSResourceLimits {
        var limits = VSResourceLimits()
        limits.maximumFileBytes = maximumFileBytes
        limits.maximumFileChunkBytes = UInt32(clamping: maximumChunkBytes)
        return limits
    }

    func applying(remote: ProtocolV1RemoteManagedPolicy) -> ProtocolV1FileTransferPolicy {
        guard remote.managed else { return self }
        return ProtocolV1FileTransferPolicy(
            allowed: allowed && remote.fileTransferAllowed,
            maximumFileBytes: min(maximumFileBytes, remote.maximumFileBytes),
            maximumChunkBytes: maximumChunkBytes,
            maximumConcurrentTransfers: maximumConcurrentTransfers,
            maximumTotalTemporaryBytes: maximumTotalTemporaryBytes
        )
    }

    func negotiated(with peer: VSResourceLimits) -> ProtocolV1FileTransferPolicy {
        let peerMaximumFileBytes = peer.maximumFileBytes == 0 ? maximumFileBytes : peer.maximumFileBytes
        let peerMaximumChunkBytes = peer.maximumFileChunkBytes == 0
            ? maximumChunkBytes
            : Int(peer.maximumFileChunkBytes)
        return ProtocolV1FileTransferPolicy(
            allowed: allowed,
            maximumFileBytes: min(maximumFileBytes, peerMaximumFileBytes),
            maximumChunkBytes: max(1, min(maximumChunkBytes, peerMaximumChunkBytes)),
            maximumConcurrentTransfers: maximumConcurrentTransfers,
            maximumTotalTemporaryBytes: maximumTotalTemporaryBytes
        )
    }
}

struct ProtocolV1RemoteManagedPolicy: Equatable {
    static let unmanaged = ProtocolV1RemoteManagedPolicy(
        managed: false,
        fileTransferAllowed: true,
        maximumFileBytes: ProtocolV1FileTransferPolicy.defaultMaximumFileBytes
    )

    let managed: Bool
    let fileTransferAllowed: Bool
    let maximumFileBytes: UInt64

    init(status: VSManagedPolicyStatus) {
        if status.managed {
            managed = true
            fileTransferAllowed = status.fileTransferAllowed
            maximumFileBytes = status.maximumFileBytes
        } else {
            self = .unmanaged
        }
    }

    private init(managed: Bool, fileTransferAllowed: Bool, maximumFileBytes: UInt64) {
        self.managed = managed
        self.fileTransferAllowed = fileTransferAllowed
        self.maximumFileBytes = maximumFileBytes
    }
}

struct ProtocolV1FileChunk: Equatable {
    static let maximumHeaderBytes = 64 * 1_024

    let header: VSFileChunkHeader
    let payload: Data

    init(header: VSFileChunkHeader, payload: Data) {
        self.header = header
        self.payload = payload
    }

    init(serializedFrame: Data) throws {
        var cursor = 0
        let headerLength = try Self.decodeVarint(serializedFrame, cursor: &cursor)
        guard headerLength > 0, headerLength <= Self.maximumHeaderBytes else {
            throw ProtocolV1FileTransferError.invalidChunkHeader
        }
        guard headerLength <= serializedFrame.count - cursor else {
            throw ProtocolV1FileTransferError.invalidChunkHeader
        }
        header = try VSFileChunkHeader(
            serializedBytes: serializedFrame.dropFirst(cursor).prefix(headerLength)
        )
        payload = Data(serializedFrame.dropFirst(cursor + headerLength))
        guard payload.count == Int(header.payloadLength) else {
            throw ProtocolV1FileTransferError.chunkLengthMismatch
        }
        guard header.chunkSha256.count == SHA256.byteCount else {
            throw ProtocolV1FileTransferError.invalidDigest
        }
        guard Data(SHA256.hash(data: payload)) == header.chunkSha256 else {
            throw ProtocolV1FileTransferError.chunkDigestMismatch
        }
    }

    func serializedFrame() throws -> Data {
        var header = header
        header.payloadLength = UInt32(payload.count)
        header.chunkSha256 = Data(SHA256.hash(data: payload))
        let headerBytes = try header.serializedData()
        guard headerBytes.count <= Self.maximumHeaderBytes else {
            throw ProtocolV1FileTransferError.invalidChunkHeader
        }
        var result = Self.encodeVarint(headerBytes.count)
        result.append(headerBytes)
        result.append(payload)
        return result
    }

    private static func encodeVarint(_ value: Int) -> Data {
        var remaining = UInt64(value)
        var result = Data()
        repeat {
            var byte = UInt8(remaining & 0x7f)
            remaining >>= 7
            if remaining != 0 { byte |= 0x80 }
            result.append(byte)
        } while remaining != 0
        return result
    }

    private static func decodeVarint(_ data: Data, cursor: inout Int) throws -> Int {
        var value = 0
        var shift = 0
        while cursor < data.count, shift <= 28 {
            let byte = data[data.index(data.startIndex, offsetBy: cursor)]
            cursor += 1
            value |= Int(byte & 0x7f) << shift
            if byte & 0x80 == 0 { return value }
            shift += 7
        }
        throw ProtocolV1FileTransferError.invalidChunkHeader
    }
}

struct ProtocolV1CompletedIncomingFile: Equatable {
    let transferID: Data
    let fileName: String
    let mimeType: String
    let stagingURL: URL
    let sha256: Data
}

enum ProtocolV1FileTransferError: Error, Equatable {
    case policyDenied
    case userDenied
    case invalidTransferID
    case invalidFileName
    case invalidDigest
    case fileTooLarge(UInt64)
    case concurrentLimitReached
    case temporarySpaceLimitReached
    case duplicateTransfer
    case unknownTransfer
    case invalidChunkHeader
    case chunkTooLarge(Int)
    case chunkLengthMismatch
    case chunkDigestMismatch
    case emptyChunk
    case staleSessionEpoch(expected: UInt64, actual: UInt64)
    case unexpectedOffset(expected: UInt64, actual: UInt64)
    case exceedsDeclaredLength
    case invalidFinalFlag
    case incompleteFile
    case digestMismatch
    case ioFailure(String)

    var reasonCode: String {
        switch self {
        case .policyDenied: return "policy_denied"
        case .userDenied: return "user_denied"
        case .invalidTransferID: return "invalid_transfer_id"
        case .invalidFileName: return "invalid_file_name"
        case .invalidDigest: return "invalid_digest"
        case .fileTooLarge: return "file_too_large"
        case .concurrentLimitReached: return "concurrent_limit"
        case .temporarySpaceLimitReached: return "temporary_space_limit"
        case .duplicateTransfer: return "duplicate_transfer"
        case .unknownTransfer: return "unknown_transfer"
        case .invalidChunkHeader: return "invalid_chunk_header"
        case .chunkTooLarge: return "chunk_too_large"
        case .chunkLengthMismatch: return "chunk_length_mismatch"
        case .chunkDigestMismatch: return "chunk_digest_mismatch"
        case .emptyChunk: return "empty_chunk"
        case .staleSessionEpoch: return "stale_session_epoch"
        case .unexpectedOffset: return "unexpected_offset"
        case .exceedsDeclaredLength: return "exceeds_declared_length"
        case .invalidFinalFlag: return "invalid_final_flag"
        case .incompleteFile: return "incomplete_file"
        case .digestMismatch: return "digest_mismatch"
        case .ioFailure: return "io_failure"
        }
    }
}

final class ProtocolV1IncomingFileTransferManager {
    typealias Approval = (VSFileOffer) -> Bool

    private final class State {
        let offer: VSFileOffer
        let url: URL
        let handle: FileHandle
        let sessionEpoch: UInt64
        let maximumChunkBytes: Int
        var offset: UInt64 = 0
        var hasher = SHA256()

        init(
            offer: VSFileOffer,
            url: URL,
            handle: FileHandle,
            sessionEpoch: UInt64,
            maximumChunkBytes: Int
        ) {
            self.offer = offer
            self.url = url
            self.handle = handle
            self.sessionEpoch = sessionEpoch
            self.maximumChunkBytes = maximumChunkBytes
        }
    }

    let policy: ProtocolV1FileTransferPolicy
    private let directory: URL
    private let approval: Approval
    private let lock = NSLock()
    private var transfers: [Data: State] = [:]

    init(
        policy: ProtocolV1FileTransferPolicy = .default,
        directory: URL,
        approval: @escaping Approval
    ) throws {
        self.policy = policy
        self.directory = directory
        self.approval = approval
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
        } catch {
            throw ProtocolV1FileTransferError.ioFailure(error.localizedDescription)
        }
    }

    deinit { cancelAll() }

    func accept(
        _ offer: VSFileOffer,
        remotePolicy: ProtocolV1RemoteManagedPolicy,
        negotiatedPolicy: ProtocolV1FileTransferPolicy,
        sessionEpoch: UInt64
    ) throws -> VSFileAccept {
        let effectivePolicy = try validateOfferForApproval(
            offer,
            remotePolicy: remotePolicy,
            negotiatedPolicy: negotiatedPolicy
        )
        guard approval(offer) else { throw ProtocolV1FileTransferError.userDenied }

        try lock.withLock {
            guard transfers[offer.transferID] == nil else { throw ProtocolV1FileTransferError.duplicateTransfer }
            guard transfers.count < effectivePolicy.maximumConcurrentTransfers else {
                throw ProtocolV1FileTransferError.concurrentLimitReached
            }
            let declared = transfers.values.reduce(UInt64.zero) { $0 + $1.offer.byteLength }
            guard offer.byteLength <= effectivePolicy.maximumTotalTemporaryBytes,
                  declared <= effectivePolicy.maximumTotalTemporaryBytes - offer.byteLength else {
                throw ProtocolV1FileTransferError.temporarySpaceLimitReached
            }
            let url = directory.appendingPathComponent(".vibescreen-\(UUID().uuidString).partial")
            guard FileManager.default.createFile(
                atPath: url.path,
                contents: nil,
                attributes: [.posixPermissions: 0o600]
            ) else {
                throw ProtocolV1FileTransferError.ioFailure("unable_to_create_staging_file")
            }
            do {
                let handle = try FileHandle(forWritingTo: url)
                transfers[offer.transferID] = State(
                    offer: offer,
                    url: url,
                    handle: handle,
                    sessionEpoch: sessionEpoch,
                    maximumChunkBytes: effectivePolicy.maximumChunkBytes
                )
            } catch {
                try? FileManager.default.removeItem(at: url)
                throw ProtocolV1FileTransferError.ioFailure(error.localizedDescription)
            }
        }

        var response = VSFileAccept()
        response.transferID = offer.transferID
        response.accepted = true
        response.maximumChunkBytes = UInt32(clamping: effectivePolicy.maximumChunkBytes)
        return response
    }

    func validateOfferForApproval(
        _ offer: VSFileOffer,
        remotePolicy: ProtocolV1RemoteManagedPolicy,
        negotiatedPolicy: ProtocolV1FileTransferPolicy,
        pendingTransferCount: Int = 0
    ) throws -> ProtocolV1FileTransferPolicy {
        let effectivePolicy = negotiatedPolicy.applying(remote: remotePolicy)
        guard effectivePolicy.allowed else { throw ProtocolV1FileTransferError.policyDenied }
        guard !offer.transferID.isEmpty else { throw ProtocolV1FileTransferError.invalidTransferID }
        guard Self.isSafeFileName(offer.fileName) else { throw ProtocolV1FileTransferError.invalidFileName }
        guard offer.sha256.count == SHA256.byteCount else { throw ProtocolV1FileTransferError.invalidDigest }
        guard offer.byteLength <= effectivePolicy.maximumFileBytes else {
            throw ProtocolV1FileTransferError.fileTooLarge(offer.byteLength)
        }

        try lock.withLock {
            guard transfers[offer.transferID] == nil else { throw ProtocolV1FileTransferError.duplicateTransfer }
            guard transfers.count + pendingTransferCount < effectivePolicy.maximumConcurrentTransfers else {
                throw ProtocolV1FileTransferError.concurrentLimitReached
            }
            let declared = transfers.values.reduce(UInt64.zero) { $0 + $1.offer.byteLength }
            guard offer.byteLength <= effectivePolicy.maximumTotalTemporaryBytes,
                  declared <= effectivePolicy.maximumTotalTemporaryBytes - offer.byteLength else {
                throw ProtocolV1FileTransferError.temporarySpaceLimitReached
            }
        }
        return effectivePolicy
    }

    func append(_ chunk: ProtocolV1FileChunk, sessionEpoch: UInt64) throws -> UInt64 {
        try lock.withLock {
            guard let state = transfers[chunk.header.transferID] else {
                throw ProtocolV1FileTransferError.unknownTransfer
            }
            guard chunk.header.sessionEpoch == sessionEpoch, state.sessionEpoch == sessionEpoch else {
                throw ProtocolV1FileTransferError.staleSessionEpoch(
                    expected: state.sessionEpoch,
                    actual: chunk.header.sessionEpoch
                )
            }
            guard chunk.payload.count <= state.maximumChunkBytes else {
                throw ProtocolV1FileTransferError.chunkTooLarge(chunk.payload.count)
            }
            guard !chunk.payload.isEmpty || (state.offer.byteLength == 0 && state.offset == 0 && chunk.header.final) else {
                throw ProtocolV1FileTransferError.emptyChunk
            }
            guard chunk.header.offset == state.offset else {
                throw ProtocolV1FileTransferError.unexpectedOffset(expected: state.offset, actual: chunk.header.offset)
            }
            guard UInt64(chunk.payload.count) <= state.offer.byteLength - state.offset else {
                throw ProtocolV1FileTransferError.exceedsDeclaredLength
            }
            let willComplete = state.offset + UInt64(chunk.payload.count) == state.offer.byteLength
            guard chunk.header.final == willComplete else {
                throw ProtocolV1FileTransferError.invalidFinalFlag
            }
            do {
                try state.handle.write(contentsOf: chunk.payload)
            } catch {
                throw ProtocolV1FileTransferError.ioFailure(error.localizedDescription)
            }
            state.hasher.update(data: chunk.payload)
            state.offset += UInt64(chunk.payload.count)
            return state.offset
        }
    }

    func finish(transferID: Data) throws -> ProtocolV1CompletedIncomingFile {
        try lock.withLock {
            guard let state = transfers[transferID] else { throw ProtocolV1FileTransferError.unknownTransfer }
            guard state.offset == state.offer.byteLength else { throw ProtocolV1FileTransferError.incompleteFile }
            let digest = Data(state.hasher.finalize())
            guard digest == state.offer.sha256 else {
                cleanup(state: state)
                transfers.removeValue(forKey: transferID)
                throw ProtocolV1FileTransferError.digestMismatch
            }
            do { try state.handle.close() } catch {
                cleanup(state: state)
                transfers.removeValue(forKey: transferID)
                throw ProtocolV1FileTransferError.ioFailure(error.localizedDescription)
            }
            transfers.removeValue(forKey: transferID)
            return ProtocolV1CompletedIncomingFile(
                transferID: transferID,
                fileName: state.offer.fileName,
                mimeType: state.offer.mimeType,
                stagingURL: state.url,
                sha256: digest
            )
        }
    }

    func cancel(transferID: Data) {
        lock.withLock {
            guard let state = transfers.removeValue(forKey: transferID) else { return }
            cleanup(state: state)
        }
    }

    func cancelAll() {
        lock.withLock {
            for state in transfers.values { cleanup(state: state) }
            transfers.removeAll()
        }
    }

    var activeTransferCount: Int { lock.withLock { transfers.count } }

    static func isSafeFileName(_ name: String) -> Bool {
        guard !name.isEmpty, name != ".", name != "..", !name.contains("\0"),
              !name.contains("/"), !name.contains("\\") else { return false }
        return URL(fileURLWithPath: name).lastPathComponent == name
    }

    private func cleanup(state: State) {
        try? state.handle.close()
        try? FileManager.default.removeItem(at: state.url)
    }
}

final class ProtocolV1OutgoingFileTransfer {
    let offer: VSFileOffer
    private let handle: FileHandle
    private let policy: ProtocolV1FileTransferPolicy
    private var offset: UInt64 = 0
    private var cancelled = false
    private var emittedEmptyFileChunk = false
    private var acceptedMaximumChunkBytes: Int?
    private let lock = NSLock()

    init(
        fileURL: URL,
        mimeType: String,
        policy: ProtocolV1FileTransferPolicy,
        remotePolicy: ProtocolV1RemoteManagedPolicy = .unmanaged
    ) throws {
        let effectivePolicy = policy.applying(remote: remotePolicy)
        guard effectivePolicy.allowed else { throw ProtocolV1FileTransferError.policyDenied }
        let values: URLResourceValues
        do { values = try fileURL.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey]) }
        catch { throw ProtocolV1FileTransferError.ioFailure(error.localizedDescription) }
        guard values.isRegularFile == true, let size = values.fileSize, size >= 0 else {
            throw ProtocolV1FileTransferError.invalidFileName
        }
        let byteLength = UInt64(size)
        guard byteLength <= effectivePolicy.maximumFileBytes else {
            throw ProtocolV1FileTransferError.fileTooLarge(byteLength)
        }
        guard ProtocolV1IncomingFileTransferManager.isSafeFileName(fileURL.lastPathComponent) else {
            throw ProtocolV1FileTransferError.invalidFileName
        }
        let digest = try Self.digest(fileURL: fileURL, chunkBytes: effectivePolicy.maximumChunkBytes)
        var offer = VSFileOffer()
        offer.transferID = withUnsafeBytes(of: UUID().uuid) { Data($0) }
        offer.fileName = fileURL.lastPathComponent
        offer.mimeType = mimeType
        offer.byteLength = byteLength
        offer.sha256 = digest
        self.offer = offer
        self.policy = effectivePolicy
        do { handle = try FileHandle(forReadingFrom: fileURL) }
        catch { throw ProtocolV1FileTransferError.ioFailure(error.localizedDescription) }
    }

    deinit { try? handle.close() }

    func nextChunk(maximumBytes: Int, sessionEpoch: UInt64) throws -> ProtocolV1FileChunk? {
        try lock.withLock {
            guard !cancelled else { throw ProtocolV1FileTransferError.unknownTransfer }
            if offer.byteLength == 0 {
                guard !emittedEmptyFileChunk else { return nil }
                emittedEmptyFileChunk = true
                var header = VSFileChunkHeader()
                header.transferID = offer.transferID
                header.offset = 0
                header.payloadLength = 0
                header.sessionEpoch = sessionEpoch
                header.chunkSha256 = Data(SHA256.hash(data: Data()))
                header.final = true
                return ProtocolV1FileChunk(header: header, payload: Data())
            }
            guard offset < offer.byteLength else { return nil }
            let chunkBytes = max(1, min(policy.maximumChunkBytes, maximumBytes))
            let requested = min(chunkBytes, Int(offer.byteLength - offset))
            let data: Data
            do { data = try handle.read(upToCount: requested) ?? Data() }
            catch { throw ProtocolV1FileTransferError.ioFailure(error.localizedDescription) }
            guard !data.isEmpty else { throw ProtocolV1FileTransferError.incompleteFile }
            var header = VSFileChunkHeader()
            header.transferID = offer.transferID
            header.offset = offset
            header.payloadLength = UInt32(data.count)
            header.sessionEpoch = sessionEpoch
            header.chunkSha256 = Data(SHA256.hash(data: data))
            header.final = offset + UInt64(data.count) == offer.byteLength
            offset += UInt64(data.count)
            return ProtocolV1FileChunk(header: header, payload: data)
        }
    }

    func cancel() {
        lock.withLock { cancelled = true }
        try? handle.close()
    }

    func applyAcceptedMaximumChunkBytes(_ maximumBytes: Int) {
        lock.withLock {
            acceptedMaximumChunkBytes = maximumBytes > 0 ? maximumBytes : nil
        }
    }

    func maximumChunkBytes(default defaultBytes: Int) -> Int {
        lock.withLock {
            acceptedMaximumChunkBytes ?? defaultBytes
        }
    }

    func validateAcknowledgedOffset(_ receivedBytes: UInt64) throws {
        try lock.withLock {
            guard receivedBytes == offset else {
                throw ProtocolV1FileTransferError.unexpectedOffset(expected: offset, actual: receivedBytes)
            }
        }
    }

    func validateCompletionDigest(_ sha256: Data) throws {
        guard sha256 == offer.sha256 else { throw ProtocolV1FileTransferError.digestMismatch }
    }

    var isComplete: Bool {
        lock.withLock {
            offer.byteLength == 0 ? emittedEmptyFileChunk : offset == offer.byteLength
        }
    }

    private static func digest(fileURL: URL, chunkBytes: Int) throws -> Data {
        let handle: FileHandle
        do { handle = try FileHandle(forReadingFrom: fileURL) }
        catch { throw ProtocolV1FileTransferError.ioFailure(error.localizedDescription) }
        defer { try? handle.close() }
        var hasher = SHA256()
        while true {
            let data: Data
            do { data = try handle.read(upToCount: chunkBytes) ?? Data() }
            catch { throw ProtocolV1FileTransferError.ioFailure(error.localizedDescription) }
            if data.isEmpty { break }
            hasher.update(data: data)
        }
        return Data(hasher.finalize())
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
