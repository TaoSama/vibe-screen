package dev.telemachus.display.internet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
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
              "allow_insecure_for_testing":$allowInsecure
            }
        """.trimIndent()
    }
}
