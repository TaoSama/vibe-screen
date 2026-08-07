package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PendingPairingIdentityAliasTest {
    @Test
    fun markerIsDurableBeforeCallerCreatesAlias() {
        val events = mutableListOf<String>()
        val persistence = MemoryPendingPairingIdentityAliasPersistence(events)

        val pending =
            PendingPairingIdentityAlias.create(persistence, "device-a", 2) { _, _ ->
                events += "delete"
            }
        events += "create-key"

        assertEquals(listOf("persist", "create-key"), events)
        assertNotNull(persistence.marker)
        pending.close()
    }

    @Test
    fun processRestartDeletesOrphanAndClearsMarker() {
        val persistence = MemoryPendingPairingIdentityAliasPersistence()
        PendingPairingIdentityAlias.create(persistence, "device-a", 3) { _, _ -> error("old process") }
        val deleted = mutableListOf<Pair<String, Long>>()

        val recovered =
            recoverPendingPairingIdentityAlias(
                persistence = persistence,
                isCommittedIdentity = { false },
                deleteIdentity = { deviceId, epoch -> deleted += deviceId to epoch },
            )

        assertTrue(recovered)
        assertEquals(listOf("device-a" to 3L), deleted)
        assertNull(persistence.marker)
    }

    @Test
    fun deletionFailureKeepsMarkerForNextRestartRetry() {
        val persistence = MemoryPendingPairingIdentityAliasPersistence()
        PendingPairingIdentityAlias.create(persistence, "device-a", 4) { _, _ -> error("old process") }

        assertThrows(IllegalStateException::class.java) {
            recoverPendingPairingIdentityAlias(
                persistence = persistence,
                isCommittedIdentity = { false },
                deleteIdentity = { _, _ -> error("keystore unavailable") },
            )
        }
        assertNotNull(persistence.marker)

        val deleted = mutableListOf<Long>()
        recoverPendingPairingIdentityAlias(
            persistence = persistence,
            isCommittedIdentity = { false },
            deleteIdentity = { _, epoch -> deleted += epoch },
        )

        assertEquals(listOf(4L), deleted)
        assertNull(persistence.marker)
    }

    @Test
    fun committedAliasSurvivesUiFailureAndOnDestroyCleanup() {
        val persistence = MemoryPendingPairingIdentityAliasPersistence()
        val deleted = mutableListOf<Long>()
        val pending =
            PendingPairingIdentityAlias.create(persistence, "device-a", 5) { _, epoch ->
                deleted += epoch
            }

        pending.commit()
        assertThrows(IllegalStateException::class.java) { error("UI refresh failed") }
        pending.close()

        assertTrue(deleted.isEmpty())
        assertNull(persistence.marker)
    }

    @Test
    fun committedMarkerAfterCrashIsClearedWithoutDeletingAuthorizedAlias() {
        val persistence = MemoryPendingPairingIdentityAliasPersistence()
        PendingPairingIdentityAlias.create(persistence, "device-a", 6) { _, _ -> error("old process") }
        val deleted = mutableListOf<Long>()

        recoverPendingPairingIdentityAlias(
            persistence = persistence,
            isCommittedIdentity = { marker -> marker.deviceId == "device-a" && marker.identityEpoch == 6L },
            deleteIdentity = { _, epoch -> deleted += epoch },
        )

        assertTrue(deleted.isEmpty())
        assertNull(persistence.marker)
    }

    @Test
    fun commitMarkerClearFailureNeverRevertsToPendingDeletion() {
        val persistence = MemoryPendingPairingIdentityAliasPersistence()
        val deleted = mutableListOf<Long>()
        val pending =
            PendingPairingIdentityAlias.create(persistence, "device-a", 7) { _, epoch ->
                deleted += epoch
            }
        persistence.failNextClear = true

        assertThrows(IllegalStateException::class.java) { pending.commit() }
        pending.close()

        assertTrue(deleted.isEmpty())
        assertNotNull(persistence.marker)
        recoverPendingPairingIdentityAlias(
            persistence = persistence,
            isCommittedIdentity = { it.identityEpoch == 7L },
            deleteIdentity = { _, epoch -> deleted += epoch },
        )
        assertTrue(deleted.isEmpty())
        assertNull(persistence.marker)
    }

    @Test
    fun cancelFailureAndRepairDeleteOnlyCurrentlyOwnedEpoch() {
        val persistence = MemoryPendingPairingIdentityAliasPersistence()
        val deleted = mutableListOf<Long>()

        val cancelled =
            PendingPairingIdentityAlias.create(persistence, "device-a", 8) { _, epoch ->
                deleted += epoch
            }
        cancelled.close()
        cancelled.close()

        val failed =
            PendingPairingIdentityAlias.create(persistence, "device-a", 9) { _, _ ->
                throw IllegalArgumentException("delete failed")
            }
        val pairingFailure = IllegalStateException("pairing failed")
        failed.closeWithSuppressed(pairingFailure)

        assertEquals(listOf(8L), deleted)
        assertEquals(1, pairingFailure.suppressed.size)
        assertEquals(9L, persistence.marker?.identityEpoch)

        persistence.failNextClear = false
        recoverPendingPairingIdentityAlias(
            persistence = persistence,
            isCommittedIdentity = { false },
            deleteIdentity = { _, epoch -> deleted += epoch },
        )
        val replacement =
            PendingPairingIdentityAlias.create(persistence, "device-a", 10) { _, epoch ->
                deleted += epoch
            }
        replacement.close()

        assertEquals(listOf(8L, 9L, 10L), deleted)
        assertNull(persistence.marker)
    }

    @Test
    fun committedOldIdentityIsNotDeletedByReplacementCancellation() {
        val persistence = MemoryPendingPairingIdentityAliasPersistence()
        val deleted = mutableListOf<Long>()
        val committed =
            PendingPairingIdentityAlias.create(persistence, "device-a", 11) { _, epoch ->
                deleted += epoch
            }
        committed.commit()

        val replacement =
            PendingPairingIdentityAlias.create(persistence, "device-a", 12) { _, epoch ->
                deleted += epoch
            }
        replacement.close()
        committed.close()

        assertEquals(listOf(12L), deleted)
        assertNull(persistence.marker)
    }

    @Test
    fun markerRejectsAliasThatDoesNotMatchDeviceAndEpoch() {
        val valid = PendingPairingIdentityAliasMarker.create("device-a", 13)

        assertTrue(valid.aliasIdentity.endsWith(".13"))
        assertThrows(IllegalArgumentException::class.java) {
            PendingPairingIdentityAliasMarker("device-a", 14, valid.aliasIdentity)
        }
        assertFalse(valid.aliasIdentity.contains("device-a"))
    }
}

private class MemoryPendingPairingIdentityAliasPersistence(
    private val events: MutableList<String> = mutableListOf(),
) : PendingPairingIdentityAliasPersistence {
    var marker: PendingPairingIdentityAliasMarker? = null
        private set
    var failNextClear = false

    override fun load(): PendingPairingIdentityAliasMarker? = marker

    override fun persist(marker: PendingPairingIdentityAliasMarker) {
        check(this.marker == null || this.marker == marker) { "another marker is pending" }
        events += "persist"
        this.marker = marker
    }

    override fun clear(marker: PendingPairingIdentityAliasMarker) {
        check(this.marker == marker) { "marker ownership changed" }
        if (failNextClear) {
            failNextClear = false
            error("marker clear failed")
        }
        events += "clear"
        this.marker = null
    }
}
