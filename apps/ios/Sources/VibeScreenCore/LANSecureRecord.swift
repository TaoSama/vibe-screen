import CryptoKit
import Foundation

public enum LANSecureRecordError: Error, Equatable, LocalizedError {
    case invalidTokenLength
    case invalidPeerKeyLength
    case invalidHandshake
    case invalidRecordLength
    case legacyFallbackNotAllowed
    case encryptionRequired
    case recordOpenFailed

    public var errorDescription: String? {
        switch self {
        case .invalidTokenLength:
            "Trusted LAN secure records require a 32-byte pairing token."
        case .invalidPeerKeyLength:
            "Trusted LAN secure records require an uncompressed P-256 peer key."
        case .invalidHandshake:
            "Trusted LAN secure-record negotiation failed."
        case .invalidRecordLength:
            "Trusted LAN secure record had an invalid length."
        case .legacyFallbackNotAllowed:
            "Trusted LAN plaintext fallback was not explicitly allowed."
        case .encryptionRequired:
            "Trusted LAN session attempted to send plaintext while encryption is required."
        case .recordOpenFailed:
            "Trusted LAN secure record could not be authenticated."
        }
    }
}

public enum LANRecordProtectionState: Equatable, Sendable {
    case notApplicable
    case negotiating
    case encrypted
    case explicitLegacyFallback

    public var isEncrypted: Bool { self == .encrypted }
}

public enum LANSecureRecordNegotiation {
    public static let requestMagic = Data([0x56, 0x53, 0x4c, 0x53]) // VSLS
    public static let responseMagic = Data([0x56, 0x53, 0x4c, 0x52]) // VSLR
    public static let version: UInt8 = 1
    public static let uncompressedP256PublicKeyBytes = 65
    public static let requestBytes = 4 + 1 + 1 + uncompressedP256PublicKeyBytes
    public static let responseBytes = 4 + 1 + 1 + uncompressedP256PublicKeyBytes

    public enum Flags {
        public static let secureRecordsRequired: UInt8 = 1 << 0
        public static let legacyFallbackAllowed: UInt8 = 1 << 1
    }

    public enum ResponseFlag {
        public static let secureRecordsAccepted: UInt8 = 1 << 0
        public static let explicitLegacyFallback: UInt8 = 1 << 1
    }

    public static func encodeRequest(publicKey: Data, allowLegacyFallback: Bool) throws -> Data {
        guard publicKey.count == uncompressedP256PublicKeyBytes else {
            throw LANSecureRecordError.invalidPeerKeyLength
        }
        var result = requestMagic
        result.append(version)
        var flags = Flags.secureRecordsRequired
        if allowLegacyFallback { flags |= Flags.legacyFallbackAllowed }
        result.append(flags)
        result.append(publicKey)
        return result
    }

    public static func decodeRequest(_ data: Data) throws -> (publicKey: Data, allowLegacyFallback: Bool) {
        guard data.count == requestBytes, data.prefix(4) == requestMagic, data[4] == version else {
            throw LANSecureRecordError.invalidHandshake
        }
        let flags = data[5]
        guard flags & Flags.secureRecordsRequired != 0 else {
            throw LANSecureRecordError.invalidHandshake
        }
        return (
            publicKey: data.subdata(in: 6..<requestBytes),
            allowLegacyFallback: flags & Flags.legacyFallbackAllowed != 0
        )
    }

    public static func encodeResponse(
        publicKey: Data,
        encrypted: Bool,
        explicitLegacyFallback: Bool
    ) throws -> Data {
        guard publicKey.count == uncompressedP256PublicKeyBytes else {
            throw LANSecureRecordError.invalidPeerKeyLength
        }
        guard encrypted != explicitLegacyFallback else {
            throw LANSecureRecordError.invalidHandshake
        }
        var result = responseMagic
        result.append(version)
        result.append(encrypted ? ResponseFlag.secureRecordsAccepted : ResponseFlag.explicitLegacyFallback)
        result.append(publicKey)
        return result
    }

