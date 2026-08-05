package dev.telemachus.display

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import dev.telemachus.display.internet.security.InternetPairingAcceptance
import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.InternetPairingRequest
import dev.telemachus.display.internet.security.InternetPairingURL
import java.io.ByteArrayOutputStream
import java.math.BigInteger
import java.nio.ByteBuffer
import java.security.AlgorithmParameters
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.ECPoint
import java.security.spec.ECPublicKeySpec
import java.util.Base64
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** In-memory host authority used only by the MainActivity device acceptance test. */
internal class TestHostAuthority {
    private val random = SecureRandom()
    private val signingKey = keyPair()
    private val hostIdentity = identity("test-host", signingKey)

    fun createOffer(): TestPairingOffer {
        val offerId = randomBytes(16)
        val oneTimeCredential = randomBytes(32)
        val challenge = randomBytes(32)
        val ephemeral = keyPair()
        val expiresAt = System.currentTimeMillis() / 1_000 + 300
        val encoded =
            InternetPairingURL
                .create(
                    offerId,
                    oneTimeCredential,
                    expiresAt,
                    hostIdentity,
                    challenge,
                    publicPoint(ephemeral),
                ).encode()
        return TestPairingOffer(
            encodedUrl = encoded,
            pairingIdentifier = sha256(offerId).hex(),
            offerId = offerId,
            oneTimeCredential = oneTimeCredential,
            challenge = challenge,
            expiresAt = expiresAt,
            hostEphemeral = ephemeral,
        )
    }

    fun accept(
        offer: TestPairingOffer,
        request: InternetPairingRequest,
    ): InternetPairingAcceptance {
        val parts = pairingParts(offer, request)
        check(verify(request.deviceIdentity.signingPublicKey, transcriptDigest(REQUEST_DOMAIN, *parts), request.requestSignature))
        val expectedMac = hmac(offer.oneTimeCredential, transcriptDigest(BOOTSTRAP_DOMAIN, *(parts + request.requestSignature)))
        check(MessageDigest.isEqual(expectedMac, request.bootstrapMac))

        val agreement = ecdh(offer.hostEphemeral.private, request.deviceEphemeralPublicKey)
        val shared = hkdf(agreement, offer.oneTimeCredential, transcriptDigest(SHARED_DOMAIN, *parts))
        val bootstrap = hkdf(agreement, offer.oneTimeCredential, transcriptDigest(BOOTSTRAP_CREDENTIAL_DOMAIN, *parts))
        agreement.fill(0)
        val keyId = sha256(shared + bootstrap).hex()
        shared.fill(0)
        bootstrap.fill(0)
        val resultDigest =
            transcriptDigest(
                RESULT_DOMAIN,
                *(parts + request.requestSignature + request.bootstrapMac + byteArrayOf(1) + keyId.toByteArray()),
            )
        return InternetPairingAcceptance(
            accepted = true,
            offerId = offer.offerId.copyOf(),
            hostIdentity = hostIdentity,
            sessionContext = transcriptDigest(SESSION_CONTEXT_DOMAIN, *parts),
            sessionKeyId = keyId,
            hostSignature = sign(signingKey.private, resultDigest),
        )
    }

    fun issueLease(
        offer: TestPairingOffer,
        request: InternetPairingRequest,
        sessionEpoch: Long,
    ): TestLease {
        val sessionId = randomBytes(18).base64Url()
        val protocolSessionId = randomBytes(16)
        val token = randomBytes(48).base64Url()
        val context = transcriptDigest(SESSION_CONTEXT_DOMAIN, *pairingParts(offer, request))
        val signalingUrl = "http://127.0.0.1:18080"
        val iceUrl = "stun:127.0.0.1:3478"
        val digest =
            transcriptDigest(
                LEASE_DOMAIN,
                u64(1),
                offer.pairingIdentifier.toByteArray(),
                hostIdentity.deviceId.toByteArray(),
                hostIdentity.keyId.toByteArray(),
                signalingUrl.toByteArray(),
                sessionId.toByteArray(),
                u64(sessionEpoch),
                u64(request.deviceIdentity.keyEpoch),
                context,
                protocolSessionId,
                token.toByteArray(),
                u64(1),
                u64(1),
                iceUrl.toByteArray(),
                byteArrayOf(0),
                byteArrayOf(0),
                byteArrayOf(1),
            )
        val signature = sign(signingKey.private, digest)
        val encoded =
            JsonObject().apply {
                addProperty("version", 1)
                addProperty("pairing_id", offer.pairingIdentifier)
                addProperty("pinned_host_id", hostIdentity.deviceId)
                addProperty("signaling_url", signalingUrl)
                addProperty("signaling_session_id", sessionId)
                addProperty("session_epoch", sessionEpoch)
                addProperty("identity_epoch", request.deviceIdentity.keyEpoch)
                addProperty("transcript_context", context.base64())
                addProperty("protocol_session_id", protocolSessionId.base64())
                addProperty("signaling_token", token)
                add(
                    "ice_servers",
                    JsonArray().apply {
                        add(
                            JsonObject().apply {
                                add("urls", JsonArray().apply { add(iceUrl) })
                                add("username", null)
                                add("credential", null)
                            },
                        )
                    },
                )
                addProperty("allow_insecure_for_testing", true)
                addProperty("lease_host_key_id", hostIdentity.keyId)
                addProperty("lease_signature", signature.base64())
            }.toString()
        return TestLease(encoded, sessionId, sessionEpoch)
    }

