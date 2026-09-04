package dev.telemachus.display

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
                remoteStatus = ManagedPolicyStatus.getDefaultInstance(),
            )

        assertFalse(availability.customGesturesAllowed)
        assertFalse(availability.hostActionsAllowed)
    }

    @Test
    fun `local deny wins over remote allow`() {
        val availability =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = false,
                localHostActionsAllowed = false,
                remoteStatus = managedStatus(customGesturesAllowed = true, hostActionsAllowed = true),
            )

        assertFalse(availability.customGesturesAllowed)
        assertFalse(availability.hostActionsAllowed)
    }

    @Test
    fun `remote deny wins over local allow`() {
        val availability =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                remoteStatus = managedStatus(customGesturesAllowed = false, hostActionsAllowed = false),
            )

        assertFalse(availability.customGesturesAllowed)
        assertFalse(availability.hostActionsAllowed)
    }

    @Test
    fun `local and remote allow keeps UI controls available`() {
        val availability =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                remoteStatus = managedStatus(customGesturesAllowed = true, hostActionsAllowed = true),
            )

        assertTrue(availability.customGesturesAllowed)
        assertTrue(availability.hostActionsAllowed)
    }

    private fun managedStatus(
        customGesturesAllowed: Boolean,
        hostActionsAllowed: Boolean,
    ): ManagedPolicyStatus =
        ManagedPolicyStatus.newBuilder()
            .setManaged(true)
            .setCustomGesturesAllowed(customGesturesAllowed)
            .setHostActionsAllowed(hostActionsAllowed)
            .build()
}
