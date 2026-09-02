package dev.telemachus.display

internal class DecoderUseGate<Decoder> {
    private val lock = Any()
    private var current: Decoder? = null

    fun current(): Decoder? = synchronized(lock) { current }

    fun installIf(
        decoder: Decoder?,
        admit: () -> Boolean,
    ): Boolean =
        synchronized(lock) {
            if (!admit()) {
                false
            } else {
                current = decoder
                true
            }
        }

    /** Runs [onCleared] while holding the gate after [current] has been cleared. */
    fun clear(onCleared: (Decoder?) -> Unit = {}): Decoder? =
        synchronized(lock) {
            val decoder = current
            current = null
            onCleared(decoder)
            decoder
        }

    /** Runs [onSuccess] while holding the gate after [current] has been updated. */
    fun compareAndSet(
        expected: Decoder?,
        update: Decoder?,
        onSuccess: () -> Unit = {},
    ): Boolean =
        synchronized(lock) {
            if (current !== expected) {
                false
            } else {
                current = update
                onSuccess()
                true
            }
        }

    fun replaceIfCurrent(
        expected: Decoder?,
        update: Decoder?,
        admit: () -> Boolean,
    ): Boolean =
        synchronized(lock) {
            when {
                current === expected -> {
                    if (!admit()) {
                        false
                    } else {
                        current = update
                        true
                    }
                }
                current === update -> {
                    if (!admit()) {
                        false
                    } else {
                        true
                    }
                }
                else -> false
            }
        }

    fun <Result> withCurrent(action: (Decoder) -> Result): Result? =
        synchronized(lock) {
            val decoder = current ?: return@synchronized null
            action(decoder)
        }
}
