package dev.telemachus.display.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import dev.vibescreen.protocol.v1.AudioConfig
import kotlin.math.max

internal class ProtocolPcmAudioPlayer(
    private val outputFactory: PcmAudioOutputFactory,
    private val maximumBufferedPackets: Int = DEFAULT_PLAYER_BUFFERED_PACKETS,
) {
    private var active: ActivePlayback? = null

    @Synchronized
    fun configure(
        config: AudioConfig,
        sessionEpoch: Long,
        firstSequence: Long = INITIAL_AUDIO_SEQUENCE,
    ): ProtocolAudioConfigureResult {
        val previousStopFailure = stop()
        if (previousStopFailure != null) {
            return ProtocolAudioConfigureResult.PlaybackFailed(previousStopFailure)
        }
        if (sessionEpoch <= 0) {
            return ProtocolAudioConfigureResult.Rejected(AudioRejectReason.INVALID_SESSION_EPOCH)
        }
        val format =
            try {
                PcmAudioStreamFormat.from(config)
            } catch (failure: ProtocolAudioException) {
                return ProtocolAudioConfigureResult.Rejected(failure.reason)
            }
        val jitterBuffer =
            try {
                AudioJitterBuffer(firstSequence, maximumBufferedPackets)
        } catch (failure: IllegalArgumentException) {
            return ProtocolAudioConfigureResult.Rejected(AudioRejectReason.INVALID_SEQUENCE)
        }
        val output =
            try {
                outputFactory.create(format)
            } catch (failure: AudioOutputException) {
                return ProtocolAudioConfigureResult.PlaybackFailed(failure.reason)
            }
        return try {
            output.start()
            active =
                ActivePlayback(
                    sessionEpoch = sessionEpoch,
                    format = format,
                    jitterBuffer = jitterBuffer,
                    output = output,
                )
            ProtocolAudioConfigureResult.Accepted(format.streamId, format.configEpoch)
        } catch (failure: AudioOutputException) {
            ProtocolAudioConfigureResult.PlaybackFailed(failure.reason, output.closeCapturingFailure())
        }
    }

    @Synchronized
    fun submit(serializedFrame: ByteArray): ProtocolAudioPacketResult {
        val packet =
            try {
                ProtocolAudioPacket.parse(serializedFrame)
            } catch (failure: ProtocolAudioException) {
                return ProtocolAudioPacketResult.Rejected(AudioPacketRejectReason.ProtocolRejected(failure.reason))
            }
        return submit(packet)
    }

    @Synchronized
    fun submit(packet: ProtocolAudioPacket): ProtocolAudioPacketResult {
        val current = active ?: return ProtocolAudioPacketResult.Rejected(AudioPacketRejectReason.NO_CONFIGURATION)
        val enqueueResult =
            try {
                current.jitterBuffer.enqueue(packet, current.sessionEpoch, current.format)
            } catch (failure: ProtocolAudioException) {
                return ProtocolAudioPacketResult.Rejected(AudioPacketRejectReason.ProtocolRejected(failure.reason))
            }
        val ready = current.jitterBuffer.drainReady()
        var writtenPackets = 0
        ready.forEach { readyPacket ->
            when (val write = current.output.writePcm(readyPacket.payload)) {
                is PcmAudioWriteResult.Written -> writtenPackets++
                is PcmAudioWriteResult.Failed -> {
                    return ProtocolAudioPacketResult.PlaybackFailed(write.reason, stop())
                }
            }
        }
        return ProtocolAudioPacketResult.Accepted(enqueueResult, writtenPackets)
    }

    @Synchronized
    fun stop(): AudioOutputFailureReason? {
        val current = active ?: return null
        active = null
        return current.output.closeCapturingFailure()
    }

    @Synchronized
    fun activeFormat(): PcmAudioStreamFormat? = active?.format

    private data class ActivePlayback(
        val sessionEpoch: Long,
        val format: PcmAudioStreamFormat,
        val jitterBuffer: AudioJitterBuffer,
        val output: PcmAudioOutput,
    )
}

