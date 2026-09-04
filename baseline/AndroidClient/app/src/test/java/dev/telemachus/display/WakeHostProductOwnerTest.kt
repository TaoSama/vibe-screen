package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DisplayDescriptor
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.ListDisplaysResponse
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.StartDisplayResponse
import dev.vibescreen.protocol.v1.VideoConfig
import dev.vibescreen.protocol.v1.TransportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.SecureRandom
import java.util.concurrent.Executor
import java.util.concurrent.RejectedExecutionException

class WakeHostProductOwnerTest {
    @Test
    fun `completion command cannot be copied around one time claim state`() {
        val methods = StreamOutboundCommand.ProtocolWakeHostCompletion::class.java.methods.map { it.name }.toSet()

        assertFalse(methods.contains("copy"))
        assertFalse(methods.contains("copy\$default"))
    }

    @Test
    fun `wake host advertisement follows policy and authorization secret`() {
        val session = wakeHostStreamingSession()
        val denied = OwnerHarness(session = session, policy = StaticWakeHostPolicy(false))

        assertFalse(denied.owner.canAdvertiseWakeHost())

        denied.owner.setAuthorizationSecret(ByteArray(32) { it.toByte() })
        assertTrue(denied.owner.canAdvertiseWakeHost())

        denied.owner.clearAuthorizationSecret()
        assertFalse(denied.owner.canAdvertiseWakeHost())

        val allowed = OwnerHarness(session = session, policy = StaticWakeHostPolicy(true))
        assertTrue(allowed.owner.canAdvertiseWakeHost())
    }

    @Test
    fun `outbound requests require current v1 session and bind to original generation`() {
        val session = wakeHostStreamingSession()
        val harness = OwnerHarness(session = session)
        val requestId = ByteString.copyFrom(byteArrayOf(0x44))

        harness.connectedV1 = false
        assertFalse(harness.owner.request(requestId, TARGET_MAC))
        assertTrue(harness.submissions.isEmpty())

        harness.connectedV1 = true
        assertTrue(harness.owner.request(requestId = requestId, targetMacAddress = TARGET_MAC))
        val command = harness.singleProtocolBatch()

        val envelope = command.build(session).single()
        assertEquals(Envelope.PayloadCase.WAKE_HOST_REQUEST, envelope.payloadCase)
        assertEquals(requestId, envelope.wakeHostRequest.requestId)

        harness.submissions.clear()
        assertTrue(
            harness.owner.request(
                requestId = ByteString.copyFrom(byteArrayOf(0x45)),
                targetMacAddress = TARGET_MAC,
            ),
        )
        val staleCommand = harness.singleProtocolBatch()
        harness.advanceGeneration()
        assertTrue(staleCommand.build(session).isEmpty())
    }

    @Test
    fun `outbound request signs with authorization secret`() {
        val session = wakeHostStreamingSession()
        val harness = OwnerHarness(session = session, policy = StaticWakeHostPolicy(false))
        val secret = ByteArray(32) { it.toByte() }
        val requestId = ByteString.copyFrom(byteArrayOf(0x55))
        harness.owner.setAuthorizationSecret(secret.copyOf())

        assertTrue(
            harness.owner.request(
                requestId = requestId,
                targetMacAddress = TARGET_MAC,
                secureOnPassword = SECURE_ON_PASSWORD,
            ),
        )

        val wakeHostRequest = harness.singleProtocolBatch().build(session).single().wakeHostRequest
        assertEquals(requestId, wakeHostRequest.requestId)
        assertEquals(TARGET_MAC, wakeHostRequest.targetMacAddress)
        assertEquals(SECURE_ON_PASSWORD, wakeHostRequest.secureOnPassword)
        assertEquals("mac-host", wakeHostRequest.hostId)
        assertEquals("android-test", wakeHostRequest.deviceId)
        assertEquals(WakeHostProof.keyId(secret), wakeHostRequest.keyId)
        assertTrue(wakeHostRequest.issuedAtUnixSeconds > 0)
        assertEquals(wakeHostRequest.issuedAtUnixSeconds + 60, wakeHostRequest.expiresAtUnixSeconds)
        assertEquals(WakeHostProof.MINIMUM_NONCE_BYTES, wakeHostRequest.nonce.size())
        assertEquals(WakeHostProof.SIGNATURE_BYTES, wakeHostRequest.signature.size())
        val proofContext =
            WakeHostRequestContext(
                requestId = wakeHostRequest.requestId,
                targetMacAddress = wakeHostRequest.targetMacAddress,
                secureOnPassword = wakeHostRequest.secureOnPassword,
                hostId = wakeHostRequest.hostId,
                deviceId = wakeHostRequest.deviceId,
                keyId = wakeHostRequest.keyId,
                issuedAtUnixSeconds = wakeHostRequest.issuedAtUnixSeconds,
                expiresAtUnixSeconds = wakeHostRequest.expiresAtUnixSeconds,
                nonce = wakeHostRequest.nonce,
            )
        assertEquals(WakeHostProof.signature(proofContext, secret).toList(), wakeHostRequest.signature.toByteArray().toList())
    }

