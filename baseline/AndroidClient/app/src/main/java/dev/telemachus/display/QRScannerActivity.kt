package dev.telemachus.display

import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.view.View
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
import androidx.core.content.ContextCompat
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
    private val decodeHints =
        mapOf(
            DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE),
            DecodeHintType.TRY_HARDER to true,
        )
    @Volatile private var alreadyDelivered = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setContentView(R.layout.activity_qr_scanner)
        findViewById<Button>(R.id.cancelButton).setOnClickListener { finishCanceled() }
        findViewById<Button>(R.id.retryCameraButton).setOnClickListener { handleCameraRetry() }
        startCamera()
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
        alreadyDelivered = true
        runOnUiThread {
            val validLegacy = PairingURL.parse(raw) != null
            // Product pairing is parsed exactly once by InternetPairingCoordinator,
            // which owns and clears the one-time credential. The scanner only routes
            // the namespaced payload and never interprets its security fields.
            val validInternet = raw.startsWith(INTERNET_PAIRING_PREFIX)
            if (!validLegacy && !validInternet) {
                showScannerStatus(getString(R.string.invalid_pairing_qr))
                alreadyDelivered = false
            } else {
                setResult(RESULT_OK, Intent().putExtra(EXTRA_URL, raw))
                finish()
            }
        }
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