    public static func decodeResponse(_ data: Data) throws -> (publicKey: Data, encrypted: Bool, legacy: Bool) {
        guard data.count == responseBytes, data.prefix(4) == responseMagic, data[4] == version else {
            throw LANSecureRecordError.invalidHandshake
        }
        let flags = data[5]
        let encrypted = flags & ResponseFlag.secureRecordsAccepted != 0
        let legacy = flags & ResponseFlag.explicitLegacyFallback != 0
        guard encrypted != legacy else { throw LANSecureRecordError.invalidHandshake }
        return (publicKey: data.subdata(in: 6..<responseBytes), encrypted: encrypted, legacy: legacy)
    }
}

public final class LANSecureRecordSession: @unchecked Sendable {
    public static let recordSessionEpoch: UInt64 = 1

    public enum Role: UInt32, Sendable {
        case host = 1
        case device = 2

        var remote: Role { self == .host ? .device : .host }
    }

    public let sessionIdentifier: String
    public let sessionEpoch: UInt64

    private let lock = NSLock()
    private let localRole: Role
    private var keys: LANSessionTrafficKeys?
    private let nonceStore: LANSecureRecordNonceStore
    private let sessionHash: Data
    private var replay: [LogicalChannel: LANReplayWindow] = [:]

    public init(
        role: Role,
        sessionIdentifier: String,
        sessionEpoch: UInt64 = LANSecureRecordSession.recordSessionEpoch,
        sharedSecret: Data,
        bootstrapToken: Data,
        context: Data,
        nonceStore: LANSecureRecordNonceStore = LANSecureRecordNonceStore()
    ) throws {
        guard !sessionIdentifier.isEmpty, sessionEpoch > 0 else {
            throw LANSecureRecordError.invalidHandshake
        }
        guard bootstrapToken.count == TrustedLANPairing.tokenLength else {
            throw LANSecureRecordError.invalidTokenLength
        }
        self.localRole = role
        self.sessionIdentifier = sessionIdentifier
        self.sessionEpoch = sessionEpoch
        self.nonceStore = nonceStore
        self.sessionHash = Data(SHA256.hash(data: Data(sessionIdentifier.utf8))).prefix(LANSessionPacketCipher.sessionHashBytes)
        self.keys = try LANSessionTrafficKeys.initial(
            sharedSecret: sharedSecret,
            bootstrapSecret: bootstrapToken,
            context: context
        )
    }

    public static func sessionIdentifier(hostPublicKey: Data, devicePublicKey: Data) -> String {
        var input = Data("vibescreen/trusted-lan-session/v1".utf8)
        input.append(hostPublicKey)
        input.append(devicePublicKey)
        return SHA256.hash(data: input).map { String(format: "%02x", $0) }.joined()
    }

    public static func transcriptContext(
        sessionIdentifier: String,
        hostPublicKey: Data,
        devicePublicKey: Data
    ) -> Data {
        SecurityTranscript.digest(
            domain: "vibescreen/trusted-lan-records/v1",
            parts: [
                Data(sessionIdentifier.utf8),
                hostPublicKey,
                devicePublicKey,
            ]
        )
    }

    public func seal(_ payload: Data, channel: LogicalChannel) throws -> Data {
        try lock.withLock {
            guard let keys else { throw LANSecureRecordError.encryptionRequired }
            let nonce = try nonceStore.reserve(
                channel: UInt32(channel.rawValue),
                sender: localRole.rawValue,
                keyEpoch: keys.keyEpoch
            )
            guard nonce.count == LANSessionPacketCipher.nonceBytes,
                  decodeUInt32(nonce.prefix(4)) == UInt32(channel.rawValue),
                  decodeUInt64(nonce.suffix(8)) > 0 else {
                throw LANSecureRecordError.invalidHandshake
            }
            let header = LANSessionPacketCipher.header(
                sessionHash: sessionHash,
                sessionEpoch: sessionEpoch,
                keyEpoch: keys.keyEpoch,
                sender: localRole,
                channel: channel,
                nonce: nonce
            )
            return header + (try LANSessionPacketCipher.seal(
                plaintext: payload,
                key: keys.key(channel: channel, sender: localRole),
                nonce: nonce,
                authenticatedHeader: header
            ))
        }
    }

