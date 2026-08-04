import Foundation

public enum WakeOnLANError: Error, Equatable {
    case policyDenied
    case deviceNotPaired
    case invalidMACAddress
}

public enum WakeOnLAN {
    public static func magicPacket(
        macAddress: String,
        isPaired: Bool,
        policy: ManagedPolicy
    ) throws -> Data {
        guard policy.wakeAllowed else { throw WakeOnLANError.policyDenied }
        guard isPaired else { throw WakeOnLANError.deviceNotPaired }
        let compact = macAddress.filter { $0 != ":" && $0 != "-" }
        guard compact.count == 12 else { throw WakeOnLANError.invalidMACAddress }
        var bytes: [UInt8] = []
        bytes.reserveCapacity(6)
        var index = compact.startIndex
        for _ in 0..<6 {
            let next = compact.index(index, offsetBy: 2)
            guard let byte = UInt8(compact[index..<next], radix: 16) else {
                throw WakeOnLANError.invalidMACAddress
            }
            bytes.append(byte)
            index = next
        }
        guard bytes.contains(where: { $0 != 0 }), bytes.contains(where: { $0 != 0xff }) else {
            throw WakeOnLANError.invalidMACAddress
        }
        return Data(repeating: 0xff, count: 6) + Data(Array(repeating: bytes, count: 16).flatMap { $0 })
    }
}
