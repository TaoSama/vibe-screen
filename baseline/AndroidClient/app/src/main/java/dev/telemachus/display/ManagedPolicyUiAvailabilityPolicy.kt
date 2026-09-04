package dev.telemachus.display

import dev.vibescreen.protocol.v1.ManagedPolicyStatus

internal data class ManagedPolicyUiAvailability(
    val customGesturesAllowed: Boolean,
    val hostActionsAllowed: Boolean,
)

internal object ManagedPolicyUiAvailabilityPolicy {
    fun combine(
        localCustomGesturesAllowed: Boolean,
        localHostActionsAllowed: Boolean,
        remoteStatus: ManagedPolicyStatus,
    ): ManagedPolicyUiAvailability =
        ManagedPolicyUiAvailability(
            customGesturesAllowed =
                localCustomGesturesAllowed && (!remoteStatus.managed || remoteStatus.customGesturesAllowed),
            hostActionsAllowed =
                localHostActionsAllowed && (!remoteStatus.managed || remoteStatus.hostActionsAllowed),
        )
}
