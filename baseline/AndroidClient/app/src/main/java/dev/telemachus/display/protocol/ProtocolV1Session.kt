package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.telemachus.display.ControllerEventKind
import dev.telemachus.display.ControllerStateSample
import dev.telemachus.display.NativeInputWire
import dev.telemachus.display.WakeHostPolicy
import dev.telemachus.display.WakeHostProof
import dev.telemachus.display.WakeHostRequestContext
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.AudioConfig
import dev.vibescreen.protocol.v1.AudioConfigResult
import dev.vibescreen.protocol.v1.ClientHello
import dev.vibescreen.protocol.v1.ClipboardContent
import dev.vibescreen.protocol.v1.ClipboardOffer
import dev.vibescreen.protocol.v1.ClipboardRequest
import dev.vibescreen.protocol.v1.ControllerEvent
import dev.vibescreen.protocol.v1.ControllerEventKind as ProtocolControllerEventKind
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.FileAccept
import dev.vibescreen.protocol.v1.FileOffer
import dev.vibescreen.protocol.v1.FileTransferCancel
import dev.vibescreen.protocol.v1.FileTransferComplete
import dev.vibescreen.protocol.v1.FileTransferProgress
import dev.vibescreen.protocol.v1.HostActionInvoke
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.InputTarget
import dev.vibescreen.protocol.v1.KeyEvent
import dev.vibescreen.protocol.v1.ListDisplaysRequest
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import dev.vibescreen.protocol.v1.NormalizedPoint
import dev.vibescreen.protocol.v1.Ping
import dev.vibescreen.protocol.v1.PeripheralEvent
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
import dev.vibescreen.protocol.v1.WakeHostRequest
import dev.vibescreen.protocol.v1.WakeHostResult
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.security.SecureRandom

