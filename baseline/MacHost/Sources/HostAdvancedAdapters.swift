import AppKit
import CoreMedia
import CryptoKit
import Foundation
import VibeScreenProtocol

struct HostAdvancedLimits: Equatable {
    static let production = HostAdvancedLimits(
        maximumClipboardBytes: 1 * 1_024 * 1_024,
        maximumFileBytes: 512 * 1_024 * 1_024,
        maximumFileChunkBytes: 64 * 1_024,
        maximumConcurrentFiles: 2,
        maximumTotalTemporaryBytes: 768 * 1_024 * 1_024
    )

    let maximumClipboardBytes: Int
    let maximumFileBytes: UInt64
    let maximumFileChunkBytes: Int
    let maximumConcurrentFiles: Int
    let maximumTotalTemporaryBytes: UInt64
}

enum HostAdvancedAdapterError: Error, Equatable {
    case invalidIdentifier
    case unsupportedMIMEType
    case contentTooLarge
    case invalidDigest
    case feedbackLoop
    case invalidFileName
    case fileTooLarge
    case transferLimitReached
    case duplicateTransfer
    case unknownTransfer
    case staleSession
    case invalidOffset
    case invalidFinalChunk
    case ioFailure
    case invalidWakeRequest
    case expiredWakeRequest
    case replayedWakeRequest
    case unauthenticatedWakeRequest
}

final class BulkTransferAdmissionGate {
    private let maximumItems: Int
    private let maximumBytes: Int
    private let lock = NSLock()
    private var admittedItems = 0
    private var admittedBytes = 0

    init(maximumItems: Int = 4, maximumBytes: Int = 256 * 1_024) {
        precondition(maximumItems > 0 && maximumBytes > 0)
        self.maximumItems = maximumItems
        self.maximumBytes = maximumBytes
    }

    func admit(bytes: Int) -> Bool {
        guard bytes > 0, bytes <= maximumBytes else { return false }
        return lock.withLock {
            guard admittedItems < maximumItems,
                  admittedBytes <= maximumBytes - bytes else { return false }
            admittedItems += 1
            admittedBytes += bytes
            return true
        }
    }

    func release(bytes: Int) {
        lock.withLock {
            precondition(admittedItems > 0 && admittedBytes >= bytes)
            admittedItems -= 1
            admittedBytes -= bytes
        }
    }

    var usage: (items: Int, bytes: Int) {
        lock.withLock { (admittedItems, admittedBytes) }
    }
}

final class HostClipboardAdapter {
    private let pasteboard: NSPasteboard
    private let limits: HostAdvancedLimits
    private var recentChangeIDs: [Data] = []
    private let historyLimit = 128

    init(pasteboard: NSPasteboard = .general, limits: HostAdvancedLimits = .production) {
        self.pasteboard = pasteboard
        self.limits = limits
    }

    @MainActor
    func content(for changeID: Data, originDeviceID: String) throws -> VSClipboardContent {
        guard changeID.count == 16, !originDeviceID.isEmpty,
              originDeviceID.utf8.count <= 128 else {
            throw HostAdvancedAdapterError.invalidIdentifier
        }
        let data: Data
        let mimeType: String
        if let png = pasteboard.data(forType: .png) {
            data = png
            mimeType = "image/png"
        } else if let text = pasteboard.string(forType: .string),
                  let encoded = text.data(using: .utf8) {
            data = encoded
            mimeType = "text/plain"
        } else {
            throw HostAdvancedAdapterError.unsupportedMIMEType
        }
        guard data.count <= limits.maximumClipboardBytes else {
            throw HostAdvancedAdapterError.contentTooLarge
        }
        remember(changeID)
        var content = VSClipboardContent()
        content.changeID = changeID
        content.originDeviceID = originDeviceID
        content.mimeType = mimeType
        content.content = data
        content.sha256 = Data(SHA256.hash(data: data))
        return content
    }

