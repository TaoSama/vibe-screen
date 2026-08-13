import CryptoKit
import Foundation

struct PlatformSessionKeys: Equatable {
    let keyID: String
    let keyEpoch: UInt64
    let hostControl: Data
    let deviceControl: Data
    let hostMedia: Data
    let deviceMedia: Data
    let hostAudio: Data
    let deviceAudio: Data
    let hostBulk: Data
    let deviceBulk: Data

    fileprivate var combined: Data {
        hostControl + deviceControl + hostMedia + deviceMedia
            + hostAudio + deviceAudio + hostBulk + deviceBulk
    }
}

enum PlatformSecurityChannel: UInt32 {
    case control = 1
    case media = 2
    case audio = 3
    case bulk = 4
}

enum PlatformSenderRole: UInt32 {
    case host = 1
    case device = 2
}

enum TrafficPacketCryptography {
    static func seal(plaintext: Data, key: Data, nonce: Data, authenticatedHeader: Data) throws -> Data {
        guard key.count == 32, nonce.count == 12 else {
            throw PlatformSecurityError.invalidInput("AES-256-GCM requires a 32-byte key and 12-byte nonce.")
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
        guard key.count == 32, nonce.count == 12, ciphertextAndTag.count >= 16 else {
            throw PlatformSecurityError.invalidInput("AES-256-GCM packet sizes are invalid.")
        }
        var combined = Data(capacity: nonce.count + ciphertextAndTag.count)
        combined.append(nonce)
        combined.append(ciphertextAndTag)
        let box = try AES.GCM.SealedBox(combined: combined)
        return try AES.GCM.open(box, using: SymmetricKey(data: key), authenticating: authenticatedHeader)
    }
}

extension PlatformSessionKeys {
    func key(channel: PlatformSecurityChannel, sender: PlatformSenderRole) -> Data {
        switch (channel, sender) {
        case (.control, .host): return hostControl
        case (.control, .device): return deviceControl
        case (.media, .host): return hostMedia
        case (.media, .device): return deviceMedia
        case (.audio, .host): return hostAudio
        case (.audio, .device): return deviceAudio
        case (.bulk, .host): return hostBulk
        case (.bulk, .device): return deviceBulk
        }
    }
}

enum TrafficKeyDerivation {
    private static let materialLength = 256

    static func initial(sharedSecret: Data, bootstrapSecret: Data, context: Data) throws -> PlatformSessionKeys {
        guard !sharedSecret.isEmpty, bootstrapSecret.count == 32, context.count == 32 else {
            throw PlatformSecurityError.invalidInput("Initial key derivation requires a shared secret, 32-byte bootstrap secret, and 32-byte transcript context.")
        }
        let material = hkdf(input: sharedSecret, salt: bootstrapSecret, info: context)
        return split(material: material, context: context, epoch: 1)
    }

    static func rotate(current: PlatformSessionKeys, nextEpoch: UInt64, updateNonce: Data) throws -> PlatformSessionKeys {
        guard current.keyEpoch > 0, !current.keyID.isEmpty,
              current.keyEpoch < UInt64.max, nextEpoch == current.keyEpoch + 1,
              updateNonce.count >= 16 else {
            throw PlatformSecurityError.invalidInput("Traffic-key rotation must advance exactly one epoch and use at least 16 nonce bytes.")
        }
        let context = SecurityTranscript.digest(
            domain: "vibescreen/traffic-key-update/v1",
            parts: [
                Data(current.keyID.utf8),
                SecurityTranscript.uint64(current.keyEpoch),
                SecurityTranscript.uint64(nextEpoch),
                updateNonce
            ]
        )
        let material = hkdf(input: current.combined, salt: updateNonce, info: context)
        return split(material: material, context: context, epoch: nextEpoch)
    }

    private static func hkdf(input: Data, salt: Data, info: Data) -> Data {
        let key = HKDF<SHA256>.deriveKey(
            inputKeyMaterial: SymmetricKey(data: input),
            salt: salt,
            info: info,
            outputByteCount: materialLength
        )
        return key.withUnsafeBytes { Data($0) }
    }

    private static func split(material: Data, context: Data, epoch: UInt64) -> PlatformSessionKeys {
        precondition(material.count == materialLength)
        // Preserve the Phase 3 key identifier while extending the HKDF tail.
        let firstDigest = Data(SHA256.hash(data: context + Data(material.prefix(128))))
        let keyID = Data(SHA256.hash(data: firstDigest)).map { String(format: "%02x", $0) }.joined()
        return PlatformSessionKeys(
            keyID: keyID,
            keyEpoch: epoch,
            hostControl: material.subdata(in: 0..<32),
            deviceControl: material.subdata(in: 32..<64),
            hostMedia: material.subdata(in: 64..<96),
            deviceMedia: material.subdata(in: 96..<128),
            hostAudio: material.subdata(in: 128..<160),
            deviceAudio: material.subdata(in: 160..<192),
            hostBulk: material.subdata(in: 192..<224),
            deviceBulk: material.subdata(in: 224..<256)
        )
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
        output.append(uint64(UInt64(value.count)))
        output.append(value)
    }

    static func uint64(_ value: UInt64) -> Data {
        var bigEndian = value.bigEndian
        return Data(bytes: &bigEndian, count: MemoryLayout<UInt64>.size)
    }
}
