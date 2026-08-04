package dev.telemachus.display.protocol

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException

class ProtocolUpgradeTest {
    @Test
    fun offerAndAckSelectV1() {
        val output = ByteArrayOutputStream()
        ProtocolUpgrade.writeOffer(output)
        assertArrayEquals(byteArrayOf(0x0d), output.toByteArray())
        assertEquals(
            ProtocolUpgrade.Result.V1,
            ProtocolUpgrade.classify(0x0d, ByteArrayInputStream(byteArrayOf(0x01))),
        )
    }

    @Test
    fun timeoutFallsBackWithoutBufferedByte() {
        assertEquals(
            ProtocolUpgrade.Result.Legacy(null),
            ProtocolUpgrade.classify(null, ByteArrayInputStream(byteArrayOf())),
        )
    }

    @Test
    fun legacyFirstByteIsReturnedUnchanged() {
        assertEquals(
            ProtocolUpgrade.Result.Legacy(1),
            ProtocolUpgrade.classify(1, ByteArrayInputStream(byteArrayOf(9))),
        )
    }

    @Test
    fun malformedAcknowledgementFailsClosed() {
        assertThrows(IOException::class.java) {
            ProtocolUpgrade.classify(0x0d, ByteArrayInputStream(byteArrayOf(2)))
        }
    }
}
