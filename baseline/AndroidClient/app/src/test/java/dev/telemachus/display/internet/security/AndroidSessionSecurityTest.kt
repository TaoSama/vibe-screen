package dev.telemachus.display.internet.security

import java.security.SecureRandom
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidSessionSecurityTest {
    @Test
    fun `missing authorized alias requires repairing without consuming session epoch`() {
        val expected = testIdentity("device-1", 1)
        val stateStore = authorizedState(expected.pairingIdentity)
        val identityStore = RecordingDeviceIdentityStore(existing = null)
        val security = AndroidSessionSecurity(expected.pairingIdentity.deviceId, stateStore, identityStore)

        val failure =
            assertThrows(IllegalStateException::class.java) {
                security.startSession(
                    pairingIdentifier = "pair-1",
                    expectedIdentity = expected.pairingIdentity,
                    authoritativeSessionEpoch = 7,
                    sharedSecret = ByteArray(32) { 1 },
                    bootstrapSecret = ByteArray(32) { 2 },
                    transcriptContext = ByteArray(32) { 3 },
                )
            }

        assertTrue(failure.message.orEmpty().contains("pair again"))
        assertEquals(emptyMap<String, Long>(), stateStore.state.sessionEpochHighWatermarks)
        assertEquals(1, identityStore.loadCount)
        assertEquals(0, identityStore.createCount)
    }

    @Test
    fun `mismatched authorized key is rejected before session epoch reservation`() {
        val expected = testIdentity("device-1", 1)
        val differentKey = testIdentity("device-1", 1)
        val forgedSameKeyId =
            AndroidDeviceIdentity(
                AndroidPublicIdentity(
                    deviceId = expected.pairingIdentity.deviceId,
                    keyId = expected.pairingIdentity.keyId,
                    keyEpoch = expected.pairingIdentity.keyEpoch,
                    signingPublicKey = differentKey.pairingIdentity.signingPublicKey,
                ),
                "forged-test-alias",
            )

        listOf(differentKey.androidIdentity, forgedSameKeyId).forEach { existing ->
            val stateStore = authorizedState(expected.pairingIdentity)
            val identityStore = RecordingDeviceIdentityStore(existing)
            val security = AndroidSessionSecurity(expected.pairingIdentity.deviceId, stateStore, identityStore)

            assertThrows(IllegalArgumentException::class.java) {
                security.startSession(
                    pairingIdentifier = "pair-1",
                    expectedIdentity = expected.pairingIdentity,
                    authoritativeSessionEpoch = 7,
                    sharedSecret = ByteArray(32) { 1 },
                    bootstrapSecret = ByteArray(32) { 2 },
                    transcriptContext = ByteArray(32) { 3 },
                )
            }

            assertEquals(emptyMap<String, Long>(), stateStore.state.sessionEpochHighWatermarks)
            assertEquals(0, identityStore.createCount)
        }
    }

    @Test
    fun `matching authorized identity uses existing key and reserves epoch`() {
        val expected = testIdentity("device-1", 1)
        val stateStore = authorizedState(expected.pairingIdentity)
        val identityStore = RecordingDeviceIdentityStore(expected.androidIdentity)
        val security = AndroidSessionSecurity(expected.pairingIdentity.deviceId, stateStore, identityStore)

        val active =
            security.startSession(
                pairingIdentifier = "pair-1",
                expectedIdentity = expected.pairingIdentity,
                authoritativeSessionEpoch = 7,
                sharedSecret = ByteArray(32) { 1 },
                bootstrapSecret = ByteArray(32) { 2 },
                transcriptContext = ByteArray(32) { 3 },
            )
        try {
            assertSame(expected.androidIdentity, active.identity)
            assertEquals(7L, active.sessionEpoch)
            assertEquals(
                7L,
                stateStore.state.sessionEpochHighWatermarks[
                    pairingSecurityScope(expected.pairingIdentity.deviceId, "pair-1")
                ],
            )
            assertEquals(1, identityStore.loadCount)
            assertEquals(0, identityStore.createCount)
        } finally {
            active.trafficKeys.close()
        }
    }

    private fun authorizedState(identity: InternetPairingIdentity) =
        RecordingSecurityStateStore(
            DurableSecurityState(
                identityEpochHighWatermark = identity.keyEpoch,
                authorizedIdentityEpoch = identity.keyEpoch,
                authorizedIdentityKeyId = identity.keyId,
            ),
        )

    private fun testIdentity(deviceId: String, epoch: Long): TestIdentity {
        val publicKey = publicPoint(generateEphemeral(SecureRandom()))
        val pairingIdentity =
            InternetPairingIdentity(
                deviceId = deviceId,
                keyId = pairingSha256(publicKey).toPairingHex(),
                keyEpoch = epoch,
                signingPublicKey = publicKey,
            )
        return TestIdentity(
            pairingIdentity,
            AndroidDeviceIdentity(
                AndroidPublicIdentity(deviceId, pairingIdentity.keyId, epoch, publicKey.copyOf()),
                "test-alias-${pairingIdentity.keyId}",
            ),
        )
    }
}

private data class TestIdentity(
    val pairingIdentity: InternetPairingIdentity,
    val androidIdentity: AndroidDeviceIdentity,
)

private class RecordingDeviceIdentityStore(
    var existing: AndroidDeviceIdentity?,
) : DeviceIdentityStore {
    var loadCount = 0
    var createCount = 0

    override fun loadExisting(deviceId: String, keyEpoch: Long): AndroidDeviceIdentity? {
        loadCount += 1
        return existing
    }

    override fun loadOrCreateForPairing(deviceId: String, keyEpoch: Long): AndroidDeviceIdentity {
        createCount += 1
        return checkNotNull(existing)
    }

    override fun delete(deviceId: String, keyEpoch: Long) {
        existing = null
    }
}

private class RecordingSecurityStateStore(
    initial: DurableSecurityState,
) : SecurityStateStore {
    var state = initial

    override fun load(): DurableSecurityState = state

    override fun persist(state: DurableSecurityState) {
        this.state = state
    }
}
