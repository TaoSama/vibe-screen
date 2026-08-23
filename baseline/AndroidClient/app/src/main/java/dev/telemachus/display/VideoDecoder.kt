package dev.telemachus.display

import android.annotation.SuppressLint
import android.media.MediaCodec
import android.media.MediaFormat
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.Process
import android.util.Log
import android.view.Display
import android.view.Surface
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue

private fun diagLog(msg: String) = DiagLog.log("VD", msg)

internal object VideoDecoderSdrColorSettings {
    @SuppressLint("InlinedApi")
    val integerProperties: List<Pair<String, Int>> =
        listOf(
            MediaFormat.KEY_COLOR_STANDARD to MediaFormat.COLOR_STANDARD_BT709,
            MediaFormat.KEY_COLOR_TRANSFER to MediaFormat.COLOR_TRANSFER_SDR_VIDEO,
            MediaFormat.KEY_COLOR_RANGE to MediaFormat.COLOR_RANGE_LIMITED,
        )

    fun applyTo(format: MediaFormat): MediaFormat {
        integerProperties.forEach { (key, value) ->
            format.setInteger(key, value)
        }
        return format
    }
}

class VideoDecoder(
    private val surface: Surface,
    private val display: Display? = null,
    initialWidth: Int = 1920,
    initialHeight: Int = 1200,
    private val mime: String = MediaFormat.MIMETYPE_VIDEO_HEVC,
    initialScaleMode: VideoScaleMode = VideoScaleMode.FIT,
    private val onFrameDecoded: (VideoDecoder, ByteArray) -> Unit = { _, _ -> },
    private val onFrameRendered: (VideoDecoder, Long) -> Unit = { _, _ -> },
    private val onFrameStats: (VideoDecoder, fps: Double, variance: Double) -> Unit = { _, _, _ -> },
    onKeyframeRequired: (VideoDecoder, force: Boolean, reason: String) -> Unit,
    onCodecFailure: (VideoDecoder, failure: DecoderFailure) -> Unit,
) {
    private val keyframeCallback = onKeyframeRequired
    private val codecFailureCallback = onCodecFailure
    private var decoder: MediaCodec? = null
    private var decoderThread: HandlerThread? = null
    private var decoderHandler: Handler? = null

    private var frameCount = 0L
    private var droppedFrames = 0L
    private var staleOutputDrops = 0L
    private var lastStatsTime = System.currentTimeMillis()
    private var inputFrameCount = 0L
    private var outputFrameCount = 0L
    private var firstOutputFrameSessionEpoch = 0L

    // Decoder pipeline latency (input enqueue -> output buffer available),
    // accumulated over ~60 frames then logged. High values indicate the codec
    // is queuing frames internally (compose/present can't keep up downstream),
    // which surfaces to the user as input lag on the captured display.
    private var latencySumNs: Long = 0
    private var latencySamples: Int = 0
    private var latencyMaxNs: Long = 0

    private val frameTimes = ArrayDeque<Long>(120)

    private val displayRefreshRate = display?.refreshRate ?: 60f
    private val renderIntervalNs =
        (1_000_000_000.0 / displayRefreshRate.coerceAtLeast(30f)).toLong()
    private val renderLeadNs = renderIntervalNs
    private var nextRenderTimeNs = 0L

    private var currentWidth = initialWidth
    private var currentHeight = initialHeight
    private var currentScaleMode = initialScaleMode

    @Volatile private var isRunning = false

    @Volatile private var needsKeyframe = true

    private var lastKeyframeRequestNs = 0L

    private var startupGate = createStartupGate()

    // Available input buffer indices — fed by onInputBufferAvailable callback
    private val availableInputBuffers = ConcurrentLinkedQueue<Int>()
    private val queuedFrameEpochs = ConcurrentHashMap<Long, Long>()
    private val pendingFrames =
        LatestFrameQueue<PendingFrame>(PENDING_FRAME_CAPACITY) { frame -> frame.isKeyframe }
    private val inputQueueLock = Any()
    @Volatile private var currentSessionEpoch = 0L

    init {
        setupDecoder()
    }

    fun updateResolution(
        width: Int,
        height: Int,
    ) {
        if (width != currentWidth || height != currentHeight) {
            currentWidth = width
            currentHeight = height
            release()
            startupGate = createStartupGate()
            setupDecoder()
            when (val result = startupGate.commit { true }) {
                DecoderStartupCommitResult.Committed -> Unit
                DecoderStartupCommitResult.NotCommitted -> error("Decoder recreation was discarded")
                is DecoderStartupCommitResult.Failed -> error(result.reason)
            }
            requestKeyframe("resolution changed", force = true)
        }
    }

    fun updateScaleMode(scaleMode: VideoScaleMode) {
        currentScaleMode = scaleMode
        try {
            decoder?.setVideoScalingMode(scaleMode.mediaCodecValue())
        } catch (error: IllegalStateException) {
            Log.w(TAG, "Deferring video scaling mode until decoder recreation", error)
        }
    }

    @SuppressLint("InlinedApi") // Inlined string keys safely fall through on unsupported codecs.
    private fun setupDecoder() {
        require(currentWidth in MIN_VIDEO_DIMENSION..MAX_VIDEO_DIMENSION) {
            "Unsupported video width: $currentWidth"
        }
        require(currentHeight in MIN_VIDEO_DIMENSION..MAX_VIDEO_DIMENSION) {
            "Unsupported video height: $currentHeight"
        }
        // Find a decoder that supports our resolution (prefer HW, fallback to SW)
        val decoderChoice =
            when (val selection = findBestDecoder(currentWidth, currentHeight)) {
                is DecoderSelectionResult.Selected -> selection
                DecoderSelectionResult.UnsupportedTarget -> {
                    diagLog("No usable $mime decoder supports ${currentWidth}x$currentHeight")
                    val failure =
                        DecoderFailure(
                            DecoderFailureKind.STRUCTURAL_TARGET_UNSUPPORTED,
                            if (mime == MediaFormat.MIMETYPE_VIDEO_HEVC) {
                                STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON
                            } else {
                                "decoder_target_unsupported"
                            },
                        )
                    if (mime == MediaFormat.MIMETYPE_VIDEO_HEVC) {
                        throw DecoderInitializationException(failure)
                    }
                    throw UnsupportedOperationException(failure.reason)
                }
                DecoderSelectionResult.ProbeFailed ->
                    throw IllegalStateException("Could not probe $mime decoders")
            }
        diagLog("setupDecoder: ${currentWidth}x$currentHeight, decoder=${decoderChoice.name}")

        val codec = MediaCodec.createByCodecName(decoderChoice.name)
        decoderThread = HandlerThread("DecoderThread", Process.THREAD_PRIORITY_DISPLAY).also { it.start() }
        decoderHandler = Handler(decoderThread!!.looper)

        val callback =
            object : MediaCodec.Callback() {
                override fun onInputBufferAvailable(
                    codec: MediaCodec,
                    index: Int,
                ) {
                    handleInputBufferAvailable(codec, index)
                }

                override fun onOutputBufferAvailable(
                    codec: MediaCodec,
                    index: Int,
                    info: MediaCodec.BufferInfo,
                ) {
                    handleOutputBuffer(codec, index, info)
                }

                override fun onError(
                    codec: MediaCodec,
                    e: MediaCodec.CodecException,
                ) {
                    diagLog("Codec error: ${e.diagnosticInfo}")
                    Log.e(TAG, "Codec error: ${e.diagnosticInfo}", e)
                    emitTelemetry(
                        "codec_runtime_failure",
                        mapOf("mime" to mime, "diagnostic_info" to e.diagnosticInfo),
                    )
                    needsKeyframe = true
                    startupGate.reportFatal(
                        failure =
                            DecoderFailure(
                                DecoderFailureKind.SESSION_RUNTIME_FAILURE,
                                "codec_runtime_failure",
                            ),
                        keyframeReason = "codec error",
                    )
                }

                override fun onOutputFormatChanged(
                    codec: MediaCodec,
                    format: MediaFormat,
                ) {
                    diagLog("Output format changed: $format")
                }
            }
        codec.setCallback(callback, decoderHandler)

        val format =
            VideoDecoderSdrColorSettings.applyTo(
                MediaFormat.createVideoFormat(
                    mime,
                    currentWidth,
                    currentHeight,
                ),
            )

        var configured = false

        // Attempt 1: Full low-latency config
        try {
            format.setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
            format.setInteger(MediaFormat.KEY_PRIORITY, 0)
            if (decoderChoice.supportsTargetRate) {
                format.setInteger(MediaFormat.KEY_OPERATING_RATE, displayRefreshRate.toInt())
            }
            format.setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0)
            codec.configure(format, surface, null, 0)
            configured = true
            diagLog("Configured with full low-latency")
        } catch (e: Exception) {
            diagLog("Full low-latency config failed: ${e.message}")
            codec.reset()
            codec.setCallback(callback, decoderHandler)
        }

        // Attempt 2: Without KEY_LOW_LATENCY
        if (!configured) {
            try {
                val basicFormat =
                    VideoDecoderSdrColorSettings.applyTo(
                        MediaFormat.createVideoFormat(
                            mime,
                            currentWidth,
                            currentHeight,
                        ),
                    )
                basicFormat.setInteger(MediaFormat.KEY_PRIORITY, 0)
                basicFormat.setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0)
                codec.configure(basicFormat, surface, null, 0)
                configured = true
                diagLog("Configured with basic format")
            } catch (e: Exception) {
                diagLog("Basic config failed: ${e.message}")
                codec.reset()
                codec.setCallback(callback, decoderHandler)
            }
        }

        // Attempt 3: Minimal config (just resolution)
        if (!configured) {
            try {
                val minimalFormat =
                    VideoDecoderSdrColorSettings.applyTo(
                        MediaFormat.createVideoFormat(
                            mime,
                            currentWidth,
                            currentHeight,
                        ),
                    )
                codec.configure(minimalFormat, surface, null, 0)
                diagLog("Configured with minimal format")
            } catch (e: Exception) {
                diagLog("All configure attempts failed: ${e.message}")
                Log.e(TAG, "All configure attempts failed", e)
                emitTelemetry(
                    "codec_configuration_failure",
                    mapOf("mime" to mime, "error" to (e.message ?: e.javaClass.simpleName)),
                )
                codec.release()
                decoderThread?.quitSafely()
                decoderThread = null
                decoderHandler = null
                throw e
            }
        }

        codec.setVideoScalingMode(currentScaleMode.mediaCodecValue())
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                surface.setFrameRate(
                    displayRefreshRate,
                    Surface.FRAME_RATE_COMPATIBILITY_FIXED_SOURCE,
                )
                diagLog("Surface frame rate requested: ${displayRefreshRate}Hz fixed-source")
            } catch (e: Exception) {
                diagLog("Surface frame-rate request failed: ${e.message}")
            }
        }
        needsKeyframe = true
        nextRenderTimeNs = 0L
        isRunning = true
        try {
            startupGate.start { codec.start() }
        } catch (failure: Exception) {
            startupGate.reportFatal(
                failure = DecoderFailure(DecoderFailureKind.SESSION_RUNTIME_FAILURE, "codec_start_failure"),
                keyframeReason = "codec start failed",
            )
        }
        decoder = codec
        diagLog(
            "Decoder started: ${currentWidth}x$currentHeight @ ${displayRefreshRate}Hz, " +
                "surface=$surface, valid=${surface.isValid}",
        )
    }

    internal fun commitStartup(publish: () -> Boolean): DecoderStartupCommitResult = startupGate.commit(publish)

    private fun createStartupGate(): DecoderStartupGate =
        DecoderStartupGate(
            onKeyframeRequired = { force, reason -> keyframeCallback(this, force, reason) },
            onCodecFailure = { failure -> codecFailureCallback(this, failure) },
        )

    private fun VideoScaleMode.mediaCodecValue(): Int =
        when (this) {
            VideoScaleMode.FIT -> MediaCodec.VIDEO_SCALING_MODE_SCALE_TO_FIT
            VideoScaleMode.FILL -> MediaCodec.VIDEO_SCALING_MODE_SCALE_TO_FIT_WITH_CROPPING
        }

    private fun findBestDecoder(
        width: Int,
        height: Int,
    ): DecoderSelectionResult {
        val targetRate = displayRefreshRate.toDouble().coerceAtLeast(30.0)
        val snapshot = AndroidDecoderCatalog.probe(mime, width, height, targetRate)
            ?: return DecoderSelectionResult.ProbeFailed
        return DecoderSelector.select(mime, snapshot)
    }

    fun decode(
        frameData: ByteArray,
        frameSize: Int = frameData.size,
        frameTimestamp: Long = System.nanoTime(),
        isKeyframe: Boolean = false,
        sessionEpoch: Long,
    ) {
        val abandonedFrames =
            synchronized(inputQueueLock) {
                when {
                    sessionEpoch < currentSessionEpoch -> null
                    sessionEpoch > currentSessionEpoch -> {
                        currentSessionEpoch = sessionEpoch
                        needsKeyframe = true
                        pendingFrames.drain()
                    }
                    else -> emptyList()
                }
            }
        if (abandonedFrames == null) {
            emitTelemetry(
                "frame_dropped",
                mapOf(
                    "reason" to "stale_decoder_session_epoch",
                    "frame_epoch" to sessionEpoch,
                    "current_epoch" to currentSessionEpoch,
                ),
            )
            onFrameDecoded(this, frameData)
            return
        }
        abandonedFrames.forEach { pending -> onFrameDecoded(this, pending.data) }

        if (!isRunning) {
            diagLog("decode called but isRunning=false")
            onFrameDecoded(this, frameData)
            return
        }

        inputFrameCount++
        if (inputFrameCount == 1L) {
            val header =
                frameData
                    .take(minOf(16, frameSize))
                    .joinToString(" ") { String.format(Locale.US, "%02x", it) }
            diagLog(
                "First frame: size=$frameSize, header=[$header], " +
                    "keyframe=$isKeyframe, surface=$surface, valid=${surface.isValid}",
            )
        }
        if (inputFrameCount % 60L == 0L) {
            diagLog(
                "Decode stats: input=$inputFrameCount, output=$outputFrameCount, " +
                    "dropped=$droppedFrames, availBufs=${availableInputBuffers.size}",
            )
        }

        val codec =
            decoder ?: run {
                diagLog("decoder is null in decode()")
                onFrameDecoded(this, frameData)
                return
            }

        if (needsKeyframe && !isKeyframe) {
            dropFrame(
                frameData,
                isKeyframe,
                "waiting for keyframe",
                waitForKeyframe = true,
            )
            return
        }

        // Direct feed when possible; otherwise retain exactly the newest frame.
        var offerResult: LatestFrameOfferResult<PendingFrame>? = null
        val index =
            synchronized(inputQueueLock) {
                availableInputBuffers.poll()
                    ?: run {
                        offerResult =
                            pendingFrames.offer(
                                PendingFrame(frameData, frameSize, frameTimestamp, isKeyframe, sessionEpoch),
                            )
                        null
                    }
            }
        if (index == null) {
            val result = requireNotNull(offerResult)
            result.dropped.forEach { dropped -> onFrameDecoded(this, dropped.data) }
            if (result.dropped.isNotEmpty()) {
                droppedFrames += result.dropped.size
                emitTelemetry(
                    "frame_dropped",
                    mapOf(
                        "reason" to "latest_frame_queue_backpressure",
                        "queue_capacity" to PENDING_FRAME_CAPACITY,
                        "dropped_total" to droppedFrames,
                        "keyframe_required" to result.requiresKeyframe,
                    ),
                )
            }
            if (result.requiresKeyframe) {
                needsKeyframe = true
                requestKeyframe("latest-frame queue replacement", force = true)
            }
            return
        }

        queueFrame(codec, index, frameData, frameSize, frameTimestamp, isKeyframe, sessionEpoch)
    }

    private fun handleInputBufferAvailable(
        codec: MediaCodec,
        index: Int,
    ) {
        val frame =
            synchronized(inputQueueLock) {
                pendingFrames.poll()
                    ?: run {
                        availableInputBuffers.offer(index)
                        null
                    }
            }
        if (frame == null) {
            return
        }

        val ageNs = System.nanoTime() - frame.timestampNs
        if (ageNs > MAX_RENDER_LATENCY_NS) {
            droppedFrames++
            onFrameDecoded(this, frame.data)
            availableInputBuffers.offer(index)
            emitTelemetry(
                "frame_dropped",
                mapOf(
                    "reason" to "stale_pending_frame",
                    "age_ms" to ageNs / 1_000_000.0,
                    "dropped_total" to droppedFrames,
                ),
            )
            requestKeyframe("stale pending frame", force = true)
            return
        }

        queueFrame(
            codec = codec,
            index = index,
            frameData = frame.data,
            frameSize = frame.size,
            frameTimestamp = frame.timestampNs,
            isKeyframe = frame.isKeyframe,
            sessionEpoch = frame.sessionEpoch,
        )
    }

    private fun queueFrame(
        codec: MediaCodec,
        index: Int,
        frameData: ByteArray,
        frameSize: Int,
        frameTimestamp: Long,
        isKeyframe: Boolean,
        sessionEpoch: Long,
    ) {
        val presentationTimeUs = frameTimestamp / 1000
        try {
            val inputBuffer =
                codec.getInputBuffer(index)
                    ?: throw IllegalStateException("Input buffer $index is null")
            inputBuffer.clear()
            inputBuffer.put(frameData, 0, frameSize)
            queuedFrameEpochs[presentationTimeUs] = sessionEpoch
            codec.queueInputBuffer(index, 0, frameSize, presentationTimeUs, 0)
            if (isKeyframe) {
                needsKeyframe = false
            }
        } catch (e: Exception) {
            queuedFrameEpochs.remove(presentationTimeUs)
            needsKeyframe = true
            requestKeyframe("queue input failed")
            Log.e(TAG, "decode direct feed error", e)
        } finally {
            onFrameDecoded(this, frameData)
        }
    }

    private fun dropFrame(
        frameData: ByteArray,
        isKeyframe: Boolean,
        reason: String,
        waitForKeyframe: Boolean,
        requestRefresh: Boolean = waitForKeyframe,
    ) {
        droppedFrames++
        if (droppedFrames <= 3L || droppedFrames % 60L == 0L) {
            diagLog("Dropping frame ($reason, keyframe=$isKeyframe, dropped=$droppedFrames)")
        }
        if (waitForKeyframe) {
            needsKeyframe = true
        }
        if (requestRefresh) {
            requestKeyframe(reason)
        }
        onFrameDecoded(this, frameData)
    }

    private fun requestKeyframe(
        reason: String,
        force: Boolean = false,
    ) {
        val now = System.nanoTime()
        val interval =
            if (force) FORCE_KEYFRAME_REQUEST_INTERVAL_NS else KEYFRAME_REQUEST_INTERVAL_NS
        if (now - lastKeyframeRequestNs < interval) {
            return
        }
        lastKeyframeRequestNs = now
        diagLog("Requesting keyframe: reason=$reason, force=$force")
        startupGate.requestKeyframe(force, reason)
    }

    private fun handleOutputBuffer(
        codec: MediaCodec,
        index: Int,
        info: MediaCodec.BufferInfo,
    ) {
        try {
            val outputEpoch = queuedFrameEpochs.remove(info.presentationTimeUs) ?: 0L
            if (outputEpoch != currentSessionEpoch) {
                droppedFrames++
                codec.releaseOutputBuffer(index, false)
                emitTelemetry(
                    "frame_dropped",
                    mapOf(
                        "reason" to "stale_decoder_output_epoch",
                        "frame_epoch" to outputEpoch,
                        "current_epoch" to currentSessionEpoch,
                    ),
                )
                updateStats()
                return
            }
            outputFrameCount++
            if (firstOutputFrameSessionEpoch != outputEpoch) {
                firstOutputFrameSessionEpoch = outputEpoch
                diagLog("First output frame! size=${info.size}, flags=${info.flags}, session_epoch=$outputEpoch")
                emitTelemetry(
                    "first_output_frame",
                    mapOf(
                        "session_epoch" to outputEpoch,
                        "size" to info.size,
                        "flags" to info.flags,
                    ),
                )
            }

            // Decoder latency: time from queueInputBuffer (where we encoded
            // System.nanoTime()/1000 as PTS) to now. Captures how long the
            // frame spent inside the codec's input/reorder/output queues.
            val nowNs = System.nanoTime()
            val latencyNs = nowNs - info.presentationTimeUs * 1000L
            val hasValidLatency = latencyNs in 0..MAX_REASONABLE_LATENCY_NS
            if (hasValidLatency) {
                latencySumNs += latencyNs
                latencySamples++
                if (latencyNs > latencyMaxNs) latencyMaxNs = latencyNs
            }

            if (outputFrameCount % 60L == 0L) {
                val avgMs = if (latencySamples > 0) latencySumNs / latencySamples / 1_000_000.0 else 0.0
                val maxMs = latencyMaxNs / 1_000_000.0
                val inBufs = availableInputBuffers.size
                diagLog(
                    "Output #$outputFrameCount: decoder latency avg=" +
                        "${String.format(Locale.US, "%.1f", avgMs)}ms " +
                        "max=${String.format(Locale.US, "%.1f", maxMs)}ms over $latencySamples samples, " +
                        "input bufs avail=$inBufs, dropped=$droppedFrames",
                )
                latencySumNs = 0
                latencySamples = 0
                latencyMaxNs = 0
            }

            val shouldRender =
                outputFrameCount == 1L ||
                    !hasValidLatency ||
                    latencyNs <= MAX_RENDER_LATENCY_NS

            if (!shouldRender) {
                droppedFrames++
                staleOutputDrops++
                if (staleOutputDrops <= 3L || staleOutputDrops % 60L == 0L) {
                    diagLog(
                        "Dropping stale output frame: latency=" +
                            "${String.format(Locale.US, "%.1f", latencyNs / 1_000_000.0)}ms, " +
                            "staleDrops=$staleOutputDrops",
                    )
                }
                codec.releaseOutputBuffer(index, false)
                updateStats()
                return
            }

            // Boolean `render=true` releases buffers immediately. TCP and
            // decoder callbacks arrive with a few milliseconds of jitter, so
            // two frames can reach SurfaceFlinger before one vsync and one is
            // discarded even though decode is sustaining 60 FPS. Schedule the
            // buffers on a fixed display-rate timeline instead.
            if (nextRenderTimeNs == 0L || nowNs - nextRenderTimeNs > renderIntervalNs) {
                // Keep one frame of runway so the larger once-per-second HEVC
                // keyframe does not arrive just after its compositor deadline.
                nextRenderTimeNs = nowNs + renderLeadNs
            }
            val renderTimeNs = nextRenderTimeNs
            nextRenderTimeNs += renderIntervalNs
            codec.releaseOutputBuffer(index, renderTimeNs)
            trackFrameTiming(renderTimeNs)
            updateStats()
        } catch (e: Exception) {
            Log.e(TAG, "releaseOutputBuffer failed", e)
            try {
                codec.releaseOutputBuffer(index, false)
            } catch (fallbackError: Exception) {
                Log.e(TAG, "Failed to discard output buffer after timed release error", fallbackError)
            }
        }
    }

    private fun trackFrameTiming(timestamp: Long) {
        frameTimes.addLast(timestamp)
        if (frameTimes.size > 120) frameTimes.removeFirst()

        if (frameTimes.size >= 60 && frameCount % 60L == 0L) {
            val deltas = frameTimes.zipWithNext { a, b -> (b - a) / 1_000_000.0 }
            if (deltas.isNotEmpty()) {
                val avgDelta = deltas.average()
                val variance = deltas.map { (it - avgDelta) * (it - avgDelta) }.average()
                val stdDev = kotlin.math.sqrt(variance)
                onFrameStats(this, 1000.0 / avgDelta, stdDev)
            }
        }
        onFrameRendered(this, timestamp)
    }

    private fun updateStats() {
        frameCount++
        val now = System.currentTimeMillis()
        val elapsed = now - lastStatsTime
        if (elapsed >= 1000) {
            frameCount = 0
            droppedFrames = 0
            staleOutputDrops = 0
            lastStatsTime = now
        }
    }

    fun release() {
        startupGate.discard()
        isRunning = false
        nextRenderTimeNs = 0L
        val abandonedFrames = synchronized(inputQueueLock) { pendingFrames.drain() }
        abandonedFrames.forEach { frame -> onFrameDecoded(this, frame.data) }
        availableInputBuffers.clear()
        queuedFrameEpochs.clear()
        val codec = decoder
        decoder = null
        try {
            codec?.stop()
        } catch (e: Exception) {
            Log.w(TAG, "Decoder stop failed during release", e)
        }
        try {
            codec?.release()
        } catch (e: Exception) {
            Log.e(TAG, "Decoder release failed", e)
        }
        val thread = decoderThread
        decoderThread = null
        decoderHandler = null
        if (thread != null) {
            thread.quitSafely()
            if (Thread.currentThread() !== thread) {
                try {
                    thread.join(DECODER_THREAD_JOIN_TIMEOUT_MS)
                } catch (e: InterruptedException) {
                    Thread.currentThread().interrupt()
                    Log.w(TAG, "Interrupted while waiting for decoder thread", e)
                }
            }
        }
    }

    private fun emitTelemetry(
        event: String,
        fields: Map<String, Any?> = emptyMap(),
    ) {
        Log.i(TELEMETRY_TAG, TelemetryJson.encode(event, System.currentTimeMillis(), fields))
    }

    companion object {
        private const val TAG = "VideoDecoder"
        private const val MIN_VIDEO_DIMENSION = 16
        private const val MAX_VIDEO_DIMENSION = 8_192
        private const val KEYFRAME_REQUEST_INTERVAL_NS = 1_000_000_000L
        private const val FORCE_KEYFRAME_REQUEST_INTERVAL_NS = 200_000_000L
        private const val PENDING_FRAME_CAPACITY = 1
        private const val DECODER_THREAD_JOIN_TIMEOUT_MS = 500L
        private const val TELEMETRY_TAG = "VibeScreenTelemetry"

        // Once a frame is more than three 60 Hz refresh intervals old, showing
        // it only increases perceived input lag. Drop it and catch the live edge.
        private const val MAX_RENDER_LATENCY_NS = 50_000_000L
        private const val MAX_REASONABLE_LATENCY_NS = 2_000_000_000L
    }

    private data class PendingFrame(
        val data: ByteArray,
        val size: Int,
        val timestampNs: Long,
        val isKeyframe: Boolean,
        val sessionEpoch: Long,
    )
}
