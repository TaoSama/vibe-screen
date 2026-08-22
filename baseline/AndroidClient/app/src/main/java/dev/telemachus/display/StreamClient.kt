package dev.telemachus.display

import android.content.Context
import android.os.Build
import android.util.Log
import android.view.WindowManager
import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.ProtocolChannel
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.FileChunk
import dev.telemachus.display.protocol.FileTransferException
import dev.telemachus.display.protocol.FileTransferPolicy
import dev.telemachus.display.protocol.IncomingFileTransferManager
import dev.telemachus.display.protocol.OutgoingFileTransfer
import dev.telemachus.display.protocol.ProtocolUpgrade
import dev.telemachus.display.protocol.ProtocolV1Framing
import dev.telemachus.display.protocol.ProtocolV1Failure
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.telemachus.display.protocol.RemoteManagedPolicy
import dev.telemachus.display.protocol.TouchSample
import dev.telemachus.display.protocol.UpgradeFallbackDecision
import dev.telemachus.display.protocol.UpgradeProbeOutcome
import dev.telemachus.display.protocol.MotionPointer
import dev.telemachus.display.transport.SocketStreamTransportConnection
import dev.telemachus.display.transport.StreamTransportCandidate
import dev.telemachus.display.transport.StreamTransportCandidateRejection
import dev.telemachus.display.transport.StreamTransportCandidateRejectedException
import dev.telemachus.display.transport.StreamTransportOwner
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.FileAccept
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.TransportKind
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.DataInputStream
import java.io.File
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.StandardCharsets
import java.security.SecureRandom
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

internal data class StreamVideoConfiguration(
    val encodedWidth: Int,
    val encodedHeight: Int,
    val rotation: Int,
    val configEpoch: Long,
    val bitrateKbps: Int = 0,
    val framesPerSecond: Int = 0,
    val appliesClientVideoPreferences: Boolean = false,
)

internal data class StreamDisplayGeometry(
    val logicalWidth: Int,
    val logicalHeight: Int,
    val rotation: Int,
)

internal data class StreamVideoConfigurationDecision(
    val accepted: Boolean,
    val rejectionReason: String = "",
) {
    companion object {
        val ACCEPTED = StreamVideoConfigurationDecision(accepted = true)

        fun reject(reason: String) =
            StreamVideoConfigurationDecision(
                accepted = false,
                rejectionReason = reason.ifBlank { "decoder_configuration_failure" }.take(128),
            )
    }
}

internal interface StreamVideoConfigurationCommit {
    val canSupersedePendingConfiguration: Boolean
        get() = false

    fun isPending(): Boolean

    fun tryPublish(publish: () -> Boolean): Boolean

    fun complete(decision: StreamVideoConfigurationDecision)

    fun cancel()
}

