package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.view.ContextThemeWrapper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlin.math.roundToInt
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ClipboardConfirmationDialogLayoutInstrumentedTest {
    @Test
    fun narrowAndLargeFontClipboardConfirmationKeepsContentReadableAndScrollable() {
        listOf(
            Triple(320, 640, 1.3f),
            Triple(320, 640, 2.0f),
            Triple(640, 320, 2.0f),
        ).forEach { (widthDp, heightDp, fontScale) ->
            withClipboardLayout(widthDp = widthDp, heightDp = heightDp, fontScale = fontScale) { layout ->
                layout.renderDirectReceiveConfirmation()
                layout.measureAndLayout()

                assertEquals(layout.dialogWidthPx, layout.root.measuredWidth)
                assertEquals(layout.dialogHeightPx, layout.root.measuredHeight)
                assertTrue("clipboard scroll view fills constrained dialog viewport", layout.scroll.isFillViewport)
                layout.assertTextReadable(layout.intro)
                layout.assertTextReadable(layout.direction)
                layout.assertTextReadable(layout.protection)
                layout.assertTextReadable(layout.size)
                layout.assertTextReadable(layout.preview)
                layout.assertTextReadable(layout.note)
                layout.assertLabelsOwnFields()
                layout.assertContentCanScrollIntoView()
            }
        }
    }

    @Test
    fun clipboardConfirmationCoversSendReceiveAndOverwriteCopy() {
        withClipboardLayout(widthDp = 320, heightDp = 640, fontScale = 2.0f) { layout ->
            layout.renderLanSendConfirmation()
            layout.measureAndLayout()

            assertEquals("Send", layout.context.getString(R.string.clipboard_lan_confirm_action))
            assertEquals("Copy", layout.context.getString(R.string.clipboard_receive_confirm_action))
            assertEquals(
                layout.context.getString(R.string.clipboard_confirmation_send_direction),
                layout.direction.text.toString(),
            )
            assertEquals(
                layout.context.getString(R.string.clipboard_confirmation_send_preview_unavailable),
                layout.preview.text.toString(),
            )
            layout.assertTextReadable(layout.preview)
            layout.assertLabelsOwnFields()

            layout.renderLanReceiveConfirmation()
            layout.measureAndLayout()
            assertEquals(
                layout.context.getString(R.string.clipboard_confirmation_receive_direction),
                layout.direction.text.toString(),
            )
            assertTrue(layout.size.text.contains("1.0 MiB"))
            assertEquals(
                layout.context.getString(R.string.clipboard_confirmation_receive_preview_unavailable),
                layout.preview.text.toString(),
            )
            layout.assertTextReadable(layout.protection)

            layout.renderDirectReceiveConfirmation()
            layout.measureAndLayout()
            assertTrue(layout.size.text.contains("characters"))
            assertTrue(layout.preview.text.endsWith("..."))
            layout.assertContentCanScrollIntoView()
        }
    }

    private fun withClipboardLayout(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float,
        assertion: (ClipboardMeasuredLayout) -> Unit,
    ) {
        val context = configuredContext(widthDp, heightDp, fontScale)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val parent = FrameLayout(context)
            val root = inflate(context, parent, R.layout.dialog_clipboard_confirmation) as ScrollView
            try {
                parent.addView(root)
                ClipboardMeasuredLayout(context, parent, root, layoutWidth(context, widthDp), layoutHeight(context, heightDp))
                    .let(assertion)
            } finally {
                parent.removeAllViews()
                root.removeAllViews()
            }
        }
        instrumentation.waitForIdleSync()
    }

    private class ClipboardMeasuredLayout(
        val context: Context,
        val viewport: FrameLayout,
        val root: ScrollView,
        val dialogWidthPx: Int,
        val dialogHeightPx: Int,
    ) {
        val scroll = root
        val content: ViewGroup = root.findViewById(R.id.clipboardConfirmationContent)
        val intro: TextView = root.findViewById(R.id.clipboardConfirmationIntro)
        val directionLabel: TextView = root.findViewById(R.id.clipboardConfirmationDirectionLabel)
        val direction: TextView = root.findViewById(R.id.clipboardConfirmationDirection)
        val protectionLabel: TextView = root.findViewById(R.id.clipboardConfirmationProtectionLabel)
        val protection: TextView = root.findViewById(R.id.clipboardConfirmationProtection)
        val sizeLabel: TextView = root.findViewById(R.id.clipboardConfirmationSizeLabel)
        val size: TextView = root.findViewById(R.id.clipboardConfirmationSize)
        val previewLabel: TextView = root.findViewById(R.id.clipboardConfirmationPreviewLabel)
        val preview: TextView = root.findViewById(R.id.clipboardConfirmationPreview)
        val note: TextView = root.findViewById(R.id.clipboardConfirmationNote)

        fun renderLanSendConfirmation() {
            intro.text = context.getString(R.string.clipboard_lan_legacy_confirm_message)
            direction.text = context.getString(R.string.clipboard_confirmation_send_direction)
            protection.text = context.getString(R.string.clipboard_confirmation_lan_legacy_protection)
            size.text = context.getString(R.string.clipboard_confirmation_send_size_pending, "1.0 MiB")
            preview.text = context.getString(R.string.clipboard_confirmation_send_preview_unavailable)
            note.text = context.getString(R.string.clipboard_confirmation_send_note)
        }

        fun renderLanReceiveConfirmation() {
            intro.text = context.getString(R.string.clipboard_lan_receive_confirm_message)
            direction.text = context.getString(R.string.clipboard_confirmation_receive_direction)
            protection.text = context.getString(R.string.clipboard_confirmation_lan_encrypted_protection)
            size.text = context.getString(R.string.clipboard_confirmation_send_size_pending, "1.0 MiB")
            preview.text = context.getString(R.string.clipboard_confirmation_receive_preview_unavailable)
            note.text = context.getString(R.string.clipboard_confirmation_receive_note)
        }

        fun renderDirectReceiveConfirmation() {
            intro.text = context.getString(R.string.clipboard_lan_legacy_direct_receive_confirm_message)
            direction.text = context.getString(R.string.clipboard_confirmation_receive_direction)
            protection.text = context.getString(R.string.clipboard_confirmation_lan_legacy_protection)
            size.text = context.getString(R.string.clipboard_confirmation_size_format, "612", "1.2 KiB")
            preview.text = context.getString(
                R.string.clipboard_confirmation_preview_truncated,
                "Mac clipboard line ".repeat(18).chunked(CLIPBOARD_PREVIEW_LINE_CHARS).joinToString("\n"),
            )
            note.text = context.getString(R.string.clipboard_confirmation_direct_receive_note)
        }

        fun measureAndLayout() {
            root.layoutParams =
                (root.layoutParams as ViewGroup.LayoutParams).apply {
                    width = ViewGroup.LayoutParams.MATCH_PARENT
                    height = dialogHeightPx
                }
            viewport.measure(
                View.MeasureSpec.makeMeasureSpec(dialogWidthPx, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(dialogHeightPx, View.MeasureSpec.EXACTLY),
            )
            viewport.layout(0, 0, viewport.measuredWidth, viewport.measuredHeight)
        }

        fun assertTextReadable(text: TextView) {
            val textLayout = text.layout
            assertTrue("${text.resources.getResourceEntryName(text.id)} has text layout", textLayout != null && textLayout.lineCount > 0)
            assertTrue(
                "${text.resources.getResourceEntryName(text.id)} is not ellipsized",
                (0 until textLayout.lineCount).all { line -> textLayout.getEllipsisCount(line) == 0 },
            )
            val contentWidth = text.width - text.compoundPaddingLeft - text.compoundPaddingRight
            val maximumLineWidth = (0 until textLayout.lineCount).maxOf(textLayout::getLineWidth)
            assertTrue(
                "${text.resources.getResourceEntryName(text.id)} line width $maximumLineWidth fits $contentWidth",
                maximumLineWidth <= contentWidth + TEXT_LAYOUT_SUBPIXEL_TOLERANCE_PX,
            )
        }

        fun assertLabelsOwnFields() {
            assertEquals(direction.id, directionLabel.labelFor)
            assertEquals(protection.id, protectionLabel.labelFor)
            assertEquals(size.id, sizeLabel.labelFor)
            assertEquals(preview.id, previewLabel.labelFor)
            assertTrue(directionLabel.isAccessibilityHeading)
            assertTrue(protectionLabel.isAccessibilityHeading)
            assertTrue(sizeLabel.isAccessibilityHeading)
            assertTrue(previewLabel.isAccessibilityHeading)
            assertTrue(preview.isTextSelectable)
            assertTrue(!preview.isHorizontallyScrollable)
        }

        fun assertContentCanScrollIntoView() {
            val visibleHeight = scroll.height - scroll.paddingTop - scroll.paddingBottom
            assertTrue("clipboard dialog leaves a usable viewport", visibleHeight > 0)
            if (content.height > visibleHeight) {
                assertFieldEdgesCanScrollIntoView(note)
            } else {
                assertTrue("confirmation note is visible when clipboard content fits", note.bottom <= scroll.scrollY + visibleHeight)
            }
        }

        private fun assertFieldEdgesCanScrollIntoView(field: TextView) {
            val visibleHeight = scroll.height - scroll.paddingTop - scroll.paddingBottom
            scroll.scrollTo(0, field.top.coerceAtLeast(0))
            assertTrue("field top can scroll into viewport", field.top >= scroll.scrollY)
            assertTrue("field top is visible after targeted scroll", field.top < scroll.scrollY + visibleHeight)
            scroll.scrollTo(0, (field.bottom - visibleHeight).coerceAtLeast(0))
            val visibleBottom = scroll.scrollY + visibleHeight
            assertTrue("field bottom can scroll into viewport", field.bottom <= visibleBottom)
        }
    }

    private companion object {
        const val TEXT_LAYOUT_SUBPIXEL_TOLERANCE_PX = 2f
        const val CLIPBOARD_PREVIEW_LINE_CHARS = 36
    }
}

