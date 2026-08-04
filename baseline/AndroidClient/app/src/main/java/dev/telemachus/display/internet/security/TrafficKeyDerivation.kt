package dev.telemachus.display.internet.security

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

class SessionTrafficKeys(
    val keyId: String,
    val keyEpoch: Long,
    val hostControl: ByteArray,
    val deviceControl: ByteArray,
    val hostMedia: ByteArray,
    val deviceMedia: ByteArray,
) : AutoCloseable {
    internal fun combined(): ByteArray = hostControl + deviceControl + hostMedia + deviceMedia

    /** Clears the in-memory copies owned by this instance after disconnect/rotation. */
    override fun close() {
        hostControl.fill(0)
        deviceControl.fill(0)
        hostMedia.fill(0)
        deviceMedia.fill(0)
    }
}

enum class SecurityChannel(val wireValue: Int) {
    CONTROL(1),
    MEDIA(2),
}

enum class SenderRole(val wireValue: Int) {
    HOST(1),
    DEVICE(2),
}

fun SessionTrafficKeys.key(
    channel: SecurityChannel,
    sender: SenderRole,
): ByteArray =
    when (channel to sender) {
        SecurityChannel.CONTROL to SenderRole.HOST -> hostControl
        SecurityChannel.CONTROL to SenderRole.DEVICE -> deviceControl
        SecurityChannel.MEDIA to SenderRole.HOST -> hostMedia
        SecurityChannel.MEDIA to SenderRole.DEVICE -> deviceMedia
        else -> error("Unsupported traffic-key direction")
    }

object TrafficPacketCryptography {
    fun seal(
        plaintext: ByteArray,
        key: ByteArray,
        nonce: ByteArray,
        authenticatedHeader: ByteArray,
    ): ByteArray = cipher(Cipher.ENCRYPT_MODE, key, nonce, authenticatedHeader).doFinal(plaintext)

    fun open(
        ciphertextAndTag: ByteArray,
        key: ByteArray,
        nonce: ByteArray,
        authenticatedHeader: ByteArray,
    ): ByteArray {
        require(ciphertextAndTag.size >= GCM_TAG_BYTES) { "AES-256-GCM ciphertext is missing its tag" }
        return cipher(Cipher.DECRYPT_MODE, key, nonce, authenticatedHeader).doFinal(ciphertextAndTag)
    }

    private fun cipher(
        mode: Int,
        key: ByteArray,
        nonce: ByteArray,
        authenticatedHeader: ByteArray,
    ): Cipher {
        require(key.size == 32 && nonce.size == 12) { "AES-256-GCM requires a 32-byte key and 12-byte nonce" }
        return Cipher
            .getInstance("AES/GCM/NoPadding")
            .apply {
                init(mode, SecretKeySpec(key, "AES"), GCMParameterSpec(GCM_TAG_BITS, nonce))
                updateAAD(authenticatedHeader)
            }
    }

    private const val GCM_TAG_BITS = 128
    private const val GCM_TAG_BYTES = GCM_TAG_BITS / Byte.SIZE_BITS
}

object TrafficKeyDerivation {
    private const val MATERIAL_BYTES = 128
    private const val ROTATION_DOMAIN = "vibescreen/traffic-key-update/v1"

    fun initial(
        sharedSecret: ByteArray,
        bootstrapSecret: ByteArray,
        context: ByteArray,
    ): SessionTrafficKeys {
        require(sharedSecret.isNotEmpty() && bootstrapSecret.size == 32 && context.size == 32) {
            "Initial key derivation requires a shared secret, 32-byte bootstrap secret, and 32-byte transcript context"
        }
        return split(hkdf(sharedSecret, bootstrapSecret, context), context, 1)
    }

    fun rotate(
        current: SessionTrafficKeys,
        nextEpoch: Long,
        updateNonce: ByteArray,
    ): SessionTrafficKeys {
        require(
            current.keyEpoch in 1 until Long.MAX_VALUE &&
                nextEpoch == current.keyEpoch + 1 &&
                current.keyId.isNotEmpty() &&
                updateNonce.size >= 16,
        ) { "Traffic-key rotation must advance exactly one epoch and use at least 16 nonce bytes" }
        val context =
            SecurityTranscript.digest(
                ROTATION_DOMAIN,
                current.keyId.toByteArray(Charsets.UTF_8),
                SecurityTranscript.uint64(current.keyEpoch),
                SecurityTranscript.uint64(nextEpoch),
                updateNonce,
            )
        return split(hkdf(current.combined(), updateNonce, context), context, nextEpoch)
    }

    private fun hkdf(
        input: ByteArray,
        salt: ByteArray,
        info: ByteArray,
    ): ByteArray {
        val extract = Mac.getInstance(HMAC_SHA256)
        extract.init(SecretKeySpec(salt, HMAC_SHA256))
        val pseudorandomKey = extract.doFinal(input)
        val output = ByteArrayOutputStream(MATERIAL_BYTES)
        var previous = byteArrayOf()
        var counter = 1
        while (output.size() < MATERIAL_BYTES) {
            val expand = Mac.getInstance(HMAC_SHA256)
            expand.init(SecretKeySpec(pseudorandomKey, HMAC_SHA256))
            expand.update(previous)
            expand.update(info)
            expand.update(counter.toByte())
            previous = expand.doFinal()
            output.write(previous)
            counter += 1
        }
        pseudorandomKey.fill(0)
        return output.toByteArray().copyOf(MATERIAL_BYTES)
    }

    private fun split(
        material: ByteArray,
        context: ByteArray,
        epoch: Long,
    ): SessionTrafficKeys {
        val firstDigest = sha256(context + material)
        val keyId = sha256(firstDigest).toHex()
        firstDigest.fill(0)
        return SessionTrafficKeys(
            keyId = keyId,
            keyEpoch = epoch,
            hostControl = material.copyOfRange(0, 32),
            deviceControl = material.copyOfRange(32, 64),
            hostMedia = material.copyOfRange(64, 96),
            deviceMedia = material.copyOfRange(96, 128),
        ).also { material.fill(0) }
    }

    private fun sha256(value: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(value)

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

    private const val HMAC_SHA256 = "HmacSHA256"
}

internal object SecurityTranscript {
    private const val IDENTITY_DOMAIN = "vibescreen/identity/v1"

    fun digest(
        domain: String,
        vararg parts: ByteArray,
    ): ByteArray {
        val bytes = ByteArrayOutputStream()
        listOf(IDENTITY_DOMAIN.toByteArray(), domain.toByteArray(), *parts).forEach { part ->
            bytes.write(uint64(part.size.toLong()))
            bytes.write(part)
        }
        return MessageDigest.getInstance("SHA-256").digest(bytes.toByteArray())
    }

    fun uint64(value: Long): ByteArray = ByteBuffer.allocate(Long.SIZE_BYTES).putLong(value).array()
}