    @Test
    fun `inbound request sends one packet and queues accepted completion`() {
        val session = wakeHostStreamingSession()
        val sentPackets = mutableListOf<ByteArray>()
        val harness = OwnerHarness(
            session = session,
            packetSender = WakeHostPacketSender { sentPackets += it },
        )

        harness.owner.dispatchRequest(session, 1L, request(), correlationId = 7L)

        assertEquals(listOf(WakeHostMagicPacket.build(TARGET_MAC).toList()), sentPackets.map(ByteArray::toList))
        val completion = harness.singleCompletion()
        assertTrue(completion.accepted)
        assertEquals("", completion.rejectionReason)
        assertEquals(7L, completion.correlationId)
    }

    @Test
    fun `duplicate inbound requests fail closed without sending packet`() {
        val session = wakeHostStreamingSession()
        val sentPackets = mutableListOf<ByteArray>()
        val queued = mutableListOf<Runnable>()
        val harness = OwnerHarness(
            session = session,
            executor = Executor { queued += it },
            packetSender = WakeHostPacketSender { sentPackets += it },
        )
        val request = request()

        harness.owner.dispatchRequest(session, 1L, request, correlationId = 7L)
        harness.owner.dispatchRequest(session, 1L, request, correlationId = 8L)

        assertEquals(1, queued.size)
        assertTrue(sentPackets.isEmpty())
        val duplicate = harness.singleCompletion()
        assertFalse(duplicate.accepted)
        assertEquals("too_many_pending_wake_host_requests", duplicate.rejectionReason)
        assertEquals(8L, duplicate.correlationId)
    }

    @Test
    fun `queued inbound request after disconnect releases reservation without packet or result`() {
        val session = wakeHostStreamingSession()
        val sentPackets = mutableListOf<ByteArray>()
        val queued = mutableListOf<Runnable>()
        val harness = OwnerHarness(
            session = session,
            executor = Executor { queued += it },
            packetSender = WakeHostPacketSender { sentPackets += it },
        )

        harness.owner.dispatchRequest(session, 1L, request(), correlationId = 7L)
        harness.connectedV1 = false
        queued.single().run()

        assertTrue(sentPackets.isEmpty())
        assertTrue(harness.submissions.isEmpty())
        harness.connectedV1 = true
        assertTrue(harness.sessionOwner.trackWakeHostRequest(ByteString.copyFromUtf8("next"), session, harness.connectionGeneration))
    }

    @Test
    fun `sender failure queues rejection and later request can recover`() {
        val session = wakeHostStreamingSession()
        var failSend = true
        val sentPackets = mutableListOf<ByteArray>()
        val harness = OwnerHarness(
            session = session,
            packetSender = WakeHostPacketSender { packet ->
                if (failSend) error("boom")
                sentPackets += packet
            },
        )

        harness.owner.dispatchRequest(session, 1L, request(ByteString.copyFromUtf8("failed")), correlationId = 7L)

        val failure = harness.singleCompletion()
        assertFalse(failure.accepted)
        assertEquals("wake_packet_send_failed", failure.rejectionReason)
        assertTrue(harness.warnings.single().contains("WakeHost packet send failed"))

        harness.owner.complete(failure)
        failSend = false
        harness.submissions.clear()

        harness.owner.dispatchRequest(session, 1L, request(ByteString.copyFromUtf8("retry")), correlationId = 8L)

        assertEquals(1, sentPackets.size)
        assertTrue(harness.singleCompletion().accepted)
    }

