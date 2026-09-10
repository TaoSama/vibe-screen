package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WirelessTabControllerContractTest {
    @Test
    fun connectAndRepairCopyUsesStringResourcesWithoutWarningEmoji() {
        val source = wirelessTabControllerSource()
        val bind = extractMethod(source, "fun bind")
        val onScanResult = extractMethod(source, "fun onScanResult")
        val onConnectError = extractMethod(source, "fun onConnectError")
        val showConnectionGuidance = extractMethod(source, "internal fun showConnectionGuidance")
        val showRepairMessage = extractMethod(source, "private fun showRepairMessage")

        assertFalse(onConnectError.contains("⚠"))
        assertFalse(onConnectError.contains("Couldn't"))
        assertFalse(onConnectError.contains("No response"))
        assertFalse(onConnectError.contains("Re-pair"))
        assertFalse(onConnectError.contains("secure handshake"))
        assertTrue(bind.contains("R.string.reconnecting_to_mac"))
        assertTrue(onScanResult.contains("R.string.connecting_to_mac"))
        assertTrue(onConnectError.contains("R.string.wireless_error_title_couldnt_reach_mac"))
        assertTrue(onConnectError.contains("R.string.wireless_error_network_cached"))
        assertTrue(onConnectError.contains("R.string.wireless_error_network_uncached"))
        assertTrue(onConnectError.contains("R.string.wireless_error_title_repair_required"))
        assertTrue(onConnectError.contains("R.string.wireless_error_token_rejected_cached"))
        assertTrue(onConnectError.contains("R.string.wireless_error_token_rejected_uncached"))
        assertTrue(onConnectError.contains("R.string.wireless_error_title_connection_error"))
        assertTrue(onConnectError.contains("R.string.wireless_error_protocol_message"))
        assertTrue(onConnectError.contains("showRepairMessage("))
        assertTrue(showConnectionGuidance.contains("showRepairMessage("))
        assertTrue(showRepairMessage.contains("LiveRegionTextApplier.apply(views.repairTitle, title)"))
        assertTrue(showRepairMessage.contains("LiveRegionTextApplier.apply(views.repairMessage, message)"))
        assertTrue(showRepairMessage.contains("views.repairMessage.contentDescription"))
        assertTrue(showRepairMessage.contains("R.string.connection_guidance_full_message"))
        assertFalse(showRepairMessage.contains("= \"\$title. \$message\""))
    }

    @Test
    fun scheduledReconnectShowsRetryCardAndStateTransitionsHideTerminalPanels() {
        val source = wirelessTabControllerSource()
        val transition = extractMethod(source, "private fun transition")
        val showAutomaticReconnect = extractMethod(source, "fun showAutomaticReconnect")
        val showAttempting = extractMethod(source, "fun showAutomaticReconnectAttempting")
        val showConnectionGuidance = extractMethod(source, "internal fun showConnectionGuidance")
        val show = extractMethod(source, "fun show")

        assertTrue(
            "Scheduled reconnect should stay in the paired-idle repair card with a visible countdown and immediate retry",
            showAutomaticReconnect.contains("R.string.reconnect_countdown_message") &&
                showAutomaticReconnect.contains("R.string.retry_now") &&
                showAutomaticReconnect.contains("transition(State.PAIRED_IDLE)"),
        )
        assertTrue(
            "When the retry is actively starting, the reconnect action should be disabled with loading feedback",
            showAttempting.contains("R.string.reconnecting_short") &&
                showAttempting.contains("R.string.reconnect_attempting_message") &&
                showAttempting.contains("views.reconnectButton.isEnabled = false"),
        )
        assertTrue(
            "Terminal wireless guidance should use the repair panel instead of leaving the reconnect spinner visible",
            showConnectionGuidance.contains("transition(State.REPAIR_NEEDED)"),
        )
        assertTrue(
            "Idle wireless state should use the paired idle panel instead of leaving the reconnect spinner visible",
            show.contains("transition(State.PAIRED_IDLE)"),
        )
        assertTrue(
            "The transition helper must make every wireless panel mutually exclusive",
            transition.contains("views.connecting.visibility = if (next == State.CONNECTING) View.VISIBLE else View.GONE") &&
                transition.contains("views.firstTime.visibility = if (next == State.FIRST_TIME) View.VISIBLE else View.GONE") &&
                transition.contains("views.connected.visibility = if (next == State.CONNECTED) View.VISIBLE else View.GONE") &&
                transition.contains("views.pairedIdle.visibility = if (next == State.PAIRED_IDLE) View.VISIBLE else View.GONE") &&
                transition.contains("views.repair.visibility = if (next == State.REPAIR_NEEDED) View.VISIBLE else View.GONE") &&
                transition.contains("views.permDenied.visibility = if (next == State.PERM_DENIED) View.VISIBLE else View.GONE"),
        )
    }

    @Test
    fun wirelessLifecycleRoutesThroughExpectedStatePanels() {
        val source = wirelessTabControllerSource()
        val onScanResult = extractMethod(source, "fun onScanResult")
        val onConnectSuccess = extractMethod(source, "fun onConnectSuccess")
        val onStreamDisconnected = extractMethod(source, "fun onStreamDisconnected")
        val onConnectError = extractMethod(source, "fun onConnectError")

        assertTrue(onScanResult.contains("storage.save(PairedHostStorage.Entry"))
        assertTrue(onScanResult.contains("showConnecting("))
        assertTrue(onScanResult.contains("onConnectRequested(parsed.host, parsed.port, parsed.token, deviceName, parsed.macName)"))

        assertTrue(onConnectSuccess.contains("LiveRegionTextApplier.apply(views.connectedMacName, macName)"))
        assertTrue(onConnectSuccess.contains("LiveRegionTextApplier.apply(views.connectedMacIp, ip)"))
        assertTrue(onConnectSuccess.contains("transition(State.CONNECTED)"))

        assertTrue(onStreamDisconnected.contains("storage.load() ?: run"))
        assertTrue(onStreamDisconnected.contains("transition(State.FIRST_TIME)"))
        assertTrue(onStreamDisconnected.contains("showIdleReconnectState()"))
        assertTrue(onStreamDisconnected.contains("transition(State.PAIRED_IDLE)"))

        val networkUnreachableBranch =
            extractWhenBranch(onConnectError, "is StreamClient.WirelessConnectError.NetworkUnreachable")
        assertTrue(networkUnreachableBranch.contains("showRepairMessage("))
        assertTrue(networkUnreachableBranch.contains("transition(State.REPAIR_NEEDED)"))
    }

    @Test
    fun pairedIdleStateClearsCountdownAndKeepsReconnectActionReady() {
        val source = wirelessTabControllerSource()
        val showIdleReconnectState = extractMethod(source, "private fun showIdleReconnectState")
        val onStreamDisconnected = extractMethod(source, "fun onStreamDisconnected")
        val show = extractMethod(source, "fun show")

        assertTrue(showIdleReconnectState.contains("R.string.disconnected_status"))
        assertTrue(showIdleReconnectState.contains("LiveRegionTextApplier.hide(views.reconnectCountdown)"))
        assertTrue(showIdleReconnectState.contains("views.reconnectButton.text = host.getString(R.string.reconnect)"))
        assertTrue(showIdleReconnectState.contains("views.reconnectButton.isEnabled = true"))
        assertTrue(onStreamDisconnected.contains("showIdleReconnectState()"))
        assertTrue(show.contains("showIdleReconnectState()"))
    }

    @Test
    fun trustedNetworkConfirmationUsesMaterialImmersiveDialogWithoutChangingScanCallbackSemantics() {
        val wirelessSource = wirelessTabControllerSource()
        val mainSource = mainActivitySource()
        val activityHost = extractClass(wirelessSource, "private class ActivityWirelessTabHost")
        val dialog = extractMethod(activityHost, "override fun showTrustedNetworkDialog")
        val createDialog = extractMethod(wirelessSource, "internal fun createTrustedNetworkDialog")
        val configureActions = extractMethod(wirelessSource, "private fun configureTrustedNetworkDialogActions")
        val constructor = extractMethod(wirelessSource, "constructor(")
        val setupWireless = extractMethod(mainSource, "private fun setupWirelessController")
        val triggerScan = extractMethod(wirelessSource, "private fun triggerScan")

        assertFalse("trusted-network confirmation must not use the platform AlertDialog builder", wirelessSource.contains("android.app.AlertDialog"))
        assertFalse("trusted-network confirmation must not keep a platform builder reference", wirelessSource.contains("AlertDialog.Builder"))
        assertFalse("trusted-network confirmation must not bypass the host dialog presenter", dialog.contains(".show()"))
        assertTrue(dialog.contains("if (activity.isFinishing || activity.isDestroyed) return"))
        assertTrue(dialog.indexOf("activity.isFinishing") < dialog.indexOf("showDialog(createTrustedNetworkDialog(activity, onConfirmed))"))
        assertTrue(dialog.contains("showDialog(createTrustedNetworkDialog(activity, onConfirmed))"))
        assertFalse("trusted-network dialog helper must not use the platform AlertDialog builder", createDialog.contains("android.app.AlertDialog"))
        assertTrue(createDialog.contains("R.layout.dialog_trusted_network"))
        assertTrue(wirelessSource.contains("MaterialAlertDialogBuilder(context)"))
        assertTrue(createDialog.contains(".setTitle(R.string.trusted_network_dialog_title)"))
        assertFalse(createDialog.contains(".setMessage("))
        assertTrue(wirelessSource.contains(".setView(content)"))
        assertTrue(wirelessSource.contains(".setNegativeButton(R.string.cancel, null)"))
        assertTrue(wirelessSource.contains(".setPositiveButton(R.string.trusted_network_dialog_confirm, null)"))
        assertTrue(wirelessSource.contains(".create()"))
        assertTrue(wirelessSource.contains(".also { dialog -> configureTrustedNetworkDialogActions(dialog, onConfirmed) }"))
        assertTrue(configureActions.contains("dialog.setOnShowListener"))
        assertTrue(configureActions.contains("val params = scroll.layoutParams ?: return@post"))
        assertTrue(configureActions.contains("checkNotNull(dialog.getButton(which))"))
        assertTrue(configureActions.contains("checkNotNull(dialog.getButton(AlertDialog.BUTTON_POSITIVE))"))
        assertTrue(configureActions.contains(".setOnClickListener"))
        assertTrue(configureActions.contains("onConfirmed()"))
        assertTrue(configureActions.contains("dialog.dismiss()"))
        assertTrue(wirelessSource.contains("button.setSingleLine(false)"))
        assertTrue(wirelessSource.contains("button.maxLines = TRUSTED_NETWORK_DIALOG_ACTION_MAX_LINES"))
        assertTrue(wirelessSource.contains("button.ellipsize = null"))
        assertTrue(dialog.contains("showDialog("))
        assertTrue(activityHost.contains("private val showDialog: (Dialog) -> Dialog"))
        assertTrue(constructor.contains("showDialog: (Dialog) -> Dialog"))
        assertTrue(constructor.contains("ActivityWirelessTabHost("))
        assertTrue(setupWireless.contains("showDialog = ::showImmersiveDialog"))
        assertTrue(
            "Confirmed trusted-network dialog must still persist the acknowledgement before continuing scan",
            triggerScan.indexOf("acknowledgeTrustedLan()") < triggerScan.indexOf("continueScan()"),
        )
    }

    @Test
    fun temporaryCameraDenialReturnsToReadableScanEntry() {
        val source = wirelessTabControllerSource()
        val permissionResult = extractMethod(source, "fun onCameraPermissionResult")
        val showRetry = extractMethod(source, "private fun showCameraPermissionRetryHint")
        val hideRetry = extractMethod(source, "private fun hideCameraPermissionRetryHint")

        assertTrue(permissionResult.contains("showCameraPermissionRetryHint()"))
        assertTrue(permissionResult.contains("transition(State.FIRST_TIME)"))
        assertTrue(showRetry.contains("R.string.camera_permission_retry_instructions"))
        assertTrue(showRetry.contains("views.permissionRetryMessage.contentDescription = message"))
        assertTrue(showRetry.contains("LiveRegionTextApplier.show(views.permissionRetryMessage, message)"))
        assertTrue(hideRetry.contains("views.permissionRetryMessage.contentDescription = null"))
        assertTrue(hideRetry.contains("LiveRegionTextApplier.hide(views.permissionRetryMessage)"))
    }

    @Test
    fun trustedNetworkConfirmationUsesMaterialImmersiveDialogWithLifecycleGuard() {
        val source = wirelessTabControllerSource()
        val activityHost = extractClass(source, "private class ActivityWirelessTabHost")
        val trustedDialog = extractMethod(activityHost, "override fun showTrustedNetworkDialog")
        val createDialog = extractMethod(source, "internal fun createTrustedNetworkDialog")
        val configureActions = extractMethod(source, "private fun configureTrustedNetworkDialogActions")
        val triggerScan = extractMethod(source, "private fun triggerScan")
        val compactTrustedDialog = trustedDialog.replace(Regex("\\s+"), "")
        val compactTriggerScan = triggerScan.replace(Regex("\\s+"), "")

        assertFalse("Wireless trusted dialog must not use platform AlertDialog", source.contains("android.app.AlertDialog"))
        assertTrue(createDialog.contains("MaterialAlertDialogBuilder(context)"))
        assertTrue(createDialog.contains(".setTitle(R.string.trusted_network_dialog_title)"))
        assertTrue(createDialog.contains(".setView(content)"))
        assertTrue(createDialog.contains(".setNegativeButton(R.string.cancel, null)"))
        assertTrue(createDialog.contains(".setPositiveButton(R.string.trusted_network_dialog_confirm, null)"))
        assertTrue(createDialog.contains(".also { dialog -> configureTrustedNetworkDialogActions(dialog, onConfirmed) }"))
        assertFalse(createDialog.contains(".setMessage("))
        assertTrue(configureActions.contains("button.setSingleLine(false)"))
        assertTrue(configureActions.contains("button.maxLines = TRUSTED_NETWORK_DIALOG_ACTION_MAX_LINES"))
        assertTrue(configureActions.contains("button.ellipsize = null"))
        assertTrue(configureActions.contains("onConfirmed()"))
        assertTrue(configureActions.contains("dialog.dismiss()"))
        assertTrue(compactTrustedDialog.contains("showDialog(createTrustedNetworkDialog(activity,onConfirmed))"))
        assertTrue(compactTrustedDialog.contains("if(activity.isFinishing||activity.isDestroyed)return"))
        assertTrue(
            "Lifecycle guard should run before the dialog builder is created",
            trustedDialog.indexOf("activity.isFinishing") < trustedDialog.indexOf("showDialog(createTrustedNetworkDialog(activity, onConfirmed))"),
        )
        assertTrue(
            "Unacknowledged LAN scans must acknowledge only after the dialog confirmation callback",
            compactTriggerScan.contains("host.showTrustedNetworkDialog{acknowledgeTrustedLan()continueScan()}"),
        )
        assertTrue(compactTriggerScan.contains("if(!isTrustedLanAcknowledged())"))
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

    private fun extractWhenBranch(source: String, branchStart: String): String {
        val start = source.indexOf(branchStart)
        require(start >= 0) { "Branch not found: $branchStart" }
        val nextBranch = Regex("(?m)^[\t ]*(is|else)\\s").find(source, start + branchStart.length)
        return source.substring(start, nextBranch?.range?.first ?: source.length)
    }

    private fun wirelessTabControllerSource(): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            WIRELESS_TAB_CONTROLLER_PATHS
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("WirelessTabController.kt not found from " + System.getProperty("user.dir"))
    }

    private fun extractClass(source: String, signature: String): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Class not found: $signature" }
        var braceDepth = 0
        var started = false
        for (i in start until source.length) {
            when (source[i]) {
                '{' -> {
                    started = true
                    braceDepth++
                }
                '}' -> {
                    braceDepth--
                    if (started && braceDepth == 0) return source.substring(start, i + 1)
                }
            }
        }
        error("Closing brace not found for $signature")
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

    private companion object {
        val WIRELESS_TAB_CONTROLLER_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/WirelessTabController.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/WirelessTabController.kt",
            )
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
    }
}
