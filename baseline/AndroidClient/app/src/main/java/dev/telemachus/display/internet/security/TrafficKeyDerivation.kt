package dev.telemachus.display.internet.security

import java.nio.ByteBuffer
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

class SessionTrafficKeys(
    val keyId: String,
    val keyEpoch: Long,
    val hostControl: ByteArray,
    val deviceControl: ByteArray,
    val hostMedia: ByteArray,
    val deviceMedia: ByteArray,
    val hostAudio: ByteArray,
    val deviceAudio: ByteArray,
    val hostBulk: ByteArray,
    val deviceBulk: ByteArray,
) : AutoCloseable {
    /** Clears the in-memory copies owned by this instance after disconnect/rotation. */
    override fun close() {
        hostControl.fill(0)
        deviceControl.fill(0)
        hostMedia.fill(0)
        deviceMedia.fill(0)
        hostAudio.fill(0)
        deviceAudio.fill(0)
        hostBulk.fill(0)
        deviceBulk.fill(0)
    }
}

enum class SecurityChannel(val wireValue: Int) {
    CONTROL(1),
    MEDIA(2),
    AUDIO(3),
    BULK(4),
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
        SecurityChannel.AUDIO to SenderRole.HOST -> hostAudio
        SecurityChannel.AUDIO to SenderRole.DEVICE -> deviceAudio
        SecurityChannel.BULK to SenderRole.HOST -> hostBulk
        SecurityChannel.BULK to SenderRole.DEVICE -> deviceBulk
        else -> error("Unsupported traffic key direction")
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
    private const val MATERIAL_BYTES = 256
    private const val ROTATION_DOMAIN = "vibescreen/traffic-key-update/v1"

    fun initial(
        sharedSecret: ByteArray,
        bootstrapSecret: ByteArray,
        context: ByteArray,
    ): SessionTrafficKeys = initial(sharedSecret, bootstrapSecret, context, SensitiveBufferObserver.NONE)

    internal fun initial(
        sharedSecret: ByteArray,
        bootstrapSecret: ByteArray,
        context: ByteArray,
        observer: SensitiveBufferObserver,
    ): SessionTrafficKeys {
        require(sharedSecret.isNotEmpty() && bootstrapSecret.size == 32 && context.size == 32) {
            "Initial key derivation requires a shared secret, 32-byte bootstrap secret, and 32-byte transcript context"
        }
        return split(hkdf(arrayOf(sharedSecret), bootstrapSecret, context, observer), context, 1, observer)
    }

    fun rotate(
        current: SessionTrafficKeys,
        nextEpoch: Long,
        updateNonce: ByteArray,
    ): SessionTrafficKeys = rotate(current, nextEpoch, updateNonce, SensitiveBufferObserver.NONE)

    internal fun rotate(
        current: SessionTrafficKeys,
        nextEpoch: Long,
        updateNonce: ByteArray,
        observer: SensitiveBufferObserver,
    ): SessionTrafficKeys {
        require(
            current.keyEpoch in 1 until Long.MAX_VALUE &&
                nextEpoch == current.keyEpoch + 1 &&
                current.keyId.isNotEmpty() &&
                updateNonce.size >= 16,
        ) { "Traffic-key rotation must advance exactly one epoch and use at least 16 nonce bytes" }
        val context =
            SecurityTranscript.digest(ROTATION_DOMAIN, observer) {
                text(current.keyId)
                uint64(current.keyEpoch)
                uint64(nextEpoch)
                part(updateNonce)
            }
        return try {
            split(
                hkdf(
                    arrayOf(
                        current.hostControl,
                        current.deviceControl,
                        current.hostMedia,
                        current.deviceMedia,
                        current.hostAudio,
                        current.deviceAudio,
                        current.hostBulk,
                        current.deviceBulk,
                    ),
                    updateNonce,
                    context,
                    observer,
                ),
                context,
                nextEpoch,
                observer,
            )
        } finally {
            context.fill(0)
        }
    }

    private fun hkdf(
        inputParts: Array<out ByteArray>,
        salt: ByteArray,
        info: ByteArray,
        observer: SensitiveBufferObserver,
    ): ByteArray {
        val extract = Mac.getInstance(HMAC_SHA256)
        extract.init(SecretKeySpec(salt, HMAC_SHA256))
        inputParts.forEach(extract::update)
        val pseudorandomKey = extract.doFinal()
        var output: ByteArray? = null
        var previous: ByteArray? = null
        var completed = false
        try {
            observer.allocated("hkdf-prk", pseudorandomKey)
            output = ByteArray(MATERIAL_BYTES)
            observer.allocated("hkdf-material", output)
            var offset = 0
            var counter = 1
            while (offset < output.size) {
                val expand = Mac.getInstance(HMAC_SHA256)
                expand.init(SecretKeySpec(pseudorandomKey, HMAC_SHA256))
                previous?.let(expand::update)
                expand.update(info)
                expand.update(counter.toByte())
                val next = expand.doFinal()
                try {
                    observer.allocated("hkdf-block-$counter", next)
                } catch (failure: Throwable) {
                    next.fill(0)
                    throw failure
                }
                previous?.fill(0)
                previous = next
                val copyLength = minOf(next.size, output.size - offset)
                next.copyInto(output, offset, 0, copyLength)
                offset += copyLength
                counter += 1
            }
            completed = true
            return output
        } finally {
            previous?.fill(0)
            pseudorandomKey.fill(0)
            if (!completed) output?.fill(0)
        }
    }

