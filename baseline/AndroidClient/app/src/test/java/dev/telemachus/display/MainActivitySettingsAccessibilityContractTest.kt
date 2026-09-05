package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivitySettingsAccessibilityContractTest {
    @Test
    fun unavailableVideoAndGestureControlsUseSharedAccessibilityApplier() {
        val source = mainActivitySource()
        val layout = settingsLayoutSource()
        val strings = stringsSource()
        val videoControls = extractMethod(source, "private fun setupVideoControls")
        val gestureControls = extractMethod(source, "private fun setupGestureShortcutControls")
        val applier = settingsUnavailableControlsAccessibilityApplierSource()

        assertTrue(
            "Video controls should route unavailable semantics through the shared Settings applier",
            videoControls.contains("SettingsUnavailableControlsAccessibilityApplier.apply(") &&
                videoControls.contains("unavailableContent = videoStaticContent + listOf(qualityGroup, frameRateGroup, bitrateSlider, bitrateValue)"),
        )
        assertTrue(
            "Gesture controls should route unavailable semantics through the shared Settings applier",
            gestureControls.contains("SettingsUnavailableControlsAccessibilityApplier.apply(") &&
                gestureControls.contains("unavailableContent = gestureStaticContent + listOf(swipeUpGroup, swipeDownGroup)"),
        )
        assertTrue(
            "Gesture unavailable copy should explain managed-policy denial instead of only compatibility gaps",
            gestureControls.contains("GestureShortcutAvailabilityPresentationPolicy.unavailableMessage(") &&
                gestureControls.contains("customGesturesPolicyAllowed = managedCustomGesturesAllowed") &&
                gestureControls.contains("hostActionsPolicyAllowed = managedHostActionsAllowed") &&
                strings.contains("gesture_shortcuts_policy_disabled") &&
                strings.contains("Gesture shortcuts are disabled by this device or Mac session policy"),
        )
        assertTrue(
            "Video unavailable state should hide labels, values, and controls from accessibility traversal",
            videoControls.contains("videoStaticContent: List<View>") &&
                source.contains("videoStaticContent = listOf(videoQualityLabel, videoFrameRateLabel, videoBitrateLabel)") &&
                source.contains("findViewById<TextView>(R.id.videoBitrateValue)"),
        )
        assertTrue(
            "Gesture unavailable state should hide inactive labels and controls from accessibility traversal",
            gestureControls.contains("gestureStaticContent: List<View>") &&
                source.contains("gestureStaticContent = listOf(gestureShortcutsDescription, gestureSwipeUpLabel, gestureSwipeDownLabel)"),
        )
        assertTrue(
            "Unavailable notes should become the single accessible explanation",
            applier.contains("unavailableNote.visibility = if (available) View.GONE else View.VISIBLE") &&
                applier.contains("unavailableNote.isFocusable = !available") &&
                applier.contains("View.IMPORTANT_FOR_ACCESSIBILITY_YES"),
        )
        assertTrue(
            "Disabled option groups should not remain exposed as dead controls",
            applier.contains("View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS") &&
                applier.contains("View.IMPORTANT_FOR_ACCESSIBILITY_NO"),
        )
        assertTrue(
            "Available controls should restore the platform default accessibility importance",
            applier.contains("View.IMPORTANT_FOR_ACCESSIBILITY_AUTO"),
        )
        assertFalse(
            "The Activity should not hand-roll unavailable-note visibility outside the shared applier",
            Regex("unavailableNote\\.visibility\\s*=").containsMatchIn(videoControls) ||
                Regex("unavailableNote\\.visibility\\s*=").containsMatchIn(gestureControls),
        )
        assertTrue(
            "Focusable unavailable notes should have a visible focus background",
            extractXmlElement(layout, "android:id=\"@+id/videoControlUnavailable\"")
                .contains("android:background=\"?attr/selectableItemBackground\"") &&
                extractXmlElement(layout, "android:id=\"@+id/gestureShortcutUnavailable\"")
                    .contains("android:background=\"?attr/selectableItemBackground\""),
        )
        listOf(
            "android:id=\"@+id/videoQualityLabel\"" to "android:text=\"@string/video_quality_label\"",
            "android:id=\"@+id/videoFrameRateLabel\"" to "android:text=\"@string/video_frame_rate_label\"",
            "android:id=\"@+id/videoBitrateLabel\"" to "android:text=\"@string/video_bitrate_label\"",
            "android:id=\"@+id/gestureShortcutsDescription\"" to "android:text=\"@string/gesture_shortcuts_description\"",
            "android:id=\"@+id/gestureSwipeUpLabel\"" to "android:text=\"@string/gesture_swipe_up_label\"",
            "android:id=\"@+id/gestureSwipeDownLabel\"" to "android:text=\"@string/gesture_swipe_down_label\"",
        ).forEach { (idAttribute, expectedText) ->
            assertTrue(
                "$idAttribute should be attached to $expectedText",
                extractXmlElement(layout, idAttribute).contains(expectedText),
            )
        }
    }

    @Test
    fun controlBarManagedPolicyDenialKeepsDisabledControlsExplainable() {
        val source = mainActivitySource()
        val strings = stringsSource()
        val populateHostActions = extractMethod(source, "private fun populateHostActions")
        val refreshClipboardControl = extractMethod(source, "private fun refreshClipboardControl")
        val updateClipboardLabel = extractMethod(source, "private fun updateClipboardAccessibilityLabel")
        val refreshFileTransferControl = extractMethod(source, "private fun refreshFileTransferControl")
        val applyControlButtonLabel = extractMethod(source, "private fun applyControlButtonLabel")
        val activateSession = extractMethod(source, "private fun activateSession")
        val connectInternet = extractMethod(source, "private fun connectInternet")
        val disconnectInternet = extractMethod(source, "private fun disconnectInternet")
        val applyDisconnectedSessionUi = extractMethod(source, "private fun applyDisconnectedSessionUi")
        val displayCallback = extractCallback(source, "callbackClient.onDisplaysAvailable = displays@")

        assertTrue(
            "Host actions should use the managed-policy presentation instead of disappearing without explanation",
            populateHostActions.contains("ManagedPolicyControlAvailabilityPolicy.presentation(") &&
                populateHostActions.contains("capabilityAvailable = controlBarPolicySurface.hostActions") &&
                populateHostActions.contains("policyAllowed = managedHostActionsAllowed") &&
                populateHostActions.contains("R.string.control_host_actions_policy_disabled") &&
                populateHostActions.contains("applyControlButtonLabel(binding.controlHostActionsButton, hostActionsPresentation.labelResource)"),
        )
        assertTrue(
            "Clipboard policy denial should keep one disabled button with policy-specific a11y text",
            refreshClipboardControl.contains("ManagedPolicyControlAvailabilityPolicy.presentation(") &&
                refreshClipboardControl.contains("capabilityAvailable = controlBarPolicySurface.clipboard") &&
                refreshClipboardControl.contains("policyAllowed = managedClipboardAllowed") &&
                refreshClipboardControl.contains("R.string.control_clipboard_policy_disabled") &&
                updateClipboardLabel.contains("if (!managedClipboardAllowed)") &&
                updateClipboardLabel.contains("applyControlButtonLabel(binding.controlClipboardButton, R.string.control_clipboard_policy_disabled)"),
        )
        assertTrue(
            "File-transfer policy denial should keep one disabled button with policy-specific a11y text",
            refreshFileTransferControl.contains("ManagedPolicyControlAvailabilityPolicy.presentation(") &&
                refreshFileTransferControl.contains("capabilityAvailable =") &&
                refreshFileTransferControl.contains("controlBarPolicySurface.fileTransfer || internetFileTransfer") &&
                refreshFileTransferControl.contains("policyAllowed = managedFileTransferAllowed") &&
                refreshFileTransferControl.contains("R.string.control_file_transfer_policy_disabled") &&
                refreshFileTransferControl.contains("getString(fileTransferPresentation.labelResource)") &&
                refreshFileTransferControl.contains("TooltipCompat.setTooltipText(binding.controlFileTransferButton, binding.controlFileTransferButton.contentDescription)"),
        )
        assertTrue(
            "Shared control-label helper should update both screen-reader text and long-press tooltip",
            applyControlButtonLabel.contains("button.contentDescription = label") &&
                applyControlButtonLabel.contains("TooltipCompat.setTooltipText(button, label)"),
        )
        assertTrue(
            "Control policy surface should reset on a new local session and preserve discovered controls for later policy updates",
            activateSession.contains("controlBarPolicySurface = ManagedPolicyControlSurface()") &&
                connectInternet.contains("controlBarPolicySurface = ManagedPolicyControlSurface()") &&
                disconnectInternet.contains("controlBarPolicySurface = ManagedPolicyControlSurface()") &&
                applyDisconnectedSessionUi.contains("controlBarPolicySurface = ManagedPolicyControlSurface()") &&
                refreshFileTransferControl.contains("val internetFileTransferSurface = controlBarPolicySurface.fileTransfer || internetFileTransfer") &&
                refreshFileTransferControl.contains("controlBarPolicySurface.copy(fileTransfer = internetFileTransfer || (!managedFileTransferAllowed && internetFileTransferSurface))") &&
                populateHostActions.contains("controlBarPolicySurface = controlBarPolicySurface.mergeWithCurrentHostActions(") &&
                displayCallback.contains("controlBarPolicySurface = controlBarPolicySurface.mergeWithCurrentHostActions(") &&
                populateHostActions.contains("hostActionsPolicyAllowed = managedHostActionsAllowed") &&
                displayCallback.contains("hostActionsPolicyAllowed = managedHostActionsAllowed") &&
                displayCallback.contains("callbackClient.managedPolicyControlSurfaceCapabilities()") &&
                displayCallback.contains("availableHostActions") &&
                populateHostActions.contains("client.managedPolicyControlSurfaceCapabilities()") &&
                populateHostActions.contains("actions"),
        )
        listOf(
            "control_host_actions_policy_disabled" to "Window actions disabled by policy",
            "control_clipboard_policy_disabled" to "Clipboard disabled by policy",
            "control_file_transfer_policy_disabled" to "File transfer disabled by policy",
        ).forEach { (name, copy) ->
            assertTrue(strings.contains(name))
            assertTrue(strings.contains(copy))
        }
    }

    private fun mainActivitySource(): String = sourceFile(MAIN_ACTIVITY_PATHS).readText()

    private fun settingsLayoutSource(): String = sourceFile(SETTINGS_LAYOUT_PATHS).readText()

    private fun stringsSource(): String = sourceFile(STRINGS_PATHS).readText()

    private fun settingsUnavailableControlsAccessibilityApplierSource(): String =
        sourceFile(SETTINGS_UNAVAILABLE_CONTROLS_ACCESSIBILITY_APPLIER_PATHS).readText()

    private fun sourceFile(paths: List<String>): File {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            paths
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("Source file not found from " + System.getProperty("user.dir"))
    }

    private fun extractMethod(
        source: String,
        signature: String,
    ): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Method not found: $signature" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Method body not found: $signature" }
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
        error("Closing brace not found: $signature")
    }

    private fun extractCallback(
        source: String,
        signature: String,
    ): String = extractMethod(source, signature)

    private fun extractXmlElement(
        source: String,
        idAttribute: String,
    ): String {
        val idIndex = source.indexOf(idAttribute)
        require(idIndex >= 0) { "XML element not found: $idAttribute" }
        val openStart = source.lastIndexOf('<', idIndex)
        require(openStart >= 0) { "XML element start not found: $idAttribute" }
        val openTagEnd = source.indexOf('>', idIndex)
        require(openTagEnd >= 0) { "XML element open tag end not found: $idAttribute" }
        return source.substring(openStart, openTagEnd + 1)
    }

    private companion object {
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
        val SETTINGS_LAYOUT_PATHS =
            listOf(
                "app/src/main/res/layout/dialog_settings.xml",
                "baseline/AndroidClient/app/src/main/res/layout/dialog_settings.xml",
            )
        val STRINGS_PATHS =
            listOf(
                "app/src/main/res/values/strings.xml",
                "baseline/AndroidClient/app/src/main/res/values/strings.xml",
            )
        val SETTINGS_UNAVAILABLE_CONTROLS_ACCESSIBILITY_APPLIER_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/SettingsUnavailableControlsAccessibilityApplier.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/SettingsUnavailableControlsAccessibilityApplier.kt",
            )
    }
}
