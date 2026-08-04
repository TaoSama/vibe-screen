package dev.telemachus.display.internet

import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.DurableSecurityState
import dev.telemachus.display.internet.security.SecurityLifecycle
import dev.telemachus.display.internet.security.SecurityStateStore
import dev.telemachus.display.internet.security.generateEphemeral
import dev.telemachus.display.internet.security.pairingSha256
import dev.telemachus.display.internet.security.publicPoint
import dev.telemachus.display.internet.security.toPairingHex
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.KeyPair
import java.security.SecureRandom
import java.security.Signature
import java.util.Base64

class InternetSessionProfileCodecTest {
    @Test
    fun `profile pointer commit durably includes cleanup intent`() {
        var committedQueue: Set<String>? = null
        val committed =
            commitProfileReplacement(
                cleanupQueue = setOf("old-slot"),
                commitPointerAndCleanup = { queue -> committedQueue = queue; true },
                rollbackNewSecret = { error("must not roll back successful commit") },
            )

        assertTrue(committed)
        assertEquals(setOf("old-slot"), committedQueue)
    }

    @Test
    fun `profile commit failure rolls back new secret`() {
        var rolledBack = false
        val committed =
            commitProfileReplacement(
                cleanupQueue = setOf("old-slot"),
                commitPointerAndCleanup = { false },
                rollbackNewSecret = { rolledBack = true },
            )

        assertTrue(!committed)
        assertTrue(rolledBack)
    }

    @Test
    fun `deferred cleanup queue preserves consecutive failures`() {
        val first = enqueueDeferredSecretCleanup(emptySet(), "slot-a")
        val second = enqueueDeferredSecretCleanup(first, "slot-b")
        val duplicate = enqueueDeferredSecretCleanup(second, "slot-a")

        assertEquals(setOf("slot-a", "slot-b"), duplicate)
    }

    @Test
    fun `in memory cleanup queue survives durable commit failure`() {
        val pending = DeferredSecretCleanupPending()
        pending.enqueue("slot-a")
        val attempted = pending.snapshot()
        pending.merge(attempted) // persistence failed: retain attempted work

        assertEquals(setOf("slot-a"), pending.snapshot())
        pending.replaceAfterDurableCommit(emptySet())
        assertTrue(pending.snapshot().isEmpty())
    }

