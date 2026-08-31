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
