package dev.telemachus.display.internet.security

import dev.telemachus.display.internet.PeerRole
import dev.telemachus.display.internet.SessionChannel
import dev.telemachus.display.internet.SessionPacketCipher
import java.nio.ByteBuffer
import java.security.GeneralSecurityException
import java.security.MessageDigest

/** Protocol v1 AES-GCM record layer backed by durable Android nonce allocation. */
class AndroidSessionPacketCipher internal constructor(
    sessionId: String,
    override val sessionEpoch: Long,
    private val localRole: PeerRole,
    initialKeys: SessionTrafficKeys,
    private val sealWithActiveEpoch: (
        sessionEpoch: Long,
        channel: Int,
        sender: Int,
        keyEpoch: Long,
        operation: (ByteArray) -> ByteArray,
    ) -> ByteArray,
    private val openWithActiveEpoch: (sessionEpoch: Long, operation: () -> ByteArray?) -> ByteArray?,
    private val rotateKeys: (current: SessionTrafficKeys, updateNonce: ByteArray) -> SessionTrafficKeys,
) : SessionPacketCipher {
    constructor(
        sessionId: String,
        sessionEpoch: Long,
        pairingIdentifier: String,
        identityEpoch: Long,
        localRole: PeerRole,
        platformSecurity: AndroidSessionSecurity,
        initialKeys: SessionTrafficKeys,
    ) : this(
        sessionId,
        sessionEpoch,
        localRole,
        initialKeys,
        { epoch, channel, sender, keyEpoch, operation ->
            platformSecurity.withReservedSessionNonce(
                pairingIdentifier,
                identityEpoch,
                epoch,
                channel,
                sender,
                keyEpoch,
                operation,
            )
        },
        { epoch, operation ->
            platformSecurity.withActiveSessionEpoch(
                pairingIdentifier,
                identityEpoch,
                epoch,
                operation,
            )
        },
        platformSecurity::rotateTrafficKeys,
    )

    private val lock = Any()
    private val sessionIdHash =
        MessageDigest.getInstance("SHA-256").digest(sessionId.toByteArray(Charsets.UTF_8)).copyOf(SESSION_ID_HASH_BYTES)
    private var trafficKeys: SessionTrafficKeys? = initialKeys
    private var replayWindows = mutableMapOf<SessionChannel, ReplayWindow>()

    init {
        require(sessionId.isNotBlank()) { "Session ID must not be blank" }
        require(sessionEpoch > 0) { "Session epoch must be positive" }
        require(initialKeys.keyEpoch > 0) { "Traffic key epoch must be positive" }
    }

    override fun seal(
        channel: SessionChannel,
        payload: ByteArray,
    ): ByteArray =
        synchronized(lock) {
            val keys = checkNotNull(trafficKeys) { "Session packet cipher is closed" }
            val securityChannel = channel.toSecurityChannel()
            val sender = localRole.toSenderRole()
            sealWithActiveEpoch(sessionEpoch, securityChannel.wireValue, sender.wireValue, keys.keyEpoch) { nonce ->
                check(nonce.size == NONCE_BYTES) { "Durable nonce allocator returned an invalid nonce" }
                check(ByteBuffer.wrap(nonce).int == securityChannel.wireValue) {
                    "Durable nonce allocator returned a nonce for another channel"
                }
                check(ByteBuffer.wrap(nonce, Int.SIZE_BYTES, Long.SIZE_BYTES).long > 0) {
                    "Durable nonce allocator returned a non-positive sequence"
                }
                val header = header(keys.keyEpoch, sender, securityChannel, nonce)
                header + TrafficPacketCryptography.seal(payload, keys.key(securityChannel, sender), nonce, header)
            }
        }

    override fun open(
        channel: SessionChannel,
        record: ByteArray,
    ): ByteArray? =
        synchronized(lock) outer@{
            val keys = trafficKeys ?: return null
            openWithActiveEpoch(sessionEpoch) active@{
                if (record.size < HEADER_BYTES + GCM_TAG_BYTES) return@active null
                val header = record.copyOfRange(0, HEADER_BYTES)
                val decoded = decodeHeader(header) ?: return@active null
                val expectedChannel = channel.toSecurityChannel()
                val expectedSender = localRole.remote().toSenderRole()
                if (
                    !decoded.sessionIdHash.contentEquals(sessionIdHash) ||
                    decoded.sessionEpoch != sessionEpoch ||
                    decoded.keyEpoch != keys.keyEpoch ||
                    decoded.sender != expectedSender ||
                    decoded.channel != expectedChannel ||
                    ByteBuffer.wrap(decoded.nonce).int != expectedChannel.wireValue
                ) {
                    return@active null
                }
                val sequence = ByteBuffer.wrap(decoded.nonce, Int.SIZE_BYTES, Long.SIZE_BYTES).long
                val window = replayWindows.getOrPut(channel) {
                    ReplayWindow(
                        strictlyOrdered = channel == SessionChannel.CONTROL || channel == SessionChannel.BULK,
                    )
                }
                if (!window.canAccept(sequence)) return@active null
                val plaintext =
                    try {
                        TrafficPacketCryptography.open(
                            record.copyOfRange(HEADER_BYTES, record.size),
                            keys.key(expectedChannel, expectedSender),
                            decoded.nonce,
                            header,
                        )
                    } catch (_: GeneralSecurityException) {
                        return@active null
                    } catch (_: IllegalArgumentException) {
                        return@active null
                    }
                window.commit(sequence)
                plaintext
            }
        }

    override fun rotateTrafficKeys(updateNonce: ByteArray) {
        synchronized(lock) {
            val current = checkNotNull(trafficKeys) { "Session packet cipher is closed" }
            val replacement = rotateKeys(current, updateNonce)
            trafficKeys = replacement
            replayWindows = mutableMapOf()
            current.close()
        }
    }

    override fun close() {
        synchronized(lock) {
            trafficKeys?.close()
            trafficKeys = null
            replayWindows.clear()
            sessionIdHash.fill(0)
        }
    }

    private fun header(
        keyEpoch: Long,
        sender: SenderRole,
        channel: SecurityChannel,
        nonce: ByteArray,
    ): ByteArray =
        ByteBuffer
            .allocate(HEADER_BYTES)
            .putInt(MAGIC)
            .put(VERSION)
            .put(sessionIdHash)
            .putLong(sessionEpoch)
            .putLong(keyEpoch)
            .put(sender.wireValue.toByte())
            .put(channel.wireValue.toByte())
            .put(nonce)
            .array()

    private fun decodeHeader(header: ByteArray): Header? {
        val buffer = ByteBuffer.wrap(header)
        if (buffer.int != MAGIC || buffer.get() != VERSION) return null
        val sessionHash = ByteArray(SESSION_ID_HASH_BYTES).also(buffer::get)
        val epoch = buffer.long
        val keyEpoch = buffer.long
        val senderValue = buffer.get().toInt()
        val channelValue = buffer.get().toInt()
        val sender = SenderRole.values().firstOrNull { it.wireValue == senderValue } ?: return null
        val channel = SecurityChannel.values().firstOrNull { it.wireValue == channelValue } ?: return null
        val nonce = ByteArray(NONCE_BYTES).also(buffer::get)
        return Header(sessionHash, epoch, keyEpoch, sender, channel, nonce)
    }

    private data class Header(
        val sessionIdHash: ByteArray,
        val sessionEpoch: Long,
        val keyEpoch: Long,
        val sender: SenderRole,
        val channel: SecurityChannel,
        val nonce: ByteArray,
    )

    private class ReplayWindow(
        private val strictlyOrdered: Boolean,
    ) {
        private var highest = 0L
        private var bitmap = 0L

        fun canAccept(sequence: Long): Boolean {
            if (sequence <= 0) return false
            if (strictlyOrdered) return sequence > highest
            if (sequence > highest) return true
            val distance = highest - sequence
            return distance < Long.SIZE_BITS && bitmap and (1L shl distance.toInt()) == 0L
        }

        fun commit(sequence: Long) {
            check(canAccept(sequence)) { "Replay sequence was committed twice" }
            if (sequence > highest) {
                val shift = sequence - highest
                bitmap = if (shift >= Long.SIZE_BITS) 1L else (bitmap shl shift.toInt()) or 1L
                highest = sequence
            } else {
                bitmap = bitmap or (1L shl (highest - sequence).toInt())
            }
        }
    }

    private fun SessionChannel.toSecurityChannel(): SecurityChannel =
        when (this) {
            SessionChannel.CONTROL -> SecurityChannel.CONTROL
            SessionChannel.MEDIA -> SecurityChannel.MEDIA
            SessionChannel.AUDIO -> SecurityChannel.AUDIO
            SessionChannel.BULK -> SecurityChannel.BULK
        }

    private fun PeerRole.toSenderRole(): SenderRole =
        if (this == PeerRole.HOST) SenderRole.HOST else SenderRole.DEVICE

    private fun PeerRole.remote(): PeerRole = if (this == PeerRole.HOST) PeerRole.DEVICE else PeerRole.HOST

    companion object {
        private const val MAGIC = 0x56534352 // VSCR
        private const val VERSION: Byte = 1
        private const val SESSION_ID_HASH_BYTES = 16
        private const val NONCE_BYTES = 12
        private const val GCM_TAG_BYTES = 16
        private const val HEADER_BYTES = 4 + 1 + SESSION_ID_HASH_BYTES + 8 + 8 + 1 + 1 + NONCE_BYTES
    }
}