    @Test
    fun `stale completion does not call callback and releases matching reservation`() {
        val session = wakeHostStreamingSession()
        val harness = OwnerHarness(session = session)
        val callbacks = mutableListOf<Pair<Boolean, String>>()
        harness.resultCallback = { accepted, reason -> callbacks += accepted to reason }
        val requestId = ByteString.copyFromUtf8("request")

        val generation = harness.connectionGeneration
        assertTrue(harness.sessionOwner.trackWakeHostRequest(requestId, session, generation))
        harness.connectedV1 = false

        harness.owner.deliverCompletion(session, generation, accepted = true, rejectionReason = "")

        assertTrue(callbacks.isEmpty())
        assertTrue(harness.owner.complete(completion(session, requestId, generation, accepted = true)) != null)
        harness.connectedV1 = true
        assertTrue(
            harness.sessionOwner.trackWakeHostRequest(
                ByteString.copyFromUtf8("after-stale"),
                session,
                generation,
            ),
        )
    }

    @Test
    fun `termination drain completion writes once and releases reservation`() {
        val session = wakeHostStreamingSession()
        val harness = OwnerHarness(session = session, maximumPendingWakeHostRequests = 1)
        val requestId = ByteString.copyFromUtf8("drain")
        val generation = harness.connectionGeneration
        assertTrue(harness.sessionOwner.trackWakeHostRequest(requestId, session, generation))

        harness.sessionOwner.markTerminationClaimed(SessionFailure.transport("ending"))
        harness.sessionOwner.clearSideEffectAdmission()

        val envelope = checkNotNull(harness.owner.complete(completion(session, requestId, generation, accepted = true)))
        assertEquals(Envelope.PayloadCase.WAKE_HOST_RESULT, envelope.payloadCase)
        assertEquals(requestId, envelope.wakeHostResult.requestId)
        assertTrue(envelope.wakeHostResult.accepted)
        assertNull(harness.owner.complete(completion(session, requestId, generation, accepted = true)))
    }

    @Test
    fun `capacity rejection completion writes without reservation and does not release active request`() {
        val session = wakeHostStreamingSession()
        val queued = mutableListOf<Runnable>()
        val harness = OwnerHarness(
            session = session,
            maximumPendingWakeHostRequests = 1,
            executor = Executor { queued += it },
        )
        val firstRequestId = ByteString.copyFromUtf8("first")
        val rejectedRequestId = ByteString.copyFromUtf8("second")
        val generation = harness.connectionGeneration

        harness.owner.dispatchRequest(session, generation, request(firstRequestId), correlationId = 7L)
        harness.owner.dispatchRequest(session, generation, request(rejectedRequestId), correlationId = 8L)

        assertEquals(1, queued.size)
        val rejection = harness.singleCompletion()
        assertFalse(rejection.requiresTrackedReservation)
        assertEquals(rejectedRequestId, rejection.requestId)
        assertFalse(rejection.accepted)
        assertEquals("too_many_pending_wake_host_requests", rejection.rejectionReason)

        val envelope = checkNotNull(harness.owner.complete(rejection))
        assertEquals(Envelope.PayloadCase.WAKE_HOST_RESULT, envelope.payloadCase)
        assertEquals(rejectedRequestId, envelope.wakeHostResult.requestId)
        assertFalse(envelope.wakeHostResult.accepted)
        assertEquals("too_many_pending_wake_host_requests", envelope.wakeHostResult.rejectionReason)
        assertEquals(8L, envelope.correlationId)
        assertNull(harness.owner.complete(rejection))

        assertFalse(
            harness.sessionOwner.trackWakeHostRequest(
                ByteString.copyFromUtf8("still-full"),
                session,
                generation,
            ),
        )

        harness.submissions.clear()
        queued.single().run()
        val accepted = harness.singleCompletion()
        assertTrue(accepted.requiresTrackedReservation)
        assertTrue(checkNotNull(harness.owner.complete(accepted)).wakeHostResult.accepted)
        assertTrue(
            harness.sessionOwner.trackWakeHostRequest(
                ByteString.copyFromUtf8("after-first-release"),
                session,
                generation,
            ),
        )
    }

