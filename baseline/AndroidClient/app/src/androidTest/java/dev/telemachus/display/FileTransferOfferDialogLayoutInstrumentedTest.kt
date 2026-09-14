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
import androidx.core.widget.NestedScrollView
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import kotlin.math.roundToInt
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
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
    fun productionIncomingOfferDialogKeepsActionsReadableAndNonDuplicated() {
        productionDialogConfigurations().forEach { configuration ->
            var accepted = 0
            var rejected = 0

            withFileTransferBusinessDialog(
                configuration = configuration,
                kind = FileTransferBusinessDialogKind.INCOMING,
                onPositive = { accepted++ },
                onNegative = { rejected++ },
            ) { activity, dialog, content ->
                dialog.assertFileTransferBusinessActions(activity, FileTransferBusinessDialogKind.INCOMING)
                dialog.assertCustomContentStaysAboveActions(content)
                dialog.assertNoDuplicateTalkBackSemantics(
                    title = activity.getString(R.string.file_transfer_offer_title),
                    content = content,
                )
                content.assertBusinessDialogContentCanScrollIntoView(R.id.fileTransferOfferVerification)

                assertTrue(
                    "reject click is handled by the incoming offer callback",
                    dialog.getButton(AlertDialog.BUTTON_NEGATIVE).performClick(),
                )
                assertTrue(
                    "late accept click reaches the same incoming decision",
                    dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick(),
                )
            }
            assertEquals("reject must not accept the incoming offer", 0, accepted)
            assertEquals("reject callback is delivered exactly once", 1, rejected)

            withFileTransferBusinessDialog(
                configuration = configuration,
                kind = FileTransferBusinessDialogKind.INCOMING,
                onPositive = { accepted++ },
                onNegative = { rejected++ },
            ) { _, dialog, _ ->
                assertTrue(
                    "accept click is handled by the incoming offer callback",
                    dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick(),
                )
                assertTrue(
                    "late reject click reaches the same incoming decision",
                    dialog.getButton(AlertDialog.BUTTON_NEGATIVE).performClick(),
                )
            }
            assertEquals("accept callback is delivered exactly once", 1, accepted)
            assertEquals("accept must not run the reject callback", 1, rejected)
        }
    }

    @Test
    fun productionOutgoingPreflightDialogKeepsActionsReadableAndNonDuplicated() {
        productionDialogConfigurations().forEach { configuration ->
            var sent = 0
            var cancelled = 0

            withFileTransferBusinessDialog(
                configuration = configuration,
                kind = FileTransferBusinessDialogKind.OUTGOING,
                onPositive = { sent++ },
                onNegative = { cancelled++ },
            ) { activity, dialog, content ->
                dialog.assertFileTransferBusinessActions(activity, FileTransferBusinessDialogKind.OUTGOING)
                dialog.assertCustomContentStaysAboveActions(content)
                dialog.assertNoDuplicateTalkBackSemantics(
                    title = activity.getString(R.string.file_transfer_outgoing_title),
                    content = content,
                )
                content.assertBusinessDialogContentCanScrollIntoView(R.id.fileTransferOutgoingVerification)

                assertTrue(
                    "cancel click is handled by the outgoing preflight callback",
                    dialog.getButton(AlertDialog.BUTTON_NEGATIVE).performClick(),
                )
                assertTrue(
                    "late send click reaches the same outgoing decision",
                    dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick(),
                )
            }
            assertEquals("cancel must not send the outgoing file", 0, sent)
            assertEquals("cancel callback is delivered exactly once", 1, cancelled)

            withFileTransferBusinessDialog(
                configuration = configuration,
                kind = FileTransferBusinessDialogKind.OUTGOING,
                onPositive = { sent++ },
                onNegative = { cancelled++ },
            ) { _, dialog, _ ->
                assertTrue(
                    "send click is handled by the outgoing preflight callback",
                    dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick(),
                )
                assertTrue(
                    "late cancel click reaches the same outgoing decision",
                    dialog.getButton(AlertDialog.BUTTON_NEGATIVE).performClick(),
                )
            }
            assertEquals("send callback is delivered exactly once", 1, sent)
            assertEquals("send must not run the cancel callback", 1, cancelled)
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
        listOf(
            DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 1.3f),
            DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 1.5f),
            DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 2.0f),
        ).forEach { configuration ->
            var retryClicks = 0
            var cancelClicks = 0
            withRecoverableErrorDialog(configuration, onRetry = { retryClicks++ }, onCancel = { cancelClicks++ }) { activity, dialog ->
                val title = dialog.findViewById<TextView>(androidx.appcompat.R.id.alertTitle)
                val message = checkNotNull(dialog.findViewById<TextView>(android.R.id.message))
                val positive = dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                val negative = dialog.getButton(AlertDialog.BUTTON_NEGATIVE)
                val buttonPanel = dialog.findViewById<View>(androidx.appcompat.R.id.buttonPanel)

                assertEquals(activity.getString(R.string.file_transfer_pick_failed_title), title?.text?.toString())
                assertEquals(activity.getString(R.string.file_transfer_pick_failed), message.text.toString())
                assertTrue("recoverable error dialog uses the real Material button panel", buttonPanel != null)
                assertTrue("standard dialog message is inside a NestedScrollView", message.hasNestedScrollAncestor())
                assertTextReadable(title)
                assertEquals(activity.getString(R.string.file_transfer_error_retry), positive.text.toString())
                assertEquals(activity.getString(R.string.cancel), negative.text.toString())
                positive.assertReadableDialogActionButton(activity)
                negative.assertReadableDialogActionButton(activity)

                negative.performClick()
            }
            assertEquals("cancel does not launch the file picker retry path", 0, retryClicks)
            assertEquals("cancel callback is delivered exactly once", 1, cancelClicks)
            withRecoverableErrorDialog(configuration, onRetry = { retryClicks++ }, onCancel = { cancelClicks++ }) { _, dialog ->
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
            }
            assertEquals("retry callback is delivered exactly once", 1, retryClicks)
            assertEquals("retry does not run the cancel callback", 1, cancelClicks)
        }
    }

    private fun withRecoverableErrorDialog(
        configuration: DialogConfiguration,
        onRetry: () -> Unit,
        onCancel: () -> Unit,
        assertion: (DialogHostActivity, AlertDialog) -> Unit,
    ) {
        var dialog: AlertDialog? = null
        var assertionFailure: Throwable? = null
        DialogHostActivity.configurationOverride =
            DialogHostActivity.ConfigurationOverride(
                widthDp = configuration.widthDp,
                heightDp = configuration.heightDp,
                fontScale = configuration.fontScale,
            )
        try {
            ActivityScenario.launch(DialogHostActivity::class.java).use { scenario ->
                try {
                    scenario.onActivity { activity ->
                        dialog =
                            MaterialAlertDialogBuilder(activity)
                                .setTitle(R.string.file_transfer_pick_failed_title)
                                .setMessage(R.string.file_transfer_pick_failed)
                                .setPositiveButton(R.string.file_transfer_error_retry) { _, _ -> onRetry() }
                                .setNegativeButton(R.string.cancel) { _, _ -> onCancel() }
                                .show()
                                .also(DialogActionButtonLayoutApplier::apply)
                    }
                    scenario.onActivity { activity ->
                        try {
                            val shownDialog = checkNotNull(dialog)
                            shownDialog.window?.decorView?.measureAndLayoutWithin(activity, configuration)
                            assertion(activity, shownDialog)
                        } catch (failure: Throwable) {
                            assertionFailure = failure
                        }
                    }
                    assertionFailure?.let { throw it }
                    InstrumentationRegistry.getInstrumentation().waitForIdleSync()
                } finally {
                    scenario.onActivity {
                        dialog?.dismiss()
                        dialog = null
                    }
                }
            }
        } finally {
            DialogHostActivity.configurationOverride = null
        }
    }

    private fun withFileTransferBusinessDialog(
        configuration: DialogConfiguration,
        kind: FileTransferBusinessDialogKind,
        onPositive: () -> Unit,
        onNegative: () -> Unit,
        assertion: (DialogHostActivity, AlertDialog, ScrollView) -> Unit,
    ) {
        var dialog: AlertDialog? = null
        var contentView: ScrollView? = null
        var assertionFailure: Throwable? = null
        var decided = false
        DialogHostActivity.configurationOverride =
            DialogHostActivity.ConfigurationOverride(
                widthDp = configuration.widthDp,
                heightDp = configuration.heightDp,
                fontScale = configuration.fontScale,
            )
        try {
            ActivityScenario.launch(DialogHostActivity::class.java).use { scenario ->
                try {
                    scenario.onActivity { activity ->
                        val content =
                            activity.layoutInflater.inflate(
                                kind.layoutRes,
                                null,
                                false,
                            ) as ScrollView
                        kind.render(activity, content)
                        contentView = content
                        dialog =
                            MaterialAlertDialogBuilder(activity)
                                .setTitle(kind.titleRes)
                                .setView(content)
                                .setPositiveButton(kind.positiveButtonRes) { _, _ ->
                                    if (decided) return@setPositiveButton
                                    decided = true
                                    onPositive()
                                }
                                .setNegativeButton(kind.negativeButtonRes) { _, _ ->
                                    if (decided) return@setNegativeButton
                                    decided = true
                                    onNegative()
                                }
                                .show()
                                .also(DialogActionButtonLayoutApplier::apply)
                    }
                    InstrumentationRegistry.getInstrumentation().waitForIdleSync()
                    scenario.onActivity { activity ->
                        try {
                            val shownDialog = checkNotNull(dialog)
                            shownDialog.window?.decorView?.measureAndLayoutWithin(activity, configuration)
                            assertion(activity, shownDialog, checkNotNull(contentView))
                        } catch (failure: Throwable) {
                            assertionFailure = failure
                        }
                    }
                    assertionFailure?.let { throw it }
                    InstrumentationRegistry.getInstrumentation().waitForIdleSync()
                } finally {
                    scenario.onActivity {
                        dialog?.dismiss()
                        dialog = null
                        contentView = null
                    }
                }
            }
        } finally {
            DialogHostActivity.configurationOverride = null
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

private fun productionDialogConfigurations(): List<DialogConfiguration> =
    listOf(
        DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 1.5f),
        DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 2.0f),
        DialogConfiguration(widthDp = 640, heightDp = 320, fontScale = 1.5f),
        DialogConfiguration(widthDp = 640, heightDp = 320, fontScale = 2.0f),
    )

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

