package dev.telemachus.display

internal enum class InternetCameraPermissionPanelState {
    HIDDEN,
    FIRST_DENIED,
    SETTINGS_REQUIRED,
}

internal enum class InternetCameraScanAction {
    LAUNCH_SCANNER,
    REQUEST_PERMISSION,
    SHOW_SETTINGS_PANEL,
}

internal enum class InternetCameraPermissionResultAction {
    LAUNCH_SCANNER,
    SHOW_FIRST_DENIED_PANEL,
    SHOW_SETTINGS_PANEL,
}

internal enum class InternetCameraSettingsReturnAction {
    NOOP,
    LAUNCH_SCANNER_ONCE,
    SHOW_FIRST_DENIED_PANEL,
    SHOW_SETTINGS_PANEL,
}

internal object InternetCameraPermissionRecoveryPolicy {
    fun scanRequested(
        granted: Boolean,
        permanentlyDenied: Boolean,
    ): InternetCameraScanAction =
        when {
            granted -> InternetCameraScanAction.LAUNCH_SCANNER
            permanentlyDenied -> InternetCameraScanAction.SHOW_SETTINGS_PANEL
            else -> InternetCameraScanAction.REQUEST_PERMISSION
        }

    fun permissionResult(
        granted: Boolean,
        permanentlyDenied: Boolean,
    ): InternetCameraPermissionResultAction =
        when {
            granted -> InternetCameraPermissionResultAction.LAUNCH_SCANNER
            permanentlyDenied -> InternetCameraPermissionResultAction.SHOW_SETTINGS_PANEL
            else -> InternetCameraPermissionResultAction.SHOW_FIRST_DENIED_PANEL
        }

    // A visible recovery panel is treated as an active user recovery flow, even
    // when Camera was granted from Android Settings without using our button.
    fun foregroundReturn(
        panelState: InternetCameraPermissionPanelState,
        settingsPending: Boolean,
        granted: Boolean,
        permanentlyDenied: Boolean,
    ): InternetCameraSettingsReturnAction {
        if (!settingsPending && panelState == InternetCameraPermissionPanelState.HIDDEN) {
            return InternetCameraSettingsReturnAction.NOOP
        }
        return permissionRecoveryReturn(granted, permanentlyDenied)
    }

    private fun permissionRecoveryReturn(
        granted: Boolean,
        permanentlyDenied: Boolean,
    ): InternetCameraSettingsReturnAction =
        when {
            granted -> InternetCameraSettingsReturnAction.LAUNCH_SCANNER_ONCE
            permanentlyDenied -> InternetCameraSettingsReturnAction.SHOW_SETTINGS_PANEL
            else -> InternetCameraSettingsReturnAction.SHOW_FIRST_DENIED_PANEL
        }

    fun restoredPanelState(name: String?): InternetCameraPermissionPanelState =
        InternetCameraPermissionPanelState.entries.firstOrNull { state -> state.name == name }
            ?: InternetCameraPermissionPanelState.HIDDEN
}
