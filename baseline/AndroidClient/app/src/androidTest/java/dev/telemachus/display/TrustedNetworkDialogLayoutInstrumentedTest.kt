package dev.telemachus.display

import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Rect
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TrustedNetworkDialogLayoutInstrumentedTest {
    @Test
    fun narrowAndLargeFontTrustedNetworkDialogKeepsCopyReadableAndReachable() {
        listOf(
            Triple(320, 640, 1.5f),
            Triple(320, 640, 2.0f),
            Triple(360, 740, 1.5f),
            Triple(360, 740, 2.0f),
            Triple(640, 320, 1.5f),
            Triple(640, 320, 2.0f),
        ).forEach { (widthDp, heightDp, fontScale) ->
            withTrustedNetworkLayout(widthDp = widthDp, heightDp = heightDp, fontScale = fontScale) { layout ->
                layout.measureAndLayout()

                assertEquals(layout.dialogWidthPx, layout.root.measuredWidth)
                assertEquals(layout.dialogHeightPx, layout.root.measuredHeight)
                assertTrue("trusted network scroll view fills constrained dialog viewport", layout.scroll.isFillViewport)
                layout.assertTextReadable(layout.message)
                layout.assertTalkBackReadsDialogMessage()
                layout.assertMessageCanScrollIntoView()
            }
        }
    }

    @Test
    fun restrictedLandscapeLargeFontTrustedNetworkDialogRequiresScrollableContent() {
        withTrustedNetworkLayout(widthDp = 640, heightDp = 320, fontScale = 2.0f, heightRatio = RESTRICTED_LANDSCAPE_HEIGHT_RATIO) { layout ->
            layout.measureAndLayout()

            assertTrue("restricted landscape keeps a usable viewport", layout.visibleHeight() > layout.dp(48))
            assertTrue("large-text trusted network content is taller than the restricted viewport", layout.content.height > layout.visibleHeight())
            layout.assertTextReadable(layout.message)
            layout.assertMessageCanScrollIntoView()
            layout.assertTalkBackReadsDialogMessage()
        }
    }

    @Test
    fun productionMaterialDialogKeepsTitleBodyAndActionsReachable() {
        listOf(
            ProductionDialogCase(320, 640, 1.5f, TRUSTED_NETWORK_DIALOG_MAX_HEIGHT_RATIO),
            ProductionDialogCase(320, 640, 2.0f, TRUSTED_NETWORK_DIALOG_MAX_HEIGHT_RATIO),
            ProductionDialogCase(360, 740, 1.5f, TRUSTED_NETWORK_DIALOG_MAX_HEIGHT_RATIO),
            ProductionDialogCase(360, 740, 2.0f, TRUSTED_NETWORK_DIALOG_MAX_HEIGHT_RATIO),
            ProductionDialogCase(640, 320, 1.5f, RESTRICTED_LANDSCAPE_HEIGHT_RATIO),
            ProductionDialogCase(640, 320, 2.0f, RESTRICTED_LANDSCAPE_HEIGHT_RATIO),
        ).forEach { testCase ->
            withProductionTrustedNetworkDialog(testCase) { dialog, layout ->
                assertTrue("production dialog measures trusted network root width", layout.root.measuredWidth > 0)
                assertTrue("production dialog measures trusted network root height", layout.root.measuredHeight > 0)
                assertTrue("production trusted network dialog uses scroll content", layout.root.isFillViewport)
                dialog.assertTrustedNetworkButtonTouchTargets(layout.context)
                dialog.assertTrustedNetworkActionsReadable(layout.context)
                dialog.assertTrustedNetworkVisibleTextAndActionsDoNotOverlap()
                dialog.assertTrustedNetworkTitleReadable()
                dialog.assertNoDuplicateTalkBackSemantics()
                layout.assertTextReadable(layout.message)
                layout.assertTalkBackReadsDialogMessage()
                layout.assertMessageCanScrollIntoView()
            }
        }
    }

    @Test
    fun productionMaterialDialogInvokesConfirmCallbackOnlyFromPositiveAction() {
        var confirmed = 0

        withProductionTrustedNetworkDialog(
            testCase = ProductionDialogCase(360, 740, 1.0f, TRUSTED_NETWORK_DIALOG_MAX_HEIGHT_RATIO),
            onConfirmed = { confirmed++ },
        ) { dialog, _ ->
            dialog.getButton(AlertDialog.BUTTON_NEGATIVE).performClick()
        }
        assertEquals("cancel must not acknowledge trusted LAN", 0, confirmed)

        withProductionTrustedNetworkDialog(
            testCase = ProductionDialogCase(360, 740, 1.0f, TRUSTED_NETWORK_DIALOG_MAX_HEIGHT_RATIO),
            onConfirmed = { confirmed++ },
        ) { dialog, _ ->
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
        }
        assertEquals("confirm acknowledges trusted LAN exactly once", 1, confirmed)
    }

    private fun withTrustedNetworkLayout(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float,
        heightRatio: Float = TRUSTED_NETWORK_DIALOG_MAX_HEIGHT_RATIO,
        assertion: (TrustedNetworkMeasuredLayout) -> Unit,
    ) {
        val context = configuredContext(widthDp, heightDp, fontScale)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val parent = FrameLayout(context)
            val root = inflate(context, parent, R.layout.dialog_trusted_network) as ScrollView
            try {
                parent.addView(root)
                TrustedNetworkMeasuredLayout(context, parent, root, layoutWidth(context, widthDp), layoutHeight(context, heightDp, heightRatio))
                    .let(assertion)
            } finally {
                parent.removeAllViews()
                root.removeAllViews()
            }
        }
        instrumentation.waitForIdleSync()
    }

    private fun withProductionTrustedNetworkDialog(
        testCase: ProductionDialogCase,
        onConfirmed: () -> Unit = {},
        assertion: (AlertDialog, TrustedNetworkMeasuredLayout) -> Unit,
    ) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        var activity: DialogHostActivity? = null
        var dialog: AlertDialog? = null
        var assertionFailure: Throwable? = null
        DialogHostActivity.configurationOverride =
            DialogHostActivity.ConfigurationOverride(
                widthDp = testCase.widthDp,
                heightDp = testCase.heightDp,
                fontScale = testCase.fontScale,
            )
        try {
            activity =
                instrumentation.startActivitySync(
                    Intent(applicationContext(), DialogHostActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                ) as DialogHostActivity
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                val hostActivity = checkNotNull(activity)
                dialog =
                    createTrustedNetworkDialog(hostActivity, onConfirmed = onConfirmed).also { shownDialog ->
                        shownDialog.show()
                        shownDialog.window?.setLayout(
                            layoutWidth(hostActivity, testCase.widthDp),
                            ViewGroup.LayoutParams.WRAP_CONTENT,
                        )
                    }
            }
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                try {
                    val hostActivity = checkNotNull(activity)
                    val shownDialog = checkNotNull(dialog)
                    val dialogRoot = shownDialog.trustedNetworkDialogRoot()
                    val measured =
                        TrustedNetworkMeasuredLayout(
                            context = hostActivity,
                            viewport = FrameLayout(hostActivity),
                            root = dialogRoot,
                            dialogWidthPx = layoutWidth(hostActivity, testCase.widthDp),
                            dialogHeightPx = layoutHeight(hostActivity, testCase.heightDp, testCase.heightRatio),
                        ).also { it.measureForAssertions() }
                    assertion(shownDialog, measured)
                } catch (failure: Throwable) {
                    assertionFailure = failure
                }
            }
            assertionFailure?.let { throw it }
        } finally {
            instrumentation.runOnMainSync {
                dialog?.dismiss()
                activity?.finish()
                dialog = null
                activity = null
            }
            instrumentation.waitForIdleSync()
            DialogHostActivity.configurationOverride = null
        }
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
            root.measure(
                View.MeasureSpec.makeMeasureSpec(dialogWidthPx, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(dialogHeightPx, View.MeasureSpec.EXACTLY),
            )
            root.layout(0, 0, root.measuredWidth, root.measuredHeight)
        }

        fun measureForAssertions() {
            if (root.measuredWidth <= 0 || root.measuredHeight <= 0) {
                measureOnly()
            }
            if (root.parent == null) {
                measureAndLayout()
            } else if (root.width <= 0 || root.height <= 0) {
                root.layout(0, 0, root.measuredWidth, root.measuredHeight)
            }
        }

        private fun measureOnly() {
            root.layoutParams =
                (root.layoutParams as ViewGroup.LayoutParams).apply {
                    width = ViewGroup.LayoutParams.MATCH_PARENT
                    height = dialogHeightPx
                }
            root.forceLayout()
            root.measure(
                View.MeasureSpec.makeMeasureSpec(dialogWidthPx, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(dialogHeightPx, View.MeasureSpec.EXACTLY),
            )
        }

        fun assertTextReadable(text: TextView) {
            val label = text.resources.getResourceEntryName(text.id)
            val textLayout = checkNotNull(text.layout) { "$label has text layout" }
            assertTrue("$label is laid out with at least one line", textLayout.lineCount > 0)
            assertTrue(
                "$label is not ellipsized",
                (0 until textLayout.lineCount).all { line -> textLayout.getEllipsisCount(line) == 0 },
            )
            val availableTextWidth = text.width - text.totalPaddingLeft - text.totalPaddingRight
            assertTrue(
                "$label line widths fit parent content",
                (0 until textLayout.lineCount).all { line -> textLayout.getLineWidth(line) <= availableTextWidth + TEXT_LAYOUT_SUBPIXEL_TOLERANCE_PX },
            )
            assertFalse(
                "$label should not scroll horizontally",
                text.canScrollHorizontally(-1) || text.canScrollHorizontally(1),
            )
            assertTrue("$label starts inside parent content", text.left >= 0)
            assertTrue("$label ends inside parent content", text.right <= (text.parent as View).width)
        }

        fun assertMessageCanScrollIntoView() {
            val visibleHeight = visibleHeight()
            assertTrue("trusted network dialog leaves a usable viewport", visibleHeight > 0)
            scroll.scrollTo(0, message.top.coerceAtLeast(0))
            assertTrue("message top can scroll into viewport", message.top >= scroll.scrollY)
            assertTrue("message top is visible after targeted scroll", message.top < scroll.scrollY + visibleHeight)
            scroll.scrollTo(0, (message.bottom - visibleHeight).coerceAtLeast(0))
            assertTrue("message bottom can scroll into viewport", message.bottom <= scroll.scrollY + visibleHeight)
        }

        fun assertTalkBackReadsDialogMessage() {
            assertNull("message should not duplicate TalkBack text through contentDescription", message.contentDescription)
            val info = AccessibilityNodeInfo.obtain()
            try {
                message.onInitializeAccessibilityNodeInfo(info)
                assertEquals(context.getString(R.string.trusted_network_dialog_message), info.text.toString())
            } finally {
                info.recycle()
            }
        }

        fun visibleHeight(): Int = (scroll.height.takeIf { it > 0 } ?: scroll.measuredHeight) - scroll.paddingTop - scroll.paddingBottom

        fun dp(value: Int): Int = dp(context, value)
    }
}

