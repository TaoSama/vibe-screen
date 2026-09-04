package dev.telemachus.display.internet

import com.google.protobuf.ByteString
import dev.telemachus.display.ControllerConnectionAckTracker
import dev.telemachus.display.ControllerDispatchOrdering
import dev.telemachus.display.ControllerEventKind
import dev.telemachus.display.ControllerStateSample
import dev.telemachus.display.ClipboardContentData
import dev.telemachus.display.ClipboardOfferData
import dev.telemachus.display.FileTransferProductOwner
import dev.telemachus.display.OutgoingFileTransferHandle
import dev.telemachus.display.PendingControllerInputDisposition
import dev.telemachus.display.SessionInputIdSequence
import dev.telemachus.display.STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON
import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import dev.telemachus.display.internet.security.AdvancedChannelAdmission
import dev.telemachus.display.internet.security.AdvancedChannelBacklogRejectedException
import dev.telemachus.display.internet.security.AdvancedChannelBinding
import dev.telemachus.display.internet.security.AdvancedChannelOwner
import dev.telemachus.display.internet.security.AdvancedChannelSecurityGate
import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.SecurityTranscript
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.FileChunk
import dev.telemachus.display.protocol.FileTransferException
import dev.telemachus.display.protocol.FileTransferPolicy
import dev.telemachus.display.protocol.ProtocolV1Framing
import dev.telemachus.display.protocol.RemoteManagedPolicy
import dev.vibescreen.protocol.v1.AudioConfig
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.FileOffer
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import dev.vibescreen.protocol.v1.ResourceLimits
import java.io.File
import java.io.IOException
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

class InternetProductSessionLease(
    val pairingIdentifier: String,
    val signalingSessionId: String,
    val authoritativeSessionEpoch: Long,
    val identityEpoch: Long,
    val localIdentity: InternetPairingIdentity,
    val transcriptContext: ByteArray,
    val iceServers: List<IceServer>,
    val signaling: SignalingConfiguration,
    val pinnedHostId: String,
    val iceTransportPolicy: IceTransportPolicy = IceTransportPolicy.ALL,
    val protocolSessionId: ByteArray = signalingSessionId.toByteArray(Charsets.UTF_8),
) : AutoCloseable {
    init {
        require(pairingIdentifier.isNotBlank() && signalingSessionId.isNotBlank()) { "Session lease identifiers are required" }
        require(authoritativeSessionEpoch in 1 until Long.MAX_VALUE && identityEpoch in 1 until Long.MAX_VALUE) {
            "Session and identity epochs must be positive and below the reserved maximum"
        }
        require(localIdentity.keyEpoch == identityEpoch) { "Session lease local identity epoch is inconsistent" }
        require(protocolSessionId.isNotEmpty()) { "Protocol session identifier is required" }
        require(pinnedHostId.isNotBlank()) { "Pinned host identity is required" }
        require(signaling.role == PeerRole.DEVICE) { "Android product sessions must use a device signaling credential" }
    }

    /** Mirrors macOS InternetProductSessionConfiguration.boundTranscriptContext byte-for-byte. */
    fun boundTranscriptContext(localDeviceId: String): ByteArray {
        require(localDeviceId.isNotBlank()) { "Local device identity is required" }
        return SecurityTranscript.digest(
            PRODUCT_SESSION_CONTEXT_DOMAIN,
            transcriptContext,
            signalingSessionId.toByteArray(Charsets.UTF_8),
            SecurityTranscript.uint64(authoritativeSessionEpoch),
            pinnedHostId.toByteArray(Charsets.UTF_8),
            localDeviceId.toByteArray(Charsets.UTF_8),
            SecurityTranscript.uint64(HOST_ROLE),
            SecurityTranscript.uint64(DEVICE_ROLE),
        )
    }

    override fun close() {
        signaling.close()
        iceServers.forEach(IceServer::close)
        transcriptContext.fill(0)
        protocolSessionId.fill(0)
    }

    override fun toString(): String =
        "InternetProductSessionLease(pairingIdentifier=$pairingIdentifier, signalingSessionId=$signalingSessionId, " +
            "authoritativeSessionEpoch=$authoritativeSessionEpoch, identityEpoch=$identityEpoch, credentials=<redacted>)"

    private companion object {
        const val PRODUCT_SESSION_CONTEXT_DOMAIN = "vibescreen/product-session-context/v1"
        const val HOST_ROLE = 1L
        const val DEVICE_ROLE = 2L
    }
}

enum class InternetProductSessionState {
    IDLE,
    CONNECTING,
    NEGOTIATING,
    ACTIVE,
    RECOVERING,
    SUSPENDED,
    FAILED,
    CLOSED,
}

data class ProductVideoDecision(
    val accepted: Boolean,
    val rejectionReason: String = "",
) {
    init {
        require(accepted || rejectionReason.isNotBlank()) { "Rejected video configuration requires a reason" }
    }

    companion object {
        val ACCEPT = ProductVideoDecision(true)

        fun reject(reason: String) = ProductVideoDecision(false, reason)
    }
}

class ProductVideoConfigurationEffect internal constructor(
    private val commitBlock: (() -> ProductVideoDecision) -> ProductVideoDecision,
) {
    private val committed = java.util.concurrent.atomic.AtomicBoolean(false)

    fun commit(effect: () -> ProductVideoDecision): ProductVideoDecision =
        if (committed.compareAndSet(false, true)) {
            commitBlock(effect)
        } else {
            ProductVideoDecision.reject("decoder_effect_already_committed")
        }
}

data class ProductVideoFrame(
    val streamId: Long,
    val sessionEpoch: Long,
    val configEpoch: Long,
    val frameId: Long,
    val captureTimestampNs: Long,
    val keyframe: Boolean,
    val codec: ProductVideoCodec,
    val payload: ByteArray,
)

internal data class ProductControllerEvent(
    val inputId: Long?,
    val sample: ControllerStateSample,
) {
    constructor(sample: ControllerStateSample) : this(null, sample)

    init {
        require(inputId == null || inputId > 0) { "Controller input identifier must be positive" }
    }
}

internal interface InternetProductSessionCallbacks {
    fun onStateChanged(state: InternetProductSessionState) = Unit

    fun onRouteSelected(route: PeerRoute) = Unit

    fun onVideoConfiguration(
        configuration: ProductVideoConfiguration,
        effect: ProductVideoConfigurationEffect,
        completion: (ProductVideoDecision) -> Unit,
    ) = completion(effect.commit { ProductVideoDecision.reject("decoder_not_configured") })

    fun onVideoConfigurationApplied(configuration: ProductVideoConfiguration) = Unit

    fun onVideoFrame(frame: ProductVideoFrame) = Unit

    fun onAudioRecord(payload: ByteArray) = Unit

    fun onBulkRecord(payload: ByteArray) = Unit

    fun onClipboardOffered(offer: ClipboardOfferData) = Unit

    fun onClipboardContent(content: ClipboardContentData) = Unit

    fun onManagedPolicyReceived(status: ManagedPolicyStatus) = Unit

    fun onFileOffer(offer: FileOffer) = Unit

    fun onIncomingFileProgress(transferId: ByteString, receivedBytes: Long) = Unit

    fun onIncomingFileCancelled(transferId: ByteString, reasonCode: String) = Unit

    fun onIncomingFileCompleted(completed: CompletedIncomingFile) = Unit

    fun onOutgoingFileProgress(transferId: ByteString, acknowledgedBytes: Long, totalBytes: Long) = Unit

    fun onOutgoingFileFinished(transferId: ByteString) = Unit

    fun onFileTransferResult(accepted: Boolean, reason: String) = Unit

    fun onPong(sequence: Long) = Unit

    fun onInputAck(
        inputId: Long,
        controllerId: String?,
        controllerEpoch: Long?,
        accepted: Boolean,
        rejectionReason: String,
    ) = Unit

    fun onFreshSessionRequired(reason: String) = Unit

    fun onRevoked(reason: String) = Unit

    fun onFailure(error: Throwable) = Unit
}

/** Persists authenticated revocation before UI notification or transport close. */
interface InternetProductRevocationStore {
    fun persistAuthenticatedRevocation(pairingIdentifier: String, reason: String)

    /** Must durably block admission before this session can release its transport. */
    fun persistPendingAuthenticatedRevocation(pairingIdentifier: String, reason: String)

    /** Returns true for either a durable pending barrier or a completed tombstone. */
    fun isAdmissionBlocked(pairingIdentifier: String): Boolean
}

class PendingRevocationBarrierException(cause: Throwable? = null) :
    IllegalStateException("Cannot release the Internet session before pending revocation is durably persisted", cause)

internal object InternetProductAdmissionGate {
    private val lock = ReentrantLock(true)

    fun <T> withLock(block: () -> T): T = lock.withLock(block)

    fun requireHeld() {
        check(lock.isHeldByCurrentThread) { "Internet credential mutation requires an admission transaction" }
    }
}

internal class InternetProductCredentialMutationPermit internal constructor() {
    private var active = true

    fun requireActive() {
        InternetProductAdmissionGate.requireHeld()
        check(active) { "Internet credential mutation permit is no longer active" }
    }

    internal fun invalidate() {
        InternetProductAdmissionGate.requireHeld()
        active = false
    }
}

class InternetProductRevocationCoordinator {
    private val blockedPairings = mutableSetOf<String>()
    private val reservations = mutableSetOf<Reservation>()

    internal fun reserve(pairingIdentifier: String): Reservation =
        InternetProductAdmissionGate.withLock {
            check(pairingIdentifier !in blockedPairings) { "Authenticated revocation is already pending or committed" }
            Reservation(pairingIdentifier).also {
                blockedPairings += pairingIdentifier
                reservations += it
            }
        }

    internal fun commit(reservation: Reservation) {
        InternetProductAdmissionGate.withLock {
            check(reservations.remove(reservation)) { "Authenticated revocation reservation is not active" }
            check(reservation.pairingIdentifier in blockedPairings) { "Authenticated revocation admission block was lost" }
        }
    }

    fun isBlocked(pairingIdentifier: String): Boolean =
        InternetProductAdmissionGate.withLock { pairingIdentifier in blockedPairings }

    fun hasActiveReservation(): Boolean = InternetProductAdmissionGate.withLock { reservations.isNotEmpty() }

    fun isCredentialMutationBlocked(durableBlock: () -> Boolean): Boolean =
        InternetProductAdmissionGate.withLock { reservations.isNotEmpty() || durableBlock() }

    internal fun <T> withCredentialMutationAdmission(
        durableBlock: () -> Boolean,
        mutation: (InternetProductCredentialMutationPermit) -> T,
    ): T =
        InternetProductAdmissionGate.withLock {
            check(reservations.isEmpty() && !durableBlock()) {
                "Internet credential mutation is blocked by revocation state"
            }
            val permit = InternetProductCredentialMutationPermit()
            try {
                mutation(permit)
            } finally {
                permit.invalidate()
            }
        }

    internal data class Reservation(val pairingIdentifier: String)

    companion object {
        private val PROCESS_SHARED = InternetProductRevocationCoordinator()

        fun processShared(): InternetProductRevocationCoordinator = PROCESS_SHARED
    }
}

internal data class InternetProductSessionTestHooks(
    val afterControlDecodeBeforeCommit: () -> Unit = {},
    val afterMediaDecodeBeforeCommit: () -> Unit = {},
    val beforeMediaDispatchGate: () -> Unit = {},
    val afterStateCommitBeforeDispatchGate: (InternetProductSessionState) -> Unit = {},
    val afterRevocationReservedBeforePersist: () -> Unit = {},
    val afterRevocationPersistBeforeCommit: () -> Unit = {},
    val afterRevocationStateCommitBeforeCallback: () -> Unit = {},
)

/**
 * Product Protocol v1 composition above the application-encrypted WebRTC channels.
 * One instance owns exactly one signaling session and epoch. Recovery is handed to
 * the owner, which must obtain a fresh lease and construct a replacement instance.
 */
