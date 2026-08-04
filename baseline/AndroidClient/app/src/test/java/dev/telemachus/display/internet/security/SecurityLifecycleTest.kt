package dev.telemachus.display.internet.security

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class SecurityLifecycleTest {
    @Test
    fun sessionEpochIsPersistedBeforeReturn() {
        val store = MemoryStore()
        assertEquals(7, SecurityLifecycle(store).reserveSessionEpoch(7))
        assertEquals(11, SecurityLifecycle(store).reserveSessionEpoch(11))
        assertEquals(11, store.state.sessionEpoch)
        assertThrows(IllegalArgumentException::class.java) { SecurityLifecycle(store).reserveSessionEpoch(11) }
        assertThrows(IllegalArgumentException::class.java) { SecurityLifecycle(store).reserveSessionEpoch(10) }
    }

    @Test
    fun nonceDoesNotRepeatAcrossRestart() {
        val store = MemoryStore()
        assertArrayEquals(
            "000000010000000000000001".hex(),
            SecurityLifecycle(store).reserveNonce(channel = 1, senderRole = 1, keyEpoch = 4),
        )
        assertArrayEquals(
            "000000010000000000000002".hex(),
            SecurityLifecycle(store).reserveNonce(channel = 1, senderRole = 1, keyEpoch = 4),
        )
    }

    @Test
    fun revocationFailsClosedAcrossRestart() {
        val store = MemoryStore()
        SecurityLifecycle(store).applyRevocation(8)
        assertThrows(IllegalStateException::class.java) { SecurityLifecycle(store).reserveSessionEpoch(9) }
        assertThrows(IllegalArgumentException::class.java) { SecurityLifecycle(store).applyRevocation(8) }
    }

    @Test
    fun persistenceFailureNeverReleasesReservedValue() {
        val store = MemoryStore().apply { failPersist = true }
        assertThrows(IllegalStateException::class.java) { SecurityLifecycle(store).reserveSessionEpoch(1) }
        assertEquals(0, store.state.sessionEpoch)
        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(store).reserveNonce(channel = 1, senderRole = 1, keyEpoch = 1)
        }
        assertEquals(emptyMap<String, Long>(), store.state.nonceHighWatermarks)
        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(store).consumeRotationNonceHash(ByteArray(32) { 1 })
        }
        assertEquals(emptySet<String>(), store.state.usedRotationNonceHashes)
    }

    @Test
    fun rotationNonceTombstoneMatchesGoAndSurvivesRestart() {
        val identity =
            AndroidPublicIdentity(
                deviceId = "host",
                keyId = "a".repeat(64),
                keyEpoch = 1,
                signingPublicKey = byteArrayOf(0x04) + (0 until 64).map(Int::toByte).toByteArray(),
            )
        val hash = identity.rotationNonceHash((0 until 16).map(Int::toByte).toByteArray())
        assertEquals("d5f91aab0a4c23c4c710b25146f2350906ea19fac62c79dda0f61fda6f4308c9", hash.toHex())

        val store = MemoryStore()
        SecurityLifecycle(store).consumeRotationNonceHash(hash)
        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).consumeRotationNonceHash(hash)
        }
        assertEquals(setOf(hash.toHex()), store.state.usedRotationNonceHashes)
    }

    @Test
    fun initialDerivationMatchesCrossPlatformFixedVector() {
        val keys =
            TrafficKeyDerivation.initial(
                sharedSecret = (1..32).map(Int::toByte).toByteArray(),
                bootstrapSecret = (32..63).map(Int::toByte).toByteArray(),
                context = "d6f7dfe489e792765bcabd79578ec8d1eb95891a459a8414dfcf668a592dd670".hex(),
            )

        assertEquals("d249fc90df874566874890c85690ec42cdb979fa1cf7601ce112f7f261b88eda", keys.keyId)
        assertEquals(
            "2813943a29749dde00d152db6822da75c742819cc0ada7d0f71c597123531c70" +
                "88f8b6f39161e266db1b899871e7505a3675f9a7c5c88c213b91042ebd3a1244" +
                "cf62a7f3926e10308e0402d5e51397afc1c6d666dd2dc6a856bf2ebd0106307f3" +
                "f014c1e536fdd26670c84a0737526b2fc6052ca0b08be2e5d5197fc126e4c46",
            keys.combined().toHex(),
        )
    }

    @Test
    fun rotationAdvancesExactlyOneEpochAndDestroysOldKeyCopies() {
        val current =
            TrafficKeyDerivation.initial(
                sharedSecret = (1..32).map(Int::toByte).toByteArray(),
                bootstrapSecret = (32..63).map(Int::toByte).toByteArray(),
                context = ByteArray(32) { 7 },
            )
        val rotated = TrafficKeyDerivation.rotate(current, 2, (64..79).map(Int::toByte).toByteArray())
        assertEquals(2, rotated.keyEpoch)
        assertNotEquals(current.keyId, rotated.keyId)
        assertEquals(4, listOf(rotated.hostControl, rotated.deviceControl, rotated.hostMedia, rotated.deviceMedia).map { it.toHex() }.toSet().size)
        assertThrows(IllegalArgumentException::class.java) {
            TrafficKeyDerivation.rotate(current, 3, (64..79).map(Int::toByte).toByteArray())
        }

        current.close()
        assertEquals(setOf(0.toByte()), current.combined().toSet())
    }

    @Test
    fun trafficPacketAesGcmAuthenticatesHeader() {
        val key = ByteArray(32)
        val nonce = ByteArray(12)
        val header = "header".toByteArray()
        val knownCiphertext = TrafficPacketCryptography.seal(byteArrayOf(), key, nonce, byteArrayOf())
        assertEquals("530f8afbc74536b9a963b4f1c4cb738b", knownCiphertext.toHex())
        val ciphertext = TrafficPacketCryptography.seal(byteArrayOf(), key, nonce, header)
        assertArrayEquals(byteArrayOf(), TrafficPacketCryptography.open(ciphertext, key, nonce, header))
        assertThrows(Exception::class.java) {
            TrafficPacketCryptography.open(ciphertext, key, nonce, "tampered".toByteArray())
        }
    }
}

private class MemoryStore : SecurityStateStore {
    var state = DurableSecurityState()
    var failPersist = false
    override fun load(): DurableSecurityState = state
    override fun persist(state: DurableSecurityState) {
        check(!failPersist) { "injected" }
        this.state = state
    }
}

private fun String.hex(): ByteArray = chunked(2).map { it.toInt(16).toByte() }.toByteArray()

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
