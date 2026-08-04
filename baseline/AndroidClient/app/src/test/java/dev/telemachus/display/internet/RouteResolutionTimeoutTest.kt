package dev.telemachus.display.internet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class RouteResolutionTimeoutTest {
    @Test
    fun lateRouteCancelsDeadlineAndCannotFireOrResolveTwice() {
        val scheduler = FakeRouteResolutionScheduler()
        var failures = 0
        val timeout = RouteResolutionTimeout(scheduler, AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS)

        timeout.arm { failures++ }
        timeout.arm { failures++ }
        assertEquals(1, scheduler.tasks.size)
        timeout.cancel()
        scheduler.advanceBy(AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS)
        timeout.cancel()

        assertEquals(0, failures)
        assertTrue(scheduler.tasks.single().cancelled)
    }

    @Test
    fun unresolvedRouteFailsOnceAtFiveSecondDeadline() {
        val scheduler = FakeRouteResolutionScheduler()
        var failures = 0
        val timeout = RouteResolutionTimeout(scheduler, AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS)

        timeout.arm { failures++ }
        scheduler.advanceBy(AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS - 1)
        assertEquals(0, failures)
        scheduler.advanceBy(1)
        scheduler.advanceBy(AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS)

        assertEquals(1, failures)
    }

    @Test
    fun disconnectCancellationAllowsASeparateReconnectDeadline() {
        val scheduler = FakeRouteResolutionScheduler()
        var failures = 0
        val timeout = RouteResolutionTimeout(scheduler, AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS)

        timeout.arm { failures++ }
        timeout.cancel()
        timeout.arm { failures++ }
        scheduler.advanceBy(AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS)

        assertEquals(1, failures)
        assertEquals(2, scheduler.tasks.size)
    }

    @Test
    fun lateRouteCancellationInterleavedWithArmCannotLeaveAStaleDeadline() {
        val scheduler = FakeRouteResolutionScheduler()
        var failures = 0
        lateinit var timeout: RouteResolutionTimeout
        timeout = RouteResolutionTimeout(scheduler, AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS)
        scheduler.duringSchedule = { timeout.cancel() }

        timeout.arm { failures++ }
        scheduler.advanceBy(AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS)

        assertEquals(0, failures)
        assertTrue(scheduler.tasks.single().cancelled)
    }

    @Test
    fun generationAdvanceWhileFiredCallbackWaitsRejectsOldDeadline() {
        val scheduler = FakeRouteResolutionScheduler()
        val timeout = RouteResolutionTimeout(scheduler, AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS)
        val callbackStarted = CountDownLatch(1)
        val continueCallback = CountDownLatch(1)
        var generation = 1L
        var failures = 0
        val capturedGeneration = generation
        timeout.arm {
            callbackStarted.countDown()
            continueCallback.await()
            if (capturedGeneration == generation) failures++
        }

        val timerThread = Thread { scheduler.advanceBy(AndroidWebRtcPeerEngine.ROUTE_RESOLUTION_TIMEOUT_MS) }
        timerThread.start()
        assertTrue(callbackStarted.await(2, TimeUnit.SECONDS))
        generation++
        continueCallback.countDown()
        timerThread.join(2_000)

        assertEquals(0, failures)
    }
}

private class FakeRouteResolutionScheduler : RouteResolutionScheduler {
    var now = 0L
    val tasks = mutableListOf<Task>()
    var duringSchedule: (() -> Unit)? = null

    override fun schedule(delayMillis: Long, task: () -> Unit): RouteResolutionCancellation {
        val scheduled = Task(now + delayMillis, task)
        tasks += scheduled
        duringSchedule?.invoke()
        return RouteResolutionCancellation { scheduled.cancelled = true }
    }

    fun advanceBy(milliseconds: Long) {
        now += milliseconds
        tasks.filter { !it.cancelled && !it.ran && it.deadline <= now }.forEach {
            it.ran = true
            it.action()
        }
    }

    data class Task(
        val deadline: Long,
        val action: () -> Unit,
        var cancelled: Boolean = false,
        var ran: Boolean = false,
    )
}
