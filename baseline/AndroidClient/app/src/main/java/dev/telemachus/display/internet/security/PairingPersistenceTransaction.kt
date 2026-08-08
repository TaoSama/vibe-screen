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
    private val recoveryMarkerName = "$markerName.recovery"

    fun begin(
        targetName: String,
        record: ByteArray,
        cleanupContext: String? = null,
    ) {
        validateTarget(targetName)
        cleanupContext?.let(::validateCleanupContext)
        val marker = encodeMarker(PendingStatus.PREPARED, targetName, cleanupContext)
        var recoveryMarkerCommitted = false
        try {
            check(loadPendingTarget() == null) { "Another pairing persistence transaction is pending" }
            slots.persist(recoveryMarkerName, marker)
            recoveryMarkerCommitted = true
            slots.persist(markerName, marker)
            slots.persist(targetName, record)
        } catch (failure: Throwable) {
            if (recoveryMarkerCommitted) {
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
        val committedMarker = encodeMarker(PendingStatus.COMMITTED, targetName, pending.cleanupContext)
        try {
            slots.persist(recoveryMarkerName, committedMarker)
            slots.persist(markerName, committedMarker)
        } finally {
            committedMarker.fill(0)
        }
        slots.delete(markerName)
        slots.delete(recoveryMarkerName)
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
            if (loadPendingTarget()?.status == PendingStatus.COMMITTED) {
                // The recovery marker is the durable commit point. Its
                // remaining cleanup is retried without rolling back identity.
                return
            }
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
        val pendingTargets = loadPendingTargetsForRecovery()
        if (pendingTargets.isEmpty()) return false
        val committedTargetNames =
            pendingTargets
                .filter { it.status == PendingStatus.COMMITTED }
                .mapTo(mutableSetOf()) { it.targetName }
        val deletedTargetNames = mutableSetOf<String>()
        pendingTargets
            .filter { it.status == PendingStatus.PREPARED }
            .forEach { pending ->
                if (pending.targetName !in committedTargetNames && deletedTargetNames.add(pending.targetName)) {
                    slots.delete(pending.targetName)
                }
                cleanupBusinessState(pending.targetName, pending.cleanupContext)
            }
        slots.delete(markerName)
        slots.delete(recoveryMarkerName)
        return true
    }

    private fun loadPendingTargetsForRecovery(): List<PendingTarget> =
        loadMarkers()
            .groupBy { it.targetName to it.cleanupContext }
            .values
            .map { markers -> markers.maxBy { it.status.ordinal } }

    fun hasPendingCleanup(): Boolean = loadMarkers().isNotEmpty()

    private fun loadPendingTarget(): PendingTarget? {
        val markers = loadMarkers()
        if (markers.isEmpty()) return null
        check(markers.map { it.targetName to it.cleanupContext }.distinct().size == 1) {
            "Stored pairing cleanup markers disagree"
        }
        return markers.maxBy { it.status.ordinal }
    }

    private fun loadMarkers(): List<PendingTarget> =
        listOfNotNull(loadMarker(markerName), loadMarker(recoveryMarkerName))

    private fun loadMarker(name: String): PendingTarget? {
        val marker = slots.load(name) ?: return null
        return try {
            decodeMarker(marker.toString(Charsets.UTF_8))
        } finally {
            marker.fill(0)
        }
    }

    private fun encodeMarker(status: PendingStatus, targetName: String, cleanupContext: String?): ByteArray =
        listOfNotNull(MARKER_VERSION, status.name.lowercase(), targetName, cleanupContext)
            .joinToString("\n")
            .toByteArray(Charsets.UTF_8)

    private fun decodeMarker(value: String): PendingTarget {
        val parts = value.split('\n')
        if (parts.firstOrNull() != MARKER_VERSION) {
            require(parts.size in 1..2) { "Stored pairing cleanup marker is malformed" }
            return PendingTarget(
                PendingStatus.PREPARED,
                parts[0].also(::validateTarget),
                parts.getOrNull(1)?.also(::validateCleanupContext),
            )
        }
        require(parts.size in 3..4) { "Stored pairing cleanup marker is malformed" }
        val status = runCatching { PendingStatus.valueOf(parts[1].uppercase()) }
            .getOrElse { throw IllegalArgumentException("Stored pairing cleanup marker status is invalid", it) }
        return PendingTarget(
            status,
            parts[2].also(::validateTarget),
            parts.getOrNull(3)?.also(::validateCleanupContext),
        )
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
        val status: PendingStatus,
        val targetName: String,
        val cleanupContext: String?,
    )

    private enum class PendingStatus {
        PREPARED,
        COMMITTED,
    }

    companion object {
        private const val MARKER_VERSION = "v2"
        private const val PAIRING_SECRET_PREFIX = "phase3.pairing.v1."
        private const val MAX_SLOT_NAME_BYTES = 256
        private const val MAX_CLEANUP_CONTEXT_BYTES = 256
    }
}
