package dev.telemachus.display.internet.security

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.net.URI
import java.nio.ByteBuffer
import java.nio.charset.StandardCharsets
import java.security.PrivateKey
import java.security.SecureRandom
import java.time.Clock
import java.util.Base64
data class InternetPairingIdentity(
    val deviceId: String,
    val keyId: String,
    val keyEpoch: Long,
    val signatureAlgorithm: String = SIGNATURE_ALGORITHM,
    val signingPublicKey: ByteArray,
) {
    init {
        require(deviceId.isNotBlank() && keyId.isNotBlank() && keyEpoch > 0) { "Pairing identity is incomplete" }
        require(signatureAlgorithm == SIGNATURE_ALGORITHM) { "Unsupported pairing signature algorithm" }
        require(signingPublicKey.size == P256_PUBLIC_KEY_BYTES) { "Pairing identity requires an uncompressed P-256 key" }
        require(keyId == pairingSha256(signingPublicKey).toPairingHex()) { "Pairing identity key ID does not match its signing key" }
        validateP256PublicKey(signingPublicKey)
    }

    override fun equals(other: Any?): Boolean =
        other is InternetPairingIdentity &&
            deviceId == other.deviceId && keyId == other.keyId && keyEpoch == other.keyEpoch &&
            signatureAlgorithm == other.signatureAlgorithm && signingPublicKey.contentEquals(other.signingPublicKey)

    override fun hashCode(): Int = 31 * deviceId.hashCode() + signingPublicKey.contentHashCode()
}
fun interface InternetPairingSigner {
    fun signTranscriptDigest(digest: ByteArray): ByteArray
    val publicIdentity: InternetPairingIdentity
        get() = error("Pairing signer must expose its public identity")
}

class AndroidDeviceIdentityPairingSigner(
    private val identity: AndroidDeviceIdentity,
) : InternetPairingSigner {
    override val publicIdentity =
        identity.publicIdentity.let {
            InternetPairingIdentity(it.deviceId, it.keyId, it.keyEpoch, signingPublicKey = it.signingPublicKey.copyOf())
        }
    override fun signTranscriptDigest(digest: ByteArray): ByteArray = identity.signTranscriptDigest(digest)
}

fun interface InternetPairingSecretSink {
    fun persistPairingSecrets(
        pairingIdentifier: String,
        sharedSecret: ByteArray,
        bootstrapSecret: ByteArray,
    )
}

fun AndroidStoredInternetSessionFactory.internetPairingSecretSink(): InternetPairingSecretSink =
    InternetPairingSecretSink(::persistPairingSecrets)

data class InternetPairingRequest(
    val offerId: ByteArray,
    val deviceIdentity: InternetPairingIdentity,
    val deviceName: String,
    val deviceEphemeralPublicKey: ByteArray,
    val requestSignature: ByteArray,
    val bootstrapMac: ByteArray,
) {
    fun encode(): String = InternetPairingWire.encodeRequest(this)

    override fun equals(other: Any?): Boolean =
        other is InternetPairingRequest && offerId.contentEquals(other.offerId) && deviceIdentity == other.deviceIdentity && deviceName == other.deviceName &&
            deviceEphemeralPublicKey.contentEquals(other.deviceEphemeralPublicKey) &&
            requestSignature.contentEquals(other.requestSignature) && bootstrapMac.contentEquals(other.bootstrapMac)

    override fun hashCode(): Int = offerId.contentHashCode()

    companion object {
        fun parse(value: String): InternetPairingRequest = InternetPairingWire.parseRequest(value)
    }
}

data class InternetPairingAcceptance(
    val accepted: Boolean,
    val offerId: ByteArray,
    val hostIdentity: InternetPairingIdentity,
    val sessionContext: ByteArray,
    val sessionKeyId: String,
    val hostSignature: ByteArray,
) {
    fun encode(): String = InternetPairingWire.encodeAcceptance(this)

    companion object {
        fun parse(value: String): InternetPairingAcceptance = InternetPairingWire.parseAcceptance(value)
    }
}

