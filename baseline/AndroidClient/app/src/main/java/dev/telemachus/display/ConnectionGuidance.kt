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
        mode: ConnectionMode,
    ): ConnectionGuidance =
        when (failure.kind) {
            SessionFailureKind.INVALID_DISPLAY,
            SessionFailureKind.INVALID_FRAME,
            SessionFailureKind.INVALID_ENVELOPE,
            SessionFailureKind.INVALID_MEDIA_PAYLOAD,
            SessionFailureKind.INVALID_MEDIA_HEADER,
            SessionFailureKind.INVALID_PEER_MESSAGE,
            SessionFailureKind.SESSION_REJECTED,
            SessionFailureKind.HOST_PROTOCOL_ERROR,
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
            -> from(IOException(failure.detail), port, mode)

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
        mode: ConnectionMode,
    ): ConnectionGuidance {
        if (throwable is SessionProtocolException) return from(throwable.failure, port, mode)
        val detail = throwable.message.orEmpty()
        val fallback = throwable.javaClass.simpleName
        return when {
            detail.contains("ECONNREFUSED", ignoreCase = true) ||
                detail.contains("Connection refused", ignoreCase = true) ||
                detail.contains("before display configuration", ignoreCase = true) ->
                hostNotRunning(port, mode)

            detail.contains("Network is unreachable", ignoreCase = true) ||
                detail.contains("ENETUNREACH", ignoreCase = true) ->
                networkUnreachable(port, mode)

            detail.contains("timeout", ignoreCase = true) ->
                timeout(port, mode)

            else ->
                unknown(detail, fallback, port, mode)
        }
    }

    private fun hostNotRunning(
        port: Int,
        mode: ConnectionMode,
    ): ConnectionGuidance =
        when (mode) {
            ConnectionMode.USB ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.HOST_NOT_RUNNING,
                    status = "Mac app unavailable",
                    message = "Open Vibe Screen on your Mac. If you use USB or wireless debugging, " +
                        "connect ADB from the Mac (wireless: adb connect <device-ip>:<wireless-adb-port>), " +
                        "authorize debugging, then run adb reverse tcp:$port tcp:$port.",
                )

            ConnectionMode.WIRELESS ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.HOST_NOT_RUNNING,
                    status = "Mac app unavailable",
                    message = "Open Vibe Screen on your Mac and confirm it is reachable on the same " +
                        "network. Verify the host address and port $port, then reconnect.",
                )

            ConnectionMode.INTERNET ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.HOST_NOT_RUNNING,
                    status = "Mac app unavailable",
                    message = "Open Vibe Screen on your Mac and try again. If the session expired, " +
                        "import a fresh session profile from the Mac.",
                )
        }

    private fun networkUnreachable(
        port: Int,
        mode: ConnectionMode,
    ): ConnectionGuidance =
        when (mode) {
            ConnectionMode.USB ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.NETWORK_UNREACHABLE,
                    status = "ADB route unavailable",
                    message = "Reconnect the USB data cable, or enable wireless debugging and run " +
                        "adb connect <device-ip>:<wireless-adb-port> on the Mac. Authorize debugging, " +
                        "then run adb reverse tcp:$port tcp:$port.",
                )

            ConnectionMode.WIRELESS ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.NETWORK_UNREACHABLE,
                    status = "Mac unreachable",
                    message = "Check that your phone and Mac are on the same Wi-Fi network and that " +
                        "the Mac is reachable. Verify the host address and port $port, then reconnect.",
                )

            ConnectionMode.INTERNET ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.NETWORK_UNREACHABLE,
                    status = "Network unavailable",
                    message = "Check your internet connection and try again. If the problem persists, " +
                        "import a fresh session profile from the Mac.",
                )
        }

    private fun timeout(
        port: Int,
        mode: ConnectionMode,
    ): ConnectionGuidance =
        when (mode) {
            ConnectionMode.USB ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.TIMEOUT,
                    status = "Connection timed out",
                    message = "Confirm the Mac app is listening on port $port and that its firewall allows the connection. " +
                        "If you use USB or wireless debugging, confirm ADB is connected and run " +
                        "adb reverse tcp:$port tcp:$port.",
                )

            ConnectionMode.WIRELESS ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.TIMEOUT,
                    status = "Connection timed out",
                    message = "Confirm the Mac app is listening on port $port and that its firewall " +
                        "allows the connection. Check that both devices are on the same network, " +
                        "then reconnect.",
                )

            ConnectionMode.INTERNET ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.TIMEOUT,
                    status = "Connection timed out",
                    message = "The connection to the Mac timed out. Check your internet connection " +
                        "and try again. If the session expired, import a fresh session profile.",
                )
        }

    private fun unknown(
        detail: String,
        fallback: String,
        port: Int,
        mode: ConnectionMode,
    ): ConnectionGuidance =
        when (mode) {
            ConnectionMode.USB ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.UNKNOWN,
                    status = "Connection failed",
                    message = "Check the Mac app, USB or wireless debugging, the Mac's adb connect session, " +
                        "and adb reverse for port $port, then try again. " +
                        "Technical detail: ${detail.ifBlank { fallback }}",
                )

            ConnectionMode.WIRELESS ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.UNKNOWN,
                    status = "Connection failed",
                    message = "Check the Mac app, your network connection, and the host address and " +
                        "port $port, then try again. " +
                        "Technical detail: ${detail.ifBlank { fallback }}",
                )

            ConnectionMode.INTERNET ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.UNKNOWN,
                    status = "Connection failed",
                    message = "Check your internet connection and the Mac app, then try again. " +
                        "If the problem persists, import a fresh session profile. " +
                        "Technical detail: ${detail.ifBlank { fallback }}",
                )
        }
}
