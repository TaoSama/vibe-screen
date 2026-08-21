package dev.telemachus.display.internet.security

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertThrows
import org.junit.Test

class AdvancedChannelSecurityGateTest {
    @Test
    fun `audio and bulk reservations are owner bound and independently accounted`() {
        val owner = AdvancedChannelOwner(sessionId = "session-a", sessionEpoch = 4, generation = 7)
        val replacement = AdvancedChannelOwner(sessionId = "session-b", sessionEpoch = 5, generation = 8)
        val gate = gate(owner)

        val audio = gate.reserve(8, AdvancedChannelBinding.Audio("display-a", 11), owner)
        val bulk = gate.reserve(16, AdvancedChannelBinding.Bulk(ByteArray(16) { 1 }), owner)

        assertEquals(8, gate.bufferedBytes(SecurityChannel.AUDIO))
        assertEquals(16, gate.bufferedBytes(SecurityChannel.BULK))
        assertThrows(IllegalStateException::class.java) {
            gate.reserve(1, AdvancedChannelBinding.Audio("display-a", 11), owner)
        }
        assertThrows(IllegalStateException::class.java) {
            gate.reserve(1, AdvancedChannelBinding.Bulk(ByteArray(16) { 2 }), replacement)
        }

        gate.finish(audio)
        assertEquals(0, gate.bufferedBytes(SecurityChannel.AUDIO))
        assertEquals(16, gate.bufferedBytes(SecurityChannel.BULK))
        gate.replaceOwner(replacement)
        assertEquals(0, gate.bufferedBytes(SecurityChannel.BULK))
        assertThrows(IllegalStateException::class.java) { gate.finish(bulk) }
    }

    @Test
    fun `invalid owners bindings and payload sizes fail before admission`() {
        val owner = AdvancedChannelOwner(sessionId = "session-a", sessionEpoch = 1, generation = 1)
        val gate = gate(owner)

        assertThrows(IllegalArgumentException::class.java) {
            AdvancedChannelSecurityGate(AdvancedChannelOwner(sessionId = " ", sessionEpoch = 1, generation = 1))
        }
        assertThrows(IllegalArgumentException::class.java) {
            gate.reserve(0, AdvancedChannelBinding.Audio("display-a", 1), owner)
        }
        assertThrows(IllegalArgumentException::class.java) {
            gate.reserve(9, AdvancedChannelBinding.Audio("display-a", 1), owner)
        }
        assertThrows(IllegalArgumentException::class.java) {
            gate.reserve(1, AdvancedChannelBinding.Audio(" ", 1), owner)
        }
        assertThrows(IllegalArgumentException::class.java) {
            gate.reserve(1, AdvancedChannelBinding.Bulk(ByteArray(15)), owner)
        }
        assertThrows(IllegalArgumentException::class.java) {
            gate.replaceOwner(AdvancedChannelOwner(sessionId = "session-b", sessionEpoch = 0, generation = 1))
        }
    }

    @Test
    fun `bulk transfer identifier is copied on input and output`() {
        val transferId = ByteArray(16) { it.toByte() }
        val binding = AdvancedChannelBinding.Bulk(transferId)
        transferId.fill(99)

        assertArrayEquals(ByteArray(16) { it.toByte() }, binding.transferId)
        assertNotSame(binding.transferId, binding.transferId)
    }

    private fun gate(owner: AdvancedChannelOwner): AdvancedChannelSecurityGate =
        AdvancedChannelSecurityGate(
            initialOwner = owner,
            limits = AdvancedChannelSecurityGate.Limits(
                maximumAudioRecordBytes = 8,
                maximumAudioBacklogBytes = 8,
                maximumBulkRecordBytes = 16,
                maximumBulkBacklogBytes = 16,
            ),
        )
}
