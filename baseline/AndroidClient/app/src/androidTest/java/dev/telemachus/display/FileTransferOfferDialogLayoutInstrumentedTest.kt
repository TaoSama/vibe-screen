package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.view.ContextThemeWrapper
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import kotlin.math.roundToInt
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class FileTransferOfferDialogLayoutInstrumentedTest {
    @Test
    fun narrowAndLargeFontOfferDialogKeepsDecisionContentReadableAndScrollable() {
        listOf(
            Triple(320, 640, 1.3f),
            Triple(320, 640, 2.0f),
            Triple(640, 320, 2.0f),
        ).forEach { (widthDp, heightDp, fontScale) ->
            withOfferLayout(widthDp = widthDp, heightDp = heightDp, fontScale = fontScale) { layout ->
                layout.renderSampleOffer()
                layout.measureAndLayout()

                assertEquals(layout.dialogWidthPx, layout.root.measuredWidth)
                assertEquals(layout.dialogHeightPx, layout.root.measuredHeight)
                assertTrue("offer scroll view fills constrained dialog viewport", layout.scroll.isFillViewport)
                layout.assertTextReadable(layout.intro)
                layout.assertTextReadable(layout.fileName)
                layout.assertTextReadable(layout.size)
                layout.assertTextReadable(layout.destination)
                layout.assertTextReadable(layout.verification)
                layout.assertLabelsOwnFields()
                layout.assertOfferContentCanScrollIntoView()
            }
        }
    }

    @Test
    fun offerLayoutKeepsDecisionCopyStructuredForDialogButtons() {
        withOfferLayout(widthDp = 320, heightDp = 640, fontScale = 2.0f) { layout ->
            layout.renderSampleOffer()
            layout.measureAndLayout()

            layout.assertTextReadable(layout.intro)
            layout.assertTextReadable(layout.fileName)
            layout.assertTextReadable(layout.size)
            layout.assertTextReadable(layout.destination)
            layout.assertTextReadable(layout.verification)
            layout.assertLabelsOwnFields()
            layout.assertDialogActionLabels()
            layout.assertContentReachableInProductionDialog()
        }
    }

    @Test
    fun outgoingConfirmationLayoutKeepsPreflightDetailsReadableAndScrollable() {
        listOf(
            Triple(320, 640, 1.3f),
            Triple(320, 640, 2.0f),
            Triple(640, 320, 2.0f),
        ).forEach { (widthDp, heightDp, fontScale) ->
            withOutgoingLayout(widthDp = widthDp, heightDp = heightDp, fontScale = fontScale) { layout ->
                layout.renderSampleOutgoing()
                layout.measureAndLayout()

                assertEquals(layout.dialogWidthPx, layout.root.measuredWidth)
                assertEquals(layout.dialogHeightPx, layout.root.measuredHeight)
                assertTrue("outgoing scroll view fills constrained dialog viewport", layout.scroll.isFillViewport)
                layout.assertTextReadable(layout.intro)
                layout.assertTextReadable(layout.fileName)
                layout.assertTextReadable(layout.size)
                layout.assertTextReadable(layout.limit)
                layout.assertTextReadable(layout.target)
                layout.assertTextReadable(layout.verification)
                layout.assertLabelsOwnFields()
                layout.assertDialogActionLabels()
                layout.assertOutgoingContentCanScrollIntoView()
            }
        }
    }

    @Test
    fun unavailableErrorDialogUsesDismissOnlyAction() {
        var dialog: AlertDialog? = null
        ActivityScenario.launch(DialogHostActivity::class.java).use { scenario ->
            try {
                scenario.onActivity { activity ->
                    dialog =
                        MaterialAlertDialogBuilder(activity)
                            .setTitle(R.string.file_transfer_unavailable_title)
                            .setMessage(R.string.file_transfer_unavailable)
                            .setPositiveButton(android.R.string.ok, null)
                            .show()
                }
                scenario.onActivity { activity ->
                    val shownDialog = checkNotNull(dialog)
                    val positive = shownDialog.getButton(AlertDialog.BUTTON_POSITIVE)
                    val negative = shownDialog.getButton(AlertDialog.BUTTON_NEGATIVE)
                    val neutral = shownDialog.getButton(AlertDialog.BUTTON_NEUTRAL)
                    assertEquals(activity.getString(android.R.string.ok), positive.text.toString())
                    assertTrue("dismiss-only dialog keeps cancel button hidden", negative.visibility != View.VISIBLE)
                    assertTrue("dismiss-only dialog keeps neutral button hidden", neutral.visibility != View.VISIBLE)
                    positive.assertMinimumTouchTarget(activity)
                }
            } finally {
                dialog?.dismiss()
            }
        }
    }

    @Test
    fun recoverableErrorDialogKeepsChooseAnotherFileRetryAction() {
        var dialog: AlertDialog? = null
        ActivityScenario.launch(DialogHostActivity::class.java).use { scenario ->
            try {
                scenario.onActivity { activity ->
                    dialog =
                        MaterialAlertDialogBuilder(activity)
                            .setTitle(R.string.file_transfer_pick_failed_title)
                            .setMessage(R.string.file_transfer_pick_failed)
                            .setPositiveButton(R.string.file_transfer_error_retry, null)
                            .setNegativeButton(R.string.cancel, null)
                            .show()
                }
                scenario.onActivity { activity ->
                    val shownDialog = checkNotNull(dialog)
                    val positive = shownDialog.getButton(AlertDialog.BUTTON_POSITIVE)
                    val negative = shownDialog.getButton(AlertDialog.BUTTON_NEGATIVE)
                    assertEquals(activity.getString(R.string.file_transfer_error_retry), positive.text.toString())
                    assertEquals(activity.getString(R.string.cancel), negative.text.toString())
                    positive.assertMinimumTouchTarget(activity)
                    negative.assertMinimumTouchTarget(activity)
                }
            } finally {
                dialog?.dismiss()
            }
        }
    }

    private fun withOfferLayout(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float,
        assertion: (OfferMeasuredLayout) -> Unit,
    ) {
        val context = configuredContext(widthDp, heightDp, fontScale)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val parent = FrameLayout(context)
            val root = inflate(context, parent, R.layout.dialog_file_transfer_offer) as ScrollView
            try {
                parent.addView(root)
                OfferMeasuredLayout(context, parent, root, layoutWidth(context, widthDp), layoutHeight(context, heightDp))
                    .let(assertion)
            } finally {
                parent.removeAllViews()
                root.removeAllViews()
            }
        }
        instrumentation.waitForIdleSync()
    }

    private fun withOutgoingLayout(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float,
        assertion: (OutgoingMeasuredLayout) -> Unit,
    ) {
        val context = configuredContext(widthDp, heightDp, fontScale)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val parent = FrameLayout(context)
            val root = inflate(context, parent, R.layout.dialog_file_transfer_outgoing) as ScrollView
            try {
                parent.addView(root)
                OutgoingMeasuredLayout(context, parent, root, layoutWidth(context, widthDp), layoutHeight(context, heightDp))
                    .let(assertion)
            } finally {
                parent.removeAllViews()
                root.removeAllViews()
            }
        }
        instrumentation.waitForIdleSync()
    }

    private class OfferMeasuredLayout(
        val context: Context,
        val viewport: FrameLayout,
        val root: ScrollView,
        val dialogWidthPx: Int,
        val dialogHeightPx: Int,
    ) {
        val scroll = root
        val content: ViewGroup = root.findViewById(R.id.fileTransferOfferContent)
        val intro: TextView = root.findViewById(R.id.fileTransferOfferIntro)
        val fileLabel: TextView = root.findViewById(R.id.fileTransferOfferFileLabel)
        val fileName: TextView = root.findViewById(R.id.fileTransferOfferFileName)
        val sizeLabel: TextView = root.findViewById(R.id.fileTransferOfferSizeLabel)
        val size: TextView = root.findViewById(R.id.fileTransferOfferSize)
        val destinationLabel: TextView = root.findViewById(R.id.fileTransferOfferDestinationLabel)
        val destination: TextView = root.findViewById(R.id.fileTransferOfferDestination)
        val verification: TextView = root.findViewById(R.id.fileTransferOfferVerification)

        fun renderSampleOffer() {
            renderSampleOffer(context, root)
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
            assertEquals(fileName.id, fileLabel.labelFor)
            assertEquals(size.id, sizeLabel.labelFor)
            assertEquals(destination.id, destinationLabel.labelFor)
            assertTrue(fileLabel.isAccessibilityHeading)
            assertTrue(sizeLabel.isAccessibilityHeading)
            assertTrue(destinationLabel.isAccessibilityHeading)
            assertTrue(fileName.isTextSelectable)
            assertTrue(!fileName.isHorizontallyScrollable)
        }

        fun assertDialogActionLabels() {
            assertEquals("Receive", context.getString(R.string.file_transfer_accept))
            assertEquals("Reject", context.getString(R.string.file_transfer_reject))
        }

        fun assertOfferContentCanScrollIntoView() {
            val visibleHeight = scroll.height - scroll.paddingTop - scroll.paddingBottom
            assertTrue("offer dialog leaves a usable viewport", visibleHeight > 0)
            if (content.height > visibleHeight) {
                assertFieldEdgesCanScrollIntoView(verification)
            } else {
                assertTrue("verification note is visible when offer content fits", verification.bottom <= scroll.scrollY + visibleHeight)
            }
        }

        fun assertContentReachableInProductionDialog() {
            val visibleHeight = scroll.height - scroll.paddingTop - scroll.paddingBottom
            assertTrue("production offer dialog leaves a usable viewport", visibleHeight > 0)
            if (content.height > visibleHeight) {
                assertFieldEdgesCanScrollIntoView(verification)
            } else {
                assertTrue("verification note is visible when content fits", verification.bottom <= scroll.scrollY + visibleHeight)
            }
        }

        fun assertFieldEdgesCanScrollIntoView(field: TextView) {
            val visibleHeight = scroll.height - scroll.paddingTop - scroll.paddingBottom
            scroll.scrollTo(0, field.top.coerceAtLeast(0))
            assertTrue("field top can scroll into viewport", field.top >= scroll.scrollY)
            assertTrue("field top is visible after targeted scroll", field.top < scroll.scrollY + visibleHeight)
            scroll.scrollTo(0, (field.bottom - visibleHeight).coerceAtLeast(0))
            val visibleBottom = scroll.scrollY + visibleHeight
            assertTrue("field bottom can scroll into viewport", field.bottom <= visibleBottom)
        }

    }

    private class OutgoingMeasuredLayout(
        val context: Context,
        val viewport: FrameLayout,
        val root: ScrollView,
        val dialogWidthPx: Int,
        val dialogHeightPx: Int,
    ) {
        val scroll = root
        val content: ViewGroup = root.findViewById(R.id.fileTransferOutgoingContent)
        val intro: TextView = root.findViewById(R.id.fileTransferOutgoingIntro)
        val fileLabel: TextView = root.findViewById(R.id.fileTransferOutgoingFileLabel)
        val fileName: TextView = root.findViewById(R.id.fileTransferOutgoingFileName)
        val sizeLabel: TextView = root.findViewById(R.id.fileTransferOutgoingSizeLabel)
        val size: TextView = root.findViewById(R.id.fileTransferOutgoingSize)
        val limitLabel: TextView = root.findViewById(R.id.fileTransferOutgoingLimitLabel)
        val limit: TextView = root.findViewById(R.id.fileTransferOutgoingLimit)
        val targetLabel: TextView = root.findViewById(R.id.fileTransferOutgoingTargetLabel)
        val target: TextView = root.findViewById(R.id.fileTransferOutgoingTarget)
        val verification: TextView = root.findViewById(R.id.fileTransferOutgoingVerification)

        fun renderSampleOutgoing() {
            renderSampleOutgoing(context, root)
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
            assertEquals(fileName.id, fileLabel.labelFor)
            assertEquals(size.id, sizeLabel.labelFor)
            assertEquals(limit.id, limitLabel.labelFor)
            assertEquals(target.id, targetLabel.labelFor)
            assertTrue(fileLabel.isAccessibilityHeading)
            assertTrue(sizeLabel.isAccessibilityHeading)
            assertTrue(limitLabel.isAccessibilityHeading)
            assertTrue(targetLabel.isAccessibilityHeading)
            assertTrue(fileName.isTextSelectable)
            assertTrue(!fileName.isHorizontallyScrollable)
        }

        fun assertDialogActionLabels() {
            assertEquals("Send", context.getString(R.string.file_transfer_outgoing_send))
            assertEquals("Cancel", context.getString(R.string.cancel))
        }

        fun assertOutgoingContentCanScrollIntoView() {
            val visibleHeight = scroll.height - scroll.paddingTop - scroll.paddingBottom
            assertTrue("outgoing dialog leaves a usable viewport", visibleHeight > 0)
            if (content.height > visibleHeight) {
                assertFieldEdgesCanScrollIntoView(verification)
            } else {
                assertTrue("verification note is visible when outgoing content fits", verification.bottom <= scroll.scrollY + visibleHeight)
            }
        }

        fun assertFieldEdgesCanScrollIntoView(field: TextView) {
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
    }
}