private const val CLIPBOARD_DIALOG_WINDOW_MARGIN_DP = 24
private const val CLIPBOARD_DIALOG_MAX_HEIGHT_RATIO = 0.85f

private fun configuredContext(
    widthDp: Int,
    heightDp: Int,
    fontScale: Float,
): Context {
    val configuration = Configuration(applicationContext().resources.configuration)
    configuration.screenWidthDp = widthDp
    configuration.screenHeightDp = heightDp
    configuration.smallestScreenWidthDp = minOf(widthDp, heightDp)
    configuration.orientation =
        if (widthDp > heightDp) {
            Configuration.ORIENTATION_LANDSCAPE
        } else {
            Configuration.ORIENTATION_PORTRAIT
        }
    configuration.fontScale = fontScale
    val configuredContext = applicationContext().createConfigurationContext(configuration)
    return ContextThemeWrapper(configuredContext, R.style.AppTheme)
}

private fun inflate(
    context: Context,
    parent: ViewGroup,
    layoutId: Int,
): View = LayoutInflater.from(context).inflate(layoutId, parent, false)

private fun layoutWidth(
    context: Context,
    screenWidthDp: Int,
): Int = dp(context, screenWidthDp - CLIPBOARD_DIALOG_WINDOW_MARGIN_DP * 2)

private fun layoutHeight(
    context: Context,
    screenHeightDp: Int,
): Int = dp(context, (screenHeightDp * CLIPBOARD_DIALOG_MAX_HEIGHT_RATIO).roundToInt())

private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

private fun dp(
    context: Context,
    value: Int,
): Int = (value * context.resources.displayMetrics.density).roundToInt()
