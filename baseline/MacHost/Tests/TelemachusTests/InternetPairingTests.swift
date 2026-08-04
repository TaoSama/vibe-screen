import CryptoKit
import Foundation
import XCTest
@testable import Telemachus

final class InternetPairingTests: XCTestCase {
    func testHappyPathPersistsDerivedSecretsAndReturnsSignedPublicMetadata() throws {
        let fixture = Fixture()
        let created = try fixture.coordinator.createOffer()
        let parsed = try InternetPairingURL.parse(created.url)
        XCTAssertEqual(parsed, created.offer)
        XCTAssertTrue(created.url.absoluteString.hasPrefix("vibescreen://pair?v=1&o="))

        let prepared = try fixture.prepareRequest(for: parsed)
        let accepted = try fixture.coordinator.accept(prepared.request)

        XCTAssertTrue(accepted.accepted)
        XCTAssertEqual(accepted.offerID, created.offer.offerID)
        XCTAssertEqual(accepted.pairingIdentifier, InternetPairingCanonical.hexDigest(created.offer.offerID))
        XCTAssertEqual(accepted.deviceIdentity, fixture.deviceSigner.pairingPublicIdentity)
        XCTAssertEqual(accepted.deviceName, "Xiaomi 12")
        XCTAssertEqual(accepted.sessionContext, prepared.derived.sessionContext)
        XCTAssertEqual(accepted.sessionKeyID, prepared.derived.sessionKeyID)
        XCTAssertEqual(fixture.store.values[accepted.secretNames.sharedSecret], prepared.derived.sharedSecret)
        XCTAssertEqual(fixture.store.values[accepted.secretNames.bootstrapSecret], prepared.derived.bootstrapSecret)
        XCTAssertFalse(accepted.secretNames.sharedSecret.contains(fixture.deviceSigner.pairingPublicIdentity.deviceID))

        let parts = InternetPairingCanonical.transcriptParts(offer: created.offer, request: prepared.request)
        let resultDigest = SecurityTranscript.digest(
            domain: "vibescreen/pairing-result/v1",
            parts: parts + [
                prepared.request.requestSignature,
                prepared.request.bootstrapMAC,
                Data([0x01]),
                Data(accepted.sessionKeyID.utf8)
            ]
        )
        XCTAssertTrue(InternetPairingCanonical.verify(
            signature: accepted.hostSignature,
            digest: resultDigest,
            publicKey: accepted.hostIdentity.signingPublicKey
        ))
    }

    func testOfferIsConsumedExactlyOnce() throws {
        let fixture = Fixture()
        let created = try fixture.coordinator.createOffer()
        let request = try fixture.prepareRequest(for: created.offer).request
        _ = try fixture.coordinator.accept(request)
        XCTAssertThrowsError(try fixture.coordinator.accept(request)) { error in
            XCTAssertEqual(error as? InternetPairingError, .offerAlreadyConsumed)
        }
    }

    func testExpiredOfferFailsClosedAndIsConsumed() throws {
        let fixture = Fixture()
        let created = try fixture.coordinator.createOffer(validFor: 10)
        let request = try fixture.prepareRequest(for: created.offer).request
        fixture.clock.date = fixture.clock.date.addingTimeInterval(11)
        XCTAssertThrowsError(try fixture.coordinator.accept(request)) { error in
            XCTAssertEqual(error as? InternetPairingError, .offerExpired)
        }
        XCTAssertThrowsError(try fixture.coordinator.accept(request)) { error in
            XCTAssertEqual(error as? InternetPairingError, .offerAlreadyConsumed)
        }
        XCTAssertTrue(fixture.store.values.isEmpty)
    }

