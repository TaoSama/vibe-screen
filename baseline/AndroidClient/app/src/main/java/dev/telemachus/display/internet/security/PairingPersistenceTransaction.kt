package dev.telemachus.display.internet.security

internal interface PairingPersistenceSlots {
    fun load(name: String): ByteArray?
    fun persist(name: String, value: ByteArray)
    fun delete(name: String)
}

/** Crash-safe single-record pairing commit with a deterministic cleanup slot. */
internal class PairingPersistenceTransaction(
    private val slots: PairingPersistenceSlots,
    private val markerName: String,
) {
    fun persist(targetName: String, record: ByteArray) {
        validateTarget(targetName)
        val marker = targetName.toByteArray(Charsets.UTF_8)
        var markerCommitted = false
        try {
            slots.persist(markerName, marker)
            markerCommitted = true
            slots.persist(targetName, record)
            slots.delete(markerName)
        } catch (failure: Throwable) {
            if (markerCommitted) {
                try {
                    slots.delete(targetName)
                    slots.delete(markerName)
                } catch (cleanupFailure: Throwable) {
                    failure.addSuppressed(cleanupFailure)
                }
            }
            throw failure
        } finally {
            marker.fill(0)
        }
    }

    fun retryPendingCleanup() {
        val marker = slots.load(markerName) ?: return
        val targetName =
            try {
                marker.toString(Charsets.UTF_8).also(::validateTarget)
            } finally {
                marker.fill(0)
            }
        slots.delete(targetName)
        slots.delete(markerName)
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