    @MainActor
    func apply(_ content: VSClipboardContent) throws {
        guard content.changeID.count == 16, !content.originDeviceID.isEmpty,
              content.originDeviceID.utf8.count <= 128 else {
            throw HostAdvancedAdapterError.invalidIdentifier
        }
        guard !recentChangeIDs.contains(content.changeID) else {
            throw HostAdvancedAdapterError.feedbackLoop
        }
        guard content.content.count <= limits.maximumClipboardBytes else {
            throw HostAdvancedAdapterError.contentTooLarge
        }
        guard Data(SHA256.hash(data: content.content)) == content.sha256 else {
            throw HostAdvancedAdapterError.invalidDigest
        }
        let replacement = NSPasteboardItem()
        switch content.mimeType {
        case "text/plain":
            guard let text = String(data: content.content, encoding: .utf8) else {
                throw HostAdvancedAdapterError.unsupportedMIMEType
            }
            guard replacement.setString(text, forType: .string) else {
                throw HostAdvancedAdapterError.ioFailure
            }
        case "image/png":
            guard NSImage(data: content.content) != nil,
                  replacement.setData(content.content, forType: .png) else {
                throw HostAdvancedAdapterError.ioFailure
            }
        default:
            throw HostAdvancedAdapterError.unsupportedMIMEType
        }
        let backup = pasteboard.pasteboardItems?.map(Self.copyPasteboardItem) ?? []
        pasteboard.clearContents()
        guard pasteboard.writeObjects([replacement]) else {
            pasteboard.clearContents()
            if !backup.isEmpty { _ = pasteboard.writeObjects(backup) }
            throw HostAdvancedAdapterError.ioFailure
        }
        remember(content.changeID)
    }

    private static func copyPasteboardItem(_ source: NSPasteboardItem) -> NSPasteboardItem {
        let copy = NSPasteboardItem()
        for type in source.types {
            if let data = source.data(forType: type) {
                _ = copy.setData(data, forType: type)
            }
        }
        return copy
    }

    private func remember(_ changeID: Data) {
        recentChangeIDs.append(changeID)
        if recentChangeIDs.count > historyLimit {
            recentChangeIDs.removeFirst(recentChangeIDs.count - historyLimit)
        }
    }
}

struct HostFileChunk {
    let header: VSFileChunkHeader
    let payload: Data

    init(serializedFrame: Data, maximumChunkBytes: Int) throws {
        var cursor = 0
        let headerLength = try Self.readVarint(serializedFrame, cursor: &cursor)
        guard headerLength <= 64 * 1_024, headerLength <= serializedFrame.count - cursor else {
            throw HostAdvancedAdapterError.invalidIdentifier
        }
        header = try VSFileChunkHeader(
            serializedBytes: serializedFrame.dropFirst(cursor).prefix(headerLength)
        )
        payload = Data(serializedFrame.dropFirst(cursor + headerLength))
        guard payload.count <= maximumChunkBytes,
              payload.count == Int(header.payloadLength) else {
            throw HostAdvancedAdapterError.contentTooLarge
        }
        guard !payload.isEmpty || header.final else {
            throw HostAdvancedAdapterError.invalidFinalChunk
        }
        guard header.chunkSha256.count == SHA256.byteCount,
              Data(SHA256.hash(data: payload)) == header.chunkSha256 else {
            throw HostAdvancedAdapterError.invalidDigest
        }
    }

    private static func readVarint(_ data: Data, cursor: inout Int) throws -> Int {
        var value = 0
        var shift = 0
        while cursor < data.count, shift <= 28 {
            let byte = data[data.index(data.startIndex, offsetBy: cursor)]
            cursor += 1
            value |= Int(byte & 0x7f) << shift
            if byte & 0x80 == 0 { return value }
            shift += 7
        }
        throw HostAdvancedAdapterError.invalidIdentifier
    }
}

final class HostIncomingFileAdapter {
    private final class Transfer {
        let offer: VSFileOffer
        let partialURL: URL
        let handle: FileHandle
        var offset: UInt64 = 0
        var hasher = SHA256()

        init(offer: VSFileOffer, partialURL: URL, handle: FileHandle) {
            self.offer = offer
            self.partialURL = partialURL
            self.handle = handle
        }
    }

    private let destinationDirectory: URL
    private let limits: HostAdvancedLimits
    private let lock = NSLock()
    private var transfers: [Data: Transfer] = [:]

