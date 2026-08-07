import CryptoKit
import Foundation
import Security
@testable import Telemachus

struct SharedPairingWireFixture: Decodable {
    struct Material: Decodable {
        let hostSigningPrivateScalar: String
        let deviceSigningPrivateScalar: String
        let hostEphemeralPrivateScalar: String
        let deviceEphemeralPrivateScalar: String
        let deviceEphemeralRandomFillByte: Int
        let hostSigningPublicKey: String
        let deviceSigningPublicKey: String
        let hostEphemeralPublicKey: String
        let deviceEphemeralPublicKey: String
    }

    struct WireValue: Decodable {
        let utf8: String
        let byteLength: Int
        let sha256: String
        let payloadUtf8: String?
        let payloadSha256: String?
    }

    struct Wires: Decodable {
        let qrOffer: WireValue
        let pairingRequest: WireValue
        let acceptance: WireValue
    }

    struct Expected: Decodable {
        let requestDigest: String
        let bootstrapDigest: String
        let pairingResultDigest: String
        let sessionContext: String
        let pairingIdentifier: String
        let sessionKeyId: String
    }

    struct NegativeCase: Decodable {
        let name: String
        let category: String
        let target: String
        let wireUtf8: String
        let sha256: String
    }

    let schema: String
    let fixtureScope: String
    let protocolVersion: Int
    let testMaterial: Material
    let wire: Wires
    let expected: Expected
    let negativeCases: [NegativeCase]

    static func load(filePath: String = #filePath) throws -> Self {
        var repositoryRoot = URL(fileURLWithPath: filePath)
        for _ in 0..<5 { repositoryRoot.deleteLastPathComponent() }
        let fixtureURL = repositoryRoot
            .appendingPathComponent("contracts/fixtures/pairing/v1/wire.json")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Self.self, from: Data(contentsOf: fixtureURL))
    }

    func negative(_ name: String) throws -> NegativeCase {
        guard let value = negativeCases.first(where: { $0.name == name }) else {
            throw NSError(domain: "PairingWireFixture", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "Missing negative pairing fixture: \(name)"
            ])
        }
        return value
    }
}

func pairingFixtureBase64URL(_ value: String) throws -> Data {
    guard !value.isEmpty, !value.contains("="), value.unicodeScalars.allSatisfy({
        CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
            .contains($0)
    }) else {
        throw NSError(domain: "PairingWireFixture", code: 2)
    }
    var base64 = value.replacingOccurrences(of: "-", with: "+")
        .replacingOccurrences(of: "_", with: "/")
    base64.append(String(repeating: "=", count: (4 - base64.count % 4) % 4))
    guard let decoded = Data(base64Encoded: base64) else {
        throw NSError(domain: "PairingWireFixture", code: 3)
    }
    return decoded
}

func pairingRawDigestSignature(
    privateKey: P256.Signing.PrivateKey,
    digest: Data
) throws -> Data {
    guard digest.count == SHA256.byteCount else {
        throw PlatformSecurityError.invalidInput("Test signing requires a SHA-256 digest.")
    }
    let attributes: [String: Any] = [
        kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
        kSecAttrKeyClass as String: kSecAttrKeyClassPrivate,
        kSecAttrKeySizeInBits as String: 256
    ]
    guard let key = SecKeyCreateWithData(
        privateKey.x963Representation as CFData,
        attributes as CFDictionary,
        nil
    ) else {
        throw PlatformSecurityError.invalidInput("Unable to load the test P-256 private key.")
    }
    var error: Unmanaged<CFError>?
    guard let signature = SecKeyCreateSignature(
        key,
        .ecdsaSignatureDigestX962SHA256,
        digest as CFData,
        &error
    ) as Data? else {
        if let error { throw error.takeRetainedValue() }
        throw PlatformSecurityError.invalidInput("Unable to sign the test transcript digest.")
    }
    if let error { throw error.takeRetainedValue() }
    return signature
}
