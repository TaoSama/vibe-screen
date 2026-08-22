package dev.telemachus.display

import dev.telemachus.display.protocol.ProtocolV1Framing
import dev.telemachus.display.protocol.ProtocolV1Failure
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.MediaPacketHeader
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.DataInputStream
import java.nio.ByteBuffer

class StreamMediaFrameRouterTest {
    @Test
    fun legacyFrameReadsMetadataAndDeliversToSink() {
        var nowNs = 10L
        val delivered = mutableListOf<StreamMediaFrame>()
        val router = router(
            frameSink = { frame ->
                delivered += frame
                true
            },
            nowNs = { nowNs },
        )

        val frame = byteArrayOf(0, 0, 0, 1, 0x26)
        router.receiveLegacyFrame(
            input = DataInputStream(ByteArrayInputStream(legacyPayload(frame, flags = 1))),
            hasMetadata = true,
            streamCodecIsHevc = true,
            connectionEpoch = 3,
            acceptsEpoch = { it == 3L },
            currentEpoch = { 3L },
        )

        assertEquals(1, delivered.size)
        assertTrue(delivered.single().keyframe)
        assertEquals(3L, delivered.single().connectionEpoch)
        assertEquals(0L, delivered.single().configEpoch)
        assertEquals(frame.size, delivered.single().size)
    }

    @Test
    fun legacyFrameDropsStaleEpoch() {
        val telemetry = mutableListOf<Map<String, Any?>>()
        val delivered = mutableListOf<StreamMediaFrame>()
        val router = router(
            frameSink = { frame ->
                delivered += frame
                true
            },
            emitTelemetry = { event, fields -> if (event == "frame_dropped") telemetry += fields },
        )

        router.receiveLegacyFrame(
            input = DataInputStream(ByteArrayInputStream(legacyPayload(byteArrayOf(0, 0, 0, 1, 0x26)))),
            hasMetadata = false,
            streamCodecIsHevc = true,
            connectionEpoch = 2,
            acceptsEpoch = { false },
            currentEpoch = { 5L },
        )

        assertTrue(delivered.isEmpty())
        assertEquals("stale_session_epoch", telemetry.single()["reason"])
        assertEquals(2L, telemetry.single()["frame_epoch"])
        assertEquals(5L, telemetry.single()["current_epoch"])
    }

    @Test
    fun protocolFrameDropsNonAcceptedDispositionAndReportsConfigEpoch() {
        val telemetry = mutableListOf<Map<String, Any?>>()
        val delivered = mutableListOf<StreamMediaFrame>()
        val router = router(
            frameSink = { frame ->
                delivered += frame
                true
            },
            emitTelemetry = { event, fields -> if (event == "frame_dropped") telemetry += fields },
        )

        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 9, keyframe = true),
            connectionEpoch = 4,
            validateMedia = { ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION },
        )

        assertTrue(delivered.isEmpty())
        assertEquals("drop_pending_configuration", telemetry.single()["reason"])
        assertEquals(9L, telemetry.single()["config_epoch"])
        assertEquals(4L, telemetry.single()["session_epoch"])
    }

    @Test
    fun protocolFrameDeliversAcceptedMediaAndEmitsStatsAfterInterval() {
        var nowMs = 0L
        val stats = mutableListOf<Pair<Double, Double>>()
        val delivered = mutableListOf<StreamMediaFrame>()
        val router = router(
            frameSink = { frame ->
                delivered += frame
                true
            },
            onStats = { fps, mbps -> stats += fps to mbps },
            nowMs = { nowMs },
        )
        nowMs = 1_000L

        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 7, keyframe = true, bytes = byteArrayOf(1, 2, 3, 4)),
            connectionEpoch = 6,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )

        assertEquals(1, delivered.size)
        assertEquals(7L, delivered.single().configEpoch)
        assertTrue(delivered.single().keyframe)
        assertEquals(1, stats.size)
        assertEquals(1.0, stats.single().first, 0.001)
        assertEquals(0.000032, stats.single().second, 0.000001)
    }

    @Test
    fun protocolInvalidPayloadFailsClosedAsMediaPayloadFailure() {
        val router = router()

        val failure = assertThrows(ProtocolV1Failure::class.java) {
            router.receiveProtocolFrame(
                payload = byteArrayOf(0),
                connectionEpoch = 1,
                validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
            )
        }

        assertEquals("invalid_media_payload", failure.reason)
        assertEquals(ProtocolV1Failure.Source.MEDIA_PAYLOAD, failure.source)
        assertFalse(failure.retryable)
    }

    @Test
    fun staleDeltaAfterKeyframeRequestsFreshKeyframe() {
        var nowNs = 1L
        val keyframeRequests = mutableListOf<String>()
        val router = router(
            requestKeyframe = { keyframeRequests += it },
            nowNs = { nowNs },
        )

        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 1, keyframe = true),
            connectionEpoch = 1,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )
        nowNs = 2_000_000_001L
        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 1, keyframe = false),
            connectionEpoch = 1,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )

        assertEquals(listOf("last keyframe 2000ms ago"), keyframeRequests)
    }

    private fun router(
        frameSink: (StreamMediaFrame) -> Boolean = { false },
        requestKeyframe: (String) -> Unit = {},
        onStats: (Double, Double) -> Unit = { _, _ -> },
        emitTelemetry: (String, Map<String, Any?>) -> Unit = { _, _ -> },
        diagLog: (String) -> Unit = {},
        nowNs: () -> Long = { 0L },
        nowMs: () -> Long = { 0L },
    ) = StreamMediaFrameRouter(
        frameSink = frameSink,
        requestKeyframe = requestKeyframe,
        onStats = onStats,
        emitTelemetry = emitTelemetry,
        diagLog = diagLog,
        nowNs = nowNs,
        nowMs = nowMs,
    )

    private fun legacyPayload(
        frame: ByteArray,
        flags: Int = 0,
    ): ByteArray {
        val metadataBytes = if (flags == 0) 0 else 9
        val payload = ByteArray(Int.SIZE_BYTES + metadataBytes + frame.size)
        ByteBuffer.wrap(payload).putInt(frame.size)
        if (metadataBytes > 0) {
            payload[4] = flags.toByte()
        }
        frame.copyInto(payload, Int.SIZE_BYTES + metadataBytes)
        return payload
    }

    private fun protocolPayload(
        configEpoch: Long,
        keyframe: Boolean,
        bytes: ByteArray = byteArrayOf(0, 0, 0, 1, 0x26),
    ): ByteArray =
        ProtocolV1Framing.encodeVideo(
            MediaPacketHeader
                .newBuilder()
                .setStreamId(42)
                .setSessionEpoch(7)
                .setConfigEpoch(configEpoch)
                .setFrameId(1)
                .setFragmentIndex(0)
                .setFragmentCount(1)
                .setKeyframe(keyframe)
                .setCodec(Codec.CODEC_HEVC)
                .setPayloadLength(bytes.size)
                .build(),
            bytes,
        )
}
