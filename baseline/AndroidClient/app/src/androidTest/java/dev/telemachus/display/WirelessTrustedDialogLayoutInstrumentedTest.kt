package dev.telemachus.display

import android.content.Context
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
class WirelessTrustedDialogLayoutInstrumentedTest {
    @Test
    fun standardMaterialMessageDialogKeepsTrustedLanCopyReadable() {
        listOf(
            DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 1.5f),
            DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 2.0f),
            DialogConfiguration(widthDp = 360, heightDp = 740, fontScale = 1.5f),
            DialogConfiguration(widthDp = 360, heightDp = 740, fontScale = 2.0f),
            DialogConfiguration(widthDp = 640, heightDp = 320, fontScale = 2.0f),
        ).forEach { configuration ->
            withTrustedNetworkDialog(configuration) { activity, dialog ->
                val title = dialog.findViewById<TextView>(androidx.appcompat.R.id.alertTitle)
                val message = checkNotNull(dialog.findViewById<TextView>(android.R.id.message))
                val positive = dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                val negative = dialog.getButton(AlertDialog.BUTTON_NEGATIVE)

                assertEquals(activity.getString(R.string.trusted_network_dialog_title), title?.text?.toString())
                assertEquals(activity.getString(R.string.trusted_network_dialog_message), message.text.toString())
                assertTextReadable(title)
                assertTextReadable(message)
                assertTrue("standard dialog message is inside a NestedScrollView", message.hasNestedScrollAncestor())
                assertNull("standard message text should not duplicate itself as a content description", message.contentDescription)
                assertEquals(activity.getString(R.string.trusted_network_dialog_confirm), positive.text.toString())
                assertEquals(activity.getString(android.R.string.cancel), negative.text.toString())
                assertTextReadable(positive)
                assertTextReadable(negative)
                positive.assertMinimumTouchTarget(activity)
                negative.assertMinimumTouchTarget(activity)
            }
        }
    }

    @Test
    fun trustedLanDialogConfirmationAndCancelCallbacksStayIsolated() {
        var confirmed = 0

        withTrustedNetworkDialog(DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 1.5f), onConfirmed = { confirmed++ }) { _, dialog ->
            dialog.getButton(AlertDialog.BUTTON_NEGATIVE).performClick()
        }
        assertEquals("cancel must not acknowledge trusted LAN", 0, confirmed)

        withTrustedNetworkDialog(DialogConfiguration(widthDp = 320, heightDp = 640, fontScale = 1.5f), onConfirmed = { confirmed++ }) { _, dialog ->
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
        }
        assertEquals("confirm acknowledges trusted LAN exactly once", 1, confirmed)
    }

    private fun withTrustedNetworkDialog(
        configuration: DialogConfiguration,
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
                        dialog = checkNotNull(showTrustedNetworkDialog(activity, onConfirmed))
                    }
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

    private fun assertTextReadable(text: TextView?) {
        val label = text?.resources?.getResourceEntryName(text.id) ?: "dialog title"
        val textView = checkNotNull(text) { "$label exists" }
        val layout = checkNotNull(textView.layout) { "$label has text layout" }
        assertTrue("$label has visible width", textView.measuredWidth > 0)
        assertTrue("$label has visible height", textView.measuredHeight > 0)
        assertTrue("$label has no ellipsized lines", (0 until layout.lineCount).all { line -> layout.getEllipsisCount(line) == 0 })
        assertEquals("$label renders complete text", textView.text.length, layout.getLineEnd(layout.lineCount - 1))
    }

    private fun TextView.hasNestedScrollAncestor(): Boolean {
        var current = parent
        while (current is View) {
            if (current is NestedScrollView) return true
            current = (current as? ViewGroup)?.parent
        }
        return false
    }

    private fun Button.assertMinimumTouchTarget(context: Context) {
        val minimum = context.dp(48)
        assertTrue("$text button is at least 48dp wide", width >= minimum)
        assertTrue("$text button is at least 48dp tall", height >= minimum)
    }

    private fun Context.dp(value: Int): Int =
        (value * resources.displayMetrics.density).roundToInt()

    private data class DialogConfiguration(
        val widthDp: Int,
        val heightDp: Int,
        val fontScale: Float,
    )
}
