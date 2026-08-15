package dev.telemachus.display.internet

import com.google.protobuf.ByteString
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.ResourceLimits
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
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_MEDIA_RECORD_FRAGMENTATION))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_STYLUS))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_TOUCH))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_CONTROLLER))
        assertTrue(!hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_STYLUS))
        assertTrue(!hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_TOUCH))
        assertTrue(!hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_CONTROLLER))
        assertTrue(hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_MEDIA_RECORD_FRAGMENTATION))
        assertEquals(
            InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES,
            hello.clientHello.resourceLimits.maximumEncryptedMediaRecordBytes,
        )
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

        val stylus =
            Envelope.parseFrom(
                codec.encodeStylus(
                    3,
                    sessionId,
                    7,
                    5,
                    ProductStylusEvent(4, 7, ProductInputPhase.CHANGED, 0.2, 0.8, 0.6, 30.0, -40.0),
                ),
            )
        assertEquals(Envelope.PayloadCase.STYLUS_EVENT, stylus.payloadCase)
        assertEquals(5L, stylus.stylusEvent.target.streamId)
        assertEquals(-40.0, stylus.stylusEvent.tiltYDegrees, 0.0)

        val keyframe = Envelope.parseFrom(codec.encodeKeyframeRequest(3, sessionId, 7, 5, "decoder_reset"))
        assertEquals(5, keyframe.requestKeyframe.streamId)
        val ping = Envelope.parseFrom(codec.encodePing(4, sessionId, 7, 9))
        assertEquals(9, ping.ping.sequence)
        val pong = Envelope.parseFrom(codec.encodePong(5, 4, sessionId, 7, 9))
        assertEquals(4, pong.correlationId)
        assertEquals(9, pong.pong.sequence)
    }

    @Test
    fun rejectsInvalidStylusVectorsAndTerminalPressure() {
        assertThrows(IllegalArgumentException::class.java) {
            ProductStylusEvent(1, 0, ProductInputPhase.ENDED, 0.5, 0.5, 0.1, 0.0, 0.0)
        }
        assertThrows(IllegalArgumentException::class.java) {
            ProductStylusEvent(1, 0, ProductInputPhase.CHANGED, 0.5, 0.5, 0.1, 90.0, 90.0)
        }
        assertThrows(IllegalArgumentException::class.java) {
            ProductStylusEvent(1, 0, ProductInputPhase.CHANGED, 0.5, 0.5, Double.NaN, 0.0, 0.0)
        }
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
                        .addAllCapabilities(ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES)
                        .setResourceLimits(mediaRecordLimits()),
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
                        .addAllNegotiatedCapabilities(ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES)
                        .setNegotiatedResourceLimits(mediaRecordLimits()),
                ).build()
        val decodedAccepted = codec.decodeControl(accepted.toByteArray()).message as ProductControlMessage.SessionAccepted
        assertArrayEquals(sessionId, decodedAccepted.sessionId)
        assertEquals(7, decodedAccepted.sessionEpoch)
        assertEquals(1_000, decodedAccepted.heartbeatIntervalMillis)
        assertEquals(
            InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES.toLong(),
            decodedAccepted.maximumEncryptedMediaRecordBytes,
        )
    }

    @Test
    fun decodesMediaRecordUint32LimitsWithoutSignedOverflow() {
        val unsignedMaximum = -1
        val hostHello =
            baseEnvelope(1)
                .setHostHello(
                    HostHello
                        .newBuilder()
                        .setSelectedProtocol(1)
                        .setHostId("host-1")
                        .setHostName("Mac")
                        .addAllCapabilities(ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES)
                        .setResourceLimits(mediaRecordLimits(unsignedMaximum)),
                ).build()
        val decodedHost = codec.decodeControl(hostHello.toByteArray()).message as ProductControlMessage.HostHello

        val accepted =
            baseEnvelope(2)
                .setSessionAccepted(
                    SessionAccepted
                        .newBuilder()
                        .setSessionId(ByteString.copyFrom(sessionId))
                        .setSessionEpoch(7)
                        .setHeartbeatIntervalMs(1_000)
                        .addAllNegotiatedCapabilities(ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES)
                        .setNegotiatedResourceLimits(mediaRecordLimits(unsignedMaximum)),
                ).build()
        val decodedAccepted = codec.decodeControl(accepted.toByteArray()).message as ProductControlMessage.SessionAccepted

        assertEquals(4_294_967_295L, decodedHost.maximumEncryptedMediaRecordBytes)
        assertEquals(4_294_967_295L, decodedAccepted.maximumEncryptedMediaRecordBytes)
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

    @Test
    fun mediaRecordBoundaryLeavesExactSpaceForApplicationAeadOverhead() {
        assertEquals(67, InternetMediaRecordContract.APPLICATION_AEAD_RECORD_OVERHEAD_BYTES)
        assertTrue(
            (InternetMediaRecordContract.MINIMUM_NEGOTIATED_ENCRYPTED_RECORD_BYTES -
                InternetMediaRecordContract.APPLICATION_AEAD_RECORD_OVERHEAD_BYTES -
                InternetMediaRecordContract.MAXIMUM_MEDIA_HEADER_BYTES -
                InternetMediaRecordContract.MAXIMUM_HEADER_LENGTH_VARINT_BYTES) *
                InternetMediaRecordContract.MAXIMUM_FRAGMENTS_PER_FRAME >=
                InternetMediaRecordContract.MAXIMUM_FRAME_BYTES,
        )
        assertEquals(
            4 * 1024 * 1024,
            InternetMediaRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES +
                InternetMediaRecordContract.APPLICATION_AEAD_RECORD_OVERHEAD_BYTES,
        )

        var payloadBytes = InternetMediaRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES
        var header = mediaHeader(payloadBytes)
        repeat(3) {
            val headerBytes = header.toByteArray().size
            payloadBytes =
                InternetMediaRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES -
                encodedVarintBytes(headerBytes) -
                headerBytes
            header = mediaHeader(payloadBytes)
        }
        val record = ProtobufProtocolV1ProductCodec.encodeMediaFragment(header, ByteArray(payloadBytes))

        assertEquals(InternetMediaRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES, record.size)
        assertEquals(
            InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES,
            record.size + InternetMediaRecordContract.APPLICATION_AEAD_RECORD_OVERHEAD_BYTES,
        )
        assertEquals(payloadBytes, codec.decodeMediaFragment(record).payload.size)
        assertThrows(IllegalArgumentException::class.java) {
            val oversizedPayload = ByteArray(payloadBytes + 1)
            ProtobufProtocolV1ProductCodec.encodeMediaFragment(
                mediaHeader(oversizedPayload.size),
                oversizedPayload,
            )
        }
    }

    @Test
    fun encodesControllerEventWithAllFields() {
        val event = ProductControllerEvent(
            inputId = 42,
            controllerId = "android-abc123",
            controllerEpoch = 3,
            kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
            buttonMask = 0b101,
            leftStickX = 0.5,
            leftStickY = -0.25,
            rightStickX = 0.0,
            rightStickY = 1.0,
            leftTrigger = 0.75,
            rightTrigger = 0.0,
            hatX = 1,
            hatY = -1,
        )
        val envelope = Envelope.parseFrom(codec.encodeController(5, sessionId, 7, 9, event))
        assertEquals(Envelope.PayloadCase.CONTROLLER_EVENT, envelope.payloadCase)
        val ce = envelope.controllerEvent
        assertEquals(42L, ce.inputId)
        assertEquals("android-abc123", ce.controllerId)
        assertEquals(3L, ce.controllerEpoch)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE, ce.kind)
        assertEquals(0b101, ce.buttonMask)
        assertEquals(0.5, ce.leftStickX, 0.0)
        assertEquals(-0.25, ce.leftStickY, 0.0)
        assertEquals(1.0, ce.rightStickY, 0.0)
        assertEquals(0.75, ce.leftTrigger, 0.0)
        assertEquals(1, ce.hatX)
        assertEquals(-1, ce.hatY)
        assertEquals(9L, ce.target.streamId)
    }

    @Test
    fun clientHelloAdvertisesControllerCapability() {
        val hello = Envelope.parseFrom(codec.encodeClientHello(1, sessionId, 7))
        assertTrue(hello.clientHello.capabilitiesList.contains(dev.vibescreen.protocol.v1.Capability.CAPABILITY_CONTROLLER))
    }


    @Test
    fun productControllerEventRejectsEmptyControllerId() {
        assertThrows(IllegalArgumentException::class.java) {
            ProductControllerEvent(
                inputId = 1,
                controllerId = "",
                controllerEpoch = 1,
                kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
                buttonMask = 0,
                leftStickX = 0.0, leftStickY = 0.0,
                rightStickX = 0.0, rightStickY = 0.0,
                leftTrigger = 0.0, rightTrigger = 0.0,
                hatX = 0, hatY = 0,
            )
        }
    }

    @Test
    fun productControllerEventRejectsControllerIdOver128Utf8Bytes() {
        // 43 three-byte UTF-8 characters occupy 129 bytes.
        val oversized = "中".repeat(43)
        assertEquals(129, oversized.toByteArray(Charsets.UTF_8).size)
        assertThrows(IllegalArgumentException::class.java) {
            ProductControllerEvent(
                inputId = 1,
                controllerId = oversized,
                controllerEpoch = 1,
                kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
                buttonMask = 0,
                leftStickX = 0.0, leftStickY = 0.0,
                rightStickX = 0.0, rightStickY = 0.0,
                leftTrigger = 0.0, rightTrigger = 0.0,
                hatX = 0, hatY = 0,
            )
        }
    }

    @Test
    fun productControllerEventAcceptsExactly128Utf8Bytes() {
        val id128 = "é".repeat(64)
        assertEquals(128, id128.toByteArray(Charsets.UTF_8).size)
        val event = ProductControllerEvent(
            inputId = 1,
            controllerId = id128,
            controllerEpoch = 1,
            kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
            buttonMask = 0,
            leftStickX = 0.0, leftStickY = 0.0,
            rightStickX = 0.0, rightStickY = 0.0,
            leftTrigger = 0.0, rightTrigger = 0.0,
            hatX = 0, hatY = 0,
        )
        assertEquals(id128, event.controllerId)
    }

    @Test
    fun productControllerEventRejectsNonPositiveInputId() {
        assertThrows(IllegalArgumentException::class.java) {
            ProductControllerEvent(
                inputId = 0,
                controllerId = "c1",
                controllerEpoch = 1,
                kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
                buttonMask = 0,
                leftStickX = 0.0, leftStickY = 0.0,
                rightStickX = 0.0, rightStickY = 0.0,
                leftTrigger = 0.0, rightTrigger = 0.0,
                hatX = 0, hatY = 0,
            )
        }
    }

    @Test
    fun productControllerEventRejectsNonPositiveEpoch() {
        assertThrows(IllegalArgumentException::class.java) {
            ProductControllerEvent(
                inputId = 1,
                controllerId = "c1",
                controllerEpoch = 0,
                kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
                buttonMask = 0,
                leftStickX = 0.0, leftStickY = 0.0,
                rightStickX = 0.0, rightStickY = 0.0,
                leftTrigger = 0.0, rightTrigger = 0.0,
                hatX = 0, hatY = 0,
            )
        }
    }

    @Test
    fun productControllerEventRejectsButtonMaskOutOfRange() {
        assertThrows(IllegalArgumentException::class.java) {
            ProductControllerEvent(
                inputId = 1,
                controllerId = "c1",
                controllerEpoch = 1,
                kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
                buttonMask = 0x2000,
                leftStickX = 0.0, leftStickY = 0.0,
                rightStickX = 0.0, rightStickY = 0.0,
                leftTrigger = 0.0, rightTrigger = 0.0,
                hatX = 0, hatY = 0,
            )
        }
    }

    @Test
    fun productControllerEventRejectsStickValuesOutOfRange() {
        assertThrows(IllegalArgumentException::class.java) {
            ProductControllerEvent(
                inputId = 1,
                controllerId = "c1",
                controllerEpoch = 1,
                kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
                buttonMask = 0,
                leftStickX = 1.5, leftStickY = 0.0,
                rightStickX = 0.0, rightStickY = 0.0,
                leftTrigger = 0.0, rightTrigger = 0.0,
                hatX = 0, hatY = 0,
            )
        }
    }

    @Test
    fun productControllerEventRejectsTriggerValuesOutOfRange() {
        assertThrows(IllegalArgumentException::class.java) {
            ProductControllerEvent(
                inputId = 1,
                controllerId = "c1",
                controllerEpoch = 1,
                kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
                buttonMask = 0,
                leftStickX = 0.0, leftStickY = 0.0,
                rightStickX = 0.0, rightStickY = 0.0,
                leftTrigger = -0.1, rightTrigger = 0.0,
                hatX = 0, hatY = 0,
            )
        }
    }

    @Test
    fun productControllerEventRejectsHatValuesOutOfRange() {
        assertThrows(IllegalArgumentException::class.java) {
            ProductControllerEvent(
                inputId = 1,
                controllerId = "c1",
                controllerEpoch = 1,
                kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
                buttonMask = 0,
                leftStickX = 0.0, leftStickY = 0.0,
                rightStickX = 0.0, rightStickY = 0.0,
                leftTrigger = 0.0, rightTrigger = 0.0,
                hatX = 2, hatY = 0,
            )
        }
    }

    @Test
    fun productControllerEventRejectsLifecycleEventWithNonNeutralState() {
        assertThrows(IllegalArgumentException::class.java) {
            ProductControllerEvent(
                inputId = 1,
                controllerId = "c1",
                controllerEpoch = 1,
                kind = dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
                buttonMask = 1,
                leftStickX = 0.0, leftStickY = 0.0,
                rightStickX = 0.0, rightStickY = 0.0,
                leftTrigger = 0.0, rightTrigger = 0.0,
                hatX = 0, hatY = 0,
            )
        }
    }

    private fun mediaHeader(payloadBytes: Int): MediaPacketHeader =
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
            .setPayloadLength(payloadBytes)
            .build()

    private fun mediaRecordLimits(
        maximumEncryptedMediaRecordBytes: Int = InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES,
    ): ResourceLimits.Builder =
        ResourceLimits
            .newBuilder()
            .setMaximumEncryptedMediaRecordBytes(maximumEncryptedMediaRecordBytes)

    private fun encodedVarintBytes(value: Int): Int {
        var remaining = value
        var bytes = 1
        while (remaining >= 0x80) {
            remaining = remaining ushr 7
            bytes++
        }
        return bytes
    }

    private fun baseEnvelope(messageId: Long): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(messageId)
            .setSessionId(ByteString.copyFrom(sessionId))
            .setSessionEpoch(7)
}
