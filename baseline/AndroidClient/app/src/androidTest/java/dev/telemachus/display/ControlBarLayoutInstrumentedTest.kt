package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.graphics.Rect
import android.text.TextUtils
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.LinearLayout
import android.widget.TextView
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.roundToInt

@RunWith(AndroidJUnit4::class)
class ControlBarLayoutInstrumentedTest {
    @Test
    fun revealActionIsARealClickableNodeOnlyWhileConnectedChromeIsHidden() {
        withLayout(widthDp = 320) { layout ->
            val inputViewport = layout.root.findViewById<View>(R.id.inputViewport)

            ControlBarAccessibilityApplier.applyRevealAction(
                inputViewport,
                connected = true,
                controlBarVisible = false,
            )
            val hiddenChromeNode = inputViewport.createAccessibilityNodeInfo()
            assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_YES, inputViewport.importantForAccessibility)
            assertEquals(
                layout.context.getString(R.string.show_stream_controls),
                hiddenChromeNode.contentDescription.toString(),
            )
            assertTrue(hiddenChromeNode.isClickable)
            assertTrue(hiddenChromeNode.actionList.any { it.id == AccessibilityNodeInfo.ACTION_CLICK })

            ControlBarAccessibilityApplier.applyRevealAction(
                inputViewport,
                connected = true,
                controlBarVisible = true,
            )
            assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_NO, inputViewport.importantForAccessibility)

