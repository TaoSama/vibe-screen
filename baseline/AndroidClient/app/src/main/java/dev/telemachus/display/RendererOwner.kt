package dev.telemachus.display

/**
 * Owns renderer-facing state and admission decisions without depending on
 * Android views, surfaces, transports, protocol sessions, or decoder codecs.
 */
internal class RendererOwner(
    scaleMode: () -> VideoScaleMode = { VideoScaleMode.FIT },
    renderRotation: () -> ClientRotation = { ClientRotation.FOLLOW_HOST },
    viewportLayout: (Int, Int, Int, Int, VideoScaleMode, ClientRotation) -> ViewportPolicy.Layout =
        { parentWidth, parentHeight, videoWidth, videoHeight, mode, rotation ->
            ViewportPolicy.layout(
                parentWidth = parentWidth,
                parentHeight = parentHeight,
                videoWidth = videoWidth,
                videoHeight = videoHeight,
                scaleMode = mode,
                renderRotation = rotation.degrees,
            )
        },
) {
    private val lock = Any()
    private val viewportState = RendererViewportState(scaleMode, renderRotation, viewportLayout)

    private var displayGeometry: RendererDisplayGeometry? = null
    private var renderTarget: Any? = null
    private var renderTargetGeneration = 0L
    private var decoderPresentation: RendererDecoderPresentation? = null

    val displayWidth: Int
        get() = synchronized(lock) { displayGeometry?.width ?: 0 }

    val displayHeight: Int
        get() = synchronized(lock) { displayGeometry?.height ?: 0 }

    val displayRotation: Int
        get() = synchronized(lock) { displayGeometry?.rotation ?: 0 }

    val activeDecoderConfigEpoch: Long
        get() = synchronized(lock) { decoderPresentation?.configEpoch ?: 0L }

    val currentDecoderPresentation: RendererDecoderPresentation?
        get() = synchronized(lock) { decoderPresentation }

    val currentLayout: ViewportPolicy.Layout?
        get() = synchronized(lock) { viewportState.currentLayout }

    fun updateDisplayGeometry(geometry: RendererDisplayGeometry) {
        synchronized(lock) {
            displayGeometry = geometry
            viewportState.updateDisplaySize(geometry.width, geometry.height)
        }
    }

    fun clearDisplayGeometry() {
        synchronized(lock) {
            displayGeometry = null
            viewportState.clear()
        }
    }

    fun updateViewportParent(
        width: Int,
        height: Int,
    ): ViewportPolicy.Layout? =
        synchronized(lock) {
            viewportState.updateParentSize(width, height)
            viewportState.updateScaleMode()
            viewportState.updateRenderRotation()
            viewportState.currentLayout
        }

    fun mapTouchPoint(
        x: Float,
        y: Float,
        viewWidth: Int,
        viewHeight: Int,
    ): TouchMapper.Point {
        val geometry = synchronized(lock) { displayGeometry }
        return TouchMapper.map(
            x = x,
            y = y,
            viewWidth = viewWidth,
            viewHeight = viewHeight,
            videoWidth = geometry?.width ?: 0,
            videoHeight = geometry?.height ?: 0,
            scaleMode = viewportState.scaleModeSnapshot(),
            renderRotation =
                ViewportPolicy.surfaceTransformRotation(
                    viewportState.renderRotationSnapshot(),
                ),
        )
    }

    fun rotationPolicy(): RendererRotationPolicy {
        val hostRotation = synchronized(lock) { displayGeometry?.rotation ?: 0 }
        return rotationPolicy(
            hostRotation = hostRotation,
            clientRotation = viewportState.renderRotationSnapshot(),
        )
    }

    fun rotationPolicy(hostRotation: Int): RendererRotationPolicy {
        val clientRotation = synchronized(lock) { viewportState.renderRotationSnapshot() }
        return rotationPolicy(hostRotation, clientRotation)
    }

    private fun rotationPolicy(
        hostRotation: Int,
        clientRotation: ClientRotation,
    ): RendererRotationPolicy {
        val effectiveRotation = ViewportPolicy.effectiveRotation(hostRotation, clientRotation)
        return RendererRotationPolicy(
            effectiveRotation = effectiveRotation,
            screenOrientation = ViewportPolicy.screenOrientationFor(effectiveRotation),
            surfaceRotation = ViewportPolicy.surfaceTransformRotation(clientRotation),
        )
    }

    fun publishRenderTarget(target: Any): RendererRenderTargetSnapshot =
        synchronized(lock) {
            if (renderTarget !== target) {
                renderTarget = target
                renderTargetGeneration += 1
                decoderPresentation = null
            }
            RendererRenderTargetSnapshot(renderTargetGeneration)
        }

    fun invalidateRenderTarget(target: Any): RendererRenderTargetSnapshot =
        synchronized(lock) {
            if (renderTarget !== target) {
                return@synchronized RendererRenderTargetSnapshot(renderTargetGeneration)
            }
            renderTarget = null
            renderTargetGeneration += 1
            decoderPresentation = null
            RendererRenderTargetSnapshot(renderTargetGeneration)
        }

    fun snapshotRenderTarget(target: Any): RendererRenderTargetSnapshot? =
        synchronized(lock) {
            if (renderTarget === target) RendererRenderTargetSnapshot(renderTargetGeneration) else null
        }

    fun acceptsRenderTarget(
        target: Any,
        generation: Long,
    ): Boolean = synchronized(lock) { renderTarget === target && renderTargetGeneration == generation }

    fun renderTargetReadyAction(readiness: RendererRenderTargetReadiness): RendererRenderTargetReadyAction =
        synchronized(lock) {
            if (renderTarget == null || readiness.decoderConfigured) {
                return@synchronized RendererRenderTargetReadyAction.NONE
            }
            when (readiness.flow) {
                RendererRenderTargetFlow.INTERNET ->
                    when {
                        readiness.internetConfigurationPending -> {
                            RendererRenderTargetReadyAction.RETRY_PENDING_INTERNET_CONFIGURATION
                        }
                        readiness.internetConfigurationAvailable && displayGeometry.isUsableForDecoderConfiguration -> {
                            RendererRenderTargetReadyAction.CONFIGURE_INTERNET_DECODER
                        }
                        else -> RendererRenderTargetReadyAction.NONE
                    }
                RendererRenderTargetFlow.LOCAL ->
                    when {
                        readiness.localConfigurationPending -> {
                            RendererRenderTargetReadyAction.RETRY_PENDING_LOCAL_CONFIGURATION
                        }
                        readiness.localConfigurationAvailable -> RendererRenderTargetReadyAction.CONFIGURE_LOCAL_DECODER
                        else -> RendererRenderTargetReadyAction.NONE
                    }
            }
        }

    fun commitDecoderPresentation(presentation: RendererDecoderPresentation): Boolean =
        synchronized(lock) {
            if (renderTarget == null || renderTargetGeneration != presentation.renderTargetGeneration) return@synchronized false
            decoderPresentation = presentation
            true
        }

    fun installDecoderPresentation(presentation: RendererDecoderPresentation?): Boolean =
        synchronized(lock) {
            if (presentation == null) {
                decoderPresentation = null
                true
            } else if (renderTarget != null && renderTargetGeneration == presentation.renderTargetGeneration) {
                decoderPresentation = presentation
                true
            } else {
                false
            }
        }

    fun clearDecoderPresentation() {
        synchronized(lock) { decoderPresentation = null }
    }

    fun localFrameDecision(
        sessionCurrent: Boolean,
        configEpoch: Long,
        decoderAvailable: Boolean,
    ): RendererFramePresentationDecision =
        synchronized(lock) {
            when {
                !sessionCurrent -> RendererFramePresentationDecision.Drop(RendererFrameDropReason.STALE_SESSION, releaseFrame = true)
                decoderPresentation == null -> {
                    RendererFramePresentationDecision.Drop(RendererFrameDropReason.DECODER_NOT_CONFIGURED, releaseFrame = true)
                }
                decoderPresentation?.configEpoch != configEpoch -> {
                    RendererFramePresentationDecision.Drop(RendererFrameDropReason.STALE_CONFIG_EPOCH, releaseFrame = true)
                }
                !decoderAvailable -> RendererFramePresentationDecision.Drop(RendererFrameDropReason.DECODER_UNAVAILABLE, releaseFrame = true)
                else -> RendererFramePresentationDecision.Present
            }
        }

    fun internetFrameDecision(
        sessionCurrent: Boolean,
        frameSessionEpoch: Long,
        activeSessionEpoch: Long,
        decoderAvailable: Boolean,
    ): RendererFramePresentationDecision =
        synchronized(lock) {
            when {
                !sessionCurrent -> RendererFramePresentationDecision.Drop(RendererFrameDropReason.STALE_SESSION, releaseFrame = false)
                frameSessionEpoch != activeSessionEpoch -> {
                    RendererFramePresentationDecision.Drop(RendererFrameDropReason.STALE_SESSION_EPOCH, releaseFrame = false)
                }
                decoderPresentation == null -> {
                    RendererFramePresentationDecision.Drop(RendererFrameDropReason.DECODER_NOT_CONFIGURED, releaseFrame = false)
                }
                !decoderAvailable -> RendererFramePresentationDecision.Drop(RendererFrameDropReason.DECODER_UNAVAILABLE, releaseFrame = false)
                else -> RendererFramePresentationDecision.Present
            }
        }
}

