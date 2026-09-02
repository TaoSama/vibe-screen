package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RendererViewportStateTest {
    @Test
    fun `fit layout matches parent-bounded rotated video`() {
        val state =
            RendererViewportState(
                scaleMode = { VideoScaleMode.FIT },
                renderRotation = { ClientRotation.CLOCKWISE_90 },
            )
        state.updateDisplaySize(2_000, 1_000)
        state.updateParentSize(1_200, 1_200)

        assertEquals(
            ViewportPolicy.Layout(
                viewport = ViewportPolicy.Size(600, 1_200),
                surface = ViewportPolicy.Size(1_200, 600),
            ),
            state.currentLayout,
        )
    }

    @Test
    fun `fill layout covers parent and swaps surface for quarter turn`() {
        val state =
            RendererViewportState(
                scaleMode = { VideoScaleMode.FILL },
                renderRotation = { ClientRotation.CLOCKWISE_90 },
            )
        state.updateDisplaySize(2_000, 1_000)
        state.updateParentSize(1_200, 800)

        assertEquals(
            ViewportPolicy.Layout(
                viewport = ViewportPolicy.Size(1_200, 800),
                surface = ViewportPolicy.Size(800, 1_200),
            ),
            state.currentLayout,
        )
    }

    @Test
    fun `physical and virtual display layouts use only client local rotation`() {
        val cases =
            listOf(
                Triple(
                    1_920,
                    1_080,
                    ViewportPolicy.Layout(
                        viewport = ViewportPolicy.Size(1_200, 675),
                        surface = ViewportPolicy.Size(1_200, 675),
                    ) to ViewportPolicy.Layout(
                        viewport = ViewportPolicy.Size(675, 1_200),
                        surface = ViewportPolicy.Size(1_200, 675),
                    ),
                ),
                Triple(
                    2_000,
                    1_200,
                    ViewportPolicy.Layout(
                        viewport = ViewportPolicy.Size(1_200, 720),
                        surface = ViewportPolicy.Size(1_200, 720),
                    ) to ViewportPolicy.Layout(
                        viewport = ViewportPolicy.Size(720, 1_200),
                        surface = ViewportPolicy.Size(1_200, 720),
                    ),
                ),
            )

        cases.forEach { (displayWidth, displayHeight, expectedLayouts) ->
            ClientRotation.entries.forEach { clientRotation ->
                val state =
                    RendererViewportState(
                        scaleMode = { VideoScaleMode.FIT },
                        renderRotation = { clientRotation },
                    )

                state.updateDisplaySize(displayWidth, displayHeight)
                state.updateParentSize(1_200, 1_200)

                val expected =
                    if (ViewportPolicy.surfaceTransformRotation(clientRotation) % 180 == 0) {
                        expectedLayouts.first
                    } else {
                        expectedLayouts.second
                    }
                assertEquals("display=${displayWidth}x$displayHeight client=$clientRotation", expected, state.currentLayout)
            }
        }
    }

    @Test
    fun `fill layout uses client rotation without host rotation input`() {
        ClientRotation.entries.forEach { clientRotation ->
            val state =
                RendererViewportState(
                    scaleMode = { VideoScaleMode.FILL },
                    renderRotation = { clientRotation },
                )
            state.updateDisplaySize(2_000, 1_200)
            state.updateParentSize(1_264, 2_800)

            val expectedSurface =
                if (ViewportPolicy.surfaceTransformRotation(clientRotation) % 180 == 0) {
                    ViewportPolicy.Size(1_264, 2_800)
                } else {
                    ViewportPolicy.Size(2_800, 1_264)
                }

            assertEquals(
                "client=$clientRotation",
                ViewportPolicy.Layout(
                    viewport = ViewportPolicy.Size(1_264, 2_800),
                    surface = expectedSurface,
                ),
                state.currentLayout,
            )
        }
    }

    @Test
    fun `parent size change recalculates without touching display geometry`() {
        var scaleReads = 0
        var rotationReads = 0
        val state =
            RendererViewportState(
                scaleMode = {
                    scaleReads++
                    VideoScaleMode.FIT
                },
                renderRotation = {
                    rotationReads++
                    ClientRotation.FOLLOW_HOST
                },
            )
        state.updateDisplaySize(1_920, 1_080)
        state.updateParentSize(2_400, 1_080)
        assertEquals(1, scaleReads)
        assertEquals(1, rotationReads)

        state.updateParentSize(2_000, 1_000)

        assertEquals(
            ViewportPolicy.layout(
                parentWidth = 2_000,
                parentHeight = 1_000,
                videoWidth = 1_920,
                videoHeight = 1_080,
                scaleMode = VideoScaleMode.FIT,
                renderRotation = ClientRotation.FOLLOW_HOST.degrees,
            ),
            state.currentLayout,
        )
        assertEquals(2, scaleReads)
        assertEquals(2, rotationReads)
    }

    @Test
    fun `scale and rotation snapshots come from renderer viewport inputs`() {
        var mode = VideoScaleMode.FIT
        var rotation = ClientRotation.FOLLOW_HOST
        val state =
            RendererViewportState(
                scaleMode = { mode },
                renderRotation = { rotation },
            )

        assertEquals(VideoScaleMode.FIT, state.scaleModeSnapshot())
        assertEquals(ClientRotation.FOLLOW_HOST, state.renderRotationSnapshot())

        mode = VideoScaleMode.FILL
        rotation = ClientRotation.COUNTER_CLOCKWISE_90

        assertEquals(VideoScaleMode.FILL, state.scaleModeSnapshot())
        assertEquals(ClientRotation.COUNTER_CLOCKWISE_90, state.renderRotationSnapshot())
    }

    @Test
    fun `stale display geometry is blank and cannot produce layout`() {
        val state = RendererViewportState()
        assertFalse(state.isReady)
        assertNull(state.currentLayout)
        state.updateParentSize(1_200, 1_200)
        assertFalse(state.isReady)
        assertNull(state.currentLayout)
    }

    @Test
    fun `clear resets presentation state without crashing`() {
        val state =
            RendererViewportState(
                scaleMode = { VideoScaleMode.FILL },
                renderRotation = { ClientRotation.UPSIDE_DOWN },
            )
        state.updateDisplaySize(1_920, 1_080)
        state.updateParentSize(1_200, 1_200)
        assertTrue(state.isReady)

        state.clear()

        assertFalse(state.isReady)
        assertNull(state.currentLayout)
    }
}
