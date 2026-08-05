package dev.telemachus.display.internet

import android.content.Context
import org.webrtc.CandidatePairChangeEvent
import org.webrtc.DataChannel
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

/** libwebrtc-backed production adapter for the reliable-control/latest-media data channels. */
class AndroidWebRtcPeerEngine internal constructor(
    context: Context,
    private val signalingClientFactory: SignalingClientFactory,
    private val videoProfileSink: (VideoProfile) -> Unit,
) : WebRtcPeerEngine,
    SignalingClient.Listener {
    constructor(
        context: Context,
        videoProfileSink: (VideoProfile) -> Unit = {},
    ) : this(
        context,
        SignalingClientFactory { configuration, sessionId ->
            RestSignalingClient(configuration, sessionId)
        },
        videoProfileSink,
    )

    override val controlSemantics = DataChannelSemantics.RELIABLE_CONTROL
    override val mediaSemantics = DataChannelSemantics.LATEST_MEDIA

    private val applicationContext = context.applicationContext
    private val lock = Any()
    private val statsExecutor: ScheduledExecutorService =
        Executors.newSingleThreadScheduledExecutor { runnable ->
            Thread(runnable, "vibe-webrtc-stats").apply { isDaemon = true }
        }
    private val routeResolutionTimeout =
        RouteResolutionTimeout(
            scheduler = RouteResolutionScheduler { delayMillis, task ->
                val future = statsExecutor.schedule(task, delayMillis, TimeUnit.MILLISECONDS)
                RouteResolutionCancellation { future.cancel(false) }
            },
            timeoutMillis = ROUTE_RESOLUTION_TIMEOUT_MS,
        )
    private var factory: PeerConnectionFactory? = null
    private var peerConnection: PeerConnection? = null
    private var signalingClient: SignalingClient? = null
    private var configuration: PeerConfiguration? = null
    private var observer: WebRtcPeerEngine.Observer? = null
    private var controlChannel: DataChannel? = null
    private var mediaChannel: DataChannel? = null
    private var remoteDescriptionSet = false
    private val pendingRemoteCandidates = ArrayDeque<IceCandidate>()
    private val pendingMedia = LatestFrameSlot()
    private var selectedRoute: PeerRoute? = null
    private var connectedReported = false
    private var routeResolutionFailed = false
    private var routeGeneration = 0L
    private var acceptCandidateRoutes = true
    private var startClaimed = false
    private var closed = false
    private var endOfCandidatesSent = false

    override fun start(
        configuration: PeerConfiguration,
        observer: WebRtcPeerEngine.Observer,
    ) {
        val signaling = configuration.signaling ?: throw IllegalArgumentException("Signaling configuration is required")
        val sessionCipher =
            configuration.sessionCipher
                ?: throw IllegalArgumentException(
                    "Application-record encryption is required for this Internet development preview",
                )
        require(sessionCipher.sessionEpoch == configuration.sessionEpoch) {
            "Session cipher epoch does not match PeerConfiguration"
        }
        synchronized(lock) {
            check(!closed) { "WebRTC engine is closed" }
            check(!startClaimed) { "WebRTC engine has already started" }
            startClaimed = true
            this.configuration = configuration
            this.observer = observer
        }

        try {
            AndroidWebRtcRuntime.ensureInitialized(applicationContext)
            val createdFactory = PeerConnectionFactory.builder().createPeerConnectionFactory()
            if (!synchronized(lock) { (!closed).also { if (it) factory = createdFactory } }) {
                createdFactory.dispose()
                throw IllegalStateException("WebRTC engine was closed while starting")
            }
            val rtcConfiguration =
                PeerConnection.RTCConfiguration(configuration.iceServers.map { it.toWebRtc() }).apply {
                    sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
                    continualGatheringPolicy = PeerConnection.ContinualGatheringPolicy.GATHER_CONTINUALLY
                    tcpCandidatePolicy = PeerConnection.TcpCandidatePolicy.ENABLED
                    iceTransportsType =
                        if (configuration.iceTransportPolicy == IceTransportPolicy.RELAY_ONLY) {
                            PeerConnection.IceTransportsType.RELAY
                        } else {
                            PeerConnection.IceTransportsType.ALL
                        }
                }
            val createdPeer =
                createdFactory.createPeerConnection(rtcConfiguration, PeerObserver())
                    ?: throw IllegalStateException("libwebrtc could not create a PeerConnection")
            if (!synchronized(lock) { (!closed).also { if (it) peerConnection = createdPeer } }) {
                createdPeer.close()
                createdPeer.dispose()
                throw IllegalStateException("WebRTC engine was closed while starting")
            }
            val createdSignaling = signalingClientFactory.create(signaling, configuration.sessionId)
            val installedSignaling =
                synchronized(lock) {
                    if (closed) {
                        false
                    } else {
                        signalingClient = createdSignaling
                        if (signaling.role == PeerRole.HOST) createLocalChannelsLocked(createdPeer)
                        true
                    }
                }
            if (!installedSignaling) {
                createdSignaling.close()
                throw IllegalStateException("WebRTC engine was closed while starting")
            }
            createdSignaling.start(this)
            statsExecutor.scheduleWithFixedDelay(::collectStatsSafely, STATS_INTERVAL_SECONDS, STATS_INTERVAL_SECONDS, TimeUnit.SECONDS)
            if (signaling.role == PeerRole.HOST) createOffer()
        } catch (failure: Throwable) {
            closeAfterStartFailure(failure)
            throw failure
        }
    }

    override fun sendControl(payload: ByteArray): Boolean {
        require(payload.size <= MAX_CONTROL_BYTES) { "Control payload exceeds $MAX_CONTROL_BYTES bytes" }
        val channel = synchronized(lock) { controlChannel.takeIf { !closed && it?.state() == DataChannel.State.OPEN } }
        return channel
            ?.takeIf { it.bufferedAmount() < CONTROL_BUFFER_HIGH_WATER_BYTES }
            ?.send(secureBuffer(SessionChannel.CONTROL, payload)) ?: false
    }

    override fun sendMedia(payload: ByteArray): Boolean {
        require(payload.size <= MAX_MEDIA_PACKET_BYTES) { "Media packet exceeds $MAX_MEDIA_PACKET_BYTES bytes" }
        val channel = synchronized(lock) { mediaChannel.takeIf { !closed && it?.state() == DataChannel.State.OPEN } } ?: return false
        val queued =
            synchronized(lock) {
                if (pendingMedia.hasPending() || channel.bufferedAmount() >= MEDIA_BUFFER_HIGH_WATER_BYTES) {
                    pendingMedia.replace(payload)
                    true
                } else {
                    false
                }
            }
        if (queued) {
            drainLatestMedia(channel)
            return true
        }
        return channel.send(secureBuffer(SessionChannel.MEDIA, payload))
    }

    override fun restartIce() {
        val activeConfiguration = synchronized(lock) { configuration.takeIf { !closed } }
            ?: throw IllegalStateException("WebRTC engine is not running")
        check(activeConfiguration.signaling?.supportsInSessionRenegotiation == true) {
            "The configured signaling service requires a fresh session for ICE restart"
        }
        val peer = synchronized(lock) { peerConnection.takeIf { !closed } }
            ?: throw IllegalStateException("WebRTC engine is not running")
        synchronized(lock) {
            routeGeneration++
            endOfCandidatesSent = false
            remoteDescriptionSet = false
            pendingRemoteCandidates.clear()
            selectedRoute = null
            routeResolutionFailed = false
            connectedReported = false
            acceptCandidateRoutes = false
        }
        routeResolutionTimeout.cancel()
        peer.restartIce()
        if (configuration?.signaling?.role == PeerRole.HOST) createOffer()
    }

    override fun applyVideoProfile(profile: VideoProfile) {
        synchronized(lock) { check(!closed) { "WebRTC engine is closed" } }
        videoProfileSink(profile)
    }

    override fun onOffer(sdp: String) {
        if (configuration?.signaling?.role != PeerRole.DEVICE) {
            fail(IllegalStateException("Host received an unexpected offer"))
            return
        }
        synchronized(lock) { remoteDescriptionSet = false }
        setRemoteDescription(SessionDescription(SessionDescription.Type.OFFER, sdp)) { createAnswer() }
    }

    override fun onAnswer(sdp: String) {
        if (configuration?.signaling?.role != PeerRole.HOST) {
            fail(IllegalStateException("Device received an unexpected answer"))
            return
        }
        synchronized(lock) { remoteDescriptionSet = false }
        setRemoteDescription(SessionDescription(SessionDescription.Type.ANSWER, sdp))
    }

    override fun onIceCandidate(candidate: SignalingIceCandidate) {
        val webRtcCandidate = IceCandidate(candidate.sdpMid, candidate.sdpMLineIndex, candidate.candidate)
        val peer = synchronized(lock) {
            if (closed) return
            if (!remoteDescriptionSet) {
                pendingRemoteCandidates.addLast(webRtcCandidate)
                return
            }
            peerConnection
        } ?: return
        if (!peer.addIceCandidate(webRtcCandidate)) fail(IllegalStateException("libwebrtc rejected a remote ICE candidate"))
    }

    override fun onEndOfCandidates() = Unit

    override fun onFailure(error: Throwable) = fail(error)

    override fun close() {
        val resources =
            synchronized(lock) {
                if (closed) return
                routeGeneration++
                closed = true
                val channels = listOfNotNull(controlChannel, mediaChannel).distinct()
                controlChannel = null
                mediaChannel = null
                pendingMedia.clear()
                pendingRemoteCandidates.clear()
                Resources(signalingClient, peerConnection, factory, configuration?.sessionCipher, channels)
                    .also {
                        signalingClient = null
                        peerConnection = null
                        factory = null
                        observer = null
                        configuration = null
                    }
            }
        routeResolutionTimeout.cancel()
        val cleanupActions =
            buildList<() -> Unit> {
                add { statsExecutor.shutdownNow() }
                resources.signaling?.let { signaling -> add { signaling.close() } }
                resources.channels.forEach { channel ->
                    add { channel.unregisterObserver() }
                    add { channel.close() }
                    add { channel.dispose() }
                }
                resources.peer?.let { peer ->
                    add { peer.close() }
                    add { peer.dispose() }
                }
                resources.factory?.let { factory -> add { factory.dispose() } }
                resources.sessionCipher?.let { cipher -> add { cipher.close() } }
            }
        runBestEffort(*cleanupActions.toTypedArray())
    }

    private fun createLocalChannelsLocked(peer: PeerConnection) {
        controlChannel = peer.createDataChannel(CONTROL_CHANNEL_LABEL, DataChannel.Init().apply { ordered = true })
            .also { registerChannel(it, isControl = true) }
        mediaChannel =
            peer.createDataChannel(
                MEDIA_CHANNEL_LABEL,
                DataChannel.Init().apply {
                    ordered = false
                    maxRetransmits = 0
                },
            ).also { registerChannel(it, isControl = false) }
    }

    private fun registerRemoteChannel(channel: DataChannel) {
        synchronized(lock) {
            when (channel.label()) {
                CONTROL_CHANNEL_LABEL -> {
                    if (controlChannel != null) {
                        channel.close()
                        return channel.dispose()
                    }
                    controlChannel = channel
                    registerChannel(channel, isControl = true)
                }
                MEDIA_CHANNEL_LABEL -> {
                    if (mediaChannel != null) {
                        channel.close()
                        return channel.dispose()
                    }
                    mediaChannel = channel
                    registerChannel(channel, isControl = false)
                }
                else -> {
                    channel.close()
                    channel.dispose()
                }
            }
        }
    }

    private fun registerChannel(
        channel: DataChannel,
        isControl: Boolean,
    ) {
        channel.registerObserver(
            object : DataChannel.Observer {
                override fun onBufferedAmountChange(previousAmount: Long) {
                    if (!isControl) drainLatestMedia(channel)
                }

                override fun onStateChange() {
                    if (channel.state() == DataChannel.State.OPEN) maybeReportConnected()
                }

                override fun onMessage(buffer: DataChannel.Buffer) {
                    if (!buffer.binary) return
                    val source = buffer.data.slice()
                    val maximumRecordBytes =
                        (if (isControl) MAX_CONTROL_BYTES else MAX_MEDIA_PACKET_BYTES) + MAX_RECORD_OVERHEAD_BYTES
                    if (source.remaining() !in MIN_RECORD_BYTES..maximumRecordBytes) {
                        fail(IllegalArgumentException("Inbound WebRTC data-channel record has an invalid size"))
                        return
                    }
                    val record = ByteArray(source.remaining()).also(source::get)
                    val session = synchronized(lock) { configuration.takeIf { !closed } } ?: return
                    val channelType = if (isControl) SessionChannel.CONTROL else SessionChannel.MEDIA
                    val payload = session.sessionCipher?.open(channelType, record) ?: return
                    val target = synchronized(lock) { observer.takeIf { !closed } } ?: return
                    if (isControl) target.onControlMessage(session.sessionEpoch, payload) else target.onMediaPacket(session.sessionEpoch, payload)
                }
            },
        )
    }

    private fun drainLatestMedia(channel: DataChannel) {
        val payload =
            synchronized(lock) {
                if (closed || channel.state() != DataChannel.State.OPEN || channel.bufferedAmount() >= MEDIA_BUFFER_LOW_WATER_BYTES) return
                pendingMedia.take()
            } ?: return
        if (!channel.send(secureBuffer(SessionChannel.MEDIA, payload))) {
            synchronized(lock) { pendingMedia.replace(payload) }
            scheduleMediaRetry(channel)
        }
    }

    private fun scheduleMediaRetry(channel: DataChannel) {
        if (statsExecutor.isShutdown) return
        statsExecutor.schedule({ drainLatestMedia(channel) }, MEDIA_RETRY_DELAY_MS, TimeUnit.MILLISECONDS)
    }

    private fun createOffer() = createDescription(isOffer = true)

    private fun createAnswer() = createDescription(isOffer = false)

    private fun createDescription(isOffer: Boolean) {
        val peer = synchronized(lock) { peerConnection.takeIf { !closed } } ?: return
        val callback =
            object : SdpAdapter() {
                override fun onCreateSuccess(description: SessionDescription) {
                    peer.setLocalDescription(
                        object : SdpAdapter() {
                            override fun onSetSuccess() {
                                val signaling = synchronized(lock) { signalingClient.takeIf { !closed } } ?: return
                                if (isOffer) signaling.sendOffer(description.description) else signaling.sendAnswer(description.description)
                            }

                            override fun onSetFailure(error: String) = fail(IllegalStateException("Set local SDP failed: $error"))
                        },
                        description,
                    )
                }

                override fun onCreateFailure(error: String) = fail(IllegalStateException("Create SDP failed: $error"))
            }
        if (isOffer) peer.createOffer(callback, MediaConstraints()) else peer.createAnswer(callback, MediaConstraints())
    }

    private fun setRemoteDescription(
        description: SessionDescription,
        onSuccess: () -> Unit = {},
    ) {
        val peer = synchronized(lock) { peerConnection.takeIf { !closed } } ?: return
        peer.setRemoteDescription(
            object : SdpAdapter() {
                override fun onSetSuccess() {
                    val candidates = synchronized(lock) {
                        remoteDescriptionSet = true
                        buildList { while (pendingRemoteCandidates.isNotEmpty()) add(pendingRemoteCandidates.removeFirst()) }
                    }
                    candidates.forEach { if (!peer.addIceCandidate(it)) fail(IllegalStateException("libwebrtc rejected a queued ICE candidate")) }
                    onSuccess()
                }

                override fun onSetFailure(error: String) = fail(IllegalStateException("Set remote SDP failed: $error"))
            },
            description,
        )
    }

    private fun maybeReportConnected() {
        val report =
            synchronized(lock) {
                if (!isReadyForRouteResolutionLocked() || connectedReported) return
                val route = selectedRoute
                if (route == null) {
                    // Arm while holding the same state lock used by the candidate
                    // callback. A late route therefore cannot cancel and then be
                    // followed by a stale arm from this readiness observation.
                    val generation = routeGeneration
                    routeResolutionTimeout.arm { routeResolutionTimedOut(generation) }
                    null
                } else {
                    connectedReported = true
                    observer to route
                }
            }
        if (report != null) routeResolutionTimeout.cancel()
        report?.first?.onConnected(report.second)
    }

    private fun isReadyForRouteResolutionLocked(): Boolean =
        !closed &&
            !routeResolutionFailed &&
            peerConnection?.connectionState() == PeerConnection.PeerConnectionState.CONNECTED &&
            controlChannel?.state() == DataChannel.State.OPEN &&
            mediaChannel?.state() == DataChannel.State.OPEN

    private fun routeResolutionTimedOut(generation: Long) {
        val shouldFail =
            synchronized(lock) {
                if (
                    generation != routeGeneration ||
                    !isReadyForRouteResolutionLocked() ||
                    connectedReported ||
                    selectedRoute != null
                ) {
                    false
                } else {
                    routeResolutionFailed = true
                    true
                }
            }
        if (shouldFail) {
            fail(IllegalStateException("WebRTC connected without a selected candidate route before the deadline"))
        }
    }

    private fun fail(error: Throwable) {
        val target =
            synchronized(lock) {
                routeGeneration++
                routeResolutionFailed = true
                acceptCandidateRoutes = false
                selectedRoute = null
                connectedReported = false
                observer.takeIf { !closed }
            }
        routeResolutionTimeout.cancel()
        target ?: return
        target.onFailure(error)
        target.onDisconnected()
    }

    private fun collectStatsSafely() {
        val peer = synchronized(lock) { peerConnection.takeIf { !closed } } ?: return
        peer.getStats { report ->
            val stats = WebRtcStatsParser.parse(report) ?: return@getStats
            synchronized(lock) { observer.takeIf { !closed } }?.onStats(stats)
        }
    }

    private inner class PeerObserver : PeerConnection.Observer {
        override fun onConnectionChange(state: PeerConnection.PeerConnectionState) {
            when (state) {
                PeerConnection.PeerConnectionState.CONNECTING -> synchronized(lock) { acceptCandidateRoutes = true }
                PeerConnection.PeerConnectionState.CONNECTED -> {
                    synchronized(lock) { acceptCandidateRoutes = true }
                    maybeReportConnected()
                }
                PeerConnection.PeerConnectionState.DISCONNECTED,
                PeerConnection.PeerConnectionState.CLOSED,
                -> {
                    val target =
                        synchronized(lock) {
                            routeGeneration++
                            connectedReported = false
                            selectedRoute = null
                            routeResolutionFailed = false
                            acceptCandidateRoutes = false
                            observer.takeIf { !closed }
                        }
                    routeResolutionTimeout.cancel()
                    target?.onDisconnected()
                }
                PeerConnection.PeerConnectionState.FAILED -> fail(IllegalStateException("WebRTC ICE/DTLS connection failed"))
                else -> Unit
            }
        }

        override fun onSelectedCandidatePairChanged(event: CandidatePairChangeEvent) {
            val route = if (event.local.sdp.contains(" typ relay ") || event.remote.sdp.contains(" typ relay ")) PeerRoute.RELAY else PeerRoute.DIRECT
            val target =
                synchronized(lock) {
                    if (!acceptCandidateRoutes || closed || routeResolutionFailed) return
                    val changed = route != selectedRoute
                    selectedRoute = route
                    observer.takeIf { changed && connectedReported && !closed && !routeResolutionFailed }
                }
            routeResolutionTimeout.cancel()
            // Candidate-pair selection may arrive after ICE and both negotiated
            // channels are already open. Re-evaluate readiness so the initial
            // connection event cannot be lost to callback ordering.
            maybeReportConnected()
            target?.onRouteChanged(route)
        }

        override fun onIceCandidate(candidate: IceCandidate) {
            synchronized(lock) { signalingClient.takeIf { !closed } }
                ?.sendIceCandidate(
                    SignalingIceCandidate(
                        candidate.sdp,
                        candidate.sdpMid,
                        candidate.sdpMLineIndex,
                        candidate.sdp.extractUsernameFragment(),
                    ),
                )
        }

        override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) {
            if (state == PeerConnection.IceGatheringState.COMPLETE) {
                val shouldSend = synchronized(lock) { (!endOfCandidatesSent).also { endOfCandidatesSent = true } }
                if (shouldSend) synchronized(lock) { signalingClient.takeIf { !closed } }?.sendEndOfCandidates()
            }
        }

        override fun onDataChannel(channel: DataChannel) = registerRemoteChannel(channel)
        override fun onRenegotiationNeeded() = Unit
        override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
        override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) = Unit
        override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
        override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) = Unit
        override fun onAddStream(stream: MediaStream) = Unit
        override fun onRemoveStream(stream: MediaStream) = Unit
        override fun onAddTrack(receiver: RtpReceiver, mediaStreams: Array<out MediaStream>) = Unit
    }

    private open inner class SdpAdapter : SdpObserver {
        override fun onCreateSuccess(description: SessionDescription) = Unit
        override fun onSetSuccess() = Unit
        override fun onCreateFailure(error: String) = fail(IllegalStateException(error))
        override fun onSetFailure(error: String) = fail(IllegalStateException(error))
    }

    private fun IceServer.toWebRtc(): PeerConnection.IceServer =
        PeerConnection.IceServer.builder(urls).apply {
            username?.let(::setUsername)
            credential?.let(::setPassword)
        }.createIceServer()

    private fun String.extractUsernameFragment(): String? =
        split(' ')
            .windowed(2)
            .firstOrNull { it[0] == "ufrag" }
            ?.get(1)

    private fun secureBuffer(
        channel: SessionChannel,
        payload: ByteArray,
    ): DataChannel.Buffer {
        val cipher = synchronized(lock) { configuration?.sessionCipher.takeIf { !closed } }
            ?: throw IllegalStateException("WebRTC engine is not running")
        return DataChannel.Buffer(java.nio.ByteBuffer.wrap(cipher.seal(channel, payload)), true)
    }

    private data class Resources(
        val signaling: SignalingClient?,
        val peer: PeerConnection?,
        val factory: PeerConnectionFactory?,
        val sessionCipher: SessionPacketCipher?,
        val channels: List<DataChannel>,
    )

    private fun closeAfterStartFailure(failure: Throwable) {
        try {
            close()
        } catch (closeFailure: Throwable) {
            failure.addSuppressed(closeFailure)
        }
    }

    companion object {
        internal const val CONTROL_CHANNEL_LABEL = "vibescreen.control.v1"
        internal const val MEDIA_CHANNEL_LABEL = "vibescreen.media.v1"
        private const val MAX_CONTROL_BYTES = 1_048_576
        private const val MAX_MEDIA_PACKET_BYTES = 4_194_304
        private const val MAX_RECORD_OVERHEAD_BYTES = 256
        private const val MIN_RECORD_BYTES = 16
        private const val CONTROL_BUFFER_HIGH_WATER_BYTES = 1_048_576L
        private const val MEDIA_BUFFER_LOW_WATER_BYTES = 131_072L
        private const val MEDIA_BUFFER_HIGH_WATER_BYTES = 524_288L
        private const val STATS_INTERVAL_SECONDS = 2L
        private const val MEDIA_RETRY_DELAY_MS = 50L
        internal const val ROUTE_RESOLUTION_TIMEOUT_MS = 5_000L
    }
}
