package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.TransportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class StreamProtocolSideEffectOwnerTest {
    @Test
    fun `side effects require current connected protocol session owner`() {
        val currentSession = session()
        val staleSession = session()
        var connected = true
        val acceptedGenerations = mutableSetOf(7L)
        val owner = StreamProtocolSideEffectOwner(
            isConnected = { connected },
            acceptsConnectionGeneration = acceptedGenerations::contains,
        )
        owner.activate(currentSession, 7L)

        assertTrue(owner.isCurrent(currentSession, 7L))
        assertFalse(owner.isCurrent(staleSession, 7L))
        assertFalse(owner.isCurrent(currentSession, 6L))

        acceptedGenerations.clear()
        assertFalse(owner.isCurrent(currentSession, 7L))

        acceptedGenerations += 7L
        connected = false
        assertFalse(owner.isCurrent(currentSession, 7L))

        connected = true
        owner.activate(currentSession, 8L)
        assertFalse(owner.isCurrent(currentSession, 7L))

        owner.activate(currentSession, 7L)
        owner.clear()
        assertFalse(owner.isCurrent(currentSession, 7L))
    }

    @Test
    fun `wake host pending requests are duplicate and capacity gated`() {
        val session = session()
        val owner = alwaysCurrentOwner(session = session, maximumPendingWakeHostRequests = 2)
        val first = ByteString.copyFromUtf8("first")
        val second = ByteString.copyFromUtf8("second")
        val third = ByteString.copyFromUtf8("third")

        assertTrue(owner.trackWakeHostRequest(first, session, 1L))
        assertFalse(owner.trackWakeHostRequest(first, session, 1L))
        assertTrue(owner.trackWakeHostRequest(second, session, 1L))
        assertFalse(owner.trackWakeHostRequest(third, session, 1L))

        owner.releaseWakeHostRequest(first, session, 1L)
        assertTrue(owner.trackWakeHostRequest(third, session, 1L))
    }

    @Test
    fun `wake host release must match original protocol owner`() {
        val currentSession = session()
        val staleSession = session()
        val owner = alwaysCurrentOwner(session = currentSession, maximumPendingWakeHostRequests = 1)
        val request = ByteString.copyFromUtf8("request")
        val blocked = ByteString.copyFromUtf8("blocked")

        assertTrue(owner.trackWakeHostRequest(request, currentSession, 1L))
        owner.releaseWakeHostRequest(request, staleSession, 1L)
        assertFalse(owner.trackWakeHostRequest(blocked, currentSession, 1L))

        owner.releaseWakeHostRequest(request, currentSession, 2L)
        assertFalse(owner.trackWakeHostRequest(blocked, currentSession, 1L))

        owner.releaseWakeHostRequest(request, currentSession, 1L)
        assertTrue(owner.trackWakeHostRequest(blocked, currentSession, 1L))
    }

    @Test
    fun `wake host requests require current protocol owner before reservation`() {
        val currentSession = session()
        val staleSession = session()
        var connected = true
        var currentGeneration = 5L
        val owner = StreamProtocolSideEffectOwner(
            isConnected = { connected },
            acceptsConnectionGeneration = { it == currentGeneration },
        )
        owner.activate(currentSession, 5L)
        val request = ByteString.copyFromUtf8("request")

        assertFalse(owner.trackWakeHostRequest(request, staleSession, 5L))
        assertFalse(owner.trackWakeHostRequest(request, currentSession, 4L))

        connected = false
        assertFalse(owner.trackWakeHostRequest(request, currentSession, 5L))

        connected = true
        assertTrue(owner.trackWakeHostRequest(request, currentSession, 5L))

        currentGeneration = 6L
        assertFalse(owner.trackWakeHostRequest(ByteString.copyFromUtf8("next"), currentSession, 5L))
    }

    @Test
    fun `clearing side effect owner releases outstanding wake requests`() {
        val session = session()
        val owner = alwaysCurrentOwner(session = session, maximumPendingWakeHostRequests = 1)
        val request = ByteString.copyFromUtf8("request")

        assertTrue(owner.trackWakeHostRequest(request, session, 1L))
        assertFalse(owner.trackWakeHostRequest(ByteString.copyFromUtf8("blocked"), session, 1L))

        owner.clear()

        owner.activate(session, 1L)
        assertTrue(owner.trackWakeHostRequest(ByteString.copyFromUtf8("after-clear"), session, 1L))
    }

    @Test
    fun `closing admission rejects new wake requests but keeps existing reservations releasable`() {
        val session = session()
        val owner = alwaysCurrentOwner(session = session, maximumPendingWakeHostRequests = 1)
        val request = ByteString.copyFromUtf8("request")

        assertTrue(owner.trackWakeHostRequest(request, session, 1L))
        owner.closeAdmission()

        assertFalse(owner.trackWakeHostRequest(ByteString.copyFromUtf8("blocked"), session, 1L))
        assertTrue(owner.releaseWakeHostRequest(request, session, 1L))
        assertFalse(owner.releaseWakeHostRequest(request, session, 1L))
    }

    @Test
    fun `cancelling wake requests releases only matching session and generation`() {
        val currentSession = session()
        val otherSession = session()
        val owner = StreamProtocolSideEffectOwner(
            isConnected = { true },
            acceptsConnectionGeneration = { it == 1L },
            maximumPendingWakeHostRequests = 3,
        )
        val firstRequest = ByteString.copyFromUtf8("first")
        val secondRequest = ByteString.copyFromUtf8("second")

        owner.activate(currentSession, 1L)
        assertTrue(owner.trackWakeHostRequest(firstRequest, currentSession, 1L, correlationId = 10L))
        assertTrue(owner.trackWakeHostRequest(secondRequest, currentSession, 1L, correlationId = 20L))

        assertTrue(owner.cancelWakeHostRequests(otherSession, 1L).isEmpty())
        assertTrue(owner.cancelWakeHostRequests(currentSession, 2L).isEmpty())
        assertTrue(owner.hasWakeHostRequest(firstRequest, currentSession, 1L))
        assertTrue(owner.hasWakeHostRequest(secondRequest, currentSession, 1L))

        val cancelled = owner.cancelWakeHostRequests(currentSession, 1L)

        assertEquals(listOf(firstRequest, secondRequest), cancelled.map { it.requestId })
        assertEquals(listOf(10L, 20L), cancelled.map { it.correlationId })
        assertFalse(owner.hasWakeHostRequest(firstRequest, currentSession, 1L))
        assertFalse(owner.hasWakeHostRequest(secondRequest, currentSession, 1L))
    }

    @Test
    fun `file offer decisions are claimed only by current protocol owner`() {
        val session = session()
        var connected = true
        var currentGeneration = 3L
        val owner = StreamProtocolSideEffectOwner(
            isConnected = { connected },
            acceptsConnectionGeneration = { it == currentGeneration },
            maximumPendingFileOffers = 1,
        )
        owner.activate(session, 3L)
        val transfer = ByteString.copyFromUtf8("transfer")
        val blocked = ByteString.copyFromUtf8("blocked")

        assertTrue(owner.trackFileOffer(transfer, session, 3L))
        assertFalse(owner.trackFileOffer(transfer, session, 3L))
        assertFalse(owner.trackFileOffer(blocked, session, 3L))

        currentGeneration = 4L
        assertNull(owner.claimFileOffer(transfer))
        assertFalse(owner.trackFileOffer(blocked, session, 3L))

        currentGeneration = 3L
        assertTrue(owner.trackFileOffer(blocked, session, 3L))
        val claimed = owner.claimFileOffer(blocked)
        assertTrue(claimed?.session === session)
        assertEquals(3L, claimed?.connectionGeneration)
        assertNull(owner.claimFileOffer(blocked))

        assertTrue(owner.trackFileOffer(transfer, session, 3L))
        connected = false
        assertNull(owner.claimFileOffer(transfer))

        connected = true
        assertTrue(owner.trackFileOffer(transfer, session, 3L))
        owner.clear()
        assertNull(owner.claimFileOffer(transfer))
    }

    @Test
    fun `run if current permits reentrant owner calls while holding current owner`() {
        val session = session()
        val owner = alwaysCurrentOwner(session = session, maximumPendingFileOffers = 1)
        val transfer = ByteString.copyFromUtf8("transfer")

        val admitted = owner.runIfCurrent(session, 1L) {
            owner.trackFileOffer(transfer, session, 1L)
        }

        assertTrue(admitted == true)
        val claimed = owner.claimFileOffer(transfer)
        assertTrue(claimed?.session === session)
        assertEquals(1L, claimed?.connectionGeneration)
    }

    @Test
    fun `run if current releases owner lock before side effect completes`() {
        val session = session()
        val owner = alwaysCurrentOwner(session = session)
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val clearReturned = CountDownLatch(1)
        val executor = Executors.newFixedThreadPool(2)

        try {
            val sideEffect = executor.submit<Boolean> {
                owner.runIfCurrent(session, 1L) {
                    entered.countDown()
                    assertTrue(release.await(5, TimeUnit.SECONDS))
                    true
                } ?: false
            }
            assertTrue(entered.await(5, TimeUnit.SECONDS))

            val clear = executor.submit {
                owner.clear()
                clearReturned.countDown()
            }

            assertTrue(clearReturned.await(5, TimeUnit.SECONDS))
            assertFalse(owner.isCurrent(session, 1L))

            release.countDown()
            assertTrue(sideEffect.get(5, TimeUnit.SECONDS))
            clear.get(5, TimeUnit.SECONDS)
            assertFalse(owner.isCurrent(session, 1L))
        } finally {
            release.countDown()
            executor.shutdownNow()
        }
    }

    @Test
    fun `clearing side effect owner releases outstanding file offers`() {
        val session = session()
        val owner = StreamProtocolSideEffectOwner(
            isConnected = { true },
            acceptsConnectionGeneration = { it == 1L },
            maximumPendingFileOffers = 1,
        )
        owner.activate(session, 1L)
        val transfer = ByteString.copyFromUtf8("transfer")

        assertTrue(owner.trackFileOffer(transfer, session, 1L))
        assertFalse(owner.trackFileOffer(ByteString.copyFromUtf8("blocked"), session, 1L))

        owner.clear()

        owner.activate(session, 1L)
        assertTrue(owner.trackFileOffer(ByteString.copyFromUtf8("after-clear"), session, 1L))
    }

    @Test
    fun `wake host pending capacity must be positive`() {
        assertThrows(IllegalArgumentException::class.java) {
            alwaysCurrentOwner(maximumPendingWakeHostRequests = 0)
        }
        assertThrows(IllegalArgumentException::class.java) {
            alwaysCurrentOwner(maximumPendingFileOffers = 0)
        }
    }

    private fun alwaysCurrentOwner(
        session: ProtocolV1Session = session(),
        maximumPendingWakeHostRequests: Int = StreamProtocolSideEffectOwner.DEFAULT_MAXIMUM_PENDING_WAKE_HOST_REQUESTS,
        maximumPendingFileOffers: Int = StreamProtocolSideEffectOwner.DEFAULT_MAXIMUM_PENDING_FILE_OFFERS,
    ): StreamProtocolSideEffectOwner {
        return StreamProtocolSideEffectOwner(
            isConnected = { true },
            acceptsConnectionGeneration = { it == 1L },
            maximumPendingWakeHostRequests = maximumPendingWakeHostRequests,
            maximumPendingFileOffers = maximumPendingFileOffers,
        ).also { it.activate(session, 1L) }
    }

    private fun session(): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "device",
            deviceName = "Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_H264),
        )
}