    @Test
    fun `managed policy deny completes queued inbound request and suppresses stale executor work`() {
        val session = wakeHostStreamingSession(managedConfiguration = true)
        val sentPackets = mutableListOf<ByteArray>()
        val queued = mutableListOf<Runnable>()
        val harness = OwnerHarness(
            session = session,
            executor = Executor { queued += it },
            packetSender = WakeHostPacketSender { sentPackets += it },
        )
        val requestId = ByteString.copyFromUtf8("policy-denied")
        val generation = harness.connectionGeneration

        harness.owner.dispatchRequest(session, generation, request(requestId), correlationId = 17L)
        assertEquals(1, queued.size)

        removeWakeCapabilityByManagedPolicy(session)
        harness.owner.cancelPendingForPolicyDeny(session, generation)

        val denial = harness.singleCompletion()
        assertFalse(denial.requiresTrackedReservation)
        assertTrue(denial.allowAfterWakeCapabilityRemoval)
        assertEquals(requestId, denial.requestId)
        assertFalse(denial.accepted)
        assertEquals("managed_policy_denied", denial.rejectionReason)
        assertEquals(17L, denial.correlationId)

        val envelope = checkNotNull(harness.owner.complete(denial))
        assertEquals(Envelope.PayloadCase.WAKE_HOST_RESULT, envelope.payloadCase)
        assertEquals(requestId, envelope.wakeHostResult.requestId)
        assertFalse(envelope.wakeHostResult.accepted)
        assertEquals("managed_policy_denied", envelope.wakeHostResult.rejectionReason)
        assertEquals(17L, envelope.correlationId)
        assertNull(harness.owner.complete(denial))

        harness.submissions.clear()
        queued.single().run()

        assertTrue(sentPackets.isEmpty())
        assertTrue(harness.submissions.isEmpty())
        assertTrue(harness.sessionOwner.trackWakeHostRequest(ByteString.copyFromUtf8("next"), session, generation))
    }

    @Test
    fun `stale capacity rejection completion is dropped even without reservation`() {
        val session = wakeHostStreamingSession()
        val queued = mutableListOf<Runnable>()
        val harness = OwnerHarness(
            session = session,
            maximumPendingWakeHostRequests = 1,
            executor = Executor { queued += it },
        )
        val generation = harness.connectionGeneration

        harness.owner.dispatchRequest(session, generation, request(ByteString.copyFromUtf8("first")), correlationId = 7L)
        harness.owner.dispatchRequest(session, generation, request(ByteString.copyFromUtf8("second")), correlationId = 8L)

        val rejection = harness.singleCompletion()
        assertFalse(rejection.requiresTrackedReservation)
        harness.advanceGeneration()

        assertNull(harness.owner.complete(rejection))
    }

    @Test
    fun `stale generation completion rejects but releases reservation`() {
        val session = wakeHostStreamingSession()
        val harness = OwnerHarness(session = session, maximumPendingWakeHostRequests = 1)
        val requestId = ByteString.copyFromUtf8("old-generation")
        val oldGeneration = harness.connectionGeneration
        assertTrue(harness.sessionOwner.trackWakeHostRequest(requestId, session, oldGeneration))

        harness.advanceGeneration()

        assertNull(harness.owner.complete(completion(session, requestId, oldGeneration, accepted = true)))
        assertTrue(harness.sessionOwner.trackWakeHostRequest(requestId, session, harness.connectionGeneration))
    }

    @Test
    fun `tracked completion envelope requires reservation and releases it exactly once`() {
        val session = wakeHostStreamingSession()
        val harness = OwnerHarness(session = session, maximumPendingWakeHostRequests = 1)
        val requestId = ByteString.copyFromUtf8("tracked")
        val generation = harness.connectionGeneration
        assertTrue(harness.sessionOwner.trackWakeHostRequest(requestId, session, generation))
        val completion = completion(session, requestId, generation, accepted = true)

        val envelope = checkNotNull(harness.owner.complete(completion))
        assertEquals(Envelope.PayloadCase.WAKE_HOST_RESULT, envelope.payloadCase)
        assertTrue(envelope.wakeHostResult.accepted)
        assertNull(harness.owner.complete(completion))

        assertTrue(
            harness.sessionOwner.trackWakeHostRequest(
                ByteString.copyFromUtf8("after-release"),
                session,
                generation,
            ),
        )
        assertNull(harness.owner.complete(completion(session, requestId, generation, accepted = true)))
    }

    @Test
    fun `new wake host side effects fail closed after admission closes`() {
        val session = wakeHostStreamingSession()
        val sentPackets = mutableListOf<ByteArray>()
        val harness = OwnerHarness(
            session = session,
            packetSender = WakeHostPacketSender { sentPackets += it },
        )
        val generation = harness.connectionGeneration

        harness.sessionOwner.markTerminationClaimed(SessionFailure.transport("ending"))
        harness.sessionOwner.clearSideEffectAdmission()

        assertFalse(harness.sessionOwner.trackWakeHostRequest(ByteString.copyFromUtf8("blocked"), session, generation))
        harness.owner.dispatchRequest(session, generation, request(ByteString.copyFromUtf8("dispatch")), correlationId = 9L)
        assertTrue(sentPackets.isEmpty())
        assertTrue(harness.submissions.isEmpty())
    }