data class InternetPairingPublicMetadata(
    val pairingIdentifier: String,
    val expiresAtUnixSeconds: Long,
    val hostIdentity: InternetPairingIdentity,
    val deviceIdentity: InternetPairingIdentity,
    val deviceName: String,
    val sessionKeyId: String? = null,
    val sessionContext: ByteArray? = null,
)

data class InternetPairingResult(
    val metadata: InternetPairingPublicMetadata,
)

class InternetPairingCoordinator(
    private val signer: InternetPairingSigner,
    private val secretSink: InternetPairingSecretSink,
    private val clock: Clock = Clock.systemUTC(),
    private val secureRandom: SecureRandom = SecureRandom(),
) {
    constructor(
        identity: AndroidDeviceIdentity,
        sessionFactory: AndroidStoredInternetSessionFactory,
        clock: Clock = Clock.systemUTC(),
        secureRandom: SecureRandom = SecureRandom(),
    ) : this(AndroidDeviceIdentityPairingSigner(identity), sessionFactory.internetPairingSecretSink(), clock, secureRandom)

    fun begin(encodedUrl: String, deviceName: String): PendingInternetPairing = begin(InternetPairingURL.parse(encodedUrl), deviceName)

    fun begin(url: InternetPairingURL, deviceName: String): PendingInternetPairing {
        require(deviceName.toByteArray(StandardCharsets.UTF_8).size in 1..MAX_DEVICE_NAME_BYTES) { "Device name must contain 1 to 256 UTF-8 bytes" }
        val offer = url.consumeOffer()
        try {
            validateOffer(offer, clock.instant().epochSecond)
            val ephemeral = generateEphemeral(secureRandom)
            val parts = canonicalParts(offer, signer.publicIdentity, deviceName, publicPoint(ephemeral))
            val requestSignature = signer.signTranscriptDigest(SecurityTranscript.digest(REQUEST_DOMAIN, *parts))
            require(requestSignature.size in 1..MAX_ECDSA_DER_BYTES) { "Device pairing signature is invalid" }
            val bootstrapMac = hmac(offer.oneTimeCredential, SecurityTranscript.digest(BOOTSTRAP_DOMAIN, *(parts + requestSignature)))
            val request =
                InternetPairingRequest(
                    offer.offerId,
                    signer.publicIdentity,
                    deviceName,
                    publicPoint(ephemeral),
                    requestSignature,
                    bootstrapMac,
                )
            return PendingInternetPairing(offer, ephemeral.private, parts, request, secretSink, clock)
        } catch (failure: Throwable) {
            offer.destroyCredential()
            throw failure
        }
    }
}

