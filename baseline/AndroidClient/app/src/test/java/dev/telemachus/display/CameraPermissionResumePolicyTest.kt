package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class CameraPermissionResumePolicyTest {
    @Test
    fun `settings grant recovers denied state and launches scanner once`() {
        assertEquals(
            CameraPermissionResumeAction.SHOW_SCAN_ENTRY_AND_LAUNCH,
            CameraPermissionResumePolicy.evaluate(
                WirelessTabController.State.PERM_DENIED,
                granted = true,
                permanentlyDenied = false,
            ),
        )
    }

    @Test
    fun `permanent denial remains actionable`() {
        assertEquals(
            CameraPermissionResumeAction.KEEP_DENIED,
            CameraPermissionResumePolicy.evaluate(
                WirelessTabController.State.PERM_DENIED,
                granted = false,
                permanentlyDenied = true,
            ),
        )
    }

    @Test
    fun `re-enabled prompt returns to scan entry without auto launch`() {
        assertEquals(
            CameraPermissionResumeAction.SHOW_SCAN_ENTRY,
            CameraPermissionResumePolicy.evaluate(
                WirelessTabController.State.PERM_DENIED,
                granted = false,
                permanentlyDenied = false,
            ),
        )
    }

    @Test
    fun `scanner return does not relaunch outside denied state`() {
        WirelessTabController.State.entries
            .filterNot { it == WirelessTabController.State.PERM_DENIED }
            .forEach { state ->
                assertEquals(
                    CameraPermissionResumeAction.NOOP,
                    CameraPermissionResumePolicy.evaluate(
                        state,
                        granted = true,
                        permanentlyDenied = false,
                    ),
                )
            }
    }
}
