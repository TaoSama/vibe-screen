package dev.telemachus.display

import dev.telemachus.display.internet.PeerRole
import dev.telemachus.display.internet.InternetMediaRecordContract
import dev.telemachus.display.internet.SessionChannel
import dev.telemachus.display.internet.security.AndroidSessionPacketCipher
import dev.telemachus.display.internet.security.SessionTrafficKeys
import dev.telemachus.display.internet.security.TrafficKeyDerivation
import dev.telemachus.display.internet.security.generateEphemeral
import dev.telemachus.display.internet.security.publicPoint
import dev.telemachus.display.internet.security.ecdh
import dev.telemachus.display.internet.security.SecurityTranscript
import java.io.EOFException
import java.io.FilterOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.atomic.AtomicLong

internal enum class LanRecordProtectionState {
    NOT_APPLICABLE,
    NEGOTIATING,
    ENCRYPTED,
    EXPLICIT_LEGACY_FALLBACK,
}

internal class LanSecureRecordException(message: String) : Exception(message)

internal object LanSecureRecordNegotiation {
    private val REQUEST_MAGIC = byteArrayOf(0x56, 0x53, 0x4c, 0x53) // VSLS
    private val RESPONSE_MAGIC = byteArrayOf(0x56, 0x53, 0x4c, 0x52) // VSLR
    private const val VERSION: Byte = 1
    private const val SECURE_RECORDS_REQUIRED: Byte = 1
    private const val LEGACY_FALLBACK_ALLOWED: Byte = (1 shl 1).toByte()
    private const val SECURE_RECORDS_ACCEPTED: Byte = 1
    private const val EXPLICIT_LEGACY_FALLBACK: Byte = (1 shl 1).toByte()
    const val PUBLIC_KEY_BYTES = 65
    const val REQUEST_BYTES = 4 + 1 + 1 + PUBLIC_KEY_BYTES
    const val RESPONSE_BYTES = 4 + 1 + 1 + PUBLIC_KEY_BYTES

    data class Request(
        val publicKey: ByteArray,
        val allowLegacyFallback: Boolean,
    )

    data class Response(
        val publicKey: ByteArray,
        val encrypted: Boolean,
        val legacy: Boolean,
    )

    fun encodeRequest(
        publicKey: ByteArray,
        allowLegacyFallback: Boolean,
    ): ByteArray {
        require(publicKey.size == PUBLIC_KEY_BYTES) { "Trusted LAN secure records require a P-256 public key" }
        val flags =
            (SECURE_RECORDS_REQUIRED.toInt() or if (allowLegacyFallback) LEGACY_FALLBACK_ALLOWED.toInt() else 0).toByte()
        return REQUEST_MAGIC + byteArrayOf(VERSION, flags) + publicKey
    }

    fun decodeRequest(bytes: ByteArray): Request {
        if (bytes.size != REQUEST_BYTES || !bytes.copyOfRange(0, 4).contentEquals(REQUEST_MAGIC) || bytes[4] != VERSION) {
            throw LanSecureRecordException("Invalid trusted LAN secure-record request")
        }
        val flags = bytes[5].toInt()
        if (flags and SECURE_RECORDS_REQUIRED.toInt() == 0) {
            throw LanSecureRecordException("Trusted LAN secure-record request did not require encryption")
        }
        return Request(
            bytes.copyOfRange(6, REQUEST_BYTES),
            flags and LEGACY_FALLBACK_ALLOWED.toInt() != 0,
        )
    }

    fun encodeResponse(
        publicKey: ByteArray,
        encrypted: Boolean,
        explicitLegacyFallback: Boolean,
    ): ByteArray {
        require(publicKey.size == PUBLIC_KEY_BYTES) { "Trusted LAN secure records require a P-256 public key" }
        require(encrypted != explicitLegacyFallback) { "Trusted LAN response must choose encrypted or explicit legacy" }
        val flags = if (encrypted) SECURE_RECORDS_ACCEPTED else EXPLICIT_LEGACY_FALLBACK
        return RESPONSE_MAGIC + byteArrayOf(VERSION, flags) + publicKey
    }

