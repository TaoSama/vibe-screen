package dev.telemachus.display

/** Native input that must be balanced before its owning stream session ends. */
internal data class NativeInputReleasePlan(
    val pressedKeyUsages: List<Int>,
    val pointer: NativePointerSnapshot?,
) {
    val isEmpty: Boolean
        get() = pressedKeyUsages.isEmpty() && pointer == null
}

internal data class NativePointerSnapshot(
    val x: Float,
    val y: Float,
)

internal enum class NativeInputReleaseSubmission {
    NOT_NEEDED,
    ACCEPTED,
    REJECTED,
}

/** Owns the release-before-teardown ordering for one proactive boundary. */
internal class NativeInputReleaseCoordinator<ClientIdentity : Any>(
    private val state: NativeInputSessionState<ClientIdentity>,
) {
    fun completeBoundary(
        client: ClientIdentity,
        generation: Long,
        submitRelease: (NativeInputReleasePlan) -> Boolean,
        afterRelease: () -> Unit,
    ): NativeInputReleaseSubmission {
        try {
            val release = state.takeRelease(client, generation)
            if (release == null || release.isEmpty) return NativeInputReleaseSubmission.NOT_NEEDED
            return if (submitRelease(release)) {
                NativeInputReleaseSubmission.ACCEPTED
            } else {
                NativeInputReleaseSubmission.REJECTED
            }
        } finally {
            afterRelease()
        }
    }
}

internal object NativeInputReleaseBatch {
    fun <Event> build(
        release: NativeInputReleasePlan,
        keyUp: (Int) -> Event,
        pointerTerminal: (NativePointerSnapshot) -> Event,
    ): List<Event> =
        buildList {
            release.pressedKeyUsages.forEach { add(keyUp(it)) }
            release.pointer?.let { add(pointerTerminal(it)) }
        }
}

/**
 * Tracks input boundaries by session identity and generation. A stale callback
 * can neither mutate nor drain the replacement session's state.
 */
internal class NativeInputSessionState<ClientIdentity : Any> {
    private val lock = Any()
    private var activeOwner: Owner<ClientIdentity>? = null

    fun admit(
        client: ClientIdentity,
        generation: Long,
    ): Unit = synchronized(lock) {
        if (activeOwner.matches(client, generation)) return@synchronized
        activeOwner = Owner(client, generation)
    }

    fun recordKey(
        client: ClientIdentity,
        generation: Long,
        usbHidUsage: Int,
        pressed: Boolean,
    ): Boolean =
        synchronized(lock) {
            val owner = activeOwner.takeIf { it.matches(client, generation) } ?: return@synchronized false
            if (pressed) owner.pressedKeyUsages += usbHidUsage else owner.pressedKeyUsages -= usbHidUsage
            true
        }

    fun recordPointer(
        client: ClientIdentity,
        generation: Long,
        x: Float,
        y: Float,
        buttonMask: Int,
    ): Boolean =
        synchronized(lock) {
            val owner = activeOwner.takeIf { it.matches(client, generation) } ?: return@synchronized false
            owner.pointer = NativePointerState(x, y, buttonMask)
            true
        }

    fun takeRelease(
        client: ClientIdentity,
        generation: Long,
    ): NativeInputReleasePlan? =
        synchronized(lock) {
            val owner = activeOwner.takeIf { it.matches(client, generation) } ?: return@synchronized null
            val release =
                NativeInputReleasePlan(
                    pressedKeyUsages = owner.pressedKeyUsages.sorted(),
                    pointer = owner.pointer?.takeIf { it.buttonMask != 0 }?.let { NativePointerSnapshot(it.x, it.y) },
                )
            owner.pressedKeyUsages.clear()
            owner.pointer = null
            release
        }

    fun discard(
        client: ClientIdentity,
        generation: Long,
    ): Boolean =
        synchronized(lock) {
            if (!activeOwner.matches(client, generation)) return@synchronized false
            activeOwner = null
            true
        }

    private class Owner<ClientIdentity : Any>(
        val client: ClientIdentity,
        val generation: Long,
        val pressedKeyUsages: MutableSet<Int> = mutableSetOf(),
        var pointer: NativePointerState? = null,
    )

    private data class NativePointerState(
        val x: Float,
        val y: Float,
        val buttonMask: Int,
    )

    private fun Owner<ClientIdentity>?.matches(
        client: ClientIdentity,
        generation: Long,
    ): Boolean = this?.client === client && this.generation == generation
}
