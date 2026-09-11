package dev.telemachus.display

import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import androidx.annotation.StringRes
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.constraintlayout.widget.ConstraintLayout
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.NotFoundException
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import java.util.concurrent.Executors

class QRScannerActivity : AppCompatActivity() {
    private val reader = QRCodeReader()
    private val analyzerExecutor = Executors.newSingleThreadExecutor()
    private val cameraPerm by lazy { CameraPermissionManager(this) }
    private var waitingForSettingsGrant = false
    @Volatile private var pendingResultRaw: String? = null
    private val decodeHints =
        mapOf(
            DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE),
            DecodeHintType.TRY_HARDER to true,
        )
    @Volatile private var alreadyDelivered = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        waitingForSettingsGrant = savedInstanceState?.getBoolean(KEY_WAITING_FOR_SETTINGS_GRANT) ?: false
        pendingResultRaw = savedInstanceState?.getString(KEY_PENDING_RESULT_RAW)
        alreadyDelivered = pendingResultRaw != null
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        enableScannerEdgeToEdge()
        setContentView(R.layout.activity_qr_scanner)
        setupScannerSafeInsets()
        findViewById<Button>(R.id.cancelButton).setOnClickListener { finishCanceled() }
        findViewById<Button>(R.id.retryCameraButton).setOnClickListener { handleCameraRetry() }
        pendingResultRaw?.let { raw ->
            deliverAcceptedResult(raw)
            return
        }
        startCamera()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean(KEY_WAITING_FOR_SETTINGS_GRANT, waitingForSettingsGrant)
        pendingResultRaw?.let { outState.putString(KEY_PENDING_RESULT_RAW, it) }
        super.onSaveInstanceState(outState)
    }

    private fun enableScannerEdgeToEdge() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            window.attributes.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = Color.TRANSPARENT
        window.navigationBarColor = Color.TRANSPARENT
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = false
            isAppearanceLightNavigationBars = false
        }
    }

    private fun setupScannerSafeInsets() {
        val root = findViewById<View>(R.id.qrScannerRoot)
        val baseMargins = QRScannerSafeInsets.capture(root)

        ViewCompat.setOnApplyWindowInsetsListener(root) { _, windowInsets ->
            val bars = windowInsets.getInsetsIgnoringVisibility(WindowInsetsCompat.Type.systemBars())
            val cutout = windowInsets.getInsets(WindowInsetsCompat.Type.displayCutout())
            QRScannerSafeInsets.apply(
                root,
                baseMargins,
                left = maxOf(bars.left, cutout.left),
                top = maxOf(bars.top, cutout.top),
                right = maxOf(bars.right, cutout.right),
                bottom = maxOf(bars.bottom, cutout.bottom),
            )
            windowInsets
        }
        ViewCompat.requestApplyInsets(root)
    }

    override fun onResume() {
        super.onResume()
        if (waitingForSettingsGrant && hasCameraPermission()) {
            waitingForSettingsGrant = false
            startCamera()
        }
    }

    private fun startCamera() {
        if (!hasCameraPermission()) {
            handleMissingCameraPermission()
            return
        }
        waitingForSettingsGrant = false
        showScannerReady()
        val previewView = findViewById<PreviewView>(R.id.preview)
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener({
            try {
                val provider = providerFuture.get()
                val preview =
                    Preview.Builder().build().also {
                        it.setSurfaceProvider(previewView.surfaceProvider)
                    }
                val analyzer =
                    ImageAnalysis
                        .Builder()
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build()
                analyzer.setAnalyzer(analyzerExecutor, this::analyze)
                provider.unbindAll()
                provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, preview, analyzer)
            } catch (e: Exception) {
                Log.e(TAG, "Camera bind failed", e)
                showScannerError(R.string.qr_scanner_camera_bind_failed)
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun handleCameraRetry() {
        when {
            hasCameraPermission() -> startCamera()
            cameraPerm.isPermanentlyDenied() -> openCameraPermissionSettings()
            else -> requestCameraPermission()
        }
    }

    private fun handleMissingCameraPermission() {
        if (cameraPerm.isPermanentlyDenied()) {
            showCameraPermissionBlocked()
        } else {
            requestCameraPermission()
        }
    }

    private fun requestCameraPermission() {
        showScannerError(R.string.qr_scanner_camera_permission_missing)
        cameraPerm.request(REQ_CAMERA)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_CAMERA) return
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            startCamera()
        } else if (cameraPerm.isPermanentlyDenied()) {
            showCameraPermissionBlocked()
        } else {
            showScannerError(R.string.qr_scanner_camera_permission_missing)
        }
    }

    private fun showCameraPermissionBlocked() {
        showScannerError(
            R.string.qr_scanner_camera_permission_blocked,
            R.string.open_settings,
            R.string.qr_scanner_open_settings_description,
        )
    }

    private fun openCameraPermissionSettings() {
        waitingForSettingsGrant = true
        showCameraPermissionBlocked()
        cameraPerm.openAppSettings()
    }

    private fun hasCameraPermission(): Boolean = cameraPerm.isGranted()

    private fun showScannerReady() {
        findViewById<TextView>(R.id.scannerInstruction).visibility = View.VISIBLE
        findViewById<PreviewView>(R.id.preview).visibility = View.VISIBLE
        findViewById<View>(R.id.targetFrame).visibility = View.VISIBLE
        findViewById<Button>(R.id.retryCameraButton).visibility = View.GONE
        val status = findViewById<TextView>(R.id.scannerStatus)
        status.contentDescription = getString(R.string.qr_scanner_starting_status)
        LiveRegionTextApplier.hide(status)
    }

    private fun showScannerError(
        @StringRes messageRes: Int,
        @StringRes actionTextRes: Int = R.string.retry_now,
        @StringRes actionDescriptionRes: Int = R.string.qr_scanner_retry_camera_description,
    ) {
        findViewById<TextView>(R.id.scannerInstruction).visibility = View.GONE
        findViewById<PreviewView>(R.id.preview).visibility = View.INVISIBLE
        findViewById<View>(R.id.targetFrame).visibility = View.GONE
        showScannerStatus(getString(messageRes))
        findViewById<Button>(R.id.retryCameraButton).apply {
            text = getString(actionTextRes)
            contentDescription = getString(actionDescriptionRes)
            visibility = View.VISIBLE
            requestFocus()
        }
    }

    private fun showScannerStatus(message: CharSequence) {
        val status = findViewById<TextView>(R.id.scannerStatus)
        status.contentDescription = message
        LiveRegionTextApplier.show(status, message)
    }

    private fun analyze(proxy: ImageProxy) {
        if (alreadyDelivered) {
            proxy.close()
            return
        }
        try {
            val plane = proxy.planes.firstOrNull() ?: return
            val packed =
                packAndRotateLuma(
                    plane.buffer,
                    proxy.width,
                    proxy.height,
                    plane.rowStride,
                    plane.pixelStride,
                    proxy.imageInfo.rotationDegrees,
                )
            val source =
                PlanarYUVLuminanceSource(
                    packed.bytes,
                    packed.width,
                    packed.height,
                    0,
                    0,
                    packed.width,
                    packed.height,
                    false,
                )
            val raw = reader.decode(BinaryBitmap(HybridBinarizer(source)), decodeHints).text
            if (isSupportedPairingNamespace(raw)) {
                deliverResult(raw)
            }
        } catch (_: NotFoundException) {
            // Most camera frames do not contain a QR code.
        } catch (e: Exception) {
            Log.e(TAG, "QR scan error", e)
        } finally {
            reader.reset()
            proxy.close()
        }
    }

    private fun deliverResult(raw: String) {
        if (alreadyDelivered) return
        val validLegacy = PairingURL.parse(raw) != null
        val validInternet = raw.startsWith(INTERNET_PAIRING_PREFIX)
        if (validLegacy || validInternet) {
            pendingResultRaw = raw
            alreadyDelivered = true
        }
        runOnUiThread {
            // Product pairing is parsed exactly once by InternetPairingCoordinator,
            // which owns and clears the one-time credential. The scanner only routes
            // the namespaced payload and never interprets its security fields.
            if (!validLegacy && !validInternet) {
                showScannerStatus(getString(R.string.invalid_pairing_qr))
                alreadyDelivered = false
            } else {
                deliverAcceptedResult(raw)
            }
        }
    }

    private fun deliverAcceptedResult(raw: String) {
        setResult(RESULT_OK, Intent().putExtra(EXTRA_URL, raw))
        finish()
    }

    override fun onDestroy() {
        analyzerExecutor.shutdownNow()
        super.onDestroy()
    }

    private fun finishCanceled() {
        setResult(RESULT_CANCELED)
        finish()
    }

    companion object {
        private const val TAG = "QRScanner"
        private const val INTERNET_PAIRING_PREFIX = "vibescreen://pair?"
        private const val REQ_CAMERA = 1201
        private const val KEY_WAITING_FOR_SETTINGS_GRANT = "qr_scanner_waiting_for_settings_grant"
        private const val KEY_PENDING_RESULT_RAW = "qr_scanner_pending_result_raw"
        const val EXTRA_URL = "qr_url"

        internal fun isSupportedPairingNamespace(raw: String): Boolean =
            raw.startsWith("telemachus://") || raw.startsWith(INTERNET_PAIRING_PREFIX)

        internal data class LumaImage(
            val bytes: ByteArray,
            val width: Int,
            val height: Int,
        )

        internal fun packAndRotateLuma(
            source: java.nio.ByteBuffer,
            width: Int,
            height: Int,
            rowStride: Int,
            pixelStride: Int,
            rotationDegrees: Int,
        ): LumaImage {
            require(width > 0 && height > 0)
            require(pixelStride > 0 && rowStride >= (width - 1) * pixelStride + 1)
            val packed = ByteArray(width * height)
            val buffer = source.duplicate()
            for (y in 0 until height) {
                for (x in 0 until width) {
                    packed[y * width + x] = buffer.get(y * rowStride + x * pixelStride)
                }
            }
            return rotateLuma(packed, width, height, rotationDegrees)
        }

        internal fun rotateLuma(
            source: ByteArray,
            width: Int,
            height: Int,
            rotationDegrees: Int,
        ): LumaImage {
            require(source.size == width * height)
            val normalized = ((rotationDegrees % 360) + 360) % 360
            if (normalized == 0) return LumaImage(source, width, height)
            require(normalized == 90 || normalized == 180 || normalized == 270)

            val targetWidth = if (normalized == 180) width else height
            val targetHeight = if (normalized == 180) height else width
            val target = ByteArray(source.size)
            for (y in 0 until height) {
                for (x in 0 until width) {
                    val sourceIndex = y * width + x
                    val targetIndex =
                        when (normalized) {
                            90 -> x * height + (height - 1 - y)
                            180 -> (height - 1 - y) * width + (width - 1 - x)
                            else -> (width - 1 - x) * height + y
                        }
                    target[targetIndex] = source[sourceIndex]
                }
            }
            return LumaImage(target, targetWidth, targetHeight)
        }
    }
}

