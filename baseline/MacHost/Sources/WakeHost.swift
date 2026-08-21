import Foundation
import Network
import VibeScreenProtocol

enum WakeHostRequestError: Error, Equatable {
    case invalidRequestID
    case invalidMACAddress
    case invalidSecureOnPassword
    case invalidHostIdentity
    case invalidDeviceIdentity
    case expiredProof
    case invalidNonce
    case replayedNonce
    case invalidSignature
    case policyDenied
}

struct WakeHostRequestContext: Equatable {
    let requestID: Data
    let targetMACAddress: Data
    let secureOnPassword: Data
    let hostID: String
    let deviceID: String
    let keyID: String
    let issuedAtUnixSeconds: UInt64
    let expiresAtUnixSeconds: UInt64
    let nonce: Data
    let signature: Data
    let sessionID: Data
    let sessionEpoch: UInt64

    init(
        requestID: Data,
        targetMACAddress: Data,
        secureOnPassword: Data,
        hostID: String,
        deviceID: String,
        keyID: String,
        issuedAtUnixSeconds: UInt64,
        expiresAtUnixSeconds: UInt64,
        nonce: Data,
        signature: Data,
        sessionID: Data = Data(),
        sessionEpoch: UInt64 = 0
    ) {
        self.requestID = requestID
        self.targetMACAddress = targetMACAddress
        self.secureOnPassword = secureOnPassword
        self.hostID = hostID
        self.deviceID = deviceID
        self.keyID = keyID
        self.issuedAtUnixSeconds = issuedAtUnixSeconds
        self.expiresAtUnixSeconds = expiresAtUnixSeconds
        self.nonce = nonce
        self.signature = signature
        self.sessionID = sessionID
        self.sessionEpoch = sessionEpoch
    }
}

extension WakeHostRequestContext {
    init(_ request: VSWakeHostRequest, sessionID: Data, sessionEpoch: UInt64) {
        self.init(
            requestID: request.requestID,
            targetMACAddress: request.targetMacAddress,
            secureOnPassword: request.secureOnPassword,
            hostID: request.hostID,
            deviceID: request.deviceID,
            keyID: request.keyID,
            issuedAtUnixSeconds: request.issuedAtUnixSeconds,
            expiresAtUnixSeconds: request.expiresAtUnixSeconds,
            nonce: request.nonce,
            signature: request.signature,
            sessionID: sessionID,
            sessionEpoch: sessionEpoch
        )
    }

    var hasProofFields: Bool {
        !hostID.isEmpty &&
            !deviceID.isEmpty &&
            !keyID.isEmpty &&
            issuedAtUnixSeconds > 0 &&
            expiresAtUnixSeconds > issuedAtUnixSeconds &&
            nonce.count >= 16 &&
            !signature.isEmpty &&
            !sessionID.isEmpty &&
            sessionEpoch > 0
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}

protocol WakeHostAuthorizing: Sendable {
    var wakeAllowed: Bool { get }
    func wakeAllowed(for request: WakeHostRequestContext) throws -> Bool
}

extension WakeHostAuthorizing {
    // This default is only a policy hook. Production allow implementations must
    // validate the full request context, including pairing identity and replay
    // fields, before returning true.
    func wakeAllowed(for request: WakeHostRequestContext) throws -> Bool { wakeAllowed }
}

struct DenyWakeHostAuthorizer: WakeHostAuthorizing {
    let wakeAllowed = false
}

struct StaticWakeHostAuthorizer: WakeHostAuthorizing {
    let wakeAllowed: Bool
}

protocol WakeHostNonceConsuming: Sendable {
    func consumeWakeHostNonce(
        deviceID: String,
        keyID: String,
        sessionID: Data,
        sessionEpoch: UInt64,
        nonce: Data
    ) throws
}

final class MemoryWakeHostNonceStore: WakeHostNonceConsuming, @unchecked Sendable {
    private let lock = NSLock()
    private var consumed: Set<String> = []

