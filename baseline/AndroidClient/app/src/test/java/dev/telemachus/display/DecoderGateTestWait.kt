package dev.telemachus.display

import java.util.concurrent.TimeUnit

internal fun waitUntilBlockedByDecoderGate(
    thread: Thread,
    timeoutSeconds: Long,
    operation: String,
) {
    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(timeoutSeconds)
    while (System.nanoTime() < deadline) {
        if (thread.state == Thread.State.BLOCKED) return
        Thread.sleep(10)
    }
    throw AssertionError("Expected $operation to wait for the decoder gate")
}
