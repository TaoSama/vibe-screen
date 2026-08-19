import CryptoKit
import Foundation

enum LANSecureRecordError: Error, Equatable, LocalizedError {
    case invalidTokenLength
    case invalidPeerKeyLength
    case invalidHandshake
    case invalidRecordLength
    case legacyFallbackNotAllowed
    case encryptionRequired
    case recordOpenFailed

    var errorDescription: String? {
        switch self {
        case .invalidTokenLength:
            return "Trusted LAN secure records require a 32-byte pairing token."
        case .invalidPeerKeyLength:
            return "Trusted LAN secure records require an uncompressed P-256 peer key."
        case .invalidHandshake:
            return "Trusted LAN secure-record negotiation failed."
        case .invalidRecordLength:
            return "Trusted LAN secure record had an invalid length."
        case .legacyFallbackNotAllowed:
            return "Trusted LAN plaintext fallback was not explicitly allowed."
        case .encryptionRequired:
            return "Trusted LAN session attempted to send plaintext while encryption is required."
        case .recordOpenFailed:
            return "Trusted LAN secure record could not be authenticated."
        }
    }
}

enum LANRecordProtectionState: Equatable {
    case notApplicable
    case negotiating
    case encrypted
    case explicitLegacyFallback

    var isEncrypted: Bool { self == .encrypted }
}

enum LANSecureRecordNegotiation {
    static let requestMagic = Data([0x56, 0x53, 0x4c, 0x53]) // VSLS
    static let responseMagic = Data([0x56, 0x53, 0x4c, 0x52]) // VSLR
    static let version: UInt8 = 1
    static let uncompressedP256PublicKeyBytes = 65
    static let requestBytes = 4 + 1 + 1 + uncompressedP256PublicKeyBytes
    static let responseBytes = 4 + 1 + 1 + uncompressedP256PublicKeyBytes

    enum Flags {
        static let secureRecordsRequired: UInt8 = 1 << 0
        static let legacyFallbackAllowed: UInt8 = 1 << 1
    }

    enum ResponseFlag {
        static let secureRecordsAccepted: UInt8 = 1 << 0
        static let explicitLegacyFallback: UInt8 = 1 << 1
    }