    fun decodeResponse(bytes: ByteArray): Response {
        if (bytes.size != RESPONSE_BYTES || !bytes.copyOfRange(0, 4).contentEquals(RESPONSE_MAGIC) || bytes[4] != VERSION) {
            throw LanSecureRecordException("Invalid trusted LAN secure-record response")
        }
        val flags = bytes[5].toInt()
        val encrypted = flags and SECURE_RECORDS_ACCEPTED.toInt() != 0
        val legacy = flags and EXPLICIT_LEGACY_FALLBACK.toInt() != 0
        if (encrypted == legacy) throw LanSecureRecordException("Trusted LAN response did not choose one protection mode")
        return Response(bytes.copyOfRange(6, RESPONSE_BYTES), encrypted, legacy)
    }
}

internal class LanSecureRecordSession(
    role: PeerRole,
    val sessionId: String,
    sessionEpoch: Long,
    sharedSecret: ByteArray,
    bootstrapToken: ByteArray,
    context: ByteArray,
    nonceStore: LanSecureRecordNonceStore = LanSecureRecordNonceStore(),
) : AutoCloseable {
    private val cipher =
        AndroidSessionPacketCipher(
            sessionId = sessionId,
            sessionEpoch = sessionEpoch,
            localRole = role,
            initialKeys = TrafficKeyDerivation.initial(sharedSecret, bootstrapToken, context),
            sealWithActiveEpoch = { _, channel, sender, keyEpoch, operation ->
                operation(nonceStore.reserve(channel, sender, keyEpoch))
            },
            openWithActiveEpoch = { _, operation -> operation() },
            rotateKeys = { current: SessionTrafficKeys, updateNonce: ByteArray ->
                TrafficKeyDerivation.rotate(current, current.keyEpoch + 1, updateNonce)
            },
        )

    fun seal(
        channel: SessionChannel,
        payload: ByteArray,
    ): ByteArray = cipher.seal(channel, payload)

    fun open(
        channel: SessionChannel,
        record: ByteArray,
    ): ByteArray = cipher.open(channel, record) ?: throw LanSecureRecordException("Trusted LAN record failed authentication")

    fun openDeclaredChannel(record: ByteArray): ByteArray {
        val channel = AndroidSessionPacketCipher.declaredSessionChannel(record)
            ?: throw LanSecureRecordException("Trusted LAN record did not declare a supported channel")
        return open(channel, record)
    }

    override fun close() = cipher.close()

    companion object {
        const val RECORD_SESSION_EPOCH: Long = 1

        fun sessionIdentifier(
            hostPublicKey: ByteArray,
            devicePublicKey: ByteArray,
        ): String =
            MessageDigest.getInstance("SHA-256")
                .digest("vibescreen/trusted-lan-session/v1".toByteArray(Charsets.UTF_8) + hostPublicKey + devicePublicKey)
                .joinToString("") { "%02x".format(it) }

        fun transcriptContext(
            sessionIdentifier: String,
            hostPublicKey: ByteArray,
            devicePublicKey: ByteArray,
        ): ByteArray =
            SecurityTranscript.digest(
                "vibescreen/trusted-lan-records/v1",
                sessionIdentifier.toByteArray(Charsets.UTF_8),
                hostPublicKey,
                devicePublicKey,
            )
    }
}

internal class LanSecureRecordNonceStore {
    private val counters = mutableMapOf<String, AtomicLong>()

    @Synchronized
    fun reserve(
        channel: Int,
        sender: Int,
        keyEpoch: Long,
    ): ByteArray {
        require(channel > 0 && sender > 0 && keyEpoch > 0) { "LAN secure record nonce inputs must be positive" }
        val key = "$channel:$sender:$keyEpoch"
        val sequence = counters.getOrPut(key) { AtomicLong() }.incrementAndGet()
        return ByteBuffer.allocate(12).putInt(channel).putLong(sequence).array()
    }
}

