package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QRScannerAccessibilityContractTest {
    @Test
    fun cameraBindFailureStaysOnReadableRecoveryState() {
        val source = qrScannerActivitySource()
        val statusUpdateIndex = source.indexOf("showScannerStatus(getString(messageRes))")
        val retryFocusIndex = source.indexOf("requestFocus()")

        assertFalse("QR scanner should not rely on Toast feedback", source.contains("Toast.makeText"))
        assertTrue(source.contains("@Volatile private var alreadyDelivered = false"))
        assertTrue(source.contains("showScannerError(R.string.qr_scanner_camera_permission_missing)"))
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

    private companion object {
        val QR_SCANNER_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/QRScannerActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/QRScannerActivity.kt",
            )
    }
}
