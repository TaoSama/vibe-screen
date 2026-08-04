package dev.telemachus.display

/**
 * Owns the identity, generation, and negotiated capabilities of one application session.
 *
 * Client identity is deliberately compared by reference. A generation is also required so
 * callbacks queued by an earlier activation of the same client instance cannot affect the
 * current session.
 */
internal class SessionState<ClientIdentity : Any>(
    private val initialBinding: ClientSessionBinding = ClientSessionBinding.LEGACY_TOUCH_ONLY,
) {
    private val lock = Any()
    private var nextGeneration = FIRST_GENERATION
    private var activeSession: ActiveSession<ClientIdentity>? = null

    fun activate(client: ClientIdentity): Long =
        synchronized(lock) {
            check(nextGeneration != EXHAUSTED_GENERATION) { "Session generation exhausted" }
            val generation = nextGeneration++
            activeSession =
                ActiveSession(
                    client = client,
                    generation = generation,
                    binding = initialBinding,
                )
            generation
        }

    fun invalidate(
        client: ClientIdentity,
        generation: Long,
    ): Boolean =
        synchronized(lock) {
            if (!activeSession.matches(client, generation)) return@synchronized false
            activeSession = null
            true
        }

    fun accepts(
        client: ClientIdentity,
        generation: Long,
    ): Boolean = synchronized(lock) { activeSession.matches(client, generation) }

    fun capabilities(
        client: ClientIdentity,
        generation: Long,
    ): ClientSessionCapabilities? =
        binding(client, generation)?.capabilities

    fun binding(
        client: ClientIdentity,
        generation: Long,
    ): ClientSessionBinding? =
        synchronized(lock) {
            activeSession
                ?.takeIf { it.matches(client, generation) }
                ?.binding
        }

    fun updateNegotiatedSession(
        client: ClientIdentity,
        generation: Long,
        binding: ClientSessionBinding,
    ): Boolean =
        synchronized(lock) {
            val current = activeSession ?: return@synchronized false
            if (!current.matches(client, generation)) return@synchronized false
            activeSession = current.copy(binding = binding)
            true
        }

    private data class ActiveSession<ClientIdentity : Any>(
        val client: ClientIdentity,
        val generation: Long,
        val binding: ClientSessionBinding,
    ) {
        fun matches(
            callbackClient: ClientIdentity,
            callbackGeneration: Long,
        ): Boolean = client === callbackClient && generation == callbackGeneration
    }

    private fun ActiveSession<ClientIdentity>?.matches(
        client: ClientIdentity,
        generation: Long,
    ): Boolean = this?.matches(client, generation) == true

    private companion object {
        const val FIRST_GENERATION = 1L
        const val EXHAUSTED_GENERATION = Long.MAX_VALUE
    }
}
