package dev.telemachus.display.internet

import com.google.gson.JsonParser
import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.DurableSecurityState
import dev.telemachus.display.internet.security.SecurityLifecycle
import dev.telemachus.display.internet.security.SecurityStateStore
import dev.telemachus.display.internet.security.generateEphemeral
import dev.telemachus.display.internet.security.pairingSha256
import dev.telemachus.display.internet.security.pairingSecurityScope
import dev.telemachus.display.internet.security.publicPoint
import dev.telemachus.display.internet.security.toPairingHex
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.KeyPair
import java.security.SecureRandom
import java.security.Signature
import java.util.Base64
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class InternetSessionProfileCodecTest {
    @Test
    fun `destroyable utf8 zeroizes idempotently and rejects reads after close`() {
        val secret = DestroyableUtf8.fromString("credential-that-must-disappear")

        secret.close()
        secret.close()

        assertTrue(secret.isDestroyedForTest())
        assertThrows(IllegalStateException::class.java) { secret.withString { Unit } }
        assertFalse("credential-that-must-disappear" in secret.toString())
    }

    @Test
    fun `concurrent reads and close never expose a partially zeroized credential`() {
        val secret = DestroyableUtf8.fromString("concurrent-credential")
        val executor = Executors.newFixedThreadPool(4)
        val start = CountDownLatch(1)
        val closeFuture =
            executor.submit {
                start.await()
                secret.close()
            }
        val readFutures =
            List(32) {
                executor.submit {
                    start.await()
                    try {
                        secret.withString { value -> assertEquals("concurrent-credential", value) }
                    } catch (failure: IllegalStateException) {
                        assertEquals("Secret has been destroyed", failure.message)
                    }
                }
            }
        start.countDown()
        executor.shutdown()

        assertTrue(executor.awaitTermination(5, TimeUnit.SECONDS))
        closeFuture.get()
        readFutures.forEach { it.get() }
        secret.close()
        assertTrue(secret.isDestroyedForTest())
    }

    @Test
    fun `growth and destroy zero every owned output buffer`() {
        val output = ZeroizableByteArrayOutputStream(initialCapacity = 2)
        val initialBuffer = output.backingBufferForTest()

        output.write(byteArrayOf(1, 2, 3), 0, 3)

        assertTrue(initialBuffer.all { it == 0.toByte() })
        val bufferAfterBulkGrowth = output.backingBufferForTest()
        assertTrue(bufferAfterBulkGrowth !== initialBuffer)

        repeat(bufferAfterBulkGrowth.size - output.size()) { output.write(4) }
        output.write(5)

        assertTrue(bufferAfterBulkGrowth.all { it == 0.toByte() })
        val currentBuffer = output.backingBufferForTest()
        assertTrue(currentBuffer !== bufferAfterBulkGrowth)
        assertTrue(currentBuffer.any { it != 0.toByte() })

        output.destroy()

        assertTrue(currentBuffer.all { it == 0.toByte() })
        assertEquals(0, output.size())
    }

    @Test
    fun `constructor exception paths zeroize supplied credential containers`() {
        val bearer = DestroyableUtf8.fromString("b".repeat(32))
        assertThrows(IllegalArgumentException::class.java) {
            SignalingConfiguration("http://signal.example.test", bearer, PeerRole.DEVICE)
        }
        assertTrue(bearer.isDestroyedForTest())

        val username = DestroyableUtf8.fromString("turn-user")
        assertThrows(IllegalArgumentException::class.java) {
            IceServer(listOf("turn:turn.example.test"), username, null)
        }
        assertTrue(username.isDestroyedForTest())
    }

    @Test
    fun `decoded profile close zeroizes every credential and is idempotent`() {
        val decoded = InternetSessionProfileCodec.decode(profileJson("https://signal.example.test", false), false)
        val token = decoded.secrets.signalingToken
        val username = requireNotNull(decoded.secrets.turnCredentials[1].first)
        val password = requireNotNull(decoded.secrets.turnCredentials[1].second)

        decoded.close()
        decoded.close()

        assertTrue(token.isDestroyedForTest())
        assertTrue(username.isDestroyedForTest())
        assertTrue(password.isDestroyedForTest())
        assertFalse("device-token" in decoded.toString())
        assertFalse("turn-password" in decoded.secrets.toString())
    }

    @Test
    fun `lease receives independent secret copies and zeroizes them on replacement close`() {
        val decoded = InternetSessionProfileCodec.decode(profileJson("https://signal.example.test", false), false)
        val leaseToken = decoded.secrets.signalingToken.copy()
        val leaseUsername = requireNotNull(decoded.secrets.turnCredentials[1].first).copy()
        val leasePassword = requireNotNull(decoded.secrets.turnCredentials[1].second).copy()
        val lease =
            InternetProductSessionLease(
                pairingIdentifier = decoded.profile.pairingIdentifier,
                signalingSessionId = decoded.profile.signalingSessionId,
                authoritativeSessionEpoch = decoded.profile.authoritativeSessionEpoch,
                identityEpoch = 1,
                localIdentity = testIdentity(),
                transcriptContext = decoded.profile.transcriptContext.copyOf(),
                iceServers = listOf(IceServer(listOf("stun:stun.example.test")), IceServer(listOf("turn:turn.example.test"), leaseUsername, leasePassword)),
                signaling = SignalingConfiguration(decoded.profile.signalingUrl, leaseToken, PeerRole.DEVICE),
                pinnedHostId = decoded.profile.pinnedHostId,
            )

        decoded.close()
        leaseToken.withString { assertEquals("device-token-abcdefghijklmnopqrstuvwxyz", it) }
        lease.close()
        lease.close()

        assertTrue(leaseToken.isDestroyedForTest())
        assertTrue(leaseUsername.isDestroyedForTest())
        assertTrue(leasePassword.isDestroyedForTest())
        assertFalse("turn-password" in lease.toString())
    }

    @Test
    fun `streaming parser bounds secrets and never includes them in failures`() {
        val token = "sensitive-token-" + "x".repeat(8_192)
        val malformed = profileJson("https://signal.example.test", false).replace("device-token-abcdefghijklmnopqrstuvwxyz", token)

        val failure = assertThrows(IllegalArgumentException::class.java) { InternetSessionProfileCodec.decode(malformed, false) }

        assertFalse(failure.toString().contains(token))
    }

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
            decoded.secrets.signalingToken.withString { assertEquals("device-token-abcdefghijklmnopqrstuvwxyz", it) }
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
        val unsigned = signedLeaseFixture(host.keyId, host.keyEpoch)
        val valid = unsigned.copy(profile = unsigned.profile.copy(leaseSignature = sign(keyPair, InternetSessionLeaseSignature.digest(unsigned))))
        InternetSessionLeaseSignature.verify(valid, host)

        val mutations =
            listOf(
                valid.copy(profile = valid.profile.copy(pairingIdentifier = "pair-2")),
                valid.copy(profile = valid.profile.copy(pinnedHostId = "host-2")),
                valid.copy(profile = valid.profile.copy(pinnedDeviceId = "device-2")),
                valid.copy(profile = valid.profile.copy(leaseDeviceKeyId = "device-key-2")),
                valid.copy(profile = valid.profile.copy(signalingUrl = "https://other.example.test")),
                valid.copy(profile = valid.profile.copy(signalingSessionId = "session-8")),
                valid.copy(profile = valid.profile.copy(authoritativeSessionEpoch = 8)),
                valid.copy(profile = valid.profile.copy(hostIdentityEpoch = 5)),
                valid.copy(profile = valid.profile.copy(deviceIdentityEpoch = 2)),
                valid.copy(profile = valid.profile.copy(expiresAtUnixSeconds = 4_102_444_799)),
                valid.copy(profile = valid.profile.copy(transcriptContext = ByteArray(32) { 2 })),
                valid.copy(profile = valid.profile.copy(protocolSessionId = "other".toByteArray())),
                valid.copy(profile = valid.profile.copy(iceServerUrls = valid.profile.iceServerUrls.reversed())),
                valid.copy(profile = valid.profile.copy(allowInsecureForTesting = true)),
                valid.copy(secrets = secrets("z".repeat(32), listOf(null to null, "turn-user" to "turn-password"))),
                valid.copy(secrets = secrets("device-token-abcdefghijklmnopqrstuvwxyz", listOf(null to null, "changed" to "turn-password"))),
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
            "2e70ad358a425c631805820394d90ad46edb9ebb7f62541f594f5c22c2fbe377",
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
        val unsigned = signedLeaseFixture(host.keyId, host.keyEpoch)
        val signed = unsigned.copy(profile = unsigned.profile.copy(leaseSignature = sign(keyPair, InternetSessionLeaseSignature.digest(unsigned))))
        InternetSessionLeaseSignature.verify(signed, host)
        val pairingScope = pairingSecurityScope("device-1", signed.profile.pairingIdentifier)
        val durableState = object : SecurityStateStore {
            override fun load() =
                DurableSecurityState(
                    sessionEpochHighWatermarks =
                        mapOf(pairingScope to signed.profile.authoritativeSessionEpoch),
                    identityEpochHighWatermark = signed.profile.deviceIdentityEpoch,
                    authorizedIdentityEpoch = signed.profile.deviceIdentityEpoch,
                )
            override fun persist(state: DurableSecurityState) = error("Stale lease must not update durable state")
        }
        var secretPersisted = false
        var profilePersisted = false

        assertFails {
            SecurityLifecycle(durableState).withFreshSessionEpochCandidate(
                pairingScope,
                signed.profile.deviceIdentityEpoch,
                signed.profile.authoritativeSessionEpoch,
            ) {
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
                profileJson("https://signal.example.test", false).replace("\"device_identity_epoch\":1", "\"device_identity_epoch\":${Long.MAX_VALUE}"),
                false,
            )
        }
    }

    @Test
    fun `legacy single identity epoch lease fails closed`() {
        val legacy = JsonParser.parseString(profileJson("https://signal.example.test", false)).asJsonObject
        legacy.remove("host_identity_epoch")
        legacy.remove("device_identity_epoch")
        legacy.addProperty("identity_epoch", 1)
        assertFails { InternetSessionProfileCodec.decode(legacy.toString(), false) }
    }

    private fun profileJson(url: String, allowInsecure: Boolean): String {
        val transcript = Base64.getEncoder().encodeToString(ByteArray(32) { 1 })
        val protocolId = Base64.getEncoder().encodeToString("session-7".toByteArray())
        return """
            {
              "version":1,
              "pairing_id":"pair-1",
              "pinned_host_id":"host-1",
              "pinned_device_id":"device-1",
              "lease_device_key_id":"device-key-id",
              "signaling_url":"$url",
              "signaling_session_id":"session-7",
              "session_epoch":7,
              "host_identity_epoch":1,
              "device_identity_epoch":1,
              "expires_at":4102444800,
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

    private fun signedLeaseFixture(hostKeyId: String, hostIdentityEpoch: Long = 1): DecodedInternetProfile =
        DecodedInternetProfile(
            StoredInternetSessionProfile(
                pairingIdentifier = "pair-1",
                pinnedHostId = "host-1",
                pinnedDeviceId = "device-1",
                leaseDeviceKeyId = "device-key-id",
                signalingUrl = "https://signal.example.test",
                signalingSessionId = "session-7",
                authoritativeSessionEpoch = 7,
                hostIdentityEpoch = hostIdentityEpoch,
                deviceIdentityEpoch = 1,
                expiresAtUnixSeconds = 4_102_444_800,
                transcriptContext = ByteArray(32) { 1 },
                protocolSessionId = "protocol-session-7".toByteArray(),
                iceServerUrls = listOf(listOf("stun:stun.example.test"), listOf("turn:turn.example.test")),
                allowInsecureForTesting = false,
                leaseHostKeyId = hostKeyId,
                leaseSignature = byteArrayOf(1),
            ),
            secrets("device-token-abcdefghijklmnopqrstuvwxyz", listOf(null to null, "turn-user" to "turn-password")),
        )

    private fun secrets(token: String, credentials: List<Pair<String?, String?>>): ImportedInternetSecrets =
        ImportedInternetSecrets(
            DestroyableUtf8.fromString(token),
            credentials.map { (username, credential) ->
                username?.let(DestroyableUtf8::fromString) to credential?.let(DestroyableUtf8::fromString)
            },
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

    private fun testIdentity(): InternetPairingIdentity {
        val publicKey = publicPoint(generateEphemeral(SecureRandom()))
        return InternetPairingIdentity("device-1", pairingSha256(publicKey).toPairingHex(), 1, signingPublicKey = publicKey)
    }
}
