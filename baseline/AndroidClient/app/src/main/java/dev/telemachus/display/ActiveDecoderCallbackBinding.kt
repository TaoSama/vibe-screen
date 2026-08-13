package dev.telemachus.display

internal class ActiveDecoderCallbackBinding<Decoder : Any>(
    private val decoder: Decoder,
    private val sessionGeneration: Long,
    private val isActive: (Decoder, Long) -> Boolean,
) {
    fun isActive(): Boolean = isActive(decoder, sessionGeneration)

    fun runIfActive(action: () -> Unit): Boolean {
        if (!isActive()) return false
        action()
        return true
    }
}