internal sealed interface ProtocolAudioConfigureResult {
    data class Accepted(val streamId: Long, val configEpoch: Long) : ProtocolAudioConfigureResult

    data class Rejected(val reason: AudioRejectReason) : ProtocolAudioConfigureResult

    data class PlaybackFailed(
        val reason: AudioOutputFailureReason,
        val cleanupFailureReason: AudioOutputFailureReason? = null,
    ) : ProtocolAudioConfigureResult
}

internal sealed interface ProtocolAudioPacketResult {
    data class Accepted(
        val enqueueResult: AudioEnqueueResult,
        val writtenPackets: Int,
    ) : ProtocolAudioPacketResult

    data class Rejected(val reason: AudioPacketRejectReason) : ProtocolAudioPacketResult

    data class PlaybackFailed(
        val reason: AudioOutputFailureReason,
        val cleanupFailureReason: AudioOutputFailureReason? = null,
    ) : ProtocolAudioPacketResult
}

internal sealed interface AudioPacketRejectReason {
    data object NO_CONFIGURATION : AudioPacketRejectReason

    data class ProtocolRejected(val reason: AudioRejectReason) : AudioPacketRejectReason
}

internal const val AUDIO_PACKET_NO_CONFIGURATION_CODE = "no_audio_configuration"

internal interface PcmAudioOutputFactory {
    fun create(format: PcmAudioStreamFormat): PcmAudioOutput
}

internal interface PcmAudioOutput : AutoCloseable {
    fun start()

    fun writePcm(payload: ByteArray): PcmAudioWriteResult

    fun stop()
}

internal sealed interface PcmAudioWriteResult {
    data object Written : PcmAudioWriteResult

    data class Failed(val reason: AudioOutputFailureReason) : PcmAudioWriteResult
}

internal enum class AudioOutputFailureReason(val code: String) {
    CREATE_FAILED("audio_track_create_failed"),
    NOT_INITIALIZED("audio_track_not_initialized"),
    START_FAILED("audio_track_start_failed"),
    WRITE_FAILED("audio_track_write_failed"),
    WRITE_BAD_VALUE("audio_track_write_bad_value"),
    WRITE_INVALID_OPERATION("audio_track_write_invalid_operation"),
    WRITE_DEAD_OBJECT("audio_track_write_dead_object"),
    WRITE_STALLED("audio_track_write_stalled"),
    STOP_FAILED("audio_track_stop_failed"),
    RELEASE_FAILED("audio_track_release_failed"),
}

internal class AudioOutputException(
    val reason: AudioOutputFailureReason,
    cause: Throwable? = null,
) : IllegalStateException(reason.code, cause)

internal class AndroidAudioTrackOutputFactory : PcmAudioOutputFactory {
    override fun create(format: PcmAudioStreamFormat): PcmAudioOutput = AndroidAudioTrackOutput(format)
}

