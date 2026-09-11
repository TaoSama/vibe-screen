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
        val edgeIndex = onCreate.indexOf("enableScannerEdgeToEdge()")
        val contentViewIndex = onCreate.indexOf("setContentView(R.layout.activity_qr_scanner)")
        val insetsIndex = onCreate.indexOf("setupScannerSafeInsets()")
        val cameraIndex = onCreate.indexOf("startCamera()")

        assertTrue("QR scanner should keep pairing QR contents out of screenshots", flagIndex >= 0)
        assertTrue("QR scanner should opt into edge-to-edge before inflation", edgeIndex > flagIndex)
        assertTrue("QR scanner should inflate only after FLAG_SECURE is active", contentViewIndex > flagIndex)
        assertTrue("QR scanner should attach safe-area handling before camera startup", insetsIndex > contentViewIndex)
        assertTrue("QR scanner should attach safe-area handling before camera startup", cameraIndex > insetsIndex)
        assertTrue("QR scanner should start CameraX only after FLAG_SECURE is active", cameraIndex > flagIndex)
        assertTrue("QR scanner should bind camera only after the secure layout exists", cameraIndex > contentViewIndex)
    }

    @Test
    fun scannerOwnsEdgeToEdgeAndSafeInsetsForChromeOnly() {
        val source = qrScannerActivitySource()

        assertTrue(source.contains("WindowCompat.setDecorFitsSystemWindows(window, false)"))
        assertTrue(source.contains("LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES"))
        assertTrue(source.contains("window.statusBarColor = Color.TRANSPARENT"))
        assertTrue(source.contains("window.navigationBarColor = Color.TRANSPARENT"))
        assertTrue(source.contains("WindowInsetsControllerCompat(window, window.decorView).apply"))
        assertTrue(source.contains("isAppearanceLightStatusBars = false"))
        assertTrue(source.contains("isAppearanceLightNavigationBars = false"))
        assertTrue(source.contains("ViewCompat.setOnApplyWindowInsetsListener(root)"))
        assertTrue(source.contains("getInsetsIgnoringVisibility(WindowInsetsCompat.Type.systemBars())"))
        assertTrue(source.contains("WindowInsetsCompat.Type.displayCutout()"))
        assertTrue(source.contains("QRScannerSafeInsets.apply("))
        assertTrue(source.contains("root.findViewById<View>(R.id.scannerInstruction)"))
        assertTrue(source.contains("root.findViewById<View>(R.id.cancelButton)"))
        assertTrue(source.contains("root.findViewById<View>(R.id.targetFrame)"))
        assertFalse("Preview must stay edge-to-edge for camera framing", source.contains("R.id.preview).applyMargins"))
    }

    @Test
    fun scannerContractsStayStaticAndDoNotLaunchCameraActivity() {
        val source = qrScannerContractSource()
        val activityScenario = "Activity" + "Scenario"
        val scenarioLaunch = activityScenario + "." + "launch"
        val qrScannerClass = "QRScannerActivity" + "::class"
        val startActivityCall = "start" + "Activity("

        assertFalse(source.contains(activityScenario))
        assertFalse(source.contains("$scenarioLaunch($qrScannerClass.java)"))
        assertFalse(source.contains("$scenarioLaunch<QRScannerActivity>"))
        assertFalse(source.contains(startActivityCall))
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

    @Test
    fun scannerRestoresTransientStateAcrossRotation() {
        val source = qrScannerActivitySource()
        val onCreate = extractMethod(source, "override fun onCreate")
        val onSave = extractMethod(source, "override fun onSaveInstanceState")
        val deliverResult = extractMethod(source, "private fun deliverResult")

        assertTrue(source.contains("private const val KEY_WAITING_FOR_SETTINGS_GRANT"))
        assertTrue(source.contains("private const val KEY_PENDING_RESULT_RAW"))
        assertTrue(source.contains("@Volatile private var pendingResultRaw: String? = null"))
        assertTrue(onCreate.contains("waitingForSettingsGrant = savedInstanceState?.getBoolean(KEY_WAITING_FOR_SETTINGS_GRANT) ?: false"))
        assertTrue(onCreate.contains("pendingResultRaw = savedInstanceState?.getString(KEY_PENDING_RESULT_RAW)"))
        assertTrue(onCreate.contains("alreadyDelivered = pendingResultRaw != null"))
        assertTrue(onCreate.contains("pendingResultRaw?.let { raw ->"))
        assertTrue(onCreate.contains("deliverAcceptedResult(raw)"))
        assertTrue(onSave.contains("outState.putBoolean(KEY_WAITING_FOR_SETTINGS_GRANT, waitingForSettingsGrant)"))
        assertTrue(onSave.contains("pendingResultRaw?.let { outState.putString(KEY_PENDING_RESULT_RAW, it) }"))
        assertTrue(deliverResult.indexOf("pendingResultRaw = raw") < deliverResult.indexOf("runOnUiThread"))
        assertTrue(onSave.indexOf("outState.putBoolean(KEY_WAITING_FOR_SETTINGS_GRANT") < onSave.indexOf("super.onSaveInstanceState(outState)"))
    }

    private fun qrScannerActivitySource(): String {
        return readSource(QR_SCANNER_ACTIVITY_PATHS, "QRScannerActivity.kt")
    }

    private fun qrScannerContractSource(): String {
        return readSource(QR_SCANNER_CONTRACT_PATHS, "QRScannerAccessibilityContractTest.kt")
    }

    private fun readSource(
        paths: List<String>,
        name: String,
    ): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            paths
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("$name not found from " + System.getProperty("user.dir"))
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
        val QR_SCANNER_CONTRACT_PATHS =
            listOf(
                "app/src/test/java/dev/telemachus/display/QRScannerAccessibilityContractTest.kt",
                "baseline/AndroidClient/app/src/test/java/dev/telemachus/display/QRScannerAccessibilityContractTest.kt",
            )
    }
}
