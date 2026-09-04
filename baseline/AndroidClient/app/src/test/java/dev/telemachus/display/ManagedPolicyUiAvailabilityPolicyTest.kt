package dev.telemachus.display

import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ManagedPolicyUiAvailabilityPolicyTest {
    @Test
    fun `unmanaged remote status preserves local UI policy snapshot`() {
        val availability =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = false,
                localHostActionsAllowed = false,
                localClipboardAllowed = false,
                localFileTransferAllowed = false,
                remoteStatus = ManagedPolicyStatus.getDefaultInstance(),
            )

        assertFalse(availability.customGesturesAllowed)
        assertFalse(availability.hostActionsAllowed)
        assertFalse(availability.clipboardAllowed)
        assertFalse(availability.fileTransferAllowed)
    }

    @Test
    fun `unmanaged remote status preserves local allowed snapshot`() {
        val availability =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                localClipboardAllowed = true,
                localFileTransferAllowed = true,
                remoteStatus = ManagedPolicyStatus.getDefaultInstance(),
            )

        assertTrue(availability.customGesturesAllowed)
        assertTrue(availability.hostActionsAllowed)
        assertTrue(availability.clipboardAllowed)
        assertTrue(availability.fileTransferAllowed)
    }

    @Test
    fun `local deny wins over remote allow`() {
        val availability =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = false,
                localHostActionsAllowed = false,
                localClipboardAllowed = false,
                localFileTransferAllowed = false,
                remoteStatus = managedStatus(customGesturesAllowed = true, hostActionsAllowed = true),
            )

        assertFalse(availability.customGesturesAllowed)
        assertFalse(availability.hostActionsAllowed)
        assertFalse(availability.clipboardAllowed)
        assertFalse(availability.fileTransferAllowed)
    }

    @Test
    fun `remote deny wins over local allow`() {
        val availability =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                localClipboardAllowed = true,
                localFileTransferAllowed = true,
                remoteStatus = managedStatus(
                    customGesturesAllowed = false,
                    hostActionsAllowed = false,
                    clipboardAllowed = false,
                    fileTransferAllowed = false,
                    maximumFileBytes = ProtocolV1Session.ManagedPolicy.DEFAULT_MAXIMUM_FILE_BYTES,
                ),
            )

        assertFalse(availability.customGesturesAllowed)
        assertFalse(availability.hostActionsAllowed)
        assertFalse(availability.clipboardAllowed)
        assertFalse(availability.fileTransferAllowed)
    }

    @Test
    fun `local and remote allow keeps UI controls available`() {
        val availability =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                localClipboardAllowed = true,
                localFileTransferAllowed = true,
                remoteStatus = managedStatus(customGesturesAllowed = true, hostActionsAllowed = true),
            )

        assertTrue(availability.customGesturesAllowed)
        assertTrue(availability.hostActionsAllowed)
        assertTrue(availability.clipboardAllowed)
        assertTrue(availability.fileTransferAllowed)
    }

    @Test
    fun `zero file byte policy disables file transfer availability`() {
        val availability =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                localClipboardAllowed = true,
                localFileTransferAllowed = true,
                remoteStatus = managedStatus(
                    customGesturesAllowed = true,
                    hostActionsAllowed = true,
                    clipboardAllowed = true,
                    fileTransferAllowed = true,
                    maximumFileBytes = 0L,
                ),
            )

        assertTrue(availability.clipboardAllowed)
        assertFalse(availability.fileTransferAllowed)
    }

    private fun managedStatus(
        customGesturesAllowed: Boolean,
        hostActionsAllowed: Boolean,
        clipboardAllowed: Boolean = true,
        fileTransferAllowed: Boolean = true,
        maximumFileBytes: Long = ProtocolV1Session.ManagedPolicy.DEFAULT_MAXIMUM_FILE_BYTES,
    ): ManagedPolicyStatus =
        ManagedPolicyStatus.newBuilder()
            .setManaged(true)
            .setClipboardAllowed(clipboardAllowed)
            .setFileTransferAllowed(fileTransferAllowed)
            .setCustomGesturesAllowed(customGesturesAllowed)
            .setHostActionsAllowed(hostActionsAllowed)
            .setMaximumFileBytes(maximumFileBytes)
            .build()
}
