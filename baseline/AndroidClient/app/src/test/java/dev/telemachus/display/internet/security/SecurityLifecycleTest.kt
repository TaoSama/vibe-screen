package dev.telemachus.display.internet.security

import java.security.MessageDigest
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class SecurityLifecycleTest {
    private val pairingScopeA = pairingSecurityScope("device-a", "pairing-a")
    private val pairingScopeB = pairingSecurityScope("device-a", "pairing-b")

    @Test
    fun missingSecurityStateInitializesOnlyWithExplicitFreshInstallEvidence() {
        val deviceScope = deviceSecurityScope("device-a")

        assertThrows(IllegalStateException::class.java) {
            SecurityStatePreferenceCodec.decode(emptyMap<String, Any>(), deviceScope)
        }
        val initialized =
            SecurityStatePreferenceCodec.decode(
                emptyMap<String, Any>(),
                deviceScope,
                allowEmptyInitialization = true,
            )

        assertEquals(true, initialized.migratedFromLegacy)
        assertEquals(DurableSecurityState(), initialized.state)
    }

    @Test
    fun sessionEpochIsPersistedBeforeReturn() {
        val store = MemoryStore(authorizedState())
        assertEquals(7, SecurityLifecycle(store).reserveSessionEpoch(pairingScopeA, 1, 7))
        assertEquals(11, SecurityLifecycle(store).reserveSessionEpoch(pairingScopeA, 1, 11))
        assertEquals(11L, store.state.sessionEpochHighWatermarks[pairingScopeA])
        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).reserveSessionEpoch(pairingScopeA, 1, 11)
        }
        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).reserveSessionEpoch(pairingScopeA, 1, 10)
        }
    }

    @Test
    fun pairingScopesAreIndependentButSamePairingCannotReplayAcrossRestart() {
        val store = MemoryStore(authorizedState())
        val first = SecurityLifecycle(store)
        assertEquals(7, first.reserveSessionEpoch(pairingScopeA, 1, 7))
        assertEquals(1, SecurityLifecycle(store).reserveSessionEpoch(pairingScopeB, 1, 1))
        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).reserveSessionEpoch(pairingScopeA, 1, 7)
        }
        assertEquals(8, SecurityLifecycle(store).reserveSessionEpoch(pairingScopeA, 1, 8))
    }

    @Test
    fun deletedProfileCannotReimportLeaseAtPairingHighWatermark() {
        val store =
            MemoryStore(
                authorizedState(
                    sessionEpochHighWatermarks = mapOf(pairingScopeA to 7),
                ),
            )
        var secretPersisted = false
        var profilePersisted = false

        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).withFreshSessionEpochCandidate(pairingScopeA, 1, 7) {
                secretPersisted = true
                profilePersisted = true
            }
        }

        assertEquals(false, secretPersisted)
        assertEquals(false, profilePersisted)
        assertEquals(7L, store.state.sessionEpochHighWatermarks[pairingScopeA])
    }

    @Test
    fun nonceDoesNotRepeatAcrossRestart() {
        val store = MemoryStore(authorizedState())
        assertArrayEquals(
            "000000010000000000000001".hex(),
            SecurityLifecycle(store).reserveNonce(pairingScopeA, 1, channel = 1, senderRole = 1, keyEpoch = 4),
        )
        assertArrayEquals(
            "000000010000000000000002".hex(),
            SecurityLifecycle(store).reserveNonce(pairingScopeA, 1, channel = 1, senderRole = 1, keyEpoch = 4),
        )
        assertArrayEquals(
            "000000010000000000000001".hex(),
            SecurityLifecycle(store).reserveNonce(pairingScopeB, 1, channel = 1, senderRole = 1, keyEpoch = 4),
        )
    }

    @Test
    fun recordChannelsUseIndependentDurableNonceDomains() {
        val lifecycle = SecurityLifecycle(MemoryStore(authorizedState()))
        val firstHostNonceByChannel =
            (1..4).map { channel ->
                lifecycle.reserveNonce(pairingScopeA, 1, channel, senderRole = 1, keyEpoch = 1)
            }

        assertEquals(
            listOf(
                "000000010000000000000001",
                "000000020000000000000001",
                "000000030000000000000001",
                "000000040000000000000001",
            ),
            firstHostNonceByChannel.map(ByteArray::toHex),
        )
        assertArrayEquals(
            "000000030000000000000002".hex(),
            lifecycle.reserveNonce(pairingScopeA, 1, channel = 3, senderRole = 1, keyEpoch = 1),
        )
        assertArrayEquals(
            "000000030000000000000001".hex(),
            lifecycle.reserveNonce(pairingScopeA, 1, channel = 3, senderRole = 2, keyEpoch = 1),
        )
        assertArrayEquals(
            "000000030000000000000001".hex(),
            lifecycle.reserveNonce(pairingScopeA, 1, channel = 3, senderRole = 1, keyEpoch = 2),
        )
    }

    @Test
    fun revocationFailsClosedAcrossRestart() {
        val store = MemoryStore(authorizedState())
        SecurityLifecycle(store).applyRevocation(pairingScopeA, 1, 8)
        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(store).reserveSessionEpoch(pairingScopeA, 1, 9)
        }
        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(store).applyRevocation(pairingScopeA, 1, 8)
        }
    }

    @Test
    fun persistenceFailureNeverReleasesReservedValue() {
        val store = MemoryStore(authorizedState()).apply { failPersist = true }
        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(store).reserveSessionEpoch(pairingScopeA, 1, 1)
        }
        assertEquals(emptyMap<String, Long>(), store.state.sessionEpochHighWatermarks)
        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(store).reserveNonce(pairingScopeA, 1, channel = 1, senderRole = 1, keyEpoch = 1)
        }
        assertEquals(emptyMap<String, Long>(), store.state.nonceHighWatermarks)
        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(store).consumeRotationNonceHash(1, ByteArray(32) { 1 })
        }
        assertEquals(emptySet<String>(), store.state.usedRotationNonceHashes)
        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(store).reserveNextIdentityEpoch()
        }
        assertEquals(1L, store.state.identityEpochHighWatermark)
    }

    @Test
    fun identityEpochAdvancesAcrossRevocationReauthorizationAndRestart() {
        val store = MemoryStore()
        val initial = SecurityLifecycle(store)

        assertEquals(1, initial.reserveNextIdentityEpoch())
        assertThrows(IllegalStateException::class.java) { initial.requireAuthorizedIdentityKeyId(1) }
        initial.authorizeIdentityEpoch(1, identityKeyOne)
        assertEquals(identityKeyOne, initial.requireAuthorizedIdentityKeyId(1))

        initial.applyRevocation(pairingScopeA, 1, 8)
        assertThrows(IllegalStateException::class.java) { initial.requireAuthorizedIdentityKeyId(1) }

        val afterRevocation = SecurityLifecycle(store)
        assertEquals(2, afterRevocation.reserveNextIdentityEpoch())
        afterRevocation.authorizeIdentityEpoch(2, identityKeyTwo)
        assertEquals(identityKeyTwo, afterRevocation.requireAuthorizedIdentityKeyId(2))
        assertThrows(IllegalStateException::class.java) { afterRevocation.requireAuthorizedIdentityKeyId(1) }
        afterRevocation.applyRevocation(pairingScopeB, 2, 1)
        assertEquals(8L, store.state.revocationSequenceHighWatermarks[pairingScopeA])
        assertEquals(1L, store.state.revocationSequenceHighWatermarks[pairingScopeB])

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
        assertThrows(IllegalArgumentException::class.java) { lifecycle.authorizeIdentityEpoch(1, identityKeyOne) }
        lifecycle.authorizeIdentityEpoch(2, identityKeyTwo)

        assertEquals(3, SecurityLifecycle(store).reserveNextIdentityEpoch())
    }

    @Test
    fun repeatedAuthorizationOfCurrentEpochIsIdempotentButCannotClearRevocation() {
        val store = MemoryStore()
        val lifecycle = SecurityLifecycle(store)
        val identityEpoch = lifecycle.reserveNextIdentityEpoch()
        lifecycle.authorizeIdentityEpoch(identityEpoch, identityKeyOne)
        val persistedAfterAuthorization = store.persistCount

        SecurityLifecycle(store).authorizeIdentityEpoch(identityEpoch, identityKeyOne)

        assertEquals(persistedAfterAuthorization, store.persistCount)
        assertEquals(identityEpoch, store.state.authorizedIdentityEpoch)
        lifecycle.applyRevocation(pairingScopeA, identityEpoch, 1)
        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).authorizeIdentityEpoch(identityEpoch, identityKeyOne)
        }
        assertEquals(true, store.state.revoked)
    }

    @Test
    fun failedIdentityAuthorizationKeepsRevocationAndAuthorizedEpochDurable() {
        val store =
            MemoryStore(
                DurableSecurityState(
                    identityEpochHighWatermark = 2,
                    authorizedIdentityEpoch = 1,
                    authorizedIdentityKeyId = identityKeyOne,
                    revoked = true,
                ),
            )
        store.failPersist = true

        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(store).authorizeIdentityEpoch(2, identityKeyTwo)
        }
        assertEquals(1, store.state.authorizedIdentityEpoch)
        assertEquals(true, store.state.revoked)
    }

    @Test
    fun longMaxValueCannotPoisonMonotonicEpochs() {
        val initial =
            DurableSecurityState(
                sessionEpochHighWatermarks = mapOf(pairingScopeA to 7),
                revocationSequenceHighWatermarks = mapOf(pairingScopeA to 3),
                identityEpochHighWatermark = Long.MAX_VALUE,
                authorizedIdentityEpoch = 2,
            )
        val store = MemoryStore(initial)
        val lifecycle = SecurityLifecycle(store)

        assertThrows(IllegalArgumentException::class.java) {
            lifecycle.reserveSessionEpoch(pairingScopeA, 2, Long.MAX_VALUE)
        }
        assertThrows(IllegalArgumentException::class.java) {
            lifecycle.applyRevocation(pairingScopeA, 2, Long.MAX_VALUE)
        }
        assertThrows(IllegalStateException::class.java) { lifecycle.reserveNextIdentityEpoch() }
        assertThrows(IllegalArgumentException::class.java) {
            lifecycle.authorizeIdentityEpoch(Long.MAX_VALUE, identityKeyOne)
        }
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

        val store = MemoryStore(authorizedState())
        SecurityLifecycle(store).consumeRotationNonceHash(1, hash)
        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).consumeRotationNonceHash(1, hash)
        }
        assertEquals(setOf(hash.toHex()), store.state.usedRotationNonceHashes)
    }

    @Test
    fun legacyStateBindsOnceToOriginalIdentityAndSurvivesRestart() {
        val legacyNonceKey = "1:1:4"
        val store =
            MemoryStore(
                authorizedState(
                    usedRotationNonceHashes = setOf("a".repeat(64)),
                    legacySessionState =
                        LegacySessionSecurityState(
                            sessionEpoch = 7,
                            nonceHighWatermarks = mapOf(legacyNonceKey to 3),
                            ownerIdentityEpoch = 1,
                            revocationSequence = 0,
                            revoked = false,
                        ),
                ),
            )

        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).withFreshSessionEpochCandidate(pairingScopeA, 1, 7) { Unit }
        }
        assertEquals(null, store.state.legacySessionState)
        assertEquals(7L, store.state.sessionEpochHighWatermarks[pairingScopeA])
        assertArrayEquals(
            "000000010000000000000004".hex(),
            SecurityLifecycle(store).reserveNonce(pairingScopeA, 1, 1, 1, 4),
        )
        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).consumeRotationNonceHash(1, ByteArray(32) { 0xaa.toByte() })
        }
    }

    @Test
    fun legacyStateRemainsTombstonedWhileNewIdentityUsesAnotherPairing() {
        val legacy =
            LegacySessionSecurityState(
                sessionEpoch = 9,
                nonceHighWatermarks = emptyMap(),
                ownerIdentityEpoch = 1,
                revocationSequence = 0,
                revoked = false,
            )
        val store =
            MemoryStore(
                DurableSecurityState(
                    identityEpochHighWatermark = 2,
                    authorizedIdentityEpoch = 2,
                    legacySessionState = legacy,
                ),
            )
        assertEquals(1, SecurityLifecycle(store).reserveSessionEpoch(pairingScopeB, 2, 1))
        assertEquals(legacy, store.state.legacySessionState)
        assertEquals(1L, store.state.sessionEpochHighWatermarks[pairingScopeB])
        assertThrows(IllegalArgumentException::class.java) {
            SecurityLifecycle(store).reserveSessionEpoch(pairingScopeB, 2, 1)
        }
    }

    @Test
    fun newerIdentityReadDoesNotRewriteUnownedLegacyState() {
        val legacy =
            LegacySessionSecurityState(
                sessionEpoch = 9,
                nonceHighWatermarks = emptyMap(),
                ownerIdentityEpoch = 1,
                revocationSequence = 0,
                revoked = false,
            )
        val store =
            MemoryStore(
                DurableSecurityState(
                    identityEpochHighWatermark = 2,
                    authorizedIdentityEpoch = 2,
                    authorizedIdentityKeyId = identityKeyTwo,
                    legacySessionState = legacy,
                ),
            )

        SecurityLifecycle(store).withFreshSessionEpochCandidate(pairingScopeB, 2, 1) { Unit }

        assertEquals(0, store.persistCount)
        assertEquals(legacy, store.state.legacySessionState)
    }

    @Test
    fun legacyPreferencesMigrateOnceWithoutDroppingRevocationOrReplayState() {
        val deviceScope = deviceSecurityScope("device-a")
        val legacyValues =
            mapOf<String, Any>(
                "session_epoch" to 9L,
                "revocation_sequence" to 4L,
                "revoked" to true,
                "nonce.1:1:3" to 5L,
                "rotation_nonce_hashes" to setOf("b".repeat(64)),
                "identity_epoch_high_watermark" to 2L,
                "authorized_identity_epoch" to 2L,
            )

        val migrated = SecurityStatePreferenceCodec.decode(legacyValues, deviceScope)
        assertEquals(true, migrated.migratedFromLegacy)
        assertEquals(true, migrated.state.revoked)
        assertEquals(9L, migrated.state.legacySessionState?.sessionEpoch)
        assertEquals(5L, migrated.state.legacySessionState?.nonceHighWatermarks?.get("1:1:3"))
        assertEquals(4L, migrated.state.legacySessionState?.revocationSequence)
        assertEquals(setOf("b".repeat(64)), migrated.state.usedRotationNonceHashes)

        val encoded = SecurityStatePreferenceCodec.encode(migrated.state, deviceScope)
        assertEquals(3, encoded["schema_version"])
        assertEquals(false, "session_epoch" in encoded)
        assertEquals(false, "nonce.1:1:3" in encoded)
        val restarted = SecurityStatePreferenceCodec.decode(encoded, deviceScope)
        assertEquals(false, restarted.migratedFromLegacy)
        assertEquals(migrated.state, restarted.state)
    }

    @Test
    fun version2MigrationBackfillsAuthorizedIdentityKeyFromMatchingStoredIdentity() {
        val deviceId = "device-a"
        val deviceScope = deviceSecurityScope(deviceId)
        val identity = storedIdentity(deviceId, 1)
        val decoded = SecurityStatePreferenceCodec.decode(version2Preferences(deviceScope), deviceScope)

        val resolved =
            decoded.resolveAuthorizedIdentityKeyBinding(deviceId) { resolvedDeviceId, resolvedEpoch ->
                assertEquals(deviceId, resolvedDeviceId)
                assertEquals(1L, resolvedEpoch)
                identity
            }

        assertEquals(identity.keyId, resolved.authorizedIdentityKeyId)
        val encoded = SecurityStatePreferenceCodec.encode(resolved, deviceScope)
        assertEquals(3, encoded["schema_version"])
        assertEquals(identity.keyId, encoded["authorized_identity_key_id"])
    }

    @Test
    fun version2MigrationMakesSameEpochAuthorizationIdempotent() {
        val deviceId = "device-a"
        val deviceScope = deviceSecurityScope(deviceId)
        val identity = storedIdentity(deviceId, 1)
        val decoded = SecurityStatePreferenceCodec.decode(version2Preferences(deviceScope), deviceScope)
        val store = MemoryStore(decoded.resolveAuthorizedIdentityKeyBinding(deviceId) { _, _ -> identity })

        SecurityLifecycle(store).authorizeIdentityEpoch(1, identity.keyId)

        assertEquals(0, store.persistCount)
        assertEquals(identity.keyId, SecurityLifecycle(store).requireAuthorizedIdentityKeyId(1))
    }

    @Test
    fun version2MigrationRetainsMissingBindingAndRejectsMismatchedStoredIdentity() {
        val deviceId = "device-a"
        val deviceScope = deviceSecurityScope(deviceId)
        val decoded = SecurityStatePreferenceCodec.decode(version2Preferences(deviceScope), deviceScope)

        val missing = decoded.resolveAuthorizedIdentityKeyBinding(deviceId) { _, _ -> null }
        assertEquals(null, missing.authorizedIdentityKeyId)
        assertThrows(IllegalStateException::class.java) {
            SecurityLifecycle(MemoryStore(missing)).requireAuthorizedIdentityKeyId(1)
        }
        assertThrows(IllegalStateException::class.java) {
            decoded.resolveAuthorizedIdentityKeyBinding(deviceId) { _, _ -> storedIdentity("device-b", 1) }
        }
        assertThrows(IllegalStateException::class.java) {
            decoded.resolveAuthorizedIdentityKeyBinding(deviceId) { _, _ -> storedIdentity(deviceId, 2) }
        }
    }

    @Test
    fun versionedPreferencesRejectUnknownVersionDeviceScopeAndMalformedFields() {
        val deviceScope = deviceSecurityScope("device-a")
        val encoded =
            SecurityStatePreferenceCodec
                .encode(authorizedState(), deviceScope)
                .toMutableMap()

        assertThrows(IllegalStateException::class.java) {
            SecurityStatePreferenceCodec.decode(encoded + ("schema_version" to 4), deviceScope)
        }
        assertThrows(IllegalStateException::class.java) {
            SecurityStatePreferenceCodec.decode(encoded + ("unexpected" to 1L), deviceScope)
        }
        assertThrows(IllegalStateException::class.java) {
            SecurityStatePreferenceCodec.decode(encoded, deviceSecurityScope("device-b"))
        }
        assertThrows(IllegalStateException::class.java) {
            SecurityStatePreferenceCodec.decode(
                encoded + ("session.$pairingScopeA" to "7"),
                deviceScope,
            )
        }

        val revokedLegacyState =
            DurableSecurityState(
                revoked = true,
                identityEpochHighWatermark = 1,
                authorizedIdentityEpoch = 1,
                legacySessionState =
                    LegacySessionSecurityState(
                        sessionEpoch = 7,
                        nonceHighWatermarks = emptyMap(),
                        ownerIdentityEpoch = 1,
                        revocationSequence = 8,
                        revoked = true,
                    ),
            )
        val revokedEncoded = SecurityStatePreferenceCodec.encode(revokedLegacyState, deviceScope)
        assertThrows(IllegalStateException::class.java) {
            SecurityStatePreferenceCodec.decode(revokedEncoded + ("revoked" to false), deviceScope)
        }
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
            listOf(keys.hostControl, keys.deviceControl, keys.hostMedia, keys.deviceMedia).joinToString("") { it.toHex() },
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
        assertEquals(
            setOf(0.toByte()),
            listOf(current.hostControl, current.deviceControl, current.hostMedia, current.deviceMedia).flatMap(ByteArray::asIterable).toSet(),
        )
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

private fun authorizedState(
    sessionEpochHighWatermarks: Map<String, Long> = emptyMap(),
    usedRotationNonceHashes: Set<String> = emptySet(),
    legacySessionState: LegacySessionSecurityState? = null,
): DurableSecurityState =
    DurableSecurityState(
        sessionEpochHighWatermarks = sessionEpochHighWatermarks,
        usedRotationNonceHashes = usedRotationNonceHashes,
        identityEpochHighWatermark = 1,
        authorizedIdentityEpoch = 1,
        legacySessionState = legacySessionState,
    )

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

private fun version2Preferences(deviceScope: String): Map<String, Any> =
    SecurityStatePreferenceCodec
        .encode(
            DurableSecurityState(
                identityEpochHighWatermark = 1,
                authorizedIdentityEpoch = 1,
                authorizedIdentityKeyId = identityKeyOne,
            ),
            deviceScope,
        ).toMutableMap()
        .apply {
            this["schema_version"] = 2
            remove("authorized_identity_key_id")
        }

private fun storedIdentity(deviceId: String, keyEpoch: Long): AndroidPublicIdentity {
    val publicKey = byteArrayOf(0x04) + ByteArray(64) { (it + keyEpoch.toInt()).toByte() }
    return AndroidPublicIdentity(
        deviceId = deviceId,
        keyId = MessageDigest.getInstance("SHA-256").digest(publicKey).toHex(),
        keyEpoch = keyEpoch,
        signingPublicKey = publicKey,
    )
}

private val identityKeyOne = "1".repeat(64)
private val identityKeyTwo = "2".repeat(64)
