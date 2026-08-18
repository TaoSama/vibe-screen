package dev.telemachus.display

import com.google.protobuf.ByteString
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class WakeHostTest {
    @Test
    fun magicPacketRepeatsTargetMacAndAppendsSecureOnPassword() {
        val mac = mac(0x01, 0x23, 0x45, 0x67, 0x89, 0xab)
        val password = mac(0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff)

        val packet = WakeHostMagicPacket.build(mac, password)

        assertEquals(WakeHostMagicPacket.BASE_PACKET_BYTES + WakeHostMagicPacket.SECURE_ON_PASSWORD_BYTES, packet.size)
        assertTrue(packet.take(6).all { it == 0xff.toByte() })
        repeat(16) { index ->
            assertArrayEquals(mac.toByteArray(), packet.copyOfRange(6 + index * 6, 12 + index * 6))
        }
        assertArrayEquals(password.toByteArray(), packet.copyOfRange(102, 108))
    }

    @Test
    fun magicPacketRejectsInvalidMacAndSecureOnPassword() {
        assertFailure(WakeHostRequestFailure.INVALID_MAC_ADDRESS) {
            WakeHostMagicPacket.build(ByteString.EMPTY)
        }
        assertFailure(WakeHostRequestFailure.INVALID_MAC_ADDRESS) {
            WakeHostMagicPacket.build(ByteString.copyFrom(ByteArray(6)))
        }
        assertFailure(WakeHostRequestFailure.INVALID_MAC_ADDRESS) {
            WakeHostMagicPacket.build(ByteString.copyFrom(ByteArray(6) { 0xff.toByte() }))
        }
        assertFailure(WakeHostRequestFailure.INVALID_SECURE_ON_PASSWORD) {
            WakeHostMagicPacket.build(mac(1, 2, 3, 4, 5, 6), ByteString.copyFrom(byteArrayOf(1, 2, 3)))
        }
    }

    @Test
    fun decisionDefaultsToDenyAndAllowsExplicitPolicy() {
        val request =
            WakeHostRequestContext(
                requestId = ByteString.copyFrom(byteArrayOf(0x42)),
                targetMacAddress = mac(1, 2, 3, 4, 5, 6),
            )

        assertFailure(WakeHostRequestFailure.POLICY_DENIED) { WakeHostDecision.magicPacket(request) }

        assertEquals(
            WakeHostMagicPacket.BASE_PACKET_BYTES,
            WakeHostDecision.magicPacket(request, StaticWakeHostPolicy(true)).size,
        )
    }

    @Test
    fun decisionRejectsEmptyRequestIdBeforePolicy() {
        val request =
            WakeHostRequestContext(
                requestId = ByteString.EMPTY,
                targetMacAddress = mac(1, 2, 3, 4, 5, 6),
            )

        assertFailure(WakeHostRequestFailure.INVALID_REQUEST_ID) {
            WakeHostDecision.magicPacket(request, StaticWakeHostPolicy(true))
        }
    }

    private fun assertFailure(
        expected: WakeHostRequestFailure,
        block: () -> Unit,
    ) {
        val failure = assertThrows(WakeHostRequestException::class.java, block)
        assertEquals(expected, failure.failure)
    }

    private fun mac(vararg bytes: Int): ByteString =
        ByteString.copyFrom(bytes.map { it.toByte() }.toByteArray())
}