class PendingInternetPairing internal constructor(
    private val offer: InternetPairingOffer,
    private val ephemeralPrivateKey: PrivateKey,
    private val canonicalParts: Array<ByteArray>,
    val request: InternetPairingRequest,
    private val secretSink: InternetPairingSecretSink,
    private val clock: Clock,
) : AutoCloseable {
    private var consumed = false

    val publicMetadata =
        InternetPairingPublicMetadata(
            pairingSha256(offer.offerId).toPairingHex(),
            offer.expiresAtUnixSeconds,
            offer.hostIdentity,
            request.deviceIdentity,
            request.deviceName,
        )

    @Synchronized
    fun complete(acceptance: InternetPairingAcceptance): InternetPairingResult {
        check(!consumed) { "Pairing attempt was already completed" }
        consumed = true
        try {
            require(clock.instant().epochSecond <= offer.expiresAtUnixSeconds) { "Pairing offer expired" }
            require(acceptance.accepted) { "Host rejected pairing" }
            require(acceptance.hostSignature.size in 1..MAX_ECDSA_DER_BYTES) { "Host pairing signature is invalid" }
            require(acceptance.offerId.contentEquals(offer.offerId)) { "Host accepted a different pairing offer" }
            require(acceptance.hostIdentity == offer.hostIdentity) { "Host acceptance identity does not match the offer" }
            val expectedContext = SecurityTranscript.digest(SESSION_CONTEXT_DOMAIN, *canonicalParts)
            require(acceptance.sessionContext.contentEquals(expectedContext)) { "Host returned a different pairing session context" }
            val sharedSecret = ecdh(ephemeralPrivateKey, offer.hostEphemeralPublicKey)
            val pairingSecret =
                try {
                    hkdf(sharedSecret, offer.oneTimeCredential, SecurityTranscript.digest(SHARED_DOMAIN, *canonicalParts))
                } catch (failure: Throwable) {
                    sharedSecret.fill(0)
                    throw failure
                }
            val bootstrapSecret =
                try {
                    hkdf(sharedSecret, offer.oneTimeCredential, SecurityTranscript.digest(BOOTSTRAP_CREDENTIAL_DOMAIN, *canonicalParts))
                } catch (failure: Throwable) {
                    pairingSecret.fill(0)
                    throw failure
                } finally {
                    sharedSecret.fill(0)
                }
            try {
                val expectedKeyId = pairingSha256(pairingSecret + bootstrapSecret).toPairingHex()
                require(java.security.MessageDigest.isEqual(expectedKeyId.toByteArray(), acceptance.sessionKeyId.toByteArray())) {
                    "Host returned an unexpected pairing key identifier"
                }
                val resultDigest =
                    SecurityTranscript.digest(
                        RESULT_DOMAIN,
                        *(canonicalParts + request.requestSignature + request.bootstrapMac + byteArrayOf(1) + acceptance.sessionKeyId.toByteArray()),
                    )
                require(verify(offer.hostIdentity.signingPublicKey, resultDigest, acceptance.hostSignature)) {
                    "Host pairing acceptance signature is invalid"
                }
                secretSink.persistPairingSecrets(pairingSha256(offer.offerId).toPairingHex(), pairingSecret.copyOf(), bootstrapSecret.copyOf())
                return InternetPairingResult(publicMetadata.copy(sessionKeyId = expectedKeyId, sessionContext = expectedContext))
            } finally {
                pairingSecret.fill(0)
                bootstrapSecret.fill(0)
            }
        } finally {
            offer.destroyCredential()
        }
    }

    @Synchronized
    override fun close() {
        if (!consumed) {
            consumed = true
            offer.destroyCredential()
        }
    }
}

class InternetPairingURL private constructor(
    private var offer: InternetPairingOffer?,
) {
    internal fun consumeOffer(): InternetPairingOffer = checkNotNull(offer) { "Pairing URL was already consumed" }.also { offer = null }

    fun encode(): String {
        val current = checkNotNull(offer) { "Pairing URL was already consumed" }
        return "vibescreen://pair?v=1&o=${base64Url(current.toJson().toString().toByteArray(StandardCharsets.UTF_8))}"
    }

    companion object {
        fun create(
            offerId: ByteArray,
            oneTimeCredential: ByteArray,
            expiresAtUnixSeconds: Long,
            hostIdentity: InternetPairingIdentity,
            challenge: ByteArray,
            hostEphemeralPublicKey: ByteArray,
        ): InternetPairingURL =
            InternetPairingURL(
                InternetPairingOffer(
                    offerId.copyOf(),
                    oneTimeCredential.copyOf(),
                    expiresAtUnixSeconds,
                    hostIdentity,
                    challenge.copyOf(),
                    hostEphemeralPublicKey.copyOf(),
                ),
            )

        fun parse(value: String): InternetPairingURL {
            val uri = runCatching { URI(value) }.getOrElse { throw IllegalArgumentException("Malformed pairing URL", it) }
            require(
                uri.scheme == "vibescreen" && uri.host == "pair" && uri.path.isEmpty() &&
                    uri.userInfo == null && uri.port == -1 && uri.rawFragment == null,
            ) { "Unsupported pairing URL" }
            val parameters = parseQuery(uri.rawQuery ?: "")
            require(parameters.keys == setOf("v", "o") && parameters.getValue("v").single() == "1") { "Unsupported pairing URL version" }
            require(parameters.values.all { it.size == 1 }) { "Pairing URL contains duplicate parameters" }
            val payload = decodeBase64Url(parameters.getValue("o").single())
            val json = runCatching { JsonParser.parseString(String(payload, StandardCharsets.UTF_8)).asJsonObject }
                .getOrElse { throw IllegalArgumentException("Pairing URL payload is invalid", it) }
            return InternetPairingURL(InternetPairingOffer.fromJson(json))
        }

        private fun parseQuery(query: String): Map<String, List<String>> =
            query.split('&').filter(String::isNotEmpty).groupBy({ it.substringBefore('=') }, { it.substringAfter('=', "") })
    }
}

