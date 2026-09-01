package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class StreamClientReconnectBudgetContractTest {
    @Test
    fun heartbeatTimeoutLeavesBudgetForFirstReconnectWithinThreeSeconds() {
        val source = streamClientSource()
        val pollIntervalMs = constantLong(source, "HEARTBEAT_POLL_INTERVAL_MS")
        val timeoutMs = constantLong(source, "HEARTBEAT_TIMEOUT_MS")

        assertTrue(
            "heartbeat timeout $timeoutMs ms must leave room for the first reconnect backoff under 3s",
            timeoutMs <= HEARTBEAT_TIMEOUT_BUDGET_MS,
        )
        assertTrue(
            "heartbeat timeout must exceed the socket poll interval",
            timeoutMs > pollIntervalMs,
        )
        assertTrue(
            "heartbeat timeout plus maximum first-attempt jitter must stay within the reconnect gate",
            timeoutMs + FIRST_RECONNECT_MAX_DELAY_MS <= RECONNECT_GATE_MS,
        )
    }

    private fun streamClientSource(): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            STREAM_CLIENT_PATHS
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("StreamClient.kt not found from " + System.getProperty("user.dir"))
    }

    private fun constantLong(source: String, name: String): Long {
        val match =
            Regex("private const val " + Regex.escape(name) + " = ([0-9_]+)L?")
                .find(source)
                ?: error("constant not found: $name")
        return match.groupValues[1].replace("_", "").toLong()
    }

    private companion object {
        const val RECONNECT_GATE_MS = 3_000L
        const val HEARTBEAT_TIMEOUT_BUDGET_MS = 2_000L
        const val FIRST_RECONNECT_MAX_DELAY_MS = 600L

        val STREAM_CLIENT_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/StreamClient.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/StreamClient.kt",
            )
    }
}
