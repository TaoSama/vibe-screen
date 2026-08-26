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
import dev.vibescreen.protocol.v1.VideoConfig
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.charset.CharacterCodingException
import java.security.MessageDigest

class ProtocolV1ClipboardTest {
    private val deviceId = "android-test"
    private val hostId = "mac-host"
    private val sessionId = ByteString.copyFromUtf8("session-1")

    private fun clipboardSession(): ProtocolV1Session {
        val caps = clipboardCapabilities(managedConfiguration = true)
        val session =
            ProtocolV1Session(
                deviceId = deviceId,
                deviceName = "Test Android",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
                nowNs = { 1_000L },
            )
        session.clientHello()
        session.receive(hostHello(2, caps))
        session.receive(sessionAccepted(3, caps))
        session.receive(base(4).setManagedPolicyStatus(managedPolicyStatus()).build())
        session.receive(displayList(5))
        session.receive(startDisplay(6))
        val requested = singleVideoConfigurationRequested(session.receive(videoConfig(7)))
        session.completeVideoConfiguration(
            completedConfigEpoch = 3,
            configurationToken = requested.configurationToken,
            accepted = true,
            rejectionReason = "",
        )
        return session
    }

    @Test
    fun offerClipboardCreatesValidOfferAndCachesSnapshot() {
        val session = clipboardSession()
        val text = "hello clipboard"
        val envelope = session.offerClipboard(text) ?: throw AssertionError("offer should succeed")

        val offer = envelope.clipboardOffer
        assertEquals(16, offer.changeId.size())
        assertEquals(deviceId, offer.originDeviceId)
        assertEquals("text/plain", offer.mimeType)
        assertEquals(text.toByteArray(Charsets.UTF_8).size.toLong(), offer.byteLength)
        assertEquals(32, offer.sha256.size())
        assertArrayEquals(sha256(text.toByteArray(Charsets.UTF_8)), offer.sha256.toByteArray())
    }

    @Test
    fun offerClipboardRequiresStreamingState() {
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
        val session =
            ProtocolV1Session(
                deviceId = deviceId,
                deviceName = "Test Android",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC),
                nowNs = { 1_000L },
            )
        session.clientHello()
        session.receive(hostHello(2, caps))
        session.receive(sessionAccepted(3, caps))