    static func encodeRequest(publicKey: Data, allowLegacyFallback: Bool) throws -> Data {
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

    static func decodeRequest(_ data: Data) throws -> (publicKey: Data, allowLegacyFallback: Bool) {
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

    static func encodeResponse(
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

    static func decodeResponse(_ data: Data) throws -> (publicKey: Data, encrypted: Bool, legacy: Bool) {
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

final class LANSecureRecordSession {
    static let recordSessionEpoch: UInt64 = 1

    enum Role {
        case host
        case device

        var platformRole: PlatformSenderRole { self == .host ? .host : .device }
    }

    let sessionIdentifier: String
    let sessionEpoch: UInt64

    private let cipher: PlatformSessionPacketCipher

    init(
        role: Role,
        sessionIdentifier: String,
        sessionEpoch: UInt64,
        sharedSecret: Data,
        bootstrapToken: Data,
        context: Data,
        nonceStore: LANSecureRecordNonceStore = LANSecureRecordNonceStore()
    ) throws {
        guard bootstrapToken.count == 32 else { throw LANSecureRecordError.invalidTokenLength }
        self.sessionIdentifier = sessionIdentifier
        self.sessionEpoch = sessionEpoch
        let keys = try TrafficKeyDerivation.initial(
            sharedSecret: sharedSecret,
            bootstrapSecret: bootstrapToken,
            context: context
        )
        cipher = PlatformSessionPacketCipher(
            sessionIdentifier: sessionIdentifier,
            sessionEpoch: sessionEpoch,
            localRole: role.platformRole,
            initialKeys: keys,
            withActiveSessionEpoch: { operation in try operation() },
            reserveNonce: nonceStore.reserve(channel:sender:keyEpoch:),
            rotateKeys: { current, updateNonce in
                try TrafficKeyDerivation.rotate(
                    current: current,
                    nextEpoch: current.keyEpoch + 1,
                    updateNonce: updateNonce
                )
            }
        )
    }

    static func transcriptContext(
        sessionIdentifier: String,
        hostPublicKey: Data,
        devicePublicKey: Data
    ) -> Data {
        SecurityTranscript.digest(
            domain: "vibescreen/trusted-lan-records/v1",
            parts: [
                Data(sessionIdentifier.utf8),
                hostPublicKey,
                devicePublicKey
            ]
        )
    }

    static func sessionIdentifier(hostPublicKey: Data, devicePublicKey: Data) -> String {
        var input = Data("vibescreen/trusted-lan-session/v1".utf8)
        input.append(hostPublicKey)
        input.append(devicePublicKey)
        return SHA256.hash(data: input).map { String(format: "%02x", $0) }.joined()
    }

    func seal(_ payload: Data, channel: InternetTransportChannel) throws -> Data {
        try cipher.seal(payload, channel: channel)
    }

    func open(_ record: Data, channel: InternetTransportChannel) throws -> Data {
        guard let plaintext = cipher.open(record, channel: channel) else {
            throw LANSecureRecordError.recordOpenFailed
        }
        return plaintext
    }

    func openDeclaredChannel(_ record: Data) throws -> Data {
        guard let channel = PlatformSessionPacketCipher.declaredInternetChannel(in: record) else {
            throw LANSecureRecordError.recordOpenFailed
        }
        return try open(record, channel: channel)
    }

    func close() { cipher.close() }
}

struct LANSecureRecordStreamFramer {
    static let lengthPrefixBytes = 4
    static let maximumRecordBytes = ProtocolV1Framer.maximumPayloadBytes + PlatformSessionPacketCipher.recordOverhead

    private var buffer = Data()

    mutating func append(_ bytes: Data, open: (Data) throws -> Data) throws -> [Data] {
        buffer.append(bytes)
        var payloads: [Data] = []
        while buffer.count >= Self.lengthPrefixBytes {
            let length = buffer.prefix(Self.lengthPrefixBytes).reduce(UInt32.zero) {
                ($0 << 8) | UInt32($1)
            }
            guard length > 0, length <= Self.maximumRecordBytes else {
                throw LANSecureRecordError.invalidRecordLength
            }
            let frameBytes = Self.lengthPrefixBytes + Int(length)
            guard buffer.count >= frameBytes else { break }
            let record = Data(buffer.dropFirst(Self.lengthPrefixBytes).prefix(Int(length)))
            payloads.append(try open(record))
            buffer.removeFirst(frameBytes)
        }
        return payloads
    }

    static func encode(_ record: Data) throws -> Data {
        guard !record.isEmpty, record.count <= maximumRecordBytes else {
            throw LANSecureRecordError.invalidRecordLength
        }
        var result = Data()
        result.appendLANUInt32(UInt32(record.count))
        result.append(record)
        return result
    }
}

final class LANSecureRecordNonceStore {
    private let lock = NSLock()
    private var counters: [String: UInt64] = [:]

    func reserve(channel: UInt32, sender: UInt32, keyEpoch: UInt64) throws -> Data {
        guard channel > 0, sender > 0, keyEpoch > 0 else {
            throw PlatformSecurityError.invalidInput("LAN secure record nonce inputs must be positive.")
        }
        return lock.withLock {
            let key = "\(channel):\(sender):\(keyEpoch)"
            let next = (counters[key] ?? 0) + 1
            counters[key] = next
            var nonce = Data()
            nonce.appendLANUInt32(channel)
            nonce.appendLANUInt64(next)
            return nonce
        }
    }
}

extension P256.KeyAgreement.PrivateKey {
    func sharedSecretData(with peerPublicKey: Data) throws -> Data {
        guard peerPublicKey.count == LANSecureRecordNegotiation.uncompressedP256PublicKeyBytes else {
            throw LANSecureRecordError.invalidPeerKeyLength
        }
        let peer = try P256.KeyAgreement.PublicKey(x963Representation: peerPublicKey)
        let shared = try sharedSecretFromKeyAgreement(with: peer)
        return shared.withUnsafeBytes { Data($0) }
    }
}

private extension Data {
    mutating func appendLANUInt32(_ value: UInt32) {
        var bigEndian = value.bigEndian
        append(Data(bytes: &bigEndian, count: MemoryLayout<UInt32>.size))
    }

    mutating func appendLANUInt64(_ value: UInt64) {
        var bigEndian = value.bigEndian
        append(Data(bytes: &bigEndian, count: MemoryLayout<UInt64>.size))
    }
}
