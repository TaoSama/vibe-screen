package dev.telemachus.display

import dev.vibescreen.protocol.v1.ManagedPolicyStatus

internal data class ManagedPolicyUiAvailability(
    val customGestures: ManagedPolicyUiAvailabilityState,
    val hostActions: ManagedPolicyUiAvailabilityState,
    val clipboard: ManagedPolicyUiAvailabilityState,
    val fileTransfer: ManagedPolicyUiAvailabilityState,
    val wakeHost: ManagedPolicyUiAvailabilityState,
    val fixedHost: ManagedPolicyUiAvailabilityState,
) {
    val customGesturesAllowed: Boolean = customGestures.allowed
    val hostActionsAllowed: Boolean = hostActions.allowed
    val clipboardAllowed: Boolean = clipboard.allowed
    val fileTransferAllowed: Boolean = fileTransfer.allowed
    val wakeHostAllowed: Boolean = wakeHost.allowed
    val fixedHostAllowed: Boolean = fixedHost.allowed
}

internal enum class ManagedPolicyUiAvailabilityState {
    ALLOWED,
    POLICY_DENIED,
    HOST_UNAVAILABLE,
    ;

    val allowed: Boolean
        get() = this == ALLOWED
}

internal object ManagedPolicyUiAvailabilityPolicy {
    fun combine(
        localCustomGesturesAllowed: Boolean,
        localHostActionsAllowed: Boolean,
        localClipboardAllowed: Boolean,
        localFileTransferAllowed: Boolean,
        remoteStatus: ManagedPolicyStatus,
        localWakeHostAllowed: Boolean = true,
        localFixedHostAllowed: Boolean = true,
    ): ManagedPolicyUiAvailability =
        ManagedPolicyUiAvailability(
            customGestures =
                restrictionState(
                    localAllowed = localCustomGesturesAllowed,
                    remoteAllowed = !remoteStatus.managed || remoteStatus.customGesturesAllowed,
                ),
            hostActions =
                restrictionState(
                    localAllowed = localHostActionsAllowed,
                    remoteAllowed = !remoteStatus.managed || remoteStatus.hostActionsAllowed,
                ),
            clipboard =
                restrictionState(
                    localAllowed = localClipboardAllowed,
                    remoteAllowed = !remoteStatus.managed || remoteStatus.clipboardAllowed,
                ),
            fileTransfer =
                restrictionState(
                    localAllowed = localFileTransferAllowed,
                    remoteAllowed = !remoteStatus.managed || remoteStatus.fileTransferAllowed && remoteStatus.maximumFileBytes > 0L,
                ),
            wakeHost =
                restrictionState(
                    localAllowed = localWakeHostAllowed,
                    remoteAllowed = !remoteStatus.managed || remoteStatus.wakeAllowed,
                ),
            fixedHost =
                restrictionState(
                    localAllowed = localFixedHostAllowed,
                    remoteAllowed = !remoteStatus.managed || fixedHostPolicyAllowsAnyTarget(remoteStatus),
                ),
        )

    fun localPolicyState(policyAllowed: Boolean): ManagedPolicyUiAvailabilityState =
        if (policyAllowed) ManagedPolicyUiAvailabilityState.HOST_UNAVAILABLE else ManagedPolicyUiAvailabilityState.POLICY_DENIED

    private fun restrictionState(
        localAllowed: Boolean,
        remoteAllowed: Boolean,
    ): ManagedPolicyUiAvailabilityState =
        if (localAllowed && remoteAllowed) {
            ManagedPolicyUiAvailabilityState.ALLOWED
        } else {
            ManagedPolicyUiAvailabilityState.POLICY_DENIED
        }

    fun fixedHostPolicyAllowsAnyTarget(
        allowedHostsRestricted: Boolean,
        allowedHosts: Collection<String>,
        deniedHosts: Collection<String>,
    ): Boolean {
        val allowed = allowedHosts.mapNotNull(::normalizedHost).toSet()
        val denied = deniedHosts.mapNotNull(::normalizedHost).toSet()
        return !allowedHostsRestricted || (allowed - denied).isNotEmpty()
    }

    fun fixedHostPolicyAllowsNoHost(
        allowedHostsRestricted: Boolean,
        deniedHosts: Collection<String>,
    ): Boolean = !allowedHostsRestricted && deniedHosts.mapNotNull(::normalizedHost).isEmpty()

    private fun fixedHostPolicyAllowsAnyTarget(remoteStatus: ManagedPolicyStatus): Boolean =
        fixedHostPolicyAllowsAnyTarget(
            allowedHostsRestricted = remoteStatus.allowedHostsRestricted,
            allowedHosts = remoteStatus.allowedHostsList,
            deniedHosts = remoteStatus.deniedHostsList,
        )

    private fun normalizedHost(host: String): String? = host.trim().ifEmpty { null }?.lowercase()
}