internal data class InternetPairingOffer(
    val offerId: ByteArray,
    val oneTimeCredential: ByteArray,
    val expiresAtUnixSeconds: Long,
    val hostIdentity: InternetPairingIdentity,
    val challenge: ByteArray,
    val hostEphemeralPublicKey: ByteArray,
    val protocolMin: Long = PROTOCOL_VERSION,
    val protocolMax: Long = PROTOCOL_VERSION,
    val hostRole: String = HOST_ROLE,
    val deviceRole: String = DEVICE_ROLE,
    val signatureAlgorithms: List<String> = listOf(SIGNATURE_ALGORITHM),
    val keyAgreementAlgorithms: List<String> = listOf(KEY_AGREEMENT_ALGORITHM),
    val aeadAlgorithms: List<String> = listOf(AEAD_ALGORITHM),
    val requiredCapabilities: List<String> = REQUIRED_CAPABILITIES,
) {
    fun destroyCredential() = oneTimeCredential.fill(0)

    fun toJson() =
        JsonObject().apply {
            addProperty("protocol_min", protocolMin)
            addProperty("protocol_max", protocolMax)
            addProperty("host_role", hostRole)
            addProperty("device_role", deviceRole)
            add("signature_algorithms", signatureAlgorithms.toJsonArray())
            add("key_agreement_algorithms", keyAgreementAlgorithms.toJsonArray())
            add("aead_algorithms", aeadAlgorithms.toJsonArray())
            add("required_capabilities", requiredCapabilities.toJsonArray())
            addProperty("offer_id", base64Url(offerId))
            addProperty("one_time_credential", base64Url(oneTimeCredential))
            addProperty("expires_at_unix_seconds", expiresAtUnixSeconds)
            add("host_identity", hostIdentity.toJson())
            addProperty("challenge", base64Url(challenge))
            addProperty("ephemeral_public_key", base64Url(hostEphemeralPublicKey))
        }

    companion object {
        private val fields =
            setOf(
                "protocol_min", "protocol_max", "host_role", "device_role", "signature_algorithms",
                "key_agreement_algorithms", "aead_algorithms", "required_capabilities", "offer_id",
                "one_time_credential", "expires_at_unix_seconds", "host_identity", "challenge", "ephemeral_public_key",
            )

        fun fromJson(json: JsonObject): InternetPairingOffer {
            require(json.keySet() == fields) { "Pairing offer fields are invalid" }
            return InternetPairingOffer(
                offerId = decodeBase64Url(json.requiredString("offer_id")),
                oneTimeCredential = decodeBase64Url(json.requiredString("one_time_credential")),
                expiresAtUnixSeconds = json.requiredLong("expires_at_unix_seconds"),
                hostIdentity = identityFromJson(json.getAsJsonObject("host_identity") ?: error("Missing host identity")),
                challenge = decodeBase64Url(json.requiredString("challenge")),
                hostEphemeralPublicKey = decodeBase64Url(json.requiredString("ephemeral_public_key")),
                protocolMin = json.requiredLong("protocol_min"),
                protocolMax = json.requiredLong("protocol_max"),
                hostRole = json.requiredString("host_role"),
                deviceRole = json.requiredString("device_role"),
                signatureAlgorithms = json.requiredStrings("signature_algorithms"),
                keyAgreementAlgorithms = json.requiredStrings("key_agreement_algorithms"),
                aeadAlgorithms = json.requiredStrings("aead_algorithms"),
                requiredCapabilities = json.requiredStrings("required_capabilities"),
            )
        }
    }
}

