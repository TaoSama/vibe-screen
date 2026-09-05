package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.ClipboardContent
import dev.vibescreen.protocol.v1.ClipboardOffer
import dev.vibescreen.protocol.v1.ClipboardRequest
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DisplayDescriptor
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.ListDisplaysResponse
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import dev.vibescreen.protocol.v1.ManagedRestrictionResult
import dev.vibescreen.protocol.v1.ResourceLimits
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.StartDisplayResponse
import dev.vibescreen.protocol.v1.TransportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.MessageDigest

class ProtocolV1ClipboardFailClosedTest {
    private val deviceId = "android-test"
    private val hostId = "mac-host"
    private val sessionId = ByteString.copyFromUtf8("session-1")

    @Test
    fun clipboardPayloadsWithStaleSessionEpochFailClosed() {
        fun stale(envelope: Envelope): Envelope = envelope.toBuilder().setSessionEpoch(8).build()

        listOf(
            "offer" to stale(clipboardOffer(id = 10)),
            "request" to stale(clipboardRequest(id = 10)),
            "content" to stale(clipboardContent(id = 10)),
        ).forEach { (payload, envelope) ->
            val session = readyClipboardSession()

            assertPeerProtocolViolation("$payload should fail closed on stale epoch", session, envelope)
        }
    }

    @Test
    fun managedPolicyDenyRejectsEveryIncomingClipboardPayloadType() {
        listOf(
            "offer" to clipboardOffer(id = 11),
            "request" to clipboardRequest(id = 11),
            "content" to clipboardContent(id = 11),
        ).forEach { (payload, envelope) ->
            val session = readyClipboardSession()
            session.receive(base(10).setManagedPolicyStatus(managedPolicyStatus(clipboardAllowed = false)).build())

            assertPeerProtocolViolation("$payload should fail closed after remote clipboard deny", session, envelope)
            assertFalse(session.canSendClipboard)
        }
    }

    @Test
    fun managedPolicyDenyBlocksOutgoingClipboardMessages() {
        val session = readyClipboardSession()
        val offeredChangeId = defaultChangeId()
        session.receive(clipboardOffer(id = 10, changeId = offeredChangeId))
        assertTrue(session.canSendClipboard)

        session.receive(base(11).setManagedPolicyStatus(managedPolicyStatus(clipboardAllowed = false)).build())

        assertFalse(session.canSendClipboard)
        assertFalse(Capability.CAPABILITY_CLIPBOARD in session.negotiated)
        assertEquals(0L, session.negotiatedMaxClipboardBytes)
        assertNull(session.offerClipboard("policy denied"))
        assertNull(session.requestClipboard(offeredChangeId))
    }

    @Test
    fun clipboardPayloadsBeforeStreamingFailClosed() {
        listOf(
            "offer" to clipboardOffer(id = 4),
            "request" to clipboardRequest(id = 4),
            "content" to clipboardContent(id = 4),
        ).forEach { (payload, envelope) ->
            val session = negotiatedButNotStreamingSession()

            assertPeerProtocolViolation("$payload should fail closed before streaming", session, envelope)
        }
    }

    @Test
    fun clipboardPayloadsWithoutNegotiatedCapabilityFailClosed() {
        val caps = listOf(Capability.CAPABILITY_TOUCH)
        listOf(
            "offer" to clipboardOffer(id = 10),
            "request" to clipboardRequest(id = 10),
            "content" to clipboardContent(id = 10),
        ).forEach { (payload, envelope) ->
            val session = readyClipboardSession(capabilities = caps)

            assertPeerProtocolViolation("$payload should fail closed without clipboard capability", session, envelope)
            assertFalse(session.canSendClipboard)
        }
    }

