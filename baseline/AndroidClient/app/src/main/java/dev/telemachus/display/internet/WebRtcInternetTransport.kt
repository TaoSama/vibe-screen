package dev.telemachus.display.internet

/**
 * SDK-independent Internet transport coordinator. A concrete engine owns SDP/signaling,
 * DTLS/SRTP, WebRTC tracks/data channels, and TURN credentials; this class owns recovery policy.
 */
class WebRtcInternetTransport(
    private val configuration: PeerConfiguration,
    private val peerEngine: WebRtcPeerEngine,
    private val networkMonitor: NetworkMonitor,
    private val clock: MonotonicClock,
    private val adaptiveVideoPolicy: AdaptiveVideoPolicy = AdaptiveVideoPolicy(),
    private val eventSink: (InternetTransportEvent) -> Unit = {},
) : WebRtcPeerEngine.Observer,
    NetworkMonitor.Listener,
    AutoCloseable {
    private val lock = Any()
    private var activeNetwork: NetworkSnapshot? = null
    private var lastIceRestartAtMillis = Long.MIN_VALUE
    private var reconnectAttempt = 0
    private var nextRecoveryAtMillis: Long? = null
    private var pendingIceRestartReason: String? = null
    @Volatile private var closed = false

    @Volatile
    var state: InternetTransportState = InternetTransportState.IDLE
        private set

    @Volatile var onControlMessage: ((ByteArray) -> Unit)? = null
    @Volatile var onMediaPacket: ((ByteArray) -> Unit)? = null

    fun start() {
        val stateEvent =
            synchronized(lock) {
                check(!closed) { "Transport is closed" }
                check(state == InternetTransportState.IDLE) { "Transport has already started" }
                require(peerEngine.controlSemantics == DataChannelSemantics.RELIABLE_CONTROL) {
                    "Control channel must be reliable and ordered"
                }
                require(peerEngine.mediaSemantics == DataChannelSemantics.LATEST_MEDIA) {
                    "Media channel must be unordered with no retransmissions"
                }
                transitionLocked(InternetTransportState.CONNECTING)
            }
        stateEvent?.let(eventSink)
        try {
            networkMonitor.start(this)
            peerEngine.applyVideoProfile(adaptiveVideoPolicy.currentProfile)
            peerEngine.start(configuration, this)
        } catch (startFailure: Throwable) {
            try {
                close()
            } catch (closeFailure: Throwable) {
                startFailure.addSuppressed(closeFailure)
            }
            throw startFailure
        }
    }

    fun sendControl(payload: ByteArray): Boolean {
        val canSend = synchronized(lock) { !closed && state.isConnected() }
        return canSend && peerEngine.sendControl(payload)
    }

    fun sendMedia(payload: ByteArray): Boolean {
        val canSend = synchronized(lock) { !closed && state.isConnected() }
        return canSend && peerEngine.sendMedia(payload)
    }

    override fun onConnected(route: PeerRoute) {
        val stateEvent =
            synchronized(lock) {
                if (closed) return
                reconnectAttempt = 0
                nextRecoveryAtMillis = null
                pendingIceRestartReason = null
                transitionLocked(
                    if (route == PeerRoute.DIRECT) {
                        InternetTransportState.CONNECTED_DIRECT
                    } else {
                        InternetTransportState.CONNECTED_RELAY
                    },
                )
            }
        stateEvent?.let(eventSink)
        eventSink(InternetTransportEvent.RouteSelected(route))
    }

    override fun onDisconnected() {
        val stateEvent =
            synchronized(lock) {
                if (closed) return
                val event =
                    transitionLocked(
                        if (activeNetwork == null) {
                            InternetTransportState.SUSPENDED
                        } else {
                            InternetTransportState.RECOVERING
                        },
                    )
                if (activeNetwork != null) scheduleRecoveryLocked()
                event
            }
        stateEvent?.let(eventSink)
    }

    override fun onControlMessage(
        sessionEpoch: Long,
        payload: ByteArray,
    ) {
        val callback = synchronized(lock) { onControlMessage.takeIf { acceptsPacketLocked(sessionEpoch) } }
        callback?.invoke(payload)
    }

    override fun onMediaPacket(
        sessionEpoch: Long,
        payload: ByteArray,
    ) {
        val callback = synchronized(lock) { onMediaPacket.takeIf { acceptsPacketLocked(sessionEpoch) } }
        callback?.invoke(payload)
    }

    override fun onStats(stats: WebRtcStats) {
        val profile = synchronized(lock) { if (closed) null else adaptiveVideoPolicy.update(stats) }
        profile?.let {
            peerEngine.applyVideoProfile(it)
            eventSink(InternetTransportEvent.VideoProfileChanged(it))
        }
    }

    override fun onAvailable(network: NetworkSnapshot) {
        var stateEvent: InternetTransportEvent.StateChanged? = null
        var restartReason: String? = null
        var forceRestart = false
        synchronized(lock) {
            if (closed) return
            if (!network.validated) {
                if (activeNetwork?.id == network.id) {
                    activeNetwork = null
                    nextRecoveryAtMillis = null
                    pendingIceRestartReason = null
                    stateEvent = transitionLocked(InternetTransportState.SUSPENDED)
                }
                return@synchronized
            }

            val previousNetworkId = activeNetwork?.id
            activeNetwork = network
            if (state == InternetTransportState.SUSPENDED) {
                stateEvent = transitionLocked(InternetTransportState.RECOVERING)
                restartReason = "validated network became available"
                forceRestart = true
                scheduleRecoveryLocked()
            } else if (previousNetworkId != null && previousNetworkId != network.id) {
                restartReason = "network changed from $previousNetworkId to ${network.id}"
            }
        }
        stateEvent?.let(eventSink)
        restartReason?.let { requestIceRestart(it, forceRestart) }
    }

    override fun onLost(networkId: String) {
        val stateEvent =
            synchronized(lock) {
                if (closed || activeNetwork?.id != networkId) return
                activeNetwork = null
                nextRecoveryAtMillis = null
                pendingIceRestartReason = null
                transitionLocked(InternetTransportState.SUSPENDED)
            }
        stateEvent?.let(eventSink)
    }

    /** Drives delayed ICE recovery from the owner's existing timer/heartbeat; it creates no hidden thread. */
    fun tick() {
        var restartReason: String? = null
        synchronized(lock) {
            if (closed || activeNetwork == null) return
            val now = clock.nowMillis()
            val pendingReason = pendingIceRestartReason
            if (pendingReason != null && iceRestartCooldownElapsedLocked(now)) {
                pendingIceRestartReason = null
                restartReason = pendingReason
            } else {
                val recoveryAt = nextRecoveryAtMillis
                if (recoveryAt != null && now >= recoveryAt) {
                    restartReason = "peer disconnected"
                    reconnectAttempt++
                    nextRecoveryAtMillis = null
                    scheduleRecoveryLocked()
                }
            }
        }
        restartReason?.let { requestIceRestart(it, force = true) }
    }

    override fun close() {
        val stateEvent =
            synchronized(lock) {
                if (closed) return
                closed = true
                nextRecoveryAtMillis = null
                pendingIceRestartReason = null
                transitionLocked(InternetTransportState.CLOSED)
            }

        var closeFailure: Throwable? = null
        try {
            networkMonitor.close()
        } catch (failure: Throwable) {
            closeFailure = failure
        }
        try {
            peerEngine.close()
        } catch (failure: Throwable) {
            if (closeFailure == null) {
                closeFailure = failure
            } else {
                closeFailure.addSuppressed(failure)
            }
        }
        stateEvent?.let(eventSink)
        closeFailure?.let { throw it }
    }

    private fun requestIceRestart(
        reason: String,
        force: Boolean,
    ) {
        val shouldRestart =
            synchronized(lock) {
                if (closed || activeNetwork == null) return
                val now = clock.nowMillis()
                if (!force && !iceRestartCooldownElapsedLocked(now)) {
                    pendingIceRestartReason = reason
                    false
                } else {
                    lastIceRestartAtMillis = now
                    pendingIceRestartReason = null
                    true
                }
            }
        if (shouldRestart) {
            try {
                peerEngine.restartIce()
                eventSink(InternetTransportEvent.IceRestartRequested(reason))
            } catch (failure: Throwable) {
                synchronized(lock) {
                    if (!closed) {
                        lastIceRestartAtMillis = Long.MIN_VALUE
                        pendingIceRestartReason = reason
                    }
                }
                throw failure
            }
        }
    }

    private fun iceRestartCooldownElapsedLocked(now: Long): Boolean =
        lastIceRestartAtMillis == Long.MIN_VALUE || now - lastIceRestartAtMillis >= ICE_RESTART_COOLDOWN_MS

    private fun scheduleRecoveryLocked() {
        if (nextRecoveryAtMillis != null) return
        val delay =
            (INITIAL_RECOVERY_DELAY_MS shl reconnectAttempt.coerceAtMost(MAX_BACKOFF_SHIFT))
                .coerceAtMost(MAX_RECOVERY_DELAY_MS)
        nextRecoveryAtMillis = clock.nowMillis() + delay
    }

    private fun transitionLocked(newState: InternetTransportState): InternetTransportEvent.StateChanged? {
        if (state == newState) return null
        state = newState
        return InternetTransportEvent.StateChanged(newState)
    }

    private fun acceptsPacketLocked(sessionEpoch: Long): Boolean =
        !closed && state.isConnected() && sessionEpoch == configuration.sessionEpoch

    private fun InternetTransportState.isConnected(): Boolean =
        this == InternetTransportState.CONNECTED_DIRECT || this == InternetTransportState.CONNECTED_RELAY

    companion object {
        private const val ICE_RESTART_COOLDOWN_MS = 5_000L
        private const val INITIAL_RECOVERY_DELAY_MS = 500L
        private const val MAX_RECOVERY_DELAY_MS = 8_000L
        private const val MAX_BACKOFF_SHIFT = 4
    }
}