            ControlBarAccessibilityApplier.applyRevealAction(
                inputViewport,
                connected = false,
                controlBarVisible = false,
            )
            assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_NO, inputViewport.importantForAccessibility)
        }
    }

    @Test
    fun phoneWidthsUseProductionInlineLayoutAndPreserveTouchTargets() {
        listOf(320, 360).forEach { widthDp ->
            withLayout(widthDp = widthDp) { layout ->
                assertEquals(ControlBarLayoutPolicy.Mode.INLINE, layout.mode)
                assertEquals(LinearLayout.HORIZONTAL, layout.views.content.orientation)
                assertEquals(LinearLayout.HORIZONTAL, layout.views.actions.orientation)
                assertEquals(0, layout.selectorParams.width)
                assertEquals(1f, layout.selectorParams.weight)
                assertAccessibleDisplayName(layout)
                assertActionGeometry(layout)
            }
        }
    }

    @Test
    fun productionBinderClearsStaleDisplayStateWhenSelectionIsUnavailable() {
        withLayout(widthDp = 320) { layout ->
            assertEquals(View.VISIBLE, layout.views.displaySelector.visibility)
            assertTrue(layout.views.displaySelector.isEnabled)

            val selectable =
                DisplayCapsuleViewBinder.bind(
                    resources = layout.context.resources,
                    selector = layout.views.displaySelector,
                    labelView = layout.label,
                    displaySelection = false,
                    displays = emptyList(),
                    selectedId = "",
                )

            assertFalse(selectable)
            assertEquals(View.GONE, layout.views.displaySelector.visibility)
            assertFalse(layout.views.displaySelector.isEnabled)
            assertEquals(
                layout.context.getString(R.string.display_capsule_placeholder),
                layout.label.text.toString(),
            )
            assertEquals(
                layout.context.getString(
                    R.string.control_displays_current,
                    layout.context.getString(R.string.display_capsule_placeholder),
                ),
                layout.views.displaySelector.contentDescription.toString(),
            )
        }
    }

    @Test
    fun productionApplierCoversStackedColumnAndHiddenSelectorBoundaries() {
        val geometry = ControlBarLayoutApplier.geometry(applicationContext().resources)
        val withHostColumnWidth =
            geometry.horizontalContentPaddingPx + geometry.horizontalActionsWidthPx(true)
        val withoutHostColumnWidth =
            geometry.horizontalContentPaddingPx + geometry.horizontalActionsWidthPx(false)
        val withHostInlineWidth = withHostColumnWidth + geometry.selectorMinimumWidthPx
        val withoutHostInlineWidth = withoutHostColumnWidth + geometry.selectorMinimumWidthPx
        assertModeAndShape(
            widthPx = withHostColumnWidth,
            selectorVisible = false,
            hostVisible = true,
            expectedMode = ControlBarLayoutPolicy.Mode.COMPACT,
        )
        assertModeAndShape(
            widthPx = withHostInlineWidth - 1,
            selectorVisible = true,
            hostVisible = true,
            expectedMode = ControlBarLayoutPolicy.Mode.STACKED,
        )
        assertModeAndShape(
            widthPx = withHostColumnWidth - 1,
            selectorVisible = true,
            hostVisible = true,
            expectedMode = ControlBarLayoutPolicy.Mode.COLUMN,
        )
        assertModeAndShape(
            widthPx = withoutHostInlineWidth - 1,
            selectorVisible = true,
            hostVisible = false,
            expectedMode = ControlBarLayoutPolicy.Mode.STACKED,
        )
        assertModeAndShape(
            widthPx = withoutHostColumnWidth - 1,
            selectorVisible = true,
            hostVisible = false,
            expectedMode = ControlBarLayoutPolicy.Mode.COLUMN,
        )
        assertModeAndShape(
            widthPx = withoutHostColumnWidth - 1,
            selectorVisible = false,
            hostVisible = false,
            expectedMode = ControlBarLayoutPolicy.Mode.COLUMN,
        )
    }

    @Test
    fun safeInsetsAndRepeatedResizeReapplyTheProductionLayout() {
        withLayout(widthDp = 320, applyLayout = false) { layout ->
            val baseMargins = ChromeSafeAreaApplier.captureBaseMargins(layout.views.card)
            val safeInsets =
                SafeAreaGeometry.Insets.of(
                    left = layout.dp(25),
                    top = layout.dp(7),
                    right = layout.dp(25),
                    bottom = layout.dp(9),
                )
            ChromeSafeAreaApplier.applyMargins(layout.views.card, baseMargins, safeInsets)
            var mode = layout.apply(windowWidthPx = layout.dp(320), safeAreaInsets = safeInsets)
            layout.measureAndLayout(layout.dp(320))
            assertEquals(ControlBarLayoutPolicy.Mode.STACKED, mode)
            assertMargins(layout, baseMargins, safeInsets)
            assertActionGeometry(layout)

            val changedInsets =
                SafeAreaGeometry.Insets.of(
                    left = layout.dp(10),
                    top = layout.dp(3),
                    right = layout.dp(20),
                    bottom = layout.dp(5),
                )
            ChromeSafeAreaApplier.applyMargins(layout.views.card, baseMargins, changedInsets)
            mode = layout.apply(windowWidthPx = layout.dp(360), safeAreaInsets = changedInsets)
            layout.measureAndLayout(layout.dp(360))
            assertEquals(ControlBarLayoutPolicy.Mode.INLINE, mode)
            assertMargins(layout, baseMargins, changedInsets)
            assertEquals(LinearLayout.HORIZONTAL, layout.views.content.orientation)
            assertEquals(1f, layout.selectorParams.weight)
            assertActionGeometry(layout)

            mode = layout.apply(windowWidthPx = layout.dp(183), safeAreaInsets = SafeAreaGeometry.Insets.NONE)
            ChromeSafeAreaApplier.applyMargins(
                layout.views.card,
                baseMargins,
                SafeAreaGeometry.Insets.NONE,
            )
            layout.measureAndLayout(layout.dp(183))
            assertEquals(ControlBarLayoutPolicy.Mode.COLUMN, mode)
            assertMargins(layout, baseMargins, SafeAreaGeometry.Insets.NONE)
            assertEquals(LinearLayout.VERTICAL, layout.views.actions.orientation)
            assertActionGeometry(layout)
        }
    }

    @Test
    fun resourceGeometryUsesExactPixelsAtNonIntegerDensityBoundaries() {
        val context = densityContext(DENSITY_DPI_FOR_2_75)
        val geometry = ControlBarLayoutApplier.geometry(context.resources)
        assertEquals(34, geometry.horizontalContentPaddingPx)
        assertEquals(242, geometry.selectorMinimumWidthPx)
        assertEquals(132, geometry.buttonSizePx)
        assertEquals(11, geometry.actionMarginPx)
        assertEquals(33, geometry.disconnectSeparationPx)
        assertEquals(22, geometry.columnActionSpacingPx)

        withLayout(context = context, widthPx = 749) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.INLINE, layout.mode)
        }
        withLayout(context = context, widthPx = 748) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.STACKED, layout.mode)
        }
        withLayout(context = context, widthPx = 507) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.STACKED, layout.mode)
        }
        withLayout(context = context, widthPx = 506) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COLUMN, layout.mode)
        }
        withLayout(context = context, widthPx = 595, hostVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.INLINE, layout.mode)
        }
        withLayout(context = context, widthPx = 594, hostVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.STACKED, layout.mode)
        }
        withLayout(context = context, widthPx = 353, hostVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.STACKED, layout.mode)
        }
        withLayout(context = context, widthPx = 352, hostVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COLUMN, layout.mode)
        }
    }

    @Test
    fun hiddenSelectorUsesExactCompactBoundariesAtNonIntegerDensity() {
        val context = densityContext(DENSITY_DPI_FOR_2_75)
        withLayout(context = context, widthPx = 507, selectorVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COMPACT, layout.mode)
        }
        withLayout(context = context, widthPx = 506, selectorVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COLUMN, layout.mode)
        }
        withLayout(
            context = context,
            widthPx = 353,
            selectorVisible = false,
            hostVisible = false,
        ) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COMPACT, layout.mode)
        }
        withLayout(
            context = context,
            widthPx = 352,
            selectorVisible = false,
            hostVisible = false,
        ) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COLUMN, layout.mode)
        }
    }

    private fun assertModeAndShape(
        widthPx: Int,
        selectorVisible: Boolean,
        hostVisible: Boolean,
        expectedMode: ControlBarLayoutPolicy.Mode,
    ) {
        withLayout(
            widthPx = widthPx,
            selectorVisible = selectorVisible,
            hostVisible = hostVisible,
        ) { layout ->
            assertEquals(expectedMode, layout.mode)
            when (expectedMode) {
                ControlBarLayoutPolicy.Mode.COMPACT -> {
                    assertEquals(ViewGroup.LayoutParams.WRAP_CONTENT, layout.cardParams.width)
                    assertEquals(LinearLayout.HORIZONTAL, layout.views.content.orientation)
                    assertEquals(LinearLayout.HORIZONTAL, layout.views.actions.orientation)
                }
                ControlBarLayoutPolicy.Mode.INLINE -> {
                    assertEquals(0, layout.cardParams.width)
                    assertEquals(LinearLayout.HORIZONTAL, layout.views.content.orientation)
                    assertEquals(LinearLayout.HORIZONTAL, layout.views.actions.orientation)
                    assertEquals(0, layout.selectorParams.width)
                    assertEquals(1f, layout.selectorParams.weight)
                }
                ControlBarLayoutPolicy.Mode.STACKED -> {
                    assertEquals(0, layout.cardParams.width)
                    assertEquals(LinearLayout.VERTICAL, layout.views.content.orientation)
                    assertEquals(LinearLayout.HORIZONTAL, layout.views.actions.orientation)
                    assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, layout.selectorParams.width)
                    assertEquals(0f, layout.selectorParams.weight)
                }
                ControlBarLayoutPolicy.Mode.COLUMN -> {
                    assertEquals(0, layout.cardParams.width)
                    assertEquals(LinearLayout.VERTICAL, layout.views.content.orientation)
                    assertEquals(LinearLayout.VERTICAL, layout.views.actions.orientation)
                    assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, layout.selectorParams.width)
                    assertEquals(0f, layout.selectorParams.weight)
                }
            }
            assertActionGeometry(layout)
        }
    }

    private fun assertAccessibleDisplayName(layout: MeasuredLayout) {
        assertEquals(FULL_DISPLAY_NAME, layout.label.text.toString())
        assertEquals(TextUtils.TruncateAt.END, layout.label.ellipsize)
        assertEquals(1, layout.label.maxLines)
        val expectedDescription =
            layout.context.getString(R.string.control_displays_current, FULL_DISPLAY_NAME)
        assertEquals(expectedDescription, layout.views.displaySelector.contentDescription.toString())
    }

    private fun assertActionGeometry(layout: MeasuredLayout) {
        val minimum = layout.context.resources.getDimensionPixelSize(R.dimen.control_bar_button_size)
        val safeBounds =
            Rect(
                layout.safeAreaInsets.left,
                layout.safeAreaInsets.top,
                layout.root.width - layout.safeAreaInsets.right,
                layout.root.height - layout.safeAreaInsets.bottom,
            )
        val cardBounds = descendantBounds(layout.root, layout.views.card)
        assertTrue("Control bar escaped the safe window", safeBounds.contains(cardBounds))
        if (layout.views.displaySelector.visibility == View.VISIBLE) {
            assertTrue(
                "Display selector was narrower than 48dp",
                layout.views.displaySelector.measuredWidth >= minimum,
            )
            assertTrue(
                "Display selector was shorter than 48dp",
                layout.views.displaySelector.measuredHeight >= minimum,
            )
            assertTrue(
                "Display selector escaped the safe window",
                safeBounds.contains(descendantBounds(layout.root, layout.views.displaySelector)),
            )
        }
        val actionBounds =
            listOf(layout.views.hostAction, layout.views.settings, layout.views.disconnect)
                .filter { it.visibility == View.VISIBLE }
                .map { control ->
                    assertTrue("Control ${control.id} was narrower than 48dp", control.measuredWidth >= minimum)
                    assertTrue("Control ${control.id} was shorter than 48dp", control.measuredHeight >= minimum)
                    descendantBounds(layout.root, control).also { bounds ->
                        assertTrue("Control ${control.id} escaped the control bar", cardBounds.contains(bounds))
                        assertTrue("Control ${control.id} escaped the safe window", safeBounds.contains(bounds))
                    }
                }
        actionBounds.forEachIndexed { index, bounds ->
            actionBounds.drop(index + 1).forEach { other ->
                assertFalse("Action controls overlapped", Rect.intersects(bounds, other))
            }
        }
    }

    private fun assertMargins(
        layout: MeasuredLayout,
        base: SafeAreaGeometry.Insets,
        insets: SafeAreaGeometry.Insets,
    ) {
        assertEquals(base.left + insets.left, layout.cardParams.marginStart)
        assertEquals(base.top + insets.top, layout.cardParams.topMargin)
        assertEquals(base.right + insets.right, layout.cardParams.marginEnd)
        assertEquals(base.bottom + insets.bottom, layout.cardParams.bottomMargin)
    }

    private fun withLayout(
        context: Context = applicationContext(),
        widthDp: Int? = null,
        widthPx: Int? = null,
        selectorVisible: Boolean = true,
        hostVisible: Boolean = true,
        applyLayout: Boolean = true,
        assertion: (MeasuredLayout) -> Unit,
    ) {
        val themedContext = ContextThemeWrapper(context, R.style.AppTheme)
        val root = LayoutInflater.from(themedContext).inflate(R.layout.activity_main, null, false) as ViewGroup
        val views =
            ControlBarViews(
                card = root.findViewById(R.id.controlBar),
                content = root.findViewById(R.id.controlBarContent),
                displaySelector = root.findViewById(R.id.displayCapsuleGroup),
                actions = root.findViewById(R.id.controlActionsGroup),
                hostAction = root.findViewById(R.id.controlHostActionsButton),
                settings = root.findViewById(R.id.controlSettingsButton),
                disconnect = root.findViewById(R.id.controlDisconnectButton),
            )
        val label = root.findViewById<TextView>(R.id.controlDisplaysLabel)
        views.card.visibility = View.VISIBLE
        views.displaySelector.visibility = if (selectorVisible) View.VISIBLE else View.GONE
        views.hostAction.visibility = if (hostVisible) View.VISIBLE else View.GONE
        if (selectorVisible) {
            DisplayCapsuleViewBinder.bind(
                resources = themedContext.resources,
                selector = views.displaySelector,
                labelView = label,
                displaySelection = true,
                displays = listOf(display("main", FULL_DISPLAY_NAME, true), display("side", "Side")),
                selectedId = "main",
            )
        }
        val resolvedWidth = widthPx ?: dp(themedContext, requireNotNull(widthDp))
        val layout = MeasuredLayout(themedContext, root, views, label, resolvedWidth)
        if (applyLayout) {
            layout.mode = layout.apply(resolvedWidth, SafeAreaGeometry.Insets.NONE)
            layout.measureAndLayout(resolvedWidth)
        }
        assertion(layout)
    }

    private fun densityContext(densityDpi: Int): Context {
        val configuration = Configuration(applicationContext().resources.configuration)
        configuration.densityDpi = densityDpi
        return applicationContext().createConfigurationContext(configuration)
    }

    private fun display(
        id: String,
        name: String,
        primary: Boolean = false,
    ) =
        StreamDisplayOption(
            id = id,
            name = name,
            width = 1920,
            height = 1080,
            isPrimary = primary,
            isVirtual = false,
        )

    private fun descendantBounds(
        root: ViewGroup,
        descendant: View,
    ): Rect =
        Rect(0, 0, descendant.width, descendant.height).also { bounds ->
            root.offsetDescendantRectToMyCoords(descendant, bounds)
        }

    private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

    private fun dp(
        context: Context,
        value: Int,
    ): Int = (value * context.resources.displayMetrics.density).roundToInt()

    private class MeasuredLayout(
        val context: Context,
        val root: ViewGroup,
        val views: ControlBarViews,
        val label: TextView,
        private var windowWidthPx: Int,
    ) {
        var mode: ControlBarLayoutPolicy.Mode = ControlBarLayoutPolicy.Mode.INLINE
        var safeAreaInsets: SafeAreaGeometry.Insets = SafeAreaGeometry.Insets.NONE
            private set
        val cardParams: ViewGroup.MarginLayoutParams
            get() = views.card.layoutParams as ViewGroup.MarginLayoutParams
        val selectorParams: LinearLayout.LayoutParams
            get() = views.displaySelector.layoutParams as LinearLayout.LayoutParams

        fun apply(
            windowWidthPx: Int,
            safeAreaInsets: SafeAreaGeometry.Insets,
        ): ControlBarLayoutPolicy.Mode {
            this.windowWidthPx = windowWidthPx
            this.safeAreaInsets = safeAreaInsets
            return ControlBarLayoutApplier.apply(
                views = views,
                resources = context.resources,
                windowWidthPx = windowWidthPx,
                safeAreaInsets = safeAreaInsets,
            ).also { mode = it }
        }

        fun measureAndLayout(widthPx: Int = windowWidthPx) {
            root.measure(
                View.MeasureSpec.makeMeasureSpec(widthPx, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(dp(LAYOUT_HEIGHT_DP), View.MeasureSpec.EXACTLY),
            )
            root.layout(0, 0, root.measuredWidth, root.measuredHeight)
        }

        fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).roundToInt()
    }

    private companion object {
        const val LAYOUT_HEIGHT_DP = 600
        const val DENSITY_DPI_FOR_2_75 = 440
        const val FULL_DISPLAY_NAME =
            "Vibe Screen Virtual Extended Display With A Deliberately Long Name"
    }
}
