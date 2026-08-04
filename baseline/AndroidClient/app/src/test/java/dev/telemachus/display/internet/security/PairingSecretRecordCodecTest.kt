package dev.telemachus.display.internet.security

import java.nio.ByteBuffer
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class PairingSecretRecordCodecTest {
    @Test
    fun roundTripRetainsBothSecrets() {
        val shared = ByteArray(48) { it.toByte() }
        val bootstrap = ByteArray(32) { (it + 48).toByte() }
        val decoded = PairingSecretRecordCodec.decode(PairingSecretRecordCodec.encode(shared, bootstrap))
        try {
            assertArrayEquals(shared, decoded.sharedSecret)
            assertArrayEquals(bootstrap, decoded.bootstrapSecret)
        } finally {
            decoded.close()
        }
    }

    @Test
    fun rejectsTruncatedAndLengthConfusedRecords() {
        assertThrows(IllegalArgumentException::class.java) {
            PairingSecretRecordCodec.decode(byteArrayOf(1, 0, 0, 0, 1))
        }
        val invalidLength = ByteBuffer.allocate(5 + 33).put(1.toByte()).putInt(2).put(ByteArray(33)).array()
        assertThrows(IllegalArgumentException::class.java) {
            PairingSecretRecordCodec.decode(invalidLength)
        }
    }
}
