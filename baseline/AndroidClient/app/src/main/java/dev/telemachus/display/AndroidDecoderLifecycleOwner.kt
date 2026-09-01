package dev.telemachus.display

internal data class DecoderLifecycleAttempt(
    val sessionToken: Any,
    val sessionGeneration: Long,
    val surfaceToken: Any,
    val surfaceGeneration: Long,
    val configurationToken: Any,
    val configurationGeneration: Long,
    val configEpoch: Long,
    val codec: StreamCodec,
    val failSessionOnFailure: Boolean,
    val allowsActiveDecoderReplacement: Boolean = false,
    val isConfigurationCurrent: () -> Boolean,
)

internal sealed interface DecoderLifecycleAttemptAdmission {
    data object Start : DecoderLifecycleAttemptAdmission

    data object RetryWhenSurfaceReady : DecoderLifecycleAttemptAdmission

    data class Failed(
        val reason: String,
    ) : DecoderLifecycleAttemptAdmission
}

internal sealed interface DecoderLifecycleCommitResult {
    data object Configured : DecoderLifecycleCommitResult

    data object RetryWhenSurfaceReady : DecoderLifecycleCommitResult

    data class Failed(
        val reason: String,
    ) : DecoderLifecycleCommitResult
}

internal interface AndroidDecoderLifecyclePort<Decoder : Any> {
    fun hasBlockingActiveDecoder(attempt: DecoderLifecycleAttempt): Boolean

    fun isAttemptCurrent(attempt: DecoderLifecycleAttempt): Boolean

    fun canRetryAttempt(attempt: DecoderLifecycleAttempt): Boolean

    fun isPublishedDecoderCurrent(
        decoder: Decoder,
        attempt: DecoderLifecycleAttempt,
    ): Boolean

    fun updateScaleMode(decoder: Decoder)

    fun commitStartup(
        decoder: Decoder,
        publish: () -> Boolean,
    ): DecoderStartupCommitResult

    fun publishDecoder(
        decoder: Decoder,
        attempt: DecoderLifecycleAttempt,
    ): Boolean

    fun releaseDecoder(decoder: Decoder)

    fun recordStructuralFailure(
        codec: StreamCodec,
        failure: DecoderFailure,
        isCurrentConfiguration: () -> Boolean,
    ): Boolean

    fun reportInitializationFailure(
        error: Exception,
        failSession: Boolean,
    )
}

