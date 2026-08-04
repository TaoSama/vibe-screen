package dev.telemachus.display

/**
 * Owns process-local connection attempt generations.
 *
 * Wire session epochs are intentionally absent from this type: a host may
 * restart and reuse a lower wire epoch, while connection attempt ownership
 * must remain strictly monotonic for the lifetime of this client process.
 */
class ConnectionGenerationTracker {
    private var lastGeneration = 0L
    private var currentGeneration: Long? = null

    @Synchronized
    fun beginAttempt(): Long {
        check(lastGeneration < Long.MAX_VALUE) { "connection generation exhausted" }
        val generation = lastGeneration + 1L
        lastGeneration = generation
        currentGeneration = generation
        return generation
    }

    @Synchronized
    fun isCurrent(generation: Long): Boolean = generation > 0L && currentGeneration == generation

    /**
     * Finishes [generation] only when it still owns the active attempt.
     * Duplicate completion and callbacks from superseded attempts are no-ops.
     */
    @Synchronized
    fun finishCurrent(generation: Long): Boolean {
        if (!isCurrent(generation)) return false
        currentGeneration = null
        return true
    }
}
