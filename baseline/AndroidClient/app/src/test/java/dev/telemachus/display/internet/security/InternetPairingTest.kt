package dev.telemachus.display.internet.security

import com.google.gson.JsonParser
import java.math.BigInteger
import java.nio.ByteBuffer
import java.security.AlgorithmParameters
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.ECPoint
import java.security.spec.ECPrivateKeySpec
import java.security.spec.ECPublicKeySpec
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import java.util.Base64
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class InternetPairingTest {
    @Test
    fun happyPathAuthenticatesBothPeersAndPersistsDerivedSecrets() {
        val fixture = Fixture()
        val pending = fixture.coordinator.begin(fixture.url.encode(), DEVICE_NAME)

        assertTrue(fixture.verifyRequest(pending.request))
        val hostResult = fixture.accept(pending.request)
        val result = pending.complete(hostResult.acceptance)

        assertEquals(sha256(fixture.offerId).toHex(), result.metadata.pairingIdentifier)
        assertEquals(DEVICE_NAME, result.metadata.deviceName)
        assertEquals(hostResult.sessionKeyId, result.metadata.sessionKeyId)
        assertArrayEquals(hostResult.sessionContext, result.metadata.sessionContext)
        assertArrayEquals(hostResult.sharedSecret, fixture.sink.sharedSecret)
        assertArrayEquals(hostResult.bootstrapSecret, fixture.sink.bootstrapSecret)
        assertFalse(result.metadata.toString().contains(fixture.oneTime.base64Url()))
        assertThrows(IllegalStateException::class.java) { pending.complete(hostResult.acceptance) }
    }

    @Test
    fun rejectsExpiredOfferAtScanAndAtAcceptance() {
        val expired = Fixture(expiresAt = NOW - 1)
        assertThrows(IllegalArgumentException::class.java) { expired.coordinator.begin(expired.url.encode(), DEVICE_NAME) }

        val clock = MutableClock(NOW)
        val fixture = Fixture(expiresAt = NOW + 1, clock = clock)
        val pending = fixture.coordinator.begin(fixture.url.encode(), DEVICE_NAME)
        val acceptance = fixture.accept(pending.request).acceptance
        clock.epochSeconds = NOW + 2
        assertThrows(IllegalArgumentException::class.java) { pending.complete(acceptance) }
        assertEquals(null, fixture.sink.sharedSecret)
    }

    @Test
    fun scannedOfferObjectIsConsumedExactlyOnce() {
        val fixture = Fixture()
        val parsed = InternetPairingURL.parse(fixture.url.encode())

        fixture.coordinator.begin(parsed, DEVICE_NAME).close()

        assertThrows(IllegalStateException::class.java) { fixture.coordinator.begin(parsed, DEVICE_NAME) }
        assertEquals(null, fixture.sink.sharedSecret)
    }

    @Test
    fun expirationBoundaryIsExclusiveAtScanAndAcceptance() {
        val scanBoundary = Fixture(expiresAt = NOW)
        assertThrows(IllegalArgumentException::class.java) {
            scanBoundary.coordinator.begin(scanBoundary.url.encode(), DEVICE_NAME)
        }

        val clock = MutableClock(NOW)
        val acceptanceBoundary = Fixture(expiresAt = NOW + 1, clock = clock)
        val pending = acceptanceBoundary.coordinator.begin(acceptanceBoundary.url.encode(), DEVICE_NAME)
        val acceptance = acceptanceBoundary.accept(pending.request).acceptance
        clock.epochSeconds = NOW + 1

        assertThrows(IllegalArgumentException::class.java) { pending.complete(acceptance) }
        assertEquals(null, acceptanceBoundary.sink.sharedSecret)
    }

    @Test
    fun temporarySecretSinkCopiesAreZeroizedAfterSuccessAndFailure() {
        val successSink = ReferencingSink()
        val successFixture = Fixture(sinkOverride = successSink)
        val successPending = successFixture.coordinator.begin(successFixture.url.encode(), DEVICE_NAME)
        successPending.complete(successFixture.accept(successPending.request).acceptance)

        assertEquals(setOf(0.toByte()), successSink.sharedReference?.toSet())
        assertEquals(setOf(0.toByte()), successSink.bootstrapReference?.toSet())

        val failureSink = ReferencingSink(throwOnPersist = true)
        val failureFixture = Fixture(sinkOverride = failureSink)
        val failurePending = failureFixture.coordinator.begin(failureFixture.url.encode(), DEVICE_NAME)

        assertThrows(IllegalStateException::class.java) {
            failurePending.complete(failureFixture.accept(failurePending.request).acceptance)
        }
        assertEquals(setOf(0.toByte()), failureSink.sharedReference?.toSet())
        assertEquals(setOf(0.toByte()), failureSink.bootstrapReference?.toSet())
    }

    @Test
    fun rejectsMutatedRequestAndAcceptance() {
        val fixture = Fixture()
        val pending = fixture.coordinator.begin(fixture.url.encode(), DEVICE_NAME)
        val mutatedRequest =
            pending.request.copy(
                requestSignature = pending.request.requestSignature.copyOf().apply {
                    this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte()
                },
            )
        assertFalse(fixture.verifyRequest(mutatedRequest))

        val valid = fixture.accept(pending.request).acceptance
        val mutatedAcceptance =
            valid.copy(hostSignature = valid.hostSignature.copyOf().apply { this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte() })
        assertThrows(IllegalArgumentException::class.java) { pending.complete(mutatedAcceptance) }
        assertEquals(null, fixture.sink.sharedSecret)
    }

    @Test
    fun rejectsProtocolDowngradeAndNonCanonicalCapabilities() {
        val fixture = Fixture()
        val downgraded = mutatePayload(fixture.url.encode()) { addProperty("protocol_min", 0) }
        assertThrows(IllegalArgumentException::class.java) { fixture.coordinator.begin(downgraded, DEVICE_NAME) }

        val fixture2 = Fixture()
        val reordered =
            mutatePayload(fixture2.url.encode()) {
                add(
                    "required_capabilities",
                    com.google.gson.JsonArray().apply {
                        add("peer_identity")
                        add("application_e2ee")
                        add("audio_data_channel")
                        add("bulk_data_channel")
                        add("control_data_channel")
                        add("media_data_channel")
                    },
                )
            }
        assertThrows(IllegalArgumentException::class.java) { fixture2.coordinator.begin(reordered, DEVICE_NAME) }
    }

    @Test
    fun urlParserRejectsWrongEnvelopeAndDuplicateParameters() {
        val encoded = Fixture().url.encode()
        assertThrows(IllegalArgumentException::class.java) { InternetPairingURL.parse(encoded.replace("vibescreen://pair", "https://pair")) }
        assertThrows(IllegalArgumentException::class.java) { InternetPairingURL.parse("$encoded&v=1") }
    }

    @Test
    fun urlParserRejectsNonCanonicalQrPayloadsBeforeCredentialUse() {
        val encoded = Fixture().url.encode()
        val payload = encoded.substringAfter("&o=")

        assertThrows(IllegalArgumentException::class.java) { InternetPairingURL.parse("vibescreen://pair?o=$payload&v=1") }
        assertThrows(IllegalArgumentException::class.java) { InternetPairingURL.parse("$encoded&") }
        assertThrows(IllegalArgumentException::class.java) { InternetPairingURL.parse(encoded.replace("&o=", "&&o=")) }
        assertThrows(IllegalArgumentException::class.java) { InternetPairingURL.parse(encoded.replace("&o=", "&o=%")) }
        assertThrows(IllegalArgumentException::class.java) { InternetPairingURL.parse(encoded.replace("&o=", "&o=+")) }
        assertThrows(IllegalArgumentException::class.java) { InternetPairingURL.parse("$encoded#fragment") }
        assertThrows(IllegalArgumentException::class.java) {
            InternetPairingURL.parse("vibescreen://pair?v=1&o=" + "A".repeat(16_384))
        }
    }

    @Test
    fun cancelledPendingPairingCannotBeCompleted() {
        val fixture = Fixture()
        val pending = fixture.coordinator.begin(fixture.url.encode(), DEVICE_NAME)
        val acceptance = fixture.accept(pending.request).acceptance
        pending.close()
        pending.close()
        assertThrows(IllegalStateException::class.java) { pending.complete(acceptance) }
        assertEquals(null, fixture.sink.sharedSecret)
    }

    @Test
    fun requestAndAcceptanceJsonRoundTripWithExactFields() {
        val fixture = Fixture()
        val pending = fixture.coordinator.begin(fixture.url.encode(), DEVICE_NAME)
        val request = InternetPairingRequest.parse(pending.request.encode())
        assertEquals(pending.request, request)

        val acceptance = fixture.accept(request).acceptance
        val decoded = InternetPairingAcceptance.parse(acceptance.encode())
        assertEquals(acceptance.accepted, decoded.accepted)
        assertArrayEquals(acceptance.offerId, decoded.offerId)
        assertEquals(acceptance.hostIdentity, decoded.hostIdentity)
        assertArrayEquals(acceptance.sessionContext, decoded.sessionContext)
        assertEquals(acceptance.sessionKeyId, decoded.sessionKeyId)
        assertArrayEquals(acceptance.hostSignature, decoded.hostSignature)
    }

    @Test
    fun wireJsonRejectsUnknownFieldsWrongTypesAndNonCanonicalBytes() {
        val fixture = Fixture()
        val request = fixture.coordinator.begin(fixture.url.encode(), DEVICE_NAME).request
        val unknown = JsonParser.parseString(request.encode()).asJsonObject.apply { addProperty("secret", "leak") }.toString()
        assertThrows(IllegalArgumentException::class.java) { InternetPairingRequest.parse(unknown) }

        val wrongType = JsonParser.parseString(request.encode()).asJsonObject.apply { addProperty("device_name", 7) }.toString()
        assertThrows(IllegalArgumentException::class.java) { InternetPairingRequest.parse(wrongType) }

        val padded = JsonParser.parseString(request.encode()).asJsonObject.apply {
            addProperty("offer_id", get("offer_id").asString + "=")
        }.toString()
        assertThrows(IllegalArgumentException::class.java) { InternetPairingRequest.parse(padded) }
    }

    @Test
    fun sharedWireFixtureRunsThroughProductionCanonicalSignAndVerify() {
        val fixture = SharedPairingWireFixture.load()
        assertEquals("vibescreen.pairing-wire-fixture.v1", fixture.schema)
        assertEquals("TEST_ONLY_SYNTHETIC_MATERIAL_DO_NOT_USE_IN_PRODUCTION", fixture.fixtureScope)
        assertEquals(1, fixture.protocolVersion)
        assertEquals(66, fixture.materialInt("device_ephemeral_random_fill_byte"))

        val qrWire = fixture.wire("qr_offer")
        val requestWire = fixture.wire("pairing_request")
        val acceptanceWire = fixture.wire("acceptance")
        listOf(qrWire, requestWire, acceptanceWire).forEach { wire ->
            assertEquals(wire.byteLength, wire.utf8.toByteArray().size)
            assertEquals(wire.sha256, pairingFixtureSha256Hex(wire.utf8))
        }
        assertEquals(qrWire.utf8, InternetPairingURL.parse(qrWire.utf8).encode())

        val expectedRequest = InternetPairingRequest.parse(requestWire.utf8)
        assertEquals(requestWire.utf8, expectedRequest.encode())
        val acceptance = InternetPairingAcceptance.parse(acceptanceWire.utf8)
        assertEquals(acceptanceWire.utf8, acceptance.encode())
        assertArrayEquals(
            decodePairingFixtureBase64URL(fixture.material("device_signing_public_key")),
            expectedRequest.deviceIdentity.signingPublicKey,
        )
        assertArrayEquals(
            decodePairingFixtureBase64URL(fixture.material("device_ephemeral_public_key")),
            expectedRequest.deviceEphemeralPublicKey,
        )
        assertArrayEquals(
            decodePairingFixtureBase64URL(fixture.material("host_signing_public_key")),
            acceptance.hostIdentity.signingPublicKey,
        )

        val execution = beginSharedFixture(fixture)
        assertEquals(1, execution.signer.calls)
        assertArrayEquals(
            decodePairingFixtureBase64URL(fixture.expected("request_digest")),
            execution.signer.lastDigest,
        )
        assertEquals(expectedRequest, execution.pending.request)
        assertEquals(requestWire.utf8, execution.pending.request.encode())

        val result = execution.pending.complete(acceptance)
        assertEquals(fixture.expected("pairing_identifier"), result.metadata.pairingIdentifier)
        assertEquals(fixture.expected("session_key_id"), result.metadata.sessionKeyId)
        assertArrayEquals(
            decodePairingFixtureBase64URL(fixture.expected("session_context")),
            result.metadata.sessionContext,
        )
        assertEquals(fixture.expected("pairing_identifier"), execution.sink.pairingIdentifier)
        assertTrue(execution.sink.sharedSecret?.size == 32)
        assertTrue(execution.sink.bootstrapSecret?.size == 32)
    }

    @Test
    fun sharedFixtureRawDigestSignaturesRejectDoubleHashAndBadInputs() {
        val fixture = SharedPairingWireFixture.load()
        val request = InternetPairingRequest.parse(fixture.wire("pairing_request").utf8)
        val digest = decodePairingFixtureBase64URL(fixture.expected("request_digest"))
        assertTrue(verify(request.deviceIdentity.signingPublicKey, digest, request.requestSignature))
        assertFalse(verify(request.deviceIdentity.signingPublicKey, sha256(digest), request.requestSignature))

        val privateKey = decodeFixturePrivateKey(fixture.material("device_signing_private_scalar"))
        val rawDigestSignature =
            Signature.getInstance("NONEwithECDSA").run {
                initSign(privateKey, FixedFillSecureRandom(0x24.toByte()))
                update(digest)
                sign()
            }
        assertTrue(verify(request.deviceIdentity.signingPublicKey, digest, rawDigestSignature))
        val doubleHashedSignature =
            Signature.getInstance("SHA256withECDSA").run {
                initSign(privateKey, FixedFillSecureRandom(0x25.toByte()))
                update(digest)
                sign()
            }
        assertFalse(verify(request.deviceIdentity.signingPublicKey, digest, doubleHashedSignature))

        val shortDigest = digest.copyOf(31)
        val validShortDigestSignature =
            Signature.getInstance("NONEwithECDSA").run {
                initSign(privateKey, FixedFillSecureRandom(0x26.toByte()))
                update(shortDigest)
                sign()
            }
        assertTrue(
            Signature.getInstance("NONEwithECDSA").run {
                initVerify(decodePublic(request.deviceIdentity.signingPublicKey))
                update(shortDigest)
                verify(validShortDigestSignature)
            },
        )
        assertFalse(verify(request.deviceIdentity.signingPublicKey, shortDigest, validShortDigestSignature))

        val wrongDigest = digest.copyOf().apply { this[0] = (this[0].toInt() xor 1).toByte() }
        val wrongSignature = request.requestSignature.copyOf().apply {
            this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte()
        }
        assertFalse(verify(request.deviceIdentity.signingPublicKey, wrongDigest, request.requestSignature))
        assertFalse(verify(request.deviceIdentity.signingPublicKey, digest, wrongSignature))
        assertFalse(
            verify(
                decodePairingFixtureBase64URL(fixture.material("host_signing_public_key")),
                digest,
                request.requestSignature,
            ),
        )
        assertFalse(verify(ByteArray(65), digest, request.requestSignature))
        assertFalse(verify(request.deviceIdentity.signingPublicKey.copyOf(64), digest, request.requestSignature))
        assertFalse(verify(request.deviceIdentity.signingPublicKey, digest, byteArrayOf()))
        assertFalse(verify(request.deviceIdentity.signingPublicKey, digest, ByteArray(81) { 0x30 }))
        assertFalse(verify(request.deviceIdentity.signingPublicKey, digest, ByteArray(8) { 0x30 }))
        assertFalse(verify(request.deviceIdentity.signingPublicKey, digest, byteArrayOf(0x30, 0x00)))
    }

    @Test
    fun sharedWireFixtureNegativeCasesFailClosed() {
        val fixture = SharedPairingWireFixture.load()
        assertEquals(setOf("field_tamper", "signature", "size", "order"), fixture.negativeCategories)
        listOf(
            "reordered_required_capabilities",
            "tampered_request_field",
            "tampered_request_signature",
            "oversized_device_name",
            "tampered_acceptance_signature",
            "tampered_session_context",
        ).forEach { name ->
            val negative = fixture.negative(name)
            assertEquals(name, negative.sha256, pairingFixtureSha256Hex(negative.wireUtf8))
        }

        assertThrows(IllegalArgumentException::class.java) {
            beginSharedFixture(
                fixture,
                qrWire = fixture.negative("reordered_required_capabilities").wireUtf8,
            )
        }

        val changedField = InternetPairingRequest.parse(fixture.negative("tampered_request_field").wireUtf8)
        val changedExecution = beginSharedFixture(fixture, deviceName = changedField.deviceName, enforceDigest = false)
        assertFalse(
            verify(
                changedField.deviceIdentity.signingPublicKey,
                checkNotNull(changedExecution.signer.lastDigest),
                changedField.requestSignature,
            ),
        )
        changedExecution.pending.close()

        val changedSignature = InternetPairingRequest.parse(fixture.negative("tampered_request_signature").wireUtf8)
        assertFalse(
            verify(
                changedSignature.deviceIdentity.signingPublicKey,
                decodePairingFixtureBase64URL(fixture.expected("request_digest")),
                changedSignature.requestSignature,
            ),
        )
        assertThrows(IllegalArgumentException::class.java) {
            InternetPairingRequest.parse(fixture.negative("oversized_device_name").wireUtf8)
        }

        val changedAcceptanceSignature = InternetPairingAcceptance.parse(
            fixture.negative("tampered_acceptance_signature").wireUtf8,
        )
        val signatureExecution = beginSharedFixture(fixture)
        assertThrows(IllegalArgumentException::class.java) {
            signatureExecution.pending.complete(changedAcceptanceSignature)
        }
        assertEquals(null, signatureExecution.sink.sharedSecret)

        val changedContext = InternetPairingAcceptance.parse(
            fixture.negative("tampered_session_context").wireUtf8,
        )
        val contextExecution = beginSharedFixture(fixture)
        assertThrows(IllegalArgumentException::class.java) {
            contextExecution.pending.complete(changedContext)
        }
        assertEquals(null, contextExecution.sink.sharedSecret)
    }
}