private fun Button.assertReadableDialogActionButton(context: Context) {
    assertEquals("$text button allows two rendered lines", 2, maxLines)
    assertTrue("$text button is allowed to wrap", !isSingleLine)
    assertTrue("$text button has no ellipsize policy", ellipsize == null)
    assertTrue("$text button does not horizontally scroll", !isHorizontallyScrollable)
    assertMinimumTouchTarget(context)
    assertTextReadable(this)
    val layout = checkNotNull(layout) { "$text button has text layout" }
    assertTrue("$text button uses at most two rendered lines", layout.lineCount <= 2)
    val contentBottom = height - compoundPaddingBottom
    val lastLineBottom = compoundPaddingTop + layout.getLineBottom(layout.lineCount - 1)
    assertTrue("$text button text is not vertically clipped", lastLineBottom <= contentBottom + DIALOG_ACTION_TEXT_LAYOUT_TOLERANCE_PX)
}

private fun AlertDialog.assertFileTransferBusinessActions(
    activity: DialogHostActivity,
    kind: FileTransferBusinessDialogKind,
) {
    val positive = getButton(AlertDialog.BUTTON_POSITIVE)
    val negative = getButton(AlertDialog.BUTTON_NEGATIVE)
    val buttonPanel = findViewById<View>(androidx.appcompat.R.id.buttonPanel)

    assertTrue("file-transfer business dialog uses the real Material button panel", buttonPanel != null)
    assertEquals(activity.getString(kind.positiveButtonRes), positive.text.toString())
    assertEquals(activity.getString(kind.negativeButtonRes), negative.text.toString())
    positive.assertReadableDialogActionButton(activity)
    negative.assertReadableDialogActionButton(activity)
}

