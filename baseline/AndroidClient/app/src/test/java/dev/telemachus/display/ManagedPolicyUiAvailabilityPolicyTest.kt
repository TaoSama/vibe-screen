package dev.telemachus.display

import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import org.junit.Assert.assertEquals
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
        assertEquals(ManagedPolicyUiAvailabilityState.POLICY_DENIED, availability.clipboard)
        assertEquals(ManagedPolicyUiAvailabilityState.POLICY_DENIED, availability.fileTransfer)
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
        assertEquals(ManagedPolicyUiAvailabilityState.POLICY_DENIED, availability.clipboard)
        assertEquals(ManagedPolicyUiAvailabilityState.POLICY_DENIED, availability.fileTransfer)
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
        assertEquals(ManagedPolicyUiAvailabilityState.POLICY_DENIED, availability.fileTransfer)
    }

    @Test
    fun wakeHostDenyIsTrackedAsPolicyDenied() {
        val localDenied =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                localClipboardAllowed = true,
                localFileTransferAllowed = true,
                localWakeHostAllowed = false,
                remoteStatus = managedStatus(customGesturesAllowed = true, hostActionsAllowed = true, wakeAllowed = true),
            )
        val remoteDenied =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                localClipboardAllowed = true,
                localFileTransferAllowed = true,
                localWakeHostAllowed = true,
                remoteStatus = managedStatus(customGesturesAllowed = true, hostActionsAllowed = true, wakeAllowed = false),
            )

        assertEquals(ManagedPolicyUiAvailabilityState.POLICY_DENIED, localDenied.wakeHost)
        assertFalse(localDenied.wakeHostAllowed)
        assertEquals(ManagedPolicyUiAvailabilityState.POLICY_DENIED, remoteDenied.wakeHost)
        assertFalse(remoteDenied.wakeHostAllowed)
    }

    @Test
    fun fixedHostRestrictionsAreTrackedAsPolicyDeniedWhenNoTargetCanBeAllowed() {
        val restrictedWithoutTarget =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                localClipboardAllowed = true,
                localFileTransferAllowed = true,
                remoteStatus = managedStatus(
                    customGesturesAllowed = true,
                    hostActionsAllowed = true,
                    allowedHostsRestricted = true,
                ),
            )
        val allowedTargetAvailable =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                localClipboardAllowed = true,
                localFileTransferAllowed = true,
                remoteStatus = managedStatus(
                    customGesturesAllowed = true,
                    hostActionsAllowed = true,
                    allowedHostsRestricted = true,
                    allowedHosts = setOf("host.local"),
                    deniedHosts = setOf("other.local"),
                ),
            )
        val allowedTargetDenied =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                localClipboardAllowed = true,
                localFileTransferAllowed = true,
                remoteStatus = managedStatus(
                    customGesturesAllowed = true,
                    hostActionsAllowed = true,
                    allowedHostsRestricted = true,
                    allowedHosts = setOf("host.local"),
                    deniedHosts = setOf("host.local"),
                ),
            )
        val localNoHostDenied =
            ManagedPolicyUiAvailabilityPolicy.combine(
                localCustomGesturesAllowed = true,
                localHostActionsAllowed = true,
                localClipboardAllowed = true,
                localFileTransferAllowed = true,
                localFixedHostAllowed = false,
                remoteStatus = managedStatus(customGesturesAllowed = true, hostActionsAllowed = true),
            )

        assertEquals(ManagedPolicyUiAvailabilityState.POLICY_DENIED, restrictedWithoutTarget.fixedHost)
        assertFalse(restrictedWithoutTarget.fixedHostAllowed)
        assertEquals(ManagedPolicyUiAvailabilityState.ALLOWED, allowedTargetAvailable.fixedHost)
        assertTrue(allowedTargetAvailable.fixedHostAllowed)
        assertEquals(ManagedPolicyUiAvailabilityState.POLICY_DENIED, allowedTargetDenied.fixedHost)
        assertFalse(allowedTargetDenied.fixedHostAllowed)
        assertEquals(ManagedPolicyUiAvailabilityState.POLICY_DENIED, localNoHostDenied.fixedHost)
        assertFalse(localNoHostDenied.fixedHostAllowed)
    }

    @Test
    fun fixedHostPolicyAllowsAnyTargetNormalizesHostSets() {
        assertTrue(
            ManagedPolicyUiAvailabilityPolicy.fixedHostPolicyAllowsAnyTarget(
                allowedHostsRestricted = true,
                allowedHosts = listOf(" Host.Local ", ""),
                deniedHosts = listOf("other.local"),
            ),
        )
        assertFalse(
            ManagedPolicyUiAvailabilityPolicy.fixedHostPolicyAllowsAnyTarget(
                allowedHostsRestricted = true,
                allowedHosts = listOf(" Host.Local ", ""),
                deniedHosts = listOf("host.local"),
            ),
        )
    }

    @Test
    fun fixedHostPolicyAllowsNoHostFailsClosedForHostBindingRestrictions() {
        assertTrue(
            ManagedPolicyUiAvailabilityPolicy.fixedHostPolicyAllowsNoHost(
                allowedHostsRestricted = false,
                deniedHosts = emptyList(),
            ),
        )
        assertFalse(
            ManagedPolicyUiAvailabilityPolicy.fixedHostPolicyAllowsNoHost(
                allowedHostsRestricted = true,
                deniedHosts = emptyList(),
            ),
        )
        assertFalse(
            ManagedPolicyUiAvailabilityPolicy.fixedHostPolicyAllowsNoHost(
                allowedHostsRestricted = false,
                deniedHosts = listOf(" Host.Local ", ""),
            ),
        )
    }

    @Test
    fun localPolicyStateDistinguishesNoHostFromExplicitPolicyDenial() {
        assertEquals(
            ManagedPolicyUiAvailabilityState.HOST_UNAVAILABLE,
            ManagedPolicyUiAvailabilityPolicy.localPolicyState(policyAllowed = true),
        )
        assertEquals(
            ManagedPolicyUiAvailabilityState.POLICY_DENIED,
            ManagedPolicyUiAvailabilityPolicy.localPolicyState(policyAllowed = false),
        )
    }

    private fun managedStatus(
        customGesturesAllowed: Boolean,
        hostActionsAllowed: Boolean,
        clipboardAllowed: Boolean = true,
        fileTransferAllowed: Boolean = true,
        wakeAllowed: Boolean = true,
        maximumFileBytes: Long = ProtocolV1Session.ManagedPolicy.DEFAULT_MAXIMUM_FILE_BYTES,
        allowedHostsRestricted: Boolean = false,
        allowedHosts: Set<String> = emptySet(),
        deniedHosts: Set<String> = emptySet(),
    ): ManagedPolicyStatus =
        ManagedPolicyStatus.newBuilder()
            .setManaged(true)
            .setClipboardAllowed(clipboardAllowed)
            .setFileTransferAllowed(fileTransferAllowed)
            .setWakeAllowed(wakeAllowed)
            .setCustomGesturesAllowed(customGesturesAllowed)
            .setHostActionsAllowed(hostActionsAllowed)
            .setMaximumFileBytes(maximumFileBytes)
            .setAllowedHostsRestricted(allowedHostsRestricted)
            .addAllAllowedHosts(allowedHosts)
            .addAllDeniedHosts(deniedHosts)
            .build()
}
