import CryptoKit
import Foundation

struct InternetPairingDerivedSecrets: Equatable {
    let sharedSecret: Data
    let bootstrapSecret: Data
    let sessionContext: Data
    let sessionKeyID: String
}

enum InternetPairingCanonical {
    static func validateNegotiation(_ offer: InternetPairingOffer) throws {
        guard offer.protocolMin == InternetPairingCoordinator.protocolVersion,
              offer.protocolMax == InternetPairingCoordinator.protocolVersion,
              offer.hostRole == "host", offer.deviceRole == "device",
              offer.signatureAlgorithms == InternetPairingCoordinator.signatureAlgorithms,
              offer.keyAgreementAlgorithms == InternetPairingCoordinator.keyAgreementAlgorithms,
              offer.aeadAlgorithms == InternetPairingCoordinator.aeadAlgorithms,
              offer.requiredCapabilities == InternetPairingCoordinator.requiredCapabilities else {
            throw InternetPairingError.downgradeDetected
        }
    }

    static func validateOffer(_ offer: InternetPairingOffer) throws {
        try validateNegotiation(offer)
        try validateIdentity(offer.hostIdentity)
        guard offer.offerID.count == 16, offer.oneTimeCredential.count == 32,
              offer.challenge.count == 32, offer.ephemeralPublicKey.count == 65,
              offer.expiresAtUnixSeconds > 0 else {
            throw InternetPairingError.invalidOffer("Offer field sizes are invalid.")
        }
        do { _ = try P256.KeyAgreement.PublicKey(x963Representation: offer.ephemeralPublicKey) }
        catch { throw InternetPairingError.invalidOffer("Host ECDH public key is invalid.") }
    }

    static func validateIdentity(_ identity: InternetPairingPublicIdentity) throws {
        guard !identity.deviceID.isEmpty, identity.deviceID.utf8.count <= 256,
              !identity.keyID.isEmpty, identity.keyID.utf8.count <= 256,
              identity.keyEpoch > 0,
              identity.signatureAlgorithm == "ECDSA_P256_SHA256",
              identity.signingPublicKey.count == 65,
              identity.keyID == hexDigest(identity.signingPublicKey) else {
            throw InternetPairingError.invalidOffer("Identity fields are invalid.")
        }
        do { _ = try P256.Signing.PublicKey(x963Representation: identity.signingPublicKey) }
        catch { throw InternetPairingError.invalidOffer("Identity signing key is invalid.") }
    }

    static func transcriptParts(offer: InternetPairingOffer, request: InternetPairingDeviceRequest) -> [Data] {
        [
            SecurityTranscript.uint64(offer.protocolMin),
            SecurityTranscript.uint64(offer.protocolMax),
            Data(offer.hostRole.utf8),
            Data(offer.deviceRole.utf8),
            canonicalList(offer.signatureAlgorithms),
            canonicalList(offer.keyAgreementAlgorithms),
            canonicalList(offer.aeadAlgorithms),
            canonicalList(offer.requiredCapabilities),
            offer.offerID,
            offer.challenge,
            SecurityTranscript.uint64(offer.expiresAtUnixSeconds),
            Data(offer.hostIdentity.deviceID.utf8),
            Data(offer.hostIdentity.keyID.utf8),
            SecurityTranscript.uint64(offer.hostIdentity.keyEpoch),
            Data(offer.hostIdentity.signatureAlgorithm.utf8),
            offer.hostIdentity.signingPublicKey,
            offer.ephemeralPublicKey,
            Data(request.deviceIdentity.deviceID.utf8),
            Data(request.deviceIdentity.keyID.utf8),
            SecurityTranscript.uint64(request.deviceIdentity.keyEpoch),
            Data(request.deviceIdentity.signatureAlgorithm.utf8),
            request.deviceIdentity.signingPublicKey,
            Data(request.deviceName.utf8),
            request.ephemeralPublicKey
        ]
    }

    static func canonicalList(_ values: [String]) -> Data {
        var data = SecurityTranscript.uint64(UInt64(values.count))
        for value in values {
            let bytes = Data(value.utf8)
            data.append(SecurityTranscript.uint64(UInt64(bytes.count)))
            data.append(bytes)
        }
        return data
    }

    static func verify(signature: Data, digest: Data, publicKey: Data) -> Bool {
        do {
            let key = try P256.Signing.PublicKey(x963Representation: publicKey)
            let parsed = try P256.Signing.ECDSASignature(derRepresentation: signature)
            return key.isValidSignature(parsed, for: digest)
        } catch { return false }
    }

    static func hexDigest(_ data: Data) -> String {
        Data(SHA256.hash(data: data)).map { String(format: "%02x", $0) }.joined()
    }

    static func derive(ecdh: SharedSecret, oneTime: Data, parts: [Data]) -> InternetPairingDerivedSecrets {
        let sharedInfo = SecurityTranscript.digest(domain: "vibescreen/pairing-shared/v1", parts: parts)
        let bootstrapInfo = SecurityTranscript.digest(
            domain: "vibescreen/pairing-bootstrap-credential/v1",
            parts: parts
        )
        let inputKey = SymmetricKey(data: ecdh.withUnsafeBytes { Data($0) })
        let shared: Data = HKDF<SHA256>.deriveKey(
            inputKeyMaterial: inputKey,
            salt: oneTime,
            info: sharedInfo,
            outputByteCount: 32
        ).withUnsafeBytes { Data($0) }
        let bootstrap: Data = HKDF<SHA256>.deriveKey(
            inputKeyMaterial: inputKey,
            salt: oneTime,
            info: bootstrapInfo,
            outputByteCount: 32
        ).withUnsafeBytes { Data($0) }
        let context = SecurityTranscript.digest(domain: "vibescreen/pairing-session-context/v1", parts: parts)
        let keyID = Data(SHA256.hash(data: shared + bootstrap)).map { String(format: "%02x", $0) }.joined()
        return InternetPairingDerivedSecrets(
            sharedSecret: shared,
            bootstrapSecret: bootstrap,
            sessionContext: context,
            sessionKeyID: keyID
        )
    }
}
