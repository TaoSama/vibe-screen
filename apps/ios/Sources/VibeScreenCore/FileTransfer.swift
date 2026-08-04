import CryptoKit
import Foundation
import VibeScreenProtocol

public struct FileTransferPolicy: Equatable, Sendable {
    public let maximumFileBytes: UInt64
    public let maximumChunkBytes: Int
    public let maximumConcurrentTransfers: Int
    public let maximumTotalTemporaryBytes: UInt64

    public init(
        maximumFileBytes: UInt64 = 512 * 1_024 * 1_024,
        maximumChunkBytes: Int = 64 * 1_024,
        maximumConcurrentTransfers: Int = 2,
        maximumTotalTemporaryBytes: UInt64 = 768 * 1_024 * 1_024
    ) {
        self.maximumFileBytes = maximumFileBytes
        self.maximumChunkBytes = maximumChunkBytes
        self.maximumConcurrentTransfers = maximumConcurrentTransfers
        self.maximumTotalTemporaryBytes = maximumTotalTemporaryBytes
    }
}

public struct FileChunk: Sendable {
    public let header: VSFileChunkHeader
    public let payload: Data

    public init(serializedFrame: Data) throws {
        var cursor = 0
        let headerLength = try DelimitedPayload.readVarint(from: serializedFrame, cursor: &cursor)
        guard headerLength <= 64 * 1_024, headerLength <= serializedFrame.count - cursor else {
            throw FileTransferError.invalidChunkHeader
        }
        header = try VSFileChunkHeader(
            serializedBytes: serializedFrame.dropFirst(cursor).prefix(headerLength)
        )
        payload = Data(serializedFrame.dropFirst(cursor + headerLength))
        guard payload.count == Int(header.payloadLength) else {
            throw FileTransferError.chunkLengthMismatch
        }
        guard header.chunkSha256.count == SHA256.byteCount else {
            throw FileTransferError.invalidDigest
        }
        if Data(SHA256.hash(data: payload)) != header.chunkSha256 {
            throw FileTransferError.chunkDigestMismatch
        }
    }

    public func serializedFrame() throws -> Data {
        let headerBytes = try header.serializedData()
        return DelimitedPayload.encodeVarint(headerBytes.count) + headerBytes + payload
    }
}

public struct CompletedIncomingFile: Equatable, Sendable {
    public let transferID: Data
    public let fileName: String
    public let stagingURL: URL
    public let sha256: Data
}

public enum FileTransferError: Error, Equatable {
    case policyDenied
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
    case unexpectedOffset(expected: UInt64, actual: UInt64)
    case exceedsDeclaredLength
    case invalidFinalFlag
    case incompleteFile
    case digestMismatch
    case ioFailure(String)
}

public final class IncomingFileTransferManager: @unchecked Sendable {
    private final class State {
        let offer: VSFileOffer
        let url: URL
        let handle: FileHandle
        var offset: UInt64 = 0
        var hasher = SHA256()

        init(offer: VSFileOffer, url: URL, handle: FileHandle) {
            self.offer = offer
            self.url = url
            self.handle = handle
        }
    }

    public let policy: FileTransferPolicy
    private let directory: URL
    private let lock = NSLock()
    private var transfers: [Data: State] = [:]

