package dev.telemachus.display.internet.security

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
            transaction.persist(TARGET, byteArrayOf(1, 2, 3))
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
        PairingPersistenceTransaction(slots, MARKER).persist(TARGET, byteArrayOf(4, 5))

        assertFalse(MARKER in slots.values)
        assertArrayEquals(byteArrayOf(4, 5), slots.values.getValue(TARGET))
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
    }
}
