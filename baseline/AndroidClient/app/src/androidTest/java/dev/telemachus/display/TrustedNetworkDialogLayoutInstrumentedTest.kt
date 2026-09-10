package dev.telemachus.display

import android.app.Dialog
import android.content.Context
import android.content.res.Configuration
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.view.ContextThemeWrapper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlin.math.roundToInt
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TrustedNetworkDialogLayoutInstrumentedTest {
    @Test
    fun narrowAndLargeFontTrustedNetworkDialogKeepsCopyReadableAndScrollable() {
        listOf(
            DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 1.3f),
            DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 2.0f),
            DialogConfiguration(widthDp = 360, heightDp = 740, fontScale = 1.5f),
            DialogConfiguration(widthDp = 360, heightDp = 740, fontScale = 2.0f),
            DialogConfiguration(widthDp = 640, heightDp = 320, fontScale = 2.0f),
        ).forEach { configuration ->
            withTrustedNetworkLayout(configuration) { layout ->
                layout.measureAndLayout()

                assertEquals(layout.dialogWidthPx, layout.root.measuredWidth)
                assertEquals(layout.dialogHeightPx, layout.root.measuredHeight)
                assertTrue("trusted network scroll view fills constrained dialog viewport", layout.scroll.isFillViewport)
                assertEquals(layout.context.getString(R.string.trusted_network_dialog_message), layout.message.text.toString())
                layout.assertTextReadable(layout.message)
                layout.assertNoDuplicateTalkBackSemantics()
                layout.assertMessageCanScrollIntoView()
            }
        }
    }

    @Test
    fun restrictedLandscapeLargeFontTrustedNetworkDialogKeepsContentReachable() {
        withTrustedNetworkLayout(
            DialogConfiguration(widthDp = 320, heightDp = 220, fontScale = 2.0f, heightRatio = 0.30f),
        ) { layout ->
            layout.measureAndLayout()

            assertTrue("trusted network dialog leaves a usable viewport", layout.usableHeightPx() >= layout.dp(96))
            assertTrue("trusted network content is taller than the constrained viewport", layout.content.height > layout.usableHeightPx())
            layout.assertTextReadable(layout.message)
            layout.assertMessageCanScrollIntoView()
        }
    }

    @Test
    fun materialDialogBuilderAcceptsTrustedNetworkLayoutAndActions() {
        val context = configuredContext(widthDp = 320, heightDp = 640, fontScale = 2.0f)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val dialog: Dialog = createTrustedNetworkDialog(context) {}
            try {
                assertTrue("trusted network dialog uses AppCompat AlertDialog", dialog is AlertDialog)
                val content = LayoutInflater.from(context).inflate(R.layout.dialog_trusted_network, null, false) as ScrollView
                assertEquals(R.id.trustedNetworkDialogScroll, content.id)
                assertTrue("trusted network layout uses a scroll container", content.isFillViewport)
                assertEquals(
                    context.getString(R.string.trusted_network_dialog_message),
                    content.findViewById<TextView>(R.id.trustedNetworkDialogMessage).text.toString(),
                )
            } finally {
                dialog.dismiss()
            }
        }
        instrumentation.waitForIdleSync()
    }

    private fun withTrustedNetworkLayout(
        configuration: DialogConfiguration,
        assertion: (TrustedNetworkMeasuredLayout) -> Unit,
    ) {
        val context = configuredContext(configuration.widthDp, configuration.heightDp, configuration.fontScale)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val parent = FrameLayout(context)
            val root = inflate(context, parent, R.layout.dialog_trusted_network) as ScrollView
            try {
                parent.addView(root)
                TrustedNetworkMeasuredLayout(
                    context = context,
                    viewport = parent,
                    root = root,
                    dialogWidthPx = layoutWidth(context, configuration.widthDp),
                    dialogHeightPx = layoutHeight(context, configuration.heightDp, configuration.heightRatio),
                ).let(assertion)
            } finally {
                parent.removeAllViews()
                root.removeAllViews()
            }
        }
        instrumentation.waitForIdleSync()
    }

    private class TrustedNetworkMeasuredLayout(
        val context: Context,
        val viewport: FrameLayout,
        val root: ScrollView,
        val dialogWidthPx: Int,
        val dialogHeightPx: Int,
    ) {
        val scroll = root
        val content: ViewGroup = root.findViewById(R.id.trustedNetworkDialogContent)
        val message: TextView = root.findViewById(R.id.trustedNetworkDialogMessage)

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

        fun usableHeightPx(): Int = scroll.height - scroll.paddingTop - scroll.paddingBottom

        fun assertTextReadable(text: TextView) {
            val textLayout = text.layout
            val label = text.resources.getResourceEntryName(text.id)
            assertTrue(
                "$label has text layout",
                textLayout != null && textLayout.lineCount > 0,
            )
            assertTrue(
                "$label is not ellipsized",
                (0 until textLayout.lineCount).all { line -> textLayout.getEllipsisCount(line) == 0 },
            )
            val contentWidth = text.width - text.compoundPaddingLeft - text.compoundPaddingRight
            val maximumLineWidth = (0 until textLayout.lineCount).maxOf(textLayout::getLineWidth)
            assertTrue(
                label + " line width " + maximumLineWidth + " fits " + contentWidth,
                maximumLineWidth <= contentWidth + TEXT_LAYOUT_SUBPIXEL_TOLERANCE_PX,
            )
            assertEquals(
                "$label renders complete text",
                text.text.length,
                textLayout.getLineEnd(textLayout.lineCount - 1),
            )
        }

        fun assertNoDuplicateTalkBackSemantics() {
            assertNull("trusted network message text should not duplicate itself as a content description", message.contentDescription)
        }

        fun assertMessageCanScrollIntoView() {
            val usableHeight = usableHeightPx()
            assertTrue("trusted network dialog has room for readable content", usableHeight > 0)
            if (content.height > usableHeight) {
                root.scrollTo(0, (message.bottom - usableHeight).coerceAtLeast(0))
                assertTrue("trusted network message bottom can scroll into view", message.bottom <= root.scrollY + usableHeight)
            } else {
                assertTrue("trusted network message fits without scrolling", message.bottom <= root.scrollY + usableHeight)
            }
        }

        fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).roundToInt()
    }

    private data class DialogConfiguration(
        val widthDp: Int,
        val heightDp: Int,
        val fontScale: Float,
        val heightRatio: Float = 1.0f,
    )

    private companion object {
        const val TEXT_LAYOUT_SUBPIXEL_TOLERANCE_PX = 2f
    }
}

