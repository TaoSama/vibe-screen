package dev.telemachus.display.transport

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread

class StreamTransportOwnerTest {
    @Test
    fun promotesCurrentCandidateToActive() {
        val owner = StreamTransportOwner<FakeConnection>()
        val connection = FakeConnection()
        val candidate = owner.createCandidate(7, { it == 7L }) { connection }

        val promotion = owner.promote(candidate) { generation -> generation == 7L }

        assertTrue(promotion.promoted)
        assertTrue(promotion.closeFailures.isEmpty())
        assertSame(connection, owner.activeConnection())
        assertEquals(0, connection.closeCount)
    }

    @Test
    fun rejectsIneligibleCandidateBeforeCreatingConnection() {
        val owner = StreamTransportOwner<FakeConnection>()
        val factoryCalled = AtomicBoolean()

        val rejection =
            assertThrows(StreamTransportCandidateRejectedException::class.java) {
                owner.createCandidate(3, { false }) {
                    factoryCalled.set(true)
                    FakeConnection()
                }
            }

        assertEquals(StreamTransportCandidateRejection.INELIGIBLE, rejection.reason)
        assertFalse(factoryCalled.get())
    }

    @Test
    fun closesCandidateWhenEligibilityChangesDuringCreation() {
        val owner = StreamTransportOwner<FakeConnection>()
        val eligible = AtomicBoolean(true)
        val connection = FakeConnection()

        val rejection =
            assertThrows(StreamTransportCandidateRejectedException::class.java) {
                owner.createCandidate(3, { eligible.get() }) {
                    eligible.set(false)
                    connection
                }
            }

        assertEquals(StreamTransportCandidateRejection.INELIGIBLE, rejection.reason)
        assertEquals(1, connection.closeCount)
    }

    @Test
    fun rejectsSecondPendingCandidateWithoutReplacingFirst() {
        val owner = StreamTransportOwner<FakeConnection>()
        val first = FakeConnection()
        val secondFactoryCalled = AtomicBoolean()
        val firstCandidate = owner.createCandidate(1, { true }) { first }

        val rejection =
            assertThrows(StreamTransportCandidateRejectedException::class.java) {
                owner.createCandidate(2, { true }) {
                    secondFactoryCalled.set(true)
                    FakeConnection()
                }
            }

        assertEquals(StreamTransportCandidateRejection.PENDING_EXISTS, rejection.reason)
        assertFalse(secondFactoryCalled.get())
        assertEquals(0, first.closeCount)
        assertTrue(owner.promote(firstCandidate) { true }.promoted)
        assertSame(first, owner.activeConnection())
    }

    @Test
    fun rejectsAndClosesCandidateThatBecomesStaleBeforePromotion() {
        val owner = StreamTransportOwner<FakeConnection>()
        val connection = FakeConnection()
        val candidate = owner.createCandidate(3, { true }) { connection }

        val promotion = owner.promote(candidate) { false }

        assertFalse(promotion.promoted)
        assertEquals(1, connection.closeCount)
        assertEquals(null, owner.activeConnection())
    }

    @Test
    fun promotionAtomicallyReplacesAndClosesActiveConnection() {
        val owner = StreamTransportOwner<FakeConnection>()
        val first = FakeConnection()
        val second = FakeConnection()
        val firstCandidate = owner.createCandidate(1, { true }) { first }
        assertTrue(owner.promote(firstCandidate) { true }.promoted)
        val secondCandidate = owner.createCandidate(2, { true }) { second }

        val promotion = owner.promote(secondCandidate) { true }

        assertTrue(promotion.promoted)
        assertEquals(1, first.closeCount)
        assertEquals(0, second.closeCount)
        assertSame(second, owner.activeConnection())
    }

    @Test
    fun closeAllWaitsForRegistrationAndCannotMissCreatedConnection() {
        val owner = StreamTransportOwner<FakeConnection>()
        val connection = FakeConnection()
        val factoryEntered = CountDownLatch(1)
        val allowFactoryReturn = CountDownLatch(1)
        val registrationFinished = CountDownLatch(1)
        val closeFinished = CountDownLatch(1)
        val registrationFailure = AtomicReference<Throwable?>()

        val registrationThread =
            thread(start = true) {
                runCatching {
                    owner.createCandidate(1, { true }) {
                        factoryEntered.countDown()
                        assertTrue(allowFactoryReturn.await(1, TimeUnit.SECONDS))
                        connection
                    }
                }.exceptionOrNull()?.let(registrationFailure::set)
                registrationFinished.countDown()
            }
        assertTrue(factoryEntered.await(1, TimeUnit.SECONDS))
        val closeThread =
            thread(start = true) {
                owner.closeAll()
                closeFinished.countDown()
            }
        assertFalse(closeFinished.await(50, TimeUnit.MILLISECONDS))

        allowFactoryReturn.countDown()
        assertTrue(registrationFinished.await(1, TimeUnit.SECONDS))
        assertTrue(closeFinished.await(1, TimeUnit.SECONDS))
        registrationThread.join()
        closeThread.join()

        assertEquals(null, registrationFailure.get())
        assertEquals(1, connection.closeCount)
    }

    @Test
    fun closeAllAttemptsEveryConnectionAndReportsFailures() {
        val owner = StreamTransportOwner<FakeConnection>()
        val active = FakeConnection(closeFailure = IllegalStateException("active close"))
        val pending = FakeConnection()
        val activeCandidate = owner.createCandidate(1, { true }) { active }
        assertTrue(owner.promote(activeCandidate) { true }.promoted)
        owner.createCandidate(2, { true }) { pending }

        val failures = owner.closeAll()

        assertEquals(listOf("active close"), failures.map(Exception::getMessage))
        assertEquals(1, active.closeCount)
        assertEquals(1, pending.closeCount)
        assertEquals(null, owner.activeConnection())
    }

    @Test
    fun closeAndShutdownAreAttemptedExactlyOnce() {
        val owner = StreamTransportOwner<FakeConnection>()
        val connection = FakeConnection()
        val candidate = owner.createCandidate(1, { true }) { connection }
        assertTrue(owner.promote(candidate) { true }.promoted)

        owner.shutdownActiveOutput()
        owner.shutdownActiveOutput()
        owner.closeAll()
        owner.closeAll()
        owner.release(candidate)

        assertEquals(1, connection.shutdownCount)
        assertEquals(1, connection.closeCount)
    }

    private class FakeConnection(
        private val closeFailure: Exception? = null,
    ) : StreamTransportConnection {
        override val input = DataInputStream(ByteArrayInputStream(ByteArray(0)))
        override val output = DataOutputStream(ByteArrayOutputStream())
        override var readTimeoutMillis = 0
        var shutdownCount = 0
            private set
        var closeCount = 0
            private set
        private val shutdown = AtomicBoolean()
        private val closed = AtomicBoolean()

        override fun shutdownOutput(): Exception? {
            if (shutdown.compareAndSet(false, true)) shutdownCount += 1
            return null
        }

        override fun closeOnce(): List<Exception> {
            if (!closed.compareAndSet(false, true)) return emptyList()
            closeCount += 1
            return listOfNotNull(closeFailure)
        }
    }
}
