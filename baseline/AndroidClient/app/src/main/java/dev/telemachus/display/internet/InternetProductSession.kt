package dev.telemachus.display.internet

import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import dev.telemachus.display.internet.security.SecurityTranscript
import dev.vibescreen.protocol.v1.Capability
import java.util.concurrent.atomic.AtomicLong

data class InternetProductSessionLease(
    val pairingIdentifier: String,
    val signalingSessionId: String,
    val authoritativeSessionEpoch: Long,
    val identityEpoch: Long,
    val transcriptContext: ByteArray,
    val iceServers: List<IceServer>,
    val signaling: SignalingConfiguration,
    val pinnedHostId: String,
    val iceTransportPolicy: IceTransportPolicy = IceTransportPolicy.ALL,
    val protocolSessionId: ByteArray = signalingSessionId.toByteArray(Charsets.UTF_8),
) {
    init {
        require(pairingIdentifier.isNotBlank() && signalingSessionId.isNotBlank()) { "Session lease identifiers are required" }
        require(authoritativeSessionEpoch in 1 until Long.MAX_VALUE && identityEpoch in 1 until Long.MAX_VALUE) {
            "Session and identity epochs must be positive and below the reserved maximum"
        }
        require(protocolSessionId.isNotEmpty()) { "Protocol session identifier is required" }
        require(pinnedHostId.isNotBlank()) { "Pinned host identity is required" }
        require(signaling.role == PeerRole.DEVICE) { "Android product sessions must use a device signaling credential" }
    }

    /** Mirrors macOS InternetProductSessionConfiguration.boundTranscriptContext byte-for-byte. */
    fun boundTranscriptContext(localDeviceId: String): ByteArray {
        require(localDeviceId.isNotBlank()) { "Local device identity is required" }
        return SecurityTranscript.digest(
            PRODUCT_SESSION_CONTEXT_DOMAIN,
            transcriptContext,
            signalingSessionId.toByteArray(Charsets.UTF_8),
            SecurityTranscript.uint64(authoritativeSessionEpoch),
            pinnedHostId.toByteArray(Charsets.UTF_8),
            localDeviceId.toByteArray(Charsets.UTF_8),
            SecurityTranscript.uint64(HOST_ROLE),
            SecurityTranscript.uint64(DEVICE_ROLE),
        )
    }

    private companion object {
        const val PRODUCT_SESSION_CONTEXT_DOMAIN = "vibescreen/product-session-context/v1"
        const val HOST_ROLE = 1L
        const val DEVICE_ROLE = 2L
    }
}

enum class InternetProductSessionState {
    IDLE,
    CONNECTING,
    NEGOTIATING,
    ACTIVE,
    RECOVERING,
    SUSPENDED,
    FAILED,
    CLOSED,
}

data class ProductVideoDecision(
    val accepted: Boolean,
    val rejectionReason: String = "",
) {
    init {
        require(accepted || rejectionReason.isNotBlank()) { "Rejected video configuration requires a reason" }
    }

    companion object {
        val ACCEPT = ProductVideoDecision(true)

        fun reject(reason: String) = ProductVideoDecision(false, reason)
    }
}

data class ProductVideoFrame(
    val streamId: Long,
    val sessionEpoch: Long,
    val configEpoch: Long,
    val frameId: Long,
    val captureTimestampNs: Long,
    val keyframe: Boolean,
    val codec: ProductVideoCodec,
    val payload: ByteArray,
)

interface InternetProductSessionCallbacks {
    fun onStateChanged(state: InternetProductSessionState) = Unit

    fun onRouteSelected(route: PeerRoute) = Unit

    fun onVideoConfiguration(configuration: ProductVideoConfiguration): ProductVideoDecision =
        ProductVideoDecision.reject("decoder_not_configured")

    fun onVideoFrame(frame: ProductVideoFrame) = Unit

    fun onPong(sequence: Long) = Unit

