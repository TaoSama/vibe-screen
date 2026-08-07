package dev.telemachus.display.internet

internal sealed interface InternetDecoderConfigurationResult {
    data class Completed(
        val decision: ProductVideoDecision,
    ) : InternetDecoderConfigurationResult

    data object RetryWhenSurfaceReady : InternetDecoderConfigurationResult
}

internal class InternetVideoDecoderLifecycle(
    private val isCurrentSession: () -> Boolean,
    private val postToUi: (() -> Unit) -> Unit,
    private val configureDecoder:
        (
            ProductVideoConfiguration,
            () -> Boolean,
            (() -> ProductVideoDecision) -> ProductVideoDecision,
            (InternetDecoderConfigurationResult) -> Unit,
        ) -> Unit,
    private val scheduleTimeout: (Runnable, Long) -> Unit,
    private val cancelTimeout: (Runnable) -> Unit,
    private val surfaceReadinessTimeoutMs: Long = DEFAULT_SURFACE_READINESS_TIMEOUT_MS,
    private val nowNs: () -> Long = System::nanoTime,
) {
    private var surfaceRevision = 0L
    private var nextAttemptId = 0L
    private var pendingConfiguration: PendingConfiguration? = null

    val hasPendingConfiguration: Boolean
        get() = pendingConfiguration != null

    init {
        require(surfaceReadinessTimeoutMs > 0L) { "surfaceReadinessTimeoutMs must be positive" }
    }

    fun onVideoConfiguration(
        configuration: ProductVideoConfiguration,
        effect: ProductVideoConfigurationEffect,
        completion: (ProductVideoDecision) -> Unit,
    ) {
        if (!isCurrentSession()) {
            completion(ProductVideoDecision.reject("stale_session"))
            return
        }
        postToUi ui@{
            if (!isCurrentSession()) {
                completion(ProductVideoDecision.reject("stale_session"))
                return@ui
            }
            if (pendingConfiguration != null) {
                completion(ProductVideoDecision.reject("video_configuration_pending"))
                return@ui
            }
            PendingConfiguration(configuration, effect, completion).also { pending ->
                pendingConfiguration = pending
                startConfiguration(pending)
            }
        }
    }

    fun onSurfaceReady() {
        dispatch {
            surfaceRevision++
            pendingConfiguration?.let(::startConfiguration)
        }
    }

    fun invalidate(reason: String = "stale_session") {
        postToUi {
            pendingConfiguration?.let { pending ->
                finish(pending, ProductVideoDecision.reject(reason))
            }
        }
    }

    private fun startConfiguration(pending: PendingConfiguration) {
        if (pendingConfiguration !== pending || pending.attemptInFlight) return
        if (pending.surfaceWaitDeadlineNs > 0L) {
            if (nowNs() >= pending.surfaceWaitDeadlineNs) {
                finish(pending, ProductVideoDecision.reject("decoder_surface_timeout"))
                return
            }
            cancelSurfaceTimeout(pending)
        }
        if (!isCurrentSession()) {
            finish(pending, ProductVideoDecision.reject("stale_session"))
            return
        }
        pending.attemptInFlight = true
        val attemptId = ++nextAttemptId
        val attemptSurfaceRevision = surfaceRevision
        pending.attemptId = attemptId
        val isAttemptCurrent = {
            pendingConfiguration === pending &&
                pending.attemptId == attemptId &&
                pending.attemptInFlight &&
                isCurrentSession()
        }
        val commitEffect = { publish: () -> ProductVideoDecision ->
            if (!isAttemptCurrent()) {
                ProductVideoDecision.reject("stale_session")
            } else {
                pending.effect.commit {
                    if (isAttemptCurrent()) publish() else ProductVideoDecision.reject("stale_session")
                }
            }
        }
        try {
            configureDecoder(
                pending.configuration,
                isAttemptCurrent,
                commitEffect,
            ) { result ->
                postToUi {
                    handleConfigurationResult(
                        pending = pending,
                        attemptId = attemptId,
                        attemptSurfaceRevision = attemptSurfaceRevision,
                        result = result,
                    )
                }
            }
        } catch (failure: RuntimeException) {
            pending.attemptInFlight = false
            finish(
                pending,
                ProductVideoDecision.reject(failure.message ?: "decoder_configuration_failure"),
            )
        }
    }

    private fun handleConfigurationResult(
        pending: PendingConfiguration,
        attemptId: Long,
        attemptSurfaceRevision: Long,
        result: InternetDecoderConfigurationResult,
    ) {
        if (pendingConfiguration !== pending || pending.attemptId != attemptId) return
        pending.attemptInFlight = false
        if (!isCurrentSession()) {
            finish(pending, ProductVideoDecision.reject("stale_session"))
            return
        }
        when (result) {
            is InternetDecoderConfigurationResult.Completed -> finish(pending, result.decision)
            InternetDecoderConfigurationResult.RetryWhenSurfaceReady -> {
                if (surfaceRevision > attemptSurfaceRevision) {
                    startConfiguration(pending)
                } else {
                    beginSurfaceWait(pending)
                }
            }
        }
    }

    private fun beginSurfaceWait(pending: PendingConfiguration) {
        if (pendingConfiguration !== pending || pending.surfaceWaitDeadlineNs > 0L) return
        pending.surfaceWaitDeadlineNs = nowNs() + surfaceReadinessTimeoutMs * NANOS_PER_MILLISECOND
        scheduleTimeout(pending.timeout, surfaceReadinessTimeoutMs)
    }

    private fun finish(
        pending: PendingConfiguration,
        decision: ProductVideoDecision,
    ) {
        if (pendingConfiguration !== pending) return
        pendingConfiguration = null
        cancelSurfaceTimeout(pending)
        pending.completion(decision)
    }

    private fun cancelSurfaceTimeout(pending: PendingConfiguration) {
        if (pending.surfaceWaitDeadlineNs <= 0L) return
        pending.surfaceWaitDeadlineNs = 0L
        cancelTimeout(pending.timeout)
    }

    private fun dispatch(action: () -> Unit) {
        if (!isCurrentSession()) return
        postToUi ui@{
            if (!isCurrentSession()) return@ui
            action()
        }
    }

    private inner class PendingConfiguration(
        val configuration: ProductVideoConfiguration,
        val effect: ProductVideoConfigurationEffect,
        val completion: (ProductVideoDecision) -> Unit,
    ) {
        var attemptInFlight = false
        var attemptId = 0L
        var surfaceWaitDeadlineNs = 0L
        val timeout =
            Runnable {
                postToUi {
                    if (pendingConfiguration === this &&
                        surfaceWaitDeadlineNs > 0L &&
                        nowNs() >= surfaceWaitDeadlineNs
                    ) {
                        finish(this, ProductVideoDecision.reject("decoder_surface_timeout"))
                    }
                }
            }
    }

    companion object {
        const val DEFAULT_SURFACE_READINESS_TIMEOUT_MS = 1_500L
        private const val NANOS_PER_MILLISECOND = 1_000_000L
    }
}
