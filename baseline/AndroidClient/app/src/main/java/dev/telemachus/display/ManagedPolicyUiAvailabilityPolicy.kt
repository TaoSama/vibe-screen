package dev.telemachus.display

import dev.vibescreen.protocol.v1.ManagedPolicyStatus

internal data class ManagedPolicyUiAvailability(
    val customGesturesAllowed: Boolean,
    val hostActionsAllowed: Boolean,
    val clipboardAllowed: Boolean,
    val fileTransferAllowed: Boolean,
)

internal object ManagedPolicyUiAvailabilityPolicy {
    fun combine(
        localCustomGesturesAllowed: Boolean,
        localHostActionsAllowed: Boolean,
        localClipboardAllowed: Boolean,
        localFileTransferAllowed: Boolean,
        remoteStatus: ManagedPolicyStatus,
    ): ManagedPolicyUiAvailability =
        ManagedPolicyUiAvailability(
            customGesturesAllowed =
                localCustomGesturesAllowed && (!remoteStatus.managed || remoteStatus.customGesturesAllowed),
            hostActionsAllowed =
                localHostActionsAllowed && (!remoteStatus.managed || remoteStatus.hostActionsAllowed),
            clipboardAllowed =
                localClipboardAllowed && (!remoteStatus.managed || remoteStatus.clipboardAllowed),
            fileTransferAllowed =
                localFileTransferAllowed && (!remoteStatus.managed || remoteStatus.fileTransferAllowed && remoteStatus.maximumFileBytes > 0L),
        )
}
