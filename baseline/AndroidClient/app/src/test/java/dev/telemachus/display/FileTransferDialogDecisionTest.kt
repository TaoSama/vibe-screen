package dev.telemachus.display

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FileTransferDialogDecisionTest {
    @Test
    fun onlyFirstAdmittedDecisionFinishes() {
        val decision = FileTransferDialogDecision()

        assertTrue(decision.isPending)
        assertTrue(decision.tryFinish())
        assertFalse(decision.isPending)
        assertFalse(decision.tryFinish())
    }

    @Test
    fun rejectedAdmissionLeavesDecisionPending() {
        val decision = FileTransferDialogDecision()

        assertFalse(decision.tryFinish { false })
        assertTrue(decision.isPending)
        assertTrue(decision.tryFinish { true })
        assertFalse(decision.isPending)
    }
}
