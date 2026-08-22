package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.internet.security.InternetPairingSigner
import dev.telemachus.display.internet.security.SecurityTranscript
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

internal enum class WakeHostRequestFailure {
    INVALID_REQUEST_ID,
    INVALID_MAC_ADDRESS,
    INVALID_SECURE_ON_PASSWORD,
    POLICY_DENIED,
}

internal class WakeHostRequestException(
    val failure: WakeHostRequestFailure,
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
    val sessionId: ByteString = ByteString.EMPTY,
    val sessionEpoch: Long = 0,
)

data class WakeHostProof(
    val deviceId: String,
    val keyId: String,
    val issuedAtUnixSeconds: Long,
    val expiresAtUnixSeconds: Long,
    val nonce: ByteString,
    val signature: ByteString,
)

object WakeHostProofFactory {
    const val NONCE_BYTES = 16
    const val MAXIMUM_LIFETIME_SECONDS = 300L

    fun create(
        signer: InternetPairingSigner,
        requestId: ByteString,
        targetMacAddress: ByteString,
        secureOnPassword: ByteString,
        hostId: String,
        issuedAtUnixSeconds: Long,
        expiresAtUnixSeconds: Long,
        nonce: ByteString,
        sessionId: ByteString,
        sessionEpoch: Long,
    ): WakeHostProof {
        val identity = signer.publicIdentity
        require(requestId.size() > 0) { "Wake host request id is required" }
        require(hostId.isNotBlank()) { "Wake host target host id is required" }
        require(identity.deviceId.isNotBlank() && identity.keyId.isNotBlank()) { "Paired device identity is required" }
        require(nonce.size() >= NONCE_BYTES && nonce.toByteArray().any { it != 0.toByte() }) {
            "Wake host nonce requires at least $NONCE_BYTES non-zero-capable bytes"
        }
        require(sessionId.size() > 0 && sessionEpoch > 0) { "Wake host proof requires an active session" }
        require(issuedAtUnixSeconds > 0 && expiresAtUnixSeconds > issuedAtUnixSeconds) {
            "Wake host proof requires a bounded validity window"
        }
        require(expiresAtUnixSeconds - issuedAtUnixSeconds <= MAXIMUM_LIFETIME_SECONDS) {
            "Wake host proof validity exceeds $MAXIMUM_LIFETIME_SECONDS seconds"
        }
        val digest = proofDigest(
            requestId = requestId,
            targetMacAddress = targetMacAddress,
            secureOnPassword = secureOnPassword,
            hostId = hostId,
            deviceId = identity.deviceId,
            keyId = identity.keyId,
            issuedAtUnixSeconds = issuedAtUnixSeconds,
            expiresAtUnixSeconds = expiresAtUnixSeconds,
            nonce = nonce,
            sessionId = sessionId,
            sessionEpoch = sessionEpoch,
        )
        return WakeHostProof(
            deviceId = identity.deviceId,
            keyId = identity.keyId,
            issuedAtUnixSeconds = issuedAtUnixSeconds,
            expiresAtUnixSeconds = expiresAtUnixSeconds,
            nonce = nonce,
            signature = ByteString.copyFrom(signer.signTranscriptDigest(digest)),
        )
    }

    fun proofDigest(
        requestId: ByteString,
        targetMacAddress: ByteString,
        secureOnPassword: ByteString,
        hostId: String,
        deviceId: String,
        keyId: String,
        issuedAtUnixSeconds: Long,
        expiresAtUnixSeconds: Long,
        nonce: ByteString,
        sessionId: ByteString,
        sessionEpoch: Long,
    ): ByteArray =
        SecurityTranscript.digest(
            "vibescreen/wake-host-request/v1",
            requestId.toByteArray(),
            targetMacAddress.toByteArray(),
            secureOnPassword.toByteArray(),
            hostId.toByteArray(Charsets.UTF_8),
            deviceId.toByteArray(Charsets.UTF_8),
            keyId.toByteArray(Charsets.UTF_8),
            SecurityTranscript.uint64(issuedAtUnixSeconds),
            SecurityTranscript.uint64(expiresAtUnixSeconds),
            nonce.toByteArray(),
            sessionId.toByteArray(),
            SecurityTranscript.uint64(sessionEpoch),
        )
}

interface WakeHostPolicy {
    val wakeAllowed: Boolean

    // This default is only a policy hook. Production allow implementations must
    // validate the full request context, including pairing identity and replay
    // fields, before returning true.
    fun wakeAllowed(request: WakeHostRequestContext): Boolean = wakeAllowed

    companion object {
        val DENY: WakeHostPolicy = StaticWakeHostPolicy(false)
    }
}

data class StaticWakeHostPolicy(
    override val wakeAllowed: Boolean,
) : WakeHostPolicy

fun interface WakeHostPacketSender {
    fun send(packet: ByteArray)
}

class UdpWakeHostPacketSender(
    private val broadcastAddress: String = "255.255.255.255",
    private val port: Int = 9,
) : WakeHostPacketSender {
    private val address: InetAddress = InetAddress.getByName(broadcastAddress)

    init {
        require(port in 1..65535) { "port must be 1..65535" }
    }

    override fun send(packet: ByteArray) {
        DatagramSocket().use { socket ->
            socket.broadcast = true
            val payload = DatagramPacket(
                packet,
                packet.size,
                address,
                port,
            )
            socket.send(payload)
        }
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
        if (!policy.wakeAllowed(request)) {
            throw WakeHostRequestException(WakeHostRequestFailure.POLICY_DENIED)
        }
        return WakeHostMagicPacket.build(request.targetMacAddress, request.secureOnPassword)
    }
}