private fun validateOffer(offer: InternetPairingOffer, now: Long) {
    require(offer.protocolMin == PROTOCOL_VERSION && offer.protocolMax == PROTOCOL_VERSION) { "Pairing protocol downgrade rejected" }
    require(offer.hostRole == HOST_ROLE && offer.deviceRole == DEVICE_ROLE) { "Pairing roles are invalid" }
    require(offer.signatureAlgorithms == listOf(SIGNATURE_ALGORITHM)) { "Pairing signature algorithms are invalid" }
    require(offer.keyAgreementAlgorithms == listOf(KEY_AGREEMENT_ALGORITHM)) { "Pairing key agreement algorithms are invalid" }
    require(offer.aeadAlgorithms == listOf(AEAD_ALGORITHM)) { "Pairing AEAD algorithms are invalid" }
    require(offer.requiredCapabilities == REQUIRED_CAPABILITIES) { "Pairing capabilities are invalid or unsorted" }
    require(
        offer.offerId.size == OFFER_ID_BYTES && offer.challenge.size == CHALLENGE_BYTES &&
            offer.oneTimeCredential.size == CREDENTIAL_BYTES && offer.hostEphemeralPublicKey.size == P256_PUBLIC_KEY_BYTES,
    ) { "Pairing offer has invalid field sizes" }
    require(offer.expiresAtUnixSeconds > 0 && offer.expiresAtUnixSeconds >= now) { "Pairing offer expired" }
    validateP256PublicKey(offer.hostIdentity.signingPublicKey)
    validateP256PublicKey(offer.hostEphemeralPublicKey)
}

private fun canonicalParts(
    offer: InternetPairingOffer,
    deviceIdentity: InternetPairingIdentity,
    deviceName: String,
    deviceEphemeral: ByteArray,
): Array<ByteArray> =
    arrayOf(
        u64(offer.protocolMin), u64(offer.protocolMax), offer.hostRole.bytes(), offer.deviceRole.bytes(),
        canonicalList(offer.signatureAlgorithms), canonicalList(offer.keyAgreementAlgorithms),
        canonicalList(offer.aeadAlgorithms), canonicalList(offer.requiredCapabilities), offer.offerId,
        offer.challenge, u64(offer.expiresAtUnixSeconds),
        *identityParts(offer.hostIdentity), offer.hostEphemeralPublicKey,
        *identityParts(deviceIdentity), deviceName.bytes(), deviceEphemeral,
    )

private fun identityParts(identity: InternetPairingIdentity) =
    arrayOf(identity.deviceId.bytes(), identity.keyId.bytes(), u64(identity.keyEpoch), identity.signatureAlgorithm.bytes(), identity.signingPublicKey)

private fun canonicalList(values: List<String>): ByteArray =
    ByteBuffer.allocate(Long.SIZE_BYTES + values.sumOf { Long.SIZE_BYTES + it.bytes().size }).apply {
        putLong(values.size.toLong())
        values.forEach { value -> value.bytes().also { putLong(it.size.toLong()); put(it) } }
    }.array()

