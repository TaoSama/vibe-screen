package dev.telemachus.display

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.util.Log
import android.view.WindowManager
import dev.telemachus.display.protocol.ProtocolChannel
import dev.telemachus.display.protocol.ProtocolUpgrade
import dev.telemachus.display.protocol.ProtocolV1Framing
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.TransportKind
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.DataInputStream
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong

class StreamClient(
    private val host: String,
    private val port: Int,
    private val context: Context? = null,
    private val socketFactory: () -> Socket = ::Socket,
) {
    @Volatile private var socket: Socket? = null
    private var inputStream: DataInputStream? = null
    private var outputStream: java.io.DataOutputStream? = null

    @Volatile private var isConnected = false
    @Volatile private var sessionReady = false
    @Volatile private var stopRequested = false
    @Volatile private var connectionEpoch = 0L
    @Volatile private var lastTerminationFailure: SessionFailure? = null
    @Volatile private var wireMode = WireMode.LEGACY
    private var pendingLegacyFirstByte: Int? = null
    private var protocolSession: ProtocolV1Session? = null
    private val nextInputId = AtomicLong(1L)
    private val nextPingSequence = AtomicLong(1L)
    @Volatile private var lastV1PingSequence = 0L
    @Volatile private var lastV1PingSentNs = 0L

    private val heartbeat = HeartbeatMonitor(HEARTBEAT_TIMEOUT_MS)
    private val reconnectBackoff = ReconnectBackoff()

    // Callback includes actual frame size (may differ from buffer.size due to pooling),
    // receive timestamp, and whether the frame can restart HEVC decoding.
    var onFrameReceived: ((ByteArray, Int, Long, Boolean, Long) -> Unit)? = null
    var onConnectionStatus: ((Boolean) -> Unit)? = null
    var onDisplaySize: ((Int, Int, Int) -> Unit)? = null // width, height, rotation
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
                onWriteFailure?.invoke(detail)
                requestConnectionEnd(SessionFailure.write(detail))
            },
            coalesce = { kind, pending, replacement ->
                if (kind == OutboundCommandScheduler.Kind.KEYFRAME &&
                    pending is OutboundCommand.Keyframe &&
                    replacement is OutboundCommand.Keyframe
                ) {
                    OutboundCommand.Keyframe(pending.flags or replacement.flags)
                } else {
                    replacement
                }
            },
            threadName = "VibeOutboundWriter",
        )
    private val terminationDispatcher =
        OnceAsyncDispatcher(
            executor = SESSION_TERMINATION_EXECUTOR,
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
            try {
                val candidate = socketFactory()
                socket = candidate
                if (terminationDispatcher.isClaimed()) {
                    cleanupCandidateSocket(candidate)
                    return@withContext
                }
                candidate.tcpNoDelay = true
                candidate.connect(InetSocketAddress(host, port), CONNECT_TIMEOUT_MS)
                candidate.soTimeout = HEARTBEAT_POLL_INTERVAL_MS
                inputStream = DataInputStream(java.io.BufferedInputStream(socket?.getInputStream(), 65536))
                outputStream = java.io.DataOutputStream(socket?.getOutputStream())
                streamCodecIsHevc = true
                codecNegotiated = false
                connectionEpoch = SESSION_EPOCHS.beginSession()
                negotiateProtocol(TransportKind.TRANSPORT_KIND_USB)
                isConnected = true
                if (terminationDispatcher.isClaimed()) {
                    isConnected = false
                    cleanupCandidateSocket(candidate)
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
            } catch (e: Exception) {
                Log.e(TAG, "❌ Connection error", e)
                completeConnectionEndNow(SessionFailure.transport(e.message ?: e.javaClass.simpleName))
                if (!sessionReady && !stopRequested) throw e
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
    ) = withContext(Dispatchers.IO) {
        if (terminationDispatcher.isClaimed()) return@withContext
        sessionReady = false
        val request =
            try {
                AuthHandshake.encodeRequest(token, deviceName)
            } catch (error: IllegalArgumentException) {
                throw WirelessConnectError.ProtocolError
            }
        Log.i(TAG, "connectWireless: trying $host:$port (device=$deviceName, token bytes=${token.size})")

        val s = socketFactory()
        socket = s
        if (terminationDispatcher.isClaimed()) {
            cleanupCandidateSocket(s)
            return@withContext
        }
        try {
            // Force the socket onto the active WiFi network. On some Android setups
            // the default route can silently drop LAN traffic.
            s.tcpNoDelay = true
            val wifiNetwork =
                context?.let { ctx ->
                    val cm = ctx.getSystemService(ConnectivityManager::class.java)
                    cm.activeNetwork?.takeIf { net ->
                        cm
                            .getNetworkCapabilities(net)
                            ?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
                    }
                }
            if (wifiNetwork != null) {
                Log.i(TAG, "connectWireless: binding socket to WiFi network $wifiNetwork")
                wifiNetwork.bindSocket(s)
            } else {
                Log.w(TAG, "connectWireless: no WiFi network found, using default routing")
            }
            s.connect(InetSocketAddress(host, port), CONNECT_TIMEOUT_MS)
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
                        connectionEpoch = SESSION_EPOCHS.beginSession()
                        isConnected = true
                        if (terminationDispatcher.isClaimed()) {
                            isConnected = false
                            cleanupCandidateSocket(s)
                            return@withContext
                        }
                        s.soTimeout = HEARTBEAT_POLL_INTERVAL_MS
                        inputStream = DataInputStream(java.io.BufferedInputStream(rawInput, 65536))
                        outputStream = java.io.DataOutputStream(rawOutput)
                        streamCodecIsHevc = true
                        codecNegotiated = false
                        negotiateProtocol(TransportKind.TRANSPORT_KIND_LAN)
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
                    mapOf("host" to host, "port" to port, "session_epoch" to connectionEpoch),
                )
                diagLog("Wireless connected to $host:$port")
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
        outputStream?.let { out ->
            out.writeByte(MESSAGE_CLIENT_SUPPORTS_FRAME_METADATA)
            out.flush()
            diagLog("Advertised frame metadata support")
        }
    }

    private fun negotiateProtocol(transport: TransportKind) {
        val socket = checkNotNull(socket)
        val input = checkNotNull(inputStream)
        val output = checkNotNull(outputStream)
        ProtocolUpgrade.writeOffer(output)
        socket.soTimeout = PROTOCOL_UPGRADE_TIMEOUT_MS
        val firstByte =
            try {
                input.read()
            } catch (_: SocketTimeoutException) {
                null
            }
        when (val result = ProtocolUpgrade.classify(firstByte, input)) {
            ProtocolUpgrade.Result.V1 -> {
                wireMode = WireMode.V1
                pendingLegacyFirstByte = null
                protocolSession =
                    ProtocolV1Session(
                        deviceId = "android-${Build.MODEL}".take(MAX_PROTOCOL_ID_BYTES),
                        deviceName = (Build.MODEL ?: "Android").take(MAX_DEVICE_NAME_BYTES),
                        transport = transport,
                        codecs =
                            if (CodecCapabilities.shouldAdvertiseAvcOnly) {
                                listOf(Codec.CODEC_H264)
                            } else {
                                listOf(Codec.CODEC_HEVC, Codec.CODEC_H264)
                            },
                    )
                submitOutbound(
                    kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                    command = OutboundCommand.ProtocolControl(checkNotNull(protocolSession).clientHello()),
                )
                diagLog("Protocol v1 upgrade accepted")
            }
            is ProtocolUpgrade.Result.Legacy -> {
                wireMode = WireMode.LEGACY
                protocolSession = null
                pendingLegacyFirstByte = result.firstByte
                advertiseAvcOnlyIfNeeded()
                advertiseFrameMetadataSupport()
                offerDeviceInfoCapability()
                diagLog("Protocol upgrade unavailable; using legacy wire mode")
            }
        }
        socket.soTimeout = HEARTBEAT_POLL_INTERVAL_MS
    }

    /**
     * Payload-free offer (type 12). Older Mac hosts consume one unknown byte and
     * never reply, so we only send the 66-byte type 11 payload after the host
     * accepts with the same type.
     */
    private fun offerDeviceInfoCapability() {
        outputStream?.let { out ->
            out.writeByte(MESSAGE_DEVICE_INFO_CAPABILITY)
            out.flush()
            diagLog("Offered device-info capability")
        }
    }

    /**
     * Reports Build.MODEL and the panel's maximum supported refresh rate so the
     * Mac settings UI can stop hardcoding a developer tablet. Uses wire type 11
     * (66 bytes) only after [MESSAGE_DEVICE_INFO_CAPABILITY] acceptance.
     */
    private fun sendDeviceInfo() {
        val out = outputStream ?: return
        try {
            val model = Build.MODEL
            val modelBytes = model.toByteArray(Charsets.UTF_8)
            val modelField = ByteArray(64)
            modelBytes.copyInto(modelField, 0, 0, minOf(modelBytes.size, 63))

            val refreshRate = resolveMaxRefreshRateHz()
            val buffer = ByteArray(1 + 64 + 1)
            buffer[0] = MESSAGE_CLIENT_DEVICE_INFO.toByte()
            System.arraycopy(modelField, 0, buffer, 1, 64)
            buffer[65] = (refreshRate.coerceIn(0, 255) and 0xFF).toByte()

            out.write(buffer)
            out.flush()
            diagLog("Sent device info: model=$model, maxRefreshRate=$refreshRate")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to send device info", e)
        }
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
        outputStream?.let { out ->
            out.writeByte(MESSAGE_CLIENT_AVC_ONLY)
            out.flush()
            diagLog("Advertised AVC-only (HEVC unavailable or failed at runtime)")
            emitTelemetry(
                "codec_fallback_requested",
                mapOf("from" to "HEVC", "to" to "H264", "session_epoch" to connectionEpoch),
            )
        }
    }

    private suspend fun receiveData() =
        withContext(Dispatchers.IO) {
            val input = inputStream ?: return@withContext
            var terminalFailure = SessionFailure.transport("receive loop ended")

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
                            onDisplaySize?.invoke(width, height, rotation)
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
                            diagLog("Server shut down gracefully — closing")
                            stopRequested = true
                            terminalFailure = SessionFailure.serverShutdown()
                            onServerShutdown?.invoke()
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
                Log.e(TAG, "Session protocol failure: ${error.failure.detail}", error)
            } catch (e: IOException) {
                terminalFailure = SessionFailure.transport(e.message ?: e.javaClass.simpleName)
                if (isConnected) {
                    Log.e(TAG, "❌ Read error", e)
                }
            } finally {
                completeConnectionEndNow(terminalFailure)
            }
        }

    private fun receiveV1Frame(input: DataInputStream) {
        val firstChannel =
            try {
                input.read()
            } catch (_: SocketTimeoutException) {
                if (heartbeat.isExpired(System.nanoTime())) throw IOException("heartbeat timeout")
                return
            }
        val frame = ProtocolV1Framing.read(input, firstChannel)
        when (frame.channel) {
            ProtocolChannel.CONTROL -> {
                val envelope =
                    try {
                        Envelope.parseFrom(frame.payload)
                    } catch (failure: Exception) {
                        throw IOException("Malformed Protocol v1 Envelope", failure)
                    }
                val session = checkNotNull(protocolSession)
                val actions =
                    try {
                        session.receive(envelope)
                    } catch (failure: IOException) {
                        if (envelope.payloadCase != Envelope.PayloadCase.PROTOCOL_ERROR) {
                            try {
                                submitOutbound(
                                    kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                                    command = OutboundCommand.ProtocolControl(
                                        session.protocolError(
                                        failure.message ?: "invalid protocol state",
                                        correlationId = envelope.messageId,
                                    ),
                                    ),
                                )
                            } catch (writeFailure: Exception) {
                                failure.addSuppressed(writeFailure)
                            }
                        }
                        throw failure
                    }
                heartbeat.recordInbound(System.nanoTime())
                actions.forEach { action ->
                    when (action) {
                        is ProtocolV1Session.Action.Send ->
                            submitOutbound(
                                kind = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                                command = OutboundCommand.ProtocolControl(action.envelope),
                            )
                        is ProtocolV1Session.Action.VideoConfigured -> {
                            streamCodecIsHevc = action.codec == Codec.CODEC_HEVC
                            codecNegotiated = true
                            if (!sessionReady) {
                                sessionReady = true
                                reconnectBackoff.reset()
                                onConnectionStatus?.invoke(true)
                            }
                            onCodecSelected?.invoke(streamCodecIsHevc)
                            onDisplaySize?.invoke(action.width, action.height, 0)
                        }
                        is ProtocolV1Session.Action.PongReceived -> {
                            if (action.sequence == lastV1PingSequence && lastV1PingSentNs > 0L) {
                                onLatencyMeasured?.invoke((System.nanoTime() - lastV1PingSentNs) / 1_000_000.0)
                            }
                        }
                        is ProtocolV1Session.Action.Disconnected -> {
                            stopRequested = !action.mayResume
                            throw IOException("Host ended Protocol v1 session")
                        }
                    }
                }
            }
            ProtocolChannel.VIDEO -> {
                val payload = ProtocolV1Framing.decodeVideo(frame.payload)
                val session = checkNotNull(protocolSession)
                session.validateMedia(payload.header)
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
                    )
                }
                updateStats(payload.annexB.size)
            }
        }
    }

    fun sendTouch(
        x: Float,
        y: Float,
        action: Int,
        pointerCount: Int = 1,
        x2: Float = 0f,
        y2: Float = 0f,
    ) {
        if (!isConnected) return
        val kind =
            if (action == TOUCH_ACTION_MOVE) {
                OutboundCommandScheduler.Kind.MOVE
            } else {
                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH
            }

        if (wireMode == WireMode.V1) {
            val phase =
                when (action) {
                    0 -> InputPhase.INPUT_PHASE_BEGAN
                    1 -> InputPhase.INPUT_PHASE_CHANGED
                    2 -> InputPhase.INPUT_PHASE_ENDED
                    else -> InputPhase.INPUT_PHASE_CANCELLED
                }
            val session = protocolSession ?: return
            if (!session.isStreaming) return
            val points =
                if (pointerCount.coerceIn(1, 2) == 2) {
                    listOf(x to y, x2 to y2)
                } else {
                    listOf(x to y)
                }
            points.forEachIndexed { pointerId, point ->
                val envelope =
                    session.touch(
                        inputId = nextInputId.getAndIncrement(),
                        pointerId = pointerId,
                        phase = phase,
                        x = point.first.toDouble(),
                        y = point.second.toDouble(),
                    )
                submitOutbound(
                    kind = kind,
                    command = OutboundCommand.ProtocolControl(envelope),
                )
            }
            return
        }

        val command = OutboundCommand.Touch(x, y, action, pointerCount.coerceIn(1, 2), x2, y2)
        submitOutbound(
            kind = kind,
            command = command,
            timeoutMillis = 0,
        )
    }

    // Callback for latency measurement (round-trip ping/pong)
    var onLatencyMeasured: ((Double) -> Unit)? = null

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
                command = OutboundCommand.ProtocolControl(session.requestKeyframe(reason)),
            )
            return
        }

        val flags = if (force) KEYFRAME_REQUEST_FLAG_FORCE else 0
        diagLog("Requesting keyframe: reason=$reason, force=$force")
        submitOutbound(
            kind = OutboundCommandScheduler.Kind.KEYFRAME,
            command = OutboundCommand.Keyframe(flags),
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
                command = OutboundCommand.ProtocolControl(session.ping(sequence)),
            )
            return
        }
        submitOutbound(
            kind = OutboundCommandScheduler.Kind.PING,
            command = OutboundCommand.Ping(System.nanoTime()),
        )
    }

    private fun submitOutbound(
        kind: OutboundCommandScheduler.Kind,
        command: OutboundCommand,
        timeoutMillis: Long = 0,
    ) {
        val submission =
            try {
                outboundScheduler.submit(kind, command, timeoutMillis)
            } catch (error: InterruptedException) {
                Thread.currentThread().interrupt()
                requestConnectionEnd(SessionFailure.write("outbound submission interrupted"))
                return
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
    }

    private fun writeOutboundCommand(command: OutboundCommand) {
        val out = outputStream ?: throw IOException("session output is closed")
        when (command) {
            is OutboundCommand.Touch -> {
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

            is OutboundCommand.Keyframe ->
                out.write(byteArrayOf(MESSAGE_KEYFRAME_REQUEST.toByte(), command.flags.toByte()))

            is OutboundCommand.Ping -> {
                val buffer = ByteBuffer.allocate(9).order(ByteOrder.LITTLE_ENDIAN)
                buffer.put(MESSAGE_PING.toByte())
                buffer.putLong(command.sentAtNs)
                out.write(buffer.array())
            }

            is OutboundCommand.ProtocolControl ->
                ProtocolV1Framing.write(out, ProtocolChannel.CONTROL, command.envelope.toByteArray())
        }
        if (command !is OutboundCommand.ProtocolControl) out.flush()
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
            callback.invoke(frameData, frameSize, receiveTimestamp, isKeyframe, epoch)
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
        try {
            try {
                if (!outboundScheduler.shutdownGracefully(OUTBOUND_DRAIN_TIMEOUT_MS)) {
                    outboundScheduler.shutdownNow()
                }
            } catch (error: InterruptedException) {
                Thread.currentThread().interrupt()
                outboundScheduler.shutdownNow()
            }
            socket?.close()
            outputStream?.close()
            inputStream?.close()
        } catch (e: Exception) {
            Log.e(TAG, "Error during cleanup", e)
        }
        outputStream = null
        inputStream = null
        socket = null
        protocolSession = null
        pendingLegacyFirstByte = null
    }

    private fun cleanupCandidateSocket(candidate: Socket? = socket) {
        try {
            candidate?.close()
        } catch (error: IOException) {
            Log.d(TAG, "Candidate socket was already closed", error)
        }
        if (socket === candidate) {
            socket = null
        }
        outboundScheduler.shutdownNow()
    }

    private fun diagLog(msg: String) = DiagLog.log("SC", msg)

    private fun emitTelemetry(
        event: String,
        fields: Map<String, Any?> = emptyMap(),
    ) {
        Log.i(TELEMETRY_TAG, TelemetryJson.encode(event, System.currentTimeMillis(), fields))
    }

    private sealed interface OutboundCommand {
        data class Touch(
            val x: Float,
            val y: Float,
            val action: Int,
            val pointerCount: Int,
            val x2: Float,
            val y2: Float,
        ) : OutboundCommand

        data class Keyframe(
            val flags: Int,
        ) : OutboundCommand

        data class Ping(
            val sentAtNs: Long,
        ) : OutboundCommand

        data class ProtocolControl(
            val envelope: Envelope,
        ) : OutboundCommand
    }

    private data class TerminationRequest(
        val failure: SessionFailure,
        val wasConnected: Boolean,
    )

    companion object {
        private const val TAG = "StreamClient"
        private const val MAX_FRAME_SIZE = 5 * 1024 * 1024 // 5MB
        private const val KEYFRAME_REQUEST_INTERVAL_NS = 500_000_000L
        private const val KEYFRAME_STALE_INTERVAL_NS = 1_500_000_000L
        private const val OUTBOUND_QUEUE_CAPACITY = 32
        private const val OUTBOUND_DRAIN_TIMEOUT_MS = 200L
        private const val CONNECT_TIMEOUT_MS = 5_000
        private const val HANDSHAKE_TIMEOUT_MS = 5_000
        private const val PROTOCOL_UPGRADE_TIMEOUT_MS = 250
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
        private const val TOUCH_ACTION_MOVE = 1
        private val SESSION_EPOCHS = SessionEpochGate()
        private val SESSION_TERMINATION_EXECUTOR =
            Executors.newSingleThreadExecutor { runnable ->
                Thread(runnable, "VibeSessionTerminator").apply { isDaemon = true }
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
