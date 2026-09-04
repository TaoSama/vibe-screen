package dev.telemachus.display

import dev.telemachus.display.protocol.ProtocolV1Framing
import dev.telemachus.display.protocol.ProtocolV1Failure
import dev.telemachus.display.protocol.ProtocolV1Session
import java.io.DataInputStream

internal data class StreamMediaFrame(
    val buffer: ByteArray,
    val size: Int,
    val receiveTimestampNs: Long,
    val keyframe: Boolean,
    val connectionEpoch: Long,
    val configEpoch: Long,
)

internal class StreamMediaFrameRouter(
    private val frameSink: (StreamMediaFrame) -> Boolean,
    private val requestKeyframe: (String) -> Unit,
    private val onStats: (Double, Double) -> Unit,
    private val emitTelemetry: (String, Map<String, Any?>) -> Unit,
    private val diagLog: (String) -> Unit,
    private val hasFrameSink: () -> Boolean = { true },
    private val decoderTelemetry: () -> DecoderTelemetrySnapshot = { DecoderTelemetrySnapshot.empty },
    private val nowNs: () -> Long = System::nanoTime,
    private val nowMs: () -> Long = System::currentTimeMillis,
) {
    private var bytesReceived = 0L
    private var framesReceived = 0L
    private var diagFrameCount = 0L
    private var firstFrameTelemetryEpoch = 0L
    private var lastStatsTime = nowMs()
    private var lastKeyframeReceivedNs = 0L
    private val bufferPool = ArrayDeque<ByteArray>(MAX_POOLED_BUFFERS)
    private val poolLock = Any()

    fun releaseBuffer(buffer: ByteArray) {
        synchronized(poolLock) {
            if (bufferPool.size < MAX_POOLED_BUFFERS) {
                bufferPool.addLast(buffer)
            }
        }
    }

    fun resetStream() {
        bytesReceived = 0L
        framesReceived = 0L
        diagFrameCount = 0L
        firstFrameTelemetryEpoch = 0L
        lastStatsTime = nowMs()
        lastKeyframeReceivedNs = 0L
    }

    fun receiveLegacyFrame(
        input: DataInputStream,
        hasMetadata: Boolean,
        streamCodecIsHevc: Boolean,
        connectionEpoch: Long,
        acceptsEpoch: (Long) -> Boolean,
        currentEpoch: () -> Long,
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
            input.readLong()
            isKeyframe = (flags and FRAME_FLAG_KEYFRAME) != 0
        }

        val frameData = acquireBuffer(frameSize)
        try {
            input.readFully(frameData, 0, frameSize)
        } catch (failure: Throwable) {
            releaseBuffer(frameData)
            throw failure
        }

        if (!hasMetadata && !isKeyframe) {
            isKeyframe = isSyncFrame(frameData, frameSize, streamCodecIsHevc)
        }

        if (!acceptsEpoch(connectionEpoch)) {
            releaseBuffer(frameData)
            emitTelemetry(
                "frame_dropped",
                mapOf(
                    "reason" to "stale_session_epoch",
                    "frame_epoch" to connectionEpoch,
                    "current_epoch" to currentEpoch(),
                ),
            )
            return
        }

        deliver(
            StreamMediaFrame(
                buffer = frameData,
                size = frameSize,
                receiveTimestampNs = nowNs(),
                keyframe = isKeyframe,
                connectionEpoch = connectionEpoch,
                configEpoch = LEGACY_CONFIG_EPOCH,
            ),
            emitDiagnostics = true,
            metadata = hasMetadata,
        )
    }

    fun receiveProtocolFrame(
        payload: ByteArray,
        connectionEpoch: Long,
        acceptsEpoch: (Long) -> Boolean = { true },
        currentEpoch: () -> Long = { connectionEpoch },
        validateMedia: (dev.vibescreen.protocol.v1.MediaPacketHeader) -> ProtocolV1Session.MediaDisposition,
    ) {
        val decoded =
            try {
                ProtocolV1Framing.decodeVideo(payload)
            } catch (failure: Exception) {
                throw ProtocolV1Failure(
                    reason = "invalid_media_payload",
                    retryable = false,
                    source = ProtocolV1Failure.Source.MEDIA_PAYLOAD,
                    message = "invalid_media_payload: ${failure.message ?: failure.javaClass.simpleName}",
                    cause = failure,
                )
            }
        if (!acceptsEpoch(connectionEpoch)) {
            releaseBuffer(decoded.annexB)
            emitTelemetry(
                "frame_dropped",
                mapOf(
                    "reason" to "stale_session_epoch",
                    "frame_epoch" to connectionEpoch,
                    "current_epoch" to currentEpoch(),
                ),
            )
            return
        }
        val mediaDisposition = validateMedia(decoded.header)
        if (mediaDisposition != ProtocolV1Session.MediaDisposition.ACCEPT) {
            releaseBuffer(decoded.annexB)
            emitTelemetry(
                "frame_dropped",
                mapOf(
                    "reason" to mediaDisposition.name.lowercase(),
                    "config_epoch" to decoded.header.configEpoch,
                    "session_epoch" to connectionEpoch,
                ),
            )
            return
        }
        deliver(
            StreamMediaFrame(
                buffer = decoded.annexB,
                size = decoded.annexB.size,
                receiveTimestampNs = nowNs(),
                keyframe = decoded.header.keyframe,
                connectionEpoch = connectionEpoch,
                configEpoch = decoded.header.configEpoch,
            ),
            emitDiagnostics = false,
            metadata = true,
        )
    }

    private fun deliver(
        frame: StreamMediaFrame,
        emitDiagnostics: Boolean,
        metadata: Boolean,
    ) {
        checkKeyframeFreshness(frame.receiveTimestampNs, frame.keyframe)
        recordFirstReceivedFrame(frame, metadata)
        if (emitDiagnostics) {
            diagFrameCount++
            if (diagFrameCount == 1L) {
                diagLog(
                    "First video frame: size=${frame.size}, keyframe=${frame.keyframe}, " +
                        "metadata=$metadata, callback=${hasFrameSink()}",
                )
            }
            if (diagFrameCount % DIAGNOSTIC_FRAME_INTERVAL == 0L) {
                diagLog("Frames received: $diagFrameCount")
            }
        }
        if (!frameSink(frame)) {
            releaseBuffer(frame.buffer)
        }
        updateStats(frame.size, frame.connectionEpoch)
    }

    private fun recordFirstReceivedFrame(
        frame: StreamMediaFrame,
        metadata: Boolean,
    ) {
        if (frame.configEpoch <= LEGACY_CONFIG_EPOCH) return
        if (firstFrameTelemetryEpoch == frame.connectionEpoch) return
        firstFrameTelemetryEpoch = frame.connectionEpoch
        diagLog(
            "First frame: size=${frame.size}, keyframe=${frame.keyframe}, " +
                "metadata=$metadata, session_epoch=${frame.connectionEpoch}, config_epoch=${frame.configEpoch}, " +
                "callback=${hasFrameSink()}",
        )
        emitTelemetry(
            "first_frame_received",
            mapOf(
                "session_epoch" to frame.connectionEpoch,
                "config_epoch" to frame.configEpoch,
                "size" to frame.size,
                "keyframe" to frame.keyframe,
                "metadata" to metadata,
            ),
        )
    }

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
        return ByteArray(minSize)
    }

    private fun updateStats(
        bytes: Int,
        connectionEpoch: Long,
    ) {
        bytesReceived += bytes
        framesReceived++

        val now = nowMs()
        val elapsed = now - lastStatsTime

        if (elapsed >= STATS_INTERVAL_MS) {
            val mbps = (bytesReceived * 8.0) / (elapsed / 1000.0) / 1_000_000
            val fps = (framesReceived * 1000.0) / elapsed
            onStats(fps, mbps)
            emitTelemetry(
                "stream_stats",
                streamStatsFields(connectionEpoch, fps, mbps),
            )

            bytesReceived = 0
            framesReceived = 0
            lastStatsTime = now
        }
    }

    private fun streamStatsFields(
        connectionEpoch: Long,
        fps: Double,
        mbps: Double,
    ): Map<String, Any?> {
        val decoder = decoderTelemetry()
        return linkedMapOf(
            "session_epoch" to connectionEpoch,
            "fps" to fps,
            "mbps" to mbps,
            "dropped_frames" to decoder.droppedFrames,
            "decoder_latency_avg_ms" to decoder.decoderLatencyAvgMs,
            "decoder_latency_max_ms" to decoder.decoderLatencyMaxMs,
        )
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
            requestKeyframe("last keyframe ${keyframeAgeNs / 1_000_000L}ms ago")
        }
    }

    companion object {
        private const val MAX_FRAME_SIZE = 5 * 1024 * 1024
        private const val MAX_POOLED_BUFFERS = 8
        private const val KEYFRAME_STALE_INTERVAL_NS = 1_500_000_000L
        private const val STATS_INTERVAL_MS = 1_000L
        private const val LEGACY_CONFIG_EPOCH = 0L
        private const val FRAME_FLAG_KEYFRAME = 1
        private const val DIAGNOSTIC_FRAME_INTERVAL = 60L

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
