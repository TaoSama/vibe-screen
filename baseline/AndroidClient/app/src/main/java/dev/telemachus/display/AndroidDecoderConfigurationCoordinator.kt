package dev.telemachus.display

/**
 * Coordinates Android decoder configuration attempts without depending on
 * Android framework, concrete codec, concrete sessions, or transports. The activity
 * supplies platform objects and UI side effects through the request adapters.
 */
internal class AndroidDecoderConfigurationCoordinator<Decoder : Any, InternetConfiguration : Any>(
    private val decoderPresentationOwner: DecoderPresentationOwner<Decoder, InternetConfiguration>,
    private val executeDecoderWork: (() -> Unit) -> Unit,
    private val postCommit: (() -> Unit) -> Unit,
    private val updateScaleMode: (Decoder) -> Unit,
    private val commitStartup: (Decoder, (() -> Boolean)) -> DecoderStartupCommitResult,
    private val releaseDecoder: (Decoder) -> Unit,
    private val recordStructuralFailure: (StreamCodec, DecoderFailure, () -> Boolean) -> Boolean,
) {
    fun <Session : Any> configureLocal(
        request: LocalDecoderConfigurationRequest<Session, Decoder>,
        createDecoder: (DecoderCreationCallbacks<Decoder>) -> Decoder,
        completion: (AndroidDecoderConfigurationResult) -> Unit = {},
    ) {
        val session = request.session ?: return completion(AndroidDecoderConfigurationResult.Failed(STALE_SESSION_REASON))
        if (!request.isSessionCurrent(session, request.sessionGeneration)) {
            completion(AndroidDecoderConfigurationResult.Failed(STALE_SESSION_REASON))
            return
        }
        val configuration = request.configuration
        if (configuration == null || configuration.configEpoch != request.expectedConfigEpoch) {
            completion(AndroidDecoderConfigurationResult.Failed(STALE_VIDEO_CONFIGURATION_REASON))
            return
        }
        val renderTargetGeneration = request.renderTargetGeneration
        if (renderTargetGeneration == null) {
            completion(AndroidDecoderConfigurationResult.RetryWhenSurfaceReady)
            return
        }
        val configurationGeneration = decoderPresentationOwner.beginDecoderConfigurationAttempt()
        val attempt =
            DecoderLifecycleAttempt(
                sessionToken = session,
                sessionGeneration = request.sessionGeneration,
                surfaceToken = request.renderTarget,
                surfaceGeneration = renderTargetGeneration,
                configurationToken = configuration,
                configurationGeneration = configurationGeneration,
                configEpoch = request.expectedConfigEpoch,
                codec = request.codec,
                failSessionOnFailure = request.failSessionOnFailure,
                isConfigurationCurrent = request.isConfigurationCurrent,
            )
        val lifecycleOwner = localLifecycleOwner(request, session, configuration)
        scheduleConfiguration(
            plan =
                DecoderConfigurationPlan(
                    attempt = attempt,
                    lifecycleOwner = lifecycleOwner,
                    createDecoder = createDecoder,
                    publishConfigurationCommit = request.publishConfigurationCommit,
                    onConfigured = request.onConfigured,
                    completion = completion,
                ),
        )
    }

    fun <Session : Any> configureInternet(
        request: InternetDecoderConfigurationRequest<Session, Decoder, InternetConfiguration>,
        createDecoder: (DecoderCreationCallbacks<Decoder>) -> Decoder,
        completion: (AndroidDecoderConfigurationResult) -> Unit = {},
    ) {
        request.unsupportedCodecReason?.let { reason ->
            completion(AndroidDecoderConfigurationResult.Failed(reason))
            return
        }
        val session = request.session ?: return completion(AndroidDecoderConfigurationResult.Failed(STALE_SESSION_REASON))
        if (!request.isSessionCurrent()) {
            completion(AndroidDecoderConfigurationResult.Failed(STALE_SESSION_REASON))
            return
        }
        val renderTargetGeneration = request.renderTargetGeneration
        if (renderTargetGeneration == null || !request.isRenderTargetUsable()) {
            completion(AndroidDecoderConfigurationResult.RetryWhenSurfaceReady)
            return
        }
        val configurationGeneration = decoderPresentationOwner.beginDecoderConfigurationAttempt()
        val attempt =
            DecoderLifecycleAttempt(
                sessionToken = session,
                sessionGeneration = request.sessionGeneration,
                surfaceToken = request.renderTarget,
                surfaceGeneration = renderTargetGeneration,
                configurationToken = request.configuration,
                configurationGeneration = configurationGeneration,
                configEpoch = request.configEpoch,
                codec = request.codec,
                failSessionOnFailure = false,
                allowsActiveDecoderReplacement = true,
                isConfigurationCurrent = request.isConfigurationCurrent,
            )
        val lifecycleOwner = internetLifecycleOwner(request)
        scheduleConfiguration(
            plan =
                DecoderConfigurationPlan(
                    attempt = attempt,
                    lifecycleOwner = lifecycleOwner,
                    createDecoder = createDecoder,
                    publishConfigurationCommit = request.publishConfigurationCommit,
                    onConfigured = {},
                    completion = completion,
                ),
        )
    }

    private fun scheduleConfiguration(plan: DecoderConfigurationPlan<Decoder>) {
        executeDecoderWork {
            when (val admission = plan.lifecycleOwner.admitAttempt(plan.attempt)) {
                DecoderLifecycleAttemptAdmission.Start -> Unit
                DecoderLifecycleAttemptAdmission.RetryWhenSurfaceReady -> {
                    plan.completeOnOwnerThread(AndroidDecoderConfigurationResult.RetryWhenSurfaceReady)
                    return@executeDecoderWork
                }
                is DecoderLifecycleAttemptAdmission.Failed -> {
                    plan.completeOnOwnerThread(AndroidDecoderConfigurationResult.Failed(admission.reason))
                    return@executeDecoderWork
                }
            }

            val callbacks = DecoderCreationCallbacks(plan.lifecycleOwner, plan.attempt, postCommit)
            val decoder =
                try {
                    plan.createDecoder(callbacks)
                } catch (failure: Throwable) {
                    postCommit {
                        val result = plan.lifecycleOwner.handleCreationFailure(plan.attempt, failure)
                        plan.completion(result.toConfigurationResult())
                    }
                    return@executeDecoderWork
                }

            postCommit {
                var commitDecision: DecoderConfigurationCommitDecision? = null
                val result =
                    plan.lifecycleOwner.commitCreatedDecoder(
                        attempt = plan.attempt,
                        decoder = decoder,
                        publishConfigurationCommit = { publish ->
                            plan.publishConfigurationCommit {
                                if (publish()) {
                                    DecoderConfigurationCommitDecision.ACCEPT
                                } else {
                                    DecoderConfigurationCommitDecision.reject(STALE_DECODER_CONFIGURATION_REASON)
                                }
                            }.also { decision -> commitDecision = decision }.accepted
                        },
                    )
                val configurationResult = result.toConfigurationResult(commitDecision)
                if (configurationResult is AndroidDecoderConfigurationResult.Configured) {
                    try {
                        plan.onConfigured(decoder)
                    } catch (failure: Exception) {
                        if (plan.lifecycleOwner.runIfActive(decoder, plan.attempt) {}) {
                            plan.lifecycleOwner.handleCreationFailure(plan.attempt, failure)
                        }
                    }
                }
                plan.completion(configurationResult)
            }
        }
    }

    private fun <Session : Any> localLifecycleOwner(
        request: LocalDecoderConfigurationRequest<Session, Decoder>,
        session: Session,
        configuration: EncodedVideoConfigurationSnapshot,
    ): AndroidDecoderLifecycleOwner<Decoder> =
        AndroidDecoderLifecycleOwner(
            object : AndroidDecoderLifecyclePort<Decoder> {
                override fun hasBlockingActiveDecoder(attempt: DecoderLifecycleAttempt): Boolean =
                    decoderPresentationOwner.hasBlockingActiveDecoder(attempt)

                override fun isAttemptCurrent(attempt: DecoderLifecycleAttempt): Boolean =
                    decoderPresentationOwner.isLocalAttemptCurrent(
                        attempt = attempt,
                        configuration = configuration,
                        isSessionCurrent = { request.isSessionCurrent(session, attempt.sessionGeneration) },
                        isRenderTargetUsable = request.isRenderTargetUsable,
                    )

                override fun canRetryAttempt(attempt: DecoderLifecycleAttempt): Boolean =
                    decoderPresentationOwner.canRetryLocalAttempt(
                        configuration = configuration,
                        isSessionCurrent = { request.isSessionCurrent(session, attempt.sessionGeneration) },
                    )

                override fun isPublishedDecoderCurrent(
                    decoder: Decoder,
                    attempt: DecoderLifecycleAttempt,
                ): Boolean =
                    decoderPresentationOwner.isPublishedLocalDecoderCurrent(
                        decoder = decoder,
                        attempt = attempt,
                        configuration = configuration,
                        isSessionCurrent = { request.isSessionCurrent(session, attempt.sessionGeneration) },
                        isRenderTargetUsable = request.isRenderTargetUsable,
                    )

                override fun updateScaleMode(decoder: Decoder) = this@AndroidDecoderConfigurationCoordinator.updateScaleMode(decoder)

                override fun commitStartup(
                    decoder: Decoder,
                    publish: () -> Boolean,
                ): DecoderStartupCommitResult = this@AndroidDecoderConfigurationCoordinator.commitStartup(decoder, publish)

                override fun publishDecoder(
                    decoder: Decoder,
                    attempt: DecoderLifecycleAttempt,
                ): Boolean = decoderPresentationOwner.publishLocalDecoder(decoder, attempt)

                override fun releaseDecoder(decoder: Decoder) = this@AndroidDecoderConfigurationCoordinator.releaseDecoder(decoder)

                override fun recordStructuralFailure(
                    codec: StreamCodec,
                    failure: DecoderFailure,
                    isCurrentConfiguration: () -> Boolean,
                ): Boolean = this@AndroidDecoderConfigurationCoordinator.recordStructuralFailure(codec, failure, isCurrentConfiguration)

                override fun reportInitializationFailure(
                    error: Exception,
                    failSession: Boolean,
                ) = request.reportInitializationFailure(error, failSession)
            },
        )

    private fun <Session : Any> internetLifecycleOwner(
        request: InternetDecoderConfigurationRequest<Session, Decoder, InternetConfiguration>,
    ): AndroidDecoderLifecycleOwner<Decoder> =
        AndroidDecoderLifecycleOwner(
            object : AndroidDecoderLifecyclePort<Decoder> {
                override fun hasBlockingActiveDecoder(attempt: DecoderLifecycleAttempt): Boolean =
                    decoderPresentationOwner.hasBlockingActiveDecoder(attempt)

                override fun isAttemptCurrent(attempt: DecoderLifecycleAttempt): Boolean =
                    decoderPresentationOwner.isInternetAttemptCurrent(
                        attempt = attempt,
                        isSessionCurrent = request.isSessionCurrent,
                        isRenderTargetUsable = request.isRenderTargetUsable,
                    )

                override fun canRetryAttempt(attempt: DecoderLifecycleAttempt): Boolean =
                    decoderPresentationOwner.canRetryInternetAttempt(
                        attempt = attempt,
                        isSessionCurrent = request.isSessionCurrent,
                    )

                override fun isPublishedDecoderCurrent(
                    decoder: Decoder,
                    attempt: DecoderLifecycleAttempt,
                ): Boolean =
                    decoderPresentationOwner.isPublishedInternetDecoderCurrent(
                        decoder = decoder,
                        attempt = attempt,
                        isSessionCurrent = request.isSessionCurrent,
                        isRenderTargetUsable = request.isRenderTargetUsable,
                    )

                override fun updateScaleMode(decoder: Decoder) = this@AndroidDecoderConfigurationCoordinator.updateScaleMode(decoder)

                override fun commitStartup(
                    decoder: Decoder,
                    publish: () -> Boolean,
                ): DecoderStartupCommitResult = this@AndroidDecoderConfigurationCoordinator.commitStartup(decoder, publish)

                override fun publishDecoder(
                    decoder: Decoder,
                    attempt: DecoderLifecycleAttempt,
                ): Boolean =
                    decoderPresentationOwner.publishInternetDecoder(
                        decoder = decoder,
                        attempt = attempt,
                        configuration = request.configuration,
                        displayWidth = request.displayWidth,
                        displayHeight = request.displayHeight,
                        displayRotation = request.displayRotation,
                        currentConnected = request.currentConnected,
                        applyConnected = request.applyConnected,
                        presentState = request.presentState,
                        restoreState = request.restoreState,
                        afterCommit = request.afterCommit,
                    )

                override fun releaseDecoder(decoder: Decoder) = this@AndroidDecoderConfigurationCoordinator.releaseDecoder(decoder)

                override fun recordStructuralFailure(
                    codec: StreamCodec,
                    failure: DecoderFailure,
                    isCurrentConfiguration: () -> Boolean,
                ): Boolean = this@AndroidDecoderConfigurationCoordinator.recordStructuralFailure(codec, failure, isCurrentConfiguration)

                override fun reportInitializationFailure(
                    error: Exception,
                    failSession: Boolean,
                ) = request.reportInitializationFailure(error, failSession)
            },
        )

    private fun DecoderLifecycleCommitResult.toConfigurationResult(
        commitDecision: DecoderConfigurationCommitDecision? = null,
    ): AndroidDecoderConfigurationResult =
        when (this) {
            DecoderLifecycleCommitResult.Configured -> AndroidDecoderConfigurationResult.Configured
            DecoderLifecycleCommitResult.RetryWhenSurfaceReady -> AndroidDecoderConfigurationResult.RetryWhenSurfaceReady
            is DecoderLifecycleCommitResult.Failed ->
                AndroidDecoderConfigurationResult.Failed(
                    commitDecision?.takeUnless { it.accepted }?.rejectionReason ?: reason,
                )
        }

    private fun DecoderConfigurationPlan<Decoder>.completeOnOwnerThread(result: AndroidDecoderConfigurationResult) {
        postCommit { completion(result) }
    }

    private data class DecoderConfigurationPlan<Decoder : Any>(
        val attempt: DecoderLifecycleAttempt,
        val lifecycleOwner: AndroidDecoderLifecycleOwner<Decoder>,
        val createDecoder: (DecoderCreationCallbacks<Decoder>) -> Decoder,
        val publishConfigurationCommit: ((() -> DecoderConfigurationCommitDecision) -> DecoderConfigurationCommitDecision),
        val onConfigured: (Decoder) -> Unit,
        val completion: (AndroidDecoderConfigurationResult) -> Unit,
    )

    private companion object {
        const val STALE_SESSION_REASON = "stale_session"
        const val STALE_VIDEO_CONFIGURATION_REASON = "stale_video_configuration"
        const val STALE_DECODER_CONFIGURATION_REASON = "stale_decoder_configuration"
    }
}