        assertFalse(session.canSendClipboard)
        assertNull(session.offerClipboard("not streaming yet"))
    }

    @Test
    fun clipboardLimitIsZeroWhenCapabilityIsNotNegotiated() {
        val caps = listOf(Capability.CAPABILITY_TOUCH)
        val session =
            ProtocolV1Session(
                deviceId = deviceId,
                deviceName = "Test Android",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC),
                nowNs = { 1_000L },
            )

        assertEquals(0L, session.negotiatedMaxClipboardBytes)
        session.clientHello()
        session.receive(hostHello(2, caps, hostMaxClipboardBytes = 128L))
        session.receive(sessionAccepted(3, caps, acceptedMaxClipboardBytes = 128L))

        assertEquals(0L, session.negotiatedMaxClipboardBytes)
        assertNull(session.offerClipboard("clipboard unavailable"))
    }

    @Test
    fun incomingClipboardBeforeStreamingFailsClosed() {
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
        val session =
            ProtocolV1Session(
                deviceId = deviceId,
                deviceName = "Test Android",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC),
                nowNs = { 1_000L },
            )
        session.clientHello()
        session.receive(hostHello(2, caps))
        session.receive(sessionAccepted(3, caps))

        val bytes = "early".toByteArray(Charsets.UTF_8)
        val offer =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(4)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardOffer(
                    ClipboardOffer
                        .newBuilder()
                        .setChangeId(ByteString.copyFrom(ByteArray(16) { it.toByte() }))
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setByteLength(bytes.size.toLong())
                        .setSha256(ByteString.copyFrom(sha256(bytes))),
                ).build()

        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(offer) }
        assertEquals("invalid_peer_message", failure.reason)
    }

    @Test
    fun offerThenRequestDeliversContentOnce() {
        val session = clipboardSession()
        val text = "hello clipboard"
        val offerEnv = session.offerClipboard(text) ?: throw AssertionError("offer failed")
        val changeId = offerEnv.clipboardOffer.changeId

        // Host requests the content.
        val requestEnv =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardRequest(ClipboardRequest.newBuilder().setChangeId(changeId))
                .build()
        val actions = session.receive(requestEnv)
        val sendAction = actions.filterIsInstance<ProtocolV1Session.Action.Send>().single()
        val content = sendAction.envelope.clipboardContent
        assertEquals(changeId, content.changeId)
        assertEquals(deviceId, content.originDeviceId)
        assertEquals("text/plain", content.mimeType)
        assertEquals(text, content.content.toStringUtf8())
        assertArrayEquals(sha256(text.toByteArray(Charsets.UTF_8)), content.sha256.toByteArray())

        // A second request for the same changeId is a stale authenticated no-op:
        // the one-shot snapshot was consumed, but the stream remains healthy.
        val secondRequest =
            requestEnv.toBuilder().setMessageId(11).build()
        assertTrue(session.receive(secondRequest).isEmpty())
        assertTrue(session.isStreaming)

        val replacement = session.offerClipboard("replacement")
        assertNotNull(replacement)
    }

    @Test
    fun malformedClipboardRequestStillFailsClosed() {
        val session = clipboardSession()
        val request =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardRequest(
                    ClipboardRequest.newBuilder().setChangeId(ByteString.copyFrom(byteArrayOf(1))),
                ).build()

        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(request) }
        assertEquals("invalid_peer_message", failure.reason)
    }

    @Test
    fun receivedOfferCanBeRequestedAndContentValidated() {
        val session = clipboardSession()
        val hostText = "from mac"
        val hostBytes = hostText.toByteArray(Charsets.UTF_8)
        val hostChangeId = ByteString.copyFrom(ByteArray(16) { it.toByte() })
        val hostSha = ByteString.copyFrom(sha256(hostBytes))

        // Host offers clipboard.
        val offerEnv =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardOffer(
                    ClipboardOffer
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setByteLength(hostBytes.size.toLong())
                        .setSha256(hostSha),
                ).build()
        val offerActions = session.receive(offerEnv)
        val offered = offerActions.single() as ProtocolV1Session.Action.ClipboardOffered
        assertEquals(hostChangeId, offered.changeId)

        // Client requests the content.
        val requestEnv = session.requestClipboard(hostChangeId) ?: throw AssertionError("request failed")
        assertEquals(hostChangeId, requestEnv.clipboardRequest.changeId)

        // Host sends content.
        val contentEnv =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(12)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardContent(
                    ClipboardContent
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setContent(ByteString.copyFrom(hostBytes))
                        .setSha256(hostSha),
                ).build()
        val contentActions = session.receive(contentEnv)
        val received = contentActions.single() as ProtocolV1Session.Action.ClipboardContentReceived
        assertEquals(hostChangeId, received.changeId)
        assertEquals(hostText, received.content.toString(Charsets.UTF_8))
        assertFalse(received.pending)
    }

    @Test
    fun solicitedContentWithOfferLengthMismatchFailsClosed() {
        val session = clipboardSession()
        val hostChangeId = ByteString.copyFrom(ByteArray(16) { (it + 1).toByte() })
        val bytes = "length".toByteArray(Charsets.UTF_8)
        val digest = ByteString.copyFrom(sha256(bytes))

        session.receive(
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardOffer(
                    ClipboardOffer
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setByteLength(bytes.size.toLong() + 1L)
                        .setSha256(digest),
                ).build(),
        )
        assertNotNull(session.requestClipboard(hostChangeId))

        val content =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(11)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardContent(
                    ClipboardContent
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setContent(ByteString.copyFrom(bytes))
                        .setSha256(digest),
                ).build()

        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(content) }
        assertEquals("invalid_peer_message", failure.reason)
    }

    @Test
    fun solicitedContentWithOfferDigestMismatchFailsClosed() {
        val session = clipboardSession()
        val hostChangeId = ByteString.copyFrom(ByteArray(16) { (it + 2).toByte() })
        val offeredBytes = "first!".toByteArray(Charsets.UTF_8)
        val contentBytes = "second".toByteArray(Charsets.UTF_8)
        val offeredDigest = ByteString.copyFrom(sha256(offeredBytes))
        val contentDigest = ByteString.copyFrom(sha256(contentBytes))
        assertEquals(offeredBytes.size, contentBytes.size)

        session.receive(
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardOffer(
                    ClipboardOffer
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setByteLength(offeredBytes.size.toLong())
                        .setSha256(offeredDigest),
                ).build(),
        )
        assertNotNull(session.requestClipboard(hostChangeId))

        val content =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(11)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardContent(
                    ClipboardContent
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setContent(ByteString.copyFrom(contentBytes))
                        .setSha256(contentDigest),
                ).build()

        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(content) }
        assertEquals("invalid_peer_message", failure.reason)
    }

    @Test
    fun duplicateRequestForSameOfferIsSuppressed() {
        val session = clipboardSession()
        val hostChangeId = ByteString.copyFrom(ByteArray(16) { it.toByte() })
        val hostBytes = "x".toByteArray(Charsets.UTF_8)
        val hostSha = ByteString.copyFrom(sha256(hostBytes))

        session.receive(
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardOffer(
                    ClipboardOffer
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setByteLength(1L)
                        .setSha256(hostSha),
                ).build(),
        )

        val first = session.requestClipboard(hostChangeId)
        assertNotNull(first)
        // Second request for the same changeId while one is in flight returns null.
        val second = session.requestClipboard(hostChangeId)
        assertNull(second)
    }

    @Test
    fun expiredRequestCanBeRetriedForTheSameOffer() {
        val session = clipboardSession()
        val hostChangeId = ByteString.copyFrom(ByteArray(16) { (it + 3).toByte() })
        val hostBytes = "retry".toByteArray(Charsets.UTF_8)
        session.receive(
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardOffer(
                    ClipboardOffer
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setByteLength(hostBytes.size.toLong())
                        .setSha256(ByteString.copyFrom(sha256(hostBytes))),
                ).build(),
        )

        assertNotNull(session.requestClipboard(hostChangeId))
        assertFalse(session.expireClipboardRequest(ByteString.copyFrom(ByteArray(16))))
        assertTrue(session.expireClipboardRequest(hostChangeId))
        assertNotNull(session.requestClipboard(hostChangeId))
    }

    @Test
    fun duplicateOfferWithChangedMetadataFailsClosed() {
        val session = clipboardSession()
        val hostChangeId = ByteString.copyFrom(ByteArray(16) { it.toByte() })
        val firstBytes = "first".toByteArray(Charsets.UTF_8)
        val secondBytes = "second".toByteArray(Charsets.UTF_8)

        fun offer(messageId: Long, bytes: ByteArray): Envelope =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(messageId)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardOffer(
                    ClipboardOffer
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setByteLength(bytes.size.toLong())
                        .setSha256(ByteString.copyFrom(sha256(bytes))),
                ).build()

        session.receive(offer(10, firstBytes))
        val failure = assertThrows(ProtocolV1Failure::class.java) {
            session.receive(offer(11, secondBytes))
        }
        assertEquals("invalid_peer_message", failure.reason)
    }

    @Test
    fun loopbackOfferWithOurOwnChangeIdIsRejected() {
        val session = clipboardSession()
        val offerEnv = session.offerClipboard("loopback") ?: throw AssertionError("offer failed")
        val ourChangeId = offerEnv.clipboardOffer.changeId

        // Host echoes our changeId back as an offer.
        val loopback =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardOffer(
                    ClipboardOffer
                        .newBuilder()
                        .setChangeId(ourChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setByteLength(8L)
                        .setSha256(ByteString.copyFrom(ByteArray(32))),
                ).build()
        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(loopback) }
        assertEquals("invalid_peer_message", failure.reason)
    }

    @Test
    fun contentWithWrongOriginIsRejected() {
        val session = clipboardSession()
        val hostChangeId = ByteString.copyFrom(ByteArray(16) { it.toByte() })
        val bytes = "x".toByteArray(Charsets.UTF_8)

        val contentEnv =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardContent(
                    ClipboardContent
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId("not-the-host")
                        .setMimeType("text/plain")
                        .setContent(ByteString.copyFrom(bytes))
                        .setSha256(ByteString.copyFrom(sha256(bytes))),
                ).build()
        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(contentEnv) }
        assertEquals("invalid_peer_message", failure.reason)
    }

    @Test
    fun contentWithInvalidUtf8IsRejected() {
        val session = clipboardSession()
        val hostChangeId = ByteString.copyFrom(ByteArray(16) { it.toByte() })
        // 0xFF is never valid as the first byte of a UTF-8 sequence.
        val invalidBytes = byteArrayOf(0xFF.toByte(), 0xFE.toByte())

        val contentEnv =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardContent(
                    ClipboardContent
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setContent(ByteString.copyFrom(invalidBytes))
                        .setSha256(ByteString.copyFrom(sha256(invalidBytes))),
                ).build()
        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(contentEnv) }
        assertEquals("invalid_peer_message", failure.reason)
        assertTrue(failure.cause is CharacterCodingException)
    }

    @Test
    fun contentExceedingNegotiatedLimitIsRejected() {
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
        val session =
            ProtocolV1Session(
                deviceId = deviceId,
                deviceName = "Test",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC),
                nowNs = { 1_000L },
            )
        session.clientHello()
        session.receive(hostHello(2, caps, hostMaxClipboardBytes = 10L))
        session.receive(sessionAccepted(3, caps, acceptedMaxClipboardBytes = 10L))
        session.receive(displayList(4))
        session.receive(startDisplay(5))
        val requested = singleVideoConfigurationRequested(session.receive(videoConfig(6)))
        session.completeVideoConfiguration(3, requested.configurationToken, true, "")

        assertEquals(10L, session.negotiatedMaxClipboardBytes)

        val hostChangeId = ByteString.copyFrom(ByteArray(16) { it.toByte() })
        val tooBig = ByteArray(11) { 'a'.code.toByte() }
        val contentEnv =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardContent(
                    ClipboardContent
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setContent(ByteString.copyFrom(tooBig))
                        .setSha256(ByteString.copyFrom(sha256(tooBig))),
                ).build()
        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(contentEnv) }
        assertEquals("invalid_peer_message", failure.reason)
    }

    @Test
    fun acceptedLimitCannotExceedHostHelloLimit() {
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
        val session =
            ProtocolV1Session(
                deviceId = deviceId,
                deviceName = "Test",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC),
                nowNs = { 1_000L },
            )
        session.clientHello()
        // Host advertises 100 bytes but accepted tries to inflate to 500.
        session.receive(hostHello(2, caps, hostMaxClipboardBytes = 100L))
        session.receive(sessionAccepted(3, caps, acceptedMaxClipboardBytes = 500L))
        // Effective limit must be min(local 1MiB, hostHello 100, accepted 500) = 100.
        assertEquals(100L, session.negotiatedMaxClipboardBytes)
    }

    @Test
    fun zeroAcceptedLimitFallsBackToHostHelloOrLocal() {
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
        val session =
            ProtocolV1Session(
                deviceId = deviceId,
                deviceName = "Test",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC),
                nowNs = { 1_000L },
            )
        session.clientHello()
        session.receive(hostHello(2, caps, hostMaxClipboardBytes = 0L))
        session.receive(sessionAccepted(3, caps, acceptedMaxClipboardBytes = 0L))
        assertEquals(ProtocolV1Session.LOCAL_MAX_CLIPBOARD_BYTES, session.negotiatedMaxClipboardBytes)
    }

    @Test
    fun unmanagedRemotePolicyDoesNotDisableClipboard() {
        val session = clipboardSession()
        val status =
            ManagedPolicyStatus
                .newBuilder()
                .setManaged(false)
                .setClipboardAllowed(false)
                .build()
        val policy = base(10).setManagedPolicyStatus(status).build()

        val received = session.receive(policy).single() as ProtocolV1Session.Action.ManagedPolicyReceived
        assertEquals(status, received.status)
        assertTrue(session.canSendClipboard)
        assertNotNull(session.offerClipboard("still allowed"))
    }

    @Test
    fun managedPolicyStatusRequiresNegotiatedCapability() {
        val session = clipboardSessionWithoutManagedConfiguration()
        val status =
            ManagedPolicyStatus
                .newBuilder()
                .setManaged(false)
                .setClipboardAllowed(true)
                .build()
        val policy = base(10).setManagedPolicyStatus(status).build()

        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(policy) }

        assertEquals("invalid_peer_message", failure.reason)
        assertTrue(session.canSendClipboard)
    }

    @Test
    fun managedRemotePolicyDenyDisablesClipboardAndClearsSnapshot() {
        val session = clipboardSession()
        val offered = session.offerClipboard("before deny") ?: throw AssertionError("offer should succeed")
        val denied = managedPolicyStatus(clipboardAllowed = false)
        val policy = base(10).setManagedPolicyStatus(denied).build()

        val received = session.receive(policy).single() as ProtocolV1Session.Action.ManagedPolicyReceived
        assertEquals(denied, received.status)
        assertFalse(session.canSendClipboard)
        assertNull(session.offerClipboard("after deny"))
        assertNull(session.requestClipboard(offered.clipboardOffer.changeId))

        val request =
            base(11)
                .setClipboardRequest(ClipboardRequest.newBuilder().setChangeId(offered.clipboardOffer.changeId))
                .build()
        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(request) }
        assertEquals("invalid_peer_message", failure.reason)
    }

    @Test
    fun hostIdRequiredWhenClipboardNegotiated() {
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
        val session =
            ProtocolV1Session(
                deviceId = deviceId,
                deviceName = "Test",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC),
                nowNs = { 1_000L },
            )
        session.clientHello()
        session.receive(hostHello(2, caps, hostId = ""))
        val failure = assertThrows(ProtocolV1Failure::class.java) {
            session.receive(sessionAccepted(3, caps))
        }
        assertEquals("invalid_peer_message", failure.reason)
    }

    @Test
    fun directContentWithoutOfferIsPending() {
        val session = clipboardSession()
        val hostChangeId = ByteString.copyFrom(ByteArray(16) { it.toByte() })
        val bytes = "direct".toByteArray(Charsets.UTF_8)

        val contentEnv =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardContent(
                    ClipboardContent
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setContent(ByteString.copyFrom(bytes))
                        .setSha256(ByteString.copyFrom(sha256(bytes))),
                ).build()
        val actions = session.receive(contentEnv)
        val received = actions.single() as ProtocolV1Session.Action.ClipboardContentReceived
        assertTrue(received.pending)
    }

    @Test
    fun directContentDoesNotBlockLaterOfferWithSameChangeId() {
        val session = clipboardSession()
        val hostChangeId = ByteString.copyFrom(ByteArray(16) { (it + 1).toByte() })
        val bytes = "direct then offer".toByteArray(Charsets.UTF_8)
        val digest = ByteString.copyFrom(sha256(bytes))
        val direct =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(10)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardContent(
                    ClipboardContent
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setContent(ByteString.copyFrom(bytes))
                        .setSha256(digest),
                ).build()
        val directAction =
            session.receive(direct).single() as ProtocolV1Session.Action.ClipboardContentReceived
        assertTrue(directAction.pending)

        val offer =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(11)
                .setSessionId(sessionId)
                .setSessionEpoch(7)
                .setClipboardOffer(
                    ClipboardOffer
                        .newBuilder()
                        .setChangeId(hostChangeId)
                        .setOriginDeviceId(hostId)
                        .setMimeType("text/plain")
                        .setByteLength(bytes.size.toLong())
                        .setSha256(digest),
                ).build()

        val offered = session.receive(offer).single() as ProtocolV1Session.Action.ClipboardOffered
        assertEquals(hostChangeId, offered.changeId)
        assertNotNull(session.requestClipboard(hostChangeId))
    }

    private fun sha256(bytes: ByteArray): ByteArray =
        MessageDigest.getInstance("SHA-256").digest(bytes)

    private fun singleVideoConfigurationRequested(
        actions: List<ProtocolV1Session.Action>,
    ): ProtocolV1Session.Action.VideoConfigurationRequested =
        actions.filterIsInstance<ProtocolV1Session.Action.VideoConfigurationRequested>().single()

    private fun clipboardSessionWithoutManagedConfiguration(): ProtocolV1Session {
        val caps = clipboardCapabilities(managedConfiguration = false)
        val session =
            ProtocolV1Session(
                deviceId = deviceId,
                deviceName = "Test Android",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
                nowNs = { 1_000L },
            )
        session.clientHello()
        session.receive(hostHello(2, caps))
        session.receive(sessionAccepted(3, caps))
        session.receive(displayList(4))
        session.receive(startDisplay(5))
        val requested = singleVideoConfigurationRequested(session.receive(videoConfig(6)))
        session.completeVideoConfiguration(
            completedConfigEpoch = 3,
            configurationToken = requested.configurationToken,
            accepted = true,
            rejectionReason = "",
        )
        return session
    }

    private fun clipboardCapabilities(managedConfiguration: Boolean): List<Capability> {
        val capabilities = mutableListOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
        if (managedConfiguration) capabilities += Capability.CAPABILITY_MANAGED_CONFIGURATION
        return capabilities
    }

    private fun hostHello(
        id: Long,
        advertisedCapabilities: List<Capability>,
        hostId: String = this.hostId,
        hostMaxClipboardBytes: Long = 0L,
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
                        ResourceLimits.newBuilder().setMaximumClipboardBytes(hostMaxClipboardBytes),
                    ),
            ).build()

    private fun sessionAccepted(
        id: Long,
        negotiatedCapabilities: List<Capability>,
        acceptedMaxClipboardBytes: Long = 0L,
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
                        ResourceLimits.newBuilder().setMaximumClipboardBytes(acceptedMaxClipboardBytes),
                    ),
            ).build()

    private fun base(id: Long): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(sessionId)
            .setSessionEpoch(7)

    private fun managedPolicyStatus(
        clipboardAllowed: Boolean = true,
        fileTransferAllowed: Boolean = true,
        audioAllowed: Boolean = true,
        wakeAllowed: Boolean = true,
        customGesturesAllowed: Boolean = true,
        hostActionsAllowed: Boolean = true,
        maximumFileBytes: Long = 512L * 1_024L * 1_024L,
        allowedHosts: List<String> = listOf(hostId),
        allowedHostsRestricted: Boolean = true,
        deniedHosts: List<String> = emptyList(),
    ): ManagedPolicyStatus {
        val results =
            listOf(
                restrictionResult("clipboard", clipboardAllowed),
                restrictionResult("file_transfer", fileTransferAllowed),
                restrictionResult("audio", audioAllowed),
                restrictionResult("wake", wakeAllowed),
                restrictionResult("custom_gestures", customGesturesAllowed),
                restrictionResult("host_actions", hostActionsAllowed),
                restrictionResult("maximum_file_bytes", maximumFileBytes > 0L),
                restrictionResult("allowed_hosts", !allowedHostsRestricted || (allowedHosts.toSet() - deniedHosts.toSet()).isNotEmpty()),
                restrictionResult("denied_hosts", deniedHosts.isEmpty()),
            )
        return ManagedPolicyStatus
            .newBuilder()
            .setManaged(true)
            .setClipboardAllowed(clipboardAllowed)
            .setFileTransferAllowed(fileTransferAllowed)
            .setAudioAllowed(audioAllowed)
            .setWakeAllowed(wakeAllowed)
            .setCustomGesturesAllowed(customGesturesAllowed)
            .setHostActionsAllowed(hostActionsAllowed)
            .setMaximumFileBytes(maximumFileBytes)
            .addAllAllowedHosts(allowedHosts)
            .setAllowedHostsRestricted(allowedHostsRestricted)
            .addAllRestrictionResults(results)
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
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(sessionId)
            .setSessionEpoch(7)
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
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(sessionId)
            .setSessionEpoch(7)
            .setStartDisplayResponse(
                StartDisplayResponse.newBuilder().setAccepted(true).setStreamId(42),
            ).build()

    private fun videoConfig(id: Long): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(sessionId)
            .setSessionEpoch(7)
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
