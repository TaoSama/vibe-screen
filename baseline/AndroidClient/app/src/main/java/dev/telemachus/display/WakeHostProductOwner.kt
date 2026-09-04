package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.Envelope
import java.security.SecureRandom
import java.util.concurrent.Executor

internal class WakeHostProductOwner(
    private val executor: Executor,
    private val policy: WakeHostPolicy,
    private val packetSender: WakeHostPacketSender,
    private val sessionOwner: StreamProtocolSessionOwner,
    private val requestIdRandom: SecureRandom,
    private val isConnectedV1: () -> Boolean,
    private val submitOutbound: (OutboundCommandScheduler.Kind, StreamOutboundCommand, Long) -> OutboundCommandScheduler.Submission,
    private val isOutboundAdmitted: (OutboundCommandScheduler.Submission) -> Boolean,
    private val requestConnectionEnd: (SessionFailure) -> Unit,
    private val logWarning: (String, Throwable) -> Unit,
    private val onResult: () -> ((accepted: Boolean, rejectionReason: String) -> Unit)?,
    private val protocolActionTimeoutMs: Long,
) {
    @Volatile private var authorizationSecret: ByteArray? = null

    fun clearAuthorizationSecret() {
        authorizationSecret = null
    }

    fun setAuthorizationSecret(secret: ByteArray) {
        authorizationSecret = secret.copyOf()
    }

    fun canAdvertiseWakeHost(): Boolean =
        authorizationSecret?.isNotEmpty() == true || policy.wakeAllowed

    fun request(
        targetMacAddress: ByteString,
        secureOnPassword: ByteString = ByteString.EMPTY,
    ): Boolean {
        val requestId = ByteString.copyFrom(ByteArray(WAKE_HOST_REQUEST_ID_BYTES).also(requestIdRandom::nextBytes))
        return request(requestId, targetMacAddress, secureOnPassword)
    }

    fun request(
        requestId: ByteString,
        targetMacAddress: ByteString,
        secureOnPassword: ByteString = ByteString.EMPTY,
    ): Boolean {
        if (!isConnectedV1()) return false
        val session = sessionOwner.currentSession ?: return false
        val connectionGeneration = sessionOwner.connectionGeneration
        if (!session.canRequestWakeHost) return false
        val submission =
            submitOutbound(
                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                StreamOutboundCommand.ProtocolBatch { activeSession ->
                    if (activeSession !== session || !sessionOwner.isCurrent(session, connectionGeneration)) {
                        emptyList()
                    } else {
                        activeSession.requestWakeHost(
                            requestId,
                            targetMacAddress,
                            secureOnPassword,
                            authorizationSecret = authorizationSecret?.copyOf(),
                        )?.let { listOf(it) } ?: emptyList()
                    }
                },
                0L,
            )
        return isOutboundAdmitted(submission)
    }

    fun dispatchRequest(
        session: ProtocolV1Session,
        connectionGeneration: Long,
        request: WakeHostRequestContext,
        correlationId: Long,
    ) {
        if (!sessionOwner.isCurrent(session, connectionGeneration)) return
        if (!sessionOwner.trackWakeHostRequest(request.requestId, session, connectionGeneration, correlationId)) {
            val submission =
                submitCompletion(
                    session = session,
                    connectionGeneration = connectionGeneration,
                    requestId = request.requestId,
                    accepted = false,
                    rejectionReason = TOO_MANY_PENDING_REQUESTS_REASON,
                    correlationId = correlationId,
                    requiresTrackedReservation = false,
                )
            if (!isOutboundAdmitted(submission)) endForCompletionBackpressure(submission)
            return
        }
        try {
            executor.execute { executeRequest(session, connectionGeneration, request, correlationId) }
        } catch (failure: RuntimeException) {
            sessionOwner.releaseWakeHostRequest(request.requestId, session, connectionGeneration)
            logWarning("WakeHost executor rejected request", failure)
            val submission =
                submitCompletion(
                    session = session,
                    connectionGeneration = connectionGeneration,
                    requestId = request.requestId,
                    accepted = false,
                    rejectionReason = DISPATCH_FAILED_REASON,
                    correlationId = correlationId,
                    requiresTrackedReservation = false,
                )
            if (!isOutboundAdmitted(submission)) endForCompletionBackpressure(submission)
        }
    }

    fun complete(command: StreamOutboundCommand.ProtocolWakeHostCompletion): Envelope? {
        val retained = sessionOwner.retainsSession(command.session, command.connectionGeneration)
        if (!retained || !command.claimForWrite()) return null
        if (command.requiresTrackedReservation &&
            !sessionOwner.releaseWakeHostRequest(
                command.requestId,
                command.session,
                command.connectionGeneration,
            )
        ) {
            return null
        }
        return command.session.completeWakeHost(
            requestId = command.requestId,
            accepted = command.accepted,
            rejectionReason = command.rejectionReason,
            correlationId = command.correlationId,
            allowAfterWakeCapabilityRemoval = command.allowAfterWakeCapabilityRemoval,
        )
    }

    fun cancelPendingForPolicyDeny(
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ) {
        val cancelled = sessionOwner.cancelWakeHostRequests(session, connectionGeneration)
        cancelled.forEach { pendingRequest ->
            val submission =
                submitCompletion(
                    session = session,
                    connectionGeneration = connectionGeneration,
                    requestId = pendingRequest.requestId,
                    accepted = false,
                    rejectionReason = POLICY_DENIED_REASON,
                    correlationId = pendingRequest.correlationId,
                    requiresTrackedReservation = false,
                    allowAfterWakeCapabilityRemoval = true,
                )
            if (!isOutboundAdmitted(submission)) endForCompletionBackpressure(submission)
        }
    }

    fun deliverCompletion(
        session: ProtocolV1Session,
        connectionGeneration: Long,
        accepted: Boolean,
        rejectionReason: String,
    ) {
        if (!sessionOwner.isCurrent(session, connectionGeneration)) return
        onResult()?.invoke(accepted, rejectionReason)
    }

    private fun executeRequest(
        session: ProtocolV1Session,
        connectionGeneration: Long,
        request: WakeHostRequestContext,
        correlationId: Long,
    ) {
        if (!sessionOwner.isCurrent(session, connectionGeneration)) {
            sessionOwner.releaseWakeHostRequest(request.requestId, session, connectionGeneration)
            return
        }
        if (!sessionOwner.hasWakeHostRequest(request.requestId, session, connectionGeneration)) {
            return
        }
        val (accepted, reason) = performRequest(request) { packet ->
            sessionOwner.runIfCurrent(session, connectionGeneration) {
                packetSender.send(packet)
            } != null
        }
        if (reason == STALE_SESSION_REASON) {
            sessionOwner.releaseWakeHostRequest(request.requestId, session, connectionGeneration)
            return
        }
        val submission =
            submitCompletion(
                session = session,
                connectionGeneration = connectionGeneration,
                requestId = request.requestId,
                accepted = accepted,
                rejectionReason = reason,
                correlationId = correlationId,
            )
        if (!isOutboundAdmitted(submission)) {
            sessionOwner.releaseWakeHostRequest(request.requestId, session, connectionGeneration)
            endForCompletionBackpressure(submission)
        }
    }

    private fun performRequest(
        request: WakeHostRequestContext,
        sendPacket: (ByteArray) -> Boolean,
    ): Pair<Boolean, String> =
        try {
            val packet = WakeHostDecision.magicPacket(request, policy)
            if (sendPacket(packet)) true to "" else false to STALE_SESSION_REASON
        } catch (failure: WakeHostRequestException) {
            false to failure.reasonCode
        } catch (failure: WakeHostPacketSenderException) {
            false to failure.reasonCode
        } catch (failure: Exception) {
            logWarning("WakeHost packet send failed with ${failure.javaClass.simpleName}", failure)
            false to PACKET_SEND_FAILED_REASON
        }

    private fun submitCompletion(
        session: ProtocolV1Session,
        connectionGeneration: Long,
        requestId: ByteString,
        accepted: Boolean,
        rejectionReason: String,
        correlationId: Long,
        requiresTrackedReservation: Boolean = true,
        allowAfterWakeCapabilityRemoval: Boolean = false,
    ): OutboundCommandScheduler.Submission =
        submitOutbound(
            OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
            StreamOutboundCommand.ProtocolWakeHostCompletion(
                session = session,
                connectionGeneration = connectionGeneration,
                requestId = requestId,
                accepted = accepted,
                rejectionReason = rejectionReason,
                correlationId = correlationId,
                requiresTrackedReservation = requiresTrackedReservation,
                allowAfterWakeCapabilityRemoval = allowAfterWakeCapabilityRemoval,
            ),
            protocolActionTimeoutMs,
        )

    private fun endForCompletionBackpressure(submission: OutboundCommandScheduler.Submission) {
        requestConnectionEnd(
            SessionFailure.protocol(
                SessionFailureKind.OUTBOUND_BACKPRESSURE,
                "WakeHost completion queue unavailable: $submission",
            ),
        )
    }

    private val WakeHostRequestException.reasonCode: String
        get() =
            when (failure) {
                WakeHostRequestFailure.INVALID_REQUEST_ID -> "invalid_request_id"
                WakeHostRequestFailure.INVALID_MAC_ADDRESS -> "invalid_mac_address"
                WakeHostRequestFailure.INVALID_SECURE_ON_PASSWORD -> "invalid_secure_on_password"
                WakeHostRequestFailure.INVALID_AUTHORIZATION -> "wake_host_unauthorized"
                WakeHostRequestFailure.EXPIRED_AUTHORIZATION -> "wake_host_authorization_expired"
                WakeHostRequestFailure.REPLAYED_REQUEST -> "wake_host_replay"
                WakeHostRequestFailure.POLICY_DENIED -> "wake_host_policy_denied"
            }

    private val WakeHostPacketSenderException.reasonCode: String
        get() =
            when (failure) {
                WakeHostPacketSenderFailure.INVALID_BROADCAST_ADDRESS -> "invalid_broadcast_target"
                WakeHostPacketSenderFailure.INVALID_PORT -> "invalid_broadcast_target"
            }

    companion object {
        private const val WAKE_HOST_REQUEST_ID_BYTES = 16
        private const val TOO_MANY_PENDING_REQUESTS_REASON = "too_many_pending_wake_host_requests"
        private const val STALE_SESSION_REASON = "stale_session"
        private const val PACKET_SEND_FAILED_REASON = "wake_packet_send_failed"
        private const val DISPATCH_FAILED_REASON = "wake_host_dispatch_failed"
        private const val POLICY_DENIED_REASON = "managed_policy_denied"
    }
}
