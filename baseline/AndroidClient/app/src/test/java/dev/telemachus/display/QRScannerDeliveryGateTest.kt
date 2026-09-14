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

        val snapshot = gate.markStateSavedAndSnapshot()
        assertEquals(QRScannerDeliveryClaimState.CLAIMED_ACCEPTED, snapshot.claimState)
        assertEquals(VALID_PAIRING_QR, snapshot.pendingRaw)
        assertFalse(gate.tryClaimAccepted("vibescreen://pair?v=1&o=second"))
    }

    @Test
    fun stateSavedSnapshotRejectsLaterClaimsFromOldInstance() {
        val gate = QRScannerDeliveryGate()

        val snapshot = gate.markStateSavedAndSnapshot()

        assertEquals(QRScannerDeliveryClaimState.UNCLAIMED, snapshot.claimState)
        assertNull(snapshot.pendingRaw)
        assertFalse(gate.tryClaimAccepted(VALID_PAIRING_QR))
        assertFalse(gate.tryClaimInvalid())
        val finalSnapshot = gate.snapshotForSave()
        assertEquals(QRScannerDeliveryClaimState.UNCLAIMED, finalSnapshot.claimState)
        assertNull(finalSnapshot.pendingRaw)
    }

    @Test
    fun reopenAfterStateSaveAllowsSameInstanceToScanAgain() {
        val gate = QRScannerDeliveryGate()

        gate.markStateSavedAndSnapshot()
        assertFalse(gate.tryClaimAccepted(VALID_PAIRING_QR))

        gate.reopenAfterStateSave()

        assertTrue(gate.tryClaimAccepted(VALID_PAIRING_QR))
        assertEquals(VALID_PAIRING_QR, gate.pendingResultRaw())
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
    fun concurrentStateSaveAndAcceptedClaimCannotLoseAcceptedPayload() {
        val gate = QRScannerDeliveryGate()
        val ready = CountDownLatch(2)
        val start = CountDownLatch(1)
        val savedSnapshot = AtomicReference<QRScannerDeliverySnapshot>()
        val claimResult = AtomicReference<Boolean>()

        val writer = Thread({
            ready.countDown()
            start.await()
            claimResult.set(gate.tryClaimAccepted(VALID_PAIRING_QR))
        }, "qr-accepted-writer")
        val saver = Thread({
            ready.countDown()
            start.await()
            savedSnapshot.set(gate.markStateSavedAndSnapshot())
        }, "qr-state-saver")

        writer.start()
        saver.start()
        assertTrue(ready.await(5, TimeUnit.SECONDS))
        start.countDown()
        writer.join()
        saver.join()

        val saved = savedSnapshot.get()
        val finalSnapshot = gate.snapshotForSave()
        when (saved.claimState) {
            QRScannerDeliveryClaimState.UNCLAIMED -> {
                assertNull(saved.pendingRaw)
                assertEquals(false, claimResult.get())
                assertEquals(QRScannerDeliveryClaimState.UNCLAIMED, finalSnapshot.claimState)
                assertNull(finalSnapshot.pendingRaw)
            }
            QRScannerDeliveryClaimState.CLAIMED_ACCEPTED -> {
                assertEquals(VALID_PAIRING_QR, saved.pendingRaw)
                assertEquals(true, claimResult.get())
                assertEquals(QRScannerDeliveryClaimState.CLAIMED_ACCEPTED, finalSnapshot.claimState)
                assertEquals(VALID_PAIRING_QR, finalSnapshot.pendingRaw)
            }
            QRScannerDeliveryClaimState.CLAIMED_INVALID -> error("unexpected invalid state")
        }
    }

    @Test
    fun stateSaveDuringInvalidInFlightDoesNotReopenAfterRetryRelease() {
        val gate = QRScannerDeliveryGate()

        assertTrue(gate.tryClaimInvalid())
        val snapshot = gate.markStateSavedAndSnapshot()
        assertEquals(QRScannerDeliveryClaimState.CLAIMED_INVALID, snapshot.claimState)
        assertNull(snapshot.pendingRaw)

        gate.releaseForRetry()

        assertFalse(gate.tryClaimAccepted(VALID_PAIRING_QR))
        gate.reopenAfterStateSave()
        assertTrue(gate.tryClaimAccepted(VALID_PAIRING_QR))
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