    @Test
    fun `decodes strict production profile without exposing credentials in public encoding`() {
        val decoded = InternetSessionProfileCodec.decode(profileJson("https://signal.example.test", false), false)
        try {
            assertEquals("host-1", decoded.profile.pinnedHostId)
            assertEquals(7L, decoded.profile.authoritativeSessionEpoch)
            assertEquals("device-token-abcdefghijklmnopqrstuvwxyz", decoded.secrets.signalingToken)
            val public = InternetSessionProfileCodec.encodePublic(decoded.profile)
            assertTrue("device-token" !in public)
            assertTrue("turn-password" !in public)
            assertEquals(decoded.profile.pinnedHostId, InternetSessionProfileCodec.decodePublic(public, false).pinnedHostId)
        } finally {
            decoded.close()
        }
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects unknown root field`() {
        InternetSessionProfileCodec.decode(
            profileJson("https://signal.example.test", false).dropLast(1) + ",\"extra\":true}",
            false,
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects imported local device identity`() {
        InternetSessionProfileCodec.decode(
            profileJson("https://signal.example.test", false).dropLast(1) + ",\"local_device_id\":\"attacker\"}",
            false,
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects loopback http in production`() {
        InternetSessionProfileCodec.decode(profileJson("http://127.0.0.1:8080", true), false)
    }

    @Test
    fun `allows explicit loopback http only in debug`() {
        InternetSessionProfileCodec.decode(profileJson("http://127.0.0.1:8080", true), true).close()
    }

    @Test
    fun `host signature covers every lease security field`() {
        val keyPair = generateEphemeral(SecureRandom())
        val publicKey = publicPoint(keyPair)
        val host =
            InternetPairingIdentity(
                deviceId = "host-1",
                keyId = pairingSha256(publicKey).toPairingHex(),
                keyEpoch = 4,
                signingPublicKey = publicKey,
            )
        val unsigned = signedLeaseFixture(host.keyId)
        val valid = unsigned.copy(profile = unsigned.profile.copy(leaseSignature = sign(keyPair, InternetSessionLeaseSignature.digest(unsigned))))
        InternetSessionLeaseSignature.verify(valid, host)

        val mutations =
            listOf(
                valid.copy(profile = valid.profile.copy(pairingIdentifier = "pair-2")),
                valid.copy(profile = valid.profile.copy(pinnedHostId = "host-2")),
                valid.copy(profile = valid.profile.copy(signalingUrl = "https://other.example.test")),
                valid.copy(profile = valid.profile.copy(signalingSessionId = "session-8")),
                valid.copy(profile = valid.profile.copy(authoritativeSessionEpoch = 8)),
                valid.copy(profile = valid.profile.copy(identityEpoch = 2)),
                valid.copy(profile = valid.profile.copy(transcriptContext = ByteArray(32) { 2 })),
                valid.copy(profile = valid.profile.copy(protocolSessionId = "other".toByteArray())),
                valid.copy(profile = valid.profile.copy(iceServerUrls = valid.profile.iceServerUrls.reversed())),
                valid.copy(profile = valid.profile.copy(allowInsecureForTesting = true)),
                valid.copy(secrets = valid.secrets.copy(signalingToken = "z".repeat(32))),
                valid.copy(secrets = valid.secrets.copy(turnCredentials = listOf(null to null, "changed" to "turn-password"))),
            )
        mutations.forEach { mutated ->
            assertFails { InternetSessionLeaseSignature.verify(mutated, host) }
        }
        assertFails { InternetSessionLeaseSignature.verify(valid, host.copy(deviceId = "host-2")) }
        assertFails { InternetSessionLeaseSignature.verify(valid.copy(profile = valid.profile.copy(leaseHostKeyId = "wrong")), host) }
        assertFails {
            InternetSessionLeaseSignature.verify(
                valid.copy(profile = valid.profile.copy(leaseSignature = valid.profile.leaseSignature.copyOf().also { it[it.lastIndex] = (it.last() + 1).toByte() })),
                host,
            )
        }
    }

    @Test
    fun `lease transcript has a stable known answer`() {
        assertEquals(
            "9e6426d343a5f5e57652b42288df902bd24ff1df975b3fde4ab3bb0f1d8c5cbb",
            InternetSessionLeaseSignature.digest(signedLeaseFixture("host-key-id")).toHex(),
        )
    }

    @Test
    fun `valid signed stale lease does not persist secret or profile after profile deletion`() {
        val keyPair = generateEphemeral(SecureRandom())
        val publicKey = publicPoint(keyPair)
        val host =
            InternetPairingIdentity(
                deviceId = "host-1",
                keyId = pairingSha256(publicKey).toPairingHex(),
                keyEpoch = 1,
                signingPublicKey = publicKey,
            )
        val unsigned = signedLeaseFixture(host.keyId)
        val signed = unsigned.copy(profile = unsigned.profile.copy(leaseSignature = sign(keyPair, InternetSessionLeaseSignature.digest(unsigned))))
        InternetSessionLeaseSignature.verify(signed, host)
        val durableState = object : SecurityStateStore {
            override fun load() = DurableSecurityState(sessionEpoch = signed.profile.authoritativeSessionEpoch)
            override fun persist(state: DurableSecurityState) = error("Stale lease must not update durable state")
        }
        var secretPersisted = false
        var profilePersisted = false

        assertFails {
            SecurityLifecycle(durableState).withFreshSessionEpochCandidate(signed.profile.authoritativeSessionEpoch) {
                secretPersisted = true
                profilePersisted = true
            }
        }

        assertEquals(false, secretPersisted)
        assertEquals(false, profilePersisted)
    }

    @Test
    fun `rejects reserved maximum epochs`() {
        assertFails {
            InternetSessionProfileCodec.decode(
                profileJson("https://signal.example.test", false).replace("\"session_epoch\":7", "\"session_epoch\":${Long.MAX_VALUE}"),
                false,
            )
        }
        assertFails {
            InternetSessionProfileCodec.decode(
                profileJson("https://signal.example.test", false).replace("\"identity_epoch\":1", "\"identity_epoch\":${Long.MAX_VALUE}"),
                false,
            )
        }
    }

    private fun profileJson(url: String, allowInsecure: Boolean): String {
        val transcript = Base64.getEncoder().encodeToString(ByteArray(32) { 1 })
        val protocolId = Base64.getEncoder().encodeToString("session-7".toByteArray())
        return """
            {
              "version":1,
              "pairing_id":"pair-1",
              "pinned_host_id":"host-1",
              "signaling_url":"$url",
              "signaling_session_id":"session-7",
              "session_epoch":7,
              "identity_epoch":1,
              "transcript_context":"$transcript",
              "protocol_session_id":"$protocolId",
              "signaling_token":"device-token-abcdefghijklmnopqrstuvwxyz",
              "ice_servers":[
                {"urls":["stun:stun.example.test"],"username":null,"credential":null},
                {"urls":["turn:turn.example.test"],"username":"turn-user","credential":"turn-password"}
              ],
              "allow_insecure_for_testing":$allowInsecure,
              "lease_host_key_id":"host-key-id",
              "lease_signature":"AQ=="
            }
        """.trimIndent()
    }

    private fun signedLeaseFixture(hostKeyId: String): DecodedInternetProfile =
        DecodedInternetProfile(
            StoredInternetSessionProfile(
                pairingIdentifier = "pair-1",
                pinnedHostId = "host-1",
                signalingUrl = "https://signal.example.test",
                signalingSessionId = "session-7",
                authoritativeSessionEpoch = 7,
                identityEpoch = 1,
                transcriptContext = ByteArray(32) { 1 },
                protocolSessionId = "protocol-session-7".toByteArray(),
                iceServerUrls = listOf(listOf("stun:stun.example.test"), listOf("turn:turn.example.test")),
                allowInsecureForTesting = false,
                leaseHostKeyId = hostKeyId,
                leaseSignature = byteArrayOf(1),
            ),
            ImportedInternetSecrets(
                signalingToken = "device-token-abcdefghijklmnopqrstuvwxyz",
                turnCredentials = listOf(null to null, "turn-user" to "turn-password"),
            ),
        )

    private fun sign(keyPair: KeyPair, digest: ByteArray): ByteArray =
        Signature.getInstance("NONEwithECDSA").run { initSign(keyPair.private); update(digest); sign() }

    private fun assertFails(block: () -> Unit) {
        try {
            block()
            throw AssertionError("Expected operation to fail closed")
        } catch (_: IllegalArgumentException) {
            // Expected.
        }
    }

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
}