internal class ProtocolV1Failure(
    val reason: String,
    val retryable: Boolean,
    val source: Source,
    message: String,
    cause: Throwable? = null,
) : IOException(message, cause) {
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
    private val advertiseController: Boolean = false,
    private val advertisePeripheralInputFramework: Boolean = false,
    localManagedPolicy: ManagedPolicy = ManagedPolicy.UNMANAGED,
    private val fileTransferPolicy: FileTransferPolicy = FileTransferPolicy(),
    private val wakeHostPolicy: WakeHostPolicy = WakeHostPolicy.DENY,
    private val nowNs: () -> Long = System::nanoTime,
) {
    sealed class Action {
        data class Send(val envelope: Envelope) : Action()

        data class DisplaysAvailable(
            val displays: List<DisplayOption>,
            val selectedId: String,
        ) : Action()

        data class DisplaySelectionPending(
            val selectedId: String,
            val pendingId: String,
        ) : Action()

        data class DisplaySelectionConfirmed(
            val selectedId: String,
        ) : Action()

        data class DisplaySelectionRejected(
            val selectedId: String,
            val rejectedId: String,
            val reason: String,
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

        data class AudioConfigurationRequested(
            val config: AudioConfig,
            val sessionEpoch: Long,
            val correlationId: Long,
        ) : Action()

        data class AudioStopped(val reason: String) : Action()

        data class DisplayGeometryChanged(
            val width: Int,
            val height: Int,
            val rotation: Int,
        ) : Action()

        data class PongReceived(val sequence: Long) : Action()

        data class ControllerInputAck(
            val inputId: Long,
            val accepted: Boolean,
            val rejectionReason: String,
        ) : Action()

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

        data class FileOfferReceived(
            val offer: FileOffer,
        ) : Action()

        data class FileAcceptReceived(
            val response: FileAccept,
        ) : Action()

        data class FileProgressReceived(
            val progress: FileTransferProgress,
        ) : Action()

        data class FileCancelReceived(
            val cancellation: FileTransferCancel,
        ) : Action()

        data class FileCompleteReceived(
            val result: FileTransferComplete,
        ) : Action()

        data class ManagedPolicyReceived(
            val status: ManagedPolicyStatus,
        ) : Action()

        data class WakeHost(
            val request: WakeHostRequestContext,
            val correlationId: Long,
        ) : Action()

        data class WakeHostCompleted(
            val requestId: ByteString,
            val accepted: Boolean,
            val rejectionReason: String,
        ) : Action()

        data class Disconnected(
            val reasonCode: String,
            val mayResume: Boolean,
        ) : Action()

        /** A peer clipboard offer has arrived and may be requested. */
        data class ClipboardOffered(
            val changeId: ByteString,
            val originDeviceId: String,
            val mimeType: String,
            val byteLength: Long,
            val sha256: ByteString,
        ) : Action()

        /**
         * Peer clipboard content has arrived. When [pending] is true the content
         * was sent without a matching offer/request handshake and must not be
         * auto-applied to the system clipboard.
         */
        data class ClipboardContentReceived(
            val changeId: ByteString,
            val originDeviceId: String,
            val mimeType: String,
            val content: ByteArray,
            val sha256: ByteString,
            val pending: Boolean,
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

    class ManagedPolicy(
        val isManaged: Boolean,
        val clipboardAllowed: Boolean,
        val fileTransferAllowed: Boolean,
        val audioAllowed: Boolean,
        val wakeAllowed: Boolean,
        val customGesturesAllowed: Boolean,
        val hostActionsAllowed: Boolean,
        val maximumFileBytes: Long,
        allowedHosts: Set<String>,
        allowedHostsRestricted: Boolean? = null,
    ) {
        val allowedHosts = allowedHosts.mapNotNull { normalizeHost(it) }.toSet()
        val allowedHostsRestricted = allowedHostsRestricted ?: this.allowedHosts.isNotEmpty()

        fun applying(remote: ManagedPolicy): ManagedPolicy {
            if (!remote.isManaged) return this
            val restricted = allowedHostsRestricted || remote.allowedHostsRestricted
            val hosts =
                when {
                    allowedHostsRestricted && remote.allowedHostsRestricted -> allowedHosts.intersect(remote.allowedHosts)
                    allowedHostsRestricted -> allowedHosts
                    remote.allowedHostsRestricted -> remote.allowedHosts
                    else -> emptySet()
                }
            return ManagedPolicy(
                isManaged = true,
                clipboardAllowed = clipboardAllowed && remote.clipboardAllowed,
                fileTransferAllowed = fileTransferAllowed && remote.fileTransferAllowed,
                audioAllowed = audioAllowed && remote.audioAllowed,
                wakeAllowed = wakeAllowed && remote.wakeAllowed,
                customGesturesAllowed = customGesturesAllowed && remote.customGesturesAllowed,
                hostActionsAllowed = hostActionsAllowed && remote.hostActionsAllowed,
                maximumFileBytes = minOf(maximumFileBytes, remote.maximumFileBytes),
                allowedHosts = hosts,
                allowedHostsRestricted = restricted,
            )
        }

        fun allowsHost(hostId: String): Boolean {
            val normalized = normalizeHost(hostId)
            return !allowedHostsRestricted || (normalized != null && normalized in allowedHosts)
        }

        fun copy(
            isManaged: Boolean = this.isManaged,
            clipboardAllowed: Boolean = this.clipboardAllowed,
            fileTransferAllowed: Boolean = this.fileTransferAllowed,
            audioAllowed: Boolean = this.audioAllowed,
            wakeAllowed: Boolean = this.wakeAllowed,
            customGesturesAllowed: Boolean = this.customGesturesAllowed,
            hostActionsAllowed: Boolean = this.hostActionsAllowed,
            maximumFileBytes: Long = this.maximumFileBytes,
            allowedHosts: Set<String> = this.allowedHosts,
            allowedHostsRestricted: Boolean = this.allowedHostsRestricted,
        ): ManagedPolicy =
            ManagedPolicy(
                isManaged = isManaged,
                clipboardAllowed = clipboardAllowed,
                fileTransferAllowed = fileTransferAllowed,
                audioAllowed = audioAllowed,
                wakeAllowed = wakeAllowed,
                customGesturesAllowed = customGesturesAllowed,
                hostActionsAllowed = hostActionsAllowed,
                maximumFileBytes = maximumFileBytes,
                allowedHosts = allowedHosts,
                allowedHostsRestricted = allowedHostsRestricted,
            )

        fun toStatus(): ManagedPolicyStatus =
            ManagedPolicyStatus
                .newBuilder()
                .setManaged(isManaged)
                .setClipboardAllowed(clipboardAllowed)
                .setFileTransferAllowed(fileTransferAllowed)
                .setAudioAllowed(audioAllowed)
                .setWakeAllowed(wakeAllowed)
                .setCustomGesturesAllowed(customGesturesAllowed)
                .setHostActionsAllowed(hostActionsAllowed)
                .setMaximumFileBytes(maximumFileBytes)
                .addAllAllowedHosts(allowedHosts.sorted())
                .setAllowedHostsRestricted(allowedHostsRestricted)
                .build()

        companion object {
            const val DEFAULT_MAXIMUM_FILE_BYTES = 512L * 1_024L * 1_024L
            val UNMANAGED =
                ManagedPolicy(
                    isManaged = false,
                    clipboardAllowed = true,
                    fileTransferAllowed = true,
                    audioAllowed = true,
                    wakeAllowed = true,
                    customGesturesAllowed = true,
                    hostActionsAllowed = true,
                    maximumFileBytes = DEFAULT_MAXIMUM_FILE_BYTES,
                    allowedHosts = emptySet(),
                    allowedHostsRestricted = false,
                )

            fun fromStatus(status: ManagedPolicyStatus): ManagedPolicy {
                if (!status.managed) return UNMANAGED
                val hosts = status.allowedHostsList.mapNotNull { normalizeHost(it) }.toSet()
                return ManagedPolicy(
                    isManaged = true,
                    clipboardAllowed = status.clipboardAllowed,
                    fileTransferAllowed = status.fileTransferAllowed,
                    audioAllowed = status.audioAllowed,
                    wakeAllowed = status.wakeAllowed,
                    customGesturesAllowed = status.customGesturesAllowed,
                    hostActionsAllowed = status.hostActionsAllowed,
                    maximumFileBytes = status.maximumFileBytes,
                    allowedHosts = hosts,
                    allowedHostsRestricted = status.allowedHostsRestricted || hosts.isNotEmpty(),
                )
            }

            private fun normalizeHost(hostId: String): String? {
                val trimmed = hostId.trim()
                return trimmed.ifEmpty { null }?.lowercase()
            }
        }
    }

    private class ManagedPolicyResolver(
        private val localPolicy: ManagedPolicy,
    ) {
        private var remotePolicy: ManagedPolicy? = null

        val effectivePolicy: ManagedPolicy
            get() = remotePolicy?.let { localPolicy.applying(it) } ?: localPolicy

        fun setRemote(policy: ManagedPolicy?) {
            remotePolicy = policy
        }

        fun clearRemote() {
            remotePolicy = null
        }
    }

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
    private var peerHostId = ""
    private var streamId = 0L
    private var configEpoch = 0L
    private var retiredConfigEpoch = 0L
    private var configuredCodec = Codec.CODEC_UNSPECIFIED
    private var audioStreamId = 0L
    private var audioConfigEpoch = 0L
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
    private var pendingDisplaySelectionIdValue: String? = null
    private var pendingDisplaySelectionCommitId: String? = null
    private var pendingDisplaySelectionStreamId: Long = 0L
    private var pendingDisplaySelectionWidth: Int = 0
    private var pendingDisplaySelectionHeight: Int = 0
    private var baseNegotiatedCapabilities = emptySet<Capability>()
    private var negotiatedCapabilities = emptySet<Capability>()
    private var hostCapabilities = emptySet<Capability>()
    private var hostCodecs = emptySet<Codec>()
    private val decodeCapabilities = VideoColorNegotiation.sdrDecodeCapabilities(codecs)
    private var negotiatedFileTransferPolicy = fileTransferPolicy
    private var acceptedResourceLimits = ResourceLimits.getDefaultInstance()
    // Host actions advertised for the active session, filtered to the fixed ids
    // this client can invoke. Reset whenever a session ends.
    private var availableHostActions = emptyList<HostAction>()
    // Invocation ids sent to the host and still awaiting a result. Bounded so a
    // client that spams actions cannot grow this without limit; the oldest id is
    // evicted when full. A result must match a tracked id, so the host cannot
    // forge an unsolicited success/failure that the UI would surface.
    private val pendingHostActionInvocations = ArrayDeque<ByteString>()
    private val pendingWakeHostRequests = ArrayDeque<ByteString>()
    private val managedPolicyResolver = ManagedPolicyResolver(localManagedPolicy)

    // Host-advertised clipboard byte limit from HostHello.resource_limits.
    private var hostMaxClipboardBytes = 0L
    // Effective negotiated limit: min(local, hostHello if >0, accepted if >0).
    private var negotiatedMaxClipboardBytesValue = LOCAL_MAX_CLIPBOARD_BYTES
    // Our cached clipboard offer snapshot (only one outstanding offer at a time).
    private var offeredClipboard: OfferedClipboard? = null
    // Most recent peer clipboard offer received.
    private var receivedClipboardOffer: ReceivedClipboardOffer? = null
    // changeId of the peer offer we have explicitly requested content for.
    // Content is solicited only when it matches this id; otherwise it is
    // treated as direct/pending and must not be auto-applied.
    private var requestedClipboardChangeId: ByteString? = null
    // Bounded FIFO set of changeIds already sent or accepted, used to reject
    // loopback echoes of our own offers/content.
    private val clipboardSeenChangeIds = ArrayDeque<ByteString>()
    // Bounded history of completed clipboard transfers for diagnostics.
    private val clipboardFeedbackHistory = ArrayDeque<ClipboardFeedback>()
    // Local Android managed-configuration integration is outside this slice,
    // so local policy is permissive. A remote managed status with
    // clipboard_allowed=false denies clipboard for the active session.
    private var remoteManagedClipboardAllowed = true
    private val secureRandom = SecureRandom()

    private val advertisedCapabilities =
        buildSet {
            addAll(BASE_ADVERTISED_CAPABILITIES)
            if (advertiseController) add(Capability.CAPABILITY_CONTROLLER)
            if (advertisePeripheralInputFramework) add(Capability.CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK)
            if (fileTransferPolicy.allowed) add(Capability.CAPABILITY_FILE_TRANSFER)
            if (wakeHostPolicy.wakeAllowed) {
                add(Capability.CAPABILITY_WAKE_HOST)
            }
        }.filteredBy(localManagedPolicy)
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

    /** Display id requested by the client and awaiting host/decoder acceptance, if any. */
    val pendingDisplaySelectionId: String?
        @Synchronized
        get() = pendingDisplaySelectionIdValue

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

    val canSendPeripheral: Boolean
        @Synchronized
        get() = state == State.STREAMING && Capability.CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK in negotiatedCapabilities

    /** Host actions the client may invoke, empty until a catalog arrives. */
    val hostActions: List<HostAction>
        @Synchronized
        get() = availableHostActions

    /** Whether host actions were negotiated and the session is streaming. */
    val canInvokeHostActions: Boolean
        @Synchronized
        get() =
            state == State.STREAMING &&
                Capability.CAPABILITY_HOST_ACTIONS in negotiatedCapabilities &&
                managedPolicyResolver.effectivePolicy.hostActionsAllowed

    /** Whether clipboard transfer was negotiated and media is streaming. */
    val canSendClipboard: Boolean
        @Synchronized
        get() = state == State.STREAMING && Capability.CAPABILITY_CLIPBOARD in negotiatedCapabilities &&
            remoteManagedClipboardAllowed

    /** Effective clipboard byte limit for the active session. */
    val negotiatedMaxClipboardBytes: Long
        @Synchronized
        get() =
            if (state != State.CLOSED && Capability.CAPABILITY_CLIPBOARD in negotiatedCapabilities) {
                negotiatedMaxClipboardBytesValue
            } else {
                0L
            }

    val canTransferFiles: Boolean
        @Synchronized
        get() = isNegotiated() && Capability.CAPABILITY_FILE_TRANSFER in negotiatedCapabilities

    val negotiatedFilePolicy: FileTransferPolicy
        @Synchronized
        get() = negotiatedFileTransferPolicy

    val canRequestWakeHost: Boolean
        @Synchronized
        get() = state == State.STREAMING && Capability.CAPABILITY_WAKE_HOST in negotiatedCapabilities

    val canReceiveAudio: Boolean
        @Synchronized
        get() =
            (state == State.STREAMING || state == State.REDISPLAY_REQUESTED) &&
                Capability.CAPABILITY_AUDIO in negotiatedCapabilities &&
                audioStreamId > 0L

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
                        .setMaximumVideoStreams(1)
                        .setMaximumAudioStreams(if (Capability.CAPABILITY_AUDIO in advertisedCapabilities) 1 else 0)
                        .setMaximumClipboardBytes(LOCAL_MAX_CLIPBOARD_BYTES)
                        .setMaximumFileBytes(if (fileTransferPolicy.allowed) fileTransferPolicy.maximumFileBytes else 0L)
                        .setMaximumFileChunkBytes(if (fileTransferPolicy.allowed) fileTransferPolicy.maximumChunkBytes else 0),
                ).addAllVideoDecodeCapabilities(decodeCapabilities)
                .build()
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
            Envelope.PayloadCase.AUDIO_CONFIG -> onAudioConfig(envelope)
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
            Envelope.PayloadCase.INPUT_ACK -> onInputAck(envelope)
            Envelope.PayloadCase.HOST_ACTION_CATALOG -> onHostActionCatalog(envelope)
            Envelope.PayloadCase.HOST_ACTION_RESULT -> onHostActionResult(envelope)
            Envelope.PayloadCase.MANAGED_POLICY_STATUS -> onManagedPolicyStatus(envelope.managedPolicyStatus)
            Envelope.PayloadCase.FILE_OFFER -> onFileOffer(envelope)
            Envelope.PayloadCase.FILE_ACCEPT -> onFileAccept(envelope)
            Envelope.PayloadCase.FILE_TRANSFER_PROGRESS -> onFileTransferProgress(envelope)
            Envelope.PayloadCase.FILE_TRANSFER_CANCEL -> onFileTransferCancel(envelope)
            Envelope.PayloadCase.FILE_TRANSFER_COMPLETE -> onFileTransferComplete(envelope)
            Envelope.PayloadCase.WAKE_HOST_REQUEST -> onWakeHostRequest(envelope)
            Envelope.PayloadCase.WAKE_HOST_RESULT -> onWakeHostResult(envelope)
            Envelope.PayloadCase.DISCONNECT_NOTICE -> {
                pendingVideoConfiguration = null
                pendingVideoPreferences = null
                videoPreferencesRequestInFlight = false
                pendingDisplaySelectionIdValue = null
                pendingDisplaySelectionCommitId = null
                pendingDisplaySelectionStreamId = 0L
                pendingDisplaySelectionWidth = 0
                pendingDisplaySelectionHeight = 0
                availableHostActions = emptyList()
                pendingHostActionInvocations.clear()
                pendingWakeHostRequests.clear()
                clearClipboardState()
                remoteManagedClipboardAllowed = true
                managedPolicyResolver.clearRemote()
                clearAudioState()
                state = State.CLOSED
                listOf(
                    Action.Disconnected(
                        reasonCode = envelope.disconnectNotice.reasonCode,
                        mayResume = envelope.disconnectNotice.mayResume,
                    ),
                )
            }
            Envelope.PayloadCase.CLIPBOARD_OFFER -> onClipboardOffer(envelope)
            Envelope.PayloadCase.CLIPBOARD_REQUEST -> onClipboardRequest(envelope)
            Envelope.PayloadCase.CLIPBOARD_CONTENT -> onClipboardContent(envelope)
            Envelope.PayloadCase.PROTOCOL_ERROR -> {
                pendingDisplaySelectionIdValue = null
                pendingDisplaySelectionCommitId = null
                pendingDisplaySelectionStreamId = 0L
                pendingDisplaySelectionWidth = 0
                pendingDisplaySelectionHeight = 0
                clearAudioState()
                clearClipboardState()
                remoteManagedClipboardAllowed = true
                managedPolicyResolver.clearRemote()
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

    private fun onInputAck(envelope: Envelope): List<Action> {
        if (!isNegotiated()) throw protocolFailure("InputAck arrived before session negotiation")
        val expectsInputAck =
            Capability.CAPABILITY_CONTROLLER in negotiatedCapabilities ||
                Capability.CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK in negotiatedCapabilities
        if (!expectsInputAck) {
            throw protocolFailure("InputAck arrived without negotiated acknowledged input")
        }
        val acknowledgement = envelope.inputAck
        if (acknowledgement.inputId <= 0L) throw protocolFailure("InputAck input_id must be positive")
        if (!acknowledgement.accepted && acknowledgement.rejectionReason.isBlank()) {
            throw protocolFailure("Rejected InputAck requires a reason")
        }
        return listOf(
            Action.ControllerInputAck(
                inputId = acknowledgement.inputId,
                accepted = acknowledgement.accepted,
                rejectionReason = acknowledgement.rejectionReason,
            ),
        )
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
     * other than the current one. Returns state/update actions to publish, or
     * an empty list when the request is not applicable.
     */
    @Synchronized
    fun selectDisplay(targetDisplayId: String): List<Action> {
        if (state != State.STREAMING) return emptyList()
        if (Capability.CAPABILITY_MULTI_DISPLAY !in negotiatedCapabilities) return emptyList()
        if (targetDisplayId.isBlank() || targetDisplayId == displayId) return emptyList()
        val targetDisplay = availableDisplays.firstOrNull { it.id == targetDisplayId } ?: return emptyList()
        state = State.REDISPLAY_REQUESTED
        displayGeometryPublished = false
        pendingDisplaySelectionIdValue = targetDisplayId
        pendingDisplaySelectionWidth = targetDisplay.width
        pendingDisplaySelectionHeight = targetDisplay.height
        val request =
            StartDisplayRequest
                .newBuilder()
                .setMode(dev.vibescreen.protocol.v1.DisplayMode.DISPLAY_MODE_EXISTING)
                .setSourceDisplayId(targetDisplayId)
                .build()
        return listOf(
            Action.DisplaySelectionPending(selectedId = displayId, pendingId = targetDisplayId),
            Action.Send(envelope().setStartDisplayRequest(request).build()),
        )
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
        if (!managedPolicyResolver.effectivePolicy.hostActionsAllowed) return null
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
    fun offerFile(offer: FileOffer): Envelope? {
        if (!canTransferFiles) return null
        return envelope().setFileOffer(offer).build()
    }

    @Synchronized
    fun fileAccept(response: FileAccept): Envelope? {
        if (!canTransferFiles) return null
        return envelope().setFileAccept(response).build()
    }

    @Synchronized
    fun fileProgress(transferId: ByteString, receivedBytes: Long): Envelope? {
        if (!canTransferFiles) return null
        val progress =
            FileTransferProgress
                .newBuilder()
                .setTransferId(transferId)
                .setReceivedBytes(receivedBytes)
                .build()
        return envelope().setFileTransferProgress(progress).build()
    }

    @Synchronized
    fun fileComplete(
        transferId: ByteString,
        accepted: Boolean,
        sha256: ByteString,
        rejectionReason: String,
    ): Envelope? {
        if (!canTransferFiles) return null
        val result =
            FileTransferComplete
                .newBuilder()
                .setTransferId(transferId)
                .setAccepted(accepted)
                .setSha256(sha256)
                .setRejectionReason(if (accepted) "" else rejectionReason)
                .build()
        return envelope().setFileTransferComplete(result).build()
    }

    @Synchronized
    fun fileCancel(transferId: ByteString, reasonCode: String): Envelope? {
        if (!canTransferFiles) return null
        val cancel =
            FileTransferCancel
                .newBuilder()
                .setTransferId(transferId)
                .setReasonCode(reasonCode)
                .build()
        return envelope().setFileTransferCancel(cancel).build()
    }

    @Synchronized
    fun requestWakeHost(
        requestId: ByteString,
        targetMacAddress: ByteString,
        secureOnPassword: ByteString = ByteString.EMPTY,
        authorizationSecret: ByteArray? = null,
    ): Envelope? {
        if (state != State.STREAMING) return null
        if (Capability.CAPABILITY_WAKE_HOST !in negotiatedCapabilities) return null
        if (requestId.isEmpty) return null
        if (peerHostId.isBlank()) return null
        if (pendingWakeHostRequests.contains(requestId)) return null
        if (pendingWakeHostRequests.size >= MAX_PENDING_WAKE_HOST_REQUESTS) {
            pendingWakeHostRequests.removeFirst()
        }
        pendingWakeHostRequests.addLast(requestId)
        val keyId = authorizationSecret?.let(WakeHostProof::keyId).orEmpty()
        val issuedAtUnixSeconds = if (authorizationSecret != null) System.currentTimeMillis() / 1_000L else 0L
        val expiresAtUnixSeconds = if (authorizationSecret != null) issuedAtUnixSeconds + WAKE_HOST_AUTHORIZATION_LIFETIME_SECONDS else 0L
        val nonce =
            authorizationSecret?.let {
                ByteString.copyFrom(ByteArray(WakeHostProof.MINIMUM_NONCE_BYTES).also(secureRandom::nextBytes))
            } ?: ByteString.EMPTY
        val signature =
            authorizationSecret?.let { secret ->
                WakeHostProof.signature(
                    requestId = requestId,
                    targetMacAddress = targetMacAddress,
                    secureOnPassword = secureOnPassword,
                    hostId = peerHostId,
                    deviceId = deviceId,
                    keyId = keyId,
                    issuedAtUnixSeconds = issuedAtUnixSeconds,
                    expiresAtUnixSeconds = expiresAtUnixSeconds,
                    nonce = nonce,
                    secret = secret,
                )
            } ?: ByteString.EMPTY
        val request =
            WakeHostRequest
                .newBuilder()
                .setRequestId(requestId)
                .setTargetMacAddress(targetMacAddress)
                .setSecureOnPassword(secureOnPassword)
                .setHostId(peerHostId)
                .setDeviceId(deviceId)
                .setKeyId(keyId)
                .setIssuedAtUnixSeconds(issuedAtUnixSeconds)
                .setExpiresAtUnixSeconds(expiresAtUnixSeconds)
                .setNonce(nonce)
                .setSignature(signature)
                .build()
        return envelope().setWakeHostRequest(request).build()
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
                .setModifierMask(
                    NativeInputWire.wireModifierMask(
                        standardMask = modifierMask,
                        standardByteNegotiated =
                            Capability.CAPABILITY_USB_HID_MODIFIER_BYTE in negotiatedCapabilities,
                    ),
                )
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
        check(Capability.CAPABILITY_CONTROLLER in negotiatedCapabilities) { "Controller was not negotiated" }
        require(inputId > 0)
        val event =
            ControllerEvent
                .newBuilder()
                .setInputId(inputId)
                .setControllerId(sample.controllerId)
                .setControllerEpoch(sample.controllerEpoch)
                .setKind(sample.kind.toProto())
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
    fun peripheral(
        inputId: Long,
        peripheralKind: String,
        payload: ByteArray,
    ): Envelope {
        check(state == State.STREAMING)
        check(Capability.CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK in negotiatedCapabilities) {
            "Peripheral input framework was not negotiated"
        }
        require(inputId > 0) { "inputId must be positive" }
        require(peripheralKind.isNotEmpty()) { "peripheralKind must not be empty" }
        val kindBytes = peripheralKind.toByteArray(StandardCharsets.UTF_8)
        require(kindBytes.size <= MAX_PERIPHERAL_KIND_BYTES) {
            "peripheralKind must encode to 1-$MAX_PERIPHERAL_KIND_BYTES UTF-8 bytes"
        }
        require(payload.size <= MAX_PERIPHERAL_PAYLOAD_BYTES) {
            "peripheral payload must not exceed $MAX_PERIPHERAL_PAYLOAD_BYTES bytes"
        }
        val event =
            PeripheralEvent
                .newBuilder()
                .setInputId(inputId)
                .setPeripheralKind(peripheralKind)
                .setPayload(ByteString.copyFrom(payload))
                .setTarget(InputTarget.newBuilder().setDisplayId(displayId).setStreamId(streamId))
                .build()
        return envelope().setPeripheralEvent(event).build()
    }

    @Synchronized
    fun validateMedia(header: dev.vibescreen.protocol.v1.MediaPacketHeader): MediaDisposition {
        val pendingStreamId = pendingDisplaySelectionStreamId
        val expectedPendingStream = pendingStreamId > 0L && header.streamId == pendingStreamId
        if (header.sessionEpoch != sessionEpoch || (header.streamId != streamId && !expectedPendingStream)) {
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
        if (Capability.CAPABILITY_USB_HID_MODIFIER_BYTE in hostCapabilities &&
            Capability.CAPABILITY_KEYBOARD !in hostCapabilities
        ) {
            throw protocolFailure("USB HID modifier-byte capability requires keyboard")
        }
        peerHostId = hello.hostId
        hostMaxClipboardBytes = hello.resourceLimits.maximumClipboardBytes
        remoteManagedClipboardAllowed = true
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
        val peerIntersection = advertisedCapabilities
            .intersect(hostCapabilities)
            .withCapabilityDependenciesApplied()
        if (!peerIntersection.containsAll(negotiated)) {
            throw protocolFailure("Negotiated capabilities include capabilities not advertised by both peers")
        }
        val omittedNonPolicyCapabilities = (peerIntersection - negotiated) - POLICY_FILTERABLE_CAPABILITIES
        if (omittedNonPolicyCapabilities.isNotEmpty()) {
            throw protocolFailure("Negotiated capabilities omitted required peer intersection: $omittedNonPolicyCapabilities")
        }
        acceptedResourceLimits = accepted.negotiatedResourceLimits
        negotiatedFileTransferPolicy = fileTransferPolicy.negotiated(acceptedResourceLimits)
        sessionId = accepted.sessionId
        sessionEpoch = accepted.sessionEpoch
        baseNegotiatedCapabilities = negotiated
        negotiatedCapabilities = baseNegotiatedCapabilities.filteredBy(managedPolicyResolver.effectivePolicy)
        remoteManagedClipboardAllowed = true
        val acceptedMax = accepted.negotiatedResourceLimits.maximumClipboardBytes
        negotiatedMaxClipboardBytesValue =
            minOf(
                LOCAL_MAX_CLIPBOARD_BYTES,
                if (hostMaxClipboardBytes > 0L) hostMaxClipboardBytes else LOCAL_MAX_CLIPBOARD_BYTES,
                if (acceptedMax > 0L) acceptedMax else LOCAL_MAX_CLIPBOARD_BYTES,
            )
        if (Capability.CAPABILITY_CLIPBOARD in baseNegotiatedCapabilities && peerHostId.isBlank()) {
            throw protocolFailure("Host id is required when clipboard capability is negotiated")
        }
        state = State.ACTIVE
        val actions = mutableListOf<Action>()
        actions += Action.Send(envelope().setListDisplaysRequest(ListDisplaysRequest.getDefaultInstance()).build())
        if (Capability.CAPABILITY_MANAGED_CONFIGURATION in negotiatedCapabilities) {
            actions += Action.Send(envelope().setManagedPolicyStatus(managedPolicyResolver.effectivePolicy.toStatus()).build())
        }
        return actions
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
        val runtimeDisplaySelection = state == State.REDISPLAY_REQUESTED && pendingDisplaySelectionIdValue != null
        val expectedDisplayId = pendingDisplaySelectionIdValue ?: displayId
        if (!response.accepted) {
            clearPendingDisplaySelectionState(clearQueuedVideoPreferences = runtimeDisplaySelection)
            if (runtimeDisplaySelection && streamId > 0L && configEpoch > 0L) {
                state = State.STREAMING
                displayGeometryPublished = displayWidth > 0 && displayHeight > 0
                return listOf(
                    Action.DisplaySelectionRejected(
                        selectedId = displayId,
                        rejectedId = expectedDisplayId,
                        reason = response.rejectionReason.ifBlank { "display_selection_rejected" },
                    ),
                )
            }
            throw protocolFailure("Display start rejected: ${response.rejectionReason}")
        }
        if (response.streamId <= 0) {
            clearPendingDisplaySelectionState(clearQueuedVideoPreferences = runtimeDisplaySelection)
            throw protocolFailure("Display start rejected: ${response.rejectionReason}")
        }
        if (runtimeDisplaySelection) {
            pendingDisplaySelectionStreamId = response.streamId
        } else {
            streamId = response.streamId
        }
        if (response.hasDisplay()) {
            try {
                updateDisplayDescriptor(
                    display = response.display,
                    expectedDisplayId = expectedDisplayId,
                    commitDisplayId = !runtimeDisplaySelection,
                )
            } catch (failure: ProtocolV1Failure) {
                clearPendingDisplaySelectionState(clearQueuedVideoPreferences = runtimeDisplaySelection)
                throw failure
            }
        }
        if (runtimeDisplaySelection) {
            pendingDisplaySelectionCommitId = expectedDisplayId
        }
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
            val rejectedDisplaySelectionId = clearPendingDisplaySelection()
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
            ).withDisplaySelectionRejected(rejectedDisplaySelectionId, "video_configuration_pending")
        }
        val expectedConfigStreamId =
            pendingDisplaySelectionStreamId.takeIf { state == State.REDISPLAY_REQUESTED && it > 0L } ?: streamId
        val protocolAccepted =
            config.streamId == expectedConfigStreamId &&
                config.configEpoch > configEpoch &&
                config.encodedSize.width in 16..8192 &&
                config.encodedSize.height in 16..8192 &&
                config.framesPerSecond in 1..240 &&
                config.bitrateKbps > 0 &&
                config.rotationDegrees.toInt() in VALID_ROTATIONS &&
                config.codec in codecs &&
                config.codec in hostCodecs
        if (!protocolAccepted) {
            videoPreferencesRequestInFlight = false
            val rejectedDisplaySelectionId = clearPendingDisplaySelection()
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
            ).withDisplaySelectionRejected(rejectedDisplaySelectionId, "unsupported_video_config")
        }
        val colorDecision =
            VideoColorNegotiation.evaluate(
                requestedColor = if (config.hasColorDescription()) config.colorDescription else null,
                negotiatedHdr = Capability.CAPABILITY_HDR_VIDEO in negotiatedCapabilities,
                decodeCapabilities = decodeCapabilities,
                codec = config.codec,
                width = config.encodedSize.width,
                height = config.encodedSize.height,
                framesPerSecond = config.framesPerSecond,
            )
        if (colorDecision is VideoColorDecision.Fallback || colorDecision is VideoColorDecision.Rejected) {
            videoPreferencesRequestInFlight = false
            val rejectedDisplaySelectionId = clearPendingDisplaySelection()
            val selectedColor = (colorDecision as? VideoColorDecision.Fallback)?.selectedColor
            val reason =
                when (colorDecision) {
                    is VideoColorDecision.Fallback -> colorDecision.reason
                    is VideoColorDecision.Rejected -> colorDecision.reason
                    VideoColorDecision.Accepted -> error("accepted decision is handled before rejection")
                }
            return listOf(
                Action.Send(
                    videoConfigResult(
                        configEpoch = config.configEpoch,
                        streamId = config.streamId,
                        accepted = false,
                        rejectionReason = reason,
                        selectedColorDescription = selectedColor,
                        correlationId = envelope.messageId,
                    ),
                ),
            ).withDisplaySelectionRejected(rejectedDisplaySelectionId, reason)
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
            val failedDisplaySelectionId = pendingDisplaySelectionCommitId
            clearPendingDisplaySelectionState(clearQueuedVideoPreferences = failedDisplaySelectionId != null)
            if (failedDisplaySelectionId != null) {
                state = State.STREAMING
                displayGeometryPublished = displayWidth > 0 && displayHeight > 0
            }
            return buildList {
                add(result)
                if (failedDisplaySelectionId != null) {
                    add(
                        Action.DisplaySelectionRejected(
                            selectedId = displayId,
                            rejectedId = failedDisplaySelectionId,
                            reason = rejectionReason.ifBlank { "decoder_configuration_failure" },
                        ),
                    )
                }
                add(
                    Action.VideoConfigurationRejected(
                        configEpoch = pending.configEpoch,
                        reason = rejectionReason.ifBlank { "decoder_configuration_failure" },
                    ),
                )
            }
        }

        val committedDisplaySelectionId = pendingDisplaySelectionCommitId
        if (committedDisplaySelectionId != null) {
            displayId = committedDisplaySelectionId
            streamId = pendingDisplaySelectionStreamId
            displayWidth = pendingDisplaySelectionWidth
            displayHeight = pendingDisplaySelectionHeight
        }
        clearPendingDisplaySelectionState(clearQueuedVideoPreferences = false)
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
        if (committedDisplaySelectionId != null) {
            actions += Action.DisplaySelectionConfirmed(committedDisplaySelectionId)
            if (availableDisplays.any { it.id == committedDisplaySelectionId }) {
                actions += Action.DisplaysAvailable(availableDisplays, committedDisplaySelectionId)
            }
        }
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

    private fun onAudioConfig(envelope: Envelope): List<Action> {
        if (!isNegotiated()) throw protocolFailure("AudioConfig in state $state")
        if (Capability.CAPABILITY_AUDIO !in negotiatedCapabilities) {
            throw protocolFailure("AudioConfig without negotiated audio")
        }
        if (state != State.STREAMING) throw protocolFailure("AudioConfig arrived before video streaming")
        val config = envelope.audioConfig
        if (config.streamId <= 0L || config.configEpoch <= 0L || config.configEpoch <= audioConfigEpoch) {
            return listOf(
                Action.Send(
                    audioConfigResult(
                        streamId = config.streamId,
                        configEpoch = config.configEpoch,
                        accepted = false,
                        rejectionReason = "invalid_audio_config_epoch",
                        correlationId = envelope.messageId,
                    ),
                ),
            )
        }
        return listOf(Action.AudioConfigurationRequested(config, sessionEpoch, envelope.messageId))
    }

    @Synchronized
    fun completeAudioConfiguration(
        config: AudioConfig,
        accepted: Boolean,
        rejectionReason: String,
        correlationId: Long,
    ): Envelope? {
        if (state != State.STREAMING) return null
        if (Capability.CAPABILITY_AUDIO !in negotiatedCapabilities) return null
        if (config.streamId <= 0L || config.configEpoch <= 0L || config.configEpoch <= audioConfigEpoch) return null
        if (accepted) {
            audioStreamId = config.streamId
            audioConfigEpoch = config.configEpoch
        } else {
            clearAudioState()
        }
        return audioConfigResult(
            streamId = config.streamId,
            configEpoch = config.configEpoch,
            accepted = accepted,
            rejectionReason = if (accepted) "" else rejectionReason.ifBlank { "audio_configuration_rejected" },
            correlationId = correlationId,
        )
    }

    private fun updateDisplayDescriptor(
        display: dev.vibescreen.protocol.v1.DisplayDescriptor,
        expectedDisplayId: String?,
        commitDisplayId: Boolean = true,
    ) {
        if (display.displayId.isBlank() ||
            (expectedDisplayId != null && display.displayId != expectedDisplayId) ||
            !display.hasLogicalSize() ||
            display.logicalSize.width !in 16..8192 ||
            display.logicalSize.height !in 16..8192
        ) {
            throw protocolFailure("Invalid display descriptor")
        }
        if (commitDisplayId) {
            displayId = display.displayId
            displayWidth = display.logicalSize.width
            displayHeight = display.logicalSize.height
        } else {
            pendingDisplaySelectionWidth = display.logicalSize.width
            pendingDisplaySelectionHeight = display.logicalSize.height
        }
    }

    private fun clearPendingDisplaySelection(): String? {
        val rejectedDisplaySelectionId = pendingDisplaySelectionCommitId ?: pendingDisplaySelectionIdValue
        clearPendingDisplaySelectionState(clearQueuedVideoPreferences = rejectedDisplaySelectionId != null)
        if (rejectedDisplaySelectionId != null) {
            state = State.STREAMING
            displayGeometryPublished = displayWidth > 0 && displayHeight > 0
        }
        return rejectedDisplaySelectionId
    }

    private fun clearPendingDisplaySelectionState(clearQueuedVideoPreferences: Boolean) {
        pendingDisplaySelectionIdValue = null
        pendingDisplaySelectionCommitId = null
        pendingDisplaySelectionStreamId = 0L
        pendingDisplaySelectionWidth = 0
        pendingDisplaySelectionHeight = 0
        if (clearQueuedVideoPreferences) pendingVideoPreferences = null
    }

    private fun List<Action>.withDisplaySelectionRejected(
        rejectedDisplaySelectionId: String?,
        reason: String,
    ): List<Action> =
        if (rejectedDisplaySelectionId == null) {
            this
        } else {
            this +
                Action.DisplaySelectionRejected(
                    selectedId = displayId,
                    rejectedId = rejectedDisplaySelectionId,
                    reason = reason,
                )
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
        if (!managedPolicyResolver.effectivePolicy.hostActionsAllowed) {
            availableHostActions = emptyList()
            return listOf(Action.HostActionsAvailable(emptyList()))
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
        if (!managedPolicyResolver.effectivePolicy.hostActionsAllowed) {
            pendingHostActionInvocations.clear()
            return emptyList()
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

    /**
     * Offer the given text to the peer. The session caches exactly one snapshot;
     * a subsequent offer replaces the previous one. Returns the offer envelope
     * to send, or null when clipboard was not negotiated or the text is invalid.
     */
    @Synchronized
    fun offerClipboard(text: String): Envelope? {
        if (state != State.STREAMING) return null
        if (Capability.CAPABILITY_CLIPBOARD !in negotiatedCapabilities) return null
        if (!remoteManagedClipboardAllowed) return null
        val bytes = text.toByteArray(Charsets.UTF_8)
        if (bytes.isEmpty()) return null
        if (bytes.size.toLong() > negotiatedMaxClipboardBytesValue) return null
        val changeId = ByteString.copyFrom(ByteArray(CLIPBOARD_CHANGE_ID_BYTES).also(secureRandom::nextBytes))
        val sha256 = ByteString.copyFrom(sha256Digest(bytes))
        rememberClipboardChangeId(changeId)
        offeredClipboard =
            OfferedClipboard(
                changeId = changeId,
                originDeviceId = deviceId,
                mimeType = CLIPBOARD_MIME_TEXT_PLAIN,
                byteLength = bytes.size.toLong(),
                sha256 = sha256,
                content = bytes,
            )
        val offer =
            ClipboardOffer
                .newBuilder()
                .setChangeId(changeId)
                .setOriginDeviceId(deviceId)
                .setMimeType(CLIPBOARD_MIME_TEXT_PLAIN)
                .setByteLength(bytes.size.toLong())
                .setSha256(sha256)
                .build()
        return envelope().setClipboardOffer(offer).build()
    }

    /**
     * Request the content for a previously received clipboard offer. The request
     * is only valid for the most recently received offer. Returns the request
     * envelope to send, or null when no matching offer exists.
     */
    @Synchronized
    fun requestClipboard(changeId: ByteString): Envelope? {
        if (state != State.STREAMING) return null
        if (Capability.CAPABILITY_CLIPBOARD !in negotiatedCapabilities) return null
        if (!remoteManagedClipboardAllowed) return null
        val received = receivedClipboardOffer ?: return null
        if (received.changeId != changeId) return null
        // Do not re-request the same offer while a request is already in flight.
        if (requestedClipboardChangeId == changeId) return null
        requestedClipboardChangeId = changeId
        val request = ClipboardRequest.newBuilder().setChangeId(changeId).build()
        return envelope().setClipboardRequest(request).build()
    }

    @Synchronized
    fun canRequestClipboard(changeId: ByteString): Boolean =
        state == State.STREAMING &&
            Capability.CAPABILITY_CLIPBOARD in negotiatedCapabilities &&
            remoteManagedClipboardAllowed &&
            receivedClipboardOffer?.changeId == changeId &&
            requestedClipboardChangeId != changeId

    /**
     * Release a request that the UI timed out waiting for. This does not drop
     * the cached offer, so the user may explicitly retry the same change ID.
     */
    @Synchronized
    fun expireClipboardRequest(changeId: ByteString): Boolean {
        if (!remoteManagedClipboardAllowed) return false
        if (requestedClipboardChangeId != changeId) return false
        requestedClipboardChangeId = null
        return true
    }

    private fun onClipboardOffer(envelope: Envelope): List<Action> {
        if (state != State.STREAMING) throw protocolFailure("ClipboardOffer in state $state")
        if (Capability.CAPABILITY_CLIPBOARD !in negotiatedCapabilities) {
            throw protocolFailure("ClipboardOffer without negotiated clipboard")
        }
        if (!remoteManagedClipboardAllowed) {
            throw protocolFailure("ClipboardOffer denied by managed policy")
        }
        val offer = envelope.clipboardOffer
        if (offer.changeId.size() != CLIPBOARD_CHANGE_ID_BYTES) {
            throw protocolFailure("Invalid clipboard change_id length: ${offer.changeId.size()}")
        }
        if (offer.originDeviceId.isBlank()) {
            throw protocolFailure("ClipboardOffer missing origin_device_id")
        }
        if (offer.originDeviceId != peerHostId) {
            throw protocolFailure("ClipboardOffer origin_device_id does not match host id")
        }
        if (offer.mimeType != CLIPBOARD_MIME_TEXT_PLAIN) {
            throw protocolFailure("Unsupported clipboard mime type: ${offer.mimeType}")
        }
        if (offer.byteLength <= 0L || offer.byteLength > negotiatedMaxClipboardBytesValue) {
            throw protocolFailure("Invalid clipboard byte_length: ${offer.byteLength}")
        }
        if (offer.sha256.size() != CLIPBOARD_SHA256_BYTES) {
            throw protocolFailure("Invalid clipboard sha256 length: ${offer.sha256.size()}")
        }
        // Reject loopback: the host echoed a changeId we originated.
        if (offer.changeId in clipboardSeenChangeIds) {
            throw protocolFailure("ClipboardOffer change_id is a loopback of our own offer")
        }
        val existing = receivedClipboardOffer
        if (existing != null &&
            existing.changeId == offer.changeId &&
            (existing.originDeviceId != offer.originDeviceId ||
                existing.mimeType != offer.mimeType ||
                existing.byteLength != offer.byteLength ||
                existing.sha256 != offer.sha256)
        ) {
            throw protocolFailure("ClipboardOffer metadata changed for an existing change_id")
        }
        // A new offer supersedes any previous offer and its in-flight request.
        requestedClipboardChangeId = null
        receivedClipboardOffer =
            ReceivedClipboardOffer(
                changeId = offer.changeId,
                originDeviceId = offer.originDeviceId,
                mimeType = offer.mimeType,
                byteLength = offer.byteLength,
                sha256 = offer.sha256,
            )
        return listOf(
            Action.ClipboardOffered(
                changeId = offer.changeId,
                originDeviceId = offer.originDeviceId,
                mimeType = offer.mimeType,
                byteLength = offer.byteLength,
                sha256 = offer.sha256,
            ),
        )
    }

    private fun onClipboardRequest(envelope: Envelope): List<Action> {
        if (state != State.STREAMING) throw protocolFailure("ClipboardRequest in state $state")
        if (Capability.CAPABILITY_CLIPBOARD !in negotiatedCapabilities) {
            throw protocolFailure("ClipboardRequest without negotiated clipboard")
        }
        if (!remoteManagedClipboardAllowed) {
            throw protocolFailure("ClipboardRequest denied by managed policy")
        }
        val request = envelope.clipboardRequest
        if (request.changeId.size() != CLIPBOARD_CHANGE_ID_BYTES) {
            throw protocolFailure("Invalid clipboard request change_id length")
        }
        // A valid but unknown request can race a replacement offer or repeat
        // after the one-shot snapshot was consumed. It is an authenticated
        // no-op, not a reason to tear down the streaming session.
        val offered = offeredClipboard ?: return emptyList()
        if (request.changeId != offered.changeId) {
            return emptyList()
        }
        val content =
            ClipboardContent
                .newBuilder()
                .setChangeId(offered.changeId)
                .setOriginDeviceId(deviceId)
                .setMimeType(offered.mimeType)
                .setContent(ByteString.copyFrom(offered.content))
                .setSha256(offered.sha256)
                .build()
        // Consume the snapshot: a repeated request for the same changeId must
        // not re-send the body. Track the id so loopback echoes are rejected.
        rememberClipboardChangeId(offered.changeId)
        offeredClipboard = null
        recordClipboardFeedback(
            ClipboardFeedback(
                changeId = offered.changeId,
                originDeviceId = offered.originDeviceId,
                byteLength = offered.byteLength,
                success = true,
                reason = "",
            ),
        )
        return listOf(Action.Send(envelope().setClipboardContent(content).build()))
    }

    private fun onClipboardContent(envelope: Envelope): List<Action> {
        if (state != State.STREAMING) throw protocolFailure("ClipboardContent in state $state")
        if (Capability.CAPABILITY_CLIPBOARD !in negotiatedCapabilities) {
            throw protocolFailure("ClipboardContent without negotiated clipboard")
        }
        if (!remoteManagedClipboardAllowed) {
            throw protocolFailure("ClipboardContent denied by managed policy")
        }
        val content = envelope.clipboardContent
        if (content.changeId.size() != CLIPBOARD_CHANGE_ID_BYTES) {
            throw protocolFailure("Invalid clipboard content change_id length")
        }
        // Reject loopback echoes of changeIds we already sent or accepted.
        if (content.changeId in clipboardSeenChangeIds) {
            throw protocolFailure("ClipboardContent change_id was already sent or accepted")
        }
        if (content.originDeviceId.isBlank()) {
            throw protocolFailure("ClipboardContent missing origin_device_id")
        }
        if (content.originDeviceId != peerHostId) {
            throw protocolFailure("ClipboardContent origin_device_id does not match host id")
        }
        if (content.mimeType != CLIPBOARD_MIME_TEXT_PLAIN) {
            throw protocolFailure("Unsupported clipboard content mime type: ${content.mimeType}")
        }
        val contentBytes = content.content.toByteArray()
        if (contentBytes.isEmpty()) throw protocolFailure("ClipboardContent content is empty")
        if (contentBytes.size.toLong() > negotiatedMaxClipboardBytesValue) {
            throw protocolFailure("ClipboardContent exceeds negotiated limit")
        }
        // Strict UTF-8 validation: reject malformed bytes rather than replacing them.
        validateUtf8(contentBytes)
        if (content.sha256.size() != CLIPBOARD_SHA256_BYTES) {
            throw protocolFailure("Invalid clipboard content sha256 length")
        }
        val actualSha256 = ByteString.copyFrom(sha256Digest(contentBytes))
        if (actualSha256 != content.sha256) {
            throw protocolFailure("ClipboardContent sha256 mismatch")
        }
        // Content is solicited only when it matches a changeId we explicitly
        // requested. A received offer alone is not enough; unrequested content
        // is delivered as pending and must not be auto-applied.
        val solicited = requestedClipboardChangeId == content.changeId
        if (solicited) {
            val received = receivedClipboardOffer
            if (received == null || received.changeId != content.changeId) {
                throw protocolFailure("ClipboardContent matches request but no offer is cached")
            }
            if (received.byteLength != contentBytes.size.toLong()) {
                throw protocolFailure("ClipboardContent byte_length does not match offer")
            }
            if (received.sha256 != content.sha256) {
                throw protocolFailure("ClipboardContent sha256 does not match offer")
            }
            if (received.originDeviceId != content.originDeviceId ||
                received.mimeType != content.mimeType
            ) {
                throw protocolFailure("ClipboardContent identity does not match offer")
            }
            receivedClipboardOffer = null
            requestedClipboardChangeId = null
        }
        // Direct content is staged, not yet accepted by the user. Do not add it
        // to the accepted-ID history until an offer/request flow completes.
        if (solicited) rememberClipboardChangeId(content.changeId)
        recordClipboardFeedback(
            ClipboardFeedback(
                changeId = content.changeId,
                originDeviceId = content.originDeviceId,
                byteLength = contentBytes.size.toLong(),
                success = true,
                reason = "",
            ),
        )
        return listOf(
            Action.ClipboardContentReceived(
                changeId = content.changeId,
                originDeviceId = content.originDeviceId,
                mimeType = content.mimeType,
                content = contentBytes,
                sha256 = content.sha256,
                pending = !solicited,
            ),
        )
    }

    private fun onWakeHostRequest(envelope: Envelope): List<Action> {
        if (!isNegotiated()) throw protocolFailure("WakeHostRequest in state $state")
        if (Capability.CAPABILITY_WAKE_HOST !in negotiatedCapabilities) {
            throw protocolFailure("WakeHostRequest without negotiated wake host")
        }
        if (state != State.STREAMING) throw protocolFailure("WakeHostRequest before streaming")
        val request = envelope.wakeHostRequest
        if (request.requestId.isEmpty) throw protocolFailure("WakeHostRequest missing request id")
        if (request.hostId.isBlank() || request.hostId != peerHostId) {
            throw protocolFailure("WakeHostRequest targets a different host")
        }
        if (request.deviceId.isBlank() || request.deviceId != deviceId) {
            throw protocolFailure("WakeHostRequest device identity does not match this session")
        }
        return listOf(Action.WakeHost(request.toContext(), envelope.messageId))
    }

    private fun onWakeHostResult(envelope: Envelope): List<Action> {
        if (!isNegotiated()) throw protocolFailure("WakeHostResult in state $state")
        if (Capability.CAPABILITY_WAKE_HOST !in negotiatedCapabilities) {
            throw protocolFailure("WakeHostResult without negotiated wake host")
        }
        val result = envelope.wakeHostResult
        if (result.requestId.isEmpty) throw protocolFailure("WakeHostResult missing request id")
        if (!result.accepted && result.rejectionReason.isBlank()) {
            throw protocolFailure("Rejected WakeHostResult requires a reason")
        }
        if (!pendingWakeHostRequests.remove(result.requestId)) {
            return emptyList()
        }
        return listOf(
            Action.WakeHostCompleted(
                requestId = result.requestId,
                accepted = result.accepted,
                rejectionReason = result.rejectionReason,
            ),
        )
    }

    private fun recordClipboardFeedback(feedback: ClipboardFeedback) {
        clipboardFeedbackHistory.addLast(feedback)
        while (clipboardFeedbackHistory.size > MAX_CLIPBOARD_FEEDBACK_HISTORY) {
            clipboardFeedbackHistory.removeFirst()
        }
    }

    private fun rememberClipboardChangeId(changeId: ByteString) {
        if (changeId in clipboardSeenChangeIds) return
        clipboardSeenChangeIds.addLast(changeId)
        while (clipboardSeenChangeIds.size > MAX_CLIPBOARD_SEEN_IDS) {
            clipboardSeenChangeIds.removeFirst()
        }
    }

    private fun clearClipboardState() {
        offeredClipboard = null
        receivedClipboardOffer = null
        requestedClipboardChangeId = null
        clipboardSeenChangeIds.clear()
        clipboardFeedbackHistory.clear()
    }

    private fun validateUtf8(bytes: ByteArray) {
        val decoder = StandardCharsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
        try {
            decoder.decode(ByteBuffer.wrap(bytes))
        } catch (e: CharacterCodingException) {
            throw protocolFailure("Clipboard content is not valid UTF-8", e)
        }
    }

    private fun sha256Digest(bytes: ByteArray): ByteArray =
        MessageDigest.getInstance("SHA-256").digest(bytes)

    private fun onManagedPolicyStatus(status: ManagedPolicyStatus): List<Action> {
        if (!isNegotiated()) throw protocolFailure("ManagedPolicyStatus in state $state")
        if (Capability.CAPABILITY_MANAGED_CONFIGURATION !in baseNegotiatedCapabilities) {
            throw protocolFailure("ManagedPolicyStatus without negotiated managed configuration")
        }
        managedPolicyResolver.setRemote(ManagedPolicy.fromStatus(status))
        val effective = managedPolicyResolver.effectivePolicy
        remoteManagedClipboardAllowed = effective.clipboardAllowed
        if (!remoteManagedClipboardAllowed) clearClipboardState()
        negotiatedFileTransferPolicy = fileTransferPolicy
            .negotiated(acceptedResourceLimits)
            .applying(RemoteManagedPolicy(effective.toStatus()))
        if (!effective.allowsHost(hostId = peerHostId)) {
            throw protocolFailure("Managed policy does not allow this host")
        }
        val hadHostActionState =
            Capability.CAPABILITY_HOST_ACTIONS in negotiatedCapabilities ||
                availableHostActions.isNotEmpty() ||
                pendingHostActionInvocations.isNotEmpty()
        val hadAudioState = Capability.CAPABILITY_AUDIO in negotiatedCapabilities && audioStreamId > 0L
        negotiatedCapabilities = baseNegotiatedCapabilities.filteredBy(effective)
        val actions = mutableListOf<Action>(Action.ManagedPolicyReceived(status))
        if (hadAudioState && Capability.CAPABILITY_AUDIO !in negotiatedCapabilities) {
            clearAudioState()
            actions += Action.AudioStopped("managed_policy_audio_denied")
        }
        if (!effective.hostActionsAllowed) {
            availableHostActions = emptyList()
            pendingHostActionInvocations.clear()
            return if (hadHostActionState) {
                actions + Action.HostActionsAvailable(emptyList())
            } else {
                actions
            }
        }
        return actions
    }

    private fun onFileOffer(envelope: Envelope): List<Action> {
        if (!isNegotiated()) throw protocolFailure("FileOffer in state $state")
        if (Capability.CAPABILITY_FILE_TRANSFER !in negotiatedCapabilities) {
            throw protocolFailure("FileOffer without negotiated file transfer")
        }
        if (envelope.fileOffer.transferId.isEmpty) throw protocolFailure("FileOffer missing transfer id")
        return listOf(Action.FileOfferReceived(envelope.fileOffer))
    }

    private fun onFileAccept(envelope: Envelope): List<Action> {
        if (!isNegotiated()) throw protocolFailure("FileAccept in state $state")
        if (Capability.CAPABILITY_FILE_TRANSFER !in negotiatedCapabilities) {
            throw protocolFailure("FileAccept without negotiated file transfer")
        }
        if (envelope.fileAccept.transferId.isEmpty) throw protocolFailure("FileAccept missing transfer id")
        return listOf(Action.FileAcceptReceived(envelope.fileAccept))
    }

    private fun onFileTransferProgress(envelope: Envelope): List<Action> {
        if (!isNegotiated()) throw protocolFailure("FileTransferProgress in state $state")
        if (Capability.CAPABILITY_FILE_TRANSFER !in negotiatedCapabilities) {
            throw protocolFailure("FileTransferProgress without negotiated file transfer")
        }
        if (envelope.fileTransferProgress.transferId.isEmpty) throw protocolFailure("FileTransferProgress missing transfer id")
        return listOf(Action.FileProgressReceived(envelope.fileTransferProgress))
    }

    private fun onFileTransferCancel(envelope: Envelope): List<Action> {
        if (!isNegotiated()) throw protocolFailure("FileTransferCancel in state $state")
        if (Capability.CAPABILITY_FILE_TRANSFER !in negotiatedCapabilities) {
            throw protocolFailure("FileTransferCancel without negotiated file transfer")
        }
        if (envelope.fileTransferCancel.transferId.isEmpty) throw protocolFailure("FileTransferCancel missing transfer id")
        return listOf(Action.FileCancelReceived(envelope.fileTransferCancel))
    }

    private fun onFileTransferComplete(envelope: Envelope): List<Action> {
        if (!isNegotiated()) throw protocolFailure("FileTransferComplete in state $state")
        if (Capability.CAPABILITY_FILE_TRANSFER !in negotiatedCapabilities) {
            throw protocolFailure("FileTransferComplete without negotiated file transfer")
        }
        if (envelope.fileTransferComplete.transferId.isEmpty) throw protocolFailure("FileTransferComplete missing transfer id")
        return listOf(Action.FileCompleteReceived(envelope.fileTransferComplete))
    }

    @Synchronized
    fun completeWakeHost(
        requestId: ByteString,
        accepted: Boolean,
        rejectionReason: String,
        correlationId: Long,
    ): Envelope? {
        if (state != State.STREAMING && state != State.REDISPLAY_REQUESTED) return null
        if (Capability.CAPABILITY_WAKE_HOST !in negotiatedCapabilities) return null
        if (requestId.isEmpty) return null
        return envelope(correlationId = correlationId)
            .setWakeHostResult(
                WakeHostResult
                    .newBuilder()
                    .setRequestId(requestId)
                    .setAccepted(accepted)
                    .setRejectionReason(if (accepted) "" else rejectionReason.ifBlank { "wake_host_rejected" }),
            ).build()
    }

    private fun WakeHostRequest.toContext(): WakeHostRequestContext =
        WakeHostRequestContext(
            requestId = requestId,
            targetMacAddress = targetMacAddress,
            secureOnPassword = secureOnPassword,
            hostId = hostId,
            deviceId = this@toContext.deviceId,
            keyId = this@toContext.keyId,
            issuedAtUnixSeconds = this@toContext.issuedAtUnixSeconds,
            expiresAtUnixSeconds = this@toContext.expiresAtUnixSeconds,
            nonce = this@toContext.nonce,
            signature = this@toContext.signature,
        )

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
        selectedColorDescription: dev.vibescreen.protocol.v1.ColorDescription? = null,
        correlationId: Long,
    ): Envelope =
        envelope(correlationId = correlationId)
            .setVideoConfigResult(
                VideoConfigResult
                    .newBuilder()
                    .setConfigEpoch(configEpoch)
                    .setStreamId(streamId)
                    .setAccepted(accepted)
                    .setRejectionReason(rejectionReason)
                    .also { builder ->
                        if (selectedColorDescription != null) {
                            builder.selectedColorDescription = selectedColorDescription
                        }
                    },
            ).build()

    private fun audioConfigResult(
        streamId: Long,
        configEpoch: Long,
        accepted: Boolean,
        rejectionReason: String,
        correlationId: Long,
    ): Envelope =
        envelope(correlationId = correlationId)
            .setAudioConfigResult(
                AudioConfigResult
                    .newBuilder()
                    .setStreamId(streamId)
                    .setConfigEpoch(configEpoch)
                    .setAccepted(accepted)
                    .setRejectionReason(rejectionReason),
            ).build()

    private fun clearAudioState() {
        audioStreamId = 0L
        audioConfigEpoch = 0L
    }

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

    private fun protocolFailure(message: String, cause: Throwable? = null): ProtocolV1Failure =
        ProtocolV1Failure(
            reason = "invalid_peer_message",
            retryable = false,
            source = ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION,
            message = "Protocol v1: $message",
            cause = cause,
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

    private fun ControllerEventKind.toProto(): ProtocolControllerEventKind =
        when (this) {
            ControllerEventKind.CONNECTED -> ProtocolControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED
            ControllerEventKind.STATE -> ProtocolControllerEventKind.CONTROLLER_EVENT_KIND_STATE
            ControllerEventKind.DISCONNECTED -> ProtocolControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED
        }

    private data class OfferedClipboard(
        val changeId: ByteString,
        val originDeviceId: String,
        val mimeType: String,
        val byteLength: Long,
        val sha256: ByteString,
        val content: ByteArray,
    )

    private data class ReceivedClipboardOffer(
        val changeId: ByteString,
        val originDeviceId: String,
        val mimeType: String,
        val byteLength: Long,
        val sha256: ByteString,
    )

    private data class ClipboardFeedback(
        val changeId: ByteString,
        val originDeviceId: String,
        val byteLength: Long,
        val success: Boolean,
        val reason: String,
    )

    companion object {
        private const val STYLUS_BUTTON_MASK = 0b11
        const val MAX_PERIPHERAL_KIND_BYTES = 128
        const val MAX_PERIPHERAL_PAYLOAD_BYTES = 64 * 1024
        const val VERSION = 1
        private val VALID_ROTATIONS = setOf(0, 90, 180, 270)
        private val BASE_ADVERTISED_CAPABILITIES =
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
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            )

        /** Move the focused Mac window onto the client display. Fixed with the host. */
        const val ACTION_MOVE_WINDOW = "move-window"

        /** Return windows previously moved to the client back to the Mac. Fixed with the host. */
        const val ACTION_RETURN_WINDOWS = "return-windows"

        // Only these fixed ids are surfaced; unknown catalog entries are ignored
        // so the client never offers an action it cannot present or invoke.
        private val KNOWN_HOST_ACTION_IDS = setOf(ACTION_MOVE_WINDOW, ACTION_RETURN_WINDOWS)
        private val POLICY_FILTERABLE_CAPABILITIES =
            setOf(
                Capability.CAPABILITY_CLIPBOARD,
                Capability.CAPABILITY_FILE_TRANSFER,
                Capability.CAPABILITY_AUDIO,
                Capability.CAPABILITY_WAKE_HOST,
                Capability.CAPABILITY_HOST_ACTIONS,
            )

        private fun Set<Capability>.withCapabilityDependenciesApplied(): Set<Capability> {
            val capabilities = toMutableSet()
            if (Capability.CAPABILITY_STYLUS !in capabilities) {
                capabilities.remove(Capability.CAPABILITY_STYLUS_EXTENDED)
            }
            if (Capability.CAPABILITY_KEYBOARD !in capabilities) {
                capabilities.remove(Capability.CAPABILITY_USB_HID_MODIFIER_BYTE)
            }
            return capabilities
        }

        // Bound the surfaced actions and in-flight invocations so a misbehaving
        // host or caller cannot grow either without limit.
        private const val MAX_HOST_ACTIONS = 8
        private const val MAX_PENDING_HOST_ACTIONS = 16
        private const val MAX_PENDING_WAKE_HOST_REQUESTS = 16
        private const val WAKE_HOST_AUTHORIZATION_LIFETIME_SECONDS = 60L

        // Clipboard transfer limits and wire constants.
        const val LOCAL_MAX_CLIPBOARD_BYTES: Long = 1024L * 1024L
        private const val CLIPBOARD_CHANGE_ID_BYTES = 16
        private const val CLIPBOARD_SHA256_BYTES = 32
        private const val MAX_CLIPBOARD_SEEN_IDS = 128
        private const val MAX_CLIPBOARD_FEEDBACK_HISTORY = 128
        private const val CLIPBOARD_MIME_TEXT_PLAIN = "text/plain"

        private fun Set<Capability>.filteredBy(policy: ManagedPolicy): Set<Capability> =
            filterTo(mutableSetOf()) { capability ->
                when (capability) {
                    Capability.CAPABILITY_CLIPBOARD -> policy.clipboardAllowed
                    Capability.CAPABILITY_FILE_TRANSFER -> policy.fileTransferAllowed
                    Capability.CAPABILITY_AUDIO -> policy.audioAllowed
                    Capability.CAPABILITY_WAKE_HOST -> policy.wakeAllowed
                    Capability.CAPABILITY_HOST_ACTIONS -> policy.hostActionsAllowed
                    else -> true
                }
            }
    }
}
