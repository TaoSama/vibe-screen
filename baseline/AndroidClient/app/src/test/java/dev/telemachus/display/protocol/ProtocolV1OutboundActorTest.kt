package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DisplayDescriptor
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.ListDisplaysResponse
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.StartDisplayResponse
import dev.vibescreen.protocol.v1.TransportKind
import dev.vibescreen.protocol.v1.VideoConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class ProtocolV1OutboundActorTest {
    @Test
    fun concurrentBuildersAssignIdsInExactWireOrder() {
        val writes = Collections.synchronizedList(mutableListOf<Envelope>())
        val failure = AtomicReference<Throwable>()
        val actor =
            ProtocolV1OutboundActor(
                session = session(),
                writeEnvelope = writes::add,
                onFailure = failure::set,
                capacity = 8,
            )
        val executor = Executors.newFixedThreadPool(8)
        val start = CountDownLatch(1)
        val finished = CountDownLatch(8)

        repeat(8) { producer ->
            executor.execute {
                start.await()
                repeat(50) { index ->
                    assertTrue(actor.protocolError("producer-$producer-$index"))
                }
                finished.countDown()
            }
        }
        start.countDown()

        assertTrue(finished.await(10, TimeUnit.SECONDS))
        assertTrue(actor.awaitIdle(10_000))
        assertEquals(null, failure.get())
        assertEquals((1L..400L).toList(), writes.map(Envelope::getMessageId))
        actor.close()
        executor.shutdownNow()
    }

    @Test
    fun queuedBuildersAreWrittenInSubmissionOrder() {
        val writes = Collections.synchronizedList(mutableListOf<Envelope>())
        val failure = AtomicReference<Throwable>()
        val actor = ProtocolV1OutboundActor(session(), writes::add, onFailure = failure::set)

        assertTrue(actor.clientHello())
        assertTrue(actor.submit { it.protocolError("after hello") })
        assertTrue(actor.awaitIdle(2_000))

        assertEquals(listOf(1L, 2L), writes.map(Envelope::getMessageId))
        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, writes[0].payloadCase)
        assertEquals(Envelope.PayloadCase.PROTOCOL_ERROR, writes[1].payloadCase)
        assertEquals(null, failure.get())
        actor.close()
    }

    @Test
    fun writerFailureClosesActorAndIsReported() {
        val failure = AtomicReference<Throwable>()
        val reported = CountDownLatch(1)
        val expected = IOException("closed wire")
        val actor =
            ProtocolV1OutboundActor(
                session = session(),
                writeEnvelope = { throw expected },
                onFailure = {
                    failure.set(it)
                    reported.countDown()
                },
                capacity = 1,
            )

        assertTrue(actor.clientHello())
        assertTrue(reported.await(2, TimeUnit.SECONDS))
        assertEquals(expected, failure.get())
        assertTrue(actor.isClosed)
        assertFalse(actor.ping(1))
    }

    @Test
    fun closeReleasesProducerWaitingOnFullMailbox() {
        val writerStarted = CountDownLatch(1)
        val keepWriterBlocked = CountDownLatch(1)
        val submitFinished = CountDownLatch(1)
        val submitResult = AtomicReference<Boolean>()
        val actor =
            ProtocolV1OutboundActor(
                session = session(),
                writeEnvelope = {
                    writerStarted.countDown()
                    keepWriterBlocked.await()
                },
                onFailure = { throw AssertionError(it) },
                capacity = 1,
            )

        assertTrue(actor.clientHello())
        assertTrue(writerStarted.await(2, TimeUnit.SECONDS))
        assertTrue(actor.submit { it.protocolError("fills mailbox") })
        val producer =
            Thread {
                submitResult.set(actor.submit { it.protocolError("blocked producer") })
                submitFinished.countDown()
            }.apply { start() }

        assertFalse(submitFinished.await(100, TimeUnit.MILLISECONDS))
        actor.close()
        assertTrue(submitFinished.await(2, TimeUnit.SECONDS))
        assertFalse(submitResult.get())
        producer.join(2_000)
    }

    @Test
    fun receiveAndWaitPublishesVideoConfiguredBeforeReturning() {
        val configured = AtomicReference<ProtocolV1Session.Action.VideoConfigured>()
        val writes = Collections.synchronizedList(mutableListOf<Envelope>())
        val actor =
            ProtocolV1OutboundActor(
                session = session(),
                writeEnvelope = writes::add,
                onAction = { action ->
                    if (action is ProtocolV1Session.Action.VideoConfigured) configured.set(action)
                },
                onFailure = { throw AssertionError(it) },
            )

        assertTrue(actor.clientHello())
        actor.receiveAndWait(hostHello(1), 2_000)
        actor.receiveAndWait(sessionAccepted(2), 2_000)
        actor.receiveAndWait(displayList(3), 2_000)
        actor.receiveAndWait(startDisplay(4), 2_000)
        actor.receiveAndWait(videoConfig(5), 2_000)

        assertEquals(1920, configured.get().width)
        assertEquals(
            listOf(
                Envelope.PayloadCase.CLIENT_HELLO,
                Envelope.PayloadCase.LIST_DISPLAYS_REQUEST,
                Envelope.PayloadCase.START_DISPLAY_REQUEST,
                Envelope.PayloadCase.VIDEO_CONFIG_RESULT,
            ),
            writes.map(Envelope::getPayloadCase),
        )
        assertEquals((1L..4L).toList(), writes.map(Envelope::getMessageId))
        assertTrue(actor.submit { it.requestKeyframe("configured") })
        assertTrue(actor.awaitIdle(2_000))
        actor.close()
    }

    @Test
    fun receiveAndWaitPropagatesProtocolFailureAndClosesActor() {
        val reported = CountDownLatch(1)
        val actor =
            ProtocolV1OutboundActor(
                session = session(),
                writeEnvelope = {},
                onFailure = { reported.countDown() },
            )

        assertTrue(actor.clientHello())
        val failure =
            org.junit.Assert.assertThrows(IOException::class.java) {
                actor.receiveAndWait(sessionAccepted(1), 2_000)
            }
        assertTrue(failure.message!!.contains("SessionAccepted before HostHello"))
        assertTrue(reported.await(2, TimeUnit.SECONDS))
        assertTrue(actor.isClosed)
    }

    private fun session(): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-actor-test",
            deviceName = "Actor Test",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
            nowNs = { 1_000L },
        )

    private fun hostHello(id: Long): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setHostHello(
                HostHello
                    .newBuilder()
                    .setSelectedProtocol(1)
                    .addCapabilities(Capability.CAPABILITY_TOUCH)
                    .addCapabilities(Capability.CAPABILITY_TELEMETRY)
                    .addCodecs(Codec.CODEC_HEVC),
            ).build()

    private fun sessionAccepted(id: Long): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionAccepted(
                SessionAccepted
                    .newBuilder()
                    .setSessionId(SESSION_ID)
                    .setSessionEpoch(7)
                    .addNegotiatedCapabilities(Capability.CAPABILITY_TOUCH)
                    .addNegotiatedCapabilities(Capability.CAPABILITY_TELEMETRY),
            ).build()

    private fun displayList(id: Long): Envelope =
        base(id)
            .setListDisplaysResponse(
                ListDisplaysResponse
                    .newBuilder()
                    .addDisplays(
                        DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-main")
                            .setLogicalSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080)),
                    ),
            ).build()

    private fun startDisplay(id: Long): Envelope =
        base(id)
            .setStartDisplayResponse(
                StartDisplayResponse.newBuilder().setAccepted(true).setStreamId(42),
            ).build()

    private fun videoConfig(id: Long): Envelope =
        base(id)
            .setVideoConfig(
                VideoConfig
                    .newBuilder()
                    .setConfigEpoch(3)
                    .setCodec(Codec.CODEC_HEVC)
                    .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                    .setFramesPerSecond(60)
                    .setBitrateKbps(12_000)
                    .setStreamId(42),
            ).build()

    private fun base(id: Long): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(SESSION_ID)
            .setSessionEpoch(7)

    companion object {
        private val SESSION_ID = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4))
    }
}
