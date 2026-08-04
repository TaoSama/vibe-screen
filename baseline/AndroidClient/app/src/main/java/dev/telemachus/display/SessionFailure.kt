package dev.telemachus.display

import java.io.IOException

internal enum class SessionFailureKind {
    TRANSPORT_CLOSED,
    HEARTBEAT_TIMEOUT,
    WRITE_FAILED,
    OUTBOUND_BACKPRESSURE,
    INVALID_DISPLAY,
    INVALID_FRAME,
    UNKNOWN_MESSAGE,
    CODEC_CONFIGURATION,
    SERVER_SHUTDOWN,
    USER_REQUESTED,
}

internal data class SessionFailure(
    val kind: SessionFailureKind,
    val detail: String,
    val retryable: Boolean,
    val intentional: Boolean = false,
) {
    companion object {
        fun transport(detail: String) =
            SessionFailure(SessionFailureKind.TRANSPORT_CLOSED, detail, retryable = true)

        fun heartbeat(detail: String) =
            SessionFailure(SessionFailureKind.HEARTBEAT_TIMEOUT, detail, retryable = true)

        fun write(detail: String) =
            SessionFailure(SessionFailureKind.WRITE_FAILED, detail, retryable = true)

        fun protocol(
            kind: SessionFailureKind,
            detail: String,
        ) = SessionFailure(kind, detail, retryable = false)

        fun codec(detail: String) =
            SessionFailure(SessionFailureKind.CODEC_CONFIGURATION, detail, retryable = true)

        fun serverShutdown() =
            SessionFailure(
                SessionFailureKind.SERVER_SHUTDOWN,
                "Mac ended the session",
                retryable = false,
                intentional = true,
            )

        fun userRequested() =
            SessionFailure(
                SessionFailureKind.USER_REQUESTED,
                "Disconnected by user",
                retryable = false,
                intentional = true,
            )
    }
}

internal class SessionProtocolException(
    val failure: SessionFailure,
) : IOException(failure.detail)
