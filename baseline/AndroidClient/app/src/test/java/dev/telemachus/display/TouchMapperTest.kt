package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class TouchMapperTest {
    @Test
    fun `maps center through horizontal letterbox`() {
        val point =
            TouchMapper.map(
                x = 1000f,
                y = 600f,
                viewWidth = 2000,
                viewHeight = 1200,
                videoWidth = 2000,
                videoHeight = 1124,
            )

        assertEquals(0.5f, point.x, 0.0001f)
        assertEquals(0.5f, point.y, 0.0001f)
    }

    @Test
    fun `maps picture edges rather than black bars`() {
        val contentTop = (1200f - 1124f) / 2f
        val top = TouchMapper.map(1000f, contentTop, 2000, 1200, 2000, 1124)
        val bottom = TouchMapper.map(1000f, contentTop + 1124f, 2000, 1200, 2000, 1124)

        assertEquals(0f, top.y, 0.0001f)
        assertEquals(1f, bottom.y, 0.0001f)
    }

    @Test
    fun `clamps touches in black bars to video bounds`() {
        val above = TouchMapper.map(1000f, 0f, 2000, 1200, 2000, 1124)
        val below = TouchMapper.map(1000f, 1200f, 2000, 1200, 2000, 1124)

        assertEquals(0f, above.y, 0.0001f)
        assertEquals(1f, below.y, 0.0001f)
    }

    @Test
    fun `handles pillarboxing`() {
        val point = TouchMapper.map(500f, 500f, 2000, 1000, 1000, 1000)

        assertEquals(0f, point.x, 0.0001f)
        assertEquals(0.5f, point.y, 0.0001f)
    }

    @Test
    fun `fill mode maps cropped video rather than clamping to visible bounds`() {
        val left =
            TouchMapper.map(
                x = 0f,
                y = 500f,
                viewWidth = 1000,
                viewHeight = 1000,
                videoWidth = 2000,
                videoHeight = 1000,
                scaleMode = VideoScaleMode.FILL,
            )

        assertEquals(0.25f, left.x, 0.0001f)
        assertEquals(0.5f, left.y, 0.0001f)
    }

    @Test
    fun `fit corners inverse map through every render rotation`() {
        val expected =
            mapOf(
                0 to listOf(point(0f, 0f), point(1f, 0f), point(1f, 1f), point(0f, 1f)),
                90 to listOf(point(0f, 1f), point(0f, 0f), point(1f, 0f), point(1f, 1f)),
                180 to listOf(point(1f, 1f), point(0f, 1f), point(0f, 0f), point(1f, 0f)),
                270 to listOf(point(1f, 0f), point(1f, 1f), point(0f, 1f), point(0f, 0f)),
            )

        expected.forEach { (rotation, expectedCorners) ->
            val quarterTurn = rotation == 90 || rotation == 270
            val viewWidth = if (quarterTurn) 600 else 1200
            val viewHeight = if (quarterTurn) 1200 else 600
            assertCorners(
                expected = expectedCorners,
                viewWidth = viewWidth,
                viewHeight = viewHeight,
                scaleMode = VideoScaleMode.FIT,
                rotation = rotation,
            )
        }
    }

    @Test
    fun `fill corners inverse map cropped video through every render rotation`() {
        val expected =
            mapOf(
                0 to listOf(point(0.25f, 0f), point(0.75f, 0f), point(0.75f, 1f), point(0.25f, 1f)),
                90 to listOf(point(0.25f, 1f), point(0.25f, 0f), point(0.75f, 0f), point(0.75f, 1f)),
                180 to listOf(point(0.75f, 1f), point(0.25f, 1f), point(0.25f, 0f), point(0.75f, 0f)),
                270 to listOf(point(0.75f, 0f), point(0.75f, 1f), point(0.25f, 1f), point(0.25f, 0f)),
            )

        expected.forEach { (rotation, expectedCorners) ->
            assertCorners(
                expected = expectedCorners,
                viewWidth = 1000,
                viewHeight = 1000,
                scaleMode = VideoScaleMode.FILL,
                rotation = rotation,
            )
        }
    }

    private fun assertCorners(
        expected: List<TouchMapper.Point>,
        viewWidth: Int,
        viewHeight: Int,
        scaleMode: VideoScaleMode,
        rotation: Int,
    ) {
        val actual =
            listOf(
                0f to 0f,
                viewWidth.toFloat() to 0f,
                viewWidth.toFloat() to viewHeight.toFloat(),
                0f to viewHeight.toFloat(),
            ).map { (x, y) ->
                TouchMapper.map(
                    x = x,
                    y = y,
                    viewWidth = viewWidth,
                    viewHeight = viewHeight,
                    videoWidth = 2000,
                    videoHeight = 1000,
                    scaleMode = scaleMode,
                    renderRotation = rotation,
                )
            }

        expected.zip(actual).forEachIndexed { index, (expectedPoint, actualPoint) ->
            assertEquals("corner $index x at $rotation degrees", expectedPoint.x, actualPoint.x, 0.0001f)
            assertEquals("corner $index y at $rotation degrees", expectedPoint.y, actualPoint.y, 0.0001f)
        }
    }

    private fun point(
        x: Float,
        y: Float,
    ) = TouchMapper.Point(x, y)
}
