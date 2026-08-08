package dev.telemachus.display.internet.security

import androidx.test.ext.junit.runners.AndroidJUnit4
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AndroidDeviceIdentityStoreInstrumentedTest {
    @Test
    fun missingAliasReadNeverRecreatesButPairingCreateStillWorks() {
        val store = AndroidDeviceIdentityStore()
        val deviceId = "identity-loss-${UUID.randomUUID()}"
        val epoch = 1L

        try {
            val original = store.loadOrCreateForPairing(deviceId, epoch)
            assertNotNull(store.loadExisting(deviceId, epoch))
            store.delete(deviceId, epoch)

            assertNull(store.loadExisting(deviceId, epoch))
            assertNull(store.loadExisting(deviceId, epoch))

            val replacement = store.loadOrCreateForPairing(deviceId, epoch)
            assertEquals(deviceId, replacement.publicIdentity.deviceId)
            assertEquals(epoch, replacement.publicIdentity.keyEpoch)
            assertTrue(replacement.signTranscriptDigest(ByteArray(32) { 7 }).isNotEmpty())
            assertNotNull(original.publicIdentity.keyId)
        } finally {
            store.delete(deviceId, epoch)
        }
    }
}
