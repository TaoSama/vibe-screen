package dev.telemachus.display

import android.R.attr.state_checked
import android.R.attr.state_enabled
import android.content.Context
import android.content.res.Configuration
import android.content.res.Resources
import android.graphics.Typeface
import android.util.TypedValue
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.graphics.ColorUtils
import androidx.core.view.ViewCompat
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.material.button.MaterialButton
import com.google.android.material.button.MaterialButtonToggleGroup
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.roundToInt

@RunWith(AndroidJUnit4::class)
class ConnectionStateAccessibilityInstrumentedTest {
    @Test
    fun productionConnectionStatesUsePoliteLiveRegions() {
        withProductionLayout { root ->
            listOf(
                R.id.connectionTitle,
                R.id.connectionSubtitle,
                R.id.connectionErrorMessage,
                R.id.statusText,
                R.id.internetProfileSummary,
                R.id.internetStateText,
                R.id.wirelessConnecting,
                R.id.wirelessFirstTime,
                R.id.wirelessConnected,
                R.id.wirelessPairedIdle,
                R.id.wirelessTokenMismatch,
                R.id.repairMessage,
                R.id.wirelessPermDenied,
            ).forEach { id ->
                assertEquals(
                    root.resources.getResourceEntryName(id),
                    View.ACCESSIBILITY_LIVE_REGION_POLITE,
                    root.findViewById<View>(id).accessibilityLiveRegion,
                )
            }
            assertEquals(
                View.ACCESSIBILITY_LIVE_REGION_NONE,
                root.findViewById<View>(R.id.connectionErrorTitle).accessibilityLiveRegion,
            )
            assertEquals(
                View.ACCESSIBILITY_LIVE_REGION_ASSERTIVE,
                root.findViewById<View>(R.id.internetErrorText).accessibilityLiveRegion,
            )
            assertEquals(
                View.ACCESSIBILITY_LIVE_REGION_NONE,
                root.findViewById<View>(R.id.wirelessCameraPermissionRetry).accessibilityLiveRegion,
            )
        }
    }

    @Test
    fun connectionGuidanceRegionsExposeGroupedScreenReaderStatus() {
        withProductionLayout { root ->
            val views = connectionPanelViews(root)
            ConnectionPanelLayoutApplier.apply(
                resources = root.resources,
                views = views,
                connectionMode = ConnectionMode.USB,
                subtitleExpanded = false,
            )

            assertTrue(ViewCompat.isAccessibilityHeading(root.findViewById(R.id.connectionTitle)))
            val connectionErrorContainer = root.findViewById<View>(R.id.connectionErrorContainer)
            assertTrue(ViewCompat.isScreenReaderFocusable(connectionErrorContainer))
            assertEquals(
                listOf("connectionErrorMessage"),
                clickableDescendantNames(connectionErrorContainer),
            )
            assertEquals(
                "Selectable diagnostic text keeps copy handles without owning the grouped status announcement",
                View.ACCESSIBILITY_LIVE_REGION_NONE,
                root.findViewById<View>(R.id.connectionErrorTitle).accessibilityLiveRegion,
            )
            listOf(
                R.id.wirelessConnecting,
                R.id.internetProfileSummary,
                R.id.internetStateText,
                R.id.internetErrorText,
            ).forEach { id ->
                val region = root.findViewById<View>(id)
                assertTrue(
                    root.resources.getResourceEntryName(id),
                    ViewCompat.isScreenReaderFocusable(region),
                )
                val clickableDescendants = clickableDescendantNames(region)
                assertTrue(
                    "${root.resources.getResourceEntryName(id)} clickable descendants: $clickableDescendants",
                    clickableDescendants.isEmpty(),
                )
            }
            listOf(
                R.id.wirelessFirstTime to R.id.wirelessScanButton,
                R.id.wirelessConnected to R.id.wirelessDisconnectButton,
                R.id.wirelessConnected to R.id.wirelessForgetButton,
                R.id.wirelessPairedIdle to R.id.wirelessReconnectButton,
                R.id.wirelessPairedIdle to R.id.wirelessIdleForgetButton,
                R.id.wirelessTokenMismatch to R.id.wirelessRescanButton,
                R.id.wirelessPermDenied to R.id.wirelessOpenSettingsButton,
            ).forEach { (regionId, buttonId) ->
                val region = root.findViewById<View>(regionId)
                val button = root.findViewById<MaterialButton>(buttonId)
                assertFalse(
                    root.resources.getResourceEntryName(regionId),
                    ViewCompat.isScreenReaderFocusable(region),
                )
                assertTrue(root.resources.getResourceEntryName(buttonId), button.isClickable)
                assertNotEquals(
                    root.resources.getResourceEntryName(buttonId),
                    View.IMPORTANT_FOR_ACCESSIBILITY_NO,
                    button.importantForAccessibility,
                )
                assertNotEquals(
                    root.resources.getResourceEntryName(buttonId),
                    View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS,
                    button.importantForAccessibility,
                )
            }
        }
    }

