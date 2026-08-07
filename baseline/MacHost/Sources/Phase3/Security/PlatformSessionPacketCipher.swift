import CryptoKit
import Foundation

/// Protocol v1 record protection above WebRTC. TURN and signaling never see
/// application plaintext or traffic keys.
final class PlatformSessionPacketCipher {
    static let recordOverhead = 67

    let sessionIdentifier: String
    let sessionEpoch: UInt64

    private static let magic: UInt32 = 0x56534352
    private static let version: UInt8 = 1
    private static let sessionHashBytes = 16
    private static let nonceBytes = 12
    private static let tagBytes = 16
    private static let headerBytes = 51

    private let localRole: PlatformSenderRole
    private let withActiveSessionEpoch: (() throws -> Data?) throws -> Data?
    private let reserveNonce: (UInt32, UInt32, UInt64) throws -> Data
    private let rotateKeys: (PlatformSessionKeys, Data) throws -> PlatformSessionKeys
    private let lock = NSLock()
    private var keys: PlatformSessionKeys?
    private var replay: [PlatformSecurityChannel: ReplayWindow] = [:]
    private var sessionHash: Data

    init(
        sessionIdentifier: String,
        sessionEpoch: UInt64,
        localRole: PlatformSenderRole,
        initialKeys: PlatformSessionKeys,
        platformSecurity: PlatformSessionSecurity
    ) {
        self.sessionIdentifier = sessionIdentifier
        self.sessionEpoch = sessionEpoch
        self.localRole = localRole
        self.keys = initialKeys
        self.sessionHash = Data(SHA256.hash(data: Data(sessionIdentifier.utf8))).prefix(Self.sessionHashBytes)
        self.withActiveSessionEpoch = { operation in
            try platformSecurity.withActiveSessionEpoch(
                sessionEpoch,
                operation: operation
            )
        }
        self.reserveNonce = { channel, senderRole, keyEpoch in
            try platformSecurity.reserveNonce(
                sessionEpoch: sessionEpoch,
                channel: channel,
                senderRole: senderRole,
                keyEpoch: keyEpoch
            )
        }
        self.rotateKeys = platformSecurity.rotateTrafficKeys
    }

    private init(
        sessionIdentifier: String,
        sessionEpoch: UInt64,
        localRole: PlatformSenderRole,
        initialKeys: PlatformSessionKeys,
        withActiveSessionEpoch: @escaping (() throws -> Data?) throws -> Data?,
        reserveNonce: @escaping (UInt32, UInt32, UInt64) throws -> Data,
        rotateKeys: @escaping (PlatformSessionKeys, Data) throws -> PlatformSessionKeys
    ) {
        self.sessionIdentifier = sessionIdentifier
        self.sessionEpoch = sessionEpoch
        self.localRole = localRole
        self.keys = initialKeys
        self.sessionHash = Data(SHA256.hash(data: Data(sessionIdentifier.utf8))).prefix(Self.sessionHashBytes)
        self.withActiveSessionEpoch = withActiveSessionEpoch
        self.reserveNonce = reserveNonce
        self.rotateKeys = rotateKeys
    }

    func seal(_ payload: Data, channel: InternetTransportChannel) throws -> Data {
        try lock.withPacketCipherLock {
            guard let keys else { throw PlatformSecurityError.invalidInput("Session packet cipher is closed.") }
            guard let record = try withActiveSessionEpoch({
                let securityChannel = channel.securityChannel
                let nonce = try reserveNonce(securityChannel.rawValue, localRole.rawValue, keys.keyEpoch)
                guard nonce.count == Self.nonceBytes else {
                    throw PlatformSecurityError.persistenceFailure("Durable nonce allocator returned an invalid nonce.")
                }
                let header = makeHeader(keyEpoch: keys.keyEpoch, sender: localRole, channel: securityChannel, nonce: nonce)
                return header + (try TrafficPacketCryptography.seal(
                    plaintext: payload,
                    key: keys.key(channel: securityChannel, sender: localRole),
                    nonce: nonce,
                    authenticatedHeader: header
                ))
            }) else {
                throw PlatformSecurityError.persistenceFailure("Active session seal returned no record.")
            }
            return record
        }
    }

