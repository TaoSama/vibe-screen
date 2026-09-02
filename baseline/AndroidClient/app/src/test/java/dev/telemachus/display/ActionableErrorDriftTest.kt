package dev.telemachus.display

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ActionableErrorDriftTest {
    @Test
    fun requiredActionableErrorContractsStayCoveredOffline() {
        val statesByCode = loadActionableErrorMatrix()

        EXPECTED_CONTRACTS.forEach { expected ->
            val state = statesByCode[expected.code]
            assertNotNull("Missing actionable contract " + expected.code, state)
            requireNotNull(state)

            val contract = state.getAsJsonObject("contract")
            assertEquals(expected.title, contract.get("title").asString)
            assertEquals(expected.body, contract.get("body").asString)
            assertEquals(expected.action, contract.get("action").asString)
            assertEquals("covered-offline", state.get("gate_status").asString)
            assertFalse(state.get("readme_gate_closure").asBoolean)
            assertTrue(
                expected.code + " must cite offline evidence",
                state.getAsJsonArray("offline_evidence").size() > 0,
            )
        }

        assertEquals(EXPECTED_CONTRACTS.map { it.code }.toSet(), statesByCode.keys)
    }

    private fun loadActionableErrorMatrix(): Map<String, JsonObject> {
        val matrix = JsonParser.parseString(actionableErrorMatrixFile().readText()).asJsonObject
        val states = matrix.getAsJsonArray("states")
        return buildMap {
            states.forEach { element ->
                val state = element.asJsonObject
                val contract = state.getAsJsonObject("contract") ?: return@forEach
                val code = contract.get("code")?.asString ?: return@forEach
                put(code, state)
            }
        }
    }

    private fun actionableErrorMatrixFile(): File {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            MATRIX_PATHS
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("actionable-error-states.json not found from " + System.getProperty("user.dir"))
    }

    private data class ExpectedContract(
        val code: String,
        val title: String,
        val body: String,
        val action: String,
    )

    private companion object {
        val MATRIX_PATHS =
            listOf(
                "docs/changes/2026-08-23-actionable-error-states/actionable-error-states.json",
                "../docs/changes/2026-08-23-actionable-error-states/actionable-error-states.json",
                "../../docs/changes/2026-08-23-actionable-error-states/actionable-error-states.json",
            )

        val EXPECTED_CONTRACTS =
            listOf(
                ExpectedContract(
                    code = "host_screen_recording_denied",
                    title = "Screen Recording permission denied",
                    body = "The macOS Host cannot capture a display because Screen Recording permission is missing or stale for the installed app identity.",
                    action = "Grant Screen Recording to the installed Vibe Screen app in System Settings, quit, reopen, and rerun the Host preflight.",
                ),
                ExpectedContract(
                    code = "accessibility_denied_or_limited",
                    title = "Accessibility permission denied",
                    body = "macOS input injection or window movement is unavailable because Accessibility is not granted to the stable signed Host app.",
                    action = "Grant Accessibility to the stable signed installed app, quit and reopen Vibe Screen, then retry input or window movement.",
                ),
                ExpectedContract(
                    code = "adb_reverse_missing",
                    title = "ADB reverse route missing",
                    body = "USB mode cannot reach the Mac because the Android-to-Mac reverse route for TCP 54321 is missing, refused, or stale.",
                    action = "Reconnect or authorize the Android device, use the Mac app USB repair action to restore the reverse route, then retry.",
                ),
                ExpectedContract(
                    code = "usb_disconnected",
                    title = "USB device disconnected",
                    body = "The Android device is no longer reachable over the authorized USB debugging transport, so the client cannot use the local stream route.",
                    action = "Reconnect the cable, unlock and authorize the phone, wait for the Mac app to repair USB routing, then retry.",
                ),
                ExpectedContract(
                    code = "lan_route_unavailable",
                    title = "LAN route unavailable",
                    body = "Trusted LAN cannot route from the Android device to the saved Mac address and port on the same private network.",
                    action = "Reconnect both devices to the same trusted Wi-Fi, disable VPN or guest isolation, verify the saved Mac address and port, then reconnect.",
                ),
                ExpectedContract(
                    code = "tcp_54321_unavailable",
                    title = "TCP 54321 unavailable",
                    body = "The Host is not reachable on TCP port 54321 because the listener is absent, failed to start, or the port is occupied.",
                    action = "Start or restart Vibe Screen on the Mac. If another process is listening on TCP 54321, stop it and restart Vibe Screen.",
                ),
                ExpectedContract(
                    code = "stale_epoch_or_session_errors",
                    title = "Stale session epoch",
                    body = "The client rejected data from an older Protocol v1 session or configuration epoch to protect the current stream state.",
                    action = "Reconnect for a fresh session epoch; if it repeats, update both devices and collect logs instead of treating recovery as device-verified.",
                ),
            )
    }
}