    @Test
    fun wirelessRepairGuidanceExposesFullScreenReaderStatus() {
        withProductionLayout { root ->
            val controller =
                WirelessTabController(
                    host = FakeWirelessTabHost(root.context),
                    views = wirelessViews(root),
                    storage = FakeWirelessPairingStore(),
                    cameraPerm = FakeWirelessCameraPermission(),
                    isTrustedLanAcknowledged = { true },
                    acknowledgeTrustedLan = {},
                    onConnectRequested = { _, _, _, _, _ -> },
                )
            val guidance =
                ConnectionGuidanceFactory.from(
                    java.net.ConnectException("ECONNREFUSED"),
                    ConnectionGuidanceContext.trustedLan(54321),
                )

            controller.showConnectionGuidance(guidance)

            val title = root.findViewById<TextView>(R.id.repairTitle)
            val message = root.findViewById<TextView>(R.id.repairMessage)
            val expectedTitle = ConnectionGuidanceTextFormatter.format(root.resources, guidance.status)
            val expectedMessage = ConnectionGuidanceTextFormatter.format(root.resources, guidance.message)
            assertEquals(View.VISIBLE, root.findViewById<View>(R.id.wirelessTokenMismatch).visibility)
            assertEquals(expectedTitle, title.text.toString())
            assertEquals(expectedMessage, message.text.toString())
            assertEquals(
                root.context.getString(R.string.connection_guidance_full_message, expectedTitle, expectedMessage),
                message.contentDescription,
            )
            assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, message.accessibilityLiveRegion)
            assertTrue(root.findViewById<Button>(R.id.wirelessRescanButton).isClickable)
        }
    }

    @Test
    fun wirelessLanStateMachineKeepsPanelsMutuallyExclusiveAndActionsCurrent() {
        withProductionLayout { root ->
            val context = root.context
            root.findViewById<View>(R.id.wirelessModeContent).visibility = View.VISIBLE
            val storage = FakeWirelessPairingStore()
            val cameraPermission = FakeWirelessCameraPermission()
            val controller =
                WirelessTabController(
                    host = FakeWirelessTabHost(context),
                    views = wirelessViews(root),
                    storage = storage,
                    cameraPerm = cameraPermission,
                    isTrustedLanAcknowledged = { true },
                    acknowledgeTrustedLan = {},
                    onConnectRequested = { _, _, _, _, _ -> },
                )
            controller.bind()

            controller.show()
            assertOnlyWirelessPanelVisible(root, R.id.wirelessFirstTime)
            assertWirelessActions(
                root,
                WirelessAction(R.id.wirelessScanButton, context.getString(R.string.scan_qr_code)),
            )
            assertEquals(context.getString(R.string.scan_qr_code), root.buttonText(R.id.wirelessScanButton))
            assertTrue(root.findViewById<Button>(R.id.wirelessScanButton).isEnabled)
            assertEquals(View.GONE, root.findViewById<View>(R.id.wirelessCameraPermissionRetry).visibility)

            controller.onScanResult(TEST_PAIRING_URL)
            assertOnlyWirelessPanelVisible(root, R.id.wirelessConnecting)
            assertWirelessActions(root)
            assertEquals(
                context.getString(R.string.connecting_to_mac, TEST_MAC_NAME),
                root.text(R.id.connectingLabel),
            )
            assertEquals(TEST_LAN_ENDPOINT, root.text(R.id.connectingSubtitle))

            controller.onConnectSuccess(TEST_MAC_NAME, TEST_LAN_ENDPOINT)
            assertOnlyWirelessPanelVisible(root, R.id.wirelessConnected)
            assertWirelessActions(
                root,
                WirelessAction(R.id.wirelessDisconnectButton, context.getString(R.string.disconnect)),
                WirelessAction(R.id.wirelessForgetButton, context.getString(R.string.forget_this_mac)),
            )
            assertEquals(TEST_MAC_NAME, root.text(R.id.connectedMacName))
            assertEquals(TEST_LAN_ENDPOINT, root.text(R.id.connectedMacIp))
            assertTrue(root.findViewById<Button>(R.id.wirelessDisconnectButton).isEnabled)
            assertTrue(root.findViewById<Button>(R.id.wirelessForgetButton).isEnabled)

            controller.onStreamDisconnected()
            assertOnlyWirelessPanelVisible(root, R.id.wirelessPairedIdle)
            assertWirelessActions(
                root,
                WirelessAction(R.id.wirelessReconnectButton, context.getString(R.string.reconnect)),
                WirelessAction(R.id.wirelessIdleForgetButton, context.getString(R.string.forget_this_mac)),
            )
            assertEquals(context.getString(R.string.disconnected_status), root.text(R.id.idleStatusLabel))
            assertEquals(TEST_MAC_NAME, root.text(R.id.idleMacName))
            assertEquals(TEST_LAN_ENDPOINT, root.text(R.id.idleMacIp))
            assertEquals(View.GONE, root.findViewById<View>(R.id.wirelessReconnectCountdown).visibility)
            assertEquals(context.getString(R.string.reconnect), root.buttonText(R.id.wirelessReconnectButton))
            assertTrue(root.findViewById<Button>(R.id.wirelessReconnectButton).isEnabled)

            controller.showAutomaticReconnect(TEST_MAC_NAME, TEST_LAN_HOST, TEST_LAN_PORT, remainingSeconds = 9)
            assertOnlyWirelessPanelVisible(root, R.id.wirelessPairedIdle)
            assertWirelessActions(
                root,
                WirelessAction(R.id.wirelessReconnectButton, context.getString(R.string.retry_now)),
                WirelessAction(R.id.wirelessIdleForgetButton, context.getString(R.string.forget_this_mac)),
            )
            assertEquals(context.getString(R.string.reconnect_countdown_title), root.text(R.id.idleStatusLabel))
            assertEquals(View.VISIBLE, root.findViewById<View>(R.id.wirelessReconnectCountdown).visibility)
            assertEquals(
                context.getString(R.string.reconnect_countdown_message, TEST_MAC_NAME, TEST_LAN_HOST, TEST_LAN_PORT, 9),
                root.text(R.id.wirelessReconnectCountdown),
            )
            assertEquals(context.getString(R.string.retry_now), root.buttonText(R.id.wirelessReconnectButton))
            assertTrue(root.findViewById<Button>(R.id.wirelessReconnectButton).isEnabled)
            assertTrue(root.findViewById<Button>(R.id.wirelessIdleForgetButton).isEnabled)

            controller.showAutomaticReconnectAttempting(TEST_MAC_NAME, TEST_LAN_HOST, TEST_LAN_PORT)
            assertOnlyWirelessPanelVisible(root, R.id.wirelessPairedIdle)
            assertWirelessActions(
                root,
                WirelessAction(R.id.wirelessReconnectButton, context.getString(R.string.connecting), enabled = false),
                WirelessAction(R.id.wirelessIdleForgetButton, context.getString(R.string.forget_this_mac)),
            )
            assertEquals(context.getString(R.string.reconnecting_short), root.text(R.id.idleStatusLabel))
            assertEquals(
                context.getString(R.string.reconnect_attempting_message, TEST_MAC_NAME, TEST_LAN_HOST, TEST_LAN_PORT),
                root.text(R.id.wirelessReconnectCountdown),
            )
            assertEquals(context.getString(R.string.connecting), root.buttonText(R.id.wirelessReconnectButton))
            assertFalse(root.findViewById<Button>(R.id.wirelessReconnectButton).isEnabled)

            controller.onConnectError(StreamClient.WirelessConnectError.TokenRejected)
            assertOnlyWirelessPanelVisible(root, R.id.wirelessTokenMismatch)
            assertWirelessActions(
                root,
                WirelessAction(R.id.wirelessRescanButton, context.getString(R.string.scan_qr_code)),
            )
            assertEquals(context.getString(R.string.wireless_error_title_repair_required), root.text(R.id.repairTitle))
            assertEquals(
                context.getString(R.string.wireless_error_token_rejected_cached, TEST_MAC_NAME),
                root.text(R.id.repairMessage),
            )
            assertTrue(root.findViewById<Button>(R.id.wirelessRescanButton).isEnabled)

            storage.clear()
            controller.onConnectError(StreamClient.WirelessConnectError.TokenRejected)
            assertOnlyWirelessPanelVisible(root, R.id.wirelessTokenMismatch)
            assertWirelessActions(
                root,
                WirelessAction(R.id.wirelessRescanButton, context.getString(R.string.scan_qr_code)),
            )
            assertEquals(
                context.getString(R.string.wireless_error_token_rejected_uncached),
                root.text(R.id.repairMessage),
            )

            controller.onCameraPermissionResult(granted = false)
            assertOnlyWirelessPanelVisible(root, R.id.wirelessFirstTime)
            assertWirelessActions(
                root,
                WirelessAction(R.id.wirelessScanButton, context.getString(R.string.scan_qr_code)),
            )
            assertEquals(View.VISIBLE, root.findViewById<View>(R.id.wirelessCameraPermissionRetry).visibility)
            assertEquals(context.getString(R.string.scan_qr_code), root.buttonText(R.id.wirelessScanButton))
            assertTrue(root.findViewById<Button>(R.id.wirelessScanButton).isEnabled)

            cameraPermission.permanentlyDenied = true
            controller.onCameraPermissionResult(granted = false)
            assertOnlyWirelessPanelVisible(root, R.id.wirelessPermDenied)
            assertWirelessActions(
                root,
                WirelessAction(R.id.wirelessOpenSettingsButton, context.getString(R.string.open_settings)),
            )
            assertEquals(View.GONE, root.findViewById<View>(R.id.wirelessCameraPermissionRetry).visibility)
            assertTrue(root.findViewById<Button>(R.id.wirelessOpenSettingsButton).performClick())
            assertEquals(1, cameraPermission.openSettingsCalls)
        }
    }

    @Test
    fun productionLayoutDoesNotPreRenderModeSpecificGuidance() {
        withProductionLayout { root ->
            val title = root.findViewById<TextView>(R.id.connectionTitle)
            val subtitle = root.findViewById<TextView>(R.id.connectionSubtitle)
            val status = root.findViewById<TextView>(R.id.statusText)

            assertEquals("", title.text.toString())
            assertEquals("", subtitle.text.toString())
            assertEquals(root.context.getString(R.string.looking_for_mac), status.text.toString())
        }
    }

    @Test
    fun liveRegionTextOnlyChangesForNewContent() {
        withProductionLayout { root ->
            val label = root.findViewById<TextView>(R.id.statusText)
            val original = label.text

            assertFalse(LiveRegionTextApplier.apply(label, original.toString()))
            assertTrue("Equivalent content should preserve the current text instance", original === label.text)

            val replacement = "Connection failed with actionable guidance"
            assertTrue(LiveRegionTextApplier.apply(label, replacement))
            assertEquals(replacement, label.text.toString())
            assertFalse(LiveRegionTextApplier.apply(label, replacement))
        }
    }

    @Test
    fun hiddenLiveRegionMessageReannouncesTheSameErrorWhenShownAgain() {
        withProductionLayout { root ->
            val error = root.findViewById<TextView>(R.id.internetErrorText)
            val message = "Pairing expired. Import a fresh profile."

            assertTrue(LiveRegionTextApplier.show(error, message))
            assertEquals(View.VISIBLE, error.visibility)
            assertEquals(message, error.text.toString())

            assertTrue(LiveRegionTextApplier.hide(error))
            assertEquals(View.GONE, error.visibility)
            assertEquals("", error.text.toString())

            assertTrue(LiveRegionTextApplier.show(error, message))
            assertEquals(View.VISIBLE, error.visibility)
            assertEquals(message, error.text.toString())
        }
    }

    @Test
    fun connectedStatusAnnouncementUsesVisibleStreamChromeAndDeduplicates() {
        withProductionLayout { root ->
            val settingsPanel = root.findViewById<View>(R.id.settingsPanel)
            val controlBar = root.findViewById<View>(R.id.controlBar)
            settingsPanel.visibility = View.GONE
            controlBar.visibility = View.VISIBLE

            val announcements = mutableListOf<String>()
            val coordinator = ConnectionStatusAnnouncementCoordinator()
            val connected = root.context.getString(R.string.connected_streaming)
            val announce = { text: CharSequence ->
                assertEquals(View.VISIBLE, controlBar.visibility)
                announcements += text.toString()
            }

            assertTrue(coordinator.announceIfChanged(connected, announce))
            assertFalse(coordinator.announceIfChanged(connected, announce))
            assertEquals(listOf(connected), announcements)

            coordinator.reset()
            assertTrue(coordinator.announceIfChanged(connected, announce))
            assertEquals(listOf(connected, connected), announcements)
        }
    }

    @Test
    fun connectionDetailsMeetsTouchTargetAndKeepsItsFullLabel() {
        listOf(1f, 2f).forEach { fontScale ->
            val configuration = Configuration(applicationContext().resources.configuration)
            configuration.screenWidthDp = 320
            configuration.fontScale = fontScale
            val configuredContext = applicationContext().createConfigurationContext(configuration)

            withProductionLayout(configuredContext) { root ->
                val action = root.findViewById<TextView>(R.id.showAdvanced)
                listOf(R.string.connection_details, R.string.hide_connection_details).forEach { label ->
                    action.setText(label)
                    measureAndLayout(root, configuredContext, widthDp = 320, heightDp = 800)

                    assertTrue(action.measuredHeight >= dp(configuredContext, 48))
                    val textLayout = checkNotNull(action.layout)
                    assertTrue((0 until textLayout.lineCount).all { textLayout.getEllipsisCount(it) == 0 })
                    assertEquals(action.text.length, textLayout.getLineEnd(textLayout.lineCount - 1))
                    assertTrue(
                        textLayout.getLineBottom(textLayout.lineCount - 1) <=
                            action.height - action.compoundPaddingBottom,
                    )
                }
            }
        }
    }

    @Test
    fun internetSecurityDescriptionStaysFullyVisibleWithoutDisclosureActions() {
        val context = configuredContext(widthDp = 361, heightDp = 800)
        withProductionLayout(context) { root ->
            val subtitle = root.findViewById<TextView>(R.id.connectionSubtitle)
            val views = connectionPanelViews(root)
            subtitle.setText(R.string.internet_waiting_description)

            ConnectionPanelLayoutApplier.apply(
                resources = context.resources,
                views = views,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            measureAndLayout(root, context, widthDp = 361, heightDp = 800)
            assertEquals(
                context.getString(R.string.internet_waiting_description),
                subtitle.text.toString(),
            )
            assertFalse(subtitle.isClickable)
            assertFalse(subtitle.isFocusable)
            assertTrue(subtitle.compoundDrawablesRelative[2] == null)
            assertEquals(Int.MAX_VALUE, subtitle.maxLines)
            assertTrue(ViewCompat.getStateDescription(subtitle) == null)
            val node = AccessibilityNodeInfoCompat.obtain()
            ViewCompat.onInitializeAccessibilityNodeInfo(subtitle, node)
            assertFalse(
                node.actionList.any {
                    it.label == context.getString(R.string.internet_security_details_expand_action) ||
                        it.label == context.getString(R.string.internet_security_details_collapse_action)
                },
            )
            val textLayout = checkNotNull(subtitle.layout)
            assertTrue((0 until textLayout.lineCount).all { textLayout.getEllipsisCount(it) == 0 })

            ConnectionPanelLayoutApplier.apply(
                resources = context.resources,
                views = views,
                connectionMode = ConnectionMode.USB,
                subtitleExpanded = false,
            )
            assertEquals(0, subtitle.minimumHeight)
            assertFalse(subtitle.isClickable)
            assertFalse(subtitle.isFocusable)
            assertTrue(subtitle.compoundDrawablesRelative[2] == null)
            assertEquals(Int.MAX_VALUE, subtitle.maxLines)
        }
    }

    @Test
    fun internetSecurityDescriptionStaysVisibleAfterModeAndConfigurationChanges() {
        listOf(
            configuredContext(widthDp = 361, heightDp = 800),
            configuredContext(widthDp = 800, heightDp = 361),
        ).forEach { context ->
            withProductionLayout(context) { root ->
                val subtitle = root.findViewById<TextView>(R.id.connectionSubtitle)
                val views = connectionPanelViews(root)
                subtitle.setText(R.string.internet_waiting_description)

                ConnectionPanelLayoutApplier.apply(
                    resources = root.resources,
                    views = views,
                    connectionMode = ConnectionMode.INTERNET,
                    subtitleExpanded = false,
                )
                assertEquals(Int.MAX_VALUE, subtitle.maxLines)
                assertFalse(subtitle.isClickable)

                ConnectionPanelLayoutApplier.apply(
                    resources = root.resources,
                    views = views,
                    connectionMode = ConnectionMode.WIRELESS,
                    subtitleExpanded = false,
                )
                ConnectionPanelLayoutApplier.apply(
                    resources = root.resources,
                    views = views,
                    connectionMode = ConnectionMode.INTERNET,
                    subtitleExpanded = false,
                )
                val configuration = context.resources.configuration
                measureAndLayout(
                    root,
                    context,
                    widthDp = configuration.screenWidthDp,
                    heightDp = configuration.screenHeightDp,
                )
                assertTextRenderedWithoutEllipsis(subtitle)

                assertEquals(root.context.getString(R.string.internet_waiting_description), subtitle.text.toString())
                assertEquals(Int.MAX_VALUE, subtitle.maxLines)
                assertFalse(subtitle.isClickable)
                assertFalse(subtitle.isFocusable)
                assertTrue(subtitle.compoundDrawablesRelative[2] == null)
            }
        }
    }

    @Test
    fun p0110UsbErrorCopyKeepsChecklistReachableWithLargeText() {
        val context = configuredContext(widthDp = 361, heightDp = 800, fontScale = 1.3f)
        withProductionLayout(context) { root ->
            val errorContainer = root.findViewById<View>(R.id.connectionErrorContainer)
            val errorMessage = root.findViewById<TextView>(R.id.connectionErrorMessage)
            val checklist = root.findViewById<View>(R.id.checklistContainer)
            val scrollView = root.findViewById<ViewGroup>(R.id.connectionScroll)
            val content = root.findViewById<ViewGroup>(R.id.connectionContent)

            root.findViewById<View>(R.id.usbModeContent).visibility = View.VISIBLE
            errorContainer.visibility = View.VISIBLE
            checklist.visibility = View.VISIBLE
            val guidance =
                ConnectionGuidanceFactory.from(
                    java.net.ConnectException("ECONNREFUSED"),
                    ConnectionGuidanceContext.adb(54321, AdbTransportKind.USB),
                )
            errorMessage.text = ConnectionGuidanceTextFormatter.format(context.resources, guidance.message)
            ConnectionPanelLayoutApplier.apply(
                resources = context.resources,
                views = connectionPanelViews(root),
                connectionMode = ConnectionMode.USB,
                subtitleExpanded = false,
            )
            measureAndLayout(root, context, widthDp = 361, heightDp = 800)

            assertFalse(errorMessage.text.toString().contains("adb reverse", ignoreCase = true))
            assertTextRenderedWithoutEllipsis(errorMessage)
            val checklistBounds = boundsInAncestor(content, checklist)
            assertTrue("Checklist starts below first viewport: $checklistBounds", checklistBounds.top < scrollView.height)
        }
    }

    @Test
    fun p0110ModeToggleKeepsInternetReadableWithLargeText() {
        val context = configuredContext(widthDp = 361, heightDp = 800, fontScale = 1.3f)
        withProductionLayout(context) { root ->
            measureAndLayout(root, context, widthDp = 361, heightDp = 800)

            listOf(R.id.modeUSB, R.id.modeWireless, R.id.modeInternet).forEach { id ->
                val button = root.findViewById<MaterialButton>(id)
                assertTrue(root.resources.getResourceEntryName(id), button.measuredHeight >= dp(context, 48))
                assertFalse(root.resources.getResourceEntryName(id), button.isAllCaps)
                assertTextRenderedWithoutEllipsis(button)
            }
        }
    }

    @Test
    fun productionModeToggleHasReadableCheckedAndDistinctDisabledStates() {
        withProductionLayout { root ->
            listOf(R.id.modeUSB, R.id.modeWireless, R.id.modeInternet).forEach { id ->
                val button = root.findViewById<MaterialButton>(id)
                assertTrue(
                    root.resources.getResourceEntryName(id),
                    button.autoSizeMinTextSize >= sp(root.context, 12),
                )
                val checkedBackground = stateColor(button.backgroundTintList, state_enabled, state_checked)
                val checkedText = stateColor(button.textColors, state_enabled, state_checked)
                val disabledBackground = stateColor(button.backgroundTintList, -state_enabled, state_checked)
                val disabledText = stateColor(button.textColors, -state_enabled)

                assertTrue(ColorUtils.calculateContrast(checkedText, checkedBackground) >= 4.5)
                assertNotEquals(checkedBackground, disabledBackground)
                assertNotEquals(checkedText, disabledText)
            }
        }
    }

    @Test
    fun internetRouteToggleDoesNotAutosizeBelowReadableText() {
        withProductionLayout { root ->
            listOf(R.id.internetPreferDirect, R.id.internetForceRelay).forEach { id ->
                val button = root.findViewById<MaterialButton>(id)
                assertTrue(
                    root.resources.getResourceEntryName(id),
                    button.autoSizeMinTextSize >= sp(root.context, 12),
                )
            }
        }
    }

    @Test
    fun productionUsbConnectVisuallyDistinguishesEnabledAndDisabledStates() {
        withProductionLayout { root ->
            val button = root.findViewById<MaterialButton>(R.id.connectButton)
            val enabledBackground = stateColor(button.backgroundTintList, state_enabled)
            val disabledBackground = stateColor(button.backgroundTintList, -state_enabled)
            val enabledText = stateColor(button.textColors, state_enabled)
            val disabledText = stateColor(button.textColors, -state_enabled)

            assertNotEquals(enabledBackground, disabledBackground)
            assertNotEquals(enabledText, disabledText)
            assertTrue(ColorUtils.calculateContrast(enabledText, enabledBackground) >= 4.5)
        }
    }

    @Test
    fun productionChecklistReportsEveryTransportLabelAndHighlightsFailures() {
        withProductionLayout { root ->
            val indicator = root.findViewById<View>(R.id.checkDeveloperMode)
            val label = root.findViewById<TextView>(R.id.textDeveloperMode)
            val context = root.context
            val labels =
                listOf(
                    R.string.developer_mode,
                    R.string.usb_debugging,
                    R.string.wireless_debugging,
                    R.string.usb_or_wireless_debugging,
                    R.string.usb_data_link,
                    R.string.wireless_debugging_connection,
                    R.string.usb_data_link_or_wireless_debugging,
                    R.string.mac_server,
                )

            labels.forEach { labelResource ->
                ChecklistStatus.entries.forEach { status ->
                    ChecklistStatusApplier.apply(context, indicator, label, labelResource, status)
                    assertEquals(
                        context.getString(
                            R.string.checklist_item_status,
                            context.getString(labelResource),
                            context.getString(
                                when (status) {
                                    ChecklistStatus.READY -> R.string.checklist_ready
                                    ChecklistStatus.NOT_READY -> R.string.checklist_not_ready
                                    ChecklistStatus.CHECKING -> R.string.checklist_checking
                                },
                            ),
                        ),
                        label.text.toString(),
                    )
                }
            }
            assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, label.accessibilityLiveRegion)
            assertFalse(indicator.isImportantForAccessibility)

            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.mac_server,
                ChecklistStatus.CHECKING,
            )
            val unchangedText = label.text
            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.mac_server,
                ChecklistStatus.CHECKING,
            )
            assertTrue("Unchanged status should not replace the live-region text", unchangedText === label.text)

            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.mac_server,
                ChecklistStatus.NOT_READY,
            )
            assertEquals(ContextCompat.getColor(context, R.color.warning), label.currentTextColor)
            assertEquals(Typeface.BOLD, (label.typeface?.style ?: Typeface.NORMAL) and Typeface.BOLD)

            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.mac_server,
                ChecklistStatus.READY,
            )
            assertEquals(ContextCompat.getColor(context, R.color.on_surface_muted), label.currentTextColor)
            assertEquals(Typeface.NORMAL, label.typeface?.style ?: Typeface.NORMAL)
        }
    }

    private fun withProductionLayout(
        context: Context = applicationContext(),
        block: (ViewGroup) -> Unit,
    ) {
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val themedContext = ContextThemeWrapper(context, R.style.AppTheme)
            block(LayoutInflater.from(themedContext).inflate(R.layout.activity_main, null, false) as ViewGroup)
        }
    }

    private fun measureAndLayout(
        root: ViewGroup,
        context: Context,
        widthDp: Int,
        heightDp: Int,
    ) {
        val widthPx = dp(context, widthDp)
        val heightPx = dp(context, heightDp)
        root.measure(
            View.MeasureSpec.makeMeasureSpec(widthPx, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(heightPx, View.MeasureSpec.EXACTLY),
        )
        root.layout(0, 0, root.measuredWidth, root.measuredHeight)
    }

    private fun configuredContext(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float = 1f,
        orientation: Int =
            if (widthDp > heightDp) Configuration.ORIENTATION_LANDSCAPE else Configuration.ORIENTATION_PORTRAIT,
    ): Context {
        val configuration = Configuration(applicationContext().resources.configuration)
        configuration.screenWidthDp = widthDp
        configuration.screenHeightDp = heightDp
        configuration.smallestScreenWidthDp = minOf(widthDp, heightDp)
        configuration.fontScale = fontScale
        configuration.orientation = orientation
        return applicationContext().createConfigurationContext(configuration)
    }

    private fun assertTextRenderedWithoutEllipsis(text: TextView) {
        val textLayout = checkNotNull(text.layout)
        assertTrue(text.measuredWidth > 0 && text.measuredHeight > 0)
        assertTrue((0 until textLayout.lineCount).all { line -> textLayout.getEllipsisCount(line) == 0 })
        assertEquals(text.text.length, textLayout.getLineEnd(textLayout.lineCount - 1))
    }

    private fun boundsInAncestor(
        ancestor: ViewGroup,
        view: View,
    ): android.graphics.Rect =
        android.graphics.Rect(0, 0, view.width, view.height).also { rect ->
            ancestor.offsetDescendantRectToMyCoords(view, rect)
        }

    private fun connectionPanelViews(root: ViewGroup): ConnectionPanelLayoutApplier.Views =
        ConnectionPanelLayoutApplier.Views(
            content = root.findViewById(R.id.connectionContent),
            header = root.findViewById(R.id.connectionHeader),
            actions = root.findViewById(R.id.connectionActions),
            subtitle = root.findViewById(R.id.connectionSubtitle),
        )

    private fun wirelessViews(root: View): WirelessTabController.Views =
        WirelessTabController.Views(
            connecting = root.findViewById(R.id.wirelessConnecting),
            firstTime = root.findViewById(R.id.wirelessFirstTime),
            connected = root.findViewById(R.id.wirelessConnected),
            pairedIdle = root.findViewById(R.id.wirelessPairedIdle),
            repair = root.findViewById(R.id.wirelessTokenMismatch),
            permDenied = root.findViewById(R.id.wirelessPermDenied),
            scanButton = root.findViewById<Button>(R.id.wirelessScanButton),
            rescanButton = root.findViewById<Button>(R.id.wirelessRescanButton),
            disconnectButton = root.findViewById<Button>(R.id.wirelessDisconnectButton),
            forgetButton = root.findViewById<Button>(R.id.wirelessForgetButton),
            reconnectButton = root.findViewById<Button>(R.id.wirelessReconnectButton),
            idleForgetButton = root.findViewById<Button>(R.id.wirelessIdleForgetButton),
            openSettingsButton = root.findViewById<Button>(R.id.wirelessOpenSettingsButton),
            connectedMacName = root.findViewById(R.id.connectedMacName),
            connectedMacIp = root.findViewById(R.id.connectedMacIp),
            connectingLabel = root.findViewById(R.id.connectingLabel),
            connectingSubtitle = root.findViewById(R.id.connectingSubtitle),
            idleStatusLabel = root.findViewById(R.id.idleStatusLabel),
            idleMacName = root.findViewById(R.id.idleMacName),
            idleMacIp = root.findViewById(R.id.idleMacIp),
            reconnectCountdown = root.findViewById(R.id.wirelessReconnectCountdown),
            permissionRetryMessage = root.findViewById(R.id.wirelessCameraPermissionRetry),
            repairTitle = root.findViewById(R.id.repairTitle),
            repairMessage = root.findViewById(R.id.repairMessage),
        )

    private fun assertOnlyWirelessPanelVisible(
        root: View,
        visiblePanelId: Int,
    ) {
        WIRELESS_PANEL_IDS.forEach { panelId ->
            assertEquals(
                root.resources.getResourceEntryName(panelId),
                if (panelId == visiblePanelId) View.VISIBLE else View.GONE,
                root.findViewById<View>(panelId).visibility,
            )
        }
    }

    private fun assertWirelessActions(
        root: View,
        vararg expectedActions: WirelessAction,
    ) {
        val expectedById = expectedActions.associateBy { it.id }
        WIRELESS_ACTION_IDS.forEach { actionId ->
            val button = root.findViewById<Button>(actionId)
            val expected = expectedById[actionId]
            val name = root.resources.getResourceEntryName(actionId)
            if (expected == null) {
                assertFalse(
                    "$name should not be exposed outside its active LAN panel",
                    button.isVisibleWithin(root),
                )
            } else {
                assertTrue(
                    "$name should be exposed in its active LAN panel",
                    button.isVisibleWithin(root),
                )
                assertEquals(name, expected.text, button.text.toString())
                assertEquals(name, expected.enabled, button.isEnabled)
            }
        }
    }

    private fun View.isVisibleWithin(root: View): Boolean {
        var current: View? = this
        while (current != null) {
            if (current.visibility != View.VISIBLE) return false
            if (current === root) return true
            current = current.parent as? View
        }
        return false
    }

    private fun View.text(id: Int): String = findViewById<TextView>(id).text.toString()

    private fun View.buttonText(id: Int): String = findViewById<Button>(id).text.toString()

    private fun assertAccessibilityAction(
        view: View,
        expectedLabel: String,
    ) {
        val actionLabels = view.createAccessibilityNodeInfo().actionList.mapNotNull { it.label?.toString() }
        assertTrue("Expected accessibility action '$expectedLabel' in $actionLabels", expectedLabel in actionLabels)
    }

    private fun clickableDescendantNames(view: View): List<String> {
        val group = view as? ViewGroup ?: return emptyList()
        return (0 until group.childCount).flatMap { index ->
            val child = group.getChildAt(index)
            val childName = viewName(child)
            val self = if (child.isClickable && child.isImportantForAccessibility) listOf(childName) else emptyList()
            self + clickableDescendantNames(child)
        }
    }

    private fun viewName(view: View): String =
        if (view.id == View.NO_ID) {
            view.javaClass.simpleName
        } else {
            view.resources.getResourceEntryName(view.id)
        }

    private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

    private fun dp(context: Context, value: Int): Int =
        (value * context.resources.displayMetrics.density).roundToInt()

    private fun sp(context: Context, value: Int): Int =
        TypedValue
            .applyDimension(TypedValue.COMPLEX_UNIT_SP, value.toFloat(), context.resources.displayMetrics)
            .roundToInt()

    private fun stateColor(colors: android.content.res.ColorStateList?, vararg states: Int): Int {
        checkNotNull(colors)
        return colors.getColorForState(states, colors.defaultColor)
    }

    private data class WirelessAction(
        val id: Int,
        val text: String,
        val enabled: Boolean = true,
    )

    private class FakeWirelessPairingStore : WirelessPairingStore {
        private var entry: PairedHostStorage.Entry? = null

        override fun save(entry: PairedHostStorage.Entry) {
            this.entry = entry
        }

        override fun load(): PairedHostStorage.Entry? = entry

        override fun clear() {
            entry = null
        }
    }

    private class FakeWirelessCameraPermission : WirelessCameraPermission {
        var permanentlyDenied: Boolean = false
        var openSettingsCalls: Int = 0

        override fun isGranted(): Boolean = true

        override fun isPermanentlyDenied(): Boolean = permanentlyDenied

        override fun request(requestCode: Int) = Unit

        override fun openAppSettings() {
            openSettingsCalls += 1
        }
    }

    private class FakeWirelessTabHost(
        private val context: Context,
    ) : WirelessTabHost {
        override val resources: Resources
            get() = context.resources

        override fun getString(
            resId: Int,
            vararg formatArgs: Any,
        ): String = context.getString(resId, *formatArgs)

        override fun showTrustedNetworkDialog(onConfirmed: () -> Unit) {
            onConfirmed()
        }

        override fun launchScanner() = Unit
    }

    private companion object {
        const val TEST_MAC_NAME = "Studio Mac"
        const val TEST_LAN_HOST = "192.168.50.8"
        const val TEST_LAN_PORT = 54321
        const val TEST_LAN_TOKEN = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        val TEST_LAN_ENDPOINT = "$TEST_LAN_HOST:$TEST_LAN_PORT"
        val TEST_PAIRING_URL = "telemachus://$TEST_LAN_HOST:$TEST_LAN_PORT?t=$TEST_LAN_TOKEN&name=$TEST_MAC_NAME"
        val WIRELESS_PANEL_IDS =
            listOf(
                R.id.wirelessConnecting,
                R.id.wirelessFirstTime,
                R.id.wirelessConnected,
                R.id.wirelessPairedIdle,
                R.id.wirelessTokenMismatch,
                R.id.wirelessPermDenied,
            )
        val WIRELESS_ACTION_IDS =
            listOf(
                R.id.wirelessScanButton,
                R.id.wirelessDisconnectButton,
                R.id.wirelessForgetButton,
                R.id.wirelessReconnectButton,
                R.id.wirelessIdleForgetButton,
                R.id.wirelessRescanButton,
                R.id.wirelessOpenSettingsButton,
            )
    }
}
