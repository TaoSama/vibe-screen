package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.FileChunk
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.FileOffer
import java.util.concurrent.CompletableFuture
import java.util.concurrent.atomic.AtomicBoolean

internal sealed interface StreamOutboundCommand {
    data class Touch(
        val x: Float,
        val y: Float,
        val action: Int,
        val pointerCount: Int,
        val x2: Float,
        val y2: Float,
    ) : StreamOutboundCommand

    data class Keyframe(
        val flags: Int,
    ) : StreamOutboundCommand

    data class Ping(
        val sentAtNs: Long,
    ) : StreamOutboundCommand

    data class LegacyControl(
        val payload: ByteArray,
    ) : StreamOutboundCommand

    class ProtocolBatch(
        val onUnavailable: (() -> Unit)? = null,
        val build: (ProtocolV1Session) -> List<Envelope>,
    ) : StreamOutboundCommand

    class ProtocolActionBatch(
        val build: (ProtocolV1Session) -> List<ProtocolV1Session.Action>,
        val onEmpty: ((ProtocolV1Session) -> Unit)? = null,
    ) : StreamOutboundCommand

    data class ProtocolFileOfferSubmission(
        val session: ProtocolV1Session,
        val connectionGeneration: Long,
        val offer: FileOffer,
        val prepared: FileTransferProductOwner.PreparedOutgoingTransfer,
    ) : StreamOutboundCommand

    data class ProtocolReceive(
        val session: ProtocolV1Session,
        val connectionGeneration: Long,
        val envelope: Envelope,
        val completion: CompletableFuture<Unit>,
    ) : StreamOutboundCommand

    data class ProtocolBulk(
        val session: ProtocolV1Session,
        val connectionGeneration: Long,
        val chunk: FileChunk,
        val completion: CompletableFuture<Unit>,
    ) : StreamOutboundCommand

    data class ProtocolFileOfferDecision(
        val session: ProtocolV1Session,
        val connectionGeneration: Long,
        val offer: FileOffer,
        val acceptedByUser: Boolean,
    ) : StreamOutboundCommand

    data class ProtocolSendBulk(
        val chunk: FileChunk,
    ) : StreamOutboundCommand

    data class ProtocolVideoConfigurationCompletion(
        val pending: StreamVideoConfigurationPendingCommit,
        val decision: StreamVideoConfigurationDecision,
    ) : StreamOutboundCommand

    class ProtocolWakeHostCompletion(
        val session: ProtocolV1Session,
        val connectionGeneration: Long,
        val requestId: ByteString,
        val accepted: Boolean,
        val rejectionReason: String,
        val correlationId: Long,
        val requiresTrackedReservation: Boolean = true,
    ) : StreamOutboundCommand {
        private val claimed = AtomicBoolean(false)

        fun claimForWrite(): Boolean = claimed.compareAndSet(false, true)
    }
}

internal interface StreamVideoConfigurationPendingCommit : StreamVideoConfigurationCommit {
    val session: ProtocolV1Session
    val connectionGeneration: Long
    val configuration: StreamVideoConfiguration
    val configurationToken: Long
}
