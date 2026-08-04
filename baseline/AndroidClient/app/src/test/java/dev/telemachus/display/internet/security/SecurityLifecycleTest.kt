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
    fun deletedProfileCannotReimportLeaseAtDurableSessionHighWatermark() {
        val store = MemoryStore(DurableSecurityState(sessionEpoch = 7))
        var secretPersisted = false
        var profilePersisted = false

        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).withFreshSessionEpochCandidate(7) {
                secretPersisted = true
                profilePersisted = true
            }
        }

        assertEquals(false, secretPersisted)
        assertEquals(false, profilePersisted)
        assertEquals(7, store.state.sessionEpoch)
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
        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(store).reserveNextIdentityEpoch()
        }
        assertEquals(0, store.state.identityEpochHighWatermark)
    }

    @Test
    fun identityEpochAdvancesAcrossRevocationReauthorizationAndRestart() {
        val store = MemoryStore()
        val initial = SecurityLifecycle(store)

        assertEquals(1, initial.reserveNextIdentityEpoch())
        assertThrows(IllegalStateException::class.java) { initial.requireAuthorizedIdentityEpoch(1) }
        initial.authorizeIdentityEpoch(1)
        initial.requireAuthorizedIdentityEpoch(1)

        initial.applyRevocation(1)
        assertThrows(IllegalStateException::class.java) { initial.requireAuthorizedIdentityEpoch(1) }

        val afterRevocation = SecurityLifecycle(store)
        assertEquals(2, afterRevocation.reserveNextIdentityEpoch())
        afterRevocation.authorizeIdentityEpoch(2)
        afterRevocation.requireAuthorizedIdentityEpoch(2)
        assertThrows(IllegalStateException::class.java) { afterRevocation.requireAuthorizedIdentityEpoch(1) }

        assertEquals(3, SecurityLifecycle(store).reserveNextIdentityEpoch())
        assertEquals(3, store.state.identityEpochHighWatermark)
        assertEquals(2, store.state.authorizedIdentityEpoch)
    }

    @Test
    fun cancelledIdentityReservationIsBurnedAndCannotBeAuthorizedLater() {
        val store = MemoryStore()
        val lifecycle = SecurityLifecycle(store)

        assertEquals(1, lifecycle.reserveNextIdentityEpoch())
        assertEquals(2, lifecycle.reserveNextIdentityEpoch())
        assertThrows(IllegalArgumentException::class.java) { lifecycle.authorizeIdentityEpoch(1) }
        lifecycle.authorizeIdentityEpoch(2)

        assertEquals(3, SecurityLifecycle(store).reserveNextIdentityEpoch())
    }

    @Test
    fun repeatedAuthorizationOfCurrentEpochIsIdempotentButCannotClearRevocation() {
        val store = MemoryStore()
        val lifecycle = SecurityLifecycle(store)
        val identityEpoch = lifecycle.reserveNextIdentityEpoch()
        lifecycle.authorizeIdentityEpoch(identityEpoch)
        val persistedAfterAuthorization = store.persistCount

        SecurityLifecycle(store).authorizeIdentityEpoch(identityEpoch)

        assertEquals(persistedAfterAuthorization, store.persistCount)
        assertEquals(identityEpoch, store.state.authorizedIdentityEpoch)
        lifecycle.applyRevocation(1)
        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).authorizeIdentityEpoch(identityEpoch)
        }
        assertEquals(true, store.state.revoked)
    }

    @Test
    fun failedIdentityAuthorizationKeepsRevocationAndAuthorizedEpochDurable() {
        val store = MemoryStore(DurableSecurityState(identityEpochHighWatermark = 2, authorizedIdentityEpoch = 1, revoked = true))
        store.failPersist = true

        assertThrows(IllegalStateException::class.java) { SecurityLifecycle(store).authorizeIdentityEpoch(2) }
        assertEquals(1, store.state.authorizedIdentityEpoch)
        assertEquals(true, store.state.revoked)
    }

    @Test
    fun longMaxValueCannotPoisonMonotonicEpochs() {
        val initial =
            DurableSecurityState(
                sessionEpoch = 7,
                revocationSequence = 3,
                identityEpochHighWatermark = Long.MAX_VALUE,
                authorizedIdentityEpoch = 2,
            )
        val store = MemoryStore(initial)
        val lifecycle = SecurityLifecycle(store)

        assertThrows(IllegalArgumentException::class.java) { lifecycle.reserveSessionEpoch(Long.MAX_VALUE) }
        assertThrows(IllegalArgumentException::class.java) { lifecycle.applyRevocation(Long.MAX_VALUE) }
        assertThrows(IllegalStateException::class.java) { lifecycle.reserveNextIdentityEpoch() }
        assertThrows(IllegalArgumentException::class.java) { lifecycle.authorizeIdentityEpoch(Long.MAX_VALUE) }
        assertEquals(initial, store.state)
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

private class MemoryStore(
    initialState: DurableSecurityState = DurableSecurityState(),
) : SecurityStateStore {
    var state = initialState
    var failPersist = false
    var persistCount = 0
    override fun load(): DurableSecurityState = state
    override fun persist(state: DurableSecurityState) {
        check(!failPersist) { "injected" }
        this.state = state
        persistCount += 1
    }
}

private fun String.hex(): ByteArray = chunked(2).map { it.toInt(16).toByte() }.toByteArray()

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