    public func open(_ record: Data, channel: LogicalChannel) throws -> Data {
        guard let plaintext = openIfAuthentic(record, channel: channel) else {
            throw LANSecureRecordError.recordOpenFailed
        }
        return plaintext
    }

    public func openDeclaredChannel(_ record: Data) throws -> (channel: LogicalChannel, payload: Data) {
        guard let channel = LANSessionPacketCipher.declaredChannel(in: record),
              let plaintext = openIfAuthentic(record, channel: channel) else {
            throw LANSecureRecordError.recordOpenFailed
        }
        return (channel, plaintext)
    }

    public func close() {
        lock.withLock {
            keys?.close()
            keys = nil
            replay.removeAll()
        }
    }

    deinit { close() }

    private func openIfAuthentic(_ record: Data, channel expectedChannel: LogicalChannel) -> Data? {
        lock.withLock {
            guard let keys, record.count >= LANSessionPacketCipher.headerBytes + LANSessionPacketCipher.tagBytes else {
                return nil
            }
            let header = Data(record.prefix(LANSessionPacketCipher.headerBytes))
            guard let decoded = LANSessionPacketCipher.decodeHeader(header),
                  decoded.sessionHash == sessionHash,
                  decoded.sessionEpoch == sessionEpoch,
                  decoded.keyEpoch == keys.keyEpoch,
                  decoded.sender == localRole.remote,
                  decoded.channel == expectedChannel,
                  decodeUInt32(decoded.nonce.prefix(4)) == UInt32(expectedChannel.rawValue) else {
                return nil
            }
            let sequence = decodeUInt64(decoded.nonce.suffix(8))
            var window = replay[expectedChannel] ?? LANReplayWindow(
                strictlyOrdered: expectedChannel == .control || expectedChannel == .bulkTransfer
            )
            guard window.canAccept(sequence),
                  let plaintext = try? LANSessionPacketCipher.open(
                    ciphertextAndTag: Data(record.dropFirst(LANSessionPacketCipher.headerBytes)),
                    key: keys.key(channel: expectedChannel, sender: localRole.remote),
                    nonce: decoded.nonce,
                    authenticatedHeader: header
                  ) else {
                return nil
            }
            window.commit(sequence)
            replay[expectedChannel] = window
            return plaintext
        }
    }
}

public struct LANSecureRecordStreamFramer: Sendable {
    public static let lengthPrefixBytes = 4
    public static let maximumRecordBytes = TransportFramer.headerLength
        + TransportFramer.maximumPayloadBytes
        + LANSessionPacketCipher.recordOverhead

    private var buffer = Data()

    public init() {}

    public mutating func append(
        _ bytes: Data,
        open: (Data) throws -> (channel: LogicalChannel, payload: Data)
    ) throws -> [TransportFrame] {
        buffer.append(bytes)
        var frames: [TransportFrame] = []
        while buffer.count >= Self.lengthPrefixBytes {
            let length = decodeUInt32(buffer.prefix(Self.lengthPrefixBytes))
            guard length > 0, length <= Self.maximumRecordBytes else {
                throw LANSecureRecordError.invalidRecordLength
            }
            let totalLength = Self.lengthPrefixBytes + Int(length)
            guard buffer.count >= totalLength else { break }
            let record = Data(buffer.dropFirst(Self.lengthPrefixBytes).prefix(Int(length)))
            let opened = try open(record)
            frames.append(TransportFrame(channel: opened.channel, payload: opened.payload))
            buffer.removeFirst(totalLength)
        }
        return frames
    }

