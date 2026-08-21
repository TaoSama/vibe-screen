package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.FileAccept
import dev.vibescreen.protocol.v1.FileOffer
import dev.vibescreen.protocol.v1.FileTransferCancel
import dev.vibescreen.protocol.v1.FileTransferComplete
import dev.vibescreen.protocol.v1.FileTransferProgress
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import java.io.DataOutputStream

/** Routes Protocol v1 session actions to the owning StreamClient handlers. */
internal class StreamProtocolActionDispatcher(
    private val sink: Sink,
) {
    interface Sink {
        fun writeProtocolEnvelope(out: DataOutputStream, envelope: Envelope)

        fun onDisplaysAvailable(
            displays: List<ProtocolV1Session.DisplayOption>,
            selectedId: String,
        )

        fun onVideoConfigurationRequested(
            session: ProtocolV1Session,
            configurationToken: Long,
            codec: Codec,
            width: Int,
            height: Int,
            rotation: Int,
            configEpoch: Long,
            bitrateKbps: Int,
            framesPerSecond: Int,
        )

        fun onVideoConfigurationRejectedBeforeResponse(reason: String)

        fun onVideoConfigurationCommitted(appliesClientVideoPreferences: Boolean)

        fun onDisplayGeometryChanged(
            width: Int,
            height: Int,
            rotation: Int,
        )

        fun onPongReceived(sequence: Long)

        fun onControllerInputAck(
            inputId: Long,
            accepted: Boolean,
            rejectionReason: String,
        )

        fun onHostActionsAvailable(actions: List<ProtocolV1Session.HostAction>)

        fun onHostActionCompleted(
            accepted: Boolean,
            rejectionReason: String,
        )

        fun onClipboardOffered(
            session: ProtocolV1Session,
            connectionGeneration: Long,
            changeId: ByteString,
            originDeviceId: String,
            mimeType: String,
            byteLength: Long,
            sha256: ByteString,
        )

        fun onClipboardContentReceived(
            session: ProtocolV1Session,
            connectionGeneration: Long,
            changeId: ByteString,
            originDeviceId: String,
            mimeType: String,
            content: ByteArray,
            sha256: ByteString,
            pending: Boolean,
        )

        fun onManagedPolicyReceived(status: ManagedPolicyStatus)

        fun onFileOfferReceived(
            out: DataOutputStream,
            session: ProtocolV1Session,
            offer: FileOffer,
        )

        fun onFileAcceptReceived(
            out: DataOutputStream,
            session: ProtocolV1Session,
            response: FileAccept,
        )

        fun onFileProgressReceived(
            out: DataOutputStream,
            session: ProtocolV1Session,
            progress: FileTransferProgress,
        )

        fun onFileCancelReceived(cancellation: FileTransferCancel)

        fun onFileCompleteReceived(result: FileTransferComplete)

        fun onWakeHostRequested(
            session: ProtocolV1Session,
            connectionGeneration: Long,
            request: WakeHostRequestContext,
            correlationId: Long,
        )

        fun onWakeHostCompleted(
            accepted: Boolean,
            rejectionReason: String,
        )

        fun onDisconnected(
            reasonCode: String,
            mayResume: Boolean,
        ): SessionFailure
    }

    sealed class ReceiveResult {
        data object Completed : ReceiveResult()
        data class Disconnected(val failure: SessionFailure) : ReceiveResult()
    }

    data class VideoConfigurationCompletionResult(
        val configurationCommitted: Boolean,
        val appliesClientVideoPreferences: Boolean,
        val rejectionReason: String?,
    )

    fun dispatchReceivedActions(
        out: DataOutputStream,
        session: ProtocolV1Session,
        connectionGeneration: Long,
        actions: List<ProtocolV1Session.Action>,
    ): ReceiveResult {
        for (action in actions) {
            when (action) {
                is ProtocolV1Session.Action.Send -> sink.writeProtocolEnvelope(out, action.envelope)
                is ProtocolV1Session.Action.DisplaysAvailable ->
                    sink.onDisplaysAvailable(action.displays, action.selectedId)
                is ProtocolV1Session.Action.VideoConfigurationRequested ->
                    sink.onVideoConfigurationRequested(
                        session = session,
                        configurationToken = action.configurationToken,
                        codec = action.codec,
                        width = action.width,
                        height = action.height,
                        rotation = action.rotation,
                        configEpoch = action.configEpoch,
                        bitrateKbps = action.bitrateKbps,
                        framesPerSecond = action.framesPerSecond,
                    )
                is ProtocolV1Session.Action.VideoConfigurationCommitted,
                is ProtocolV1Session.Action.VideoConfigurationRejected,
                -> throw IllegalStateException(
                    "Unexpected decoder completion action during protocol receive",
                )
                is ProtocolV1Session.Action.DisplayGeometryChanged ->
                    sink.onDisplayGeometryChanged(action.width, action.height, action.rotation)
                is ProtocolV1Session.Action.PongReceived -> sink.onPongReceived(action.sequence)
                is ProtocolV1Session.Action.ControllerInputAck ->
                    sink.onControllerInputAck(action.inputId, action.accepted, action.rejectionReason)
                is ProtocolV1Session.Action.HostActionsAvailable -> sink.onHostActionsAvailable(action.actions)
                is ProtocolV1Session.Action.HostActionCompleted ->
                    sink.onHostActionCompleted(action.accepted, action.rejectionReason)
                is ProtocolV1Session.Action.ClipboardOffered ->
                    sink.onClipboardOffered(
                        session = session,
                        connectionGeneration = connectionGeneration,
                        changeId = action.changeId,
                        originDeviceId = action.originDeviceId,
                        mimeType = action.mimeType,
                        byteLength = action.byteLength,
                        sha256 = action.sha256,
                    )
                is ProtocolV1Session.Action.ClipboardContentReceived ->
                    sink.onClipboardContentReceived(
                        session = session,
                        connectionGeneration = connectionGeneration,
                        changeId = action.changeId,
                        originDeviceId = action.originDeviceId,
                        mimeType = action.mimeType,
                        content = action.content,
                        sha256 = action.sha256,
                        pending = action.pending,
                    )
                is ProtocolV1Session.Action.ManagedPolicyReceived -> sink.onManagedPolicyReceived(action.status)
                is ProtocolV1Session.Action.FileOfferReceived -> sink.onFileOfferReceived(out, session, action.offer)
                is ProtocolV1Session.Action.FileAcceptReceived -> sink.onFileAcceptReceived(out, session, action.response)
                is ProtocolV1Session.Action.FileProgressReceived ->
                    sink.onFileProgressReceived(out, session, action.progress)
                is ProtocolV1Session.Action.FileCancelReceived -> sink.onFileCancelReceived(action.cancellation)
                is ProtocolV1Session.Action.FileCompleteReceived -> sink.onFileCompleteReceived(action.result)
                is ProtocolV1Session.Action.WakeHost ->
                    sink.onWakeHostRequested(
                        session = session,
                        connectionGeneration = connectionGeneration,
                        request = action.request,
                        correlationId = action.correlationId,
                    )
                is ProtocolV1Session.Action.WakeHostCompleted ->
                    sink.onWakeHostCompleted(action.accepted, action.rejectionReason)
                is ProtocolV1Session.Action.Disconnected ->
                    return ReceiveResult.Disconnected(
                        sink.onDisconnected(action.reasonCode, action.mayResume),
                    )
            }
        }
        return ReceiveResult.Completed
    }

    fun dispatchVideoConfigurationCompletionActions(
        out: DataOutputStream,
        actions: List<ProtocolV1Session.Action>,
    ): VideoConfigurationCompletionResult {
        val rejectedReason = actions
            .filterIsInstance<ProtocolV1Session.Action.VideoConfigurationRejected>()
            .singleOrNull()
            ?.reason
        rejectedReason?.let(sink::onVideoConfigurationRejectedBeforeResponse)

        var configurationCommitted = false
        var appliesClientVideoPreferences = false
        actions.forEach { action ->
            when (action) {
                is ProtocolV1Session.Action.Send -> sink.writeProtocolEnvelope(out, action.envelope)
                is ProtocolV1Session.Action.VideoConfigurationCommitted -> {
                    configurationCommitted = true
                    appliesClientVideoPreferences = action.appliesClientVideoPreferences
                    sink.onVideoConfigurationCommitted(action.appliesClientVideoPreferences)
                }
                is ProtocolV1Session.Action.VideoConfigurationRejected -> Unit
                is ProtocolV1Session.Action.DisplayGeometryChanged ->
                    sink.onDisplayGeometryChanged(action.width, action.height, action.rotation)
                is ProtocolV1Session.Action.VideoConfigurationRequested,
                is ProtocolV1Session.Action.PongReceived,
                is ProtocolV1Session.Action.ControllerInputAck,
                is ProtocolV1Session.Action.Disconnected,
                is ProtocolV1Session.Action.DisplaysAvailable,
                is ProtocolV1Session.Action.HostActionsAvailable,
                is ProtocolV1Session.Action.HostActionCompleted,
                is ProtocolV1Session.Action.ClipboardOffered,
                is ProtocolV1Session.Action.ClipboardContentReceived,
                is ProtocolV1Session.Action.ManagedPolicyReceived,
                is ProtocolV1Session.Action.FileOfferReceived,
                is ProtocolV1Session.Action.FileAcceptReceived,
                is ProtocolV1Session.Action.FileProgressReceived,
                is ProtocolV1Session.Action.FileCancelReceived,
                is ProtocolV1Session.Action.FileCompleteReceived,
                is ProtocolV1Session.Action.WakeHost,
                is ProtocolV1Session.Action.WakeHostCompleted,
                -> throw IllegalStateException(
                    "Unexpected action while completing decoder configuration",
                )
            }
        }
        return VideoConfigurationCompletionResult(
            configurationCommitted = configurationCommitted,
            appliesClientVideoPreferences = appliesClientVideoPreferences,
            rejectionReason = rejectedReason,
        )
    }
}