    private fun pairingParts(
        offer: TestPairingOffer,
        request: InternetPairingRequest,
    ): Array<ByteArray> =
        arrayOf(
            u64(1),
            u64(1),
            "host".toByteArray(),
            "device".toByteArray(),
            canonicalList(listOf("ECDSA_P256_SHA256")),
            canonicalList(listOf("ECDH_P256")),
            canonicalList(listOf("AES_256_GCM")),
            canonicalList(listOf("application_e2ee", "control_data_channel", "media_data_channel", "peer_identity")),
            offer.offerId,
            offer.challenge,
            u64(offer.expiresAt),
            *identityParts(hostIdentity),
            publicPoint(offer.hostEphemeral),
            *identityParts(request.deviceIdentity),
            request.deviceName.toByteArray(),
            request.deviceEphemeralPublicKey,
        )

    private fun randomBytes(size: Int) = ByteArray(size).also(random::nextBytes)
}

internal data class TestPairingOffer(
    val encodedUrl: String,
    val pairingIdentifier: String,
    val offerId: ByteArray,
    val oneTimeCredential: ByteArray,
    val challenge: ByteArray,
    val expiresAt: Long,
    val hostEphemeral: KeyPair,
)

internal data class TestLease(
    val encoded: String,
    val signalingSessionId: String,
    val sessionEpoch: Long,
)

private fun identity(deviceId: String, pair: KeyPair): InternetPairingIdentity {
    val publicKey = publicPoint(pair)
    return InternetPairingIdentity(deviceId, sha256(publicKey).hex(), 1, signingPublicKey = publicKey)
}

private fun keyPair(): KeyPair =
    KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()

private fun publicPoint(pair: KeyPair): ByteArray {
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
    KeyAgreement.getInstance("ECDH").run {
        init(privateKey)
        doPhase(decodePublic(publicKey), true)
        generateSecret()
    }

private fun sign(privateKey: PrivateKey, digest: ByteArray): ByteArray =
    Signature.getInstance("NONEwithECDSA").run {
        initSign(privateKey)
        update(digest)
        sign()
    }

private fun verify(publicKey: ByteArray, digest: ByteArray, signature: ByteArray): Boolean =
    Signature.getInstance("NONEwithECDSA").run {
        initVerify(decodePublic(publicKey))
        update(digest)
        verify(signature)
    }

private fun transcriptDigest(domain: String, vararg parts: ByteArray): ByteArray {
    val output = ByteArrayOutputStream()
    listOf("vibescreen/identity/v1".toByteArray(), domain.toByteArray(), *parts).forEach { part ->
        output.write(u64(part.size.toLong()))
        output.write(part)
    }
    return sha256(output.toByteArray())
}

private fun identityParts(identity: InternetPairingIdentity): Array<ByteArray> =
    arrayOf(
        identity.deviceId.toByteArray(),
        identity.keyId.toByteArray(),
        u64(identity.keyEpoch),
        identity.signatureAlgorithm.toByteArray(),
        identity.signingPublicKey,
    )

private fun canonicalList(values: List<String>): ByteArray =
    ByteBuffer.allocate(8 + values.sumOf { 8 + it.toByteArray().size }).apply {
        putLong(values.size.toLong())
        values.forEach { value -> value.toByteArray().also { putLong(it.size.toLong()); put(it) } }
    }.array()

private fun u64(value: Long): ByteArray = ByteBuffer.allocate(8).putLong(value).array()
private fun hmac(key: ByteArray, value: ByteArray): ByteArray =
    Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(key, "HmacSHA256"))
        doFinal(value)
    }

private fun hkdf(input: ByteArray, salt: ByteArray, info: ByteArray): ByteArray {
    val extract = hmac(salt, input)
    return try {
        hmac(extract, info + byteArrayOf(1))
    } finally {
        extract.fill(0)
    }
}

private fun sha256(value: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(value)
private fun ByteArray.hex(): String = joinToString("") { "%02x".format(it) }
private fun ByteArray.base64(): String = Base64.getEncoder().encodeToString(this)
private fun ByteArray.base64Url(): String = Base64.getUrlEncoder().withoutPadding().encodeToString(this)

private const val REQUEST_DOMAIN = "vibescreen/pairing-request/v1"
private const val BOOTSTRAP_DOMAIN = "vibescreen/pairing-bootstrap/v1"
private const val SHARED_DOMAIN = "vibescreen/pairing-shared/v1"
private const val BOOTSTRAP_CREDENTIAL_DOMAIN = "vibescreen/pairing-bootstrap-credential/v1"
private const val SESSION_CONTEXT_DOMAIN = "vibescreen/pairing-session-context/v1"
private const val RESULT_DOMAIN = "vibescreen/pairing-result/v1"
private const val LEASE_DOMAIN = "vibescreen/internet-session-lease/v1"