    func testTranscriptMutationInvalidatesDeviceProof() throws {
        let fixture = Fixture()
        let created = try fixture.coordinator.createOffer()
        let prepared = try fixture.prepareRequest(for: created.offer)
        let mutatedIdentity = InternetPairingPublicIdentity(
            deviceID: "mutated-device",
            keyID: prepared.request.deviceIdentity.keyID,
            keyEpoch: prepared.request.deviceIdentity.keyEpoch,
            signingPublicKey: prepared.request.deviceIdentity.signingPublicKey
        )
        let mutated = InternetPairingDeviceRequest(
            offerID: prepared.request.offerID,
            deviceIdentity: mutatedIdentity,
            deviceName: prepared.request.deviceName,
            ephemeralPublicKey: prepared.request.ephemeralPublicKey,
            requestSignature: prepared.request.requestSignature,
            bootstrapMAC: prepared.request.bootstrapMAC
        )
        XCTAssertThrowsError(try fixture.coordinator.accept(mutated)) { error in
            XCTAssertEqual(error as? InternetPairingError, .invalidDeviceSignature)
        }
        XCTAssertTrue(fixture.store.values.isEmpty)
    }

    func testBootstrapMACMutationIsRejected() throws {
        let fixture = Fixture()
        let created = try fixture.coordinator.createOffer()
        let prepared = try fixture.prepareRequest(for: created.offer)
        var mac = prepared.request.bootstrapMAC
        mac[0] ^= 0x01
        let mutated = InternetPairingDeviceRequest(
            offerID: prepared.request.offerID,
            deviceIdentity: prepared.request.deviceIdentity,
            deviceName: prepared.request.deviceName,
            ephemeralPublicKey: prepared.request.ephemeralPublicKey,
            requestSignature: prepared.request.requestSignature,
            bootstrapMAC: mac
        )
        XCTAssertThrowsError(try fixture.coordinator.accept(mutated)) { error in
            XCTAssertEqual(error as? InternetPairingError, .invalidBootstrapMAC)
        }
        XCTAssertTrue(fixture.store.values.isEmpty)
    }

    func testDowngradeAndIdentityKeyIDMutationAreRejected() throws {
        let fixture = Fixture()
        let offer = try fixture.coordinator.createOffer().offer
        let downgraded = Fixture.copyOffer(offer, requiredCapabilities: ["peer_identity"])
        XCTAssertThrowsError(try InternetPairingCanonical.validateNegotiation(downgraded)) { error in
            XCTAssertEqual(error as? InternetPairingError, .downgradeDetected)
        }

        let badIdentity = InternetPairingPublicIdentity(
            deviceID: offer.hostIdentity.deviceID,
            keyID: String(repeating: "0", count: 64),
            keyEpoch: offer.hostIdentity.keyEpoch,
            signingPublicKey: offer.hostIdentity.signingPublicKey
        )
        XCTAssertThrowsError(try InternetPairingCanonical.validateIdentity(badIdentity))
    }

    func testURLRejectsWrongVersionDuplicateAndUnknownParameters() throws {
        let fixture = Fixture()
        let valid = try fixture.coordinator.createOffer().url.absoluteString
        let wrongVersion = valid.replacingOccurrences(of: "?v=1&", with: "?v=2&")
        XCTAssertThrowsError(try InternetPairingURL.parse(try XCTUnwrap(URL(string: wrongVersion))))
        XCTAssertThrowsError(try InternetPairingURL.parse(try XCTUnwrap(URL(string: valid + "&v=1"))))
        XCTAssertThrowsError(try InternetPairingURL.parse(try XCTUnwrap(URL(string: valid + "&extra=1"))))
    }

    func testRequestAndAcceptanceWireRoundTripAndRejectUnknownFields() throws {
        let fixture = Fixture()
        let created = try fixture.coordinator.createOffer()
        let prepared = try fixture.prepareRequest(for: created.offer)
        let requestData = try InternetPairingDeviceRequestWire.encode(prepared.request)
        XCTAssertEqual(try InternetPairingDeviceRequestWire.parse(requestData), prepared.request)
        XCTAssertThrowsError(try InternetPairingDeviceRequestWire.parse(addingUnknownField(to: requestData)))

        let accepted = try fixture.coordinator.accept(prepared.request)
        let acceptanceData = try InternetPairingAcceptanceWire.encode(accepted)
        let publicAcceptance = try InternetPairingAcceptanceWire.parse(acceptanceData)
        XCTAssertTrue(publicAcceptance.accepted)
        XCTAssertEqual(publicAcceptance.offerID, accepted.offerID)
        XCTAssertEqual(publicAcceptance.hostIdentity, accepted.hostIdentity)
        XCTAssertEqual(publicAcceptance.sessionContext, accepted.sessionContext)
        XCTAssertEqual(publicAcceptance.sessionKeyID, accepted.sessionKeyID)
        XCTAssertEqual(publicAcceptance.hostSignature, accepted.hostSignature)
        XCTAssertThrowsError(try InternetPairingAcceptanceWire.parse(addingUnknownField(to: acceptanceData)))
    }