internal object QRScannerSafeInsets {
    data class Snapshot(
        val instruction: MarginSnapshot,
        val status: MarginSnapshot,
        val retry: MarginSnapshot,
        val cancel: MarginSnapshot,
        val target: MarginSnapshot,
        val statusGoneTop: Int,
    )

    data class MarginSnapshot(
        val start: Int,
        val top: Int,
        val end: Int,
        val bottom: Int,
    )

    fun capture(root: View): Snapshot =
        Snapshot(
            instruction = root.findViewById<View>(R.id.scannerInstruction).marginSnapshot(),
            status = root.findViewById<View>(R.id.scannerStatus).marginSnapshot(),
            retry = root.findViewById<View>(R.id.retryCameraButton).marginSnapshot(),
            cancel = root.findViewById<View>(R.id.cancelButton).marginSnapshot(),
            target = root.findViewById<View>(R.id.targetFrame).marginSnapshot(),
            statusGoneTop = root.findViewById<View>(R.id.scannerStatus).goneTopMargin(),
        )

    fun apply(
        root: View,
        base: Snapshot,
        left: Int,
        top: Int,
        right: Int,
        bottom: Int,
    ) {
        val isRtl = ViewCompat.getLayoutDirection(root) == ViewCompat.LAYOUT_DIRECTION_RTL
        val startInset = if (isRtl) right else left
        val endInset = if (isRtl) left else right
        root.findViewById<View>(R.id.scannerInstruction)
            .applyMargins(base.instruction, start = startInset, top = top, end = endInset)
        root.findViewById<View>(R.id.scannerStatus)
            .applyMargins(base.status, start = startInset, end = endInset)
        root.findViewById<View>(R.id.scannerStatus)
            .applyGoneTopMargin(base.statusGoneTop, top)
        root.findViewById<View>(R.id.retryCameraButton)
            .applyMargins(base.retry, start = startInset, end = endInset)
        root.findViewById<View>(R.id.cancelButton)
            .applyMargins(base.cancel, start = startInset, end = endInset, bottom = bottom)
        root.findViewById<View>(R.id.targetFrame)
            .applyMargins(base.target, start = startInset, end = endInset)
    }

