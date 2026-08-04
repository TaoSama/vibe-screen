package dev.telemachus.display.internet

/** ICE server configuration consumed by a concrete WebRTC peer implementation. */
data class IceServer(
    val urls: List<String>,
    val username: String? = null,
    val credential: String? = null,
) {
    init {
        require(urls.isNotEmpty()) { "At least one ICE server URL is required" }
        require(urls.all { it.startsWith("stun:") || it.startsWith("stuns:") || it.startsWith("turn:") || it.startsWith("turns:") }) {
            "ICE URLs must use stun, stuns, turn, or turns"
        }
        if (urls.any { it.startsWith("turn:") || it.startsWith("turns:") }) {
            require(!username.isNullOrBlank() && !credential.isNullOrBlank()) {
                "TURN servers require username and credential"
            }
        }
    }

    override fun toString(): String = "IceServer(urls=$urls, username=<redacted>, credential=<redacted>)"
}

data class PeerConfiguration(
    val iceServers: List<IceServer>,
    val sessionId: String,
    val sessionEpoch: Long,
    val signaling: SignalingConfiguration? = null,
    val sessionCipher: SessionPacketCipher? = null,
    val iceTransportPolicy: IceTransportPolicy = IceTransportPolicy.ALL,
) {
    init {
        require(iceServers.isNotEmpty()) { "At least one STUN or TURN server is required" }
        require(sessionId.isNotBlank()) { "Session ID must not be blank" }
        require(sessionEpoch > 0) { "Session epoch must be positive" }
        require(
            iceTransportPolicy != IceTransportPolicy.RELAY_ONLY ||
                iceServers.any { server -> server.urls.any { it.startsWith("turn:") || it.startsWith("turns:") } },
        ) { "Relay-only policy requires a TURN server" }
    }

    override fun toString(): String =
        "PeerConfiguration(iceServers=$iceServers, sessionId=$sessionId, sessionEpoch=$sessionEpoch, " +
            "signaling=$signaling, iceTransportPolicy=$iceTransportPolicy, sessionCipher=<redacted>)"
}

/** ALL prefers a direct candidate pair and permits TURN fallback; RELAY_ONLY is an explicit diagnostic policy. */
enum class IceTransportPolicy {
    ALL,
    RELAY_ONLY,
}

enum class SessionChannel {
    CONTROL,
    MEDIA,
}

/** End-to-end record protection above WebRTC; TURN only observes DTLS ciphertext. */
interface SessionPacketCipher : AutoCloseable {
    val sessionEpoch: Long

    fun seal(
        channel: SessionChannel,
        payload: ByteArray,
    ): ByteArray

    /** Returns null for malformed, unauthenticated, stale, or replayed records. */
    fun open(
        channel: SessionChannel,
        record: ByteArray,
    ): ByteArray?

    fun rotateTrafficKeys(updateNonce: ByteArray)
}

enum class PeerRole {
    HOST,
    DEVICE,
}

/** Short-lived signaling session credentials issued by the rendezvous service. */
class SignalingConfiguration(
    val baseUrl: String,
    val bearerToken: String,
    val role: PeerRole,
    val pollWaitSeconds: Int = 20,
    val allowInsecureForTesting: Boolean = false,
    val supportsInSessionRenegotiation: Boolean = false,
) {
    init {
        val url = java.net.URI(baseUrl)
        require(url.scheme == "https" || (url.scheme == "http" && allowInsecureForTesting)) {
            "Signaling requires HTTPS; HTTP is allowed only by an explicit test configuration"
        }
        require(!url.host.isNullOrBlank()) { "Signaling URL must include a host" }
        require(url.rawQuery == null && url.rawFragment == null) {
            "Signaling base URL must not include a query or fragment"
        }
        require(bearerToken.length >= 32) { "Signaling bearer token is invalid" }
        require(pollWaitSeconds in 0..60) { "Signaling poll wait must be between 0 and 60 seconds" }
    }

    override fun toString(): String =
        "SignalingConfiguration(baseUrl=$baseUrl, bearerToken=<redacted>, role=$role, " +
            "pollWaitSeconds=$pollWaitSeconds, allowInsecureForTesting=$allowInsecureForTesting, " +
            "supportsInSessionRenegotiation=$supportsInSessionRenegotiation)"
}

/** Documents the required WebRTC data-channel behavior without depending on an SDK. */
data class DataChannelSemantics(
    val ordered: Boolean,
    val maxRetransmits: Int?,
) {
    companion object {
        val RELIABLE_CONTROL = DataChannelSemantics(ordered = true, maxRetransmits = null)
        val LATEST_MEDIA = DataChannelSemantics(ordered = false, maxRetransmits = 0)
    }
}

enum class PeerRoute {
    DIRECT,
    RELAY,
}

data class WebRtcStats(
    val availableBitrateKbps: Int,
    val packetLossPercent: Double,
    val roundTripTimeMs: Int,
    val jitterMs: Int,
)

data class VideoProfile(
    val width: Int,
    val height: Int,
    val framesPerSecond: Int,
    val bitrateKbps: Int,
)

interface WebRtcPeerEngine : AutoCloseable {
    interface Observer {
        fun onConnected(route: PeerRoute)

        fun onDisconnected()

        fun onControlMessage(
            sessionEpoch: Long,
            payload: ByteArray,
        )

        fun onMediaPacket(
            sessionEpoch: Long,
            payload: ByteArray,
        )

        fun onStats(stats: WebRtcStats)

        fun onFailure(error: Throwable) = Unit
    }

    val controlSemantics: DataChannelSemantics
    val mediaSemantics: DataChannelSemantics

    fun start(
        configuration: PeerConfiguration,
        observer: Observer,
    )

    fun sendControl(payload: ByteArray): Boolean

    /** Must prefer a current decodable packet over retaining stale media backlog. */
    fun sendMedia(payload: ByteArray): Boolean

    fun restartIce()

    fun applyVideoProfile(profile: VideoProfile)
}

data class NetworkSnapshot(
    val id: String,
    val validated: Boolean,
    val metered: Boolean,
    val transports: Set<NetworkTransport>,
)

enum class NetworkTransport {
    WIFI,
    CELLULAR,
    ETHERNET,
    VPN,
    OTHER,
}

interface NetworkMonitor : AutoCloseable {
    interface Listener {
        fun onAvailable(network: NetworkSnapshot)

        fun onLost(networkId: String)
    }

    fun start(listener: Listener)
}

fun interface MonotonicClock {
    fun nowMillis(): Long
}

enum class InternetTransportState {
    IDLE,
    CONNECTING,
    CONNECTED_DIRECT,
    CONNECTED_RELAY,
    RECOVERING,
    SUSPENDED,
    CLOSED,
}

sealed class InternetTransportEvent {
    data class StateChanged(val state: InternetTransportState) : InternetTransportEvent()

    data class RouteSelected(val route: PeerRoute) : InternetTransportEvent()

    /** The current rendezvous is single-use; recovery must allocate a new signaling/product session. */
    data class FreshSessionRequested(val reason: String) : InternetTransportEvent()

    data class VideoProfileChanged(val profile: VideoProfile) : InternetTransportEvent()

    data class Failure(val error: Throwable) : InternetTransportEvent()
}