internal enum class RendererFrameDropReason {
    STALE_SESSION,
    STALE_CONFIG_EPOCH,
    STALE_SESSION_EPOCH,
    DECODER_NOT_CONFIGURED,
    DECODER_UNAVAILABLE,
}

internal enum class RendererRenderTargetFlow {
    LOCAL,
    INTERNET,
}

internal data class RendererRenderTargetReadiness(
    val flow: RendererRenderTargetFlow,
    val decoderConfigured: Boolean,
    val localConfigurationPending: Boolean,
    val localConfigurationAvailable: Boolean,
    val internetConfigurationPending: Boolean,
    val internetConfigurationAvailable: Boolean,
)

internal data class RendererRotationPolicy(
    val effectiveRotation: Int,
    val screenOrientation: Int,
    val surfaceRotation: Int,
)

internal enum class RendererRenderTargetReadyAction {
    NONE,
    RETRY_PENDING_LOCAL_CONFIGURATION,
    CONFIGURE_LOCAL_DECODER,
    RETRY_PENDING_INTERNET_CONFIGURATION,
    CONFIGURE_INTERNET_DECODER,
}

internal val RendererFrameDropReason.logToken: String
    get() =
        when (this) {
            RendererFrameDropReason.STALE_SESSION -> "stale_session"
            RendererFrameDropReason.STALE_CONFIG_EPOCH -> "stale_config_epoch"
            RendererFrameDropReason.STALE_SESSION_EPOCH -> "stale_session_epoch"
            RendererFrameDropReason.DECODER_NOT_CONFIGURED -> "decoder_not_configured"
            RendererFrameDropReason.DECODER_UNAVAILABLE -> "decoder_unavailable"
        }

internal data class RendererDisplayGeometry(
    val width: Int,
    val height: Int,
    val rotation: Int,
)

private val RendererDisplayGeometry?.isUsableForDecoderConfiguration: Boolean
    get() = this != null && width > 0 && height > 0

internal data class RendererRenderTargetSnapshot(
    val generation: Long,
)

internal data class RendererDecoderPresentation(
    val configEpoch: Long,
    val renderTargetGeneration: Long,
)

internal sealed interface RendererFramePresentationDecision {
    data object Present : RendererFramePresentationDecision

    data class Drop(
        val reason: RendererFrameDropReason,
        val releaseFrame: Boolean,
    ) : RendererFramePresentationDecision
}
