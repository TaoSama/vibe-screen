package dev.telemachus.display.internet

/** Runs every cleanup action and reports all failures without losing their order. */
internal fun runBestEffort(vararg actions: () -> Unit) {
    var firstFailure: Throwable? = null
    actions.forEach { action ->
        try {
            action()
        } catch (failure: Throwable) {
            if (firstFailure == null) {
                firstFailure = failure
            } else {
                firstFailure?.addSuppressed(failure)
            }
        }
    }
    firstFailure?.let { throw it }
}
