package dev.telemachus.display.internet

fun interface RouteResolutionCancellation {
    fun cancel()
}

fun interface RouteResolutionScheduler {
    fun schedule(delayMillis: Long, task: () -> Unit): RouteResolutionCancellation
}

/** One pending candidate-route deadline per WebRTC product session. */
internal class RouteResolutionTimeout(
    private val scheduler: RouteResolutionScheduler,
    private val timeoutMillis: Long,
) {
    private val lock = Any()
    private var generation = 0L
    private var armed = false
    private var cancellation: RouteResolutionCancellation? = null

    fun arm(onTimeout: () -> Unit) {
        val token =
            synchronized(lock) {
                if (armed) return
                armed = true
                ++generation
            }
        val scheduled =
            scheduler.schedule(timeoutMillis) {
                val fire =
                    synchronized(lock) {
                        if (!armed || generation != token) {
                            false
                        } else {
                            armed = false
                            cancellation = null
                            true
                        }
                    }
                if (fire) onTimeout()
            }
        val cancelImmediately =
            synchronized(lock) {
                if (armed && generation == token) {
                    cancellation = scheduled
                    false
                } else {
                    true
                }
            }
        if (cancelImmediately) scheduled.cancel()
    }

    fun cancel() {
        val pending =
            synchronized(lock) {
                generation++
                armed = false
                cancellation.also { cancellation = null }
            }
        pending?.cancel()
    }
}
