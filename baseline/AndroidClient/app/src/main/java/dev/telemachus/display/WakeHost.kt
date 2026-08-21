package dev.telemachus.display

import com.google.protobuf.ByteString
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

enum class WakeHostRequestFailure {
    INVALID_REQUEST_ID,
    INVALID_MAC_ADDRESS,
    INVALID_SECURE_ON_PASSWORD,
    INVALID_AUTHORIZATION,
    EXPIRED_AUTHORIZATION,
    REPLAYED_REQUEST,
    POLICY_DENIED,
}

internal class WakeHostRequestException(
    val failure: WakeHostRequestFailure,
) : IllegalArgumentException(failure.name)

enum class WakeHostPacketSenderFailure {
    INVALID_BROADCAST_ADDRESS,
    INVALID_PORT,
}

internal class WakeHostPacketSenderException(
    val failure: WakeHostPacketSenderFailure,
) : IllegalArgumentException(failure.name)

data class WakeHostRequestContext(
    val requestId: ByteString,
    val targetMacAddress: ByteString,
    val secureOnPassword: ByteString = ByteString.EMPTY,
    val hostId: String = "",
    val deviceId: String = "",
    val keyId: String = "",
    val issuedAtUnixSeconds: Long = 0,
    val expiresAtUnixSeconds: Long = 0,
    val nonce: ByteString = ByteString.EMPTY,
    val signature: ByteString = ByteString.EMPTY,
)

data class WakeHostAuthorizationProof(
    val keyId: String,
    val issuedAtUnixSeconds: Long,
    val expiresAtUnixSeconds: Long,
    val nonce: ByteString,
    val signature: ByteString,
)

interface WakeHostPolicy {
    val wakeAllowed: Boolean

    // This default is only a policy hook. Production allow implementations must
    // validate the full request context, including pairing identity and replay
    // fields, before returning no failure.
    fun authorizationFailure(request: WakeHostRequestContext): WakeHostRequestFailure? =
        if (wakeAllowed) null else WakeHostRequestFailure.POLICY_DENIED

    fun wakeAllowed(request: WakeHostRequestContext): Boolean = authorizationFailure(request) == null

    companion object {
        val DENY: WakeHostPolicy = StaticWakeHostPolicy(false)
    }
}

data class StaticWakeHostPolicy(
    override val wakeAllowed: Boolean,
) : WakeHostPolicy

fun interface WakeHostReplayStore {
    fun consume(
        keyId: String,
        nonce: ByteString,
    ): Boolean
}

class InMemoryWakeHostReplayStore(
    private val maximumEntries: Int = 256,
) : WakeHostReplayStore {
    private val seen = LinkedHashSet<String>()

    @Synchronized
    override fun consume(
        keyId: String,
        nonce: ByteString,
    ): Boolean {
        val key = "$keyId:${nonce.toByteArray().toBase64ForReplayKey()}"
        if (key in seen) return false
        seen += key
        while (seen.size > maximumEntries.coerceAtLeast(1)) {
            val first = seen.iterator().next()
            seen.remove(first)
        }
        return true
    }

    private fun ByteArray.toBase64ForReplayKey(): String = java.util.Base64.getEncoder().encodeToString(this)
}

