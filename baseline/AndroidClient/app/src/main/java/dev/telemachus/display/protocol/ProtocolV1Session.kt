package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.telemachus.display.ControllerEventKind
import dev.telemachus.display.ControllerStateSample
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.ClientHello
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.ControllerEvent
import dev.vibescreen.protocol.v1.ControllerEventKind as ProtocolControllerEventKind
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostActionInvoke
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.InputTarget
import dev.vibescreen.protocol.v1.KeyEvent
import dev.vibescreen.protocol.v1.ListDisplaysRequest
import dev.vibescreen.protocol.v1.NormalizedPoint
import dev.vibescreen.protocol.v1.Ping
import dev.vibescreen.protocol.v1.PointerEvent
import dev.vibescreen.protocol.v1.Pong
import dev.vibescreen.protocol.v1.ProtocolError
import dev.vibescreen.protocol.v1.ProtocolErrorCode
import dev.vibescreen.protocol.v1.ProtocolRange
import dev.vibescreen.protocol.v1.RequestKeyframe
import dev.vibescreen.protocol.v1.ResourceLimits
import dev.vibescreen.protocol.v1.ScrollEvent
import dev.vibescreen.protocol.v1.SetVideoPreferences
import dev.vibescreen.protocol.v1.StartDisplayRequest
import dev.vibescreen.protocol.v1.StylusEvent
import dev.vibescreen.protocol.v1.StylusContactState
import dev.vibescreen.protocol.v1.StylusToolKind
import dev.vibescreen.protocol.v1.TransportKind
import dev.vibescreen.protocol.v1.TouchEvent
import dev.vibescreen.protocol.v1.VideoConfigResult
import dev.vibescreen.protocol.v1.VideoQualityPreset
import java.io.IOException

internal class ProtocolV1Failure(
    val reason: String,
    val retryable: Boolean,
    val source: Source,
    message: String,
) : IOException(message) {
    enum class Source {
        SESSION_REJECTED,
        HOST_PROTOCOL_ERROR,
        PEER_PROTOCOL_VIOLATION,
        FRAME,
        ENVELOPE,
        MEDIA_PAYLOAD,
    }
}