internal class AndroidAudioTrackOutput(
    private val format: PcmAudioStreamFormat,
    private val track: AudioTrack = createAudioTrack(format),
) : PcmAudioOutput {
    private var closed = false

    init {
        if (track.state != AudioTrack.STATE_INITIALIZED) {
            track.release()
            throw AudioOutputException(AudioOutputFailureReason.NOT_INITIALIZED)
        }
    }

    override fun start() {
        try {
            track.play()
        } catch (failure: IllegalStateException) {
            throw AudioOutputException(AudioOutputFailureReason.START_FAILED, failure)
        }
        if (track.playState != AudioTrack.PLAYSTATE_PLAYING) {
            throw AudioOutputException(AudioOutputFailureReason.START_FAILED)
        }
    }

    override fun writePcm(payload: ByteArray): PcmAudioWriteResult {
        var offset = 0
        var zeroWriteCount = 0
        while (offset < payload.size) {
            val written =
                try {
                    track.write(payload, offset, payload.size - offset, AudioTrack.WRITE_BLOCKING)
                } catch (failure: IllegalStateException) {
                    return PcmAudioWriteResult.Failed(AudioOutputFailureReason.WRITE_INVALID_OPERATION)
                }
            when {
                written > 0 -> {
                    offset += written
                    zeroWriteCount = 0
                }
                written == 0 -> {
                    zeroWriteCount++
                    if (zeroWriteCount >= MAX_ZERO_WRITES_PER_PACKET) {
                        return PcmAudioWriteResult.Failed(AudioOutputFailureReason.WRITE_STALLED)
                    }
                }
                else -> return PcmAudioWriteResult.Failed(mapAudioTrackWriteFailure(written))
            }
        }
        return PcmAudioWriteResult.Written
    }

    override fun stop() {
        try {
            if (track.playState != AudioTrack.PLAYSTATE_STOPPED) {
                track.stop()
            }
        } catch (failure: IllegalStateException) {
            throw AudioOutputException(AudioOutputFailureReason.STOP_FAILED, failure)
        }
    }

    override fun close() {
        if (closed) return
        closed = true
        val stopFailure =
            try {
                stop()
                null
            } catch (failure: AudioOutputException) {
                failure
            }
        try {
            track.release()
        } catch (failure: RuntimeException) {
            throw AudioOutputException(AudioOutputFailureReason.RELEASE_FAILED, failure)
        }
        if (stopFailure != null) throw stopFailure
    }
}

private fun createAudioTrack(format: PcmAudioStreamFormat): AudioTrack {
    val audioFormat =
        AudioFormat
            .Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .setSampleRate(format.sampleRateHz)
            .setChannelIndexMask(channelIndexMask(format.channelCount))
            .build()
    val attributes =
        AudioAttributes
            .Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_MOVIE)
            .build()
    return try {
        AudioTrack
            .Builder()
            .setAudioAttributes(attributes)
            .setAudioFormat(audioFormat)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .setBufferSizeInBytes(playbackBufferBytes(format))
            .build()
    } catch (failure: RuntimeException) {
        throw AudioOutputException(AudioOutputFailureReason.CREATE_FAILED, failure)
    }
}

private fun PcmAudioOutput.closeCapturingFailure(): AudioOutputFailureReason? =
    try {
        close()
        null
    } catch (failure: Exception) {
        (failure as? AudioOutputException)?.reason ?: AudioOutputFailureReason.RELEASE_FAILED
    }

private fun channelIndexMask(channelCount: Int): Int = (1 shl channelCount) - 1

private fun playbackBufferBytes(format: PcmAudioStreamFormat): Int {
    val oneHundredMillis = format.sampleRateHz / PLAYBACK_BUFFER_FRACTION_PER_SECOND
    val minimumBufferedBytes = max(oneHundredMillis, format.framesPerPacket) * format.channelCount * PCM_SAMPLE_BYTES
    return max(format.bytesPerPacket * PLAYBACK_BUFFER_PACKETS, minimumBufferedBytes)
}

private fun mapAudioTrackWriteFailure(errorCode: Int): AudioOutputFailureReason =
    when (errorCode) {
        AudioTrack.ERROR_BAD_VALUE -> AudioOutputFailureReason.WRITE_BAD_VALUE
        AudioTrack.ERROR_INVALID_OPERATION -> AudioOutputFailureReason.WRITE_INVALID_OPERATION
        AudioTrack.ERROR_DEAD_OBJECT -> AudioOutputFailureReason.WRITE_DEAD_OBJECT
        else -> AudioOutputFailureReason.WRITE_FAILED
    }

private const val INITIAL_AUDIO_SEQUENCE = 0L
private const val DEFAULT_PLAYER_BUFFERED_PACKETS = 8
private const val PLAYBACK_BUFFER_PACKETS = 8
private const val PLAYBACK_BUFFER_FRACTION_PER_SECOND = 10
private const val PCM_SAMPLE_BYTES = 2
private const val MAX_ZERO_WRITES_PER_PACKET = 2