class SharedSecretWakeHostPolicy(
    private val secret: ByteArray,
    private val replayStore: WakeHostReplayStore = InMemoryWakeHostReplayStore(),
    private val nowUnixSeconds: () -> Long = { System.currentTimeMillis() / 1_000L },
) : WakeHostPolicy {
    override val wakeAllowed: Boolean = secret.isNotEmpty()

    override fun authorizationFailure(request: WakeHostRequestContext): WakeHostRequestFailure? {
        if (!wakeAllowed) return WakeHostRequestFailure.POLICY_DENIED
        if (request.keyId.isBlank() || request.keyId != WakeHostProof.keyId(secret)) return WakeHostRequestFailure.INVALID_AUTHORIZATION
        if (request.nonce.size() < WakeHostProof.MINIMUM_NONCE_BYTES) return WakeHostRequestFailure.INVALID_AUTHORIZATION
        if (request.signature.size() != WakeHostProof.SIGNATURE_BYTES) return WakeHostRequestFailure.INVALID_AUTHORIZATION
        val now = nowUnixSeconds()
        if (request.expiresAtUnixSeconds <= request.issuedAtUnixSeconds) return WakeHostRequestFailure.EXPIRED_AUTHORIZATION
        if (request.expiresAtUnixSeconds - request.issuedAtUnixSeconds > MAX_AUTHORIZATION_LIFETIME_SECONDS) {
            return WakeHostRequestFailure.EXPIRED_AUTHORIZATION
        }
        if (now + ALLOWED_CLOCK_SKEW_SECONDS < request.issuedAtUnixSeconds) return WakeHostRequestFailure.EXPIRED_AUTHORIZATION
        if (request.expiresAtUnixSeconds + ALLOWED_CLOCK_SKEW_SECONDS < now) return WakeHostRequestFailure.EXPIRED_AUTHORIZATION
        val expected = WakeHostProof.signature(request, secret)
        if (!WakeHostProof.constantTimeEquals(request.signature.toByteArray(), expected)) return WakeHostRequestFailure.INVALID_AUTHORIZATION
        if (!replayStore.consume(request.keyId, request.nonce)) return WakeHostRequestFailure.REPLAYED_REQUEST
        return null
    }

    companion object {
        private const val MAX_AUTHORIZATION_LIFETIME_SECONDS = 120L
        private const val ALLOWED_CLOCK_SKEW_SECONDS = 30L
    }
}

fun interface WakeHostPacketSender {
    fun send(packet: ByteArray)
}

class UdpWakeHostPacketSender(
    private val broadcastAddress: String = "255.255.255.255",
    private val port: Int = 9,
) : WakeHostPacketSender {
    private val target = WakeHostBroadcastTarget.parse(broadcastAddress, port)
    private val address: InetAddress = InetAddress.getByName(target.address)

    override fun send(packet: ByteArray) {
        DatagramSocket().use { socket ->
            socket.broadcast = true
            val payload = DatagramPacket(
                packet,
                packet.size,
                address,
                target.port,
            )
            socket.send(payload)
        }
    }
}

internal data class WakeHostBroadcastTarget(
    val address: String,
    val port: Int,
) {
    companion object {
        fun parse(
            address: String,
            port: Int,
        ): WakeHostBroadcastTarget {
            if (port !in 1..65535) {
                throw WakeHostPacketSenderException(WakeHostPacketSenderFailure.INVALID_PORT)
            }
            val octets = address.split('.')
            if (octets.size != 4) {
                throw WakeHostPacketSenderException(WakeHostPacketSenderFailure.INVALID_BROADCAST_ADDRESS)
            }
            val values =
                octets.map { part ->
                    if (part.isBlank() || part.any { it !in '0'..'9' }) {
                        throw WakeHostPacketSenderException(WakeHostPacketSenderFailure.INVALID_BROADCAST_ADDRESS)
                    }
                    part.toIntOrNull()?.takeIf { it in 0..255 }
                        ?: throw WakeHostPacketSenderException(WakeHostPacketSenderFailure.INVALID_BROADCAST_ADDRESS)
                }
            if (values == listOf(0, 0, 0, 0) || values.last() != 255) {
                throw WakeHostPacketSenderException(WakeHostPacketSenderFailure.INVALID_BROADCAST_ADDRESS)
            }
            return WakeHostBroadcastTarget(address, port)
        }
    }
}

object WakeHostProof {
    const val MINIMUM_NONCE_BYTES = 16
    const val SIGNATURE_BYTES = 32
    private val DOMAIN = "VS-WOL-HMAC-v1".toByteArray(Charsets.UTF_8)
    private const val HMAC_SHA256 = "HmacSHA256"

