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

/** libwebrtc-backed production adapter for Protocol v1 Internet data channels. */
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
    override val dataChannelSemantics: Map<WebRtcDataChannelKind, DataChannelSemantics> =
        WebRtcDataChannelKind.entries.associateWith { it.semantics }

    private val applicationContext = context.applicationContext
    private val lock = Any()
    private val channelObserverLifecycle = Any()
    private val sendLinearizer = PeerSendLinearizer()
    private val statsExecutor: ScheduledExecutorService =
        Executors.newSingleThreadScheduledExecutor { runnable ->
            Thread(runnable, "vibe-webrtc-stats").apply { isDaemon = true }
        }
    private val mediaRetryGate =
        PeerMediaRetryGate<PeerMediaRetryKey>(
            PeerRetryScheduler { task ->
                val future = statsExecutor.schedule(task, MEDIA_RETRY_DELAY_MS, TimeUnit.MILLISECONDS)
                PeerRetryCancellation { future.cancel(false) }
            },
        )
    private val audioRetryGate =
        PeerMediaRetryGate<PeerMediaRetryKey>(
            PeerRetryScheduler { task ->
                val future = statsExecutor.schedule(task, AUDIO_RETRY_DELAY_MS, TimeUnit.MILLISECONDS)
                PeerRetryCancellation { future.cancel(false) }
            },
        )
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
    private var audioChannel: DataChannel? = null
    private var bulkChannel: DataChannel? = null
    private var remoteDescriptionSet = false
    private val pendingRemoteCandidates = ArrayDeque<IceCandidate>()
    private val mediaBatches = LatestFrameBatchQueue()
    private val audioRecords = LatestFrameBatchQueue()
    private var selectedRoute: PeerRoute? = null
    private var connectedReported = false
    private var routeResolutionFailed = false
    private var routeGeneration = 0L
    private var acceptCandidateRoutes = true
    private var startClaimed = false
    private var closed = false
    private var endOfCandidatesSent = false
    private var connectionFailureReported = false

    private sealed class RestartPreparation {
        data class Ready(val snapshot: PeerRestartSnapshot) : RestartPreparation()

        data class RequiresFreshSession(val reason: String) : RestartPreparation()

        data class Failed(val reason: String) : RestartPreparation()
    }

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
            val webRtcIceServers =
                try {
                    configuration.iceServers.map { it.toWebRtc() }
                } finally {
                    configuration.iceServers.forEach(IceServer::close)
                }
            val rtcConfiguration =
                PeerConnection.RTCConfiguration(webRtcIceServers).apply {
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
        return sendLinearizer.sendControl(
            snapshot = {
                synchronized(lock) {
                    val channel = controlChannel
                    val cipher = configuration?.sessionCipher
                    if (
                        closed ||
                        !connectedReported ||
                        routeResolutionFailed ||
                        selectedRoute == null ||
                        channel == null ||
                        cipher == null ||
                        channel.state() != DataChannel.State.OPEN ||
                        channel.bufferedAmount() >= CONTROL_BUFFER_HIGH_WATER_BYTES
                    ) {
                        null
                    } else {
                        PeerControlSendSnapshot(channel, cipher, routeGeneration)
                    }
                }
            },
            seal = { cipher -> cipher.seal(SessionChannel.CONTROL, payload) },
            isCurrent = { candidate ->
                synchronized(lock) {
                    !closed &&
                        connectedReported &&
                        !routeResolutionFailed &&
                        selectedRoute != null &&
                        routeGeneration == candidate.generation &&
                        controlChannel === candidate.channel &&
                        configuration?.sessionCipher === candidate.cipher &&
                        candidate.channel.state() == DataChannel.State.OPEN &&
                        candidate.channel.bufferedAmount() < CONTROL_BUFFER_HIGH_WATER_BYTES
                }
            },
            transmit = { channel, record ->
                channel.send(DataChannel.Buffer(java.nio.ByteBuffer.wrap(record), true))
            },
        )
    }

    override fun sendMedia(frame: OutboundMediaFrame): Boolean {
        val snapshot =
            sendLinearizer.withGate {
                synchronized(lock) {
                    currentLatestRecordPathLocked(WebRtcDataChannelKind.MEDIA)?.also { mediaBatches.offer(frame) }
                }
            } ?: return false
        return drainLatestRecords(snapshot, WebRtcDataChannelKind.MEDIA, mediaBatches)
    }

    override fun sendAudioRecord(payload: ByteArray): Boolean {
        require(payload.isNotEmpty()) { "Audio transport record must not be empty" }
        require(payload.size <= InternetAudioRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES) {
            "Audio transport record exceeds ${InternetAudioRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES} bytes"
        }
        val snapshot =
            sendLinearizer.withGate {
                synchronized(lock) {
                    currentLatestRecordPathLocked(WebRtcDataChannelKind.AUDIO)?.also {
                        audioRecords.offer(OutboundMediaFrame.single(payload))
                    }
                }
            } ?: return false
        return drainLatestRecords(snapshot, WebRtcDataChannelKind.AUDIO, audioRecords)
    }

    override fun sendBulkRecord(payload: ByteArray): Boolean {
        require(payload.isNotEmpty()) { "Bulk transport record must not be empty" }
        require(payload.size <= InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES) {
            "Bulk transport record exceeds ${InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES} bytes"
        }
        return sendLinearizer.sendControl(
            snapshot = {
                synchronized(lock) {
                    val channel = bulkChannel
                    val cipher = configuration?.sessionCipher
                    if (
                        closed ||
                        !connectedReported ||
                        routeResolutionFailed ||
                        selectedRoute == null ||
                        channel == null ||
                        cipher == null ||
                        channel.state() != DataChannel.State.OPEN ||
                        channel.bufferedAmount() >= BULK_BUFFER_HIGH_WATER_BYTES
                    ) {
                        null
                    } else {
                        PeerControlSendSnapshot(channel, cipher, routeGeneration)
                    }
                }
            },
            seal = { cipher -> cipher.seal(SessionChannel.BULK, payload) },
            isCurrent = { candidate ->
                synchronized(lock) {
                    !closed &&
                        connectedReported &&
                        !routeResolutionFailed &&
                        selectedRoute != null &&
                        routeGeneration == candidate.generation &&
                        bulkChannel === candidate.channel &&
                        configuration?.sessionCipher === candidate.cipher &&
                        candidate.channel.state() == DataChannel.State.OPEN &&
                        candidate.channel.bufferedAmount() < BULK_BUFFER_HIGH_WATER_BYTES
                }
            },
            transmit = { channel, record ->
                channel.send(DataChannel.Buffer(java.nio.ByteBuffer.wrap(record), true))
            },
        )
    }

    override fun restartIce(): WebRtcIceRestartResult {
        val preparation: RestartPreparation =
            try {
                sendLinearizer.withGate {
                    val restartPreparation = synchronized(lock) {
                        val activeConfiguration = configuration.takeIf { !closed }
                            ?: return@withGate RestartPreparation.Failed("WebRTC engine is not running")
                        val signaling = activeConfiguration.signaling
                            ?: return@withGate RestartPreparation.RequiresFreshSession(
                                "The configured signaling service requires a fresh session for ICE restart",
                            )
                        if (!signaling.supportsInSessionRenegotiation) {
                            return@withGate RestartPreparation.RequiresFreshSession(
                                "The configured signaling service requires a fresh session for ICE restart",
                            )
                        }
                        val activePeer = peerConnection.takeIf { !closed }
                            ?: return@withGate RestartPreparation.Failed("WebRTC engine is not running")
                        routeGeneration++
                        mediaBatches.clear()
                        audioRecords.clear()
                        endOfCandidatesSent = false
                        remoteDescriptionSet = false
                        pendingRemoteCandidates.clear()
                        selectedRoute = null
                        routeResolutionFailed = false
                        connectedReported = false
                        connectionFailureReported = false
                        acceptCandidateRoutes = false
                        RestartPreparation.Ready(
                            PeerRestartSnapshot(
                                activePeer,
                                routeGeneration,
                                signaling.role == PeerRole.HOST,
                                channelObserverBindingsLocked(routeGeneration),
                            ),
                        )
                    }
                    mediaRetryGate.cancel()
                    audioRetryGate.cancel()
                    restartPreparation
                }
            } catch (failure: Throwable) {
                return WebRtcIceRestartResult.Failed(failure.message ?: "ICE restart failed")
            }
        val restart =
            when (preparation) {
                is RestartPreparation.Ready -> preparation.snapshot
                is RestartPreparation.RequiresFreshSession -> return WebRtcIceRestartResult.RequiresFreshSession(preparation.reason)
                is RestartPreparation.Failed -> return WebRtcIceRestartResult.Failed(preparation.reason)
            }
        routeResolutionTimeout.cancel()
        try {
            rebindChannelObservers(restart.observerBindings)
        } catch (failure: Throwable) {
            return WebRtcIceRestartResult.Failed(failure.message ?: "ICE restart failed")
        }
        val shouldCreateOffer =
            try {
                sendLinearizer.withGate {
                    val current =
                        synchronized(lock) {
                            !closed &&
                                routeGeneration == restart.generation &&
                                peerConnection === restart.peer
                        }
                    check(current) { "WebRTC engine changed before ICE restart" }
                    restart.peer.restartIce()
                    synchronized(lock) {
                        !closed &&
                            routeGeneration == restart.generation &&
                            peerConnection === restart.peer &&
                            restart.shouldCreateOffer
                    }
                }
            } catch (failure: Throwable) {
                return WebRtcIceRestartResult.Failed(failure.message ?: "ICE restart failed")
            }
        if (shouldCreateOffer) createOffer()
        return WebRtcIceRestartResult.Started
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
            sendLinearizer.withGate {
                val detached = synchronized(lock) {
                    if (closed) {
                        null
                    } else {
                        routeGeneration++
                        closed = true
                        val channels =
                            listOfNotNull(controlChannel, mediaChannel, audioChannel, bulkChannel).distinct()
                        controlChannel = null
                        mediaChannel = null
                        audioChannel = null
                        bulkChannel = null
                        mediaBatches.clear()
                        audioRecords.clear()
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
                }
                if (detached != null) {
                    mediaRetryGate.cancel()
                    audioRetryGate.cancel()
                }
                detached
            } ?: return
        routeResolutionTimeout.cancel()
        val cleanupActions =
            buildList<() -> Unit> {
                add { statsExecutor.shutdownNow() }
                resources.signaling?.let { signaling -> add { signaling.close() } }
                resources.channels.forEach { channel ->
                    add {
                        synchronized(channelObserverLifecycle) {
                            runBestEffort(
                                { channel.unregisterObserver() },
                                { channel.close() },
                                { channel.dispose() },
                            )
                        }
                    }
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
        WebRtcDataChannelKind.entries.forEach { kind ->
            val channel =
                peer.createDataChannel(
                    kind.label,
                    DataChannel.Init().apply {
                        ordered = kind.ordered
                        maxRetransmits = kind.maxRetransmits ?: -1
                    },
                )
            setChannelLocked(kind, channel)
            registerChannel(channel, kind = kind, generation = routeGeneration)
        }
    }

    private fun registerRemoteChannel(channel: DataChannel) {
        synchronized(lock) {
            if (closed) {
                channel.close()
                return channel.dispose()
            }
            val kind = WebRtcDataChannelKind.fromLabel(channel.label())
            if (kind == null || channelForKindLocked(kind) != null) {
                channel.close()
                return channel.dispose()
            }
            setChannelLocked(kind, channel)
            registerChannel(channel, kind = kind, generation = routeGeneration)
        }
    }

    private fun registerChannel(
        channel: DataChannel,
        kind: WebRtcDataChannelKind,
        generation: Long,
    ) {
        val callbackSource = PeerInboundCallbackSource(channel, generation)
        channel.registerObserver(
            object : DataChannel.Observer {
                override fun onBufferedAmountChange(previousAmount: Long) {
                    if (kind == WebRtcDataChannelKind.MEDIA || kind == WebRtcDataChannelKind.AUDIO) {
                        val snapshot =
                            sendLinearizer.withGate {
                                synchronized(lock) {
                                    currentLatestRecordPathLocked(kind, channel)
                                        ?.takeIf { it.generation == callbackSource.generation }
                                }
                            }
                        if (snapshot != null) drainLatestRecords(snapshot, kind, kind.latestQueue)
                    }
                }

                override fun onStateChange() {
                    val isCurrent =
                        synchronized(lock) {
                            routeGeneration == callbackSource.generation &&
                                channelForKindLocked(kind) === callbackSource.channel
                        }
                    if (isCurrent && channel.state() == DataChannel.State.OPEN) maybeReportConnected()
                }

                override fun onMessage(buffer: DataChannel.Buffer) {
                    if (!buffer.binary) return
                    sendLinearizer.receiveInbound(
                        snapshot = {
                            synchronized(lock) {
                                currentInboundPathLocked(callbackSource, kind)
                            }
                        },
                        decode = { cipher ->
                            val source = buffer.data.slice()
                            val maximumRecordBytes = kind.maximumEncryptedRecordBytes
                            require(source.remaining() in MIN_RECORD_BYTES..maximumRecordBytes) {
                                "Inbound WebRTC data-channel record has an invalid size"
                            }
                            val record = ByteArray(source.remaining()).also(source::get)
                            cipher.open(kind.sessionChannel, record)
                        },
                        isCurrent = { candidate ->
                            synchronized(lock) { isCurrentInboundPathLocked(candidate, kind) }
                        },
                        onDecodeFailure = ::fail,
                    ) { target, sessionEpoch, payload ->
                        when (kind) {
                            WebRtcDataChannelKind.CONTROL -> target.onControlMessage(sessionEpoch, payload)
                            WebRtcDataChannelKind.MEDIA -> target.onMediaPacket(sessionEpoch, payload)
                            WebRtcDataChannelKind.AUDIO -> target.onAudioRecord(sessionEpoch, payload)
                            WebRtcDataChannelKind.BULK -> target.onBulkRecord(sessionEpoch, payload)
                        }
                    }
                }
            },
        )
    }

    private fun rebindChannelObservers(bindings: List<ChannelObserverBinding>) {
        synchronized(channelObserverLifecycle) {
            bindings.forEach { binding ->
                val isCurrent =
                    synchronized(lock) {
                        !closed &&
                            routeGeneration == binding.source.generation &&
                            channelForKindLocked(binding.kind) === binding.source.channel
                    }
                if (isCurrent) {
                    registerChannel(
                        binding.source.channel,
                        binding.kind,
                        binding.source.generation,
                    )
                }
            }
        }
    }

    private fun channelObserverBindingsLocked(generation: Long): List<ChannelObserverBinding> =
        buildList {
            WebRtcDataChannelKind.entries.forEach { kind ->
                channelForKindLocked(kind)?.let {
                    add(ChannelObserverBinding(PeerInboundCallbackSource(it, generation), kind))
                }
            }
        }

    private fun currentInboundPathLocked(
        callbackSource: PeerInboundCallbackSource<DataChannel>,
        kind: WebRtcDataChannelKind,
    ): PeerInboundReceiveSnapshot<DataChannel, SessionPacketCipher, WebRtcPeerEngine.Observer>? {
        val session = configuration
        val cipher = session?.sessionCipher
        val target = observer
        val expectedChannel = channelForKindLocked(kind)
        return if (
            closed ||
            !connectedReported ||
            routeResolutionFailed ||
            selectedRoute == null ||
            routeGeneration != callbackSource.generation ||
            expectedChannel !== callbackSource.channel ||
            session == null ||
            cipher == null ||
            target == null ||
            peerConnection?.connectionState() != PeerConnection.PeerConnectionState.CONNECTED ||
            callbackSource.channel.state() != DataChannel.State.OPEN
        ) {
            null
        } else {
            PeerInboundReceiveSnapshot(callbackSource, cipher, target, session.sessionEpoch)
        }
    }

    private fun isCurrentInboundPathLocked(
        snapshot: PeerInboundReceiveSnapshot<DataChannel, SessionPacketCipher, WebRtcPeerEngine.Observer>,
        kind: WebRtcDataChannelKind,
    ): Boolean {
        val expectedChannel = channelForKindLocked(kind)
        return !closed &&
            connectedReported &&
            !routeResolutionFailed &&
            selectedRoute != null &&
            routeGeneration == snapshot.generation &&
            expectedChannel === snapshot.channel &&
            configuration?.sessionCipher === snapshot.cipher &&
            configuration?.sessionEpoch == snapshot.sessionEpoch &&
            observer === snapshot.target &&
            peerConnection?.connectionState() == PeerConnection.PeerConnectionState.CONNECTED &&
            snapshot.channel.state() == DataChannel.State.OPEN
    }

    private fun drainLatestRecords(
        initialSnapshot: PeerMediaSendSnapshot<DataChannel, SessionPacketCipher>,
        kind: WebRtcDataChannelKind,
        queue: LatestFrameBatchQueue,
    ): Boolean {
        var snapshot = initialSnapshot
        while (true) {
            val outcome =
                try {
                    sendLinearizer.withCurrentMediaPath(
                        snapshot = { synchronized(lock) { currentLatestRecordPathLocked(kind, snapshot.channel) } },
                        isCurrent = { candidate -> synchronized(lock) { isCurrentLatestRecordPathLocked(candidate, kind) } },
                    ) { candidate ->
                        if (candidate.channel.bufferedAmount() >= kind.bufferLowWaterBytes) {
                            MediaDrainOutcome.BLOCKED
                        } else {
                            val accepted =
                                queue.sendNext { payload ->
                                    candidate.channel.send(secureBuffer(candidate.cipher, kind.sessionChannel, payload))
                                }
                            when (accepted) {
                                null -> MediaDrainOutcome.EMPTY
                                true -> MediaDrainOutcome.ACCEPTED
                                false -> MediaDrainOutcome.RETRY
                            }
                        }
                    } ?: MediaDrainOutcome.STALE
                } catch (failure: Throwable) {
                    fail(failure)
                    return false
                }
            when (outcome) {
                MediaDrainOutcome.ACCEPTED -> {
                    val current = synchronized(lock) { currentLatestRecordPathLocked(kind, snapshot.channel) }
                        ?: return false
                    snapshot = current
                }
                MediaDrainOutcome.BLOCKED,
                MediaDrainOutcome.RETRY,
                -> {
                    scheduleLatestRecordRetry(snapshot, kind)
                    return true
                }
                MediaDrainOutcome.EMPTY -> return true
                MediaDrainOutcome.STALE -> {
                    sendLinearizer.withGate { queue.clear() }
                    return false
                }
            }
        }
    }

    private fun scheduleLatestRecordRetry(
        snapshot: PeerMediaSendSnapshot<DataChannel, SessionPacketCipher>,
        kind: WebRtcDataChannelKind,
    ) {
        try {
            sendLinearizer.withGate {
                val isCurrent = synchronized(lock) { isCurrentLatestRecordPathLocked(snapshot, kind) }
                if (!isCurrent || statsExecutor.isShutdown) return@withGate
                kind.retryGate.schedule(PeerMediaRetryKey(snapshot.channel, snapshot.generation)) { retry ->
                    val current =
                        synchronized(lock) {
                            currentLatestRecordPathLocked(kind, retry.channel)
                                ?.takeIf { it.generation == retry.generation }
                        }
                    if (current != null) drainLatestRecords(current, kind, kind.latestQueue)
                }
            }
        } catch (failure: Throwable) {
            if (!statsExecutor.isShutdown) fail(failure)
        }
    }

    private fun currentLatestRecordPathLocked(
        kind: WebRtcDataChannelKind,
        channel: DataChannel? = channelForKindLocked(kind),
    ): PeerMediaSendSnapshot<DataChannel, SessionPacketCipher>? {
        val cipher = configuration?.sessionCipher
        return if (
            closed ||
            !connectedReported ||
            routeResolutionFailed ||
            selectedRoute == null ||
            channel == null ||
            channelForKindLocked(kind) !== channel ||
            cipher == null ||
            channel.state() != DataChannel.State.OPEN
        ) {
            null
        } else {
            PeerMediaSendSnapshot(channel, cipher, routeGeneration)
        }
    }

    private fun isCurrentLatestRecordPathLocked(
        snapshot: PeerMediaSendSnapshot<DataChannel, SessionPacketCipher>,
        kind: WebRtcDataChannelKind,
    ): Boolean =
        !closed &&
            connectedReported &&
            !routeResolutionFailed &&
            selectedRoute != null &&
            routeGeneration == snapshot.generation &&
            channelForKindLocked(kind) === snapshot.channel &&
            configuration?.sessionCipher === snapshot.cipher &&
            snapshot.channel.state() == DataChannel.State.OPEN

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
            WebRtcDataChannelKind.entries.all { kind ->
                channelForKindLocked(kind)?.state() == DataChannel.State.OPEN
            }

    private fun routeResolutionTimedOut(generation: Long) {
        val shouldFail =
            sendLinearizer.withGate {
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
            }
        if (shouldFail) {
            fail(IllegalStateException("WebRTC connected without a selected candidate route before the deadline"))
        }
    }

    private fun fail(error: Throwable) {
        val target =
            sendLinearizer.withGate {
                val failedTarget = synchronized(lock) {
                    routeGeneration++
                    routeResolutionFailed = true
                    acceptCandidateRoutes = false
                    selectedRoute = null
                    connectedReported = false
                    mediaBatches.clear()
                    audioRecords.clear()
                    observer.takeIf { !closed }
                }
                mediaRetryGate.cancel()
                audioRetryGate.cancel()
                failedTarget
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
                PeerConnection.PeerConnectionState.CONNECTING -> synchronized(lock) {
                    connectionFailureReported = false
                    acceptCandidateRoutes = true
                }
                PeerConnection.PeerConnectionState.CONNECTED -> {
                    synchronized(lock) {
                        connectionFailureReported = false
                        acceptCandidateRoutes = true
                    }
                    maybeReportConnected()
                }
                PeerConnection.PeerConnectionState.DISCONNECTED,
                PeerConnection.PeerConnectionState.CLOSED,
                -> {
                    val transition =
                        sendLinearizer.withGate {
                            val snapshot = synchronized(lock) {
                                routeGeneration++
                                connectedReported = false
                                selectedRoute = null
                                routeResolutionFailed = false
                                acceptCandidateRoutes = false
                                mediaBatches.clear()
                                audioRecords.clear()
                                PeerDisconnectSnapshot(
                                    observer.takeIf { !closed },
                                    channelObserverBindingsLocked(routeGeneration),
                                )
                            }
                            mediaRetryGate.cancel()
                            audioRetryGate.cancel()
                            snapshot
                        }
                    routeResolutionTimeout.cancel()
                    try {
                        rebindChannelObservers(transition.observerBindings)
                    } catch (failure: Throwable) {
                        fail(failure)
                        return
                    }
                    transition.target?.onDisconnected()
                }
                PeerConnection.PeerConnectionState.FAILED -> {
                    val transition = disconnectForFailureRecovery()
                    transition.target?.onConnectionFailed("WebRTC ICE/DTLS connection failed")
                }
                else -> Unit
            }
        }

        private fun disconnectForRecovery(): PeerDisconnectSnapshot {
            val transition =
                sendLinearizer.withGate {
                    val snapshot = synchronized(lock) {
                        routeGeneration++
                        connectedReported = false
                        selectedRoute = null
                        routeResolutionFailed = false
                        acceptCandidateRoutes = false
                        mediaBatches.clear()
                        audioRecords.clear()
                        PeerDisconnectSnapshot(
                            observer.takeIf { !closed },
                            channelObserverBindingsLocked(routeGeneration),
                        )
                    }
                    mediaRetryGate.cancel()
                    audioRetryGate.cancel()
                    snapshot
                }
            routeResolutionTimeout.cancel()
            try {
                rebindChannelObservers(transition.observerBindings)
            } catch (failure: Throwable) {
                fail(failure)
                return PeerDisconnectSnapshot(null, emptyList())
            }
            return transition
        }

        private fun disconnectForFailureRecovery(): PeerDisconnectSnapshot {
            val shouldReport = synchronized(lock) {
                (!connectionFailureReported).also { if (it) connectionFailureReported = true }
            }
            if (!shouldReport) return PeerDisconnectSnapshot(null, emptyList())
            return disconnectForRecovery()
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
        override fun onRenegotiationNeeded() {
            val shouldCreateOffer =
                synchronized(lock) {
                    !closed &&
                        configuration?.signaling?.role == PeerRole.HOST &&
                        configuration?.signaling?.supportsInSessionRenegotiation == true
                }
            if (shouldCreateOffer) createOffer()
        }
        override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
        override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
            if (state == PeerConnection.IceConnectionState.FAILED) {
                val transition = disconnectForFailureRecovery()
                transition.target?.onConnectionFailed("WebRTC ICE connection failed")
            }
        }
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

    private fun IceServer.toWebRtc(): PeerConnection.IceServer {
        val builder = PeerConnection.IceServer.builder(urls)
        usernameSecret?.withString(builder::setUsername)
        credentialSecret?.withString(builder::setPassword)
        return builder.createIceServer()
    }

    private fun String.extractUsernameFragment(): String? =
        split(' ')
            .windowed(2)
            .firstOrNull { it[0] == "ufrag" }
            ?.get(1)

    private fun secureBuffer(
        cipher: SessionPacketCipher,
        channel: SessionChannel,
        payload: ByteArray,
    ): DataChannel.Buffer {
        val record = cipher.seal(channel, payload)
        val maximumRecordBytes = WebRtcDataChannelKind.entries.first { it.sessionChannel == channel }.maximumEncryptedRecordBytes
        require(record.size <= maximumRecordBytes) {
            "Encrypted ${channel.name.lowercase()} record exceeds $maximumRecordBytes bytes"
        }
        return DataChannel.Buffer(java.nio.ByteBuffer.wrap(record), true)
    }

    private fun channelForKindLocked(kind: WebRtcDataChannelKind): DataChannel? =
        when (kind) {
            WebRtcDataChannelKind.CONTROL -> controlChannel
            WebRtcDataChannelKind.MEDIA -> mediaChannel
            WebRtcDataChannelKind.AUDIO -> audioChannel
            WebRtcDataChannelKind.BULK -> bulkChannel
        }

    private fun setChannelLocked(
        kind: WebRtcDataChannelKind,
        channel: DataChannel?,
    ) {
        when (kind) {
            WebRtcDataChannelKind.CONTROL -> controlChannel = channel
            WebRtcDataChannelKind.MEDIA -> mediaChannel = channel
            WebRtcDataChannelKind.AUDIO -> audioChannel = channel
            WebRtcDataChannelKind.BULK -> bulkChannel = channel
        }
    }

    private enum class MediaDrainOutcome {
        ACCEPTED,
        BLOCKED,
        EMPTY,
        RETRY,
        STALE,
    }

    private data class Resources(
        val signaling: SignalingClient?,
        val peer: PeerConnection?,
        val factory: PeerConnectionFactory?,
        val sessionCipher: SessionPacketCipher?,
        val channels: List<DataChannel>,
    )

    private data class PeerRestartSnapshot(
        val peer: PeerConnection,
        val generation: Long,
        val shouldCreateOffer: Boolean,
        val observerBindings: List<ChannelObserverBinding>,
    )

    private data class PeerDisconnectSnapshot(
        val target: WebRtcPeerEngine.Observer?,
        val observerBindings: List<ChannelObserverBinding>,
    )

    private data class ChannelObserverBinding(
        val source: PeerInboundCallbackSource<DataChannel>,
        val kind: WebRtcDataChannelKind,
    )

    private data class PeerMediaRetryKey(
        val channel: DataChannel,
        val generation: Long,
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
        internal const val AUDIO_CHANNEL_LABEL = "vibescreen.audio.v1"
        internal const val BULK_CHANNEL_LABEL = "vibescreen.bulk.v1"
        private const val MAX_CONTROL_BYTES = InternetControlRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES
        private const val MIN_RECORD_BYTES = 16
        internal const val CONTROL_BUFFER_HIGH_WATER_BYTES = 4L * MAX_CONTROL_BYTES
        private const val BULK_BUFFER_HIGH_WATER_BYTES = 4L * 1024L * 1024L
        private const val MEDIA_BUFFER_LOW_WATER_BYTES = 131_072L
        private const val AUDIO_BUFFER_LOW_WATER_BYTES = 64_000L
        private const val STATS_INTERVAL_SECONDS = 2L
        private const val MEDIA_RETRY_DELAY_MS = 50L
        private const val AUDIO_RETRY_DELAY_MS = 20L
        internal const val ROUTE_RESOLUTION_TIMEOUT_MS = 5_000L
    }

    private val WebRtcDataChannelKind.bufferLowWaterBytes: Long
        get() =
            when (this) {
                WebRtcDataChannelKind.MEDIA -> MEDIA_BUFFER_LOW_WATER_BYTES
                WebRtcDataChannelKind.AUDIO -> AUDIO_BUFFER_LOW_WATER_BYTES
                WebRtcDataChannelKind.CONTROL,
                WebRtcDataChannelKind.BULK,
                -> error("${name.lowercase()} does not use the latest-record drain path")
            }

    private val WebRtcDataChannelKind.latestQueue: LatestFrameBatchQueue
        get() =
            when (this) {
                WebRtcDataChannelKind.MEDIA -> mediaBatches
                WebRtcDataChannelKind.AUDIO -> audioRecords
                WebRtcDataChannelKind.CONTROL,
                WebRtcDataChannelKind.BULK,
                -> error("${name.lowercase()} does not use the latest-record drain path")
            }

    private val WebRtcDataChannelKind.retryGate: PeerMediaRetryGate<PeerMediaRetryKey>
        get() =
            when (this) {
                WebRtcDataChannelKind.MEDIA -> mediaRetryGate
                WebRtcDataChannelKind.AUDIO -> audioRetryGate
                WebRtcDataChannelKind.CONTROL,
                WebRtcDataChannelKind.BULK,
                -> error("${name.lowercase()} does not use the latest-record drain path")
            }
}