private fun InternetPairingIdentity.toJson() =
    JsonObject().apply {
        addProperty("device_id", deviceId)
        addProperty("key_id", keyId)
        addProperty("key_epoch", keyEpoch)
        addProperty("signature_algorithm", signatureAlgorithm)
        addProperty("signing_public_key", base64Url(signingPublicKey))
    }

private fun identityFromJson(json: JsonObject): InternetPairingIdentity {
    require(json.keySet() == setOf("device_id", "key_id", "key_epoch", "signature_algorithm", "signing_public_key")) {
        "Pairing identity fields are invalid"
    }
    return InternetPairingIdentity(
        json.requiredString("device_id"), json.requiredString("key_id"), json.requiredLong("key_epoch"),
        json.requiredString("signature_algorithm"), decodeBase64Url(json.requiredString("signing_public_key")),
    )
}

private fun List<String>.toJsonArray() = com.google.gson.JsonArray().also { array -> forEach(array::add) }
private fun JsonObject.requiredString(name: String): String = get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString
    ?: throw IllegalArgumentException("Pairing field $name must be a string")
private fun JsonObject.requiredLong(name: String): Long {
    val primitive = get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber }?.asJsonPrimitive
        ?: throw IllegalArgumentException("Pairing field $name must be an integer")
    val literal = primitive.toString()
    require(literal.matches(Regex("-?[0-9]+"))) { "Pairing field $name must be an integer" }
    return literal.toLongOrNull() ?: throw IllegalArgumentException("Pairing field $name is outside the integer range")
}
private fun JsonObject.requiredStrings(name: String): List<String> = getAsJsonArray(name)?.map {
    require(it.isJsonPrimitive && it.asJsonPrimitive.isString) { "Pairing field $name must contain strings" }; it.asString
} ?: throw IllegalArgumentException("Pairing field $name must be an array")

private fun base64Url(value: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(value)
private fun decodeBase64Url(value: String): ByteArray {
    require(value.isNotEmpty() && '=' !in value && value.all { it.isLetterOrDigit() || it == '-' || it == '_' }) { "Invalid base64url value" }
    val decoded = runCatching { Base64.getUrlDecoder().decode(value) }.getOrElse { throw IllegalArgumentException("Invalid base64url value", it) }
    require(base64Url(decoded) == value) { "Non-canonical base64url value" }
    return decoded
}
private fun String.bytes(): ByteArray = toByteArray(StandardCharsets.UTF_8)
private fun u64(value: Long): ByteArray = SecurityTranscript.uint64(value)

private const val PROTOCOL_VERSION = 1L
private const val HOST_ROLE = "host"
private const val DEVICE_ROLE = "device"
internal const val SIGNATURE_ALGORITHM = "ECDSA_P256_SHA256"
private const val KEY_AGREEMENT_ALGORITHM = "ECDH_P256"
private const val AEAD_ALGORITHM = "AES_256_GCM"
private val REQUIRED_CAPABILITIES =
    listOf("application_e2ee", "control_data_channel", "media_data_channel", "peer_identity")
private const val REQUEST_DOMAIN = "vibescreen/pairing-request/v1"
private const val BOOTSTRAP_DOMAIN = "vibescreen/pairing-bootstrap/v1"
private const val SHARED_DOMAIN = "vibescreen/pairing-shared/v1"
private const val BOOTSTRAP_CREDENTIAL_DOMAIN = "vibescreen/pairing-bootstrap-credential/v1"
private const val SESSION_CONTEXT_DOMAIN = "vibescreen/pairing-session-context/v1"
private const val RESULT_DOMAIN = "vibescreen/pairing-result/v1"
private const val P256_PUBLIC_KEY_BYTES = 65
private const val OFFER_ID_BYTES = 16
private const val CHALLENGE_BYTES = 32
private const val CREDENTIAL_BYTES = 32
private const val MAX_DEVICE_NAME_BYTES = 256
private const val MAX_ECDSA_DER_BYTES = 80