private fun AlertDialog.assertCustomContentStaysAboveActions(content: ScrollView) {
    val positive = getButton(AlertDialog.BUTTON_POSITIVE)
    val negative = getButton(AlertDialog.BUTTON_NEGATIVE)
    val actionTop = minOf(positive.screenTop(), negative.screenTop())
    val contentBottom = content.screenBottom()
    val decorBottom = checkNotNull(window?.decorView) { "dialog decor exists" }.screenBottom()
    val geometry =
        "contentBottom=$contentBottom actionTop=$actionTop " +
            "contentTop=${content.screenTop()} contentHeight=${content.height} " +
            "positiveTop=${positive.screenTop()} positiveHeight=${positive.height} " +
            "negativeTop=${negative.screenTop()} negativeHeight=${negative.height} " +
            "decorBottom=$decorBottom"

    assertTrue("file-transfer dialog content stays above actions: $geometry", contentBottom <= actionTop)
    assertTrue("file-transfer dialog content has a visible top edge", content.screenTop() >= 0)
    assertTrue("file-transfer dialog actions are visible", positive.screenBottom() > actionTop && negative.screenBottom() > actionTop)
    assertTrue(
        "file-transfer dialog actions stay within decor bounds: $geometry",
        positive.screenBottom() <= decorBottom && negative.screenBottom() <= decorBottom,
    )
}

private fun AlertDialog.assertNoDuplicateTalkBackSemantics(
    title: String,
    content: View,
) {
    val titleView = window?.decorView?.findTextViewWithText(title)
    val positive = getButton(AlertDialog.BUTTON_POSITIVE)
    val negative = getButton(AlertDialog.BUTTON_NEGATIVE)

    assertNull("dialog title text should not duplicate itself as a content description", titleView?.contentDescription)
    assertNull("positive action should not duplicate itself as a content description", positive.contentDescription)
    assertNull("negative action should not duplicate itself as a content description", negative.contentDescription)
    content.forEachTextView { textView ->
        assertNull(
            "${textView.resources.getResourceEntryName(textView.id)} should not duplicate itself as a content description",
            textView.contentDescription,
        )
    }
}

