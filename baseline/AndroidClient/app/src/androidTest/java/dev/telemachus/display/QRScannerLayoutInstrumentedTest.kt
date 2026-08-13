package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.graphics.Rect
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.view.ContextThemeWrapper
import androidx.camera.view.PreviewView
import androidx.constraintlayout.widget.ConstraintLayout
import androidx.test.annotation.UiThreadTest
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.roundToInt

@RunWith(AndroidJUnit4::class)
class QRScannerLayoutInstrumentedTest {
    @Test
    @UiThreadTest
    fun shortLandscapeKeepsScannerChromeSeparated() {
        listOf(320, 393).forEach { heightDp ->
            listOf(1f, 2f).forEach { fontScale ->
                withLayout(widthDp = 640, heightDp = heightDp, fontScale = fontScale) { layout ->
                    layout.assertSeparated()
                }
            }
        }
    }

    @Test
    @UiThreadTest
    fun compactPortraitAndLargeTextKeepScannerChromeSeparated() {
        listOf(320, 400, 568).forEach { heightDp ->
            listOf(1f, 2f).forEach { fontScale ->
                withLayout(widthDp = 320, heightDp = heightDp, fontScale = fontScale) { layout ->
                    layout.assertSeparated()
                }
            }
        }
    }

    @Test
    @UiThreadTest
    fun regularPortraitCapsTargetAtProductionMaximum() {
        withLayout(widthDp = 393, heightDp = 800) { layout ->
            assertEquals(layout.dp(240), layout.target.width)
            assertEquals(layout.dp(240), layout.target.height)
            layout.assertSeparated()
        }
    }

    private fun withLayout(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float = 1f,
        assertion: (MeasuredLayout) -> Unit,
    ) {
        val configuration = Configuration(applicationContext().resources.configuration)
        configuration.screenWidthDp = widthDp
        configuration.screenHeightDp = heightDp
        configuration.orientation =
            if (widthDp > heightDp) Configuration.ORIENTATION_LANDSCAPE else Configuration.ORIENTATION_PORTRAIT
        configuration.fontScale = fontScale
        val configuredContext = applicationContext().createConfigurationContext(configuration)
        val context = ContextThemeWrapper(configuredContext, R.style.AppTheme)
        val root =
            LayoutInflater.from(context)
                .inflate(R.layout.activity_qr_scanner, null, false) as ConstraintLayout
        val measured = MeasuredLayout(context, root, widthDp, heightDp)
        measured.measureAndLayout()
        assertion(measured)
    }

    private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

    private class MeasuredLayout(
        val context: Context,
        val root: ConstraintLayout,
        widthDp: Int,
        heightDp: Int,
    ) {
        val preview = root.findViewById<PreviewView>(R.id.preview)
        val instruction = root.findViewById<TextView>(R.id.scannerInstruction)
        val target = root.findViewById<View>(R.id.targetFrame)
        val cancel = root.findViewById<Button>(R.id.cancelButton)
        private val widthPx = dp(widthDp)
        private val heightPx = dp(heightDp)

        fun measureAndLayout() {
            root.measure(
                View.MeasureSpec.makeMeasureSpec(widthPx, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(heightPx, View.MeasureSpec.EXACTLY),
            )
            root.layout(0, 0, root.measuredWidth, root.measuredHeight)
        }

        fun assertSeparated() {
            assertEquals(widthPx, preview.width)
            assertEquals(heightPx, preview.height)
            assertEquals(target.width, target.height)
            assertTrue(target.width > 0)
            assertTrue(target.width <= dp(240))
            assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_NO, target.importantForAccessibility)
            assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_NO, preview.importantForAccessibility)
            assertTrue(cancel.width >= dp(48))
            assertTrue(cancel.height >= dp(48))
            val instructionLayout = instruction.layout
            assertTrue(instructionLayout != null && instructionLayout.lineCount > 0)
            assertTrue(
                (0 until instructionLayout.lineCount).all { line ->
                    instructionLayout.getEllipsisCount(line) == 0
                },
            )
            assertEquals(
                instruction.text.length,
                instructionLayout.getLineEnd(instructionLayout.lineCount - 1),
            )
            assertTrue(
                instructionLayout.getLineBottom(instructionLayout.lineCount - 1) <=
                    instruction.height - instruction.compoundPaddingBottom,
            )
            assertFalse(Rect.intersects(bounds(instruction), bounds(target)))
            assertFalse(Rect.intersects(bounds(target), bounds(cancel)))
            assertFalse(Rect.intersects(bounds(instruction), bounds(cancel)))
            assertTrue(instruction.top >= 0)
            assertTrue(cancel.bottom <= root.height)
        }

        fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).roundToInt()

        private fun bounds(view: View): Rect = Rect(view.left, view.top, view.right, view.bottom)
    }
}