class StreamClient(
    private val host: String,
    private val port: Int,
    private val context: Context? = null,
    private val socketFactory: () -> Socket = ::Socket,
    private val videoConfigurationCommitTimeoutMs: Long = VIDEO_CONFIGURATION_COMMIT_TIMEOUT_MS,
    private val videoConfigurationTimeoutExecutor: ScheduledExecutorService = VIDEO_CONFIGURATION_TIMEOUT_EXECUTOR,
    private val terminationExecutor: Executor = SESSION_TERMINATION_EXECUTOR,
    private val wakeHostExecutor: Executor = WAKE_HOST_EXECUTOR,
    private val advertiseController: Boolean = false,
    private val wakeHostPolicy: WakeHostPolicy = WakeHostPolicy.DENY,
    private val wakeHostPacketSender: WakeHostPacketSender = UdpWakeHostPacketSender(),
) {
    internal val actualPort: Int = port
    private val transportOwner = StreamTransportOwner<SocketStreamTransportConnection>()

    @Volatile private var isConnected = false
    @Volatile private var sessionReady = false
    @Volatile private var stopRequested = false
    /** Process-local decoder/attempt generation. Never assigned from a wire session epoch. */
    @Volatile private var connectionEpoch = 0L
    @Volatile private var lastTerminationFailure: SessionFailure? = null
    @Volatile private var wireMode = WireMode.LEGACY
    private var pendingLegacyFirstByte: Int? = null
    @Volatile private var protocolSession: ProtocolV1Session? = null
    private val nextInputId = AtomicLong(1L)
    private val nextPingSequence = AtomicLong(1L)
    private val pendingOutboundFailure = AtomicReference<SessionFailure?>(null)
    private val pendingDecoderFailure = AtomicReference<SessionFailure?>(null)
    private val pendingInboundFailure = AtomicReference<SessionFailure?>(null)
    private val pendingVideoConfigurationCommit = AtomicReference<PendingVideoConfigurationCommit?>(null)
    @Volatile private var lanRecordProtectionState = LanRecordProtectionState.NOT_APPLICABLE
    internal val currentLanProtectionState: LanRecordProtectionState
        get() = lanRecordProtectionState
    @Volatile private var lanSecureRecordSession: LanSecureRecordSession? = null
    // Android currently sends only client-to-host control messages on the trusted-LAN record layer.
    @Volatile private var nextOutboundChannel = dev.telemachus.display.internet.SessionChannel.CONTROL
    private val incomingFileTransfers = AtomicReference<IncomingFileTransferManager?>(null)
    private val outgoingFileTransfers = mutableMapOf<ByteString, OutgoingFileTransfer>()
    private var remoteManagedPolicy = RemoteManagedPolicy.UNMANAGED
    private val fileTransferPolicy = FileTransferPolicy()
    private val pendingInboundWakeHostRequests = ArrayDeque<ByteString>()
    @Volatile private var lastV1PingSequence = 0L
    @Volatile private var lastV1PingSentNs = 0L
    private val controllerConnectionAcks = ControllerConnectionAckTracker()

    private val heartbeat = HeartbeatMonitor(HEARTBEAT_TIMEOUT_MS)
    private val reconnectBackoff = ReconnectBackoff()
    private val protocolActionDispatcher = StreamProtocolActionDispatcher(StreamProtocolActionSink())
    // Protocol request ids must be unpredictable so a result cannot be spoofed
    // by replaying a guessed id.
    private val protocolRequestRandom = SecureRandom()

    // Callback includes actual frame size (may differ from buffer.size due to pooling),
    // receive timestamp, and whether the frame can restart HEVC decoding.
    var onFrameReceived: ((ByteArray, Int, Long, Boolean, Long, Long) -> Unit)? = null
    var onConnectionStatus: ((Boolean) -> Unit)? = null
    internal var onVideoConfiguration:
        ((StreamVideoConfiguration, StreamVideoConfigurationCommit) -> Unit)? = null
    internal var onVideoConfigurationApplied: ((StreamVideoConfiguration) -> Unit)? = null
    internal var onDisplayGeometry: ((StreamDisplayGeometry) -> Unit)? = null
    internal var onDisplaysAvailable: ((List<StreamDisplayOption>, selectedId: String) -> Unit)? = null
    internal var onHostActionsAvailable: ((List<HostActionOption>) -> Unit)? = null
    internal var onHostActionResult: ((accepted: Boolean, rejectionReason: String) -> Unit)? = null
    /** A peer clipboard offer has arrived; the UI may request the content by changeId. */
    internal var onClipboardOffered: ((offer: ClipboardOfferData) -> Unit)? = null
    /** Peer clipboard content has arrived. pending=true means no offer/request handshake preceded it. */
    internal var onClipboardContentReceived: ((content: ClipboardContentData) -> Unit)? = null
    internal var onFileOffer: ((dev.vibescreen.protocol.v1.FileOffer) -> Boolean)? = null
    internal var onIncomingFileCompleted: ((CompletedIncomingFile) -> Unit)? = null
    internal var onFileTransferResult: ((accepted: Boolean, reason: String) -> Unit)? = null
    internal var onWakeHostResult: ((accepted: Boolean, rejectionReason: String) -> Unit)? = null
    var onStats: ((Double, Double) -> Unit)? = null
    var onReconnectSuggested: ((delayMs: Long) -> Unit)? = null
    var onWriteFailure: ((reason: String) -> Unit)? = null
    internal var onSessionEnded: ((failure: SessionFailure) -> Unit)? = null

    /** Invoked when the server confirms the stream codec (true = HEVC). */
    var onCodecSelected: ((Boolean) -> Unit)? = null
    var onServerShutdown: (() -> Unit)? = null

    /** Stream codec for sync-frame parsing. HEVC unless the server says otherwise. */
    @Volatile var streamCodecIsHevc = true
        private set

    /** True once a MESSAGE_CODEC_SELECTED arrived — distinguishes new Macs from old. */
    @Volatile var codecNegotiated = false
        private set

    init {
        require(videoConfigurationCommitTimeoutMs > 0L) { "videoConfigurationCommitTimeoutMs must be positive" }
    }

    private var bytesReceived = 0L
    private var framesReceived = 0L
    private var diagFrameCount = 0L
    private var lastStatsTime = System.currentTimeMillis()
    private val keyframeRequestLock = Any()
    private var lastKeyframeRequestNs = 0L
    private var lastKeyframeReceivedNs = 0L

    // Buffer pooling to reduce GC pressure from per-frame allocations
    // At 60fps with ~100KB frames, this prevents ~6MB/s of allocations
    private val bufferPool = ArrayDeque<ByteArray>(8)
    private val poolLock = Any()

    /**
     * Acquire a buffer from pool or allocate new one if needed
     * @param minSize Minimum size required for the buffer
     */
    private fun acquireBuffer(minSize: Int): ByteArray {
        synchronized(poolLock) {
            val iterator = bufferPool.iterator()
            while (iterator.hasNext()) {
                val buffer = iterator.next()
                if (buffer.size >= minSize) {
                    iterator.remove()
                    return buffer
                }
            }
        }
        // No suitable buffer found, allocate new one
        return ByteArray(minSize)
    }

    /**
     * Release a buffer back to the pool for reuse
     * Called after decode completes via onFrameDecoded callback
     */
    fun releaseBuffer(buffer: ByteArray) {
        synchronized(poolLock) {
            // Keep pool size limited to prevent memory bloat
            if (bufferPool.size < 8) {
                bufferPool.addLast(buffer)
            }
            // If pool is full, let buffer be GC'd
        }
    }

    private val outboundScheduler =
        OutboundCommandScheduler(
            capacity = OUTBOUND_QUEUE_CAPACITY,
            writer = ::writeOutboundCommand,
            onWriteFailure = { failure ->
                val detail = failure.cause.message ?: failure.cause.javaClass.simpleName
                Log.e(TAG, "Outbound write failed", failure.cause)
                pendingOutboundFailure.compareAndSet(null, SessionFailure.write(detail))
                onWriteFailure?.invoke(detail)
                transportOwner.shutdownActiveOutput()?.let { shutdownFailure ->
                    Log.d(TAG, "Outbound side was already closed", shutdownFailure)
                }
            },
            coalesce = { kind, pending, replacement ->
                if (kind == OutboundCommandScheduler.Kind.KEYFRAME &&
                    pending is StreamOutboundCommand.Keyframe &&
                    replacement is StreamOutboundCommand.Keyframe
                ) {
                    StreamOutboundCommand.Keyframe(pending.flags or replacement.flags)
                } else {
                    replacement
                }
            },
            threadName = "VibeOutboundWriter",
        )
    private val inputDispatcher =
        StreamInputDispatcher(
            state = ::currentInputSessionState,
            nextInputId = nextInputId,
            submitOutbound = ::submitOutbound,
            controllerConnectionAcks = controllerConnectionAcks,
        )
    private val terminationDispatcher =
        OnceAsyncDispatcher(
            executor = terminationExecutor,
            onClaim = { request ->
                lastTerminationFailure = request.failure
                isConnected = false
            },
            complete = ::completeConnectionEnd,
        )

    suspend fun connect() =
        withContext(Dispatchers.IO) {
            if (terminationDispatcher.isClaimed()) return@withContext
            sessionReady = false
            stopRequested = false
            pendingOutboundFailure.set(null)
            pendingDecoderFailure.set(null)
            pendingInboundFailure.set(null)
            try {
                val candidate = registerInitialTransportCandidate() ?: return@withContext
                if (terminationDispatcher.isClaimed()) {
                    cleanupCandidateTransport(candidate)
                    return@withContext
                }
                candidate.connection.socket.tcpNoDelay = true
                candidate.connection.socket.connect(InetSocketAddress(host, port), CONNECT_TIMEOUT_MS)
                candidate.connection.socket.soTimeout = HEARTBEAT_POLL_INTERVAL_MS
                candidate.connection.installStreams()
                if (!promoteTransportCandidate(candidate) { !terminationDispatcher.isClaimed() }) {
                    outboundScheduler.shutdownNow()
                    return@withContext
                }
                streamCodecIsHevc = true
                codecNegotiated = false
                connectionEpoch = SESSION_EPOCHS.beginSession()
                val upgradeDecision = negotiateProtocol(TransportKind.TRANSPORT_KIND_USB)
                if (upgradeDecision == UpgradeFallbackDecision.OpenFreshLegacyConnection) {
                    reopenUsbAsLegacy(connectionEpoch)
                }
                isConnected = true
                if (terminationDispatcher.isClaimed()) {
                    isConnected = false
                    closeTransport()
                    outboundScheduler.shutdownNow()
                    return@withContext
                }
                heartbeat.reset(System.nanoTime())
                lastKeyframeReceivedNs = 0L
                synchronized(keyframeRequestLock) {
                    lastKeyframeRequestNs = 0L
                }

                diagLog("Connected to $host:$port")
                emitTelemetry(
                    "connection_opened",
                    mapOf("host" to host, "port" to port, "session_epoch" to connectionEpoch),
                )
                receiveData()
                if (!sessionReady && !stopRequested) {
                    val failure = lastTerminationFailure
                    if (failure != null && !failure.retryable) throw SessionProtocolException(failure)
                    throw IOException("Mac connection closed before display configuration")
                }
            } catch (e: SessionProtocolException) {
                Log.e(TAG, "Session protocol failure", e)
                completeConnectionEndNow(e.failure)
                if (!sessionReady && !stopRequested) throw e
            } catch (e: Exception) {
                Log.e(TAG, "❌ Connection error", e)
                completeConnectionEndNow(SessionFailure.transport(e.message ?: e.javaClass.simpleName))
                if (!sessionReady && !stopRequested) {
                    val failure = lastTerminationFailure
                    if (failure != null && !failure.retryable) throw SessionProtocolException(failure)
                    if (e.message.orEmpty().contains("before display configuration")) throw e
                    throw IOException("Mac connection closed before display configuration", e)
                }
            }
        }

    sealed class WirelessConnectError(
        msg: String,
    ) : Exception(msg) {
        object NetworkUnreachable : WirelessConnectError("Mac unreachable — check both on same WiFi")

        object TokenRejected : WirelessConnectError("Token rejected — re-pair required")

        object ProtocolError : WirelessConnectError("Connection error, please rescan QR")
    }

    /**
     * Wireless connect: opens TCP, performs auth handshake, then resumes the existing receive loop on success.
     * Throws WirelessConnectError on any failure.
     */
    suspend fun connectWireless(
        token: ByteArray,
        deviceName: String,
        allowPlaintextLegacyFallback: Boolean = false,
    ) = withContext(Dispatchers.IO) {
        if (terminationDispatcher.isClaimed()) return@withContext
        sessionReady = false
        stopRequested = false
        pendingOutboundFailure.set(null)
        pendingDecoderFailure.set(null)
        pendingInboundFailure.set(null)
        val request =
            try {
                AuthHandshake.encodeRequest(token, deviceName)
            } catch (error: IllegalArgumentException) {
                throw WirelessConnectError.ProtocolError
            }
        Log.i(TAG, "connectWireless: trying $host:$port (device=$deviceName, token bytes=${token.size})")

        val candidate = registerInitialTransportCandidate() ?: return@withContext
        val s = candidate.connection.socket
        if (terminationDispatcher.isClaimed()) {
            cleanupCandidateTransport(candidate)
            return@withContext
        }
        try {
            // Keep trusted-LAN traffic on WiFi even when cellular is the default route.
            s.tcpNoDelay = true
            val route = AndroidWirelessNetworkRoute.bindPreferredWifi(context, s, host)
            val address = route?.address ?: java.net.InetAddress.getByName(host)
            Log.i(TAG, "connectWireless: route=${route?.network ?: "default"}, address=${address.hostAddress}")
            s.connect(InetSocketAddress(address, port), CONNECT_TIMEOUT_MS)
        } catch (error: SocketTimeoutException) {
            failWirelessHandshake(SessionFailure.transport("TCP connect timeout"), WirelessConnectError.NetworkUnreachable)
        } catch (error: IOException) {
            failWirelessHandshake(
                SessionFailure.transport(error.message ?: error.javaClass.simpleName),
                WirelessConnectError.NetworkUnreachable,
            )
        } catch (error: CancellationException) {
            cancelWirelessStartup(error)
        } catch (error: Exception) {
            failWirelessHandshake(
                SessionFailure.transport(error.message ?: error.javaClass.simpleName),
                WirelessConnectError.ProtocolError,
            )
        }
        if (terminationDispatcher.isClaimed()) return@withContext

        val rawInput =
            try {
                s.getInputStream()
            } catch (error: IOException) {
                failWirelessHandshake(
                    SessionFailure.transport(error.message ?: "failed to open wireless input"),
                    WirelessConnectError.NetworkUnreachable,
                )
            } catch (error: CancellationException) {
                cancelWirelessStartup(error)
            } catch (error: Exception) {
                failWirelessHandshake(
                    SessionFailure.transport(error.message ?: error.javaClass.simpleName),
                    WirelessConnectError.ProtocolError,
                )
            }
        val rawOutput =
            try {
                s.getOutputStream()
            } catch (error: IOException) {
                failWirelessHandshake(
                    SessionFailure.transport(error.message ?: "failed to open wireless output"),
                    WirelessConnectError.NetworkUnreachable,
                )
            } catch (error: CancellationException) {
                cancelWirelessStartup(error)
            } catch (error: Exception) {
                failWirelessHandshake(
                    SessionFailure.transport(error.message ?: error.javaClass.simpleName),
                    WirelessConnectError.ProtocolError,
                )
            }
        try {
            s.soTimeout = HANDSHAKE_TIMEOUT_MS
            rawOutput.write(request)
            rawOutput.flush()
        } catch (error: IOException) {
            failWirelessHandshake(
                SessionFailure.transport(error.message ?: "wireless handshake write failed"),
                WirelessConnectError.NetworkUnreachable,
            )
        } catch (error: CancellationException) {
            cancelWirelessStartup(error)
        } catch (error: Exception) {
            failWirelessHandshake(
                SessionFailure.transport(error.message ?: error.javaClass.simpleName),
                WirelessConnectError.ProtocolError,
            )
        }

        val responseBuf = ByteArray(5)
        var read = 0
        try {
            while (read < 5) {
                val r = rawInput.read(responseBuf, read, 5 - read)
                if (r <= 0) break
                read += r
            }
        } catch (error: SocketTimeoutException) {
            failWirelessHandshake(SessionFailure.transport("handshake response timed out"), WirelessConnectError.ProtocolError)
        } catch (error: IOException) {
            failWirelessHandshake(
                SessionFailure.transport(error.message ?: "wireless handshake read failed"),
                WirelessConnectError.NetworkUnreachable,
            )
        } catch (error: CancellationException) {
            cancelWirelessStartup(error)
        } catch (error: Exception) {
            failWirelessHandshake(
                SessionFailure.transport(error.message ?: error.javaClass.simpleName),
                WirelessConnectError.ProtocolError,
            )
        }
        if (read != 5) {
            failWirelessHandshake(SessionFailure.transport("incomplete handshake response"), WirelessConnectError.ProtocolError)
        }

        val status =
            AuthHandshake.parseResponse(responseBuf) ?: run {
                failWirelessHandshake(SessionFailure.transport("invalid handshake response"), WirelessConnectError.ProtocolError)
            }
        Log.i(TAG, "connectWireless: handshake response status=$status")
        when (status) {
            AuthHandshake.ResponseStatus.OK -> {
                val startupSucceeded =
                    try {
                        s.soTimeout = HEARTBEAT_POLL_INTERVAL_MS
                        connectionEpoch = SESSION_EPOCHS.beginSession()
                        val protection =
                            if (allowPlaintextLegacyFallback) {
                                LanSecureRecordClientNegotiation(
                                    LanRecordProtectionState.EXPLICIT_LEGACY_FALLBACK,
                                    null,
                                )
                            } else {
                                negotiateLanSecureRecordsAsClient(
                                    input = rawInput,
                                    output = rawOutput,
                                    token = token,
                                )
                            }
                        lanSecureRecordSession?.close()
                        lanSecureRecordSession = protection.session
                        lanRecordProtectionState = protection.state
                        val protectedInput =
                            if (protection.state == LanRecordProtectionState.ENCRYPTED) {
                                LanSecureRecordInputStream(rawInput, checkNotNull(protection.session))
                            } else {
                                rawInput
                            }
                        val protectedOutput =
                            if (protection.state == LanRecordProtectionState.ENCRYPTED) {
                                LanSecureRecordOutputStream(
                                    rawOutput,
                                    checkNotNull(protection.session),
                                ) { nextOutboundChannel }
                            } else {
                                rawOutput
                            }
                        candidate.connection.installStreams(protectedInput, protectedOutput)
                        if (!promoteTransportCandidate(candidate) { !terminationDispatcher.isClaimed() }) {
                            outboundScheduler.shutdownNow()
                            return@withContext
                        }
                        isConnected = true
                        if (terminationDispatcher.isClaimed()) {
                            isConnected = false
                            closeTransport()
                            outboundScheduler.shutdownNow()
                            return@withContext
                        }
                        streamCodecIsHevc = true
                        codecNegotiated = false
                        val upgradeDecision = negotiateProtocol(TransportKind.TRANSPORT_KIND_LAN)
                        if (upgradeDecision == UpgradeFallbackDecision.OpenFreshLegacyConnection) {
                            reopenWirelessAsLegacy(
                                token,
                                deviceName,
                                connectionEpoch,
                                allowPlaintextLegacyFallback,
                            )
                        }
                        true
                    } catch (error: IOException) {
                        completeConnectionEndNow(SessionFailure.write(error.message ?: "wireless session startup failed"))
                        false
                    } catch (error: CancellationException) {
                        cancelWirelessStartup(error)
                    } catch (error: Exception) {
                        completeConnectionEndNow(SessionFailure.write(error.message ?: error.javaClass.simpleName))
                        false
                    }
                if (!startupSucceeded) return@withContext
                if (terminationDispatcher.isClaimed()) return@withContext
                heartbeat.reset(System.nanoTime())
                emitTelemetry(
                    "connection_opened",
                    mapOf(
                        "host" to host,
                        "port" to port,
                        "session_epoch" to connectionEpoch,
                        "trusted_lan_encrypted" to (lanRecordProtectionState == LanRecordProtectionState.ENCRYPTED),
                        "trusted_lan_legacy_plaintext" to
                            (lanRecordProtectionState == LanRecordProtectionState.EXPLICIT_LEGACY_FALLBACK),
                    ),
                )
                diagLog(
                    "Wireless connected to $host:$port " +
                        if (lanRecordProtectionState == LanRecordProtectionState.ENCRYPTED) {
                            "(trusted LAN encrypted records)"
                        } else {
                            "(explicit trusted LAN legacy plaintext)"
                        },
                )
                receiveData()
            }

            AuthHandshake.ResponseStatus.INVALID_TOKEN -> {
                failWirelessHandshake(SessionFailure.transport("wireless token rejected"), WirelessConnectError.TokenRejected)
            }

            else -> {
                failWirelessHandshake(SessionFailure.transport("wireless handshake rejected"), WirelessConnectError.ProtocolError)
            }
        }
    }

    private fun failWirelessHandshake(
        failure: SessionFailure,
        error: WirelessConnectError,
    ): Nothing {
        completeConnectionEndNow(failure)
        throw error
    }

    private fun cancelWirelessStartup(error: CancellationException): Nothing {
        completeConnectionEndNow(SessionFailure.transport("wireless connection cancelled"))
        throw error
    }

    private fun advertiseFrameMetadataSupport() {
        enqueueLegacyControlByte(MESSAGE_CLIENT_SUPPORTS_FRAME_METADATA)
        diagLog("Queued frame metadata support")
    }

    private fun negotiateProtocol(transport: TransportKind): UpgradeFallbackDecision {
        val connection = checkNotNull(transportOwner.activeConnection())
        val input = connection.input
        val output = connection.output
        ProtocolUpgrade.writeOffer(output)
        connection.readTimeoutMillis = PROTOCOL_UPGRADE_TIMEOUT_MS
        val firstByte =
            try {
                input.read()
            } catch (_: SocketTimeoutException) {
                null
            }
        val outcome =
            if (firstByte == null) {
                UpgradeProbeOutcome.TimedOut
            } else if (firstByte < 0) {
                throw IOException("Protocol upgrade probe closed before a response")
            } else {
                when (val result = ProtocolUpgrade.classify(firstByte, input)) {
                    ProtocolUpgrade.Result.V1 -> UpgradeProbeOutcome.V1Acknowledged
                    is ProtocolUpgrade.Result.Legacy ->
                        UpgradeProbeOutcome.LegacyByte(checkNotNull(result.firstByte))
                }
            }
        val decision = UpgradeFallbackDecision.fromProbeOutcome(outcome)
        when (decision) {
            UpgradeFallbackDecision.UseCurrentV1Connection -> {
                wireMode = WireMode.V1
                pendingLegacyFirstByte = null
                val session = createProtocolSession(transport)
                protocolSession = session
                nextInputId.set(1L)
                controllerConnectionAcks.reset()
                writeProtocolEnvelope(output, session.clientHello())
                diagLog("Protocol v1 upgrade accepted")
            }
            is UpgradeFallbackDecision.UseCurrentLegacyConnection -> {
                configureLegacyMode(decision.firstByte)
                diagLog("Protocol upgrade unavailable after explicit legacy response")
            }
            UpgradeFallbackDecision.OpenFreshLegacyConnection -> {
                diagLog("Protocol upgrade timed out; probe socket must be replaced")
            }
        }
        connection.readTimeoutMillis = HEARTBEAT_POLL_INTERVAL_MS
        return decision
    }

    private fun createProtocolSession(transport: TransportKind): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-${Build.MODEL}".take(MAX_PROTOCOL_ID_BYTES),
            deviceName = (Build.MODEL ?: "Android").take(MAX_DEVICE_NAME_BYTES),
            transport = transport,
            codecs =
                CodecCapabilities.advertisedStreamCodecs.mapNotNull(StreamCodec::toProtocolCodecOrNull),
            advertiseController = advertiseController,
            fileTransferPolicy = fileTransferPolicy,
            wakeHostPolicy = wakeHostPolicy,
        ).also {
            incomingFileTransfers.set(
                IncomingFileTransferManager(
                    policy = fileTransferPolicy,
                    directory = fileTransferStagingDirectory(),
                    approve = { offer -> onFileOffer?.invoke(offer) == true },
                ),
            )
            remoteManagedPolicy = RemoteManagedPolicy.UNMANAGED
            outgoingFileTransfers.values.forEach { it.cancel() }
            outgoingFileTransfers.clear()
        }

    private fun fileTransferStagingDirectory(): File {
        val tmpDir = System.getProperty("java.io.tmpdir") ?: "."
        val root = context?.cacheDir ?: File(tmpDir)
        return File(root, "vibescreen-file-transfer")
    }

    private fun configureLegacyMode(firstByte: Int? = null) {
        wireMode = WireMode.LEGACY
        protocolSession = null
        controllerConnectionAcks.reset()
        pendingLegacyFirstByte = firstByte
        advertiseAvcOnlyIfNeeded()
        advertiseFrameMetadataSupport()
        offerDeviceInfoCapability()
    }

    private fun reopenUsbAsLegacy(attemptGeneration: Long) {
        closeTransport()
        installFreshLegacyTransport(attemptGeneration) { fresh ->
            fresh.tcpNoDelay = true
            fresh.connect(InetSocketAddress(host, port), CONNECT_TIMEOUT_MS)
            fresh.getInputStream() to fresh.getOutputStream()
        }
    }

    private fun reopenWirelessAsLegacy(
        token: ByteArray,
        deviceName: String,
        attemptGeneration: Long,
        allowPlaintextLegacyFallback: Boolean = false,
    ) {
        closeTransport()
        installFreshLegacyTransport(attemptGeneration) { fresh ->
            configureWirelessSocket(fresh)
            authenticateWirelessSocket(fresh, token, deviceName, allowPlaintextLegacyFallback)
        }
    }

    private fun installFreshLegacyTransport(
        attemptGeneration: Long,
        prepare: (Socket) -> Pair<java.io.InputStream, java.io.OutputStream>,
    ) {
        val candidate = registerTransportCandidate(attemptGeneration, ::ownsAttempt)
        var promoted = false
        try {
            val streams = prepare(candidate.connection.socket)
            candidate.connection.socket.soTimeout = HEARTBEAT_POLL_INTERVAL_MS
            candidate.connection.installStreams(streams.first, streams.second)
            promoted = promoteTransportCandidate(candidate, ::ownsAttempt)
            check(promoted) { "Fallback connection attempt was superseded" }
            configureLegacyMode()
        } catch (failure: Exception) {
            if (promoted) closeTransport()
            throw failure
        } finally {
            if (!promoted) logTransportCloseFailures(transportOwner.release(candidate))
        }
    }

    private fun registerTransportCandidate(
        attemptGeneration: Long,
        eligible: (Long) -> Boolean,
    ): StreamTransportCandidate<SocketStreamTransportConnection> {
        return try {
            transportOwner.createCandidate(attemptGeneration, eligible) {
                SocketStreamTransportConnection(socketFactory())
            }
        } catch (rejected: StreamTransportCandidateRejectedException) {
            logTransportCloseFailures(rejected.closeFailures)
            throw IOException("Transport connection attempt was superseded", rejected)
        }
    }

    private fun registerInitialTransportCandidate(): StreamTransportCandidate<SocketStreamTransportConnection>? =
        try {
            transportOwner.createCandidate(
                UNASSIGNED_ATTEMPT_GENERATION,
                { !terminationDispatcher.isClaimed() },
            ) {
                SocketStreamTransportConnection(socketFactory())
            }
        } catch (rejected: StreamTransportCandidateRejectedException) {
            logTransportCloseFailures(rejected.closeFailures)
            if (rejected.reason == StreamTransportCandidateRejection.INELIGIBLE &&
                terminationDispatcher.isClaimed()
            ) {
                null
            } else {
                throw IOException("Transport connection attempt was superseded", rejected)
            }
        }

    private fun promoteTransportCandidate(
        candidate: StreamTransportCandidate<SocketStreamTransportConnection>,
        acceptsGeneration: (Long) -> Boolean,
    ): Boolean {
        val promotion = transportOwner.promote(candidate, acceptsGeneration)
        logTransportCloseFailures(promotion.closeFailures)
        return promotion.promoted
    }

    private fun ownsAttempt(attemptGeneration: Long): Boolean =
        !terminationDispatcher.isClaimed() &&
            connectionEpoch == attemptGeneration &&
            SESSION_EPOCHS.accepts(attemptGeneration)

    private fun closeTransport() {
        logTransportCloseFailures(transportOwner.closeAll())
    }

    private fun logTransportCloseFailures(failures: List<Exception>) {
        if (failures.isNotEmpty()) {
            Log.w(TAG, "Transport close reported ${failures.size} failure(s)", failures.first())
        }
    }

    private fun configureWirelessSocket(fresh: Socket) {
        fresh.tcpNoDelay = true
        val route = AndroidWirelessNetworkRoute.bindPreferredWifi(context, fresh, host)
        val address = route?.address ?: java.net.InetAddress.getByName(host)
        fresh.connect(InetSocketAddress(address, port), CONNECT_TIMEOUT_MS)
    }

    private fun authenticateWirelessSocket(
        fresh: Socket,
        token: ByteArray,
        deviceName: String,
        allowPlaintextLegacyFallback: Boolean = false,
    ): Pair<java.io.InputStream, java.io.OutputStream> {
        fresh.soTimeout = HANDSHAKE_TIMEOUT_MS
        val output = fresh.getOutputStream()
        val rawInput = fresh.getInputStream()
        output.write(AuthHandshake.encodeRequest(token, deviceName))
        output.flush()
        val response = ByteArray(AUTH_RESPONSE_BYTES)
        var offset = 0
        while (offset < response.size) {
            val count = rawInput.read(response, offset, response.size - offset)
            if (count < 0) throw IOException("Wireless authentication ended early")
            if (count == 0) continue
            offset += count
        }
        when (AuthHandshake.parseResponse(response)) {
            AuthHandshake.ResponseStatus.OK -> Unit
            AuthHandshake.ResponseStatus.INVALID_TOKEN -> throw WirelessConnectError.TokenRejected
            else -> throw WirelessConnectError.ProtocolError
        }
        val protection =
            if (allowPlaintextLegacyFallback) {
                LanSecureRecordClientNegotiation(
                    LanRecordProtectionState.EXPLICIT_LEGACY_FALLBACK,
                    null,
                )
            } else {
                negotiateLanSecureRecordsAsClient(
                    input = rawInput,
                    output = output,
                    token = token,
                )
            }
        lanSecureRecordSession?.close()
        lanSecureRecordSession = protection.session
        lanRecordProtectionState = protection.state
        val protectedInput =
            if (protection.state == LanRecordProtectionState.ENCRYPTED) {
                LanSecureRecordInputStream(rawInput, checkNotNull(protection.session))
            } else {
                rawInput
            }
        val protectedOutput =
            if (protection.state == LanRecordProtectionState.ENCRYPTED) {
                LanSecureRecordOutputStream(output, checkNotNull(protection.session)) { nextOutboundChannel }
            } else {
                output
            }
        return protectedInput to protectedOutput
    }

    /**
     * Payload-free offer (type 12). Older Mac hosts consume one unknown byte and
     * never reply, so we only send the 66-byte type 11 payload after the host
     * accepts with the same type.
     */
    private fun offerDeviceInfoCapability() {
        enqueueLegacyControlByte(MESSAGE_DEVICE_INFO_CAPABILITY)
        diagLog("Queued device-info capability")
    }

    /**
     * Reports Build.MODEL and the panel's maximum supported refresh rate so the
     * Mac settings UI can stop hardcoding a developer tablet. Uses wire type 11
     * (66 bytes) only after [MESSAGE_DEVICE_INFO_CAPABILITY] acceptance.
     */
    private fun sendDeviceInfo() {
        val model = Build.MODEL ?: "Android"
        val modelBytes = model.toByteArray(Charsets.UTF_8)
        val modelField = ByteArray(64)
        modelBytes.copyInto(modelField, 0, 0, minOf(modelBytes.size, 63))
        val refreshRate = resolveMaxRefreshRateHz()
        val payload = ByteArray(1 + 64 + 1)
        payload[0] = MESSAGE_CLIENT_DEVICE_INFO.toByte()
        System.arraycopy(modelField, 0, payload, 1, 64)
        payload[65] = (refreshRate.coerceIn(0, 255) and 0xFF).toByte()
        submitOutbound(
            kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
            command = StreamOutboundCommand.LegacyControl(payload),
        )
        diagLog("Queued device info: model=$model, maxRefreshRate=$refreshRate")
    }

    private fun resolveMaxRefreshRateHz(): Int {
        val appContext = context ?: return 60
        return try {
            val windowManager = appContext.getSystemService(Context.WINDOW_SERVICE) as WindowManager

            @Suppress("DEPRECATION")
            val display = windowManager.defaultDisplay

            val maxFromModes =
                display.supportedModes
                    .maxOfOrNull { mode -> kotlin.math.round(mode.refreshRate).toInt() }

            if (maxFromModes != null) {
                maxFromModes
            } else {
                @Suppress("DEPRECATION")
                kotlin.math.round(display.refreshRate).toInt()
            }
        } catch (e: Exception) {
            Log.w(TAG, "Could not read display refresh rate, using 60", e)
            60
        }
    }

    private fun advertiseAvcOnlyIfNeeded() {
        if (!CodecCapabilities.shouldAdvertiseAvcOnly) return
        enqueueLegacyControlByte(MESSAGE_CLIENT_AVC_ONLY)
        diagLog("Queued AVC-only advertisement (HEVC unavailable or failed at runtime)")
        emitTelemetry(
            "codec_fallback_requested",
            mapOf("from" to "HEVC", "to" to "H264", "session_epoch" to connectionEpoch),
        )
    }

    private fun enqueueLegacyControlByte(messageType: Int) {
        submitOutbound(
            kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
            command = StreamOutboundCommand.LegacyControl(byteArrayOf(messageType.toByte())),
        )
    }

    private suspend fun receiveData() =
        withContext(Dispatchers.IO) {
            val input = transportOwner.activeConnection()?.input ?: return@withContext
            var terminalFailure: SessionFailure? = null

            try {
                while (isConnected) {
                    if (wireMode == WireMode.V1) {
                        receiveV1Frame(input)
                        continue
                    }
                    val type =
                        try {
                            pendingLegacyFirstByte?.also { pendingLegacyFirstByte = null }?.toByte() ?: input.readByte()
                        } catch (_: SocketTimeoutException) {
                            pendingOutboundFailure.get()?.let { throw SessionProtocolException(it) }
                            if (heartbeat.isExpired(System.nanoTime())) {
                                emitTelemetry(
                                    "heartbeat_timeout",
                                    mapOf("session_epoch" to connectionEpoch),
                                )
                                throw SessionProtocolException(SessionFailure.heartbeat("heartbeat timeout"))
                            }
                            continue
                        }
                    heartbeat.recordInbound(System.nanoTime())

                    when (type.toInt()) {
                        MESSAGE_VIDEO_FRAME -> {
                            receiveVideoFrame(input, hasMetadata = false)
                        }

                        MESSAGE_VIDEO_FRAME_WITH_METADATA -> {
                            receiveVideoFrame(input, hasMetadata = true)
                        }

                        1 -> { // Display size + rotation
                            val width = input.readInt()
                            val height = input.readInt()
                            val rotation = input.readInt()
                            if (width !in MIN_DISPLAY_DIMENSION..MAX_DISPLAY_DIMENSION ||
                                height !in MIN_DISPLAY_DIMENSION..MAX_DISPLAY_DIMENSION ||
                                rotation !in VALID_DISPLAY_ROTATIONS
                            ) {
                                throw SessionProtocolException(
                                    SessionFailure.protocol(
                                        SessionFailureKind.INVALID_DISPLAY,
                                        "Invalid display configuration: ${width}x$height @ $rotation",
                                    ),
                                )
                            }
                            diagLog("Display config: ${width}x$height @ $rotation°")
                            if (!sessionReady) {
                                sessionReady = true
                                reconnectBackoff.reset()
                                onConnectionStatus?.invoke(true)
                            }
                            val configuration =
                                StreamVideoConfiguration(
                                    encodedWidth = width,
                                    encodedHeight = height,
                                    rotation = rotation,
                                    configEpoch = LEGACY_CONFIG_EPOCH,
                                )
                            val callbackEpoch = connectionEpoch
                            val callback = onVideoConfiguration
                            if (callback != null) {
                                callback.invoke(
                                    configuration,
                                    LegacyVideoConfigurationCommit(callbackEpoch),
                                )
                            }
                            onDisplayGeometry?.invoke(
                                StreamDisplayGeometry(
                                    logicalWidth = width,
                                    logicalHeight = height,
                                    rotation = rotation,
                                ),
                            )
                        }

                        5 -> { // Pong response — measure round-trip latency
                            val buf = ByteArray(8)
                            input.readFully(buf)
                            val sentTime = ByteBuffer.wrap(buf).order(ByteOrder.LITTLE_ENDIAN).long
                            val rtt = (System.nanoTime() - sentTime) / 1_000_000.0 // ms
                            onLatencyMeasured?.invoke(rtt)
                        }

                        MESSAGE_CODEC_SELECTED -> {
                            val codecId = input.readByte().toInt()
                            streamCodecIsHevc = codecId == 0
                            codecNegotiated = true
                            diagLog("Server selected codec: ${if (streamCodecIsHevc) "HEVC" else "H.264"}")
                            emitTelemetry(
                                "codec_selected",
                                mapOf(
                                    "codec" to if (streamCodecIsHevc) "HEVC" else "H264",
                                    "session_epoch" to connectionEpoch,
                                ),
                            )
                            onCodecSelected?.invoke(streamCodecIsHevc)
                        }

                        MESSAGE_DEVICE_INFO_CAPABILITY -> {
                            // Host accepted our offer — safe to send the payload.
                            diagLog("Host accepted device-info capability")
                            sendDeviceInfo()
                        }

                        MESSAGE_SERVER_SHUTDOWN -> {
                            stopRequested = true
                            terminalFailure = SessionFailure.serverShutdown()
                            completeConnectionEndNow(checkNotNull(terminalFailure))
                            diagLog("Server shut down gracefully — closing")
                            break
                        }

                        else -> {
                            throw SessionProtocolException(
                                SessionFailure.protocol(
                                    SessionFailureKind.UNKNOWN_MESSAGE,
                                    "Unknown message type: ${type.toInt()}",
                                ),
                            )
                        }
                    }
                }
            } catch (error: SessionProtocolException) {
                terminalFailure = error.failure
                pendingVideoConfigurationCommit.getAndSet(null)?.cancel()
                completeConnectionEndNow(error.failure)
                Log.e(TAG, "Session protocol failure: ${error.failure.detail}", error)
                throw error
            } catch (error: ProtocolV1Failure) {
                terminalFailure = error.toSessionFailure()
                pendingVideoConfigurationCommit.getAndSet(null)?.cancel()
                completeConnectionEndNow(checkNotNull(terminalFailure))
                Log.e(TAG, "Protocol v1 failure: ${error.message}", error)
                throw SessionProtocolException(checkNotNull(terminalFailure))
            } catch (e: IOException) {
                terminalFailure =
                    pendingInboundFailure.get()
                        ?: pendingDecoderFailure.get()
                        ?: SessionFailure.transport(e.message ?: e.javaClass.simpleName)
                pendingVideoConfigurationCommit.getAndSet(null)?.cancel()
                completeConnectionEndNow(checkNotNull(terminalFailure))
                if (isConnected) {
                    Log.e(TAG, "❌ Read error", e)
                }
            } finally {
                completeConnectionEndNow(
                    terminalFailure
                        ?: pendingInboundFailure.get()
                        ?: pendingDecoderFailure.get()
                        ?: SessionFailure.transport("receive loop ended"),
                )
            }
        }

    private fun receiveV1Frame(input: DataInputStream) {
        val firstChannel =
            try {
                input.read()
            } catch (_: SocketTimeoutException) {
                pendingOutboundFailure.get()?.let { throw SessionProtocolException(it) }
                if (heartbeat.isExpired(System.nanoTime())) {
                    throw SessionProtocolException(SessionFailure.heartbeat("heartbeat timeout"))
                }
                return
            }
        if (firstChannel < 0) throw IOException("Protocol v1 transport closed")
        val frame =
            try {
                ProtocolV1Framing.read(input, firstChannel)
            } catch (failure: IOException) {
                throw terminalProtocolFailure(
                    reason = "invalid_frame",
                    source = ProtocolV1Failure.Source.FRAME,
                    cause = failure,
                )
            }
        when (frame.channel) {
            ProtocolChannel.CONTROL -> {
                val envelope =
                    try {
                        Envelope.parseFrom(frame.payload)
                    } catch (failure: Exception) {
                        throw terminalProtocolFailure(
                            reason = "invalid_envelope",
                            source = ProtocolV1Failure.Source.ENVELOPE,
                            cause = failure,
                        )
                    }
                if (envelope.payloadCase == Envelope.PayloadCase.DISCONNECT_NOTICE) {
                    pendingVideoConfigurationCommit.getAndSet(null)?.cancel()
                }
                val completion = CompletableFuture<Unit>()
                val submission = submitOutbound(
                    kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                    command = StreamOutboundCommand.ProtocolReceive(envelope, completion),
                    timeoutMillis = PROTOCOL_ACTION_TIMEOUT_MS,
                )
                if (submission == OutboundCommandScheduler.Submission.TIMED_OUT ||
                    submission == OutboundCommandScheduler.Submission.CLOSED
                ) {
                    throw SessionProtocolException(
                        SessionFailure.protocol(
                            SessionFailureKind.OUTBOUND_BACKPRESSURE,
                            "Protocol receive queue unavailable: $submission",
                        ),
                    )
                }
                awaitProtocolReceive(completion)
                heartbeat.recordInbound(System.nanoTime())
            }
            ProtocolChannel.VIDEO -> {
                val payload =
                    try {
                        ProtocolV1Framing.decodeVideo(frame.payload)
                    } catch (failure: Exception) {
                        throw terminalProtocolFailure(
                            reason = "invalid_media_payload",
                            source = ProtocolV1Failure.Source.MEDIA_PAYLOAD,
                            cause = failure,
                        )
                    }
                val session = checkNotNull(protocolSession)
                val mediaDisposition = session.validateMedia(payload.header)
                if (mediaDisposition != ProtocolV1Session.MediaDisposition.ACCEPT) {
                    releaseBuffer(payload.annexB)
                    emitTelemetry(
                        "frame_dropped",
                        mapOf(
                            "reason" to mediaDisposition.name.lowercase(),
                            "config_epoch" to payload.header.configEpoch,
                            "session_epoch" to connectionEpoch,
                        ),
                    )
                    return
                }
                val receiveTimestamp = System.nanoTime()
                checkKeyframeFreshness(receiveTimestamp, payload.header.keyframe)
                val callback = onFrameReceived
                if (callback == null) {
                    releaseBuffer(payload.annexB)
                } else {
                    callback.invoke(
                        payload.annexB,
                        payload.annexB.size,
                        receiveTimestamp,
                        payload.header.keyframe,
                        connectionEpoch,
                        payload.header.configEpoch,
                    )
                }
                updateStats(payload.annexB.size)
            }
            ProtocolChannel.BULK -> {
                val chunk =
                    try {
                        FileChunk.fromFrame(frame.payload)
                    } catch (failure: Exception) {
                        throw protocolFailure(
                            reason = "invalid_file_payload",
                            source = ProtocolV1Failure.Source.MEDIA_PAYLOAD,
                            cause = failure,
                        )
                    }
                val completion = CompletableFuture<Unit>()
                val submission = submitOutbound(
                    kind = OutboundCommandScheduler.Kind.FILE_TRANSFER,
                    command = StreamOutboundCommand.ProtocolBulk(chunk, completion),
                    timeoutMillis = PROTOCOL_ACTION_TIMEOUT_MS,
                )
                if (submission == OutboundCommandScheduler.Submission.TIMED_OUT ||
                    submission == OutboundCommandScheduler.Submission.CLOSED
                ) {
                    throw SessionProtocolException(
                        SessionFailure.protocol(
                            SessionFailureKind.OUTBOUND_BACKPRESSURE,
                            "Protocol file queue unavailable: $submission",
                        ),
                    )
                }
                awaitProtocolReceive(completion)
                heartbeat.recordInbound(System.nanoTime())
            }
        }
    }

    private fun currentInputSessionState(): StreamInputSessionState {
        val isProtocolV1 = wireMode == WireMode.V1
        val session = if (isProtocolV1) protocolSession else null
        return StreamInputSessionState(
            connected = isConnected,
            protocolV1 = isProtocolV1,
            canSendTouch = session?.canSendTouch == true,
            canSendPointer = session?.canSendPointer == true,
            canSendKeyboard = session?.canSendKeyboard == true,
            canSendStylus = session?.canSendStylus == true,
            canSendExtendedStylus = session?.canSendExtendedStylus == true,
            canSendController = session?.canSendController == true,
        )
    }

    fun sendTouch(
        x: Float,
        y: Float,
        action: Int,
        pointerCount: Int = 1,
        x2: Float = 0f,
        y2: Float = 0f,
    ) = inputDispatcher.sendTouch(x, y, action, pointerCount, x2, y2)

    internal fun sendMotionTouch(
        v1Samples: List<TouchSample>,
        legacyAction: Int,
        legacyPointers: List<MotionPointer>,
    ) = inputDispatcher.sendMotionTouch(v1Samples, legacyAction, legacyPointers)

    internal fun canSendStylus(): Boolean =
        inputDispatcher.canSendStylus()

    internal fun canSendExtendedStylus(): Boolean =
        inputDispatcher.canSendExtendedStylus()

    internal fun sendMotionStylus(samples: List<StylusSample>): Boolean {
        return inputDispatcher.sendMotionStylus(samples)
    }

    /**
     * Forward a native pointer sample (move/drag/button) to the host. buttonMask
     * uses the shared wire bits (bit0 = primary, bit1 = secondary). No-op unless
     * pointer input was negotiated and media is streaming.
     */
    fun sendPointer(
        phase: InputPhase,
        x: Float,
        y: Float,
        buttonMask: Int,
    ): Boolean = inputDispatcher.sendPointer(phase, x, y, buttonMask)

    /** Forward a scroll delta to the host. No-op unless pointer input negotiated. */
    fun sendScroll(
        deltaX: Double,
        deltaY: Double,
    ): Boolean = inputDispatcher.sendScroll(deltaX, deltaY)

    /**
     * Forward a key event to the host. modifierMask uses the canonical USB HID
     * byte; ProtocolV1Session selects the negotiated standard or legacy wire
     * layout. No-op unless keyboard input was negotiated and media is streaming.
     */
    fun sendKey(
        usbHidUsage: Int,
        pressed: Boolean,
        modifierMask: Int,
    ): Boolean = inputDispatcher.sendKey(usbHidUsage, pressed, modifierMask)

    /** Enqueues every native-input boundary in one FIFO batch before teardown. */
    internal fun sendNativeInputRelease(
        release: NativeInputReleasePlan,
        pointerPhase: InputPhase,
    ): Boolean = inputDispatcher.sendNativeInputRelease(release, pointerPhase)

    // Callback for latency measurement (round-trip ping/pong)
    var onLatencyMeasured: ((Double) -> Unit)? = null

    internal var onControllerInputAck: ((ControllerConnection, Boolean, String) -> Unit)? = null

    /** Capabilities negotiated for the active Protocol v1 session, empty otherwise. */
    internal fun negotiatedCapabilities(): Set<dev.vibescreen.protocol.v1.Capability> =
        if (wireMode == WireMode.V1) protocolSession?.negotiated ?: emptySet() else emptySet()

    internal fun sendController(dispatch: ControllerDispatch): Boolean {
        return inputDispatcher.sendController(dispatch)
    }

    /** True when clipboard transfer is available on the active Protocol v1 session. */
    val canSendClipboard: Boolean
        get() = isConnected && wireMode == WireMode.V1 && protocolSession?.canSendClipboard == true

    /** Negotiated clipboard byte limit for the active session; 0 when not negotiated. */
    val negotiatedMaxClipboardBytes: Long
        get() = if (wireMode == WireMode.V1) protocolSession?.negotiatedMaxClipboardBytes ?: 0L else 0L

    /**
     * Offer the given text to the peer as a clipboard transfer.
     * Returns true when the offer was queued; false when clipboard was not
     * negotiated, the session is not streaming, or the text exceeds the limit.
     */
    fun offerClipboard(text: String): Boolean {
        if (!isConnected || wireMode != WireMode.V1) return false
        val session = protocolSession ?: return false
        if (!session.canSendClipboard) return false
        val byteCount = text.toByteArray(StandardCharsets.UTF_8).size.toLong()
        if (byteCount <= 0L || byteCount > session.negotiatedMaxClipboardBytes) return false
        val submission =
            submitOutbound(
                kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                command = StreamOutboundCommand.ProtocolBatch { activeSession ->
                    activeSession.offerClipboard(text)?.let { listOf(it) } ?: emptyList()
                },
            )
        return isOutboundAdmitted(submission)
    }

    /**
     * Request the content for a previously received clipboard offer.
     * Returns true when the request was queued; false when no matching offer
     * exists or clipboard was not negotiated.
     */
    fun requestClipboard(changeId: ByteArray): Boolean {
        if (!isConnected || wireMode != WireMode.V1) return false
        val session = protocolSession ?: return false
        if (!session.canSendClipboard) return false
        val id = ByteString.copyFrom(changeId)
        if (!session.canRequestClipboard(id)) return false
        val submission =
            submitOutbound(
                kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                command = StreamOutboundCommand.ProtocolBatch { activeSession ->
                    activeSession.requestClipboard(id)?.let { listOf(it) } ?: emptyList()
                },
            )
        return isOutboundAdmitted(submission)
    }

    /**
     * Serialize a UI timeout behind the original request so a retry for the
     * same change ID cannot overtake request-state cleanup.
     */
    fun expireClipboardRequest(
        changeId: ByteArray,
        completion: (Boolean) -> Unit,
    ): Boolean {
        if (!isConnected || wireMode != WireMode.V1) return false
        val session = protocolSession ?: return false
        if (!session.canSendClipboard) return false
        val id = ByteString.copyFrom(changeId)
        val submission =
            submitOutbound(
                kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                command = StreamOutboundCommand.ProtocolBatch { activeSession ->
                    completion(activeSession.expireClipboardRequest(id))
                    emptyList()
                },
            )
        return isOutboundAdmitted(submission)
    }

    /**
     * Ask the host to switch the captured display at runtime. No-op unless the
     * session is streaming, display selection was negotiated, and the id names a
     * known, non-current display.
     */
    fun selectDisplay(displayId: String) {
        if (!isConnected || wireMode != WireMode.V1) return
        val session = protocolSession ?: return
        if (!session.isStreaming) return
        submitOutbound(
            kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
            command = StreamOutboundCommand.ProtocolBatch { activeSession ->
                activeSession.selectDisplay(displayId)?.let { listOf(it) } ?: emptyList()
            },
        )
    }

    /**
     * Ask the host to run an advertised action (window migration/return).
     * No-op unless the session is streaming, host actions were negotiated, and
     * the id names an advertised action. The invocation id is generated per
     * request so the eventual HostActionResult can be correlated.
     */
    fun invokeHostAction(actionId: String) {
        if (!isConnected || wireMode != WireMode.V1) return
        val session = protocolSession ?: return
        if (!session.canInvokeHostActions) return
        val invocationId = ByteString.copyFrom(ByteArray(HOST_ACTION_INVOCATION_ID_BYTES).also(protocolRequestRandom::nextBytes))
        submitOutbound(
            kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
            command = StreamOutboundCommand.ProtocolBatch { activeSession ->
                activeSession.invokeHostAction(actionId, invocationId)?.let { listOf(it) } ?: emptyList()
            },
        )
    }

    fun requestWakeHost(
        targetMacAddress: ByteString,
        secureOnPassword: ByteString = ByteString.EMPTY,
    ): Boolean {
        val requestId = ByteString.copyFrom(ByteArray(WAKE_HOST_REQUEST_ID_BYTES).also(protocolRequestRandom::nextBytes))
        return requestWakeHost(requestId, targetMacAddress, secureOnPassword)
    }

    internal fun requestWakeHost(
        requestId: ByteString,
        targetMacAddress: ByteString,
        secureOnPassword: ByteString = ByteString.EMPTY,
    ): Boolean {
        if (!isConnected || wireMode != WireMode.V1) return false
        val session = protocolSession ?: return false
        if (!session.canRequestWakeHost) return false
        val submission =
            submitOutbound(
                kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                command = StreamOutboundCommand.ProtocolBatch { activeSession ->
                    activeSession.requestWakeHost(requestId, targetMacAddress, secureOnPassword)?.let { listOf(it) }
                        ?: emptyList()
                },
            )
        return isOutboundAdmitted(submission)
    }

    /**
     * Ask the host to change video encoding preferences at runtime. No-op unless
     * the session is streaming and client video control was negotiated. Zero /
     * unspecified fields leave the corresponding host setting unchanged.
     */
    fun setVideoPreferences(
        bitrateKbps: Int,
        framesPerSecond: Int,
        qualityPreset: dev.vibescreen.protocol.v1.VideoQualityPreset,
        resetQualityToAuto: Boolean = false,
    ) {
        if (!isConnected || wireMode != WireMode.V1) return
        // Do not gate on isStreaming here: the session coalesces a request that
        // arrives mid-reconfiguration and sends the newest intent once the
        // replacement VideoConfig commits, so dropping it now would lose the
        // last user change.
        protocolSession ?: return
        submitOutbound(
            kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
            command = StreamOutboundCommand.ProtocolBatch { activeSession ->
                activeSession
                    .setVideoPreferences(bitrateKbps, framesPerSecond, qualityPreset, resetQualityToAuto)
                    ?.let { listOf(it) } ?: emptyList()
            },
        )
    }

    /**
     * Ask the host to send an IDR/sync frame.
     *
     * Non-forced requests are rate-limited here so all callers share the same
     * backpressure guard. Forced requests are reserved for startup and hard
     * decoder recovery paths where waiting for the throttle would leave the
     * client black or unsynchronized.
     */
    fun requestKeyframe(
        force: Boolean = false,
        reason: String = "client request",
    ) {
        if (!isConnected) return
        val now = System.nanoTime()
        val shouldSend =
            synchronized(keyframeRequestLock) {
                if (!force &&
                    lastKeyframeRequestNs > 0L &&
                    now - lastKeyframeRequestNs < KEYFRAME_REQUEST_INTERVAL_NS
                ) {
                    false
                } else {
                    lastKeyframeRequestNs = now
                    true
                }
            }
        if (!shouldSend) return

        if (wireMode == WireMode.V1) {
            val session = protocolSession ?: return
            if (!session.isStreaming) return
            submitOutbound(
                kind = OutboundCommandScheduler.Kind.KEYFRAME,
                command = StreamOutboundCommand.ProtocolBatch { listOf(it.requestKeyframe(reason)) },
            )
            return
        }

        val flags = if (force) KEYFRAME_REQUEST_FLAG_FORCE else 0
        diagLog("Requesting keyframe: reason=$reason, force=$force")
        submitOutbound(
            kind = OutboundCommandScheduler.Kind.KEYFRAME,
            command = StreamOutboundCommand.Keyframe(flags),
            timeoutMillis = 0,
        )
    }

    /**
     * Send a ping to measure round-trip latency through the USB connection
     */
    fun sendPing() {
        if (!isConnected) return
        if (wireMode == WireMode.V1) {
            val session = protocolSession ?: return
            if (!session.isStreaming) return
            val sequence = nextPingSequence.getAndIncrement()
            lastV1PingSequence = sequence
            lastV1PingSentNs = System.nanoTime()
            submitOutbound(
                kind = OutboundCommandScheduler.Kind.PING,
                command = StreamOutboundCommand.ProtocolBatch { listOf(it.ping(sequence)) },
            )
            return
        }
        submitOutbound(
            kind = OutboundCommandScheduler.Kind.PING,
            command = StreamOutboundCommand.Ping(System.nanoTime()),
        )
    }

    private fun submitOutbound(
        kind: OutboundCommandScheduler.Kind,
        command: StreamOutboundCommand,
        timeoutMillis: Long = 0,
    ): OutboundCommandScheduler.Submission {
        val submission =
            try {
                outboundScheduler.submit(kind, command, timeoutMillis)
            } catch (error: InterruptedException) {
                Thread.currentThread().interrupt()
                requestConnectionEnd(SessionFailure.write("outbound submission interrupted"))
                return OutboundCommandScheduler.Submission.CLOSED
            }
        if (submission == OutboundCommandScheduler.Submission.TIMED_OUT &&
            kind != OutboundCommandScheduler.Kind.MOVE &&
            kind != OutboundCommandScheduler.Kind.PING
        ) {
            requestConnectionEnd(
                SessionFailure.protocol(
                    SessionFailureKind.OUTBOUND_BACKPRESSURE,
                    "Outbound queue saturated while preserving $kind",
                ),
            )
        }
        return submission
    }

    private fun isOutboundAdmitted(submission: OutboundCommandScheduler.Submission): Boolean =
        submission != OutboundCommandScheduler.Submission.TIMED_OUT &&
            submission != OutboundCommandScheduler.Submission.CLOSED


    private fun writeOutboundCommand(command: StreamOutboundCommand) {
        val out = transportOwner.activeConnection()?.output ?: throw IOException("session output is closed")
        when (command) {
            is StreamOutboundCommand.Touch -> {
                val size = 6 + command.pointerCount * 8
                val buffer = ByteBuffer.allocate(size).order(ByteOrder.LITTLE_ENDIAN)
                buffer.put(MESSAGE_TOUCH.toByte())
                buffer.put(command.pointerCount.toByte())
                buffer.putFloat(command.x)
                buffer.putFloat(command.y)
                if (command.pointerCount == 2) {
                    buffer.putFloat(command.x2)
                    buffer.putFloat(command.y2)
                }
                buffer.putInt(command.action)
                out.write(buffer.array())
            }

            is StreamOutboundCommand.Keyframe ->
                out.write(byteArrayOf(MESSAGE_KEYFRAME_REQUEST.toByte(), command.flags.toByte()))

            is StreamOutboundCommand.Ping -> {
                val buffer = ByteBuffer.allocate(9).order(ByteOrder.LITTLE_ENDIAN)
                buffer.put(MESSAGE_PING.toByte())
                buffer.putLong(command.sentAtNs)
                out.write(buffer.array())
            }

            is StreamOutboundCommand.LegacyControl -> out.write(command.payload)

            is StreamOutboundCommand.ProtocolBatch -> {
                val session = checkNotNull(protocolSession) { "Protocol v1 session is closed" }
                command.build(session).forEach { writeProtocolEnvelope(out, it) }
            }

            is StreamOutboundCommand.ProtocolReceive -> processProtocolReceive(out, command)

            is StreamOutboundCommand.ProtocolVideoConfigurationCompletion ->
                processVideoConfigurationCompletion(out, command)

            is StreamOutboundCommand.ProtocolBulk -> processProtocolBulk(out, command)

            is StreamOutboundCommand.ProtocolSendBulk ->
                ProtocolV1Framing.write(out, ProtocolChannel.BULK, command.chunk.toFrame())

            is StreamOutboundCommand.ProtocolWakeHostCompletion ->
                processWakeHostCompletion(out, command)
        }
        if (command !is StreamOutboundCommand.ProtocolBatch &&
            command !is StreamOutboundCommand.ProtocolReceive &&
            command !is StreamOutboundCommand.ProtocolBulk &&
            command !is StreamOutboundCommand.ProtocolSendBulk &&
            command !is StreamOutboundCommand.ProtocolVideoConfigurationCompletion &&
            command !is StreamOutboundCommand.ProtocolWakeHostCompletion
        ) {
            out.flush()
        }
    }

    private fun processProtocolReceive(
        out: java.io.DataOutputStream,
        command: StreamOutboundCommand.ProtocolReceive,
    ) {
        val session = checkNotNull(protocolSession) { "Protocol v1 session is closed" }
        try {
            val actions = session.receive(command.envelope)
            when (val result = protocolActionDispatcher.dispatchReceivedActions(out, session, connectionEpoch, actions)) {
                StreamProtocolActionDispatcher.ReceiveResult.Completed -> command.completion.complete(Unit)
                is StreamProtocolActionDispatcher.ReceiveResult.Disconnected -> {
                    command.completion.completeExceptionally(SessionProtocolException(result.failure))
                    return
                }
            }
        } catch (failure: ProtocolV1Failure) {
            pendingVideoConfigurationCommit.getAndSet(null)?.cancel()
            if (failure.source == ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION &&
                command.envelope.payloadCase != Envelope.PayloadCase.PROTOCOL_ERROR
            ) {
                try {
                    writeProtocolEnvelope(
                        out,
                        session.protocolError(
                            failure.message ?: "invalid protocol state",
                            correlationId = command.envelope.messageId,
                        ),
                    )
                } catch (writeFailure: IOException) {
                    failure.addSuppressed(writeFailure)
                    command.completion.completeExceptionally(failure)
                    throw writeFailure
                }
            }
            val sessionFailure = failure.toSessionFailure()
            pendingInboundFailure.compareAndSet(null, sessionFailure)
            completeConnectionEndNow(sessionFailure)
            command.completion.completeExceptionally(SessionProtocolException(sessionFailure))
        } catch (failure: IOException) {
            pendingVideoConfigurationCommit.getAndSet(null)?.cancel()
            requestConnectionEnd(
                SessionFailure.write(failure.message ?: "Protocol v1 receive write failed"),
            )
            command.completion.completeExceptionally(failure)
            throw failure
        } catch (failure: RuntimeException) {
            pendingVideoConfigurationCommit.getAndSet(null)?.cancel()
            requestConnectionEnd(
                SessionFailure.protocol(
                    SessionFailureKind.INVALID_PEER_MESSAGE,
                    failure.message ?: "Protocol v1 receive processing failed",
                ),
            )
            command.completion.completeExceptionally(failure)
            throw failure
        }
    }

    private inner class StreamProtocolActionSink : StreamProtocolActionDispatcher.Sink {
        override fun writeProtocolEnvelope(
            out: java.io.DataOutputStream,
            envelope: Envelope,
        ) = this@StreamClient.writeProtocolEnvelope(out, envelope)

        override fun onDisplaysAvailable(
            displays: List<ProtocolV1Session.DisplayOption>,
            selectedId: String,
        ) {
            val options =
                displays.map {
                    StreamDisplayOption(
                        it.id,
                        it.name,
                        it.width,
                        it.height,
                        it.isPrimary,
                        it.isVirtual,
                    )
                }
            onDisplaysAvailable?.invoke(options, selectedId)
        }

        override fun onVideoConfigurationRequested(
            session: ProtocolV1Session,
            configurationToken: Long,
            codec: Codec,
            width: Int,
            height: Int,
            rotation: Int,
            configEpoch: Long,
            bitrateKbps: Int,
            framesPerSecond: Int,
        ) {
            streamCodecIsHevc = codec == Codec.CODEC_HEVC
            codecNegotiated = true
            onCodecSelected?.invoke(streamCodecIsHevc)
            beginVideoConfiguration(
                session = session,
                configurationToken = configurationToken,
                configuration = StreamVideoConfiguration(
                    encodedWidth = width,
                    encodedHeight = height,
                    rotation = rotation,
                    configEpoch = configEpoch,
                    bitrateKbps = bitrateKbps,
                    framesPerSecond = framesPerSecond,
                ),
            )
        }

        override fun onVideoConfigurationRejectedBeforeResponse(reason: String) {
            // Publish the local codec reason before the rejection ACK can make the
            // peer close its socket. If EOF races the async termination request,
            // the receive loop must still report CODEC_CONFIGURATION.
            pendingDecoderFailure.compareAndSet(null, SessionFailure.codec(reason))
        }

        override fun onVideoConfigurationCommitted(appliesClientVideoPreferences: Boolean) {
            if (!sessionReady) {
                sessionReady = true
                reconnectBackoff.reset()
                onConnectionStatus?.invoke(true)
            }
        }

        override fun onDisplayGeometryChanged(
            width: Int,
            height: Int,
            rotation: Int,
        ) {
            onDisplayGeometry?.invoke(
                StreamDisplayGeometry(
                    logicalWidth = width,
                    logicalHeight = height,
                    rotation = rotation,
                ),
            )
        }

        override fun onPongReceived(sequence: Long) {
            if (sequence == lastV1PingSequence && lastV1PingSentNs > 0L) {
                onLatencyMeasured?.invoke((System.nanoTime() - lastV1PingSentNs) / 1_000_000.0)
            }
        }

        override fun onControllerInputAck(
            inputId: Long,
            accepted: Boolean,
            rejectionReason: String,
        ) {
            controllerConnectionAcks.acknowledge(inputId)?.let { connection ->
                onControllerInputAck?.invoke(connection, accepted, rejectionReason)
            }
        }

        override fun onHostActionsAvailable(actions: List<ProtocolV1Session.HostAction>) {
            val options = actions.map { HostActionOption(it.id, it.localizedName, it.requiresConfirmation) }
            onHostActionsAvailable?.invoke(options)
        }

        override fun onHostActionCompleted(
            accepted: Boolean,
            rejectionReason: String,
        ) {
            onHostActionResult?.invoke(accepted, rejectionReason)
        }

        override fun onClipboardOffered(
            session: ProtocolV1Session,
            connectionGeneration: Long,
            changeId: ByteString,
            originDeviceId: String,
            mimeType: String,
            byteLength: Long,
            sha256: ByteString,
        ) {
            if (!isCurrentProtocolSession(session, connectionGeneration)) return
            onClipboardOffered?.invoke(
                ClipboardOfferData(
                    changeId = changeId.toByteArray(),
                    originDeviceId = originDeviceId,
                    mimeType = mimeType,
                    byteLength = byteLength,
                    sha256 = sha256.toByteArray(),
                ),
            )
        }

        override fun onClipboardContentReceived(
            session: ProtocolV1Session,
            connectionGeneration: Long,
            changeId: ByteString,
            originDeviceId: String,
            mimeType: String,
            content: ByteArray,
            sha256: ByteString,
            pending: Boolean,
        ) {
            if (!isCurrentProtocolSession(session, connectionGeneration)) return
            onClipboardContentReceived?.invoke(
                ClipboardContentData(
                    changeId = changeId.toByteArray(),
                    originDeviceId = originDeviceId,
                    mimeType = mimeType,
                    content = content,
                    sha256 = sha256.toByteArray(),
                    pending = pending,
                ),
            )
        }

        override fun onManagedPolicyReceived(status: dev.vibescreen.protocol.v1.ManagedPolicyStatus) {
            remoteManagedPolicy = RemoteManagedPolicy(status)
        }

        override fun onFileOfferReceived(
            out: java.io.DataOutputStream,
            session: ProtocolV1Session,
            offer: dev.vibescreen.protocol.v1.FileOffer,
        ) {
            val manager = checkNotNull(incomingFileTransfers.get()) { "Incoming file manager is closed" }
            val response =
                try {
                    manager.accept(
                        offer,
                        remotePolicy = remoteManagedPolicy,
                        negotiatedPolicy = session.negotiatedFilePolicy,
                        sessionEpoch = session.activeSessionEpoch,
                    )
                } catch (failure: FileTransferException) {
                    rejectedFileAccept(offer.transferId, failure.reasonCode)
                }
            session.fileAccept(response)?.let { writeProtocolEnvelope(out, it) }
        }

        override fun onFileAcceptReceived(
            out: java.io.DataOutputStream,
            session: ProtocolV1Session,
            response: FileAccept,
        ) {
            if (response.accepted) {
                outgoingFileTransfers[response.transferId]?.let { transfer ->
                    transfer.applyAcceptedMaximumChunkBytes(response.maximumChunkBytes)
                    sendNextOutgoingFileChunk(out, session, transfer)
                }
            } else {
                outgoingFileTransfers.remove(response.transferId)?.cancel()
                onFileTransferResult?.invoke(false, response.rejectionReason)
            }
        }

        override fun onFileProgressReceived(
            out: java.io.DataOutputStream,
            session: ProtocolV1Session,
            progress: dev.vibescreen.protocol.v1.FileTransferProgress,
        ) {
            outgoingFileTransfers[progress.transferId]?.let { transfer ->
                sendNextOutgoingFileChunk(out, session, transfer)
            }
        }

        override fun onFileCancelReceived(cancellation: dev.vibescreen.protocol.v1.FileTransferCancel) {
            incomingFileTransfers.get()?.cancel(cancellation.transferId)
            outgoingFileTransfers.remove(cancellation.transferId)?.cancel()
            onFileTransferResult?.invoke(false, cancellation.reasonCode)
        }

        override fun onFileCompleteReceived(result: dev.vibescreen.protocol.v1.FileTransferComplete) {
            outgoingFileTransfers.remove(result.transferId)?.cancel()
            onFileTransferResult?.invoke(result.accepted, result.rejectionReason)
        }

        override fun onWakeHostRequested(
            session: ProtocolV1Session,
            connectionGeneration: Long,
            request: WakeHostRequestContext,
            correlationId: Long,
        ) {
            dispatchWakeHostRequest(
                session = session,
                connectionGeneration = connectionGeneration,
                request = request,
                correlationId = correlationId,
            )
        }

        override fun onWakeHostCompleted(
            accepted: Boolean,
            rejectionReason: String,
        ) {
            onWakeHostResult?.invoke(accepted, rejectionReason)
        }

        override fun onDisconnected(
            reasonCode: String,
            mayResume: Boolean,
        ): SessionFailure {
            pendingVideoConfigurationCommit.getAndSet(null)?.cancel()
            stopRequested = !mayResume
            val failure =
                if (mayResume) {
                    SessionFailure.transport("Host ended Protocol v1 session and allowed resume")
                } else if (reasonCode == "host_shutdown") {
                    SessionFailure.serverShutdown()
                } else {
                    SessionFailure(
                        kind = SessionFailureKind.HOST_PROTOCOL_ERROR,
                        detail = "Host ended Protocol v1 session: $reasonCode",
                        retryable = false,
                    )
                }
            requestConnectionEnd(failure)
            return failure
        }
    }

    private fun processProtocolBulk(
        out: java.io.DataOutputStream,
        command: StreamOutboundCommand.ProtocolBulk,
    ) {
        val session = checkNotNull(protocolSession) { "Protocol v1 session is closed" }
        val manager = incomingFileTransfers.get()
        if (manager == null) {
            session.fileCancel(command.chunk.header.transferId, "policy_denied")?.let { writeProtocolEnvelope(out, it) }
            command.completion.complete(Unit)
            return
        }
        try {
            val received = manager.append(command.chunk, session.activeSessionEpoch)
            session.fileProgress(command.chunk.header.transferId, received)?.let { writeProtocolEnvelope(out, it) }
            if (command.chunk.header.final) {
                val completed = manager.finish(command.chunk.header.transferId)
                session.fileComplete(
                    transferId = completed.transferId,
                    accepted = true,
                    sha256 = completed.sha256,
                    rejectionReason = "",
                )?.let { writeProtocolEnvelope(out, it) }
                onIncomingFileCompleted?.invoke(completed)
            }
            out.flush()
            command.completion.complete(Unit)
        } catch (failure: FileTransferException) {
            manager.cancel(command.chunk.header.transferId)
            session.fileCancel(command.chunk.header.transferId, failure.reasonCode)?.let { writeProtocolEnvelope(out, it) }
            out.flush()
            command.completion.completeExceptionally(failure)
        } catch (failure: IOException) {
            manager.cancel(command.chunk.header.transferId)
            session.fileCancel(command.chunk.header.transferId, "io_failure")?.let { writeProtocolEnvelope(out, it) }
            out.flush()
            command.completion.completeExceptionally(failure)
            throw failure
        }
    }

    private fun sendNextOutgoingFileChunk(
        out: java.io.DataOutputStream,
        session: ProtocolV1Session,
        transfer: OutgoingFileTransfer,
    ) {
        try {
            if (!outgoingFileTransfers.containsKey(transfer.offer.transferId)) return
            val chunk = transfer.nextChunk(
                maximumBytes = transfer.maximumChunkBytes(defaultBytes = fileTransferPolicy.maximumChunkBytes),
                sessionEpoch = session.activeSessionEpoch,
            ) ?: return
            ProtocolV1Framing.write(out, ProtocolChannel.BULK, chunk.toFrame())
        } catch (failure: FileTransferException) {
            outgoingFileTransfers.remove(transfer.offer.transferId)?.cancel()
            session.fileCancel(transfer.offer.transferId, failure.reasonCode)?.let { writeProtocolEnvelope(out, it) }
        }
    }

    private fun performWakeHostRequest(request: WakeHostRequestContext): Pair<Boolean, String> =
        try {
            val packet = WakeHostDecision.magicPacket(request, wakeHostPolicy)
            wakeHostPacketSender.send(packet)
            true to ""
        } catch (failure: WakeHostRequestException) {
            false to
                when (failure.failure) {
                    WakeHostRequestFailure.INVALID_REQUEST_ID -> "invalid_request_id"
                    WakeHostRequestFailure.INVALID_MAC_ADDRESS -> "invalid_mac_address"
                    WakeHostRequestFailure.INVALID_SECURE_ON_PASSWORD -> "invalid_secure_on_password"
                    WakeHostRequestFailure.POLICY_DENIED -> "wake_host_policy_denied"
                }
        } catch (failure: Exception) {
            Log.w(TAG, "WakeHost packet send failed with ${failure.javaClass.simpleName}", failure)
            false to "wake_packet_send_failed"
        }

    private fun dispatchWakeHostRequest(
        session: ProtocolV1Session,
        connectionGeneration: Long,
        request: WakeHostRequestContext,
        correlationId: Long,
    ) {
        if (!trackInboundWakeHostRequest(request.requestId)) {
            submitOutbound(
                kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                command = StreamOutboundCommand.ProtocolWakeHostCompletion(
                    session = session,
                    connectionGeneration = connectionGeneration,
                    requestId = request.requestId,
                    accepted = false,
                    rejectionReason = "too_many_pending_wake_host_requests",
                    correlationId = correlationId,
                ),
                timeoutMillis = PROTOCOL_ACTION_TIMEOUT_MS,
            )
            return
        }
        wakeHostExecutor.execute {
            val (accepted, reason) = performWakeHostRequest(request)
            val submission =
                submitOutbound(
                    kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                    command = StreamOutboundCommand.ProtocolWakeHostCompletion(
                        session = session,
                        connectionGeneration = connectionGeneration,
                        requestId = request.requestId,
                        accepted = accepted,
                        rejectionReason = reason,
                        correlationId = correlationId,
                    ),
                    timeoutMillis = PROTOCOL_ACTION_TIMEOUT_MS,
                )
            if (!isOutboundAdmitted(submission)) {
                releaseInboundWakeHostRequest(request.requestId)
                requestConnectionEnd(
                    SessionFailure.protocol(
                        SessionFailureKind.OUTBOUND_BACKPRESSURE,
                        "WakeHost completion queue unavailable: $submission",
                    ),
                )
            }
        }
    }

    @Synchronized
    private fun trackInboundWakeHostRequest(requestId: ByteString): Boolean {
        if (pendingInboundWakeHostRequests.contains(requestId)) return false
        if (pendingInboundWakeHostRequests.size >= MAX_PENDING_INBOUND_WAKE_HOST_REQUESTS) return false
        pendingInboundWakeHostRequests.addLast(requestId)
        return true
    }

    @Synchronized
    private fun releaseInboundWakeHostRequest(requestId: ByteString) {
        pendingInboundWakeHostRequests.remove(requestId)
    }

    private fun processWakeHostCompletion(
        out: java.io.DataOutputStream,
        command: StreamOutboundCommand.ProtocolWakeHostCompletion,
    ) {
        try {
            if (!isCurrentProtocolSession(command.session, command.connectionGeneration)) return
            command.session.completeWakeHost(
                requestId = command.requestId,
                accepted = command.accepted,
                rejectionReason = command.rejectionReason,
                correlationId = command.correlationId,
            )?.let { writeProtocolEnvelope(out, it) }
        } finally {
            releaseInboundWakeHostRequest(command.requestId)
        }
    }

    private fun beginVideoConfiguration(
        session: ProtocolV1Session,
        configurationToken: Long,
        configuration: StreamVideoConfiguration,
    ) {
        val pending =
            PendingVideoConfigurationCommit(
                session = session,
                connectionGeneration = connectionEpoch,
                configuration = configuration,
                configurationToken = configurationToken,
            )
        if (!pendingVideoConfigurationCommit.compareAndSet(null, pending)) {
            throw IllegalStateException("A decoder configuration commit is already pending")
        }
        pending.scheduleTimeout()
        val callback = onVideoConfiguration
        if (callback == null) {
            pending.complete(StreamVideoConfigurationDecision.reject("decoder_configuration_callback_missing"))
            return
        }
        try {
            callback.invoke(configuration, pending)
        } catch (failure: RuntimeException) {
            pending.complete(
                StreamVideoConfigurationDecision.reject(
                    failure.message ?: "decoder_configuration_callback_failure",
                ),
            )
        }
    }

    private fun processVideoConfigurationCompletion(
        out: java.io.DataOutputStream,
        command: StreamOutboundCommand.ProtocolVideoConfigurationCompletion,
    ) {
        val pending = command.pending as? PendingVideoConfigurationCommit ?: return
        if (!pendingVideoConfigurationCommit.compareAndSet(pending, null)) return
        if (!isCurrentProtocolSession(pending.session, pending.connectionGeneration)) return
        val actions =
            pending.session.completeVideoConfiguration(
                completedConfigEpoch = pending.configuration.configEpoch,
                configurationToken = pending.configurationToken,
                accepted = command.decision.accepted,
                rejectionReason = command.decision.rejectionReason,
            )
        if (actions.isEmpty()) {
            requestConnectionEnd(
                SessionFailure.protocol(
                    SessionFailureKind.INVALID_PEER_MESSAGE,
                    "Decoder completion no longer matches the pending VideoConfig",
                ),
            )
            return
        }
        val result = protocolActionDispatcher.dispatchVideoConfigurationCompletionActions(out, actions)
        out.flush()
        if (result.configurationCommitted && isCurrentProtocolSession(pending.session, pending.connectionGeneration)) {
            onVideoConfigurationApplied?.invoke(
                pending.configuration.copy(
                    appliesClientVideoPreferences = result.appliesClientVideoPreferences,
                ),
            )
        }
        result.rejectionReason?.let { requestConnectionEnd(SessionFailure.codec(it)) }
    }

    private fun isCurrentProtocolSession(
        expectedSession: ProtocolV1Session,
        expectedConnectionGeneration: Long,
    ): Boolean =
        isConnected &&
            connectionEpoch == expectedConnectionGeneration &&
            SESSION_EPOCHS.accepts(expectedConnectionGeneration) &&
            protocolSession === expectedSession

    private fun writeProtocolEnvelope(
        out: java.io.DataOutputStream,
        envelope: Envelope,
    ) = ProtocolV1Framing.write(out, ProtocolChannel.CONTROL, envelope.toByteArray())

    private fun rejectedFileAccept(transferId: ByteString, reasonCode: String): FileAccept =
        FileAccept
            .newBuilder()
            .setTransferId(transferId)
            .setAccepted(false)
            .setRejectionReason(reasonCode)
            .build()

    private fun awaitProtocolReceive(completion: CompletableFuture<Unit>) {
        try {
            completion.get(PROTOCOL_ACTION_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        } catch (failure: ExecutionException) {
            val cause = failure.cause ?: failure
            when (cause) {
                is ProtocolV1Failure -> throw cause
                is SessionProtocolException -> throw cause
                is IOException -> throw cause
                else -> throw IOException("Protocol v1 receive processing failed", cause)
            }
        } catch (failure: TimeoutException) {
            throw IOException("Protocol v1 receive processing timed out", failure)
        } catch (failure: InterruptedException) {
            Thread.currentThread().interrupt()
            throw IOException("Protocol v1 receive processing interrupted", failure)
        }
    }

    private fun updateStats(bytes: Int) {
        bytesReceived += bytes
        framesReceived++

        val now = System.currentTimeMillis()
        val elapsed = now - lastStatsTime

        if (elapsed >= 1000) {
            val mbps = (bytesReceived * 8.0) / (elapsed / 1000.0) / 1_000_000
            val fps = (framesReceived * 1000.0) / elapsed
            onStats?.invoke(fps, mbps)
            emitTelemetry(
                "stream_stats",
                mapOf(
                    "session_epoch" to connectionEpoch,
                    "fps" to fps,
                    "mbps" to mbps,
                ),
            )

            bytesReceived = 0
            framesReceived = 0
            lastStatsTime = now
        }
    }

    private fun receiveVideoFrame(
        input: DataInputStream,
        hasMetadata: Boolean,
    ) {
        val frameSize = input.readInt()

        if (frameSize <= 0 || frameSize > MAX_FRAME_SIZE) {
            throw SessionProtocolException(
                SessionFailure.protocol(SessionFailureKind.INVALID_FRAME, "Invalid frame size: $frameSize"),
            )
        }

        var isKeyframe = false
        if (hasMetadata) {
            val flags = input.readUnsignedByte()
            input.readLong() // Host capture timestamp; clocks are not comparable with Android.
            isKeyframe = (flags and FRAME_FLAG_KEYFRAME) != 0
        }

        val frameData = acquireBuffer(frameSize)
        input.readFully(frameData, 0, frameSize)

        if (!hasMetadata && !isKeyframe) {
            isKeyframe = isSyncFrame(frameData, frameSize, streamCodecIsHevc)
        }

        // Capture timestamp after full frame received for accurate age tracking.
        val receiveTimestamp = System.nanoTime()
        val epoch = connectionEpoch
        if (!SESSION_EPOCHS.accepts(epoch)) {
            releaseBuffer(frameData)
            emitTelemetry(
                "frame_dropped",
                mapOf(
                    "reason" to "stale_session_epoch",
                    "frame_epoch" to epoch,
                    "current_epoch" to SESSION_EPOCHS.currentEpoch(),
                ),
            )
            return
        }
        checkKeyframeFreshness(receiveTimestamp, isKeyframe)
        diagFrameCount++
        if (diagFrameCount == 1L) {
            diagLog(
                "First video frame: size=$frameSize, keyframe=$isKeyframe, " +
                    "metadata=$hasMetadata, callback=${onFrameReceived != null}",
            )
        }
        if (diagFrameCount % 60L == 0L) {
            diagLog("Frames received: $diagFrameCount")
        }

        val callback = onFrameReceived
        if (callback != null) {
            callback.invoke(
                frameData,
                frameSize,
                receiveTimestamp,
                isKeyframe,
                epoch,
                LEGACY_CONFIG_EPOCH,
            )
        } else {
            releaseBuffer(frameData)
        }
        updateStats(frameSize)
    }

    private fun checkKeyframeFreshness(
        receiveTimestamp: Long,
        isKeyframe: Boolean,
    ) {
        if (isKeyframe) {
            lastKeyframeReceivedNs = receiveTimestamp
            return
        }

        val lastKeyframeNs = lastKeyframeReceivedNs
        if (lastKeyframeNs <= 0L) return

        val keyframeAgeNs = receiveTimestamp - lastKeyframeNs
        if (keyframeAgeNs > KEYFRAME_STALE_INTERVAL_NS) {
            requestKeyframe(
                reason = "last keyframe ${keyframeAgeNs / 1_000_000L}ms ago",
            )
        }
    }

    fun disconnect() {
        stopRequested = true
        requestConnectionEnd(SessionFailure.userRequested())
    }

    fun failCurrentSession(reason: String) {
        stopRequested = false
        requestConnectionEnd(SessionFailure.codec(reason))
    }

    fun offerFile(file: File, mimeType: String = "application/octet-stream") {
        if (!isConnected || wireMode != WireMode.V1) return
        val transfer =
            try {
                OutgoingFileTransfer(
                    file = file,
                    mimeType = mimeType,
                    policy = fileTransferPolicy,
                    remotePolicy = remoteManagedPolicy,
                )
            } catch (failure: FileTransferException) {
                onFileTransferResult?.invoke(false, failure.reasonCode)
                return
            }
        val submission = submitOutbound(
            kind = OutboundCommandScheduler.Kind.FILE_TRANSFER,
            command = StreamOutboundCommand.ProtocolBatch { session ->
                if (!session.canTransferFiles || outgoingFileTransfers.isNotEmpty()) {
                    transfer.cancel()
                    emptyList()
                } else {
                    outgoingFileTransfers[transfer.offer.transferId] = transfer
                    listOfNotNull(session.offerFile(transfer.offer))
                }
            },
            timeoutMillis = PROTOCOL_ACTION_TIMEOUT_MS,
        )
        if (submission == OutboundCommandScheduler.Submission.TIMED_OUT ||
            submission == OutboundCommandScheduler.Submission.CLOSED
        ) {
            transfer.cancel()
            onFileTransferResult?.invoke(false, "outbound_backpressure")
        }
    }

    private fun requestConnectionEnd(failure: SessionFailure) {
        terminationDispatcher.dispatch(TerminationRequest(failure, isConnected))
    }

    private fun completeConnectionEndNow(failure: SessionFailure) {
        terminationDispatcher.completeNow(TerminationRequest(failure, isConnected))
    }

    private fun completeConnectionEnd(request: TerminationRequest) {
        val failure = request.failure
        val wasConnected = request.wasConnected
        cleanup()
        if (!wasConnected && connectionEpoch == 0L) return
        val ownsCurrentEpoch = connectionEpoch == 0L || SESSION_EPOCHS.accepts(connectionEpoch)
        if (ownsCurrentEpoch) {
            onSessionEnded?.invoke(failure)
            if (failure.kind == SessionFailureKind.SERVER_SHUTDOWN) {
                onServerShutdown?.invoke()
            }
            onConnectionStatus?.invoke(false)
        }
        if (wasConnected) {
            emitTelemetry(
                "connection_closed",
                mapOf(
                    "reason" to failure.detail,
                    "failure_kind" to failure.kind.name,
                    "retryable" to failure.retryable,
                    "session_epoch" to connectionEpoch,
                    "intentional" to failure.intentional,
                ),
            )
        }
        if (failure.retryable && ownsCurrentEpoch) {
            val delayMs = reconnectBackoff.nextDelayMs()
            emitTelemetry(
                "reconnect_scheduled",
                mapOf("delay_ms" to delayMs, "session_epoch" to connectionEpoch),
            )
            onReconnectSuggested?.invoke(delayMs)
        }
        Log.d(TAG, "Disconnected: ${failure.kind}: ${failure.detail}")
    }

    private fun cleanup() {
        pendingVideoConfigurationCommit.getAndSet(null)?.cancel()
        try {
            try {
                if (!outboundScheduler.shutdownGracefully(OUTBOUND_DRAIN_TIMEOUT_MS)) {
                    outboundScheduler.shutdownNow()
                }
            } catch (error: InterruptedException) {
                Thread.currentThread().interrupt()
                outboundScheduler.shutdownNow()
            }
            closeTransport()
        } catch (e: Exception) {
            Log.e(TAG, "Error during cleanup", e)
        }
        protocolSession = null
        incomingFileTransfers.getAndSet(null)?.cancelAll()
        outgoingFileTransfers.values.forEach { it.cancel() }
        outgoingFileTransfers.clear()
        remoteManagedPolicy = RemoteManagedPolicy.UNMANAGED
        pendingInboundWakeHostRequests.clear()
        controllerConnectionAcks.reset()
        pendingLegacyFirstByte = null
        lanSecureRecordSession?.close()
        lanSecureRecordSession = null
        lanRecordProtectionState = LanRecordProtectionState.NOT_APPLICABLE
        nextOutboundChannel = dev.telemachus.display.internet.SessionChannel.CONTROL
    }

    private fun cleanupCandidateTransport(
        candidate: StreamTransportCandidate<SocketStreamTransportConnection>,
    ) {
        logTransportCloseFailures(transportOwner.release(candidate))
        logTransportCloseFailures(transportOwner.closeAll())
        outboundScheduler.shutdownNow()
    }

    private fun ProtocolV1Failure.toSessionFailure(): SessionFailure =
        SessionFailure(
            kind =
                when (source) {
                    ProtocolV1Failure.Source.SESSION_REJECTED -> SessionFailureKind.SESSION_REJECTED
                    ProtocolV1Failure.Source.HOST_PROTOCOL_ERROR -> SessionFailureKind.HOST_PROTOCOL_ERROR
                    ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION ->
                        if (reason == "invalid_media_header") {
                            SessionFailureKind.INVALID_MEDIA_HEADER
                        } else {
                            SessionFailureKind.INVALID_PEER_MESSAGE
                        }
                    ProtocolV1Failure.Source.FRAME -> SessionFailureKind.INVALID_FRAME
                    ProtocolV1Failure.Source.ENVELOPE -> SessionFailureKind.INVALID_ENVELOPE
                    ProtocolV1Failure.Source.MEDIA_PAYLOAD -> SessionFailureKind.INVALID_MEDIA_PAYLOAD
                },
            detail = "$reason: ${message ?: reason}",
            retryable = retryable,
        )

    private fun protocolFailure(
        reason: String,
        source: ProtocolV1Failure.Source,
        cause: Throwable,
    ): ProtocolV1Failure =
        ProtocolV1Failure(
            reason = reason,
            retryable = false,
            source = source,
            message = "$reason: ${cause.message ?: cause.javaClass.simpleName}",
            cause = cause,
        )

    private fun terminalProtocolFailure(
        reason: String,
        source: ProtocolV1Failure.Source,
        cause: Throwable,
    ): SessionProtocolException {
        val failure = protocolFailure(reason, source, cause).toSessionFailure()
        pendingInboundFailure.compareAndSet(null, failure)
        completeConnectionEndNow(failure)
        return SessionProtocolException(failure)
    }

    private fun diagLog(msg: String) = DiagLog.log("SC", msg)

    private fun emitTelemetry(
        event: String,
        fields: Map<String, Any?> = emptyMap(),
    ) {
        Log.i(TELEMETRY_TAG, TelemetryJson.encode(event, System.currentTimeMillis(), fields))
    }

    private inner class PendingVideoConfigurationCommit(
        override val session: ProtocolV1Session,
        override val connectionGeneration: Long,
        override val configuration: StreamVideoConfiguration,
        override val configurationToken: Long,
    ) : StreamVideoConfigurationPendingCommit {
        private val stateLock = Any()
        private var state = VideoConfigurationCommitState.PENDING
        @Volatile private var timeout: ScheduledFuture<*>? = null

        fun scheduleTimeout() {
            timeout =
                videoConfigurationTimeoutExecutor.schedule(
                    {
                        timeout(
                            StreamVideoConfigurationDecision.reject(
                                "decoder_configuration_timeout",
                            ),
                        )
                    },
                    videoConfigurationCommitTimeoutMs,
                    TimeUnit.MILLISECONDS,
                )
        }

        override fun isPending(): Boolean =
            synchronized(stateLock) {
                state in ACTIVE_VIDEO_CONFIGURATION_COMMIT_STATES &&
                    isCurrentProtocolSession(session, connectionGeneration)
            }

        override fun tryPublish(publish: () -> Boolean): Boolean {
            val claimed =
                synchronized(stateLock) {
                    if (state != VideoConfigurationCommitState.PENDING ||
                        !isCurrentProtocolSession(session, connectionGeneration)
                    ) {
                        return@synchronized false
                    }
                    state = VideoConfigurationCommitState.RESERVED
                    true
                }
            if (!claimed) return false
            val published =
                try {
                    publish()
                } catch (failure: RuntimeException) {
                    // The commit is already RESERVED, and timeout() can only
                    // claim a PENDING commit, so a throwing publish() would
                    // otherwise strand the state machine in RESERVED with
                    // isPending() stuck true. Reject the commit before
                    // rethrowing so it leaves the active states.
                    complete(
                        StreamVideoConfigurationDecision.reject(
                            DECODER_CONFIGURATION_PUBLISH_FAILED_REASON,
                        ),
                    )
                    throw failure
                }
            if (published) {
                timeout?.cancel(false)
            } else {
                complete(
                    StreamVideoConfigurationDecision.reject(
                        DECODER_CONFIGURATION_NOT_PUBLISHED_REASON,
                    ),
                )
            }
            return published
        }

        override fun complete(decision: StreamVideoConfigurationDecision) {
            val claimed =
                synchronized(stateLock) {
                    if (decision.accepted) {
                        if (state != VideoConfigurationCommitState.RESERVED) return@synchronized false
                    } else if (state !in ACTIVE_VIDEO_CONFIGURATION_COMMIT_STATES) {
                        return@synchronized false
                    }
                    state = VideoConfigurationCommitState.COMPLETED
                    true
                }
            if (!claimed) return
            timeout?.cancel(false)
            completeClaimed(decision)
        }

        private fun timeout(decision: StreamVideoConfigurationDecision) {
            val claimed =
                synchronized(stateLock) {
                    if (state != VideoConfigurationCommitState.PENDING) return@synchronized false
                    state = VideoConfigurationCommitState.COMPLETED
                    true
                }
            if (claimed) {
                completeClaimed(decision)
            }
        }

        private fun completeClaimed(decision: StreamVideoConfigurationDecision) {
            if (!isCurrentProtocolSession(session, connectionGeneration)) return
            val submission =
                submitOutbound(
                    kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                    command = StreamOutboundCommand.ProtocolVideoConfigurationCompletion(this, decision),
                    timeoutMillis = PROTOCOL_ACTION_TIMEOUT_MS,
                )
            if (submission == OutboundCommandScheduler.Submission.TIMED_OUT ||
                submission == OutboundCommandScheduler.Submission.CLOSED
            ) {
                pendingVideoConfigurationCommit.compareAndSet(this, null)
                requestConnectionEnd(
                    SessionFailure.protocol(
                        SessionFailureKind.OUTBOUND_BACKPRESSURE,
                        "Decoder configuration completion queue unavailable: $submission",
                    ),
                )
            }
        }

        override fun cancel() {
            val previous =
                synchronized(stateLock) {
                    val current = state
                    state = VideoConfigurationCommitState.CANCELLED
                    current
                }
            if (previous in ACTIVE_VIDEO_CONFIGURATION_COMMIT_STATES) timeout?.cancel(false)
        }
    }

    private inner class LegacyVideoConfigurationCommit(
        private val connectionGeneration: Long,
    ) : StreamVideoConfigurationCommit {
        private val stateLock = Any()
        private var state = VideoConfigurationCommitState.PENDING

        override val canSupersedePendingConfiguration = true

        override fun isPending(): Boolean =
            synchronized(stateLock) {
                state in ACTIVE_VIDEO_CONFIGURATION_COMMIT_STATES &&
                    isConnected &&
                    connectionEpoch == connectionGeneration &&
                    SESSION_EPOCHS.accepts(connectionGeneration)
            }

        override fun tryPublish(publish: () -> Boolean): Boolean {
            val claimed =
                synchronized(stateLock) {
                    if (state != VideoConfigurationCommitState.PENDING ||
                        !isConnected ||
                        connectionEpoch != connectionGeneration ||
                        !SESSION_EPOCHS.accepts(connectionGeneration)
                    ) {
                        return@synchronized false
                    }
                    state = VideoConfigurationCommitState.RESERVED
                    true
                }
            if (!claimed) return false
            return try {
                publish()
            } catch (failure: RuntimeException) {
                // A throwing publish() must not strand the commit in RESERVED:
                // isPending() would stay true and no timeout can reclaim it.
                // Release the reservation before rethrowing.
                synchronized(stateLock) {
                    if (state == VideoConfigurationCommitState.RESERVED) {
                        state = VideoConfigurationCommitState.CANCELLED
                    }
                }
                throw failure
            }
        }

        override fun complete(decision: StreamVideoConfigurationDecision) {
            val claimed =
                synchronized(stateLock) {
                    if (decision.accepted) {
                        if (state != VideoConfigurationCommitState.RESERVED) return@synchronized false
                    } else if (state !in ACTIVE_VIDEO_CONFIGURATION_COMMIT_STATES) {
                        return@synchronized false
                    }
                    state = VideoConfigurationCommitState.COMPLETED
                    true
                }
            if (!claimed || !isConnected || connectionEpoch != connectionGeneration) return
            if (decision.accepted) {
                requestKeyframe(force = true, reason = "decoder_configuration_committed")
            } else {
                failCurrentSession(decision.rejectionReason)
            }
        }

        override fun cancel() {
            synchronized(stateLock) {
                if (state in ACTIVE_VIDEO_CONFIGURATION_COMMIT_STATES) {
                    state = VideoConfigurationCommitState.CANCELLED
                }
            }
        }
    }

    private data class TerminationRequest(
        val failure: SessionFailure,
        val wasConnected: Boolean,
    )

    companion object {
        private enum class VideoConfigurationCommitState {
            PENDING,
            RESERVED,
            COMPLETED,
            CANCELLED,
        }

        private val ACTIVE_VIDEO_CONFIGURATION_COMMIT_STATES =
            setOf(VideoConfigurationCommitState.PENDING, VideoConfigurationCommitState.RESERVED)
        private const val TAG = "StreamClient"
        private const val MAX_FRAME_SIZE = 5 * 1024 * 1024 // 5MB
        private const val KEYFRAME_REQUEST_INTERVAL_NS = 500_000_000L
        private const val KEYFRAME_STALE_INTERVAL_NS = 1_500_000_000L
        private const val OUTBOUND_QUEUE_CAPACITY = 32
        private const val OUTBOUND_DRAIN_TIMEOUT_MS = 200L
        private const val CONNECT_TIMEOUT_MS = 5_000
        private const val HANDSHAKE_TIMEOUT_MS = 5_000
        private const val PROTOCOL_UPGRADE_TIMEOUT_MS = 250
        private const val PROTOCOL_ACTION_TIMEOUT_MS = 2_000L
        private const val DECODER_CONFIGURATION_NOT_PUBLISHED_REASON =
            "decoder_configuration_not_published"
        private const val DECODER_CONFIGURATION_PUBLISH_FAILED_REASON =
            "decoder_configuration_publish_failed"
        private const val VIDEO_CONFIGURATION_COMMIT_TIMEOUT_MS = 2_000L
        private const val LEGACY_CONFIG_EPOCH = 0L
        private const val UNASSIGNED_ATTEMPT_GENERATION = 0L
        private const val AUTH_RESPONSE_BYTES = 5
        private const val HOST_ACTION_INVOCATION_ID_BYTES = 16
        private const val WAKE_HOST_REQUEST_ID_BYTES = 16
        private const val MAX_PENDING_INBOUND_WAKE_HOST_REQUESTS = 16
        private const val HEARTBEAT_POLL_INTERVAL_MS = 1_000
        private const val HEARTBEAT_TIMEOUT_MS = 3_500L
        private const val MIN_DISPLAY_DIMENSION = 16
        private const val MAX_DISPLAY_DIMENSION = 8_192
        private val VALID_DISPLAY_ROTATIONS = setOf(0, 90, 180, 270)
        private const val TELEMETRY_TAG = "VibeScreenTelemetry"
        private const val MESSAGE_VIDEO_FRAME = 0
        private const val MESSAGE_TOUCH = 2
        private const val MESSAGE_PING = 4
        private const val MESSAGE_VIDEO_FRAME_WITH_METADATA = 6
        private const val MESSAGE_KEYFRAME_REQUEST = 7
        private const val MESSAGE_CLIENT_SUPPORTS_FRAME_METADATA = 8
        private const val MESSAGE_CLIENT_AVC_ONLY = 9
        private const val MESSAGE_CODEC_SELECTED = 10
        private const val MESSAGE_CLIENT_DEVICE_INFO = 11
        private const val MESSAGE_DEVICE_INFO_CAPABILITY = 12
        private const val MAX_PROTOCOL_ID_BYTES = 128
        private const val MAX_DEVICE_NAME_BYTES = 64

        // Type 3 (gap between touch=2 and ping=4). Not 12 — that is device-info capability.
        private const val MESSAGE_SERVER_SHUTDOWN = 3
        private const val FRAME_FLAG_KEYFRAME = 1
        private const val KEYFRAME_REQUEST_FLAG_FORCE = 1
        private val SESSION_EPOCHS = SessionEpochGate()
        private val VIDEO_CONFIGURATION_TIMEOUT_EXECUTOR =
            Executors.newSingleThreadScheduledExecutor { runnable ->
                Thread(runnable, "VibeVideoConfigurationTimeout").apply { isDaemon = true }
            }
        private val SESSION_TERMINATION_EXECUTOR =
            Executors.newSingleThreadExecutor { runnable ->
                Thread(runnable, "VibeSessionTerminator").apply { isDaemon = true }
            }
        private val WAKE_HOST_EXECUTOR =
            Executors.newSingleThreadExecutor { runnable ->
                Thread(runnable, "VibeWakeHostSender").apply { isDaemon = true }
            }

        private enum class WireMode { LEGACY, V1 }

        /**
         * Codec-aware sync-frame (keyframe) detection on the legacy
         * MESSAGE_VIDEO_FRAME path. HEVC: IRAP NAL types 16..21 from
         * (header and 0x7E) shr 1. H.264: IDR slice, (header and 0x1F) == 5.
         * Internal (not private) so unit tests can exercise both branches.
         */
        internal fun isSyncFrame(
            data: ByteArray,
            size: Int,
            isHevc: Boolean,
        ): Boolean {
            var i = 0
            while (i + 5 < size) {
                var start = -1
                var startCodeLength = 0

                while (i + 3 < size) {
                    if (data[i] == 0.toByte() && data[i + 1] == 0.toByte()) {
                        if (data[i + 2] == 1.toByte()) {
                            start = i
                            startCodeLength = 3
                            break
                        }
                        if (i + 3 < size && data[i + 2] == 0.toByte() && data[i + 3] == 1.toByte()) {
                            start = i
                            startCodeLength = 4
                            break
                        }
                    }
                    i++
                }

                if (start < 0) return false

                val nalStart = start + startCodeLength
                if (nalStart + 1 >= size) return false

                val header = data[nalStart].toInt()
                val isSync =
                    if (isHevc) {
                        ((header and 0x7E) shr 1) in 16..21
                    } else {
                        (header and 0x1F) == 5
                    }
                if (isSync) {
                    return true
                }

                i = nalStart + 2
            }
            return false
        }
    }
}
