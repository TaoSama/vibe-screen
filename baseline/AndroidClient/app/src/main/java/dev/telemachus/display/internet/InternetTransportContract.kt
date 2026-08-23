package dev.telemachus.display.internet

/** ICE server configuration consumed by a concrete WebRTC peer implementation. */
class DestroyableUtf8 private constructor(
    private val value: ByteArray,
) : AutoCloseable {
    private var destroyed = false

    @Synchronized
    internal fun <T> withString(block: (String) -> T): T {
        check(!destroyed) { "Secret has been destroyed" }
        // Android, HttpURLConnection, and libwebrtc accept only String credentials. The
        // transient String created here cannot be proven erasable if those APIs copy it.
        return block(value.toString(Charsets.UTF_8))
    }

    @Synchronized
    internal fun <T> withBytes(block: (ByteArray) -> T): T {
        check(!destroyed) { "Secret has been destroyed" }
        return block(value)
    }

    @Synchronized
    internal fun copy(): DestroyableUtf8 {
        check(!destroyed) { "Secret has been destroyed" }
        return DestroyableUtf8(value.copyOf())
    }

    @Synchronized
    internal fun byteLength(): Int {
        check(!destroyed) { "Secret has been destroyed" }
        return value.size
    }

    @Synchronized
    internal fun isBlank(): Boolean {
        check(!destroyed) { "Secret has been destroyed" }
        return value.isEmpty() || value.all { it.toInt().toChar().isWhitespace() }
    }

    @Synchronized
    internal fun isDestroyedForTest(): Boolean = destroyed && value.all { it == 0.toByte() }

    @Synchronized
    override fun close() {
        if (destroyed) return
        value.fill(0)
        destroyed = true
    }

    override fun toString(): String = "DestroyableUtf8(<redacted>)"

    companion object {
        internal fun fromString(value: String): DestroyableUtf8 = DestroyableUtf8(value.toByteArray(Charsets.UTF_8))

        internal fun fromBytes(value: ByteArray): DestroyableUtf8 = DestroyableUtf8(value.copyOf())
    }
}

class IceServer internal constructor(
    val urls: List<String>,
    internal val usernameSecret: DestroyableUtf8?,
    internal val credentialSecret: DestroyableUtf8?,
) : AutoCloseable {
    constructor(urls: List<String>, username: String? = null, credential: String? = null) :
        this(urls, username?.let(DestroyableUtf8::fromString), credential?.let(DestroyableUtf8::fromString))

    init {
        try {
            require(urls.isNotEmpty()) { "At least one ICE server URL is required" }
            require(urls.all { it.startsWith("stun:") || it.startsWith("stuns:") || it.startsWith("turn:") || it.startsWith("turns:") }) {
                "ICE URLs must use stun, stuns, turn, or turns"
            }
            if (urls.any { it.startsWith("turn:") || it.startsWith("turns:") }) {
                require(usernameSecret != null && !usernameSecret.isBlank() && credentialSecret != null && !credentialSecret.isBlank()) {
                    "TURN servers require username and credential"
                }
            }
        } catch (failure: Throwable) {
            usernameSecret?.close()
            credentialSecret?.close()
            throw failure
        }
    }

    override fun toString(): String = "IceServer(urls=$urls, username=<redacted>, credential=<redacted>)"

    override fun close() {
        usernameSecret?.close()
        credentialSecret?.close()
    }
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
    AUDIO,
    BULK,
}

