package dev.telemachus.display

import dev.telemachus.display.protocol.ProtocolV1Session
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ManagedConfigurationProviderTest {
    @Test
    fun emptyRestrictionsAreUnmanaged() {
        assertEquals(ProtocolV1Session.ManagedPolicy.UNMANAGED, ManagedConfigurationProvider { null }.loadPolicy())
        assertEquals(ProtocolV1Session.ManagedPolicy.UNMANAGED, ManagedConfigurationProvider { emptyMap() }.loadPolicy())
    }

    @Test
    fun fullMapParsesPolicyAndNormalizesHosts() {
        val policy = ManagedConfigurationProvider {
            mapOf(
                ManagedConfigurationKeys.CLIPBOARD_ALLOWED to true,
                ManagedConfigurationKeys.FILE_TRANSFER_ALLOWED to true,
                ManagedConfigurationKeys.AUDIO_ALLOWED to true,
                ManagedConfigurationKeys.WAKE_ALLOWED to true,
                ManagedConfigurationKeys.CUSTOM_GESTURES_ALLOWED to true,
                ManagedConfigurationKeys.HOST_ACTIONS_ALLOWED to true,
                ManagedConfigurationKeys.MAXIMUM_FILE_BYTES to 4096,
                ManagedConfigurationKeys.ALLOWED_HOSTS to arrayOf(" Mac-A ", "mac-b", ""),
                ManagedConfigurationKeys.DENIED_HOSTS to "MAC-B\n mac-c ",
            )
        }.loadPolicy()

        assertTrue(policy.isManaged)
        assertTrue(policy.clipboardAllowed)
        assertTrue(policy.fileTransferAllowed)
        assertTrue(policy.audioAllowed)
        assertTrue(policy.wakeAllowed)
        assertTrue(policy.customGesturesAllowed)
        assertTrue(policy.hostActionsAllowed)
        assertEquals(4096L, policy.maximumFileBytes)
        assertEquals(setOf("mac-a", "mac-b"), policy.allowedHosts)
        assertEquals(setOf("mac-b", "mac-c"), policy.deniedHosts)
        assertTrue(policy.allowsHost("mac-a"))
        assertFalse(policy.allowsHost("mac-b"))
        assertTrue(ProtocolV1Session.ManagedPolicy.hasCompleteRestrictionResults(policy.toStatus()))
    }

    @Test
    fun missingFieldsDefaultClosedForManagedConfiguration() {
        val policy = ManagedConfigurationProvider {
            mapOf(ManagedConfigurationKeys.ALLOWED_HOSTS to listOf("mac-a"))
        }.loadPolicy()

        assertTrue(policy.isManaged)
        assertFalse(policy.clipboardAllowed)
        assertFalse(policy.fileTransferAllowed)
        assertFalse(policy.audioAllowed)
        assertFalse(policy.wakeAllowed)
        assertFalse(policy.customGesturesAllowed)
        assertFalse(policy.hostActionsAllowed)
        assertEquals(0L, policy.maximumFileBytes)
        assertEquals(setOf("mac-a"), policy.allowedHosts)
        assertTrue(ProtocolV1Session.ManagedPolicy.hasCompleteRestrictionResults(policy.toStatus()))
    }

    @Test
    fun malformedValuesFailClosed() {
        listOf(
            mapOf(ManagedConfigurationKeys.CLIPBOARD_ALLOWED to "true"),
            mapOf(ManagedConfigurationKeys.ALLOWED_HOSTS to listOf("mac-a", 42)),
            mapOf(ManagedConfigurationKeys.MAXIMUM_FILE_BYTES to -1),
        ).forEach { values ->
            val policy = ManagedConfigurationProvider { values }.loadPolicy()

            assertTrue(policy.isManaged)
            assertFalse(policy.clipboardAllowed)
            assertFalse(policy.fileTransferAllowed)
            assertFalse(policy.audioAllowed)
            assertFalse(policy.wakeAllowed)
            assertFalse(policy.customGesturesAllowed)
            assertFalse(policy.hostActionsAllowed)
            assertEquals(0L, policy.maximumFileBytes)
            assertTrue(policy.allowedHostsRestricted)
            assertTrue(policy.allowedHosts.isEmpty())
            assertTrue(policy.restrictionResults.all { it.source == "local_parse_error" })
            assertTrue(ProtocolV1Session.ManagedPolicy.hasCompleteRestrictionResults(policy.toStatus()))
        }
    }
}
