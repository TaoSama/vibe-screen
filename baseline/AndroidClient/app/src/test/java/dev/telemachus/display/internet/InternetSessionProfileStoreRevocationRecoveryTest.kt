package dev.telemachus.display.internet

import com.google.gson.JsonObject
import dev.telemachus.display.internet.security.generateEphemeral
import dev.telemachus.display.internet.security.pairingSha256
import dev.telemachus.display.internet.security.publicPoint
import dev.telemachus.display.internet.security.toPairingHex
import java.security.SecureRandom
import java.util.Base64
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class InternetSessionProfileStoreRevocationRecoveryTest {
    @Test
    fun `production retry preserves superseding pairing and resumes failed old delete`() {
        val preferences = MemoryInternetProfilePreferences()
        val secrets = MemoryInternetProfileSecretStore()
        val store = InternetSessionProfileStore(preferences, debuggable = false, secretStore = secrets)
        val pairTwoProfile = profile("pair-2", "session-2", 8)
        val pairTwoProfileSecret = store.profileSecretName(pairTwoProfile)
        val deferredSecret = "phase3.internet.profile.v1.deferred-pair-2"
        preferences.seed(InternetSessionProfileStore.PROFILE_KEY, InternetSessionProfileCodec.encodePublic(pairTwoProfile))
        preferences.seed(InternetSessionProfileStore.PAIRING_KEY, version2PairingBinding("pair-2", 8))
        preferences.seed(
            InternetSessionProfileStore.PENDING_REVOCATION_CLEANUP_KEY,
            PendingRevocationCleanupCodec.encode(PendingRevocationCleanup("pair-1", "device-1", 7)),
        )
        preferences.seed(InternetSessionProfileStore.DEFERRED_SECRET_CLEANUP_KEY, setOf(deferredSecret))
        secrets.persist(pairTwoProfileSecret, byteArrayOf(2))
        secrets.persist(deferredSecret, byteArrayOf(3))
        val pairingSecrets = mutableSetOf("pair-1", "pair-2")
        val identityKeys = mutableSetOf("device-1:7", "device-2:8")
        var failOldPairingDelete = true

        val first =
            store.retryPendingRevocationCleanup(
                deletePairingSecret = { pairingIdentifier ->
                    if (pairingIdentifier == "pair-1" && failOldPairingDelete) error("keystore busy")
                    pairingSecrets.remove(pairingIdentifier)
                },
                deleteIdentityKey = { deviceId, epoch -> identityKeys.remove("$deviceId:$epoch") },
            )

        assertEquals(setOf(RevocationCleanupStep.PAIRING_SECRET), first?.remainingSteps)
        assertEquals(
            setOf(RevocationCleanupStep.PAIRING_SECRET),
            persistedCleanup(preferences)?.remainingSteps,
        )
        assertPairTwoStatePreserved(store, preferences, secrets, pairTwoProfileSecret, deferredSecret)
        assertTrue("pair-1" in pairingSecrets)
        assertFalse("device-1:7" in identityKeys)

        failOldPairingDelete = false
        val restartedStore = InternetSessionProfileStore(preferences, debuggable = false, secretStore = secrets)
        val second =
            restartedStore.retryPendingRevocationCleanup(
                deletePairingSecret = { pairingSecrets.remove(it) },
                deleteIdentityKey = { deviceId, epoch -> identityKeys.remove("$deviceId:$epoch") },
            )

        assertTrue(requireNotNull(second).complete)
        assertNull(persistedCleanup(preferences))
        assertEquals(setOf("pair-2"), pairingSecrets)
        assertEquals(setOf("device-2:8"), identityKeys)
        assertPairTwoStatePreserved(restartedStore, preferences, secrets, pairTwoProfileSecret, deferredSecret)
    }

    @Test
    fun `production retry deletes all same owner state and clears marker`() {
        val preferences = MemoryInternetProfilePreferences()
        val secrets = MemoryInternetProfileSecretStore()
        val store = InternetSessionProfileStore(preferences, debuggable = false, secretStore = secrets)
        val pairOneProfile = profile("pair-1", "session-1", 7)
        val pairOneProfileSecret = store.profileSecretName(pairOneProfile)
        preferences.seed(InternetSessionProfileStore.PROFILE_KEY, InternetSessionProfileCodec.encodePublic(pairOneProfile))
        preferences.seed(InternetSessionProfileStore.PAIRING_KEY, version2PairingBinding("pair-1", 7))
        preferences.seed(
            InternetSessionProfileStore.PENDING_REVOCATION_CLEANUP_KEY,
            PendingRevocationCleanupCodec.encode(PendingRevocationCleanup("pair-1", "device-1", 7)),
        )
        secrets.persist(pairOneProfileSecret, byteArrayOf(1))
        val pairingSecrets = mutableSetOf("pair-1")
        val identityKeys = mutableSetOf("device-1:7")

        val result =
            store.retryPendingRevocationCleanup(
                deletePairingSecret = { pairingSecrets.remove(it) },
                deleteIdentityKey = { deviceId, epoch -> identityKeys.remove("$deviceId:$epoch") },
            )

        assertTrue(requireNotNull(result).complete)
        assertTrue(pairingSecrets.isEmpty())
        assertTrue(identityKeys.isEmpty())
        assertNull(preferences.getString(InternetSessionProfileStore.PROFILE_KEY, null))
        assertNull(preferences.getString(InternetSessionProfileStore.PAIRING_KEY, null))
        assertNull(preferences.getString(InternetSessionProfileStore.PENDING_REVOCATION_CLEANUP_KEY, null))
        assertNull(secrets.load(pairOneProfileSecret))
    }

    private fun assertPairTwoStatePreserved(
        store: InternetSessionProfileStore,
        preferences: MemoryInternetProfilePreferences,
        secrets: MemoryInternetProfileSecretStore,
        profileSecret: String,
        deferredSecret: String,
    ) {
        assertEquals("pair-2", store.loadPublicProfile()?.pairingIdentifier)
        assertEquals("pair-2", store.verifiedPairingIdentifier())
        assertNotNull(secrets.load(profileSecret))
        assertNotNull(secrets.load(deferredSecret))
        assertEquals(
            setOf(deferredSecret),
            preferences.getStringSet(InternetSessionProfileStore.DEFERRED_SECRET_CLEANUP_KEY, emptySet()),
        )
    }

    private fun persistedCleanup(preferences: MemoryInternetProfilePreferences): PendingRevocationCleanup? =
        preferences
            .getString(InternetSessionProfileStore.PENDING_REVOCATION_CLEANUP_KEY, null)
            ?.let(PendingRevocationCleanupCodec::decode)

    private fun profile(pairingIdentifier: String, sessionId: String, epoch: Long) =
        StoredInternetSessionProfile(
            pairingIdentifier = pairingIdentifier,
            pinnedHostId = "host-$pairingIdentifier",
            pinnedDeviceId = "device-${pairingIdentifier.removePrefix("pair-")}",
            leaseDeviceKeyId = "device-key-$pairingIdentifier",
            signalingUrl = "https://signal.example.test",
            signalingSessionId = sessionId,
            authoritativeSessionEpoch = epoch,
            hostIdentityEpoch = epoch,
            deviceIdentityEpoch = epoch,
            expiresAtUnixSeconds = 4_102_444_800,
            transcriptContext = ByteArray(32) { 1 },
            protocolSessionId = sessionId.toByteArray(),
            iceServerUrls = listOf(listOf("stun:stun.example.test:3478")),
            allowInsecureForTesting = false,
            leaseHostKeyId = "lease-key-$pairingIdentifier",
            leaseSignature = byteArrayOf(1),
        )

    private fun version2PairingBinding(pairingIdentifier: String, epoch: Long): String {
        val hostSigningPublicKey = publicPoint(generateEphemeral(SecureRandom()))
        val localSigningPublicKey = publicPoint(generateEphemeral(SecureRandom()))
        val localDeviceId = "device-${pairingIdentifier.removePrefix("pair-")}"
        return JsonObject().apply {
            addProperty("version", 2)
            addProperty("pairing_id", pairingIdentifier)
            addProperty("host_device_id", "host-$pairingIdentifier")
            addProperty("host_key_id", pairingSha256(hostSigningPublicKey).toPairingHex())
            addProperty("host_identity_epoch", epoch)
            addProperty("host_signature_algorithm", "ECDSA_P256_SHA256")
            addProperty("host_signing_public_key", Base64.getEncoder().encodeToString(hostSigningPublicKey))
            addProperty("local_device_id", localDeviceId)
            addProperty("local_key_id", pairingSha256(localSigningPublicKey).toPairingHex())
            addProperty("local_identity_epoch", epoch)
            addProperty("local_signature_algorithm", "ECDSA_P256_SHA256")
            addProperty("local_signing_public_key", Base64.getEncoder().encodeToString(localSigningPublicKey))
            addProperty("session_context", Base64.getEncoder().encodeToString(ByteArray(32) { 1 }))
        }.toString()
    }
}