    fun onFreshSessionRequired(reason: String) = Unit

    fun onRevoked(reason: String) = Unit

    fun onFailure(error: Throwable) = Unit
}

/** Persists authenticated revocation before UI notification or transport close. */
fun interface InternetProductRevocationStore {
    fun persistAuthenticatedRevocation(pairingIdentifier: String, reason: String)
}

/**
 * Product Protocol v1 composition above the application-encrypted WebRTC channels.
 * One instance owns exactly one signaling session and epoch. Recovery is handed to
 * the owner, which must obtain a fresh lease and construct a replacement instance.
 */
class InternetProductSession internal constructor(
    private val lease: InternetProductSessionLease,
    configuration: PeerConfiguration,
    peerEngine: WebRtcPeerEngine,
    networkMonitor: NetworkMonitor,
    private val clock: MonotonicClock,
    private val codec: ProtocolV1ProductCodec,
    private val callbacks: InternetProductSessionCallbacks,
    private val revocationStore: InternetProductRevocationStore,
) : AutoCloseable {
    private val lock = Any()
    private val nextMessageId = AtomicLong(0)
    private var currentVideoConfiguration: ProductVideoConfiguration? = null
    private var acceptedHostHello = false
    private var acceptedSession = false
    private var negotiationStarted = false
    private var freshSessionRequested = false
    private var heartbeatIntervalMillis = 0L
    private var nextHeartbeatAtMillis = Long.MAX_VALUE
    private var nextHeartbeatSequence = 1L
    private var lastReceivedControlMessageId = 0L
    private var closed = false
    private val frameAssembler = ProductMediaFrameAssembler()

    private val transport =
        WebRtcInternetTransport(
            configuration = configuration,
            peerEngine = peerEngine,
            networkMonitor = networkMonitor,
            clock = clock,
            eventSink = ::handleTransportEvent,
        ).apply {
            onControlMessage = ::handleControl
            onMediaPacket = ::handleMedia
        }

    @Volatile
    var state: InternetProductSessionState = InternetProductSessionState.IDLE
        private set

    fun start() {
        synchronized(lock) {
            check(!closed) { "Product session is closed" }
            check(state == InternetProductSessionState.IDLE) { "Product session has already started" }
        }
        transition(InternetProductSessionState.CONNECTING)
        try {
            transport.start()
        } catch (failure: Throwable) {
            fail(failure)
            throw failure
        }
    }

    fun tick() {
        transport.tick()
        heartbeatTick()
    }

    fun sendTouch(event: ProductTouchEvent): Boolean =
        sendApplicationControl {
            codec.encodeTouch(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, event)
        }

    fun requestKeyframe(reason: String): Boolean {
        val streamId = synchronized(lock) { currentVideoConfiguration?.streamId } ?: return false
        return sendApplicationControl {
            codec.encodeKeyframeRequest(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                streamId,
                reason,
            )
        }
    }

    fun sendPing(sequence: Long): Boolean =
        sendApplicationControl {
            codec.encodePing(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, sequence)
        }

    override fun close() {
        val shouldClose =
            synchronized(lock) {
                if (closed) return
                closed = true
                acceptedSession = false
                currentVideoConfiguration = null
                nextHeartbeatAtMillis = Long.MAX_VALUE
                frameAssembler.reset()
                true
            }
        if (shouldClose) {
            runBestEffort(
                { transport.close() },
                { transition(InternetProductSessionState.CLOSED) },
            )
        }
    }

    private fun handleTransportEvent(event: InternetTransportEvent) {
        if (synchronized(lock) { closed }) return
        when (event) {
            is InternetTransportEvent.StateChanged -> {
                when (event.state) {
                    InternetTransportState.CONNECTING -> transition(InternetProductSessionState.CONNECTING)
                    InternetTransportState.RECOVERING -> transition(InternetProductSessionState.RECOVERING)
                    InternetTransportState.SUSPENDED -> transition(InternetProductSessionState.SUSPENDED)
                    InternetTransportState.CONNECTED_DIRECT,
                    InternetTransportState.CONNECTED_RELAY
                    -> resumeAuthenticatedSessionAfterTransportRecovery()
                    InternetTransportState.CLOSED -> transition(InternetProductSessionState.CLOSED)
                    else -> Unit
                }
            }
            is InternetTransportEvent.RouteSelected -> {
                callbacks.onRouteSelected(event.route)
                beginProtocolNegotiation()
            }
            is InternetTransportEvent.RouteUpdated -> callbacks.onRouteSelected(event.route)
            is InternetTransportEvent.FreshSessionRequested -> {
                val notify =
                    synchronized(lock) {
                        if (freshSessionRequested || closed) false else true.also { freshSessionRequested = it }
                    }
                if (notify) {
                    transition(InternetProductSessionState.RECOVERING)
                    callbacks.onFreshSessionRequired(event.reason)
                }
            }
            is InternetTransportEvent.Failure -> fail(event.error)
            is InternetTransportEvent.VideoProfileChanged -> Unit
        }
    }

    private fun beginProtocolNegotiation() {
        val shouldSend =
            synchronized(lock) {
                if (closed || acceptedSession || negotiationStarted) {
                    false
                } else {
                    negotiationStarted = true
                    true
                }
            }
        if (!shouldSend) return
        transition(InternetProductSessionState.NEGOTIATING)
        sendRequiredControl(
            codec.encodeClientHello(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
            ),
        )
    }

    private fun handleControl(payload: ByteArray) {
        if (synchronized(lock) { closed }) return
        val decoded =
            try {
                codec.decodeControl(payload)
            } catch (failure: Throwable) {
                return fail(IllegalArgumentException("Protocol v1 control message was rejected", failure))
            }
        if (!decoded.sessionId.contentEquals(lease.protocolSessionId) || decoded.sessionEpoch != lease.authoritativeSessionEpoch) {
            return fail(IllegalArgumentException("Protocol v1 control routing metadata does not match the active session"))
        }
        val monotonic =
            synchronized(lock) {
                if (decoded.messageId <= lastReceivedControlMessageId) {
                    false
                } else {
                    lastReceivedControlMessageId = decoded.messageId
                    true
                }
            }
        if (!monotonic) return fail(IllegalArgumentException("Protocol v1 control message ID is not positive and monotonic"))
        when (val message = decoded.message) {
            is ProductControlMessage.HostHello -> handleHostHello(message)
            is ProductControlMessage.SessionAccepted -> handleSessionAccepted(message)
            is ProductControlMessage.SessionRejected -> {
                fail(IllegalStateException("Session rejected (${message.reasonCode}); retryable=${message.retryable}"))
            }
            is ProductControlMessage.VideoConfiguration -> handleVideoConfiguration(message.value)
            is ProductControlMessage.Pong -> callbacks.onPong(message.sequence)
            is ProductControlMessage.Ping -> {
                sendRequiredControl(
                    codec.encodePong(
                        nextMessageId(),
                        decoded.messageId,
                        lease.protocolSessionId,
                        lease.authoritativeSessionEpoch,
                        message.sequence,
                    ),
                )
            }
            is ProductControlMessage.Disconnect -> requestFreshSessionIfAllowed(message.reasonCode, message.mayResume)
            is ProductControlMessage.Revoked -> {
                try {
                    revocationStore.persistAuthenticatedRevocation(lease.pairingIdentifier, message.reasonCode)
                } catch (failure: Throwable) {
                    fail(IllegalStateException("Authenticated revocation could not be persisted", failure))
                    close()
                    return
                }
                transition(InternetProductSessionState.FAILED)
                callbacks.onRevoked(message.reasonCode)
                close()
            }
            is ProductControlMessage.ProtocolFailure -> {
                fail(IllegalStateException("Protocol failure (${message.code}); retryable=${message.retryable}"))
            }
            ProductControlMessage.Ignored -> Unit
        }
    }

    private fun handleHostHello(message: ProductControlMessage.HostHello) {
        val required = ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES.toSet()
        if (
            message.hostId != lease.pinnedHostId ||
            message.selectedProtocol != ProtobufProtocolV1ProductCodec.PROTOCOL_VERSION ||
            !message.capabilities.containsAll(required)
        ) {
            return fail(IllegalArgumentException("Host does not support the required Internet security capabilities"))
        }
        synchronized(lock) { acceptedHostHello = true }
    }

    private fun handleSessionAccepted(message: ProductControlMessage.SessionAccepted) {
        val valid =
            synchronized(lock) {
                acceptedHostHello &&
                    message.sessionId.contentEquals(lease.protocolSessionId) &&
                    message.sessionEpoch == lease.authoritativeSessionEpoch &&
                    message.capabilities.containsAll(REQUIRED_SESSION_CAPABILITIES) &&
                    message.heartbeatIntervalMillis in MIN_HEARTBEAT_INTERVAL_MS..MAX_HEARTBEAT_INTERVAL_MS
            }
        if (!valid) return fail(IllegalArgumentException("Session acceptance does not match the authenticated lease"))
        synchronized(lock) {
            acceptedSession = true
            heartbeatIntervalMillis = message.heartbeatIntervalMillis
            scheduleNextHeartbeatLocked()
        }
        transition(InternetProductSessionState.ACTIVE)
    }

    private fun resumeAuthenticatedSessionAfterTransportRecovery() {
        val shouldResume =
            synchronized(lock) {
                if (!acceptedSession || !negotiationStarted || closed) {
                    false
                } else {
                    scheduleNextHeartbeatLocked()
                    true
                }
            }
        if (shouldResume) transition(InternetProductSessionState.ACTIVE)
    }

    private fun heartbeatTick() {
        val sequence =
            synchronized(lock) {
                if (closed || state != InternetProductSessionState.ACTIVE || clock.nowMillis() < nextHeartbeatAtMillis) {
                    null
                } else {
                    val value = nextHeartbeatSequence++
                    scheduleNextHeartbeatLocked()
                    value
                }
            } ?: return
        sendPing(sequence)
    }

    private fun scheduleNextHeartbeatLocked() {
        nextHeartbeatAtMillis = clock.nowMillis() + heartbeatIntervalMillis
    }

    private fun handleVideoConfiguration(configuration: ProductVideoConfiguration) {
        if (!synchronized(lock) { acceptedSession && !closed }) {
            return fail(IllegalStateException("Video configuration arrived before session acceptance"))
        }
        val previousConfigurationEpoch = synchronized(lock) { currentVideoConfiguration?.configEpoch ?: 0 }
        if (configuration.configEpoch <= previousConfigurationEpoch) {
            return fail(IllegalArgumentException("Video configuration epoch did not increase"))
        }
        val decision =
            try {
                callbacks.onVideoConfiguration(configuration)
            } catch (failure: Throwable) {
                ProductVideoDecision.reject("decoder_configuration_failure").also { callbacks.onFailure(failure) }
            }
        sendRequiredControl(
            codec.encodeVideoConfigResult(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                configuration,
                decision.accepted,
                decision.rejectionReason,
            ),
        )
        if (decision.accepted) {
            synchronized(lock) {
                currentVideoConfiguration = configuration
                frameAssembler.startConfiguration(configuration)
            }
        }
    }

    private fun handleMedia(payload: ByteArray) {
        val configuration = synchronized(lock) { currentVideoConfiguration.takeIf { acceptedSession && !closed } } ?: return
        val fragment =
            try {
                codec.decodeMediaFragment(payload)
            } catch (failure: Throwable) {
                return fail(IllegalArgumentException("Protocol v1 media packet was rejected", failure))
            }
        if (
            fragment.sessionEpoch != lease.authoritativeSessionEpoch ||
            fragment.streamId != configuration.streamId ||
            fragment.configEpoch != configuration.configEpoch ||
            fragment.codec != configuration.codec
        ) {
            return
        }
        val frame = synchronized(lock) { frameAssembler.offer(fragment) } ?: return
        callbacks.onVideoFrame(frame)
    }

    private fun requestFreshSessionIfAllowed(reason: String, mayResume: Boolean) {
        if (!mayResume) return fail(IllegalStateException("Host ended the Internet session: $reason"))
        val notify =
            synchronized(lock) {
                if (freshSessionRequested || closed) false else true.also { freshSessionRequested = it }
            }
        if (notify) {
            transition(InternetProductSessionState.RECOVERING)
            callbacks.onFreshSessionRequired(reason)
        }
    }

    private fun sendApplicationControl(encode: () -> ByteArray): Boolean {
        if (!synchronized(lock) { acceptedSession && !closed && state == InternetProductSessionState.ACTIVE }) return false
        val encoded = encode()
        if (transport.sendControl(encoded)) return true
        fail(IllegalStateException("Reliable control channel backlog rejected a state-changing message"))
        return false
    }

    private fun sendRequiredControl(payload: ByteArray) {
        if (!transport.sendControl(payload)) {
            fail(IllegalStateException("Required Protocol v1 control message could not be queued"))
        }
    }

    private fun nextMessageId(): Long {
        val next = nextMessageId.incrementAndGet()
        check(next > 0) { "Protocol message identifier exhausted" }
        return next
    }

    private fun fail(error: Throwable) {
        val notify =
            synchronized(lock) {
                if (closed || state == InternetProductSessionState.FAILED) false else true
            }
        if (notify) {
            transition(InternetProductSessionState.FAILED)
            callbacks.onFailure(error)
        }
    }

    private fun transition(next: InternetProductSessionState) {
        val changed =
            synchronized(lock) {
                if (state == next) false else true.also { state = next }
            }
        if (changed) callbacks.onStateChanged(next)
    }

    companion object {
        private const val MIN_HEARTBEAT_INTERVAL_MS = 100L
        private const val MAX_HEARTBEAT_INTERVAL_MS = 60_000L
        private val REQUIRED_SESSION_CAPABILITIES =
            setOf(
                Capability.CAPABILITY_DEVICE_IDENTITY,
                Capability.CAPABILITY_END_TO_END_ENCRYPTION,
                Capability.CAPABILITY_REPLAY_PROTECTION,
            )

        fun create(
            storedSessionFactory: AndroidStoredInternetSessionFactory,
            localDeviceId: String,
            lease: InternetProductSessionLease,
            networkMonitor: NetworkMonitor,
            clock: MonotonicClock,
            codec: ProtocolV1ProductCodec,
            callbacks: InternetProductSessionCallbacks,
            revocationStore: InternetProductRevocationStore,
        ): InternetProductSession {
            require(localDeviceId == storedSessionFactory.localDeviceId) {
                "Stored security identity does not match the product session identity"
            }
            require(localDeviceId == codec.localDeviceId) {
                "Protocol identity does not match the product session identity"
            }
            val boundContext = lease.boundTranscriptContext(localDeviceId)
            val stored =
                try {
                    storedSessionFactory.create(
                        pairingIdentifier = lease.pairingIdentifier,
                        sessionId = lease.signalingSessionId,
                        localRole = PeerRole.DEVICE,
                        identityEpoch = lease.identityEpoch,
                        authoritativeSessionEpoch = lease.authoritativeSessionEpoch,
                        transcriptContext = boundContext,
                        iceServers = lease.iceServers,
                        signaling = lease.signaling,
                        iceTransportPolicy = lease.iceTransportPolicy,
                    )
                } finally {
                    boundContext.fill(0)
                }
            return try {
                InternetProductSession(
                    lease,
                    stored.configuration,
                    stored.engine,
                    networkMonitor,
                    clock,
                    codec,
                    callbacks,
                    revocationStore,
                )
            } catch (failure: Throwable) {
                stored.close()
                throw failure
            }
        }
    }
}