    @Test
    fun invalidClipboardOfferMetadataFailsClosed() {
        listOf(
            "bad change id" to { _: ProtocolV1Session ->
                clipboardOffer(id = 10, changeId = ByteString.copyFrom(byteArrayOf(0x01)))
            },
            "empty origin" to { _: ProtocolV1Session ->
                clipboardOffer(id = 10, originDeviceId = "")
            },
            "wrong origin" to { _: ProtocolV1Session ->
                clipboardOffer(id = 10, originDeviceId = "not-the-host")
            },
            "unsupported mime" to { _: ProtocolV1Session ->
                clipboardOffer(id = 10, mimeType = "text/html")
            },
            "zero byte length" to { _: ProtocolV1Session ->
                clipboardOffer(id = 10, byteLength = 0L)
            },
            "oversized byte length" to { _: ProtocolV1Session ->
                clipboardOffer(id = 10, byteLength = ProtocolV1Session.LOCAL_MAX_CLIPBOARD_BYTES + 1L)
            },
            "bad digest length" to { _: ProtocolV1Session ->
                clipboardOffer(id = 10, digest = ByteString.copyFrom(byteArrayOf(0x02)))
            },
            "loopback change id" to { session: ProtocolV1Session ->
                val ownOffer = session.offerClipboard("loopback") ?: error("local offer should succeed")
                clipboardOffer(id = 10, changeId = ownOffer.clipboardOffer.changeId)
            },
        ).forEach { (caseName, envelopeFactory) ->
            val session = readyClipboardSession()

            assertPeerProtocolViolation("offer $caseName", session, envelopeFactory(session))
        }
    }

    @Test
    fun invalidClipboardContentMetadataFailsClosed() {
        listOf(
            "bad change id" to { _: ProtocolV1Session ->
                clipboardContent(id = 10, changeId = ByteString.copyFrom(byteArrayOf(0x01)))
            },
            "empty origin" to { _: ProtocolV1Session ->
                clipboardContent(id = 10, originDeviceId = "")
            },
            "wrong origin" to { _: ProtocolV1Session ->
                clipboardContent(id = 10, originDeviceId = "not-the-host")
            },
            "unsupported mime" to { _: ProtocolV1Session ->
                clipboardContent(id = 10, mimeType = "text/html")
            },
            "empty content" to { _: ProtocolV1Session ->
                val bytes = ByteArray(0)
                clipboardContent(id = 10, bytes = bytes, digest = ByteString.copyFrom(sha256(bytes)))
            },
            "oversized content" to { _: ProtocolV1Session ->
                val bytes = ByteArray(11) { 'a'.code.toByte() }
                clipboardContent(id = 10, bytes = bytes, digest = ByteString.copyFrom(sha256(bytes)))
            },
            "bad digest length" to { _: ProtocolV1Session ->
                clipboardContent(id = 10, digest = ByteString.copyFrom(byteArrayOf(0x02)))
            },
            "digest mismatch" to { _: ProtocolV1Session ->
                clipboardContent(id = 10, digest = ByteString.copyFrom(sha256("other".toByteArray(Charsets.UTF_8))))
            },
            "invalid utf8" to { _: ProtocolV1Session ->
                val bytes = byteArrayOf(0xFF.toByte(), 0xFE.toByte())
                clipboardContent(id = 10, bytes = bytes, digest = ByteString.copyFrom(sha256(bytes)))
            },
            "loopback change id" to { session: ProtocolV1Session ->
                val ownOffer = session.offerClipboard("loopback") ?: error("local offer should succeed")
                clipboardContent(id = 10, changeId = ownOffer.clipboardOffer.changeId)
            },
        ).forEach { (caseName, envelopeFactory) ->
            val session = readyClipboardSession(maximumClipboardBytes = 10L)

            assertPeerProtocolViolation("content $caseName", session, envelopeFactory(session))
        }
    }

    @Test
    fun unknownWellFormedClipboardRequestIsAuthenticatedNoOp() {
        val session = readyClipboardSession()
        val unknown = ByteString.copyFrom(ByteArray(16) { 0x55.toByte() })

        val actions = session.receive(clipboardRequest(id = 10, changeId = unknown))

        assertTrue(actions.isEmpty())
        assertTrue(session.isStreaming)
    }

    @Test
    fun clipboardRequestWithInvalidChangeIdLengthFailsClosed() {
        val session = readyClipboardSession()

        assertPeerProtocolViolation(
            "request bad change id",
            session,
            clipboardRequest(id = 10, changeId = ByteString.copyFrom(byteArrayOf(0x01))),
        )
    }

