import Foundation
import CryptoKit
import Network
import VibeScreenProtocol

enum WakeHostRequestError: Error, Equatable {
    case invalidRequestID
    case invalidMACAddress
    case invalidSecureOnPassword
    case invalidAuthorization
    case expiredAuthorization
    case replayedRequest
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
}

extension WakeHostRequestContext {
    init(_ request: VSWakeHostRequest) {
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
            signature: request.signature
        )
    }
}

protocol WakeHostAuthorizing: Sendable {
    var wakeAllowed: Bool { get }
    func authorizationFailure(for request: WakeHostRequestContext) -> WakeHostRequestError?
}

extension WakeHostAuthorizing {
    // This default is only a policy hook. Production allow implementations must
    // validate the full request context, including pairing identity and replay
    // fields, before returning true.
    func authorizationFailure(for request: WakeHostRequestContext) -> WakeHostRequestError? {
        wakeAllowed ? nil : .policyDenied
    }
}

struct DenyWakeHostAuthorizer: WakeHostAuthorizing {
    let wakeAllowed = false
}

struct StaticWakeHostAuthorizer: WakeHostAuthorizing {
    let wakeAllowed: Bool
}

protocol WakeHostReplayStoring: Sendable {
    func consume(keyID: String, nonce: Data) -> Bool
}

final class InMemoryWakeHostReplayStore: WakeHostReplayStoring, @unchecked Sendable {
    private let maximumEntries: Int
    private let lock = NSLock()
    private var seen: Set<String> = []
    private var order: [String] = []

    init(maximumEntries: Int = 256) {
        self.maximumEntries = max(1, maximumEntries)
    }

    func consume(keyID: String, nonce: Data) -> Bool {
        let key = keyID + ":" + nonce.base64EncodedString()
        return lock.withLock {
            guard !seen.contains(key) else { return false }
            seen.insert(key)
            order.append(key)
            while order.count > maximumEntries {
                seen.remove(order.removeFirst())
            }
            return true
        }
    }
}

struct SharedSecretWakeHostAuthorizer: WakeHostAuthorizing {
    static let maximumAuthorizationLifetimeSeconds: UInt64 = 120
    static let allowedClockSkewSeconds: UInt64 = 30

    private let secret: Data
    private let replayStore: any WakeHostReplayStoring
    private let now: @Sendable () -> UInt64

    var wakeAllowed: Bool { !secret.isEmpty }

    init(
        secret: Data,
        replayStore: any WakeHostReplayStoring = InMemoryWakeHostReplayStore(),
        now: @escaping @Sendable () -> UInt64 = { UInt64(Date().timeIntervalSince1970) }
    ) {
        self.secret = secret
        self.replayStore = replayStore
        self.now = now
    }

    func authorizationFailure(for request: WakeHostRequestContext) -> WakeHostRequestError? {
        guard wakeAllowed else { return .policyDenied }
        guard !request.keyID.isEmpty, request.keyID == WakeHostProof.keyID(secret: secret),
              request.nonce.count >= WakeHostProof.minimumNonceByteCount,
              request.signature.count == WakeHostProof.signatureByteCount else {
            return .invalidAuthorization
        }
        let current = now()
        let latestAllowedIssue = current.saturatingAdding(Self.allowedClockSkewSeconds)
        let latestAllowedCurrent = request.expiresAtUnixSeconds.saturatingAdding(Self.allowedClockSkewSeconds)
        guard request.expiresAtUnixSeconds > request.issuedAtUnixSeconds,
              request.expiresAtUnixSeconds - request.issuedAtUnixSeconds <= Self.maximumAuthorizationLifetimeSeconds,
              latestAllowedIssue >= request.issuedAtUnixSeconds,
              latestAllowedCurrent >= current else {
            return .expiredAuthorization
        }
        let expected = WakeHostProof.signature(
            requestID: request.requestID,
            targetMACAddress: request.targetMACAddress,
            secureOnPassword: request.secureOnPassword,
            hostID: request.hostID,
            deviceID: request.deviceID,
            keyID: request.keyID,
            issuedAtUnixSeconds: request.issuedAtUnixSeconds,
            expiresAtUnixSeconds: request.expiresAtUnixSeconds,
            nonce: request.nonce,
            secret: secret
        )
        guard WakeHostProof.constantTimeEquals(request.signature, expected) else {
            return .invalidAuthorization
        }
        guard replayStore.consume(keyID: request.keyID, nonce: request.nonce) else {
            return .replayedRequest
        }
        return nil
    }
}

private extension UInt64 {
    func saturatingAdding(_ value: UInt64) -> UInt64 {
        let result = addingReportingOverflow(value)
        return result.overflow ? UInt64.max : result.partialValue
    }
}

