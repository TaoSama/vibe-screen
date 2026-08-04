package dev.telemachus.display

internal enum class CameraPermissionResumeAction {
    NOOP,
    KEEP_DENIED,
    SHOW_SCAN_ENTRY,
    SHOW_SCAN_ENTRY_AND_LAUNCH,
}

internal object CameraPermissionResumePolicy {
    fun evaluate(
        state: WirelessTabController.State,
        granted: Boolean,
        permanentlyDenied: Boolean,
    ): CameraPermissionResumeAction {
        if (state != WirelessTabController.State.PERM_DENIED) {
            return CameraPermissionResumeAction.NOOP
        }
        return when {
            granted -> CameraPermissionResumeAction.SHOW_SCAN_ENTRY_AND_LAUNCH
            permanentlyDenied -> CameraPermissionResumeAction.KEEP_DENIED
            else -> CameraPermissionResumeAction.SHOW_SCAN_ENTRY
        }
    }
}