internal data class LocalDecoderConfigurationRequest<Session : Any, Decoder : Any>(
    val session: Session?,
    val sessionGeneration: Long,
    val renderTarget: Any,
    val renderTargetGeneration: Long?,
    val configuration: EncodedVideoConfigurationSnapshot?,
    val expectedConfigEpoch: Long,
    val codec: StreamCodec,
    val failSessionOnFailure: Boolean,
    val isSessionCurrent: (Session, Long) -> Boolean,
    val isRenderTargetUsable: () -> Boolean,
    val isConfigurationCurrent: () -> Boolean,
    val publishConfigurationCommit: ((() -> DecoderConfigurationCommitDecision) -> DecoderConfigurationCommitDecision),
    val reportInitializationFailure: (Exception, Boolean) -> Unit,
    val onConfigured: (Decoder) -> Unit = {},
)

internal data class InternetDecoderConfigurationRequest<Session : Any, Decoder : Any, InternetConfiguration : Any>(
    val session: Session?,
    val sessionGeneration: Long,
    val renderTarget: Any,
    val renderTargetGeneration: Long?,
    val configuration: InternetConfiguration,
    val configEpoch: Long,
    val codec: StreamCodec,
    val unsupportedCodecReason: String? = null,
    val displayWidth: Int,
    val displayHeight: Int,
    val displayRotation: Int,
    val currentConnected: Boolean,
    val applyConnected: (Boolean) -> Unit,
    val presentState: (InternetDecoderPresentationState<Decoder, InternetConfiguration>) -> Unit,
    val restoreState: (InternetDecoderPresentationState<Decoder, InternetConfiguration>) -> Unit,
    val afterCommit: (InternetDecoderPresentationState<Decoder, InternetConfiguration>) -> Unit = {},
    val isSessionCurrent: () -> Boolean,
    val isRenderTargetUsable: () -> Boolean,
    val isConfigurationCurrent: () -> Boolean,
    val publishConfigurationCommit: ((() -> DecoderConfigurationCommitDecision) -> DecoderConfigurationCommitDecision),
    val reportInitializationFailure: (Exception, Boolean) -> Unit,
)