internal class MemoryInternetProfilePreferences : InternetProfilePreferences {
    private val values = mutableMapOf<String, Any>()

    override fun getString(key: String, defaultValue: String?): String? =
        when (val value = values[key]) {
            null -> defaultValue
            is String -> value
            else -> throw ClassCastException(key)
        }

    @Suppress("UNCHECKED_CAST")
    override fun getStringSet(key: String, defaultValue: Set<String>?): Set<String>? =
        when (val value = values[key]) {
            null -> defaultValue
            is Set<*> -> (value as Set<String>).toSet()
            else -> throw ClassCastException(key)
        }

    override fun edit(): InternetProfilePreferencesEditor = Editor()

    fun seed(key: String, value: Any) {
        values[key] = if (value is Set<*>) value.toSet() else value
    }

    private inner class Editor : InternetProfilePreferencesEditor {
        private val updates = linkedMapOf<String, Any>()
        private val removals = mutableSetOf<String>()

        override fun putString(key: String, value: String): InternetProfilePreferencesEditor = apply {
            updates[key] = value
            removals -= key
        }

        override fun putStringSet(key: String, value: Set<String>): InternetProfilePreferencesEditor = apply {
            updates[key] = value.toSet()
            removals -= key
        }

        override fun remove(key: String): InternetProfilePreferencesEditor = apply {
            removals += key
            updates -= key
        }

        override fun commit(): Boolean {
            removals.forEach(values::remove)
            values.putAll(updates)
            return true
        }
    }
}

internal class MemoryInternetProfileSecretStore : InternetProfileSecretStore {
    private val values = mutableMapOf<String, ByteArray>()
    var persistCount = 0
        private set
    val entryCount: Int
        get() = values.size

    override fun persist(name: String, secret: ByteArray) {
        values[name] = secret.copyOf()
        persistCount += 1
    }

    override fun load(name: String): ByteArray? = values[name]?.copyOf()

    override fun delete(name: String) {
        values.remove(name)
    }

    fun resetPersistCount() {
        persistCount = 0
    }
}