private data class SharedFixtureExecution(
    val pending: PendingInternetPairing,
    val signer: FixtureDigestSigner,
    val sink: MemorySink,
)

private class FixtureDigestSigner(
    override val publicIdentity: InternetPairingIdentity,
    private val expectedDigest: ByteArray?,
    private val fixtureSignature: ByteArray,
) : InternetPairingSigner {
    var calls = 0
        private set
    var lastDigest: ByteArray? = null
        private set

    override fun signTranscriptDigest(digest: ByteArray): ByteArray {
        calls += 1
        lastDigest = digest.copyOf()
        if (expectedDigest != null) {
            check(MessageDigest.isEqual(expectedDigest, digest)) { "Production canonical digest drifted from the shared fixture" }
        }
        return fixtureSignature.copyOf()
    }
}

private fun beginSharedFixture(
    fixture: SharedPairingWireFixture,
    qrWire: String = fixture.wire("qr_offer").utf8,
    deviceName: String = "Fixture Android",
    enforceDigest: Boolean = true,
): SharedFixtureExecution {
    val expectedRequest = InternetPairingRequest.parse(fixture.wire("pairing_request").utf8)
    val signer =
        FixtureDigestSigner(
            expectedRequest.deviceIdentity,
            if (enforceDigest) decodePairingFixtureBase64URL(fixture.expected("request_digest")) else null,
            expectedRequest.requestSignature,
        )
    val sink = MemorySink()
    val coordinator =
        InternetPairingCoordinator(
            signer,
            sink,
            Clock.fixed(Instant.ofEpochSecond(2_000_000_000L), ZoneOffset.UTC),
            FixedFillSecureRandom(fixture.materialInt("device_ephemeral_random_fill_byte").toByte()),
        )
    return SharedFixtureExecution(coordinator.begin(qrWire, deviceName), signer, sink)
}