private const val TRUSTED_NETWORK_DIALOG_WINDOW_MARGIN_DP = 24
private const val TRUSTED_NETWORK_DIALOG_MAX_HEIGHT_RATIO = 0.85f
private const val TRUSTED_NETWORK_DIALOG_ACTION_MAX_LINES = 2
private const val RESTRICTED_LANDSCAPE_HEIGHT_RATIO = 0.36f
private const val TEXT_LAYOUT_SUBPIXEL_TOLERANCE_PX = 2f

private data class ProductionDialogCase(
    val widthDp: Int,
    val heightDp: Int,
    val fontScale: Float,
    val heightRatio: Float,
)

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
): Int = dp(context, screenWidthDp - TRUSTED_NETWORK_DIALOG_WINDOW_MARGIN_DP * 2)

private fun layoutHeight(
    context: Context,
    screenHeightDp: Int,
    heightRatio: Float,
): Int = dp(context, (screenHeightDp * heightRatio).roundToInt())

private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

private fun dp(
    context: Context,
    value: Int,
): Int {
    val density =
        context.resources.displayMetrics.density.takeIf { it > 0f }
            ?: applicationContext().resources.displayMetrics.density
    return (value * density).roundToInt()
}

private fun AlertDialog.assertTrustedNetworkButtonTouchTargets(context: Context) {
    listOf(
        getButton(AlertDialog.BUTTON_NEGATIVE),
        getButton(AlertDialog.BUTTON_POSITIVE),
    ).forEach { button: Button ->
        val minimum = dp(context, 48)
        assertTrue(button.text.toString() + " button is at least 48dp wide", button.width >= minimum)
        assertTrue(button.text.toString() + " button is at least 48dp tall", button.height >= minimum)
    }
}

