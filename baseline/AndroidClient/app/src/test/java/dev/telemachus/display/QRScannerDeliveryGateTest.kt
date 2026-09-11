package dev.telemachus.display

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QRScannerDeliveryGateTest {
    @Test
    fun duplicateInvalidFramesAreBlockedUntilUiHandlingReleasesGate() {
        val gate = QRScannerDeliveryGate()

        assertTrue(gate.tryClaim())
        assertFalse(gate.tryClaim())

        gate.releaseForRetry()

        assertTrue(gate.tryClaim())
    }

    @Test
    fun validResultKeepsGateClaimedForOneShotDelivery() {
        val gate = QRScannerDeliveryGate()

        assertTrue(gate.tryClaim())

        assertTrue(gate.isClaimed())
        assertFalse(gate.tryClaim())
    }

    @Test
    fun restoredPendingResultStartsClaimed() {
        val gate = QRScannerDeliveryGate()

        gate.setClaimed(true)

        assertTrue(gate.isClaimed())
        assertFalse(gate.tryClaim())
    }
}