private fun decodeFixturePrivateKey(value: String): PrivateKey {
    val parameters = AlgorithmParameters.getInstance("EC").apply { init(ECGenParameterSpec("secp256r1")) }
    val spec = parameters.getParameterSpec(ECParameterSpec::class.java)
    val scalar = BigInteger(1, decodePairingFixtureBase64URL(value))
    return KeyFactory.getInstance("EC").generatePrivate(ECPrivateKeySpec(scalar, spec))
}

private class Fixture(
    val expiresAt: Long = NOW + 300,
    clock: Clock = Clock.fixed(Instant.ofEpochSecond(NOW), ZoneOffset.UTC),
    sinkOverride: InternetPairingSecretSink? = null,
) {
    val hostSigning = keyPair()
    val hostEphemeral = keyPair()
    val deviceSigning = keyPair()
    val offerId = ByteArray(16) { (it + 81).toByte() }
    val oneTime = ByteArray(32) { (it + 1).toByte() }
    val challenge = ByteArray(32) { (it + 41).toByte() }
    val hostIdentity = identity("host-1", hostSigning)
    private val deviceIdentity = identity("device-1", deviceSigning)
    val url =
        InternetPairingURL.create(
            offerId,
            oneTime,
            expiresAt,
            hostIdentity,
            challenge,
            encodePublic(hostEphemeral),
        )
    val sink = MemorySink()
    val coordinator = InternetPairingCoordinator(JvmSigner(deviceIdentity, deviceSigning.private), sinkOverride ?: sink, clock)

    fun verifyRequest(request: InternetPairingRequest): Boolean {
        val parts = parts(request)
        val signatureValid = verify(request.deviceIdentity.signingPublicKey, digest(REQUEST_DOMAIN, *parts), request.requestSignature)
        val expectedMac = hmac(oneTime, digest(BOOTSTRAP_DOMAIN, *(parts + request.requestSignature)))
        return signatureValid && MessageDigest.isEqual(expectedMac, request.bootstrapMac)
    }

    fun accept(request: InternetPairingRequest): HostResult {
        check(verifyRequest(request))
        val parts = parts(request)
        val ecdh = ecdh(hostEphemeral.private, request.deviceEphemeralPublicKey)
        val shared = hkdf(ecdh, oneTime, digest(SHARED_DOMAIN, *parts))
        val bootstrap = hkdf(ecdh, oneTime, digest(BOOTSTRAP_CREDENTIAL_DOMAIN, *parts))
        ecdh.fill(0)
        val keyId = sha256(shared + bootstrap).toHex()
        val resultDigest =
            digest(
                RESULT_DOMAIN,
                *(parts + request.requestSignature + request.bootstrapMac + byteArrayOf(1) + keyId.toByteArray()),
            )
        val context = digest(SESSION_CONTEXT_DOMAIN, *parts)
        val acceptance = InternetPairingAcceptance(true, offerId.copyOf(), hostIdentity, context, keyId, sign(hostSigning.private, resultDigest))
        return HostResult(acceptance, keyId, shared, bootstrap, context)
    }

    private fun parts(request: InternetPairingRequest): Array<ByteArray> =
        arrayOf(
            u64(1), u64(1), "host".toByteArray(), "device".toByteArray(),
            canonicalList(listOf("ECDSA_P256_SHA256")), canonicalList(listOf("ECDH_P256")),
            canonicalList(listOf("AES_256_GCM")),
            canonicalList(
                listOf(
                    "application_e2ee",
                    "audio_data_channel",
                    "bulk_data_channel",
                    "control_data_channel",
                    "media_data_channel",
                    "peer_identity",
                ),
            ),
            offerId, challenge, u64(expiresAt),
            *identityParts(hostIdentity), encodePublic(hostEphemeral),
            *identityParts(request.deviceIdentity), request.deviceName.toByteArray(), request.deviceEphemeralPublicKey,
        )
}

