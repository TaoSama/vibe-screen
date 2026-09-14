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
    fun `settings return launches scanner only for pending grant`() {
        assertEquals(
            InternetCameraSettingsReturnAction.NOOP,
            InternetCameraPermissionRecoveryPolicy.settingsReturn(
                settingsPending = false,
                granted = true,
                permanentlyDenied = false,
            ),
        )
        assertEquals(
            InternetCameraSettingsReturnAction.LAUNCH_SCANNER_ONCE,
            InternetCameraPermissionRecoveryPolicy.settingsReturn(
                settingsPending = true,
                granted = true,
                permanentlyDenied = false,
            ),
        )
        assertEquals(
            InternetCameraSettingsReturnAction.SHOW_SETTINGS_PANEL,
            InternetCameraPermissionRecoveryPolicy.settingsReturn(
                settingsPending = true,
                granted = false,
                permanentlyDenied = true,
            ),
        )
        assertEquals(
            InternetCameraSettingsReturnAction.SHOW_FIRST_DENIED_PANEL,
            InternetCameraPermissionRecoveryPolicy.settingsReturn(
                settingsPending = true,
                granted = false,
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
