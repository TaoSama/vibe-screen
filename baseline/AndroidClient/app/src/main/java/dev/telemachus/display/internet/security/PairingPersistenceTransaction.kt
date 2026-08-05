package dev.telemachus.display.internet.security

internal interface PairingPersistenceSlots {
    fun load(name: String): ByteArray?
    fun persist(name: String, value: ByteArray)
    fun delete(name: String)
}

/** Crash-safe pairing transaction kept pending through authorization and metadata commit. */
internal class PairingPersistenceTransaction(
    private val slots: PairingPersistenceSlots,
    private val markerName: String,
) {
    fun begin(targetName: String, record: ByteArray) {
        validateTarget(targetName)
        val marker = targetName.toByteArray(Charsets.UTF_8)
        var markerCommitted = false
        try {
            check(slots.load(markerName) == null) { "Another pairing persistence transaction is pending" }
            slots.persist(markerName, marker)
            markerCommitted = true
            slots.persist(targetName, record)
        } catch (failure: Throwable) {
            if (markerCommitted) {
                try {
                    retryPendingCleanup()
                } catch (cleanupFailure: Throwable) {
                    failure.addSuppressed(cleanupFailure)
                }
            }
            throw failure
        } finally {
            marker.fill(0)
        }
    }

    fun commit(targetName: String) {
        validateTarget(targetName)
        val pending = loadPendingTarget() ?: error("Pairing persistence transaction marker is missing")
        check(pending == targetName) { "Pairing persistence transaction targets another secret slot" }
        slots.delete(markerName)
    }

    fun complete(
        targetName: String,
        commitBusinessState: () -> Unit,
        cleanupBusinessState: () -> Unit,
    ) {
        try {
            commitBusinessState()
            commit(targetName)
        } catch (failure: Throwable) {
            try {
                val recovered = retryPendingCleanup(cleanupBusinessState)
                if (!recovered) cleanupBusinessState()
            } catch (cleanupFailure: Throwable) {
                failure.addSuppressed(cleanupFailure)
            }
            throw failure
        }
    }

    fun retryPendingCleanup(cleanupBusinessState: () -> Unit = {}): Boolean {
        val targetName = loadPendingTarget() ?: return false
        slots.delete(targetName)
        cleanupBusinessState()
        slots.delete(markerName)
        return true
    }

    private fun loadPendingTarget(): String? {
        val marker = slots.load(markerName) ?: return null
        return try {
            marker.toString(Charsets.UTF_8).also(::validateTarget)
        } finally {
            marker.fill(0)
        }
    }

    private fun validateTarget(targetName: String) {
        require(targetName.startsWith(PAIRING_SECRET_PREFIX) && targetName.length <= MAX_SLOT_NAME_BYTES) {
            "Stored pairing cleanup marker does not identify a valid pairing-secret slot"
        }
    }

    companion object {
        private const val PAIRING_SECRET_PREFIX = "phase3.pairing.v1."
        private const val MAX_SLOT_NAME_BYTES = 256
    }
}
