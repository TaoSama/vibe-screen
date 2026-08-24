import CryptoKit
import Foundation
import XCTest
@testable import Telemachus

final class InternetPairingTests: XCTestCase {
    func testConcurrentAcceptsUseIndependentPersistenceMarkers() throws {
        let fixture = Fixture()
        let firstOffer = try fixture.coordinator.createOffer().offer
        let secondOffer = try fixture.coordinator.createOffer().offer
        let first = try fixture.coordinator.accept(
            fixture.prepareRequest(for: firstOffer).request
        )
        let second = try fixture.coordinator.accept(
            fixture.prepareRequest(for: secondOffer).request
        )

        XCTAssertEqual(
            try fixture.store.names(prefix: "pairing.persistence-cleanup.v2.").count,
            2
        )
        try fixture.coordinator.commitPersistence(secretNames: first.secretNames)
        XCTAssertNotNil(fixture.store.values[second.secretNames.sharedSecret])
        XCTAssertEqual(
            try fixture.store.names(prefix: "pairing.persistence-cleanup.v2.").count,
            1
        )
        try fixture.coordinator.commitPersistence(secretNames: second.secretNames)
        XCTAssertTrue(
            try fixture.store.names(prefix: "pairing.persistence-cleanup.v2.").isEmpty
        )
    }

    func testPairingURLRejectsOversizeBeforePayloadDecode() throws {
        let oversized = "vibescreen://pair?v=1&o=" + String(repeating: "A", count: 16_384)
        XCTAssertThrowsError(
            try InternetPairingURL.parse(try XCTUnwrap(URL(string: oversized)))
        )
    }

