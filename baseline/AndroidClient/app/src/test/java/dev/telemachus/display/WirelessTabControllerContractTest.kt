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
            "The transition helper must make connecting, paired idle, and repair panels mutually exclusive",
            transition.contains("views.connecting.visibility = if (next == State.CONNECTING) View.VISIBLE else View.GONE") &&
                transition.contains("views.pairedIdle.visibility = if (next == State.PAIRED_IDLE) View.VISIBLE else View.GONE") &&
                transition.contains("views.repair.visibility = if (next == State.REPAIR_NEEDED) View.VISIBLE else View.GONE"),
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

    private companion object {
        val WIRELESS_TAB_CONTROLLER_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/WirelessTabController.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/WirelessTabController.kt",
            )
    }
}
