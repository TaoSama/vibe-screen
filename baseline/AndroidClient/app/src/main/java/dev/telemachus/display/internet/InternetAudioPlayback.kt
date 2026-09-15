package dev.telemachus.display.internet

import dev.telemachus.display.AudioReadinessSnapshot
import dev.telemachus.display.audio.AndroidAudioTrackOutputFactory
import dev.telemachus.display.audio.AUDIO_PACKET_NO_CONFIGURATION_CODE
import dev.telemachus.display.audio.AudioPacketRejectReason
import dev.telemachus.display.audio.ProtocolAudioConfigureResult
import dev.telemachus.display.audio.ProtocolAudioPacketResult
import dev.telemachus.display.audio.ProtocolPcmAudioPlayer
import dev.vibescreen.protocol.v1.AudioConfig

internal data class InternetAudioDecision(
    val accepted: Boolean,
    val rejectionReason: String = "",
) {
    init {
        require(accepted || rejectionReason.isNotBlank()) { "Rejected audio requires a reason" }
    }

    companion object {
        val ACCEPT = InternetAudioDecision(true)
        fun reject(reason: String) = InternetAudioDecision(false, reason)
    }
}

internal interface InternetAudioPlayback {
    val canAdvertiseAudio: Boolean

    fun configure(config: AudioConfig, sessionEpoch: Long): InternetAudioDecision

    fun submit(serializedFrame: ByteArray): InternetAudioDecision

    fun stop(reason: String)

    fun readinessSnapshot(): AudioReadinessSnapshot
}

internal class ProtocolInternetAudioPlayback(
    private val player: ProtocolPcmAudioPlayer = ProtocolPcmAudioPlayer(AndroidAudioTrackOutputFactory()),
) : InternetAudioPlayback {
    private val lock = Any()
    private var acceptedPacketCount = 0L
    private var writtenPacketCount = 0L

    override val canAdvertiseAudio: Boolean = true

    override fun configure(config: AudioConfig, sessionEpoch: Long): InternetAudioDecision =
        synchronized(lock) {
            acceptedPacketCount = 0
            writtenPacketCount = 0
            when (val result = player.configure(config, sessionEpoch)) {
                is ProtocolAudioConfigureResult.Accepted -> {
                    InternetAudioDecision.ACCEPT
                }
                is ProtocolAudioConfigureResult.Rejected -> InternetAudioDecision.reject(result.reason.code)
                is ProtocolAudioConfigureResult.PlaybackFailed -> InternetAudioDecision.reject(result.reason.code)
            }
        }

    override fun submit(serializedFrame: ByteArray): InternetAudioDecision =
        synchronized(lock) {
            when (val result = player.submit(serializedFrame)) {
                is ProtocolAudioPacketResult.Accepted -> {
                    acceptedPacketCount++
                    if (result.writtenPackets > 0) {
                        writtenPacketCount += result.writtenPackets.toLong()
                    }
                    InternetAudioDecision.ACCEPT
                }
                is ProtocolAudioPacketResult.Rejected -> InternetAudioDecision.reject(result.reason.protocolCode)
                is ProtocolAudioPacketResult.PlaybackFailed -> {
                    acceptedPacketCount = 0
                    writtenPacketCount = 0
                    InternetAudioDecision.reject(result.reason.code)
                }
            }
        }

    override fun stop(reason: String) {
        synchronized(lock) {
            player.stop()
            acceptedPacketCount = 0
            writtenPacketCount = 0
        }
    }

    override fun readinessSnapshot(): AudioReadinessSnapshot =
        synchronized(lock) {
            AudioReadinessSnapshot(
                activeFormat = player.activeFormat(),
                acceptedPacketCount = acceptedPacketCount,
                writtenPacketCount = writtenPacketCount,
            )
        }
}

private val AudioPacketRejectReason.protocolCode: String
    get() =
        when (this) {
            AudioPacketRejectReason.NO_CONFIGURATION -> AUDIO_PACKET_NO_CONFIGURATION_CODE
            is AudioPacketRejectReason.ProtocolRejected -> reason.code
        }
