package dev.telemachus.display

import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Paint
import android.graphics.Rect
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.LinearLayout
import android.widget.TextView
import androidx.constraintlayout.widget.ConstraintLayout
import androidx.core.view.ViewCompat
import androidx.core.widget.NestedScrollView
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.material.button.MaterialButton
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.roundToInt

private const val AUTO_CONNECT_EXTRA = "auto_connect"

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
    fun p0110LandscapeLargeTextKeepsInternetConnectPreviewOnFirstScreen() {
        withLayout(widthDp = 800, heightDp = 361, fontScale = 1.3f) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertConfigurationUsesTwoColumns(expected = true)
            layout.assertTextRenderedWithoutEllipsis(layout.internetProfileSummary)
            layout.assertTextRenderedWithoutEllipsis(layout.internetStateText)
            layout.assertInternetProfileActionsHorizontal(expectedGapDp = 8)
            layout.assertReadableActionRowFitsActionsColumn(
                gapDp = 8,
                R.id.internetScanProfileButton,
                R.id.internetImportProfileButton,
            )
            layout.assertPrimaryInternetActionVisible()
            layout.assertMinimumTouchTarget(layout.internetConnectButton)
            layout.assertHeaderAndActionsSeparated()
        }
    }

    @Test
    fun narrowTwoColumnLandscapeLargeTextStacksActionRowsWithoutClipping() {
        listOf(1.3f, 1.5f, 2.0f).forEach { fontScale ->
            withLayout(widthDp = 600, heightDp = 360, fontScale = fontScale) { layout ->
                layout.showModeContent(R.id.internetModeContent)
                layout.showAllInternetSecondaryActions()
                layout.applyPanel(
                    resources = layout.context.resources,
                    connectionMode = ConnectionMode.INTERNET,
                    subtitleExpanded = false,
                )
                layout.measureAndLayout()

                layout.assertConfigurationUsesTwoColumns(expected = true)
                layout.assertModeToggleStacked()
                layout.assertInternetProfileActionsStacked(expectedGapDp = 8)
                layout.assertInternetSecondaryActionsStacked(expectedGapDp = 8)
                listOf(
                    layout.usbModeButton,
                    layout.wirelessModeButton,
                    layout.internetModeButton,
                    layout.internetScanProfileButton,
                    layout.internetImportProfileButton,
                    layout.internetConnectionSettingsButton,
                    layout.internetDisconnectButton,
                    layout.internetRevokeButton,
                ).forEach { button ->
                    layout.assertTextRenderedWithoutEllipsis(button)
                    layout.assertMinimumTouchTarget(button)
                    layout.assertFullyReachableByScroll(button)
                }
                layout.assertHeaderAndActionsSeparated()
            }
        }
    }

    @Test
    fun narrowTwoColumnLandscapeLargeTextStacksLongActionLabelsWithoutClipping() {
        listOf(1.3f, 2.0f).forEach { fontScale ->
            withLayout(widthDp = 600, heightDp = 360, fontScale = fontScale) { layout ->
                layout.showModeContent(R.id.internetModeContent)
                layout.showAllInternetSecondaryActions()
                layout.useLongConnectionActionLabels()
                layout.applyPanel(
                    resources = layout.context.resources,
                    connectionMode = ConnectionMode.INTERNET,
                    subtitleExpanded = false,
                )
                layout.measureAndLayout()

                layout.assertConfigurationUsesTwoColumns(expected = true)
                layout.assertModeToggleStacked()
                layout.assertInternetProfileActionsStacked(expectedGapDp = 8)
                layout.assertInternetSecondaryActionsStacked(expectedGapDp = 8)
                listOf(
                    layout.usbModeButton,
                    layout.wirelessModeButton,
                    layout.internetModeButton,
                    layout.internetScanProfileButton,
                    layout.internetImportProfileButton,
                    layout.internetConnectionSettingsButton,
                    layout.internetDisconnectButton,
                    layout.internetRevokeButton,
                ).forEach { button ->
                    layout.assertTextRenderedWithoutEllipsis(button)
                    layout.assertMinimumTouchTarget(button)
                    layout.assertFullyReachableByScroll(button)
                }
                layout.assertHeaderAndActionsSeparated()
            }
        }
    }

    @Test
    fun expandedTwoColumnLargeTextStacksVeryLongActionLabelsByMeasuredWidth() {
        withLayout(widthDp = 1200, heightDp = 700, fontScale = 1.3f) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.showDisconnectedInternetSecondaryActions()
            layout.useVeryLongConnectionActionLabels()
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertConfigurationUsesTwoColumns(expected = true)
            layout.assertModeToggleStacked()
            layout.assertInternetProfileActionsStacked(expectedGapDp = 8)
            layout.assertDisconnectedInternetSecondaryActionsStacked(expectedGapDp = 8)
            listOf(
                layout.usbModeButton,
                layout.wirelessModeButton,
                layout.internetModeButton,
                layout.internetScanProfileButton,
                layout.internetImportProfileButton,
                layout.internetConnectionSettingsButton,
                layout.internetRevokeButton,
            ).forEach { button ->
                layout.assertTextRenderedWithoutEllipsis(button)
                layout.assertMinimumTouchTarget(button)
                layout.assertFullyReachableByScroll(button)
            }
            layout.assertHeaderAndActionsSeparated()
        }
    }

    @Test
    fun expandedTwoColumnDefaultTextStacksVeryLongActionLabelsByMeasuredWidth() {
        withLayout(widthDp = 1200, heightDp = 700, fontScale = 1.0f) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.showAllInternetSecondaryActions()
            layout.useVeryLongInternetSecondaryActionLabels()
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertConfigurationUsesTwoColumns(expected = true)
            layout.assertModeToggleHorizontal()
            layout.assertInternetProfileActionsHorizontal(expectedGapDp = 8)
            layout.assertInternetSecondaryActionsStacked(expectedGapDp = 8)
            listOf(
                layout.usbModeButton,
                layout.wirelessModeButton,
                layout.internetModeButton,
                layout.internetScanProfileButton,
                layout.internetImportProfileButton,
                layout.internetConnectionSettingsButton,
                layout.internetDisconnectButton,
                layout.internetRevokeButton,
            ).forEach { button ->
                layout.assertTextRenderedWithoutEllipsis(button)
                layout.assertMinimumTouchTarget(button)
                layout.assertFullyReachableByScroll(button)
            }
            layout.assertHeaderAndActionsSeparated()
        }
    }

    @Test
    fun expandedTwoColumnLargeTextKeepsDefaultActionLabelsHorizontal() {
        withLayout(widthDp = 1200, heightDp = 700, fontScale = 1.3f) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.showAllInternetSecondaryActions()
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertConfigurationUsesTwoColumns(expected = true)
            layout.assertModeToggleHorizontal()
            layout.assertInternetProfileActionsHorizontal(expectedGapDp = 8)
            layout.assertInternetSecondaryActionsHorizontal(expectedGapDp = 8)
            layout.assertReadableActionRowFitsActionsColumn(
                gapDp = 0,
                R.id.modeUSB,
                R.id.modeWireless,
                R.id.modeInternet,
            )
            layout.assertReadableActionRowFitsActionsColumn(
                gapDp = 8,
                R.id.internetScanProfileButton,
                R.id.internetImportProfileButton,
            )
            layout.assertReadableActionRowFitsActionsColumn(
                gapDp = 8,
                R.id.internetConnectionSettingsButton,
                R.id.internetDisconnectButton,
                R.id.internetRevokeButton,
            )
            listOf(
                layout.usbModeButton,
                layout.wirelessModeButton,
                layout.internetModeButton,
                layout.internetScanProfileButton,
                layout.internetImportProfileButton,
                layout.internetConnectionSettingsButton,
                layout.internetDisconnectButton,
                layout.internetRevokeButton,
            ).forEach { button ->
                layout.assertTextRenderedWithoutEllipsis(button)
                layout.assertMinimumTouchTarget(button)
                layout.assertFullyReachableByScroll(button)
            }
            layout.assertHeaderAndActionsSeparated()
        }
    }

    @Test
    fun materialButtonReadableWidthCountsIconSpaceOnce() {
        withLayout(widthDp = 1200, heightDp = 700, fontScale = 1.3f) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.showAllInternetSecondaryActions()
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertReadableWidthCountsMaterialIconOnce(layout.internetConnectionSettingsButton)
        }
    }

    @Test
    fun wideTwoColumnLandscapeDefaultTextKeepsActionRowsHorizontal() {
        withLayout(widthDp = 800, heightDp = 361, fontScale = 1.0f) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.showAllInternetSecondaryActions()
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertConfigurationUsesTwoColumns(expected = true)
            layout.assertPanelGeometryUsesResources()
            layout.assertModeToggleHorizontal()
            layout.assertInternetProfileActionsHorizontal(expectedGapDp = 8)
            layout.assertInternetSecondaryActionsHorizontal(expectedGapDp = 8)
            listOf(
                layout.usbModeButton,
                layout.wirelessModeButton,
                layout.internetModeButton,
                layout.internetScanProfileButton,
                layout.internetImportProfileButton,
                layout.internetConnectionSettingsButton,
                layout.internetDisconnectButton,
                layout.internetRevokeButton,
            ).forEach { button ->
                layout.assertMinimumTouchTarget(button)
                layout.assertFullyReachableByScroll(button)
            }
        }
    }

    @Test
    fun connectionPanelOuterGeometryRebindsPhoneAndWideResourcesWithoutReinflating() {
        val phoneContext = configuredContext(widthDp = 361, heightDp = 800)
        val widePortraitContext = configuredContext(widthDp = 680, heightDp = 880)
        val wideLandscapeContext = configuredContext(widthDp = 880, heightDp = 680)

        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val root = inflateLayout(phoneContext)
            val panel = root.findViewById<View>(R.id.settingsPanel)

            val phoneBase = applyPanelContainerGeometry(phoneContext, panel)
            measureAndLayout(root, phoneContext, 361, 800)
            assertPanelContainerGeometry(phoneContext, root, panel, phoneBase, 680, 24, 20)

            val widePortraitBase = applyPanelContainerGeometry(widePortraitContext, panel)
            measureAndLayout(root, widePortraitContext, 680, 880)
            assertPanelContainerGeometry(widePortraitContext, root, panel, widePortraitBase, 880, 32, 28)

            val safeInsets =
                SafeAreaGeometry.Insets.of(
                    left = dp(wideLandscapeContext, 7),
                    top = dp(wideLandscapeContext, 5),
                    right = dp(wideLandscapeContext, 11),
                    bottom = dp(wideLandscapeContext, 13),
                )
            val wideLandscapeBase = applyPanelContainerGeometry(wideLandscapeContext, panel, safeInsets)
            measureAndLayout(root, wideLandscapeContext, 880, 680)
            assertPanelContainerGeometry(
                wideLandscapeContext, root, panel, wideLandscapeBase, 880, 32, 12, safeInsets,
            )
        }
    }

    @Test
    fun connectionPanelOuterGeometrySurvivesMultiWindowWidthRoundTrip() {
        val phoneContext = configuredContext(widthDp = 500, heightDp = 800)
        val wideContext = configuredContext(widthDp = 680, heightDp = 880)
        val phoneAgainContext = configuredContext(widthDp = 500, heightDp = 800)

        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val root = inflateLayout(phoneContext)
            val panel = root.findViewById<View>(R.id.settingsPanel)

            val phoneBase = applyPanelContainerGeometry(phoneContext, panel)
            measureAndLayout(root, phoneContext, 500, 800)
            assertPanelContainerGeometry(phoneContext, root, panel, phoneBase, 680, 24, 20)

            val wideBase = applyPanelContainerGeometry(wideContext, panel)
            measureAndLayout(root, wideContext, 680, 880)
            assertPanelContainerGeometry(wideContext, root, panel, wideBase, 880, 32, 28)

            val phoneAgainBase = applyPanelContainerGeometry(phoneAgainContext, panel)
            measureAndLayout(root, phoneAgainContext, 500, 800)
            assertPanelContainerGeometry(phoneAgainContext, root, panel, phoneAgainBase, 680, 24, 20)
        }
    }

    @Test
    fun portraitToWideLandscapeUsesConfigurationWidthBeforeSecondLayout() {
        val portraitContext = configuredContext(widthDp = 361, heightDp = 800, fontScale = 1.3f)
        val landscapeContext = configuredContext(widthDp = 873, heightDp = 393, fontScale = 1.3f)

        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val root = inflateLayout(portraitContext)
            val portrait = MeasuredLayout(portraitContext, root, widthDp = 361, heightDp = 800)
            portrait.showModeContent(R.id.internetModeContent)
            portrait.showDisconnectedInternetSecondaryActions()
            portrait.applyPanel(
                resources = portraitContext.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            portrait.measureAndLayout()
            portrait.assertConfigurationUsesTwoColumns(expected = false)
            portrait.assertModeToggleStacked()
            portrait.assertInternetProfileActionsStacked(expectedGapDp = 8)
            portrait.assertDisconnectedInternetSecondaryActionsStacked(expectedGapDp = 8)

            val staleLandscape = MeasuredLayout(landscapeContext, root, widthDp = 873, heightDp = 393)
            staleLandscape.applyPanel(
                resources = landscapeContext.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            staleLandscape.assertConfigurationUsesTwoColumns(expected = true)
            staleLandscape.assertModeToggleHorizontal()
            staleLandscape.assertInternetProfileActionsHorizontal(expectedGapDp = 8)
            staleLandscape.assertDisconnectedInternetSecondaryActionsHorizontal(expectedGapDp = 8)

            staleLandscape.measureAndLayout()
            staleLandscape.applyPanel(
                resources = landscapeContext.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            staleLandscape.measureAndLayout()

            staleLandscape.assertConfigurationUsesTwoColumns(expected = true)
            staleLandscape.assertModeToggleHorizontal()
            staleLandscape.assertInternetProfileActionsHorizontal(expectedGapDp = 8)
            staleLandscape.assertDisconnectedInternetSecondaryActionsHorizontal(expectedGapDp = 8)
            staleLandscape.assertHeaderAndActionsSeparated()
        }
    }

    @Test
    fun landscapeToPortraitSecondLayoutKeepsActionRowsStackedForNarrowWidth() {
        val landscapeContext = configuredContext(widthDp = 873, heightDp = 393, fontScale = 1.3f)
        val portraitContext = configuredContext(widthDp = 361, heightDp = 800, fontScale = 1.3f)

        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val root = inflateLayout(landscapeContext)
            val landscape = MeasuredLayout(landscapeContext, root, widthDp = 873, heightDp = 393)
            landscape.showModeContent(R.id.internetModeContent)
            landscape.showDisconnectedInternetSecondaryActions()
            landscape.applyPanel(
                resources = landscapeContext.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            landscape.measureAndLayout()
            landscape.assertConfigurationUsesTwoColumns(expected = true)
            landscape.assertModeToggleHorizontal()
            landscape.assertInternetProfileActionsHorizontal(expectedGapDp = 8)
            landscape.assertDisconnectedInternetSecondaryActionsHorizontal(expectedGapDp = 8)

            val portrait = MeasuredLayout(portraitContext, root, widthDp = 361, heightDp = 800)
            portrait.applyPanel(
                resources = portraitContext.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            portrait.measureAndLayout()
            portrait.applyPanel(
                resources = portraitContext.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            portrait.measureAndLayout()

            portrait.assertConfigurationUsesTwoColumns(expected = false)
            portrait.assertModeToggleStacked()
            portrait.assertInternetProfileActionsStacked(expectedGapDp = 8)
            portrait.assertDisconnectedInternetSecondaryActionsStacked(expectedGapDp = 8)
            portrait.assertPrimaryInternetActionVisible()
        }
    }

    @Test
    fun portraitToExpandedLandscapeKeepsModeToggleHorizontalAcrossSecondLayout() {
        val portraitContext = configuredContext(widthDp = 361, heightDp = 800, fontScale = 1.3f)
        val landscapeContext = configuredContext(widthDp = 1200, heightDp = 700, fontScale = 1.3f)

        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val root = inflateLayout(portraitContext)
            val portrait = MeasuredLayout(portraitContext, root, widthDp = 361, heightDp = 800)
            portrait.applyPanel(
                resources = portraitContext.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            portrait.measureAndLayout()
            portrait.assertConfigurationUsesTwoColumns(expected = false)
            portrait.assertModeToggleStacked()

            val expandedLandscape = MeasuredLayout(landscapeContext, root, widthDp = 1200, heightDp = 700)
            expandedLandscape.applyPanel(
                resources = landscapeContext.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            expandedLandscape.assertConfigurationUsesTwoColumns(expected = true)
            expandedLandscape.assertModeToggleHorizontal()

            expandedLandscape.measureAndLayout()
            expandedLandscape.applyPanel(
                resources = landscapeContext.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            expandedLandscape.measureAndLayout()

            expandedLandscape.assertConfigurationUsesTwoColumns(expected = true)
            expandedLandscape.assertModeToggleHorizontal()
            expandedLandscape.assertInternetProfileActionsHorizontal(expectedGapDp = 8)
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
    fun narrowPortraitKeepsUsbRetryDiagnosticsReadableAtMaxFontScale() {
        withLayout(widthDp = 361, heightDp = 800, fontScale = 2f) { layout ->
            layout.showModeContent(R.id.usbModeContent)
            layout.usbErrorContainer.visibility = View.VISIBLE
            layout.checklistContainer.visibility = View.VISIBLE
            val guidance =
                ConnectionGuidanceFactory.from(
                    java.io.IOException("unexpected USB transport failure"),
                    ConnectionGuidanceContext.adb(54321, AdbTransportKind.UNAVAILABLE),
                )
            layout.usbErrorTitle.text = ConnectionGuidanceTextFormatter.format(layout.context.resources, guidance.status)
            layout.usbErrorMessage.text = ConnectionGuidanceTextFormatter.format(layout.context.resources, guidance.message)
            layout.usbErrorContainer.contentDescription =
                layout.context.getString(
                    R.string.connection_guidance_full_message,
                    layout.usbErrorTitle.text,
                    layout.usbErrorMessage.text,
                )

            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.USB,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertRetryActionVisibleOnFirstScreen()
            layout.assertMinimumTouchTarget(layout.connectButton)
            layout.assertTextRenderedWithoutEllipsis(layout.usbErrorTitle)
            layout.assertTextRenderedWithoutEllipsis(layout.usbErrorMessage)
            layout.assertFullyReachableByScroll(layout.usbErrorContainer)
            layout.assertFullyReachableByScroll(layout.usbErrorMessage)
            layout.assertFullyReachableByScroll(layout.checklistContainer)
            layout.assertNoOverlap(layout.connectButton, layout.usbErrorContainer)
            layout.assertNoOverlap(layout.usbErrorTitle, layout.usbErrorMessage)
            layout.assertLargeFontDiagnosticsSpacing()
            layout.assertGroupedDiagnosticsAccessibility()
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
    fun narrowPortraitKeepsInternetSecondaryActionsReadableAtLargeFontScale() {
        withLayout(widthDp = 361, heightDp = 800, fontScale = 2f) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.showAllInternetSecondaryActions()
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertInternetSecondaryActionsStacked(expectedGapDp = 8)
            listOf(
                layout.internetConnectionSettingsButton,
                layout.internetDisconnectButton,
                layout.internetRevokeButton,
            ).forEach { button ->
                layout.assertTextRenderedWithoutEllipsis(button)
                layout.assertMinimumTouchTarget(button)
                layout.assertFullyReachableByScroll(button)
            }
        }
    }

    @Test
    fun defaultFontKeepsInternetSecondaryActionsSideBySide() {
        withLayout(widthDp = 361, heightDp = 800) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.showAllInternetSecondaryActions()
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertInternetSecondaryActionsHorizontal(expectedGapDp = 8)
            listOf(
                layout.internetConnectionSettingsButton,
                layout.internetDisconnectButton,
                layout.internetRevokeButton,
            ).forEach { button ->
                layout.assertMinimumTouchTarget(button)
                layout.assertFullyReachableByScroll(button)
            }
        }
    }

    @Test
    fun hiddenInternetSettingsDoesNotLeaveLeadingSecondaryActionGap() {
        withLayout(widthDp = 361, heightDp = 800, fontScale = 2f) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.showConnectedInternetSecondaryActionsWithoutSettings()
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertConnectedInternetSecondaryActionsStartWithoutGap(expectedGapDp = 8)
            listOf(
                layout.internetDisconnectButton,
                layout.internetRevokeButton,
            ).forEach { button ->
                layout.assertTextRenderedWithoutEllipsis(button)
                layout.assertMinimumTouchTarget(button)
                layout.assertFullyReachableByScroll(button)
            }
        }
    }

    @Test
    fun hiddenInternetSettingsDoesNotLeaveHorizontalLeadingSecondaryActionGap() {
        withLayout(widthDp = 361, heightDp = 800) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.showConnectedInternetSecondaryActionsWithoutSettings()
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertConnectedInternetSecondaryActionsHorizontalStartWithoutGap(expectedGapDp = 8)
        }
    }

    @Test
    fun disconnectedInternetSecondaryActionsKeepSettingsFlushAtLargeFontScale() {
        withLayout(widthDp = 361, heightDp = 800, fontScale = 2f) { layout ->
            layout.showModeContent(R.id.internetModeContent)
            layout.showDisconnectedInternetSecondaryActions()
            layout.applyPanel(
                resources = layout.context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            layout.measureAndLayout()

            layout.assertDisconnectedInternetSecondaryActionsStacked(expectedGapDp = 8)
            listOf(
                layout.internetConnectionSettingsButton,
                layout.internetRevokeButton,
            ).forEach { button ->
                layout.assertTextRenderedWithoutEllipsis(button)
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

    @Test
    fun narrowPortraitLargeTextKeepsLegalFooterReachableReadableAndTouchable() {
        listOf(320 to 640, 360 to 800).forEach { (widthDp, heightDp) ->
            withLayout(widthDp = widthDp, heightDp = heightDp, fontScale = 2f) { layout ->
                layout.showModeContent(R.id.usbModeContent)
                layout.applyPanel(
                    resources = layout.context.resources,
                    connectionMode = ConnectionMode.USB,
                    subtitleExpanded = false,
                )
                layout.measureAndLayout()

                layout.assertFullyReachableByScroll(layout.legalFooter)
                layout.assertFullyReachableByScroll(layout.legalSummary)
                layout.assertFullyReachableByScroll(layout.openSourceLicensesButton)
                layout.assertTextRenderedWithoutEllipsis(layout.legalSummary)
                layout.assertTextRenderedWithoutEllipsis(layout.openSourceLicensesButton)
                layout.assertMinimumTouchTarget(layout.openSourceLicensesButton)
                layout.assertNoOverlap(layout.legalSummary, layout.openSourceLicensesButton)
            }
        }
    }

    @Test
    fun narrowPortraitLargeTextKeepsWirelessAndInternetPrimaryActionsSelfSizing() {
        listOf(320 to 640, 360 to 800).forEach { (widthDp, heightDp) ->
            listOf(1.5f, 2.0f).forEach { fontScale ->
                withLayout(widthDp = widthDp, heightDp = heightDp, fontScale = fontScale) { layout ->
                    layout.showModeContent(R.id.internetModeContent)
                    layout.applyPanel(
                        resources = layout.context.resources,
                        connectionMode = ConnectionMode.INTERNET,
                        subtitleExpanded = false,
                    )
                    layout.measureAndLayout()
                    layout.assertPrimaryActionSelfSizes(layout.internetConnectButton)

                    layout.showWirelessState(layout.wirelessFirstTime)
                    layout.applyPanel(
                        resources = layout.context.resources,
                        connectionMode = ConnectionMode.WIRELESS,
                        subtitleExpanded = false,
                    )
                    layout.measureAndLayout()
                    layout.assertPrimaryActionSelfSizes(layout.wirelessScanButton)

                    layout.showWirelessState(layout.wirelessPairedIdle)
                    layout.applyPanel(
                        resources = layout.context.resources,
                        connectionMode = ConnectionMode.WIRELESS,
                        subtitleExpanded = false,
                    )
                    layout.measureAndLayout()
                    layout.assertPrimaryActionSelfSizes(layout.wirelessReconnectButton)

                    layout.showWirelessState(layout.wirelessTokenMismatch)
                    layout.applyPanel(
                        resources = layout.context.resources,
                        connectionMode = ConnectionMode.WIRELESS,
                        subtitleExpanded = false,
                    )
                    layout.measureAndLayout()
                    layout.assertPrimaryActionSelfSizes(layout.wirelessRescanButton)

                    layout.showWirelessState(layout.wirelessPermDenied)
                    layout.applyPanel(
                        resources = layout.context.resources,
                        connectionMode = ConnectionMode.WIRELESS,
                        subtitleExpanded = false,
                    )
                    layout.measureAndLayout()
                    layout.assertPrimaryActionSelfSizes(layout.wirelessOpenSettingsButton)
                }
            }
        }
    }

    @Test
    fun primaryActionSelfSizingSurvivesNarrowWideRoundTripsAtLargeFontScales() {
        listOf(1.5f to 2.0f, 2.0f to 1.5f).forEach { (narrowFontScale, wideFontScale) ->
            val narrowContext = configuredContext(widthDp = 320, heightDp = 640, fontScale = narrowFontScale)
            val wideContext = configuredContext(widthDp = 600, heightDp = 360, fontScale = wideFontScale)
            val narrowAgainContext = configuredContext(widthDp = 360, heightDp = 800, fontScale = narrowFontScale)

            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                val root = inflateLayout(narrowContext)
                val narrow = MeasuredLayout(narrowContext, root, widthDp = 320, heightDp = 640)
                narrow.showModeContent(R.id.internetModeContent)
                narrow.applyPanel(
                    resources = narrowContext.resources,
                    connectionMode = ConnectionMode.INTERNET,
                    subtitleExpanded = false,
                )
                narrow.measureAndLayout()
                narrow.assertConfigurationUsesTwoColumns(expected = false)
                narrow.assertAllWirelessAndInternetPrimaryActionsSelfSize()

                val wide = MeasuredLayout(wideContext, root, widthDp = 600, heightDp = 360)
                wide.applyPanel(
                    resources = wideContext.resources,
                    connectionMode = ConnectionMode.WIRELESS,
                    subtitleExpanded = false,
                )
                wide.measureAndLayout()
                wide.assertConfigurationUsesTwoColumns(expected = true)
                wide.assertAllWirelessAndInternetPrimaryActionsSelfSize()

                val narrowAgain = MeasuredLayout(narrowAgainContext, root, widthDp = 360, heightDp = 800)
                narrowAgain.applyPanel(
                    resources = narrowAgainContext.resources,
                    connectionMode = ConnectionMode.INTERNET,
                    subtitleExpanded = false,
                )
                narrowAgain.measureAndLayout()
                narrowAgain.assertConfigurationUsesTwoColumns(expected = false)
                narrowAgain.assertAllWirelessAndInternetPrimaryActionsSelfSize()
            }
        }
    }

    @Test
    fun openSourceLicensesButtonOpensPackagedNoticesDialog() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val launchIntent = Intent(applicationContext(), MainActivity::class.java)
            .putExtra(AUTO_CONNECT_EXTRA, false)
        ActivityScenario.launch<MainActivity>(launchIntent).use { scenario ->
            scenario.onActivity { activity ->
                val scrollView = activity.findViewById<NestedScrollView>(R.id.connectionScroll)
                val button = activity.findViewById<View>(R.id.openSourceLicensesButton)
                scrollView.scrollTo(0, scrollView.getChildAt(0).height)
                assertTrue("Open-source notices entry should accept clicks", button.performClick())
            }
            instrumentation.waitForIdleSync()
            val expectedTitle = applicationContext().getString(R.string.open_source_notices_title)
            assertTrue(
                "Open-source notices dialog title should be visible after clicking the production entry point",
                instrumentation.waitForVisibleText(expectedTitle),
            )
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

    private fun android.app.Instrumentation.waitForVisibleText(
        expected: String,
        timeoutMs: Long = 5_000L,
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        do {
            val root = uiAutomation.rootInActiveWindow
            if (root != null && root.containsText(expected)) return true
            Thread.sleep(50)
        } while (System.currentTimeMillis() < deadline)
        return false
    }

    private fun AccessibilityNodeInfo.containsText(expected: String): Boolean {
        if (text?.toString() == expected || contentDescription?.toString() == expected) return true
        for (index in 0 until childCount) {
            val child = getChild(index) ?: continue
            if (child.containsText(expected)) return true
        }
        return false
    }

    private fun dp(
        context: Context,
        value: Int,
    ): Int = (value * context.resources.displayMetrics.density).roundToInt()

    private fun applyPanelContainerGeometry(
        context: Context,
        panel: View,
        safeAreaInsets: SafeAreaGeometry.Insets = SafeAreaGeometry.Insets.NONE,
    ): SafeAreaGeometry.Insets =
        ConnectionPanelContainerGeometryApplier.apply(context.resources, panel, safeAreaInsets)

    private fun measureAndLayout(
        root: ViewGroup,
        context: Context,
        widthDp: Int,
        heightDp: Int,
    ) {
        root.measure(
            View.MeasureSpec.makeMeasureSpec(dp(context, widthDp), View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(dp(context, heightDp), View.MeasureSpec.EXACTLY),
        )
        root.layout(0, 0, root.measuredWidth, root.measuredHeight)
    }

    private fun assertPanelContainerGeometry(
        context: Context,
        root: ViewGroup,
        panel: View,
        baseMargins: SafeAreaGeometry.Insets,
        maxWidthDp: Int,
        horizontalMarginDp: Int,
        verticalMarginDp: Int,
        safeAreaInsets: SafeAreaGeometry.Insets = SafeAreaGeometry.Insets.NONE,
    ) {
        val params = panel.layoutParams as ConstraintLayout.LayoutParams
        val expectedBase =
            SafeAreaGeometry.Insets.of(
                left = dp(context, horizontalMarginDp),
                top = dp(context, verticalMarginDp),
                right = dp(context, horizontalMarginDp),
                bottom = dp(context, verticalMarginDp),
            )
        assertEquals(dp(context, maxWidthDp), params.matchConstraintMaxWidth)
        assertEquals(expectedBase.left + safeAreaInsets.left, params.marginStart)
        assertEquals(expectedBase.top + safeAreaInsets.top, params.topMargin)
        assertEquals(expectedBase.right + safeAreaInsets.right, params.marginEnd)
        assertEquals(expectedBase.bottom + safeAreaInsets.bottom, params.bottomMargin)
        assertEquals(expectedBase, baseMargins)
        assertEquals(params.marginStart, panel.left)
        assertEquals(params.topMargin, panel.top)
        assertEquals(root.measuredWidth - params.marginEnd, panel.right)
        assertEquals(root.measuredHeight - params.bottomMargin, panel.bottom)
        assertTrue(panel.measuredWidth <= params.matchConstraintMaxWidth)
    }

    private class MeasuredLayout(
        val context: Context,
        val root: ViewGroup,
        widthDp: Int,
        heightDp: Int,
    ) {
        val header = root.findViewById<LinearLayout>(R.id.connectionHeader)
        val actions = root.findViewById<LinearLayout>(R.id.connectionActions)
        private val panel = root.findViewById<View>(R.id.settingsPanel)
        val content = root.findViewById<LinearLayout>(R.id.connectionContent)
        val subtitle = root.findViewById<TextView>(R.id.connectionSubtitle)
        val internetError = root.findViewById<TextView>(R.id.internetErrorText)
        val usbErrorContainer = root.findViewById<View>(R.id.connectionErrorContainer)
        val usbErrorTitle = root.findViewById<TextView>(R.id.connectionErrorTitle)
        val usbErrorMessage = root.findViewById<TextView>(R.id.connectionErrorMessage)
        val checklistContainer = root.findViewById<View>(R.id.checklistContainer)
        val connectButton = root.findViewById<TextView>(R.id.connectButton)
        val inlineSettingsButton = root.findViewById<View>(R.id.connectionSettingsButton)
        val usbModeButton = root.findViewById<TextView>(R.id.modeUSB)
        val wirelessModeButton = root.findViewById<TextView>(R.id.modeWireless)
        val internetModeButton = root.findViewById<TextView>(R.id.modeInternet)
        val internetProfileActions = root.findViewById<LinearLayout>(R.id.internetProfileActions)
        val internetProfileSummary = root.findViewById<TextView>(R.id.internetProfileSummary)
        val internetStateText = root.findViewById<TextView>(R.id.internetStateText)
        val modeToggle = root.findViewById<LinearLayout>(R.id.modeToggleGroup)
        val wirelessFirstTime = root.findViewById<View>(R.id.wirelessFirstTime)
        val wirelessPairedIdle = root.findViewById<View>(R.id.wirelessPairedIdle)
        val wirelessTokenMismatch = root.findViewById<View>(R.id.wirelessTokenMismatch)
        val wirelessPermDenied = root.findViewById<View>(R.id.wirelessPermDenied)
        val wirelessScanButton = root.findViewById<TextView>(R.id.wirelessScanButton)
        val wirelessReconnectButton = root.findViewById<TextView>(R.id.wirelessReconnectButton)
        val wirelessRescanButton = root.findViewById<TextView>(R.id.wirelessRescanButton)
        val wirelessOpenSettingsButton = root.findViewById<TextView>(R.id.wirelessOpenSettingsButton)
        val internetScanProfileButton = root.findViewById<TextView>(R.id.internetScanProfileButton)
        val internetImportProfileButton = root.findViewById<TextView>(R.id.internetImportProfileButton)
        val internetConnectButton = root.findViewById<TextView>(R.id.internetConnectButton)
        val internetSecondaryActions = root.findViewById<LinearLayout>(R.id.internetSecondaryActions)
        val internetConnectionSettingsButton = root.findViewById<TextView>(R.id.internetConnectionSettingsButton)
        val internetDisconnectButton = root.findViewById<TextView>(R.id.internetDisconnectButton)
        val internetRevokeButton = root.findViewById<TextView>(R.id.internetRevokeButton)
        val legalFooter = root.findViewById<View>(R.id.connectionLegalFooter)
        val legalSummary = root.findViewById<TextView>(R.id.connectionLegalSummary)
        val openSourceLicensesButton = root.findViewById<TextView>(R.id.openSourceLicensesButton)
        private val scrollView = root.findViewById<NestedScrollView>(R.id.connectionScroll)
        private val icon = root.findViewById<View>(R.id.connectionIcon)
        private val wordmark = root.findViewById<View>(R.id.connectionWordmark)
        private val title = root.findViewById<View>(R.id.connectionTitle)
        private val progress = root.findViewById<View>(R.id.connectionProgress)
        private val internetRouteLabel = root.findViewById<View>(R.id.internetRouteLabel)
        private val internetRouteToggle = root.findViewById<View>(R.id.internetRouteToggleGroup)
        private val internetConnect = internetConnectButton
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

        fun showWirelessState(activeState: View) {
            showModeContent(R.id.wirelessModeContent)
            listOf(wirelessFirstTime, wirelessPairedIdle, wirelessTokenMismatch, wirelessPermDenied)
                .forEach { state -> state.visibility = if (state === activeState) View.VISIBLE else View.GONE }
        }

        fun showAllInternetSecondaryActions() {
            internetConnectionSettingsButton.visibility = View.VISIBLE
            internetDisconnectButton.visibility = View.VISIBLE
            internetRevokeButton.visibility = View.VISIBLE
        }

        fun showConnectedInternetSecondaryActionsWithoutSettings() {
            internetConnectionSettingsButton.visibility = View.GONE
            internetDisconnectButton.visibility = View.VISIBLE
            internetRevokeButton.visibility = View.VISIBLE
        }

        fun showDisconnectedInternetSecondaryActions() {
            internetConnectionSettingsButton.visibility = View.VISIBLE
            internetDisconnectButton.visibility = View.GONE
            internetRevokeButton.visibility = View.VISIBLE
        }

        fun assertAllWirelessAndInternetPrimaryActionsSelfSize() {
            showModeContent(R.id.internetModeContent)
            applyPanel(
                resources = context.resources,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            measureAndLayout()
            assertPrimaryActionSelfSizes(internetConnectButton)

            showWirelessState(wirelessFirstTime)
            applyPanel(
                resources = context.resources,
                connectionMode = ConnectionMode.WIRELESS,
                subtitleExpanded = false,
            )
            measureAndLayout()
            assertPrimaryActionSelfSizes(wirelessScanButton)

            showWirelessState(wirelessPairedIdle)
            applyPanel(
                resources = context.resources,
                connectionMode = ConnectionMode.WIRELESS,
                subtitleExpanded = false,
            )
            measureAndLayout()
            assertPrimaryActionSelfSizes(wirelessReconnectButton)

            showWirelessState(wirelessTokenMismatch)
            applyPanel(
                resources = context.resources,
                connectionMode = ConnectionMode.WIRELESS,
                subtitleExpanded = false,
            )
            measureAndLayout()
            assertPrimaryActionSelfSizes(wirelessRescanButton)

            showWirelessState(wirelessPermDenied)
            applyPanel(
                resources = context.resources,
                connectionMode = ConnectionMode.WIRELESS,
                subtitleExpanded = false,
            )
            measureAndLayout()
            assertPrimaryActionSelfSizes(wirelessOpenSettingsButton)
        }

        fun useLongConnectionActionLabels() {
            usbModeButton.text = "USB cable"
            wirelessModeButton.text = "Trusted LAN"
            internetModeButton.text = "Internet preview"
            internetScanProfileButton.text = "Scan pairing QR"
            internetImportProfileButton.text = "Import profile file"
            internetConnectionSettingsButton.text = "Display settings"
            internetDisconnectButton.text = "Disconnect session"
            internetRevokeButton.text = "Revoke this Mac"
        }

        fun useVeryLongConnectionActionLabels() {
            usbModeButton.text = "UsbDisplayRecoveryProbeLabel"
            wirelessModeButton.text = "TrustedNetworkRecoveryProbeLabel"
            internetModeButton.text = "InternetPreviewRecoveryProbeLabel"
            internetScanProfileButton.text = "ScanPairingRecoveryProbeLabel"
            internetImportProfileButton.text = "ImportProfileRecoveryProbeLabel"
            internetConnectionSettingsButton.text = "DisplaySettingsRecoveryProbeLabel"
            internetDisconnectButton.text = "DisconnectSessionRecoveryProbeLabel"
            internetRevokeButton.text = "RevokePairingRecoveryProbeLabel"
        }

        fun useVeryLongInternetSecondaryActionLabels() {
            internetConnectionSettingsButton.text = "DisplaySettingsRecoveryProbeLabel"
            internetDisconnectButton.text = "DisconnectSessionRecoveryProbeLabel"
            internetRevokeButton.text = "RevokePairingRecoveryProbeLabel"
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

        fun assertPrimaryActionSelfSizes(button: TextView) {
            val viewName = button.resources.getResourceEntryName(button.id)
            assertEquals("$viewName should allow exactly two rendered text lines", 2, button.maxLines)
            assertEquals("$viewName must not enable ellipsis", null, button.ellipsize)
            assertTrue("$viewName height was " + button.height + "px", button.height >= dp(56))
            assertTextRenderedWithoutEllipsis(button)
            assertTextVerticallyUnclipped(button)
            assertFullyReachableByScroll(button)
            assertNoVisibleSiblingOverlap(button)
        }

        fun assertTextVerticallyUnclipped(text: TextView) {
            val textLayout = checkNotNull(text.layout)
            val viewName = text.resources.getResourceEntryName(text.id)
            val availableTextHeight = (text.height - text.compoundPaddingTop - text.compoundPaddingBottom).coerceAtLeast(0)
            val lastLineBottom = textLayout.getLineBottom(textLayout.lineCount - 1)
            assertTrue(
                "$viewName text bottom $lastLineBottom exceeded available height $availableTextHeight " +
                    "viewHeight=" + text.height +
                    " paddingTop=" + text.compoundPaddingTop +
                    " paddingBottom=" + text.compoundPaddingBottom +
                    " lineCount=" + textLayout.lineCount +
                    " text='" + text.text + "'",
                lastLineBottom <= availableTextHeight,
            )
        }

        fun assertReadableActionRowFitsActionsColumn(
            gapDp: Int,
            vararg ids: Int,
        ) {
            val buttonWidthsPx = ConnectionPanelLayoutApplier.readableButtonWidthsPx(actions, *ids)
            val totalGapPx = dp(gapDp) * (buttonWidthsPx.size - 1).coerceAtLeast(0)
            val requiredWidthPx = buttonWidthsPx.sum() + totalGapPx
            assertTrue(
                "Required readable action row width $requiredWidthPx px must fit actions column ${actions.width} px",
                requiredWidthPx <= actions.width,
            )
        }

        fun assertReadableWidthCountsMaterialIconOnce(button: TextView) {
            val materialButton = button as MaterialButton
            val readableWidth =
                ConnectionPanelLayoutApplier.readableButtonWidthsPx(actions, button.id).single()
            val textWidth = readableTextWidthPx(button)
            val compoundPadding = button.compoundPaddingStart + button.compoundPaddingEnd
            val iconWidth = materialButton.icon?.intrinsicWidth?.coerceAtLeast(0) ?: 0
            val iconSpace = iconWidth + materialButton.iconPadding.coerceAtLeast(0)
            val explicitPaddingWithIcon = button.paddingStart + button.paddingEnd + iconSpace
            assertTrue(
                "Icon-bearing button must expose icon space for this assertion",
                iconSpace > 0,
            )
            assertEquals(
                textWidth + maxOf(compoundPadding, explicitPaddingWithIcon),
                readableWidth,
            )
            assertTrue(
                "Readable width must not add icon space on top of compound padding: " +
                    "readable=$readableWidth text=$textWidth compound=$compoundPadding iconSpace=$iconSpace",
                readableWidth <= textWidth + compoundPadding + iconSpace,
            )
            if (compoundPadding >= explicitPaddingWithIcon) {
                assertTrue(
                    "Compound padding already accounts for the icon, so readable width must stay below double-counted width",
                    readableWidth < textWidth + compoundPadding + iconSpace,
                )
            }
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

        fun assertPanelGeometryUsesResources() {
            val params = panel.layoutParams as ConstraintLayout.LayoutParams
            val expectedHorizontalMargin = context.resources.getDimensionPixelSize(R.dimen.connection_panel_margin_horizontal)
            val expectedVerticalMargin = context.resources.getDimensionPixelSize(R.dimen.connection_panel_margin_vertical)
            assertEquals(context.resources.getDimensionPixelSize(R.dimen.connection_panel_max_width), params.matchConstraintMaxWidth)
            assertEquals(expectedHorizontalMargin, params.marginStart)
            assertEquals(expectedHorizontalMargin, params.marginEnd)
            assertEquals(expectedVerticalMargin, params.topMargin)
            assertEquals(expectedVerticalMargin, params.bottomMargin)
            assertTrue(
                "panel width ${panel.measuredWidth}px must not exceed max ${params.matchConstraintMaxWidth}px",
                panel.measuredWidth <= params.matchConstraintMaxWidth,
            )
        }

        fun assertNoOverlap(
            first: View,
            second: View,
        ) {
            assertFalse(
                first.resources.getResourceEntryName(first.id) + " must not overlap " +
                    second.resources.getResourceEntryName(second.id),
                Rect.intersects(boundsInContent(first), boundsInContent(second)),
            )
        }

        fun assertNoVisibleSiblingOverlap(target: View) {
            val parent = target.parent as? ViewGroup ?: return
            val targetBounds = boundsInContent(target)
            for (index in 0 until parent.childCount) {
                val sibling = parent.getChildAt(index)
                if (sibling === target || sibling.visibility == View.GONE) continue
                assertFalse(
                    viewName(target) + " must not overlap visible sibling " + viewName(sibling),
                    Rect.intersects(targetBounds, boundsInContent(sibling)),
                )
            }
        }

        private fun viewName(view: View): String =
            if (view.id != View.NO_ID) {
                view.resources.getResourceEntryName(view.id)
            } else {
                view.javaClass.simpleName
            }

        fun assertGroupedDiagnosticsAccessibility() {
            assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, usbErrorContainer.accessibilityLiveRegion)
            assertTrue(ViewCompat.isScreenReaderFocusable(usbErrorContainer))
            assertEquals(
                context.getString(
                    R.string.connection_guidance_full_message,
                    usbErrorTitle.text,
                    usbErrorMessage.text,
                ),
                usbErrorContainer.contentDescription.toString(),
            )
            assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_NO, usbErrorTitle.importantForAccessibility)
        }

        fun assertLargeFontDiagnosticsSpacing() {
            assertEquals(dp(12), usbErrorContainer.paddingStart)
            assertEquals(dp(12), usbErrorContainer.paddingTop)
            assertEquals(dp(12), usbErrorContainer.paddingEnd)
            assertEquals(dp(12), usbErrorContainer.paddingBottom)
            assertEquals(dp(8), margins(usbErrorTitle).bottomMargin)
        }

        fun assertModeToggleStacked() {
            assertEquals(LinearLayout.VERTICAL, modeToggle.orientation)
            listOf(usbModeButton, wirelessModeButton, internetModeButton).forEach { button ->
                assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, button.layoutParams.width)
                assertEquals(0f, linearMargins(button).weight, 0f)
            }
        }

        fun assertModeToggleHorizontal() {
            assertEquals(LinearLayout.HORIZONTAL, modeToggle.orientation)
            listOf(usbModeButton, wirelessModeButton, internetModeButton).forEach { button ->
                assertEquals(0, button.layoutParams.width)
                assertEquals(1f, linearMargins(button).weight, 0f)
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

        fun assertInternetSecondaryActionsStacked(expectedGapDp: Int) {
            assertEquals(LinearLayout.VERTICAL, internetSecondaryActions.orientation)
            listOf(
                internetConnectionSettingsButton to 0,
                internetDisconnectButton to expectedGapDp,
                internetRevokeButton to expectedGapDp,
            ).forEach { (button, topMarginDp) ->
                assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, button.layoutParams.width)
                assertEquals(0f, linearMargins(button).weight, 0f)
                assertEquals(0, linearMargins(button).marginStart)
                assertEquals(dp(topMarginDp), linearMargins(button).topMargin)
            }
        }

        fun assertInternetSecondaryActionsHorizontal(expectedGapDp: Int) {
            assertEquals(LinearLayout.HORIZONTAL, internetSecondaryActions.orientation)
            listOf(
                internetConnectionSettingsButton to 0,
                internetDisconnectButton to expectedGapDp,
                internetRevokeButton to expectedGapDp,
            ).forEach { (button, startMarginDp) ->
                assertEquals(0, button.layoutParams.width)
                assertEquals(1f, linearMargins(button).weight, 0f)
                assertEquals(dp(startMarginDp), linearMargins(button).marginStart)
                assertEquals(0, linearMargins(button).topMargin)
            }
        }

        fun assertConnectedInternetSecondaryActionsStartWithoutGap(expectedGapDp: Int) {
            assertEquals(LinearLayout.VERTICAL, internetSecondaryActions.orientation)
            assertEquals(View.GONE, internetConnectionSettingsButton.visibility)
            assertEquals(View.VISIBLE, internetDisconnectButton.visibility)
            assertEquals(View.VISIBLE, internetRevokeButton.visibility)
            assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, internetDisconnectButton.layoutParams.width)
            assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, internetRevokeButton.layoutParams.width)
            assertEquals(0f, linearMargins(internetDisconnectButton).weight, 0f)
            assertEquals(0f, linearMargins(internetRevokeButton).weight, 0f)
            assertEquals(0, linearMargins(internetDisconnectButton).marginStart)
            assertEquals(0, linearMargins(internetDisconnectButton).topMargin)
            assertEquals(0, linearMargins(internetRevokeButton).marginStart)
            assertEquals(dp(expectedGapDp), linearMargins(internetRevokeButton).topMargin)
        }

        fun assertConnectedInternetSecondaryActionsHorizontalStartWithoutGap(expectedGapDp: Int) {
            assertEquals(LinearLayout.HORIZONTAL, internetSecondaryActions.orientation)
            assertEquals(View.GONE, internetConnectionSettingsButton.visibility)
            assertEquals(View.VISIBLE, internetDisconnectButton.visibility)
            assertEquals(View.VISIBLE, internetRevokeButton.visibility)
            assertEquals(0, internetDisconnectButton.layoutParams.width)
            assertEquals(0, internetRevokeButton.layoutParams.width)
            assertEquals(1f, linearMargins(internetDisconnectButton).weight, 0f)
            assertEquals(1f, linearMargins(internetRevokeButton).weight, 0f)
            assertEquals(0, linearMargins(internetDisconnectButton).marginStart)
            assertEquals(0, linearMargins(internetDisconnectButton).topMargin)
            assertEquals(dp(expectedGapDp), linearMargins(internetRevokeButton).marginStart)
            assertEquals(0, linearMargins(internetRevokeButton).topMargin)
        }

        fun assertDisconnectedInternetSecondaryActionsStacked(expectedGapDp: Int) {
            assertEquals(LinearLayout.VERTICAL, internetSecondaryActions.orientation)
            assertEquals(View.VISIBLE, internetConnectionSettingsButton.visibility)
            assertEquals(View.GONE, internetDisconnectButton.visibility)
            assertEquals(View.VISIBLE, internetRevokeButton.visibility)
            assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, internetConnectionSettingsButton.layoutParams.width)
            assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, internetRevokeButton.layoutParams.width)
            assertEquals(0f, linearMargins(internetConnectionSettingsButton).weight, 0f)
            assertEquals(0f, linearMargins(internetRevokeButton).weight, 0f)
            assertEquals(0, linearMargins(internetConnectionSettingsButton).marginStart)
            assertEquals(0, linearMargins(internetConnectionSettingsButton).topMargin)
            assertEquals(0, linearMargins(internetRevokeButton).marginStart)
            assertEquals(dp(expectedGapDp), linearMargins(internetRevokeButton).topMargin)
        }

        fun assertDisconnectedInternetSecondaryActionsHorizontal(expectedGapDp: Int) {
            assertEquals(LinearLayout.HORIZONTAL, internetSecondaryActions.orientation)
            assertEquals(View.VISIBLE, internetConnectionSettingsButton.visibility)
            assertEquals(View.GONE, internetDisconnectButton.visibility)
            assertEquals(View.VISIBLE, internetRevokeButton.visibility)
            assertEquals(0, internetConnectionSettingsButton.layoutParams.width)
            assertEquals(0, internetRevokeButton.layoutParams.width)
            assertEquals(1f, linearMargins(internetConnectionSettingsButton).weight, 0f)
            assertEquals(1f, linearMargins(internetRevokeButton).weight, 0f)
            assertEquals(0, linearMargins(internetConnectionSettingsButton).marginStart)
            assertEquals(0, linearMargins(internetConnectionSettingsButton).topMargin)
            assertEquals(dp(expectedGapDp), linearMargins(internetRevokeButton).marginStart)
            assertEquals(0, linearMargins(internetRevokeButton).topMargin)
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
            val profileActionsBounds = boundsInContent(internetProfileActions)
            assertTrue(
                "Internet action height was " + internetConnect.height + "px",
                internetConnect.height >= dp(48),
            )
            assertTrue(
                "Internet action " + actionBounds + " starts below the " +
                    scrollView.height + "px first-screen viewport",
                actionBounds.top >= 0 && actionBounds.bottom <= scrollView.height,
            )
            assertTrue(
                "Internet action " + actionBounds + " should precede profile actions " + profileActionsBounds,
                actionBounds.bottom <= profileActionsBounds.top,
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

        private fun readableTextWidthPx(text: TextView): Int {
            val availableLines = text.maxLines.takeIf { it > 0 } ?: 1
            val label = text.text.toString()
            val paint = Paint(text.paint)
            val balancedLineWidth = ceilDiv(paint.measureText(label).roundToInt(), availableLines)
            val longestWordWidth =
                label.split(Regex("\\s+"))
                    .filter { it.isNotBlank() }
                    .maxOfOrNull { word -> paint.measureText(word).roundToInt() }
                    ?: 0
            return maxOf(balancedLineWidth, longestWordWidth)
        }

        private fun ceilDiv(
            value: Int,
            divisor: Int,
        ): Int {
            val safeDivisor = divisor.coerceAtLeast(1)
            return (value.coerceAtLeast(0) + safeDivisor - 1) / safeDivisor
        }
    }

    private fun ConnectionGuidance.formattedMessage(context: Context): String =
        ConnectionGuidanceTextFormatter.format(context.resources, message)
}
