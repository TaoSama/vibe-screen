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
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.roundToInt

@RunWith(AndroidJUnit4::class)
class ControlBarLayoutInstrumentedTest {
    @Test
    fun productionRevealActionRestoresHiddenStreamControls() {
        val preferences = PreferencesManager(InstrumentationRegistry.getInstrumentation().targetContext)
        val previousMode = preferences.connectionMode
        preferences.connectionMode = ConnectionMode.INTERNET
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    MainActivity::class.java.getDeclaredField("isConnected").apply {
                        isAccessible = true
                        setBoolean(activity, true)
                    }
                    MainActivity::class.java.getDeclaredMethod("hideControlBar").apply {
                        isAccessible = true
                        invoke(activity)
                    }
                    val inputViewport = activity.findViewById<View>(R.id.inputViewport)
                    val controlBar = activity.findViewById<View>(R.id.controlBar)
                    assertEquals(View.GONE, controlBar.visibility)
                    assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_YES, inputViewport.importantForAccessibility)

                    assertTrue(inputViewport.performAccessibilityAction(AccessibilityNodeInfo.ACTION_CLICK, null))
                    assertEquals(View.VISIBLE, controlBar.visibility)
                    assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_NO, inputViewport.importantForAccessibility)
                }
            }
        } finally {
            preferences.connectionMode = previousMode
        }
    }

    @Test
    fun revealActionIsARealClickableNodeOnlyWhileConnectedChromeIsHidden() {
        withLayout(widthDp = 320) { layout ->
            val inputViewport = layout.root.findViewById<View>(R.id.inputViewport)

            ControlBarAccessibilityApplier.applyRevealAction(
                inputViewport,
                connected = true,
                controlBarVisible = false,
            )
            assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_YES, inputViewport.importantForAccessibility)
            assertEquals(
                layout.context.getString(R.string.show_stream_controls),
                inputViewport.contentDescription.toString(),
            )
            assertTrue(inputViewport.isClickable)

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
    fun phoneWidthsUseProductionLayoutAndPreserveTouchTargets() {
        listOf(320, 360).forEach { widthDp ->
            withLayout(widthDp = widthDp) { layout ->
                val expectedMode =
                    ControlBarLayoutPolicy.mode(
                        availableWidthPx = layout.dp(widthDp),
                        displaySelectorVisible = true,
                        hostActionsVisible = true,
                        clipboardVisible = true,
                        geometry = ControlBarLayoutApplier.geometry(layout.context.resources),
                    )
                assertEquals(expectedMode, layout.mode)
                assertEquals(
                    if (expectedMode == ControlBarLayoutPolicy.Mode.INLINE) {
                        LinearLayout.HORIZONTAL
                    } else {
                        LinearLayout.VERTICAL
                    },
                    layout.views.content.orientation,
                )
                assertEquals(LinearLayout.HORIZONTAL, layout.views.actions.orientation)
                if (expectedMode == ControlBarLayoutPolicy.Mode.INLINE) {
                    assertEquals(0, layout.selectorParams.width)
                    assertEquals(1f, layout.selectorParams.weight)
                } else {
                    assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, layout.selectorParams.width)
                    assertEquals(0f, layout.selectorParams.weight)
                }
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
    fun productionBinderDisablesSelectorAndAnnouncesPendingDisplaySwitch() {
        withLayout(widthDp = 320) { layout ->
            val selectable =
                DisplayCapsuleViewBinder.bind(
                    resources = layout.context.resources,
                    selector = layout.views.displaySelector,
                    labelView = layout.label,
                    displaySelection = true,
                    displays = listOf(display("main", FULL_DISPLAY_NAME, true), display("side", "Side Display")),
                    selectedId = "main",
                    pendingDisplayId = "side",
                )

            assertTrue(selectable)
            assertEquals(View.VISIBLE, layout.views.displaySelector.visibility)
            assertFalse(layout.views.displaySelector.isEnabled)
            assertEquals(
                layout.context.getString(R.string.display_capsule_switching, "Side Display"),
                layout.label.text.toString(),
            )
            assertEquals(
                layout.context.getString(R.string.control_displays_switching, FULL_DISPLAY_NAME, "Side Display"),
                layout.views.displaySelector.contentDescription.toString(),
            )
        }
    }

    @Test
    fun productionApplierCoversStackedColumnAndHiddenSelectorBoundaries() {
        val geometry = ControlBarLayoutApplier.geometry(applicationContext().resources)
        val withHostColumnWidth = compactMinimumWidth(geometry, hostActionsVisible = true, clipboardVisible = true)
        val withoutHostColumnWidth = compactMinimumWidth(geometry, hostActionsVisible = false, clipboardVisible = false)
        val withHostStackedWidth = stackedMinimumWidth(geometry, hostActionsVisible = true, clipboardVisible = true)
        val withoutHostStackedWidth = stackedMinimumWidth(geometry, hostActionsVisible = false, clipboardVisible = false)
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
            widthPx = withHostStackedWidth - 1,
            selectorVisible = true,
            hostVisible = true,
            expectedMode = ControlBarLayoutPolicy.Mode.COLUMN,
        )
        assertModeAndShape(
            widthPx = withoutHostInlineWidth - 1,
            selectorVisible = true,
            hostVisible = false,
            clipboardVisible = false,
            expectedMode = ControlBarLayoutPolicy.Mode.STACKED,
        )
        assertModeAndShape(
            widthPx = withoutHostStackedWidth - 1,
            selectorVisible = true,
            hostVisible = false,
            clipboardVisible = false,
            expectedMode = ControlBarLayoutPolicy.Mode.COLUMN,
        )
        assertModeAndShape(
            widthPx = withoutHostColumnWidth - 1,
            selectorVisible = false,
            hostVisible = false,
            clipboardVisible = false,
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
            assertEquals(ControlBarLayoutPolicy.Mode.STACKED, mode)
            assertMargins(layout, baseMargins, changedInsets)
            assertEquals(LinearLayout.VERTICAL, layout.views.content.orientation)
            assertEquals(0f, layout.selectorParams.weight)
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
    fun statsOverlayStacksInsideNarrowSafeWindows() {
        withLayout(widthDp = 320, applyLayout = false) { layout ->
            val safeInsets =
                SafeAreaGeometry.Insets.of(
                    left = layout.dp(12),
                    top = 0,
                    right = layout.dp(12),
                    bottom = 0,
                )
            val mode = layout.applyStatusOverlay(layout.dp(320), safeInsets)
            layout.measureAndLayout(layout.dp(320))

            assertEquals(StatusOverlayLayoutPolicy.Mode.STACKED, mode)
            assertEquals(LinearLayout.VERTICAL, layout.statusOverlay.content.orientation)
            val expectedMaximumWidth = layout.dp(320) - layout.dp(24) - layout.dp(32)
            assertTrue(layout.statusOverlay.card.measuredWidth <= expectedMaximumWidth)
            assertTrue(layout.statusOverlay.card.measuredWidth >= expectedMaximumWidth - 1)
            assertStatusOverlayItemsReadable(layout)
        }
    }

    @Test
    fun statsOverlayKeepsSingleRowWhenAllColumnsFit() {
        withLayout(widthDp = 900, applyLayout = false) { layout ->
            val mode = layout.applyStatusOverlay(layout.dp(900), SafeAreaGeometry.Insets.NONE)
            layout.measureAndLayout(layout.dp(900))

            assertEquals(StatusOverlayLayoutPolicy.Mode.SINGLE_ROW, mode)
            assertEquals(LinearLayout.HORIZONTAL, layout.statusOverlay.content.orientation)
            assertStatusOverlayItemsReadable(layout)
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
        assertEquals(198, geometry.statusMinimumWidthPx)
        assertEquals(17, geometry.statusGapPx)

        val withHostColumnWidth = compactMinimumWidth(geometry, hostActionsVisible = true, clipboardVisible = true)
        val withoutHostColumnWidth = compactMinimumWidth(geometry, hostActionsVisible = false, clipboardVisible = false)
        val withHostStackedWidth = stackedMinimumWidth(geometry, hostActionsVisible = true, clipboardVisible = true)
        val withoutHostStackedWidth = stackedMinimumWidth(geometry, hostActionsVisible = false, clipboardVisible = false)
        val withHostInlineWidth = withHostColumnWidth + geometry.selectorMinimumWidthPx
        val withoutHostInlineWidth = withoutHostColumnWidth + geometry.selectorMinimumWidthPx

        withLayout(context = context, widthPx = withHostInlineWidth) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.INLINE, layout.mode)
        }
        withLayout(context = context, widthPx = withHostInlineWidth - 1) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.STACKED, layout.mode)
        }
        withLayout(context = context, widthPx = withHostStackedWidth) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.STACKED, layout.mode)
        }
        withLayout(context = context, widthPx = withHostStackedWidth - 1) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COLUMN, layout.mode)
        }
        withLayout(context = context, widthPx = withoutHostInlineWidth, hostVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.INLINE, layout.mode)
        }
        withLayout(context = context, widthPx = withoutHostInlineWidth - 1, hostVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.STACKED, layout.mode)
        }
        withLayout(context = context, widthPx = withoutHostStackedWidth, hostVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.STACKED, layout.mode)
        }
        withLayout(context = context, widthPx = withoutHostStackedWidth - 1, hostVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COLUMN, layout.mode)
        }
    }

    @Test
    fun hiddenSelectorUsesExactCompactBoundariesAtNonIntegerDensity() {
        val context = densityContext(DENSITY_DPI_FOR_2_75)
        val geometry = ControlBarLayoutApplier.geometry(context.resources)
        val withHostColumnWidth = compactMinimumWidth(geometry, hostActionsVisible = true, clipboardVisible = true)
        val withoutHostColumnWidth = compactMinimumWidth(geometry, hostActionsVisible = false, clipboardVisible = false)

        withLayout(context = context, widthPx = withHostColumnWidth, selectorVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COMPACT, layout.mode)
        }
        withLayout(context = context, widthPx = withHostColumnWidth - 1, selectorVisible = false) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COLUMN, layout.mode)
        }
        withLayout(
            context = context,
            widthPx = withoutHostColumnWidth,
            selectorVisible = false,
            hostVisible = false,
            clipboardVisible = false,
        ) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COMPACT, layout.mode)
        }
        withLayout(
            context = context,
            widthPx = withoutHostColumnWidth - 1,
            selectorVisible = false,
            hostVisible = false,
            clipboardVisible = false,
        ) { layout ->
            assertEquals(ControlBarLayoutPolicy.Mode.COLUMN, layout.mode)
        }
    }

    private fun assertModeAndShape(
        widthPx: Int,
        selectorVisible: Boolean,
        hostVisible: Boolean,
        clipboardVisible: Boolean = hostVisible,
        expectedMode: ControlBarLayoutPolicy.Mode,
    ) {
        withLayout(
            widthPx = widthPx,
            selectorVisible = selectorVisible,
            hostVisible = hostVisible,
            clipboardVisible = clipboardVisible,
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

    private fun stackedMinimumWidth(
        geometry: ControlBarLayoutPolicy.Geometry,
        hostActionsVisible: Boolean,
        clipboardVisible: Boolean,
    ): Int =
        geometry.horizontalContentPaddingPx +
            maxOf(
                geometry.statusMinimumWidthPx,
                geometry.selectorMinimumWidthPx,
                geometry.horizontalActionsWidthPx(hostActionsVisible, clipboardVisible),
            )

    private fun compactMinimumWidth(
        geometry: ControlBarLayoutPolicy.Geometry,
        hostActionsVisible: Boolean,
        clipboardVisible: Boolean,
    ): Int =
        geometry.horizontalContentPaddingPx +
            geometry.statusMinimumWidthPx +
            geometry.statusGapPx +
            geometry.horizontalActionsWidthPx(hostActionsVisible, clipboardVisible)

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
            listOf(layout.views.hostAction, layout.views.clipboard, layout.views.settings, layout.views.disconnect)
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

    private fun assertStatusOverlayItemsReadable(layout: MeasuredLayout) {
        val overlayBounds = descendantBounds(layout.root, layout.statusOverlay.card)
        val content = layout.statusOverlay.content
        (0 until content.childCount).forEach { index ->
            val item = content.getChildAt(index)
            val params = item.layoutParams as LinearLayout.LayoutParams
            assertEquals(0f, params.weight)
            assertTrue("Status item $index width", item.measuredWidth >= layout.dp(48))
            assertTrue("Status item $index height", item.measuredHeight > 0)
            assertTrue(
                "Status item $index escaped overlay",
                overlayBounds.contains(descendantBounds(layout.root, item)),
            )
        }
    }

    private fun withLayout(
        context: Context = applicationContext(),
        widthDp: Int? = null,
        widthPx: Int? = null,
        selectorVisible: Boolean = true,
        hostVisible: Boolean = true,
        clipboardVisible: Boolean = hostVisible,
        applyLayout: Boolean = true,
        assertion: (MeasuredLayout) -> Unit,
    ) {
        val themedContext = ContextThemeWrapper(context, R.style.AppTheme)
        val root = LayoutInflater.from(themedContext).inflate(R.layout.activity_main, null, false) as ViewGroup
        val views =
            ControlBarViews(
                card = root.findViewById(R.id.controlBar),
                content = root.findViewById(R.id.controlBarContent),
                connectionStatus = root.findViewById(R.id.connectionSecurityGroup),
                displaySelector = root.findViewById(R.id.displayCapsuleGroup),
                actions = root.findViewById(R.id.controlActionsGroup),
                hostAction = root.findViewById(R.id.controlHostActionsButton),
                clipboard = root.findViewById(R.id.controlClipboardButton),
                settings = root.findViewById(R.id.controlSettingsButton),
                disconnect = root.findViewById(R.id.controlDisconnectButton),
            )
        val statusOverlay =
            StatusOverlayViews(
                card = root.findViewById(R.id.statusBar),
                content = root.findViewById(R.id.statusBarContent),
            )
        val label = root.findViewById<TextView>(R.id.controlDisplaysLabel)
        views.card.visibility = View.VISIBLE
        statusOverlay.card.visibility = View.VISIBLE
        views.connectionStatus.visibility = View.VISIBLE
        views.displaySelector.visibility = if (selectorVisible) View.VISIBLE else View.GONE
        views.hostAction.visibility = if (hostVisible) View.VISIBLE else View.GONE
        views.clipboard.visibility = if (clipboardVisible) View.VISIBLE else View.GONE
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
        val layout = MeasuredLayout(themedContext, root, views, statusOverlay, label, resolvedWidth)
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
        val statusOverlay: StatusOverlayViews,
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

        fun applyStatusOverlay(
            windowWidthPx: Int,
            safeAreaInsets: SafeAreaGeometry.Insets,
        ): StatusOverlayLayoutPolicy.Mode =
            StatusOverlayLayoutApplier.apply(
                views = statusOverlay,
                resources = context.resources,
                windowWidthPx = windowWidthPx,
                safeAreaInsets = safeAreaInsets,
            )

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