private class ProductMediaFrameAssembler {
    private var configuration: ProductVideoConfiguration? = null
    private var current: PendingFrame? = null
    private var waitingForKeyframe = true
    private var highestFrameId = 0L

    fun startConfiguration(configuration: ProductVideoConfiguration) {
        this.configuration = configuration
        current = null
        waitingForKeyframe = true
        highestFrameId = 0
    }

    fun offer(fragment: ProductMediaFragment): ProductVideoFrame? {
        val active = configuration ?: return null
        if (fragment.frameId <= highestFrameId || fragment.fragmentCount !in 1..MAX_FRAGMENTS) return null
        val pending = current
        if (pending == null || fragment.frameId > pending.frameId) {
            current = PendingFrame(fragment)
        } else if (fragment.frameId < pending.frameId || !pending.matches(fragment)) {
            return null
        }
        val target = checkNotNull(current)
        if (!target.add(fragment) || target.totalBytes > MAX_FRAME_BYTES) {
            if (target.totalBytes > MAX_FRAME_BYTES) current = null
            return null
        }
        if (!target.complete()) return null
        current = null
        highestFrameId = target.frameId
        if (waitingForKeyframe && !target.keyframe) return null
        waitingForKeyframe = false
        return ProductVideoFrame(
            streamId = active.streamId,
            sessionEpoch = fragment.sessionEpoch,
            configEpoch = active.configEpoch,
            frameId = target.frameId,
            captureTimestampNs = target.captureTimestampNs,
            keyframe = target.keyframe,
            codec = active.codec,
            payload = target.combine(),
        )
    }