    private fun View.marginSnapshot(): MarginSnapshot {
        val margins = layoutParams as ViewGroup.MarginLayoutParams
        return MarginSnapshot(margins.marginStart, margins.topMargin, margins.marginEnd, margins.bottomMargin)
    }

    private fun View.applyMargins(
        base: MarginSnapshot,
        start: Int = 0,
        top: Int = 0,
        end: Int = 0,
        bottom: Int = 0,
    ) {
        val margins = layoutParams as ViewGroup.MarginLayoutParams
        val nextStart = base.start + start
        val nextTop = base.top + top
        val nextEnd = base.end + end
        val nextBottom = base.bottom + bottom
        if (
            margins.marginStart != nextStart ||
            margins.topMargin != nextTop ||
            margins.marginEnd != nextEnd ||
            margins.bottomMargin != nextBottom
        ) {
            margins.marginStart = nextStart
            margins.topMargin = nextTop
            margins.marginEnd = nextEnd
            margins.bottomMargin = nextBottom
            layoutParams = margins
        }
    }

    private fun View.goneTopMargin(): Int {
        val params = layoutParams as? ConstraintLayout.LayoutParams ?: return 0
        return params.goneTopMargin
    }

    private fun View.applyGoneTopMargin(
        base: Int,
        top: Int,
    ) {
        val params = layoutParams as? ConstraintLayout.LayoutParams ?: return
        val nextTop = base + top
        if (params.goneTopMargin != nextTop) {
            params.goneTopMargin = nextTop
            layoutParams = params
        }
    }
}
