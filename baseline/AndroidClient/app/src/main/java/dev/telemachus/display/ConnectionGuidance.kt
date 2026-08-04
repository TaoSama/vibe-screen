package dev.telemachus.display

import java.io.IOException

internal enum class ConnectionFailureKind {
    HOST_NOT_RUNNING,
    NETWORK_UNREACHABLE,
    TIMEOUT,
    INCOMPATIBLE_SESSION,
    INPUT_OVERLOADED,
    UNKNOWN,
}

internal data class ConnectionGuidance(
    val kind: ConnectionFailureKind,
    val status: String,
    val message: String,
)

internal object ConnectionGuidanceFactory {
    fun from(
        failure: SessionFailure,
        port: Int,
    ): ConnectionGuidance =
        when (failure.kind) {
            SessionFailureKind.INVALID_DISPLAY,
            SessionFailureKind.INVALID_FRAME,
            SessionFailureKind.UNKNOWN_MESSAGE,
            ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.INCOMPATIBLE_SESSION,
                    status = "Mac app is incompatible",
                    message = "Update Vibe Screen on both devices, then reconnect. " +
                        "Technical detail: ${failure.detail}",
                )

            SessionFailureKind.OUTBOUND_BACKPRESSURE ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.INPUT_OVERLOADED,
                    status = "Input stream overloaded",
                    message = "Reconnect, then reduce simultaneous touch or peripheral input. " +
                        "Technical detail: ${failure.detail}",
                )

            SessionFailureKind.CODEC_CONFIGURATION ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.INCOMPATIBLE_SESSION,
                    status = "Video decoder recovery",
                    message = "Keep the Mac app open while the client retries with a compatible codec.",
                )

            SessionFailureKind.HEARTBEAT_TIMEOUT,
            SessionFailureKind.TRANSPORT_CLOSED,
            SessionFailureKind.WRITE_FAILED,
            -> from(IOException(failure.detail), port)

            SessionFailureKind.SERVER_SHUTDOWN,
            SessionFailureKind.USER_REQUESTED,
            ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.UNKNOWN,
                    status = "Session ended",
                    message = failure.detail,
                )
        }

    fun from(
        throwable: Throwable,
        port: Int,
    ): ConnectionGuidance {
        if (throwable is SessionProtocolException) return from(throwable.failure, port)
        val detail = throwable.message.orEmpty()
        return when {
            detail.contains("ECONNREFUSED", ignoreCase = true) ||
                detail.contains("Connection refused", ignoreCase = true) ||
                detail.contains("before display configuration", ignoreCase = true) ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.HOST_NOT_RUNNING,
                    status = "Mac app unavailable",
                    message = "Open Vibe Screen on your Mac, then try again.",
                )

            detail.contains("Network is unreachable", ignoreCase = true) ||
                detail.contains("ENETUNREACH", ignoreCase = true) ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.NETWORK_UNREACHABLE,
                    status = "USB route unavailable",
                    message = "Reconnect the USB data cable, authorize debugging, then run " +
                        "adb reverse tcp:$port tcp:$port on the Mac.",
                )

            detail.contains("timeout", ignoreCase = true) ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.TIMEOUT,
                    status = "Connection timed out",
                    message = "Confirm the Mac app is listening on port $port and that its firewall allows the connection.",
                )

            else ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.UNKNOWN,
                    status = "Connection failed",
                    message = "Check the Mac app, USB debugging, and adb reverse for port $port, then try again. " +
                        "Technical detail: ${detail.ifBlank { throwable.javaClass.simpleName }}",
                )
        }
    }
}
