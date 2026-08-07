package dev.telemachus.display.internet.security

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficKeyDerivationZeroizationTest {
    @Test
    fun `initial derivation preserves fixture and zeroizes every owned temporary`() {
        val observed = mutableListOf<ByteArray>()
        val keys =
            TrafficKeyDerivation.initial(
                sharedSecret = (1..32).map(Int::toByte).toByteArray(),
                bootstrapSecret = (32..63).map(Int::toByte).toByteArray(),
                context = "d6f7dfe489e792765bcabd79578ec8d1eb95891a459a8414dfcf668a592dd670".hex(),
                observer = SensitiveBufferObserver { _, buffer -> observed += buffer },
            )

        assertEquals("d249fc90df874566874890c85690ec42cdb979fa1cf7601ce112f7f261b88eda", keys.keyId)
        assertEquals(
            "2813943a29749dde00d152db6822da75c742819cc0ada7d0f71c597123531c70" +
                "88f8b6f39161e266db1b899871e7505a3675f9a7c5c88c213b91042ebd3a1244" +
                "cf62a7f3926e10308e0402d5e51397afc1c6d666dd2dc6a856bf2ebd0106307f3" +
                "f014c1e536fdd26670c84a0737526b2fc6052ca0b08be2e5d5197fc126e4c46",
            listOf(keys.hostControl, keys.deviceControl, keys.hostMedia, keys.deviceMedia).joinToString("") { it.toHex() },
        )
        assertTrue(observed.isNotEmpty())
        assertTrue(observed.all(ByteArray::isZeroized))

        keys.close()
        assertTrue(listOf(keys.hostControl, keys.deviceControl, keys.hostMedia, keys.deviceMedia).all(ByteArray::isZeroized))
    }

    @Test
    fun `derivation failure zeroizes every allocated temporary`() {
        val observed = mutableListOf<ByteArray>()
        val observer =
            SensitiveBufferObserver { label, buffer ->
                observed += buffer
                if (label == "hkdf-block-2") throw InjectedFailure()
            }

        assertThrows(InjectedFailure::class.java) {
            TrafficKeyDerivation.initial(
                sharedSecret = ByteArray(32) { 1 },
                bootstrapSecret = ByteArray(32) { 2 },
                context = ByteArray(32) { 3 },
                observer = observer,
            )
        }

        assertTrue(observed.isNotEmpty())
        assertTrue(observed.all(ByteArray::isZeroized))
    }

    private class InjectedFailure : RuntimeException()
}

private fun ByteArray.isZeroized(): Boolean = all { it == 0.toByte() }

private fun String.hex(): ByteArray = chunked(2).map { it.toInt(16).toByte() }.toByteArray()

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