    @Test
    fun `executor rejection fails closed and releases request`() {
        val session = wakeHostStreamingSession()
        val harness = OwnerHarness(
            session = session,
            executor = Executor { throw RejectedExecutionException("closed") },
        )

        harness.owner.dispatchRequest(session, 1L, request(), correlationId = 7L)

        val completion = harness.singleCompletion()
        assertFalse(completion.accepted)
        assertEquals("wake_host_dispatch_failed", completion.rejectionReason)
        assertTrue(harness.sessionOwner.trackWakeHostRequest(ByteString.copyFromUtf8("next"), session, harness.connectionGeneration))
    }

    @Test
    fun `capacity rejection backpressures unavailable completion queue`() {
        val session = wakeHostStreamingSession()
        val failures = mutableListOf<SessionFailure>()
        val queued = mutableListOf<Runnable>()
        val harness = OwnerHarness(
            session = session,
            maximumPendingWakeHostRequests = 1,
            executor = Executor { queued += it },
            submit = { _, _, _ -> OutboundCommandScheduler.Submission.TIMED_OUT },
            onConnectionEnd = failures::add,
        )

        harness.owner.dispatchRequest(session, 1L, request(ByteString.copyFromUtf8("first")), correlationId = 7L)
        harness.owner.dispatchRequest(session, 1L, request(ByteString.copyFromUtf8("second")), correlationId = 8L)

        assertEquals(SessionFailureKind.OUTBOUND_BACKPRESSURE, failures.single().kind)
    }

    private class OwnerHarness(
        private val session: ProtocolV1Session,
        maximumPendingWakeHostRequests: Int = StreamProtocolSideEffectOwner.DEFAULT_MAXIMUM_PENDING_WAKE_HOST_REQUESTS,
        policy: WakeHostPolicy = StaticWakeHostPolicy(true),
        executor: Executor = Executor { it.run() },
        packetSender: WakeHostPacketSender = WakeHostPacketSender {},
        submit: ((OutboundCommandScheduler.Kind, StreamOutboundCommand, Long) -> OutboundCommandScheduler.Submission)? = null,
        onConnectionEnd: (SessionFailure) -> Unit = {},
    ) {
        var resultCallback: ((Boolean, String) -> Unit)? = null
        val submissions = mutableListOf<StreamOutboundCommand>()
        val warnings = mutableListOf<String>()
        val sessionOwner = StreamProtocolSessionOwner(
            maximumPendingWakeHostRequests = maximumPendingWakeHostRequests,
        ).also {
            it.beginSession()
            it.activate(session)
            it.markConnected()
        }
        var connectedV1 = true
            set(value) {
                field = value
                if (value) {
                    sessionOwner.markConnected()
                } else {
                    sessionOwner.markDisconnected()
                }
            }
        val connectionGeneration: Long
            get() = sessionOwner.connectionGeneration
        val owner = WakeHostProductOwner(
            executor = executor,
            policy = policy,
            packetSender = packetSender,
            sessionOwner = sessionOwner,
            requestIdRandom = SecureRandom(ByteArray(16)),
            isConnectedV1 = { connectedV1 },
            submitOutbound = submit ?: { _, command, _ ->
                submissions += command
                OutboundCommandScheduler.Submission.ACCEPTED
            },
            isOutboundAdmitted = { submission ->
                submission != OutboundCommandScheduler.Submission.TIMED_OUT &&
                    submission != OutboundCommandScheduler.Submission.CLOSED
            },
            requestConnectionEnd = onConnectionEnd,
            logWarning = { message, _ -> warnings += message },
            onResult = { resultCallback },
            protocolActionTimeoutMs = 2_000L,
        )

        fun singleProtocolBatch(): StreamOutboundCommand.ProtocolBatch =
            submissions.single() as StreamOutboundCommand.ProtocolBatch

        fun singleCompletion(): StreamOutboundCommand.ProtocolWakeHostCompletion =
            submissions.single() as StreamOutboundCommand.ProtocolWakeHostCompletion

        fun advanceGeneration() {
            sessionOwner.beginSession()
            sessionOwner.activate(session)
            sessionOwner.markConnected()
        }
    }

    private fun request(requestId: ByteString = ByteString.copyFromUtf8("request")): WakeHostRequestContext =
        WakeHostRequestContext(
            requestId = requestId,
            targetMacAddress = TARGET_MAC,
        )

