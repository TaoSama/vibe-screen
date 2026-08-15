package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class StreamClientEndpointTest {
    @Test
    fun actualPortRetainsSessionEndpoint() {
        val client = StreamClient("127.0.0.1", 60_000)

        assertEquals(60_000, client.actualPort)
    }
}
