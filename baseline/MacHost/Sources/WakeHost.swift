import Foundation
import Network
import VibeScreenProtocol

enum WakeHostRequestError: Error, Equatable {
    case invalidRequestID
    case invalidMACAddress
    case invalidSecureOnPassword
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
    func wakeAllowed(for request: WakeHostRequestContext) -> Bool
}

extension WakeHostAuthorizing {
    // This default is only a policy hook. Production allow implementations must
    // validate the full request context, including pairing identity and replay
    // fields, before returning true.
    func wakeAllowed(for request: WakeHostRequestContext) -> Bool { wakeAllowed }
}

struct DenyWakeHostAuthorizer: WakeHostAuthorizing {
    let wakeAllowed = false
}

struct StaticWakeHostAuthorizer: WakeHostAuthorizing {
    let wakeAllowed: Bool
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
        guard authorizer.wakeAllowed(for: request) else { throw WakeHostRequestError.policyDenied }
        return try WakeHostPacketBuilder.magicPacket(
            targetMACAddress: request.targetMACAddress,
            secureOnPassword: request.secureOnPassword
        )
    }
}