    func testWireRejectsInvalidCryptographicSizesAndEncodings() throws {
        let fixture = Fixture()
        let created = try fixture.coordinator.createOffer()
        let prepared = try fixture.prepareRequest(for: created.offer)
        let invalidRequest = InternetPairingDeviceRequest(
            offerID: Data(repeating: 0, count: 15),
            deviceIdentity: prepared.request.deviceIdentity,
            deviceName: prepared.request.deviceName,
            ephemeralPublicKey: prepared.request.ephemeralPublicKey,
            requestSignature: Data([0x01]),
            bootstrapMAC: prepared.request.bootstrapMAC
        )
        XCTAssertThrowsError(try InternetPairingDeviceRequestWire.encode(invalidRequest))

        let accepted = try fixture.coordinator.accept(prepared.request)
        let invalidAcceptance = InternetPairingAcceptance(
            accepted: true,
            offerID: Data(repeating: 0, count: 15),
            pairingIdentifier: accepted.pairingIdentifier,
            hostIdentity: accepted.hostIdentity,
            deviceIdentity: accepted.deviceIdentity,
            deviceName: accepted.deviceName,
            sessionContext: accepted.sessionContext,
            sessionKeyID: accepted.sessionKeyID,
            hostSignature: accepted.hostSignature,
            secretNames: accepted.secretNames
        )
        XCTAssertThrowsError(try InternetPairingAcceptanceWire.encode(invalidAcceptance))
    }

    func testPartialPairingPersistenceLeavesDurableCleanupAndRetriesAfterRestart() throws {
        let fixture = Fixture()
        let created = try fixture.coordinator.createOffer()
        let prepared = try fixture.prepareRequest(for: created.offer)
        let pairingID = InternetPairingCanonical.hexDigest(created.offer.offerID)
        let sharedName = "pairing.\(pairingID).shared.v1"
        let bootstrapName = "pairing.\(pairingID).bootstrap.v1"
        fixture.store.failingPersists = [bootstrapName]
        fixture.store.failingDeletes = [sharedName]

        XCTAssertThrowsError(try fixture.coordinator.accept(prepared.request))
        XCTAssertNotNil(fixture.store.values[sharedName])
        XCTAssertTrue(
            fixture.store.values.keys.contains { $0.contains("persistence-cleanup") },
            "The deterministic cleanup slot must survive a rollback failure"
        )

        fixture.store.failingPersists = []
        fixture.store.failingDeletes = []
        let restarted = InternetPairingCoordinator(
            signer: fixture.hostSigner,
            secretStore: fixture.store,
            now: { fixture.clock.date }
        )
        _ = try restarted.createOffer()
        XCTAssertNil(fixture.store.values[sharedName])
        XCTAssertNil(fixture.store.values[bootstrapName])
        XCTAssertFalse(fixture.store.values.keys.contains { $0.contains("persistence-cleanup") })
    }

    private func addingUnknownField(to data: Data) throws -> Data {
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        object["unknown_field"] = true
        return try JSONSerialization.data(withJSONObject: object)
    }
}

private final class Fixture {
    final class Clock { var date = Date(timeIntervalSince1970: 2_000_000_000) }

    let hostSigner = MemorySigner(deviceID: "host-device")
    let deviceSigner = MemorySigner(deviceID: "android-device")
    let store = MemorySecretStore()
    let clock = Clock()
    lazy var coordinator = InternetPairingCoordinator(
        signer: hostSigner,
        secretStore: store,
        now: { [clock] in clock.date }
    )

