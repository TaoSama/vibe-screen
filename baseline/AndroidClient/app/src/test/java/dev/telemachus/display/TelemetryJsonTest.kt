package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class TelemetryJsonTest {
    @Test
    fun encodesOneMachineReadableEventPerLine() {
        val json =
            TelemetryJson.encode(
                event = "frame_dropped",
                timestampMs = 123L,
                fields = linkedMapOf("reason" to "old\nepoch", "count" to 2, "retryable" to true),
            )

        assertEquals(
            "{\"schema_version\":1,\"timestamp_ms\":123,\"event\":\"frame_dropped\",\"reason\":\"old\\nepoch\",\"count\":2,\"retryable\":true}",
            json,
        )
    }

    @Test
    fun rejectsReservedFieldsAndNonFiniteNumbers() {
        assertThrows(IllegalArgumentException::class.java) {
            TelemetryJson.encode("event", 1L, mapOf("event" to "replacement"))
        }
        assertThrows(IllegalArgumentException::class.java) {
            TelemetryJson.encode("event", 1L, mapOf("value" to Double.NaN))
        }
    }
}
