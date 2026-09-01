package dev.telemachus.display

import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

internal data class EncodedVideoConfigurationSnapshot(
    val width: Int,
    val height: Int,
    val configEpoch: Long,
)

internal class EncodedVideoConfigurationState {
    private val current = AtomicReference<EncodedVideoConfigurationSnapshot?>()

    fun publish(
        width: Int,
        height: Int,
        configEpoch: Long,
    ): EncodedVideoConfigurationSnapshot =
        EncodedVideoConfigurationSnapshot(width, height, configEpoch).also(current::set)

    fun snapshot(): EncodedVideoConfigurationSnapshot? = current.get()

    fun isCurrent(snapshot: EncodedVideoConfigurationSnapshot): Boolean = current.get() === snapshot

    fun clear() {
        current.set(null)
    }
}

internal data class InternetDecoderPresentationState<Decoder, Configuration>(
    val decoder: Decoder?,
    val configuration: Configuration?,
    val rendererPresentation: RendererDecoderPresentation?,
    val displayWidth: Int,
    val displayHeight: Int,
    val displayRotation: Int,
    val connected: Boolean,
)

internal fun <State> commitInternetDecoderPresentation(
    nextState: State,
    captureState: () -> State,
    installState: (State) -> Boolean,
    restoreState: (attempted: State, previous: State) -> Unit,
    presentState: (previous: State) -> Unit,
): State? {
    val previousState = captureState()
    if (!installState(nextState)) return null
    try {
        presentState(previousState)
    } catch (failure: Throwable) {
        try {
            restoreState(nextState, previousState)
        } catch (rollbackFailure: Throwable) {
            failure.addSuppressed(rollbackFailure)
        }
        throw failure
    }
    return previousState
}

/**
 * Owns the Android decoder's product-session presentation state. Platform
 * objects create and drive the actual decoder, while this boundary owns the
 * admission gate, render-target generation, configuration epochs, presentation
 * commit/rollback, and frame routing decisions.
 */