private data class HostResult(
    val acceptance: InternetPairingAcceptance,
    val sessionKeyId: String,
    val sharedSecret: ByteArray,
    val bootstrapSecret: ByteArray,
    val sessionContext: ByteArray,
)

private class MemorySink : InternetPairingSecretSink {
    var pairingIdentifier: String? = null
    var sharedSecret: ByteArray? = null
    var bootstrapSecret: ByteArray? = null

    override fun persistPairingSecrets(pairingIdentifier: String, sharedSecret: ByteArray, bootstrapSecret: ByteArray) {
        this.pairingIdentifier = pairingIdentifier
        this.sharedSecret = sharedSecret.copyOf()
        this.bootstrapSecret = bootstrapSecret.copyOf()
    }
}

private class ReferencingSink(
    private val throwOnPersist: Boolean = false,
) : InternetPairingSecretSink {
    var sharedReference: ByteArray? = null
    var bootstrapReference: ByteArray? = null

    override fun persistPairingSecrets(pairingIdentifier: String, sharedSecret: ByteArray, bootstrapSecret: ByteArray) {
        sharedReference = sharedSecret
        bootstrapReference = bootstrapSecret
        if (throwOnPersist) throw IllegalStateException("persist failed")
    }
}

private class JvmSigner(
    override val publicIdentity: InternetPairingIdentity,
    private val privateKey: PrivateKey,
) : InternetPairingSigner {
    override fun signTranscriptDigest(digest: ByteArray): ByteArray = sign(privateKey, digest)
}

