package dev.telemachus.display

import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.TransportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class ProtocolV1SchedulerSerializationTest {
    @Test
    fun concurrentBuildersAllocateMessageIdsInWireOrder() {
        val session =
            ProtocolV1Session(
                deviceId = "android-scheduler-test",
                deviceName = "Scheduler Test",
                transport = TransportKind.TRANSPORT_KIND_USB,
                codecs = listOf(Codec.CODEC_HEVC),
                nowNs = { 1_000L },
            )
        val writes = Collections.synchronizedList(mutableListOf<Envelope>())
        val failures = Collections.synchronizedList(mutableListOf<Throwable>())
        val scheduler =
            OutboundCommandScheduler<(ProtocolV1Session) -> Envelope>(
                capacity = 32,
                writer = { build -> writes += build(session) },
                onWriteFailure = { failures += it.cause },
                threadName = "ProtocolV1SchedulerTest",
            )
        val producers = Executors.newFixedThreadPool(8)
        val start = CountDownLatch(1)
        val finished = CountDownLatch(8)

        repeat(8) { producer ->
            producers.execute {
                start.await()
                repeat(25) { index ->
                    while (true) {
                        val result =
                            scheduler.submit(
                                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                                { active -> active.protocolError("producer-$producer-$index") },
                                timeoutMillis = 500,
                            )
                        if (result != OutboundCommandScheduler.Submission.TIMED_OUT) break
                    }
                }
                finished.countDown()
            }
        }
        start.countDown()

        assertTrue(finished.await(10, TimeUnit.SECONDS))
        assertTrue(scheduler.shutdownGracefully(10_000))
        assertTrue(failures.isEmpty())
        assertEquals((1L..200L).toList(), writes.map(Envelope::getMessageId))
        producers.shutdownNow()
    }

    @Test
    fun moveCoalescingReplacesAWholePointerBatch() {
        val writerStarted = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val writes = Collections.synchronizedList(mutableListOf<List<Int>>())
        val scheduler =
            OutboundCommandScheduler<List<Int>>(
                capacity = 4,
                writer = { command ->
                    if (command == listOf(0)) {
                        writerStarted.countDown()
                        releaseWriter.await()
                    }
                    writes += command
                },
                onWriteFailure = { throw AssertionError(it.cause) },
            )
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH, listOf(0)),
        )
        assertTrue(writerStarted.await(2, TimeUnit.SECONDS))
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(OutboundCommandScheduler.Kind.MOVE, listOf(7, 9)),
        )
        assertEquals(
            OutboundCommandScheduler.Submission.COALESCED,
            scheduler.submit(OutboundCommandScheduler.Kind.MOVE, listOf(11, 13)),
        )
        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(2_000))
        assertEquals(listOf(listOf(0), listOf(11, 13)), writes)
    }
}
