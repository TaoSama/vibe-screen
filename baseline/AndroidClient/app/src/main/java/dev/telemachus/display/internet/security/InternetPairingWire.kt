package dev.telemachus.display.internet.security

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.nio.charset.StandardCharsets
import java.util.Base64

internal object InternetPairingWire {
    private val requestFields =
        setOf("offer_id", "device_identity", "device_name", "ephemeral_public_key", "request_signature", "bootstrap_mac")
    private val acceptanceFields =
        setOf("accepted", "offer_id", "host_identity", "session_context", "session_key_id", "host_signature")
    private val identityFields =
        setOf("device_id", "key_id", "key_epoch", "signature_algorithm", "signing_public_key")

    fun encodeRequest(request: InternetPairingRequest): String {
        validateRequest(request)
        return JsonObject().apply {
            addProperty("offer_id", request.offerId.b64())
            add("device_identity", request.deviceIdentity.toWireJson())
            addProperty("device_name", request.deviceName)
            addProperty("ephemeral_public_key", request.deviceEphemeralPublicKey.b64())
            addProperty("request_signature", request.requestSignature.b64())
            addProperty("bootstrap_mac", request.bootstrapMac.b64())
        }.toString()
    }

    fun parseRequest(value: String): InternetPairingRequest {
        val json = parseObject(value)
        require(json.keySet() == requestFields) { "Pairing request fields are invalid" }
        return InternetPairingRequest(
            offerId = json.bytes("offer_id"),
            deviceIdentity = parseIdentity(json.objectValue("device_identity")),
            deviceName = json.string("device_name"),
            deviceEphemeralPublicKey = json.bytes("ephemeral_public_key"),
            requestSignature = json.bytes("request_signature"),
            bootstrapMac = json.bytes("bootstrap_mac"),
        ).also(::validateRequest)
    }

    fun encodeAcceptance(acceptance: InternetPairingAcceptance): String {
        validateAcceptance(acceptance)
        return JsonObject().apply {
            addProperty("accepted", acceptance.accepted)
            addProperty("offer_id", acceptance.offerId.b64())
            add("host_identity", acceptance.hostIdentity.toWireJson())
            addProperty("session_context", acceptance.sessionContext.b64())
            addProperty("session_key_id", acceptance.sessionKeyId)
            addProperty("host_signature", acceptance.hostSignature.b64())
        }.toString()
    }

    fun parseAcceptance(value: String): InternetPairingAcceptance {
        val json = parseObject(value)
        require(json.keySet() == acceptanceFields) { "Pairing acceptance fields are invalid" }
        return InternetPairingAcceptance(
            accepted = json.boolean("accepted"),
            offerId = json.bytes("offer_id"),
            hostIdentity = parseIdentity(json.objectValue("host_identity")),
            sessionContext = json.bytes("session_context"),
            sessionKeyId = json.string("session_key_id"),
            hostSignature = json.bytes("host_signature"),
        ).also(::validateAcceptance)
    }

    private fun validateRequest(request: InternetPairingRequest) {
        require(request.offerId.size == OFFER_ID_BYTES) { "Pairing request offer ID must contain 16 bytes" }
        require(request.deviceName.toByteArray(StandardCharsets.UTF_8).size in 1..MAX_DEVICE_NAME_BYTES) {
            "Pairing request device name must contain 1 to 256 UTF-8 bytes"
        }
        require(request.deviceEphemeralPublicKey.size == P256_PUBLIC_KEY_BYTES) { "Pairing request ephemeral key is invalid" }
        validateP256PublicKey(request.deviceEphemeralPublicKey)
        require(request.requestSignature.size in 1..MAX_ECDSA_DER_BYTES) { "Pairing request signature is invalid" }
        require(request.bootstrapMac.size == SHA256_BYTES) { "Pairing request bootstrap MAC must contain 32 bytes" }
    }

    private fun validateAcceptance(acceptance: InternetPairingAcceptance) {
        require(acceptance.offerId.size == OFFER_ID_BYTES) { "Pairing acceptance offer ID must contain 16 bytes" }
        require(acceptance.sessionContext.size == SHA256_BYTES) { "Pairing acceptance session context must contain 32 bytes" }
        require(acceptance.sessionKeyId.length == SHA256_BYTES * 2 && acceptance.sessionKeyId.all { it in '0'..'9' || it in 'a'..'f' }) {
            "Pairing acceptance session key ID must be lowercase SHA-256 hex"
        }
        require(acceptance.hostSignature.size in 1..MAX_ECDSA_DER_BYTES) { "Pairing acceptance signature is invalid" }
    }

    private fun InternetPairingIdentity.toWireJson() =
        JsonObject().apply {
            addProperty("device_id", deviceId)
            addProperty("key_id", keyId)
            addProperty("key_epoch", keyEpoch)
            addProperty("signature_algorithm", signatureAlgorithm)
            addProperty("signing_public_key", signingPublicKey.b64())
        }

    private fun parseIdentity(json: JsonObject): InternetPairingIdentity {
        require(json.keySet() == identityFields) { "Pairing identity fields are invalid" }
        return InternetPairingIdentity(
            deviceId = json.string("device_id"),
            keyId = json.string("key_id"),
            keyEpoch = json.long("key_epoch"),
            signatureAlgorithm = json.string("signature_algorithm"),
            signingPublicKey = json.bytes("signing_public_key"),
        )
    }

    private fun parseObject(value: String): JsonObject =
        runCatching { JsonParser.parseString(value).asJsonObject }
            .getOrElse { throw IllegalArgumentException("Pairing JSON is invalid", it) }

    private fun JsonObject.string(name: String): String =
        get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString
            ?: throw IllegalArgumentException("Pairing field $name must be a string")

    private fun JsonObject.long(name: String): Long {
        val primitive = get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber }?.asJsonPrimitive
            ?: throw IllegalArgumentException("Pairing field $name must be an integer")
        val literal = primitive.toString()
        require(literal.matches(Regex("-?[0-9]+"))) { "Pairing field $name must be an integer" }
        return literal.toLongOrNull() ?: throw IllegalArgumentException("Pairing field $name is outside the integer range")
    }

    private fun JsonObject.boolean(name: String): Boolean {
        val primitive = get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isBoolean }?.asJsonPrimitive
            ?: throw IllegalArgumentException("Pairing field $name must be a boolean")
        return primitive.asBoolean
    }

    private fun JsonObject.objectValue(name: String): JsonObject =
        get(name)?.takeIf { it.isJsonObject }?.asJsonObject
            ?: throw IllegalArgumentException("Pairing field $name must be an object")

    private fun JsonObject.bytes(name: String): ByteArray = string(name).decodeB64()

    private fun ByteArray.b64(): String = Base64.getUrlEncoder().withoutPadding().encodeToString(this)

    private fun String.decodeB64(): ByteArray {
        require(isNotEmpty() && '=' !in this && all { it.isLetterOrDigit() || it == '-' || it == '_' }) {
            "Pairing field is not canonical base64url"
        }
        val decoded = runCatching { Base64.getUrlDecoder().decode(this) }
            .getOrElse { throw IllegalArgumentException("Pairing field is not base64url", it) }
        require(decoded.b64() == this) { "Pairing field is not canonical base64url" }
        return decoded
    }

    private const val OFFER_ID_BYTES = 16
    private const val SHA256_BYTES = 32
    private const val P256_PUBLIC_KEY_BYTES = 65
    private const val MAX_DEVICE_NAME_BYTES = 256
    private const val MAX_ECDSA_DER_BYTES = 80
}