/** Product-session state machine. It intentionally has no Android, UI, codec, or transport imports. */
internal class ProtocolV1Session(
    private val deviceId: String,
    private val deviceName: String,
    private val transport: TransportKind,
    private val codecs: List<Codec>,
    private val nowNs: () -> Long = System::nanoTime,
) {
    sealed class Action {
        data class Send(val envelope: Envelope) : Action()

        data class DisplaysAvailable(
            val displays: List<DisplayOption>,
            val selectedId: String,
        ) : Action()

        data class VideoConfigurationRequested(
            val width: Int,
            val height: Int,
            val rotation: Int,
            val codec: Codec,
            val configEpoch: Long,
            val sessionEpoch: Long,
            val configurationToken: Long,
            val bitrateKbps: Int,
            val framesPerSecond: Int,
        ) : Action()

        data class VideoConfigurationCommitted(
            val configEpoch: Long,
            val appliesClientVideoPreferences: Boolean,
        ) : Action()

        data class VideoConfigurationRejected(
            val configEpoch: Long,
            val reason: String,
        ) : Action()

        data class DisplayGeometryChanged(
            val width: Int,
            val height: Int,
            val rotation: Int,
        ) : Action()

        data class PongReceived(val sequence: Long) : Action()

        /**
         * Host-advertised action catalog for the active session, filtered to
         * the fixed action ids this client understands. Empty when the host
         * advertises none the client can invoke.
         */
        data class HostActionsAvailable(
            val actions: List<HostAction>,
        ) : Action()

        /** Result of a previously invoked host action, correlated by [invocationId]. */
        data class HostActionCompleted(
            val invocationId: ByteString,
            val accepted: Boolean,
            val rejectionReason: String,
        ) : Action()

        data class Disconnected(
            val reasonCode: String,
            val mayResume: Boolean,
        ) : Action()
    }

    /** A host action the client may invoke, surfaced without Android imports. */
    data class HostAction(
        val id: String,
        val localizedName: String,
        val requiresConfirmation: Boolean,
    )

    /** A display advertised by the host that the client may select. */
    data class DisplayOption(
        val id: String,
        val name: String,
        val width: Int,
        val height: Int,
        val isPrimary: Boolean,
        val isVirtual: Boolean,
    )

    private enum class State {
        AWAITING_HOST_HELLO,
        AWAITING_SESSION,
        ACTIVE,
        DISPLAY_REQUESTED,
        STREAMING,
        REDISPLAY_REQUESTED,
        CLOSED,
    }

    private var state = State.AWAITING_HOST_HELLO
    private var nextMessageId = 1L
    private var nextVideoConfigurationToken = 1L
    private var lastInboundMessageId = 0L
    private var sessionId = ByteString.EMPTY
    private var sessionEpoch = 0L
    private var streamId = 0L
    private var configEpoch = 0L
    private var retiredConfigEpoch = 0L
    private var configuredCodec = Codec.CODEC_UNSPECIFIED
    private var pendingVideoConfiguration: PendingVideoConfiguration? = null
    // Latest client video-preferences intent that arrived while a
    // reconfiguration was still in flight (state != STREAMING). Only the newest
    // request is retained; it is sent once the replacement VideoConfig commits
    // so a rapid sequence of changes still delivers the final user intent to
    // the host instead of silently dropping the later ones.
    private var pendingVideoPreferences: PendingVideoPreferences? = null
    private var videoPreferencesRequestInFlight = false
    private var awaitingConfigurationKeyframe = false
    private var lastFrameId = 0L
    private var displayId = ""
    private var displayWidth = 0
    private var displayHeight = 0
    private var displayGeometryPublished = false
    private var availableDisplays = emptyList<DisplayOption>()
    private var negotiatedCapabilities = emptySet<Capability>()
    private var hostCapabilities = emptySet<Capability>()
    private var hostCodecs = emptySet<Codec>()
    // Host actions advertised for the active session, filtered to the fixed ids
    // this client can invoke. Reset whenever a session ends.
    private var availableHostActions = emptyList<HostAction>()
    // Invocation ids sent to the host and still awaiting a result. Bounded so a
    // client that spams actions cannot grow this without limit; the oldest id is
    // evicted when full. A result must match a tracked id, so the host cannot
    // forge an unsolicited success/failure that the UI would surface.
    private val pendingHostActionInvocations = ArrayDeque<ByteString>()

    private val advertisedCapabilities =
        setOf(
            Capability.CAPABILITY_TOUCH,
            Capability.CAPABILITY_KEYBOARD,
            Capability.CAPABILITY_POINTER,
            Capability.CAPABILITY_STYLUS,
            Capability.CAPABILITY_STYLUS_EXTENDED,
            Capability.CAPABILITY_CONTROLLER,
            Capability.CAPABILITY_MULTI_DISPLAY,
            Capability.CAPABILITY_CLIENT_VIDEO_CONTROL,
            Capability.CAPABILITY_HOST_ACTIONS,
        )
    private val requiredCapabilities = emptySet<Capability>()

    val activeSessionEpoch: Long
        @Synchronized
        get() = sessionEpoch

    /** Capabilities agreed by both peers; drives client-side control availability. */
    val negotiated: Set<Capability>
        @Synchronized
        get() = negotiatedCapabilities

    /** Host displays discovered during negotiation, empty until the list arrives. */
    val displays: List<DisplayOption>
        @Synchronized
        get() = availableDisplays

    /** Currently selected/active display id. */
    val selectedDisplayId: String
        @Synchronized
        get() = displayId

    val isStreaming: Boolean
        @Synchronized
        get() = state == State.STREAMING

    val canSendTouch: Boolean
        @Synchronized
        get() = state == State.STREAMING && Capability.CAPABILITY_TOUCH in negotiatedCapabilities

    val canSendPointer: Boolean
        @Synchronized
        get() = state == State.STREAMING && Capability.CAPABILITY_POINTER in negotiatedCapabilities

    val canSendKeyboard: Boolean
        @Synchronized
        get() = state == State.STREAMING && Capability.CAPABILITY_KEYBOARD in negotiatedCapabilities

    val canSendStylus: Boolean
        @Synchronized
        get() = state == State.STREAMING && Capability.CAPABILITY_STYLUS in negotiatedCapabilities

    val canSendExtendedStylus: Boolean
        @Synchronized
        get() =
            canSendStylus &&
                Capability.CAPABILITY_STYLUS_EXTENDED in negotiatedCapabilities

    val canSendController: Boolean
        @Synchronized
        get() = state == State.STREAMING && Capability.CAPABILITY_CONTROLLER in negotiatedCapabilities

    /** Host actions the client may invoke, empty until a catalog arrives. */
    val hostActions: List<HostAction>
        @Synchronized
        get() = availableHostActions

    /** Whether host actions were negotiated and the session is streaming. */
    val canInvokeHostActions: Boolean
        @Synchronized
        get() = state == State.STREAMING && Capability.CAPABILITY_HOST_ACTIONS in negotiatedCapabilities

    enum class MediaDisposition {
        ACCEPT,
        DROP_PENDING_CONFIGURATION,
        DROP_RETIRED_CONFIGURATION,
        DROP_AWAITING_KEYFRAME,
    }

    init {
        require(deviceId.isNotBlank()) { "deviceId must not be blank" }
        require(deviceName.isNotBlank()) { "deviceName must not be blank" }
        require(codecs.isNotEmpty() && codecs.none { it == Codec.CODEC_UNSPECIFIED }) { "At least one codec is required" }
    }

    @Synchronized
    fun clientHello(): Envelope {
        check(state == State.AWAITING_HOST_HELLO)
        val hello =
            ClientHello
                .newBuilder()
                .setSupportedProtocols(ProtocolRange.newBuilder().setMinimum(VERSION).setMaximum(VERSION))
                .setDeviceId(deviceId)
                .setDeviceName(deviceName)
                .addAllCapabilities(advertisedCapabilities)
                .addAllRequiredCapabilities(requiredCapabilities)
                .addAllCodecs(codecs)
                .addTransports(transport)
                .setResourceLimits(
                    ResourceLimits
                        .newBuilder()
                        .setMaximumClients(1)
                        .setMaximumDisplays(1)
                        .setMaximumVideoStreams(1),
                ).build()
        return envelope().setClientHello(hello).build()
    }

    @Synchronized
    fun receive(envelope: Envelope): List<Action> {
        validateEnvelope(envelope)
        return when (envelope.payloadCase) {
            Envelope.PayloadCase.HOST_HELLO -> onHostHello(envelope)
            Envelope.PayloadCase.SESSION_ACCEPTED -> onSessionAccepted(envelope)
            Envelope.PayloadCase.SESSION_REJECTED -> {
                val rejected = envelope.sessionRejected
                throw ProtocolV1Failure(
                    reason = rejected.reasonCode.ifBlank { "session_rejected" },
                    retryable = rejected.retryable,
                    source = ProtocolV1Failure.Source.SESSION_REJECTED,
                    message = rejected.message.ifBlank { "Session rejected: ${rejected.reasonCode}" },
                )
            }
            Envelope.PayloadCase.LIST_DISPLAYS_RESPONSE -> onDisplays(envelope)
            Envelope.PayloadCase.START_DISPLAY_RESPONSE -> onStartDisplay(envelope)
            Envelope.PayloadCase.VIDEO_CONFIG -> onVideoConfig(envelope)
            Envelope.PayloadCase.DISPLAY_CHANGED -> onDisplayChanged(envelope)
            Envelope.PayloadCase.PING ->
                listOf(
                    Action.Send(
                        envelope(correlationId = envelope.messageId)
                            .setPong(Pong.newBuilder().setSequence(envelope.ping.sequence))
                            .build(),
                    ),
                )
            Envelope.PayloadCase.PONG -> listOf(Action.PongReceived(envelope.pong.sequence))
            Envelope.PayloadCase.HOST_ACTION_CATALOG -> onHostActionCatalog(envelope)
            Envelope.PayloadCase.HOST_ACTION_RESULT -> onHostActionResult(envelope)
            Envelope.PayloadCase.DISCONNECT_NOTICE -> {
                pendingVideoConfiguration = null
                pendingVideoPreferences = null
                videoPreferencesRequestInFlight = false
                availableHostActions = emptyList()
                pendingHostActionInvocations.clear()
                state = State.CLOSED
                listOf(
                    Action.Disconnected(
                        reasonCode = envelope.disconnectNotice.reasonCode,
                        mayResume = envelope.disconnectNotice.mayResume,
                    ),
                )
            }
            Envelope.PayloadCase.PROTOCOL_ERROR -> {
                val error = envelope.protocolError
                throw ProtocolV1Failure(
                    reason = error.code.name,
                    retryable = error.retryable,
                    source = ProtocolV1Failure.Source.HOST_PROTOCOL_ERROR,
                    message = "Host protocol error ${error.code}: ${error.message}",
                )
            }
            else -> throw protocolFailure("Unexpected ${envelope.payloadCase} in state $state")
        }
    }

    @Synchronized
    fun ping(sequence: Long): Envelope {
        require(sequence > 0)
        check(state >= State.ACTIVE && state != State.CLOSED)
        return envelope().setPing(Ping.newBuilder().setSequence(sequence)).build()
    }

    @Synchronized
    fun requestKeyframe(reason: String): Envelope {
        check(state == State.STREAMING)
        return envelope()
            .setRequestKeyframe(RequestKeyframe.newBuilder().setStreamId(streamId).setReasonCode(reason.take(128)))
            .build()
    }

    /**
     * Ask the host to switch the captured display at runtime. Valid only while
     * streaming, when display selection was negotiated, and for a known display
     * other than the current one. Returns the StartDisplay request to send, or
     * null when the request is not applicable.
     */
    @Synchronized
    fun selectDisplay(targetDisplayId: String): Envelope? {
        if (state != State.STREAMING) return null
        if (Capability.CAPABILITY_MULTI_DISPLAY !in negotiatedCapabilities) return null
        if (targetDisplayId.isBlank() || targetDisplayId == displayId) return null
        if (availableDisplays.none { it.id == targetDisplayId }) return null
        state = State.REDISPLAY_REQUESTED
        displayGeometryPublished = false
        // Adopt the requested id up front so the StartDisplayResponse and later
        // DisplayChanged for the new display validate against the selection.
        displayId = targetDisplayId
        val request =
            StartDisplayRequest
                .newBuilder()
                .setMode(dev.vibescreen.protocol.v1.DisplayMode.DISPLAY_MODE_EXISTING)
                .setSourceDisplayId(targetDisplayId)
                .build()
        return envelope().setStartDisplayRequest(request).build()
    }

    /**
     * Ask the host to change video encoding preferences at runtime. Requires
     * client video control to be negotiated. Any numeric field left at
     * zero/unspecified tells the host to keep its current setting;
     * [resetQualityToAuto] restores the host default quality (the only way to
     * express a preset -> AUTO transition). The host clamps the values, applies
     * them, and re-advertises a fresh VideoConfig with a bumped epoch, so this
     * reuses the same reconfiguration transition as a runtime display switch
     * (media stays gated until the new config is accepted).
     *
     * When a reconfiguration is already in flight (state != STREAMING) the
     * request cannot be sent yet, so the latest intent is retained and
     * automatically sent once the replacement VideoConfig commits. Returns the
     * request to send now, or null when nothing is sent (not applicable, or
     * coalesced for later delivery).
     */
    @Synchronized
    fun setVideoPreferences(
        bitrateKbps: Int,
        framesPerSecond: Int,
        qualityPreset: VideoQualityPreset,
        resetQualityToAuto: Boolean = false,
    ): Envelope? {
        if (Capability.CAPABILITY_CLIENT_VIDEO_CONTROL !in negotiatedCapabilities) return null
        if (bitrateKbps <= 0 &&
            framesPerSecond <= 0 &&
            qualityPreset == VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED &&
            !resetQualityToAuto
        ) {
            return null
        }
        val prefs =
            PendingVideoPreferences(
                bitrateKbps = maxOf(0, bitrateKbps),
                framesPerSecond = maxOf(0, framesPerSecond),
                qualityPreset = qualityPreset,
                resetQualityToAuto = resetQualityToAuto,
            )
        if (state != State.STREAMING) {
            // A reconfiguration is pending; hold the newest intent and send it
            // once the replacement VideoConfig commits so the last user change
            // still reaches the host.
            pendingVideoPreferences = prefs
            return null
        }
        return buildAndEnterVideoPreferencesLocked(prefs)
    }

    /**
     * Build the SetVideoPreferences envelope and enter the reconfiguration
     * state. The host answers with StartDisplayResponse + VideoConfig on a
     * bumped epoch exactly like a display switch, so enter the same state and
     * let the existing reconfiguration path gate media until the client accepts.
     * Must be called under the session lock while STREAMING.
     */
    private fun buildAndEnterVideoPreferencesLocked(prefs: PendingVideoPreferences): Envelope {
        val request =
            SetVideoPreferences
                .newBuilder()
                .setBitrateKbps(prefs.bitrateKbps)
                .setFramesPerSecond(prefs.framesPerSecond)
                .setQualityPreset(prefs.qualityPreset)
                .setResetQualityToAuto(prefs.resetQualityToAuto)
                .build()
        state = State.REDISPLAY_REQUESTED
        displayGeometryPublished = false
        videoPreferencesRequestInFlight = true
        return envelope().setSetVideoPreferences(request).build()
    }

    /**
     * Ask the host to run a previously advertised action, such as moving the
     * focused window onto the client display. Valid only while streaming, when
     * host actions were negotiated, and for an advertised action id. The
     * [invocationId] correlates the eventual HostActionResult. Returns the
     * invoke envelope to send, or null when the request is not applicable.
     */
    @Synchronized
    fun invokeHostAction(
        actionId: String,
        invocationId: ByteString,
    ): Envelope? {
        if (state != State.STREAMING) return null
        if (Capability.CAPABILITY_HOST_ACTIONS !in negotiatedCapabilities) return null
        if (invocationId.isEmpty) return null
        if (availableHostActions.none { it.id == actionId }) return null
        // Track the id so only a matching, solicited result can drive the UI.
        // Duplicate ids (a caller reusing one) are rejected up front.
        if (pendingHostActionInvocations.contains(invocationId)) return null
        if (pendingHostActionInvocations.size >= MAX_PENDING_HOST_ACTIONS) {
            pendingHostActionInvocations.removeFirst()
        }
        pendingHostActionInvocations.addLast(invocationId)
        val invoke =
            HostActionInvoke
                .newBuilder()
                .setActionId(actionId)
                .setInvocationId(invocationId)
                .setTarget(InputTarget.newBuilder().setDisplayId(displayId).setStreamId(streamId))
                .build()
        return envelope().setHostActionInvoke(invoke).build()
    }

    @Synchronized
    fun touch(
        inputId: Long,
        pointerId: Int,
        phase: InputPhase,
        x: Double,
        y: Double,
    ): Envelope {
        check(state == State.STREAMING)
        check(Capability.CAPABILITY_TOUCH in negotiatedCapabilities) { "Touch was not negotiated" }
        require(inputId > 0 && pointerId >= 0 && phase != InputPhase.INPUT_PHASE_UNSPECIFIED)
        require(x in 0.0..1.0 && y in 0.0..1.0)
        val event =
            TouchEvent
                .newBuilder()
                .setInputId(inputId)
                .setPointerId(pointerId)
                .setPhase(phase)
                .setPosition(NormalizedPoint.newBuilder().setX(x).setY(y))
                .setTarget(InputTarget.newBuilder().setDisplayId(displayId).setStreamId(streamId))
                .build()
        return envelope().setTouchEvent(event).build()
    }

    @Synchronized
    fun stylus(
        inputId: Long,
        pointerId: Int,
        phase: InputPhase,
        x: Double,
        y: Double,
        pressure: Double,
        tiltXDegrees: Double,
        tiltYDegrees: Double,
        toolKind: StylusToolKind? = null,
        buttonMask: Int = 0,
        contactState: StylusContactState? = null,
    ): Envelope {
        check(state == State.STREAMING)
        check(Capability.CAPABILITY_STYLUS in negotiatedCapabilities) { "Stylus was not negotiated" }
        require(inputId > 0 && pointerId >= 0 && phase != InputPhase.INPUT_PHASE_UNSPECIFIED)
        require(x.isFinite() && y.isFinite() && x in 0.0..1.0 && y in 0.0..1.0)
        require(pressure.isFinite() && pressure in 0.0..1.0)
        require(
            phase !in setOf(InputPhase.INPUT_PHASE_ENDED, InputPhase.INPUT_PHASE_CANCELLED) || pressure == 0.0,
        ) { "Terminal stylus events must have zero pressure" }
        require(tiltXDegrees.isFinite() && tiltXDegrees in -90.0..90.0)
        require(tiltYDegrees.isFinite() && tiltYDegrees in -90.0..90.0)
        require(Math.hypot(tiltXDegrees, tiltYDegrees) <= 90.0)
        val extended = toolKind != null || contactState != null || buttonMask != 0
        require((toolKind == null) == (contactState == null)) { "Extended stylus fields must be supplied together" }
        if (extended) {
            check(Capability.CAPABILITY_STYLUS_EXTENDED in negotiatedCapabilities) { "Extended stylus was not negotiated" }
            require(toolKind != StylusToolKind.STYLUS_TOOL_KIND_UNSPECIFIED)
            require(contactState != StylusContactState.STYLUS_CONTACT_STATE_UNSPECIFIED)
            require(buttonMask and STYLUS_BUTTON_MASK.inv() == 0)
            require(contactState != StylusContactState.STYLUS_CONTACT_STATE_PROXIMITY || pressure == 0.0)
        }
        val builder =
            StylusEvent.newBuilder()
                .setInputId(inputId)
                .setPointerId(pointerId)
                .setPhase(phase)
                .setPosition(NormalizedPoint.newBuilder().setX(x).setY(y))
                .setPressure(pressure)
                .setTiltXDegrees(tiltXDegrees)
                .setTiltYDegrees(tiltYDegrees)
                .setTarget(InputTarget.newBuilder().setDisplayId(displayId).setStreamId(streamId))
        if (toolKind != null && contactState != null) {
            builder.setToolKind(toolKind).setButtonMask(buttonMask).setContactState(contactState)
        }
        val event = builder.build()
        return envelope().setStylusEvent(event).build()
    }

    @Synchronized
    fun pointer(
        inputId: Long,
        phase: InputPhase,
        x: Double,
        y: Double,
        buttonMask: Int,
    ): Envelope {
        check(state == State.STREAMING)
        check(Capability.CAPABILITY_POINTER in negotiatedCapabilities) { "Pointer was not negotiated" }
        require(inputId > 0 && phase != InputPhase.INPUT_PHASE_UNSPECIFIED)
        require(x in 0.0..1.0 && y in 0.0..1.0)
        val event =
            PointerEvent
                .newBuilder()
                .setInputId(inputId)
                .setPhase(phase)
                .setPosition(NormalizedPoint.newBuilder().setX(x).setY(y))
                .setButtonMask(buttonMask)
                .setTarget(InputTarget.newBuilder().setDisplayId(displayId).setStreamId(streamId))
                .build()
        return envelope().setPointerEvent(event).build()
    }

    @Synchronized
    fun scroll(
        inputId: Long,
        deltaX: Double,
        deltaY: Double,
    ): Envelope {
        check(state == State.STREAMING)
        check(Capability.CAPABILITY_POINTER in negotiatedCapabilities) { "Pointer scrolling was not negotiated" }
        require(inputId > 0)
        val event =
            ScrollEvent
                .newBuilder()
                .setInputId(inputId)
                .setDeltaX(deltaX)
                .setDeltaY(deltaY)
                .setTarget(InputTarget.newBuilder().setDisplayId(displayId).setStreamId(streamId))
                .build()
        return envelope().setScrollEvent(event).build()
    }

    @Synchronized
    fun key(
        inputId: Long,
        usbHidUsage: Int,
        pressed: Boolean,
        modifierMask: Int,
    ): Envelope {
        check(state == State.STREAMING)
        check(Capability.CAPABILITY_KEYBOARD in negotiatedCapabilities) { "Keyboard was not negotiated" }
        require(inputId > 0)
        val event =
            KeyEvent
                .newBuilder()
                .setInputId(inputId)
                .setUsbHidUsage(usbHidUsage)
                .setPressed(pressed)
                .setModifierMask(modifierMask)
                .setTarget(InputTarget.newBuilder().setDisplayId(displayId).setStreamId(streamId))
                .build()
        return envelope().setKeyEvent(event).build()
    }

    @Synchronized
    fun controller(
        inputId: Long,
        sample: ControllerStateSample,
    ): Envelope {
        check(state == State.STREAMING)
        check(Capability.CAPABILITY_CONTROLLER in negotiatedCapabilities) { "Controller input was not negotiated" }
        require(inputId > 0)
        val kind =
            when (sample.kind) {
                ControllerEventKind.CONNECTED -> ProtocolControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED
                ControllerEventKind.STATE -> ProtocolControllerEventKind.CONTROLLER_EVENT_KIND_STATE
                ControllerEventKind.DISCONNECTED -> ProtocolControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED
            }
        val event =
            ControllerEvent
                .newBuilder()
                .setInputId(inputId)
                .setControllerId(sample.controllerId)
                .setControllerEpoch(sample.controllerEpoch)
                .setKind(kind)
                .setButtonMask(sample.buttonMask)
                .setLeftStickX(sample.axes.leftX)
                .setLeftStickY(sample.axes.leftY)
                .setRightStickX(sample.axes.rightX)
                .setRightStickY(sample.axes.rightY)
                .setLeftTrigger(sample.axes.leftTrigger)
                .setRightTrigger(sample.axes.rightTrigger)
                .setHatX(sample.axes.hatX)
                .setHatY(sample.axes.hatY)
                .setTarget(InputTarget.newBuilder().setDisplayId(displayId).setStreamId(streamId))
                .build()
        return envelope().setControllerEvent(event).build()
    }

    @Synchronized
    fun validateMedia(header: dev.vibescreen.protocol.v1.MediaPacketHeader): MediaDisposition {
        if (header.sessionEpoch != sessionEpoch || header.streamId != streamId) {
            throw mediaFailure("Stale or cross-stream media header")
        }
        if (header.fragmentCount != 1 || header.fragmentIndex != 0) {
            throw mediaFailure("Fragmented Protocol v1 media is unsupported")
        }
        if (header.payloadLength <= 0) throw mediaFailure("Media payload must not be empty")
        val pending = pendingVideoConfiguration
        if (pending != null) {
            if (header.configEpoch == pending.configEpoch ||
                (configEpoch > 0L && header.configEpoch == configEpoch)
            ) {
                return MediaDisposition.DROP_PENDING_CONFIGURATION
            }
            throw mediaFailure("Stale or cross-stream media header")
        }
        // A runtime display switch (selectDisplay) moves the session into
        // REDISPLAY_REQUESTED and sends a StartDisplayRequest, but the host
        // keeps producing media on the current configEpoch until it processes
        // that request. Frames already in flight on the still-current epoch
        // therefore arrive before the new VideoConfig. Drop them as switch
        // in-progress instead of hard-failing: without this the very first
        // in-flight frame trips "Media received before VideoConfig acceptance"
        // and tears the session down (the on-device flap).
        if (state == State.REDISPLAY_REQUESTED) {
            if (configEpoch > 0L && header.configEpoch == configEpoch) {
                return MediaDisposition.DROP_PENDING_CONFIGURATION
            }
            if (retiredConfigEpoch > 0L && header.configEpoch == retiredConfigEpoch) {
                return MediaDisposition.DROP_RETIRED_CONFIGURATION
            }
            throw mediaFailure("Stale or cross-stream media header")
        }
        if (state != State.STREAMING) throw mediaFailure("Media received before VideoConfig acceptance")
        if (retiredConfigEpoch > 0L && header.configEpoch == retiredConfigEpoch) {
            return MediaDisposition.DROP_RETIRED_CONFIGURATION
        }
        if (header.configEpoch != configEpoch) throw mediaFailure("Stale or cross-stream media header")
        if (header.codec != configuredCodec) throw mediaFailure("Media codec differs from accepted VideoConfig")
        if (awaitingConfigurationKeyframe && !header.keyframe) {
            return MediaDisposition.DROP_AWAITING_KEYFRAME
        }
        if (header.frameId <= lastFrameId) throw mediaFailure("Non-monotonic media frame_id")
        awaitingConfigurationKeyframe = false
        lastFrameId = header.frameId
        return MediaDisposition.ACCEPT
    }

    @Synchronized
    fun protocolError(
        message: String,
        correlationId: Long = 0,
    ): Envelope =
        envelope(correlationId)
            .setProtocolError(
                ProtocolError
                    .newBuilder()
                    .setCode(ProtocolErrorCode.PROTOCOL_ERROR_CODE_INVALID_STATE)
                    .setMessage(message.take(256))
                    .setComponent("android-session")
                    .setRetryable(false),
            ).build()

    private fun onHostHello(envelope: Envelope): List<Action> {
        if (state != State.AWAITING_HOST_HELLO) throw protocolFailure("Duplicate HostHello")
        val hello = envelope.hostHello
        if (hello.selectedProtocol != VERSION) throw protocolFailure("Unsupported selected protocol ${hello.selectedProtocol}")
        hostCapabilities = hello.capabilitiesList.toSet()
        hostCodecs = hello.codecsList.toSet()
        val missing = requiredCapabilities - hostCapabilities
        if (missing.isNotEmpty()) {
            throw protocolFailure("Host lacks required capabilities: $missing")
        }
        if (hostCodecs.intersect(codecs.toSet()).isEmpty()) throw protocolFailure("Host and device share no codec")
        state = State.AWAITING_SESSION
        return emptyList()
    }

    private fun onSessionAccepted(envelope: Envelope): List<Action> {
        if (state != State.AWAITING_SESSION) throw protocolFailure("SessionAccepted before HostHello")
        val accepted = envelope.sessionAccepted
        if (accepted.sessionId.isEmpty || accepted.sessionEpoch <= 0) throw protocolFailure("Invalid accepted session identity")
        if ((!envelope.sessionId.isEmpty && envelope.sessionId != accepted.sessionId) ||
            (envelope.sessionEpoch != 0L && envelope.sessionEpoch != accepted.sessionEpoch)
        ) {
            throw protocolFailure("Outer and accepted session identity differ")
        }
        val negotiated = accepted.negotiatedCapabilitiesList.toSet()
        if (!negotiated.containsAll(requiredCapabilities)) {
            throw protocolFailure("Required capabilities were not negotiated")
        }
        val expectedCapabilities = advertisedCapabilities.intersect(hostCapabilities)
        if (negotiated != expectedCapabilities) {
            throw protocolFailure("Negotiated capabilities are not the peer intersection")
        }
        sessionId = accepted.sessionId
        sessionEpoch = accepted.sessionEpoch
        negotiatedCapabilities = negotiated
        state = State.ACTIVE
        return listOf(Action.Send(envelope().setListDisplaysRequest(ListDisplaysRequest.getDefaultInstance()).build()))
    }

    private fun onDisplays(envelope: Envelope): List<Action> {
        if (state != State.ACTIVE) throw protocolFailure("Display list in state $state")
        val descriptors = envelope.listDisplaysResponse.displaysList
        if (descriptors.isEmpty()) throw protocolFailure("Host reported no displays")
        val options = descriptors.map(::toDisplayOption)
        availableDisplays = options
        // The host orders the currently captured display first. `isPrimary`
        // describes the macOS main display and must not override the active
        // stream source (for example, a virtual extended display).
        val selected = options.first()
        val descriptor = descriptors.first { it.displayId == selected.id }
        updateDisplayDescriptor(descriptor, expectedDisplayId = null)
        state = State.DISPLAY_REQUESTED
        val request =
            StartDisplayRequest
                .newBuilder()
                .setMode(dev.vibescreen.protocol.v1.DisplayMode.DISPLAY_MODE_EXISTING)
                .setSourceDisplayId(displayId)
                .build()
        return listOf(
            Action.DisplaysAvailable(options, displayId),
            Action.Send(envelope().setStartDisplayRequest(request).build()),
        )
    }

    private fun onStartDisplay(envelope: Envelope): List<Action> {
        if (state != State.DISPLAY_REQUESTED && state != State.REDISPLAY_REQUESTED) {
            throw protocolFailure("StartDisplayResponse in state $state")
        }
        val response = envelope.startDisplayResponse
        if (!response.accepted || response.streamId <= 0) {
            throw protocolFailure("Display start rejected: ${response.rejectionReason}")
        }
        streamId = response.streamId
        if (response.hasDisplay()) updateDisplayDescriptor(response.display, expectedDisplayId = displayId)
        return emptyList()
    }

    private fun onVideoConfig(envelope: Envelope): List<Action> {
        if (state != State.DISPLAY_REQUESTED &&
            state != State.REDISPLAY_REQUESTED &&
            state != State.STREAMING
        ) {
            throw protocolFailure("VideoConfig in state $state")
        }
        val config = envelope.videoConfig
        if (pendingVideoConfiguration != null) {
            return listOf(
                Action.Send(
                    videoConfigResult(
                        configEpoch = config.configEpoch,
                        streamId = config.streamId,
                        accepted = false,
                        rejectionReason = "video_configuration_pending",
                        correlationId = envelope.messageId,
                    ),
                ),
            )
        }
        val accepted =
            config.streamId == streamId &&
                config.configEpoch > configEpoch &&
                config.encodedSize.width in 16..8192 &&
                config.encodedSize.height in 16..8192 &&
                config.rotationDegrees.toInt() in VALID_ROTATIONS &&
                config.codec in codecs &&
                config.codec in hostCodecs
        if (!accepted) {
            videoPreferencesRequestInFlight = false
            return listOf(
                Action.Send(
                    videoConfigResult(
                        configEpoch = config.configEpoch,
                        streamId = config.streamId,
                        accepted = false,
                        rejectionReason = "unsupported_video_config",
                        correlationId = envelope.messageId,
                    ),
                ),
            )
        }
        val configurationToken = nextVideoConfigurationToken++
        pendingVideoConfiguration =
            PendingVideoConfiguration(
                correlationId = envelope.messageId,
                streamId = config.streamId,
                configEpoch = config.configEpoch,
                rotation = config.rotationDegrees.toInt(),
                codec = config.codec,
                configurationToken = configurationToken,
            )
        return listOf(
            Action.VideoConfigurationRequested(
                width = config.encodedSize.width,
                height = config.encodedSize.height,
                rotation = config.rotationDegrees.toInt(),
                codec = config.codec,
                configEpoch = config.configEpoch,
                sessionEpoch = sessionEpoch,
                configurationToken = configurationToken,
                bitrateKbps = config.bitrateKbps,
                framesPerSecond = config.framesPerSecond,
            ),
        )
    }

    @Synchronized
    fun completeVideoConfiguration(
        completedConfigEpoch: Long,
        configurationToken: Long,
        accepted: Boolean,
        rejectionReason: String,
    ): List<Action> {
        if (state != State.DISPLAY_REQUESTED &&
            state != State.REDISPLAY_REQUESTED &&
            state != State.STREAMING
        ) {
            return emptyList()
        }
        val pending = pendingVideoConfiguration ?: return emptyList()
        if (pending.configEpoch != completedConfigEpoch ||
            pending.configurationToken != configurationToken
        ) {
            return emptyList()
        }
        pendingVideoConfiguration = null
        val result =
            Action.Send(
                videoConfigResult(
                    configEpoch = pending.configEpoch,
                    streamId = pending.streamId,
                    accepted = accepted,
                    rejectionReason = if (accepted) "" else rejectionReason.ifBlank { "decoder_configuration_failure" },
                    correlationId = pending.correlationId,
                ),
            )
        if (!accepted) {
            videoPreferencesRequestInFlight = false
            return listOf(
                result,
                Action.VideoConfigurationRejected(
                    configEpoch = pending.configEpoch,
                    reason = rejectionReason.ifBlank { "decoder_configuration_failure" },
                ),
            )
        }

        retiredConfigEpoch = configEpoch
        configEpoch = pending.configEpoch
        configuredCodec = pending.codec
        lastFrameId = 0L
        awaitingConfigurationKeyframe = true
        state = State.STREAMING
        val appliesClientVideoPreferences = videoPreferencesRequestInFlight
        videoPreferencesRequestInFlight = false
        val actions =
            mutableListOf<Action>(
                result,
                Action.Send(requestKeyframe("decoder_configuration_committed")),
                Action.VideoConfigurationCommitted(configEpoch, appliesClientVideoPreferences),
            )
        if (!displayGeometryPublished) {
            actions +=
                Action.DisplayGeometryChanged(
                    width = displayWidth,
                    height = displayHeight,
                    rotation = pending.rotation,
                )
            displayGeometryPublished = true
        }
        // The stream is back to STREAMING, so any preference change that was
        // coalesced during the reconfiguration can now be sent. This re-enters
        // REDISPLAY_REQUESTED, gating media again until the host commits the
        // newest request.
        pendingVideoPreferences?.let { prefs ->
            pendingVideoPreferences = null
            actions += Action.Send(buildAndEnterVideoPreferencesLocked(prefs))
        }
        return actions
    }

    private fun onDisplayChanged(envelope: Envelope): List<Action> {
        if (state != State.STREAMING) throw protocolFailure("DisplayChanged in state $state")
        val changed = envelope.displayChanged
        if (!changed.hasDisplay() ||
            changed.display.displayId != displayId ||
            changed.display.logicalSize.width !in 16..8192 ||
            changed.display.logicalSize.height !in 16..8192 ||
            changed.rotationDegrees.toInt() !in VALID_ROTATIONS
        ) {
            throw protocolFailure("Invalid DisplayChanged")
        }
        displayWidth = changed.display.logicalSize.width
        displayHeight = changed.display.logicalSize.height
        displayGeometryPublished = true
        return listOf(
            Action.DisplayGeometryChanged(
                width = displayWidth,
                height = displayHeight,
                rotation = changed.rotationDegrees.toInt(),
            ),
        )
    }

    private fun updateDisplayDescriptor(
        display: dev.vibescreen.protocol.v1.DisplayDescriptor,
        expectedDisplayId: String?,
    ) {
        if (display.displayId.isBlank() ||
            (expectedDisplayId != null && display.displayId != expectedDisplayId) ||
            !display.hasLogicalSize() ||
            display.logicalSize.width !in 16..8192 ||
            display.logicalSize.height !in 16..8192
        ) {
            throw protocolFailure("Invalid display descriptor")
        }
        displayId = display.displayId
        displayWidth = display.logicalSize.width
        displayHeight = display.logicalSize.height
    }
    private fun onHostActionCatalog(envelope: Envelope): List<Action> {
        // The host advertises actions after SessionAccepted, before StartDisplay,
        // so the catalog arrives while the session is negotiated but not yet
        // streaming. Accept it in any post-negotiation, non-closed state and
        // cache it; the UI only surfaces the actions once streaming. Only the
        // negotiated capability and a live session are required.
        if (!isNegotiated()) throw protocolFailure("HostActionCatalog in state $state")
        if (Capability.CAPABILITY_HOST_ACTIONS !in negotiatedCapabilities) {
            throw protocolFailure("HostActionCatalog without negotiated host actions")
        }
        val actions =
            envelope.hostActionCatalog.actionsList
                .asSequence()
                .filter { it.actionId in KNOWN_HOST_ACTION_IDS }
                .distinctBy { it.actionId }
                .take(MAX_HOST_ACTIONS)
                .map {
                    HostAction(
                        id = it.actionId,
                        localizedName = it.localizedName,
                        requiresConfirmation = it.requiresConfirmation,
                    )
                }.toList()
        availableHostActions = actions
        return listOf(Action.HostActionsAvailable(actions))
    }

    private fun onHostActionResult(envelope: Envelope): List<Action> {
        if (!isNegotiated()) throw protocolFailure("HostActionResult in state $state")
        if (Capability.CAPABILITY_HOST_ACTIONS !in negotiatedCapabilities) {
            throw protocolFailure("HostActionResult without negotiated host actions")
        }
        val result = envelope.hostActionResult
        if (result.invocationId.isEmpty) throw protocolFailure("HostActionResult missing invocation id")
        // Only a matching invocation may drive UI. A duplicate or late result
        // is an authenticated no-op and must not tear down the video session.
        if (!pendingHostActionInvocations.remove(result.invocationId)) {
            return emptyList()
        }
        return listOf(
            Action.HostActionCompleted(
                invocationId = result.invocationId,
                accepted = result.accepted,
                rejectionReason = result.rejectionReason,
            ),
        )
    }

    private fun toDisplayOption(display: dev.vibescreen.protocol.v1.DisplayDescriptor): DisplayOption {
        if (display.displayId.isBlank() ||
            !display.hasLogicalSize() ||
            display.logicalSize.width !in 16..8192 ||
            display.logicalSize.height !in 16..8192
        ) {
            throw protocolFailure("Invalid display descriptor")
        }
        return DisplayOption(
            id = display.displayId,
            name = display.name.ifBlank { display.displayId },
            width = display.logicalSize.width,
            height = display.logicalSize.height,
            isPrimary = display.isPrimary,
            isVirtual = display.isVirtual,
        )
    }

    private fun videoConfigResult(
        configEpoch: Long,
        streamId: Long,
        accepted: Boolean,
        rejectionReason: String,
        correlationId: Long,
    ): Envelope =
        envelope(correlationId = correlationId)
            .setVideoConfigResult(
                VideoConfigResult
                    .newBuilder()
                    .setConfigEpoch(configEpoch)
                    .setStreamId(streamId)
                    .setAccepted(accepted)
                    .setRejectionReason(rejectionReason),
            ).build()

    private fun validateEnvelope(envelope: Envelope) {
        if (envelope.protocolVersion != VERSION) throw protocolFailure("Unsupported envelope version ${envelope.protocolVersion}")
        if (envelope.messageId <= lastInboundMessageId) throw protocolFailure("Non-monotonic message_id")
        if (state >= State.ACTIVE && state != State.CLOSED) {
            if (envelope.sessionId != sessionId || envelope.sessionEpoch != sessionEpoch) {
                throw protocolFailure("Wrong session_id or session_epoch")
            }
        } else if (envelope.payloadCase == Envelope.PayloadCase.HOST_HELLO &&
            (!envelope.sessionId.isEmpty || envelope.sessionEpoch != 0L)
        ) {
            throw protocolFailure("HostHello unexpectedly carries session identity")
        }
        if (envelope.payloadCase == Envelope.PayloadCase.PAYLOAD_NOT_SET) throw protocolFailure("Envelope payload is missing")
        lastInboundMessageId = envelope.messageId
    }

    private fun envelope(correlationId: Long = 0): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(VERSION)
            .setMessageId(nextMessageId++)
            .setCorrelationId(correlationId)
            .setSessionId(sessionId)
            .setSessionEpoch(sessionEpoch)
            .setSentAtMonotonicNs(nowNs())

    private fun protocolFailure(message: String): ProtocolV1Failure =
        ProtocolV1Failure(
            reason = "invalid_peer_message",
            retryable = false,
            source = ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION,
            message = "Protocol v1: $message",
        )

    // A session is negotiated once SessionAccepted has advanced past the
    // handshake and before it closes. Host actions may arrive across this whole
    // window, not just while streaming.
    private fun isNegotiated(): Boolean = state >= State.ACTIVE && state != State.CLOSED

    private fun mediaFailure(message: String): ProtocolV1Failure =
        ProtocolV1Failure(
            reason = "invalid_media_header",
            retryable = false,
            source = ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION,
            message = "Protocol v1: $message",
        )

    private data class PendingVideoConfiguration(
        val correlationId: Long,
        val streamId: Long,
        val configEpoch: Long,
        val rotation: Int,
        val codec: Codec,
        val configurationToken: Long,
    )

    private data class PendingVideoPreferences(
        val bitrateKbps: Int,
        val framesPerSecond: Int,
        val qualityPreset: VideoQualityPreset,
        val resetQualityToAuto: Boolean,
    )

    companion object {
        private const val STYLUS_BUTTON_MASK = 0b11
        const val VERSION = 1
        private val VALID_ROTATIONS = setOf(0, 90, 180, 270)

        /** Move the focused Mac window onto the client display. Fixed with the host. */
        const val ACTION_MOVE_WINDOW = "move-window"

        /** Return windows previously moved to the client back to the Mac. Fixed with the host. */
        const val ACTION_RETURN_WINDOWS = "return-windows"

        // Only these fixed ids are surfaced; unknown catalog entries are ignored
        // so the client never offers an action it cannot present or invoke.
        private val KNOWN_HOST_ACTION_IDS = setOf(ACTION_MOVE_WINDOW, ACTION_RETURN_WINDOWS)

        // Bound the surfaced actions and in-flight invocations so a misbehaving
        // host or caller cannot grow either without limit.
        private const val MAX_HOST_ACTIONS = 8
        private const val MAX_PENDING_HOST_ACTIONS = 16
    }
}
