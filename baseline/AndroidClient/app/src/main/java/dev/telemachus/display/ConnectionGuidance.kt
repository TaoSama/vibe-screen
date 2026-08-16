package dev.telemachus.display

import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.Collections
import java.util.IdentityHashMap

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

internal enum class AdbTransportKind {
    USB,
    WIRELESS,
    UNAVAILABLE,
}

internal data class ConnectionGuidanceContext private constructor(
    val mode: ConnectionMode,
    val port: Int?,
    val adbTransport: AdbTransportKind,
) {
    fun withPort(port: Int): ConnectionGuidanceContext =
        ConnectionGuidanceContext(mode, port, adbTransport)

    companion object {
        fun adb(
            port: Int,
            transport: AdbTransportKind,
        ) = ConnectionGuidanceContext(ConnectionMode.USB, port, transport)

        fun trustedLan(port: Int) =
            ConnectionGuidanceContext(ConnectionMode.WIRELESS, port, AdbTransportKind.UNAVAILABLE)

        fun internet() =
            ConnectionGuidanceContext(ConnectionMode.INTERNET, null, AdbTransportKind.UNAVAILABLE)
    }
}

internal object ConnectionGuidanceFactory {
    fun from(
        failure: SessionFailure,
        context: ConnectionGuidanceContext,
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
                    message = "Update Vibe Screen on both devices, then reconnect.",
                )

            SessionFailureKind.OUTBOUND_BACKPRESSURE ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.INPUT_OVERLOADED,
                    status = "Input stream overloaded",
                    message = "Reconnect, then reduce simultaneous touch or peripheral input.",
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
            -> from(IOException(failure.detail), context)

