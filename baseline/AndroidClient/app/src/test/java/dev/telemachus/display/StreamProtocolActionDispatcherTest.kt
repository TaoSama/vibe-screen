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
import dev.vibescreen.protocol.v1.TransportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.io.File

class StreamProtocolActionDispatcherTest {
    @Test
    fun receiveDispatchRoutesEachProtocolActionCategoryThroughTheSink() {
        val sink = RecordingProtocolActionSink()
        val dispatcher = StreamProtocolActionDispatcher(sink)
        val out = DataOutputStream(ByteArrayOutputStream())
        val session = session()
        val transferId = ByteString.copyFromUtf8("transfer")

        val result = dispatcher.dispatchReceivedActions(
            out = out,
            session = session,
            connectionGeneration = 42,
            actions = listOf(
                ProtocolV1Session.Action.Send(Envelope.getDefaultInstance()),
                ProtocolV1Session.Action.DisplaysAvailable(
                    displays = listOf(ProtocolV1Session.DisplayOption("main", "Main", 1920, 1080, true, false)),
                    selectedId = "main",
                ),
                ProtocolV1Session.Action.DisplaySelectionPending("main", "virtual"),
                ProtocolV1Session.Action.DisplaySelectionConfirmed("virtual"),
                ProtocolV1Session.Action.DisplaySelectionRejected("main", "missing", "not_found"),
                ProtocolV1Session.Action.VideoConfigurationRequested(
                    width = 1920,
                    height = 1080,
                    rotation = 0,
                    codec = Codec.CODEC_HEVC,
                    configEpoch = 7,
                    sessionEpoch = 5,
                    configurationToken = 11,
                    bitrateKbps = 12_000,
                    framesPerSecond = 60,
                ),
                ProtocolV1Session.Action.DisplayGeometryChanged(1920, 1080, 0),
                ProtocolV1Session.Action.PongReceived(9),
                ProtocolV1Session.Action.ControllerInputAck(10, true, ""),
                ProtocolV1Session.Action.HostActionsAvailable(
                    listOf(ProtocolV1Session.HostAction("move-window", "Move Window", false)),
                ),
                ProtocolV1Session.Action.HostActionCompleted(ByteString.copyFromUtf8("invocation"), true, ""),
                ProtocolV1Session.Action.ClipboardOffered(
                    ByteString.copyFromUtf8("clipboard-offer-id"),
                    "host",
                    "text/plain",
                    4,
                    ByteString.copyFrom(ByteArray(32)),
                ),
                ProtocolV1Session.Action.ClipboardContentReceived(
                    ByteString.copyFromUtf8("clipboard-data-id"),
                    "host",
                    "text/plain",
                    byteArrayOf(1, 2),
                    ByteString.copyFrom(ByteArray(32)),
                    pending = false,
                ),
                ProtocolV1Session.Action.ManagedPolicyReceived(ManagedPolicyStatus.getDefaultInstance()),
                ProtocolV1Session.Action.FileOfferReceived(FileOffer.newBuilder().setTransferId(transferId).build()),
                ProtocolV1Session.Action.FileAcceptReceived(FileAccept.newBuilder().setTransferId(transferId).build()),
                ProtocolV1Session.Action.FileProgressReceived(FileTransferProgress.newBuilder().setTransferId(transferId).build()),
                ProtocolV1Session.Action.FileCancelReceived(FileTransferCancel.newBuilder().setTransferId(transferId).build()),
                ProtocolV1Session.Action.FileCompleteReceived(FileTransferComplete.newBuilder().setTransferId(transferId).build()),
                ProtocolV1Session.Action.WakeHost(
                    WakeHostRequestContext(
                        requestId = ByteString.copyFromUtf8("wake"),
                        targetMacAddress = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4, 5, 6)),
                    ),
                    correlationId = 13,
                ),
                ProtocolV1Session.Action.WakeHostCompleted(ByteString.copyFromUtf8("wake"), true, ""),
            ),
        )

        assertEquals(StreamProtocolActionDispatcher.ReceiveResult.Completed, result)
        assertEquals(
            listOf(
                "send:PAYLOAD_NOT_SET",
                "displays:main:1",
                "display-pending:main:virtual",
                "display-confirmed:virtual",
                "display-rejected:main:missing:not_found",
                "video-request:11:CODEC_HEVC:1920x1080:7",
                "geometry:1920x1080:0",
                "pong:9",
                "controller-ack:10:true:",
                "host-actions:move-window",
                "host-action-result:true:",
                "clipboard-offered:clipboard-offer-id:42",
                "clipboard-content:clipboard-data-id:false:42",
                "managed-policy:false",
                "file-offer:transfer:42",
                "file-accept:transfer:false",
                "file-progress:transfer",
                "file-cancel:transfer",
                "file-complete:transfer:false",
                "wake-request:wake:13:42",
                "wake-result:true:",
            ),
            sink.events,
        )
    }

    @Test
    fun receiveDispatchReturnsDisconnectedResultAndDoesNotHandleLaterActions() {
        val sink = RecordingProtocolActionSink()
        val dispatcher = StreamProtocolActionDispatcher(sink)

        val result = dispatcher.dispatchReceivedActions(
            out = DataOutputStream(ByteArrayOutputStream()),
            session = session(),
            connectionGeneration = 7,
            actions = listOf(
                ProtocolV1Session.Action.Disconnected(reasonCode = "host_shutdown", mayResume = false),
                ProtocolV1Session.Action.Send(Envelope.getDefaultInstance()),
            ),
        )

        assertTrue(result is StreamProtocolActionDispatcher.ReceiveResult.Disconnected)
        assertEquals(
            SessionFailureKind.SERVER_SHUTDOWN,
            (result as StreamProtocolActionDispatcher.ReceiveResult.Disconnected).failure.kind,
        )
        assertEquals(listOf("disconnected:host_shutdown:false"), sink.events)
    }

    @Test
    fun receiveDispatchRejectsDecoderCompletionActions() {
        val dispatcher = StreamProtocolActionDispatcher(RecordingProtocolActionSink())
        val out = DataOutputStream(ByteArrayOutputStream())
        val session = session()

        assertThrows(IllegalStateException::class.java) {
            dispatcher.dispatchReceivedActions(
                out = out,
                session = session,
                connectionGeneration = 1,
                actions = listOf(ProtocolV1Session.Action.VideoConfigurationCommitted(3, true)),
            )
        }
        assertThrows(IllegalStateException::class.java) {
            dispatcher.dispatchReceivedActions(
                out = out,
                session = session,
                connectionGeneration = 1,
                actions = listOf(ProtocolV1Session.Action.VideoConfigurationRejected(3, "decoder_failed")),
            )
        }
    }

    @Test
    fun videoCompletionDispatchOnlyAdmitsDecoderCompletionActions() {
        val sink = RecordingProtocolActionSink()
        val dispatcher = StreamProtocolActionDispatcher(sink)
        val out = DataOutputStream(ByteArrayOutputStream())

        val result = dispatcher.dispatchVideoConfigurationCompletionActions(
            out = out,
            actions = listOf(
                ProtocolV1Session.Action.VideoConfigurationRejected(4, "decoder_failed"),
                ProtocolV1Session.Action.Send(Envelope.getDefaultInstance()),
                ProtocolV1Session.Action.VideoConfigurationCommitted(4, appliesClientVideoPreferences = true),
                ProtocolV1Session.Action.DisplaysAvailable(
                    displays = listOf(ProtocolV1Session.DisplayOption("virtual", "Virtual", 2000, 1200, false, true)),
                    selectedId = "virtual",
                ),
                ProtocolV1Session.Action.DisplaySelectionConfirmed("virtual"),
                ProtocolV1Session.Action.DisplaySelectionRejected("main", "missing", "not_found"),
                ProtocolV1Session.Action.DisplayGeometryChanged(2000, 1200, 90),
            ),
        )

        assertTrue(result.configurationCommitted)
        assertTrue(result.appliesClientVideoPreferences)
        assertEquals("decoder_failed", result.rejectionReason)
        assertEquals(
            listOf(
                "video-rejected-before-response:decoder_failed",
                "send:PAYLOAD_NOT_SET",
                "video-committed:true",
                "displays:virtual:1",
                "display-confirmed:virtual",
                "display-rejected:main:missing:not_found",
                "geometry:2000x1200:90",
            ),
            sink.events,
        )

        assertThrows(IllegalStateException::class.java) {
            dispatcher.dispatchVideoConfigurationCompletionActions(
                out = out,
                actions = listOf(ProtocolV1Session.Action.PongReceived(1)),
            )
        }
    }

    @Test
    fun dispatcherOwnsActionRoutingWithoutAndroidTransportOrDecoderOwnership() {
        val dispatcher = source(PRODUCTION_PROTOCOL_ACTION_DISPATCHER)
        val streamClient = source(PRODUCTION_STREAM_CLIENT)

        assertTrue(streamClient.contains("private val protocolActionDispatcher ="))
        assertTrue(streamClient.contains("protocolActionDispatcher.dispatchReceivedActions"))
        assertTrue(streamClient.contains("protocolActionDispatcher.dispatchVideoConfigurationCompletionActions"))
        assertFalse(streamClient.contains("is ProtocolV1Session.Action.HostActionsAvailable ->"))
        assertFalse(streamClient.contains("is ProtocolV1Session.Action.FileOfferReceived ->"))
        assertFalse(streamClient.contains("is ProtocolV1Session.Action.WakeHostCompleted ->"))

        FORBIDDEN_DISPATCHER_REFERENCES.forEach { reference ->
            assertFalse("StreamProtocolActionDispatcher must not depend on " + reference, dispatcher.contains(reference))
        }
    }

    private fun session(): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "device",
            deviceName = "Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_H264),
        )

    private fun source(relativePath: String): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            listOf(relativePath, "baseline/AndroidClient/" + relativePath)
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error(relativePath + " not found from " + System.getProperty("user.dir"))
    }

    private class RecordingProtocolActionSink : StreamProtocolActionDispatcher.Sink {
        val events = mutableListOf<String>()

        override fun writeProtocolEnvelope(out: DataOutputStream, envelope: Envelope) {
            events += "send:" + envelope.payloadCase
        }

        override fun onDisplaysAvailable(displays: List<ProtocolV1Session.DisplayOption>, selectedId: String) {
            events += "displays:" + selectedId + ":" + displays.size
        }

        override fun onDisplaySelectionPending(selectedId: String, pendingId: String) {
            events += "display-pending:" + selectedId + ":" + pendingId
        }

        override fun onDisplaySelectionConfirmed(selectedId: String) {
            events += "display-confirmed:" + selectedId
        }

        override fun onDisplaySelectionRejected(selectedId: String, rejectedId: String, reason: String) {
            events += "display-rejected:" + selectedId + ":" + rejectedId + ":" + reason
        }

        override fun onVideoConfigurationRequested(
            session: ProtocolV1Session,
            configurationToken: Long,
            codec: Codec,
            width: Int,
            height: Int,
            rotation: Int,
            configEpoch: Long,
            bitrateKbps: Int,
            framesPerSecond: Int,
        ) {
            events += "video-request:" + configurationToken + ":" + codec + ":" + width + "x" + height + ":" + configEpoch
        }

        override fun onVideoConfigurationRejectedBeforeResponse(reason: String) {
            events += "video-rejected-before-response:" + reason
        }

        override fun onVideoConfigurationCommitted(appliesClientVideoPreferences: Boolean) {
            events += "video-committed:" + appliesClientVideoPreferences
        }

        override fun onDisplayGeometryChanged(width: Int, height: Int, rotation: Int) {
            events += "geometry:" + width + "x" + height + ":" + rotation
        }

        override fun onPongReceived(sequence: Long) {
            events += "pong:" + sequence
        }

        override fun onControllerInputAck(inputId: Long, accepted: Boolean, rejectionReason: String) {
            events += "controller-ack:" + inputId + ":" + accepted + ":" + rejectionReason
        }

        override fun onHostActionsAvailable(actions: List<ProtocolV1Session.HostAction>) {
            events += "host-actions:" + actions.joinToString { it.id }
        }

        override fun onHostActionCompleted(accepted: Boolean, rejectionReason: String) {
            events += "host-action-result:" + accepted + ":" + rejectionReason
        }

        override fun onClipboardOffered(
            session: ProtocolV1Session,
            connectionGeneration: Long,
            changeId: ByteString,
            originDeviceId: String,
            mimeType: String,
            byteLength: Long,
            sha256: ByteString,
        ) {
            events += "clipboard-offered:" + changeId.toStringUtf8() + ":" + connectionGeneration
        }

        override fun onClipboardContentReceived(
            session: ProtocolV1Session,
            connectionGeneration: Long,
            changeId: ByteString,
            originDeviceId: String,
            mimeType: String,
            content: ByteArray,
            sha256: ByteString,
            pending: Boolean,
        ) {
            events += "clipboard-content:" + changeId.toStringUtf8() + ":" + pending + ":" + connectionGeneration
        }

        override fun onManagedPolicyReceived(status: ManagedPolicyStatus) {
            events += "managed-policy:" + status.managed
        }

        override fun onFileOfferReceived(
            out: DataOutputStream,
            session: ProtocolV1Session,
            connectionGeneration: Long,
            offer: FileOffer,
        ) {
            events += "file-offer:" + offer.transferId.toStringUtf8() + ":" + connectionGeneration
        }

        override fun onFileAcceptReceived(out: DataOutputStream, session: ProtocolV1Session, response: FileAccept) {
            events += "file-accept:" + response.transferId.toStringUtf8() + ":" + response.accepted
        }

        override fun onFileProgressReceived(out: DataOutputStream, session: ProtocolV1Session, progress: FileTransferProgress) {
            events += "file-progress:" + progress.transferId.toStringUtf8()
        }

        override fun onFileCancelReceived(cancellation: FileTransferCancel) {
            events += "file-cancel:" + cancellation.transferId.toStringUtf8()
        }

        override fun onFileCompleteReceived(
            out: DataOutputStream,
            session: ProtocolV1Session,
            result: FileTransferComplete,
        ) {
            events += "file-complete:" + result.transferId.toStringUtf8() + ":" + result.accepted
        }

        override fun onWakeHostRequested(
            session: ProtocolV1Session,
            connectionGeneration: Long,
            request: WakeHostRequestContext,
            correlationId: Long,
        ) {
            events += "wake-request:" + request.requestId.toStringUtf8() + ":" + correlationId + ":" + connectionGeneration
        }

        override fun onWakeHostCompleted(accepted: Boolean, rejectionReason: String) {
            events += "wake-result:" + accepted + ":" + rejectionReason
        }

        override fun onDisconnected(reasonCode: String, mayResume: Boolean): SessionFailure {
            events += "disconnected:" + reasonCode + ":" + mayResume
            return if (reasonCode == "host_shutdown") {
                SessionFailure.serverShutdown()
            } else {
                SessionFailure.transport(reasonCode)
            }
        }
    }

    private companion object {
        const val PRODUCTION_STREAM_CLIENT = "app/src/main/java/dev/telemachus/display/StreamClient.kt"
        const val PRODUCTION_PROTOCOL_ACTION_DISPATCHER =
            "app/src/main/java/dev/telemachus/display/StreamProtocolActionDispatcher.kt"

        val FORBIDDEN_DISPATCHER_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
                "StreamTransport",
                "StreamTransportOwner",
                "SocketStreamTransportConnection",
                "VideoDecoder",
                "MediaCodec",
                "java.net.Socket",
            )
    }
}
