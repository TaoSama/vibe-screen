package dev.telemachus.display.internet

import com.google.protobuf.ByteString
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.SessionAccepted
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolV1ProductCodecTest {
    private val codec = ProtobufProtocolV1ProductCodec("device-1", "Android", setOf(ProductVideoCodec.H264, ProductVideoCodec.HEVC)) { 99 }
    private val sessionId = "session-1".toByteArray()

    @Test
    fun encodesRealProtocolV1HelloTouchKeyframeAndPingEnvelopes() {
        val hello = Envelope.parseFrom(codec.encodeClientHello(1, sessionId, 7))
        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, hello.payloadCase)
        assertEquals("device-1", hello.clientHello.deviceId)
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_END_TO_END_ENCRYPTION))
        assertEquals(listOf(Codec.CODEC_H264, Codec.CODEC_HEVC), hello.clientHello.codecsList.sortedBy { it.number })

        val touch =
            Envelope.parseFrom(
                codec.encodeTouch(
                    2,
                    sessionId,
                    7,
                    ProductTouchEvent(3, 0, ProductInputPhase.BEGAN, 0.25, 0.75, 0.5),
                ),
            )
        assertEquals(Envelope.PayloadCase.TOUCH_EVENT, touch.payloadCase)
        assertEquals(0.25, touch.touchEvent.position.x, 0.0)

        val keyframe = Envelope.parseFrom(codec.encodeKeyframeRequest(3, sessionId, 7, 5, "decoder_reset"))
        assertEquals(5, keyframe.requestKeyframe.streamId)
        val ping = Envelope.parseFrom(codec.encodePing(4, sessionId, 7, 9))
        assertEquals(9, ping.ping.sequence)
        val pong = Envelope.parseFrom(codec.encodePong(5, 4, sessionId, 7, 9))
        assertEquals(4, pong.correlationId)
        assertEquals(9, pong.pong.sequence)
    }

    @Test
    fun decodesScopedHostAndSessionControl() {
        val hostHello =
            baseEnvelope(1)
                .setHostHello(
                    HostHello
                        .newBuilder()
                        .setSelectedProtocol(1)
                        .setHostId("host-1")
                        .setHostName("Mac")
                        .addAllCapabilities(ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES),
                ).build()
        val decodedHost = codec.decodeControl(hostHello.toByteArray()).message as ProductControlMessage.HostHello
        assertEquals("host-1", decodedHost.hostId)

        val accepted =
            baseEnvelope(2)
                .setSessionAccepted(
                    SessionAccepted
                        .newBuilder()
                        .setSessionId(ByteString.copyFrom(sessionId))
                        .setSessionEpoch(7)
                        .setHeartbeatIntervalMs(1_000)
                        .addAllNegotiatedCapabilities(ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES),
                ).build()
        val decodedAccepted = codec.decodeControl(accepted.toByteArray()).message as ProductControlMessage.SessionAccepted
        assertArrayEquals(sessionId, decodedAccepted.sessionId)
        assertEquals(7, decodedAccepted.sessionEpoch)
        assertEquals(1_000, decodedAccepted.heartbeatIntervalMillis)
    }

    @Test
    fun mediaFramingMatchesMacVarintFixtureAndRejectsMalformedPrefixes() {
        val fixture =
            "130805100918032007300138d209400148025003616263"
                .chunked(2)
                .map { it.toInt(16).toByte() }
                .toByteArray()
        val decoded = codec.decodeMediaFragment(fixture)
        assertEquals(5, decoded.streamId)
        assertEquals(9, decoded.sessionEpoch)
        assertEquals(7, decoded.frameId)
        assertEquals(ProductVideoCodec.HEVC, decoded.codec)
        assertArrayEquals("abc".toByteArray(), decoded.payload)

        val header =
            MediaPacketHeader
                .newBuilder()
                .setStreamId(5)
                .setSessionEpoch(9)
                .setConfigEpoch(3)
                .setFrameId(7)
                .setFragmentCount(1)
                .setCaptureTimestampNs(1234)
                .setKeyframe(true)
                .setCodec(Codec.CODEC_HEVC)
                .setPayloadLength(3)
                .build()
        assertArrayEquals(fixture, ProtobufProtocolV1ProductCodec.encodeMediaFragment(header, "abc".toByteArray()))
        assertThrows(IllegalArgumentException::class.java) {
            codec.decodeMediaFragment(byteArrayOf(0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 1))
        }
    }

    private fun baseEnvelope(messageId: Long): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(messageId)
            .setSessionId(ByteString.copyFrom(sessionId))
            .setSessionEpoch(7)
}