    private fun completion(
        session: ProtocolV1Session,
        requestId: ByteString,
        connectionGeneration: Long,
        accepted: Boolean,
    ): StreamOutboundCommand.ProtocolWakeHostCompletion =
        StreamOutboundCommand.ProtocolWakeHostCompletion(
            session = session,
            connectionGeneration = connectionGeneration,
            requestId = requestId,
            accepted = accepted,
            rejectionReason = if (accepted) "" else "wake_host_policy_denied",
            correlationId = 7L,
        )

    private fun wakeHostStreamingSession(managedConfiguration: Boolean = false): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-test",
            deviceName = "Test Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
            advertiseWakeHost = true,
            nowNs = { 1_000L },
        ).also { session ->
            session.clientHello()
            session.receive(hostHello(2, managedConfiguration))
            session.receive(sessionAccepted(3, managedConfiguration))
            var nextMessageId = 4L
            if (managedConfiguration) {
                session.receive(
                    base(nextMessageId++)
                        .setManagedPolicyStatus(managedWakeHostAllowedStatus())
                        .build(),
                )
            }
            session.receive(displayList(nextMessageId++))
            session.receive(startDisplay(nextMessageId++))
            val requested =
                session.receive(videoConfig(nextMessageId))
                    .filterIsInstance<ProtocolV1Session.Action.VideoConfigurationRequested>()
                    .single()
            session.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }

    private fun removeWakeCapabilityByManagedPolicy(session: ProtocolV1Session) {
        session.receive(base(99).setManagedPolicyStatus(managedWakeHostAllowedStatus(wakeAllowed = false)).build())
    }

    private fun managedWakeHostAllowedStatus(wakeAllowed: Boolean = true) =
        ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            wakeAllowed = wakeAllowed,
        ).toStatus()

    private fun hostHello(
        id: Long,
        managedConfiguration: Boolean = false,
    ): Envelope =
        Envelope.newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setHostHello(
                HostHello.newBuilder()
                    .setSelectedProtocol(1)
                    .setHostId("mac-host")
                    .addAllCapabilities(wakeHostCapabilities(managedConfiguration))
                    .addAllCodecs(listOf(Codec.CODEC_HEVC, Codec.CODEC_H264)),
            ).build()

    private fun sessionAccepted(
        id: Long,
        managedConfiguration: Boolean = false,
    ): Envelope =
        Envelope.newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionAccepted(
                SessionAccepted.newBuilder()
                    .setSessionId(ByteString.copyFromUtf8("session"))
                    .setSessionEpoch(7)
                    .setHeartbeatIntervalMs(1_000)
                    .addAllNegotiatedCapabilities(wakeHostCapabilities(managedConfiguration)),
            ).build()

    private fun displayList(id: Long): Envelope =
        base(id)
            .setListDisplaysResponse(
                ListDisplaysResponse.newBuilder()
                    .addDisplays(
                        DisplayDescriptor.newBuilder()
                            .setDisplayId("display-main")
                            .setLogicalSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080)),
                    ),
            ).build()

    private fun startDisplay(id: Long): Envelope =
        base(id)
            .setStartDisplayResponse(
                StartDisplayResponse.newBuilder()
                    .setAccepted(true)
                    .setStreamId(42),
            ).build()

    private fun videoConfig(id: Long): Envelope =
        base(id)
            .setVideoConfig(
                VideoConfig.newBuilder()
                    .setCodec(Codec.CODEC_HEVC)
                    .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                    .setFramesPerSecond(60)
                    .setBitrateKbps(12_000)
                    .setRotationDegrees(0)
                    .setStreamId(42)
                    .setConfigEpoch(3),
            ).build()

    private fun base(id: Long): Envelope.Builder =
        Envelope.newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(ByteString.copyFromUtf8("session"))
            .setSessionEpoch(7)

    private companion object {
        val TARGET_MAC: ByteString = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4, 5, 6))
        val SECURE_ON_PASSWORD: ByteString = ByteString.copyFrom(byteArrayOf(6, 5, 4, 3, 2, 1))
        val WAKE_HOST_CAPABILITIES: List<Capability> =
            listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_WAKE_HOST)

        fun wakeHostCapabilities(managedConfiguration: Boolean): List<Capability> =
            if (managedConfiguration) {
                WAKE_HOST_CAPABILITIES + Capability.CAPABILITY_MANAGED_CONFIGURATION
            } else {
                WAKE_HOST_CAPABILITIES
            }
    }
}
