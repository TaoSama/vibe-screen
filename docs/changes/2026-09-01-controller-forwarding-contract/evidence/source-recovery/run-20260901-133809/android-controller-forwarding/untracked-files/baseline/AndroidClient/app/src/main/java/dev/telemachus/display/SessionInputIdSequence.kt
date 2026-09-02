package dev.telemachus.display

import java.util.concurrent.atomic.AtomicLong

/** Allocates one positive input-id namespace for a negotiated product session. */
internal class SessionInputIdSequence {
    private val lastIssued = AtomicLong(0L)

    fun next(): Long {
        val next = lastIssued.incrementAndGet()
        check(next > 0L) { "Session input identifier exhausted" }
        return next
    }

    fun resetForNewSession() {
        lastIssued.set(0L)
    }
}
