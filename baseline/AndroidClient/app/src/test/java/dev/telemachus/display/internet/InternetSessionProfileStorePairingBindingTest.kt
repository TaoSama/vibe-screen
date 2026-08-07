package dev.telemachus.display.internet

import com.google.gson.JsonArray
import com.google.gson.JsonNull
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dev.telemachus.display.internet.security.AndroidDeviceIdentity
import dev.telemachus.display.internet.security.AndroidPublicIdentity
import dev.telemachus.display.internet.security.AndroidSessionSecurity
import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import dev.telemachus.display.internet.security.DeviceIdentityStore
import dev.telemachus.display.internet.security.DurableSecurityState
import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.InternetPairingPublicMetadata
import dev.telemachus.display.internet.security.SecurityStateStore
import dev.telemachus.display.internet.security.generateEphemeral
import dev.telemachus.display.internet.security.pairingSecurityScope
import dev.telemachus.display.internet.security.pairingSha256
import dev.telemachus.display.internet.security.publicPoint
import dev.telemachus.display.internet.security.toPairingHex
import java.security.KeyPair
import java.security.SecureRandom
import java.security.Signature
import java.util.Base64
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class InternetSessionProfileStorePairingBindingTest {
    @Test
    fun `version two binding round trips full local identity through production store`() {
        val fixture = recordedFixture()
        val imported =
            fixture.store.import(
                signedLeaseJson(fixture, 7),
                fixture.factory,
                fixture.coordinator,
            )

        assertEquals(7L, imported.authoritativeSessionEpoch)
        val lease = requireNotNull(fixture.store.loadLease(forceRelay = false))
        assertEquals(fixture.localIdentity, lease.localIdentity)
        assertEquals(fixture.localIdentity.keyEpoch, lease.identityEpoch)
        val raw = requireNotNull(fixture.preferences.getString(InternetSessionProfileStore.PAIRING_KEY, null))
        val binding = JsonParser.parseString(raw).asJsonObject
        assertEquals(2, binding.get("version").asInt)
        assertEquals(fixture.localIdentity.keyId, binding.get("local_key_id").asString)
        assertEquals(fixture.localIdentity.signatureAlgorithm, binding.get("local_signature_algorithm").asString)
        assertEquals(
            fixture.localIdentity.signingPublicKey.toList(),
            Base64.getDecoder().decode(binding.get("local_signing_public_key").asString).toList(),
        )
    }

    @Test
    fun `tampered local key id public key and algorithm are rejected`() {
        val fixture = recordedFixture()
        val raw = requireNotNull(fixture.preferences.getString(InternetSessionProfileStore.PAIRING_KEY, null))
        val otherPublicKey = publicPoint(generateEphemeral(SecureRandom()))
        val mutations =
            listOf<(JsonObject) -> Unit>(
                { it.addProperty("local_key_id", "0".repeat(64)) },
                { it.addProperty("local_signing_public_key", Base64.getEncoder().encodeToString(otherPublicKey)) },
                { it.addProperty("local_signature_algorithm", "ECDSA_P384_SHA384") },
                { it.addProperty("local_identity_epoch", 1.5) },
                { it.addProperty("version", 2.0) },
            )

        mutations.forEach { mutate ->
            val binding = JsonParser.parseString(raw).asJsonObject.deepCopy()
            mutate(binding)
            fixture.preferences.seed(InternetSessionProfileStore.PAIRING_KEY, binding.toString())
            assertThrows(IllegalArgumentException::class.java) { fixture.store.hasVerifiedPairing() }
        }
    }

    @Test
    fun `legacy binding requires repairing without deleting credentials or creating identity`() {
        val fixture = recordedFixture()
        val legacy = legacyBinding(fixture)
        fixture.preferences.seed(InternetSessionProfileStore.PAIRING_KEY, legacy)
        fixture.secrets.persist("sentinel-credential", byteArrayOf(9))
        fixture.secrets.resetPersistCount()
        fixture.identityStore.resetCounts()
        val entryCount = fixture.secrets.entryCount

        assertTrue(fixture.store.hasVerifiedPairing())
        assertEquals(fixture.pairingIdentifier, fixture.store.verifiedPairingIdentifier())
        val failure =
            assertThrows(IllegalStateException::class.java) {
                fixture.store.import(
                    signedLeaseJson(fixture, 7),
                    fixture.factory,
                    fixture.coordinator,
                )
            }

        assertTrue(failure.message.orEmpty().contains("pair again"))
        assertEquals(0, fixture.identityStore.loadCount)
        assertEquals(0, fixture.identityStore.createCount)
        assertEquals(0, fixture.secrets.persistCount)
        assertEquals(entryCount, fixture.secrets.entryCount)
        assertNotNull(fixture.secrets.load("sentinel-credential"))
        assertEquals(legacy, fixture.preferences.getString(InternetSessionProfileStore.PAIRING_KEY, null))
        assertNull(fixture.preferences.getString(InternetSessionProfileStore.PROFILE_KEY, null))
    }

    @Test
    fun `missing identity alias fails factory closed without consuming authoritative epoch`() {
        val fixture = recordedFixture()
        fixture.identityStore.existing = null
        fixture.identityStore.resetCounts()
        val entryCount = fixture.secrets.entryCount

        val failure =
            assertThrows(IllegalStateException::class.java) {
                fixture.factory.create(
                    pairingIdentifier = fixture.pairingIdentifier,
                    sessionId = "session-7",
                    localRole = PeerRole.DEVICE,
                    expectedIdentity = fixture.localIdentity,
                    authoritativeSessionEpoch = 7,
                    transcriptContext = ByteArray(32) { 5 },
                    iceServers = listOf(IceServer(listOf("stun:stun.example.test"))),
                    signaling =
                        SignalingConfiguration(
                            baseUrl = "https://signal.example.test",
                            bearerToken = "device-token-with-at-least-32-characters",
                            role = PeerRole.DEVICE,
                        ),
                )
            }

        assertTrue(failure.message.orEmpty().contains("pair again"))
        assertEquals(emptyMap<String, Long>(), fixture.stateStore.state.sessionEpochHighWatermarks)
        assertEquals(1, fixture.identityStore.loadCount)
        assertEquals(0, fixture.identityStore.createCount)
        assertEquals(entryCount, fixture.secrets.entryCount)
    }

    @Test
    fun `production import rejects equal and stale pairing epochs before persistence`() {
        val fixture = recordedFixture()
        val pairingScope = pairingSecurityScope(fixture.localDeviceId, fixture.pairingIdentifier)
        fixture.stateStore.state =
            fixture.stateStore.state.copy(sessionEpochHighWatermarks = mapOf(pairingScope to 7))

        listOf(7L, 6L).forEach { candidate ->
            fixture.preferences.edit().remove(InternetSessionProfileStore.PROFILE_KEY).commit()
            fixture.secrets.resetPersistCount()

            assertThrows(IllegalArgumentException::class.java) {
                fixture.store.import(
                    signedLeaseJson(fixture, candidate),
                    fixture.factory,
                    fixture.coordinator,
                )
            }

            assertEquals(0, fixture.secrets.persistCount)
            assertNull(fixture.preferences.getString(InternetSessionProfileStore.PROFILE_KEY, null))
            assertEquals(7L, fixture.stateStore.state.sessionEpochHighWatermarks[pairingScope])
        }
    }

    @Test
    fun `expired signed lease is rejected before credential persistence`() {
        val fixture = recordedFixture(nowUnixSeconds = { 4_102_444_800 })
        fixture.secrets.resetPersistCount()

        val failure =
            assertThrows(IllegalArgumentException::class.java) {
                fixture.store.import(
                    signedLeaseJson(fixture, 7),
                    fixture.factory,
                    fixture.coordinator,
                )
            }

        assertTrue(failure.message.orEmpty().contains("expired"))
        assertEquals(0, fixture.secrets.persistCount)
        assertNull(fixture.preferences.getString(InternetSessionProfileStore.PROFILE_KEY, null))
    }

    private fun recordedFixture(
        nowUnixSeconds: () -> Long = { 2_000_000_000 },
    ): PairingStoreFixture {
        val pairingIdentifier = "pair-identity-loss"
        val localDeviceId = "device-1"
        val local = testIdentity(localDeviceId, 1)
        val hostKeyPair = generateEphemeral(SecureRandom())
        val hostPublicKey = publicPoint(hostKeyPair)
        val hostIdentity =
            InternetPairingIdentity(
                deviceId = "host-1",
                keyId = pairingSha256(hostPublicKey).toPairingHex(),
                keyEpoch = 1,
                signingPublicKey = hostPublicKey,
            )
        val metadata =
            InternetPairingPublicMetadata(
                pairingIdentifier = pairingIdentifier,
                expiresAtUnixSeconds = 4_102_444_800,
                hostIdentity = hostIdentity,
                deviceIdentity = local.pairingIdentity,
                deviceName = "Android",
                sessionKeyId = "session-key-1",
                sessionContext = ByteArray(32) { 4 },
            )
        val preferences = MemoryInternetProfilePreferences()
        val secrets = MemoryInternetProfileSecretStore()
        val identityStore = PairingTestDeviceIdentityStore(local.androidIdentity)
        val stateStore = PairingTestSecurityStateStore(DurableSecurityState(identityEpochHighWatermark = 1))
        val sessionSecurity = AndroidSessionSecurity(localDeviceId, stateStore, identityStore)
        val factory =
            AndroidStoredInternetSessionFactory(
                localDeviceId = localDeviceId,
                sessionSecurity = sessionSecurity,
                loadSecret = secrets::load,
                persistSecret = secrets::persist,
                deleteSecret = secrets::delete,
            )
        val store = InternetSessionProfileStore(
            preferences,
            debuggable = false,
            secretStore = secrets,
            nowUnixSeconds = nowUnixSeconds,
        )
        val coordinator = InternetProductRevocationCoordinator()
        coordinator.withCredentialMutationAdmission(durableBlock = { false }) { permit ->
            factory.persistPairingSecrets(pairingIdentifier, ByteArray(32) { 1 }, ByteArray(32) { 2 })
            store.recordVerifiedPairing(permit, metadata, factory)
        }
        return PairingStoreFixture(
            pairingIdentifier,
            localDeviceId,
            local.pairingIdentity,
            hostIdentity,
            hostKeyPair,
            metadata,
            preferences,
            secrets,
            identityStore,
            stateStore,
            sessionSecurity,
            factory,
            store,
            coordinator,
        )
    }

    private fun signedLeaseJson(fixture: PairingStoreFixture, sessionEpoch: Long): String {
        val unsigned =
            DecodedInternetProfile(
                profile =
                    StoredInternetSessionProfile(
                        pairingIdentifier = fixture.pairingIdentifier,
                        pinnedHostId = fixture.hostIdentity.deviceId,
                        pinnedDeviceId = fixture.localIdentity.deviceId,
                        leaseDeviceKeyId = fixture.localIdentity.keyId,
                        signalingUrl = "https://signal.example.test",
                        signalingSessionId = "session-$sessionEpoch",
                        authoritativeSessionEpoch = sessionEpoch,
                        hostIdentityEpoch = fixture.hostIdentity.keyEpoch,
                        deviceIdentityEpoch = fixture.localIdentity.keyEpoch,
                        expiresAtUnixSeconds = 4_102_444_800,
                        transcriptContext = requireNotNull(fixture.metadata.sessionContext).copyOf(),
                        protocolSessionId = "protocol-$sessionEpoch".toByteArray(),
                        iceServerUrls = listOf(listOf("stun:stun.example.test")),
                        allowInsecureForTesting = false,
                        leaseHostKeyId = fixture.hostIdentity.keyId,
                        leaseSignature = byteArrayOf(1),
                    ),
                secrets =
                    ImportedInternetSecrets(
                        signalingToken = DestroyableUtf8.fromString("device-token-with-at-least-32-characters"),
                        turnCredentials = listOf(null to null),
                    ),
            )
        val signature = sign(fixture.hostKeyPair, InternetSessionLeaseSignature.digest(unsigned))
        val profile = unsigned.profile.copy(leaseSignature = signature)
        return JsonObject().apply {
            addProperty("version", 1)
            addProperty("pairing_id", profile.pairingIdentifier)
            addProperty("pinned_host_id", profile.pinnedHostId)
            addProperty("pinned_device_id", profile.pinnedDeviceId)
            addProperty("lease_device_key_id", profile.leaseDeviceKeyId)
            addProperty("signaling_url", profile.signalingUrl)
            addProperty("signaling_session_id", profile.signalingSessionId)
            addProperty("session_epoch", profile.authoritativeSessionEpoch)
            addProperty("host_identity_epoch", profile.hostIdentityEpoch)
            addProperty("device_identity_epoch", profile.deviceIdentityEpoch)
            addProperty("expires_at", profile.expiresAtUnixSeconds)
            addProperty("transcript_context", Base64.getEncoder().encodeToString(profile.transcriptContext))
            addProperty("protocol_session_id", Base64.getEncoder().encodeToString(profile.protocolSessionId))
            unsigned.secrets.signalingToken.withString { addProperty("signaling_token", it) }
            add(
                "ice_servers",
                JsonArray().apply {
                    add(
                        JsonObject().apply {
                            add("urls", JsonArray().apply { add("stun:stun.example.test") })
                            add("username", JsonNull.INSTANCE)
                            add("credential", JsonNull.INSTANCE)
                        },
                    )
                },
            )
            addProperty("allow_insecure_for_testing", false)
            addProperty("lease_host_key_id", profile.leaseHostKeyId)
            addProperty("lease_signature", Base64.getEncoder().encodeToString(signature))
        }.toString()
    }

    private fun legacyBinding(fixture: PairingStoreFixture): String =
        JsonObject().apply {
            addProperty("pairing_id", fixture.pairingIdentifier)
            addProperty("host_device_id", fixture.hostIdentity.deviceId)
            addProperty("host_key_id", fixture.hostIdentity.keyId)
            addProperty("host_identity_epoch", fixture.hostIdentity.keyEpoch)
            addProperty("host_signature_algorithm", fixture.hostIdentity.signatureAlgorithm)
            addProperty("host_signing_public_key", Base64.getEncoder().encodeToString(fixture.hostIdentity.signingPublicKey))
            addProperty("local_device_id", fixture.localIdentity.deviceId)
            addProperty("local_identity_epoch", fixture.localIdentity.keyEpoch)
            addProperty("session_context", Base64.getEncoder().encodeToString(requireNotNull(fixture.metadata.sessionContext)))
        }.toString()

    private fun testIdentity(deviceId: String, epoch: Long): ProfileTestIdentity {
        val publicKey = publicPoint(generateEphemeral(SecureRandom()))
        val pairingIdentity =
            InternetPairingIdentity(
                deviceId = deviceId,
                keyId = pairingSha256(publicKey).toPairingHex(),
                keyEpoch = epoch,
                signingPublicKey = publicKey,
            )
        return ProfileTestIdentity(
            pairingIdentity,
            AndroidDeviceIdentity(
                AndroidPublicIdentity(deviceId, pairingIdentity.keyId, epoch, publicKey.copyOf()),
                "profile-test-${pairingIdentity.keyId}",
            ),
        )
    }

    private fun sign(keyPair: KeyPair, digest: ByteArray): ByteArray =
        Signature.getInstance("NONEwithECDSA").run {
            initSign(keyPair.private)
            update(digest)
            sign()
        }
}

