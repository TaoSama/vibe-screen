package dev.telemachus.display.internet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Test
import org.junit.Assert.assertThrows

class BestEffortCleanupTest {
    @Test
    fun `executes every cleanup and aggregates later failures`() {
        val calls = mutableListOf<Int>()
        val first = IllegalStateException("first")
        val second = IllegalArgumentException("second")

        val thrown =
            assertThrows(IllegalStateException::class.java) {
                runBestEffort(
                    { calls += 1; throw first },
                    { calls += 2 },
                    { calls += 3; throw second },
                    { calls += 4 },
                )
            }

        assertSame(first, thrown)
        assertEquals(listOf(1, 2, 3, 4), calls)
        assertEquals(listOf(second), thrown.suppressed.toList())
    }
}