    private fun readyClipboardSession(
        capabilities: List<Capability> = clipboardCapabilities(),
        maximumClipboardBytes: Long = ProtocolV1Session.LOCAL_MAX_CLIPBOARD_BYTES,
    ): ProtocolV1Session {
        val session = negotiatedButNotStreamingSession(capabilities, maximumClipboardBytes)
        var inboundId = 4L
        if (Capability.CAPABILITY_MANAGED_CONFIGURATION in capabilities) {
            session.receive(base(inboundId++).setManagedPolicyStatus(managedPolicyStatus(clipboardAllowed = true)).build())
        }
        session.receive(displayList(inboundId++))
        session.receive(startDisplay(inboundId++))
        val requested =
            session.receive(videoConfig(inboundId))
                .filterIsInstance<ProtocolV1Session.Action.VideoConfigurationRequested>()
                .single()
        session.completeVideoConfiguration(3, requested.configurationToken, true, "")
        return session
    }

    private fun negotiatedButNotStreamingSession(
        capabilities: List<Capability> = clipboardCapabilities(),
        maximumClipboardBytes: Long = ProtocolV1Session.LOCAL_MAX_CLIPBOARD_BYTES,
    ): ProtocolV1Session {
        val session =
            ProtocolV1Session(
                deviceId = deviceId,
                deviceName = "Test Android",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
                nowNs = { 1_000L },
            )
        session.clientHello()
        session.receive(hostHello(2, capabilities, maximumClipboardBytes))
        session.receive(sessionAccepted(3, capabilities, maximumClipboardBytes))
        return session
    }

    private fun clipboardOffer(
        id: Long,
        changeId: ByteString = defaultChangeId(),
        text: String = "from mac",
        originDeviceId: String = hostId,
        mimeType: String = "text/plain",
        byteLength: Long? = null,
        digest: ByteString? = null,
    ): Envelope {
        val bytes = text.toByteArray(Charsets.UTF_8)
        return base(id)
            .setClipboardOffer(
                ClipboardOffer
                    .newBuilder()
                    .setChangeId(changeId)
                    .setOriginDeviceId(originDeviceId)
                    .setMimeType(mimeType)
                    .setByteLength(byteLength ?: bytes.size.toLong())
                    .setSha256(digest ?: ByteString.copyFrom(sha256(bytes))),
            ).build()
    }

    private fun clipboardRequest(
        id: Long,
        changeId: ByteString = defaultChangeId(),
    ): Envelope =
        base(id)
            .setClipboardRequest(ClipboardRequest.newBuilder().setChangeId(changeId))
            .build()

    private fun clipboardContent(
        id: Long,
        changeId: ByteString = defaultChangeId(),
        text: String = "from mac",
        bytes: ByteArray = text.toByteArray(Charsets.UTF_8),
        originDeviceId: String = hostId,
        mimeType: String = "text/plain",
        digest: ByteString? = null,
    ): Envelope {
        return base(id)
            .setClipboardContent(
                ClipboardContent
                    .newBuilder()
                    .setChangeId(changeId)
                    .setOriginDeviceId(originDeviceId)
                    .setMimeType(mimeType)
                    .setContent(ByteString.copyFrom(bytes))
                    .setSha256(digest ?: ByteString.copyFrom(sha256(bytes))),
            ).build()
    }