private class MutableClock(
    var epochSeconds: Long,
) : Clock() {
    override fun getZone(): ZoneId = ZoneOffset.UTC
    override fun withZone(zone: ZoneId): Clock = this
    override fun instant(): Instant = Instant.ofEpochSecond(epochSeconds)
}

private fun mutatePayload(url: String, mutation: com.google.gson.JsonObject.() -> Unit): String {
    val encoded = url.substringAfter("&o=")
    val json = JsonParser.parseString(String(Base64.getUrlDecoder().decode(encoded))).asJsonObject.apply(mutation)
    return "vibescreen://pair?v=1&o=${json.toString().toByteArray().base64Url()}"
}

private fun identity(deviceId: String, pair: KeyPair): InternetPairingIdentity {
    val key = encodePublic(pair)
    return InternetPairingIdentity(deviceId, sha256(key).toHex(), 1, signingPublicKey = key)
}

private fun keyPair(): KeyPair =
    KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()

private fun encodePublic(pair: KeyPair): ByteArray {
    val key = pair.public as ECPublicKey
    return byteArrayOf(4) + coordinate(key.w.affineX) + coordinate(key.w.affineY)
}

private fun coordinate(value: BigInteger): ByteArray {
    val signed = value.toByteArray()
    val unsigned = if (signed.size == 33 && signed[0] == 0.toByte()) signed.copyOfRange(1, signed.size) else signed
    return ByteArray(32 - unsigned.size) + unsigned
}

