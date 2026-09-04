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
        val telemetry = mutableListOf<Pair<String, Map<String, Any?>>>()
        val delivered = mutableListOf<StreamMediaFrame>()
        val router = router(
            frameSink = { frame ->
                delivered += frame
                true
            },
            onStats = { fps, mbps -> stats += fps to mbps },
            emitTelemetry = { event, fields -> telemetry += event to fields },
            decoderTelemetry = {
                DecoderTelemetrySnapshot(
                    droppedFrames = 3L,
                    decoderLatencyAvgMs = 4.5,
                    decoderLatencyMaxMs = 8.25,
                )
            },
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

        val streamStats = telemetry.single { it.first == "stream_stats" }.second
        assertEquals(6L, streamStats["session_epoch"])
        assertEquals(1.0, streamStats["fps"] as Double, 0.001)
        assertEquals(0.000032, streamStats["mbps"] as Double, 0.000001)
        assertEquals(3L, streamStats["dropped_frames"])
        assertEquals(4.5, streamStats["decoder_latency_avg_ms"] as Double, 0.001)
        assertEquals(8.25, streamStats["decoder_latency_max_ms"] as Double, 0.001)
    }

    @Test
    fun streamStatsRemainFailClosedWhenDecoderTelemetryIsUnavailable() {
        var nowMs = 0L
        val telemetry = mutableListOf<Pair<String, Map<String, Any?>>>()
        val router = router(
            emitTelemetry = { event, fields -> telemetry += event to fields },
            nowMs = { nowMs },
        )
        nowMs = 1_000L

        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 7, keyframe = true),
            connectionEpoch = 6,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )

        val streamStats = telemetry.single { it.first == "stream_stats" }.second
        assertEquals(0L, streamStats["dropped_frames"])
        assertTrue(streamStats.containsKey("decoder_latency_avg_ms"))
        assertTrue(streamStats.containsKey("decoder_latency_max_ms"))
        assertEquals(null, streamStats["decoder_latency_avg_ms"])
        assertEquals(null, streamStats["decoder_latency_max_ms"])
    }

    @Test
    fun streamStatsPollDecoderTelemetryOncePerStatsInterval() {
        var nowMs = 0L
        var decoderPolls = 0
        val telemetry = mutableListOf<Pair<String, Map<String, Any?>>>()
        val router = router(
            emitTelemetry = { event, fields -> telemetry += event to fields },
            decoderTelemetry = {
                decoderPolls++
                DecoderTelemetrySnapshot(decoderPolls.toLong(), decoderPolls.toDouble(), decoderPolls.toDouble() + 10.0)
            },
            nowMs = { nowMs },
        )

        nowMs = 999L
        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 7, keyframe = true),
            connectionEpoch = 6,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )
        assertEquals(0, decoderPolls)

        nowMs = 1_000L
        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 7, keyframe = false),
            connectionEpoch = 6,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )

        val streamStats = telemetry.single { it.first == "stream_stats" }.second
        assertEquals(1, decoderPolls)
        assertEquals(1L, streamStats["dropped_frames"])
        assertEquals(1.0, streamStats["decoder_latency_avg_ms"] as Double, 0.001)
        assertEquals(11.0, streamStats["decoder_latency_max_ms"] as Double, 0.001)
    }

    @Test
    fun streamStatsConsumesDecoderTelemetryOnceThenAllowsNextPeriodToAccumulate() {
        var nowMs = 0L
        val accumulator = DecoderTelemetryAccumulator()
        val telemetry = mutableListOf<Pair<String, Map<String, Any?>>>()
        val router = router(
            emitTelemetry = { event, fields -> telemetry += event to fields },
            decoderTelemetry = accumulator::consume,
            nowMs = { nowMs },
        )

        accumulator.recordDecoderLatency(5_000_000L)
        accumulator.recordDroppedFrames(2L)
        accumulator.peek()
        nowMs = 1_000L
        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 7, keyframe = true),
            connectionEpoch = 6,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )

        accumulator.recordDecoderLatency(7_000_000L)
        accumulator.recordDecoderLatency(9_000_000L)
        accumulator.recordDroppedFrames()
        nowMs = 2_000L
        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 7, keyframe = false),
            connectionEpoch = 6,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )

        val stats = telemetry.filter { it.first == "stream_stats" }.map { it.second }
        assertEquals(2, stats.size)
        assertEquals(2L, stats[0]["dropped_frames"])
        assertEquals(5.0, stats[0]["decoder_latency_avg_ms"] as Double, 0.001)
        assertEquals(5.0, stats[0]["decoder_latency_max_ms"] as Double, 0.001)
        assertEquals(1L, stats[1]["dropped_frames"])
        assertEquals(8.0, stats[1]["decoder_latency_avg_ms"] as Double, 0.001)
        assertEquals(9.0, stats[1]["decoder_latency_max_ms"] as Double, 0.001)
    }

    @Test
    fun firstFrameTelemetryIsEmittedOncePerSessionEpoch() {
        val telemetry = mutableListOf<Pair<String, Map<String, Any?>>>()
        val delivered = mutableListOf<StreamMediaFrame>()
        val router = router(
            frameSink = { frame ->
                delivered += frame
                true
            },
            emitTelemetry = { event, fields -> telemetry += event to fields },
        )

        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 7, keyframe = true),
            connectionEpoch = 6,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )
        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 7, keyframe = false),
            connectionEpoch = 6,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )
        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 8, keyframe = true),
            connectionEpoch = 7,
            validateMedia = { ProtocolV1Session.MediaDisposition.ACCEPT },
        )

        val firstFrameEvents = telemetry.filter { it.first == "first_frame_received" }
        assertEquals(3, delivered.size)
        assertEquals(2, firstFrameEvents.size)
        assertEquals(listOf(6L, 7L), firstFrameEvents.map { it.second["session_epoch"] })
        assertEquals(listOf(7L, 8L), firstFrameEvents.map { it.second["config_epoch"] })
        assertTrue(firstFrameEvents.all { it.second["metadata"] == true })
    }

    @Test
    fun legacyFrameDoesNotEmitFirstFrameTelemetry() {
        val telemetry = mutableListOf<Pair<String, Map<String, Any?>>>()
        val delivered = mutableListOf<StreamMediaFrame>()
        val router = router(
            frameSink = { frame ->
                delivered += frame
                true
            },
            emitTelemetry = { event, fields -> telemetry += event to fields },
        )

        router.receiveLegacyFrame(
            input = DataInputStream(ByteArrayInputStream(legacyPayload(byteArrayOf(0, 0, 0, 1, 0x26)))),
            hasMetadata = false,
            streamCodecIsHevc = true,
            connectionEpoch = 3,
            acceptsEpoch = { it == 3L },
            currentEpoch = { 3L },
        )

        assertEquals(1, delivered.size)
        assertTrue(telemetry.none { it.first == "first_frame_received" })
    }

    @Test
    fun droppedProtocolFrameDoesNotEmitFirstFrameTelemetry() {
        val telemetry = mutableListOf<Pair<String, Map<String, Any?>>>()
        val router = router(
            emitTelemetry = { event, fields -> telemetry += event to fields },
        )

        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 9, keyframe = true),
            connectionEpoch = 4,
            validateMedia = { ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION },
        )

        assertTrue(telemetry.none { it.first == "first_frame_received" })
        assertEquals("frame_dropped", telemetry.single().first)
    }

    @Test
    fun protocolFrameDropsStaleLocalEpochBeforeValidation() {
        val telemetry = mutableListOf<Pair<String, Map<String, Any?>>>()
        var validateMediaCalled = false
        val router = router(
            emitTelemetry = { event, fields -> telemetry += event to fields },
        )

        router.receiveProtocolFrame(
            payload = protocolPayload(configEpoch = 9, keyframe = true),
            connectionEpoch = 4,
            acceptsEpoch = { false },
            currentEpoch = { 5L },
            validateMedia = {
                validateMediaCalled = true
                ProtocolV1Session.MediaDisposition.ACCEPT
            },
        )

        assertFalse(validateMediaCalled)
        assertTrue(telemetry.none { it.first == "first_frame_received" })
        assertEquals("frame_dropped", telemetry.single().first)
        assertEquals("stale_session_epoch", telemetry.single().second["reason"])
        assertEquals(4L, telemetry.single().second["frame_epoch"])
        assertEquals(5L, telemetry.single().second["current_epoch"])
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
        decoderTelemetry: () -> DecoderTelemetrySnapshot = { DecoderTelemetrySnapshot.empty },
        nowNs: () -> Long = { 0L },
        nowMs: () -> Long = { 0L },
    ) = StreamMediaFrameRouter(
        frameSink = frameSink,
        requestKeyframe = requestKeyframe,
        onStats = onStats,
        emitTelemetry = emitTelemetry,
        diagLog = diagLog,
        decoderTelemetry = decoderTelemetry,
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