    func testEncodedPairingURLRoundTripsWithCanonicalQuerySeparator() throws {
        let fixture = Fixture()
        let created = try fixture.coordinator.createOffer()

        XCTAssertEqual(try InternetPairingURL.parse(created.url), created.offer)
        XCTAssertTrue(created.url.absoluteString.hasPrefix("vibescreen://pair?v=1&o="))
    }

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
        let identityBindingName = try XCTUnwrap(accepted.secretNames.identityBinding)
        let identityBinding = try PairedHostIdentityBinding.decode(
            XCTUnwrap(fixture.store.values[identityBindingName])
        )
        XCTAssertEqual(identityBinding.deviceID, accepted.hostIdentity.deviceID)
        XCTAssertEqual(identityBinding.keyID, accepted.hostIdentity.keyID)
        XCTAssertEqual(identityBinding.keyEpoch, accepted.hostIdentity.keyEpoch)
        XCTAssertEqual(identityBinding.signatureAlgorithm, accepted.hostIdentity.signatureAlgorithm)
        XCTAssertEqual(identityBinding.signingPublicKey, accepted.hostIdentity.signingPublicKey)
        let peerIdentityBinding = try PairedPeerIdentityBinding.decode(
            XCTUnwrap(
                fixture.store.values[
                    try XCTUnwrap(accepted.secretNames.peerIdentityBinding)
                ]
            )
        )
        XCTAssertEqual(
            peerIdentityBinding.identity.deviceID,
            accepted.deviceIdentity.deviceID
        )
        XCTAssertEqual(
            peerIdentityBinding.identity.keyID,
            accepted.deviceIdentity.keyID
        )
        XCTAssertFalse(accepted.secretNames.sharedSecret.contains(fixture.deviceSigner.pairingPublicIdentity.deviceID))
        XCTAssertTrue(fixture.store.values.keys.contains { $0.contains("persistence-cleanup") })
        let pendingContext = try XCTUnwrap(
            InternetPairingCoordinator.pendingPersistenceContext(
                secretStore: fixture.store
            )
        )
        XCTAssertEqual(pendingContext.pairingIdentifier, accepted.pairingIdentifier)
        XCTAssertEqual(
            pendingContext.peerSecurityScopeID,
            PairedDeviceSecurityScope.identifier(
                PlatformPublicIdentity(
                    deviceID: accepted.deviceIdentity.deviceID,
                    keyID: accepted.deviceIdentity.keyID,
                    keyEpoch: accepted.deviceIdentity.keyEpoch,
                    signingPublicKey: accepted.deviceIdentity.signingPublicKey
                )
            )
        )

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
        var businessStateCommitted = false
        try fixture.coordinator.completePersistence(
            secretNames: accepted.secretNames,
            commitBusinessState: { businessStateCommitted = true },
            cleanupBusinessState: { businessStateCommitted = false }
        )
        XCTAssertTrue(businessStateCommitted)
        XCTAssertFalse(fixture.store.values.keys.contains { $0.contains("persistence-cleanup") })
        XCTAssertNotNil(fixture.store.values[accepted.secretNames.sharedSecret])
        XCTAssertNotNil(fixture.store.values[accepted.secretNames.bootstrapSecret])
        XCTAssertNotNil(fixture.store.values[identityBindingName])
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
        XCTAssertThrowsError(try fixture.coordinator.accept(prepared.request)) { error in
            XCTAssertEqual(error as? InternetPairingError, .offerAlreadyConsumed)
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

    func testSharedWireFixtureMatchesCanonicalPairingContract() throws {
        let fixture = try SharedPairingWireFixture.load()
        XCTAssertEqual(fixture.schema, "vibescreen.pairing-wire-fixture.v1")
        XCTAssertEqual(
            fixture.fixtureScope,
            "TEST_ONLY_SYNTHETIC_MATERIAL_DO_NOT_USE_IN_PRODUCTION"
        )
        XCTAssertEqual(fixture.protocolVersion, 1)
        XCTAssertEqual(fixture.testMaterial.deviceEphemeralRandomFillByte, 66)

        for wire in [fixture.wire.qrOffer, fixture.wire.pairingRequest, fixture.wire.acceptance] {
            let data = Data(wire.utf8.utf8)
            XCTAssertEqual(data.count, wire.byteLength)
            XCTAssertEqual(InternetPairingCanonical.hexDigest(data), wire.sha256)
        }
        let offerPayload = try XCTUnwrap(fixture.wire.qrOffer.payloadUtf8)
        XCTAssertEqual(
            InternetPairingCanonical.hexDigest(Data(offerPayload.utf8)),
            fixture.wire.qrOffer.payloadSha256
        )

        let offerURL = try XCTUnwrap(URL(string: fixture.wire.qrOffer.utf8))
        let offer = try InternetPairingURL.parse(offerURL)
        let requestData = Data(fixture.wire.pairingRequest.utf8.utf8)
        let request = try InternetPairingDeviceRequestWire.parse(requestData)
        let acceptance = try InternetPairingAcceptanceWire.parse(
            Data(fixture.wire.acceptance.utf8.utf8)
        )

        XCTAssertEqual(
            offer.hostIdentity.signingPublicKey,
            try pairingFixtureBase64URL(fixture.testMaterial.hostSigningPublicKey)
        )
        XCTAssertEqual(
            offer.ephemeralPublicKey,
            try pairingFixtureBase64URL(fixture.testMaterial.hostEphemeralPublicKey)
        )
        XCTAssertEqual(
            request.deviceIdentity.signingPublicKey,
            try pairingFixtureBase64URL(fixture.testMaterial.deviceSigningPublicKey)
        )
        XCTAssertEqual(
            request.ephemeralPublicKey,
            try pairingFixtureBase64URL(fixture.testMaterial.deviceEphemeralPublicKey)
        )

        let deviceSigningKey = try P256.Signing.PrivateKey(
            rawRepresentation: pairingFixtureBase64URL(
                fixture.testMaterial.deviceSigningPrivateScalar
            )
        )
        XCTAssertEqual(
            deviceSigningKey.publicKey.x963Representation,
            request.deviceIdentity.signingPublicKey
        )
        let hostSigningKey = try P256.Signing.PrivateKey(
            rawRepresentation: pairingFixtureBase64URL(
                fixture.testMaterial.hostSigningPrivateScalar
            )
        )
        XCTAssertEqual(hostSigningKey.publicKey.x963Representation, offer.hostIdentity.signingPublicKey)

        let parts = InternetPairingCanonical.transcriptParts(offer: offer, request: request)
        let requestDigest = SecurityTranscript.digest(
            domain: "vibescreen/pairing-request/v1",
            parts: parts
        )
        XCTAssertEqual(
            requestDigest,
            try pairingFixtureBase64URL(fixture.expected.requestDigest)
        )
        XCTAssertTrue(InternetPairingCanonical.verify(
            signature: request.requestSignature,
            digest: requestDigest,
            publicKey: request.deviceIdentity.signingPublicKey
        ))

        let bootstrapDigest = SecurityTranscript.digest(
            domain: "vibescreen/pairing-bootstrap/v1",
            parts: parts + [request.requestSignature]
        )
        XCTAssertEqual(
            bootstrapDigest,
            try pairingFixtureBase64URL(fixture.expected.bootstrapDigest)
        )
        XCTAssertTrue(HMAC<SHA256>.isValidAuthenticationCode(
            request.bootstrapMAC,
            authenticating: bootstrapDigest,
            using: SymmetricKey(data: offer.oneTimeCredential)
        ))

        let deviceEphemeral = try P256.KeyAgreement.PrivateKey(
            rawRepresentation: pairingFixtureBase64URL(
                fixture.testMaterial.deviceEphemeralPrivateScalar
            )
        )
        XCTAssertEqual(deviceEphemeral.publicKey.x963Representation, request.ephemeralPublicKey)
        let hostEphemeral = try P256.KeyAgreement.PublicKey(
            x963Representation: offer.ephemeralPublicKey
        )
        let derived = InternetPairingCanonical.derive(
            ecdh: try deviceEphemeral.sharedSecretFromKeyAgreement(with: hostEphemeral),
            oneTime: offer.oneTimeCredential,
            parts: parts
        )
        XCTAssertEqual(
            derived.sessionContext,
            try pairingFixtureBase64URL(fixture.expected.sessionContext)
        )
        XCTAssertEqual(derived.sessionKeyID, fixture.expected.sessionKeyId)
        XCTAssertEqual(
            InternetPairingCanonical.hexDigest(offer.offerID),
            fixture.expected.pairingIdentifier
        )
        XCTAssertEqual(acceptance.sessionContext, derived.sessionContext)
        XCTAssertEqual(acceptance.sessionKeyID, derived.sessionKeyID)

        let resultDigest = SecurityTranscript.digest(
            domain: "vibescreen/pairing-result/v1",
            parts: parts + [
                request.requestSignature,
                request.bootstrapMAC,
                Data([0x01]),
                Data(derived.sessionKeyID.utf8)
            ]
        )
        XCTAssertEqual(
            resultDigest,
            try pairingFixtureBase64URL(fixture.expected.pairingResultDigest)
        )
        XCTAssertTrue(InternetPairingCanonical.verify(
            signature: acceptance.hostSignature,
            digest: resultDigest,
            publicKey: acceptance.hostIdentity.signingPublicKey
        ))
    }

    func testPairingVerifierUsesRawDigestAndFailsClosed() throws {
        let fixture = try SharedPairingWireFixture.load()
        let request = try InternetPairingDeviceRequestWire.parse(
            Data(fixture.wire.pairingRequest.utf8.utf8)
        )
        let digest = try pairingFixtureBase64URL(fixture.expected.requestDigest)
        let devicePrivateKey = try P256.Signing.PrivateKey(
            rawRepresentation: pairingFixtureBase64URL(
                fixture.testMaterial.deviceSigningPrivateScalar
            )
        )
        XCTAssertTrue(InternetPairingCanonical.verify(
            signature: request.requestSignature,
            digest: digest,
            publicKey: request.deviceIdentity.signingPublicKey
        ))
        XCTAssertTrue(InternetPairingCanonical.verify(
            signature: try pairingRawDigestSignature(privateKey: devicePrivateKey, digest: digest),
            digest: digest,
            publicKey: request.deviceIdentity.signingPublicKey
        ))

        let doubleHashedSignature = try devicePrivateKey.signature(for: digest).derRepresentation
        XCTAssertFalse(InternetPairingCanonical.verify(
            signature: doubleHashedSignature,
            digest: digest,
            publicKey: request.deviceIdentity.signingPublicKey
        ))

        var wrongDigest = digest
        wrongDigest[0] ^= 0x01
        var wrongSignature = request.requestSignature
        wrongSignature[wrongSignature.count - 1] ^= 0x01
        XCTAssertFalse(InternetPairingCanonical.verify(
            signature: request.requestSignature,
            digest: wrongDigest,
            publicKey: request.deviceIdentity.signingPublicKey
        ))
        XCTAssertFalse(InternetPairingCanonical.verify(
            signature: wrongSignature,
            digest: digest,
            publicKey: request.deviceIdentity.signingPublicKey
        ))
        XCTAssertFalse(InternetPairingCanonical.verify(
            signature: request.requestSignature,
            digest: digest,
            publicKey: try pairingFixtureBase64URL(fixture.testMaterial.hostSigningPublicKey)
        ))
        XCTAssertFalse(InternetPairingCanonical.verify(
            signature: Data([0x30, 0x00]),
            digest: digest,
            publicKey: request.deviceIdentity.signingPublicKey
        ))
        XCTAssertFalse(InternetPairingCanonical.verify(
            signature: request.requestSignature,
            digest: Data(digest.dropLast()),
            publicKey: request.deviceIdentity.signingPublicKey
        ))
        XCTAssertFalse(InternetPairingCanonical.verify(
            signature: request.requestSignature,
            digest: digest,
            publicKey: Data(repeating: 0, count: 65)
        ))
    }

    func testSharedWireFixtureNegativeCasesFailClosed() throws {
        let fixture = try SharedPairingWireFixture.load()
        XCTAssertEqual(
            Set(fixture.negativeCases.map(\.category)),
            Set(["field_tamper", "signature", "size", "order"])
        )
        for negative in fixture.negativeCases {
            XCTAssertEqual(
                InternetPairingCanonical.hexDigest(Data(negative.wireUtf8.utf8)),
                negative.sha256,
                negative.name
            )
        }

        let reordered = try fixture.negative("reordered_required_capabilities")
        XCTAssertThrowsError(
            try InternetPairingURL.parse(try XCTUnwrap(URL(string: reordered.wireUtf8)))
        ) { error in
            XCTAssertEqual(error as? InternetPairingError, .downgradeDetected)
        }

        let offer = try InternetPairingURL.parse(
            try XCTUnwrap(URL(string: fixture.wire.qrOffer.utf8))
        )
        let changedField = try InternetPairingDeviceRequestWire.parse(
            Data(try fixture.negative("tampered_request_field").wireUtf8.utf8)
        )
        let changedDigest = SecurityTranscript.digest(
            domain: "vibescreen/pairing-request/v1",
            parts: InternetPairingCanonical.transcriptParts(offer: offer, request: changedField)
        )
        XCTAssertFalse(InternetPairingCanonical.verify(
            signature: changedField.requestSignature,
            digest: changedDigest,
            publicKey: changedField.deviceIdentity.signingPublicKey
        ))

        let changedSignature = try InternetPairingDeviceRequestWire.parse(
            Data(try fixture.negative("tampered_request_signature").wireUtf8.utf8)
        )
        XCTAssertFalse(InternetPairingCanonical.verify(
            signature: changedSignature.requestSignature,
            digest: try pairingFixtureBase64URL(fixture.expected.requestDigest),
            publicKey: changedSignature.deviceIdentity.signingPublicKey
        ))
        XCTAssertThrowsError(
            try InternetPairingDeviceRequestWire.parse(
                Data(try fixture.negative("oversized_device_name").wireUtf8.utf8)
            )
        )

        let changedAcceptanceSignature = try InternetPairingAcceptanceWire.parse(
            Data(try fixture.negative("tampered_acceptance_signature").wireUtf8.utf8)
        )
        XCTAssertFalse(InternetPairingCanonical.verify(
            signature: changedAcceptanceSignature.hostSignature,
            digest: try pairingFixtureBase64URL(fixture.expected.pairingResultDigest),
            publicKey: changedAcceptanceSignature.hostIdentity.signingPublicKey
        ))
        let changedContext = try InternetPairingAcceptanceWire.parse(
            Data(try fixture.negative("tampered_session_context").wireUtf8.utf8)
        )
        XCTAssertNotEqual(
            changedContext.sessionContext,
            try pairingFixtureBase64URL(fixture.expected.sessionContext)
        )
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

    func testPostPersistBusinessFailureAndDeleteFailureResumeAfterRestart() throws {
        let fixture = Fixture()
        let created = try fixture.coordinator.createOffer()
        let prepared = try fixture.prepareRequest(for: created.offer)
        let accepted = try fixture.coordinator.accept(prepared.request)
        var metadataCommitted = false
        fixture.store.failingDeletes = [accepted.secretNames.sharedSecret]

        XCTAssertThrowsError(
            try fixture.coordinator.completePersistence(
                secretNames: accepted.secretNames,
                commitBusinessState: {
                    metadataCommitted = true
                    throw InternetPairingError.persistenceFailure("metadata commit failed")
                },
                cleanupBusinessState: {
                    metadataCommitted = false
                }
            )
        )
        XCTAssertTrue(metadataCommitted)
        XCTAssertNotNil(fixture.store.values[accepted.secretNames.sharedSecret])
        XCTAssertTrue(fixture.store.values.keys.contains { $0.contains("persistence-cleanup") })

        fixture.store.failingDeletes = []
        let restarted = InternetPairingCoordinator(
            signer: fixture.hostSigner,
            secretStore: fixture.store,
            now: { fixture.clock.date }
        )
        XCTAssertTrue(
            try restarted.retryPendingPersistenceCleanup {
                metadataCommitted = false
            }
        )
        XCTAssertFalse(metadataCommitted)
        XCTAssertNil(fixture.store.values[accepted.secretNames.sharedSecret])
        XCTAssertNil(fixture.store.values[accepted.secretNames.bootstrapSecret])
        XCTAssertNil(fixture.store.values[try XCTUnwrap(accepted.secretNames.identityBinding)])
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
        try pairingRawDigestSignature(privateKey: key, digest: digest)
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
    func names(prefix: String) throws -> [String] {
        values.keys.filter { $0.hasPrefix(prefix) }
    }
}