    fun keyId(secret: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(secret).toHex()

    fun signature(
        requestId: ByteString,
        targetMacAddress: ByteString,
        secureOnPassword: ByteString,
        hostId: String,
        deviceId: String,
        keyId: String,
        issuedAtUnixSeconds: Long,
        expiresAtUnixSeconds: Long,
        nonce: ByteString,
        secret: ByteArray,
    ): ByteString =
        ByteString.copyFrom(
            signature(
                WakeHostRequestContext(
                    requestId = requestId,
                    targetMacAddress = targetMacAddress,
                    secureOnPassword = secureOnPassword,
                    hostId = hostId,
                    deviceId = deviceId,
                    keyId = keyId,
                    issuedAtUnixSeconds = issuedAtUnixSeconds,
                    expiresAtUnixSeconds = expiresAtUnixSeconds,
                    nonce = nonce,
                ),
                secret,
            ),
        )

    fun signature(
        request: WakeHostRequestContext,
        secret: ByteArray,
    ): ByteArray {
        val mac = Mac.getInstance(HMAC_SHA256)
        mac.init(SecretKeySpec(secret, HMAC_SHA256))
        return mac.doFinal(canonicalBytes(request))
    }

    fun constantTimeEquals(
        lhs: ByteArray,
        rhs: ByteArray,
    ): Boolean {
        if (lhs.size != rhs.size) return false
        var diff = 0
        lhs.indices.forEach { index -> diff = diff or (lhs[index].toInt() xor rhs[index].toInt()) }
        return diff == 0
    }

    private fun canonicalBytes(request: WakeHostRequestContext): ByteArray {
        val fields =
            listOf(
                ByteString.copyFrom(DOMAIN),
                request.requestId,
                request.targetMacAddress,
                request.secureOnPassword,
                ByteString.copyFrom(request.hostId.toByteArray(Charsets.UTF_8)),
                ByteString.copyFrom(request.deviceId.toByteArray(Charsets.UTF_8)),
                ByteString.copyFrom(request.keyId.toByteArray(Charsets.UTF_8)),
            )
        val size = fields.sumOf { Int.SIZE_BYTES + it.size() } + Long.SIZE_BYTES + Long.SIZE_BYTES + Int.SIZE_BYTES + request.nonce.size()
        val buffer = ByteBuffer.allocate(size).order(ByteOrder.BIG_ENDIAN)
        fields.forEach { field ->
            buffer.putInt(field.size())
            buffer.put(field.toByteArray())
        }
        buffer.putLong(request.issuedAtUnixSeconds)
        buffer.putLong(request.expiresAtUnixSeconds)
        buffer.putInt(request.nonce.size())
        buffer.put(request.nonce.toByteArray())
        return buffer.array()
    }
}

internal object WakeHostMagicPacket {
    const val MAC_ADDRESS_BYTES = 6
    const val SECURE_ON_PASSWORD_BYTES = 6
    const val BASE_PACKET_BYTES = 102

    fun build(
        targetMacAddress: ByteString,
        secureOnPassword: ByteString = ByteString.EMPTY,
    ): ByteArray {
        val mac = targetMacAddress.toByteArray()
        if (mac.size != MAC_ADDRESS_BYTES || mac.all { it == 0.toByte() } || mac.all { it == 0xff.toByte() }) {
            throw WakeHostRequestException(WakeHostRequestFailure.INVALID_MAC_ADDRESS)
        }
        val password = secureOnPassword.toByteArray()
        if (password.isNotEmpty() && password.size != SECURE_ON_PASSWORD_BYTES) {
            throw WakeHostRequestException(WakeHostRequestFailure.INVALID_SECURE_ON_PASSWORD)
        }
        val packet = ByteArray(BASE_PACKET_BYTES + password.size)
        packet.fill(0xff.toByte(), fromIndex = 0, toIndex = 6)
        var offset = 6
        repeat(16) {
            mac.copyInto(packet, destinationOffset = offset)
            offset += mac.size
        }
        password.copyInto(packet, destinationOffset = offset)
        return packet
    }
}

internal object WakeHostDecision {
    fun magicPacket(
        request: WakeHostRequestContext,
        policy: WakeHostPolicy = WakeHostPolicy.DENY,
    ): ByteArray {
        if (request.requestId.isEmpty) {
            throw WakeHostRequestException(WakeHostRequestFailure.INVALID_REQUEST_ID)
        }
        policy.authorizationFailure(request)?.let { throw WakeHostRequestException(it) }
        return WakeHostMagicPacket.build(request.targetMacAddress, request.secureOnPassword)
    }
}

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