    struct Prepared {
        let request: InternetPairingDeviceRequest
        let derived: InternetPairingDerivedSecrets
    }

    func prepareRequest(for offer: InternetPairingOffer) throws -> Prepared {
        let ephemeral = P256.KeyAgreement.PrivateKey()
        let unsigned = InternetPairingDeviceRequest(
            offerID: offer.offerID,
            deviceIdentity: deviceSigner.pairingPublicIdentity,
            deviceName: "Xiaomi 12",
            ephemeralPublicKey: ephemeral.publicKey.x963Representation,
            requestSignature: Data(),
            bootstrapMAC: Data()
        )
        let parts = InternetPairingCanonical.transcriptParts(offer: offer, request: unsigned)
        let digest = SecurityTranscript.digest(domain: "vibescreen/pairing-request/v1", parts: parts)
        let signature = try deviceSigner.signPairingDigest(digest)
        let bootstrapDigest = SecurityTranscript.digest(
            domain: "vibescreen/pairing-bootstrap/v1",
            parts: parts + [signature]
        )
        let mac = Data(HMAC<SHA256>.authenticationCode(
            for: bootstrapDigest,
            using: SymmetricKey(data: offer.oneTimeCredential)
        ))
        let request = InternetPairingDeviceRequest(
            offerID: offer.offerID,
            deviceIdentity: deviceSigner.pairingPublicIdentity,
            deviceName: "Xiaomi 12",
            ephemeralPublicKey: ephemeral.publicKey.x963Representation,
            requestSignature: signature,
            bootstrapMAC: mac
        )
        let hostKey = try P256.KeyAgreement.PublicKey(x963Representation: offer.ephemeralPublicKey)
        let ecdh = try ephemeral.sharedSecretFromKeyAgreement(with: hostKey)
        return Prepared(
            request: request,
            derived: InternetPairingCanonical.derive(ecdh: ecdh, oneTime: offer.oneTimeCredential, parts: parts)
        )
    }

    static func copyOffer(
        _ offer: InternetPairingOffer,
        requiredCapabilities: [String]
    ) -> InternetPairingOffer {
        InternetPairingOffer(
            protocolMin: offer.protocolMin,
            protocolMax: offer.protocolMax,
            hostRole: offer.hostRole,
            deviceRole: offer.deviceRole,
            signatureAlgorithms: offer.signatureAlgorithms,
            keyAgreementAlgorithms: offer.keyAgreementAlgorithms,
            aeadAlgorithms: offer.aeadAlgorithms,
            requiredCapabilities: requiredCapabilities,
            offerID: offer.offerID,
            oneTimeCredential: offer.oneTimeCredential,
            expiresAtUnixSeconds: offer.expiresAtUnixSeconds,
            hostIdentity: offer.hostIdentity,
            challenge: offer.challenge,
            ephemeralPublicKey: offer.ephemeralPublicKey
        )
    }
}

private final class MemorySigner: InternetPairingSigner {
    private let key = P256.Signing.PrivateKey()
    let deviceID: String

    init(deviceID: String) { self.deviceID = deviceID }

    var pairingPublicIdentity: InternetPairingPublicIdentity {
        let encoded = key.publicKey.x963Representation
        return InternetPairingPublicIdentity(
            deviceID: deviceID,
            keyID: InternetPairingCanonical.hexDigest(encoded),
            keyEpoch: 1,
            signingPublicKey: encoded
        )
    }

    func signPairingDigest(_ digest: Data) throws -> Data {
        try key.signature(for: digest).derRepresentation
    }
}

private final class MemorySecretStore: InternetPairingSecretStore {
    var values: [String: Data] = [:]
    var failingPersists: Set<String> = []
    var failingDeletes: Set<String> = []
    func load(name: String) throws -> Data? { values[name] }
    func persist(name: String, secret: Data) throws {
        if failingPersists.contains(name) { throw PlatformSecurityError.persistenceFailure("injected persist") }
        values[name] = secret
    }
    func delete(name: String) throws {
        if failingDeletes.contains(name) { throw PlatformSecurityError.persistenceFailure("injected delete") }
        values.removeValue(forKey: name)
    }
}