            SessionFailureKind.SERVER_SHUTDOWN ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.UNKNOWN,
                    status = "Session ended",
                    message = "Mac ended the session",
                )

            SessionFailureKind.USER_REQUESTED ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.UNKNOWN,
                    status = "Session ended",
                    message = "Disconnected by user",
                )
        }

    fun from(
        throwable: Throwable,
        context: ConnectionGuidanceContext,
    ): ConnectionGuidance {
        if (throwable is SessionProtocolException) return from(throwable.failure, context)
        val causes = causeChain(throwable)
        return when {
            causes.any { it is ConnectException } ||
                causes.containMessage("ECONNREFUSED") ||
                causes.containMessage("Connection refused") ||
                causes.containMessage("before display configuration") ->
                hostNotRunning(context)

            causes.any { it is NoRouteToHostException || it is UnknownHostException } ||
                causes.containMessage("Network is unreachable") ||
                causes.containMessage("ENETUNREACH") ->
                networkUnreachable(context)

            causes.any { it is SocketTimeoutException } || causes.containMessage("timeout") ->
                timeout(context)

            else ->
                unknown(context)
        }
    }

    private fun hostNotRunning(context: ConnectionGuidanceContext): ConnectionGuidance =
        ConnectionGuidance(
            kind = ConnectionFailureKind.HOST_NOT_RUNNING,
            status = "Mac app unavailable",
            message =
                when (context.mode) {
                    ConnectionMode.USB ->
                        adbRecovery(context, "Open Vibe Screen on your Mac.")
                    ConnectionMode.WIRELESS ->
                        "Open Vibe Screen on your Mac in LAN mode. Confirm both devices use the same " +
                            "trusted Wi-Fi, the saved host address and port ${context.requiredPort()} are current, " +
                            "and the macOS firewall allows Vibe Screen, then reconnect or scan a fresh QR code."
                    ConnectionMode.INTERNET ->
                        "Open Vibe Screen on your Mac in Internet mode and confirm it is online. " +
                            "Try again; if the lease expired, import a fresh session profile from the Mac."
                },
        )

    private fun networkUnreachable(context: ConnectionGuidanceContext): ConnectionGuidance =
        ConnectionGuidance(
            kind = ConnectionFailureKind.NETWORK_UNREACHABLE,
            status =
                if (context.mode == ConnectionMode.USB) {
                    "ADB route unavailable"
                } else {
                    "Network unavailable"
                },
            message =
                when (context.mode) {
                    ConnectionMode.USB ->
                        adbRecovery(context, "The Android-to-Mac route is unavailable.")
                    ConnectionMode.WIRELESS ->
                        "Reconnect both devices to the same trusted Wi-Fi and disable VPN or guest-network " +
                            "isolation. Verify the saved Mac address and port ${context.requiredPort()}, then reconnect."
                    ConnectionMode.INTERNET ->
                        "Restore this device's Internet connection, then try again. If direct routing remains " +
                            "unavailable, select TURN only when the imported profile provides TURN credentials."
                },
        )

    private fun timeout(context: ConnectionGuidanceContext): ConnectionGuidance =
        ConnectionGuidance(
            kind = ConnectionFailureKind.TIMEOUT,
            status = "Connection timed out",
            message =
                when (context.mode) {
                    ConnectionMode.USB ->
                        adbRecovery(
                            context,
                            "Confirm Vibe Screen is listening on port ${context.requiredPort()} on your Mac.",
                        )
                    ConnectionMode.WIRELESS ->
                        "Confirm Vibe Screen is listening in LAN mode on port ${context.requiredPort()}, both devices " +
                            "remain on the same trusted Wi-Fi, and the macOS firewall allows the connection, then retry."
                    ConnectionMode.INTERNET ->
                        "Check this device's Internet connection and the selected Direct or TURN route, then retry. " +
                            "If the lease expired, import a fresh session profile from the Mac."
                },
        )

    private fun unknown(context: ConnectionGuidanceContext): ConnectionGuidance =
        ConnectionGuidance(
            kind = ConnectionFailureKind.UNKNOWN,
            status = "Connection failed",
            message =
                when (context.mode) {
                    ConnectionMode.USB ->
                        adbRecovery(context, "Check Vibe Screen on your Mac and retry.")
                    ConnectionMode.WIRELESS ->
                        "Check Vibe Screen in LAN mode, the trusted Wi-Fi connection, the saved host address, " +
                            "port ${context.requiredPort()}, and the macOS firewall, then retry."
                    ConnectionMode.INTERNET ->
                        "Check Vibe Screen in Internet mode and this device's network, then retry. " +
                            "If the session is no longer valid, import a fresh session profile."
                },
        )

    private fun causeChain(throwable: Throwable): List<Throwable> {
        val seen = Collections.newSetFromMap(IdentityHashMap<Throwable, Boolean>())
        val causes = ArrayList<Throwable>(MAX_CAUSE_DEPTH)
        var current: Throwable? = throwable
        while (current != null && causes.size < MAX_CAUSE_DEPTH && seen.add(current)) {
            causes += current
            current = current.cause
        }
        return causes
    }

    private fun List<Throwable>.containMessage(fragment: String): Boolean =
        any { cause -> cause.message?.contains(fragment, ignoreCase = true) == true }

    private fun adbRecovery(
        context: ConnectionGuidanceContext,
        prefix: String,
    ): String {
        val port = context.requiredPort()
        val routeSteps =
            when (context.adbTransport) {
                AdbTransportKind.USB ->
                    "Keep the USB data cable connected, authorize USB debugging, then run " +
                        "adb reverse tcp:$port tcp:$port on the Mac."
                AdbTransportKind.WIRELESS ->
                    "Keep Wireless debugging enabled, run adb connect <device-ip>:<wireless-adb-port> on the Mac, " +
                        "authorize the connection, then run adb reverse tcp:$port tcp:$port."
                AdbTransportKind.UNAVAILABLE ->
                    "Enable Developer options and connect either a USB data cable with USB debugging or Wireless " +
                        "debugging. For Wireless debugging, run adb connect <device-ip>:<wireless-adb-port>; " +
                        "then run adb reverse tcp:$port tcp:$port."
            }
        return "$prefix $routeSteps"
    }

    private fun ConnectionGuidanceContext.requiredPort(): Int =
        checkNotNull(port) { "Port is required for USB and LAN guidance" }

    private const val MAX_CAUSE_DEPTH = 32
}
