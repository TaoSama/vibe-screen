import CryptoKit
import Darwin
import Foundation

final class PlatformSessionKeys: Equatable {
    let keyID: String
    let keyEpoch: UInt64
    private(set) var hostControl: Data
    private(set) var deviceControl: Data
    private(set) var hostMedia: Data
    private(set) var deviceMedia: Data
    private(set) var hostAudio: Data
    private(set) var deviceAudio: Data
    private(set) var hostBulk: Data
    private(set) var deviceBulk: Data
    private var closed = false

    fileprivate var legacyCombined: Data {
        hostControl + deviceControl + hostMedia + deviceMedia
    }

    init(
        keyID: String,
        keyEpoch: UInt64,
        hostControl: Data,
        deviceControl: Data,
        hostMedia: Data,
        deviceMedia: Data,
        hostAudio: Data,
        deviceAudio: Data,
        hostBulk: Data,
        deviceBulk: Data
    ) {
        self.keyID = keyID
        self.keyEpoch = keyEpoch
        self.hostControl = hostControl
        self.deviceControl = deviceControl
        self.hostMedia = hostMedia
        self.deviceMedia = deviceMedia
        self.hostAudio = hostAudio
        self.deviceAudio = deviceAudio
        self.hostBulk = hostBulk
        self.deviceBulk = deviceBulk
    }

    static func == (lhs: PlatformSessionKeys, rhs: PlatformSessionKeys) -> Bool {
        lhs.keyID == rhs.keyID && lhs.keyEpoch == rhs.keyEpoch &&
            lhs.hostControl == rhs.hostControl && lhs.deviceControl == rhs.deviceControl &&
            lhs.hostMedia == rhs.hostMedia && lhs.deviceMedia == rhs.deviceMedia &&
            lhs.hostAudio == rhs.hostAudio && lhs.deviceAudio == rhs.deviceAudio &&
            lhs.hostBulk == rhs.hostBulk && lhs.deviceBulk == rhs.deviceBulk
    }

    func copy() -> PlatformSessionKeys {
        PlatformSessionKeys(
            keyID: keyID,
            keyEpoch: keyEpoch,
            hostControl: hostControl.ownedCopy,
            deviceControl: deviceControl.ownedCopy,
            hostMedia: hostMedia.ownedCopy,
            deviceMedia: deviceMedia.ownedCopy,
            hostAudio: hostAudio.ownedCopy,
            deviceAudio: deviceAudio.ownedCopy,
            hostBulk: hostBulk.ownedCopy,
            deviceBulk: deviceBulk.ownedCopy
        )
    }

    /// Overwrites all eight traffic-key buffers in place using memset_s so
    /// the compiler cannot elide the store.
    func zeroize() {
        hostControl.zeroize()
        deviceControl.zeroize()
        hostMedia.zeroize()
        deviceMedia.zeroize()
        hostAudio.zeroize()
        deviceAudio.zeroize()
        hostBulk.zeroize()
        deviceBulk.zeroize()
    }

    func close() {
        guard !closed else { return }
        zeroize()
        closed = true
    }

    var isClearedForTest: Bool {
        closed && [
            hostControl, deviceControl, hostMedia, deviceMedia,
            hostAudio, deviceAudio, hostBulk, deviceBulk,
        ].allSatisfy { $0.allSatisfy { $0 == 0 } }
    }

    deinit { close() }
}

extension Data {
    /// Overwrites the buffer with zeros using memset_s so the compiler cannot
    /// elide the store. For uniquely-referenced Data this clears the actual
    /// backing bytes; shared (COW) buffers are copied first.
    mutating func zeroize() {
        guard !isEmpty else { return }
        _ = withUnsafeMutableBytes { bytes in
            memset_s(bytes.baseAddress, bytes.count, 0, bytes.count)
        }
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
        defer { combined.zeroize() }
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
    private static let legacyMaterialLength = 128
    private static let materialLength = 256

    static func initial(sharedSecret: Data, bootstrapSecret: Data, context: Data) throws -> PlatformSessionKeys {
        guard !sharedSecret.isEmpty, bootstrapSecret.count == 32, context.count == 32 else {
            throw PlatformSecurityError.invalidInput("Initial key derivation requires a shared secret, 32-byte bootstrap secret, and 32-byte transcript context.")
        }
        var material = hkdf(input: sharedSecret, salt: bootstrapSecret, info: context)
        defer { material.zeroize() }
        return split(material: material, context: context, epoch: 1)
    }

    static func rotate(current: PlatformSessionKeys, nextEpoch: UInt64, updateNonce: Data) throws -> PlatformSessionKeys {
        guard current.keyEpoch > 0, !current.keyID.isEmpty,
              current.keyEpoch < UInt64.max, nextEpoch == current.keyEpoch + 1,
              updateNonce.count >= 16 else {
            throw PlatformSecurityError.invalidInput("Traffic-key rotation must advance exactly one epoch and use at least 16 nonce bytes.")
        }
        var context = SecurityTranscript.digest(
            domain: "vibescreen/traffic-key-update/v1",
            parts: [
                Data(current.keyID.utf8),
                SecurityTranscript.uint64(current.keyEpoch),
                SecurityTranscript.uint64(nextEpoch),
                updateNonce
            ]
        )
        defer { context.zeroize() }
        // Preserve rotation compatibility with peers that negotiated only control/media.
        var legacyInput = current.legacyCombined
        defer { legacyInput.zeroize() }
        var material = hkdf(input: legacyInput, salt: updateNonce, info: context)
        defer { material.zeroize() }
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
        var keyIDHasher = SHA256()
        keyIDHasher.update(data: context)
        // Keep the v1 key ID stable for control/media-only peers.
        keyIDHasher.update(data: material.prefix(legacyMaterialLength))
        var firstDigest = Data(keyIDHasher.finalize())
        defer { firstDigest.zeroize() }
        var keyIDDigest = Data(SHA256.hash(data: firstDigest))
        defer { keyIDDigest.zeroize() }
        let keyID = keyIDDigest.map { String(format: "%02x", $0) }.joined()
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

extension Data {
    var ownedCopy: Data { withUnsafeBytes { Data($0) } }
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