private fun decodePublic(encoded: ByteArray): ECPublicKey {
    val parameters = AlgorithmParameters.getInstance("EC").apply { init(ECGenParameterSpec("secp256r1")) }
    val spec = parameters.getParameterSpec(ECParameterSpec::class.java)
    val point = ECPoint(BigInteger(1, encoded.copyOfRange(1, 33)), BigInteger(1, encoded.copyOfRange(33, 65)))
    return KeyFactory.getInstance("EC").generatePublic(ECPublicKeySpec(point, spec)) as ECPublicKey
}

private fun ecdh(privateKey: PrivateKey, publicKey: ByteArray): ByteArray =
    KeyAgreement.getInstance("ECDH").run { init(privateKey); doPhase(decodePublic(publicKey), true); generateSecret() }

private fun sign(privateKey: PrivateKey, digest: ByteArray): ByteArray =
    Signature.getInstance("NONEwithECDSA").run { initSign(privateKey); update(digest); sign() }

private fun identityParts(identity: InternetPairingIdentity) =
    arrayOf(
        identity.deviceId.toByteArray(), identity.keyId.toByteArray(), u64(identity.keyEpoch),
        identity.signatureAlgorithm.toByteArray(), identity.signingPublicKey,
    )

private fun canonicalList(values: List<String>): ByteArray =
    ByteBuffer.allocate(8 + values.sumOf { 8 + it.toByteArray().size }).apply {
        putLong(values.size.toLong())
        values.forEach { value -> value.toByteArray().also { putLong(it.size.toLong()); put(it) } }
    }.array()

