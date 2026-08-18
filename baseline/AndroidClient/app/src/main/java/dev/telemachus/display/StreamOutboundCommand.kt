package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.FileChunk
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.Envelope
import java.util.concurrent.CompletableFuture

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
        val build: (ProtocolV1Session) -> List<Envelope>,
    ) : StreamOutboundCommand

    data class ProtocolReceive(
        val envelope: Envelope,
        val completion: CompletableFuture<Unit>,
    ) : StreamOutboundCommand

    data class ProtocolBulk(
        val chunk: FileChunk,
        val completion: CompletableFuture<Unit>,
    ) : StreamOutboundCommand

    data class ProtocolSendBulk(
        val chunk: FileChunk,
    ) : StreamOutboundCommand

    data class ProtocolVideoConfigurationCompletion(
        val pending: StreamVideoConfigurationPendingCommit,
        val decision: StreamVideoConfigurationDecision,
    ) : StreamOutboundCommand

    data class ProtocolWakeHostCompletion(
        val session: ProtocolV1Session,
        val connectionGeneration: Long,
        val requestId: ByteString,
        val accepted: Boolean,
        val rejectionReason: String,
        val correlationId: Long,
    ) : StreamOutboundCommand
}

internal interface StreamVideoConfigurationPendingCommit : StreamVideoConfigurationCommit {
    val session: ProtocolV1Session
    val connectionGeneration: Long
    val configuration: StreamVideoConfiguration
    val configurationToken: Long
}