internal class DecoderPresentationOwner<Decoder : Any, InternetConfiguration : Any>(
    private val rendererOwner: RendererOwner,
    private val internetConfigurationEpoch: (InternetConfiguration) -> Long,
) {
    private val decoderUseGate = DecoderUseGate<Decoder>()
    private val configurationGeneration = AtomicLong()
    private val encodedVideoConfigurationState = EncodedVideoConfigurationState()
    private val currentRenderTargetRef = AtomicReference<Any?>()
    private val internetVideoConfiguration = AtomicReference<InternetConfiguration?>()

    val displayWidth: Int
        get() = rendererOwner.displayWidth

    val displayHeight: Int
        get() = rendererOwner.displayHeight

    val displayRotation: Int
        get() = rendererOwner.displayRotation

    val activeDecoderConfigEpoch: Long
        get() = rendererOwner.activeDecoderConfigEpoch

    fun currentDecoder(): Decoder? = decoderUseGate.current()

    fun currentRenderTarget(): Any? = currentRenderTargetRef.get()

    fun internetConfiguration(): InternetConfiguration? = internetVideoConfiguration.get()

    fun publishRenderTarget(target: Any): RendererRenderTargetSnapshot {
        currentRenderTargetRef.set(target)
        return rendererOwner.publishRenderTarget(target)
    }

    fun invalidateRenderTarget(target: Any): RendererRenderTargetSnapshot {
        currentRenderTargetRef.compareAndSet(target, null)
        return rendererOwner.invalidateRenderTarget(target)
    }

    fun snapshotRenderTarget(target: Any): RendererRenderTargetSnapshot? =
        rendererOwner.snapshotRenderTarget(target)

    fun updateLocalDisplayGeometry(geometry: StreamDisplayGeometry) {
        rendererOwner.updateDisplayGeometry(
            RendererDisplayGeometry(
                width = geometry.logicalWidth,
                height = geometry.logicalHeight,
                rotation = geometry.rotation,
            ),
        )
    }

    fun publishLocalVideoConfiguration(
        width: Int,
        height: Int,
        configEpoch: Long,
    ): EncodedVideoConfigurationSnapshot =
        encodedVideoConfigurationState.publish(width, height, configEpoch)

    fun localVideoConfigurationSnapshot(): EncodedVideoConfigurationSnapshot? =
        encodedVideoConfigurationState.snapshot()

    fun clearLocalVideoConfiguration() {
        encodedVideoConfigurationState.clear()
    }

    fun beginDecoderConfigurationAttempt(): Long = configurationGeneration.incrementAndGet()

    fun hasBlockingActiveDecoder(attempt: DecoderLifecycleAttempt): Boolean =
        !attempt.allowsActiveDecoderReplacement && currentDecoder() != null

    fun isLocalAttemptCurrent(
        attempt: DecoderLifecycleAttempt,
        configuration: EncodedVideoConfigurationSnapshot,
        isSessionCurrent: () -> Boolean,
        isRenderTargetUsable: () -> Boolean,
    ): Boolean =
        isRenderTargetUsable() &&
            acceptsAttemptRenderTarget(attempt) &&
            configurationGeneration.get() == attempt.configurationGeneration &&
            encodedVideoConfigurationState.isCurrent(configuration) &&
            isSessionCurrent()

    fun canRetryLocalAttempt(
        configuration: EncodedVideoConfigurationSnapshot,
        isSessionCurrent: () -> Boolean,
    ): Boolean = isSessionCurrent() && encodedVideoConfigurationState.isCurrent(configuration)

    fun isPublishedLocalDecoderCurrent(
        decoder: Decoder,
        attempt: DecoderLifecycleAttempt,
        configuration: EncodedVideoConfigurationSnapshot,
        isSessionCurrent: () -> Boolean,
        isRenderTargetUsable: () -> Boolean,
    ): Boolean =
        isSessionCurrent() &&
            currentDecoder() === decoder &&
            rendererOwner.activeDecoderConfigEpoch == attempt.configEpoch &&
            configurationGeneration.get() == attempt.configurationGeneration &&
            encodedVideoConfigurationState.isCurrent(configuration) &&
            currentRenderTargetRef.get() === attempt.surfaceToken &&
            isRenderTargetUsable() &&
            acceptsAttemptRenderTarget(attempt)

    fun publishLocalDecoder(
        decoder: Decoder,
        attempt: DecoderLifecycleAttempt,
    ): Boolean =
        decoderUseGate.installIf(decoder) {
            rendererOwner.commitDecoderPresentation(
                RendererDecoderPresentation(
                    configEpoch = attempt.configEpoch,
                    renderTargetGeneration = attempt.surfaceGeneration,
                ),
            )
        }

    fun isInternetAttemptCurrent(
        attempt: DecoderLifecycleAttempt,
        isSessionCurrent: () -> Boolean,
        isRenderTargetUsable: () -> Boolean,
    ): Boolean =
        isSessionCurrent() &&
            attempt.isConfigurationCurrent() &&
            configurationGeneration.get() == attempt.configurationGeneration &&
            currentRenderTargetRef.get() === attempt.surfaceToken &&
            isRenderTargetUsable() &&
            acceptsAttemptRenderTarget(attempt)

    fun canRetryInternetAttempt(
        attempt: DecoderLifecycleAttempt,
        isSessionCurrent: () -> Boolean,
    ): Boolean =
        isSessionCurrent() &&
            attempt.isConfigurationCurrent() &&
            configurationGeneration.get() == attempt.configurationGeneration

    fun isPublishedInternetDecoderCurrent(
        decoder: Decoder,
        attempt: DecoderLifecycleAttempt,
        isSessionCurrent: () -> Boolean,
        isRenderTargetUsable: () -> Boolean,
    ): Boolean =
        isSessionCurrent() &&
            attempt.isConfigurationCurrent() &&
            configurationGeneration.get() == attempt.configurationGeneration &&
            currentDecoder() === decoder &&
            rendererOwner.activeDecoderConfigEpoch == attempt.configEpoch &&
            internetVideoConfiguration.get()?.let(internetConfigurationEpoch) == attempt.configEpoch &&
            currentRenderTargetRef.get() === attempt.surfaceToken &&
            isRenderTargetUsable() &&
            acceptsAttemptRenderTarget(attempt)

    fun publishInternetDecoder(
        decoder: Decoder,
        attempt: DecoderLifecycleAttempt,
        configuration: InternetConfiguration,
        displayWidth: Int,
        displayHeight: Int,
        displayRotation: Int,
        currentConnected: Boolean,
        applyConnected: (Boolean) -> Unit,
        presentState: (InternetDecoderPresentationState<Decoder, InternetConfiguration>) -> Unit,
        restoreState: (InternetDecoderPresentationState<Decoder, InternetConfiguration>) -> Unit,
    ): Boolean {
        val nextState =
            InternetDecoderPresentationState(
                decoder = decoder,
                configuration = configuration,
                rendererPresentation =
                    RendererDecoderPresentation(
                        configEpoch = attempt.configEpoch,
                        renderTargetGeneration = attempt.surfaceGeneration,
                    ),
                displayWidth = displayWidth,
                displayHeight = displayHeight,
                displayRotation = displayRotation,
                connected = true,
            )
        return commitInternetDecoderPresentation(
            nextState = nextState,
            currentConnected = currentConnected,
            applyConnected = applyConnected,
            presentState = presentState,
            restoreState = restoreState,
        )
    }

    fun updateCurrentDecoderScaleMode(updateScaleMode: (Decoder) -> Unit) {
        decoderUseGate.withCurrent(updateScaleMode)
    }

    fun detachCurrentDecoder(): Decoder? {
        configurationGeneration.incrementAndGet()
        val decoder = decoderUseGate.clear()
        rendererOwner.clearDecoderPresentation()
        return decoder
    }

    fun releaseCurrentDecoder(releaseDecoder: (Decoder) -> Unit) {
        detachCurrentDecoder()?.let(releaseDecoder)
    }

    fun detachExpectedDecoderForQuarantine(expected: Decoder?): Boolean {
        val cleared = decoderUseGate.compareAndSet(expected, null)
        if (cleared) {
            rendererOwner.clearDecoderPresentation()
            configurationGeneration.incrementAndGet()
        }
        return cleared
    }

    fun clearInternetConfiguration() {
        internetVideoConfiguration.set(null)
    }

    fun clearDisplayGeometry() {
        rendererOwner.clearDisplayGeometry()
    }

    fun routeLocalFrame(
        sessionCurrent: Boolean,
        configEpoch: Long,
        decode: (Decoder) -> Unit,
        onDrop: (RendererFramePresentationDecision.Drop) -> Unit,
    ): Boolean {
        val usedDecoder =
            decoderUseGate.withCurrent { decoder ->
                when (
                    val decision =
                        rendererOwner.localFrameDecision(
                            sessionCurrent = sessionCurrent,
                            configEpoch = configEpoch,
                            decoderAvailable = true,
                        )
                ) {
                    RendererFramePresentationDecision.Present -> decode(decoder)
                    is RendererFramePresentationDecision.Drop -> onDrop(decision)
                }
                true
            } ?: false
        if (!usedDecoder) {
            val decision =
                rendererOwner.localFrameDecision(
                    sessionCurrent = sessionCurrent,
                    configEpoch = configEpoch,
                    decoderAvailable = false,
                )
            if (decision is RendererFramePresentationDecision.Drop) onDrop(decision)
        }
        return usedDecoder
    }

    fun routeInternetFrame(
        sessionCurrent: Boolean,
        frameSessionEpoch: Long,
        activeSessionEpoch: Long,
        decode: (Decoder) -> Unit,
    ): Boolean {
        val usedDecoder =
            decoderUseGate.withCurrent { decoder ->
                when (
                    rendererOwner.internetFrameDecision(
                        sessionCurrent = sessionCurrent,
                        frameSessionEpoch = frameSessionEpoch,
                        activeSessionEpoch = activeSessionEpoch,
                        decoderAvailable = true,
                    )
                ) {
                    RendererFramePresentationDecision.Present -> decode(decoder)
                    is RendererFramePresentationDecision.Drop -> Unit
                }
                true
            } ?: false
        if (!usedDecoder) {
            rendererOwner.internetFrameDecision(
                sessionCurrent = sessionCurrent,
                frameSessionEpoch = frameSessionEpoch,
                activeSessionEpoch = activeSessionEpoch,
                decoderAvailable = false,
            )
        }
        return usedDecoder
    }

    private fun commitInternetDecoderPresentation(
        nextState: InternetDecoderPresentationState<Decoder, InternetConfiguration>,
        currentConnected: Boolean,
        applyConnected: (Boolean) -> Unit,
        presentState: (InternetDecoderPresentationState<Decoder, InternetConfiguration>) -> Unit,
        restoreState: (InternetDecoderPresentationState<Decoder, InternetConfiguration>) -> Unit,
    ): Boolean {
        return commitInternetDecoderPresentation(
            nextState = nextState,
            captureState = { captureInternetDecoderPresentation(currentConnected) },
            installState = { installInternetDecoderPresentation(it, applyConnected) },
            restoreState = { attempted, previous ->
                restoreInternetDecoderPresentation(attempted, previous, applyConnected)
                restoreState(previous)
            },
            presentState = presentState,
        ) != null
    }

    private fun captureInternetDecoderPresentation(
        connected: Boolean,
    ): InternetDecoderPresentationState<Decoder, InternetConfiguration> =
        InternetDecoderPresentationState(
            decoder = currentDecoder(),
            configuration = internetVideoConfiguration.get(),
            rendererPresentation = rendererOwner.currentDecoderPresentation,
            displayWidth = rendererOwner.displayWidth,
            displayHeight = rendererOwner.displayHeight,
            displayRotation = rendererOwner.displayRotation,
            connected = connected,
        )

    private fun installInternetDecoderPresentation(
        state: InternetDecoderPresentationState<Decoder, InternetConfiguration>,
        applyConnected: (Boolean) -> Unit,
    ): Boolean {
        if (!decoderUseGate.installIf(state.decoder) {
                rendererOwner.installDecoderPresentation(state.rendererPresentation)
            }
        ) {
            return false
        }
        installConfigurationAndGeometry(state, applyConnected)
        return true
    }

    private fun restoreInternetDecoderPresentation(
        attempted: InternetDecoderPresentationState<Decoder, InternetConfiguration>,
        previous: InternetDecoderPresentationState<Decoder, InternetConfiguration>,
        applyConnected: (Boolean) -> Unit,
    ) {
        check(
            decoderUseGate.replaceIfCurrent(attempted.decoder, previous.decoder) {
                rendererOwner.installDecoderPresentation(previous.rendererPresentation)
            },
        ) { "Internet decoder changed while presentation rollback was in progress" }
        installConfigurationAndGeometry(previous, applyConnected)
    }

    private fun installConfigurationAndGeometry(
        state: InternetDecoderPresentationState<Decoder, InternetConfiguration>,
        applyConnected: (Boolean) -> Unit,
    ) {
        internetVideoConfiguration.set(state.configuration)
        if (state.displayWidth > 0 && state.displayHeight > 0) {
            rendererOwner.updateDisplayGeometry(
                RendererDisplayGeometry(
                    width = state.displayWidth,
                    height = state.displayHeight,
                    rotation = state.displayRotation,
                ),
            )
        } else {
            rendererOwner.clearDisplayGeometry()
        }
        applyConnected(state.connected)
    }

    private fun acceptsAttemptRenderTarget(attempt: DecoderLifecycleAttempt): Boolean =
        rendererOwner.acceptsRenderTarget(attempt.surfaceToken, attempt.surfaceGeneration)
}
