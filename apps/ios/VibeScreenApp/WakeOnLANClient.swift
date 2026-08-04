import Foundation
import Network
import VibeScreenCore

enum WakeOnLANClient {
    static func send(
        macAddress: String,
        isPaired: Bool,
        policy: ManagedPolicy,
        broadcastAddress: String = "255.255.255.255",
        port: UInt16 = 9
    ) async throws {
        let packet = try WakeOnLAN.magicPacket(
            macAddress: macAddress,
            isPaired: isPaired,
            policy: policy
        )
        guard let networkPort = NWEndpoint.Port(rawValue: port) else {
            throw WakeOnLANClientError.invalidPort
        }
        let connection = NWConnection(
            host: NWEndpoint.Host(broadcastAddress),
            port: networkPort,
            using: .udp
        )
        connection.start(queue: .global(qos: .userInitiated))
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connection.send(content: packet, completion: .contentProcessed { error in
                connection.cancel()
                if let error { continuation.resume(throwing: error) }
                else { continuation.resume() }
            })
        }
    }
}

enum WakeOnLANClientError: Error {
    case invalidPort
}