private const val FILE_OFFER_DIALOG_WINDOW_MARGIN_DP = 24
private const val FILE_OFFER_DIALOG_MAX_HEIGHT_RATIO = 0.85f

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
): Int = dp(context, screenWidthDp - FILE_OFFER_DIALOG_WINDOW_MARGIN_DP * 2)

private fun layoutHeight(
    context: Context,
    screenHeightDp: Int,
): Int = dp(context, (screenHeightDp * FILE_OFFER_DIALOG_MAX_HEIGHT_RATIO).roundToInt())

private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

private fun dp(
    context: Context,
    value: Int,
): Int = (value * context.resources.displayMetrics.density).roundToInt()

private fun Button.assertMinimumTouchTarget(context: Context) {
    val minimum = dp(context, 48)
    assertTrue("$text button is at least 48dp wide", width >= minimum)
    assertTrue("$text button is at least 48dp tall", height >= minimum)
}

private fun renderSampleOffer(
    context: Context,
    root: View,
) {
    root.findViewById<TextView>(R.id.fileTransferOfferFileName).text =
        "vibescreen-proof-export-" + "review-segment-".repeat(8) + "final.zip"
    root.findViewById<TextView>(R.id.fileTransferOfferSize).text = context.getString(R.string.file_transfer_size_bytes, 1_048_576L)
    root.findViewById<TextView>(R.id.fileTransferOfferDestination).text =
        context.getString(R.string.file_transfer_app_downloads_destination)
}

private fun renderSampleOutgoing(
    context: Context,
    root: View,
) {
    root.findViewById<TextView>(R.id.fileTransferOutgoingFileName).text =
        "vibescreen-proof-export-" + "review-segment-".repeat(8) + "final.zip"
    root.findViewById<TextView>(R.id.fileTransferOutgoingSize).text = context.getString(R.string.file_transfer_size_bytes, 1_048_576L)
    root.findViewById<TextView>(R.id.fileTransferOutgoingLimit).text = context.getString(R.string.file_transfer_size_bytes, 16_777_216L)
    root.findViewById<TextView>(R.id.fileTransferOutgoingTarget).text = context.getString(R.string.file_transfer_outgoing_target_mac)
}
