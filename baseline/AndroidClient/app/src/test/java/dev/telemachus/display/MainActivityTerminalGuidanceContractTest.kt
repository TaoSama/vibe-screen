package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityTerminalGuidanceContractTest {
    @Test
    fun onSessionEndedUsesRetainedSessionPortInsteadOfCurrentUiPort() {
        val callback = onSessionEndedCallback(mainActivitySource())
        val compactCallback = callback.replace(Regex("\\s+"), " ")

        assertTrue(
            "onSessionEnded must build guidance from the immutable session context",
            compactCallback.contains("guidanceContext.withPort(callbackClient.actualPort)"),
        )
        assertFalse(
            "onSessionEnded must not read the current UI port",
            callback.contains("currentUsbPort()"),
        )
        assertFalse(
            "onSessionEnded must not read view binding on the termination thread",
            callback.contains("binding."),
        )
        assertFalse(
            "onSessionEnded diagnostics must not persist raw failure details",
            callback.contains("failure.detail"),
        )
    }

    @Test
    fun setupCallersCaptureUsbAndLanOwnershipBeforeCallbacks() {
        val source = mainActivitySource().replace(Regex("\\s+"), " ")

        assertTrue(
            "USB connections must capture their ADB transport before callback delivery",
            source.contains("ConnectionGuidanceContext.adb(port, currentUsbTransportSnapshot().adbTransport)"),
        )
        assertTrue(
            "LAN connections must capture trusted-LAN ownership",
            source.contains("ConnectionGuidanceContext.trustedLan(port)"),
        )
        assertTrue(
            "Internet failures must use Internet-owned guidance",
            source.contains("ConnectionGuidanceContext.internet()"),
        )
    }

    @Test
    fun usbConnectionGuidanceUsesInlineErrorInsteadOfBlockingDialog() {
        val source = mainActivitySource()
        val connect = extractMethod(source, "private fun connect")
        val disconnected = extractMethod(source, "private fun applyDisconnectedSessionUi")
        val compactDisconnected = disconnected.replace(Regex("\\s+"), "")

        assertFalse(
            "USB connection failures must not block the disconnected panel with an AlertDialog",
            connect.contains("showError(guidance.message)"),
        )
        assertFalse(
            "USB connection failures must not use the blocking terminal dialog path",
            connect.contains("showError(guidanceMessage(guidance))"),
        )
        assertTrue(
            "Manual USB connection failures should render inline guidance",
            connect.contains("inlineGuidance?.let(::showUsbConnectionGuidance)"),
        )
        assertFalse(
            "Automatic USB retry failures should still render actionable inline guidance",
            connect.contains("!automatic && e !is SessionProtocolException"),
        )
        assertTrue(
            "Retryable protocol failures should still show pre-session inline guidance while retrying",
            connect.contains("if (e !is SessionProtocolException || e.failure.retryable)"),
        )
        assertTrue(
            "Terminal guidance must route through the mode-specific inline guidance presenter",
            disconnected.contains("showTerminalConnectionGuidance(mode, guidance)"),
        )
        assertFalse(
            "Terminal guidance must not fall back to the blocking dialog path",
            compactDisconnected.contains("showError(guidanceMessage(guidance))"),
        )
    }

    @Test
    fun reconnectSuggestionRoutesThroughSingleRetryCoordinator() {
        val source = mainActivitySource()
        val reconnectCallback = extractCallback(source, "callbackClient.onReconnectSuggested = reconnect@")
        val compactCallback = reconnectCallback.replace(Regex("\\s+"), "")

        assertTrue(
            "StreamClient reconnect suggestions must feed the session retry coordinator",
            compactCallback.contains("retryCoordinator.onReconnectSuggested(delayMs)"),
        )
        assertFalse(
            "Reconnect callback must not independently schedule USB retries",
            reconnectCallback.contains("scheduleAutomaticUsbConnect"),
        )
        assertFalse(
            "Reconnect callback must not independently schedule wireless retries",
            reconnectCallback.contains("scheduleWirelessReconnect"),
        )
        assertFalse(
            "Reconnect callback must not store a shared pending retry delay outside the coordinator",
            reconnectCallback.contains("pendingAutomaticReconnectDelayMs"),
        )
        assertFalse(
            "MainActivity must not keep a second wireless ReconnectBackoff owner",
            source.contains("initialWirelessReconnectBackoff"),
        )
    }

    @Test
    fun automaticRetryConsumersUseCoordinatorSuggestedDelay() {
        val source = mainActivitySource()
        val usbConnect = extractMethod(source, "private fun connect")
        val wirelessConnect = extractMethod(source, "private fun connectWireless")
        val usbRetryConsumer = extractBlockAfterMarker(usbConnect, "createSessionAutomaticRetryCoordinator(callbackClient, callbackGeneration)")
        val wirelessRetryConsumer = extractBlockAfterMarker(wirelessConnect, "createSessionAutomaticRetryCoordinator(callbackClient, callbackGeneration)")

        assertTrue(
            "USB retry consumer must accept the coordinator delay parameter",
            usbRetryConsumer.contains("{ delayMs: Long ->"),
        )
        assertTrue(
            "USB retry consumer must schedule with the suggested delay",
            usbRetryConsumer.contains("scheduleAutomaticUsbConnect(delayMs)"),
        )
        assertFalse(
            "USB retry consumer must not fall back to the old fixed or shared pending delay path",
            usbRetryConsumer.contains("pendingAutomaticReconnectDelayMs") ||
                usbRetryConsumer.contains("pendingWirelessReconnectDelayMs"),
        )
        assertTrue(
            "Wireless retry consumer must accept the coordinator delay parameter",
            wirelessRetryConsumer.contains("{ delayMs: Long ->"),
        )
        assertTrue(
            "Wireless retry consumer must schedule with the suggested delay",
            wirelessRetryConsumer.contains("scheduleWirelessReconnect(delayMs)"),
        )
    }

    @Test
    fun backgroundWirelessReconnectKeepsCoordinatorSelectedDelayForForegroundResume() {
        val source = mainActivitySource()
        val onStart = extractMethod(source, "override fun onStart")
        val scheduleWirelessReconnect = extractMethod(source, "private fun scheduleWirelessReconnect")
        val compactScheduler = scheduleWirelessReconnect.replace(Regex("\\s+"), "")

        assertTrue(
            "Wireless retry scheduler must clamp the coordinator-selected delay before storing it",
            compactScheduler.contains("valdelayMs=suggestedDelayMs.coerceIn(1L,WIRELESS_RECONNECT_MAXIMUM_DELAY_MS)"),
        )
        assertTrue(
            "Wireless retry scheduler must keep the selected delay if retry becomes eligible while backgrounded",
            compactScheduler.contains("if(!isInForeground){pendingAutomaticReconnectDelayMs=delayMsreturn}"),
        )
        assertTrue(
            "Foreground start must use the pending coordinator-selected delay",
            onStart.contains("pendingAutomaticReconnectDelayMs?.let(::scheduleWirelessReconnect)"),
        )
    }

    @Test
    fun automaticUsbRetryClampsSuggestedDelayToBackoffBudget() {
        val scheduleAutomaticUsbConnect = extractMethod(mainActivitySource(), "private fun scheduleAutomaticUsbConnect")
        val compact = scheduleAutomaticUsbConnect.replace(Regex("\\s+"), "")

        assertTrue(
            "USB retry scheduler must clamp any suggested delay into the reconnect backoff budget",
            compact.contains("delayMs.coerceIn(1L,ReconnectBackoff.MAXIMUM_DELAY_MS)"),
        )
        assertTrue(
            "USB retry scheduler must post the clamped delay",
            compact.contains("postDelayed(autoConnectRunnable,boundedDelayMs)"),
        )
        assertFalse(
            "USB retry scheduler must not post raw unbounded delays",
            compact.contains("postDelayed(autoConnectRunnable,delayMs)"),
        )
    }

    @Test
    fun automaticUsbLaunchCleansExistingModeSessionBeforePersistingUsbMode() {
        val source = mainActivitySource()
        val enableAutomaticUsbConnect = extractMethod(source, "private fun enableAutomaticUsbConnect")
        val showUsbWithoutAutomaticConnect = extractMethod(source, "private fun showUsbWithoutAutomaticConnect")
        val cleanup = extractMethod(source, "private fun cleanupCurrentSessionBeforeUsbLaunch")

        assertTrue(
            "Automatic USB launch cleanup must reuse the explicit mode-switch cleanup path",
            cleanup.contains("cancelConnectionForModeSwitch()"),
        )
        assertTrue(
            "Automatic USB launch cleanup must keep existing USB sessions instead of tearing them down unconditionally",
            cleanup.replace(Regex("\\s+"), "")
                .contains("if(prefs.connectionMode!=ConnectionMode.USB){cancelConnectionForModeSwitch()}"),
        )
        assertCleanupBeforeUsbModePersistence(enableAutomaticUsbConnect, "enableAutomaticUsbConnect")
        assertCleanupBeforeUsbModePersistence(showUsbWithoutAutomaticConnect, "showUsbWithoutAutomaticConnect")
    }

    @Test
    fun scheduledUsbReconnectShowsSpinnerWhileIdleAndTerminalModesHideIt() {
        val updateDisconnectedHeader = extractMethod(mainActivitySource(), "private fun updateDisconnectedHeader")
        val usbBranch = extractWhenBranch(updateDisconnectedHeader, "ConnectionMode.USB ->")
        val wirelessBranch = extractWhenBranch(updateDisconnectedHeader, "ConnectionMode.WIRELESS ->")
        val internetBranch = extractWhenBranch(updateDisconnectedHeader, "ConnectionMode.INTERNET ->")
        val compactUsb = usbBranch.replace(Regex("\\s+"), "")

        assertTrue(
            "Scheduled USB reconnect should show the header spinner before the connection attempt starts",
            compactUsb.contains("if(connectionAttemptInProgress||isReconnecting)View.VISIBLEelseView.GONE"),
        )
        assertTrue(
            "Wireless idle and terminal guidance should hide the USB header spinner",
            wirelessBranch.contains("binding.connectionProgress.visibility = View.GONE"),
        )
        assertTrue(
            "Internet idle and terminal guidance should hide the USB header spinner",
            internetBranch.contains("binding.connectionProgress.visibility = View.GONE"),
        )
    }

    @Test
    fun automaticUsbChecklistUsesTerminalGuidanceStatusInsteadOfHardcodedChecking() {
        val updateChecklist = extractMethod(mainActivitySource(), "private fun updateChecklist")
        val automaticBranch = extractBlockAfterMarker(updateChecklist, "if (automaticUsbConnect || connectionAttemptInProgress)")
        val compactBranch = automaticBranch.replace(Regex("\\s+"), "")

        assertTrue(
            "Automatic USB checklist must stop showing Mac server as Checking after terminal guidance is visible",
            compactBranch.contains("MacServerChecklistStatusPolicy.waitingStatus("),
        )
        assertFalse(
            "Automatic USB checklist must not hard-code the Mac server row to Checking",
            compactBranch.contains("R.string.mac_server,ChecklistStatus.CHECKING"),
        )
    }

    @Test
    fun terminalGuidanceUsesModeSpecificInlineSurfaces() {
        val presenter = extractMethod(mainActivitySource(), "private fun showTerminalConnectionGuidance")
        val compact = presenter.replace(Regex("\\s+"), "")

        assertTrue(
            "Terminal guidance must branch on the current connection mode",
            compact.contains("when(mode)"),
        )
        assertTrue(
            "USB terminal guidance should use the USB recovery panel",
            compact.contains("ConnectionMode.USB->showUsbConnectionGuidance(guidance)"),
        )
        assertTrue(
            "LAN terminal guidance should stay inside the Wireless tab repair surface",
            compact.contains("wirelessController.showConnectionGuidance(guidance)"),
        )
        assertTrue(
            "Internet terminal guidance should stay inside the Internet tab error surface",
            compact.contains("LiveRegionTextApplier.show(binding.internetErrorText,"),
        )
        assertTrue(
            "Internet terminal guidance should use localized guidance text",
            compact.contains("guidanceFullMessage(guidance)"),
        )
        assertFalse(
            "The non-USB branch must not show the USB-specific inline panel",
            compact.contains("else{showUsbConnectionGuidance(guidance)}"),
        )
        assertFalse(
            "Terminal guidance should not fall back to a blocking dialog",
            compact.contains("showError(guidance.message)"),
        )
        assertFalse(
            "Terminal guidance should not fall back to a localized blocking dialog",
            compact.contains("showError(guidanceMessage(guidance))"),
        )
    }

    @Test
    fun inlineUsbGuidanceExpandsChecklistForRecovery() {
        val source = mainActivitySource()
        val setupUi = extractMethod(source, "private fun setupUI")
        val inlineGuidance = extractMethod(source, "private fun showUsbConnectionGuidance")
        val clearGuidance = extractMethod(source, "private fun clearUsbConnectionGuidance")
        val updateMainStatus = extractMethod(source, "private fun updateMainStatus")
        val compactUpdateMainStatus = updateMainStatus.replace(Regex("\\s+"), "")

        assertFalse(
            "USB validation guidance must use string resources instead of hardcoded text",
            setupUi.contains("Please enter a host address"),
        )
        assertTrue(
            "USB validation guidance must load its message from strings.xml",
            setupUi.contains("ConnectionGuidanceText(R.string.host_address_required)"),
        )
        assertUsesLiveRegion(inlineGuidance, "connectionErrorTitle", "showUsbConnectionGuidance")
        assertUsesLiveRegionShow(inlineGuidance, "connectionErrorMessage", "showUsbConnectionGuidance")
        assertTrue(inlineGuidance.contains("guidanceStatus(guidance)"))
        assertTrue(inlineGuidance.contains("guidanceMessage(guidance)"))
        assertTrue(
            "Inline USB guidance should expand details so the failed checklist item is visible",
            inlineGuidance.contains("setConnectionDetailsVisible(true)"),
        )
        assertTrue(
            "Inline USB guidance should make the primary status indicator visibly fail",
            inlineGuidance.contains("binding.statusIndicator.setBackgroundResource(R.drawable.status_indicator_red)"),
        )
        assertTrue(
            "Checklist refreshes must preserve the red status indicator while inline USB guidance is visible",
            compactUpdateMainStatus.contains(
                "if(binding.connectionErrorContainer.visibility==View.VISIBLE){" +
                    "binding.statusIndicator.setBackgroundResource(R.drawable.status_indicator_red)return}",
            ),
        )
        assertTrue(
            "Clearing USB guidance should return the indicator to the neutral waiting state",
            clearGuidance.contains("binding.statusIndicator.setBackgroundResource(R.drawable.status_indicator_waiting)"),
        )
    }

    @Test
    fun showErrorUsesMaterialDialogImmersiveModeAndResources() {
        val showError = extractMethod(mainActivitySource(), "private fun showError")

        assertTrue(showError.contains("showImmersiveDialog("))
        assertTrue(showError.contains("MaterialAlertDialogBuilder(this)"))
        assertTrue(showError.contains("R.string.connection_error_title"))
        assertTrue(showError.contains("android.R.string.ok"))
        assertFalse(showError.contains("android.app.AlertDialog"))
        assertFalse(showError.contains("Connection Error"))
        assertFalse(showError.contains("\"OK\""))
    }

    @Test
    fun internetFailuresUseLocalizedGuidanceAndStateLabels() {
        val source = mainActivitySource()
        val updateInternetState = extractMethod(source, "private fun updateInternetState")
        val internetStateLabel = extractMethod(source, "private fun internetStateLabel")
        val showInternetFailure = extractMethod(source, "private fun showInternetFailure")

        assertFalse(updateInternetState.contains("state.name.lowercase()"))
        assertTrue(updateInternetState.contains("internetStateLabel(state)"))
        assertTrue(showInternetFailure.contains("guidanceFullMessage(guidance)"))
        assertTrue(showInternetFailure.contains("internetStateLabel(InternetProductSessionState.FAILED)"))
        listOf(
            "R.string.internet_state_label_idle",
            "R.string.internet_state_label_connecting",
            "R.string.internet_state_label_negotiating",
            "R.string.internet_state_label_active",
            "R.string.internet_state_label_recovering",
            "R.string.internet_state_label_suspended",
            "R.string.internet_state_label_failed",
            "R.string.internet_state_label_closed",
        ).forEach { labelResource ->
            assertTrue("Missing $labelResource", internetStateLabel.contains(labelResource))
        }
    }

    @Test
    fun disconnectedStreamUiKeepsSettingsReachableWithoutSmallScreenOcclusion() {
        val source = mainActivitySource()
        val disconnected = extractMethod(source, "private fun showDisconnectedStreamUi")
        val entryPolicy = extractMethod(source, "private fun applyDisconnectedSettingsEntryPolicy")
        val configurationChanged = extractMethod(source, "override fun onConfigurationChanged")
        val compactEntryPolicy = entryPolicy.replace(Regex("\\s+"), "")
        val removedInlineSettingsFlag = "connection_panel_inline_settings_" + "button"
        val removedFloatingSettingsBinding = "binding." + "settings" + "Button"

        assertTrue(
            "Disconnected state should keep settings visible in the active mode main flow",
            compactEntryPolicy.contains("valinternetMode=prefs.connectionMode==ConnectionMode.INTERNET") &&
                compactEntryPolicy.contains("binding.connectionSettingsButton.visibility=if(internetMode)View.GONEelseView.VISIBLE") &&
                compactEntryPolicy.contains("binding.internetConnectionSettingsButton.visibility=if(internetMode)View.VISIBLEelseView.GONE"),
        )
        assertFalse(
            "Disconnected settings entry policy should no longer branch through resource flags",
            entryPolicy.contains(removedInlineSettingsFlag) ||
                entryPolicy.contains("resources.getBoolean"),
        )
        assertFalse(
            "Disconnected settings entry policy should not reference the removed floating settings affordance",
            entryPolicy.contains(removedFloatingSettingsBinding),
        )
        assertTrue(
            "Disconnected entry policy must apply when the disconnected panel is first shown",
            disconnected.contains("applyDisconnectedSettingsEntryPolicy()"),
        )
        assertTrue(
            "Configuration changes must re-expose the inline settings entry while disconnected",
            configurationChanged.contains("if (!isConnected)") &&
                configurationChanged.contains("applyDisconnectedSettingsEntryPolicy()"),
        )
    }

    @Test
    fun wideDisconnectedLayoutsKeepSettingsInlineSoRetryActionsAreUncovered() {
        listOf(
            "app/src/main/res/values-w600dp/bools.xml",
            "app/src/main/res/values-w600dp-land/bools.xml",
        ).forEach { path ->
            val source = resourceSource(path)

            assertTrue(
                "$path should still opt into the wide two-column connection panel",
                source.contains("""<bool name="connection_panel_two_column">true</bool>"""),
            )
        }
        listOf(
            "app/src/main/res/values/bools.xml",
            "app/src/main/res/values-land/bools.xml",
            "app/src/main/res/values-w600dp/bools.xml",
            "app/src/main/res/values-w600dp-land/bools.xml",
        ).forEach { path ->
            val removedInlineSettingsFlag = "connection_panel_inline_settings_" + "button"
            assertFalse(
                "$path should not keep the removed inline-settings feature flag",
                resourceSource(path).contains(removedInlineSettingsFlag),
            )
        }
    }

    @Test
    fun wideLandscapeConnectionPanelUsesCompactVerticalMargins() {
        val source = resourceSource("app/src/main/res/values-w600dp-land/dimens.xml")

        assertTrue(
            "Wide landscape has limited vertical space, so its connection panel margins must not inherit the taller wide-portrait value",
            source.contains("""<dimen name="connection_panel_margin_vertical">12dp</dimen>"""),
        )
    }

    @Test
    fun wideLandscapeHeaderUsesCompactVerticalSpacing() {
        val source = resourceSource("app/src/main/res/values-w600dp-land/dimens.xml")

        assertTrue(
            "Wide landscape large-text captures need a shorter header so the left column does not crop its guidance copy",
            source.contains("""<dimen name="connection_icon_size">48dp</dimen>""") &&
                source.contains("""<dimen name="connection_icon_margin_bottom">8dp</dimen>""") &&
                source.contains("""<dimen name="connection_wordmark_margin_bottom">4dp</dimen>""") &&
                source.contains("""<dimen name="connection_subtitle_margin_bottom">4dp</dimen>"""),
        )
    }

    @Test
    fun inlineDisconnectedSettingsButtonExposesAccessibleClickTarget() {
        val source = mainActivityLayoutSource()
        val inlineSettingsButton = extractXmlElement(source, "android:id=\"@+id/connectionSettingsButton\"")
        val internetSettingsButton = extractXmlElement(source, "android:id=\"@+id/internetConnectionSettingsButton\"")
        val removedFloatingSettingsId = "android:id=\"@+id/" + "settings" + "Button\""

        assertFalse(
            "Disconnected settings must not keep a duplicate floating entry",
            source.contains(removedFloatingSettingsId),
        )
        assertTrue(
            "The inline settings button needs the accessible label",
            inlineSettingsButton.contains("android:contentDescription=\"@string/display_settings\""),
        )
        assertTrue(
            "The inline settings button should expose visible settings text",
            inlineSettingsButton.contains("android:text=\"@string/display_settings\""),
        )
        assertTrue(
            "The inline settings button should keep the expected settings icon",
            inlineSettingsButton.contains("app:icon=\"@drawable/ic_settings\""),
        )
        assertTrue(
            "Internet needs its own inline settings target before the legal footer",
            internetSettingsButton.contains("android:contentDescription=\"@string/display_settings\"") &&
                internetSettingsButton.contains("android:text=\"@string/display_settings\"") &&
                internetSettingsButton.contains("app:icon=\"@drawable/ic_settings\""),
        )
        assertTrue(
            "Internet settings must keep the 48dp touch target minimum while sharing the secondary action row",
            internetSettingsButton.contains("android:minHeight=\"48dp\"") &&
                internetSettingsButton.contains("android:layout_height=\"wrap_content\"") &&
                internetSettingsButton.contains("android:maxLines=\"2\""),
        )
    }

    @Test
    fun internetDisconnectedFlowKeepsStatusAndSecondaryActionsBeforeLegalFooter() {
        val source = mainActivityLayoutSource()
        val internetMode = source.substring(
            source.indexOf("android:id=\"@+id/internetModeContent\""),
            source.indexOf("<!-- ============= /INTERNET MODE CONTENT ============= -->"),
        )
        val profileIndex = internetMode.indexOf("android:id=\"@+id/internetProfileSummary\"")
        val stateIndex = internetMode.indexOf("android:id=\"@+id/internetStateText\"")
        val routeIndex = internetMode.indexOf("android:id=\"@+id/internetRouteToggleGroup\"")
        val scanIndex = internetMode.indexOf("android:id=\"@+id/internetScanProfileButton\"")
        val importIndex = internetMode.indexOf("android:id=\"@+id/internetImportProfileButton\"")
        val connectIndex = internetMode.indexOf("android:id=\"@+id/internetConnectButton\"")
        val settingsIndex = internetMode.indexOf("android:id=\"@+id/internetConnectionSettingsButton\"")
        val revokeIndex = internetMode.indexOf("android:id=\"@+id/internetRevokeButton\"")
        val errorIndex = internetMode.indexOf("android:id=\"@+id/internetErrorText\"")
        val footerIndex = source.indexOf("android:id=\"@+id/connectionLegalFooter\"")
        val internetModeIndex = source.indexOf("android:id=\"@+id/internetModeContent\"")

        assertTrue("Internet profile summary should be present", profileIndex >= 0)
        assertTrue("Internet state should be present", stateIndex >= 0)
        assertTrue("Internet route policy should be present", routeIndex >= 0)
        assertTrue("Internet scan/import actions should be present", scanIndex >= 0 && importIndex >= 0)
        assertTrue("Internet connect action should be present", connectIndex >= 0)
        assertTrue("Internet settings and revoke actions should be present", settingsIndex >= 0 && revokeIndex >= 0)
        assertTrue("Internet error region should remain reachable after actions", errorIndex >= 0)
        assertTrue(
            "Internet status must appear before route and connect controls so idle/failed state is visible without scrolling past actions",
            profileIndex < stateIndex && stateIndex < routeIndex && routeIndex < scanIndex &&
                scanIndex < importIndex && importIndex < connectIndex && connectIndex < settingsIndex &&
                settingsIndex < revokeIndex && revokeIndex < errorIndex,
        )
        assertTrue(
            "Legal attribution belongs after the connection actions, not inside the Internet primary flow",
            footerIndex > internetModeIndex,
        )
    }

    @Test
    fun internetSecondaryActionsShareCompactAccessibleRow() {
        val source = mainActivityLayoutSource()
        val row = source.substring(
            source.indexOf("android:id=\"@+id/internetSecondaryActions\""),
            source.indexOf("android:id=\"@+id/internetErrorText\""),
        )
        val settingsIndex = row.indexOf("android:id=\"@+id/internetConnectionSettingsButton\"")
        val disconnectIndex = row.indexOf("android:id=\"@+id/internetDisconnectButton\"")
        val revokeIndex = row.indexOf("android:id=\"@+id/internetRevokeButton\"")

        assertTrue("Internet secondary actions should render in one compact row", row.contains("android:orientation=\"horizontal\""))
        assertTrue("Settings, disconnect, and revoke should share the same row order", settingsIndex >= 0 && settingsIndex < disconnectIndex && disconnectIndex < revokeIndex)
        listOf("internetConnectionSettingsButton", "internetDisconnectButton", "internetRevokeButton").forEach { id ->
            val button = extractXmlElement(row, "android:id=\"@+id/$id\"")
            assertTrue(
                "$id should stay responsive in the secondary row",
                button.contains("android:layout_width=\"0dp\"") &&
                    button.contains("android:layout_weight=\"1\"") &&
                    button.contains("android:minHeight=\"48dp\"") &&
                    button.contains("android:maxLines=\"2\"") &&
                    button.contains("android:paddingStart=\"4dp\"") &&
                    button.contains("android:paddingEnd=\"4dp\"") &&
                    button.contains("app:autoSizeTextType=\"uniform\"") &&
                    button.contains("app:autoSizeMinTextSize=\"10sp\"") &&
                    button.contains("app:autoSizeMaxTextSize=\"14sp\""),
            )
        }
    }

    @Test
    fun openSourceAttributionRemainsReachableWithoutOccupyingPrimaryCopySpace() {
        val source = mainActivityLayoutSource()
        val footer = source.substring(
            source.indexOf("android:id=\"@+id/connectionLegalFooter\""),
            source.indexOf("<!-- /connectionActions -->"),
        )
        val openSourceButton = extractXmlElement(footer, "android:id=\"@+id/openSourceLicensesButton\"")
        val strings = resourceSource("app/src/main/res/values/strings.xml")
        val buildScript = resourceSource("app/build.gradle.kts")
        val noticeDialog = extractMethod(mainActivitySource(), "private fun showOpenSourceNotices")

        assertTrue(
            "The legal footer should be constrained by the connection panel width so the summary can wrap at large font scales",
            footer.contains("android:layout_width=\"match_parent\""),
        )
        assertFalse(
            "The long upstream URL should not occupy the disconnected primary flow; complete attribution lives in packaged notices",
            footer.contains("@string/fork_credit"),
        )
        assertTrue(
            "The footer still needs a visible attribution summary",
            footer.contains("@string/open_source_notices_summary") &&
                strings.contains("Source attribution and dependency terms are in notices."),
        )
        assertTrue(
            "The notices entry must remain a 48dp accessible tap target",
            openSourceButton.contains("android:layout_height=\"48dp\"") &&
                openSourceButton.contains("android:contentDescription=\"@string/open_source_licenses_description\""),
        )
        assertTrue(
            "Packaged notices must include the project NOTICE and generated runtime dependency license report",
            buildScript.contains("include(\"LICENSE\", \"NOTICE\", \"licenses/Apache-2.0.txt\")") &&
                buildScript.contains("ANDROID_RUNTIME_DEPENDENCY_LICENSES.md"),
        )
        assertTrue(
            "The dialog should show complete packaged upstream and dependency notices",
            noticeDialog.contains("assets.open(UPSTREAM_NOTICE_ASSET)") &&
                noticeDialog.contains("assets.open(DEPENDENCY_LICENSES_ASSET)") &&
                noticeDialog.contains("setTitle(R.string.open_source_notices_title)"),
        )
    }

    @Test
    fun connectionDetailsLinkIsKeyboardFocusable() {
        val connectionDetails = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/showAdvanced\"")

        assertTrue(
            "Connection details expands inline recovery guidance, so keyboard and D-pad users need a focus target",
            connectionDetails.contains("android:focusable=\"true\""),
        )
        assertTrue(
            "Connection details should remain reachable when navigating with hardware keyboard focus",
            connectionDetails.contains("android:focusableInTouchMode=\"true\""),
        )
        assertTrue(
            "Connection details should keep the 48dp touch target minimum",
            connectionDetails.contains("android:minHeight=\"48dp\""),
        )
        assertTrue(
            "Connection details needs a visible keyboard and D-pad focus indicator",
            connectionDetails.contains("android:background=\"?attr/selectableItemBackgroundBorderless\""),
        )
    }

    @Test
    fun internetDisconnectButtonCanGrowForLargeFontLabels() {
        val disconnectButton = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/internetDisconnectButton\"")

        assertTrue(
            "Internet disconnect copy may wrap at large font scale, so height must not be fixed",
            disconnectButton.contains("android:layout_height=\"wrap_content\""),
        )
        assertTrue(
            "Internet disconnect button still needs the 48dp touch target minimum",
            disconnectButton.contains("android:minHeight=\"48dp\""),
        )
        assertTrue(
            "Internet disconnect copy should be allowed to use a second line instead of clipping",
            disconnectButton.contains("android:maxLines=\"2\""),
        )
    }

    @Test
    fun internetRevokeButtonCanGrowForLargeFontLabels() {
        val revokeButton = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/internetRevokeButton\"")

        assertTrue(
            "Internet revoke copy is long enough to wrap at large font scale, so height must not be fixed",
            revokeButton.contains("android:layout_height=\"wrap_content\""),
        )
        assertTrue(
            "Internet revoke button still needs the 48dp touch target minimum",
            revokeButton.contains("android:minHeight=\"48dp\""),
        )
        assertTrue(
            "Internet revoke copy should be allowed to use a second line instead of clipping",
            revokeButton.contains("android:maxLines=\"2\""),
        )
    }

    @Test
    fun internetRoutePolicyToggleKeepsAccessibleTouchTargets() {
        listOf("internetPreferDirect", "internetForceRelay").forEach { id ->
            val button = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/$id\"")

            assertTrue(
                "$id should keep the 48dp touch target minimum",
                button.contains("android:minHeight=\"48dp\""),
            )
        }
    }

    @Test
    fun wirelessSecondaryActionsKeepAccessibleTouchTargets() {
        listOf("wirelessDisconnectButton", "wirelessForgetButton", "wirelessIdleForgetButton").forEach { id ->
            val button = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/$id\"")

            assertTrue(
                "$id should keep the 48dp touch target minimum",
                button.contains("android:minHeight=\"48dp\""),
            )
        }
    }

    @Test
    fun internetDisconnectedTitleUsesCompactPreviewCopy() {
        val titleResolver = extractMethod(mainActivitySource(), "private fun internetWaitingTitleResource")

        assertTrue(
            "Internet disconnected title should use the compact preview copy on phones so primary actions stay discoverable",
            titleResolver.contains("R.string.internet_waiting_title_compact"),
        )
        assertFalse(
            "The longer development-preview title should not be selected at runtime for the disconnected card",
            titleResolver.contains("R.string.internet_waiting_title\n") ||
                titleResolver.contains("R.string.internet_waiting_title }"),
        )
    }

    @Test
    fun connectionPanelOuterGeometryUsesResponsiveResources() {
        val settingsPanel = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/settingsPanel\"")
        val connectionContent = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/connectionContent\"")

        assertTrue(
            "Connection panel horizontal margin should adapt by resource qualifier",
            settingsPanel.contains("android:layout_marginStart=\"@dimen/connection_panel_margin_horizontal\"") &&
                settingsPanel.contains("android:layout_marginEnd=\"@dimen/connection_panel_margin_horizontal\""),
        )
        assertTrue(
            "Connection panel vertical margin should adapt by resource qualifier",
            settingsPanel.contains("android:layout_marginTop=\"@dimen/connection_panel_margin_vertical\"") &&
                settingsPanel.contains("android:layout_marginBottom=\"@dimen/connection_panel_margin_vertical\""),
        )
        assertTrue(
            "Connection panel max width should follow phone/tablet resource qualifiers",
            settingsPanel.contains("app:layout_constraintWidth_max=\"@dimen/connection_panel_max_width\""),
        )
        assertFalse(
            "Connection panel must not keep the old hard-coded 680dp cap",
            settingsPanel.contains("layout_constraintWidth_max=\"680dp\""),
        )
        assertTrue(
            "Horizontal connection layouts must not baseline-align the header against the actions column",
            connectionContent.contains("android:baselineAligned=\"false\""),
        )
    }

    @Test
    fun statusOverlaySecurityTextCanWrapLongLinkState() {
        val securityText = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/securityText\"")

        assertTrue(
            "Link/security copy can be long in transport error states, so it needs a second line",
            securityText.contains("android:maxLines=\"2\""),
        )
        assertFalse(
            "Link/security copy must not be forced through single-line ellipsizing",
            securityText.contains("android:ellipsize=\"end\"") ||
                securityText.contains("android:maxLines=\"1\""),
        )
    }

    @Test
    fun modeToggleButtonsCanWrapWithoutForcedTwoLineHeight() {
        listOf("modeUSB", "modeWireless", "modeInternet").forEach { id ->
            val button = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/$id\"")

            assertTrue(
                "$id should allow labels to use a second line when needed",
                button.contains("android:maxLines=\"2\""),
            )
            assertTrue(
                "$id must retain the 48dp Material touch target minimum",
                button.contains("android:minHeight=\"48dp\""),
            )
            assertFalse(
                "$id must not force every label to occupy two text lines",
                button.contains("android:lines="),
            )
            assertTrue(
                "$id should keep logical padding for RTL-safe layout",
                button.contains("android:paddingStart=\"2dp\"") &&
                    button.contains("android:paddingEnd=\"2dp\""),
            )
            assertTrue(
                "$id must zero physical Material padding so compact labels are not ellipsized",
                button.contains("android:paddingLeft=\"0dp\"") &&
                    button.contains("android:paddingRight=\"0dp\""),
            )
            assertTrue(
                "$id must not reserve selected-icon space that can truncate short labels",
                button.contains("app:icon=\"@null\"") && button.contains("app:iconSize=\"0dp\""),
            )
            assertTrue(
                "$id must disable Material all-caps transformation",
                button.contains("app:textAllCaps=\"false\""),
            )
            assertTrue(
                "$id must keep natural letter spacing so short labels do not exceed their segment",
                button.contains("android:letterSpacing=\"0\""),
            )
        }
    }

    @Test
    fun modeToggleSegmentsUseEqualResponsiveWidths() {
        listOf("modeUSB", "modeWireless", "modeInternet").forEach { id ->
            val button = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/$id\"")

            assertTrue(
                "$id should participate in the toggle row as an equal-width responsive segment",
                button.contains("android:layout_width=\"0dp\"") &&
                    button.contains("android:layout_weight=\"1\""),
            )
        }
    }

    @Test
    fun usbRetryActionStaysAheadOfDiagnosticDetails() {
        val source = mainActivityLayoutSource()
        val usbIndex = source.indexOf("android:id=\"@+id/usbModeContent\"")
        val errorIndex = source.indexOf("android:id=\"@+id/connectionErrorContainer\"")
        val connectIndex = source.indexOf("android:id=\"@+id/connectButton\"")
        val statusIndex = source.indexOf("android:id=\"@+id/statusIndicator\"")
        val checklistIndex = source.indexOf("android:id=\"@+id/checklistContainer\"")

        assertTrue("USB mode content should be present", usbIndex >= 0)
        assertTrue("USB content should keep the inline error details available", errorIndex >= 0)
        assertTrue("USB content should include the primary retry/connect action", connectIndex >= 0)
        assertTrue("USB content should include the compact route status after the action", statusIndex >= 0)
        assertTrue("USB content should include diagnostic checklist details", checklistIndex >= 0)
        assertTrue(
            "The retry/connect action must appear before long diagnostic details so it remains reachable at large font scale",
            usbIndex < connectIndex && connectIndex < errorIndex && errorIndex < statusIndex && statusIndex < checklistIndex,
        )

        val connectButton = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/connectButton\"")
        assertTrue(
            "TRY AGAIN may wrap at large font scale, so the primary USB action must grow vertically",
            connectButton.contains("android:layout_height=\"wrap_content\"") &&
                connectButton.contains("android:minHeight=\"56dp\"") &&
                connectButton.contains("android:maxLines=\"2\""),
        )
    }

    @Test
    fun compactLayoutPressureKeepsGuidanceCompleteAndPrioritizesTheRetryAction() {
        val source = mainActivitySource()
        val applier =
            resourceSource("app/src/main/java/dev/telemachus/display/ConnectionPanelLayoutApplier.kt")
                .replace(Regex("\\s+"), "")
        val disclosurePolicy =
            resourceSource("app/src/main/java/dev/telemachus/display/ConnectionSubtitleDisclosurePolicy.kt")
                .replace(Regex("\\s+"), "")
        val connectionScroll = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/connectionScroll\"")
        val errorMessage = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/connectionErrorMessage\"")

        assertFalse(
            "Compact landscape must not hide USB recovery steps by capping the error message",
            applier.contains("applyErrorMessageDensity") ||
                applier.contains("views.errorMessage") ||
                source.contains("errorMessage = binding.connectionErrorMessage"),
        )
        assertFalse(
            "Security and recovery guidance must not become a non-expandable ellipsized preview",
            disclosurePolicy.contains("COMPACT_MAX_LINES") ||
                disclosurePolicy.contains("ellipsizeEnd=compact"),
        )
        assertTrue(
            "Full diagnostic text must remain in normal wrap-content layout so TalkBack and scrolling can access it",
            errorMessage.contains("android:layout_height=\"wrap_content\"") &&
                !errorMessage.contains("android:maxLines") &&
                !errorMessage.contains("android:ellipsize"),
        )
        assertFalse(
            "The scroll view must not fill the viewport because that can remeasure tall two-column content to the card height and clip controls",
            connectionScroll.contains("android:fillViewport=\"true\""),
        )
    }

    @Test
    fun overlayOpacityOnlyDimsTheStatsOverlay() {
        val source = mainActivitySource()
        val restoreOverlayPosition = extractMethod(source, "private fun restoreOverlayPosition")
        val updateOverlayOpacity = extractMethod(source, "private fun updateOverlayOpacity")
        val showSettingsDialog = extractMethod(source, "private fun showSettingsDialog")
        val opacitySliderListener =
            showSettingsDialog.substring(
                showSettingsDialog.indexOf("opacitySlider.addOnChangeListener"),
                showSettingsDialog.indexOf("scaleFitButton.setOnClickListener"),
            )

        assertTrue(
            "Saved overlay opacity should still apply to the stats overlay",
            restoreOverlayPosition.contains("updateOverlayOpacity(prefs.overlayOpacity)"),
        )
        assertTrue(
            "Changing overlay opacity from Settings should still update the stats overlay",
            opacitySliderListener.contains("updateOverlayOpacity(value)"),
        )
        assertTrue(
            "Overlay opacity must target only the stream stats overlay",
            updateOverlayOpacity.contains("binding.statusBar.alpha = opacity"),
        )
        assertFalse(
            "Overlay opacity must not target the disconnected inline settings entry",
            updateOverlayOpacity.contains("connectionSettingsButton"),
        )
        assertFalse(
            "Restoring overlay state must not dim the disconnected inline settings entry",
            restoreOverlayPosition.contains("connectionSettingsButton") ||
                restoreOverlayPosition.contains("updateSettingsButtonOpacity"),
        )
        assertFalse(
            "Changing overlay opacity from Settings must not dim the disconnected inline settings entry",
            opacitySliderListener.contains("connectionSettingsButton") ||
                opacitySliderListener.contains("updateSettingsButtonOpacity"),
        )
        assertFalse(
            "No settings-button opacity helper should re-bind the affordance to overlay opacity",
            source.contains("private fun updateSettingsButtonOpacity"),
        )
    }

    @Test
    fun connectedStreamUiUsesLongInitialControlBarReveal() {
        val source = mainActivitySource()
        val connected = extractMethod(source, "private fun showConnectedStreamUi")
        val reveal = extractMethod(source, "private fun revealControlBar")
        val securityStatus = extractMethod(source, "private fun updateConnectionSecurityStatus")
        val compactConnected = connected.replace(Regex("\\s+"), "")
        val compactReveal = reveal.replace(Regex("\\s+"), "")
        val compactSecurity = securityStatus.replace(Regex("\\s+"), "")

        assertTrue(
            "Newly connected sessions should leave controls visible long enough to find settings and disconnect",
            compactConnected.contains(
                "revealControlBar(ControlBarAccessibilityPolicy.RevealReason.SESSION_STARTED)",
            ),
        )
        assertTrue(
            "Manual reveals should keep the standard reveal reason by default",
            compactReveal.contains(
                "revealReason:ControlBarAccessibilityPolicy.RevealReason=" +
                    "ControlBarAccessibilityPolicy.RevealReason.USER_REQUEST",
            ),
        )
        assertTrue(
            "Control-bar hide timing should be resolved by the shared accessibility policy",
            compactReveal.contains("ControlBarAccessibilityPolicy.autoHideDelayMs("),
        )
        assertTrue(
            "Streaming UI should update the connection/security indicator before revealing controls",
            compactConnected.contains("updateConnectionSecurityStatus()"),
        )
        assertTrue(
            "The stats overlay should carry the same connection/security state as the control bar",
            compactSecurity.contains("binding.securityText.text=getString(R.string.stream_status_overlay_format,label,detail)"),
        )
        assertTrue(
            "Streaming UI should render the negotiated LAN record protection state when available",
            securityStatus.contains("streamClient?.currentLanProtectionState"),
        )
        assertTrue(
            "Streaming UI should send the LAN protection state to the shared presentation policy",
            compactSecurity.contains("lanProtectionState=lanProtectionState"),
        )
    }

    @Test
    fun controlMenusAnchorToTheirFullTouchTargets() {
        val source = mainActivitySource()
        val displaysMenu = extractMethod(source, "private fun showDisplaysMenu")
        val hostActionsMenu = extractMethod(source, "private fun showHostActionsMenu")
        val clipboardMenu = extractMethod(source, "private fun showClipboardMenu")
        val popupPresenter = extractMethod(source, "private fun showControlPopupMenu")
        val compactPresenter = popupPresenter.replace(Regex("\\s+"), "")

        assertTrue(
            "The display menu should anchor to the whole selector row, matching its actual tap target",
            displaysMenu.contains("PopupMenu(this, binding.displayCapsuleGroup)"),
        )
        assertFalse(
            "The display menu must not anchor to the small icon inside the selector",
            displaysMenu.contains("PopupMenu(this, binding.controlDisplaysButton)"),
        )
        assertTrue(displaysMenu.contains("showDisplayPopupMenu(popup, binding.displayCapsuleGroup)"))
        assertTrue(displaysMenu.contains("DisplayMenuSelectionGuard.acceptsSelection"))
        assertTrue(displaysMenu.contains("DISPLAY_MENU_SELECTION_GUARD_MS"))
        assertFalse(displaysMenu.contains("showControlPopupMenu(popup, binding.displayCapsuleGroup)"))
        assertTrue(hostActionsMenu.contains("showControlPopupMenu(popup, binding.controlHostActionsButton)"))
        assertTrue(clipboardMenu.contains("showControlPopupMenu(popup, binding.controlClipboardButton)"))
        assertTrue(compactPresenter.contains("popup.gravity=Gravity.END"))
        assertTrue(compactPresenter.contains("anchor.post{popup.show()}"))

        val displayPopupPresenter = extractMethod(source, "private fun showDisplayPopupMenu")
        val compactDisplayPresenter = displayPopupPresenter.replace(Regex("\\s+"), "")
        assertTrue(compactDisplayPresenter.contains("popup.show()onShown(SystemClock.uptimeMillis())"))
        assertTrue(compactDisplayPresenter.contains("DISPLAY_MENU_SHOW_DELAY_MS"))
    }

    @Test
    fun displaySelectionMenuDoesNotOptimisticallyRelabelTheActiveDisplay() {
        val displaysMenu = extractMethod(mainActivitySource(), "private fun showDisplaysMenu")
        val clickHandler = extractCallback(displaysMenu, "popup.setOnMenuItemClickListener { item ->")

        assertTrue(
            "Selecting a menu item must still request the host-side switch",
            clickHandler.contains("streamClient?.selectDisplay(option.id)"),
        )
        assertTrue(
            "Selecting a menu item should surface pending UI only after the request is accepted for sending",
            clickHandler.contains("markDisplaySelectionPending(previousDisplayId, option.id)"),
        )
        assertFalse(
            "The capsule label must wait for the confirmed Host display state",
            clickHandler.contains("selectedDisplayId = option.id"),
        )
    }

    @Test
    fun lanClipboardPromptsUseNegotiatedProtectionState() {
        val source = mainActivitySource()
        val send = extractMethod(source, "private fun beginSendLocalClipboard")
        val receive = extractMethod(source, "private fun beginReceiveRemoteClipboard")
        val directReceive = extractMethod(source, "private fun showDirectClipboardConfirmation")

        assertTrue(send.contains("LanClipboardProtectionMessagePolicy.sendMessage(client.currentLanProtectionState)"))
        assertTrue(receive.contains("LanClipboardProtectionMessagePolicy.receiveMessage(client.currentLanProtectionState)"))
        assertTrue(
            directReceive.contains(
                "LanClipboardProtectionMessagePolicy.directReceiveMessage(client.currentLanProtectionState)",
            ),
        )
    }

    @Test
    fun onConfigurationChangedConnectionTitleUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val onConfigurationChanged = extractMethod(source, "override fun onConfigurationChanged")

        assertFalse(
            "onConfigurationChanged must not set connectionTitle via setText (bypasses live-region deduplication)",
            onConfigurationChanged.contains("connectionTitle.setText"),
        )
        assertUsesLiveRegion(onConfigurationChanged, "connectionTitle", "onConfigurationChanged")
    }

    @Test
    fun modeVisibilityAppliesSubtitleLayoutFromItsExplicitMode() {
        val source = mainActivitySource()
        val applyModeVisibility = extractMethod(source, "private fun applyModeVisibility")
        val applyConnectionPanelLayout = extractMethod(source, "private fun applyConnectionPanelLayout")
        val compactModeVisibility = applyModeVisibility.replace(Regex("\\s+"), "")
        val compactLayout = applyConnectionPanelLayout.replace(Regex("\\s+"), "")

        assertTrue(
            "Mode visibility must render disclosure state from the requested mode",
            compactModeVisibility.contains("applyConnectionPanelLayout(mode)"),
        )
        assertTrue(
            "Configuration-driven callers may still use the current persisted mode by default",
            compactLayout.contains("connectionMode:ConnectionMode=prefs.connectionMode"),
        )
        assertTrue(
            "The explicit layout mode must reach the disclosure applier",
            compactLayout.contains("connectionMode=connectionMode"),
        )
    }

    @Test
    fun updateDisconnectedHeaderUsesLiveRegionApplierForTitleAndSubtitle() {
        val source = mainActivitySource()
        val updateHeader = extractMethod(source, "private fun updateDisconnectedHeader")

        assertFalse(
            "updateDisconnectedHeader must not set connectionTitle via setText",
            updateHeader.contains("connectionTitle.setText"),
        )
        assertFalse(
            "updateDisconnectedHeader must not set connectionSubtitle via setText",
            updateHeader.contains("connectionSubtitle.setText"),
        )
        assertUsesLiveRegion(updateHeader, "connectionTitle", "updateDisconnectedHeader")
        assertUsesLiveRegion(updateHeader, "connectionSubtitle", "updateDisconnectedHeader")
    }

    @Test
    fun updateUsbTransportSubtitleUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val updateSubtitle = extractMethod(source, "private fun updateUsbTransportSubtitle")

        assertFalse(
            "updateUsbTransportSubtitle must not set connectionSubtitle via direct .text assignment",
            updateSubtitle.contains("connectionSubtitle.text ="),
        )
        assertUsesLiveRegion(updateSubtitle, "connectionSubtitle", "updateUsbTransportSubtitle")
    }

    @Test
    fun revocationQuarantineInternetErrorTextUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val allowMutation = extractMethod(source, "private fun allowInternetCredentialMutation")

        assertNoDirectInternetErrorTextAssignment(allowMutation, "revocation quarantine")
        assertUsesLiveRegionShow(allowMutation, "internetErrorText", "revocation quarantine")
    }

    @Test
    fun revokeInternetPairingInternetErrorTextUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val revoke = extractMethod(source, "private fun revokeInternetPairing")

        assertNoDirectInternetErrorTextAssignment(revoke, "revokeInternetPairing")
        assertUsesLiveRegionShow(revoke, "internetErrorText", "revokeInternetPairing")
    }

    @Test
    fun setupInternetUiPendingRevocationCleanupInternetErrorTextUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val setup = extractMethod(source, "private fun setupInternetUi")

        assertNoDirectInternetErrorTextAssignment(setup, "setupInternetUi")
        assertUsesLiveRegionShow(setup, "internetErrorText", "setupInternetUi")
    }

    @Test
    fun internetCameraPermissionBlockedShowsInlineGuidanceBeforeOpeningSettings() {
        val source = mainActivitySource()
        val setup = extractMethod(source, "private fun setupInternetUi")
        val blocked = extractMethod(source, "private fun showInternetCameraPermissionBlocked")
        val compactBlocked = blocked.replace(Regex("\\s+"), "")

        assertTrue(
            "Internet scan permanent-denial path should leave recovery context in the panel",
            setup.contains("cameraPerm.isPermanentlyDenied() -> showInternetCameraPermissionBlocked()"),
        )
        assertNoDirectInternetErrorTextAssignment(blocked, "showInternetCameraPermissionBlocked")
        assertUsesLiveRegionShow(blocked, "internetErrorText", "showInternetCameraPermissionBlocked")
        assertTrue(compactBlocked.contains("R.string.internet_camera_permission_blocked"))
        assertTrue(
            "System Settings should open only after the inline recovery message is visible",
            compactBlocked.indexOf("LiveRegionTextApplier.show(binding.internetErrorText,") <
                compactBlocked.indexOf("cameraPerm.openAppSettings()"),
        )
    }

    @Test
    fun internetSensitiveDialogsUseSecureImmersiveMaterialDialogs() {
        val source = mainActivitySource()
        val setup = extractMethod(source, "private fun setupInternetUi")
        val importDialog = extractMethod(source, "private fun showInternetProfileImportDialog")
        val pairingDialog = extractMethod(source, "private fun showInternetPairingCompletionDialog")
        val secureDialog = extractMethod(source, "private fun <T : Dialog> showSecureImmersiveDialog")
        val compactSetup = setup.replace(Regex("\\s+"), "")

        assertFalse("Internet revoke confirmation should not use platform AlertDialog", setup.contains("android.app.AlertDialog"))
        assertFalse("Internet import should not use platform AlertDialog", importDialog.contains("android.app.AlertDialog.Builder"))
        assertFalse("Internet pairing should not use platform AlertDialog", pairingDialog.contains("android.app.AlertDialog.Builder"))
        assertTrue(compactSetup.contains("showSecureImmersiveDialog(MaterialAlertDialogBuilder(this)"))
        assertTrue(importDialog.contains("MaterialAlertDialogBuilder(this)"))
        assertTrue(importDialog.contains("showSecureImmersiveDialog(dialog)"))
        assertTrue(pairingDialog.contains("MaterialAlertDialogBuilder(this)"))
        assertTrue(pairingDialog.contains("showSecureImmersiveDialog(dialog)"))
        assertTrue(secureDialog.contains("WindowManager.LayoutParams.FLAG_SECURE"))
        assertTrue(
            "FLAG_SECURE should be applied before the dialog is shown",
            secureDialog.indexOf("addFlags(WindowManager.LayoutParams.FLAG_SECURE)") <
                secureDialog.indexOf("showImmersiveDialog(dialog)"),
        )
    }

    @Test
    fun internetPairingDialogUsesDedicatedSmallScreenLayout() {
        val source = mainActivitySource()
        val pairingDialog = extractMethod(source, "private fun showInternetPairingCompletionDialog")
        val compactPairingDialog = pairingDialog.replace(Regex("\\s+"), "")

        assertTrue(pairingDialog.contains("R.layout.dialog_internet_pairing_completion"))
        assertTrue(pairingDialog.contains("R.id.internetPairingRequestText"))
        assertTrue(pairingDialog.contains("R.id.internetPairingIdentityText"))
        assertTrue(pairingDialog.contains("R.id.internetPairingAcceptanceInput"))
        assertFalse("Pairing dialog must not build a raw vertical LinearLayout in code", pairingDialog.contains("android.widget.LinearLayout"))
        assertTrue(
            "The one-time request must remain selectable and should not scroll horizontally on phones",
            compactPairingDialog.contains("setTextIsSelectable(true)") &&
                compactPairingDialog.contains("setHorizontallyScrolling(false)"),
        )
    }

    @Test
    fun onFreshSessionRequiredInternetErrorTextUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val callback = extractMethod(source, "override fun onFreshSessionRequired")

        assertNoDirectInternetErrorTextAssignment(callback, "onFreshSessionRequired")
        assertUsesLiveRegionShow(callback, "internetErrorText", "onFreshSessionRequired")
    }

    @Test
    fun internetStateTextAlwaysUsesLiveRegionApplier() {
        val source = mainActivitySource()

        assertFalse(source.contains("internetStateText.setText"))
        assertFalse(source.contains("internetStateText.text ="))
        // Imported, pairing, session, failure, idle, and revoked states all announce through the helper.
        assertUsesLiveRegion(source, "internetStateText", "MainActivity", minimumCalls = 6)
    }

    @Test
    fun userVisibleAuxiliaryErrorsDoNotExposeRawProtocolReasons() {
        val source = mainActivitySource()
        val decoderFailure = extractMethod(source, "private fun reportDecoderInitializationFailure")
        val hostActionResult = extractCallback(source, "callbackClient.onHostActionResult = hostActionResult@{ accepted, rejectionReason ->")
        val fileTransferResult = extractCallback(source, "callbackClient.onFileTransferResult = fileResult@{ accepted, reason ->")

        assertTrue(
            "decoder details should remain in diagnostics",
            decoderFailure.contains("Decoder init FAILED: \${error.message}"),
        )
        assertFalse(
            "decoder exception messages must not be appended to the visible status",
            decoderFailure.contains("Video decoder failed: \${error.message}"),
        )
        assertTrue(
            "visible decoder status should use fixed recovery copy",
            decoderFailure.contains("R.string.connection_guidance_video_decoder_recovery_title"),
        )

        assertFalse(
            "Host action rejection reason is a protocol/debug value, not user copy",
            hostActionResult.contains("host_action_rejected_with_reason"),
        )
        assertFalse(
            "Host action toast must not interpolate the raw rejection reason",
            hostActionResult.contains("getString(R.string.host_action_rejected, rejectionReason)") ||
                hostActionResult.contains("getString(R.string.host_action_rejected_with_reason, rejectionReason)"),
        )
        assertTrue(hostActionResult.contains("hostActionFailureMessageId(rejectionReason)"))
        assertTrue(
            "Host action guidance should handle the Mac Host localized permission rejection",
            source.contains("rejectionReason.contains(\"Accessibility permission\", ignoreCase = true)"),
        )
        assertTrue(
            "Host action guidance should handle the Mac Host localized focused-window rejection",
            source.contains("rejectionReason.contains(\"focused window\", ignoreCase = true)"),
        )

        assertFalse(
            "File transfer reason is a protocol/debug value, not user copy",
            fileTransferResult.contains("file_transfer_failed_with_reason"),
        )
        assertTrue(fileTransferResult.contains("fileTransferFailureMessageId(reason)"))
    }

    @Test
    fun transientFeedbackUsesDedupedToastSurface() {
        val source = mainActivitySource()
        val directToastCount = countOccurrences(source, "Toast.makeText(")

        assertTrue(source.contains("private fun showDedupedToast"))
        assertTrue(source.contains("TOAST_DEDUP_WINDOW_MS"))
        assertTrue("Only the deduped helper should call Toast.makeText directly", directToastCount == 1)
    }

    @Test
    fun internetProfileSummaryUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val refresh = extractMethod(source, "private fun refreshInternetProfileUi")

        assertFalse(refresh.contains("internetProfileSummary.setText"))
        assertFalse(refresh.contains("internetProfileSummary.text ="))
        assertUsesLiveRegion(refresh, "internetProfileSummary", "refreshInternetProfileUi")
    }

    @Test
    fun internetErrorVisibilityUsesAnnouncementAwareHelpers() {
        val compactSource = mainActivitySource().replace(Regex("\\s+"), "")
        val showInvocation = "LiveRegionTextApplier.show(binding.internetErrorText,"
        val hideInvocation = "LiveRegionTextApplier.hide(binding.internetErrorText)"
        val showCount = countOccurrences(compactSource, showInvocation)
        val hideCount = countOccurrences(compactSource, hideInvocation)

        assertFalse(compactSource.contains("internetErrorText.visibility=View.VISIBLE"))
        assertFalse(compactSource.contains("internetErrorText.visibility=View.GONE"))
        // Cleanup, fresh-session, session failure, quarantine, and revocation paths show errors.
        assertTrue("Expected at least 5 error show calls; found $showCount", showCount >= 5)
        // Import success, session creation, and idle disconnect hide stale errors.
        assertTrue("Expected at least 3 error hide calls; found $hideCount", hideCount >= 3)
    }

    @Test
    fun connectedMainSessionReplaysSavedVideoPreferencesBehindCapabilityGate() {
        val source = mainActivitySource()
        val connectionStatus = extractCallback(source, "callbackClient.onConnectionStatus = connectionStatus@{ connected ->")
        val replay = extractMethod(source, "private fun replaySavedVideoPreferencesIfAvailable")

        assertTrue(
            "Connected main sessions must try to replay saved video preferences",
            connectionStatus.contains("replaySavedVideoPreferencesIfAvailable(callbackClient, callbackGeneration)"),
        )
        assertTrue(
            "Replay must stay gated on negotiated client-video-control capability",
            replay.contains("CAPABILITY_CLIENT_VIDEO_CONTROL"),
        )
        assertTrue(
            "Replay must send through the existing StreamClient video-preference path",
            replay.contains("callbackClient.setVideoPreferences("),
        )
    }

    @Test
    fun explicitVideoPreferenceControlsResetQualityUiToAuto() {
        val setupVideoControls = extractMethod(mainActivitySource(), "private fun setupVideoControls")
        val compact = setupVideoControls.replace(Regex("\\s+"), "")

        assertTrue(
            "Programmatic quality reset should not send a second quality request",
            compact.contains("if(suppressQualityListener)return@addOnButtonCheckedListener"),
        )
        assertTrue(
            "Explicit frame-rate requests should make the quality buttons reflect preset-free wire semantics",
            compact.contains("framesPerSecond=fps,qualityPreset=VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,resetQualityToAuto=true,") &&
                compact.contains("syncQualityAutoForExplicitVideoSetting()prefs.videoFrameRate=fps"),
        )
        assertTrue(
            "Explicit bitrate requests should make the quality buttons reflect preset-free wire semantics",
            compact.contains("qualityPreset=VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,resetQualityToAuto=true,") &&
                compact.contains("syncQualityAutoForExplicitVideoSetting()prefs.videoBitrateMbps=mbps"),
        )
    }

    @Test
    fun methodExtractionIgnoresBracesOutsideTheMethodStructure() {
        val source =
            """
            // private fun target() { declaration decoy }
            private fun target() {
                val ordinary = "{ string brace }"
                val raw = """ + "\"\"\"{ raw brace }\"\"\"" + """
                val character = '}'
                // { line-comment brace }
                /* outer { /* nested } */ block } */
                LiveRegionTextApplier.apply(binding.connectionTitle, ordinary + raw + character)
            }
            private fun next() {
                error("must not be included")
            }
            """.trimIndent()

        val extracted = extractMethod(source, "private fun target")

        assertTrue(extracted.contains("LiveRegionTextApplier.apply"))
        assertFalse(extracted.contains("private fun next"))
        assertFalse(extracted.contains("declaration decoy"))
    }

    private fun assertNoDirectInternetErrorTextAssignment(block: String, owner: String) {
        assertFalse(
            "$owner must not set internetErrorText via setText (bypasses live-region deduplication)",
            block.contains("internetErrorText.setText"),
        )
        assertFalse(
            "$owner must not set internetErrorText via direct .text assignment (bypasses live-region deduplication)",
            block.contains("internetErrorText.text ="),
        )
    }

    private fun assertUsesLiveRegion(
        block: String,
        viewName: String,
        owner: String,
        minimumCalls: Int = 1,
    ) {
        val compactBlock = block.replace(Regex("\\s+"), "")
        val invocation = "LiveRegionTextApplier.apply(binding.$viewName,"
        val callCount = countOccurrences(compactBlock, invocation)
        assertTrue(
            "$owner must route $viewName through LiveRegionTextApplier at least $minimumCalls time(s); found $callCount",
            callCount >= minimumCalls,
        )
    }

    private fun assertUsesLiveRegionShow(
        block: String,
        viewName: String,
        owner: String,
    ) {
        val compactBlock = block.replace(Regex("\\s+"), "")
        assertTrue(
            "$owner must make $viewName visible before changing its live-region text",
            compactBlock.contains("LiveRegionTextApplier.show(binding.$viewName,"),
        )
    }

    private fun assertCleanupBeforeUsbModePersistence(
        block: String,
        owner: String,
    ) {
        val cleanupIndex = block.indexOf("cleanupCurrentSessionBeforeUsbLaunch()")
        val persistUsbModeIndex = block.indexOf("prefs.connectionMode = ConnectionMode.USB")

        assertTrue("$owner must clean up the current LAN/Internet session first", cleanupIndex >= 0)
        assertTrue("$owner must persist USB mode", persistUsbModeIndex >= 0)
        assertTrue(
            "$owner must clean up before writing prefs.connectionMode = USB",
            cleanupIndex < persistUsbModeIndex,
        )
    }

    private fun extractMethod(source: String, signature: String): String {
        val declaration =
            Regex("(?m)^[\\t ]*" + Regex.escape(signature) + "(?=\\s|\\()")
                .find(source)
                ?: error("Method not found: $signature")
        val start = declaration.range.first
        var braceDepth = 0
        var methodStarted = false
        var lineComment = false
        var blockCommentDepth = 0
        var quotedCharacter: Char? = null
        var tripleQuotedString = false
        var escaped = false
        var i = start
        while (i < source.length) {
            val current = source[i]
            val next = source.getOrNull(i + 1)
            if (lineComment) {
                lineComment = current != '\n'
                i++
                continue
            }
            if (blockCommentDepth > 0) {
                when {
                    current == '/' && next == '*' -> {
                        blockCommentDepth++
                        i += 2
                    }
                    current == '*' && next == '/' -> {
                        blockCommentDepth--
                        i += 2
                    }
                    else -> i++
                }
                continue
            }
            if (tripleQuotedString) {
                if (source.startsWith("\"\"\"", i)) {
                    tripleQuotedString = false
                    i += 3
                } else {
                    i++
                }
                continue
            }
            val quote = quotedCharacter
            if (quote != null) {
                when {
                    escaped -> escaped = false
                    current == '\\' -> escaped = true
                    current == quote -> quotedCharacter = null
                }
                i++
                continue
            }
            when {
                current == '/' && next == '/' -> {
                    lineComment = true
                    i += 2
                }
                current == '/' && next == '*' -> {
                    blockCommentDepth = 1
                    i += 2
                }
                source.startsWith("\"\"\"", i) -> {
                    tripleQuotedString = true
                    i += 3
                }
                current == '"' || current == '\'' -> {
                    quotedCharacter = current
                    escaped = false
                    i++
                }
                current == '{' -> {
                    methodStarted = true
                    braceDepth++
                    i++
                }
                current == '}' -> {
                    braceDepth--
                    if (methodStarted && braceDepth == 0) return source.substring(start, i + 1)
                    i++
                }
                else -> i++
            }
        }
        error("Closing brace not found for $signature")
    }

    private fun countOccurrences(
        source: String,
        target: String,
    ): Int {
        require(target.isNotEmpty())
        var count = 0
        var offset = 0
        while (true) {
            val match = source.indexOf(target, offset)
            if (match < 0) return count
            count++
            offset = match + target.length
        }
    }

    private fun onSessionEndedCallback(source: String): String {
        val startMarker = "callbackClient.onSessionEnded = sessionEnded@{ failure ->"
        val endMarker = "callbackClient.onConnectionStatus = connectionStatus@{ connected ->"
        val start = source.indexOf(startMarker)
        require(start >= 0) { "MainActivity onSessionEnded callback not found" }
        val end = source.indexOf(endMarker, start)
        require(end > start) { "MainActivity onSessionEnded callback boundary not found" }
        return source.substring(start, end)
    }

    private fun extractCallback(source: String, startMarker: String): String {
        val start = source.indexOf(startMarker)
        require(start >= 0) { "Callback not found: $startMarker" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Callback body not found: $startMarker" }
        var depth = 0
        for (index in bodyStart until source.length) {
            when (source[index]) {
                '{' -> depth++
                '}' -> {
                    depth--
                    if (depth == 0) return source.substring(start, index + 1)
                }
            }
        }
        error("Callback closing brace not found: $startMarker")
    }

    private fun extractBlockAfterMarker(
        source: String,
        marker: String,
    ): String {
        val start = source.indexOf(marker)
        require(start >= 0) { "Block marker not found: $marker" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Block body not found: $marker" }
        var depth = 0
        for (index in bodyStart until source.length) {
            when (source[index]) {
                '{' -> depth++
                '}' -> {
                    depth--
                    if (depth == 0) return source.substring(start, index + 1)
                }
            }
        }
        error("Block closing brace not found: $marker")
    }

    private fun extractWhenBranch(
        source: String,
        marker: String,
    ): String {
        val start = source.indexOf(marker)
        require(start >= 0) { "When branch not found: $marker" }
        val nextBranch = Regex("\\n[\\t ]*ConnectionMode\\.")
            .find(source, start + marker.length)
            ?.range
            ?.first
            ?: source.indexOf("\n            }", start).takeIf { it > start }
            ?: error("When branch end not found: $marker")
        return source.substring(start, nextBranch)
    }

    private fun mainActivitySource(): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            MAIN_ACTIVITY_PATHS
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("MainActivity.kt not found from " + System.getProperty("user.dir"))
    }

    private fun mainActivityLayoutSource(): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            ACTIVITY_MAIN_LAYOUT_PATHS
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("activity_main.xml not found from " + System.getProperty("user.dir"))
    }

    private fun resourceSource(relativePath: String): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            listOf(relativePath, "baseline/AndroidClient/$relativePath")
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("$relativePath not found from " + System.getProperty("user.dir"))
    }

    private fun extractXmlElement(
        source: String,
        idAttribute: String,
    ): String {
        val idIndex = source.indexOf(idAttribute)
        require(idIndex >= 0) { "XML element not found: $idAttribute" }
        val openStart = source.lastIndexOf('<', idIndex)
        require(openStart >= 0) { "XML element start not found: $idAttribute" }
        val elementName =
            source.substring(openStart + 1)
                .takeWhile { !it.isWhitespace() && it != '>' }
        val closeMarker = "</$elementName>"
        val closeEnd = source.indexOf(closeMarker, idIndex)
        if (closeEnd >= 0) return source.substring(openStart, closeEnd + closeMarker.length)
        val selfClosingEnd = source.indexOf("/>", idIndex)
        require(selfClosingEnd >= 0) { "XML element end not found: $idAttribute" }
        return source.substring(openStart, selfClosingEnd + 2)
    }

    private companion object {
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
        val ACTIVITY_MAIN_LAYOUT_PATHS =
            listOf(
                "app/src/main/res/layout/activity_main.xml",
                "baseline/AndroidClient/app/src/main/res/layout/activity_main.xml",
            )
    }
}