private data class PairingStoreFixture(
    val pairingIdentifier: String,
    val localDeviceId: String,
    val localIdentity: InternetPairingIdentity,
    val hostIdentity: InternetPairingIdentity,
    val hostKeyPair: KeyPair,
    val metadata: InternetPairingPublicMetadata,
    val preferences: MemoryInternetProfilePreferences,
    val secrets: MemoryInternetProfileSecretStore,
    val identityStore: PairingTestDeviceIdentityStore,
    val stateStore: PairingTestSecurityStateStore,
    val sessionSecurity: AndroidSessionSecurity,
    val factory: AndroidStoredInternetSessionFactory,
    val store: InternetSessionProfileStore,
    val coordinator: InternetProductRevocationCoordinator,
)

private data class ProfileTestIdentity(
    val pairingIdentity: InternetPairingIdentity,
    val androidIdentity: AndroidDeviceIdentity,
)

private class PairingTestDeviceIdentityStore(
    var existing: AndroidDeviceIdentity?,
) : DeviceIdentityStore {
    var loadCount = 0
        private set
    var createCount = 0
        private set

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

    fun resetCounts() {
        loadCount = 0
        createCount = 0
    }
}

private class PairingTestSecurityStateStore(
    initial: DurableSecurityState,
) : SecurityStateStore {
    var state = initial

    override fun load(): DurableSecurityState = state

    override fun persist(state: DurableSecurityState) {
        this.state = state
    }
}
