package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.telemachus.display.ControllerAxes
import dev.telemachus.display.ControllerEventKind
import dev.telemachus.display.ControllerStateSample
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DisconnectNotice
import dev.vibescreen.protocol.v1.DisplayDescriptor
import dev.vibescreen.protocol.v1.DisplayChanged
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostActionCatalog
import dev.vibescreen.protocol.v1.HostActionDescriptor
import dev.vibescreen.protocol.v1.HostActionResult
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.InputAck
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.ListDisplaysResponse
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.Ping
import dev.vibescreen.protocol.v1.ProtocolError
import dev.vibescreen.protocol.v1.ProtocolErrorCode
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.SessionRejected
import dev.vibescreen.protocol.v1.StartDisplayResponse
import dev.vibescreen.protocol.v1.TransportKind
import dev.vibescreen.protocol.v1.VideoConfig
import dev.vibescreen.protocol.v1.VideoQualityPreset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolV1SessionTest {
    @Test
    fun clientHelloPinsVersionAndExactProductionCapabilities() {
        val session = session()
        val hello = session.clientHello()

        assertEquals(1, hello.protocolVersion)
        assertEquals(1L, hello.messageId)
        assertEquals(1_000L, hello.sentAtMonotonicNs)
        assertEquals(1, hello.clientHello.supportedProtocols.minimum)
        assertEquals(1, hello.clientHello.supportedProtocols.maximum)
        assertEquals(
            listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_KEYBOARD,
                Capability.CAPABILITY_POINTER,
                Capability.CAPABILITY_STYLUS,
                Capability.CAPABILITY_STYLUS_EXTENDED,
                Capability.CAPABILITY_MULTI_DISPLAY,
                Capability.CAPABILITY_CLIENT_VIDEO_CONTROL,
                Capability.CAPABILITY_HOST_ACTIONS,
                Capability.CAPABILITY_USB_HID_MODIFIER_BYTE,
                Capability.CAPABILITY_CLIPBOARD,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            ),
            hello.clientHello.capabilitiesList,
        )
        assertEquals(emptyList<Capability>(), hello.clientHello.requiredCapabilitiesList)
        assertEquals(listOf(Codec.CODEC_HEVC, Codec.CODEC_H264), hello.clientHello.codecsList)
    }

    @Test
    fun hostModifierCapabilityWithoutKeyboardFailsDependencyValidation() {
        val session = session()
        session.clientHello()
        val failure =
            assertThrows(ProtocolV1Failure::class.java) {
                session.receive(
                    hostHello(
                        2,
                        advertisedCapabilities =
                            listOf(
                                Capability.CAPABILITY_TOUCH,
                                Capability.CAPABILITY_USB_HID_MODIFIER_BYTE,
                            ),
                    ),
                )
            }
        assertEquals(ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION, failure.source)
        assertFalse(failure.retryable)
    }

    @Test
    fun managedPolicyAppliesDenyWinsAndAllowedHosts() {
        val local =
            ProtocolV1Session.ManagedPolicy(
                isManaged = true,
                clipboardAllowed = true,
                fileTransferAllowed = true,
                audioAllowed = true,
                wakeAllowed = true,
                customGesturesAllowed = true,
                hostActionsAllowed = true,
                maximumFileBytes = 4_096,
                allowedHosts = setOf("host", "other"),
            )
        val remote =
            ManagedPolicyStatus
                .newBuilder()
                .setManaged(true)
                .setClipboardAllowed(false)
                .setFileTransferAllowed(true)
                .setAudioAllowed(false)
                .setWakeAllowed(true)
                .setCustomGesturesAllowed(true)
                .setHostActionsAllowed(false)
                .setMaximumFileBytes(1_024)
                .addAllowedHosts("host")
                .build()

        val effective = local.applying(ProtocolV1Session.ManagedPolicy.fromStatus(remote))

        assertFalse(effective.clipboardAllowed)
        assertTrue(effective.fileTransferAllowed)
        assertFalse(effective.audioAllowed)
        assertTrue(effective.wakeAllowed)
        assertTrue(effective.customGesturesAllowed)
        assertFalse(effective.hostActionsAllowed)
        assertEquals(1_024, effective.maximumFileBytes)
        assertEquals(setOf("host"), effective.allowedHosts)
        assertTrue(effective.allowsHost("host"))
        assertFalse(effective.allowsHost("other"))
    }

    @Test
    fun disjointAllowedHostsDenyAllHosts() {
        val local =
            ProtocolV1Session.ManagedPolicy(
                isManaged = true,
                clipboardAllowed = true,
                fileTransferAllowed = true,
                audioAllowed = true,
                wakeAllowed = true,
                customGesturesAllowed = true,
                hostActionsAllowed = true,
                maximumFileBytes = 4_096,
                allowedHosts = setOf("local-host"),
            )
        val remote =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.toStatus()
                .toBuilder()
                .setManaged(true)
                .addAllowedHosts("remote-host")
                .build()

        val effective = local.applying(ProtocolV1Session.ManagedPolicy.fromStatus(remote))

        assertTrue(effective.allowedHostsRestricted)
        assertTrue(effective.allowedHosts.isEmpty())
        assertFalse(effective.allowsHost("local-host"))
        assertFalse(effective.allowsHost("remote-host"))
    }

    @Test
    fun managedRemoteStatusWithUnsetFieldsFailsClosed() {
        val policy =
            ProtocolV1Session.ManagedPolicy.fromStatus(
                ManagedPolicyStatus.newBuilder().setManaged(true).build(),
            )

        assertTrue(policy.isManaged)
        assertFalse(policy.clipboardAllowed)
        assertFalse(policy.fileTransferAllowed)
        assertFalse(policy.audioAllowed)
        assertFalse(policy.wakeAllowed)
        assertFalse(policy.customGesturesAllowed)
        assertFalse(policy.hostActionsAllowed)
        assertEquals(0, policy.maximumFileBytes)
        assertTrue(policy.allowedHosts.isEmpty())
    }

    @Test
    fun hostActionCatalogBeforeStreamingIsCachedAndFilteredToKnownIds() {
        val session = hostActionSessionThroughDisplayStart()
        // Catalog arrives after SessionAccepted, before the first VideoConfig
        // commits, so the session is negotiated but not yet streaming.
        val descriptors =
            listOf(
                HostActionDescriptor.newBuilder().setActionId("move-window").setLocalizedName("Move").build(),
                HostActionDescriptor.newBuilder().setActionId("unknown-action").setLocalizedName("Nope").build(),
                HostActionDescriptor.newBuilder().setActionId("return-windows").build(),
            )
        val actions =
            session.receive(hostActionCatalog(6, descriptors)).single()
                as ProtocolV1Session.Action.HostActionsAvailable
        assertEquals(listOf("move-window", "return-windows"), actions.actions.map { it.id })
        assertEquals(listOf("move-window", "return-windows"), session.hostActions.map { it.id })
    }

    @Test
    fun hostActionCatalogDeduplicatesRepeatedActionIds() {
        val session = hostActionStreamingSession()
        val descriptors =
            listOf(
                HostActionDescriptor.newBuilder().setActionId("move-window").setLocalizedName("First").build(),
                HostActionDescriptor.newBuilder().setActionId("move-window").setLocalizedName("Second").build(),
            )
        val actions =
            session.receive(hostActionCatalog(7, descriptors)).single()
                as ProtocolV1Session.Action.HostActionsAvailable
        assertEquals(listOf("move-window"), actions.actions.map { it.id })
        assertEquals("First", actions.actions.single().localizedName)
    }

    @Test
    fun invokeHostActionSendsInvokeAndResultIsCorrelated() {
        val session = hostActionStreamingSession()
        session.receive(hostActionCatalog(7))
        assertTrue(session.canInvokeHostActions)
        val invocationId = ByteString.copyFrom(byteArrayOf(9, 8, 7, 6))
        val envelope = session.invokeHostAction("move-window", invocationId)!!
        assertEquals("move-window", envelope.hostActionInvoke.actionId)
        assertEquals(invocationId, envelope.hostActionInvoke.invocationId)
        val completed =
            session.receive(hostActionResult(8, invocationId, accepted = true)).single()
                as ProtocolV1Session.Action.HostActionCompleted
        assertTrue(completed.accepted)
        assertEquals(invocationId, completed.invocationId)
    }

    @Test
    fun invokeHostActionRejectsUnknownIdAndNonStreaming() {
        val streaming = hostActionStreamingSession()
        streaming.receive(hostActionCatalog(7))
        val id = ByteString.copyFrom(byteArrayOf(1, 1))
        assertNull(streaming.invokeHostAction("not-advertised", id))
        // Before streaming the session cannot invoke even a known action.
        val negotiated = hostActionSessionThroughDisplayStart()
        negotiated.receive(hostActionCatalog(6))
        assertFalse(negotiated.canInvokeHostActions)
        assertNull(negotiated.invokeHostAction("move-window", id))
    }

    @Test
    fun hostActionResultForUnknownInvocationIsIgnored() {
        val session = hostActionStreamingSession()
        session.receive(hostActionCatalog(7))
        val unsolicited = ByteString.copyFrom(byteArrayOf(4, 2))
        // A result with no matching sent invocation is never surfaced to UI.
        assertTrue(session.receive(hostActionResult(8, unsolicited)).isEmpty())
    }

    @Test
    fun hostActionResultConsumesPendingSoDuplicateIsIgnored() {
        val session = hostActionStreamingSession()
        session.receive(hostActionCatalog(7))
        val invocationId = ByteString.copyFrom(byteArrayOf(5, 5, 5))
        session.invokeHostAction("return-windows", invocationId)
        session.receive(hostActionResult(8, invocationId))
        // The pending id was consumed; a replayed result is now an authenticated no-op.
        assertTrue(session.receive(hostActionResult(9, invocationId)).isEmpty())
    }

    @Test
    fun hostActionCatalogWithoutNegotiatedCapabilityFails() {
        val session = streamingSession()
        assertInvalidPeerMessage { session.receive(hostActionCatalog(7)) }
    }

    @Test
    fun handshakeDisplayAndVideoReachStreamingWithHostEpoch() {
        val session = session()
        session.clientHello()
        assertTrue(session.receive(hostHello(2)).isEmpty())
        val listRequest = session.receive(sessionAccepted(3)).single() as ProtocolV1Session.Action.Send
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, listRequest.envelope.payloadCase)
        assertEquals(SESSION_ID, listRequest.envelope.sessionId)
        assertEquals(7L, listRequest.envelope.sessionEpoch)

        val displayActions = session.receive(displayList(4))
        val available = displayActions[0] as ProtocolV1Session.Action.DisplaysAvailable
        assertEquals(listOf("display-main"), available.displays.map { it.id })
        assertEquals("display-main", available.selectedId)
        val start = displayActions[1] as ProtocolV1Session.Action.Send
        assertEquals("display-main", start.envelope.startDisplayRequest.sourceDisplayId)
        assertTrue(session.receive(startDisplay(5)).isEmpty())

        val requested = session.receive(videoConfig(6)).single() as ProtocolV1Session.Action.VideoConfigurationRequested
        assertEquals(1920, requested.width)
        assertEquals(1080, requested.height)
        assertEquals(90, requested.rotation)
        assertEquals(3L, requested.configEpoch)
        assertEquals(7L, requested.sessionEpoch)
        assertEquals(12_000, requested.bitrateKbps)
        assertEquals(60, requested.framesPerSecond)
        assertFalse(session.isStreaming)
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION,
            session.validateMedia(mediaHeader()),
        )

        val actions =
            session.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        val result = actions[0] as ProtocolV1Session.Action.Send
        val keyframe = actions[1] as ProtocolV1Session.Action.Send
        val committed = actions[2] as ProtocolV1Session.Action.VideoConfigurationCommitted
        val geometry = actions[3] as ProtocolV1Session.Action.DisplayGeometryChanged
        assertTrue(result.envelope.videoConfigResult.accepted)
        assertEquals(6L, result.envelope.correlationId)
        assertEquals(Envelope.PayloadCase.REQUEST_KEYFRAME, keyframe.envelope.payloadCase)
        assertEquals(3L, committed.configEpoch)
        assertFalse(committed.appliesClientVideoPreferences)
        assertEquals(1920, geometry.width)
        assertEquals(1080, geometry.height)
        assertEquals(90, geometry.rotation)
        assertTrue(session.isStreaming)
    }

    @Test
    fun runtimeDisplayChangeCarriesRotationWithoutReconfiguringMedia() {
        val session = streamingSession()
        val action =
            session.receive(
                base(7)
                    .setDisplayChanged(
                        DisplayChanged
                            .newBuilder()
                            .setDisplay(
                                DisplayDescriptor
                                    .newBuilder()
                                    .setDisplayId("display-main")
                                    .setLogicalSize(Dimensions.newBuilder().setWidth(1080).setHeight(1920)),
                            ).setRotationDegrees(270),
                    ).build(),
            ).single() as ProtocolV1Session.Action.DisplayGeometryChanged

        assertEquals(1080, action.width)
        assertEquals(1920, action.height)
        assertEquals(270, action.rotation)
        session.validateMedia(mediaHeader())
    }

    @Test
    fun staleVideoConfigEpochIsRejectedWithoutAReconfigurationAction() {
        val session = streamingSession()

        val actions = session.receive(videoConfig(id = 7, configEpoch = 3))
        val result = actions.single() as ProtocolV1Session.Action.Send

        assertFalse(result.envelope.videoConfigResult.accepted)
        assertEquals(3L, result.envelope.videoConfigResult.configEpoch)
    }

    @Test
    fun reconfigurationDropsPendingAndRetiredEpochsUntilNewKeyframe() {
        val session = streamingSession()
        assertEquals(
            ProtocolV1Session.MediaDisposition.ACCEPT,
            session.validateMedia(mediaHeader(frameId = 1)),
        )

        val requested =
            session.receive(videoConfig(id = 7, configEpoch = 4)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION,
            session.validateMedia(mediaHeader(configEpoch = 3, frameId = 2)),
        )
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION,
            session.validateMedia(mediaHeader(configEpoch = 4, frameId = 1)),
        )

        session.completeVideoConfiguration(
            completedConfigEpoch = 4,
            configurationToken = requested.configurationToken,
            accepted = true,
            rejectionReason = "",
        )
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_RETIRED_CONFIGURATION,
            session.validateMedia(mediaHeader(configEpoch = 3, frameId = 2)),
        )
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_AWAITING_KEYFRAME,
            session.validateMedia(mediaHeader(configEpoch = 4, frameId = 1, keyframe = false)),
        )
        assertEquals(
            ProtocolV1Session.MediaDisposition.ACCEPT,
            session.validateMedia(mediaHeader(configEpoch = 4, frameId = 2, keyframe = true)),
        )
    }

    @Test
    fun staleDecoderCompletionProducesNoAckAndLeavesPendingRequestIntact() {
        val session = sessionThroughDisplayStart()
        val requested =
            session.receive(videoConfig(6)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested

        assertTrue(
            session.completeVideoConfiguration(
                completedConfigEpoch = 99,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            ).isEmpty(),
        )
        assertTrue(
            session.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken + 1,
                accepted = true,
                rejectionReason = "",
            ).isEmpty(),
        )
        assertFalse(session.isStreaming)
        val completion =
            session.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        assertTrue((completion.first() as ProtocolV1Session.Action.Send).envelope.videoConfigResult.accepted)
    }

    @Test
    fun disconnectNoticeInvalidatesPendingVideoConfigurationAndLateCompletion() {
        val session = sessionThroughDisplayStart()
        val requested =
            session.receive(videoConfig(6)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested

        val disconnected =
            session.receive(
                base(7)
                    .setDisconnectNotice(
                        DisconnectNotice.newBuilder().setReasonCode("host_shutdown").setMayResume(false),
                    ).build(),
            ).single()
        assertTrue(disconnected is ProtocolV1Session.Action.Disconnected)
        assertTrue(
            session.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            ).isEmpty(),
        )
        assertFalse(session.isStreaming)
        assertFalse(session.canSendTouch)
        assertInvalidMediaHeader { session.validateMedia(mediaHeader()) }
    }

    @Test
    fun displayChangeForAnotherDisplayIsRejected() {
        val session = streamingSession()
        val changed =
            DisplayChanged
                .newBuilder()
                .setDisplay(
                    DisplayDescriptor
                        .newBuilder()
                        .setDisplayId("stale-display")
                        .setLogicalSize(Dimensions.newBuilder().setWidth(1080).setHeight(1920)),
                ).setRotationDegrees(270)

        assertInvalidPeerMessage {
            session.receive(base(7).setDisplayChanged(changed).build())
        }
    }

    @Test
    fun rejectsVersionSessionEpochAndUnexpectedPayload() {
        val wrongVersion = session().also { it.clientHello() }
        assertInvalidPeerMessage {
            wrongVersion.receive(hostHello(2).toBuilder().setProtocolVersion(2).build())
        }

        val active = streamingSession()
        assertInvalidPeerMessage {
            active.receive(
                Envelope.newBuilder(videoConfig(7)).setSessionEpoch(6).build(),
            )
        }

        val missingPayload = session().also { it.clientHello() }
        assertInvalidPeerMessage {
            missingPayload.receive(
                Envelope.newBuilder().setProtocolVersion(1).setMessageId(2).build(),
            )
        }
    }

    @Test
    fun validatesMediaHeaderAndRejectsFragmentOrStaleEpoch() {
        val session = streamingSession()
        session.validateMedia(mediaHeader())
        assertInvalidMediaHeader { session.validateMedia(mediaHeader().toBuilder().setFragmentCount(2).build()) }
        assertInvalidMediaHeader { session.validateMedia(mediaHeader().toBuilder().setSessionEpoch(6).build()) }
        assertInvalidMediaHeader { session.validateMedia(mediaHeader().toBuilder().setPayloadLength(0).build()) }
        assertInvalidMediaHeader { session.validateMedia(mediaHeader()) }
        assertInvalidMediaHeader {
            streamingSession().validateMedia(mediaHeader().toBuilder().setCodec(Codec.CODEC_H264).build())
        }
    }

    @Test
    fun touchHeartbeatKeyframeAndProtocolErrorUseControlEnvelope() {
        val session = streamingSession()
        val touch = session.touch(100, 1, InputPhase.INPUT_PHASE_BEGAN, 0.25, 0.75)
        assertEquals(Envelope.PayloadCase.TOUCH_EVENT, touch.payloadCase)
        assertEquals("display-main", touch.touchEvent.target.displayId)
        assertEquals(42L, touch.touchEvent.target.streamId)

        val pong = session.receive(
            base(7).setPing(Ping.newBuilder().setSequence(99)).build(),
        ).single() as ProtocolV1Session.Action.Send
        assertEquals(99L, pong.envelope.pong.sequence)
        assertEquals(7L, pong.envelope.correlationId)
        assertEquals(42L, session.requestKeyframe("decoder").requestKeyframe.streamId)

        val error =
            base(8)
                .setProtocolError(
                    ProtocolError
                        .newBuilder()
                        .setCode(ProtocolErrorCode.PROTOCOL_ERROR_CODE_INVALID_STATE)
                        .setMessage("bad state"),
                ).build()
        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(error) }
        assertEquals(ProtocolV1Failure.Source.HOST_PROTOCOL_ERROR, failure.source)
        assertEquals(ProtocolErrorCode.PROTOCOL_ERROR_CODE_INVALID_STATE.name, failure.reason)
        assertFalse(failure.retryable)
    }

    @Test
    fun stylusRequiresNegotiationAndValidTerminalPressure() {
        assertFalse(streamingSession().canSendStylus)
        val session = stylusStreamingSession()
        assertTrue(session.canSendStylus)
        val envelope = session.stylus(101, 7, InputPhase.INPUT_PHASE_CHANGED, 0.25, 0.75, 0.6, 30.0, -40.0)
        assertEquals(Envelope.PayloadCase.STYLUS_EVENT, envelope.payloadCase)
        assertEquals("display-main", envelope.stylusEvent.target.displayId)
        assertEquals(42L, envelope.stylusEvent.target.streamId)
        assertThrows(IllegalArgumentException::class.java) {
            session.stylus(102, 7, InputPhase.INPUT_PHASE_ENDED, 0.25, 0.75, 0.1, 0.0, 0.0)
        }
        assertThrows(IllegalArgumentException::class.java) {
            session.stylus(103, 7, InputPhase.INPUT_PHASE_CHANGED, 0.25, 0.75, 0.1, 90.0, 90.0)
        }
    }

    @Test
    fun negotiatingKeyboardAndPointerUnlocksNativeInputSenders() {
        val touchOnly = streamingSession()
        assertTrue(touchOnly.canSendTouch)
        assertFalse(touchOnly.canSendPointer)
        assertFalse(touchOnly.canSendKeyboard)

        val session = nativeInputStreamingSession()
        assertTrue(session.canSendPointer)
        assertTrue(session.canSendKeyboard)
        assertEquals(
            setOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_KEYBOARD,
                Capability.CAPABILITY_POINTER,
                Capability.CAPABILITY_MULTI_DISPLAY,
                Capability.CAPABILITY_USB_HID_MODIFIER_BYTE,
            ),
            session.negotiated,
        )

        val pointer = session.pointer(200, InputPhase.INPUT_PHASE_BEGAN, 0.4, 0.6, buttonMask = 1)
        assertEquals(Envelope.PayloadCase.POINTER_EVENT, pointer.payloadCase)
        assertEquals(InputPhase.INPUT_PHASE_BEGAN, pointer.pointerEvent.phase)
        assertEquals(0.4, pointer.pointerEvent.position.x, 1e-9)
        assertEquals(0.6, pointer.pointerEvent.position.y, 1e-9)
        assertEquals(1, pointer.pointerEvent.buttonMask)
        assertEquals("display-main", pointer.pointerEvent.target.displayId)
        assertEquals(42L, pointer.pointerEvent.target.streamId)

        val scroll = session.scroll(201, deltaX = 3.0, deltaY = -7.0)
        assertEquals(Envelope.PayloadCase.SCROLL_EVENT, scroll.payloadCase)
        assertEquals(3.0, scroll.scrollEvent.deltaX, 1e-9)
        assertEquals(-7.0, scroll.scrollEvent.deltaY, 1e-9)
        assertEquals(42L, scroll.scrollEvent.target.streamId)

        val key = session.key(202, usbHidUsage = 0x04, pressed = true, modifierMask = 8)
        assertEquals(Envelope.PayloadCase.KEY_EVENT, key.payloadCase)
        assertEquals(0x04, key.keyEvent.usbHidUsage)
        assertTrue(key.keyEvent.pressed)
        assertEquals(8, key.keyEvent.modifierMask)
        assertEquals(42L, key.keyEvent.target.streamId)

        assertEquals(0x01, session.key(203, 0x04, true, 0x01).keyEvent.modifierMask)
        assertEquals(0x02, session.key(204, 0x04, true, 0x02).keyEvent.modifierMask)

        val oldHost = nativeInputStreamingSession(standardModifierByte = false)
        assertEquals(0x02, oldHost.key(203, 0x04, true, 0x01).keyEvent.modifierMask)
        assertEquals(0x01, oldHost.key(204, 0x04, true, 0x02).keyEvent.modifierMask)
        assertEquals(0x02, oldHost.key(205, 0x04, true, 0x10).keyEvent.modifierMask)
    }

    @Test
    fun sessionRejectionPreservesReasonAndRetryability() {
        val session = session().also { it.clientHello() }
        session.receive(hostHello(2))
        val rejected =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(3)
                .setSessionRejected(
                    SessionRejected
                        .newBuilder()
                        .setReasonCode("host_busy")
                        .setMessage("Try another host")
                        .setRetryable(true),
                ).build()

        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(rejected) }

        assertEquals(ProtocolV1Failure.Source.SESSION_REJECTED, failure.source)
        assertEquals("host_busy", failure.reason)
        assertEquals("Try another host", failure.message)
        assertTrue(failure.retryable)
    }

    @Test
    fun rejectedVideoConfigIsAcknowledgedButNeverEnablesMedia() {
        val session = sessionThroughDisplayStart()
        val actions = session.receive(videoConfig(6).toBuilder().setVideoConfig(videoConfig(6).videoConfig.toBuilder().setStreamId(99)).build())
        val result = actions.single() as ProtocolV1Session.Action.Send
        assertFalse(result.envelope.videoConfigResult.accepted)
        assertFalse(session.isStreaming)
        assertInvalidMediaHeader { session.validateMedia(mediaHeader()) }
    }

    @Test
    fun rejectsCodecThatHostDidNotAdvertise() {
        val session = session()
        session.clientHello()
        session.receive(hostHello(2, listOf(Codec.CODEC_H264)))
        session.receive(sessionAccepted(3))
        session.receive(displayList(4))
        session.receive(startDisplay(5))
        val result = session.receive(videoConfig(6)).single() as ProtocolV1Session.Action.Send
        assertFalse(result.envelope.videoConfigResult.accepted)
        assertFalse(session.isStreaming)
    }

    @Test
    fun rejectsSessionAcceptedWithCapabilityClientDidNotAdvertise() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(
                id = 2,
                advertisedCapabilities =
                    listOf(
                        Capability.CAPABILITY_TOUCH,
                        Capability.CAPABILITY_TELEMETRY,
                    ),
            ),
        )
        val acceptedMessage = sessionAccepted(3)
        val accepted =
            acceptedMessage.toBuilder()
                .setSessionAccepted(
                    acceptedMessage.sessionAccepted.toBuilder()
                        .addNegotiatedCapabilities(Capability.CAPABILITY_TELEMETRY),
                ).build()

        assertInvalidPeerMessage { session.receive(accepted) }
    }

    @Test
    fun acceptsExactIntersectionWhenHostAdvertisesAdditionalCapabilities() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(
                id = 2,
                advertisedCapabilities =
                    listOf(
                        Capability.CAPABILITY_TOUCH,
                        Capability.CAPABILITY_TELEMETRY,
                    ),
            ),
        )

        val listRequest = session.receive(sessionAccepted(3)).single() as ProtocolV1Session.Action.Send

        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, listRequest.envelope.payloadCase)
    }

    @Test
    fun acceptsSessionAcceptedThatOmitsPolicyFilteredOptionalCapability() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(
                id = 2,
                advertisedCapabilities =
                    listOf(
                        Capability.CAPABILITY_TOUCH,
                        Capability.CAPABILITY_HOST_ACTIONS,
                    ),
            ),
        )

        val listRequest =
            session.receive(sessionAccepted(3, negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH))).single()
                as ProtocolV1Session.Action.Send

        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, listRequest.envelope.payloadCase)
        assertEquals(setOf(Capability.CAPABILITY_TOUCH), session.negotiated)
        assertFalse(session.canInvokeHostActions)
    }

    @Test
    fun managedPolicyStatusIsSentAfterNegotiation() {
        val session = session(
            localManagedPolicy =
                ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                    isManaged = true,
                    hostActionsAllowed = false,
                    maximumFileBytes = 2_048,
                    allowedHosts = setOf("host"),
                ),
        )
        session.clientHello()
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MANAGED_CONFIGURATION)
        session.receive(hostHello(2, advertisedCapabilities = caps))

        val actions = session.receive(sessionAccepted(3, negotiatedCapabilities = caps))
            .filterIsInstance<ProtocolV1Session.Action.Send>()

        assertEquals(2, actions.size)
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, actions[0].envelope.payloadCase)
        assertEquals(Envelope.PayloadCase.MANAGED_POLICY_STATUS, actions[1].envelope.payloadCase)
        val status = actions[1].envelope.managedPolicyStatus
        assertTrue(status.managed)
        assertFalse(status.hostActionsAllowed)
        assertEquals(2_048, status.maximumFileBytes)
        assertEquals(listOf("host"), status.allowedHostsList)
    }

    @Test
    fun remoteManagedPolicyDenyClearsHostActionsAndBlocksInvoke() {
        val session = hostActionManagedStreamingSession()
        session.receive(hostActionCatalog(7))
        assertTrue(session.canInvokeHostActions)
        assertEquals(listOf("move-window", "return-windows"), session.hostActions.map { it.id })

        val denied =
            ManagedPolicyStatus
                .newBuilder()
                .setManaged(true)
                .setClipboardAllowed(true)
                .setFileTransferAllowed(true)
                .setAudioAllowed(true)
                .setWakeAllowed(true)
                .setCustomGesturesAllowed(true)
                .setHostActionsAllowed(false)
                .setMaximumFileBytes(4_096)
                .addAllowedHosts("host")
                .build()
        val actions = session.receive(managedPolicyStatus(8, denied))

        val available = actions.single() as ProtocolV1Session.Action.HostActionsAvailable
        assertTrue(available.actions.isEmpty())
        assertTrue(session.hostActions.isEmpty())
        assertFalse(Capability.CAPABILITY_HOST_ACTIONS in session.negotiated)
        assertFalse(session.canInvokeHostActions)
        assertNull(session.invokeHostAction("move-window", ByteString.copyFrom(byteArrayOf(1))))
    }

    @Test
    fun remoteManagedPolicyAllowedHostsMismatchFailsClosed() {
        val session = session()
        session.clientHello()
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MANAGED_CONFIGURATION)
        session.receive(hostHello(2, advertisedCapabilities = caps))
        session.receive(sessionAccepted(3, negotiatedCapabilities = caps))

        val restricted =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.toStatus()
                .toBuilder()
                .setManaged(true)
                .addAllowedHosts("different-host")
                .build()

        assertInvalidPeerMessage { session.receive(managedPolicyStatus(4, restricted)) }
    }

    @Test
    fun rejectsSessionAcceptedWithCapabilityHostDidNotAdvertise() {
        val session = session()
        session.clientHello()
        session.receive(hostHello(2, advertisedCapabilities = emptyList()))

        assertInvalidPeerMessage { session.receive(sessionAccepted(3)) }
    }

    @Test
    fun rejectsSessionAcceptedThatOmitsMutuallyAdvertisedTouch() {
        val session = session()
        session.clientHello()
        session.receive(hostHello(2))

        assertInvalidPeerMessage {
            session.receive(sessionAccepted(3, negotiatedCapabilities = emptyList()))
        }
    }

    @Test
    fun displayOnlyNegotiationStreamsButBlocksTouch() {
        val session = session()
        session.clientHello()
        assertTrue(session.receive(hostHello(2, advertisedCapabilities = emptyList())).isEmpty())
        val listRequest =
            session.receive(sessionAccepted(3, negotiatedCapabilities = emptyList())).single()
                as ProtocolV1Session.Action.Send
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, listRequest.envelope.payloadCase)
        session.receive(displayList(4))
        session.receive(startDisplay(5))
        val configured =
            session.receive(videoConfig(6)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested
        assertFalse(session.isStreaming)
        session.completeVideoConfiguration(
            completedConfigEpoch = 3,
            configurationToken = configured.configurationToken,
            accepted = true,
            rejectionReason = "",
        )

        assertTrue(session.isStreaming)
        assertFalse(session.canSendTouch)
        assertThrows(IllegalStateException::class.java) {
            session.touch(100, 1, InputPhase.INPUT_PHASE_BEGAN, 0.25, 0.75)
        }
    }

    @Test
    fun multiDisplayNegotiationListsAllDisplaysAndSelectsPrimaryFirst() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(2, advertisedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MULTI_DISPLAY)),
        )
        session.receive(
            sessionAccepted(3, negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MULTI_DISPLAY)),
        )

        val actions = session.receive(twoDisplayList(4))
        val available = actions[0] as ProtocolV1Session.Action.DisplaysAvailable
        assertEquals(listOf("display-main", "display-2"), available.displays.map { it.id })
        assertEquals("display-main", available.selectedId)
        val start = actions[1] as ProtocolV1Session.Action.Send
        assertEquals("display-main", start.envelope.startDisplayRequest.sourceDisplayId)
    }

    @Test
    fun multiDisplayNegotiationSelectsHostOrderedActiveDisplayBeforePrimary() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(2, advertisedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MULTI_DISPLAY)),
        )
        session.receive(
            sessionAccepted(3, negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MULTI_DISPLAY)),
        )

        val actions = session.receive(activeSecondaryDisplayList(4))
        val available = actions[0] as ProtocolV1Session.Action.DisplaysAvailable
        assertEquals(listOf("display-2", "display-main"), available.displays.map { it.id })
        assertEquals("display-2", available.selectedId)
        val start = actions[1] as ProtocolV1Session.Action.Send
        assertEquals("display-2", start.envelope.startDisplayRequest.sourceDisplayId)
    }

    @Test
    fun runtimeDisplaySelectionEmitsStartDisplayForKnownDisplayOnly() {
        val session = multiDisplayStreamingSession()

        assertNull(session.selectDisplay("display-main"))
        assertNull(session.selectDisplay("unknown-display"))

        val request = session.selectDisplay("display-2")!!
        assertEquals(
            Envelope.PayloadCase.START_DISPLAY_REQUEST,
            request.payloadCase,
        )
        assertEquals("display-2", request.startDisplayRequest.sourceDisplayId)
    }

    @Test
    fun setVideoPreferencesRequiresStreamingCapabilityAndANonEmptyRequest() {
        // Without CLIENT_VIDEO_CONTROL negotiated the request is a no-op.
        val ungated = multiDisplayStreamingSession()
        assertNull(
            ungated.setVideoPreferences(
                bitrateKbps = 8_000,
                framesPerSecond = 30,
                qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
            ),
        )

        val session = videoControlStreamingSession()
        // An all-empty request changes nothing, so it produces no envelope.
        assertNull(
            session.setVideoPreferences(
                bitrateKbps = 0,
                framesPerSecond = 0,
                qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
            ),
        )

        val request =
            session.setVideoPreferences(
                bitrateKbps = 8_000,
                framesPerSecond = 30,
                qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_SHARP,
            )!!
        assertEquals(Envelope.PayloadCase.SET_VIDEO_PREFERENCES, request.payloadCase)
        assertEquals(8_000, request.setVideoPreferences.bitrateKbps)
        assertEquals(30, request.setVideoPreferences.framesPerSecond)
        assertEquals(
            VideoQualityPreset.VIDEO_QUALITY_PRESET_SHARP,
            request.setVideoPreferences.qualityPreset,
        )

        // After sending, the session gates media until the host's re-advertised
        // VideoConfig is accepted, mirroring a display switch.
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION,
            session.validateMedia(mediaHeader()),
        )
    }

    @Test
    fun presetToAutoSendsResetToAutoRequest() {
        // A preset -> AUTO transition cannot be expressed by an empty preset
        // (that means "keep current"), so the reset flag must produce a real
        // request that the host can act on.
        val session = videoControlStreamingSession()
        val request =
            session.setVideoPreferences(
                bitrateKbps = 0,
                framesPerSecond = 0,
                qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
                resetQualityToAuto = true,
            )!!
        assertEquals(Envelope.PayloadCase.SET_VIDEO_PREFERENCES, request.payloadCase)
        assertTrue(request.setVideoPreferences.resetQualityToAuto)
        assertEquals(0, request.setVideoPreferences.bitrateKbps)
        assertEquals(0, request.setVideoPreferences.framesPerSecond)
        assertEquals(
            VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
            request.setVideoPreferences.qualityPreset,
        )
    }

    @Test
    fun preferenceChangeDuringReconfigurationIsCoalescedAndSentAfterCommit() {
        val session = videoControlStreamingSession()
        // First change is sent immediately and gates media on a bumped epoch.
        val first =
            session.setVideoPreferences(
                bitrateKbps = 8_000,
                framesPerSecond = 30,
                qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
            )!!
        assertEquals(8_000, first.setVideoPreferences.bitrateKbps)

        // A second change arrives before the replacement VideoConfig commits.
        // It cannot be sent yet, so it is coalesced (no envelope now) and must
        // be the value that reaches the host after the commit.
        assertNull(
            session.setVideoPreferences(
                bitrateKbps = 20_000,
                framesPerSecond = 60,
                qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
            ),
        )

        // Host re-advertises the first change on epoch 4; committing it returns
        // to streaming and must flush the coalesced newest intent.
        val requested =
            session.receive(videoConfig(30, configEpoch = 4)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested
        val committed =
            session.completeVideoConfiguration(
                completedConfigEpoch = 4,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        val flushed =
            committed
                .filterIsInstance<ProtocolV1Session.Action.Send>()
                .map { it.envelope }
                .single { it.payloadCase == Envelope.PayloadCase.SET_VIDEO_PREFERENCES }
        assertTrue(
            committed
                .filterIsInstance<ProtocolV1Session.Action.VideoConfigurationCommitted>()
                .single()
                .appliesClientVideoPreferences,
        )
        assertEquals(20_000, flushed.setVideoPreferences.bitrateKbps)
        assertEquals(60, flushed.setVideoPreferences.framesPerSecond)

        // The flushed request re-gates media until its own VideoConfig commits.
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION,
            session.validateMedia(mediaHeader(configEpoch = 4)),
        )
    }

    @Test
    fun rejectedPreferenceConfigurationDoesNotMarkLaterHostConfigurationAsClientRequested() {
        val session = videoControlStreamingSession()
        session.setVideoPreferences(
            bitrateKbps = 8_000,
            framesPerSecond = 30,
            qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
        )
        val rejectedRequest =
            session.receive(videoConfig(30, configEpoch = 4)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested
        session.completeVideoConfiguration(
            completedConfigEpoch = 4,
            configurationToken = rejectedRequest.configurationToken,
            accepted = false,
            rejectionReason = "decoder_rejected",
        )

        val laterRequest =
            session.receive(videoConfig(31, configEpoch = 5)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested
        val laterCommit =
            session.completeVideoConfiguration(
                completedConfigEpoch = 5,
                configurationToken = laterRequest.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        assertFalse(
            laterCommit
                .filterIsInstance<ProtocolV1Session.Action.VideoConfigurationCommitted>()
                .single()
                .appliesClientVideoPreferences,
        )
    }

    @Test
    fun runtimeDisplaySelectionRepublishesGeometryOnNewVideoConfig() {
        val session = multiDisplayStreamingSession()
        session.selectDisplay("display-2")
        session.receive(
            base(20).setStartDisplayResponse(
                StartDisplayResponse
                    .newBuilder()
                    .setAccepted(true)
                    .setStreamId(42)
                    .setDisplay(
                        DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-2")
                            .setName("Display 2")
                            .setLogicalSize(Dimensions.newBuilder().setWidth(2560).setHeight(1440)),
                    ),
            ).build(),
        )
        val requested =
            session.receive(videoConfig(21, configEpoch = 4)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested
        val committed =
            session.completeVideoConfiguration(
                completedConfigEpoch = 4,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        val geometry = committed.last() as ProtocolV1Session.Action.DisplayGeometryChanged
        assertEquals(2560, geometry.width)
        assertEquals(1440, geometry.height)
        assertTrue(session.isStreaming)
    }


    @Test
    fun defaultClientHelloExcludesControllerCapability() {
        val session = session()
        val hello = session.clientHello()
        assertFalse(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_CONTROLLER))
    }

    @Test
    fun advertiseControllerAddsControllerWithoutDroppingExistingCapabilities() {
        val defaultCapabilities = session().clientHello().clientHello.capabilitiesList.toSet()
        val session =
            ProtocolV1Session(
                deviceId = "android-test",
                deviceName = "Test Android",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
                advertiseController = true,
                nowNs = { 1_000L },
            )
        val hello = session.clientHello()
        assertEquals(
            defaultCapabilities + Capability.CAPABILITY_CONTROLLER,
            hello.clientHello.capabilitiesList.toSet(),
        )
    }

    @Test
    fun canSendControllerRequiresNegotiatedControllerCapability() {
        val session = controllerStreamingSession()
        assertTrue(session.canSendController)
    }

    @Test
    fun canSendControllerRequiresStreamingState() {
        val session = controllerSessionThroughDisplayStart()
        assertFalse(session.canSendController)
    }

    @Test
    fun canSendControllerIsFalseDuringRuntimeDisplaySelection() {
        val session = controllerMultiDisplayStreamingSession()

        assertNotNull(session.selectDisplay("display-2"))
        assertFalse(session.canSendController)
    }

    @Test
    fun canSendControllerFalseWithoutNegotiation() {
        val session = streamingSession()
        assertFalse(session.canSendController)
    }

    @Test
    fun controllerEncodesFullStateSample() {
        val session = controllerStreamingSession()
        val sample =
            ControllerStateSample(
                controllerId = "pad-1",
                controllerEpoch = 1,
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
        val envelope = session.controller(inputId = 9, sample = sample)
        assertEquals(Envelope.PayloadCase.CONTROLLER_EVENT, envelope.payloadCase)
        val event = envelope.controllerEvent
        assertEquals(9L, event.inputId)
        assertEquals("pad-1", event.controllerId)
        assertEquals(1L, event.controllerEpoch)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE, event.kind)
        assertEquals(0b101, event.buttonMask)
        assertEquals(0.5, event.leftStickX, 0.0)
        assertEquals(-0.25, event.leftStickY, 0.0)
        assertEquals(1.0, event.rightStickX, 0.0)
        assertEquals(-1.0, event.rightStickY, 0.0)
        assertEquals(0.75, event.leftTrigger, 0.0)
        assertEquals(0.0, event.rightTrigger, 0.0)
        assertEquals(1, event.hatX)
        assertEquals(-1, event.hatY)
        assertEquals("display-main", event.target.displayId)
        assertEquals(42L, event.target.streamId)
    }

    @Test
    fun controllerRejectsNonPositiveInputId() {
        val session = controllerStreamingSession()
        val sample = ControllerStateSample("pad-1", 1, ControllerEventKind.STATE)
        assertThrows(IllegalArgumentException::class.java) {
            session.controller(inputId = 0, sample = sample)
        }
    }

    @Test
    fun controllerEncodesNeutralLifecycleKinds() {
        val session = controllerStreamingSession()
        val connected = session.controller(1, ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED))
        assertEquals(
            dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            connected.controllerEvent.kind,
        )
        assertEquals(0, connected.controllerEvent.buttonMask)
        assertEquals(ControllerAxes.NEUTRAL.leftX, connected.controllerEvent.leftStickX, 0.0)

        val disconnected = session.controller(2, ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED))
        assertEquals(
            dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
            disconnected.controllerEvent.kind,
        )
        assertEquals(0, disconnected.controllerEvent.buttonMask)
    }

    @Test
    fun controllerBeforeStreamingFails() {
        val session = controllerSessionThroughDisplayStart()
        val sample = ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED)
        assertThrows(IllegalStateException::class.java) {
            session.controller(inputId = 1, sample = sample)
        }
    }

    @Test
    fun controllerWithoutNegotiatedCapabilityFails() {
        val session = streamingSession()
        val sample = ControllerStateSample("pad-1", 1, ControllerEventKind.STATE)
        assertThrows(IllegalStateException::class.java) {
            session.controller(inputId = 1, sample = sample)
        }
    }

    @Test
    fun inputAckAcceptedIsDecoded() {
        val session = controllerStreamingSession()
        val ack =
            base(8)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(9)
                        .setAccepted(true),
                ).build()
        val action = session.receive(ack).single() as ProtocolV1Session.Action.ControllerInputAck
        assertEquals(9L, action.inputId)
        assertTrue(action.accepted)
        assertEquals("", action.rejectionReason)
    }

    @Test
    fun inputAckRejectedRequiresReason() {
        val session = controllerStreamingSession()
        val ack =
            base(8)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(9)
                        .setAccepted(false)
                        .setRejectionReason("maximum_active_controllers_exceeded"),
                ).build()
        val action = session.receive(ack).single() as ProtocolV1Session.Action.ControllerInputAck
        assertEquals(9L, action.inputId)
        assertFalse(action.accepted)
        assertEquals("maximum_active_controllers_exceeded", action.rejectionReason)
    }

    @Test
    fun inputAckRejectedWithoutReasonFails() {
        val session = controllerStreamingSession()
        val ack =
            base(8)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(9)
                        .setAccepted(false),
                ).build()
        assertInvalidPeerMessage { session.receive(ack) }
    }

    @Test
    fun inputAckNonPositiveInputIdFails() {
        val session = controllerStreamingSession()
        val ack =
            base(8)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(0)
                        .setAccepted(true),
                ).build()
        assertInvalidPeerMessage { session.receive(ack) }
    }

    @Test
    fun inputAckWithoutNegotiatedControllerFails() {
        val session = streamingSession()
        val ack =
            base(8)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(9)
                        .setAccepted(true),
                ).build()
        assertInvalidPeerMessage { session.receive(ack) }
    }

    @Test
    fun inputAckBeforeSessionNegotiationFails() {
        val session =
            ProtocolV1Session(
                deviceId = "android-test",
                deviceName = "Test Android",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
                advertiseController = true,
                nowNs = { 1_000L },
            )
        session.clientHello()
        val ack =
            base(1)
                .setInputAck(InputAck.newBuilder().setInputId(9).setAccepted(true))
                .build()

        assertInvalidPeerMessage { session.receive(ack) }
    }

    @Test
    fun inputAckDuringDisplaySetupIsDecodedWhenControllerCapabilityNegotiated() {
        val session = controllerSessionThroughDisplayStart()
        val ack =
            base(6)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(9)
                        .setAccepted(false)
                        .setRejectionReason("maximum_active_controllers_exceeded"),
                ).build()

        val action = session.receive(ack).single() as ProtocolV1Session.Action.ControllerInputAck
        assertEquals(9L, action.inputId)
        assertFalse(action.accepted)
        assertEquals("maximum_active_controllers_exceeded", action.rejectionReason)
    }

    @Test
    fun inputAckDuringRuntimeDisplaySelectionIsDecodedWhenControllerCapabilityNegotiated() {
        val session = controllerMultiDisplayStreamingSession()
        assertNotNull(session.selectDisplay("display-2"))
        val ack =
            base(7)
                .setInputAck(InputAck.newBuilder().setInputId(9).setAccepted(true))
                .build()

        val action = session.receive(ack).single() as ProtocolV1Session.Action.ControllerInputAck
        assertEquals(9L, action.inputId)
        assertTrue(action.accepted)
        assertEquals("", action.rejectionReason)
    }

    private fun streamingSession(): ProtocolV1Session =
        sessionThroughDisplayStart().also {
            val requested =
                it.receive(videoConfig(6)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }

    private val controllerCaps =
        listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CONTROLLER)

    private fun controllerSessionThroughDisplayStart(): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-test",
            deviceName = "Test Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
            advertiseController = true,
            nowNs = { 1_000L },
        ).also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = controllerCaps))
            it.receive(sessionAccepted(3, negotiatedCapabilities = controllerCaps))
            it.receive(displayList(4))
            it.receive(startDisplay(5))
        }

    private fun controllerStreamingSession(): ProtocolV1Session =
        controllerSessionThroughDisplayStart().also {
            val requested =
                it.receive(videoConfig(6)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }

    private fun controllerMultiDisplayStreamingSession(): ProtocolV1Session {
        val capabilities = controllerCaps + Capability.CAPABILITY_MULTI_DISPLAY
        return ProtocolV1Session(
            deviceId = "android-test",
            deviceName = "Test Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
            advertiseController = true,
            nowNs = { 1_000L },
        ).also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = capabilities))
            it.receive(sessionAccepted(3, negotiatedCapabilities = capabilities))
            it.receive(twoDisplayList(4))
            it.receive(startDisplay(5))
            val requested =
                it.receive(videoConfig(6)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(3, requested.configurationToken, true, "")
        }
    }

    private fun nativeInputStreamingSession(standardModifierByte: Boolean = true): ProtocolV1Session {
        val caps =
            buildList {
                addAll(listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_KEYBOARD,
                Capability.CAPABILITY_POINTER,
                Capability.CAPABILITY_MULTI_DISPLAY,
                ))
                if (standardModifierByte) add(Capability.CAPABILITY_USB_HID_MODIFIER_BYTE)
            }
        return session().also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = caps))
            it.receive(sessionAccepted(3, negotiatedCapabilities = caps))
            it.receive(displayList(4))
            it.receive(startDisplay(5))
            val requested =
                it.receive(videoConfig(6)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }
    }

    private fun stylusStreamingSession(): ProtocolV1Session {
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_STYLUS)
        return session().also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = caps))
            it.receive(sessionAccepted(3, negotiatedCapabilities = caps))
            it.receive(displayList(4))
            it.receive(startDisplay(5))
            val requested = it.receive(videoConfig(6)).single() as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(3, requested.configurationToken, true, "")
        }
    }

    private fun multiDisplayStreamingSession(): ProtocolV1Session =
        session().also {
            it.clientHello()
            it.receive(
                hostHello(2, advertisedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MULTI_DISPLAY)),
            )
            it.receive(
                sessionAccepted(3, negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MULTI_DISPLAY)),
            )
            it.receive(twoDisplayList(4))
            it.receive(startDisplay(5))
            val requested =
                it.receive(videoConfig(6)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }

   private fun sessionThroughDisplayStart(): ProtocolV1Session =
       session().also {
           it.clientHello()
           it.receive(hostHello(2))
           it.receive(sessionAccepted(3))
           it.receive(displayList(4))
           it.receive(startDisplay(5))
       }

    private val hostActionCaps =
        listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_HOST_ACTIONS)

    private fun hostActionSessionThroughDisplayStart(): ProtocolV1Session =
        session().also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = hostActionCaps))
            it.receive(sessionAccepted(3, negotiatedCapabilities = hostActionCaps))
            it.receive(displayList(4))
            it.receive(startDisplay(5))
        }

    private fun hostActionStreamingSession(): ProtocolV1Session =
        hostActionSessionThroughDisplayStart().also {
            val requested =
                it.receive(videoConfig(6)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }

    private fun hostActionManagedStreamingSession(): ProtocolV1Session {
        val caps = hostActionCaps + Capability.CAPABILITY_MANAGED_CONFIGURATION
        return session().also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = caps))
            it.receive(sessionAccepted(3, negotiatedCapabilities = caps))
            it.receive(displayList(4))
            it.receive(startDisplay(5))
            val requested =
                it.receive(videoConfig(6)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }
    }

    private fun videoControlStreamingSession(): ProtocolV1Session =
        session().also {
            it.clientHello()
            it.receive(
                hostHello(
                    2,
                    advertisedCapabilities =
                        listOf(
                            Capability.CAPABILITY_TOUCH,
                            Capability.CAPABILITY_CLIENT_VIDEO_CONTROL,
                        ),
                ),
            )
            it.receive(
                sessionAccepted(
                    3,
                    negotiatedCapabilities =
                        listOf(
                            Capability.CAPABILITY_TOUCH,
                            Capability.CAPABILITY_CLIENT_VIDEO_CONTROL,
                        ),
                ),
            )
            it.receive(displayList(4))
            it.receive(startDisplay(5))
            val requested =
                it.receive(videoConfig(6)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }

    private fun session(
        localManagedPolicy: ProtocolV1Session.ManagedPolicy = ProtocolV1Session.ManagedPolicy.UNMANAGED,
    ): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-test",
            deviceName = "Test Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
            localManagedPolicy = localManagedPolicy,
            nowNs = { 1_000L },
        )

    private fun assertInvalidPeerMessage(block: () -> Unit) {
        val failure = assertThrows(ProtocolV1Failure::class.java, block)
        assertEquals("invalid_peer_message", failure.reason)
        assertEquals(ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION, failure.source)
        assertFalse(failure.retryable)
    }

    private fun assertInvalidMediaHeader(block: () -> Unit) {
        val failure = assertThrows(ProtocolV1Failure::class.java, block)
        assertEquals("invalid_media_header", failure.reason)
        assertEquals(ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION, failure.source)
        assertFalse(failure.retryable)
    }

    private fun hostHello(
        id: Long,
        advertisedCodecs: List<Codec> = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
        advertisedCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
    ): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setHostHello(
                HostHello
                    .newBuilder()
                    .setSelectedProtocol(1)
                    .setHostId("host")
                    .addAllCapabilities(advertisedCapabilities)
                    .addAllCodecs(advertisedCodecs),
            ).build()

    private fun managedPolicyStatus(
        id: Long,
        status: ManagedPolicyStatus,
    ): Envelope = base(id).setManagedPolicyStatus(status).build()

    private fun sessionAccepted(
        id: Long,
        negotiatedCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
    ): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionAccepted(
                SessionAccepted
                    .newBuilder()
                    .setSessionId(SESSION_ID)
                    .setSessionEpoch(7)
                    .setHeartbeatIntervalMs(1_000)
                    .addAllNegotiatedCapabilities(negotiatedCapabilities),
            ).build()

    private fun displayList(id: Long): Envelope =
        base(id)
            .setListDisplaysResponse(
                ListDisplaysResponse
                    .newBuilder()
                    .addDisplays(
                        DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-main")
                            .setLogicalSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080)),
                    ),
            ).build()

    private fun startDisplay(id: Long): Envelope =
        base(id)
            .setStartDisplayResponse(
                StartDisplayResponse
                    .newBuilder()
                    .setAccepted(true)
                    .setStreamId(42),
            ).build()

    private fun twoDisplayList(id: Long): Envelope =
        base(id)
            .setListDisplaysResponse(
                ListDisplaysResponse
                    .newBuilder()
                    .addDisplays(
                        DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-main")
                            .setName("Built-in Retina")
                            .setIsPrimary(true)
                            .setLogicalSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080)),
                    ).addDisplays(
                        DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-2")
                            .setName("Display 2")
                            .setLogicalSize(Dimensions.newBuilder().setWidth(2560).setHeight(1440)),
                    ),
            ).build()

    private fun activeSecondaryDisplayList(id: Long): Envelope =
        base(id)
            .setListDisplaysResponse(
                ListDisplaysResponse
                    .newBuilder()
                    .addDisplays(
                        DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-2")
                            .setName("Display 2")
                            .setLogicalSize(Dimensions.newBuilder().setWidth(2560).setHeight(1440)),
                    ).addDisplays(
                        DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-main")
                            .setName("Built-in Retina")
                            .setIsPrimary(true)
                            .setLogicalSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080)),
                    ),
            ).build()

    private fun videoConfig(
        id: Long,
        configEpoch: Long = 3,
    ): Envelope =
        base(id)
            .setVideoConfig(
                VideoConfig
                    .newBuilder()
                    .setConfigEpoch(configEpoch)
                    .setCodec(Codec.CODEC_HEVC)
                    .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                    .setFramesPerSecond(60)
                    .setBitrateKbps(12_000)
                    .setStreamId(42)
                    .setRotationDegrees(90),
            ).build()

   private fun base(id: Long): Envelope.Builder =
       Envelope
           .newBuilder()
           .setProtocolVersion(1)
           .setMessageId(id)
           .setSessionId(SESSION_ID)
           .setSessionEpoch(7)

    private fun hostActionCatalog(
        id: Long,
        descriptors: List<HostActionDescriptor> =
            listOf(
                HostActionDescriptor.newBuilder().setActionId("move-window").setLocalizedName("Move window").build(),
                HostActionDescriptor.newBuilder().setActionId("return-windows").setLocalizedName("Return").build(),
            ),
    ): Envelope =
        base(id)
            .setHostActionCatalog(HostActionCatalog.newBuilder().addAllActions(descriptors))
            .build()

    private fun hostActionResult(
        id: Long,
        invocationId: ByteString,
        accepted: Boolean = true,
        rejectionReason: String = "",
    ): Envelope =
        base(id)
            .setHostActionResult(
                HostActionResult
                    .newBuilder()
                    .setInvocationId(invocationId)
                    .setAccepted(accepted)
                    .setRejectionReason(rejectionReason),
            ).build()

    private fun mediaHeader(
        configEpoch: Long = 3,
        frameId: Long = 1,
        keyframe: Boolean = true,
    ): MediaPacketHeader =
        MediaPacketHeader
            .newBuilder()
            .setStreamId(42)
            .setSessionEpoch(7)
            .setConfigEpoch(configEpoch)
            .setFrameId(frameId)
            .setFragmentIndex(0)
            .setFragmentCount(1)
            .setKeyframe(keyframe)
            .setCodec(Codec.CODEC_HEVC)
            .setPayloadLength(4)
            .build()

    companion object {
        private val SESSION_ID = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4))
    }
}