    public static func encode(_ record: Data) throws -> Data {
        guard !record.isEmpty, record.count <= maximumRecordBytes else {
            throw LANSecureRecordError.invalidRecordLength
        }
        var result = Data()
        result.appendUInt32(UInt32(record.count))
        result.append(record)
        return result
    }
}

public final class LANSecureRecordNonceStore: @unchecked Sendable {
    private let lock = NSLock()
    private var counters: [String: UInt64] = [:]

    public init() {}

    public func reserve(channel: UInt32, sender: UInt32, keyEpoch: UInt64) throws -> Data {
        guard channel > 0, sender > 0, keyEpoch > 0 else {
            throw LANSecureRecordError.invalidHandshake
        }
        return lock.withLock {
            let key = "\(channel):\(sender):\(keyEpoch)"
            let next = (counters[key] ?? 0) + 1
            counters[key] = next
            var nonce = Data()
            nonce.appendUInt32(channel)
            nonce.appendUInt64(next)
            return nonce
        }
    }
}

public enum LANSecureRecordClient {
    public static func negotiate(
        token: Data,
        allowLegacyFallback: Bool,
        send: (Data, String) async throws -> Void,
        read: (Int, String) async throws -> Data
    ) async throws -> (state: LANRecordProtectionState, session: LANSecureRecordSession?) {
        guard token.count == TrustedLANPairing.tokenLength else {
            throw LANSecureRecordError.invalidTokenLength
        }
        let privateKey = P256.KeyAgreement.PrivateKey()
        let publicKey = privateKey.publicKey.x963Representation
        let request = try LANSecureRecordNegotiation.encodeRequest(
            publicKey: publicKey,
            allowLegacyFallback: allowLegacyFallback
        )
        try await send(request, "可信局域网安全记录协商请求")
        let responseData = try await read(
            LANSecureRecordNegotiation.responseBytes,
            "可信局域网安全记录协商响应"
        )
        let response = try LANSecureRecordNegotiation.decodeResponse(responseData)
        if response.legacy {
            guard allowLegacyFallback else { throw LANSecureRecordError.legacyFallbackNotAllowed }
            return (.explicitLegacyFallback, nil)
        }
        let sessionIdentifier = LANSecureRecordSession.sessionIdentifier(
            hostPublicKey: response.publicKey,
            devicePublicKey: publicKey
        )
        let context = LANSecureRecordSession.transcriptContext(
            sessionIdentifier: sessionIdentifier,
            hostPublicKey: response.publicKey,
            devicePublicKey: publicKey
        )
        let sharedSecret = try privateKey.sharedSecretData(with: response.publicKey)
        let session = try LANSecureRecordSession(
            role: .device,
            sessionIdentifier: sessionIdentifier,
            sessionEpoch: LANSecureRecordSession.recordSessionEpoch,
            sharedSecret: sharedSecret,
            bootstrapToken: token,
            context: context
        )
        return (.encrypted, session)
    }
}

struct LANSessionPacketCipher {
    static let recordOverhead = 67
    static let magic: UInt32 = 0x56534352
    static let version: UInt8 = 1
    static let sessionHashBytes = 16
    static let nonceBytes = 12
    static let tagBytes = 16
    static let headerBytes = 51

    static func header(
        sessionHash: Data,
        sessionEpoch: UInt64,
        keyEpoch: UInt64,
        sender: LANSecureRecordSession.Role,
        channel: LogicalChannel,
        nonce: Data
    ) -> Data {
        var header = Data()
        header.appendUInt32(magic)
        header.append(version)
        header.append(sessionHash)
        header.appendUInt64(sessionEpoch)
        header.appendUInt64(keyEpoch)
        header.append(UInt8(sender.rawValue))
        header.append(channel.rawValue)
        header.append(nonce)
        return header
    }

