package dev.telemachus.display.protocol

/** The transport action required after probing a connection for Protocol v1. */
internal sealed class UpgradeFallbackDecision {
    data object UseCurrentV1Connection : UpgradeFallbackDecision()

    data object OpenFreshLegacyConnection : UpgradeFallbackDecision()

    data class UseCurrentLegacyConnection(
        val firstByte: Int,
    ) : UpgradeFallbackDecision()

    companion object {
        fun fromProbeOutcome(outcome: UpgradeProbeOutcome): UpgradeFallbackDecision =
            when (outcome) {
                UpgradeProbeOutcome.V1Acknowledged -> UseCurrentV1Connection
                UpgradeProbeOutcome.TimedOut -> OpenFreshLegacyConnection
                is UpgradeProbeOutcome.LegacyByte -> UseCurrentLegacyConnection(outcome.value)
            }
    }
}

internal sealed class UpgradeProbeOutcome {
    data object V1Acknowledged : UpgradeProbeOutcome()

    data object TimedOut : UpgradeProbeOutcome()

    data class LegacyByte(
        val value: Int,
    ) : UpgradeProbeOutcome() {
        init {
            require(value in 0..MAX_BYTE_VALUE) { "legacy byte must be unsigned" }
        }
    }

    companion object {
        private const val MAX_BYTE_VALUE = 0xff
    }
}
