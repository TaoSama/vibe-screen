package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class InternetCameraPermissionRecoveryPolicyTest {
    @Test
    fun `scan request launches only when camera is already granted`() {
        assertEquals(
            InternetCameraScanAction.LAUNCH_SCANNER,
            InternetCameraPermissionRecoveryPolicy.scanRequested(
                granted = true,
                permanentlyDenied = false,
            ),
        )
    }

    @Test
    fun `first scan denial requests camera permission instead of showing settings`() {
        assertEquals(
            InternetCameraScanAction.REQUEST_PERMISSION,
            InternetCameraPermissionRecoveryPolicy.scanRequested(
                granted = false,
                permanentlyDenied = false,
            ),
        )
    }

    @Test
    fun `permanent scan denial shows settings panel without opening settings`() {
        assertEquals(
            InternetCameraScanAction.SHOW_SETTINGS_PANEL,
            InternetCameraPermissionRecoveryPolicy.scanRequested(
                granted = false,
                permanentlyDenied = true,
            ),
        )
    }

    @Test
    fun `permission result keeps first denial inline and permanent denial explicit`() {
        assertEquals(
            InternetCameraPermissionResultAction.SHOW_FIRST_DENIED_PANEL,
            InternetCameraPermissionRecoveryPolicy.permissionResult(
                granted = false,
                permanentlyDenied = false,
            ),
        )
        assertEquals(
            InternetCameraPermissionResultAction.SHOW_SETTINGS_PANEL,
            InternetCameraPermissionRecoveryPolicy.permissionResult(
                granted = false,
                permanentlyDenied = true,
            ),
        )
    }

    @Test
    fun `foreground return launches scanner when visible permission panel becomes granted`() {
        listOf(
            InternetCameraPermissionPanelState.FIRST_DENIED,
            InternetCameraPermissionPanelState.SETTINGS_REQUIRED,
        ).forEach { panelState ->
            assertEquals(
                InternetCameraSettingsReturnAction.LAUNCH_SCANNER_ONCE,
                InternetCameraPermissionRecoveryPolicy.foregroundReturn(
                    panelState = panelState,
                    settingsPending = false,
                    granted = true,
                    permanentlyDenied = false,
                ),
            )
        }
    }

    @Test
    fun `foreground return preserves explicit settings return grant`() {
        assertEquals(
            InternetCameraSettingsReturnAction.LAUNCH_SCANNER_ONCE,
            InternetCameraPermissionRecoveryPolicy.foregroundReturn(
                panelState = InternetCameraPermissionPanelState.HIDDEN,
                settingsPending = true,
                granted = true,
                permanentlyDenied = false,
            ),
        )
    }

    @Test
    fun `foreground return keeps visible permission panel actionable when still denied`() {
        assertEquals(
            InternetCameraSettingsReturnAction.SHOW_SETTINGS_PANEL,
            InternetCameraPermissionRecoveryPolicy.foregroundReturn(
                panelState = InternetCameraPermissionPanelState.SETTINGS_REQUIRED,
                settingsPending = false,
                granted = false,
                permanentlyDenied = true,
            ),
        )
        assertEquals(
            InternetCameraSettingsReturnAction.SHOW_FIRST_DENIED_PANEL,
            InternetCameraPermissionRecoveryPolicy.foregroundReturn(
                panelState = InternetCameraPermissionPanelState.FIRST_DENIED,
                settingsPending = false,
                granted = false,
                permanentlyDenied = false,
            ),
        )
    }

    @Test
    fun `foreground return ignores hidden panel without settings return`() {
        assertEquals(
            InternetCameraSettingsReturnAction.NOOP,
            InternetCameraPermissionRecoveryPolicy.foregroundReturn(
                panelState = InternetCameraPermissionPanelState.HIDDEN,
                settingsPending = false,
                granted = true,
                permanentlyDenied = false,
            ),
        )
    }

    @Test
    fun `restored unknown panel state fails closed to hidden`() {
        assertEquals(
            InternetCameraPermissionPanelState.HIDDEN,
            InternetCameraPermissionRecoveryPolicy.restoredPanelState("unexpected"),
        )
        assertEquals(
            InternetCameraPermissionPanelState.SETTINGS_REQUIRED,
            InternetCameraPermissionRecoveryPolicy.restoredPanelState("SETTINGS_REQUIRED"),
        )
    }
}
