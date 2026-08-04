package dev.telemachus.display.internet

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WebRtcDataChannelProtocolTest {
    @Test
    fun latestFrameSlotDropsStalePendingPacket() {
        val slot = LatestFrameSlot()
        slot.replace(byteArrayOf(1))
        slot.replace(byteArrayOf(2))

        assertArrayEquals(byteArrayOf(2), slot.take())
        assertNull(slot.take())
    }

    @Test
    fun latestFrameSlotOwnsPayloadCopy() {
        val payload = byteArrayOf(7)
        val slot = LatestFrameSlot()
        slot.replace(payload)
        payload[0] = 9

        assertArrayEquals(byteArrayOf(7), slot.take())
    }
}
