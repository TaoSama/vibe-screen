package dev.telemachus.display.internet.security

import dev.telemachus.display.internet.InternetProductRevocationCoordinator
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingPersistenceTransactionTest {
    @Test
    fun partialWriteAndRollbackFailureRetainsMarkerForRestartCleanup() {
        val slots = MemorySlots()
        val transaction = PairingPersistenceTransaction(slots, MARKER)
        slots.failPersist = setOf(TARGET)
        slots.failDelete = setOf(TARGET)

        val failure = assertThrows(IllegalStateException::class.java) {
            transaction.begin(TARGET, byteArrayOf(1, 2, 3))
        }
        assertTrue(failure.suppressed.isNotEmpty())
        assertTrue(MARKER in slots.values)

        slots.failPersist = emptySet()
        slots.failDelete = emptySet()
        PairingPersistenceTransaction(slots, MARKER).retryPendingCleanup()
        assertFalse(MARKER in slots.values)
        assertFalse(TARGET in slots.values)
    }

    @Test
    fun successfulCommitClearsMarkerAndKeepsRecord() {
        val slots = MemorySlots()
        val transaction = PairingPersistenceTransaction(slots, MARKER)
        transaction.begin(TARGET, byteArrayOf(4, 5))

        assertTrue(MARKER in slots.values)
        transaction.complete(TARGET, commitBusinessState = {}, cleanupBusinessState = {})

        assertFalse(MARKER in slots.values)
        assertArrayEquals(byteArrayOf(4, 5), slots.values.getValue(TARGET))
    }

    @Test
    fun postPersistBusinessFailureAndDeleteFailureResumeAfterRestart() {
        val slots = MemorySlots()
        val transaction = PairingPersistenceTransaction(slots, MARKER)
        transaction.begin(TARGET, byteArrayOf(7, 8, 9))
        var metadataCommitted = false
        slots.failDelete = setOf(TARGET)

        val failure = assertThrows(IllegalStateException::class.java) {
            transaction.complete(
                TARGET,
                commitBusinessState = {
                    metadataCommitted = true
                    throw IllegalStateException("metadata commit failed")
                },
                cleanupBusinessState = { metadataCommitted = false },
            )
        }
        assertTrue(failure.suppressed.isNotEmpty())
        assertTrue(metadataCommitted)
        assertTrue(MARKER in slots.values)
        assertTrue(TARGET in slots.values)

        slots.failDelete = emptySet()
        assertTrue(
            PairingPersistenceTransaction(slots, MARKER).retryPendingCleanup { _, _ ->
                metadataCommitted = false
            },
        )
        assertFalse(metadataCommitted)
        assertFalse(MARKER in slots.values)
        assertFalse(TARGET in slots.values)
    }

    @Test
    fun restartCleanupReturnsBusinessOwnerWithoutLosingLegacyCompatibility() {
        val slots = MemorySlots()
        PairingPersistenceTransaction(slots, MARKER).begin(TARGET, byteArrayOf(1), "pair-2")
        var cleanupOwner: String? = null

        assertTrue(
            PairingPersistenceTransaction(slots, MARKER).retryPendingCleanup { _, owner -> cleanupOwner = owner },
        )

        assertTrue(cleanupOwner == "pair-2")
        slots.values[MARKER] = TARGET.toByteArray()
        PairingPersistenceTransaction(slots, MARKER).retryPendingCleanup { _, owner -> cleanupOwner = owner }
        assertTrue(cleanupOwner == null)
    }

    @Test
    fun authenticatedRevocationFinishesBeforePairingMarkerRecoveryAcrossRestart() {
        val slots = MemorySlots()
        PairingPersistenceTransaction(slots, MARKER).begin(TARGET, byteArrayOf(2), "pair-2")
        slots.values[OLD_TARGET] = byteArrayOf(1)
        var verifiedPairing: String? = "pair-1"
        var authenticatedPending = true
        var revocationCleanupPending = false

        fun retryPairingCleanup(coordinator: InternetProductRevocationCoordinator) {
            coordinator.withCredentialMutationAdmission(
                durableBlock = { authenticatedPending || revocationCleanupPending },
            ) { permit ->
                permit.requireActive()
                PairingPersistenceTransaction(slots, MARKER).retryPendingCleanup { _, cleanupOwner ->
                    if (verifiedPairing == cleanupOwner) verifiedPairing = null
                }
            }
        }

        assertThrows(IllegalStateException::class.java) {
            retryPairingCleanup(InternetProductRevocationCoordinator())
        }
        assertTrue(verifiedPairing == "pair-1")
        assertTrue(MARKER in slots.values)
        assertTrue(TARGET in slots.values)

        // Simulated restart: authenticated promotion still has the verified pair-1
        // binding, then its own cleanup removes pair-1 state before pair-2 rollback.
        assertTrue(verifiedPairing == "pair-1")
        authenticatedPending = false
        revocationCleanupPending = true
        assertThrows(IllegalStateException::class.java) {
            retryPairingCleanup(InternetProductRevocationCoordinator())
        }
        slots.values.remove(OLD_TARGET)
        verifiedPairing = null
        revocationCleanupPending = false
        retryPairingCleanup(InternetProductRevocationCoordinator())

        assertTrue(verifiedPairing == null)
        assertFalse(OLD_TARGET in slots.values)
        assertFalse(TARGET in slots.values)
        assertFalse(MARKER in slots.values)
    }

    private class MemorySlots : PairingPersistenceSlots {
        val values = mutableMapOf<String, ByteArray>()
        var failPersist = emptySet<String>()
        var failDelete = emptySet<String>()
        override fun load(name: String): ByteArray? = values[name]?.copyOf()
        override fun persist(name: String, value: ByteArray) {
            if (name in failPersist) throw IllegalStateException("persist $name")
            values[name] = value.copyOf()
        }
        override fun delete(name: String) {
            if (name in failDelete) throw IllegalArgumentException("delete $name")
            values.remove(name)
        }
    }

    companion object {
        private const val MARKER = "phase3.pairing.persistence-cleanup.v1"
        private const val TARGET = "phase3.pairing.v1.0123456789abcdef"
        private const val OLD_TARGET = "phase3.pairing.v1.fedcba9876543210"
    }
}
