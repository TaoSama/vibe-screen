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
        val floatingSettingsBranch = extractBlockAfterMarker(entryPolicy, "if (!useInlineSettingsButton)")

        assertTrue(
            "Disconnected state should use the resource policy for inline settings",
            entryPolicy.contains("resources.getBoolean(R.bool.connection_panel_inline_settings_button)"),
        )
        assertTrue(
            "Narrow layouts should show the inline connection settings button",
            entryPolicy.contains("binding.connectionSettingsButton.visibility = if (useInlineSettingsButton) View.VISIBLE else View.GONE"),
        )
        assertTrue(
            "Narrow layouts should hide the floating settings button",
            entryPolicy.contains("binding.settingsButton.visibility = if (useInlineSettingsButton) View.GONE else View.VISIBLE"),
        )
        assertTrue(
            "Wide layouts should keep the floating button above the connection panel",
            entryPolicy.contains("if (!useInlineSettingsButton)"),
        )
        assertTrue(
            "Wide disconnected settings button must sit above the connection panel",
            floatingSettingsBranch.contains("settingsButton.bringToFront()"),
        )
        assertTrue(
            "Wide disconnected settings button must have a higher z-order than the connection panel",
            floatingSettingsBranch.contains("settingsButton.translationZ = binding.settingsPanel.elevation + 1f"),
        )
        assertTrue(
            "Wide disconnected settings button must ignore overlay opacity and stay readable",
            floatingSettingsBranch.contains("binding.settingsButton.alpha = 1f"),
        )
        assertTrue(
            "Disconnected entry policy must apply when the disconnected panel is first shown",
            disconnected.contains("applyDisconnectedSettingsEntryPolicy()"),
        )
        assertTrue(
            "Configuration changes must re-evaluate inline versus floating settings entry while disconnected",
            configurationChanged.contains("if (!isConnected)") &&
                configurationChanged.contains("applyDisconnectedSettingsEntryPolicy()"),
        )
    }

    @Test
    fun floatingDisconnectedSettingsButtonExposesAccessibleClickTarget() {
        val settingsButton = extractXmlElement(mainActivityLayoutSource(), "android:id=\"@+id/settingsButton\"")

        assertTrue(
            "The clickable floating settings container needs the accessible label",
            settingsButton.contains("android:contentDescription=\"@string/display_settings\""),
        )
        assertTrue(
            "The floating settings container should be keyboard focusable",
            settingsButton.contains("android:focusable=\"true\""),
        )
        assertTrue(
            "The inner icon should not duplicate the parent accessibility node",
            settingsButton.contains("android:importantForAccessibility=\"no\""),
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
            "Overlay opacity must not target the disconnected floating settings entry",
            updateOverlayOpacity.contains("settingsButton"),
        )
        assertFalse(
            "Restoring overlay state must not dim the disconnected floating settings entry",
            restoreOverlayPosition.contains("settingsButton") ||
                restoreOverlayPosition.contains("updateSettingsButtonOpacity"),
        )
        assertFalse(
            "Changing overlay opacity from Settings must not dim the disconnected floating settings entry",
            opacitySliderListener.contains("settingsButton") ||
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