internal sealed interface AndroidDecoderConfigurationResult {
    data object Configured : AndroidDecoderConfigurationResult

    data object RetryWhenSurfaceReady : AndroidDecoderConfigurationResult

    data class Failed(
        val reason: String,
    ) : AndroidDecoderConfigurationResult
}

internal data class DecoderConfigurationCommitDecision(
    val accepted: Boolean,
    val rejectionReason: String = "",
) {
    init {
        require(accepted || rejectionReason.isNotBlank()) { "Rejected decoder configuration commit requires a reason" }
    }

    companion object {
        val ACCEPT = DecoderConfigurationCommitDecision(true)

        fun reject(reason: String) = DecoderConfigurationCommitDecision(false, reason)
    }
}

internal class DecoderCreationCallbacks<Decoder : Any> internal constructor(
    private val lifecycleOwner: AndroidDecoderLifecycleOwner<Decoder>,
    private val attempt: DecoderLifecycleAttempt,
    private val postActiveCallback: (() -> Unit) -> Unit,
) {
    fun onFrameDecoded(
        frame: ByteArray,
        action: (ByteArray) -> Unit,
    ) {
        action(frame)
    }

    fun onKeyframeRequired(
        decoder: Decoder,
        force: Boolean,
        reason: String,
        action: (force: Boolean, reason: String) -> Unit,
    ) {
        postActiveCallback {
            lifecycleOwner.runIfActive(decoder, attempt) {
                action(force, reason)
            }
        }
    }

    fun onCodecFailure(
        decoder: Decoder,
        failure: DecoderFailure,
        action: (decoder: Decoder, failure: DecoderFailure) -> Unit,
    ) {
        postActiveCallback {
            lifecycleOwner.runIfActive(decoder, attempt) {
                lifecycleOwner.recordActiveStructuralFailure(decoder, attempt, failure)
                action(decoder, failure)
            }
        }
    }
}
