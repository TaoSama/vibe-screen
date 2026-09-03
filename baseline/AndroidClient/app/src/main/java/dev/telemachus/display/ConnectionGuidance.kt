package dev.telemachus.display

import android.content.res.Resources
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.Collections
import java.util.IdentityHashMap

internal enum class ConnectionFailureKind {
    HOST_NOT_RUNNING,
    USB_ROUTE_UNAVAILABLE,
    NETWORK_UNREACHABLE,
    TIMEOUT,
    INCOMPATIBLE_SESSION,
    INPUT_OVERLOADED,
    UNKNOWN,
}

internal data class ConnectionGuidance(
    val kind: ConnectionFailureKind,
    val status: ConnectionGuidanceText,
    val message: ConnectionGuidanceText,
)

internal data class ConnectionGuidanceText(
    val resourceId: Int,
    val args: List<Any> = emptyList(),
)

internal object ConnectionGuidanceTextFormatter {
    fun format(
        resources: Resources,
        text: ConnectionGuidanceText,
    ): String {
        val resolvedArgs =
            text.args.map { arg ->
                if (arg is ConnectionGuidanceText) {
                    format(resources, arg)
                } else {
                    arg
                }
            }.toTypedArray()
        return resources.getString(text.resourceId, *resolvedArgs)
    }
}

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
                    status = text(R.string.connection_guidance_mac_incompatible_title),
                    message = text(R.string.connection_guidance_mac_incompatible_message),
                )

            SessionFailureKind.OUTBOUND_BACKPRESSURE ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.INPUT_OVERLOADED,
                    status = text(R.string.connection_guidance_input_overloaded_title),
                    message = text(R.string.connection_guidance_input_overloaded_message),
                )

            SessionFailureKind.CODEC_CONFIGURATION ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.INCOMPATIBLE_SESSION,
                    status = text(R.string.connection_guidance_video_decoder_recovery_title),
                    message = text(R.string.connection_guidance_video_decoder_recovery_message),
                )

            SessionFailureKind.HEARTBEAT_TIMEOUT,
            SessionFailureKind.TRANSPORT_CLOSED,
            SessionFailureKind.WRITE_FAILED,
            -> from(IOException(failure.detail), context)

            SessionFailureKind.SERVER_SHUTDOWN ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.UNKNOWN,
                    status = text(R.string.connection_guidance_session_ended_title),
                    message = text(R.string.connection_guidance_mac_ended_session_message),
                )

            SessionFailureKind.USER_REQUESTED ->
                ConnectionGuidance(
                    kind = ConnectionFailureKind.UNKNOWN,
                    status = text(R.string.connection_guidance_session_ended_title),
                    message = text(R.string.connection_guidance_user_disconnected_message),
                )
        }

    fun from(
        throwable: Throwable,
        context: ConnectionGuidanceContext,
    ): ConnectionGuidance {
        if (throwable is SessionProtocolException) return from(throwable.failure, context)
        val causes = causeChain(throwable)
        return when {
            causes.any { it is SocketTimeoutException } ||
                causes.containMessage("timeout") ||
                causes.containMessage("timed out") ||
                causes.containMessage("ETIMEDOUT") ->
                timeout(context)

            causes.containMessage("before display configuration") ||
                causes.containMessage("Protocol upgrade probe closed before a response") ->
                hostNotRunning(context)

            context.mode == ConnectionMode.USB && causes.isConnectionRefused() ->
                usbRouteUnavailable(context)

            causes.any { it is NoRouteToHostException || it is UnknownHostException } ||
                causes.containMessage("Network is unreachable") ||
                causes.containMessage("ENETUNREACH") ||
                causes.containMessage("No Wi-Fi route is available") ->
                networkUnreachable(context)

            causes.isConnectionRefused() ->
                hostNotRunning(context)

            else ->
                unknown(context)
        }
    }

    private fun hostNotRunning(context: ConnectionGuidanceContext): ConnectionGuidance =
        ConnectionGuidance(
            kind = ConnectionFailureKind.HOST_NOT_RUNNING,
            status = text(R.string.connection_guidance_mac_unavailable_title),
            message =
                when (context.mode) {
                    ConnectionMode.USB ->
                        adbRecovery(context, text(R.string.connection_guidance_usb_open_mac_prefix))
                    ConnectionMode.WIRELESS ->
                        text(R.string.connection_guidance_lan_host_unavailable_message, context.requiredPort())
                    ConnectionMode.INTERNET ->
                        text(R.string.connection_guidance_internet_host_unavailable_message)
                },
        )

    private fun networkUnreachable(context: ConnectionGuidanceContext): ConnectionGuidance =
        ConnectionGuidance(
            kind = ConnectionFailureKind.NETWORK_UNREACHABLE,
            status =
                if (context.mode == ConnectionMode.USB) {
                    text(R.string.connection_guidance_adb_route_unavailable_title)
                } else {
                    text(R.string.connection_guidance_network_unavailable_title)
                },
            message =
                when (context.mode) {
                    ConnectionMode.USB ->
                        adbRecovery(context, text(R.string.connection_guidance_usb_route_unavailable_prefix))
                    ConnectionMode.WIRELESS ->
                        text(R.string.connection_guidance_lan_network_unavailable_message, context.requiredPort())
                    ConnectionMode.INTERNET ->
                        text(R.string.connection_guidance_internet_network_unavailable_message)
                },
        )

    private fun usbRouteUnavailable(context: ConnectionGuidanceContext): ConnectionGuidance =
        ConnectionGuidance(
            kind = ConnectionFailureKind.USB_ROUTE_UNAVAILABLE,
            status = text(R.string.connection_guidance_adb_route_unavailable_title),
            message = adbRecovery(context, text(R.string.connection_guidance_usb_route_unavailable_prefix)),
        )

    private fun timeout(context: ConnectionGuidanceContext): ConnectionGuidance =
        ConnectionGuidance(
            kind = ConnectionFailureKind.TIMEOUT,
            status = text(R.string.connection_guidance_timeout_title),
            message =
                when (context.mode) {
                    ConnectionMode.USB ->
                        adbRecovery(
                            context,
                            text(R.string.connection_guidance_usb_timeout_prefix),
                        )
                    ConnectionMode.WIRELESS ->
                        text(R.string.connection_guidance_lan_timeout_message, context.requiredPort())
                    ConnectionMode.INTERNET ->
                        text(R.string.connection_guidance_internet_timeout_message)
                },
        )

    private fun unknown(context: ConnectionGuidanceContext): ConnectionGuidance =
        ConnectionGuidance(
            kind = ConnectionFailureKind.UNKNOWN,
            status = text(R.string.connection_guidance_failed_title),
            message =
                when (context.mode) {
                    ConnectionMode.USB ->
                        adbRecovery(context, text(R.string.connection_guidance_usb_unknown_prefix))
                    ConnectionMode.WIRELESS ->
                        text(R.string.connection_guidance_lan_unknown_message, context.requiredPort())
                    ConnectionMode.INTERNET ->
                        text(R.string.connection_guidance_internet_unknown_message)
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

    private fun List<Throwable>.isConnectionRefused(): Boolean =
        any { it is ConnectException } ||
            containMessage("ECONNREFUSED") ||
            containMessage("Connection refused")

    private fun adbRecovery(
        context: ConnectionGuidanceContext,
        prefix: ConnectionGuidanceText,
    ): ConnectionGuidanceText {
        val port = context.requiredPort()
        return when (context.adbTransport) {
            AdbTransportKind.USB -> text(R.string.connection_guidance_usb_recovery_usb, prefix, port)
            AdbTransportKind.WIRELESS -> text(R.string.connection_guidance_usb_recovery_wireless_adb, prefix, port)
            AdbTransportKind.UNAVAILABLE -> text(R.string.connection_guidance_usb_recovery_unavailable, prefix, port)
        }
    }

    private fun text(
        resourceId: Int,
        vararg args: Any,
    ) = ConnectionGuidanceText(resourceId, args.toList())

    private fun ConnectionGuidanceContext.requiredPort(): Int =
        checkNotNull(port) { "Port is required for USB and LAN guidance" }

    private const val MAX_CAUSE_DEPTH = 32
}
