package dev.telemachus.display

import java.util.concurrent.atomic.AtomicBoolean

internal sealed interface MainSessionDecoderConfigurationResult {
    data object Configured : MainSessionDecoderConfigurationResult

    data object RetryWhenSurfaceReady : MainSessionDecoderConfigurationResult

    data class Failed(
        val reason: String,
    ) : MainSessionDecoderConfigurationResult
}

internal class MainSessionDisplayLifecycle(
    private val isCurrentSession: () -> Boolean,
    private val postToUi: (() -> Unit) -> Unit,
    private val updateVideoConfiguration: (StreamVideoConfiguration) -> Unit,
    private val releaseDecoder: () -> Unit,
    private val configureDecoder:
        (
            StreamVideoConfiguration,
            () -> Boolean,
            (() -> Boolean) -> Boolean,
            (MainSessionDecoderConfigurationResult) -> Unit,
        ) -> Unit,
    private val updateDisplayGeometry: (StreamDisplayGeometry) -> Unit,
    private val scheduleTimeout: (Runnable, Long) -> Unit = { _, _ -> },
    private val cancelTimeout: (Runnable) -> Unit = {},
    private val surfaceReadinessTimeoutMs: Long = DEFAULT_SURFACE_READINESS_TIMEOUT_MS,
    private val nowNs: () -> Long = System::nanoTime,
) {
    private var surfaceRevision = 0L
    private var nextAttemptId = 0L
    private var pendingVideoConfiguration: PendingVideoConfiguration? = null

    val hasPendingVideoConfiguration: Boolean
        get() = pendingVideoConfiguration != null

    init {
        require(surfaceReadinessTimeoutMs > 0L) { "surfaceReadinessTimeoutMs must be positive" }
    }

    fun onVideoConfiguration(
        configuration: StreamVideoConfiguration,
        completion: (StreamVideoConfigurationDecision) -> Unit,
    ) {
        onVideoConfiguration(
            configuration,
            CallbackVideoConfigurationCommit(completion),
        )
    }

    fun onVideoConfiguration(
        configuration: StreamVideoConfiguration,
        commit: StreamVideoConfigurationCommit,
    ) {
        if (!isCurrentSession()) {
            commit.complete(StreamVideoConfigurationDecision.reject("stale_session"))
            return
        }
        postToUi ui@{
            if (!isCurrentSession()) {
                commit.complete(StreamVideoConfigurationDecision.reject("stale_session"))
                return@ui
            }
            pendingVideoConfiguration?.let { pending ->
                if (!commit.canSupersedePendingConfiguration) {
                    commit.complete(StreamVideoConfigurationDecision.reject("video_configuration_pending"))
                    return@ui
                }
                retire(pending)
            }
            try {
                updateVideoConfiguration(configuration)
                releaseDecoder()
                val pending =
                    PendingVideoConfiguration(
                        configuration = configuration,
                        commit = commit,
                    )
                pendingVideoConfiguration = pending
                startDecoderConfiguration(pending)
            } catch (failure: RuntimeException) {
                commit.complete(
                    StreamVideoConfigurationDecision.reject(
                        failure.message ?: "decoder_configuration_failure",
                    ),
                )
            }
        }
    }

    fun onDisplayGeometry(geometry: StreamDisplayGeometry) {
        dispatch { updateDisplayGeometry(geometry) }
    }

    fun onSurfaceReady() {
        dispatch {
            surfaceRevision++
            pendingVideoConfiguration?.let(::startDecoderConfiguration)
        }
    }

    fun invalidate(reason: String = "stale_session") {
        postToUi {
            pendingVideoConfiguration?.let {
                finish(
                    it,
                    StreamVideoConfigurationDecision.reject(reason),
                )
            }
        }
    }

    private fun startDecoderConfiguration(pending: PendingVideoConfiguration) {
        if (pendingVideoConfiguration !== pending || pending.attemptInFlight) return
        if (!pending.commit.isPending()) {
            abandon(pending)
            return
        }
        if (pending.surfaceWaitDeadlineNs > 0L) {
            if (nowNs() >= pending.surfaceWaitDeadlineNs) {
                finish(pending, StreamVideoConfigurationDecision.reject("decoder_surface_timeout"))
                return
            }
            cancelSurfaceTimeout(pending)
        }
        if (!isCurrentSession()) {
            finish(pending, StreamVideoConfigurationDecision.reject("stale_session"))
            return
        }
        pending.attemptInFlight = true
        val attemptId = ++nextAttemptId
        val attemptSurfaceRevision = surfaceRevision
        pending.attemptId = attemptId
        try {
            val isAttemptCurrent = {
                pendingVideoConfiguration === pending &&
                    pending.attemptId == attemptId &&
                    pending.attemptInFlight &&
                    pending.commit.isPending() &&
                    isCurrentSession()
            }
            val tryPublishCommit = { publish: () -> Boolean ->
                isAttemptCurrent() && pending.commit.tryPublish(publish)
            }
            configureDecoder(
                pending.configuration,
                isAttemptCurrent,
                tryPublishCommit,
            ) { result ->
                postToUi {
                    handleDecoderConfigurationResult(
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
                StreamVideoConfigurationDecision.reject(
                    failure.message ?: "decoder_configuration_failure",
                ),
            )
        }
    }

    private fun handleDecoderConfigurationResult(
        pending: PendingVideoConfiguration,
        attemptId: Long,
        attemptSurfaceRevision: Long,
        result: MainSessionDecoderConfigurationResult,
    ) {
        if (pendingVideoConfiguration !== pending || pending.attemptId != attemptId) return
        pending.attemptInFlight = false
        if (!isCurrentSession()) {
            finish(pending, StreamVideoConfigurationDecision.reject("stale_session"))
            return
        }
        when (result) {
            MainSessionDecoderConfigurationResult.Configured ->
                finish(pending, StreamVideoConfigurationDecision.ACCEPTED)
            MainSessionDecoderConfigurationResult.RetryWhenSurfaceReady -> {
                if (surfaceRevision > attemptSurfaceRevision) {
                    startDecoderConfiguration(pending)
                } else {
                    beginSurfaceWait(pending)
                }
            }
            is MainSessionDecoderConfigurationResult.Failed ->
                finish(pending, StreamVideoConfigurationDecision.reject(result.reason))
        }
    }

    private fun finish(
        pending: PendingVideoConfiguration,
        decision: StreamVideoConfigurationDecision,
    ) {
        if (pendingVideoConfiguration !== pending) return
        pendingVideoConfiguration = null
        cancelSurfaceTimeout(pending)
        pending.commit.complete(decision)
    }

    private fun abandon(pending: PendingVideoConfiguration) {
        if (pendingVideoConfiguration !== pending) return
        pendingVideoConfiguration = null
        cancelSurfaceTimeout(pending)
    }

    private fun retire(pending: PendingVideoConfiguration) {
        if (pendingVideoConfiguration !== pending) return
        pendingVideoConfiguration = null
        cancelSurfaceTimeout(pending)
        pending.commit.cancel()
    }

    private fun beginSurfaceWait(pending: PendingVideoConfiguration) {
        if (pendingVideoConfiguration !== pending || pending.surfaceWaitDeadlineNs > 0L) return
        pending.surfaceWaitDeadlineNs = nowNs() + surfaceReadinessTimeoutMs * NANOS_PER_MILLISECOND
        scheduleTimeout(pending.timeout, surfaceReadinessTimeoutMs)
    }

    private fun cancelSurfaceTimeout(pending: PendingVideoConfiguration) {
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

    private inner class PendingVideoConfiguration(
        val configuration: StreamVideoConfiguration,
        val commit: StreamVideoConfigurationCommit,
    ) {
        var attemptInFlight = false
        var attemptId = 0L
        var surfaceWaitDeadlineNs = 0L
        val timeout =
            Runnable {
                postToUi {
                    if (pendingVideoConfiguration === this &&
                        surfaceWaitDeadlineNs > 0L &&
                        nowNs() >= surfaceWaitDeadlineNs
                    ) {
                        finish(
                            this,
                            StreamVideoConfigurationDecision.reject("decoder_surface_timeout"),
                        )
                    }
                }
            }
    }

    private class CallbackVideoConfigurationCommit(
        private val completion: (StreamVideoConfigurationDecision) -> Unit,
    ) : StreamVideoConfigurationCommit {
        private val pending = AtomicBoolean(true)
        private val published = AtomicBoolean()

        override fun isPending(): Boolean = pending.get()

        override fun tryPublish(publish: () -> Boolean): Boolean {
            if (!pending.get() || !published.compareAndSet(false, true)) return false
            return publish()
        }

        override fun complete(decision: StreamVideoConfigurationDecision) {
            if (decision.accepted && !published.get()) return
            if (pending.compareAndSet(true, false)) completion(decision)
        }

        override fun cancel() {
            pending.set(false)
        }
    }

    companion object {
        const val DEFAULT_SURFACE_READINESS_TIMEOUT_MS = 1_500L
        private const val NANOS_PER_MILLISECOND = 1_000_000L
    }
}