    public init(policy: FileTransferPolicy, directory: URL) throws {
        self.policy = policy
        self.directory = directory
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            throw FileTransferError.ioFailure(error.localizedDescription)
        }
    }

    deinit {
        lock.withLock {
            for state in transfers.values {
                try? state.handle.close()
                try? FileManager.default.removeItem(at: state.url)
            }
        }
    }

    public func accept(_ offer: VSFileOffer, managedPolicy: ManagedPolicy) throws -> VSFileAccept {
        guard managedPolicy.fileTransferAllowed else { throw FileTransferError.policyDenied }
        guard !offer.transferID.isEmpty else { throw FileTransferError.invalidTransferID }
        guard Self.isSafeFileName(offer.fileName) else { throw FileTransferError.invalidFileName }
        guard offer.sha256.count == SHA256.byteCount else { throw FileTransferError.invalidDigest }
        let maximum = min(policy.maximumFileBytes, managedPolicy.maximumFileBytes)
        guard offer.byteLength <= maximum else { throw FileTransferError.fileTooLarge(offer.byteLength) }

        try lock.withLock {
            guard transfers[offer.transferID] == nil else { throw FileTransferError.duplicateTransfer }
            guard transfers.count < policy.maximumConcurrentTransfers else {
                throw FileTransferError.concurrentLimitReached
            }
            let declared = transfers.values.reduce(UInt64.zero) { $0 + $1.offer.byteLength }
            guard offer.byteLength <= policy.maximumTotalTemporaryBytes else {
                throw FileTransferError.temporarySpaceLimitReached
            }
            guard declared <= policy.maximumTotalTemporaryBytes - offer.byteLength else {
                throw FileTransferError.temporarySpaceLimitReached
            }
            let url = directory.appendingPathComponent(".vibescreen-\(UUID().uuidString).partial")
            guard FileManager.default.createFile(atPath: url.path, contents: nil) else {
                throw FileTransferError.ioFailure("unable_to_create_staging_file")
            }
            do {
                let handle = try FileHandle(forWritingTo: url)
                transfers[offer.transferID] = State(offer: offer, url: url, handle: handle)
            } catch {
                try? FileManager.default.removeItem(at: url)
                throw FileTransferError.ioFailure(error.localizedDescription)
            }
        }
        var response = VSFileAccept()
        response.transferID = offer.transferID
        response.accepted = true
        response.maximumChunkBytes = UInt32(policy.maximumChunkBytes)
        return response
    }

    public func append(_ chunk: FileChunk) throws -> UInt64 {
        try lock.withLock {
            guard let state = transfers[chunk.header.transferID] else {
                throw FileTransferError.unknownTransfer
            }
            guard chunk.payload.count <= policy.maximumChunkBytes else {
                throw FileTransferError.chunkTooLarge(chunk.payload.count)
            }
            guard chunk.header.offset == state.offset else {
                throw FileTransferError.unexpectedOffset(expected: state.offset, actual: chunk.header.offset)
            }
            guard UInt64(chunk.payload.count) <= state.offer.byteLength - state.offset else {
                throw FileTransferError.exceedsDeclaredLength
            }
            let willComplete = state.offset + UInt64(chunk.payload.count) == state.offer.byteLength
            guard chunk.header.final == willComplete else { throw FileTransferError.invalidFinalFlag }
            do {
                try state.handle.write(contentsOf: chunk.payload)
            } catch {
                throw FileTransferError.ioFailure(error.localizedDescription)
            }
            state.hasher.update(data: chunk.payload)
            state.offset += UInt64(chunk.payload.count)
            return state.offset
        }
    }

    public func finish(transferID: Data) throws -> CompletedIncomingFile {
        try lock.withLock {
            guard let state = transfers[transferID] else { throw FileTransferError.unknownTransfer }
            guard state.offset == state.offer.byteLength else { throw FileTransferError.incompleteFile }
            let digest = Data(state.hasher.finalize())
            guard digest == state.offer.sha256 else {
                try? state.handle.close()
                try? FileManager.default.removeItem(at: state.url)
                transfers.removeValue(forKey: transferID)
                throw FileTransferError.digestMismatch
            }
            do { try state.handle.close() }
            catch { throw FileTransferError.ioFailure(error.localizedDescription) }
            transfers.removeValue(forKey: transferID)
            return CompletedIncomingFile(
                transferID: transferID,
                fileName: state.offer.fileName,
                stagingURL: state.url,
                sha256: digest
            )
        }
    }

    public func cancel(transferID: Data) {
        lock.withLock {
            guard let state = transfers.removeValue(forKey: transferID) else { return }
            try? state.handle.close()
            try? FileManager.default.removeItem(at: state.url)
        }
    }

    public var activeTransferCount: Int { lock.withLock { transfers.count } }

    public static func isSafeFileName(_ name: String) -> Bool {
        guard !name.isEmpty, name != ".", name != "..", !name.contains("\0"),
              !name.contains("/"), !name.contains("\\") else { return false }
        return URL(fileURLWithPath: name).lastPathComponent == name
    }
}