private fun AlertDialog.assertTrustedNetworkActionsReadable(context: Context) {
    val negative = getButton(AlertDialog.BUTTON_NEGATIVE)
    val positive = getButton(AlertDialog.BUTTON_POSITIVE)
    assertEquals(context.getString(R.string.cancel), negative.text.toString())
    assertEquals(context.getString(R.string.trusted_network_dialog_confirm), positive.text.toString())
    listOf(negative, positive).forEach { button ->
        val label = button.text.toString()
        assertTrue(label + " action can wrap", button.maxLines >= TRUSTED_NETWORK_DIALOG_ACTION_MAX_LINES)
        assertEquals(label + " action should not ellipsize", null, button.ellipsize)
        val textLayout = checkNotNull(button.layout) { label + " action has text layout" }
        assertTrue(label + " action is laid out with at least one line", textLayout.lineCount > 0)
        assertTrue(
            label + " action is not ellipsized",
            (0 until textLayout.lineCount).all { line -> textLayout.getEllipsisCount(line) == 0 },
        )
    }
}

private fun AlertDialog.assertTrustedNetworkVisibleTextAndActionsDoNotOverlap() {
    val visibleElements =
        listOf(
            trustedNetworkDialogTitle(),
            trustedNetworkDialogRoot().findViewById<TextView>(R.id.trustedNetworkDialogMessage),
            getButton(AlertDialog.BUTTON_NEGATIVE),
            getButton(AlertDialog.BUTTON_POSITIVE),
        )
            .filter { it.visibility == View.VISIBLE }
            .map { view -> view.debugName() to view.visibleBounds() }

    visibleElements.forEachIndexed { index, namedBounds ->
        val (name, bounds) = namedBounds
        assertTrue(name + " should have visible bounds", !bounds.isEmpty)
        visibleElements.drop(index + 1).forEach { (otherName, otherBounds) ->
            assertFalse(name + " must not overlap " + otherName, Rect.intersects(bounds, otherBounds))
        }
    }
}