enum class WebRtcDataChannelKind(
    val label: String,
    val sessionChannel: SessionChannel,
    val semantics: DataChannelSemantics,
    val maximumEncryptedRecordBytes: Int,
) {
    CONTROL(
        label = "vibescreen.control.v1",
        sessionChannel = SessionChannel.CONTROL,
        semantics = DataChannelSemantics.RELIABLE_CONTROL,
        maximumEncryptedRecordBytes = InternetControlRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES,
    ),
    MEDIA(
        label = "vibescreen.media.v1",
        sessionChannel = SessionChannel.MEDIA,
        semantics = DataChannelSemantics.LATEST_MEDIA,
        maximumEncryptedRecordBytes = InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES,
    ),
    AUDIO(
        label = "vibescreen.audio.v1",
        sessionChannel = SessionChannel.AUDIO,
        semantics = DataChannelSemantics.LATEST_AUDIO,
        maximumEncryptedRecordBytes = InternetAudioRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES,
    ),
    BULK(
        label = "vibescreen.bulk.v1",
        sessionChannel = SessionChannel.BULK,
        semantics = DataChannelSemantics.RELIABLE_BULK,
        maximumEncryptedRecordBytes = InternetBulkRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES,
    );

    val ordered: Boolean = semantics.ordered
    val maxRetransmits: Int? = semantics.maxRetransmits

    companion object {
        fun fromLabel(label: String): WebRtcDataChannelKind? = entries.firstOrNull { it.label == label }
    }
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
class SignalingConfiguration internal constructor(
    val baseUrl: String,
    internal val bearerTokenSecret: DestroyableUtf8,
    val role: PeerRole,
    val pollWaitSeconds: Int = 20,
    val allowInsecureForTesting: Boolean = false,
    val supportsInSessionRenegotiation: Boolean = false,
) : AutoCloseable {
    constructor(
        baseUrl: String,
        bearerToken: String,
        role: PeerRole,
        pollWaitSeconds: Int = 20,
        allowInsecureForTesting: Boolean = false,
        supportsInSessionRenegotiation: Boolean = false,
    ) : this(
        baseUrl,
        DestroyableUtf8.fromString(bearerToken),
        role,
        pollWaitSeconds,
        allowInsecureForTesting,
        supportsInSessionRenegotiation,
    )

    init {
        try {
            val url = java.net.URI(baseUrl)
            require(url.scheme == "https" || (url.scheme == "http" && allowInsecureForTesting)) {
                "Signaling requires HTTPS; HTTP is allowed only by an explicit test configuration"
            }
            require(!url.host.isNullOrBlank()) { "Signaling URL must include a host" }
            require(url.rawQuery == null && url.rawFragment == null) {
                "Signaling base URL must not include a query or fragment"
            }
            require(bearerTokenSecret.byteLength() >= 32) { "Signaling bearer token is invalid" }
            require(pollWaitSeconds in 0..60) { "Signaling poll wait must be between 0 and 60 seconds" }
        } catch (failure: Throwable) {
            bearerTokenSecret.close()
            throw failure
        }
    }

    override fun toString(): String =
        "SignalingConfiguration(baseUrl=$baseUrl, bearerToken=<redacted>, role=$role, " +
            "pollWaitSeconds=$pollWaitSeconds, allowInsecureForTesting=$allowInsecureForTesting, " +
            "supportsInSessionRenegotiation=$supportsInSessionRenegotiation)"

    override fun close() = bearerTokenSecret.close()
}

/** Documents the required WebRTC data-channel behavior without depending on an SDK. */
data class DataChannelSemantics(
    val ordered: Boolean,
    val maxRetransmits: Int?,
) {
    companion object {
        val RELIABLE_CONTROL = DataChannelSemantics(ordered = true, maxRetransmits = null)
        val LATEST_MEDIA = DataChannelSemantics(ordered = false, maxRetransmits = 0)
        val LATEST_AUDIO = DataChannelSemantics(ordered = false, maxRetransmits = 0)
        val RELIABLE_BULK = DataChannelSemantics(ordered = true, maxRetransmits = null)
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

/** One encoded frame represented by complete Protocol v1 media records. */
class OutboundMediaFrame(records: List<ByteArray>) {
    internal val records: List<ByteArray> = records.map(ByteArray::copyOf)

    init {
        require(records.isNotEmpty()) { "Outbound media frame must contain at least one record" }
        require(records.size <= InternetMediaRecordContract.MAXIMUM_FRAGMENTS_PER_FRAME) {
            "Outbound media frame has too many records"
        }
        require(
            records.all {
                it.isNotEmpty() && it.size <= InternetMediaRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES
            },
        ) { "Outbound media frame contains an invalid record" }
        val maximumBatchBytes =
            InternetMediaRecordContract.MAXIMUM_FRAME_BYTES.toLong() +
                records.size.toLong() *
                (InternetMediaRecordContract.MAXIMUM_MEDIA_HEADER_BYTES +
                    InternetMediaRecordContract.MAXIMUM_HEADER_LENGTH_VARINT_BYTES)
        require(records.sumOf { it.size.toLong() } <= maximumBatchBytes) {
            "Outbound media frame exceeds the bounded record batch limit"
        }
    }

    companion object {
        fun single(record: ByteArray): OutboundMediaFrame = OutboundMediaFrame(listOf(record))
    }
}

interface WebRtcPeerEngine : AutoCloseable {
    interface Observer {
        fun onConnected(route: PeerRoute)

        /** Selected candidate pair changed after this session was already connected. */
        fun onRouteChanged(route: PeerRoute) = Unit

        fun onDisconnected()

        fun onConnectionFailed(reason: String) = onDisconnected()

        fun onControlMessage(
            sessionEpoch: Long,
            payload: ByteArray,
        )

        fun onMediaPacket(
            sessionEpoch: Long,
            payload: ByteArray,
        )

        fun onAudioRecord(
            sessionEpoch: Long,
            payload: ByteArray,
        ) = Unit

        fun onBulkRecord(
            sessionEpoch: Long,
            payload: ByteArray,
        ) = Unit

        fun onStats(stats: WebRtcStats)

        fun onFailure(error: Throwable) = Unit
    }

    val controlSemantics: DataChannelSemantics
    val mediaSemantics: DataChannelSemantics
    val dataChannelSemantics: Map<WebRtcDataChannelKind, DataChannelSemantics>
        get() =
            mapOf(
                WebRtcDataChannelKind.CONTROL to controlSemantics,
                WebRtcDataChannelKind.MEDIA to mediaSemantics,
                WebRtcDataChannelKind.AUDIO to DataChannelSemantics.LATEST_AUDIO,
                WebRtcDataChannelKind.BULK to DataChannelSemantics.RELIABLE_BULK,
            )

    fun start(
        configuration: PeerConfiguration,
        observer: Observer,
    )

    fun sendControl(payload: ByteArray): Boolean

    /** Must finish a started frame batch before switching to the newest pending frame. */
    fun sendMedia(frame: OutboundMediaFrame): Boolean

    /** Raw audio transport record only; this does not imply audio capture or playback. */
    fun sendAudioRecord(payload: ByteArray): Boolean = false

    /** Raw bulk transport record only; this does not imply clipboard or file-transfer support. */
    fun sendBulkRecord(payload: ByteArray): Boolean = false

    fun restartIce(): WebRtcIceRestartResult

    fun applyVideoProfile(profile: VideoProfile)
}

sealed class WebRtcIceRestartResult {
    data object Started : WebRtcIceRestartResult()

    data class RequiresFreshSession(val reason: String) : WebRtcIceRestartResult()

    data class Failed(val reason: String) : WebRtcIceRestartResult()
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

    /** Route telemetry changed without creating a new transport or product negotiation. */
    data class RouteUpdated(val route: PeerRoute) : InternetTransportEvent()

    /** The current rendezvous is single-use; recovery must allocate a new signaling/product session. */
    data class FreshSessionRequested(val reason: String) : InternetTransportEvent()

    data class VideoProfileChanged(val profile: VideoProfile) : InternetTransportEvent()

    data class Failure(val error: Throwable) : InternetTransportEvent()
}
