package dev.telemachus.display.internet

/** Typed SDP/ICE boundary implemented by the production signaling client. */
interface SignalingClient : AutoCloseable {
    interface Listener {
        fun onOffer(sdp: String)

        fun onAnswer(sdp: String)

        fun onIceCandidate(candidate: SignalingIceCandidate)

        fun onEndOfCandidates()

        fun onFailure(error: Throwable)
    }

    fun start(listener: Listener)

    fun sendOffer(sdp: String)

    fun sendAnswer(sdp: String)

    fun sendIceCandidate(candidate: SignalingIceCandidate)

    fun sendEndOfCandidates()
}

data class SignalingIceCandidate(
    val candidate: String,
    val sdpMid: String?,
    val sdpMLineIndex: Int,
    val usernameFragment: String? = null,
) {
    init {
        require(candidate.isNotBlank()) { "ICE candidate must not be blank" }
        require(sdpMLineIndex >= 0) { "SDP m-line index must not be negative" }
    }
}

internal fun interface SignalingClientFactory {
    fun create(
        configuration: SignalingConfiguration,
        sessionId: String,
    ): SignalingClient
}
