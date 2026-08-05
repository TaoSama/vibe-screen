package dev.telemachus.display.internet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class InternetRevocationCleanupTest {
    private val pending = PendingRevocationCleanup("pair-1", "device-1", 7)

    @Test
    fun `failed deletes remain durable and retry after restart`() {
        val executed = mutableListOf<RevocationCleanupStep>()
        var durable: PendingRevocationCleanup? = pending
        val first =
            retryRevocationCleanup(
                initial = pending,
                execute = { step ->
                    executed += step
                    if (step == RevocationCleanupStep.IDENTITY_KEY) error("keystore busy")
                },
                persist = { next -> durable = next; true },
            )

        assertEquals(setOf(RevocationCleanupStep.IDENTITY_KEY), first.remainingSteps)
        assertFalse(first.complete)
        assertEquals(setOf(RevocationCleanupStep.IDENTITY_KEY), durable?.remainingSteps)

        val afterRestart = PendingRevocationCleanupCodec.decode(PendingRevocationCleanupCodec.encode(requireNotNull(durable)))
        val retried = mutableListOf<RevocationCleanupStep>()
        val second =
            retryRevocationCleanup(
                initial = afterRestart,
                execute = { retried += it },
                persist = { next -> durable = next; true },
            )

        assertEquals(listOf(RevocationCleanupStep.IDENTITY_KEY), retried)
        assertTrue(second.complete)
        assertEquals(null, durable)
    }

    @Test
    fun `progress commit failure retains step but does not block other cleanup`() {
        val executed = mutableListOf<RevocationCleanupStep>()
        val persisted = mutableListOf<Set<RevocationCleanupStep>>()
        var firstCommit = true

        val result =
            retryRevocationCleanup(
                initial = pending,
                execute = { executed += it },
                persist = { next ->
                    if (firstCommit) {
                        firstCommit = false
                        false
                    } else {
                        persisted += next?.remainingSteps.orEmpty()
                        true
                    }
                },
            )

        assertEquals(RevocationCleanupStep.entries.toList(), executed)
        assertEquals(setOf(RevocationCleanupStep.PAIRING_SECRET), result.remainingSteps)
        assertTrue(RevocationCleanupStep.PAIRING_SECRET in result.failures)
        assertTrue(persisted.isNotEmpty())
    }

    @Test
    fun `profile pointer removal commits deferred secret slot atomically`() {
        var committedQueue: Set<String>? = null

        val committed = commitProfileRemoval(setOf("encrypted-slot")) { queue ->
            committedQueue = queue
            true
        }

        assertTrue(committed)
        assertEquals(setOf("encrypted-slot"), committedQueue)
    }

    @Test
    fun `legacy pair one cleanup preserves superseding pair two state after restart`() {
        val restarted = PendingRevocationCleanupCodec.decode(PendingRevocationCleanupCodec.encode(pending))
        val pairingSecrets = mutableSetOf("pair-1", "pair-2")
        val identityKeys = mutableSetOf("device-1:7", "device-2:8")
        val sessionCredentials = mutableSetOf("pair-2")
        var profileOwner: String? = "pair-2"
        var bindingOwner: String? = "pair-2"
        var durable: PendingRevocationCleanup? = restarted

        val result =
            retryOwnedRevocationCleanup(
                initial = restarted,
                currentProfilePairingIdentifier = { profileOwner },
                currentBindingPairingIdentifier = { bindingOwner },
                deletePairingSecret = { pairingSecrets.remove(it) },
                deleteIdentityKey = { deviceId, epoch -> identityKeys.remove("$deviceId:$epoch") },
                deleteSessionCredentials = {
                    sessionCredentials.remove(it)
                    profileOwner = null
                },
                deletePairingMetadata = {
                    bindingOwner = null
                },
                persist = { next -> durable = next; true },
            )

        assertTrue(result.complete)
        assertEquals(null, durable)
        assertEquals(setOf("pair-2"), pairingSecrets)
        assertEquals(setOf("device-2:8"), identityKeys)
        assertEquals(setOf("pair-2"), sessionCredentials)
        assertEquals("pair-2", profileOwner)
        assertEquals("pair-2", bindingOwner)
    }

    @Test
    fun `same owner revocation cleanup still deletes all owner state`() {
        val pairingSecrets = mutableSetOf("pair-1")
        val identityKeys = mutableSetOf("device-1:7")
        val sessionCredentials = mutableSetOf("pair-1")
        var profileOwner: String? = "pair-1"
        var bindingOwner: String? = "pair-1"
        var durable: PendingRevocationCleanup? = pending

        val result =
            retryOwnedRevocationCleanup(
                initial = pending,
                currentProfilePairingIdentifier = { profileOwner },
                currentBindingPairingIdentifier = { bindingOwner },
                deletePairingSecret = { pairingSecrets.remove(it) },
                deleteIdentityKey = { deviceId, epoch -> identityKeys.remove("$deviceId:$epoch") },
                deleteSessionCredentials = {
                    sessionCredentials.remove(it)
                    profileOwner = null
                },
                deletePairingMetadata = { bindingOwner = null },
                persist = { next -> durable = next; true },
            )

        assertTrue(result.complete)
        assertEquals(null, durable)
        assertTrue(pairingSecrets.isEmpty())
        assertTrue(identityKeys.isEmpty())
        assertTrue(sessionCredentials.isEmpty())
        assertEquals(null, profileOwner)
        assertEquals(null, bindingOwner)
    }
}
