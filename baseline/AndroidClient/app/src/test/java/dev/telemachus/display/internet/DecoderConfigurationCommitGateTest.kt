package dev.telemachus.display.internet

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DecoderConfigurationCommitGateTest {
    @Test
    fun `timeout before runnable prevents installation ownership`() {
        val gate = DecoderConfigurationCommitGate()
        assertTrue(gate.cancelPending())
        assertFalse(gate.startInstallation())
        assertFalse(gate.markDone())
    }

    @Test
    fun `installation ownership is not successful completion`() {
        val gate = DecoderConfigurationCommitGate()
        assertTrue(gate.startInstallation())
        assertTrue(gate.installationOwned)
        assertFalse(gate.done)
        assertFalse(gate.cancelPending())
    }

    @Test
    fun `done is visible only after full installation succeeds`() {
        val gate = DecoderConfigurationCommitGate()
        assertTrue(gate.startInstallation())
        assertTrue(gate.markDone())
        assertTrue(gate.done)
        assertFalse(gate.cancelPending())
    }
}
