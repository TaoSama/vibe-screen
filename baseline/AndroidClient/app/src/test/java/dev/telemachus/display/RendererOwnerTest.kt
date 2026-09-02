package dev.telemachus.display

import android.content.pm.ActivityInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RendererOwnerTest {
    @Test
    fun `display geometry and parent size produce viewport layout through renderer owner`() {
        val owner =
            RendererOwner(
                scaleMode = { VideoScaleMode.FIT },
                renderRotation = { ClientRotation.CLOCKWISE_90 },
            )

        owner.updateDisplayGeometry(RendererDisplayGeometry(width = 2_000, height = 1_000, rotation = 0))
        val layout = owner.updateViewportParent(width = 1_200, height = 1_200)

        assertEquals(2_000, owner.displayWidth)
        assertEquals(1_000, owner.displayHeight)
        assertEquals(0, owner.displayRotation)
        assertEquals(
            ViewportPolicy.Layout(
                viewport = ViewportPolicy.Size(600, 1_200),
                surface = ViewportPolicy.Size(1_200, 600),
            ),
            layout,
        )
    }

    @Test
    fun `current layout exposes last renderer viewport calculation`() {
        val owner = RendererOwner()
        assertNull(owner.currentLayout)

        owner.updateDisplayGeometry(RendererDisplayGeometry(width = 1_920, height = 1_080, rotation = 0))
        val layout = owner.updateViewportParent(width = 1_280, height = 720)

        assertEquals(layout, owner.currentLayout)
    }

    @Test
    fun `touch mapping uses renderer display geometry and client rotation`() {
        val owner =
            RendererOwner(
                scaleMode = { VideoScaleMode.FIT },
                renderRotation = { ClientRotation.CLOCKWISE_90 },
            )
        owner.updateDisplayGeometry(RendererDisplayGeometry(width = 2_000, height = 1_000, rotation = 0))

        assertEquals(
            TouchMapper.map(
                x = 600f,
                y = 600f,
                viewWidth = 1_200,
                viewHeight = 1_200,
                videoWidth = 2_000,
                videoHeight = 1_000,
                scaleMode = VideoScaleMode.FIT,
                renderRotation = 90,
            ),
            owner.mapTouchPoint(x = 600f, y = 600f, viewWidth = 1_200, viewHeight = 1_200),
        )
    }

    @Test
    fun `touch mapping covers fill crop and client rotation for internet input`() {
        val owner =
            RendererOwner(
                scaleMode = { VideoScaleMode.FILL },
                renderRotation = { ClientRotation.CLOCKWISE_90 },
            )
        owner.updateDisplayGeometry(RendererDisplayGeometry(width = 2_000, height = 1_000, rotation = 0))

        val point = owner.mapTouchPoint(x = 0f, y = 0f, viewWidth = 1_000, viewHeight = 1_000)

        assertEquals(0.25f, point.x, 0.0001f)
        assertEquals(1f, point.y, 0.0001f)
    }

    @Test
    fun `rotation policy combines host and client rotation for android adapter`() {
        val owner = RendererOwner(renderRotation = { ClientRotation.CLOCKWISE_90 })

        assertEquals(
            RendererRotationPolicy(
                effectiveRotation = 270,
                screenOrientation = ActivityInfo.SCREEN_ORIENTATION_REVERSE_PORTRAIT,
                surfaceRotation = 90,
            ),
            owner.rotationPolicy(hostRotation = 180),
        )
    }

    @Test
    fun `render target replacement invalidates stale target and decoder presentation`() {
        val owner = RendererOwner()
        val firstTarget = Any()
        val secondTarget = Any()

        val first = owner.publishRenderTarget(firstTarget)
        assertTrue(
            owner.commitDecoderPresentation(
                RendererDecoderPresentation(configEpoch = 3, renderTargetGeneration = first.generation),
            ),
        )
        val second = owner.publishRenderTarget(secondTarget)

        assertFalse(owner.acceptsRenderTarget(firstTarget, first.generation))
        assertTrue(owner.acceptsRenderTarget(secondTarget, second.generation))
        assertNull(owner.currentDecoderPresentation)
    }

    @Test
    fun `same render target keeps generation for surface size changes`() {
        val owner = RendererOwner()
        val target = Any()

        val first = owner.publishRenderTarget(target)
        val second = owner.publishRenderTarget(target)

        assertEquals(first, second)
        assertTrue(owner.acceptsRenderTarget(target, first.generation))
    }

    @Test
    fun `render target ready action waits until a target exists and decoder is absent`() {
        val owner = RendererOwner()

        assertEquals(
            RendererRenderTargetReadyAction.NONE,
            owner.renderTargetReadyAction(readiness(localConfigurationAvailable = true)),
        )

        owner.publishRenderTarget(Any())

        assertEquals(
            RendererRenderTargetReadyAction.NONE,
            owner.renderTargetReadyAction(
                readiness(
                    decoderConfigured = true,
                    localConfigurationAvailable = true,
                ),
            ),
        )
    }

    @Test
    fun `local render target ready action prefers pending configuration retry before direct decoder configuration`() {
        val owner = RendererOwner()
        owner.publishRenderTarget(Any())

        assertEquals(
            RendererRenderTargetReadyAction.RETRY_PENDING_LOCAL_CONFIGURATION,
            owner.renderTargetReadyAction(
                readiness(
                    localConfigurationPending = true,
                    localConfigurationAvailable = true,
                ),
            ),
        )
        assertEquals(
            RendererRenderTargetReadyAction.CONFIGURE_LOCAL_DECODER,
            owner.renderTargetReadyAction(readiness(localConfigurationAvailable = true)),
        )
    }

    @Test
    fun `internet render target ready action requires display geometry for direct decoder configuration`() {
        val owner = RendererOwner()
        owner.publishRenderTarget(Any())

        assertEquals(
            RendererRenderTargetReadyAction.RETRY_PENDING_INTERNET_CONFIGURATION,
            owner.renderTargetReadyAction(
                readiness(
                    flow = RendererRenderTargetFlow.INTERNET,
                    internetConfigurationPending = true,
                    internetConfigurationAvailable = true,
                ),
            ),
        )
        assertEquals(
            RendererRenderTargetReadyAction.NONE,
            owner.renderTargetReadyAction(
                readiness(
                    flow = RendererRenderTargetFlow.INTERNET,
                    internetConfigurationAvailable = true,
                ),
            ),
        )

        owner.updateDisplayGeometry(RendererDisplayGeometry(width = 1280, height = 720, rotation = 0))

        assertEquals(
            RendererRenderTargetReadyAction.CONFIGURE_INTERNET_DECODER,
            owner.renderTargetReadyAction(
                readiness(
                    flow = RendererRenderTargetFlow.INTERNET,
                    internetConfigurationAvailable = true,
                ),
            ),
        )
    }

    @Test
    fun `destroyed render target rejects late decoder presentation`() {
        val owner = RendererOwner()
        val target = Any()
        val targetSnapshot = owner.publishRenderTarget(target)

        owner.invalidateRenderTarget(target)

        assertFalse(
            owner.commitDecoderPresentation(
                RendererDecoderPresentation(configEpoch = 9, renderTargetGeneration = targetSnapshot.generation),
            ),
        )
        assertNull(owner.currentDecoderPresentation)
    }

    @Test
    fun `restoring decoder presentation fails closed after render target changes`() {
        val owner = RendererOwner()
        val firstTarget = Any()
        val first = owner.publishRenderTarget(firstTarget)
        val oldPresentation = RendererDecoderPresentation(configEpoch = 2, renderTargetGeneration = first.generation)
        assertTrue(owner.commitDecoderPresentation(oldPresentation))

        owner.publishRenderTarget(Any())
        assertFalse(owner.installDecoderPresentation(oldPresentation))

        assertNull(owner.currentDecoderPresentation)
    }

    @Test
    fun `rejected decoder presentation install keeps current presentation`() {
        val owner = RendererOwner()
        val first = owner.publishRenderTarget(Any())
        val firstPresentation = RendererDecoderPresentation(configEpoch = 2, renderTargetGeneration = first.generation)
        assertTrue(owner.commitDecoderPresentation(firstPresentation))
        val stalePresentation = RendererDecoderPresentation(configEpoch = 3, renderTargetGeneration = first.generation + 1)

        assertFalse(owner.installDecoderPresentation(stalePresentation))

        assertEquals(firstPresentation, owner.currentDecoderPresentation)
    }

    @Test
    fun `stale render target destroy does not invalidate current target`() {
        val owner = RendererOwner()
        val firstTarget = Any()
        val secondTarget = Any()
        val first = owner.publishRenderTarget(firstTarget)
        val second = owner.publishRenderTarget(secondTarget)
        assertTrue(
            owner.commitDecoderPresentation(
                RendererDecoderPresentation(configEpoch = 5, renderTargetGeneration = second.generation),
            ),
        )

        val afterStaleDestroy = owner.invalidateRenderTarget(firstTarget)

        assertEquals(second, afterStaleDestroy)
        assertFalse(owner.acceptsRenderTarget(firstTarget, first.generation))
        assertTrue(owner.acceptsRenderTarget(secondTarget, second.generation))
        assertEquals(
            RendererDecoderPresentation(configEpoch = 5, renderTargetGeneration = second.generation),
            owner.currentDecoderPresentation,
        )
    }

    @Test
    fun `local frames drop stale session stale config and missing decoder before presentation`() {
        val owner = RendererOwner()
        val target = Any()
        val targetSnapshot = owner.publishRenderTarget(target)
        assertTrue(
            owner.commitDecoderPresentation(
                RendererDecoderPresentation(configEpoch = 4, renderTargetGeneration = targetSnapshot.generation),
            ),
        )

        assertEquals(
            RendererFramePresentationDecision.Drop(RendererFrameDropReason.STALE_SESSION, releaseFrame = true),
            owner.localFrameDecision(sessionCurrent = false, configEpoch = 4, decoderAvailable = true),
        )
        assertEquals(
            RendererFramePresentationDecision.Drop(RendererFrameDropReason.STALE_CONFIG_EPOCH, releaseFrame = true),
            owner.localFrameDecision(sessionCurrent = true, configEpoch = 3, decoderAvailable = true),
        )
        assertEquals(
            RendererFramePresentationDecision.Drop(RendererFrameDropReason.DECODER_UNAVAILABLE, releaseFrame = true),
            owner.localFrameDecision(sessionCurrent = true, configEpoch = 4, decoderAvailable = false),
        )
        assertEquals(
            RendererFramePresentationDecision.Present,
            owner.localFrameDecision(sessionCurrent = true, configEpoch = 4, decoderAvailable = true),
        )
    }

    @Test
    fun `internet frames drop stale session and epoch before presentation`() {
        val owner = RendererOwner()
        val target = Any()
        val targetSnapshot = owner.publishRenderTarget(target)
        assertTrue(
            owner.commitDecoderPresentation(
                RendererDecoderPresentation(configEpoch = 11, renderTargetGeneration = targetSnapshot.generation),
            ),
        )

        assertEquals(
            RendererFramePresentationDecision.Drop(RendererFrameDropReason.STALE_SESSION, releaseFrame = false),
            owner.internetFrameDecision(
                sessionCurrent = false,
                frameSessionEpoch = 7,
                activeSessionEpoch = 7,
                decoderAvailable = true,
            ),
        )
        assertEquals(
            RendererFramePresentationDecision.Drop(RendererFrameDropReason.STALE_SESSION_EPOCH, releaseFrame = false),
            owner.internetFrameDecision(
                sessionCurrent = true,
                frameSessionEpoch = 6,
                activeSessionEpoch = 7,
                decoderAvailable = true,
            ),
        )
        assertEquals(
            RendererFramePresentationDecision.Present,
            owner.internetFrameDecision(
                sessionCurrent = true,
                frameSessionEpoch = 7,
                activeSessionEpoch = 7,
                decoderAvailable = true,
            ),
        )
    }

    private fun readiness(
        flow: RendererRenderTargetFlow = RendererRenderTargetFlow.LOCAL,
        decoderConfigured: Boolean = false,
        localConfigurationPending: Boolean = false,
        localConfigurationAvailable: Boolean = false,
        internetConfigurationPending: Boolean = false,
        internetConfigurationAvailable: Boolean = false,
    ) = RendererRenderTargetReadiness(
        flow = flow,
        decoderConfigured = decoderConfigured,
        localConfigurationPending = localConfigurationPending,
        localConfigurationAvailable = localConfigurationAvailable,
        internetConfigurationPending = internetConfigurationPending,
        internetConfigurationAvailable = internetConfigurationAvailable,
    )
}