    func consumeWakeHostNonce(
        deviceID: String,
        keyID: String,
        sessionID: Data,
        sessionEpoch: UInt64,
        nonce: Data
    ) throws {
        let key = Self.key(
            deviceID: deviceID,
            keyID: keyID,
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            nonce: nonce
        )
        try lock.withLock {
            guard !consumed.contains(key) else {
                throw WakeHostRequestError.replayedNonce
            }
            consumed.insert(key)
        }
    }

    private static func key(
        deviceID: String,
        keyID: String,
        sessionID: Data,
        sessionEpoch: UInt64,
        nonce: Data
    ) -> String {
        let session = sessionID.map { String(format: "%02x", $0) }.joined()
        let nonceHex = nonce.map { String(format: "%02x", $0) }.joined()
        return "\(deviceID)|\(keyID)|\(session)|\(sessionEpoch)|\(nonceHex)"
    }
}

struct PairingBoundWakeHostAuthorizer: WakeHostAuthorizing {
    static let maximumClockSkewSeconds: UInt64 = 300
    static let maximumProofLifetimeSeconds: UInt64 = 300

    let hostIdentity: PlatformPublicIdentity
    let peerIdentity: PlatformPublicIdentity
    let nonceStore: any WakeHostNonceConsuming
    let nowUnixSeconds: @Sendable () -> UInt64

    var wakeAllowed: Bool { true }

    init(
        hostIdentity: PlatformPublicIdentity,
        peerIdentity: PlatformPublicIdentity,
        nonceStore: any WakeHostNonceConsuming,
        nowUnixSeconds: @escaping @Sendable () -> UInt64 = { UInt64(Date().timeIntervalSince1970) }
    ) {
        self.hostIdentity = hostIdentity
        self.peerIdentity = peerIdentity
        self.nonceStore = nonceStore
        self.nowUnixSeconds = nowUnixSeconds
    }

    func wakeAllowed(for request: WakeHostRequestContext) throws -> Bool {
        try validate(request)
        return true
    }

    func validate(_ request: WakeHostRequestContext) throws {
        try Self.validateFields(
            request,
            hostIdentity: hostIdentity,
            peerIdentity: peerIdentity,
            nowUnixSeconds: nowUnixSeconds()
        )
        let digest = Self.proofDigest(for: request)
        guard InternetPairingCanonical.verify(
            signature: request.signature,
            digest: digest,
            publicKey: peerIdentity.signingPublicKey
        ) else {
            throw WakeHostRequestError.invalidSignature
        }
        try nonceStore.consumeWakeHostNonce(
            deviceID: request.deviceID,
            keyID: request.keyID,
            sessionID: request.sessionID,
            sessionEpoch: request.sessionEpoch,
            nonce: request.nonce
        )
    }

    static func proofDigest(for request: WakeHostRequestContext) -> Data {
        SecurityTranscript.digest(
            domain: "vibescreen/wake-host-request/v1",
            parts: [
                request.requestID,
                request.targetMACAddress,
                request.secureOnPassword,
                Data(request.hostID.utf8),
                Data(request.deviceID.utf8),
                Data(request.keyID.utf8),
                SecurityTranscript.uint64(request.issuedAtUnixSeconds),
                SecurityTranscript.uint64(request.expiresAtUnixSeconds),
                request.nonce,
                request.sessionID,
                SecurityTranscript.uint64(request.sessionEpoch)
            ]
        )
    }

