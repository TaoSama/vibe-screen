package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ClipboardPreviewPolicyTest {
    @Test
    fun wrapsEachClipboardPreviewLineIndependently() {
        val firstLine = "a".repeat(ClipboardPreviewPolicy.PREVIEW_LINE_CHARS + 1)
        val secondLine = "b".repeat(ClipboardPreviewPolicy.PREVIEW_LINE_CHARS * 2)

        assertEquals(
            listOf(
                "a".repeat(ClipboardPreviewPolicy.PREVIEW_LINE_CHARS),
                "a",
                "b".repeat(ClipboardPreviewPolicy.PREVIEW_LINE_CHARS),
                "b".repeat(ClipboardPreviewPolicy.PREVIEW_LINE_CHARS),
            ).joinToString("\n"),
            ClipboardPreviewPolicy.wrap(firstLine + "\n" + secondLine),
        )
    }

    @Test
    fun doesNotTruncateAtThePreviewCharacterLimit() {
        val text = "x".repeat(ClipboardPreviewPolicy.MAX_PREVIEW_CHARS)
        val preview = ClipboardPreviewPolicy.preview(text) { "TRUNCATED:" + it }

        assertFalse(preview.startsWith("TRUNCATED:"))
        assertEquals(
            expectedWrappedText('x', ClipboardPreviewPolicy.MAX_PREVIEW_CHARS),
            preview,
        )
    }

    @Test
    fun truncatesAfterThePreviewCharacterLimitBeforeWrapping() {
        val text = "x".repeat(ClipboardPreviewPolicy.MAX_PREVIEW_CHARS) + "y"
        val preview = ClipboardPreviewPolicy.preview(text) { "TRUNCATED:" + it }

        assertTrue(preview.startsWith("TRUNCATED:"))
        assertEquals(
            "TRUNCATED:" + expectedWrappedText('x', ClipboardPreviewPolicy.MAX_PREVIEW_CHARS),
            preview,
        )
        assertFalse(preview.contains("y"))
    }

    @Test
    fun emptyClipboardPreviewStaysEmpty() {
        assertEquals("", ClipboardPreviewPolicy.preview("") { "TRUNCATED:" + it })
    }

    private fun expectedWrappedText(
        character: Char,
        count: Int,
    ): String =
        character
            .toString()
            .repeat(count)
            .chunked(ClipboardPreviewPolicy.PREVIEW_LINE_CHARS)
            .joinToString("\n")
}