class InternetProductSession internal constructor(
    private val lease: InternetProductSessionLease,
    configuration: PeerConfiguration,
    peerEngine: WebRtcPeerEngine,
    networkMonitor: NetworkMonitor,
    private val clock: MonotonicClock,
    private val codec: ProtocolV1ProductCodec,
    private val audioPlayback: InternetAudioPlayback? = null,
    private val callbacks: InternetProductSessionCallbacks,
    private val revocationStore: InternetProductRevocationStore,
    private val revocationCoordinator: InternetProductRevocationCoordinator,
    private val nextControllerInputId: () -> Long = SessionInputIdSequence()::next,
    fileTransferStagingDirectory: File = defaultFileTransferStagingDirectory(),
    private val fileTransferPolicy: FileTransferPolicy = FileTransferPolicy(),
    private val testHooks: InternetProductSessionTestHooks = InternetProductSessionTestHooks(),
) : AutoCloseable {
    private val lock = Any()
    private val videoEffectGate = ReentrantLock(true)
    private val callbackGate = ReentrantLock(true)
    private val nextMessageId = AtomicLong(0)
    private var currentVideoConfiguration: ProductVideoConfiguration? = null
    private var pendingVideoConfiguration: PendingVideoConfiguration? = null
    private var pendingRevocation: PendingRevocation? = null
    private var acceptedHostHello = false
    private var acceptedSession = false
    private var expectedNegotiatedCapabilities = emptySet<Capability>()
    private var baseNegotiatedCapabilities = emptySet<Capability>()
    private var hostMaximumEncryptedMediaRecordBytes = 0L
    private var hostMaximumClipboardBytes = 0L
    private var hostMaximumFileBytes = 0L
    private var hostMaximumFileChunkBytes = 0
    private var negotiatedMaximumEncryptedMediaRecordBytes = 0
    private var negotiatedMaximumClipboardBytes = 0L
    private var remoteManagedClipboardAllowed = true
    private val managedPolicyResolver = InternetManagedPolicyResolver(codec.localManagedPolicy)
    private val localFileTransferPolicy = fileTransferPolicy.applying(RemoteManagedPolicy(codec.localManagedPolicy.toStatus()))
    private var clipboard: InternetClipboard? = null
    private var negotiatedFilePolicy = localFileTransferPolicy.copy(allowed = false, maximumFileBytes = 0L)
    private val outgoingFileTransferDeadlines = LinkedHashMap<ByteString, OutgoingFileTransferDeadline>()
    private var currentAudioConfiguration: AudioConfig? = null
    private var audioPlaybackConfigured = false
    private var negotiationStarted = false
    private var freshSessionRequested = false
    private var heartbeatIntervalMillis = 0L
    private var nextHeartbeatAtMillis = Long.MAX_VALUE
    private var nextHeartbeatSequence = 1L
    private var lastReceivedControlMessageId = 0L
    private var closed = false
    private val transportOwner = TransportOwner(generation = 1)
    private var activeTransportOwner: TransportOwner? = transportOwner
    private val frameAssembler = ProductMediaFrameAssembler(clock)
    private val controllerSendGate = ReentrantLock(true)
    private val controllerSendQueue = InternetControllerSendQueue<ProductControllerEvent>()
    private val controllerConnectionAcks = ControllerConnectionAckTracker()
    private val minimumNextControllerInputId = AtomicLong(1)
    private val fileTransferProductOwner =
        FileTransferProductOwner(
            fileTransferPolicy = localFileTransferPolicy,
            stagingDirectory = { fileTransferStagingDirectory },
            pendingOfferGate = InternetFileTransferPendingOfferGate(),
        ).apply {
            onFileOffer = callbacks::onFileOffer
            onIncomingFileProgress = callbacks::onIncomingFileProgress
            onIncomingFileCancelled = callbacks::onIncomingFileCancelled
            onIncomingFileCompleted = callbacks::onIncomingFileCompleted
            onOutgoingFileProgress = callbacks::onOutgoingFileProgress
            onOutgoingFileFinished = callbacks::onOutgoingFileFinished
            onFileTransferResult = callbacks::onFileTransferResult
        }
    private val advancedChannelGate =
        AdvancedChannelSecurityGate(
            initialOwner = advancedChannelOwner(transportOwner),
            limits =
                AdvancedChannelSecurityGate.Limits(
                    maximumAudioRecordBytes = InternetAudioRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES,
                    maximumAudioBacklogBytes =
                        AUDIO_BACKLOG_RECORD_CAPACITY * InternetAudioRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES,
                    maximumBulkRecordBytes = InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES,
                    maximumBulkBacklogBytes = 4 * 1024 * 1024,
                ),
        )

    init {
        check(!revocationCoordinator.isBlocked(lease.pairingIdentifier) && !revocationStore.isAdmissionBlocked(lease.pairingIdentifier)) {
            "This authenticated pairing is revoked"
        }
    }

    private val transport =
        WebRtcInternetTransport(
            configuration = configuration,
            peerEngine = peerEngine,
            networkMonitor = networkMonitor,
            clock = clock,
            eventSink = { event -> handleTransportEvent(transportOwner, event) },
        ).apply {
            onControlMessage = { payload -> handleControl(transportOwner, payload) }
            onMediaPacket = { payload -> handleMedia(transportOwner, payload) }
            onAudioRecord = { payload -> handleAudioRecord(transportOwner, payload) }
            onBulkRecord = { payload -> handleBulkRecord(transportOwner, payload) }
        }

    @Volatile
    var state: InternetProductSessionState = InternetProductSessionState.IDLE
        private set

    fun start() {
        withLifecycleGate {
            synchronized(lock) {
                check(!closed) { "Product session is closed" }
                check(state == InternetProductSessionState.IDLE) { "Product session has already started" }
                check(
                    !revocationCoordinator.isBlocked(lease.pairingIdentifier) &&
                        !revocationStore.isAdmissionBlocked(lease.pairingIdentifier),
                ) {
                    "This authenticated pairing is revoked"
                }
                state = InternetProductSessionState.CONNECTING
            }
            testHooks.afterStateCommitBeforeDispatchGate(InternetProductSessionState.CONNECTING)
            if (synchronized(lock) { !closed && state == InternetProductSessionState.CONNECTING }) {
                callbacks.onStateChanged(InternetProductSessionState.CONNECTING)
            }
            if (synchronized(lock) { closed }) return
            try {
                transport.start()
            } catch (failure: Throwable) {
                fail(failure)
                throw failure
            }
        }
    }

    fun tick() {
        transport.tick()
        expirePendingVideoConfiguration()
        expirePendingMediaFrame()
        expirePendingControllerConnections()
        expireOutgoingFileTransfers()
        heartbeatTick()
    }

    fun sendTouch(event: ProductTouchEvent): Boolean {
        if (!synchronized(lock) { Capability.CAPABILITY_TOUCH in expectedNegotiatedCapabilities }) return false
        return sendApplicationControl {
            codec.encodeTouch(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, event)
        }
    }

    fun canSendTouch(): Boolean =
        synchronized(lock) {
            acceptsTransportCallbackLocked() &&
                acceptedSession &&
                state == InternetProductSessionState.ACTIVE &&
                Capability.CAPABILITY_TOUCH in expectedNegotiatedCapabilities
        }

    fun sendStylus(event: ProductStylusEvent): Boolean {
        val streamId =
            synchronized(lock) {
                if (Capability.CAPABILITY_STYLUS !in expectedNegotiatedCapabilities) return false
                if (
                    (event.toolKind != null || event.contactState != null || event.buttonMask != 0) &&
                    Capability.CAPABILITY_STYLUS_EXTENDED !in expectedNegotiatedCapabilities
                ) {
                    return false
                }
                currentVideoConfiguration?.streamId
            } ?: return false
        return sendApplicationControl {
            codec.encodeStylus(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                streamId,
                event,
            )
        }
    }

    fun canSendStylus(): Boolean =
        synchronized(lock) {
            acceptsTransportCallbackLocked() &&
                acceptedSession &&
                state == InternetProductSessionState.ACTIVE &&
                currentVideoConfiguration != null &&
                Capability.CAPABILITY_STYLUS in expectedNegotiatedCapabilities
        }

    fun canSendExtendedStylus(): Boolean =
        synchronized(lock) {
            acceptsTransportCallbackLocked() &&
                acceptedSession &&
                state == InternetProductSessionState.ACTIVE &&
                currentVideoConfiguration != null &&
                Capability.CAPABILITY_STYLUS in expectedNegotiatedCapabilities &&
                Capability.CAPABILITY_STYLUS_EXTENDED in expectedNegotiatedCapabilities
        }

    fun hasNegotiatedControllerCapability(): Boolean =
        synchronized(lock) {
            acceptsTransportCallbackLocked() &&
                acceptedSession &&
                Capability.CAPABILITY_CONTROLLER in expectedNegotiatedCapabilities
        }

    fun canSendController(): Boolean =
        synchronized(lock) {
            canSendControllerLocked()
        }

    internal fun sendController(
        events: List<ProductControllerEvent>,
        delivery: InternetControllerSendQueue.Delivery,
    ): Boolean =
        controllerSendGate.withLock {
            if (events.isEmpty()) return@withLock false
            val orderedEvents = orderControllerEventsBeforeQueueing(events)
            val sendImmediately = synchronized(lock) { canSendControllerLocked() }
            val queueStructuralForRecovery =
                delivery == InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL &&
                    synchronized(lock) { canQueueControllerStructuralForRecoveryLocked() }
            if (!sendImmediately && !queueStructuralForRecovery) return@withLock false
            val enqueueResult = controllerSendQueue.enqueue(orderedEvents, delivery)
            if (enqueueResult == InternetControllerSendQueue.EnqueueResult.STRUCTURAL_OVERFLOW) {
                fail(IllegalStateException("Controller structural send queue overflowed"))
                return@withLock false
            }
            if (!sendImmediately) return@withLock true
            drainControllerQueue() || synchronized(lock) { state in CONTROLLER_STRUCTURAL_STATES }
        }

    private fun orderControllerEventsBeforeQueueing(events: List<ProductControllerEvent>): List<ProductControllerEvent> {
        if (events.size < 2) return events
        val remaining = events.toMutableList()
        val ordered = ArrayList<ProductControllerEvent>(events.size)
        var changed = false
        while (remaining.isNotEmpty()) {
            val samples = remaining.map { it.sample }
            val nextIndex =
                remaining.indices.firstOrNull { index ->
                    val sample = samples[index]
                    !ControllerDispatchOrdering.hasLaterLowerEpochDisconnect(samples, index, sample) &&
                        !ControllerDispatchOrdering.hasLaterSameConnectionConnected(samples, index, sample)
                } ?: 0
            if (nextIndex != 0) changed = true
            ordered += remaining.removeAt(nextIndex)
        }
        return if (changed) ordered else events
    }

    fun requestKeyframe(reason: String): Boolean {
        val streamId = synchronized(lock) { currentVideoConfiguration?.streamId } ?: return false
        return sendApplicationControl {
            codec.encodeKeyframeRequest(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                streamId,
                reason,
            )
        }
    }

    fun sendAudioRecord(payload: ByteArray): Boolean {
        val streamId = synchronized(lock) { currentVideoConfiguration?.streamId } ?: return false
        return sendAdvancedRecord(payload, AdvancedChannelBinding.Audio(INTERNET_DISPLAY_ID, streamId)) {
            transport.sendAudioRecord(payload)
        }
    }

    fun sendBulkRecord(
        payload: ByteArray,
        transferId: ByteArray,
    ): Boolean =
        sendAdvancedRecord(payload, AdvancedChannelBinding.Bulk(transferId)) {
            transport.sendBulkRecord(payload)
        }

    fun canSendClipboard(): Boolean = synchronized(lock) { canUseClipboardLocked() }

    fun negotiatedMaxClipboardBytes(): Long = synchronized(lock) { negotiatedMaximumClipboardBytes }

    fun offerClipboard(text: String): Boolean {
        val offer = synchronized(lock) {
            if (!canUseClipboardLocked()) return false
            clipboard?.prepareOffer(text)
        } ?: return false
        return sendApplicationControl {
            codec.encodeClipboardOffer(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                offer,
            )
        }
    }

    fun requestClipboard(changeId: ByteArray): Boolean {
        val request = synchronized(lock) {
            if (!canUseClipboardLocked()) return false
            clipboard?.requestContent(changeId)
        } ?: return false
        return sendApplicationControl {
            codec.encodeClipboardRequest(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                request,
            )
        }
    }

    fun expireClipboardRequest(changeId: ByteArray): Boolean =
        synchronized(lock) {
            if (!canUseClipboardLocked()) return false
            clipboard?.expireRequest(changeId) == true
        }

    val canTransferFiles: Boolean
        get() = synchronized(lock) { canTransferFilesLocked() }

    val negotiatedMaxFileBytes: Long
        get() = synchronized(lock) { negotiatedFilePolicy.maximumFileBytes }

    fun offerFile(file: File, mimeType: String = "application/octet-stream"): Boolean =
        offerFileWithHandle(file, mimeType) != null

    internal fun offerFileWithHandle(
        file: File,
        mimeType: String = "application/octet-stream",
    ): OutgoingFileTransferHandle? {
        val prepared =
            when (
                val result = fileTransferProductOwner.prepareOutgoingFile(
                    file = file,
                    mimeType = mimeType,
                    negotiatedPolicy = synchronized(lock) { negotiatedFilePolicy },
                )
            ) {
                is FileTransferProductOwner.PrepareOutgoingResult.Prepared -> result.transfer
                is FileTransferProductOwner.PrepareOutgoingResult.Rejected -> {
                    fileTransferProductOwner.notifyFileTransferResult(
                        FileTransferProductOwner.TransferResult(accepted = false, reason = result.reasonCode),
                    )
                    return null
                }
            }
        val offer =
            when (val start = fileTransferProductOwner.startPreparedOutgoing(prepared, canTransferFiles)) {
                is FileTransferProductOwner.StartOutgoingResult.Started -> start.offer
                is FileTransferProductOwner.StartOutgoingResult.Rejected -> {
                    fileTransferProductOwner.notifyFileTransferResult(
                        FileTransferProductOwner.TransferResult(accepted = false, reason = start.reasonCode),
                    )
                    return null
                }
                is FileTransferProductOwner.StartOutgoingResult.Stale -> {
                    start.reasonCode?.let { reason ->
                        fileTransferProductOwner.notifyFileTransferResult(
                            FileTransferProductOwner.TransferResult(accepted = false, reason = reason),
                        )
                    }
                    return null
                }
            }
        val sent =
            sendApplicationControl {
                codec.encodeFileOffer(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, offer)
            }
        if (sent) {
            scheduleOutgoingFileTransferDeadline(offer.transferId)
        } else {
            clearOutgoingFileTransferDeadline(offer.transferId)
            fileTransferProductOwner.rejectOutgoingTransfer(offer.transferId, prepared, "outbound_backpressure")
                ?.let(fileTransferProductOwner::notifyFileTransferResult)
        }
        return if (sent) {
            OutgoingFileTransferHandle(
                transferId = offer.transferId,
                fileName = offer.fileName,
                byteLength = offer.byteLength,
            )
        } else {
            null
        }
    }

    fun respondToFileOffer(
        offer: FileOffer,
        accepted: Boolean,
        rejectionReason: String = "user_denied",
    ): Boolean {
        val owner = fileTransferProductOwner.claimFileOfferDecision(offer) ?: return false
        if (owner.ownerToken !== transportOwner || owner.connectionGeneration != transportOwner.generation) {
            fileTransferProductOwner.releaseFileOfferDecision(offer)
            return false
        }
        val response =
            fileTransferProductOwner.decideFileOffer(
                offer = offer,
                acceptedByUser = accepted,
                negotiatedPolicy = synchronized(lock) { negotiatedFilePolicy },
                sessionEpoch = lease.authoritativeSessionEpoch,
            ).let { decision ->
                if (accepted || decision.accepted || rejectionReason == "user_denied") {
                    decision
                } else {
                    decision.toBuilder().setRejectionReason(rejectionReason).build()
                }
            }
        return sendApplicationControl {
            codec.encodeFileAccept(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, response)
        }
    }

    fun cancelIncomingFileTransfer(
        transferId: ByteString,
        reasonCode: String = "user_cancelled",
    ): Boolean {
        fileTransferProductOwner.releaseFileOfferDecision(transferId)
        fileTransferProductOwner.cancelIncomingTransfer(transferId)
        val sent = sendApplicationControl {
            codec.encodeFileCancel(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, transferId, reasonCode)
        }
        if (sent) {
            fileTransferProductOwner.notifyIncomingFileCancelled(transferId, reasonCode)
            fileTransferProductOwner.notifyFileTransferResult(
                FileTransferProductOwner.TransferResult(accepted = false, reason = reasonCode),
            )
        }
        return sent
    }

    fun cancelOutgoingFileTransfer(
        transferId: ByteString,
        reasonCode: String = "user_cancelled",
    ): Boolean {
        clearOutgoingFileTransferDeadline(transferId)
        val result = fileTransferProductOwner.cancelOutgoingTransfer(transferId, reasonCode) ?: return false
        sendApplicationControl {
            codec.encodeFileCancel(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, transferId, reasonCode)
        }
        fileTransferProductOwner.notifyFileTransferResult(result)
        return true
    }

    fun sendPing(sequence: Long): Boolean =
        sendApplicationControl {
            codec.encodePing(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, sequence)
        }

    private fun canSendControllerLocked(): Boolean =
        acceptsTransportCallbackLocked() &&
            acceptedSession &&
            state == InternetProductSessionState.ACTIVE &&
            currentVideoConfiguration != null &&
            Capability.CAPABILITY_CONTROLLER in expectedNegotiatedCapabilities

    private fun canQueueControllerStructuralForRecoveryLocked(): Boolean =
        acceptsTransportCallbackLocked() &&
            acceptedSession &&
            state in CONTROLLER_STRUCTURAL_STATES &&
            currentVideoConfiguration != null &&
            Capability.CAPABILITY_CONTROLLER in expectedNegotiatedCapabilities

    private fun canUseClipboardLocked(owner: TransportOwner = transportOwner): Boolean =
        acceptsTransportCallbackLocked(owner) &&
            acceptedSession &&
            state == InternetProductSessionState.ACTIVE &&
            currentVideoConfiguration != null &&
            remoteManagedClipboardAllowed &&
            Capability.CAPABILITY_CLIPBOARD in expectedNegotiatedCapabilities &&
            clipboard != null

    private fun negotiatedClipboardLimit(hostAcceptedMaximum: Long): Long =
        if (Capability.CAPABILITY_CLIPBOARD !in expectedNegotiatedCapabilities) {
            0L
        } else {
            minOf(
                InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES,
                if (hostMaximumClipboardBytes > 0L) hostMaximumClipboardBytes else InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES,
                if (hostAcceptedMaximum > 0L) hostAcceptedMaximum else InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES,
            )
        }

    private fun drainControllerQueue(): Boolean {
        while (true) {
            val pendingDisconnect = controllerConnectionAcks.nextReadyDisconnect() ?: break
            val sent =
                try {
                    sendControllerEvent(
                        ProductControllerEvent(
                            ControllerStateSample(
                                controllerId = pendingDisconnect.connection.controllerId,
                                controllerEpoch = pendingDisconnect.connection.controllerEpoch,
                                kind = ControllerEventKind.DISCONNECTED,
                            ),
                        ),
                    )
                } catch (failure: Throwable) {
                    fail(failure)
                    return false
                }
            if (!sent) return false
        }
        val result =
            controllerSendQueue.drainSelectable(
                canSend = ::canSendControllerEvent,
                sharesOrderingKey = ::sharesControllerOrderingKey,
                send = ::sendAdmittedControllerEvent,
            )
        result.failure?.let { fail(it) }
        return !result.blocked && result.failure == null
    }

    private fun canSendControllerEvent(event: ProductControllerEvent): Boolean =
        !controllerConnectionAcks.hasDeferredDisconnectBefore(event.sample.controllerId, event.sample.controllerEpoch)

    private fun sharesControllerOrderingKey(
        first: ProductControllerEvent,
        second: ProductControllerEvent,
    ): Boolean = first.sample.controllerId == second.sample.controllerId

    private fun sendAdmittedControllerEvent(event: ProductControllerEvent): Boolean {
        if (controllerConnectionAcks.hasDeferredDisconnectFor(event.sample.controllerId, event.sample.controllerEpoch)) {
            return true
        }
        if (
            event.sample.kind == ControllerEventKind.CONNECTED &&
            controllerConnectionAcks.isPending(event.sample.controllerId, event.sample.controllerEpoch)
        ) {
            return true
        }
        if (event.sample.kind != ControllerEventKind.CONNECTED) {
            when (
                controllerConnectionAcks.consumePendingNonConnected(
                    event.sample.controllerId,
                    event.sample.controllerEpoch,
                    event.sample.kind,
                )
            ) {
                PendingControllerInputDisposition.NOT_PENDING -> Unit
                PendingControllerInputDisposition.CONSUMED_PENDING_STATE,
                PendingControllerInputDisposition.DEFERRED_PENDING_DISCONNECT,
                PendingControllerInputDisposition.DUPLICATE_PENDING_DISCONNECT,
                -> return true
            }
        }
        return sendControllerEvent(event)
    }

    private fun sendControllerEvent(event: ProductControllerEvent): Boolean {
        val streamId = synchronized(lock) { currentVideoConfiguration?.streamId } ?: return false
        val inputId = event.inputId ?: allocateControllerInputId()
        event.inputId?.let(::reserveControllerInputId)
        val encoded =
            codec.encodeController(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                streamId,
                inputId,
                event.sample,
            )
        val sent = sendOptionalApplicationControl(encoded)
        if (sent) {
            when (event.sample.kind) {
                ControllerEventKind.CONNECTED -> check(
                    controllerConnectionAcks.recordConnected(
                        inputId,
                        event.sample.controllerId,
                        event.sample.controllerEpoch,
                        clock.nowMillis(),
                    ),
                ) { "duplicate controller CONNECTED input id" }
                ControllerEventKind.DISCONNECTED -> {
                    controllerConnectionAcks.recordDisconnected(event.sample.controllerId, event.sample.controllerEpoch)
                }
                ControllerEventKind.STATE -> Unit
            }
        }
        return sent
    }

    private fun allocateControllerInputId(): Long {
        while (true) {
            val candidate = nextControllerInputId()
            val floor = minimumNextControllerInputId.get()
            val inputId = maxOf(candidate, floor)
            check(inputId > 0 && inputId < Long.MAX_VALUE) { "Controller input identifier exhausted" }
            if (minimumNextControllerInputId.compareAndSet(floor, inputId + 1)) return inputId
        }
    }

    private fun reserveControllerInputId(inputId: Long) {
        check(inputId < Long.MAX_VALUE) { "Controller input identifier exhausted" }
        while (true) {
            val floor = minimumNextControllerInputId.get()
            if (floor > inputId) return
            if (minimumNextControllerInputId.compareAndSet(floor, inputId + 1)) return
        }
    }

    private fun expirePendingControllerConnections() {
        controllerSendGate.withLock {
            val expired = controllerConnectionAcks.expirePendingConnections(clock.nowMillis())
            if (expired.isEmpty()) return
            controllerSendQueue.clear()
            controllerConnectionAcks.reset()
            fail(IllegalStateException("Controller input acknowledgement timed out"))
        }
    }

    private fun sendOptionalApplicationControl(payload: ByteArray): Boolean =
        synchronized(lock) {
            acceptsTransportCallbackLocked() &&
                acceptedSession &&
                state == InternetProductSessionState.ACTIVE &&
                transport.sendControl(payload)
        }

    override fun close() {
        val shouldClose =
            withLifecycleGate {
                synchronized(lock) {
                    if (closed) return
                    if (pendingRevocation?.durableBarrier == false) throw PendingRevocationBarrierException()
                    closed = true
                    invalidateTransportOwnerLocked()
                    true
                }
            }
        if (shouldClose) {
            runBestEffort(
                { stopAudioPlayback("session_close")?.let { throw it } },
                { transport.close() },
                { lease.close() },
                { transition(InternetProductSessionState.CLOSED) },
            )
        }
    }

    /** Retries the only fallible durable step while retaining the process admission reservation. */
    fun retryPendingRevocationBarrier(): String? {
        val reservation =
            withLifecycleGate {
                val current = synchronized(lock) { pendingRevocation }
                if (current == null || current.durableBarrier) return null
                try {
                    revocationStore.persistPendingAuthenticatedRevocation(lease.pairingIdentifier, current.reason)
                    revocationCoordinator.commit(current.coordinatorReservation)
                    synchronized(lock) { current.durableBarrier = true }
                    current
                } catch (_: Throwable) {
                    null
                }
            } ?: return null
        handleReservedRevocation(reservation, reservation.reason, notifyCallbacks = false)
        return reservation.reason
    }

    fun hasUndurableRevocationBarrier(): Boolean =
        synchronized(lock) { pendingRevocation?.durableBarrier == false }

    private fun handleTransportEvent(
        owner: TransportOwner,
        event: InternetTransportEvent,
    ) {
        if (synchronized(lock) { closed }) return
        when (event) {
            is InternetTransportEvent.StateChanged -> {
                when (event.state) {
                    InternetTransportState.CONNECTING -> transitionIfOwned(owner, InternetProductSessionState.CONNECTING)
                    InternetTransportState.RECOVERING -> transitionIfOwned(owner, InternetProductSessionState.RECOVERING)
                    InternetTransportState.SUSPENDED -> transitionIfOwned(owner, InternetProductSessionState.SUSPENDED)
                    InternetTransportState.CONNECTED_DIRECT,
                    InternetTransportState.CONNECTED_RELAY
                    -> resumeAuthenticatedSessionAfterTransportRecovery(owner)
                    InternetTransportState.CLOSED -> transitionIfOwned(owner, InternetProductSessionState.CLOSED)
                    else -> Unit
                }
            }
            is InternetTransportEvent.RouteSelected -> {
                notifyRouteIfOwned(owner, event.route)
                beginProtocolNegotiation(owner)
            }
            is InternetTransportEvent.RouteUpdated -> {
                notifyRouteIfOwned(owner, event.route)
            }
            is InternetTransportEvent.FreshSessionRequested -> {
                requestFreshSession(owner, event.reason)
            }
            is InternetTransportEvent.Failure -> failIfOwned(owner, event.error)
            is InternetTransportEvent.VideoProfileChanged -> Unit
        }
    }

    private fun beginProtocolNegotiation(owner: TransportOwner) {
        val shouldSend =
            synchronized(lock) {
                if (!acceptsTransportCallbackLocked(owner) || acceptedSession || negotiationStarted) {
                    false
                } else {
                    negotiationStarted = true
                    state = InternetProductSessionState.NEGOTIATING
                    true
                }
            }
        if (!shouldSend) return
        notifyStateIfOwned(owner, InternetProductSessionState.NEGOTIATING)
        sendRequiredControlIfOwned(
            owner,
            codec.encodeClientHello(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
            ),
        )
    }

    private fun handleControl(
        owner: TransportOwner,
        payload: ByteArray,
    ) {
        if (!synchronized(lock) { acceptsTransportCallbackLocked(owner) }) return
        val decoded =
            try {
                codec.decodeControl(payload)
            } catch (failure: Throwable) {
                failIfOwned(owner, IllegalArgumentException("Protocol v1 control message was rejected", failure))
                return
            }
        testHooks.afterControlDecodeBeforeCommit()
        val revocation = decoded.message as? ProductControlMessage.Revoked
        if (revocation != null) {
            val reservation = reserveAuthenticatedRevocation(owner, decoded, revocation.reasonCode) ?: return
            testHooks.afterRevocationReservedBeforePersist()
            handleReservedRevocation(reservation, revocation.reasonCode)
            return
        }
        val admissionFailure =
            synchronized(lock) {
                if (!acceptsTransportCallbackLocked(owner)) return
                if (!decoded.sessionId.contentEquals(lease.protocolSessionId) || decoded.sessionEpoch != lease.authoritativeSessionEpoch) {
                    IllegalArgumentException("Protocol v1 control routing metadata does not match the active session")
                } else if (decoded.messageId <= lastReceivedControlMessageId) {
                    IllegalArgumentException("Protocol v1 control message ID is not positive and monotonic")
                } else {
                    lastReceivedControlMessageId = decoded.messageId
                    null
                }
            }
        if (admissionFailure != null) {
            failIfOwned(owner, admissionFailure)
            return
        }
        when (val message = decoded.message) {
            is ProductControlMessage.HostHello -> handleHostHello(owner, message)
            is ProductControlMessage.SessionAccepted -> handleSessionAccepted(owner, message)
            is ProductControlMessage.SessionRejected -> {
                failIfOwned(owner, IllegalStateException("Session rejected (${message.reasonCode}); retryable=${message.retryable}"))
            }
            is ProductControlMessage.VideoConfiguration -> handleVideoConfiguration(owner, message.value)
            is ProductControlMessage.AudioConfiguration -> handleAudioConfiguration(owner, message.config)
            is ProductControlMessage.Pong -> notifyPongIfOwned(owner, message.sequence)
            is ProductControlMessage.InputAck -> notifyInputAckIfOwned(owner, message.inputId, message.accepted, message.rejectionReason)
            is ProductControlMessage.Ping -> {
                val response =
                    codec.encodePong(
                        nextMessageId(),
                        decoded.messageId,
                        lease.protocolSessionId,
                        lease.authoritativeSessionEpoch,
                        message.sequence,
                    )
                sendRequiredControlIfOwned(owner, response)
            }
            is ProductControlMessage.Disconnect -> requestFreshSessionIfAllowed(owner, message.reasonCode, message.mayResume)
            is ProductControlMessage.Revoked -> error("Revocation must be reserved during control admission")
            is ProductControlMessage.ClipboardOffered -> handleClipboardOffer(owner, message.offer)
            is ProductControlMessage.ClipboardRequested -> handleClipboardRequest(owner, decoded.messageId, message.request)
            is ProductControlMessage.ClipboardContentReceived -> handleClipboardContent(owner, message.content)
            is ProductControlMessage.ProtocolFailure -> {
                failIfOwned(owner, IllegalStateException("Protocol failure (${message.code}); retryable=${message.retryable}"))
            }
            is ProductControlMessage.FileOfferReceived -> handleFileOffer(owner, message.offer)
            is ProductControlMessage.FileAcceptReceived -> {
                clearOutgoingFileTransferDeadline(message.response.transferId)
                writeFileTransferUpdate(owner, fileTransferProductOwner.handleFileAccept(message.response, lease.authoritativeSessionEpoch))
            }
            is ProductControlMessage.FileProgressReceived -> {
                clearOutgoingFileTransferDeadline(message.progress.transferId)
                writeFileTransferUpdate(owner, fileTransferProductOwner.handleFileProgress(message.progress, lease.authoritativeSessionEpoch))
            }
            is ProductControlMessage.FileCancelReceived -> {
                clearOutgoingFileTransferDeadline(message.cancellation.transferId)
                fileTransferProductOwner.handleFileCancel(message.cancellation)
                    ?.let { result ->
                        fileTransferProductOwner.notifyIncomingFileCancelled(
                            message.cancellation.transferId,
                            message.cancellation.reasonCode,
                        )
                        fileTransferProductOwner.notifyFileTransferResult(result)
                    }
            }
            is ProductControlMessage.FileCompleteReceived -> {
                clearOutgoingFileTransferDeadline(message.result.transferId)
                writeFileTransferUpdate(owner, fileTransferProductOwner.handleFileComplete(message.result))
            }
            is ProductControlMessage.ManagedPolicyStatusReceived -> handleManagedPolicyStatus(owner, message.status)
            ProductControlMessage.Ignored -> Unit
        }
    }

    private fun reserveAuthenticatedRevocation(
        owner: TransportOwner,
        decoded: DecodedProductControl,
        reason: String,
    ): PendingRevocation? {
        var admissionFailure: Throwable? = null
        var durableFailure: Throwable? = null
        var pending: PendingRevocation? = null
        withLifecycleGate lifecycle@{
            synchronized(lock) {
                if (!acceptsTransportCallbackLocked(owner)) return@lifecycle
                admissionFailure =
                    when {
                        !decoded.sessionId.contentEquals(lease.protocolSessionId) ||
                            decoded.sessionEpoch != lease.authoritativeSessionEpoch ->
                            IllegalArgumentException("Protocol v1 control routing metadata does not match the active session")
                        decoded.messageId <= lastReceivedControlMessageId ->
                            IllegalArgumentException("Protocol v1 control message ID is not positive and monotonic")
                        else -> null
                    }
                if (admissionFailure == null) {
                    val coordinatorReservation =
                        try {
                            revocationCoordinator.reserve(lease.pairingIdentifier)
                        } catch (failure: Throwable) {
                            admissionFailure = failure
                            return@synchronized
                        }
                    pending = PendingRevocation(owner, coordinatorReservation, reason)
                    pendingRevocation = pending
                    lastReceivedControlMessageId = decoded.messageId
                    invalidateTransportOwnerLocked()
                }
            }
            val reservation = pending
            if (reservation != null) stopAudioPlayback("session_revoked")?.let(callbacks::onFailure)
            if (reservation != null) {
                try {
                    revocationStore.persistPendingAuthenticatedRevocation(lease.pairingIdentifier, reason)
                    revocationCoordinator.commit(reservation.coordinatorReservation)
                    synchronized(lock) { reservation.durableBarrier = true }
                } catch (failure: Throwable) {
                    durableFailure = IllegalStateException("Pending authenticated revocation could not be persisted", failure)
                    synchronized(lock) { state = InternetProductSessionState.FAILED }
                    callbacks.onStateChanged(InternetProductSessionState.FAILED)
                    callbacks.onFailure(requireNotNull(durableFailure))
                }
            }
        }
        if (durableFailure != null) return null
        admissionFailure?.let { failIfOwned(owner, it) }
        return pending
    }

    private fun handleHostHello(
        owner: TransportOwner,
        message: ProductControlMessage.HostHello,
    ) {
        val required = ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES.toSet()
        val expectedCapabilities = message.capabilities.intersect(codec.offeredCapabilities).filteredBy(managedPolicyResolver.effectivePolicy)
        if (!managedPolicyResolver.effectivePolicy.allowsHost(lease.pinnedHostId)) {
            failIfOwned(owner, IllegalArgumentException("Managed policy does not allow this host"))
            return
        }
        if (
            message.hostId != lease.pinnedHostId ||
            message.selectedProtocol != ProtobufProtocolV1ProductCodec.PROTOCOL_VERSION ||
            !message.capabilities.containsAll(required) ||
            !expectedCapabilities.containsAll(required) ||
            message.maximumEncryptedMediaRecordBytes <
            InternetMediaRecordContract.MINIMUM_NEGOTIATED_ENCRYPTED_RECORD_BYTES.toLong()
        ) {
            failIfOwned(
                owner,
                IllegalArgumentException("Host does not support the required Internet capabilities and media record limit"),
            )
            return
        }
        synchronized(lock) {
            if (acceptsTransportCallbackLocked(owner)) {
                acceptedHostHello = true
                expectedNegotiatedCapabilities = expectedCapabilities
                baseNegotiatedCapabilities = expectedCapabilities
                hostMaximumEncryptedMediaRecordBytes = message.maximumEncryptedMediaRecordBytes
                hostMaximumClipboardBytes = message.maximumClipboardBytes
                hostMaximumFileBytes = message.maximumFileBytes
                hostMaximumFileChunkBytes = message.maximumFileChunkBytes
            }
        }
    }

    private fun handleSessionAccepted(
        owner: TransportOwner,
        message: ProductControlMessage.SessionAccepted,
    ) {
        var invalidAcceptance = false
        var activated = false
        synchronized(lock) {
            if (!acceptsTransportCallbackLocked(owner)) return
            if (
                !acceptedHostHello ||
                !message.sessionId.contentEquals(lease.protocolSessionId) ||
                message.sessionEpoch != lease.authoritativeSessionEpoch ||
                message.capabilities != expectedNegotiatedCapabilities ||
                message.maximumEncryptedMediaRecordBytes != minOf(
                    hostMaximumEncryptedMediaRecordBytes,
                    InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES.toLong(),
                ) ||
                negotiatedClipboardLimit(message.maximumClipboardBytes) != message.maximumClipboardBytes ||
                message.maximumFileBytes != negotiatedFilePolicyFromHostLocked().maximumFileBytes ||
                message.maximumFileChunkBytes != negotiatedFilePolicyFromHostLocked().maximumChunkBytes ||
                message.heartbeatIntervalMillis !in MIN_HEARTBEAT_INTERVAL_MS..MAX_HEARTBEAT_INTERVAL_MS
            ) {
                invalidAcceptance = true
            } else {
                acceptedSession = true
                negotiatedMaximumEncryptedMediaRecordBytes = Math.toIntExact(message.maximumEncryptedMediaRecordBytes)
                negotiatedMaximumClipboardBytes = message.maximumClipboardBytes
                clipboard = if (Capability.CAPABILITY_CLIPBOARD in expectedNegotiatedCapabilities) {
                    InternetClipboard(
                        localDeviceId = codec.localDeviceId,
                        remoteDeviceId = lease.pinnedHostId,
                        maximumBytes = negotiatedMaximumClipboardBytes,
                    )
                } else {
                    null
                }
                negotiatedFilePolicy =
                    if (Capability.CAPABILITY_FILE_TRANSFER in expectedNegotiatedCapabilities) {
                        negotiatedFilePolicyFromHostLocked()
                    } else {
                        localFileTransferPolicy.copy(allowed = false, maximumFileBytes = 0L)
                    }
                heartbeatIntervalMillis = message.heartbeatIntervalMillis
                scheduleNextHeartbeatLocked()
                if (state != InternetProductSessionState.ACTIVE) {
                    state = InternetProductSessionState.ACTIVE
                    activated = true
                }
            }
        }
        if (invalidAcceptance) failIfOwned(owner, IllegalArgumentException("Session acceptance does not match the authenticated lease"))
        if (!invalidAcceptance) {
            clearAllOutgoingFileTransferDeadlines()
            if (synchronized(lock) { Capability.CAPABILITY_FILE_TRANSFER in expectedNegotiatedCapabilities }) {
                fileTransferProductOwner.activateSession()
            } else {
                fileTransferProductOwner.clear(reasonCode = "policy_denied")
            }
            if (Capability.CAPABILITY_MANAGED_CONFIGURATION in expectedNegotiatedCapabilities) {
                sendRequiredControlIfOwned(
                    owner,
                    codec.encodeManagedPolicyStatus(
                        nextMessageId(),
                        lease.protocolSessionId,
                        lease.authoritativeSessionEpoch,
                        managedPolicyResolver.effectivePolicy.toStatus(),
                    ),
                )
            }
        }
        if (activated) notifyStateIfOwned(owner, InternetProductSessionState.ACTIVE)
    }

    private fun negotiatedFilePolicyFromHostLocked(): FileTransferPolicy =
        localFileTransferPolicy.negotiated(
            ResourceLimits
                .newBuilder()
                .setMaximumFileBytes(hostMaximumFileBytes)
                .setMaximumFileChunkBytes(hostMaximumFileChunkBytes)
                .build(),
        )

    private fun canTransferFilesLocked(): Boolean =
        acceptsTransportCallbackLocked() &&
            acceptedSession &&
            state == InternetProductSessionState.ACTIVE &&
            Capability.CAPABILITY_FILE_TRANSFER in expectedNegotiatedCapabilities &&
            negotiatedFilePolicy.allowed &&
            negotiatedFilePolicy.maximumFileBytes > 0L

    private fun scheduleOutgoingFileTransferDeadline(transferId: ByteString) {
        synchronized(lock) {
            if (!canTransferFilesLocked()) return
            outgoingFileTransferDeadlines[transferId] =
                OutgoingFileTransferDeadline(
                    owner = transportOwner,
                    deadlineMillis = clock.nowMillis() + FILE_TRANSFER_PROGRESS_TIMEOUT_MS,
                )
        }
    }

    private fun clearOutgoingFileTransferDeadline(transferId: ByteString) {
        synchronized(lock) { outgoingFileTransferDeadlines.remove(transferId) }
    }

    private fun clearAllOutgoingFileTransferDeadlines() {
        synchronized(lock) { outgoingFileTransferDeadlines.clear() }
    }

    private fun expireOutgoingFileTransfers() {
        val expired =
            synchronized(lock) {
                if (!acceptsTransportCallbackLocked() || !acceptedSession || state != InternetProductSessionState.ACTIVE) {
                    emptyList()
                } else {
                    val now = clock.nowMillis()
                    outgoingFileTransferDeadlines
                        .filter { (_, deadline) ->
                            deadline.owner === transportOwner &&
                                deadline.deadlineMillis <= now
                        }.map { it.key }
                }
            }
        expired.forEach { transferId ->
            val shouldTimeout =
                synchronized(lock) {
                    val deadline = outgoingFileTransferDeadlines[transferId] ?: return@forEach
                    if (
                        deadline.owner !== transportOwner ||
                        deadline.deadlineMillis > clock.nowMillis() ||
                        !acceptsTransportCallbackLocked() ||
                        !acceptedSession ||
                        state != InternetProductSessionState.ACTIVE
                    ) {
                        false
                    } else {
                        outgoingFileTransferDeadlines.remove(transferId)
                        true
                    }
                }
            if (!shouldTimeout) return@forEach
            val update =
                fileTransferProductOwner.timeoutOutgoingTransfer(transferId)
            writeFileTransferUpdate(transportOwner, update)
        }
    }

    private fun resumeAuthenticatedSessionAfterTransportRecovery(owner: TransportOwner) {
        val shouldResume =
            synchronized(lock) {
                if (
                    !acceptsTransportCallbackLocked(owner) ||
                    !acceptedSession ||
                    !negotiationStarted ||
                    state !in setOf(InternetProductSessionState.RECOVERING, InternetProductSessionState.SUSPENDED)
                ) {
                    false
                } else {
                    scheduleNextHeartbeatLocked()
                    state = InternetProductSessionState.ACTIVE
                    true
                }
            }
        if (shouldResume) {
            controllerSendGate.withLock { drainControllerQueue() }
            notifyStateIfOwned(owner, InternetProductSessionState.ACTIVE)
        }
    }

    private fun heartbeatTick() {
        val sequence =
            synchronized(lock) {
                if (closed || state != InternetProductSessionState.ACTIVE || clock.nowMillis() < nextHeartbeatAtMillis) {
                    null
                } else {
                    val value = nextHeartbeatSequence++
                    scheduleNextHeartbeatLocked()
                    value
                }
            } ?: return
        sendPing(sequence)
    }

    private fun scheduleNextHeartbeatLocked() {
        nextHeartbeatAtMillis = clock.nowMillis() + heartbeatIntervalMillis
    }

    private fun handleVideoConfiguration(
        owner: TransportOwner,
        configuration: ProductVideoConfiguration,
    ) {
        var validationFailure: Throwable? = null
        val reservation =
            PendingVideoConfiguration(
                configEpoch = configuration.configEpoch,
                owner = owner,
                deadlineMillis = clock.nowMillis() + VIDEO_CONFIGURATION_TIMEOUT_MS,
            )
        val reservationEpoch =
            synchronized(lock) {
                if (!acceptsTransportCallbackLocked(owner)) return
                val currentEpoch = currentVideoConfiguration?.configEpoch ?: 0
                if (!acceptedSession) {
                    validationFailure = IllegalStateException("Video configuration arrived before session acceptance")
                } else if (configuration.configEpoch <= currentEpoch) {
                    validationFailure = IllegalArgumentException("Video configuration epoch did not increase")
                } else if (pendingVideoConfiguration != null) {
                    validationFailure = IllegalStateException("Concurrent video configuration transaction was rejected")
                } else {
                    pendingVideoConfiguration = reservation
                }
                currentEpoch
            }
        validationFailure?.let {
            failIfOwned(owner, it)
            return
        }
        val completed = java.util.concurrent.atomic.AtomicBoolean(false)
        val effect =
            ProductVideoConfigurationEffect { install ->
                videoEffectGate.withLock {
                    if (!isVideoConfigurationReservationActive(owner, reservation, reservationEpoch)) {
                        ProductVideoDecision.reject("stale_session")
                    } else {
                        install().also { decision ->
                            if (decision.accepted) {
                                synchronized(lock) {
                                    if (isVideoConfigurationReservationActiveLocked(owner, reservation, reservationEpoch)) {
                                        reservation.effectCommitted = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        withLifecycleGate {
            if (!isVideoConfigurationReservationActive(owner, reservation, reservationEpoch)) return
            try {
                callbacks.onVideoConfiguration(configuration, effect) { decision ->
                    if (completed.compareAndSet(false, true)) {
                        completeVideoConfiguration(owner, reservation, reservationEpoch, configuration, decision)
                    }
                }
            } catch (failure: Throwable) {
                if (completed.compareAndSet(false, true)) {
                    notifyFailureIfOwned(owner, failure)
                    completeVideoConfiguration(
                        owner,
                        reservation,
                        reservationEpoch,
                        configuration,
                        ProductVideoDecision.reject("decoder_configuration_failure"),
                    )
                }
            }
        }
    }

    private fun completeVideoConfiguration(
        owner: TransportOwner,
        reservation: PendingVideoConfiguration,
        reservationEpoch: Long,
        configuration: ProductVideoConfiguration,
        decision: ProductVideoDecision,
    ) {
        withLifecycleGate {
            if (!isVideoConfigurationReservationActive(owner, reservation, reservationEpoch)) return
            val effectiveDecision =
                if (decision.accepted && !reservation.effectCommitted) {
                    ProductVideoDecision.reject("decoder_effect_not_committed")
                } else {
                    decision
                }
            val response =
                codec.encodeVideoConfigResult(
                    nextMessageId(),
                    lease.protocolSessionId,
                    lease.authoritativeSessionEpoch,
                    configuration,
                    effectiveDecision.accepted,
                    effectiveDecision.rejectionReason,
                )
            var sendFailed = false
            var appliedConfiguration: ProductVideoConfiguration? = null
            synchronized(lock) {
                if (!isVideoConfigurationReservationActiveLocked(owner, reservation, reservationEpoch)) return
                pendingVideoConfiguration = null
                if (!transport.sendControl(response)) {
                    sendFailed = true
                } else if (effectiveDecision.accepted) {
                    currentVideoConfiguration = configuration
                    frameAssembler.startConfiguration(configuration, lease.authoritativeSessionEpoch)
                    appliedConfiguration = configuration
                }
            }
            if (sendFailed) {
                failIfOwned(owner, IllegalStateException("Required Protocol v1 control message could not be queued"))
            } else if (!effectiveDecision.accepted &&
                effectiveDecision.rejectionReason == STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON
            ) {
                failIfOwned(
                    owner,
                    IllegalStateException("Decoder rejected the active HEVC target"),
                )
            } else {
                appliedConfiguration?.let(callbacks::onVideoConfigurationApplied)
            }
            Unit
        }
    }

    private fun handleAudioConfiguration(
        owner: TransportOwner,
        config: AudioConfig,
    ) {
        val playback = audioPlayback
        var validationFailure: Throwable? = null
        var configurationRejectionReason: String? = null
        var idempotentAcceptedConfiguration = false
        val shouldConfigure =
            synchronized(lock) {
                if (!acceptsTransportCallbackLocked(owner)) return
                val currentEpoch = currentAudioConfiguration?.configEpoch ?: 0L
                when {
                    !acceptedSession || state != InternetProductSessionState.ACTIVE || currentVideoConfiguration == null -> {
                        validationFailure = IllegalStateException("Audio configuration arrived before active video streaming")
                        false
                    }
                    Capability.CAPABILITY_AUDIO !in expectedNegotiatedCapabilities -> {
                        validationFailure = IllegalStateException("Audio configuration arrived without a negotiated audio session")
                        false
                    }
                    playback == null || !playback.canAdvertiseAudio -> {
                        validationFailure = IllegalStateException("Audio playback is unavailable for a negotiated audio session")
                        false
                    }
                    config.streamId <= 0L || config.configEpoch <= 0L -> {
                        configurationRejectionReason = "invalid_audio_config_epoch"
                        false
                    }
                    config.configEpoch <= currentEpoch -> {
                        if (audioPlaybackConfigured && currentAudioConfiguration == config) {
                            idempotentAcceptedConfiguration = true
                        } else {
                            configurationRejectionReason = "invalid_audio_config_epoch"
                        }
                        false
                    }
                    else -> true
                }
            }
        validationFailure?.let {
            failIfOwned(owner, it)
            return
        }
        if (idempotentAcceptedConfiguration) {
            val response =
                codec.encodeAudioConfigResult(
                    nextMessageId(),
                    lease.protocolSessionId,
                    lease.authoritativeSessionEpoch,
                    config,
                    accepted = true,
                    rejectionReason = "",
                )
            val sendFailed =
                synchronized(lock) {
                    acceptsTransportCallbackLocked(owner) && !transport.sendControl(response)
                }
            if (sendFailed) {
                failIfOwned(owner, IllegalStateException("Required Protocol v1 audio configuration result could not be queued"))
            }
            return
        }
        configurationRejectionReason?.let { reason ->
            val response =
                codec.encodeAudioConfigResult(
                    nextMessageId(),
                    lease.protocolSessionId,
                    lease.authoritativeSessionEpoch,
                    config,
                    accepted = false,
                    rejectionReason = reason,
                )
            val sendFailed =
                synchronized(lock) {
                    acceptsTransportCallbackLocked(owner) && !transport.sendControl(response)
                }
            if (sendFailed) {
                failIfOwned(owner, IllegalStateException("Required Protocol v1 audio configuration result could not be queued"))
            }
            return
        }
        if (!shouldConfigure || playback == null) return

        val decision =
            try {
                playback.configure(config, lease.authoritativeSessionEpoch)
            } catch (_: Throwable) {
                InternetAudioDecision.reject("audio_playback_configuration_failed")
            }
        val response =
            codec.encodeAudioConfigResult(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                config,
                decision.accepted,
                decision.rejectionReason,
            )
        var sendFailed = false
        var staleAfterConfigure = false
        synchronized(lock) {
            if (!acceptsTransportCallbackLocked(owner) || !acceptedSession || state != InternetProductSessionState.ACTIVE) {
                staleAfterConfigure = true
                return@synchronized
            }
            if (!transport.sendControl(response)) {
                sendFailed = true
            } else if (decision.accepted) {
                currentAudioConfiguration = config
                audioPlaybackConfigured = true
            } else {
                currentAudioConfiguration = null
                audioPlaybackConfigured = false
            }
        }
        if (staleAfterConfigure && decision.accepted) {
            stopAudioPlayback("stale_audio_configuration")?.let { failIfOwned(owner, it) }
        }
        if (sendFailed) {
            val failure = IllegalStateException("Required Protocol v1 audio configuration result could not be queued")
            if (decision.accepted) stopAudioPlayback("audio_config_result_send_failed")?.let(failure::addSuppressed)
            failIfOwned(owner, failure)
        } else if (!decision.accepted) {
            stopAudioPlayback("audio_configuration_rejected")?.let { failIfOwned(owner, it) }
        }
    }

    private fun isVideoConfigurationReservationActive(
        owner: TransportOwner,
        reservation: PendingVideoConfiguration,
        reservationEpoch: Long,
    ): Boolean = synchronized(lock) { isVideoConfigurationReservationActiveLocked(owner, reservation, reservationEpoch) }

    private fun isVideoConfigurationReservationActiveLocked(
        owner: TransportOwner,
        reservation: PendingVideoConfiguration,
        reservationEpoch: Long,
    ): Boolean =
        acceptsTransportCallbackLocked(owner) &&
            acceptedSession &&
            pendingVideoConfiguration === reservation &&
            (currentVideoConfiguration?.configEpoch ?: 0) == reservationEpoch

    private fun expirePendingVideoConfiguration() {
        var expiredOwner: TransportOwner? = null
        withLifecycleGate {
            synchronized(lock) {
                val pending = pendingVideoConfiguration ?: return@synchronized
                if (clock.nowMillis() >= pending.deadlineMillis) {
                    pendingVideoConfiguration = null
                    expiredOwner = pending.owner
                }
            }
            expiredOwner?.let { owner ->
                failIfOwned(owner, IllegalStateException("Video configuration transaction timed out"))
            }
        }
    }

    private fun expirePendingMediaFrame() {
        val result =
            synchronized(lock) {
                if (!acceptedSession || currentVideoConfiguration == null) {
                    ProductMediaAssemblyResult.Pending
                } else {
                    frameAssembler.expire()
                }
            }
        if (result is ProductMediaAssemblyResult.KeyframeRequired) {
            requestKeyframe(result.reason)
        }
    }

    private fun handleMedia(
        owner: TransportOwner,
        payload: ByteArray,
    ) {
        val configuration =
            synchronized(lock) {
                if (!acceptsTransportCallbackLocked(owner) || !acceptedSession) return
                currentVideoConfiguration
            } ?: return
        val fragment =
            try {
                val maximumPlaintextRecordBytes =
                    synchronized(lock) {
                        negotiatedMaximumEncryptedMediaRecordBytes -
                            InternetMediaRecordContract.APPLICATION_AEAD_RECORD_OVERHEAD_BYTES
                    }
                require(payload.size <= maximumPlaintextRecordBytes) {
                    "Protocol v1 media record exceeds the negotiated session limit"
                }
                codec.decodeMediaFragment(payload)
            } catch (failure: Throwable) {
                requestKeyframe(MEDIA_KEYFRAME_REASON_INVALID_FRAGMENT)
                failIfOwned(owner, IllegalArgumentException("Protocol v1 media packet was rejected", failure))
                return
            }
        testHooks.afterMediaDecodeBeforeCommit()
        val assemblyResult =
            synchronized(lock) {
                if (
                    !acceptsTransportCallbackLocked(owner) ||
                    !acceptedSession ||
                    currentVideoConfiguration != configuration
                ) {
                    return
                }
                frameAssembler.offer(fragment)
            }
        val frame =
            when (assemblyResult) {
                ProductMediaAssemblyResult.Pending -> return
                is ProductMediaAssemblyResult.KeyframeRequired -> {
                    requestKeyframe(assemblyResult.reason)
                    return
                }
                is ProductMediaAssemblyResult.FrameReady -> assemblyResult.frame
            }
        testHooks.beforeMediaDispatchGate()
        withLifecycleGate {
            if (synchronized(lock) { acceptsTransportCallbackLocked(owner) && acceptedSession && currentVideoConfiguration == configuration }) {
                callbacks.onVideoFrame(frame)
            }
        }
    }

    private fun handleAudioRecord(
        owner: TransportOwner,
        payload: ByteArray,
    ) {
        val route = currentAudioRecordRoute()
        val streamId = route.streamId
        if (streamId <= 0) return
        var playbackFailure: String? = null
        handleAdvancedRecord(owner, payload, AdvancedChannelBinding.Audio(INTERNET_DISPLAY_ID, streamId)) { record ->
            if (route.productPlayback) {
                val decision =
                    try {
                        audioPlayback?.submit(record) ?: InternetAudioDecision.reject("audio_playback_unavailable")
                    } catch (_: Throwable) {
                        InternetAudioDecision.reject("audio_playback_submit_failed")
                    }
                if (!decision.accepted) playbackFailure = decision.rejectionReason
            } else {
                callbacks.onAudioRecord(record.copyOf())
            }
        }
        playbackFailure?.let { reason ->
            val failure = IllegalArgumentException("Protocol v1 audio record was rejected: $reason")
            stopAudioPlayback(reason)?.let(failure::addSuppressed)
            failIfOwned(owner, failure)
        }
    }

    private fun handleBulkRecord(
        owner: TransportOwner,
        payload: ByteArray,
    ) {
        val transferId = peekFileChunkTransferId(payload)
        if (transferId == null) {
            handleAdvancedRecord(owner, payload, AdvancedChannelBinding.Bulk(DEFAULT_BULK_TRANSFER_ID)) { record ->
                callbacks.onBulkRecord(record.copyOf())
            }
            return
        }
        handleAdvancedRecord(owner, payload, AdvancedChannelBinding.Bulk(transferId.toByteArray())) { record ->
            when (val decoded = decodeFileChunk(record, transferId)) {
                is FileChunkDecodeResult.Valid -> {
                    val negotiated = synchronized(lock) { canTransferFilesLocked() }
                    when {
                        !negotiated -> rejectInvalidFileChunk(owner, decoded.chunk.header.transferId, "policy_denied")
                        !fileTransferProductOwner.isActiveIncomingTransfer(decoded.chunk.header.transferId) ->
                            rejectInvalidFileChunk(owner, decoded.chunk.header.transferId, "unknown_transfer", notifyResult = false)
                        else -> handleIncomingFileChunk(owner, decoded.chunk)
                    }
                }
                is FileChunkDecodeResult.Invalid -> {
                    if (fileTransferProductOwner.isPendingOrActiveIncomingTransfer(decoded.transferId)) {
                        rejectInvalidFileChunk(owner, decoded.transferId, decoded.reasonCode)
                    } else {
                        callbacks.onBulkRecord(record.copyOf())
                    }
                }
            }
        }
    }

    private fun handleClipboardOffer(
        owner: TransportOwner,
        offer: dev.vibescreen.protocol.v1.ClipboardOffer,
    ) {
        var validationFailure: Throwable? = null
        val result =
            synchronized(lock) {
                clipboardInboundFailureLocked(owner)?.let { failure ->
                    validationFailure = failure
                    return@synchronized null
                }
                try {
                    clipboard?.handleOffer(offer) ?: error("Clipboard was not negotiated")
                } catch (failure: Throwable) {
                    validationFailure = failure
                    null
                }
            } ?: run {
                validationFailure?.let {
                    failIfOwned(owner, IllegalArgumentException("Protocol v1 clipboard offer was rejected", it))
                }
                return
            }
        withLifecycleGate {
            if (synchronized(lock) { canUseClipboardLocked(owner) }) callbacks.onClipboardOffered(result)
        }
    }

    private fun handleClipboardRequest(
        owner: TransportOwner,
        correlationId: Long,
        request: dev.vibescreen.protocol.v1.ClipboardRequest,
    ) {
        var validationFailure: Throwable? = null
        val content =
            synchronized(lock) {
                clipboardInboundFailureLocked(owner)?.let { failure ->
                    validationFailure = failure
                    return@synchronized null
                }
                try {
                    clipboard?.makeContent(request) ?: return
                } catch (failure: Throwable) {
                    validationFailure = failure
                    null
                }
            } ?: run {
                validationFailure?.let {
                    failIfOwned(owner, IllegalArgumentException("Protocol v1 clipboard request was rejected", it))
                }
                return
            }
        sendRequiredControlIfOwned(
            owner,
            codec.encodeClipboardContent(
                nextMessageId(),
                correlationId,
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                content,
            ),
        )
    }

    private fun handleClipboardContent(
        owner: TransportOwner,
        content: dev.vibescreen.protocol.v1.ClipboardContent,
    ) {
        var validationFailure: Throwable? = null
        val result =
            synchronized(lock) {
                clipboardInboundFailureLocked(owner)?.let { failure ->
                    validationFailure = failure
                    return@synchronized null
                }
                try {
                    clipboard?.handleContent(content) ?: error("Clipboard was not negotiated")
                } catch (failure: Throwable) {
                    validationFailure = failure
                    null
                }
            } ?: run {
                validationFailure?.let {
                    failIfOwned(owner, IllegalArgumentException("Protocol v1 clipboard content was rejected", it))
                }
                return
            }
        withLifecycleGate {
            if (synchronized(lock) { canUseClipboardLocked(owner) }) callbacks.onClipboardContent(result)
        }
    }

    private fun peekFileChunkTransferId(payload: ByteArray): ByteString? {
        val header =
            try {
                ProtocolV1Framing.peekFileChunkHeader(payload)
            } catch (_: Throwable) {
                return null
            }
        return header.transferId.takeUnless { it.isEmpty }
    }

    private fun decodeFileChunk(payload: ByteArray, transferId: ByteString): FileChunkDecodeResult =
        try {
            FileChunkDecodeResult.Valid(FileChunk.fromFrame(payload))
        } catch (failure: FileTransferException) {
            FileChunkDecodeResult.Invalid(transferId, failure.reasonCode)
        } catch (_: IOException) {
            FileChunkDecodeResult.Invalid(transferId, "invalid_file_payload")
        } catch (_: Throwable) {
            FileChunkDecodeResult.Invalid(transferId, "invalid_file_payload")
        }

    private fun rejectInvalidFileChunk(
        owner: TransportOwner,
        transferId: ByteString,
        reasonCode: String,
        notifyResult: Boolean = true,
    ) {
        fileTransferProductOwner.releaseFileOfferDecision(transferId)
        fileTransferProductOwner.cancelIncomingTransfer(transferId)
        sendRequiredControlIfOwned(
            owner,
            codec.encodeFileCancel(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, transferId, reasonCode),
        )
        if (notifyResult) {
            fileTransferProductOwner.notifyFileTransferResult(
                FileTransferProductOwner.TransferResult(accepted = false, reason = reasonCode),
            )
        }
    }

    private fun handleFileOffer(
        owner: TransportOwner,
        offer: FileOffer,
    ) {
        if (synchronized(lock) { !canTransferFilesLocked() }) {
            sendFileAccept(
                fileTransferProductOwner.decideFileOffer(
                    offer = offer,
                    acceptedByUser = false,
                    negotiatedPolicy = synchronized(lock) { negotiatedFilePolicy },
                    sessionEpoch = lease.authoritativeSessionEpoch,
                ),
            )
            return
        }
        val response =
            fileTransferProductOwner.receiveFileOffer(
                ownerToken = owner,
                connectionGeneration = owner.generation,
                offer = offer,
                negotiatedPolicy = synchronized(lock) { negotiatedFilePolicy },
            )
        response?.let(::sendFileAccept)
    }

    private fun handleManagedPolicyStatus(
        owner: TransportOwner,
        status: ManagedPolicyStatus,
    ) {
        var validationFailure: Throwable? = null
        var shouldStopAudio = false
        val notifyStatus =
            synchronized(lock) {
                if (!acceptsTransportCallbackLocked(owner) || !acceptedSession) return
                if (Capability.CAPABILITY_MANAGED_CONFIGURATION !in baseNegotiatedCapabilities) {
                    validationFailure = IllegalArgumentException("ManagedPolicyStatus arrived without negotiated managed configuration")
                    return@synchronized null
                }
                if (!InternetManagedPolicy.hasCompleteRestrictionResults(status)) {
                    validationFailure = IllegalArgumentException("ManagedPolicyStatus requires complete, consistent restriction_results")
                    return@synchronized null
                }
                val remotePolicy = InternetManagedPolicy.fromStatus(status)
                managedPolicyResolver.setRemote(remotePolicy)
                val effective = managedPolicyResolver.effectivePolicy
                if (!effective.allowsHost(lease.pinnedHostId)) {
                    validationFailure = IllegalArgumentException("Managed policy does not allow this host")
                    return@synchronized null
                }
                remoteManagedClipboardAllowed = effective.clipboardAllowed
                val hadAudioState =
                    audioPlaybackConfigured &&
                        currentAudioConfiguration != null &&
                        Capability.CAPABILITY_AUDIO in expectedNegotiatedCapabilities
                expectedNegotiatedCapabilities = baseNegotiatedCapabilities.filteredBy(effective)
                shouldStopAudio = hadAudioState && Capability.CAPABILITY_AUDIO !in expectedNegotiatedCapabilities
                if (!remoteManagedClipboardAllowed) clipboard?.reset()
                // Apply managed policy to file transfer
                fileTransferProductOwner.applyManagedPolicy(status)
                negotiatedFilePolicy =
                    if (Capability.CAPABILITY_FILE_TRANSFER in expectedNegotiatedCapabilities) {
                        negotiatedFilePolicyFromHostLocked().applying(RemoteManagedPolicy(status))
                    } else {
                        localFileTransferPolicy.copy(allowed = false, maximumFileBytes = 0L)
                    }
                if (!negotiatedFilePolicy.allowed || negotiatedFilePolicy.maximumFileBytes <= 0L) {
                    outgoingFileTransferDeadlines.clear()
                }
                effective.toStatus()
            } ?: run {
                validationFailure?.let { failIfOwned(owner, it) }
                return
            }
        if (shouldStopAudio) {
            stopAudioPlayback("managed_policy_audio_denied")?.let { failIfOwned(owner, it) }
        }
        withLifecycleGate {
            if (synchronized(lock) { acceptsTransportCallbackLocked(owner) && acceptedSession }) {
                callbacks.onManagedPolicyReceived(notifyStatus)
            }
        }
    }

    private fun clipboardInboundFailureLocked(owner: TransportOwner): Throwable? {
        if (!acceptsTransportCallbackLocked(owner)) return null
        if (!acceptedSession || state != InternetProductSessionState.ACTIVE || currentVideoConfiguration == null) {
            return IllegalStateException("Clipboard message arrived before the Internet product session was active")
        }
        if (Capability.CAPABILITY_CLIPBOARD !in expectedNegotiatedCapabilities || clipboard == null) {
            return IllegalStateException("Clipboard message arrived without negotiated clipboard capability")
        }
        if (!remoteManagedClipboardAllowed) {
            return IllegalStateException("Clipboard message was denied by managed policy")
        }
        return null
    }

    private fun handleIncomingFileChunk(
        owner: TransportOwner,
        chunk: FileChunk,
    ) {
        val result =
            fileTransferProductOwner.receiveIncomingChunk(
                chunk = chunk,
                canTransferFiles = synchronized(lock) { canTransferFilesLocked() },
                sessionEpoch = lease.authoritativeSessionEpoch,
            )
        when (result) {
            is FileTransferProductOwner.IncomingChunkResult.Accepted -> {
                sendFileProgress(result.transferId, result.receivedBytes)
                fileTransferProductOwner.notifyIncomingFileProgress(result.transferId, result.receivedBytes)
                result.completed?.let { completed ->
                    sendFileComplete(completed.transferId, accepted = true, sha256 = completed.sha256, rejectionReason = "")
                    fileTransferProductOwner.notifyIncomingFileCompleted(completed)
                }
            }
            is FileTransferProductOwner.IncomingChunkResult.Rejected -> {
                result.receivedBytes?.let { received -> sendFileProgress(result.transferId, received) }
                sendFileCancel(result.transferId, result.reasonCode)
                fileTransferProductOwner.notifyIncomingFileCancelled(result.transferId, result.reasonCode)
                if (result.failure != null && result.reasonCode == "io_failure") {
                    failIfOwned(owner, result.failure)
                }
            }
        }
    }

    private fun writeFileTransferUpdate(
        owner: TransportOwner,
        update: FileTransferProductOwner.OutgoingUpdate,
    ) {
        update.chunk?.let { chunk ->
            val sent = sendFileTransferBulkRecord(chunk.toFrame(), chunk.header.transferId)
            if (!sent) {
                notifyOutgoingBulkSendFailure(owner, chunk.header.transferId, fileTransferProductOwner.handleBulkSendFailed(chunk.header.transferId))
                return
            }
            scheduleOutgoingFileTransferDeadline(chunk.header.transferId)
        }
        update.waitingForPeerTransferId?.let(::scheduleOutgoingFileTransferDeadline)
        if (update.cancelTransferId != null && update.cancelReasonCode != null) {
            clearOutgoingFileTransferDeadline(update.cancelTransferId)
            sendFileCancel(update.cancelTransferId, update.cancelReasonCode)
        }
        update.result?.let(fileTransferProductOwner::notifyFileTransferResult)
    }

    private fun sendFileTransferBulkRecord(payload: ByteArray, transferId: ByteString): Boolean =
        sendAdvancedRecord(
            payload = payload,
            binding = AdvancedChannelBinding.Bulk(transferId.toByteArray()),
            failOnBacklogRejection = false,
        ) {
            transport.sendBulkRecord(payload)
        }

    private fun notifyOutgoingBulkSendFailure(
        owner: TransportOwner,
        transferId: ByteString,
        update: FileTransferProductOwner.OutgoingUpdate,
    ) {
        val result = update.result ?: return
        clearOutgoingFileTransferDeadline(update.cancelTransferId ?: transferId)
        sendRequiredControlIfOwned(
            owner,
            codec.encodeFileCancel(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                update.cancelTransferId ?: transferId,
                update.cancelReasonCode ?: "bulk_send_failed",
            ),
        )
        fileTransferProductOwner.notifyFileTransferResult(result)
    }

    private fun sendFileAccept(response: dev.vibescreen.protocol.v1.FileAccept): Boolean =
        sendApplicationControl {
            codec.encodeFileAccept(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, response)
        }

    private fun sendFileProgress(transferId: ByteString, receivedBytes: Long): Boolean =
        sendApplicationControl {
            codec.encodeFileProgress(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, transferId, receivedBytes)
        }

    private fun sendFileCancel(transferId: ByteString, reasonCode: String): Boolean =
        sendApplicationControl {
            codec.encodeFileCancel(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, transferId, reasonCode)
        }

    private fun sendFileComplete(
        transferId: ByteString,
        accepted: Boolean,
        sha256: ByteString,
        rejectionReason: String,
    ): Boolean =
        sendApplicationControl {
            codec.encodeFileComplete(
                nextMessageId(),
                lease.protocolSessionId,
                lease.authoritativeSessionEpoch,
                transferId,
                accepted,
                sha256,
                rejectionReason,
            )
        }

    private fun handleAdvancedRecord(
        owner: TransportOwner,
        payload: ByteArray,
        binding: AdvancedChannelBinding,
        deliver: (ByteArray) -> Unit,
    ) {
        var admissionFailure: Throwable? = null
        val admission =
            synchronized(lock) {
                if (!acceptsTransportCallbackLocked(owner) || !acceptedSession || state != InternetProductSessionState.ACTIVE) {
                    return
                }
                try {
                    advancedChannelGate.reserve(payload.size, binding, advancedChannelOwner(owner))
                } catch (failure: Throwable) {
                    admissionFailure = failure
                    null
                }
            } ?: run {
                failIfOwned(owner, IllegalArgumentException("Protocol v1 advanced channel record was rejected", admissionFailure))
                return
            }
        withLifecycleGate {
            try {
                if (synchronized(lock) { acceptsTransportCallbackLocked(owner) && acceptedSession && state == InternetProductSessionState.ACTIVE }) {
                    deliver(payload)
                }
            } finally {
                finishAdvancedAdmission(admission)
            }
        }
    }

    private fun requestFreshSessionIfAllowed(
        owner: TransportOwner,
        reason: String,
        mayResume: Boolean,
    ) {
        if (!mayResume) {
            failIfOwned(owner, IllegalStateException("Host ended the Internet session: $reason"))
            return
        }
        requestFreshSession(owner, reason)
    }

    private fun requestFreshSession(
        owner: TransportOwner,
        reason: String,
    ) {
        var closeTransport = false
        withLifecycleGate {
            var stateChanged = false
            val reserved =
                synchronized(lock) {
                    if (!acceptsTransportCallbackLocked(owner)) {
                        false
                    } else {
                        stateChanged = state != InternetProductSessionState.RECOVERING
                        freshSessionRequested = true
                        closeTransport = true
                        invalidateTransportOwnerLocked()
                        state = InternetProductSessionState.RECOVERING
                        true
                    }
            }
            if (!reserved) return
            stopAudioPlayback("fresh_session_required")?.let(callbacks::onFailure)
            if (stateChanged) callbacks.onStateChanged(InternetProductSessionState.RECOVERING)
            if (closeTransport) transport.close()
            if (synchronized(lock) { !closed && freshSessionRequested && state == InternetProductSessionState.RECOVERING }) {
                callbacks.onFreshSessionRequired(reason)
            }
        }
    }

    private fun handleReservedRevocation(
        reservation: PendingRevocation,
        reason: String,
        notifyCallbacks: Boolean = true,
    ) {
        var persistenceFailure: Throwable? = null
        try {
            revocationStore.persistAuthenticatedRevocation(lease.pairingIdentifier, reason)
            testHooks.afterRevocationPersistBeforeCommit()
        } catch (failure: Throwable) {
            persistenceFailure = IllegalStateException("Authenticated revocation could not be persisted", failure)
        }
        val notify =
            withLifecycleGate {
                synchronized(lock) {
                    if (pendingRevocation !== reservation) {
                        false
                    } else {
                        pendingRevocation = null
                        if (!closed) state = InternetProductSessionState.FAILED
                        !closed
                    }
                }
            }
        if (notify && notifyCallbacks) testHooks.afterRevocationStateCommitBeforeCallback()
        runBestEffort(
            {
                withLifecycleGate {
                    if (notifyCallbacks && notify && synchronized(lock) { !closed && state == InternetProductSessionState.FAILED }) {
                        callbacks.onStateChanged(InternetProductSessionState.FAILED)
                        if (synchronized(lock) { !closed && state == InternetProductSessionState.FAILED }) {
                            if (persistenceFailure == null) {
                                callbacks.onRevoked(reason)
                            } else {
                                callbacks.onFailure(requireNotNull(persistenceFailure))
                            }
                        }
                    }
                }
            },
            { close() },
        )
    }

    private fun sendApplicationControl(encode: () -> ByteArray): Boolean {
        if (!synchronized(lock) { acceptsTransportCallbackLocked() && acceptedSession && state == InternetProductSessionState.ACTIVE }) {
            return false
        }
        val encoded = encode()
        val sent =
            synchronized(lock) {
                acceptsTransportCallbackLocked() &&
                    acceptedSession &&
                    state == InternetProductSessionState.ACTIVE &&
                    transport.sendControl(encoded)
            }
        if (!sent && synchronized(lock) { acceptsTransportCallbackLocked() }) {
            fail(IllegalStateException("Reliable control channel backlog rejected a state-changing message"))
        }
        return sent
    }

    private fun sendAdvancedRecord(
        payload: ByteArray,
        binding: AdvancedChannelBinding,
        failOnBacklogRejection: Boolean = true,
        send: () -> Boolean,
    ): Boolean {
        var admissionFailure: Throwable? = null
        val admission =
            synchronized(lock) {
                if (!acceptsTransportCallbackLocked() || !acceptedSession || state != InternetProductSessionState.ACTIVE) {
                    return false
                }
                try {
                    advancedChannelGate.reserve(payload.size, binding, advancedChannelOwner(activeTransportOwner ?: transportOwner))
                } catch (failure: Throwable) {
                    admissionFailure = failure
                    null
                }
            } ?: run {
                if (!failOnBacklogRejection && isAdvancedChannelBacklogFailure(admissionFailure)) return false
                fail(IllegalArgumentException("Protocol v1 advanced channel record was rejected", admissionFailure))
                return false
            }
        val sent =
            try {
                send()
            } finally {
                finishAdvancedAdmission(admission)
            }
        if (!sent && failOnBacklogRejection && synchronized(lock) { acceptsTransportCallbackLocked() }) {
            fail(IllegalStateException("Protocol v1 advanced channel backlog rejected a product-session record"))
        }
        return sent
    }

    private fun isAdvancedChannelBacklogFailure(failure: Throwable?): Boolean =
        failure is AdvancedChannelBacklogRejectedException

    private fun finishAdvancedAdmission(admission: AdvancedChannelAdmission) {
        try {
            advancedChannelGate.finish(admission)
        } catch (failure: Throwable) {
            fail(IllegalStateException("Protocol v1 advanced channel admission could not be released", failure))
        }
    }

    private fun sendRequiredControl(payload: ByteArray) {
        if (!transport.sendControl(payload)) {
            fail(IllegalStateException("Required Protocol v1 control message could not be queued"))
        }
    }

    private fun sendRequiredControlIfOwned(
        owner: TransportOwner,
        payload: ByteArray,
    ) {
        val sendFailed =
            synchronized(lock) {
                acceptsTransportCallbackLocked(owner) && !transport.sendControl(payload)
            }
        if (sendFailed) failIfOwned(owner, IllegalStateException("Required Protocol v1 control message could not be queued"))
    }

    private fun nextMessageId(): Long {
        val next = nextMessageId.incrementAndGet()
        check(next > 0) { "Protocol message identifier exhausted" }
        return next
    }

    private fun fail(error: Throwable) {
        val notify =
            withLifecycleGate {
                synchronized(lock) {
                    if (closed || state == InternetProductSessionState.FAILED) {
                        false
                    } else {
                        invalidateTransportOwnerLocked()
                        state = InternetProductSessionState.FAILED
                        true
                    }
                }
        }
        if (notify) {
            stopAudioPlayback("session_failure")?.let(error::addSuppressed)
            notifyTerminalFailureIfCurrent(error)
            releaseFailedSessionCredentials()
        }
    }

    private fun failIfOwned(
        owner: TransportOwner,
        error: Throwable,
    ): Boolean {
        val notify =
            withLifecycleGate {
                synchronized(lock) {
                    if (!acceptsTransportCallbackLocked(owner)) {
                        false
                    } else {
                        invalidateTransportOwnerLocked()
                        state = InternetProductSessionState.FAILED
                        true
                    }
                }
        }
        if (notify) {
            stopAudioPlayback("session_failure")?.let(error::addSuppressed)
            notifyTerminalFailureIfCurrent(error)
            releaseFailedSessionCredentials()
        }
        return notify
    }

    private fun releaseFailedSessionCredentials() {
        runBestEffort(
            { transport.close() },
            { lease.close() },
        )
    }

    private fun transitionIfOwned(
        owner: TransportOwner,
        next: InternetProductSessionState,
    ) {
        val changed =
            withLifecycleGate {
                synchronized(lock) {
                    if (!acceptsTransportCallbackLocked(owner) || state == next) {
                        false
                    } else {
                        if (next == InternetProductSessionState.CLOSED) invalidateTransportOwnerLocked()
                        state = next
                        true
                    }
                }
            }
        if (changed) {
            if (next == InternetProductSessionState.CLOSED) stopAudioPlayback("transport_closed")?.let(callbacks::onFailure)
            notifyStateIfOwned(owner, next)
        }
    }

    private fun notifyStateIfOwned(
        owner: TransportOwner,
        expected: InternetProductSessionState,
    ) {
        withLifecycleGate {
            if (synchronized(lock) { acceptsTransportCallbackLocked(owner) && state == expected }) {
                callbacks.onStateChanged(expected)
            }
        }
    }

    private fun notifyRouteIfOwned(
        owner: TransportOwner,
        route: PeerRoute,
    ) {
        withLifecycleGate {
            if (synchronized(lock) { acceptsTransportCallbackLocked(owner) }) callbacks.onRouteSelected(route)
        }
    }

    private fun notifyPongIfOwned(
        owner: TransportOwner,
        sequence: Long,
    ) {
        withLifecycleGate {
            if (synchronized(lock) { acceptsTransportCallbackLocked(owner) }) callbacks.onPong(sequence)
        }
    }

    private fun notifyInputAckIfOwned(
        owner: TransportOwner,
        inputId: Long,
        accepted: Boolean,
        rejectionReason: String,
    ) {
        var shouldDrainControllerQueue = false
        var shouldNotify = false
        var controllerId: String? = null
        var controllerEpoch: Long? = null
        controllerSendGate.withLock {
            withLifecycleGate {
                if (synchronized(lock) { acceptsTransportCallbackLocked(owner) }) {
                    val controllerWasNegotiated =
                        synchronized(lock) {
                            acceptedSession && Capability.CAPABILITY_CONTROLLER in expectedNegotiatedCapabilities
                        }
                    if (!controllerWasNegotiated) {
                        failIfOwned(
                            owner,
                            IllegalStateException("Controller input acknowledgement arrived without a negotiated controller session"),
                        )
                        return@withLifecycleGate
                    }
                    val acknowledgement =
                        controllerConnectionAcks.acknowledge(inputId).also { acknowledged ->
                            if (acknowledged != null) shouldDrainControllerQueue = true
                            if (accepted && acknowledged?.hasDeferredDisconnect == true) {
                                controllerConnectionAcks.markDisconnectReady(acknowledged.connection)
                                shouldDrainControllerQueue = true
                            }
                        }
                    controllerId = acknowledgement?.connection?.controllerId
                    controllerEpoch = acknowledgement?.connection?.controllerEpoch
                    shouldNotify = true
                }
            }
        }
        if (shouldNotify) {
            withLifecycleGate {
                if (!synchronized(lock) { acceptsTransportCallbackLocked(owner) }) return@withLifecycleGate
                callbacks.onInputAck(
                    inputId,
                    controllerId,
                    controllerEpoch,
                    accepted,
                    rejectionReason,
                )
            }
        }
        if (shouldDrainControllerQueue) controllerSendGate.withLock { drainControllerQueue() }
    }

    private fun notifyFailureIfOwned(
        owner: TransportOwner,
        error: Throwable,
    ) {
        withLifecycleGate {
            if (synchronized(lock) { acceptsTransportCallbackLocked(owner) }) callbacks.onFailure(error)
        }
    }

    private fun notifyTerminalFailureIfCurrent(error: Throwable) {
        withLifecycleGate {
            if (synchronized(lock) { !closed && state == InternetProductSessionState.FAILED }) {
                callbacks.onStateChanged(InternetProductSessionState.FAILED)
            }
            if (synchronized(lock) { !closed && state == InternetProductSessionState.FAILED }) callbacks.onFailure(error)
        }
    }

    private fun transition(next: InternetProductSessionState) {
        val changed =
            synchronized(lock) {
                if (
                    state == next ||
                    state == InternetProductSessionState.CLOSED ||
                    state == InternetProductSessionState.FAILED && next != InternetProductSessionState.CLOSED
                ) {
                    false
                } else {
                    state = next
                    true
                }
            }
        if (changed) {
            testHooks.afterStateCommitBeforeDispatchGate(next)
            withLifecycleGate {
                if (synchronized(lock) { state == next && (!closed || next == InternetProductSessionState.CLOSED) }) {
                    callbacks.onStateChanged(next)
                }
            }
        }
    }

    private inline fun <T> withLifecycleGate(block: () -> T): T =
        videoEffectGate.withLock { callbackGate.withLock(block) }

    private fun acceptsTransportCallbackLocked(owner: TransportOwner = transportOwner): Boolean =
        !closed &&
            !freshSessionRequested &&
            activeTransportOwner === owner &&
            !isTerminalStateLocked()

    private fun isTerminalStateLocked(): Boolean =
        state == InternetProductSessionState.FAILED || state == InternetProductSessionState.CLOSED

    private fun invalidateTransportOwnerLocked() {
        activeTransportOwner = null
        acceptedHostHello = false
        acceptedSession = false
        expectedNegotiatedCapabilities = emptySet()
        baseNegotiatedCapabilities = emptySet()
        hostMaximumFileBytes = 0L
        hostMaximumFileChunkBytes = 0
        negotiatedFilePolicy = localFileTransferPolicy.copy(allowed = false, maximumFileBytes = 0L)
        outgoingFileTransferDeadlines.clear()
        fileTransferProductOwner.clear()
        controllerSendQueue.clear()
        controllerConnectionAcks.reset()
        currentVideoConfiguration = null
        currentAudioConfiguration = null
        audioPlaybackConfigured = false
        pendingVideoConfiguration = null
        hostMaximumClipboardBytes = 0L
        negotiatedMaximumClipboardBytes = 0L
        remoteManagedClipboardAllowed = true
        managedPolicyResolver.clearRemote()
        clipboard?.reset()
        clipboard = null
        nextHeartbeatAtMillis = Long.MAX_VALUE
        frameAssembler.reset()
    }

    private fun advancedChannelOwner(owner: TransportOwner): AdvancedChannelOwner =
        AdvancedChannelOwner(
            sessionId = lease.signalingSessionId,
            sessionEpoch = lease.authoritativeSessionEpoch,
            generation = owner.generation,
        )

    private fun currentStreamId(): Long = synchronized(lock) { currentVideoConfiguration?.streamId ?: 0 }

    private fun currentAudioRecordRoute(): AudioRecordRoute =
        synchronized(lock) {
            val configuration = currentAudioConfiguration
            AudioRecordRoute(
                streamId =
                    when {
                        !managedPolicyResolver.effectivePolicy.audioAllowed -> 0
                        configuration != null -> configuration.streamId
                        else -> currentVideoConfiguration?.streamId ?: 0
                    },
                productPlayback =
                    audioPlaybackConfigured &&
                        configuration != null &&
                        Capability.CAPABILITY_AUDIO in expectedNegotiatedCapabilities,
            )
        }

    private fun stopAudioPlayback(reason: String): Throwable? {
        synchronized(lock) {
            currentAudioConfiguration = null
            audioPlaybackConfigured = false
        }
        return try {
            audioPlayback?.stop(reason)
            null
        } catch (failure: Throwable) {
            IllegalStateException("Audio playback stop failed", failure)
        }
    }

    private data class TransportOwner(val generation: Long)

    private data class OutgoingFileTransferDeadline(
        val owner: TransportOwner,
        val deadlineMillis: Long,
    )

    private sealed interface FileChunkDecodeResult {
        data class Valid(val chunk: FileChunk) : FileChunkDecodeResult
        data class Invalid(val transferId: ByteString, val reasonCode: String) : FileChunkDecodeResult
    }

    private class InternetFileTransferPendingOfferGate(
        private val maximumPendingFileOffers: Int = DEFAULT_MAXIMUM_PENDING_FILE_OFFERS,
    ) : FileTransferProductOwner.PendingOfferGate {
        private val pendingFileOffers = LinkedHashMap<ByteString, FileTransferProductOwner.PendingOfferOwner>()

        init {
            require(maximumPendingFileOffers > 0) { "maximumPendingFileOffers must be positive" }
        }

        @Synchronized
        override fun trackFileOffer(
            transferId: ByteString,
            ownerToken: Any,
            connectionGeneration: Long,
        ): Boolean {
            if (pendingFileOffers.containsKey(transferId)) return false
            if (pendingFileOffers.size >= maximumPendingFileOffers) return false
            pendingFileOffers[transferId] = FileTransferProductOwner.PendingOfferOwner(ownerToken, connectionGeneration)
            return true
        }

        @Synchronized
        override fun claimFileOffer(transferId: ByteString): FileTransferProductOwner.PendingOfferOwner? =
            pendingFileOffers.remove(transferId)

        @Synchronized
        override fun releaseFileOffer(transferId: ByteString) {
            pendingFileOffers.remove(transferId)
        }

        @Synchronized
        override fun hasFileOffer(transferId: ByteString): Boolean = pendingFileOffers.containsKey(transferId)

        @Synchronized
        override fun clearFileOffers() {
            pendingFileOffers.clear()
        }
    }

    private data class AudioRecordRoute(
        val streamId: Long,
        val productPlayback: Boolean,
    )

    private class PendingVideoConfiguration(
        val configEpoch: Long,
        val owner: TransportOwner,
        val deadlineMillis: Long,
    ) {
        var effectCommitted = false
    }

    private class PendingRevocation(
        val owner: TransportOwner,
        val coordinatorReservation: InternetProductRevocationCoordinator.Reservation,
        val reason: String,
    ) {
        var durableBarrier = false
    }

    companion object {
        private const val MIN_HEARTBEAT_INTERVAL_MS = 100L
        private const val MAX_HEARTBEAT_INTERVAL_MS = 60_000L
        private const val MEDIA_KEYFRAME_REASON_INVALID_FRAGMENT = "invalid_media_fragment"
        private const val VIDEO_CONFIGURATION_TIMEOUT_MS = 5_000L
        private val CONTROLLER_STRUCTURAL_STATES =
            setOf(
                InternetProductSessionState.ACTIVE,
                InternetProductSessionState.RECOVERING,
                InternetProductSessionState.SUSPENDED,
            )
        private const val AUDIO_BACKLOG_RECORD_CAPACITY = 2
        private const val DEFAULT_MAXIMUM_PENDING_FILE_OFFERS = 16
        internal const val FILE_TRANSFER_PROGRESS_TIMEOUT_MS = 30_000L
        private const val INTERNET_DISPLAY_ID = "internet-display"
        private val DEFAULT_BULK_TRANSFER_ID = "internet-bulk-v1".toByteArray(Charsets.UTF_8)

        private fun Set<Capability>.filteredBy(policy: InternetManagedPolicy): Set<Capability> =
            filterTo(mutableSetOf()) { capability ->
                when (capability) {
                    Capability.CAPABILITY_CLIPBOARD -> policy.clipboardAllowed
                    Capability.CAPABILITY_FILE_TRANSFER -> policy.effectiveFileTransferAllowed
                    Capability.CAPABILITY_AUDIO -> policy.audioAllowed
                    else -> true
                }
            }

        private fun defaultFileTransferStagingDirectory(): File =
            File(System.getProperty("java.io.tmpdir"), "vibescreen-internet-incoming-files")

        internal fun create(
            storedSessionFactory: AndroidStoredInternetSessionFactory,
            localDeviceId: String,
            lease: InternetProductSessionLease,
            networkMonitor: NetworkMonitor,
            clock: MonotonicClock,
            codec: ProtocolV1ProductCodec,
            callbacks: InternetProductSessionCallbacks,
            audioPlayback: InternetAudioPlayback? = null,
            revocationStore: InternetProductRevocationStore,
            revocationCoordinator: InternetProductRevocationCoordinator,
            nextControllerInputId: () -> Long = SessionInputIdSequence()::next,
            fileTransferStagingDirectory: File = defaultFileTransferStagingDirectory(),
        ): InternetProductSession {
            require(localDeviceId == storedSessionFactory.localDeviceId) {
                "Stored security identity does not match the product session identity"
            }
            require(localDeviceId == codec.localDeviceId) {
                "Protocol identity does not match the product session identity"
            }
            check(
                !revocationCoordinator.isBlocked(lease.pairingIdentifier) &&
                    !revocationStore.isAdmissionBlocked(lease.pairingIdentifier),
            ) { "This authenticated pairing is revoked" }
            val boundContext = lease.boundTranscriptContext(localDeviceId)
            val stored =
                try {
                    storedSessionFactory.create(
                        pairingIdentifier = lease.pairingIdentifier,
                        sessionId = lease.signalingSessionId,
                        localRole = PeerRole.DEVICE,
                        expectedIdentity = lease.localIdentity,
                        authoritativeSessionEpoch = lease.authoritativeSessionEpoch,
                        transcriptContext = boundContext,
                        iceServers = lease.iceServers,
                        signaling = lease.signaling,
                        iceTransportPolicy = lease.iceTransportPolicy,
                    )
                } catch (failure: Throwable) {
                    lease.close()
                    throw failure
                } finally {
                    boundContext.fill(0)
                }
            return try {
                InternetProductSession(
                    lease,
                    stored.configuration,
                    stored.engine,
                    networkMonitor,
                    clock,
                    codec,
                    audioPlayback,
                    callbacks,
                    revocationStore,
                    revocationCoordinator,
                    nextControllerInputId,
                    fileTransferStagingDirectory,
                )
            } catch (failure: Throwable) {
                stored.close()
                lease.close()
                throw failure
            }
        }
    }
}

internal sealed interface ProductMediaAssemblyResult {
    data object Pending : ProductMediaAssemblyResult

    data class FrameReady(val frame: ProductVideoFrame) : ProductMediaAssemblyResult

    data class KeyframeRequired(val reason: String) : ProductMediaAssemblyResult
}

internal class ProductMediaFrameAssembler(
    private val clock: MonotonicClock,
    private val assemblyDeadlineMillis: Long = DEFAULT_ASSEMBLY_DEADLINE_MS,
) {
    private var configuration: ProductVideoConfiguration? = null
    private var sessionEpoch: Long? = null
    private var current: PendingFrame? = null
    private var waitingForKeyframe = true
    private var highestFrameId = 0L

    init {
        require(assemblyDeadlineMillis > 0) { "Media assembly deadline must be positive" }
    }

    fun startConfiguration(configuration: ProductVideoConfiguration, sessionEpoch: Long) {
        require(sessionEpoch > 0) { "Media session epoch must be positive" }
        this.configuration = configuration
        this.sessionEpoch = sessionEpoch
        current = null
        waitingForKeyframe = true
        highestFrameId = 0
    }

    fun offer(fragment: ProductMediaFragment): ProductMediaAssemblyResult {
        val active = configuration ?: return ProductMediaAssemblyResult.KeyframeRequired(REASON_NO_CONFIGURATION)
        val activeSessionEpoch = sessionEpoch
            ?: return ProductMediaAssemblyResult.KeyframeRequired(REASON_NO_CONFIGURATION)
        val nowMillis = clock.nowMillis()
        val expired = expireCurrentIfNeeded(nowMillis)
        when (classifyScope(fragment, active, activeSessionEpoch)) {
            MediaScope.CURRENT -> Unit
            MediaScope.STALE -> {
                return if (expired) {
                    ProductMediaAssemblyResult.KeyframeRequired(REASON_ASSEMBLY_TIMEOUT)
                } else {
                    ProductMediaAssemblyResult.Pending
                }
            }
            MediaScope.CONFLICTING -> {
                return ProductMediaAssemblyResult.KeyframeRequired(
                    if (expired) REASON_ASSEMBLY_TIMEOUT else REASON_SCOPE_MISMATCH,
                )
            }
        }
        if (!isAdmissible(fragment)) {
            return ProductMediaAssemblyResult.KeyframeRequired(REASON_INVALID_FRAGMENT)
        }
        if (fragment.frameId <= highestFrameId) {
            return if (expired) {
                ProductMediaAssemblyResult.KeyframeRequired(REASON_ASSEMBLY_TIMEOUT)
            } else {
                ProductMediaAssemblyResult.Pending
            }
        }
        val pending = current
        if (pending == null || fragment.frameId > pending.frameId) {
            if (pending != null && !fragment.keyframe) {
                rejectAdmittedFrame(fragment.frameId)
                return ProductMediaAssemblyResult.KeyframeRequired(REASON_MISSING_FRAGMENT)
            }
            if (waitingForKeyframe && !fragment.keyframe) {
                rejectAdmittedFrame(fragment.frameId)
                return ProductMediaAssemblyResult.KeyframeRequired(REASON_KEYFRAME_REQUIRED)
            }
            current = PendingFrame(fragment, deadlineFrom(nowMillis))
        } else if (fragment.frameId < pending.frameId || !pending.matches(fragment)) {
            if (fragment.frameId == pending.frameId) {
                rejectAdmittedFrame(fragment.frameId)
                return ProductMediaAssemblyResult.KeyframeRequired(REASON_FRAGMENT_MISMATCH)
            }
            return ProductMediaAssemblyResult.Pending
        }
        val target = checkNotNull(current)
        if (!target.canAdd(fragment)) {
            rejectAdmittedFrame(fragment.frameId)
            return ProductMediaAssemblyResult.KeyframeRequired(REASON_DUPLICATE_FRAGMENT)
        }
        if (target.totalBytes > InternetMediaRecordContract.MAXIMUM_FRAME_BYTES - fragment.payload.size) {
            rejectAdmittedFrame(fragment.frameId)
            return ProductMediaAssemblyResult.KeyframeRequired(REASON_FRAME_TOO_LARGE)
        }
        target.commit(fragment)
        if (!target.complete()) return ProductMediaAssemblyResult.Pending
        current = null
        highestFrameId = target.frameId
        if (waitingForKeyframe && !target.keyframe) {
            return ProductMediaAssemblyResult.KeyframeRequired(REASON_KEYFRAME_REQUIRED)
        }
        waitingForKeyframe = false
        return ProductMediaAssemblyResult.FrameReady(
            ProductVideoFrame(
                streamId = active.streamId,
                sessionEpoch = fragment.sessionEpoch,
                configEpoch = active.configEpoch,
                frameId = target.frameId,
                captureTimestampNs = target.captureTimestampNs,
                keyframe = target.keyframe,
                codec = active.codec,
                payload = target.combine(),
            ),
        )
    }

    fun expire(): ProductMediaAssemblyResult =
        if (expireCurrentIfNeeded(clock.nowMillis())) {
            ProductMediaAssemblyResult.KeyframeRequired(REASON_ASSEMBLY_TIMEOUT)
        } else {
            ProductMediaAssemblyResult.Pending
        }

    fun reset() {
        configuration = null
        sessionEpoch = null
        current = null
        waitingForKeyframe = true
        highestFrameId = 0
    }

    private fun isAdmissible(fragment: ProductMediaFragment): Boolean =
        fragment.frameId in 1 until Long.MAX_VALUE &&
            fragment.fragmentCount in 1..InternetMediaRecordContract.MAXIMUM_FRAGMENTS_PER_FRAME &&
            fragment.fragmentIndex in 0 until fragment.fragmentCount &&
            fragment.payload.isNotEmpty()

    private fun classifyScope(
        fragment: ProductMediaFragment,
        active: ProductVideoConfiguration,
        activeSessionEpoch: Long,
    ): MediaScope =
        when {
            fragment.sessionEpoch < activeSessionEpoch -> MediaScope.STALE
            fragment.sessionEpoch > activeSessionEpoch -> MediaScope.CONFLICTING
            fragment.configEpoch < active.configEpoch -> MediaScope.STALE
            fragment.configEpoch > active.configEpoch -> MediaScope.CONFLICTING
            fragment.streamId != active.streamId || fragment.codec != active.codec -> MediaScope.CONFLICTING
            else -> MediaScope.CURRENT
        }

    private fun rejectAdmittedFrame(frameId: Long) {
        current = null
        highestFrameId = maxOf(highestFrameId, frameId)
        waitingForKeyframe = true
    }

    private fun expireCurrentIfNeeded(nowMillis: Long): Boolean {
        val pending = current ?: return false
        if (nowMillis < pending.deadlineMillis) return false
        rejectAdmittedFrame(pending.frameId)
        return true
    }

    private fun deadlineFrom(nowMillis: Long): Long =
        if (nowMillis > Long.MAX_VALUE - assemblyDeadlineMillis) {
            Long.MAX_VALUE
        } else {
            nowMillis + assemblyDeadlineMillis
        }

    private class PendingFrame(
        fragment: ProductMediaFragment,
        val deadlineMillis: Long,
    ) {
        val frameId = fragment.frameId
        val fragmentCount = fragment.fragmentCount
        val captureTimestampNs = fragment.captureTimestampNs
        val keyframe = fragment.keyframe
        private val streamId = fragment.streamId
        private val sessionEpoch = fragment.sessionEpoch
        private val configEpoch = fragment.configEpoch
        private val codec = fragment.codec
        private val fragments = arrayOfNulls<ByteArray>(fragmentCount)
        var totalBytes = 0
            private set

        fun matches(fragment: ProductMediaFragment): Boolean =
            fragment.frameId == frameId &&
                fragment.fragmentCount == fragmentCount &&
                fragment.captureTimestampNs == captureTimestampNs &&
                fragment.keyframe == keyframe &&
                fragment.streamId == streamId &&
                fragment.sessionEpoch == sessionEpoch &&
                fragment.configEpoch == configEpoch &&
                fragment.codec == codec

        fun canAdd(fragment: ProductMediaFragment): Boolean =
            fragment.fragmentIndex in fragments.indices && fragments[fragment.fragmentIndex] == null

        fun commit(fragment: ProductMediaFragment) {
            fragments[fragment.fragmentIndex] = fragment.payload.copyOf()
            totalBytes += fragment.payload.size
        }

        fun complete(): Boolean = fragments.all { it != null }

        fun combine(): ByteArray {
            val output = ByteArray(totalBytes)
            var offset = 0
            fragments.forEach { fragment ->
                val value = checkNotNull(fragment)
                value.copyInto(output, offset)
                offset += value.size
            }
            return output
        }
    }

    private enum class MediaScope {
        CURRENT,
        STALE,
        CONFLICTING,
    }

    companion object {
        internal const val REASON_NO_CONFIGURATION = "media_without_configuration"
        internal const val REASON_SCOPE_MISMATCH = "media_scope_mismatch"
        internal const val REASON_INVALID_FRAGMENT = "invalid_media_fragment"
        internal const val REASON_MISSING_FRAGMENT = "missing_media_fragment"
        internal const val REASON_FRAGMENT_MISMATCH = "media_fragment_mismatch"
        internal const val REASON_DUPLICATE_FRAGMENT = "duplicate_media_fragment"
        internal const val REASON_FRAME_TOO_LARGE = "media_frame_too_large"
        internal const val REASON_KEYFRAME_REQUIRED = "media_keyframe_required"
        internal const val REASON_ASSEMBLY_TIMEOUT = "media_assembly_timeout"
        internal const val DEFAULT_ASSEMBLY_DEADLINE_MS = 1_000L
    }
}
