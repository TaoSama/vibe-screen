package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LegacyScrollMapperTest {
    @Test
    fun `zero wheel delta does not emit a gesture`() {
        assertNull(LegacyScrollMapper.map(TouchMapper.Point(0.5f, 0.5f), 0f, 0f))
    }

    @Test
    fun `vertical wheel maps to bounded parallel two-finger movement`() {
        val gesture =
            requireNotNull(
                LegacyScrollMapper.map(
                    anchor = TouchMapper.Point(0.98f, 0.01f),
                    horizontalAxis = 0f,
                    verticalAxis = 2f,
                ),
            )

        assertEquals(1f, gesture.startSecond.x)
        assertEquals(0f, gesture.endFirst.y)
        assertEquals(0f, gesture.endSecond.y)
        assertTrue(gesture.endFirst.x in 0f..1f)
        assertTrue(gesture.endSecond.x in 0f..1f)
    }

    @Test
    fun `fractional wheel input still produces an effective movement`() {
        val gesture =
            requireNotNull(LegacyScrollMapper.map(TouchMapper.Point(0.5f, 0.5f), 0.1f, -0.1f))

        assertEquals(0.02f, kotlin.math.abs(gesture.endFirst.x - gesture.startFirst.x), 0.0001f)
        assertEquals(0.02f, kotlin.math.abs(gesture.endFirst.y - gesture.startFirst.y), 0.0001f)
    }
}
