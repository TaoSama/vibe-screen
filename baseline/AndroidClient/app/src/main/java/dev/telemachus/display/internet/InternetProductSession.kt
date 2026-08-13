package dev.telemachus.display.internet

import dev.telemachus.display.STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON
import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.SecurityTranscript
import dev.vibescreen.protocol.v1.Capability
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

interface InternetProductSessionCallbacks {
    fun onStateChanged(state: InternetProductSessionState) = Unit

    fun onRouteSelected(route: PeerRoute) = Unit

    fun onVideoConfiguration(
        configuration: ProductVideoConfiguration,
        effect: ProductVideoConfigurationEffect,
        completion: (ProductVideoDecision) -> Unit,
    ) = completion(effect.commit { ProductVideoDecision.reject("decoder_not_configured") })

    fun onVideoFrame(frame: ProductVideoFrame) = Unit

    fun onPong(sequence: Long) = Unit

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
    private val callbacks: InternetProductSessionCallbacks,
    private val revocationStore: InternetProductRevocationStore,
    private val revocationCoordinator: InternetProductRevocationCoordinator,
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
    private var hostMaximumEncryptedMediaRecordBytes = 0L
    private var negotiatedMaximumEncryptedMediaRecordBytes = 0
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

    fun sendPing(sequence: Long): Boolean =
        sendApplicationControl {
            codec.encodePing(nextMessageId(), lease.protocolSessionId, lease.authoritativeSessionEpoch, sequence)
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
            is ProductControlMessage.Pong -> notifyPongIfOwned(owner, message.sequence)
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
            is ProductControlMessage.ProtocolFailure -> {
                failIfOwned(owner, IllegalStateException("Protocol failure (${message.code}); retryable=${message.retryable}"))
            }
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
        val expectedCapabilities =
            message.capabilities.intersect(ProtobufProtocolV1ProductCodec.OFFERED_CLIENT_CAPABILITIES.toSet())
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
                hostMaximumEncryptedMediaRecordBytes = message.maximumEncryptedMediaRecordBytes
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
                message.heartbeatIntervalMillis !in MIN_HEARTBEAT_INTERVAL_MS..MAX_HEARTBEAT_INTERVAL_MS
            ) {
                invalidAcceptance = true
            } else {
                acceptedSession = true
                negotiatedMaximumEncryptedMediaRecordBytes = Math.toIntExact(message.maximumEncryptedMediaRecordBytes)
                heartbeatIntervalMillis = message.heartbeatIntervalMillis
                scheduleNextHeartbeatLocked()
                if (state != InternetProductSessionState.ACTIVE) {
                    state = InternetProductSessionState.ACTIVE
                    activated = true
                }
            }
        }
        if (invalidAcceptance) failIfOwned(owner, IllegalArgumentException("Session acceptance does not match the authenticated lease"))
        if (activated) notifyStateIfOwned(owner, InternetProductSessionState.ACTIVE)
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
        if (shouldResume) notifyStateIfOwned(owner, InternetProductSessionState.ACTIVE)
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
            synchronized(lock) {
                if (!isVideoConfigurationReservationActiveLocked(owner, reservation, reservationEpoch)) return
                pendingVideoConfiguration = null
                if (!transport.sendControl(response)) {
                    sendFailed = true
                } else if (effectiveDecision.accepted) {
                    currentVideoConfiguration = configuration
                    frameAssembler.startConfiguration(configuration, lease.authoritativeSessionEpoch)
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
            }
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
        withLifecycleGate {
            var stateChanged = false
            val reserved =
                synchronized(lock) {
                    if (!acceptsTransportCallbackLocked(owner)) {
                        false
                    } else {
                        stateChanged = state != InternetProductSessionState.RECOVERING
                        freshSessionRequested = true
                        invalidateTransportOwnerLocked()
                        state = InternetProductSessionState.RECOVERING
                        true
                    }
                }
            if (!reserved) return
            if (stateChanged) callbacks.onStateChanged(InternetProductSessionState.RECOVERING)
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
        if (changed) notifyStateIfOwned(owner, next)
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
        currentVideoConfiguration = null
        pendingVideoConfiguration = null
        nextHeartbeatAtMillis = Long.MAX_VALUE
        frameAssembler.reset()
    }

    private data class TransportOwner(val generation: Long)

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
        fun create(
            storedSessionFactory: AndroidStoredInternetSessionFactory,
            localDeviceId: String,
            lease: InternetProductSessionLease,
            networkMonitor: NetworkMonitor,
            clock: MonotonicClock,
            codec: ProtocolV1ProductCodec,
            callbacks: InternetProductSessionCallbacks,
            revocationStore: InternetProductRevocationStore,
            revocationCoordinator: InternetProductRevocationCoordinator,
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
                    callbacks,
                    revocationStore,
                    revocationCoordinator,
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