internal class AndroidDecoderLifecycleOwner<Decoder : Any>(
    private val port: AndroidDecoderLifecyclePort<Decoder>,
) {
    fun admitAttempt(attempt: DecoderLifecycleAttempt): DecoderLifecycleAttemptAdmission =
        if (port.hasBlockingActiveDecoder(attempt) || !isReadyForDecoderWork(attempt)) {
            retryOrStale(attempt)
        } else {
            DecoderLifecycleAttemptAdmission.Start
        }

    fun handleCreationFailure(
        attempt: DecoderLifecycleAttempt,
        failure: Throwable,
    ): DecoderLifecycleCommitResult {
        if (isReadyForDecoderWork(attempt)) {
            if (failure is DecoderInitializationException) {
                recordStructuralFailure(attempt, failure.failure)
            }
            port.reportInitializationFailure(failure.toException(), attempt.failSessionOnFailure)
            return DecoderLifecycleCommitResult.Failed(
                failure.message ?: DECODER_CONFIGURATION_FAILURE_REASON,
            )
        }
        return retryOrStale(attempt).toConfigurationResult()
    }

    fun commitCreatedDecoder(
        attempt: DecoderLifecycleAttempt,
        decoder: Decoder,
        publishConfigurationCommit: (() -> Boolean) -> Boolean,
    ): DecoderLifecycleCommitResult {
        val releaser = ExactlyOnceDecoderRelease(decoder, port::releaseDecoder)
        var published = false
        if (port.hasBlockingActiveDecoder(attempt) || !isReadyForDecoderWork(attempt)) {
            releaser.release()
            return retryOrStale(attempt).toConfigurationResult()
        }

        try {
            port.updateScaleMode(decoder)
        } catch (failure: RuntimeException) {
            releaser.release()
            return DecoderLifecycleCommitResult.Failed(
                failure.message ?: DECODER_CONFIGURATION_FAILURE_REASON,
            )
        }

        val startupResult =
            try {
                port.commitStartup(decoder) {
                    publishConfigurationCommit {
                        port.publishDecoder(decoder, attempt).also { didPublish ->
                            if (didPublish) published = true
                        }
                    }
                }
            } catch (failure: Throwable) {
                if (!published) releaser.release()
                throw failure
            }
        return when (startupResult) {
            DecoderStartupCommitResult.Committed -> DecoderLifecycleCommitResult.Configured
            DecoderStartupCommitResult.NotCommitted -> {
                releaser.release()
                DecoderLifecycleCommitResult.Failed(STALE_DECODER_CONFIGURATION_REASON)
            }
            is DecoderStartupCommitResult.Failed -> {
                recordStructuralFailure(attempt, startupResult.failure)
                port.reportInitializationFailure(
                    DecoderInitializationException(startupResult.failure),
                    attempt.failSessionOnFailure,
                )
                releaser.release()
                DecoderLifecycleCommitResult.Failed(startupResult.reason)
            }
        }
    }

    fun runIfActive(
        decoder: Decoder,
        attempt: DecoderLifecycleAttempt,
        action: () -> Unit,
    ): Boolean = activeBinding(decoder, attempt).runIfActive(action)

    fun recordActiveStructuralFailure(
        decoder: Decoder,
        attempt: DecoderLifecycleAttempt,
        failure: DecoderFailure,
    ): Boolean =
        port.recordStructuralFailure(
            codec = attempt.codec,
            failure = failure,
            isCurrentConfiguration = { port.isPublishedDecoderCurrent(decoder, attempt) },
        )

    private fun activeBinding(
        decoder: Decoder,
        attempt: DecoderLifecycleAttempt,
    ): ActiveDecoderCallbackBinding<Decoder> =
        ActiveDecoderCallbackBinding(decoder, attempt.sessionGeneration) { identity, generation ->
            generation == attempt.sessionGeneration && port.isPublishedDecoderCurrent(identity, attempt)
        }

    private fun isReadyForDecoderWork(attempt: DecoderLifecycleAttempt): Boolean =
        attempt.isConfigurationCurrent() && port.isAttemptCurrent(attempt)

    private fun recordStructuralFailure(
        attempt: DecoderLifecycleAttempt,
        failure: DecoderFailure,
    ): Boolean =
        port.recordStructuralFailure(
            codec = attempt.codec,
            failure = failure,
            isCurrentConfiguration = { isReadyForDecoderWork(attempt) },
        )

    private fun retryOrStale(attempt: DecoderLifecycleAttempt): DecoderLifecycleAttemptAdmission =
        if (port.canRetryAttempt(attempt)) {
            DecoderLifecycleAttemptAdmission.RetryWhenSurfaceReady
        } else {
            DecoderLifecycleAttemptAdmission.Failed(STALE_DECODER_CONFIGURATION_REASON)
        }

    private fun DecoderLifecycleAttemptAdmission.toConfigurationResult(): DecoderLifecycleCommitResult =
        when (this) {
            DecoderLifecycleAttemptAdmission.Start -> error("Decoder attempt admission was not terminal")
            DecoderLifecycleAttemptAdmission.RetryWhenSurfaceReady ->
                DecoderLifecycleCommitResult.RetryWhenSurfaceReady
            is DecoderLifecycleAttemptAdmission.Failed -> DecoderLifecycleCommitResult.Failed(reason)
        }

    private fun Throwable.toException(): Exception =
        this as? Exception ?: RuntimeException(this)

    private class ExactlyOnceDecoderRelease<Decoder : Any>(
        private val decoder: Decoder,
        private val release: (Decoder) -> Unit,
    ) {
        private var released = false

        fun release() {
            if (released) return
            released = true
            release(decoder)
        }
    }

    private companion object {
        const val STALE_DECODER_CONFIGURATION_REASON = "stale_decoder_configuration"
        const val DECODER_CONFIGURATION_FAILURE_REASON = "decoder_configuration_failure"
    }
}