protocol WakeHostPacketSending: Sendable {
    func sendWakeHostPacket(_ packet: Data) throws
}

enum WakeHostPacketSenderError: Error, Equatable {
    case invalidBroadcastAddress
    case invalidPort
    case timedOut
}

struct WakeHostBroadcastTarget: Equatable {
    let address: String
    let port: UInt16

    init(address: String, port: UInt16) throws {
        guard port > 0 else { throw WakeHostPacketSenderError.invalidPort }
        let octets = address.split(separator: ".", omittingEmptySubsequences: false)
        guard octets.count == 4 else { throw WakeHostPacketSenderError.invalidBroadcastAddress }
        let values = try octets.map { part -> UInt8 in
            guard !part.isEmpty, part.allSatisfy({ $0 >= "0" && $0 <= "9" }),
                  let value = UInt8(part) else {
                throw WakeHostPacketSenderError.invalidBroadcastAddress
            }
            return value
        }
        guard values != [0, 0, 0, 0],
              values == [255, 255, 255, 255] || values[3] == 255 else {
            throw WakeHostPacketSenderError.invalidBroadcastAddress
        }
        self.address = address
        self.port = port
    }
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
        let target = try WakeHostBroadcastTarget(address: broadcastAddress, port: port)
        guard let endpointPort = NWEndpoint.Port(rawValue: target.port) else { throw WakeHostPacketSenderError.invalidPort }
        let connection = NWConnection(
            host: NWEndpoint.Host(target.address),
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

enum WakeHostProof {
    static let minimumNonceByteCount = 16
    static let signatureByteCount = 32
    private static let domain = Data("VS-WOL-HMAC-v1".utf8)

    static func keyID(secret: Data) -> String {
        Data(SHA256.hash(data: secret)).map { String(format: "%02x", $0) }.joined()
    }

    static func signature(
        requestID: Data,
        targetMACAddress: Data,
        secureOnPassword: Data,
        hostID: String,
        deviceID: String,
        keyID: String,
        issuedAtUnixSeconds: UInt64,
        expiresAtUnixSeconds: UInt64,
        nonce: Data,
        secret: Data
    ) -> Data {
        let canonical = canonicalBytes(
            requestID: requestID,
            targetMACAddress: targetMACAddress,
            secureOnPassword: secureOnPassword,
            hostID: hostID,
            deviceID: deviceID,
            keyID: keyID,
            issuedAtUnixSeconds: issuedAtUnixSeconds,
            expiresAtUnixSeconds: expiresAtUnixSeconds,
            nonce: nonce
        )
        return Data(HMAC<SHA256>.authenticationCode(for: canonical, using: SymmetricKey(data: secret)))
    }

    static func constantTimeEquals(_ lhs: Data, _ rhs: Data) -> Bool {
        guard lhs.count == rhs.count else { return false }
        var diff: UInt8 = 0
        for (left, right) in zip(lhs, rhs) { diff |= left ^ right }
        return diff == 0
    }

    private static func canonicalBytes(
        requestID: Data,
        targetMACAddress: Data,
        secureOnPassword: Data,
        hostID: String,
        deviceID: String,
        keyID: String,
        issuedAtUnixSeconds: UInt64,
        expiresAtUnixSeconds: UInt64,
        nonce: Data
    ) -> Data {
        var data = Data()
        appendField(domain, to: &data)
        appendField(requestID, to: &data)
        appendField(targetMACAddress, to: &data)
        appendField(secureOnPassword, to: &data)
        appendField(Data(hostID.utf8), to: &data)
        appendField(Data(deviceID.utf8), to: &data)
        appendField(Data(keyID.utf8), to: &data)
        appendUInt64(issuedAtUnixSeconds, to: &data)
        appendUInt64(expiresAtUnixSeconds, to: &data)
        appendField(nonce, to: &data)
        return data
    }

    private static func appendField(_ field: Data, to data: inout Data) {
        var length = UInt32(field.count).bigEndian
        data.append(Data(bytes: &length, count: MemoryLayout<UInt32>.size))
        data.append(field)
    }

    private static func appendUInt64(_ value: UInt64, to data: inout Data) {
        var encoded = value.bigEndian
        data.append(Data(bytes: &encoded, count: MemoryLayout<UInt64>.size))
    }
}

enum WakeHostDecision {
    static func magicPacket(
        for request: WakeHostRequestContext,
        authorizer: any WakeHostAuthorizing = DenyWakeHostAuthorizer()
    ) throws -> Data {
        guard !request.requestID.isEmpty else { throw WakeHostRequestError.invalidRequestID }
        if let failure = authorizer.authorizationFailure(for: request) { throw failure }
        return try WakeHostPacketBuilder.magicPacket(
            targetMACAddress: request.targetMACAddress,
            secureOnPassword: request.secureOnPassword
        )
    }
}