    private static func validateFields(
        _ request: WakeHostRequestContext,
        hostIdentity: PlatformPublicIdentity,
        peerIdentity: PlatformPublicIdentity,
        nowUnixSeconds: UInt64
    ) throws {
        guard request.hostID == hostIdentity.deviceID,
              !request.hostID.isEmpty else {
            throw WakeHostRequestError.invalidHostIdentity
        }
        guard request.deviceID == peerIdentity.deviceID,
              request.keyID == peerIdentity.keyID,
              !request.deviceID.isEmpty,
              !request.keyID.isEmpty else {
            throw WakeHostRequestError.invalidDeviceIdentity
        }
        guard request.nonce.count >= 16,
              request.nonce.contains(where: { $0 != 0 }) else {
            throw WakeHostRequestError.invalidNonce
        }
        guard !request.sessionID.isEmpty, request.sessionEpoch > 0 else {
            throw WakeHostRequestError.expiredProof
        }
        guard request.issuedAtUnixSeconds > 0,
              request.expiresAtUnixSeconds > request.issuedAtUnixSeconds,
              request.expiresAtUnixSeconds - request.issuedAtUnixSeconds <= maximumProofLifetimeSeconds,
              nowUnixSeconds + maximumClockSkewSeconds >= request.issuedAtUnixSeconds,
              nowUnixSeconds < request.expiresAtUnixSeconds else {
            throw WakeHostRequestError.expiredProof
        }
        guard !request.signature.isEmpty else {
            throw WakeHostRequestError.invalidSignature
        }
    }
}

protocol WakeHostPacketSending: Sendable {
    func sendWakeHostPacket(_ packet: Data) throws
}

enum WakeHostPacketSenderError: Error {
    case invalidPort
    case timedOut
}

struct UDPWakeHostPacketSender: WakeHostPacketSending {
    let broadcastAddress: String
    let port: UInt16
    let timeoutNanoseconds: UInt64

    init(
        broadcastAddress: String = "255.255.255.255",
        port: UInt16 = 9,
        timeoutNanoseconds: UInt64 = 1_000_000_000
    ) {
        self.broadcastAddress = broadcastAddress
        self.port = port
        self.timeoutNanoseconds = timeoutNanoseconds
    }

    func sendWakeHostPacket(_ packet: Data) throws {
        guard port > 0,
              let endpointPort = NWEndpoint.Port(rawValue: port) else {
            throw WakeHostPacketSenderError.invalidPort
        }
        let connection = NWConnection(
            host: NWEndpoint.Host(broadcastAddress),
            port: endpointPort,
            using: .udp
        )
        let semaphore = DispatchSemaphore(value: 0)
        let result = LockedWakeHostSendResult()
        connection.start(queue: .global(qos: .userInitiated))
        connection.send(content: packet, completion: .contentProcessed { error in
            result.store(error)
            connection.cancel()
            semaphore.signal()
        })
        let timeout = DispatchTime.now() + .nanoseconds(Int(min(timeoutNanoseconds, UInt64(Int.max))))
        guard semaphore.wait(timeout: timeout) == .success else {
            connection.cancel()
            throw WakeHostPacketSenderError.timedOut
        }
        if let error = result.value { throw error }
    }
}

private final class LockedWakeHostSendResult: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Error?

    var value: Error? { lock.withLock { stored } }

    func store(_ error: Error?) {
        lock.withLock { stored = error }
    }
}

enum WakeHostPacketBuilder {
    static let targetMACAddressByteCount = 6
    static let secureOnPasswordByteCount = 6
    static let baseMagicPacketByteCount = 102

    static func magicPacket(
        targetMACAddress: Data,
        secureOnPassword: Data = Data()
    ) throws -> Data {
        guard targetMACAddress.count == targetMACAddressByteCount,
              targetMACAddress.contains(where: { $0 != 0 }),
              targetMACAddress.contains(where: { $0 != 0xff }) else {
            throw WakeHostRequestError.invalidMACAddress
        }
        guard secureOnPassword.isEmpty || secureOnPassword.count == secureOnPasswordByteCount else {
            throw WakeHostRequestError.invalidSecureOnPassword
        }
        var packet = Data(capacity: secureOnPassword.isEmpty ? baseMagicPacketByteCount : baseMagicPacketByteCount + secureOnPasswordByteCount)
        packet.append(Data(repeating: 0xff, count: 6))
        for _ in 0..<16 { packet.append(targetMACAddress) }
        packet.append(secureOnPassword)
        return packet
    }
}

enum WakeHostDecision {
    static func magicPacket(
        for request: WakeHostRequestContext,
        authorizer: any WakeHostAuthorizing = DenyWakeHostAuthorizer()
    ) throws -> Data {
        guard !request.requestID.isEmpty else { throw WakeHostRequestError.invalidRequestID }
        guard try authorizer.wakeAllowed(for: request) else { throw WakeHostRequestError.policyDenied }
        return try WakeHostPacketBuilder.magicPacket(
            targetMACAddress: request.targetMACAddress,
            secureOnPassword: request.secureOnPassword
        )
    }
}
