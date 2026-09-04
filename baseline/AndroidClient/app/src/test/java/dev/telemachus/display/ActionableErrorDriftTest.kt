package dev.telemachus.display

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.File
import java.net.ConnectException
import java.net.NoRouteToHostException
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

    @Test
    fun androidGuidanceContractsStayBoundToActualGuidanceOutput() {
        val statesByCode = loadActionableErrorGuidanceMatrix()

        EXPECTED_ANDROID_GUIDANCE_CONTRACT_CODES.forEach { code ->
            val state = requireNotNull(statesByCode[code]) { "Missing actionable contract $code" }
            val guidanceContract = requireNotNull(state.getAsJsonObject("android_guidance_contract")) {
                "Missing Android guidance contract for $code"
            }
            val guidance = guidanceFrom(guidanceContract)

            assertEquals(code, ConnectionFailureKind.valueOf(guidanceContract.get("kind").asString), guidance.kind)
            assertEquals(code, stringResourceId(guidanceContract.get("status_resource").asString), guidance.status.resourceId)
            assertEquals(code, stringResourceId(guidanceContract.get("message_resource").asString), guidance.message.resourceId)
            guidanceContract.get("message_prefix_resource")?.asString?.let { prefixResourceName ->
                val prefix = guidance.message.args.firstOrNull() as? ConnectionGuidanceText
                assertNotNull("$code must retain the nested message prefix", prefix)
                requireNotNull(prefix)
                assertEquals(code, stringResourceId(prefixResourceName), prefix.resourceId)
            }
            assertRecoveryActionIsWired(code, guidanceContract.get("recovery_button_action").asString)
        }
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

    private fun loadActionableErrorGuidanceMatrix(): Map<String, JsonObject> {
        val matrix = JsonParser.parseString(actionableErrorMatrixFile().readText()).asJsonObject
        val states = matrix.getAsJsonArray("states")
        return buildMap {
            states.forEach { element ->
                val state = element.asJsonObject
                if (!state.has("android_guidance_contract")) return@forEach
                val contract = state.getAsJsonObject("contract")
                val code = contract?.get("code")?.asString ?: state.get("id")?.asString ?: return@forEach
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

    private fun guidanceFrom(contract: JsonObject): ConnectionGuidance {
        val context =
            when (contract.get("context").asString) {
                "usb" -> ConnectionGuidanceContext.adb(54321, AdbTransportKind.USB)
                "lan" -> ConnectionGuidanceContext.trustedLan(54321)
                "internet" -> ConnectionGuidanceContext.internet()
                else -> error("Unknown Android guidance context: " + contract.get("context").asString)
            }
        val sample = contract.getAsJsonObject("sample_failure")
        return when (sample.get("source").asString) {
            "throwable" -> ConnectionGuidanceFactory.from(throwableFrom(sample), context)
            "session_failure" ->
                ConnectionGuidanceFactory.from(
                    SessionFailure.protocol(
                        SessionFailureKind.valueOf(sample.get("kind").asString),
                        sample.get("message").asString,
                    ),
                    context,
                )
            else -> error("Unknown Android guidance sample source: " + sample.get("source").asString)
        }
    }

    private fun throwableFrom(sample: JsonObject): Throwable =
        when (sample.get("type").asString) {
            "ConnectException" -> ConnectException(sample.get("message").asString)
            "NoRouteToHostException" -> NoRouteToHostException(sample.get("message").asString)
            else -> error("Unknown Android guidance throwable type: " + sample.get("type").asString)
        }

    private fun assertRecoveryActionIsWired(
        code: String,
        recoveryButtonAction: String,
    ) {
        val mainActivity = resourceSource("app/src/main/java/dev/telemachus/display/MainActivity.kt")
        val wirelessController = resourceSource("app/src/main/java/dev/telemachus/display/WirelessTabController.kt")
        val layout = resourceSource("app/src/main/res/layout/activity_main.xml")
        when (recoveryButtonAction) {
            "connectButton.try_again" -> {
                assertTrue(code, layout.contains("android:id=\"@+id/connectButton\""))
                assertTrue(code, mainActivity.contains("binding.connectButton.setOnClickListener"))
            }
            "wirelessReconnectButton.reconnect" -> {
                assertTrue(code, layout.contains("android:id=\"@+id/wirelessReconnectButton\""))
                assertTrue(code, mainActivity.contains("reconnectButton = binding.wirelessReconnectButton"))
                assertTrue(code, wirelessController.contains("views.reconnectButton.setOnClickListener"))
                assertTrue(code, wirelessController.contains("attemptAutoConnect(entry)"))
            }
            "internetConnectButton.fresh_session_retry" -> {
                assertTrue(code, layout.contains("android:id=\"@+id/internetConnectButton\""))
                assertTrue(code, mainActivity.contains("binding.internetConnectButton.setOnClickListener { connectInternet() }"))
            }
            else -> error("Unknown recovery button action: $recoveryButtonAction")
        }
    }

    private fun stringResourceId(name: String): Int =
        R.string::class.java.getDeclaredField(name).getInt(null)

    private fun resourceSource(path: String): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            val candidate = current.resolve(path)
            if (candidate.isFile) return candidate.readText()
            current = current.parentFile?.canonicalFile ?: current
        }
        error("resource not found: $path from " + System.getProperty("user.dir"))
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

        val EXPECTED_ANDROID_GUIDANCE_CONTRACT_CODES =
            setOf(
                "android-usb-host-not-running",
                "adb_reverse_missing",
                "usb_disconnected",
                "lan_route_unavailable",
                "stale_epoch_or_session_errors",
            )
    }
}
