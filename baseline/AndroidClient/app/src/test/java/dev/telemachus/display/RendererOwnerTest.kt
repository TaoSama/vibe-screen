package dev.telemachus.display

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
        assertEquals(RendererDecoderPresentation(configEpoch = 5, renderTargetGeneration = second.generation), owner.currentDecoderPresentation)
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
}