    private fun assertPeerProtocolViolation(
        message: String,
        session: ProtocolV1Session,
        envelope: Envelope,
    ) {
        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(envelope) }
        assertEquals(message, "invalid_peer_message", failure.reason)
        assertEquals(ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION, failure.source)
    }

    private fun clipboardCapabilities(): List<Capability> =
        listOf(
            Capability.CAPABILITY_TOUCH,
            Capability.CAPABILITY_CLIPBOARD,
            Capability.CAPABILITY_MANAGED_CONFIGURATION,
        )

    private fun defaultChangeId(): ByteString = ByteString.copyFrom(ByteArray(16) { it.toByte() })

    private fun sha256(bytes: ByteArray): ByteArray =
        MessageDigest.getInstance("SHA-256").digest(bytes)

    private fun hostHello(
        id: Long,
        advertisedCapabilities: List<Capability>,
        maximumClipboardBytes: Long = ProtocolV1Session.LOCAL_MAX_CLIPBOARD_BYTES,
    ): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setHostHello(
                HostHello
                    .newBuilder()
                    .setSelectedProtocol(1)
                    .setHostId(hostId)
                    .addAllCapabilities(advertisedCapabilities)
                    .addAllCodecs(listOf(Codec.CODEC_HEVC, Codec.CODEC_H264))
                    .setResourceLimits(
                        ResourceLimits.newBuilder().setMaximumClipboardBytes(maximumClipboardBytes),
                    ),
            ).build()

    private fun sessionAccepted(
        id: Long,
        negotiatedCapabilities: List<Capability>,
        maximumClipboardBytes: Long = ProtocolV1Session.LOCAL_MAX_CLIPBOARD_BYTES,
    ): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionAccepted(
                SessionAccepted
                    .newBuilder()
                    .setSessionId(sessionId)
                    .setSessionEpoch(7)
                    .setHeartbeatIntervalMs(1_000)
                    .addAllNegotiatedCapabilities(negotiatedCapabilities)
                    .setNegotiatedResourceLimits(
                        ResourceLimits.newBuilder().setMaximumClipboardBytes(maximumClipboardBytes),
                    ),
            ).build()

    private fun base(id: Long): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(sessionId)
            .setSessionEpoch(7)

    private fun managedPolicyStatus(clipboardAllowed: Boolean): ManagedPolicyStatus {
        val allowedHosts = listOf(hostId)
        val deniedHosts = emptyList<String>()
        val restrictions =
            listOf(
                restrictionResult("clipboard", clipboardAllowed),
                restrictionResult("file_transfer", true),
                restrictionResult("audio", true),
                restrictionResult("wake", true),
                restrictionResult("custom_gestures", true),
                restrictionResult("host_actions", true),
                restrictionResult("maximum_file_bytes", true),
                restrictionResult("allowed_hosts", true),
                restrictionResult("denied_hosts", true),
            )
        return ManagedPolicyStatus
            .newBuilder()
            .setManaged(true)
            .setClipboardAllowed(clipboardAllowed)
            .setFileTransferAllowed(true)
            .setAudioAllowed(true)
            .setWakeAllowed(true)
            .setCustomGesturesAllowed(true)
            .setHostActionsAllowed(true)
            .setMaximumFileBytes(512L * 1_024L * 1_024L)
            .addAllAllowedHosts(allowedHosts)
            .setAllowedHostsRestricted(true)
            .addAllRestrictionResults(restrictions)
            .addAllDeniedHosts(deniedHosts)
            .build()
    }

    private fun restrictionResult(
        restriction: String,
        allowed: Boolean,
    ): ManagedRestrictionResult =
        ManagedRestrictionResult
            .newBuilder()
            .setRestriction(restriction)
            .setAllowed(allowed)
            .setSource("managed_configuration")
            .setReason("Test managed policy result.")
            .build()

    private fun displayList(id: Long): Envelope =
        base(id)
            .setListDisplaysResponse(
                ListDisplaysResponse
                    .newBuilder()
                    .addDisplays(
                        DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-1")
                            .setName("Display 1")
                            .setLogicalSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080)),
                    ),
            ).build()

    private fun startDisplay(id: Long): Envelope =
        base(id)
            .setStartDisplayResponse(StartDisplayResponse.newBuilder().setAccepted(true).setStreamId(42))
            .build()

    private fun videoConfig(id: Long): Envelope =
        base(id)
            .setVideoConfig(
                dev.vibescreen.protocol.v1.VideoConfig
                    .newBuilder()
                    .setStreamId(42)
                    .setConfigEpoch(3)
                    .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                    .setRotationDegrees(0)
                    .setCodec(Codec.CODEC_HEVC)
                    .setFramesPerSecond(60)
                    .setBitrateKbps(8_000)
                    .setColorDescription(VideoColorNegotiation.legacySdrColor),
            ).build()
}