private fun AlertDialog.assertTrustedNetworkTitleReadable() {
    val title = trustedNetworkDialogTitle()
    assertEquals(context.getString(R.string.trusted_network_dialog_title), title.text.toString())
    val textLayout = checkNotNull(title.layout) { "trusted network dialog title has text layout" }
    assertTrue("trusted network dialog title is laid out with at least one line", textLayout.lineCount > 0)
    assertTrue(
        "trusted network dialog title is not ellipsized",
        (0 until textLayout.lineCount).all { line -> textLayout.getEllipsisCount(line) == 0 },
    )
    val availableTextWidth = title.width - title.totalPaddingLeft - title.totalPaddingRight
    assertTrue(
        "trusted network dialog title line widths fit parent content",
        (0 until textLayout.lineCount).all { line -> textLayout.getLineWidth(line) <= availableTextWidth + TEXT_LAYOUT_SUBPIXEL_TOLERANCE_PX },
    )
    assertFalse(
        "trusted network dialog title should not scroll horizontally",
        title.canScrollHorizontally(-1) || title.canScrollHorizontally(1),
    )
    assertTrue("trusted network dialog title starts inside parent content", title.left >= 0)
    assertTrue("trusted network dialog title ends inside parent content", title.right <= (title.parent as View).width)
}

private fun AlertDialog.assertNoDuplicateTalkBackSemantics() {
    listOf(
        trustedNetworkDialogTitle(),
        trustedNetworkDialogRoot(),
        trustedNetworkDialogRoot().findViewById(R.id.trustedNetworkDialogContent),
        trustedNetworkDialogRoot().findViewById<TextView>(R.id.trustedNetworkDialogMessage),
        getButton(AlertDialog.BUTTON_NEGATIVE),
        getButton(AlertDialog.BUTTON_POSITIVE),
    ).forEach { view ->
        assertNull(view.debugName() + " should not duplicate TalkBack text", view.contentDescription)
    }
}

private fun AlertDialog.trustedNetworkDialogRoot(): ScrollView =
    checkNotNull(window?.decorView?.findViewById(R.id.trustedNetworkDialogScroll)) {
        "trusted network dialog root is present"
    }

private fun AlertDialog.trustedNetworkDialogTitle(): TextView =
    checkNotNull(window?.decorView?.findTextViewWithText(context.getString(R.string.trusted_network_dialog_title))) {
        "trusted network dialog title is present"
    }

private fun AlertDialog.trustedNetworkDialogMessage(): TextView =
    checkNotNull(window?.decorView?.findViewById(R.id.trustedNetworkDialogMessage)) {
        "trusted network dialog message is present"
    }

private fun View.visibleBounds(): Rect =
    Rect().also { bounds ->
        getGlobalVisibleRect(bounds)
    }

private fun View.findTextViewWithText(expectedText: String): TextView? {
    if (this is TextView && text.toString() == expectedText) return this
    if (this !is ViewGroup) return null
    return (0 until childCount)
        .asSequence()
        .mapNotNull { index -> getChildAt(index).findTextViewWithText(expectedText) }
        .firstOrNull()
}

private fun View.debugName(): String =
    if (id == View.NO_ID) {
        javaClass.simpleName
    } else {
        runCatching { resources.getResourceEntryName(id) }.getOrDefault(javaClass.simpleName)
    }
