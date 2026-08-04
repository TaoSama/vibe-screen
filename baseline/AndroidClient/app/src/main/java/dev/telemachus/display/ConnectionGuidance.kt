package dev.telemachus.display

internal enum class ConnectionFailureKind {
    HOST_NOT_RUNNING,
    NETWORK_UNREACHABLE,
    TIMEOUT,
    UNKNOWN,
}

internal data class ConnectionGuidance(
    val kind: ConnectionFailureKind,
    val status: String,
    val message: String,
)

internal object ConnectionGuidanceFactory {
    fun from(
        throwable: Throwable,
        port: Int,
    ): ConnectionGuidance {
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
