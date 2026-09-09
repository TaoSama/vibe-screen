package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QRScannerAccessibilityContractTest {
    @Test
    fun activityAddsSecureWindowFlagBeforeCameraStarts() {
        val source = qrScannerActivitySource()
        val onCreate = extractMethod(source, "override fun onCreate")

        val flagIndex = onCreate.indexOf("window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)")
        val contentViewIndex = onCreate.indexOf("setContentView(R.layout.activity_qr_scanner)")
        val cameraIndex = onCreate.indexOf("startCamera()")

        assertTrue("QR scanner should keep pairing QR contents out of screenshots", flagIndex >= 0)
        assertTrue(contentViewIndex > flagIndex)
        assertTrue(cameraIndex > contentViewIndex)
    }

    @Test
    fun cameraBindFailureStaysOnReadableRecoveryState() {
        val source = qrScannerActivitySource()
        val statusUpdateIndex = source.indexOf("showScannerStatus(getString(messageRes))")
        val retryFocusIndex = source.indexOf("requestFocus()")

        assertFalse("QR scanner should not rely on Toast feedback", source.contains("Toast.makeText"))
        assertTrue(source.contains("@Volatile private var alreadyDelivered = false"))
        assertTrue(source.contains("showScannerError(R.string.qr_scanner_camera_bind_failed)"))
        assertTrue(source.contains("findViewById<Button>(R.id.retryCameraButton).apply"))
        assertTrue(source.contains("visibility = View.VISIBLE"))
        assertTrue(source.contains("findViewById<View>(R.id.targetFrame).visibility = View.GONE"))
        assertTrue(source.contains("requestFocus()"))
        assertTrue(source.contains("status.contentDescription = message"))
        assertTrue(source.contains("LiveRegionTextApplier.show(status, message)"))
        assertTrue(statusUpdateIndex >= 0)
        assertTrue(retryFocusIndex >= 0)
        assertTrue(statusUpdateIndex < retryFocusIndex)
        assertFalse("Assertive live region should not be double-announced", source.contains("announceForAccessibility"))
    }

    @Test
    fun missingCameraPermissionRequestsThenRecoversOrOpensSettings() {
        val source = qrScannerActivitySource()
        val startMissingIndex = source.indexOf("handleMissingCameraPermission()")
        val requestIndex = source.indexOf("cameraPerm.request(REQ_CAMERA)")
        val grantedIndex = source.indexOf("PackageManager.PERMISSION_GRANTED")
        val startAfterGrantIndex = source.indexOf("startCamera()", grantedIndex)

        assertTrue(source.contains("private val cameraPerm by lazy { CameraPermissionManager(this) }"))
        assertTrue(source.contains("findViewById<Button>(R.id.retryCameraButton).setOnClickListener { handleCameraRetry() }"))
        assertTrue(source.contains("else -> requestCameraPermission()"))
        assertTrue(source.contains("showScannerError(R.string.qr_scanner_camera_permission_missing)"))
        assertTrue(source.contains("cameraPerm.request(REQ_CAMERA)"))
        assertTrue(source.contains("override fun onRequestPermissionsResult"))
        assertTrue(source.contains("grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED"))
        assertTrue(source.contains("showCameraPermissionBlocked()"))
        assertTrue(source.contains("R.string.qr_scanner_camera_permission_blocked"))
        assertTrue(source.contains("R.string.open_settings"))
        assertTrue(source.contains("R.string.qr_scanner_open_settings_description"))
        assertTrue(source.contains("cameraPerm.openAppSettings()"))
        assertTrue(source.contains("waitingForSettingsGrant && hasCameraPermission()"))
        assertTrue(startMissingIndex >= 0)
        assertTrue(requestIndex >= 0)
        assertTrue(startMissingIndex < requestIndex)
        assertTrue(grantedIndex >= 0)
        assertTrue(startAfterGrantIndex > grantedIndex)
    }

    @Test
    fun invalidQrUsesReadableInlineStatus() {
        val source = qrScannerActivitySource()

        assertTrue(source.contains("showScannerStatus(getString(R.string.invalid_pairing_qr))"))
        assertTrue(source.contains("alreadyDelivered = false"))
    }

    private fun qrScannerActivitySource(): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            QR_SCANNER_ACTIVITY_PATHS
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("QRScannerActivity.kt not found from " + System.getProperty("user.dir"))
    }

    private fun extractMethod(
        source: String,
        signature: String,
    ): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Method not found: $signature" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Method body not found: $signature" }
        var depth = 0
        for (index in bodyStart until source.length) {
            when (source[index]) {
                '{' -> depth++
                '}' -> {
                    depth--
                    if (depth == 0) return source.substring(start, index + 1)
                }
            }
        }
        error("Closing brace not found: $signature")
    }

    private companion object {
        val QR_SCANNER_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/QRScannerActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/QRScannerActivity.kt",
            )
    }
}
