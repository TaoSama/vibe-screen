package dev.telemachus.display.internet

import android.content.Context
import org.webrtc.PeerConnectionFactory
import org.webrtc.RTCStatsReport

internal object AndroidWebRtcRuntime {
    private val initializationLock = Any()
    @Volatile private var initialized = false

    fun ensureInitialized(context: Context) {
        if (initialized) return
        synchronized(initializationLock) {
            if (initialized) return
            PeerConnectionFactory.initialize(
                PeerConnectionFactory.InitializationOptions.builder(context).createInitializationOptions(),
            )
            initialized = true
        }
    }
}

internal object WebRtcStatsParser {
    /** DataChannel media has no RTP loss/jitter report; candidate-pair stats still drive RTT/bandwidth policy. */
    fun parse(report: RTCStatsReport): WebRtcStats? {
        val pair =
            report.statsMap.values.firstOrNull {
                it.type == "candidate-pair" && it.members["nominated"] == true
            } ?: return null
        val bitrate = pair.members["availableOutgoingBitrate"].asDoubleOrNull()?.div(1_000)?.toInt() ?: return null
        val rtt = pair.members["currentRoundTripTime"].asDoubleOrNull()?.times(1_000)?.toInt() ?: 0
        return WebRtcStats(bitrate.coerceAtLeast(0), 0.0, rtt.coerceAtLeast(0), 0)
    }

    private fun Any?.asDoubleOrNull(): Double? = (this as? Number)?.toDouble()
}
