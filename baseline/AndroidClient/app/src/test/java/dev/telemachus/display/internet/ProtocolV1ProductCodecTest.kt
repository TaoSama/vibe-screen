package dev.telemachus.display.internet

import com.google.protobuf.ByteString
import dev.telemachus.display.ControllerAxes
import dev.telemachus.display.ControllerEventKind
import dev.telemachus.display.ControllerStateSample
import dev.vibescreen.protocol.v1.AudioCodec
import dev.vibescreen.protocol.v1.AudioConfig
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.ClipboardContent
import dev.vibescreen.protocol.v1.ClipboardOffer
import dev.vibescreen.protocol.v1.ClipboardRequest
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.ControllerEventKind as ProtocolControllerEventKind
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.FileAccept
import dev.vibescreen.protocol.v1.FileOffer
import dev.vibescreen.protocol.v1.FileTransferCancel
import dev.vibescreen.protocol.v1.FileTransferComplete
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.InputAck
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.ResourceLimits
import dev.vibescreen.protocol.v1.SessionAccepted
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolV1ProductCodecTest {
    private val codec = ProtobufProtocolV1ProductCodec("device-1", "Android", setOf(ProductVideoCodec.H264, ProductVideoCodec.HEVC)) { 99 }
    private val controllerCodec = ProtobufProtocolV1ProductCodec("device-1", "Android", setOf(ProductVideoCodec.H264, ProductVideoCodec.HEVC), advertiseController = true) { 99 }
    private val audioCodec = ProtobufProtocolV1ProductCodec("device-1", "Android", setOf(ProductVideoCodec.H264, ProductVideoCodec.HEVC), advertiseAudio = true) { 99 }
    private val sessionId = "session-1".toByteArray()

    @Test
    fun encodesRealProtocolV1HelloTouchKeyframeAndPingEnvelopes() {
        val hello = Envelope.parseFrom(codec.encodeClientHello(1, sessionId, 7))
        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, hello.payloadCase)
        assertEquals("device-1", hello.clientHello.deviceId)
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_END_TO_END_ENCRYPTION))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_MEDIA_RECORD_FRAGMENTATION))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_AUDIO_DATA_CHANNEL))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_BULK_DATA_CHANNEL))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_MANAGED_CONFIGURATION))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_FILE_TRANSFER))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_STYLUS))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_TOUCH))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_CLIPBOARD))
        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_MANAGED_CONFIGURATION))
        assertFalse(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_AUDIO))
        assertTrue(!hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_STYLUS))
        assertTrue(!hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_TOUCH))
        assertFalse(hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_MANAGED_CONFIGURATION))
        assertFalse(hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_FILE_TRANSFER))
        assertTrue(hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_MEDIA_RECORD_FRAGMENTATION))
        assertTrue(hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_AUDIO_DATA_CHANNEL))
        assertTrue(hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_BULK_DATA_CHANNEL))
        assertFalse(hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_AUDIO))
        assertFalse(hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_CLIPBOARD))
        assertFalse(hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_MANAGED_CONFIGURATION))
        assertFalse(hello.clientHello.requiredCapabilitiesList.contains(Capability.CAPABILITY_FILE_TRANSFER))
        assertEquals(
            InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES,
            hello.clientHello.resourceLimits.maximumEncryptedMediaRecordBytes,
        )
        assertEquals(
            InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES,
            hello.clientHello.resourceLimits.maximumClipboardBytes,
        )
        assertEquals(512L * 1024L * 1024L, hello.clientHello.resourceLimits.maximumFileBytes)
        assertEquals(64 * 1024, hello.clientHello.resourceLimits.maximumFileChunkBytes)
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
    fun localManagedPolicyFiltersClientHelloCapabilitiesAndLimits() {
        val policy =
            InternetManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                clipboardAllowed = false,
                fileTransferAllowed = false,
                maximumFileBytes = 0L,
                allowedHosts = setOf("host-1"),
                allowedHostsRestricted = true,
            )
        val managedCodec =
            ProtobufProtocolV1ProductCodec(
                localDeviceId = "device-1",
                deviceName = "Android",
                supportedCodecs = setOf(ProductVideoCodec.H264),
                localManagedPolicy = policy,
            ) { 99 }

        val hello = Envelope.parseFrom(managedCodec.encodeClientHello(1, sessionId, 7)).clientHello

        assertTrue(hello.capabilitiesList.contains(Capability.CAPABILITY_MANAGED_CONFIGURATION))
        assertFalse(hello.capabilitiesList.contains(Capability.CAPABILITY_CLIPBOARD))
        assertFalse(hello.capabilitiesList.contains(Capability.CAPABILITY_FILE_TRANSFER))
        assertEquals(0L, hello.resourceLimits.maximumClipboardBytes)
        assertEquals(0L, hello.resourceLimits.maximumFileBytes)
        assertEquals(0, hello.resourceLimits.maximumFileChunkBytes)
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
        assertEquals(1234L, decodedHost.maximumFileBytes)
        assertEquals(4096, decodedHost.maximumFileChunkBytes)
        assertEquals(1234L, decodedAccepted.maximumFileBytes)
        assertEquals(4096, decodedAccepted.maximumFileChunkBytes)
    }

    @Test
    fun encodeDecodeClipboardAndManagedPolicyControls() {
        val changeId = ByteString.copyFrom(ByteArray(InternetClipboard.CLIPBOARD_CHANGE_ID_BYTES) { it.toByte() })
        val contentBytes = "internet clipboard".toByteArray(Charsets.UTF_8)
        val digest = ByteString.copyFrom(InternetClipboard.sha256(contentBytes))
        val offer =
            ClipboardOffer
                .newBuilder()
                .setChangeId(changeId)
                .setOriginDeviceId("device-1")
                .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
                .setByteLength(contentBytes.size.toLong())
                .setSha256(digest)
                .build()
        val request = ClipboardRequest.newBuilder().setChangeId(changeId).build()
        val content =
            ClipboardContent
                .newBuilder()
                .setChangeId(changeId)
                .setOriginDeviceId("device-1")
                .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
                .setContent(ByteString.copyFrom(contentBytes))
                .setSha256(digest)
                .build()
        val policy = InternetManagedPolicy.UNMANAGED.toStatus()

        val decodedOffer = codec.decodeControl(
            codec.encodeClipboardOffer(20, sessionId, 7, offer),
        ).message as ProductControlMessage.ClipboardOffered
        assertEquals(offer, decodedOffer.offer)

        val decodedRequest = codec.decodeControl(
            codec.encodeClipboardRequest(21, sessionId, 7, request),
        ).message as ProductControlMessage.ClipboardRequested
        assertEquals(request, decodedRequest.request)

        val decodedContent = codec.decodeControl(
            codec.encodeClipboardContent(22, 21, sessionId, 7, content),
        )
        assertEquals(21L, Envelope.parseFrom(
            codec.encodeClipboardContent(22, 21, sessionId, 7, content),
        ).correlationId)
        assertEquals(content, (decodedContent.message as ProductControlMessage.ClipboardContentReceived).content)

        val decodedPolicy = codec.decodeControl(
            codec.encodeManagedPolicyStatus(23, sessionId, 7, policy),
        ).message as ProductControlMessage.ManagedPolicyStatusReceived
        assertEquals(policy, decodedPolicy.status)
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
    fun defaultClientHelloExcludesControllerCapability() {
        val hello = Envelope.parseFrom(codec.encodeClientHello(1, sessionId, 7))
        assertEquals(codec.offeredCapabilities, hello.clientHello.capabilitiesList.toSet())
        assertTrue(!hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_CONTROLLER))
    }

    @Test
    fun advertiseControllerAddsControllerWithoutDroppingExistingCapabilities() {
        val defaultCapabilities =
            Envelope.parseFrom(codec.encodeClientHello(1, sessionId, 7)).clientHello.capabilitiesList.toSet()
        val hello = Envelope.parseFrom(controllerCodec.encodeClientHello(1, sessionId, 7))
        assertEquals(defaultCapabilities + Capability.CAPABILITY_CONTROLLER, controllerCodec.offeredCapabilities)
        assertEquals(
            controllerCodec.offeredCapabilities,
            hello.clientHello.capabilitiesList.toSet(),
        )
    }

    @Test
    fun advertiseAudioAddsOptionalAudioCapabilityWithoutMakingItRequired() {
        val hello = Envelope.parseFrom(audioCodec.encodeClientHello(1, sessionId, 7)).clientHello

        assertTrue(hello.capabilitiesList.contains(Capability.CAPABILITY_AUDIO))
        assertFalse(hello.requiredCapabilitiesList.contains(Capability.CAPABILITY_AUDIO))
        assertEquals(audioCodec.offeredCapabilities, hello.capabilitiesList.toSet())
    }

    @Test
    fun decodesAudioConfigAndEncodesAudioConfigResult() {
        val config = audioConfig()
        val decoded =
            codec.decodeControl(
                baseEnvelope(8)
                    .setAudioConfig(config)
                    .build()
                    .toByteArray(),
            ).message as ProductControlMessage.AudioConfiguration

        assertEquals(config, decoded.config)

        val accepted = Envelope.parseFrom(codec.encodeAudioConfigResult(9, sessionId, 7, config, true, ""))
        assertEquals(Envelope.PayloadCase.AUDIO_CONFIG_RESULT, accepted.payloadCase)
        assertEquals(2L, accepted.audioConfigResult.streamId)
        assertEquals(1L, accepted.audioConfigResult.configEpoch)
        assertTrue(accepted.audioConfigResult.accepted)

        val rejected = Envelope.parseFrom(codec.encodeAudioConfigResult(10, sessionId, 7, config, false, "audio_track_start_failed"))
        assertFalse(rejected.audioConfigResult.accepted)
        assertEquals("audio_track_start_failed", rejected.audioConfigResult.rejectionReason)
        assertThrows(IllegalArgumentException::class.java) {
            codec.encodeAudioConfigResult(11, sessionId, 7, config, false, "")
        }
    }

    @Test
    fun encodeControllerProducesValidProtoEvent() {
        val sample =
            ControllerStateSample(
                controllerId = "pad-1",
                controllerEpoch = 3,
                kind = ControllerEventKind.STATE,
                buttonMask = 0b101,
                axes =
                    ControllerAxes(
                        leftX = 0.5,
                        leftY = -0.25,
                        rightX = 1.0,
                        rightY = -1.0,
                        leftTrigger = 0.75,
                        rightTrigger = 0.0,
                        hatX = 1,
                        hatY = -1,
                    ),
            )
        val envelope = Envelope.parseFrom(controllerCodec.encodeController(2, sessionId, 7, 42, 9, sample))
        assertEquals(Envelope.PayloadCase.CONTROLLER_EVENT, envelope.payloadCase)
        val controller = envelope.controllerEvent
        assertEquals(9L, controller.inputId)
        assertEquals("pad-1", controller.controllerId)
        assertEquals(3L, controller.controllerEpoch)
        assertEquals(ProtocolControllerEventKind.CONTROLLER_EVENT_KIND_STATE, controller.kind)
        assertEquals(0b101, controller.buttonMask)
        assertEquals(0.5, controller.leftStickX, 0.0)
        assertEquals(-0.25, controller.leftStickY, 0.0)
        assertEquals(1.0, controller.rightStickX, 0.0)
        assertEquals(-1.0, controller.rightStickY, 0.0)
        assertEquals(0.75, controller.leftTrigger, 0.0)
        assertEquals(0.0, controller.rightTrigger, 0.0)
        assertEquals(1, controller.hatX)
        assertEquals(-1, controller.hatY)
        assertEquals(42L, controller.target.streamId)
        assertEquals("", controller.target.displayId)

        assertThrows(IllegalArgumentException::class.java) {
            controllerCodec.encodeController(3, sessionId, 7, 0, 9, sample)
        }
        assertThrows(IllegalArgumentException::class.java) {
            controllerCodec.encodeController(3, sessionId, 7, 42, 0, sample)
        }
    }

    @Test
    fun encodeControllerLifecycleMapsKindAndStaysNeutral() {
        val connected = ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED)
        val connectedEnv = Envelope.parseFrom(controllerCodec.encodeController(2, sessionId, 7, 42, 1, connected))
        assertEquals(ProtocolControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, connectedEnv.controllerEvent.kind)
        assertEquals(0, connectedEnv.controllerEvent.buttonMask)

        val disconnected = ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED)
        val disconnectedEnv = Envelope.parseFrom(controllerCodec.encodeController(3, sessionId, 7, 42, 2, disconnected))
        assertEquals(ProtocolControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED, disconnectedEnv.controllerEvent.kind)
    }

    @Test
    fun decodeInputAckAcceptedAndRejected() {
        val accepted =
            baseEnvelope(8)
                .setInputAck(InputAck.newBuilder().setInputId(9).setAccepted(true))
                .build()
        val decodedAccepted = codec.decodeControl(accepted.toByteArray()).message as ProductControlMessage.InputAck
        assertEquals(9L, decodedAccepted.inputId)
        assertTrue(decodedAccepted.accepted)
        assertEquals("", decodedAccepted.rejectionReason)

        val rejected =
            baseEnvelope(9)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(10)
                        .setAccepted(false)
                        .setRejectionReason("maximum_active_controllers_exceeded"),
                ).build()
        val decodedRejected = codec.decodeControl(rejected.toByteArray()).message as ProductControlMessage.InputAck
        assertEquals(10L, decodedRejected.inputId)
        assertFalse(decodedRejected.accepted)
        assertEquals("maximum_active_controllers_exceeded", decodedRejected.rejectionReason)
    }

    @Test
    fun decodeInputAckRejectsInvalidIdentifierAndMissingReason() {
        val invalidIdentifier =
            baseEnvelope(10)
                .setInputAck(InputAck.newBuilder().setInputId(0).setAccepted(true))
                .build()
        assertThrows(IllegalArgumentException::class.java) {
            codec.decodeControl(invalidIdentifier.toByteArray())
        }

        val missingReason =
            baseEnvelope(11)
                .setInputAck(InputAck.newBuilder().setInputId(11).setAccepted(false))
                .build()
        assertThrows(IllegalArgumentException::class.java) {
            codec.decodeControl(missingReason.toByteArray())
        }

        val blankReason =
            baseEnvelope(12)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(12)
                        .setAccepted(false)
                        .setRejectionReason("   "),
                ).build()
        assertThrows(IllegalArgumentException::class.java) {
            codec.decodeControl(blankReason.toByteArray())
        }
    }

    @Test
    fun encodesAndDecodesInternetFileTransferControlMessages() {
        val transferId = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4))
        val sha256 = ByteString.copyFrom(ByteArray(32) { it.toByte() })
        val offer =
            FileOffer
                .newBuilder()
                .setTransferId(transferId)
                .setFileName("report.bin")
                .setMimeType("application/octet-stream")
                .setByteLength(5)
                .setSha256(sha256)
                .build()
        val decodedOffer = codec.decodeControl(codec.encodeFileOffer(20, sessionId, 7, offer)).message
        assertEquals(offer, (decodedOffer as ProductControlMessage.FileOfferReceived).offer)

        val accept = FileAccept.newBuilder().setTransferId(transferId).setAccepted(false).setRejectionReason("user_denied").build()
        val decodedAccept = codec.decodeControl(codec.encodeFileAccept(21, sessionId, 7, accept)).message
        assertEquals(accept, (decodedAccept as ProductControlMessage.FileAcceptReceived).response)

        val decodedProgress = codec.decodeControl(codec.encodeFileProgress(22, sessionId, 7, transferId, 5)).message
        assertEquals(5L, (decodedProgress as ProductControlMessage.FileProgressReceived).progress.receivedBytes)

        val decodedCancel = codec.decodeControl(codec.encodeFileCancel(23, sessionId, 7, transferId, "approval_timeout")).message
        assertEquals("approval_timeout", (decodedCancel as ProductControlMessage.FileCancelReceived).cancellation.reasonCode)

        val decodedComplete = codec.decodeControl(codec.encodeFileComplete(24, sessionId, 7, transferId, true, sha256, "")).message
        assertEquals(sha256, (decodedComplete as ProductControlMessage.FileCompleteReceived).result.sha256)

        val policy =
            ManagedPolicyStatus
                .newBuilder()
                .setManaged(true)
                .setFileTransferAllowed(false)
                .setMaximumFileBytes(0)
                .build()
        val decodedPolicy = codec.decodeControl(baseEnvelope(25).setManagedPolicyStatus(policy).build().toByteArray()).message
        assertEquals(policy, (decodedPolicy as ProductControlMessage.ManagedPolicyStatusReceived).status)
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

    private fun audioConfig(): AudioConfig =
        AudioConfig
            .newBuilder()
            .setStreamId(2)
            .setConfigEpoch(1)
            .setCodec(AudioCodec.AUDIO_CODEC_PCM_S16LE)
            .setSampleRateHz(48_000)
            .setChannelCount(2)
            .setFramesPerPacket(480)
            .build()

    private fun mediaRecordLimits(
        maximumEncryptedMediaRecordBytes: Int = InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES,
        maximumClipboardBytes: Long = 0L,
    ): ResourceLimits.Builder =
        ResourceLimits
            .newBuilder()
            .setMaximumEncryptedMediaRecordBytes(maximumEncryptedMediaRecordBytes)
            .setMaximumClipboardBytes(maximumClipboardBytes)
            .setMaximumFileBytes(1234)
            .setMaximumFileChunkBytes(4096)

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