    private fun split(
        material: ByteArray,
        context: ByteArray,
        epoch: Long,
        observer: SensitiveBufferObserver,
    ): SessionTrafficKeys {
        var firstDigest: ByteArray? = null
        var keyIdDigest: ByteArray? = null
        var hostControl: ByteArray? = null
        var deviceControl: ByteArray? = null
        var hostMedia: ByteArray? = null
        var deviceMedia: ByteArray? = null
        var hostAudio: ByteArray? = null
        var deviceAudio: ByteArray? = null
        var hostBulk: ByteArray? = null
        var deviceBulk: ByteArray? = null
        var completed = false
        try {
            val computedFirstDigest = MessageDigest.getInstance("SHA-256").run {
                update(context)
                update(material, 0, 128)
                digest()
            }
            firstDigest = computedFirstDigest
            observer.allocated("key-id-first-digest", computedFirstDigest)
            val computedKeyIdDigest = MessageDigest.getInstance("SHA-256").digest(computedFirstDigest)
            keyIdDigest = computedKeyIdDigest
            observer.allocated("key-id-final-digest", computedKeyIdDigest)
            val keyId = computedKeyIdDigest.toHex()
            hostControl = material.copyOfRange(0, 32)
            deviceControl = material.copyOfRange(32, 64)
            hostMedia = material.copyOfRange(64, 96)
            deviceMedia = material.copyOfRange(96, 128)
            hostAudio = material.copyOfRange(128, 160)
            deviceAudio = material.copyOfRange(160, 192)
            hostBulk = material.copyOfRange(192, 224)
            deviceBulk = material.copyOfRange(224, 256)
            val keys =
                SessionTrafficKeys(
                    keyId = keyId,
                    keyEpoch = epoch,
                    hostControl = hostControl,
                    deviceControl = deviceControl,
                    hostMedia = hostMedia,
                    deviceMedia = deviceMedia,
                    hostAudio = hostAudio,
                    deviceAudio = deviceAudio,
                    hostBulk = hostBulk,
                    deviceBulk = deviceBulk,
                )
            completed = true
            return keys
        } finally {
            firstDigest?.fill(0)
            keyIdDigest?.fill(0)
            material.fill(0)
            if (!completed) {
                hostControl?.fill(0)
                deviceControl?.fill(0)
                hostMedia?.fill(0)
                deviceMedia?.fill(0)
                hostAudio?.fill(0)
                deviceAudio?.fill(0)
                hostBulk?.fill(0)
                deviceBulk?.fill(0)
            }
        }
    }

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

    private const val HMAC_SHA256 = "HmacSHA256"
}

internal object SecurityTranscript {
    private const val IDENTITY_DOMAIN = "vibescreen/identity/v1"

    fun digest(
        domain: String,
        vararg parts: ByteArray,
    ): ByteArray = digest(domain, SensitiveBufferObserver.NONE) { parts.forEach(::part) }

    internal fun digest(
        domain: String,
        observer: SensitiveBufferObserver,
        update: TranscriptDigestUpdater.() -> Unit,
    ): ByteArray {
        val digest = MessageDigest.getInstance("SHA-256")
        val updater = TranscriptDigestUpdater(digest, observer)
        updater.text(IDENTITY_DOMAIN)
        updater.text(domain)
        updater.update()
        return digest.digest()
    }

    fun uint64(value: Long): ByteArray = ByteBuffer.allocate(Long.SIZE_BYTES).putLong(value).array()
}

internal class TranscriptDigestUpdater(
    private val digest: MessageDigest,
    private val observer: SensitiveBufferObserver,
) {
    fun part(value: ByteArray) {
        lengthPrefix(value.size.toLong())
        digest.update(value)
    }

    fun text(value: String) = withOwned("transcript-text", value.toByteArray(Charsets.UTF_8), ::part)

    fun uint64(value: Long) = withOwned("transcript-uint64", SecurityTranscript.uint64(value), ::part)

    fun byte(value: Byte) = withOwned("transcript-byte", byteArrayOf(value), ::part)

    private fun lengthPrefix(value: Long) =
        withOwned("transcript-length", SecurityTranscript.uint64(value)) { digest.update(it) }

    private inline fun withOwned(
        label: String,
        value: ByteArray,
        block: (ByteArray) -> Unit,
    ) {
        try {
            observer.allocated(label, value)
            block(value)
        } finally {
            value.fill(0)
        }
    }
}

internal fun interface SensitiveBufferObserver {
    fun allocated(label: String, buffer: ByteArray)

    companion object {
        val NONE = SensitiveBufferObserver { _, _ -> }
    }
}
