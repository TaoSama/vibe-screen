package dev.telemachus.display.internet

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import java.nio.charset.StandardCharsets
import java.util.Base64

class AuthenticatedSessionLeaseReceiver(
    private val store: InternetSessionProfileStore,
    private val storedSessionFactory: AndroidStoredInternetSessionFactory,
    private val revocationCoordinator: InternetProductRevocationCoordinator,
) {
    fun importAuthenticatedBulkRecord(payload: ByteArray): StoredInternetSessionProfile {
        val signedLease = AuthenticatedSessionLeaseDeliveryEnvelope.decode(payload)
        return store.import(String(signedLease, StandardCharsets.UTF_8), storedSessionFactory, revocationCoordinator)
    }

    fun importingCallbacks(delegate: InternetProductSessionCallbacks): InternetProductSessionCallbacks =
        AuthenticatedSessionLeaseImportingCallbacks(this, delegate)
}

private class AuthenticatedSessionLeaseImportingCallbacks(
    private val receiver: AuthenticatedSessionLeaseReceiver,
    private val delegate: InternetProductSessionCallbacks,
) : InternetProductSessionCallbacks by delegate {
    override fun onBulkRecord(payload: ByteArray) {
        try {
            receiver.importAuthenticatedBulkRecord(payload)
        } catch (failure: Exception) {
            if (AuthenticatedSessionLeaseDeliveryEnvelope.hasSessionLeasePurpose(payload)) {
                delegate.onFailure(failure)
            } else {
                delegate.onBulkRecord(payload)
            }
        }
    }
}

internal object AuthenticatedSessionLeaseDeliveryEnvelope {
    const val PURPOSE = "vibescreen.session_lease.v1"
    const val CONTENT_TYPE = "application/vnd.vibescreen.signed-internet-session-lease+json"
    val BULK_TRANSFER_ID: ByteArray = "internet-bulk-v1".toByteArray(StandardCharsets.UTF_8)

    private const val VERSION = 1
    private val ROOT_KEYS = setOf("version", "purpose", "content_type", "signed_lease")

    fun encode(signedLease: ByteArray): ByteArray {
        require(signedLease.isNotEmpty() && signedLease.size <= InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES) {
            "Signed Internet lease is empty or too large"
        }
        val root =
            JsonObject().apply {
                addProperty("version", VERSION)
                addProperty("purpose", PURPOSE)
                addProperty("content_type", CONTENT_TYPE)
                addProperty("signed_lease", Base64.getEncoder().encodeToString(signedLease))
            }
        return root.toString().toByteArray(StandardCharsets.UTF_8).also { encoded ->
            require(encoded.size <= InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES) {
                "Signed Internet lease delivery exceeds the bulk record limit"
            }
        }
    }

    fun decode(payload: ByteArray): ByteArray {
        require(payload.isNotEmpty() && payload.size <= InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES) {
            "Signed Internet lease delivery is empty or too large"
        }
        val root =
            runCatching { JsonParser.parseString(String(payload, StandardCharsets.UTF_8)).asJsonObject }
                .getOrElse { throw IllegalArgumentException("Signed Internet lease delivery is not valid JSON", it) }
        require(root.keySet() == ROOT_KEYS) { "Signed Internet lease delivery contains missing or unknown fields" }
        require(root.strictInt("version") == VERSION) { "Unsupported signed Internet lease delivery version" }
        require(root.strictString("purpose") == PURPOSE) { "Signed Internet lease delivery purpose is invalid" }
        require(root.strictString("content_type") == CONTENT_TYPE) { "Signed Internet lease delivery content type is invalid" }
        val encodedLease = root.strictString("signed_lease")
        require(encodedLease.toByteArray(StandardCharsets.UTF_8).size <= InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES) {
            "Signed Internet lease field is too large"
        }
        val signedLease =
            runCatching { Base64.getDecoder().decode(encodedLease) }
                .getOrElse { throw IllegalArgumentException("Signed Internet lease is not valid base64", it) }
        require(Base64.getEncoder().encodeToString(signedLease) == encodedLease) {
            "Signed Internet lease base64 is not canonical"
        }
        require(signedLease.isNotEmpty() && signedLease.size <= InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES) {
            "Signed Internet lease is empty or too large"
        }
        return signedLease
    }

    fun hasSessionLeasePurpose(payload: ByteArray): Boolean =
        runCatching {
            val root = JsonParser.parseString(String(payload, StandardCharsets.UTF_8)).asJsonObject
            root.get("purpose")?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString == PURPOSE
        }.getOrDefault(false)

    private fun JsonObject.strictString(name: String): String {
        val value = get(name)
        require(value != null && value.isJsonPrimitive && value.asJsonPrimitive.isString) {
            "Signed Internet lease delivery field $name must be a string"
        }
        return value.asString
    }

    private fun JsonObject.strictInt(name: String): Int {
        val value = get(name)
        require(value != null && value.isJsonPrimitive && value.asJsonPrimitive.isNumber) {
            "Signed Internet lease delivery field $name must be an integer"
        }
        val literal = value.asJsonPrimitive.toString()
        require(literal.matches(Regex("[0-9]+"))) {
            "Signed Internet lease delivery field $name must be an integer"
        }
        return literal.toIntOrNull() ?: throw IllegalArgumentException(
            "Signed Internet lease delivery field $name is outside the integer range",
        )
    }
}
