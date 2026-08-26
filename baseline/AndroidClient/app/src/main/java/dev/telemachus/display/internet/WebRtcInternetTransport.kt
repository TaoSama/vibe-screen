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
    private var lastRecoveryRequestAtMillis = Long.MIN_VALUE
    private var reconnectAttempt = 0
    private var nextRecoveryAtMillis: Long? = null
    private var pendingFreshSessionReason: String? = null
    private var selectedRoute: PeerRoute? = null
    @Volatile private var closed = false

    @Volatile
    var state: InternetTransportState = InternetTransportState.IDLE
        private set

    @Volatile var onControlMessage: ((ByteArray) -> Unit)? = null
    @Volatile var onMediaPacket: ((ByteArray) -> Unit)? = null
    @Volatile var onAudioRecord: ((ByteArray) -> Unit)? = null
    @Volatile var onBulkRecord: ((ByteArray) -> Unit)? = null

    fun start() {
        val stateEvent =
            synchronized(lock) {
                check(!closed) { "Transport is closed" }
                check(state == InternetTransportState.IDLE) { "Transport has already started" }
                for (kind in WebRtcDataChannelKind.entries) {
                    require(peerEngine.dataChannelSemantics[kind] == kind.semantics) {
                        "${kind.name.lowercase()} WebRTC data channel semantics do not match the Protocol v1 contract"
                    }
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

    fun sendMedia(frame: OutboundMediaFrame): Boolean {
        val canSend = synchronized(lock) { !closed && state.isConnected() }
        return canSend && peerEngine.sendMedia(frame)
    }

    fun sendAudioRecord(payload: ByteArray): Boolean {
        val canSend = synchronized(lock) { !closed && state.isConnected() }
        return canSend && peerEngine.sendAudioRecord(payload)
    }

    fun sendBulkRecord(payload: ByteArray): Boolean {
        val canSend = synchronized(lock) { !closed && state.isConnected() }
        return canSend && peerEngine.sendBulkRecord(payload)
    }

    override fun onConnected(route: PeerRoute) {
        val events =
            synchronized(lock) {
                if (closed) return
                reconnectAttempt = 0
                nextRecoveryAtMillis = null
                pendingFreshSessionReason = null
                routeEventsLocked(route, initial = selectedRoute == null)
            }
        events.state?.let(eventSink)
        events.route?.let(eventSink)
    }

    override fun onRouteChanged(route: PeerRoute) {
        val events =
            synchronized(lock) {
                if (closed || selectedRoute == null) return
                routeEventsLocked(route, initial = false)
            }
        events.state?.let(eventSink)
        events.route?.let(eventSink)
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

    override fun onConnectionFailed(reason: String) {
        val stateEvent =
            synchronized(lock) {
                if (closed) return
                transitionLocked(
                    if (activeNetwork == null) {
                        InternetTransportState.SUSPENDED
                    } else {
                        InternetTransportState.RECOVERING
                    },
                )
            }
        stateEvent?.let(eventSink)
        attemptIceRestart(reason)
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

    override fun onAudioRecord(
        sessionEpoch: Long,
        payload: ByteArray,
    ) {
        val callback = synchronized(lock) { onAudioRecord.takeIf { acceptsPacketLocked(sessionEpoch) } }
        callback?.invoke(payload)
    }

    override fun onBulkRecord(
        sessionEpoch: Long,
        payload: ByteArray,
    ) {
        val callback = synchronized(lock) { onBulkRecord.takeIf { acceptsPacketLocked(sessionEpoch) } }
        callback?.invoke(payload)
    }

    override fun onStats(stats: WebRtcStats) {
        val profile = synchronized(lock) { if (closed) null else adaptiveVideoPolicy.update(stats) }
        profile?.let {
            peerEngine.applyVideoProfile(it)
            eventSink(InternetTransportEvent.VideoProfileChanged(it))
        }
    }

    override fun onFailure(error: Throwable) {
        if (!synchronized(lock) { closed }) eventSink(InternetTransportEvent.Failure(error))
    }

    override fun onAvailable(network: NetworkSnapshot) {
        var stateEvent: InternetTransportEvent.StateChanged? = null
        var restartReason: String? = null
        var freshSessionReason: String? = null
        synchronized(lock) {
            if (closed) return
            if (!network.validated) {
                if (activeNetwork?.id == network.id) {
                    activeNetwork = null
                    nextRecoveryAtMillis = null
                    pendingFreshSessionReason = null
                    stateEvent = transitionLocked(InternetTransportState.SUSPENDED)
                }
                return@synchronized
            }

            val previousNetworkId = activeNetwork?.id
            activeNetwork = network
            if (state == InternetTransportState.SUSPENDED) {
                stateEvent = transitionLocked(InternetTransportState.RECOVERING)
                restartReason = "validated network became available"
            } else if (previousNetworkId != null && previousNetworkId != network.id && state.isConnected()) {
                stateEvent = transitionLocked(InternetTransportState.RECOVERING)
                nextRecoveryAtMillis = null
                pendingFreshSessionReason = null
                freshSessionReason = "network changed from $previousNetworkId to ${network.id}; fresh signaling session required"
            }
        }
        stateEvent?.let(eventSink)
        restartReason?.let { attemptIceRestart(it) }
        freshSessionReason?.let { requestFreshSession(it, force = true) }
    }

    override fun onLost(networkId: String) {
        val stateEvent =
            synchronized(lock) {
                if (closed || activeNetwork?.id != networkId) return
                activeNetwork = null
                nextRecoveryAtMillis = null
                pendingFreshSessionReason = null
                transitionLocked(InternetTransportState.SUSPENDED)
            }
        stateEvent?.let(eventSink)
    }

    /** Drives delayed ICE recovery from the owner's existing timer/heartbeat; it creates no hidden thread. */
    fun tick() {
        var restartReason: String? = null
        var freshSessionReason: String? = null
        synchronized(lock) {
            if (closed || activeNetwork == null) return
            val now = clock.nowMillis()
            val pendingReason = pendingFreshSessionReason
            if (pendingReason != null && recoveryCooldownElapsedLocked(now)) {
                pendingFreshSessionReason = null
                freshSessionReason = pendingReason
            } else {
                val recoveryAt = nextRecoveryAtMillis
                if (recoveryAt != null && now >= recoveryAt) {
                    restartReason = "peer disconnected"
                    nextRecoveryAtMillis = null
                }
            }
        }
        restartReason?.let { attemptIceRestart(it) }
        freshSessionReason?.let { requestFreshSession(it, force = true) }
    }

    override fun close() {
        val stateEvent =
            synchronized(lock) {
                if (closed) return
                closed = true
                nextRecoveryAtMillis = null
                pendingFreshSessionReason = null
                selectedRoute = null
                transitionLocked(InternetTransportState.CLOSED)
            }

        runBestEffort(
            { networkMonitor.close() },
            { peerEngine.close() },
            { stateEvent?.let(eventSink) },
        )
    }

    private fun requestFreshSession(
        reason: String,
        force: Boolean,
    ) {
        val shouldRequest =
            synchronized(lock) {
                if (closed || activeNetwork == null) return
                val now = clock.nowMillis()
                if (!force && !recoveryCooldownElapsedLocked(now)) {
                    pendingFreshSessionReason = reason
                    false
                } else {
                    lastRecoveryRequestAtMillis = now
                    pendingFreshSessionReason = null
                    true
                }
            }
        if (shouldRequest) {
            eventSink(InternetTransportEvent.FreshSessionRequested(reason))
        }
    }

    private fun attemptIceRestart(reason: String) {
        val action =
            synchronized(lock) {
                if (closed || activeNetwork == null) return
                if (reconnectAttempt >= MAX_ICE_RESTART_ATTEMPTS) {
                    nextRecoveryAtMillis = null
                    pendingFreshSessionReason = null
                    RecoveryAction.RequestFreshSession(
                        "ICE recovery exhausted after $reconnectAttempt attempts: $reason",
                    )
                } else {
                    reconnectAttempt++
                    nextRecoveryAtMillis = null
                    scheduleRecoveryLocked()
                    RecoveryAction.RestartIce(reconnectAttempt)
                }
            }
        when (action) {
            is RecoveryAction.RestartIce -> {
                when (val result = peerEngine.restartIce()) {
                    WebRtcIceRestartResult.Started -> Unit
                    is WebRtcIceRestartResult.RequiresFreshSession -> {
                        synchronized(lock) {
                            nextRecoveryAtMillis = null
                            pendingFreshSessionReason = null
                        }
                        requestFreshSession(result.reason, force = true)
                    }
                    is WebRtcIceRestartResult.Failed -> requestFreshSession(
                        "ICE restart attempt ${action.attempt} failed: ${result.reason}",
                        force = true,
                    )
                }
            }
            is RecoveryAction.RequestFreshSession -> requestFreshSession(action.reason, force = true)
        }
    }

    private fun recoveryCooldownElapsedLocked(now: Long): Boolean =
        lastRecoveryRequestAtMillis == Long.MIN_VALUE || now - lastRecoveryRequestAtMillis >= RECOVERY_REQUEST_COOLDOWN_MS

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

    private fun routeEventsLocked(route: PeerRoute, initial: Boolean): RouteEvents {
        val previous = selectedRoute
        selectedRoute = route
        val stateEvent =
            transitionLocked(
                if (route == PeerRoute.DIRECT) InternetTransportState.CONNECTED_DIRECT else InternetTransportState.CONNECTED_RELAY,
            )
        val routeEvent =
            when {
                initial -> InternetTransportEvent.RouteSelected(route)
                previous != route -> InternetTransportEvent.RouteUpdated(route)
                else -> null
            }
        return RouteEvents(stateEvent, routeEvent)
    }

    private fun acceptsPacketLocked(sessionEpoch: Long): Boolean =
        !closed && state.isConnected() && sessionEpoch == configuration.sessionEpoch

    private fun InternetTransportState.isConnected(): Boolean =
        this == InternetTransportState.CONNECTED_DIRECT || this == InternetTransportState.CONNECTED_RELAY

    private data class RouteEvents(
        val state: InternetTransportEvent.StateChanged?,
        val route: InternetTransportEvent?,
    )

    private sealed class RecoveryAction {
        data class RestartIce(val attempt: Int) : RecoveryAction()

        data class RequestFreshSession(val reason: String) : RecoveryAction()
    }

    companion object {
        private const val RECOVERY_REQUEST_COOLDOWN_MS = 5_000L
        private const val INITIAL_RECOVERY_DELAY_MS = 500L
        private const val MAX_RECOVERY_DELAY_MS = 8_000L
        private const val MAX_BACKOFF_SHIFT = 4
        private const val MAX_ICE_RESTART_ATTEMPTS = 5
    }
}