private fun ScrollView.assertBusinessDialogContentCanScrollIntoView(targetId: Int) {
    val target = checkNotNull(findViewById<TextView>(targetId)) { "target field exists" }
    val visibleHeight = height - paddingTop - paddingBottom
    assertTrue("file-transfer dialog leaves a usable viewport", visibleHeight > 0)
    if (target.height > visibleHeight || target.bottom > scrollY + visibleHeight) {
        scrollTo(0, target.top.coerceAtLeast(0))
        assertTrue("target top can scroll into viewport", target.top >= scrollY)
        assertTrue("target top is visible after targeted scroll", target.top < scrollY + visibleHeight)
        scrollTo(0, (target.bottom - visibleHeight).coerceAtLeast(0))
        assertTrue("target bottom can scroll into viewport", target.bottom <= scrollY + visibleHeight)
    } else {
        assertTrue("target is visible when dialog content fits", target.bottom <= scrollY + visibleHeight)
    }
}

private fun assertTextReadable(text: TextView?) {
    val label = text?.resources?.getResourceEntryName(text.id) ?: "dialog title"
    val textView = checkNotNull(text) { "$label exists" }
    val textLayout = checkNotNull(textView.layout) { "$label has text layout" }
    assertTrue("$label has visible width", textView.measuredWidth > 0)
    assertTrue("$label has visible height", textView.measuredHeight > 0)
    assertTrue(
        "$label is not ellipsized",
        (0 until textLayout.lineCount).all { line -> textLayout.getEllipsisCount(line) == 0 },
    )
    assertEquals("$label renders complete text", textView.text.length, textLayout.getLineEnd(textLayout.lineCount - 1))
    val contentWidth = textView.width - textView.compoundPaddingLeft - textView.compoundPaddingRight
    val maximumLineWidth = (0 until textLayout.lineCount).maxOf(textLayout::getLineWidth)
    assertTrue(
        "$label line width $maximumLineWidth fits $contentWidth",
        maximumLineWidth <= contentWidth + DIALOG_ACTION_TEXT_LAYOUT_TOLERANCE_PX,
    )
}

private fun TextView.hasNestedScrollAncestor(): Boolean {
    var current = parent
    while (current is View) {
        if (current is NestedScrollView) return true
        current = (current as? ViewGroup)?.parent
    }
    return false
}

private fun View.findTextViewWithText(expected: String): TextView? {
    if (this is TextView && text.toString() == expected) return this
    if (this !is ViewGroup) return null
    for (index in 0 until childCount) {
        getChildAt(index).findTextViewWithText(expected)?.let { return it }
    }
    return null
}

private fun View.forEachTextView(action: (TextView) -> Unit) {
    if (this is TextView) action(this)
    if (this !is ViewGroup) return
    for (index in 0 until childCount) {
        getChildAt(index).forEachTextView(action)
    }
}

private fun View.screenTop(): Int {
    val location = IntArray(2)
    getLocationOnScreen(location)
    return location[1]
}

private fun View.screenBottom(): Int = screenTop() + height

private fun View.measureAndLayoutWithin(
    context: Context,
    configuration: DialogConfiguration,
) {
    measure(
        View.MeasureSpec.makeMeasureSpec(dp(context, configuration.widthDp), View.MeasureSpec.AT_MOST),
        View.MeasureSpec.makeMeasureSpec(dp(context, configuration.heightDp), View.MeasureSpec.AT_MOST),
    )
    layout(0, 0, measuredWidth, measuredHeight)
}

private data class DialogConfiguration(
    val widthDp: Int,
    val heightDp: Int,
    val fontScale: Float,
)

private enum class FileTransferBusinessDialogKind(
    val layoutRes: Int,
    val titleRes: Int,
    val positiveButtonRes: Int,
    val negativeButtonRes: Int,
) {
    INCOMING(
        layoutRes = R.layout.dialog_file_transfer_offer,
        titleRes = R.string.file_transfer_offer_title,
        positiveButtonRes = R.string.file_transfer_accept,
        negativeButtonRes = R.string.file_transfer_reject,
    ) {
        override fun render(context: Context, root: View) {
            renderSampleOffer(context, root)
        }
    },
    OUTGOING(
        layoutRes = R.layout.dialog_file_transfer_outgoing,
        titleRes = R.string.file_transfer_outgoing_title,
        positiveButtonRes = R.string.file_transfer_outgoing_send,
        negativeButtonRes = R.string.cancel,
    ) {
        override fun render(context: Context, root: View) {
            renderSampleOutgoing(context, root)
        }
    };

    abstract fun render(context: Context, root: View)
}

private const val DIALOG_ACTION_TEXT_LAYOUT_TOLERANCE_PX = 2f

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
