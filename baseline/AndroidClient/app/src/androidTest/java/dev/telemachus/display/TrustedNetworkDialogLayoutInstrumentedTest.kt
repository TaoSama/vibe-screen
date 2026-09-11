package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.text.Layout
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.core.widget.NestedScrollView
import androidx.test.core.app.ActivityScenario
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
    fun standardMaterialMessageDialogKeepsCopyReadableScrollableAndActionsReachable() {
        listOf(
            TrustedDialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 1.5f),
            TrustedDialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 2.0f),
            TrustedDialogConfiguration(widthDp = 640, heightDp = 320, fontScale = 1.5f),
            TrustedDialogConfiguration(widthDp = 640, heightDp = 320, fontScale = 2.0f),
        ).forEach { configuration ->
            withProductionTrustedNetworkDialog(configuration) { activity, dialog ->
                val title = dialog.dialogTitleTextView()
                val message = dialog.trustedNetworkDialogMessage()
                val messageScroll = message.nestedScrollAncestor()
                val positive = dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                val negative = dialog.getButton(AlertDialog.BUTTON_NEGATIVE)

                assertEquals(activity.getString(R.string.trusted_network_dialog_title), title.text.toString())
                assertEquals(activity.getString(R.string.trusted_network_dialog_message), message.text.toString())
                assertEquals(activity.getString(R.string.trusted_network_dialog_confirm), positive.text.toString())
                assertEquals(activity.getString(R.string.cancel), negative.text.toString())
                assertTextReadable(title)
                assertTextReadable(message)
                assertEquals(Layout.BREAK_STRATEGY_BALANCED, message.breakStrategy)
                assertEquals(Layout.HYPHENATION_FREQUENCY_NORMAL, message.hyphenationFrequency)
                dialog.assertDialogButton(positive)
                dialog.assertDialogButton(negative)
                dialog.assertNoDuplicateTalkBackSemantics()
                dialog.assertMessageScrollStaysAboveActions(messageScroll)
                messageScroll.assertMessageCanScrollIntoView(message)
            }
        }
    }

    @Test
    fun restrictedLandscapeLargeFontStandardMessageRequiresScrollableContent() {
        withProductionTrustedNetworkDialog(TrustedDialogConfiguration(widthDp = 640, heightDp = 320, fontScale = 2.0f)) { _, dialog ->
            val message = dialog.trustedNetworkDialogMessage()
            val messageScroll = message.nestedScrollAncestor()

            assertTrue(
                "restricted landscape dialog message needs vertical scrolling",
                message.height > messageScroll.visibleHeight(),
            )
            messageScroll.assertMessageCanScrollIntoView(message)
            dialog.assertMessageScrollStaysAboveActions(messageScroll)
        }
    }

    @Test
    fun productionMaterialDialogInvokesConfirmCallbackOnlyFromPositiveAction() {
        var confirmed = 0

        withProductionTrustedNetworkDialog(TrustedDialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 1.5f), onConfirmed = { confirmed++ }) { _, dialog ->
            assertTrue(
                "cancel click is handled without confirming trusted LAN",
                dialog.getButton(AlertDialog.BUTTON_NEGATIVE).performClick(),
            )
            assertEquals("cancel must not acknowledge trusted LAN", 0, confirmed)
        }

        withProductionTrustedNetworkDialog(TrustedDialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 1.5f), onConfirmed = { confirmed++ }) { _, dialog ->
            assertTrue(
                "confirm click is handled by the trusted LAN callback",
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick(),
            )
            assertEquals("confirm acknowledges trusted LAN exactly once", 1, confirmed)
        }
    }

    private fun withProductionTrustedNetworkDialog(
        configuration: TrustedDialogConfiguration,
        onConfirmed: () -> Unit = {},
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
                        dialog = createTrustedNetworkDialog(activity, onConfirmed)
                        dialog?.show()
                    }
                    InstrumentationRegistry.getInstrumentation().waitForIdleSync()
                    scenario.onActivity { activity ->
                        try {
                            val shownDialog = checkNotNull(dialog)
                            shownDialog.window?.decorView?.let { decor ->
                                decor.measure(
                                    View.MeasureSpec.makeMeasureSpec(activity.dp(configuration.widthDp), View.MeasureSpec.AT_MOST),
                                    View.MeasureSpec.makeMeasureSpec(activity.dp(configuration.heightDp), View.MeasureSpec.AT_MOST),
                                )
                                decor.layout(0, 0, decor.measuredWidth, decor.measuredHeight)
                            }
                            assertion(activity, shownDialog)
                        } catch (failure: Throwable) {
                            assertionFailure = failure
                        }
                    }
                    assertionFailure?.let { throw it }
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

    private fun AlertDialog.dialogTitleTextView(): TextView =
        checkNotNull(window?.decorView?.findTextViewWithText(context.getString(R.string.trusted_network_dialog_title))) {
            "trusted network dialog title is present"
        }

    private fun AlertDialog.trustedNetworkDialogMessage(): TextView =
        checkNotNull(findViewById(android.R.id.message)) {
            "trusted network dialog message is present"
        }

    private fun assertTextReadable(text: TextView?) {
        val label = text?.resources?.getResourceEntryName(text.id) ?: "dialog title"
        val textView = checkNotNull(text) { "$label exists" }
        val layout = checkNotNull(textView.layout) { "$label has text layout" }
        assertTrue("$label has visible width", textView.measuredWidth > 0)
        assertTrue("$label has visible height", textView.measuredHeight > 0)
        assertTrue("$label has no ellipsized lines", (0 until layout.lineCount).all { line -> layout.getEllipsisCount(line) == 0 })
        assertEquals("$label renders complete text", textView.text.length, layout.getLineEnd(layout.lineCount - 1))
    }

    private fun AlertDialog.assertDialogButton(button: Button) {
        assertTrue("${button.text} button is at least 48dp wide", button.width >= context.dp(48))
        assertTrue("${button.text} button is at least 48dp tall", button.height >= context.dp(48))
        assertTrue("${button.text} button can wrap to two lines", button.maxLines >= 2)
        assertNull("${button.text} button should not ellipsize", button.ellipsize)
    }

    private fun AlertDialog.assertNoDuplicateTalkBackSemantics() {
        val title = dialogTitleTextView()
        val message = trustedNetworkDialogMessage()
        val positive = getButton(AlertDialog.BUTTON_POSITIVE)
        val negative = getButton(AlertDialog.BUTTON_NEGATIVE)

        assertNull("title text should not duplicate itself as a content description", title.contentDescription)
        assertNull("message text should not duplicate itself as a content description", message.contentDescription)
        assertNull("confirm text should not duplicate itself as a content description", positive.contentDescription)
        assertNull("cancel text should not duplicate itself as a content description", negative.contentDescription)
    }

    private fun AlertDialog.assertMessageScrollStaysAboveActions(messageScroll: NestedScrollView) {
        val positive = getButton(AlertDialog.BUTTON_POSITIVE)
        val negative = getButton(AlertDialog.BUTTON_NEGATIVE)
        val actionTop = minOf(positive.screenTop(), negative.screenTop())
        val contentBottom = messageScroll.screenBottom()
        val geometry =
            "contentBottom=$contentBottom actionTop=$actionTop " +
                "messageScrollTop=${messageScroll.screenTop()} messageScrollHeight=${messageScroll.height} " +
                "positiveTop=${positive.screenTop()} positiveHeight=${positive.height} " +
                "negativeTop=${negative.screenTop()} negativeHeight=${negative.height}"

        assertTrue("trusted network message scroll stays above dialog actions: $geometry", contentBottom <= actionTop)
        assertTrue("trusted network message scroll has a visible top edge", messageScroll.screenTop() >= 0)
        assertTrue("trusted network actions are visible", positive.screenBottom() > actionTop && negative.screenBottom() > actionTop)
    }

    private fun NestedScrollView.assertMessageCanScrollIntoView(message: TextView) {
        val visibleHeight = visibleHeight()
        assertTrue("trusted network dialog leaves a usable viewport", visibleHeight > 0)
        if (message.height > visibleHeight) {
            scrollTo(0, (message.top - paddingTop).coerceAtLeast(0))
            assertTrue("message top can scroll into viewport", message.top >= visibleTop())
            assertTrue("message top is visible after targeted scroll", message.top < visibleBottom())
            scrollTo(0, (message.bottom - height + paddingBottom).coerceAtLeast(0))
            assertTrue("message bottom can scroll into viewport", message.bottom <= visibleBottom())
        } else {
            assertTrue("trusted network message top is visible when content fits", message.top >= visibleTop())
            assertTrue("trusted network message bottom is visible when content fits", message.bottom <= visibleBottom())
        }
    }

    private fun TextView.nestedScrollAncestor(): NestedScrollView {
        var current = parent
        while (current is View) {
            if (current is NestedScrollView) return current
            current = (current as? ViewGroup)?.parent
        }
        error("standard dialog message is inside a NestedScrollView")
    }

    private fun NestedScrollView.visibleHeight(): Int = height - paddingTop - paddingBottom

    private fun NestedScrollView.visibleTop(): Int = scrollY + paddingTop

    private fun NestedScrollView.visibleBottom(): Int = scrollY + height - paddingBottom

    private fun View.findTextViewWithText(expected: String): TextView? {
        if (this is TextView && text.toString() == expected) return this
        if (this !is ViewGroup) return null
        for (index in 0 until childCount) {
            getChildAt(index).findTextViewWithText(expected)?.let { return it }
        }
        return null
    }

    private fun View.screenTop(): Int {
        val location = IntArray(2)
        getLocationOnScreen(location)
        return location[1]
    }

    private fun View.screenBottom(): Int = screenTop() + height

    private fun Context.dp(value: Int): Int =
        (value * resources.displayMetrics.density).roundToInt()

    private data class TrustedDialogConfiguration(
        val widthDp: Int,
        val heightDp: Int,
        val fontScale: Float,
    )
}