private fun configuredContext(
    widthDp: Int,
    heightDp: Int,
    fontScale: Float,
): Context {
    val configuration =
        Configuration(ApplicationProvider.getApplicationContext<Context>().resources.configuration).apply {
            screenWidthDp = widthDp
            screenHeightDp = heightDp
            smallestScreenWidthDp = minOf(widthDp, heightDp)
            this.fontScale = fontScale
            orientation =
                if (widthDp > heightDp) {
                    Configuration.ORIENTATION_LANDSCAPE
                } else {
                    Configuration.ORIENTATION_PORTRAIT
                }
        }
    val configuredContext = ApplicationProvider.getApplicationContext<Context>().createConfigurationContext(configuration)
    return ContextThemeWrapper(configuredContext, R.style.AppTheme)
}

private fun inflate(
    context: Context,
    parent: ViewGroup,
    layoutRes: Int,
): View = LayoutInflater.from(context).inflate(layoutRes, parent, false)

private fun layoutWidth(
    context: Context,
    widthDp: Int,
): Int = context.dp(widthDp).coerceAtMost(context.resources.displayMetrics.widthPixels)

private fun layoutHeight(
    context: Context,
    heightDp: Int,
    heightRatio: Float,
): Int = (context.dp(heightDp) * heightRatio).roundToInt().coerceAtLeast(context.dp(120))

private fun Context.dp(value: Int): Int = (value * resources.displayMetrics.density).roundToInt()
