package dev.telemachus.display.internet

/**
 * Keeps reliable controller lifecycle boundaries FIFO while treating analog
 * state as replaceable. Every analog batch must be a complete snapshot of all
 * active controllers, so replacing it cannot leave an omitted controller stale.
 */
class InternetControllerSendQueue<Event : Any>(
    private val maximumStructuralBatches: Int = DEFAULT_MAXIMUM_STRUCTURAL_BATCHES,
) {
    init {
        require(maximumStructuralBatches > 0)
    }

    enum class Delivery { ANALOG, FULL_STATE_STRUCTURAL }

    enum class EnqueueResult { ACCEPTED, COALESCED, STRUCTURAL_OVERFLOW }

    data class DrainResult(
        val sentEvents: Int,
        val blocked: Boolean,
        val failure: Throwable? = null,
    )

    private val lock = Any()
    private val batches = ArrayDeque<Batch<Event>>()

    fun enqueue(
        events: List<Event>,
        delivery: Delivery,
    ): EnqueueResult {
        require(events.isNotEmpty())
        val copied = events.toList()
        return synchronized(lock) {
            when (delivery) {
                Delivery.ANALOG -> {
                    val trailing = batches.lastOrNull()
                    if (trailing?.delivery == Delivery.ANALOG && trailing.nextIndex == 0 && !trailing.inFlight) {
                        batches[batches.lastIndex] = Batch(Delivery.ANALOG, copied)
                        EnqueueResult.COALESCED
                    } else {
                        batches.addLast(Batch(Delivery.ANALOG, copied))
                        EnqueueResult.ACCEPTED
                    }
                }

                Delivery.FULL_STATE_STRUCTURAL -> {
                    val trailing = batches.lastOrNull()
                    if (trailing?.delivery == Delivery.ANALOG && trailing.nextIndex == 0 && !trailing.inFlight) {
                        batches.removeLast()
                    }
                    if (batches.count { it.delivery == Delivery.FULL_STATE_STRUCTURAL } >= maximumStructuralBatches) {
                        return@synchronized EnqueueResult.STRUCTURAL_OVERFLOW
                    }
                    batches.addLast(Batch(Delivery.FULL_STATE_STRUCTURAL, copied))
                    EnqueueResult.ACCEPTED
                }
            }
        }
    }

    /** Sends until transport backpressure rejects an event, retaining that event for the next tick. */
    fun drain(send: (Event) -> Boolean): DrainResult {
        var sent = 0
        while (true) {
            val claim =
                synchronized(lock) {
                    val batch = batches.firstOrNull() ?: return@synchronized null
                    if (batch.inFlight) return DrainResult(sentEvents = sent, blocked = true)
                    batch.inFlight = true
                    Claim(batch, batch.current())
                }
                ?: return DrainResult(sentEvents = sent, blocked = false)
            var accepted = false
            var failure: Throwable? = null
            try {
                accepted = send(claim.event)
            } catch (sendFailure: Throwable) {
                failure = sendFailure
            } finally {
                synchronized(lock) {
                    claim.batch.inFlight = false
                    if (accepted) {
                        val batch = batches.firstOrNull()
                        if (batch === claim.batch && batch.current() === claim.event) {
                            batch.nextIndex++
                            if (batch.nextIndex == batch.events.size) batches.removeFirst()
                        }
                    }
                }
            }
            failure?.let { return DrainResult(sentEvents = sent, blocked = false, failure = it) }
            if (!accepted) return DrainResult(sentEvents = sent, blocked = true)
            sent++
        }
    }

    fun clear() = synchronized(lock) { batches.clear() }

    internal fun pendingBatches(): List<Pair<Delivery, List<Event>>> =
        synchronized(lock) {
            batches.map { batch -> batch.delivery to batch.events.drop(batch.nextIndex) }
        }

    private data class Batch<Event : Any>(
        val delivery: Delivery,
        val events: List<Event>,
        var nextIndex: Int = 0,
        var inFlight: Boolean = false,
    ) {
        fun current(): Event = events[nextIndex]
    }

    private data class Claim<Event : Any>(
        val batch: Batch<Event>,
        val event: Event,
    )

    private companion object {
        const val DEFAULT_MAXIMUM_STRUCTURAL_BATCHES = 128
    }
}
