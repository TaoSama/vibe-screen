package dev.telemachus.display.internet

/** One-slot queue: congestion always replaces stale unsent media with the newest packet. */
internal class LatestFrameSlot {
    private var pending: ByteArray? = null

    fun replace(payload: ByteArray) {
        pending = payload.copyOf()
    }

    fun take(): ByteArray? = pending.also { pending = null }

    fun hasPending(): Boolean = pending != null

    fun clear() {
        pending = null
    }
}
