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
    fun begin(
        targetName: String,
        record: ByteArray,
        cleanupContext: String? = null,
    ) {
        validateTarget(targetName)
        cleanupContext?.let(::validateCleanupContext)
        val marker = encodeMarker(targetName, cleanupContext)
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
        check(pending.targetName == targetName) { "Pairing persistence transaction targets another secret slot" }
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
                val recovered = retryPendingCleanup { _, _ -> cleanupBusinessState() }
                if (!recovered) cleanupBusinessState()
            } catch (cleanupFailure: Throwable) {
                failure.addSuppressed(cleanupFailure)
            }
            throw failure
        }
    }

    fun retryPendingCleanup(cleanupBusinessState: (String, String?) -> Unit = { _, _ -> }): Boolean {
        val pending = loadPendingTarget() ?: return false
        slots.delete(pending.targetName)
        cleanupBusinessState(pending.targetName, pending.cleanupContext)
        slots.delete(markerName)
        return true
    }

    fun hasPendingCleanup(): Boolean = loadPendingTarget() != null

    private fun loadPendingTarget(): PendingTarget? {
        val marker = slots.load(markerName) ?: return null
        return try {
            decodeMarker(marker.toString(Charsets.UTF_8))
        } finally {
            marker.fill(0)
        }
    }

    private fun encodeMarker(targetName: String, cleanupContext: String?): ByteArray =
        if (cleanupContext == null) {
            targetName.toByteArray(Charsets.UTF_8)
        } else {
            "$targetName\n$cleanupContext".toByteArray(Charsets.UTF_8)
        }

    private fun decodeMarker(value: String): PendingTarget {
        val parts = value.split('\n')
        require(parts.size in 1..2) { "Stored pairing cleanup marker is malformed" }
        val targetName = parts[0].also(::validateTarget)
        val cleanupContext = parts.getOrNull(1)?.also(::validateCleanupContext)
        return PendingTarget(targetName, cleanupContext)
    }

    private fun validateTarget(targetName: String) {
        require(targetName.startsWith(PAIRING_SECRET_PREFIX) && targetName.length <= MAX_SLOT_NAME_BYTES) {
            "Stored pairing cleanup marker does not identify a valid pairing-secret slot"
        }
    }

    private fun validateCleanupContext(value: String) {
        require(value.isNotBlank() && value.length <= MAX_CLEANUP_CONTEXT_BYTES && '\n' !in value) {
            "Stored pairing cleanup context is invalid"
        }
    }

    private data class PendingTarget(
        val targetName: String,
        val cleanupContext: String?,
    )

    companion object {
        private const val PAIRING_SECRET_PREFIX = "phase3.pairing.v1."
        private const val MAX_SLOT_NAME_BYTES = 256
        private const val MAX_CLEANUP_CONTEXT_BYTES = 256
    }
}
