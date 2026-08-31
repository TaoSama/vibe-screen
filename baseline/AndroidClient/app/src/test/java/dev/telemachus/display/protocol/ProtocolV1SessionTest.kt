package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.telemachus.display.ControllerAxes
import dev.telemachus.display.ControllerEventKind
import dev.telemachus.display.ControllerStateSample
import dev.telemachus.display.WakeHostProof
import dev.telemachus.display.WakeHostRequestContext
import dev.vibescreen.protocol.v1.AudioCodec
import dev.vibescreen.protocol.v1.AudioConfig
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.ColorDescription
import dev.vibescreen.protocol.v1.ColorPrimaries
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DisconnectNotice
import dev.vibescreen.protocol.v1.DisplayDescriptor
import dev.vibescreen.protocol.v1.DisplayChanged
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.FileAccept
import dev.vibescreen.protocol.v1.FileOffer
import dev.vibescreen.protocol.v1.FileTransferCancel
import dev.vibescreen.protocol.v1.FileTransferComplete
import dev.vibescreen.protocol.v1.FileTransferProgress
import dev.vibescreen.protocol.v1.HostActionCatalog
import dev.vibescreen.protocol.v1.HostActionDescriptor
import dev.vibescreen.protocol.v1.HostActionResult
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.InputAck
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.ListDisplaysResponse
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import dev.vibescreen.protocol.v1.MatrixCoefficients
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.Ping
import dev.vibescreen.protocol.v1.ProtocolError
import dev.vibescreen.protocol.v1.ProtocolErrorCode
import dev.vibescreen.protocol.v1.ResourceLimits
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.SessionRejected
import dev.vibescreen.protocol.v1.StartDisplayResponse
import dev.vibescreen.protocol.v1.TransferFunction
import dev.vibescreen.protocol.v1.TransportKind
import dev.vibescreen.protocol.v1.VideoConfig
import dev.vibescreen.protocol.v1.VideoQualityPreset
import dev.vibescreen.protocol.v1.WakeHostRequest
import dev.vibescreen.protocol.v1.WakeHostResult
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
            setOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_KEYBOARD,
                Capability.CAPABILITY_POINTER,
                Capability.CAPABILITY_STYLUS,
                Capability.CAPABILITY_STYLUS_EXTENDED,
                Capability.CAPABILITY_COLOR_MANAGEMENT,
                Capability.CAPABILITY_MULTI_DISPLAY,
                Capability.CAPABILITY_CLIENT_VIDEO_CONTROL,
                Capability.CAPABILITY_HOST_ACTIONS,
                Capability.CAPABILITY_USB_HID_MODIFIER_BYTE,
                Capability.CAPABILITY_CLIPBOARD,
                Capability.CAPABILITY_AUDIO,
                Capability.CAPABILITY_FILE_TRANSFER,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            ),
            hello.clientHello.capabilitiesList.toSet(),
        )
        assertEquals(emptyList<Capability>(), hello.clientHello.requiredCapabilitiesList)
        assertEquals(listOf(Codec.CODEC_HEVC, Codec.CODEC_H264), hello.clientHello.codecsList)
        assertEquals(2, hello.clientHello.videoDecodeCapabilitiesCount)
        assertTrue(hello.clientHello.videoDecodeCapabilitiesList.all { capability ->
            capability.bitDepthsList == listOf(8) &&
                capability.transferFunctionsList.contains(TransferFunction.TRANSFER_FUNCTION_BT709) &&
                capability.transferFunctionsList.contains(TransferFunction.TRANSFER_FUNCTION_SRGB)
        })
        assertEquals(FileTransferPolicy.DEFAULT_MAXIMUM_FILE_BYTES, hello.clientHello.resourceLimits.maximumFileBytes)
        assertEquals(FileTransferPolicy.DEFAULT_MAXIMUM_CHUNK_BYTES, hello.clientHello.resourceLimits.maximumFileChunkBytes)
        assertEquals(1, hello.clientHello.resourceLimits.maximumAudioStreams)
    }

    @Test
    fun localManagedPolicyCanDisableAudioCapabilityAndResourceLimit() {
        val session = session(localManagedPolicy = ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(audioAllowed = false))
        val hello = session.clientHello().clientHello

        assertFalse(hello.capabilitiesList.contains(Capability.CAPABILITY_AUDIO))
        assertEquals(0, hello.resourceLimits.maximumAudioStreams)
    }

    @Test
    fun fileTransferPolicyDisabledRemovesFileCapabilitiesAndResourceLimits() {
        val session =
            ProtocolV1Session(
                deviceId = "android-test",
                deviceName = "Test Android",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
                fileTransferPolicy = FileTransferPolicy(allowed = false),
                nowNs = { 1_000L },
            )
        val hello = session.clientHello().clientHello

        assertFalse(hello.capabilitiesList.contains(Capability.CAPABILITY_FILE_TRANSFER))
        assertTrue(hello.capabilitiesList.contains(Capability.CAPABILITY_MANAGED_CONFIGURATION))
        assertEquals(0L, hello.resourceLimits.maximumFileBytes)
        assertEquals(0, hello.resourceLimits.maximumFileChunkBytes)
    }

    @Test
    fun localManagedZeroMaximumRemovesFileCapabilitiesAndResourceLimits() {
        val session =
            session(
                localManagedPolicy =
                    ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                        isManaged = true,
                        maximumFileBytes = 0,
                    ),
            )
        val hello = session.clientHello().clientHello

        assertFalse(hello.capabilitiesList.contains(Capability.CAPABILITY_FILE_TRANSFER))
        assertEquals(0L, hello.resourceLimits.maximumFileBytes)
        assertEquals(0, hello.resourceLimits.maximumFileChunkBytes)
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
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                clipboardAllowed = false,
                fileTransferAllowed = true,
                audioAllowed = false,
                wakeAllowed = true,
                customGesturesAllowed = true,
                hostActionsAllowed = false,
                maximumFileBytes = 1_024,
                allowedHosts = setOf("host", "other"),
                deniedHosts = setOf("other"),
                allowedHostsRestricted = true,
            ).toStatus()

        val effective = local.applying(ProtocolV1Session.ManagedPolicy.fromStatus(remote))

        assertFalse(effective.clipboardAllowed)
        assertTrue(effective.fileTransferAllowed)
        assertFalse(effective.audioAllowed)
        assertTrue(effective.wakeAllowed)
        assertTrue(effective.customGesturesAllowed)
        assertFalse(effective.hostActionsAllowed)
        assertEquals(1_024, effective.maximumFileBytes)
        assertEquals(setOf("host"), effective.allowedHosts)
        assertEquals(setOf("other"), effective.deniedHosts)
        assertTrue(effective.allowsHost("host"))
        assertFalse(effective.allowsHost("other"))
        assertEquals(
            setOf("effective_deny_wins"),
            effective.restrictionResults.map { it.source }.toSet(),
        )
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
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                allowedHosts = setOf("remote-host"),
                allowedHostsRestricted = true,
            ).toStatus()

        val effective = local.applying(ProtocolV1Session.ManagedPolicy.fromStatus(remote))

        assertTrue(effective.allowedHostsRestricted)
        assertTrue(effective.allowedHosts.isEmpty())
        assertFalse(effective.allowsHost("local-host"))
        assertFalse(effective.allowsHost("remote-host"))
    }

    @Test
    fun deniedHostsOverrideAllowedHosts() {
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
                deniedHosts = setOf("other"),
            )
        val remote =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                allowedHosts = setOf("host"),
                deniedHosts = setOf("host"),
                allowedHostsRestricted = true,
            ).toStatus()

        val effective = local.applying(ProtocolV1Session.ManagedPolicy.fromStatus(remote))

        assertTrue(effective.allowedHostsRestricted)
        assertTrue(effective.allowedHosts.isEmpty())
        assertEquals(setOf("host", "other"), effective.deniedHosts)
        assertFalse(effective.allowsHost("host"))
        assertFalse(effective.allowsHost("other"))
        assertEquals(
            ProtocolV1Session.ManagedPolicy.REQUIRED_RESTRICTIONS,
            effective.restrictionResults.map { it.restriction }.toSet(),
        )
    }

    @Test
    fun restrictedEmptyAllowedHostsRoundTripsThroughStatus() {
        val policy =
            ProtocolV1Session.ManagedPolicy(
                isManaged = true,
                clipboardAllowed = true,
                fileTransferAllowed = true,
                audioAllowed = true,
                wakeAllowed = true,
                customGesturesAllowed = true,
                hostActionsAllowed = true,
                maximumFileBytes = 4_096,
                allowedHosts = emptySet(),
                allowedHostsRestricted = true,
            )

        val roundTripped = ProtocolV1Session.ManagedPolicy.fromStatus(policy.toStatus())

        assertTrue(roundTripped.allowedHostsRestricted)
        assertTrue(roundTripped.allowedHosts.isEmpty())
        assertFalse(roundTripped.allowsHost("any-host"))
    }

    @Test
    fun allowedHostsAreNormalizedBeforeMatchingAndSerializing() {
        val policy =
            ProtocolV1Session.ManagedPolicy(
                isManaged = true,
                clipboardAllowed = true,
                fileTransferAllowed = true,
                audioAllowed = true,
                wakeAllowed = true,
                customGesturesAllowed = true,
                hostActionsAllowed = true,
                maximumFileBytes = 4_096,
                allowedHosts = setOf(" Mac.Local ", "REMOTE.local", " "),
            )

        assertEquals(setOf("mac.local", "remote.local"), policy.allowedHosts)
        assertTrue(policy.allowsHost("mac.local"))
        assertTrue(policy.allowsHost(" MAC.LOCAL "))
        assertFalse(policy.allowsHost("other.local"))
        assertEquals(listOf("mac.local", "remote.local"), policy.toStatus().allowedHostsList)
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
    fun managedPolicyWithZeroMaximumDisablesFileTransferAndValidatesResults() {
        val policy =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                fileTransferAllowed = true,
                maximumFileBytes = 0,
            )

        assertFalse(policy.fileTransferAllowed)
        assertTrue(ProtocolV1Session.ManagedPolicy.hasCompleteRestrictionResults(policy.toStatus()))
        assertFalse(
            policy.toStatus().restrictionResultsList.single {
                it.restriction == ProtocolV1Session.ManagedPolicy.RESTRICTION_FILE_TRANSFER
            }.allowed,
        )
    }

    @Test
    fun allowedHostsRestrictionResultUsesDerivedRestrictedState() {
        val status =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                allowedHosts = setOf("host.local"),
                deniedHosts = setOf("host.local"),
                allowedHostsRestricted = true,
            ).toStatus().toBuilder()
                .setAllowedHostsRestricted(false)
                .build()
        val index = status.restrictionResultsList.indexOfFirst {
            it.restriction == ProtocolV1Session.ManagedPolicy.RESTRICTION_ALLOWED_HOSTS
        }
        val mismatched = status.toBuilder()
            .setRestrictionResults(index, status.restrictionResultsList[index].toBuilder().setAllowed(true))
            .build()

        assertFalse(ProtocolV1Session.ManagedPolicy.hasCompleteRestrictionResults(mismatched))
    }

    @Test
    fun allowedHostsRestrictionResultsMatchDerivedLocalPolicy() {
        val policy =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                allowedHosts = setOf("host.local"),
                deniedHosts = setOf("host.local"),
                allowedHostsRestricted = false,
            )
        val status = policy.toStatus()

        assertTrue(policy.allowedHostsRestricted)
        assertTrue(ProtocolV1Session.ManagedPolicy.hasCompleteRestrictionResults(status))
        assertFalse(
            status.restrictionResultsList.single {
                it.restriction == ProtocolV1Session.ManagedPolicy.RESTRICTION_ALLOWED_HOSTS
            }.allowed,
        )
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
        val committed = actions.filterIsInstance<ProtocolV1Session.Action.VideoConfigurationCommitted>().single()
        val geometry = actions.filterIsInstance<ProtocolV1Session.Action.DisplayGeometryChanged>().single()
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
    fun audioConfigRequiresNegotiatedAudioAndStreamingVideo() {
        val beforeStreaming = sessionThroughDisplayStart()
        assertInvalidPeerMessage { beforeStreaming.receive(audioConfigEnvelope(6)) }

        val withoutAudio = streamingSession()
        assertInvalidPeerMessage { withoutAudio.receive(audioConfigEnvelope(7)) }
    }

    @Test
    fun audioConfigCanBeAcceptedAfterNegotiation() {
        val session = audioStreamingSession()
        val requested =
            session.receive(audioConfigEnvelope(8)).single()
                as ProtocolV1Session.Action.AudioConfigurationRequested

        assertEquals(2L, requested.config.streamId)
        assertEquals(1L, requested.config.configEpoch)
        assertEquals(7L, requested.sessionEpoch)
        assertFalse(session.canReceiveAudio)

        val response = session.completeAudioConfiguration(requested.config, accepted = true, rejectionReason = "", correlationId = requested.correlationId)
        assertNotNull(response)
        assertTrue(response!!.audioConfigResult.accepted)
        assertEquals(8L, response.correlationId)
        assertTrue(session.canReceiveAudio)
    }

    @Test
    fun invalidAudioConfigEpochIsRejectedWithoutConfiguringPlayback() {
        val session = audioStreamingSession()

        val result = session.receive(audioConfigEnvelope(8, configEpoch = 0)).single() as ProtocolV1Session.Action.Send

        assertFalse(result.envelope.audioConfigResult.accepted)
        assertEquals("invalid_audio_config_epoch", result.envelope.audioConfigResult.rejectionReason)
        assertFalse(session.canReceiveAudio)
    }

    @Test
    fun managedPolicyAudioDenyStopsActiveAudio() {
        val session = audioStreamingSession()
        val requested =
            session.receive(audioConfigEnvelope(8)).single()
                as ProtocolV1Session.Action.AudioConfigurationRequested
        assertTrue(session.completeAudioConfiguration(requested.config, accepted = true, rejectionReason = "", correlationId = requested.correlationId)!!.audioConfigResult.accepted)
        assertTrue(session.canReceiveAudio)

        val actions = session.receive(
            managedPolicyStatus(
                9,
                ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(isManaged = true, audioAllowed = false).toStatus(),
            ),
        )

        assertTrue(actions.any { it is ProtocolV1Session.Action.AudioStopped && it.reason == "managed_policy_audio_denied" })
        assertFalse(session.canReceiveAudio)
    }

    @Test
    fun acceptedAudioRemainsReceivableDuringDisplayReconfiguration() {
        val session = audioMultiDisplayStreamingSession()
        val requested =
            session.receive(audioConfigEnvelope(8)).single()
                as ProtocolV1Session.Action.AudioConfigurationRequested
        assertTrue(session.completeAudioConfiguration(requested.config, accepted = true, rejectionReason = "", correlationId = requested.correlationId)!!.audioConfigResult.accepted)
        assertTrue(session.canReceiveAudio)

        assertNotNull(session.selectDisplay("display-2"))

        assertTrue(session.canReceiveAudio)
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
    fun hdrVideoConfigWithoutNegotiatedHdrReturnsSdrFallback() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(
                2,
                advertisedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_COLOR_MANAGEMENT),
            ),
        )
        session.receive(
            sessionAccepted(
                3,
                negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_COLOR_MANAGEMENT),
            ),
        )
        session.receive(displayList(4))
        session.receive(startDisplay(5))

        val result = session.receive(videoConfig(6, colorDescription = hdrColor())).single() as ProtocolV1Session.Action.Send

        assertFalse(result.envelope.videoConfigResult.accepted)
        assertEquals(
            VideoColorNegotiation.UNSUPPORTED_COLOR_OR_DECODE_PROFILE,
            result.envelope.videoConfigResult.rejectionReason,
        )
        assertEquals(VideoColorNegotiation.legacySdrColor, result.envelope.videoConfigResult.selectedColorDescription)
        assertFalse(session.isStreaming)
    }

    @Test
    fun unsupportedDecodeProfileRejectsWithoutSelectedColorFallback() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(
                2,
                advertisedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_COLOR_MANAGEMENT),
            ),
        )
        session.receive(
            sessionAccepted(
                3,
                negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_COLOR_MANAGEMENT),
            ),
        )
        session.receive(displayList(4))
        session.receive(startDisplay(5))

        val result =
            session.receive(
                videoConfig(
                    6,
                    colorDescription = hdrColor(),
                    framesPerSecond = 144,
                ),
            ).single() as ProtocolV1Session.Action.Send

        assertFalse(result.envelope.videoConfigResult.accepted)
        assertEquals(
            VideoColorNegotiation.UNSUPPORTED_COLOR_OR_DECODE_PROFILE,
            result.envelope.videoConfigResult.rejectionReason,
        )
        assertFalse(result.envelope.videoConfigResult.hasSelectedColorDescription())
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
                    allowedHostsRestricted = true,
                ),
        )
        session.clientHello()
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MANAGED_CONFIGURATION)
        session.receive(hostHello(2, advertisedCapabilities = caps))

        val actions = session.receive(sessionAccepted(3, negotiatedCapabilities = caps))
            .filterIsInstance<ProtocolV1Session.Action.Send>()

        assertEquals(1, actions.size)
        assertEquals(Envelope.PayloadCase.MANAGED_POLICY_STATUS, actions[0].envelope.payloadCase)
        val status = actions[0].envelope.managedPolicyStatus
        assertTrue(status.managed)
        assertFalse(status.hostActionsAllowed)
        assertEquals(2_048, status.maximumFileBytes)
        assertEquals(listOf("host"), status.allowedHostsList)
        assertTrue(status.allowedHostsRestricted)
        assertEquals(
            ProtocolV1Session.ManagedPolicy.REQUIRED_RESTRICTIONS,
            status.restrictionResultsList.map { it.restriction }.toSet(),
        )
        assertTrue(
            status.restrictionResultsList.all { it.source == "managed_configuration" && it.reason.isNotBlank() },
        )

        val remote = managedStatus(fileTransferAllowed = true, maximumFileBytes = 4_096)
        val hostPolicyActions = session.receive(managedPolicyStatus(4, remote))
        val afterHostPolicy = hostPolicyActions.filterIsInstance<ProtocolV1Session.Action.Send>().single()
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, afterHostPolicy.envelope.payloadCase)
    }

    @Test
    fun managedPolicyGateRejectsOrdinaryMessagesBeforeRemotePolicyStatus() {
        val caps =
            listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_FILE_TRANSFER,
                Capability.CAPABILITY_HOST_ACTIONS,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            )
        val resourceLimits =
            ResourceLimits
                .newBuilder()
                .setMaximumFileBytes(4_096)
                .setMaximumFileChunkBytes(1_024)
                .build()

        fun awaitingPolicySession(): ProtocolV1Session {
            val session = session()
            session.clientHello()
            session.receive(hostHello(2, advertisedCapabilities = caps))
            session.receive(sessionAccepted(3, negotiatedCapabilities = caps, resourceLimits = resourceLimits))
            return session
        }

        assertInvalidPeerMessage { awaitingPolicySession().receive(displayList(4)) }
        assertInvalidPeerMessage { awaitingPolicySession().receive(base(4).setFileOffer(fileOffer()).build()) }
        assertInvalidPeerMessage { awaitingPolicySession().receive(hostActionCatalog(4)) }
    }

    @Test
    fun managedPolicyStatusWithMissingRestrictionResultsFailsClosed() {
        val session = session()
        session.clientHello()
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MANAGED_CONFIGURATION)
        session.receive(hostHello(2, advertisedCapabilities = caps))
        val actions = session.receive(sessionAccepted(3, negotiatedCapabilities = caps))
        assertEquals(Envelope.PayloadCase.MANAGED_POLICY_STATUS, (actions.single() as ProtocolV1Session.Action.Send).envelope.payloadCase)

        val missingResults =
            ManagedPolicyStatus
                .newBuilder()
                .setManaged(true)
                .setClipboardAllowed(true)
                .setFileTransferAllowed(true)
                .setAudioAllowed(true)
                .setWakeAllowed(true)
                .setCustomGesturesAllowed(true)
                .setHostActionsAllowed(true)
                .setMaximumFileBytes(4_096)
                .build()

        assertInvalidPeerMessage { session.receive(managedPolicyStatus(4, missingResults)) }
    }

    @Test
    fun managedPolicyStatusWithMismatchedRestrictionResultFailsClosed() {
        val session = session()
        session.clientHello()
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MANAGED_CONFIGURATION)
        session.receive(hostHello(2, advertisedCapabilities = caps))
        session.receive(sessionAccepted(3, negotiatedCapabilities = caps))

        val mismatched =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                clipboardAllowed = false,
                maximumFileBytes = 4_096,
                allowedHosts = setOf("host"),
                allowedHostsRestricted = true,
            ).toStatus().toBuilder()
                .setRestrictionResults(
                    0,
                    ProtocolV1Session.ManagedPolicy.UNMANAGED.toStatus().restrictionResultsList[0],
                ).build()

        assertInvalidPeerMessage { session.receive(managedPolicyStatus(4, mismatched)) }
    }

    @Test
    fun remoteManagedPolicyDenyClearsHostActionsAndBlocksInvoke() {
        val session = hostActionManagedStreamingSession()
        session.receive(hostActionCatalog(8))
        assertTrue(session.canInvokeHostActions)
        assertEquals(listOf("move-window", "return-windows"), session.hostActions.map { it.id })

        val denied =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                hostActionsAllowed = false,
                maximumFileBytes = 4_096,
                allowedHosts = setOf("host"),
                allowedHostsRestricted = true,
            ).toStatus()
        val actions = session.receive(managedPolicyStatus(9, denied))

        val available = actions.filterIsInstance<ProtocolV1Session.Action.HostActionsAvailable>().single()
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
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                allowedHosts = setOf("different-host"),
                allowedHostsRestricted = true,
            ).toStatus()

        assertInvalidPeerMessage { session.receive(managedPolicyStatus(4, restricted)) }
    }

    @Test
    fun remoteManagedPolicyDeniedHostFailsClosedEvenWhenAllowed() {
        val session = session()
        session.clientHello()
        val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MANAGED_CONFIGURATION)
        session.receive(hostHello(2, advertisedCapabilities = caps))
        session.receive(sessionAccepted(3, negotiatedCapabilities = caps))

        val denied =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                allowedHosts = setOf("host"),
                deniedHosts = setOf("host"),
                allowedHostsRestricted = true,
            ).toStatus()

        assertInvalidPeerMessage { session.receive(managedPolicyStatus(4, denied)) }
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
    fun acceptsSessionAcceptedThatOmitsCapabilityAfterDependencyPruning() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(
                id = 2,
                advertisedCapabilities = listOf(Capability.CAPABILITY_STYLUS_EXTENDED),
            ),
        )

        val listRequest =
            session.receive(sessionAccepted(3, negotiatedCapabilities = emptyList())).single()
                as ProtocolV1Session.Action.Send

        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, listRequest.envelope.payloadCase)
        assertTrue(session.negotiated.isEmpty())
    }

    @Test
    fun rejectsSessionAcceptedThatOmitsMutuallyAdvertisedKeyboard() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(
                id = 2,
                advertisedCapabilities = listOf(Capability.CAPABILITY_KEYBOARD),
            ),
        )

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

        assertTrue(session.selectDisplay("display-main").isEmpty())
        assertTrue(session.selectDisplay("unknown-display").isEmpty())

        val actions = session.selectDisplay("display-2")
        val pending = actions[0] as ProtocolV1Session.Action.DisplaySelectionPending
        val request = actions[1] as ProtocolV1Session.Action.Send
        assertEquals("display-main", pending.selectedId)
        assertEquals("display-2", pending.pendingId)
        assertEquals(
            Envelope.PayloadCase.START_DISPLAY_REQUEST,
            request.envelope.payloadCase,
        )
        assertEquals("display-2", request.envelope.startDisplayRequest.sourceDisplayId)
        assertEquals("display-main", session.selectedDisplayId)
        assertEquals("display-2", session.pendingDisplaySelectionId)
    }

    @Test
    fun runtimeDisplaySelectionPublishesActiveDisplayOnlyAfterConfigurationCommit() {
        val session = multiDisplayStreamingSession()

        session.selectDisplay("display-2")
        session.receive(
            base(20).setStartDisplayResponse(
                StartDisplayResponse
                    .newBuilder()
                    .setAccepted(true)
                    .setStreamId(43)
                    .setDisplay(
                        DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-2")
                            .setName("Display 2")
                            .setLogicalSize(Dimensions.newBuilder().setWidth(2560).setHeight(1440)),
                ),
            ).build(),
        )
        val oldStreamMedia =
            MediaPacketHeader
                .newBuilder()
                .setSessionEpoch(7)
                .setStreamId(42)
                .setConfigEpoch(3)
                .setCodec(Codec.CODEC_HEVC)
                .setFrameId(1)
                .setFragmentIndex(0)
                .setFragmentCount(1)
                .setPayloadLength(1)
                .build()
        assertEquals(ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION, session.validateMedia(oldStreamMedia))
        val requested =
            session.receive(videoConfig(21, configEpoch = 4, streamId = 43)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested

        val committed =
            session.completeVideoConfiguration(
                completedConfigEpoch = 4,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        val confirmed = committed.filterIsInstance<ProtocolV1Session.Action.DisplaySelectionConfirmed>().single()
        assertEquals("display-2", confirmed.selectedId)
        val available = committed.filterIsInstance<ProtocolV1Session.Action.DisplaysAvailable>().single()
        assertEquals(listOf("display-main", "display-2"), available.displays.map { it.id })
        assertEquals("display-2", available.selectedId)
        assertEquals("display-2", session.selectedDisplayId)
        assertNull(session.pendingDisplaySelectionId)
    }

    @Test
    fun runtimeDisplaySelectionCommitsKnownGeometryWhenStartResponseOmitsDescriptor() {
        val session = multiDisplayStreamingSession()

        session.selectDisplay("display-2")
        session.receive(
            base(20).setStartDisplayResponse(
                StartDisplayResponse
                    .newBuilder()
                    .setAccepted(true)
                    .setStreamId(43),
            ).build(),
        )
        val requested =
            session.receive(videoConfig(21, configEpoch = 4, streamId = 43)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested

        val committed =
            session.completeVideoConfiguration(
                completedConfigEpoch = 4,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        val geometry = committed.filterIsInstance<ProtocolV1Session.Action.DisplayGeometryChanged>().single()

        assertEquals("display-2", session.selectedDisplayId)
        assertEquals(2560, geometry.width)
        assertEquals(1440, geometry.height)
        val touch = session.touch(100, 1, InputPhase.INPUT_PHASE_BEGAN, 0.25, 0.75)
        assertEquals("display-2", touch.touchEvent.target.displayId)
        assertEquals(43L, touch.touchEvent.target.streamId)
    }

    @Test
    fun runtimeDisplaySelectionRejectsWithoutChangingActiveDisplayWhenHostDeclines() {
        val session = multiDisplayStreamingSession()

        session.selectDisplay("display-2")
        val rejected =
            session.receive(
                base(20).setStartDisplayResponse(
                    StartDisplayResponse
                        .newBuilder()
                        .setAccepted(false)
                        .setRejectionReason("display_unavailable"),
                ).build(),
            ).filterIsInstance<ProtocolV1Session.Action.DisplaySelectionRejected>().single()

        assertEquals("display-main", rejected.selectedId)
        assertEquals("display-2", rejected.rejectedId)
        assertEquals("display_unavailable", rejected.reason)
        assertEquals("display-main", session.selectedDisplayId)
        assertNull(session.pendingDisplaySelectionId)
        assertTrue(session.isStreaming)
        val touch = session.touch(100, 1, InputPhase.INPUT_PHASE_BEGAN, 0.25, 0.75)
        assertEquals("display-main", touch.touchEvent.target.displayId)
        assertEquals(42L, touch.touchEvent.target.streamId)
    }

    @Test
    fun runtimeDisplaySelectionRejectsWithoutChangingActiveDisplayWhenDecoderRejects() {
        val session = multiDisplayStreamingSession()

        session.selectDisplay("display-2")
        session.receive(
            base(20).setStartDisplayResponse(
                StartDisplayResponse
                    .newBuilder()
                    .setAccepted(true)
                    .setStreamId(43)
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
            session.receive(videoConfig(21, configEpoch = 4, streamId = 43)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested

        val rejected =
            session.completeVideoConfiguration(
                completedConfigEpoch = 4,
                configurationToken = requested.configurationToken,
                accepted = false,
                rejectionReason = "decoder_configuration_failure",
            ).filterIsInstance<ProtocolV1Session.Action.DisplaySelectionRejected>().single()

        assertEquals("display-main", rejected.selectedId)
        assertEquals("display-2", rejected.rejectedId)
        assertEquals("decoder_configuration_failure", rejected.reason)
        assertEquals("display-main", session.selectedDisplayId)
        assertNull(session.pendingDisplaySelectionId)
        assertTrue(session.isStreaming)
    }

    @Test
    fun runtimeDisplaySelectionRejectsWithoutChangingActiveDisplayWhenVideoConfigIsUnsupported() {
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

        val actions =
            session.receive(
                videoConfig(21, configEpoch = 4)
                    .toBuilder()
                    .setVideoConfig(videoConfig(21, configEpoch = 4, streamId = 99).videoConfig)
                    .build(),
            )
        val rejected = actions.filterIsInstance<ProtocolV1Session.Action.DisplaySelectionRejected>().single()

        assertEquals("display-main", rejected.selectedId)
        assertEquals("display-2", rejected.rejectedId)
        assertEquals("unsupported_video_config", rejected.reason)
        assertEquals("display-main", session.selectedDisplayId)
        assertNull(session.pendingDisplaySelectionId)
        assertTrue(session.isStreaming)
        val touch = session.touch(100, 1, InputPhase.INPUT_PHASE_BEGAN, 0.25, 0.75)
        assertEquals("display-main", touch.touchEvent.target.displayId)
        assertEquals(42L, touch.touchEvent.target.streamId)
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
    fun preferenceChangeDuringRejectedDisplaySelectionIsNotFlushedLater() {
        val session = multiDisplayVideoControlStreamingSession()
        session.selectDisplay("display-2")

        assertNull(
            session.setVideoPreferences(
                bitrateKbps = 20_000,
                framesPerSecond = 60,
                qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
            ),
        )
        session.receive(
            base(20).setStartDisplayResponse(
                StartDisplayResponse
                    .newBuilder()
                    .setAccepted(false)
                    .setRejectionReason("display_unavailable"),
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

        assertFalse(
            committed
                .filterIsInstance<ProtocolV1Session.Action.Send>()
                .map { it.envelope }
                .any { it.payloadCase == Envelope.PayloadCase.SET_VIDEO_PREFERENCES },
        )
        assertFalse(
            committed
                .filterIsInstance<ProtocolV1Session.Action.VideoConfigurationCommitted>()
                .single()
                .appliesClientVideoPreferences,
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
    fun videoPreferenceCommitDoesNotRepublishDisplaySelection() {
        val session = videoControlStreamingSession()
        session.setVideoPreferences(
            bitrateKbps = 8_000,
            framesPerSecond = 30,
            qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
        )
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

        assertTrue(
            committed
                .filterIsInstance<ProtocolV1Session.Action.VideoConfigurationCommitted>()
                .single()
                .appliesClientVideoPreferences,
        )
        assertTrue(committed.filterIsInstance<ProtocolV1Session.Action.DisplaysAvailable>().isEmpty())
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
    fun defaultClientHelloExcludesWakeHostCapability() {
        val hello = session().clientHello()

        assertFalse(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_WAKE_HOST))
    }

    @Test
    fun advertiseWakeHostAllowsCapabilityAdvertisement() {
        val session = session(advertiseWakeHost = true)
        val hello = session.clientHello()

        assertTrue(hello.clientHello.capabilitiesList.contains(Capability.CAPABILITY_WAKE_HOST))
    }

    @Test
    fun requestWakeHostTracksResultByRequestId() {
        val session = wakeHostStreamingSession()
        val requestId = ByteString.copyFrom(byteArrayOf(0x44))
        val mac = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4, 5, 6))
        val secret = ByteArray(32) { it.toByte() }

        val request = session.requestWakeHost(requestId, mac, authorizationSecret = secret)!!
        assertEquals(Envelope.PayloadCase.WAKE_HOST_REQUEST, request.payloadCase)
        assertEquals(requestId, request.wakeHostRequest.requestId)
        assertEquals(mac, request.wakeHostRequest.targetMacAddress)
        assertEquals("mac-host", request.wakeHostRequest.hostId)
        assertEquals("android-test", request.wakeHostRequest.deviceId)
        assertEquals(WakeHostProof.keyId(secret), request.wakeHostRequest.keyId)
        assertTrue(request.wakeHostRequest.issuedAtUnixSeconds > 0)
        assertEquals(request.wakeHostRequest.issuedAtUnixSeconds + 60, request.wakeHostRequest.expiresAtUnixSeconds)
        assertEquals(WakeHostProof.MINIMUM_NONCE_BYTES, request.wakeHostRequest.nonce.size())
        assertEquals(WakeHostProof.SIGNATURE_BYTES, request.wakeHostRequest.signature.size())
        val proofContext =
            WakeHostRequestContext(
                requestId = request.wakeHostRequest.requestId,
                targetMacAddress = request.wakeHostRequest.targetMacAddress,
                secureOnPassword = request.wakeHostRequest.secureOnPassword,
                hostId = request.wakeHostRequest.hostId,
                deviceId = request.wakeHostRequest.deviceId,
                keyId = request.wakeHostRequest.keyId,
                issuedAtUnixSeconds = request.wakeHostRequest.issuedAtUnixSeconds,
                expiresAtUnixSeconds = request.wakeHostRequest.expiresAtUnixSeconds,
                nonce = request.wakeHostRequest.nonce,
            )
        assertEquals(WakeHostProof.signature(proofContext, secret).toList(), request.wakeHostRequest.signature.toByteArray().toList())
        assertTrue(session.receive(wakeHostResult(7, ByteString.copyFrom(byteArrayOf(0x45)), accepted = true)).isEmpty())

        val completed =
            session.receive(wakeHostResult(8, requestId, accepted = false, rejectionReason = "wake_host_policy_denied")).single()
                as ProtocolV1Session.Action.WakeHostCompleted
        assertEquals(requestId, completed.requestId)
        assertFalse(completed.accepted)
        assertEquals("wake_host_policy_denied", completed.rejectionReason)
        assertTrue(session.receive(wakeHostResult(9, requestId, accepted = true)).isEmpty())
    }

    @Test
    fun completeWakeHostEchoesRequestCorrelationAndDefaultRejectedReason() {
        val session = wakeHostStreamingSession()
        val requestId = ByteString.copyFrom(byteArrayOf(0x55))

        val response = session.completeWakeHost(
            requestId = requestId,
            accepted = false,
            rejectionReason = "",
            correlationId = 17,
        )!!

        assertEquals(Envelope.PayloadCase.WAKE_HOST_RESULT, response.payloadCase)
        assertEquals(17L, response.correlationId)
        assertEquals(requestId, response.wakeHostResult.requestId)
        assertFalse(response.wakeHostResult.accepted)
        assertEquals("wake_host_rejected", response.wakeHostResult.rejectionReason)
    }

    @Test
    fun requestWakeHostBoundsPendingResultsAndRequiresHostIdentity() {
        val blankHostSession = wakeHostStreamingSession(hostId = "")
        val mac = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4, 5, 6))
        assertNull(blankHostSession.requestWakeHost(ByteString.copyFrom(byteArrayOf(0x01)), mac))

        val session = wakeHostStreamingSession()
        val requestIds = (0 until 17).map { ByteString.copyFrom(byteArrayOf(it.toByte())) }
        requestIds.forEach { requestId -> assertNotNull(session.requestWakeHost(requestId, mac)) }

        assertTrue(session.receive(wakeHostResult(20, requestIds.first(), accepted = true)).isEmpty())
        val newest = session.receive(wakeHostResult(21, requestIds.last(), accepted = true)).single()
            as ProtocolV1Session.Action.WakeHostCompleted
        assertEquals(requestIds.last(), newest.requestId)
        assertTrue(newest.accepted)
    }

    @Test
    fun wakeHostRequestRequiresNegotiatedCapabilityStreamingAndHostMatch() {
        val ungated = streamingSession()
        assertInvalidPeerMessage { ungated.receive(wakeHostRequest(7, hostId = "mac-host")) }

        val negotiated = wakeHostSessionThroughDisplayStart()
        assertFalse(negotiated.canRequestWakeHost)
        assertInvalidPeerMessage { negotiated.receive(wakeHostRequest(7, hostId = "mac-host")) }

        val streaming = wakeHostStreamingSession()
        val action =
            streaming.receive(wakeHostRequest(7, hostId = "mac-host")).single()
                as ProtocolV1Session.Action.WakeHost
        assertEquals(ByteString.copyFrom(byteArrayOf(0x31)), action.request.requestId)
        assertEquals(7L, action.correlationId)
        assertInvalidPeerMessage { wakeHostStreamingSession().receive(wakeHostRequest(8, hostId = "")) }

        assertInvalidPeerMessage { wakeHostStreamingSession().receive(wakeHostRequest(8, hostId = "other-host")) }

        assertInvalidPeerMessage { wakeHostStreamingSession().receive(wakeHostRequest(8, hostId = "mac-host", deviceId = "other-device")) }
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
    fun advertisePeripheralInputFrameworkIsExplicitAndDoesNotDropExistingCapabilities() {
        val defaultCapabilities = session().clientHello().clientHello.capabilitiesList.toSet()
        val session =
            ProtocolV1Session(
                deviceId = "android-test",
                deviceName = "Test Android",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
                advertisePeripheralInputFramework = true,
                nowNs = { 1_000L },
            )
        val hello = session.clientHello()
        assertFalse(defaultCapabilities.contains(Capability.CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK))
        assertEquals(
            defaultCapabilities + Capability.CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK,
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

        assertTrue(session.selectDisplay("display-2").isNotEmpty())
        assertFalse(session.canSendController)
    }

    @Test
    fun canSendControllerFalseWithoutNegotiation() {
        val session = streamingSession()
        assertFalse(session.canSendController)
    }

    @Test
    fun canSendPeripheralRequiresStreamingNegotiatedFrameworkCapability() {
        assertTrue(peripheralStreamingSession().canSendPeripheral)
        assertFalse(peripheralSessionThroughDisplayStart().canSendPeripheral)
        assertFalse(streamingSession().canSendPeripheral)
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
    fun peripheralEncodesBoundedAdmissionEnvelope() {
        val session = peripheralStreamingSession()

        val envelope = session.peripheral(
            inputId = 9,
            peripheralKind = "vendor-device",
            payload = byteArrayOf(0x01, 0x02),
        )

        assertEquals(Envelope.PayloadCase.PERIPHERAL_EVENT, envelope.payloadCase)
        assertEquals(9L, envelope.peripheralEvent.inputId)
        assertEquals("vendor-device", envelope.peripheralEvent.peripheralKind)
        assertEquals(listOf(0x01.toByte(), 0x02.toByte()), envelope.peripheralEvent.payload.toByteArray().toList())
        assertEquals("display-main", envelope.peripheralEvent.target.displayId)
        assertEquals(42L, envelope.peripheralEvent.target.streamId)
    }

    @Test
    fun peripheralRejectsInvalidLocalEnvelopeFields() {
        val session = peripheralStreamingSession()

        assertThrows(IllegalArgumentException::class.java) {
            session.peripheral(inputId = 0, peripheralKind = "vendor-device", payload = byteArrayOf())
        }
        assertThrows(IllegalArgumentException::class.java) {
            session.peripheral(inputId = 1, peripheralKind = "", payload = byteArrayOf())
        }
        assertThrows(IllegalArgumentException::class.java) {
            session.peripheral(inputId = 1, peripheralKind = "a".repeat(129), payload = byteArrayOf())
        }
        assertThrows(IllegalArgumentException::class.java) {
            session.peripheral(
                inputId = 1,
                peripheralKind = "vendor-device",
                payload = ByteArray(ProtocolV1Session.MAX_PERIPHERAL_PAYLOAD_BYTES + 1),
            )
        }
    }

    @Test
    fun peripheralWithoutNegotiatedCapabilityFails() {
        val session = streamingSession()
        assertThrows(IllegalStateException::class.java) {
            session.peripheral(inputId = 1, peripheralKind = "vendor-device", payload = byteArrayOf())
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
    fun inputAckCanArriveForNegotiatedPeripheralFramework() {
        val session = peripheralStreamingSession()
        val ack =
            base(8)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(9)
                        .setAccepted(false)
                        .setRejectionReason("unsupported_peripheral_kind"),
                ).build()
        val action = session.receive(ack).single() as ProtocolV1Session.Action.ControllerInputAck
        assertEquals(9L, action.inputId)
        assertFalse(action.accepted)
        assertEquals("unsupported_peripheral_kind", action.rejectionReason)
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
        assertTrue(session.selectDisplay("display-2").isNotEmpty())
        val ack =
            base(7)
                .setInputAck(InputAck.newBuilder().setInputId(9).setAccepted(true))
                .build()

        val action = session.receive(ack).single() as ProtocolV1Session.Action.ControllerInputAck
        assertEquals(9L, action.inputId)
        assertTrue(action.accepted)
        assertEquals("", action.rejectionReason)
    }

    @Test
    fun fileTransferNegotiationSendsManagedPolicyAndListDisplaysWithPeerLimits() {
        val capabilities =
            listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_FILE_TRANSFER,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            )
        val peerLimits =
            ResourceLimits
                .newBuilder()
                .setMaximumFileBytes(10)
                .setMaximumFileChunkBytes(4)
                .build()
        val session = session()
        session.clientHello()
        session.receive(hostHello(2, advertisedCapabilities = capabilities))

        val initialActions = session.receive(
            sessionAccepted(3, negotiatedCapabilities = capabilities, resourceLimits = peerLimits),
        ).map { it as ProtocolV1Session.Action.Send }

        assertEquals(1, initialActions.size)
        assertEquals(Envelope.PayloadCase.MANAGED_POLICY_STATUS, initialActions[0].envelope.payloadCase)
        assertFalse(initialActions[0].envelope.managedPolicyStatus.managed)
        assertTrue(initialActions[0].envelope.managedPolicyStatus.fileTransferAllowed)
        assertEquals(FileTransferPolicy.DEFAULT_MAXIMUM_FILE_BYTES, initialActions[0].envelope.managedPolicyStatus.maximumFileBytes)
        val actions = session.receive(managedPolicyStatus(4, managedStatus(fileTransferAllowed = true, maximumFileBytes = 4_096)))
            .filterIsInstance<ProtocolV1Session.Action.Send>()
        assertEquals(1, actions.size)
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, actions[0].envelope.payloadCase)
        assertTrue(session.canTransferFiles)
        assertEquals(10L, session.negotiatedFilePolicy.maximumFileBytes)
        assertEquals(4, session.negotiatedFilePolicy.maximumChunkBytes)
    }

    @Test
    fun managedConfigurationCanNegotiateWithoutFileTransfer() {
        val session = session()
        session.clientHello()

        session.receive(hostHello(2, advertisedCapabilities = listOf(Capability.CAPABILITY_MANAGED_CONFIGURATION)))
        val actions = session.receive(
            sessionAccepted(3, negotiatedCapabilities = listOf(Capability.CAPABILITY_MANAGED_CONFIGURATION)),
        ).filterIsInstance<ProtocolV1Session.Action.Send>()

        assertEquals(1, actions.size)
        assertEquals(Envelope.PayloadCase.MANAGED_POLICY_STATUS, actions[0].envelope.payloadCase)
        val afterHostPolicy = session.receive(managedPolicyStatus(4, managedStatus(fileTransferAllowed = true, maximumFileBytes = 4_096)))
            .filterIsInstance<ProtocolV1Session.Action.Send>().single()
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, afterHostPolicy.envelope.payloadCase)
        assertFalse(session.canTransferFiles)
    }

    @Test
    fun zeroMaximumRemotePolicyRemovesFileTransferCapabilityBeforeDisplayList() {
        val capabilities =
            listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_FILE_TRANSFER,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            )
        val session = session()
        session.clientHello()
        session.receive(hostHello(2, advertisedCapabilities = capabilities))
        session.receive(sessionAccepted(3, negotiatedCapabilities = capabilities))
        val actions = session.receive(managedPolicyStatus(4, managedStatus(fileTransferAllowed = true, maximumFileBytes = 0)))
            .filterIsInstance<ProtocolV1Session.Action.Send>()

        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, actions.single().envelope.payloadCase)
        assertFalse(session.canTransferFiles)
        assertFalse(Capability.CAPABILITY_FILE_TRANSFER in session.negotiated)
        assertEquals(0L, session.negotiatedFilePolicy.maximumFileBytes)
    }

    @Test
    fun fileControlMessagesRequireNegotiatedCapabilityAndNonEmptyTransferId() {
        val ungated = streamingSession()
        assertInvalidPeerMessage { ungated.receive(base(7).setFileOffer(fileOffer()).build()) }

        val session = fileTransferStreamingSession()
        val offer = fileOffer()
        val received = session.receive(base(8).setFileOffer(offer).build()).single()
            as ProtocolV1Session.Action.FileOfferReceived
        assertEquals(offer.transferId, received.offer.transferId)

        val accept = FileAccept.newBuilder().setTransferId(offer.transferId).setAccepted(true).build()
        val accepted = session.receive(base(9).setFileAccept(accept).build()).single()
            as ProtocolV1Session.Action.FileAcceptReceived
        assertTrue(accepted.response.accepted)

        val progress =
            FileTransferProgress
                .newBuilder()
                .setTransferId(offer.transferId)
                .setReceivedBytes(5)
                .build()
        val progressed = session.receive(base(10).setFileTransferProgress(progress).build()).single()
            as ProtocolV1Session.Action.FileProgressReceived
        assertEquals(5L, progressed.progress.receivedBytes)

        val cancel = FileTransferCancel.newBuilder().setTransferId(offer.transferId).setReasonCode("user_cancelled").build()
        val cancelled = session.receive(base(11).setFileTransferCancel(cancel).build()).single()
            as ProtocolV1Session.Action.FileCancelReceived
        assertEquals("user_cancelled", cancelled.cancellation.reasonCode)

        val complete =
            FileTransferComplete
                .newBuilder()
                .setTransferId(offer.transferId)
                .setAccepted(true)
                .setSha256(sha256("hello".toByteArray()))
                .build()
        val completed = session.receive(base(12).setFileTransferComplete(complete).build()).single()
            as ProtocolV1Session.Action.FileCompleteReceived
        assertTrue(completed.result.accepted)

        assertInvalidPeerMessage {
            session.receive(base(13).setFileAccept(FileAccept.newBuilder().setAccepted(true)).build())
        }
    }

    @Test
    fun fileControlSendersAreNullUntilNegotiatedAndSessionScopedAfterwards() {
        val ungated = streamingSession()
        val transferId = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4))
        assertNull(ungated.offerFile(fileOffer(transferId)))
        assertNull(ungated.fileAccept(FileAccept.newBuilder().setTransferId(transferId).setAccepted(true).build()))
        assertNull(ungated.fileProgress(transferId, 1))
        assertNull(ungated.fileComplete(transferId, accepted = true, sha256 = ByteString.EMPTY, rejectionReason = ""))
        assertNull(ungated.fileCancel(transferId, "test"))

        val session = fileTransferStreamingSession()
        assertEquals(Envelope.PayloadCase.FILE_OFFER, session.offerFile(fileOffer(transferId))!!.payloadCase)
        assertEquals(
            Envelope.PayloadCase.FILE_ACCEPT,
            session.fileAccept(FileAccept.newBuilder().setTransferId(transferId).setAccepted(true).build())!!.payloadCase,
        )
        assertEquals(Envelope.PayloadCase.FILE_TRANSFER_PROGRESS, session.fileProgress(transferId, 1)!!.payloadCase)
        assertEquals(
            Envelope.PayloadCase.FILE_TRANSFER_COMPLETE,
            session.fileComplete(transferId, accepted = false, sha256 = ByteString.EMPTY, rejectionReason = "policy_denied")!!.payloadCase,
        )
        assertEquals(Envelope.PayloadCase.FILE_TRANSFER_CANCEL, session.fileCancel(transferId, "user_cancelled")!!.payloadCase)
    }

    @Test
    fun remoteManagedPolicyStatusRequiresNegotiatedManagedConfiguration() {
        val ungated = streamingSession()
        val status = managedStatus(fileTransferAllowed = false, maximumFileBytes = 10)
        assertInvalidPeerMessage { ungated.receive(base(7).setManagedPolicyStatus(status).build()) }

        val session = fileTransferStreamingSession()
        val action = session.receive(base(8).setManagedPolicyStatus(status).build()).single()
            as ProtocolV1Session.Action.ManagedPolicyReceived
        assertFalse(action.status.fileTransferAllowed)
        assertEquals(10L, action.status.maximumFileBytes)
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

    private val peripheralCaps =
        listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK)

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

    private fun peripheralSessionThroughDisplayStart(): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-test",
            deviceName = "Test Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
            advertisePeripheralInputFramework = true,
            nowNs = { 1_000L },
        ).also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = peripheralCaps))
            it.receive(sessionAccepted(3, negotiatedCapabilities = peripheralCaps))
            it.receive(displayList(4))
            it.receive(startDisplay(5))
        }

    private fun peripheralStreamingSession(): ProtocolV1Session =
        peripheralSessionThroughDisplayStart().also {
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

    private val audioCaps =
        listOf(
            Capability.CAPABILITY_TOUCH,
            Capability.CAPABILITY_AUDIO,
            Capability.CAPABILITY_MANAGED_CONFIGURATION,
        )

    private fun audioStreamingSession(): ProtocolV1Session =
        session().also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = audioCaps))
            it.receive(
                sessionAccepted(
                    3,
                    negotiatedCapabilities = audioCaps,
                    resourceLimits = ResourceLimits.newBuilder().setMaximumAudioStreams(1).build(),
                ),
            )
            it.receive(managedPolicyStatus(4, managedStatus(fileTransferAllowed = true, maximumFileBytes = 4_096)))
            it.receive(displayList(5))
            it.receive(startDisplay(6))
            val requested =
                it.receive(videoConfig(7)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }

    private fun audioMultiDisplayStreamingSession(): ProtocolV1Session {
        val capabilities = audioCaps + Capability.CAPABILITY_MULTI_DISPLAY
        return session().also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = capabilities))
            it.receive(
                sessionAccepted(
                    3,
                    negotiatedCapabilities = capabilities,
                    resourceLimits = ResourceLimits.newBuilder().setMaximumAudioStreams(1).build(),
                ),
            )
            it.receive(managedPolicyStatus(4, managedStatus(fileTransferAllowed = true, maximumFileBytes = 4_096)))
            it.receive(twoDisplayList(5))
            it.receive(startDisplay(6))
            val requested =
                it.receive(videoConfig(7)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }
    }

    private fun hostActionManagedStreamingSession(): ProtocolV1Session {
        val caps = hostActionCaps + Capability.CAPABILITY_MANAGED_CONFIGURATION
        return session().also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = caps))
            it.receive(sessionAccepted(3, negotiatedCapabilities = caps))
            it.receive(managedPolicyStatus(4, managedStatus(fileTransferAllowed = true, maximumFileBytes = 4_096)))
            it.receive(displayList(5))
            it.receive(startDisplay(6))
            val requested =
                it.receive(videoConfig(7)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }
    }

    private val wakeHostCaps =
        listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_WAKE_HOST)

    private fun wakeHostSessionThroughDisplayStart(hostId: String = "mac-host"): ProtocolV1Session =
        session(advertiseWakeHost = true).also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = wakeHostCaps, hostId = hostId))
            it.receive(sessionAccepted(3, negotiatedCapabilities = wakeHostCaps))
            it.receive(displayList(4))
            it.receive(startDisplay(5))
        }

    private fun wakeHostStreamingSession(hostId: String = "mac-host"): ProtocolV1Session =
        wakeHostSessionThroughDisplayStart(hostId = hostId).also {
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

    private fun multiDisplayVideoControlStreamingSession(): ProtocolV1Session {
        val capabilities =
            listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_MULTI_DISPLAY,
                Capability.CAPABILITY_CLIENT_VIDEO_CONTROL,
            )
        return session().also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = capabilities))
            it.receive(sessionAccepted(3, negotiatedCapabilities = capabilities))
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
    }

    private fun session(
        localManagedPolicy: ProtocolV1Session.ManagedPolicy = ProtocolV1Session.ManagedPolicy.UNMANAGED,
        advertiseWakeHost: Boolean = false,
    ): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-test",
            deviceName = "Test Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
            localManagedPolicy = localManagedPolicy,
            advertiseWakeHost = advertiseWakeHost,
            nowNs = { 1_000L },
        )

    private fun fileTransferStreamingSession(): ProtocolV1Session {
        val capabilities =
            listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_FILE_TRANSFER,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            )
        return session().also {
            it.clientHello()
            it.receive(hostHello(2, advertisedCapabilities = capabilities))
            it.receive(sessionAccepted(3, negotiatedCapabilities = capabilities))
            it.receive(managedPolicyStatus(4, managedStatus(fileTransferAllowed = true, maximumFileBytes = 4_096)))
            it.receive(displayList(5))
            it.receive(startDisplay(6))
            val requested = it.receive(videoConfig(7)).single() as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(3, requested.configurationToken, true, "")
        }
    }

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
        hostId: String = "host",
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
                    .addAllCodecs(advertisedCodecs),
            ).build()

    private fun managedPolicyStatus(
        id: Long,
        status: ManagedPolicyStatus,
    ): Envelope = base(id).setManagedPolicyStatus(status).build()

    private fun wakeHostRequest(
        id: Long,
        requestId: ByteString = ByteString.copyFrom(byteArrayOf(0x31)),
        hostId: String = "",
        deviceId: String = "android-test",
    ): Envelope =
        base(id)
            .setWakeHostRequest(
                WakeHostRequest
                    .newBuilder()
                    .setRequestId(requestId)
                    .setTargetMacAddress(ByteString.copyFrom(byteArrayOf(1, 2, 3, 4, 5, 6)))
                    .setHostId(hostId)
                    .setDeviceId(deviceId),
            ).build()

    private fun wakeHostResult(
        id: Long,
        requestId: ByteString,
        accepted: Boolean,
        rejectionReason: String = "",
    ): Envelope =
        base(id)
            .setWakeHostResult(
                WakeHostResult
                    .newBuilder()
                    .setRequestId(requestId)
                    .setAccepted(accepted)
                    .setRejectionReason(rejectionReason),
            ).build()

    private fun sessionAccepted(
        id: Long,
        negotiatedCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
        resourceLimits: ResourceLimits = ResourceLimits.getDefaultInstance(),
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
                    .addAllNegotiatedCapabilities(negotiatedCapabilities)
                    .setNegotiatedResourceLimits(resourceLimits),
            ).build()

    private fun fileOffer(
        transferId: ByteString = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4)),
    ): FileOffer =
        FileOffer
            .newBuilder()
            .setTransferId(transferId)
            .setFileName("hello.txt")
            .setMimeType("text/plain")
            .setByteLength(5)
            .setSha256(sha256("hello".toByteArray()))
            .build()

    private fun managedStatus(
        fileTransferAllowed: Boolean,
        maximumFileBytes: Long,
    ): ManagedPolicyStatus =
        ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            fileTransferAllowed = fileTransferAllowed,
            maximumFileBytes = maximumFileBytes,
            allowedHosts = setOf("host"),
            allowedHostsRestricted = true,
        ).toStatus()

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
        colorDescription: ColorDescription? = null,
        framesPerSecond: Int = 60,
        streamId: Long = 42,
    ): Envelope =
        base(id)
            .setVideoConfig(
                VideoConfig
                    .newBuilder()
                    .setConfigEpoch(configEpoch)
                    .setCodec(Codec.CODEC_HEVC)
                    .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                    .setFramesPerSecond(framesPerSecond)
                    .setBitrateKbps(12_000)
                    .setStreamId(streamId)
                    .setRotationDegrees(90)
                    .also { builder ->
                        if (colorDescription != null) {
                            builder.colorDescription = colorDescription
                        }
                    },
            ).build()

    private fun audioConfigEnvelope(
        id: Long,
        streamId: Long = 2,
        configEpoch: Long = 1,
    ): Envelope =
        base(id)
            .setAudioConfig(
                AudioConfig
                    .newBuilder()
                    .setStreamId(streamId)
                    .setConfigEpoch(configEpoch)
                    .setCodec(AudioCodec.AUDIO_CODEC_PCM_S16LE)
                    .setSampleRateHz(48_000)
                    .setChannelCount(2)
                    .setFramesPerPacket(480),
            ).build()

    private fun hdrColor(): ColorDescription =
        ColorDescription
            .newBuilder()
            .setPrimaries(ColorPrimaries.COLOR_PRIMARIES_BT2020)
            .setTransferFunction(TransferFunction.TRANSFER_FUNCTION_PQ)
            .setMatrixCoefficients(MatrixCoefficients.MATRIX_COEFFICIENTS_BT2020_NON_CONSTANT)
            .setBitDepth(10)
            .build()

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