    func open(_ record: Data, channel: InternetTransportChannel) -> Data? {
        lock.withPacketCipherLock {
            guard let keys, record.count >= Self.headerBytes + Self.tagBytes else { return nil }
            do {
                return try withActiveSessionEpoch {
                    let header = record.prefix(Self.headerBytes)
                    guard let decoded = decodeHeader(Data(header)) else { return nil }
                    let expectedChannel = channel.securityChannel
                    let expectedSender = localRole.remote
                    guard decoded.sessionHash == sessionHash,
                          decoded.sessionEpoch == sessionEpoch,
                          decoded.keyEpoch == keys.keyEpoch,
                          decoded.sender == expectedSender,
                          decoded.channel == expectedChannel,
                          decodeUInt32(decoded.nonce.prefix(4)) == expectedChannel.rawValue else {
                        return nil
                    }
                    let sequence = decodeUInt64(decoded.nonce.suffix(8))
                    var window = replay[expectedChannel] ?? ReplayWindow(strictlyOrdered: expectedChannel == .control)
                    guard window.canAccept(sequence) else { return nil }
                    guard let plaintext = try? TrafficPacketCryptography.open(
                        ciphertextAndTag: Data(record.dropFirst(Self.headerBytes)),
                        key: keys.key(channel: expectedChannel, sender: expectedSender),
                        nonce: decoded.nonce,
                        authenticatedHeader: Data(header)
                    ) else { return nil }
                    window.commit(sequence)
                    replay[expectedChannel] = window
                    return plaintext
                }
            } catch {
                return nil
            }
        }
    }

    func rotate(updateNonce: Data) throws {
        try lock.withPacketCipherLock {
            guard let current = keys else {
                throw PlatformSecurityError.invalidInput("Session packet cipher is closed.")
            }
            keys = try rotateKeys(current, updateNonce)
            replay.removeAll()
        }
    }

    func close() {
        lock.withPacketCipherLock {
            keys = nil
            replay.removeAll()
            sessionHash.resetBytes(in: 0..<sessionHash.count)
        }
    }

    static func selfTestPair(
        sessionIdentifier: String,
        sharedSecret: Data,
        bootstrapSecret: Data,
        transcriptContext: Data,
        sessionEpoch: UInt64 = 1,
        requireActiveEpoch: @escaping (UInt64) throws -> Void = { _ in },
        withActiveEpoch: ((_ epoch: UInt64, _ operation: () throws -> Data?) throws -> Data?)? = nil
    ) throws -> (host: PlatformSessionPacketCipher, device: PlatformSessionPacketCipher) {
        let keys = try TrafficKeyDerivation.initial(
            sharedSecret: sharedSecret,
            bootstrapSecret: bootstrapSecret,
            context: transcriptContext
        )
        let counters = SelfTestNonceCounters()
        let reserve: (UInt32, UInt32, UInt64) throws -> Data = { channel, sender, keyEpoch in
            try counters.reserve(channel: channel, sender: sender, keyEpoch: keyEpoch)
        }
        let rotate: (PlatformSessionKeys, Data) throws -> PlatformSessionKeys = { current, nonce in
            try TrafficKeyDerivation.rotate(current: current, nextEpoch: current.keyEpoch + 1, updateNonce: nonce)
        }
        let activeOperation = withActiveEpoch ?? { epoch, operation in
            try requireActiveEpoch(epoch)
            return try operation()
        }
        return (
            PlatformSessionPacketCipher(
                sessionIdentifier: sessionIdentifier,
                sessionEpoch: sessionEpoch,
                localRole: .host,
                initialKeys: keys,
                withActiveSessionEpoch: { try activeOperation(sessionEpoch, $0) },
                reserveNonce: reserve,
                rotateKeys: rotate
            ),
            PlatformSessionPacketCipher(
                sessionIdentifier: sessionIdentifier,
                sessionEpoch: sessionEpoch,
                localRole: .device,
                initialKeys: keys,
                withActiveSessionEpoch: { try activeOperation(sessionEpoch, $0) },
                reserveNonce: reserve,
                rotateKeys: rotate
            )
        )
    }

    private func makeHeader(
        keyEpoch: UInt64,
        sender: PlatformSenderRole,
        channel: PlatformSecurityChannel,
        nonce: Data
    ) -> Data {
        var header = Data()
        header.appendUInt32(Self.magic)
        header.append(Self.version)
        header.append(sessionHash)
        header.appendUInt64(sessionEpoch)
        header.appendUInt64(keyEpoch)
        header.append(UInt8(sender.rawValue))
        header.append(UInt8(channel.rawValue))
        header.append(nonce)
        return header
    }

    private func decodeHeader(_ header: Data) -> DecodedHeader? {
        guard header.count == Self.headerBytes,
              decodeUInt32(header.prefix(4)) == Self.magic,
              header[4] == Self.version,
              let sender = PlatformSenderRole(rawValue: UInt32(header[37])),
              let channel = PlatformSecurityChannel(rawValue: UInt32(header[38])) else { return nil }
        return DecodedHeader(
            sessionHash: header.subdata(in: 5..<21),
            sessionEpoch: decodeUInt64(header.subdata(in: 21..<29)),
            keyEpoch: decodeUInt64(header.subdata(in: 29..<37)),
            sender: sender,
            channel: channel,
            nonce: header.subdata(in: 39..<51)
        )
    }
}

struct ActiveProtectedInternetSession {
    let identity: KeychainDeviceIdentity
    let sessionEpoch: UInt64
    let packetCipher: PlatformSessionPacketCipher
}

