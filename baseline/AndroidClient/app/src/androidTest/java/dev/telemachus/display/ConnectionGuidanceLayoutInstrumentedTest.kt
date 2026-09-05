package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.graphics.Rect
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.widget.NestedScrollView
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
class ConnectionGuidanceLayoutInstrumentedTest {
    @Test
    fun xiaomi13RotationReappliesLandscapeDimensionsWithoutReinflatingTheViewTree() {
        val portraitContext = configuredContext(widthDp = 393, heightDp = 873)
        val landscapeContext = configuredContext(widthDp = 873, heightDp = 393)

        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val root = inflateLayout(portraitContext)
            val layout = MeasuredLayout(landscapeContext, root, widthDp = 873, heightDp = 393)
            layout.showModeContent(R.id.internetModeContent)
            layout.subtitle.setText(R.string.internet_waiting_description)

            layout.assertPortraitDimensionsInflated()
            layout.applyPanel(
                resources = landscapeContext.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = true,
            )
            layout.measureAndLayout()

            layout.assertConfigurationUsesTwoColumns(expected = true)
            layout.assertLandscapeDimensionsApplied()
            layout.assertTextRenderedWithoutEllipsis(layout.subtitle)
            layout.assertHeaderAndActionsSeparated()
            layout.assertPrimaryInternetActionVisible()
        }
    }

    @Test
    fun xiaomi13PortraitAndLandscapeKeepModeGuidanceReadableAndSeparated() {
        listOf(393 to 873, 873 to 393, 500 to 300).forEach { (widthDp, heightDp) ->
            withLayout(widthDp, heightDp) { layout ->
                val expectedTwoColumn = widthDp >= 600 && widthDp > heightDp
                layout.assertConfigurationUsesTwoColumns(expectedTwoColumn)
                val guidance =
                    listOf(
                        R.string.adb_transport_waiting_description to R.id.usbModeContent,
                        R.string.wireless_pair_once to R.id.wirelessModeContent,
                        R.string.internet_waiting_description to R.id.internetModeContent,
                    )
                guidance.forEach { (subtitleResource, modeContentId) ->
                    layout.showModeContent(modeContentId)
                    layout.subtitle.setText(subtitleResource)
                    val mode =
                        when (modeContentId) {
                            R.id.wirelessModeContent -> ConnectionMode.WIRELESS
                            R.id.internetModeContent -> ConnectionMode.INTERNET
                            else -> ConnectionMode.USB
                        }
                    layout.applyPanel(
                        resources = layout.context.resources,
                        connectionMode = mode,
                        subtitleExpanded = false,
                    )
                    layout.measureAndLayout()
                    layout.assertTextRenderedWithoutEllipsis(layout.subtitle)
                    layout.assertFullyReachableByScroll(layout.subtitle)
                    layout.assertHeaderAndActionsSeparated()
                }
            }
        }
    }

    @Test
    fun nubiaP0110AndXiaomi13PortraitKeepConnectPreviewOnTheFirstScreen() {
        listOf(361 to 800, 393 to 873).forEach { (widthDp, heightDp) ->
            withLayout(widthDp, heightDp) { layout ->
                layout.showModeContent(R.id.internetModeContent)
                layout.subtitle.setText(R.string.internet_waiting_description)
                val completeDescription = layout.context.getString(R.string.internet_waiting_description)

                layout.applyPanel(
                    resources = layout.context.resources,
                    connectionMode = ConnectionMode.INTERNET,
                    subtitleExpanded = false,
                )
                layout.measureAndLayout()
                assertEquals(completeDescription, layout.subtitle.text.toString())
                layout.assertTextRenderedWithoutEllipsis(layout.subtitle)
                layout.assertPrimaryInternetActionVisible()

                layout.applyPanel(
                    resources = layout.context.resources,
                    connectionMode = ConnectionMode.INTERNET,
                    subtitleExpanded = true,
                )
                layout.measureAndLayout()
                assertEquals(completeDescription, layout.subtitle.text.toString())
                layout.assertTextRenderedWithoutEllipsis(layout.subtitle)
            }
        }
    }

    @Test
    fun xiaomi13LandscapeKeepsLongestUsbLanAndInternetErrorsReadable() {
        withLayout(widthDp = 873, heightDp = 393) { layout ->
            val messages =
                listOf(
                    ConnectionGuidanceFactory.from(
                        java.io.IOException("unexpected USB transport failure"),
                        ConnectionGuidanceContext.adb(54321, AdbTransportKind.UNAVAILABLE),
                    ).formattedMessage(layout.context),
                    ConnectionGuidanceFactory.from(
                        java.net.ConnectException("Connection refused"),
                        ConnectionGuidanceContext.adb(54321, AdbTransportKind.USB),
                    ).formattedMessage(layout.context),
                    ConnectionGuidanceFactory.from(
                        java.io.IOException("unexpected LAN transport failure"),
                        ConnectionGuidanceContext.trustedLan(54321),
                    ).formattedMessage(layout.context),
                    ConnectionGuidanceFactory.from(
                        java.net.SocketTimeoutException("timeout"),
                        ConnectionGuidanceContext.internet(),
                    ).formattedMessage(layout.context),
                )
            layout.showModeContent(R.id.internetModeContent)
            layout.internetError.visibility = View.VISIBLE
            messages.forEach { message ->
                layout.internetError.text = message
                layout.measureAndLayout()
                layout.assertTextRenderedWithoutEllipsis(layout.internetError)
                layout.assertFullyReachableByScroll(layout.internetError)
                layout.assertHeaderAndActionsSeparated()
            }
        }
    }

    @Test
    fun p0110LandscapeLargeTextKeepsUsbRetryFirstAndGuidanceScrollable() {
        withLayout(widthDp = 800, heightDp = 361, fontScale = 1.3f) { layout ->
            layout.showModeContent(R.id.usbModeContent)
            layout.usbErrorContainer.visibility = View.VISIBLE
            layout.checklistContainer.visibility = View.VISIBLE
            val guidance =
                ConnectionGuidanceFactory.from(
                    java.net.ConnectException("ECONNREFUSED"),
                    ConnectionGuidanceContext.adb(54321, AdbTransportKind.USB),
                )
            layout.usbErrorMessage.text = ConnectionGuidanceTextFormatter.format(layout.context.resources, guidance.message)

            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.USB,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertRetryActionVisibleOnFirstScreen()
            layout.assertTextRenderedWithoutEllipsis(layout.usbErrorMessage)
            layout.assertFullyReachableByScroll(layout.usbErrorMessage)
            layout.assertFullyReachableByScroll(layout.checklistContainer)
            layout.assertHeaderAndActionsSeparated()
            assertFalse(layout.usbErrorMessage.text.toString().contains("adb reverse", ignoreCase = true))
            assertTrue(
                "Retry action must stay before long USB diagnostic details",
                layout.boundsInContent(layout.connectButton).bottom <=
                    layout.boundsInContent(layout.usbErrorContainer).top,
            )
        }
    }

    @Test
    fun narrowPortraitKeepsModeLabelsReadableAtLargeFontScale() {
        withLayout(widthDp = 361, heightDp = 800, fontScale = 2f) { layout ->
            layout.measureAndLayout()

            listOf(layout.usbModeButton, layout.wirelessModeButton, layout.internetModeButton).forEach { button ->
                layout.assertTextRenderedWithoutEllipsis(button)
                layout.assertMinimumTouchTarget(button)
            }
        }
    }

    @Test
    fun narrowPortraitKeepsInternetProfileActionsReadableAtLargeFontScale() {
        withLayout(widthDp = 361, heightDp = 800, fontScale = 2f) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertInternetProfileActionsStacked(expectedGapDp = 8)
            listOf(layout.internetScanProfileButton, layout.internetImportProfileButton).forEach { button ->
                layout.assertTextRenderedWithoutEllipsis(button)
                layout.assertMinimumTouchTarget(button)
                layout.assertFullyReachableByScroll(button)
            }
        }
    }

    @Test
    fun defaultFontKeepsInternetProfileActionsSideBySide() {
        withLayout(widthDp = 361, heightDp = 800) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertInternetProfileActionsHorizontal(expectedGapDp = 8)
            listOf(layout.internetScanProfileButton, layout.internetImportProfileButton).forEach { button ->
                layout.assertMinimumTouchTarget(button)
                layout.assertFullyReachableByScroll(button)
            }
        }
    }

    @Test
    fun narrowPortraitKeepsModeTouchTargetsAtDefaultFontScale() {
        withLayout(widthDp = 361, heightDp = 800) { layout ->
            layout.measureAndLayout()

            listOf(layout.usbModeButton, layout.wirelessModeButton, layout.internetModeButton).forEach { button ->
                layout.assertMinimumTouchTarget(button)
            }
        }
    }

    @Test
    fun narrowDisconnectedPanelUsesInlineSettingsButtonWithoutCoveringConnect() {
        withLayout(widthDp = 361, heightDp = 800) { layout ->
            layout.showModeContent(R.id.usbModeContent)
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.USB,
                subtitleExpanded = false,
            )
            layout.inlineSettingsButton.visibility = View.VISIBLE
            layout.measureAndLayout()

            assertEquals(View.VISIBLE, layout.inlineSettingsButton.visibility)
            layout.assertFullyReachableByScroll(layout.connectButton)
            layout.assertFullyReachableByScroll(layout.inlineSettingsButton)
            layout.assertMinimumTouchTarget(layout.inlineSettingsButton)
            assertFalse(
                "Inline settings button must not overlap the primary connect action",
                Rect.intersects(layout.boundsInContent(layout.connectButton), layout.boundsInContent(layout.inlineSettingsButton)),
            )
        }
    }

    @Test
    fun wideLandscapeKeepsInlineSettingsButtonWithoutFloatingPolicy() {
        withLayout(widthDp = 873, heightDp = 393) { layout ->
            layout.inlineSettingsButton.visibility = View.VISIBLE
            layout.measureAndLayout()

            assertEquals(View.VISIBLE, layout.inlineSettingsButton.visibility)
            layout.assertFullyReachableByScroll(layout.inlineSettingsButton)
            layout.assertMinimumTouchTarget(layout.inlineSettingsButton)
        }
    }

    private fun withLayout(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float = 1f,
        assertion: (MeasuredLayout) -> Unit,
    ) {
        val context = configuredContext(widthDp, heightDp, fontScale)
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val root = inflateLayout(context)
            val layout = MeasuredLayout(context, root, widthDp, heightDp)
            layout.applyPanel(
                resources = context.resources,
                connectionMode = ConnectionMode.USB,
                subtitleExpanded = false,
            )
            assertion(layout)
        }
    }

    private fun configuredContext(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float = 1f,
    ): Context {
        val configuration = Configuration(applicationContext().resources.configuration)
        configuration.screenWidthDp = widthDp
        configuration.screenHeightDp = heightDp
        configuration.smallestScreenWidthDp = minOf(widthDp, heightDp)
        configuration.fontScale = fontScale
        configuration.orientation =
            if (widthDp > heightDp) {
                Configuration.ORIENTATION_LANDSCAPE
            } else {
                Configuration.ORIENTATION_PORTRAIT
            }
        return applicationContext().createConfigurationContext(configuration)
    }

    private fun inflateLayout(context: Context): ViewGroup {
        val themedContext = ContextThemeWrapper(context, R.style.AppTheme)
        return LayoutInflater.from(themedContext).inflate(R.layout.activity_main, null, false) as ViewGroup
    }

    private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

    private class MeasuredLayout(
        val context: Context,
        val root: ViewGroup,
        widthDp: Int,
        heightDp: Int,
    ) {
        val header = root.findViewById<LinearLayout>(R.id.connectionHeader)
        val actions = root.findViewById<LinearLayout>(R.id.connectionActions)
        val content = root.findViewById<LinearLayout>(R.id.connectionContent)
        val subtitle = root.findViewById<TextView>(R.id.connectionSubtitle)
        val internetError = root.findViewById<TextView>(R.id.internetErrorText)
        val usbErrorContainer = root.findViewById<View>(R.id.connectionErrorContainer)
        val usbErrorMessage = root.findViewById<TextView>(R.id.connectionErrorMessage)
        val checklistContainer = root.findViewById<View>(R.id.checklistContainer)
        val connectButton = root.findViewById<View>(R.id.connectButton)
        val inlineSettingsButton = root.findViewById<View>(R.id.connectionSettingsButton)
        val usbModeButton = root.findViewById<TextView>(R.id.modeUSB)
        val wirelessModeButton = root.findViewById<TextView>(R.id.modeWireless)
        val internetModeButton = root.findViewById<TextView>(R.id.modeInternet)
        val internetProfileActions = root.findViewById<LinearLayout>(R.id.internetProfileActions)
        val internetScanProfileButton = root.findViewById<TextView>(R.id.internetScanProfileButton)
        val internetImportProfileButton = root.findViewById<TextView>(R.id.internetImportProfileButton)
        private val scrollView = root.findViewById<NestedScrollView>(R.id.connectionScroll)
        private val icon = root.findViewById<View>(R.id.connectionIcon)
        private val wordmark = root.findViewById<View>(R.id.connectionWordmark)
        private val title = root.findViewById<View>(R.id.connectionTitle)
        private val progress = root.findViewById<View>(R.id.connectionProgress)
        private val modeToggle = root.findViewById<View>(R.id.modeToggleGroup)
        private val internetRouteLabel = root.findViewById<View>(R.id.internetRouteLabel)
        private val internetRouteToggle = root.findViewById<View>(R.id.internetRouteToggleGroup)
        private val internetConnect = root.findViewById<View>(R.id.internetConnectButton)
        private val widthPx = dp(widthDp)
        private val heightPx = dp(heightDp)

        private val usbModeContent = root.findViewById<View>(R.id.usbModeContent)
        private val wirelessModeContent = root.findViewById<View>(R.id.wirelessModeContent)
        private val internetModeContent = root.findViewById<View>(R.id.internetModeContent)

        init {
            usbModeContent.visibility = View.GONE
            wirelessModeContent.visibility = View.GONE
            internetModeContent.visibility = View.GONE
        }

        private fun views() =
            ConnectionPanelLayoutApplier.Views(
                content = content,
                header = header,
                actions = actions,
                subtitle = subtitle,
            )

        fun applyPanel(
            resources: android.content.res.Resources,
            connectionMode: ConnectionMode,
            subtitleExpanded: Boolean,
        ) {
            ConnectionPanelLayoutApplier.apply(
                resources = resources,
                views = views(),
                connectionMode = connectionMode,
                subtitleExpanded = subtitleExpanded,
            )
        }

        fun showModeContent(modeContentId: Int) {
            usbModeContent.visibility = if (modeContentId == R.id.usbModeContent) View.VISIBLE else View.GONE
            wirelessModeContent.visibility = if (modeContentId == R.id.wirelessModeContent) View.VISIBLE else View.GONE
            internetModeContent.visibility = if (modeContentId == R.id.internetModeContent) View.VISIBLE else View.GONE
        }

        fun measureAndLayout() {
            root.measure(
                View.MeasureSpec.makeMeasureSpec(widthPx, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(heightPx, View.MeasureSpec.EXACTLY),
            )
            root.layout(0, 0, root.measuredWidth, root.measuredHeight)
        }

        fun assertTextRenderedWithoutEllipsis(text: TextView) {
            val textLayout = checkNotNull(text.layout)
            assertTrue(text.measuredWidth > 0 && text.measuredHeight > 0)
            val viewName = text.resources.getResourceEntryName(text.id)
            val ellipsizedLines =
                (0 until textLayout.lineCount)
                    .filter { line -> textLayout.getEllipsisCount(line) != 0 }
            val lineDetails =
                (0 until textLayout.lineCount).joinToString { line ->
                    "line=" + line +
                        ":start=" + textLayout.getLineStart(line) +
                        ":end=" + textLayout.getLineEnd(line) +
                        ":ellipsisStart=" + textLayout.getEllipsisStart(line) +
                        ":ellipsisCount=" + textLayout.getEllipsisCount(line) +
                        ":width=" + textLayout.getLineWidth(line)
                }
            assertTrue(
                "$viewName ellipsized lines=$ellipsizedLines " +
                    "width=" + text.measuredWidth +
                    " height=" + text.measuredHeight +
                    " paddingStart=" + text.compoundPaddingStart +
                    " paddingEnd=" + text.compoundPaddingEnd +
                    " textSize=" + text.textSize +
                    " lineCount=" + textLayout.lineCount +
                    " details=[$lineDetails] text='" + text.text + "'",
                ellipsizedLines.isEmpty(),
            )
            assertEquals(
                "$viewName did not render the full text '" + text.text + "'",
                text.text.length,
                textLayout.getLineEnd(textLayout.lineCount - 1),
            )
        }

        fun assertFullyReachableByScroll(view: View) {
            val viewBounds = boundsInContent(view)
            assertTrue(viewBounds.top >= 0)
            assertTrue(
                "View " + view.resources.getResourceEntryName(view.id) + " " + viewBounds +
                " escaped scroll content height " + content.height,
                viewBounds.bottom <= content.height,
            )
            val maximumScroll = (content.height - scrollView.height).coerceAtLeast(0)

            val topScroll = viewBounds.top.coerceAtMost(maximumScroll)
            scrollView.scrollTo(0, topScroll)
            assertEquals(topScroll, scrollView.scrollY)
            assertTrue(viewBounds.top >= scrollView.scrollY)
            assertTrue(viewBounds.top < scrollView.scrollY + scrollView.height)

            val bottomScroll = (viewBounds.bottom - scrollView.height).coerceIn(0, maximumScroll)
            scrollView.scrollTo(0, bottomScroll)
            assertEquals(bottomScroll, scrollView.scrollY)
            assertTrue(viewBounds.bottom > scrollView.scrollY)
            assertTrue(viewBounds.bottom <= scrollView.scrollY + scrollView.height)
            if (view.height <= scrollView.height) {
                assertTrue(viewBounds.top >= scrollView.scrollY)
            }
        }

        fun assertMinimumTouchTarget(view: View) {
            assertTrue(
                "View " + view.resources.getResourceEntryName(view.id) + " width was " + view.width + "px",
                view.width >= dp(48),
            )
            assertTrue(
                "View " + view.resources.getResourceEntryName(view.id) + " height was " + view.height + "px",
                view.height >= dp(48),
            )
            assertTrue(
                "View " + view.resources.getResourceEntryName(view.id) + " must stay enabled",
                view.isEnabled,
            )
        }

        fun assertConfigurationUsesTwoColumns(expected: Boolean) {
            assertEquals(expected, context.resources.getBoolean(R.bool.connection_panel_two_column))
            assertEquals(
                if (expected) LinearLayout.HORIZONTAL else LinearLayout.VERTICAL,
                content.orientation,
            )
        }

        fun assertHeaderAndActionsSeparated() {
            if (context.resources.getBoolean(R.bool.connection_panel_two_column)) {
                assertFalse(Rect.intersects(bounds(header), bounds(actions)))
                assertTrue(header.right <= actions.left)
            } else {
                assertTrue(header.bottom <= actions.top)
            }
        }

        fun assertLandscapeDimensionsApplied() {
            assertEquals(dp(8), content.paddingTop)
            assertEquals(dp(8), content.paddingBottom)
            assertEquals(dp(48), icon.width)
            assertEquals(dp(48), icon.height)
            assertEquals(dp(8), margins(icon).bottomMargin)
            assertEquals(dp(4), margins(wordmark).bottomMargin)
            assertEquals(dp(4), margins(title).bottomMargin)
            assertEquals(dp(4), margins(subtitle).bottomMargin)
            assertEquals(dp(8), margins(progress).bottomMargin)
            assertEquals(dp(8), margins(modeToggle).bottomMargin)
            assertEquals(dp(8), margins(internetRouteLabel).topMargin)
            assertEquals(dp(8), margins(internetRouteToggle).bottomMargin)
            assertEquals(dp(4), margins(internetConnect).topMargin)
        }

        fun assertInternetProfileActionsStacked(expectedGapDp: Int) {
            assertEquals(LinearLayout.VERTICAL, internetProfileActions.orientation)
            assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, internetScanProfileButton.layoutParams.width)
            assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, internetImportProfileButton.layoutParams.width)
            assertEquals(0f, linearMargins(internetScanProfileButton).weight, 0f)
            assertEquals(0f, linearMargins(internetImportProfileButton).weight, 0f)
            assertEquals(0, linearMargins(internetImportProfileButton).marginStart)
            assertEquals(dp(expectedGapDp), linearMargins(internetImportProfileButton).topMargin)
        }

        fun assertInternetProfileActionsHorizontal(expectedGapDp: Int) {
            assertEquals(LinearLayout.HORIZONTAL, internetProfileActions.orientation)
            assertEquals(0, internetScanProfileButton.layoutParams.width)
            assertEquals(0, internetImportProfileButton.layoutParams.width)
            assertEquals(1f, linearMargins(internetScanProfileButton).weight, 0f)
            assertEquals(1f, linearMargins(internetImportProfileButton).weight, 0f)
            assertEquals(dp(expectedGapDp), linearMargins(internetImportProfileButton).marginStart)
            assertEquals(0, linearMargins(internetImportProfileButton).topMargin)
        }

        fun assertPortraitDimensionsInflated() {
            assertEquals(dp(32), content.paddingTop)
            assertEquals(dp(28), content.paddingBottom)
            assertEquals(dp(56), icon.layoutParams.width)
            assertEquals(dp(56), icon.layoutParams.height)
            assertEquals(dp(12), margins(icon).bottomMargin)
            assertEquals(dp(6), margins(wordmark).bottomMargin)
            assertEquals(dp(6), margins(title).bottomMargin)
            assertEquals(dp(12), margins(subtitle).bottomMargin)
            assertEquals(dp(12), margins(progress).bottomMargin)
            assertEquals(dp(16), margins(modeToggle).bottomMargin)
            assertEquals(dp(12), margins(internetRouteLabel).topMargin)
            assertEquals(dp(12), margins(internetRouteToggle).bottomMargin)
            assertEquals(dp(12), margins(internetConnect).topMargin)
        }

        fun assertPrimaryInternetActionVisible() {
            scrollView.scrollTo(0, 0)
            val actionBounds = boundsInContent(internetConnect)
            assertTrue(
                "Internet action height was " + internetConnect.height + "px",
                internetConnect.height >= dp(48),
            )
            assertTrue(
                "Internet action " + actionBounds + " starts below the " +
                    scrollView.height + "px first-screen viewport",
                actionBounds.top >= 0 && actionBounds.bottom <= scrollView.height,
            )
        }

        fun assertRetryActionVisibleOnFirstScreen() {
            scrollView.scrollTo(0, 0)
            val actionBounds = boundsInContent(connectButton)
            assertTrue(
                "Retry action height was " + connectButton.height + "px",
                connectButton.height >= dp(48),
            )
            assertTrue(
                "Retry action " + actionBounds + " is outside the " +
                    scrollView.height + "px first-screen viewport",
                actionBounds.top >= 0 && actionBounds.bottom <= scrollView.height,
            )
        }

        private fun bounds(view: View): Rect = Rect(view.left, view.top, view.right, view.bottom)

        fun boundsInContent(view: View): Rect =
            Rect(0, 0, view.width, view.height).also { rect ->
                content.offsetDescendantRectToMyCoords(view, rect)
            }

        private fun margins(view: View): ViewGroup.MarginLayoutParams =
            view.layoutParams as ViewGroup.MarginLayoutParams

        private fun linearMargins(view: View): LinearLayout.LayoutParams =
            view.layoutParams as LinearLayout.LayoutParams

        private fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).roundToInt()
    }

    private fun ConnectionGuidance.formattedMessage(context: Context): String =
        ConnectionGuidanceTextFormatter.format(context.resources, message)
}
