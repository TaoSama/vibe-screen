package dev.telemachus.display.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class UpgradeFallbackDecisionTest {
    @Test
    fun acknowledgedV1ContinuesOnlyOnProbedConnection() {
        assertEquals(
            UpgradeFallbackDecision.UseCurrentV1Connection,
            UpgradeFallbackDecision.fromProbeOutcome(UpgradeProbeOutcome.V1Acknowledged),
        )
    }

    @Test
    fun timeoutRequiresFreshLegacyConnection() {
        assertEquals(
            UpgradeFallbackDecision.OpenFreshLegacyConnection,
            UpgradeFallbackDecision.fromProbeOutcome(UpgradeProbeOutcome.TimedOut),
        )
    }

    @Test
    fun immediateLegacyByteCanStayOnCurrentConnection() {
        assertEquals(
            UpgradeFallbackDecision.UseCurrentLegacyConnection(7),
            UpgradeFallbackDecision.fromProbeOutcome(UpgradeProbeOutcome.LegacyByte(7)),
        )
    }

    @Test
    fun legacyByteMustFitUnsignedWireByte() {
        assertThrows(IllegalArgumentException::class.java) {
            UpgradeProbeOutcome.LegacyByte(256)
        }
    }
}
