import Foundation

enum PairingURL {
    static func build(host: String, port: UInt16, token: Data, name: String) -> String {
        let tokenStr = base64URLEncode(token)
        var nameAllowed = CharacterSet.urlQueryAllowed
        nameAllowed.remove(charactersIn: "&=?#")
        let nameEncoded = name.addingPercentEncoding(withAllowedCharacters: nameAllowed) ?? ""
        return "telemachus://\(host):\(port)?t=\(tokenStr)&name=\(nameEncoded)"
    }

    static func base64URLEncode(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

struct WirelessPairingEndpoint: Equatable {
    let isRunning: Bool
    let address: String?
    let port: UInt16

    var isAvailable: Bool {
        isRunning && address != nil
    }

    var statusText: String {
        guard isRunning else { return "Start streaming to enable pairing" }
        return address.map { "LAN address: \($0):\(port)" }
            ?? "No LAN address available"
    }

    func pairingURL(token: Data, name: String) -> String? {
        guard isAvailable, let address else { return nil }
        return PairingURL.build(host: address, port: port, token: token, name: name)
    }
}