    init(destinationDirectory: URL, limits: HostAdvancedLimits = .production) throws {
        self.destinationDirectory = destinationDirectory
        self.limits = limits
        do {
            try FileManager.default.createDirectory(
                at: destinationDirectory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            let values = try destinationDirectory.resourceValues(forKeys: [
                .isDirectoryKey, .isSymbolicLinkKey
            ])
            guard values.isDirectory == true, values.isSymbolicLink != true else {
                throw HostAdvancedAdapterError.ioFailure
            }
        } catch {
            if let adapterError = error as? HostAdvancedAdapterError { throw adapterError }
            throw HostAdvancedAdapterError.ioFailure
        }
    }

    deinit { cancelAll() }

    func accept(_ offer: VSFileOffer) throws -> VSFileAccept {
        guard offer.transferID.count == 16 else { throw HostAdvancedAdapterError.invalidIdentifier }
        guard Self.isSafeFileName(offer.fileName) else {
            throw HostAdvancedAdapterError.invalidFileName
        }
        guard offer.byteLength > 0, offer.byteLength <= limits.maximumFileBytes else {
            throw HostAdvancedAdapterError.fileTooLarge
        }
        guard offer.sha256.count == SHA256.byteCount else {
            throw HostAdvancedAdapterError.invalidDigest
        }
        try lock.withLock {
            guard transfers[offer.transferID] == nil else {
                throw HostAdvancedAdapterError.duplicateTransfer
            }
            guard transfers.count < limits.maximumConcurrentFiles else {
                throw HostAdvancedAdapterError.transferLimitReached
            }
            let reserved = transfers.values.reduce(UInt64.zero) { $0 + $1.offer.byteLength }
            guard offer.byteLength <= limits.maximumTotalTemporaryBytes,
                  reserved <= limits.maximumTotalTemporaryBytes - offer.byteLength else {
                throw HostAdvancedAdapterError.transferLimitReached
            }
            let partialURL = destinationDirectory
                .appendingPathComponent(".vibescreen-\(UUID().uuidString).partial")
            guard FileManager.default.createFile(
                atPath: partialURL.path,
                contents: nil,
                attributes: [.posixPermissions: 0o600]
            ) else {
                throw HostAdvancedAdapterError.ioFailure
            }
            do {
                transfers[offer.transferID] = Transfer(
                    offer: offer,
                    partialURL: partialURL,
                    handle: try FileHandle(forWritingTo: partialURL)
                )
            } catch {
                try? FileManager.default.removeItem(at: partialURL)
                throw HostAdvancedAdapterError.ioFailure
            }
        }
        var result = VSFileAccept()
        result.transferID = offer.transferID
        result.accepted = true
        result.maximumChunkBytes = UInt32(limits.maximumFileChunkBytes)
        return result
    }

    func append(_ chunk: HostFileChunk, sessionEpoch: UInt64) throws -> UInt64 {
        try lock.withLock {
            guard chunk.header.sessionEpoch == sessionEpoch else {
                throw HostAdvancedAdapterError.staleSession
            }
            guard let transfer = transfers[chunk.header.transferID] else {
                throw HostAdvancedAdapterError.unknownTransfer
            }
            guard chunk.header.offset == transfer.offset else {
                throw HostAdvancedAdapterError.invalidOffset
            }
            guard UInt64(chunk.payload.count) <= transfer.offer.byteLength - transfer.offset else {
                throw HostAdvancedAdapterError.contentTooLarge
            }
            let completes = transfer.offset + UInt64(chunk.payload.count) == transfer.offer.byteLength
            guard chunk.header.final == completes else {
                throw HostAdvancedAdapterError.invalidFinalChunk
            }
            do { try transfer.handle.write(contentsOf: chunk.payload) }
            catch { throw HostAdvancedAdapterError.ioFailure }
            transfer.hasher.update(data: chunk.payload)
            transfer.offset += UInt64(chunk.payload.count)
            return transfer.offset
        }
    }

    func finish(transferID: Data) throws -> (url: URL, digest: Data) {
        try lock.withLock {
            guard let transfer = transfers[transferID] else {
                throw HostAdvancedAdapterError.unknownTransfer
            }
            guard transfer.offset == transfer.offer.byteLength else {
                throw HostAdvancedAdapterError.invalidFinalChunk
            }
            let digest = Data(transfer.hasher.finalize())
            guard digest == transfer.offer.sha256 else {
                cleanup(transferID: transferID, transfer: transfer)
                throw HostAdvancedAdapterError.invalidDigest
            }
            do { try transfer.handle.close() }
            catch { throw HostAdvancedAdapterError.ioFailure }
            let destination = uniqueDestination(for: transfer.offer.fileName)
            do { try FileManager.default.moveItem(at: transfer.partialURL, to: destination) }
            catch {
                try? FileManager.default.removeItem(at: transfer.partialURL)
                transfers.removeValue(forKey: transferID)
                throw HostAdvancedAdapterError.ioFailure
            }
            transfers.removeValue(forKey: transferID)
            return (destination, digest)
        }
    }

    func cancel(transferID: Data) {
        lock.withLock {
            guard let transfer = transfers[transferID] else { return }
            cleanup(transferID: transferID, transfer: transfer)
        }
    }

    func cancelAll() {
        lock.withLock {
            let active = Array(transfers.values)
            transfers.removeAll()
            for transfer in active {
                try? transfer.handle.close()
                try? FileManager.default.removeItem(at: transfer.partialURL)
            }
        }
    }

    private func cleanup(transferID: Data, transfer: Transfer) {
        try? transfer.handle.close()
        try? FileManager.default.removeItem(at: transfer.partialURL)
        transfers.removeValue(forKey: transferID)
    }

    private func uniqueDestination(for name: String) -> URL {
        let proposed = destinationDirectory.appendingPathComponent(name)
        guard FileManager.default.fileExists(atPath: proposed.path) else { return proposed }
        let source = URL(fileURLWithPath: name)
        let stem = source.deletingPathExtension().lastPathComponent
        let suffix = source.pathExtension
        for index in 2...10_000 {
            let candidateName = suffix.isEmpty ? "\(stem) \(index)" : "\(stem) \(index).\(suffix)"
            let candidate = destinationDirectory.appendingPathComponent(candidateName)
            if !FileManager.default.fileExists(atPath: candidate.path) { return candidate }
        }
        return destinationDirectory.appendingPathComponent("\(UUID().uuidString)-\(name)")
    }

    static func isSafeFileName(_ name: String) -> Bool {
        guard !name.isEmpty, name.utf8.count <= 255, name != ".", name != "..",
              !name.contains("\0"), !name.contains("/"), !name.contains("\\"),
              name.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) }) else {
            return false
        }
        return URL(fileURLWithPath: name).lastPathComponent == name
    }
}