extension PlatformSessionSecurity {
    func startStoredProtectedInternetSession(
        sessionIdentifier: String,
        localRole: PlatformSenderRole,
        identityEpoch: UInt64,
        secretNames: PairedDeviceSecretNames,
        transcriptContext: Data,
        agreedSessionEpoch: UInt64? = nil,
        secretStore: any InternetPairingSecretStore = KeychainSecretStore()
    ) throws -> ActiveProtectedInternetSession {
        guard let pairingIdentifier = secretNames.pairingIdentifier else {
            throw PlatformSecurityError.persistenceFailure(
                "The paired-device durable security owner is unknown. Pair again; existing credentials were retained."
            )
        }
        try requirePairingBinding(pairingIdentifier)
        guard let identityBindingName = secretNames.identityBinding,
              let encodedIdentityBinding = try secretStore.load(name: identityBindingName) else {
            throw PlatformSecurityError.persistenceFailure(
                "The paired host identity binding is missing. Pair again; existing credentials were retained."
            )
        }
        let identityBinding = try PairedHostIdentityBinding.decode(encodedIdentityBinding)
        guard let sharedSecret = try secretStore.load(name: secretNames.sharedSecret),
              let bootstrapSecret = try secretStore.load(name: secretNames.bootstrapSecret) else {
            throw PlatformSecurityError.persistenceFailure(
                "Paired-device session secrets are missing from Keychain."
            )
        }
        return try startProtectedInternetSession(
            sessionIdentifier: sessionIdentifier,
            localRole: localRole,
            expectedIdentity: identityBinding,
            identityEpoch: identityEpoch,
            sharedSecret: sharedSecret,
            bootstrapSecret: bootstrapSecret,
            transcriptContext: transcriptContext,
            agreedSessionEpoch: agreedSessionEpoch
        )
    }

    func startProtectedInternetSession(
        sessionIdentifier: String,
        localRole: PlatformSenderRole,
        expectedIdentity: PairedHostIdentityBinding,
        identityEpoch: UInt64,
        sharedSecret: Data,
        bootstrapSecret: Data,
        transcriptContext: Data,
        agreedSessionEpoch: UInt64? = nil
    ) throws -> ActiveProtectedInternetSession {
        guard !sessionIdentifier.isEmpty else {
            throw PlatformSecurityError.invalidInput("A signaling session identifier is required.")
        }
        let active: ActivePlatformSecuritySession
        if let agreedSessionEpoch {
            active = try startSession(
                expectedIdentity: expectedIdentity,
                agreedSessionEpoch: agreedSessionEpoch,
                identityEpoch: identityEpoch,
                sharedSecret: sharedSecret,
                bootstrapSecret: bootstrapSecret,
                transcriptContext: transcriptContext
            )
        } else {
            active = try startSession(
                expectedIdentity: expectedIdentity,
                identityEpoch: identityEpoch,
                sharedSecret: sharedSecret,
                bootstrapSecret: bootstrapSecret,
                transcriptContext: transcriptContext
            )
        }
        return ActiveProtectedInternetSession(
            identity: active.identity,
            sessionEpoch: active.sessionEpoch,
            packetCipher: PlatformSessionPacketCipher(
                sessionIdentifier: sessionIdentifier,
                sessionEpoch: active.sessionEpoch,
                localRole: localRole,
                initialKeys: active.trafficKeys,
                platformSecurity: self
            )
        )
    }
}

private struct DecodedHeader {
    let sessionHash: Data
    let sessionEpoch: UInt64
    let keyEpoch: UInt64
    let sender: PlatformSenderRole
    let channel: PlatformSecurityChannel
    let nonce: Data
}

private struct ReplayWindow {
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

private final class SelfTestNonceCounters {
    private let lock = NSLock()
    private var counters: [String: UInt64] = [:]

    func reserve(channel: UInt32, sender: UInt32, keyEpoch: UInt64) throws -> Data {
        try lock.withPacketCipherLock {
            let key = "\(channel):\(sender):\(keyEpoch)"
            let next = (counters[key] ?? 0) + 1
            guard next > 0 else { throw PlatformSecurityError.exhausted("Self-test nonce exhausted.") }
            counters[key] = next
            var nonce = Data()
            nonce.appendUInt32(channel)
            nonce.appendUInt64(next)
            return nonce
        }
    }
}

private extension InternetTransportChannel {
    var securityChannel: PlatformSecurityChannel {
        switch self {
        case .control: return .control
        case .media: return .media
        }
    }
}

private extension PlatformSenderRole {
    var remote: PlatformSenderRole { self == .host ? .device : .host }
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

private func decodeUInt32(_ data: Data) -> UInt32 {
    data.reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
}

private func decodeUInt64(_ data: Data) -> UInt64 {
    data.reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
}

private extension NSLock {
    func withPacketCipherLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