private fun digest(domain: String, vararg parts: ByteArray): ByteArray = SecurityTranscript.digest(domain, *parts)
private fun u64(value: Long): ByteArray = SecurityTranscript.uint64(value)
private fun hmac(key: ByteArray, value: ByteArray): ByteArray =
    Mac.getInstance("HmacSHA256").run { init(SecretKeySpec(key, "HmacSHA256")); doFinal(value) }
private fun hkdf(input: ByteArray, salt: ByteArray, info: ByteArray): ByteArray {
    val extract = hmac(salt, input)
    return hmac(extract, info + byteArrayOf(1)).also { extract.fill(0) }
}
private fun sha256(value: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(value)
private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
private fun ByteArray.base64Url(): String = Base64.getUrlEncoder().withoutPadding().encodeToString(this)

private const val NOW = 1_800_000_000L
private const val DEVICE_NAME = "Test Android"
private const val REQUEST_DOMAIN = "vibescreen/pairing-request/v1"
private const val BOOTSTRAP_DOMAIN = "vibescreen/pairing-bootstrap/v1"
private const val SHARED_DOMAIN = "vibescreen/pairing-shared/v1"
private const val BOOTSTRAP_CREDENTIAL_DOMAIN = "vibescreen/pairing-bootstrap-credential/v1"
private const val SESSION_CONTEXT_DOMAIN = "vibescreen/pairing-session-context/v1"
private const val RESULT_DOMAIN = "vibescreen/pairing-result/v1"
