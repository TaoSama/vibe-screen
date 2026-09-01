package dev.telemachus.display.internet

import dev.telemachus.display.MAXIMUM_CONTROLLER_STRUCTURAL_BATCHES

/**
 * Keeps reliable controller lifecycle boundaries FIFO while treating analog
 * state as replaceable. Every analog batch must be a complete snapshot of all
 * active controllers, so replacing it cannot leave an omitted controller stale.
 */
internal class InternetControllerSendQueue<Event : Any>(
    private val maximumStructuralBatches: Int = MAXIMUM_CONTROLLER_STRUCTURAL_BATCHES,
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
        val copied = events.toMutableList()
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
                    if (batches.count { it.delivery == Delivery.FULL_STATE_STRUCTURAL } >= maximumStructuralBatches) {
                        return@synchronized EnqueueResult.STRUCTURAL_OVERFLOW
                    }
                    val trailing = batches.lastOrNull()
                    if (trailing?.delivery == Delivery.ANALOG && trailing.nextIndex == 0 && !trailing.inFlight) {
                        batches.removeLast()
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

    /**
     * Sends the first currently admissible event, skipping causally blocked events
     * only when doing so does not pass an earlier event for the same controller.
     */
    fun drainSelectable(
        canSend: (Event) -> Boolean,
        sharesOrderingKey: (Event, Event) -> Boolean,
        send: (Event) -> Boolean,
    ): DrainResult {
        var sent = 0
        while (true) {
            val claim =
                synchronized(lock) {
                    selectClaimLocked(canSend, sharesOrderingKey)
                }
            when (claim) {
                SelectClaim.Blocked -> return DrainResult(sentEvents = sent, blocked = true)
                null -> return DrainResult(sentEvents = sent, blocked = false)
                is SelectClaim.Event<*> -> {
                    @Suppress("UNCHECKED_CAST")
                    claim as SelectClaim.Event<Event>
                    var accepted = false
                    var failure: Throwable? = null
                    try {
                        accepted = send(claim.event)
                    } catch (sendFailure: Throwable) {
                        failure = sendFailure
                    } finally {
                        synchronized(lock) {
                            claim.batch.inFlight = false
                            if (accepted) removeClaimedEventLocked(claim)
                        }
                    }
                    failure?.let { return DrainResult(sentEvents = sent, blocked = false, failure = it) }
                    if (!accepted) return DrainResult(sentEvents = sent, blocked = true)
                    sent++
                }
            }
        }
    }

    fun clear() = synchronized(lock) {
        batches.forEach { batch -> batch.inFlight = false }
        batches.clear()
    }

    internal fun pendingBatches(): List<Pair<Delivery, List<Event>>> =
        synchronized(lock) {
            batches.map { batch -> batch.delivery to batch.events.drop(batch.nextIndex) }
        }

    private fun selectClaimLocked(
        canSend: (Event) -> Boolean,
        sharesOrderingKey: (Event, Event) -> Boolean,
    ): SelectClaim<Event>? {
        val blockedEvents = mutableListOf<Event>()
        var sawBlocked = false
        batches.forEach { batch ->
            if (batch.inFlight) return SelectClaim.Blocked
            var index = batch.nextIndex
            while (index < batch.events.size) {
                val event = batch.events[index]
                if (blockedEvents.any { blocked -> sharesOrderingKey(blocked, event) }) {
                    index++
                    continue
                }
                if (!canSend(event)) {
                    blockedEvents += event
                    sawBlocked = true
                    index++
                    continue
                }
                batch.inFlight = true
                return SelectClaim.Event(batch, index, event)
            }
        }
        return if (sawBlocked) SelectClaim.Blocked else null
    }

    private fun removeClaimedEventLocked(claim: SelectClaim.Event<Event>) {
        val batch = claim.batch
        if (batches.none { it === batch }) return
        if (batch.events.getOrNull(claim.index) != claim.event) return
        batch.events.removeAt(claim.index)
        if (batch.nextIndex > batch.events.size) batch.nextIndex = batch.events.size
        if (batch.nextIndex == batch.events.size) {
            val batchIndex = batches.indexOfFirst { it === batch }
            if (batchIndex >= 0) batches.removeAt(batchIndex)
        }
    }

    private data class Batch<Event : Any>(
        val delivery: Delivery,
        val events: MutableList<Event>,
        var nextIndex: Int = 0,
        var inFlight: Boolean = false,
    ) {
        fun current(): Event = events[nextIndex]
    }

    private sealed interface SelectClaim<out Event : Any> {
        data object Blocked : SelectClaim<Nothing>

        data class Event<Event : Any>(
            val batch: Batch<Event>,
            val index: Int,
            val event: Event,
        ) : SelectClaim<Event>
    }

    private data class Claim<Event : Any>(
        val batch: Batch<Event>,
        val event: Event,
    )

}