    static func decodeHeader(_ header: Data) -> LANRecordHeader? {
        guard header.count == headerBytes,
              decodeUInt32(header.prefix(4)) == magic,
              header[4] == version,
              let sender = LANSecureRecordSession.Role(rawValue: UInt32(header[37])),
              let channel = LogicalChannel(rawValue: header[38]) else {
            return nil
        }
        return LANRecordHeader(
            sessionHash: header.subdata(in: 5..<21),
            sessionEpoch: decodeUInt64(header.subdata(in: 21..<29)),
            keyEpoch: decodeUInt64(header.subdata(in: 29..<37)),
            sender: sender,
            channel: channel,
            nonce: header.subdata(in: 39..<51)
        )
    }

    static func declaredChannel(in record: Data) -> LogicalChannel? {
        guard record.count >= headerBytes + tagBytes,
              decodeUInt32(record.prefix(4)) == magic,
              record[4] == version else { return nil }
        return LogicalChannel(rawValue: record[38])
    }

    static func seal(plaintext: Data, key: Data, nonce: Data, authenticatedHeader: Data) throws -> Data {
        guard key.count == 32, nonce.count == nonceBytes else {
            throw LANSecureRecordError.invalidHandshake
        }
        let sealed = try AES.GCM.seal(
            plaintext,
            using: SymmetricKey(data: key),
            nonce: AES.GCM.Nonce(data: nonce),
            authenticating: authenticatedHeader
        )
        return sealed.ciphertext + sealed.tag
    }

    static func open(ciphertextAndTag: Data, key: Data, nonce: Data, authenticatedHeader: Data) throws -> Data {
        guard key.count == 32, nonce.count == nonceBytes, ciphertextAndTag.count >= tagBytes else {
            throw LANSecureRecordError.invalidRecordLength
        }
        var combined = Data(capacity: nonce.count + ciphertextAndTag.count)
        combined.append(nonce)
        combined.append(ciphertextAndTag)
        let box = try AES.GCM.SealedBox(combined: combined)
        return try AES.GCM.open(box, using: SymmetricKey(data: key), authenticating: authenticatedHeader)
    }
}

struct LANRecordHeader {
    let sessionHash: Data
    let sessionEpoch: UInt64
    let keyEpoch: UInt64
    let sender: LANSecureRecordSession.Role
    let channel: LogicalChannel
    let nonce: Data
}

final class LANSessionTrafficKeys {
    let keyID: String
    let keyEpoch: UInt64
    private var keyMaterial: [LogicalChannel: [LANSecureRecordSession.Role: Data]]
    private var closed = false

    private init(keyID: String, keyEpoch: UInt64, keyMaterial: [LogicalChannel: [LANSecureRecordSession.Role: Data]]) {
        self.keyID = keyID
        self.keyEpoch = keyEpoch
        self.keyMaterial = keyMaterial
    }

    static func initial(sharedSecret: Data, bootstrapSecret: Data, context: Data) throws -> LANSessionTrafficKeys {
        guard !sharedSecret.isEmpty, bootstrapSecret.count == 32, context.count == 32 else {
            throw LANSecureRecordError.invalidHandshake
        }
        var material = hkdf(input: sharedSecret, salt: bootstrapSecret, info: context)
        defer { material.resetBytes(in: material.indices) }
        return try split(material: material, context: context, epoch: 1)
    }

    func key(channel: LogicalChannel, sender: LANSecureRecordSession.Role) -> Data {
        keyMaterial[channel]?[sender] ?? Data()
    }

    func close() {
        guard !closed else { return }
        for channel in keyMaterial.keys {
            guard let roles = keyMaterial[channel]?.keys else { continue }
            for role in roles {
                guard var key = keyMaterial[channel]?[role] else { continue }
                key.resetBytes(in: key.indices)
                keyMaterial[channel]?[role] = key
            }
        }
        closed = true
    }

    deinit { close() }

    private static func hkdf(input: Data, salt: Data, info: Data) -> Data {
        let key = HKDF<SHA256>.deriveKey(
            inputKeyMaterial: SymmetricKey(data: input),
            salt: salt,
            info: info,
            outputByteCount: 256
        )
        return key.withUnsafeBytes { Data($0) }
    }

