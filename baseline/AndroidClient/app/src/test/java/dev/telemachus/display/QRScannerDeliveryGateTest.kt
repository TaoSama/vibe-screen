package dev.telemachus.display

import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class QRScannerDeliveryGateTest {
    @Test
    fun duplicateInvalidFramesAreBlockedUntilUiHandlingReleasesGate() {
        val gate = QRScannerDeliveryGate()

        assertTrue(gate.tryClaimInvalid())
        assertFalse(gate.tryClaimInvalid())

        gate.releaseForRetry()

        assertTrue(gate.tryClaimInvalid())
    }

    @Test
    fun validResultKeepsGateClaimedForOneShotDelivery() {
        val gate = QRScannerDeliveryGate()

        assertTrue(gate.tryClaimAccepted(VALID_PAIRING_QR))

        assertTrue(gate.isClaimed())
        assertEquals(VALID_PAIRING_QR, gate.pendingResultRaw())
        assertFalse(gate.tryClaimInvalid())
        assertFalse(gate.tryClaimAccepted("vibescreen://pair?v=1&o=second"))
    }

    @Test
    fun restoredPendingResultStartsClaimed() {
        val gate = QRScannerDeliveryGate()

        gate.restorePending(VALID_PAIRING_QR)

        assertTrue(gate.isClaimed())
        assertEquals(VALID_PAIRING_QR, gate.pendingResultRaw())
        assertFalse(gate.tryClaimInvalid())
    }

    @Test
    fun acceptedClaimAndSavedPayloadAreOneSynchronizedSnapshot() {
        val gate = QRScannerDeliveryGate()

        assertTrue(gate.tryClaimAccepted(VALID_PAIRING_QR))

        val snapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.CLAIMED_ACCEPTED, snapshot.claimState)
        assertEquals(VALID_PAIRING_QR, snapshot.pendingRaw)
    }

    @Test
    fun saveDuringInvalidInFlightDoesNotPersistEmptyClaim() {
        val gate = QRScannerDeliveryGate()

        assertTrue(gate.tryClaimInvalid())
        assertTrue(gate.isClaimed())
        val invalidSnapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.CLAIMED_INVALID, invalidSnapshot.claimState)
        assertNull(invalidSnapshot.pendingRaw)

        gate.releaseForRetry()
        val releasedSnapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.UNCLAIMED, releasedSnapshot.claimState)
        assertNull(releasedSnapshot.pendingRaw)

        assertTrue(gate.tryClaimAccepted(VALID_PAIRING_QR))
        val acceptedSnapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.CLAIMED_ACCEPTED, acceptedSnapshot.claimState)
        assertEquals(VALID_PAIRING_QR, acceptedSnapshot.pendingRaw)
    }

    @Test
    fun invalidInFlightBlocksAcceptedClaimUntilRetryRelease() {
        val gate = QRScannerDeliveryGate()

        assertTrue(gate.tryClaimInvalid())
        assertFalse(gate.tryClaimAccepted(VALID_PAIRING_QR))

        val invalidSnapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.CLAIMED_INVALID, invalidSnapshot.claimState)
        assertNull(invalidSnapshot.pendingRaw)

        gate.releaseForRetry()

        assertTrue(gate.tryClaimAccepted(VALID_PAIRING_QR))
        val acceptedSnapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.CLAIMED_ACCEPTED, acceptedSnapshot.claimState)
        assertEquals(VALID_PAIRING_QR, acceptedSnapshot.pendingRaw)
    }

    @Test
    fun concurrentSaveAroundAcceptedClaimOnlySeesNoPayloadOrFullPayload() {
        val gate = QRScannerDeliveryGate()
        val ready = CountDownLatch(2)
        val start = CountDownLatch(1)
        val savedSnapshot = AtomicReference<QRScannerDeliverySnapshot>()

        val writer = Thread({
            ready.countDown()
            start.await()
            gate.tryClaimAccepted(VALID_PAIRING_QR)
        }, "qr-accepted-writer")
        val saver = Thread({
            ready.countDown()
            start.await()
            savedSnapshot.set(gate.snapshotForSave())
        }, "qr-state-saver")

        writer.start()
        saver.start()
        assertTrue(ready.await(5, TimeUnit.SECONDS))
        start.countDown()
        writer.join()
        saver.join()

        val saved = savedSnapshot.get()
        assertTrue(
            "A concurrent save may run before the accepted claim or after the raw is bound, but never sees a partial accepted state",
            (saved.claimState == QRScannerDeliveryClaimState.UNCLAIMED && saved.pendingRaw == null) ||
                (saved.claimState == QRScannerDeliveryClaimState.CLAIMED_ACCEPTED && saved.pendingRaw == VALID_PAIRING_QR),
        )
        val finalSnapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.CLAIMED_ACCEPTED, finalSnapshot.claimState)
        assertEquals(VALID_PAIRING_QR, finalSnapshot.pendingRaw)
    }

    @Test
    fun concurrentAcceptedClaimsAllowExactlyOneWinner() {
        val gate = QRScannerDeliveryGate()
        val workerCount = 8
        val ready = CountDownLatch(workerCount)
        val start = CountDownLatch(1)
        val winners = Collections.synchronizedList(mutableListOf<String>())

        val workers =
            (0 until workerCount).map { index ->
                val raw = "vibescreen://pair?v=1&o=winner-$index"
                Thread({
                    ready.countDown()
                    start.await()
                    if (gate.tryClaimAccepted(raw)) {
                        winners.add(raw)
                    }
                }, "qr-accepted-writer-$index")
            }

        workers.forEach(Thread::start)
        assertTrue(ready.await(5, TimeUnit.SECONDS))
        start.countDown()
        workers.forEach(Thread::join)

        assertEquals(1, winners.size)
        val snapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.CLAIMED_ACCEPTED, snapshot.claimState)
        assertEquals(winners.single(), snapshot.pendingRaw)
    }

    @Test
    fun invalidReleaseDoesNotClearAcceptedResult() {
        val gate = QRScannerDeliveryGate()

        assertTrue(gate.tryClaimAccepted(VALID_PAIRING_QR))
        gate.releaseForRetry()

        assertTrue(gate.isClaimed())
        assertEquals(VALID_PAIRING_QR, gate.pendingResultRaw())
        assertFalse(gate.tryClaimInvalid())
    }

    @Test
    fun restoreWithoutPendingResultStartsUnclaimed() {
        val gate = QRScannerDeliveryGate()

        assertTrue(gate.tryClaimAccepted(VALID_PAIRING_QR))
        gate.restorePending(null)

        assertFalse(gate.isClaimed())
        val snapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.UNCLAIMED, snapshot.claimState)
        assertNull(snapshot.pendingRaw)
        assertTrue(gate.tryClaimInvalid())
    }

    @Test
    fun releaseForRetryOnIdleKeepsGateUnclaimed() {
        val gate = QRScannerDeliveryGate()

        gate.releaseForRetry()

        val snapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.UNCLAIMED, snapshot.claimState)
        assertNull(snapshot.pendingRaw)
        assertTrue(gate.tryClaimAccepted(VALID_PAIRING_QR))
    }

    private companion object {
        private const val VALID_PAIRING_QR = "vibescreen://pair?v=1&o=test"
    }
}
