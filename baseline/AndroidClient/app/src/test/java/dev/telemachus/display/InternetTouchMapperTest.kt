package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class InternetTouchMapperTest {
    @Test
    fun `internet input applies fill crop and client rotation`() {
        val point =
            InternetTouchMapper.map(
                x = 0f,
                y = 0f,
                viewWidth = 1_000,
                viewHeight = 1_000,
                videoWidth = 2_000,
                videoHeight = 1_000,
                scaleMode = VideoScaleMode.FILL,
                clientRotation = ClientRotation.CLOCKWISE_90,
            )

        assertEquals(0.25f, point.x, 0.0001f)
        assertEquals(1f, point.y, 0.0001f)
    }
}
