package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HeartbeatTelemetryReporterTest {
    @Test
    fun emitsSessionWireModeAndSourceThenThrottlesUntilIntervalExpires() {
        val reporter = HeartbeatTelemetryReporter(intervalNs = 1_000L)
        val events = mutableListOf<HeartbeatTelemetryEvent>()

        assertTrue(
            reporter.record(
                nowNs = 100L,
                sessionEpoch = 7L,
                wireMode = "v1",
                source = HeartbeatTelemetrySource.CONTROL,
                emit = events::add,
            ),
        )
        assertFalse(
            reporter.record(
                nowNs = 900L,
                sessionEpoch = 8L,
                wireMode = "legacy",
                source = HeartbeatTelemetrySource.LEGACY,
                emit = events::add,
            ),
        )
        assertTrue(
            reporter.record(
                nowNs = 1_100L,
                sessionEpoch = 8L,
                wireMode = "legacy",
                source = HeartbeatTelemetrySource.BULK,
                emit = events::add,
            ),
        )

        assertEquals(2, events.size)
        assertEquals(mapOf("session_epoch" to 7L, "wire_mode" to "v1", "source" to "control"), events[0].fields())
        assertEquals(mapOf("session_epoch" to 8L, "wire_mode" to "legacy", "source" to "bulk"), events[1].fields())
    }

    @Test
    fun resetAllowsFirstHeartbeatOfNewSessionToEmitImmediately() {
        val reporter = HeartbeatTelemetryReporter(intervalNs = 1_000L)
        val events = mutableListOf<HeartbeatTelemetryEvent>()

        assertTrue(reporter.record(100L, 1L, "legacy", HeartbeatTelemetrySource.LEGACY, events::add))
        assertFalse(reporter.record(200L, 1L, "legacy", HeartbeatTelemetrySource.LEGACY, events::add))

        reporter.reset()

        assertTrue(reporter.record(201L, 2L, "v1", HeartbeatTelemetrySource.AUDIO, events::add))
        assertEquals(2, events.size)
        assertEquals(mapOf("session_epoch" to 2L, "wire_mode" to "v1", "source" to "audio"), events.last().fields())
    }
}