internal class LanSecureRecordInputStream(
    private val raw: InputStream,
    private val session: LanSecureRecordSession,
) : InputStream() {
    private var plaintext = ByteArray(0)
    private var offset = 0

    override fun read(): Int {
        val one = ByteArray(1)
        val count = read(one, 0, 1)
        return if (count < 0) -1 else one[0].toInt() and 0xff
    }

    override fun read(
        b: ByteArray,
        off: Int,
        len: Int,
    ): Int {
        if (len == 0) return 0
        if (offset >= plaintext.size) {
            plaintext = readRecordPlaintext()
            offset = 0
        }
        val count = minOf(len, plaintext.size - offset)
        plaintext.copyInto(b, off, offset, offset + count)
        offset += count
        return count
    }

    private fun readRecordPlaintext(): ByteArray {
        val prefix = raw.readExactly(4)
        val size = ByteBuffer.wrap(prefix).int
        if (size <= 0 || size > MAX_RECORD_BYTES) throw LanSecureRecordException("Invalid trusted LAN record length")
        val record = raw.readExactly(size)
        return session.openDeclaredChannel(record)
    }
}

internal class LanSecureRecordOutputStream(
    raw: OutputStream,
    private val session: LanSecureRecordSession,
    private val channelSelector: () -> SessionChannel = { SessionChannel.CONTROL },
) : FilterOutputStream(raw) {
    override fun write(b: Int) = write(byteArrayOf(b.toByte()), 0, 1)

    override fun write(b: ByteArray) = write(b, 0, b.size)

    override fun write(
        b: ByteArray,
        off: Int,
        len: Int,
    ) {
        val payload = b.copyOfRange(off, off + len)
        val record = session.seal(channelSelector(), payload)
        out.write(ByteBuffer.allocate(4).putInt(record.size).array())
        out.write(record)
    }
}

internal data class LanSecureRecordClientNegotiation(
    val state: LanRecordProtectionState,
    val session: LanSecureRecordSession?,
)

internal fun negotiateLanSecureRecordsAsClient(
    input: InputStream,
    output: OutputStream,
    token: ByteArray,
    random: SecureRandom = SecureRandom(),
): LanSecureRecordClientNegotiation {
    require(token.size == 32) { "Trusted LAN secure records require a 32-byte token" }
    val deviceEphemeral = generateEphemeral(random)
    val devicePublic = publicPoint(deviceEphemeral)
    output.write(LanSecureRecordNegotiation.encodeRequest(devicePublic, allowLegacyFallback = false))
    output.flush()
    val response = LanSecureRecordNegotiation.decodeResponse(input.readExactly(LanSecureRecordNegotiation.RESPONSE_BYTES))
    if (response.legacy) {
        throw LanSecureRecordException("Trusted LAN plaintext fallback was not explicitly allowed")
    }
    val sessionId = LanSecureRecordSession.sessionIdentifier(response.publicKey, devicePublic)
    val context = LanSecureRecordSession.transcriptContext(sessionId, response.publicKey, devicePublic)
    val sharedSecret = ecdh(deviceEphemeral.private, response.publicKey)
    return LanSecureRecordClientNegotiation(
        LanRecordProtectionState.ENCRYPTED,
        LanSecureRecordSession(PeerRole.DEVICE, sessionId, LanSecureRecordSession.RECORD_SESSION_EPOCH, sharedSecret, token, context),
    )
}

internal fun InputStream.readExactly(size: Int): ByteArray {
    val result = ByteArray(size)
    var offset = 0
    while (offset < size) {
        val count = read(result, offset, size - offset)
        if (count < 0) throw EOFException("Stream ended with ${size - offset} bytes missing")
        if (count == 0) continue
        offset += count
    }
    return result
}

private const val MAX_RECORD_BYTES =
    InternetMediaRecordContract.MAXIMUM_FRAME_BYTES +
        InternetMediaRecordContract.APPLICATION_AEAD_RECORD_OVERHEAD_BYTES
