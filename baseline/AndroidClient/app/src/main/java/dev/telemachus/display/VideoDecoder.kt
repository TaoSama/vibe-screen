package dev.telemachus.display

import android.annotation.SuppressLint
import android.media.MediaCodec
import android.media.MediaCodecList
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

class VideoDecoder(
    private val surface: Surface,
    private val display: Display? = null,
    initialWidth: Int = 1920,
    initialHeight: Int = 1200,
    private val mime: String = MediaFormat.MIMETYPE_VIDEO_HEVC,
) {
    private var decoder: MediaCodec? = null
    private var decoderThread: HandlerThread? = null
    private var decoderHandler: Handler? = null

    private var frameCount = 0L
    private var droppedFrames = 0L
    private var staleOutputDrops = 0L
    private var lastStatsTime = System.currentTimeMillis()
    private var inputFrameCount = 0L
    private var outputFrameCount = 0L

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

    @Volatile private var isRunning = false

    @Volatile private var needsKeyframe = true

    private var lastKeyframeRequestNs = 0L

    var onFrameRendered: ((Long) -> Unit)? = null
    var onFrameStats: ((fps: Double, variance: Double) -> Unit)? = null
    var onFrameDecoded: ((ByteArray) -> Unit)? = null
    var onKeyframeRequired: ((force: Boolean, reason: String) -> Unit)? = null
    var onCodecFallbackRequired: ((reason: String) -> Unit)? = null

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
            setupDecoder()
            requestKeyframe("resolution changed", force = true)
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
            findBestDecoder(currentWidth, currentHeight)
                ?: throw UnsupportedOperationException(
                    "No $mime decoder supports ${currentWidth}x$currentHeight",
                )
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
                    CodecCapabilities.reportRuntimeDecoderFailure(mime)
                    emitTelemetry(
                        "codec_runtime_failure",
                        mapOf("mime" to mime, "diagnostic_info" to e.diagnosticInfo),
                    )
                    needsKeyframe = true
                    requestKeyframe("codec error", force = true)
                    onCodecFallbackRequired?.invoke("codec_runtime_failure")
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
            MediaFormat.createVideoFormat(
                mime,
                currentWidth,
                currentHeight,
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
                    MediaFormat.createVideoFormat(
                        mime,
                        currentWidth,
                        currentHeight,
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
                    MediaFormat.createVideoFormat(
                        mime,
                        currentWidth,
                        currentHeight,
                    )
                codec.configure(minimalFormat, surface, null, 0)
                diagLog("Configured with minimal format")
            } catch (e: Exception) {
                diagLog("All configure attempts failed: ${e.message}")
                Log.e(TAG, "All configure attempts failed", e)
                CodecCapabilities.reportRuntimeDecoderFailure(mime)
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

        codec.setVideoScalingMode(MediaCodec.VIDEO_SCALING_MODE_SCALE_TO_FIT)
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
        codec.start()
        decoder = codec
        diagLog(
            "Decoder started: ${currentWidth}x$currentHeight @ ${displayRefreshRate}Hz, " +
                "surface=$surface, valid=${surface.isValid}",
        )
    }

    /**
     * Find the best decoder for [mime] at the given resolution.
     * Prefers hardware decoders, falls back to software if HW can't handle the resolution.
     * Returns codec name to use with MediaCodec.createByCodecName(), or null for default.
     */
    private fun findBestDecoder(
        width: Int,
        height: Int,
    ): DecoderChoice? {
        try {
            val codecList = MediaCodecList(MediaCodecList.ALL_CODECS)
            val targetRate = displayRefreshRate.toDouble().coerceAtLeast(30.0)
            var hwRateDecoder: String? = null
            var hwSizeDecoder: String? = null
            var swRateDecoder: String? = null
            var swSizeDecoder: String? = null

            for (info in codecList.codecInfos) {
                if (info.isEncoder) continue
                val caps =
                    try {
                        info.getCapabilitiesForType(mime)
                    } catch (_: Exception) {
                        continue
                    }

                val videoCaps = caps.videoCapabilities ?: continue
                val isHardware =
                    !info.name.startsWith("c2.android.") &&
                        !info.name.startsWith("OMX.google.")
                val supported = videoCaps.isSizeSupported(width, height)
                val rateSupported =
                    supported &&
                        try {
                            videoCaps.areSizeAndRateSupported(width, height, targetRate)
                        } catch (_: Exception) {
                            false
                        }

                diagLog(
                    "$mime decoder '${info.name}': " +
                        "width=${videoCaps.supportedWidths}, " +
                        "height=${videoCaps.supportedHeights}, " +
                        "hw=$isHardware, supports ${width}x$height=$supported, " +
                        "supports @${String.format(Locale.US, "%.0f", targetRate)}fps=$rateSupported",
                )

                if (supported) {
                    if (isHardware && rateSupported && hwRateDecoder == null) {
                        hwRateDecoder = info.name
                    } else if (isHardware && hwSizeDecoder == null) {
                        hwSizeDecoder = info.name
                    } else if (!isHardware && rateSupported && swRateDecoder == null) {
                        swRateDecoder = info.name
                    } else if (!isHardware && swSizeDecoder == null) {
                        swSizeDecoder = info.name
                    }
                }
            }

            // Prefer hardware that advertises the target refresh rate, then any
            // hardware decoder for the size, then software as a last resort.
            val chosen = hwRateDecoder ?: hwSizeDecoder ?: swRateDecoder ?: swSizeDecoder
            if (chosen != null) {
                val supportsTargetRate = chosen == hwRateDecoder || chosen == swRateDecoder
                diagLog(
                    "Selected decoder: $chosen " +
                        "(rateSupported=$supportsTargetRate)",
                )
                return DecoderChoice(chosen, supportsTargetRate)
            } else {
                diagLog("No decoder supports ${width}x$height")
            }
        } catch (e: Exception) {
            diagLog("Decoder search failed: ${e.message}")
        }
        return null
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
            onFrameDecoded?.invoke(frameData)
            return
        }
        abandonedFrames.forEach { pending -> onFrameDecoded?.invoke(pending.data) }

        if (!isRunning) {
            diagLog("decode called but isRunning=false")
            onFrameDecoded?.invoke(frameData)
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
                onFrameDecoded?.invoke(frameData)
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
            result.dropped.forEach { dropped -> onFrameDecoded?.invoke(dropped.data) }
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
            onFrameDecoded?.invoke(frame.data)
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
            onFrameDecoded?.invoke(frameData)
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
        onFrameDecoded?.invoke(frameData)
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
        onKeyframeRequired?.invoke(force, reason)
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
            if (outputFrameCount == 1L) {
                diagLog("First output frame! size=${info.size}, flags=${info.flags}")
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
            } catch (_: Exception) {
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
                onFrameStats?.invoke(1000.0 / avgDelta, stdDev)
            }
        }
        onFrameRendered?.invoke(timestamp)
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
        isRunning = false
        nextRenderTimeNs = 0L
        val abandonedFrames = synchronized(inputQueueLock) { pendingFrames.drain() }
        abandonedFrames.forEach { frame -> onFrameDecoded?.invoke(frame.data) }
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

    private data class DecoderChoice(
        val name: String,
        val supportsTargetRate: Boolean,
    )

    private data class PendingFrame(
        val data: ByteArray,
        val size: Int,
        val timestampNs: Long,
        val isKeyframe: Boolean,
        val sessionEpoch: Long,
    )
}
