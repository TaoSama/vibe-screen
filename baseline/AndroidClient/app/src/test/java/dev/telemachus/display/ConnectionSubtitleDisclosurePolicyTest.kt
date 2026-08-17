package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionSubtitleDisclosurePolicyTest {
    @Test
    fun `portrait Internet starts collapsed with an end ellipsis`() {
        val presentation =
            ConnectionSubtitleDisclosurePolicy.resolve(
                connectionMode = ConnectionMode.INTERNET,
                stackedPortrait = true,
                requestedExpanded = false,
            )

        assertTrue(presentation.expandable)
        assertFalse(presentation.expanded)
        assertEquals(ConnectionSubtitleDisclosurePolicy.COLLAPSED_MAX_LINES, presentation.maxLines)
        assertTrue(presentation.ellipsizeEnd)
    }

    @Test
    fun `explicitly expanded portrait Internet shows the complete description`() {
        val presentation =
            ConnectionSubtitleDisclosurePolicy.resolve(
                connectionMode = ConnectionMode.INTERNET,
                stackedPortrait = true,
                requestedExpanded = true,
            )

        assertTrue(presentation.expandable)
        assertTrue(presentation.expanded)
        assertEquals(ConnectionSubtitleDisclosurePolicy.MAX_LINES_UNLIMITED, presentation.maxLines)
        assertFalse(presentation.ellipsizeEnd)
    }

    @Test
    fun `landscape Internet and every local mode always show complete guidance`() {
        val presentations =
            listOf(
                ConnectionSubtitleDisclosurePolicy.resolve(ConnectionMode.INTERNET, false, false),
                ConnectionSubtitleDisclosurePolicy.resolve(ConnectionMode.USB, true, false),
                ConnectionSubtitleDisclosurePolicy.resolve(ConnectionMode.WIRELESS, true, false),
            )

        presentations.forEach { presentation ->
            assertFalse(presentation.expandable)
            assertFalse(presentation.expanded)
            assertEquals(ConnectionSubtitleDisclosurePolicy.MAX_LINES_UNLIMITED, presentation.maxLines)
            assertFalse(presentation.ellipsizeEnd)
        }
    }

    @Test
    fun `disclosure state resets after expansion`() {
        val state = ConnectionSubtitleDisclosureState()

        state.toggle()
        assertTrue(state.expanded)

        state.reset()
        assertFalse(state.expanded)
    }
}