    fun reset() {
        configuration = null
        current = null
        waitingForKeyframe = true
        highestFrameId = 0
    }

    private class PendingFrame(fragment: ProductMediaFragment) {
        val frameId = fragment.frameId
        val fragmentCount = fragment.fragmentCount
        val captureTimestampNs = fragment.captureTimestampNs
        val keyframe = fragment.keyframe
        private val streamId = fragment.streamId
        private val sessionEpoch = fragment.sessionEpoch
        private val configEpoch = fragment.configEpoch
        private val codec = fragment.codec
        private val fragments = arrayOfNulls<ByteArray>(fragmentCount)
        var totalBytes = 0
            private set

        fun matches(fragment: ProductMediaFragment): Boolean =
            fragment.frameId == frameId &&
                fragment.fragmentCount == fragmentCount &&
                fragment.captureTimestampNs == captureTimestampNs &&
                fragment.keyframe == keyframe &&
                fragment.streamId == streamId &&
                fragment.sessionEpoch == sessionEpoch &&
                fragment.configEpoch == configEpoch &&
                fragment.codec == codec

        fun add(fragment: ProductMediaFragment): Boolean {
            if (fragment.fragmentIndex !in fragments.indices || fragments[fragment.fragmentIndex] != null) return false
            fragments[fragment.fragmentIndex] = fragment.payload.copyOf()
            totalBytes += fragment.payload.size
            return true
        }

        fun complete(): Boolean = fragments.all { it != null }

        fun combine(): ByteArray {
            val output = ByteArray(totalBytes)
            var offset = 0
            fragments.forEach { fragment ->
                val value = checkNotNull(fragment)
                value.copyInto(output, offset)
                offset += value.size
            }
            return output
        }
    }

    companion object {
        private const val MAX_FRAGMENTS = 256
        private const val MAX_FRAME_BYTES = 16 * 1024 * 1024
    }
}