    private static func split(material: Data, context: Data, epoch: UInt64) throws -> LANSessionTrafficKeys {
        guard material.count == 256 else { throw LANSecureRecordError.invalidHandshake }
        var keyIDHasher = SHA256()
        keyIDHasher.update(data: context)
        keyIDHasher.update(data: material.prefix(128))
        var firstDigest = Data(keyIDHasher.finalize())
        defer { firstDigest.resetBytes(in: firstDigest.indices) }
        var keyIDDigest = Data(SHA256.hash(data: firstDigest))
        defer { keyIDDigest.resetBytes(in: keyIDDigest.indices) }
        let keyID = keyIDDigest.map { String(format: "%02x", $0) }.joined()
        return LANSessionTrafficKeys(
            keyID: keyID,
            keyEpoch: epoch,
            keyMaterial: [
                .control: [.host: material.subdata(in: 0..<32), .device: material.subdata(in: 32..<64)],
                .video: [.host: material.subdata(in: 64..<96), .device: material.subdata(in: 96..<128)],
                .audio: [.host: material.subdata(in: 128..<160), .device: material.subdata(in: 160..<192)],
                .bulkTransfer: [.host: material.subdata(in: 192..<224), .device: material.subdata(in: 224..<256)],
            ]
        )
    }
}

private struct LANReplayWindow {
    let strictlyOrdered: Bool
    private(set) var highest: UInt64 = 0
    private(set) var bitmap: UInt64 = 0

    func canAccept(_ sequence: UInt64) -> Bool {
        guard sequence > 0 else { return false }
        if strictlyOrdered { return sequence > highest }
        if sequence > highest { return true }
        let distance = highest - sequence
        return distance < 64 && bitmap & (UInt64(1) << distance) == 0
    }

    mutating func commit(_ sequence: UInt64) {
        precondition(canAccept(sequence))
        if sequence > highest {
            let shift = sequence - highest
            bitmap = shift >= 64 ? 1 : (bitmap << shift) | 1
            highest = sequence
        } else {
            bitmap |= UInt64(1) << (highest - sequence)
        }
    }
}

enum SecurityTranscript {
    static func digest(domain: String, parts: [Data]) -> Data {
        var encoded = Data()
        appendLengthPrefixed(Data("vibescreen/identity/v1".utf8), to: &encoded)
        appendLengthPrefixed(Data(domain.utf8), to: &encoded)
        parts.forEach { appendLengthPrefixed($0, to: &encoded) }
        return Data(SHA256.hash(data: encoded))
    }

    private static func appendLengthPrefixed(_ value: Data, to output: inout Data) {
        output.appendUInt64(UInt64(value.count))
        output.append(value)
    }
}

private extension P256.KeyAgreement.PrivateKey {
    func sharedSecretData(with peerPublicKey: Data) throws -> Data {
        guard peerPublicKey.count == LANSecureRecordNegotiation.uncompressedP256PublicKeyBytes else {
            throw LANSecureRecordError.invalidPeerKeyLength
        }
        let peer = try P256.KeyAgreement.PublicKey(x963Representation: peerPublicKey)
        let shared = try sharedSecretFromKeyAgreement(with: peer)
        return shared.withUnsafeBytes { Data($0) }
    }
}

private func decodeUInt32(_ data: Data) -> UInt32 {
    data.reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
}

private func decodeUInt64(_ data: Data) -> UInt64 {
    data.reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
}

private extension Data {
    mutating func appendUInt32(_ value: UInt32) {
        var bigEndian = value.bigEndian
        append(Data(bytes: &bigEndian, count: MemoryLayout<UInt32>.size))
    }

    mutating func appendUInt64(_ value: UInt64) {
        var bigEndian = value.bigEndian
        append(Data(bytes: &bigEndian, count: MemoryLayout<UInt64>.size))
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
