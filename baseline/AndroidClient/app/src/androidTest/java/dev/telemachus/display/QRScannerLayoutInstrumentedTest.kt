package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Rect
import android.graphics.drawable.ColorDrawable
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
    fun productionLayoutKeepsDecorativeCameraNodesSilentAndCancelAccessible() {
        withLayout(widthDp = 393, heightDp = 800) { layout ->
            assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_NO, layout.preview.importantForAccessibility)
            assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_NO, layout.target.importantForAccessibility)
            assertEquals(
                layout.context.getString(R.string.qr_scanner_instruction_accessibility),
                layout.instruction.contentDescription.toString(),
            )
            assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, layout.status.accessibilityLiveRegion)
            assertEquals(
                layout.context.getString(R.string.qr_scanner_cancel_description),
                layout.cancel.contentDescription.toString(),
            )
            assertTrue("Cancel remains an immediate no-Host escape hatch", layout.cancel.isClickable)
            assertTrue(layout.cancel.width >= layout.dp(48))
            assertTrue(layout.cancel.height >= layout.dp(48))
        }
    }

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

    @Test
    @UiThreadTest
    fun cameraErrorStateIsReadableAndRecoverable() {
        listOf(320 to 568, 640 to 320, 320 to 400).forEach { (widthDp, heightDp) ->
            withLayout(widthDp = widthDp, heightDp = heightDp, fontScale = 2f) { layout ->
                layout.assertCameraErrorStateSeparated()
            }
        }
    }

    @Test
    @UiThreadTest
    fun invalidQrStatusStaysReadableAboveTarget() {
        listOf(320 to 568, 640 to 320).forEach { (widthDp, heightDp) ->
            withLayout(widthDp = widthDp, heightDp = heightDp, fontScale = 2f) { layout ->
                layout.assertInvalidQrStateSeparated()
            }
        }
    }

    @Test
    @UiThreadTest
    fun permanentlyDeniedCameraStateUsesSettingsAction() {
        listOf(320 to 568, 640 to 320).forEach { (widthDp, heightDp) ->
            withLayout(widthDp = widthDp, heightDp = heightDp, fontScale = 2f) { layout ->
                layout.assertCameraPermissionBlockedStateSeparated()
            }
        }
    }

    @Test
    @UiThreadTest
    fun safeInsetsKeepScannerControlsAwayFromSystemBars() {
        listOf(
            InsetsCase(widthDp = 320, heightDp = 568, leftDp = 0, topDp = 32, rightDp = 0, bottomDp = 48),
            InsetsCase(widthDp = 640, heightDp = 320, leftDp = 48, topDp = 0, rightDp = 48, bottomDp = 0),
            InsetsCase(widthDp = 640, heightDp = 320, leftDp = 0, topDp = 24, rightDp = 0, bottomDp = 48),
        ).forEach { item ->
            withLayout(widthDp = item.widthDp, heightDp = item.heightDp, fontScale = 2f) { layout ->
                layout.applySafeInsets(item.leftDp, item.topDp, item.rightDp, item.bottomDp)
                layout.assertSafeInsetsApplied(item.leftDp, item.topDp, item.rightDp, item.bottomDp)
                layout.assertSeparated()
                layout.assertInvalidQrStateSeparated()
            }
        }
    }

    @Test
    @UiThreadTest
    fun rtlAsymmetricSafeInsetsKeepRelativeMarginsMappedToPhysicalEdges() {
        val item = InsetsCase(widthDp = 640, heightDp = 320, leftDp = 16, topDp = 24, rightDp = 72, bottomDp = 48)
        withLayout(
            widthDp = item.widthDp,
            heightDp = item.heightDp,
            fontScale = 2f,
            layoutDirection = View.LAYOUT_DIRECTION_RTL,
        ) { layout ->
            layout.applySafeInsets(item.leftDp, item.topDp, item.rightDp, item.bottomDp)
            layout.assertSafeInsetsApplied(item.leftDp, item.topDp, item.rightDp, item.bottomDp)
            layout.assertRelativeSafeInsetsApplied(item.leftDp, item.rightDp)
            layout.assertSeparated()
            layout.assertInvalidQrStateSeparated()
            layout.assertCameraErrorStateSeparated(topInsetDp = item.topDp)
            layout.assertSafeInsetsApplied(item.leftDp, item.topDp, item.rightDp, item.bottomDp)
            layout.assertRelativeSafeInsetsApplied(item.leftDp, item.rightDp)
            assertTrue(layout.retry.height >= layout.dp(48))
            assertTrue(layout.cancel.height >= layout.dp(48))
        }
    }

    @Test
    @UiThreadTest
    fun safeInsetErrorStatesKeepRecoveryActionReachable() {
        listOf(
            InsetsCase(widthDp = 320, heightDp = 400, leftDp = 0, topDp = 24, rightDp = 0, bottomDp = 48),
            InsetsCase(widthDp = 320, heightDp = 640, leftDp = 0, topDp = 48, rightDp = 0, bottomDp = 64),
            InsetsCase(widthDp = 640, heightDp = 320, leftDp = 0, topDp = 24, rightDp = 0, bottomDp = 48),
            InsetsCase(widthDp = 640, heightDp = 320, leftDp = 48, topDp = 48, rightDp = 48, bottomDp = 48),
        ).forEach { item ->
            withLayout(widthDp = item.widthDp, heightDp = item.heightDp, fontScale = 2f) { layout ->
                layout.applySafeInsets(item.leftDp, item.topDp, item.rightDp, item.bottomDp)
                layout.assertCameraErrorStateSeparated(topInsetDp = item.topDp)
                layout.assertSafeInsetsApplied(item.leftDp, item.topDp, item.rightDp, item.bottomDp)
                assertEquals(View.GONE, layout.instruction.visibility)
                assertTrue(layout.retry.height >= layout.dp(48))
                assertTrue(layout.cancel.height >= layout.dp(48))
            }
            withLayout(widthDp = item.widthDp, heightDp = item.heightDp, fontScale = 2f) { layout ->
                layout.applySafeInsets(item.leftDp, item.topDp, item.rightDp, item.bottomDp)
                layout.assertCameraPermissionBlockedStateSeparated(topInsetDp = item.topDp)
                layout.assertSafeInsetsApplied(item.leftDp, item.topDp, item.rightDp, item.bottomDp)
                assertEquals(View.GONE, layout.instruction.visibility)
                assertTrue(layout.retry.height >= layout.dp(48))
                assertTrue(layout.cancel.height >= layout.dp(48))
            }
        }
    }

    private fun withLayout(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float = 1f,
        layoutDirection: Int = View.LAYOUT_DIRECTION_LTR,
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
        root.layoutDirection = layoutDirection
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
        val status = root.findViewById<TextView>(R.id.scannerStatus)
        val target = root.findViewById<View>(R.id.targetFrame)
        val retry = root.findViewById<Button>(R.id.retryCameraButton)
        val cancel = root.findViewById<Button>(R.id.cancelButton)
        private val widthPx = dp(widthDp)
        private val heightPx = dp(heightDp)
        private val baseMargins = QRScannerSafeInsets.capture(root)

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
            assertEquals(View.GONE, status.visibility)
            assertEquals(View.GONE, retry.visibility)
            assertEquals(Color.BLACK, (root.background as ColorDrawable).color)
            assertEquals(View.ACCESSIBILITY_LIVE_REGION_NONE, instruction.accessibilityLiveRegion)
            assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, status.accessibilityLiveRegion)
            assertEquals(
                context.getString(R.string.qr_scanner_instruction_accessibility),
                instruction.contentDescription.toString(),
            )
            assertEquals(
                context.getString(R.string.qr_scanner_cancel_description),
                cancel.contentDescription.toString(),
            )
            assertEquals(
                context.getString(R.string.qr_scanner_starting_status),
                status.contentDescription.toString(),
            )
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

        fun assertCameraErrorStateSeparated(topInsetDp: Int = 0) {
            instruction.visibility = View.GONE
            target.visibility = View.GONE
            retry.visibility = View.VISIBLE
            status.visibility = View.VISIBLE
            val message = context.getString(R.string.qr_scanner_camera_bind_failed)
            status.text = message
            status.contentDescription = message
            measureAndLayout()

            assertEquals(View.VISIBLE, status.visibility)
            assertEquals(View.VISIBLE, retry.visibility)
            assertEquals(View.GONE, instruction.visibility)
            assertEquals(View.GONE, target.visibility)
            assertEquals(message, status.contentDescription.toString())
            assertEquals(
                context.getString(R.string.qr_scanner_retry_camera_description),
                retry.contentDescription.toString(),
            )
            assertTrue(retry.width >= dp(48))
            assertTrue(retry.height >= dp(48))
            val statusLayout = status.layout
            assertTrue(statusLayout != null && statusLayout.lineCount > 0)
            assertTrue(
                (0 until statusLayout.lineCount).all { line ->
                    statusLayout.getEllipsisCount(line) == 0
                },
            )
            assertTrue(
                statusLayout.getLineBottom(statusLayout.lineCount - 1) <=
                    status.height - status.compoundPaddingBottom,
            )
            assertNotVisiblyIntersecting(status, retry)
            assertNotVisiblyIntersecting(retry, cancel)
            assertTrue(status.top >= dp(topInsetDp))
            assertTrue(status.left >= 0)
            assertTrue(status.right <= root.width)
            assertTrue(retry.left >= 0)
            assertTrue(retry.right <= root.width)
            assertTrue(cancel.bottom <= root.height)
        }

        fun assertInvalidQrStateSeparated() {
            status.visibility = View.VISIBLE
            val message = context.getString(R.string.invalid_pairing_qr)
            status.text = message
            status.contentDescription = message
            measureAndLayout()

            assertEquals(View.VISIBLE, status.visibility)
            assertEquals(View.VISIBLE, target.visibility)
            assertEquals(View.GONE, retry.visibility)
            assertEquals(message, status.contentDescription.toString())
            assertTrue(target.width > 0)
            assertTrue(target.width <= dp(240))
            assertFalse(Rect.intersects(bounds(instruction), bounds(status)))
            assertFalse(Rect.intersects(bounds(status), bounds(target)))
            assertFalse(Rect.intersects(bounds(target), bounds(cancel)))
            assertEquals(instruction.bottom + dp(8), status.top)
        }

        fun assertCameraPermissionBlockedStateSeparated(topInsetDp: Int = 0) {
            instruction.visibility = View.GONE
            target.visibility = View.GONE
            retry.visibility = View.VISIBLE
            status.visibility = View.VISIBLE
            val message = context.getString(R.string.qr_scanner_camera_permission_blocked)
            status.text = message
            status.contentDescription = message
            retry.text = context.getString(R.string.open_settings)
            retry.contentDescription = context.getString(R.string.qr_scanner_open_settings_description)
            measureAndLayout()

            assertEquals(View.VISIBLE, status.visibility)
            assertEquals(View.VISIBLE, retry.visibility)
            assertEquals(View.GONE, instruction.visibility)
            assertEquals(View.GONE, target.visibility)
            assertEquals(message, status.contentDescription.toString())
            assertEquals(context.getString(R.string.open_settings), retry.text.toString())
            assertEquals(
                context.getString(R.string.qr_scanner_open_settings_description),
                retry.contentDescription.toString(),
            )
            assertNotVisiblyIntersecting(status, retry)
            assertNotVisiblyIntersecting(retry, cancel)
            assertTrue(status.top >= dp(topInsetDp))
            assertTrue(status.left >= 0)
            assertTrue(status.right <= root.width)
            assertTrue(retry.left >= 0)
            assertTrue(retry.right <= root.width)
            assertTrue(cancel.bottom <= root.height)
        }

        fun applySafeInsets(
            leftDp: Int,
            topDp: Int,
            rightDp: Int,
            bottomDp: Int,
        ) {
            QRScannerSafeInsets.apply(
                root,
                baseMargins,
                left = dp(leftDp),
                top = dp(topDp),
                right = dp(rightDp),
                bottom = dp(bottomDp),
            )
            measureAndLayout()
        }

        fun assertSafeInsetsApplied(
            leftDp: Int,
            topDp: Int,
            rightDp: Int,
            bottomDp: Int,
        ) {
            val leftInset = dp(leftDp)
            val topInset = dp(topDp)
            val rightInset = widthPx - dp(rightDp)
            val bottomInset = heightPx - dp(bottomDp)

            assertWithinHorizontalSafeInsets(instruction, leftInset, rightInset)
            if (instruction.visibility == View.VISIBLE) {
                assertTrue(instruction.top >= topInset)
            }
            if (status.visibility == View.VISIBLE && instruction.visibility == View.GONE) {
                assertTrue(status.top >= topInset)
            }
            assertWithinHorizontalSafeInsets(status, leftInset, rightInset)
            assertWithinHorizontalSafeInsets(target, leftInset, rightInset)
            assertWithinHorizontalSafeInsets(retry, leftInset, rightInset)
            assertWithinHorizontalSafeInsets(cancel, leftInset, rightInset)
            assertTrue(cancel.bottom <= bottomInset)
        }

        fun assertRelativeSafeInsetsApplied(
            leftDp: Int,
            rightDp: Int,
        ) {
            val expectedStart = dp(24 + if (root.layoutDirection == View.LAYOUT_DIRECTION_RTL) rightDp else leftDp)
            val expectedEnd = dp(24 + if (root.layoutDirection == View.LAYOUT_DIRECTION_RTL) leftDp else rightDp)
            listOf(instruction, status, target).forEach { view ->
                val margins = view.layoutParams as ViewGroup.MarginLayoutParams
                assertEquals(expectedStart, margins.marginStart)
                assertEquals(expectedEnd, margins.marginEnd)
            }
            val expectedControlStart = dp(if (root.layoutDirection == View.LAYOUT_DIRECTION_RTL) rightDp else leftDp)
            val expectedControlEnd = dp(if (root.layoutDirection == View.LAYOUT_DIRECTION_RTL) leftDp else rightDp)
            listOf(retry, cancel).forEach { view ->
                val margins = view.layoutParams as ViewGroup.MarginLayoutParams
                assertEquals(expectedControlStart, margins.marginStart)
                assertEquals(expectedControlEnd, margins.marginEnd)
            }
        }

        fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).roundToInt()

        private fun assertWithinHorizontalSafeInsets(
            view: View,
            leftInset: Int,
            rightInset: Int,
        ) {
            if (view.visibility == View.VISIBLE) {
                assertTrue(view.left >= leftInset)
                assertTrue(view.right <= rightInset)
            }
        }

        private fun assertNotVisiblyIntersecting(
            first: View,
            second: View,
        ) {
            if (first.visibility == View.VISIBLE && second.visibility == View.VISIBLE) {
                assertFalse(Rect.intersects(bounds(first), bounds(second)))
            }
        }

        private fun bounds(view: View): Rect = Rect(view.left, view.top, view.right, view.bottom)
    }

    private data class InsetsCase(
        val widthDp: Int,
        val heightDp: Int,
        val leftDp: Int,
        val topDp: Int,
        val rightDp: Int,
        val bottomDp: Int,
    )
}