struct HostWakeRequestAuthenticator {
    private let key: SymmetricKey
    private let hostID: String
    private let deviceID: String
    private let keyID: String
    private let targetMACAddress: Data
    private let maximumLifetimeSeconds: UInt64
    private var consumedNonces: [Data: UInt64] = [:]

    init(
        secret: Data,
        hostID: String,
        deviceID: String,
        keyID: String,
        targetMACAddress: Data,
        maximumLifetimeSeconds: UInt64 = 60
    ) {
        precondition(secret.count >= 32)
        precondition(targetMACAddress.count == 6)
        precondition(maximumLifetimeSeconds > 0)
        key = SymmetricKey(data: secret)
        self.hostID = hostID
        self.deviceID = deviceID
        self.keyID = keyID
        self.targetMACAddress = targetMACAddress
        self.maximumLifetimeSeconds = maximumLifetimeSeconds
    }

    mutating func validate(_ request: VSWakeHostRequest, now: UInt64) throws {
        guard request.requestID.count == 16,
              request.hostID == hostID, request.hostID.utf8.count <= 128,
              request.deviceID == deviceID, request.deviceID.utf8.count <= 128,
              request.keyID == keyID, request.keyID.utf8.count <= 128,
              request.targetMacAddress == targetMACAddress,
              request.targetMacAddress.contains(where: { $0 != 0 }),
              request.targetMacAddress.contains(where: { $0 != 0xff }),
              request.secureOnPassword.isEmpty || request.secureOnPassword.count == 6,
              request.nonce.count == 32,
              request.signature.count == SHA256.byteCount else {
            throw HostAdvancedAdapterError.invalidWakeRequest
        }
        guard request.issuedAtUnixSeconds <= now,
              now <= request.expiresAtUnixSeconds,
              request.expiresAtUnixSeconds - request.issuedAtUnixSeconds <= maximumLifetimeSeconds else {
            throw HostAdvancedAdapterError.expiredWakeRequest
        }
        consumedNonces = consumedNonces.filter { $0.value >= now }
        guard consumedNonces[request.nonce] == nil else {
            throw HostAdvancedAdapterError.replayedWakeRequest
        }
        guard HMAC<SHA256>.isValidAuthenticationCode(
            request.signature,
            authenticating: Self.signingBytes(request),
            using: key
        ) else {
            throw HostAdvancedAdapterError.unauthenticatedWakeRequest
        }
        consumedNonces[request.nonce] = request.expiresAtUnixSeconds
    }

    static func signingBytes(_ request: VSWakeHostRequest) -> Data {
        var result = Data("vibescreen-wake-v1\0".utf8)
        for bytes in [
            request.requestID,
            request.targetMacAddress,
            request.secureOnPassword,
            Data(request.hostID.utf8),
            Data(request.deviceID.utf8),
            Data(request.keyID.utf8),
            request.nonce
        ] {
            var length = UInt32(bytes.count).bigEndian
            withUnsafeBytes(of: &length) { result.append(contentsOf: $0) }
            result.append(bytes)
        }
        var issued = request.issuedAtUnixSeconds.bigEndian
        var expires = request.expiresAtUnixSeconds.bigEndian
        withUnsafeBytes(of: &issued) { result.append(contentsOf: $0) }
        withUnsafeBytes(of: &expires) { result.append(contentsOf: $0) }
        return result
    }
}

enum HostVideoColor {
    static var sdr: VSColorDescription {
        var color = VSColorDescription()
        color.primaries = .bt709
        color.transferFunction = .bt709
        color.matrixCoefficients = .bt709
        color.fullRange = true
        color.bitDepth = 8
        return color
    }
}