public final class OutgoingFileTransfer: @unchecked Sendable {
    public let offer: VSFileOffer
    private let handle: FileHandle
    private let maximumChunkBytes: Int
    private var offset: UInt64 = 0
    private let lock = NSLock()
    private var cancelled = false

    public init(
        fileURL: URL,
        mimeType: String,
        policy: FileTransferPolicy,
        managedPolicy: ManagedPolicy
    ) throws {
        guard managedPolicy.fileTransferAllowed else { throw FileTransferError.policyDenied }
        let values: URLResourceValues
        do { values = try fileURL.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey]) }
        catch { throw FileTransferError.ioFailure(error.localizedDescription) }
        guard values.isRegularFile == true, let fileSize = values.fileSize, fileSize >= 0 else {
            throw FileTransferError.invalidFileName
        }
        let byteLength = UInt64(fileSize)
        guard byteLength <= min(policy.maximumFileBytes, managedPolicy.maximumFileBytes) else {
            throw FileTransferError.fileTooLarge(byteLength)
        }
        guard IncomingFileTransferManager.isSafeFileName(fileURL.lastPathComponent) else {
            throw FileTransferError.invalidFileName
        }
        let digest = try Self.digest(fileURL: fileURL, chunkBytes: policy.maximumChunkBytes)
        var offer = VSFileOffer()
        offer.transferID = withUnsafeBytes(of: UUID().uuid) { Data($0) }
        offer.fileName = fileURL.lastPathComponent
        offer.mimeType = mimeType
        offer.byteLength = byteLength
        offer.sha256 = digest
        self.offer = offer
        maximumChunkBytes = policy.maximumChunkBytes
        do { handle = try FileHandle(forReadingFrom: fileURL) }
        catch { throw FileTransferError.ioFailure(error.localizedDescription) }
    }

    deinit { try? handle.close() }

    public func nextChunk(maximumBytes: Int? = nil, sessionEpoch: UInt64 = 0) throws -> FileChunk? {
        try lock.withLock {
            guard !cancelled else { throw FileTransferError.unknownTransfer }
            guard offset < offer.byteLength else { return nil }
            let negotiatedMaximum = max(1, min(maximumBytes ?? maximumChunkBytes, maximumChunkBytes))
            let requested = min(negotiatedMaximum, Int(offer.byteLength - offset))
            let data: Data
            do { data = try handle.read(upToCount: requested) ?? Data() }
            catch { throw FileTransferError.ioFailure(error.localizedDescription) }
            guard !data.isEmpty else { throw FileTransferError.incompleteFile }
            var header = VSFileChunkHeader()
            header.transferID = offer.transferID
            header.offset = offset
            header.payloadLength = UInt32(data.count)
            header.sessionEpoch = sessionEpoch
            header.chunkSha256 = Data(SHA256.hash(data: data))
            header.final = offset + UInt64(data.count) == offer.byteLength
            offset += UInt64(data.count)
            return FileChunk(header: header, payload: data)
        }
    }

    public func cancel() {
        lock.withLock { cancelled = true }
        try? handle.close()
    }

    private static func digest(fileURL: URL, chunkBytes: Int) throws -> Data {
        let handle: FileHandle
        do { handle = try FileHandle(forReadingFrom: fileURL) }
        catch { throw FileTransferError.ioFailure(error.localizedDescription) }
        defer { try? handle.close() }
        var hasher = SHA256()
        while true {
            let data: Data
            do { data = try handle.read(upToCount: chunkBytes) ?? Data() }
            catch { throw FileTransferError.ioFailure(error.localizedDescription) }
            if data.isEmpty { break }
            hasher.update(data: data)
        }
        return Data(hasher.finalize())
    }
}

private extension FileChunk {
    init(header: VSFileChunkHeader, payload: Data) {
        self.header = header
        self.payload = payload
    }
}
