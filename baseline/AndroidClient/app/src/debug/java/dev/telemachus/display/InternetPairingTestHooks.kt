package dev.telemachus.display

import android.content.Context
import android.content.Intent
import android.os.SystemClock
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.security.MessageDigest
import org.json.JSONObject

/** Debug source-set hooks used by real-camera QR pairing device acceptance harnesses. */
internal object InternetPairingTestHooks {
    const val EXTRA_QR_SCAN_MARKER_NAME =
        "dev.telemachus.display.extra.QR_SCAN_MARKER_NAME"

    const val FILE_INTERNET_PAIRING_OFFER = "internet_pairing_offer.txt"
    const val FILE_QR_SCAN_MARKER = "qr_scan_marker.json"
    const val FILE_QR_SCAN_MARKER_REQUEST = "qr_scan_marker_request.txt"

    val ALLOWED_APP_PRIVATE_FILE_NAMES: Set<String> =
        setOf(
            FILE_INTERNET_PAIRING_OFFER,
            FILE_QR_SCAN_MARKER,
            FILE_QR_SCAN_MARKER_REQUEST,
        )

    data class QrScanMarker(
        val payloadSha256Hex: String,
        val payloadBytes: Int,
        val frameWidth: Int,
        val frameHeight: Int,
        val rowStride: Int,
        val pixelStride: Int,
        val rotationDegrees: Int,
        val lumaWidth: Int,
        val lumaHeight: Int,
    )

    fun isWhitelistedFileName(name: String?): Boolean =
        name != null && name in ALLOWED_APP_PRIVATE_FILE_NAMES

    fun isMarkerActive(name: String?): Boolean =
        name != null && isWhitelistedFileName(name)

    fun attachQrScanMarkerExtra(
        context: Context,
        intent: Intent,
    ) {
        val request =
            consumeAppPrivateText(context, FILE_QR_SCAN_MARKER_REQUEST)
                ?.let { runCatching { JSONObject(it) }.getOrNull() }
        val targetName = request?.optString("marker_file")
        if (
            request?.optString("schema") == PRESENTER_READY_SCHEMA &&
            request.optBoolean("ready") &&
            targetName == FILE_QR_SCAN_MARKER
        ) {
            intent.putExtra(EXTRA_QR_SCAN_MARKER_NAME, targetName)
        }
    }

    fun consumeAppPrivateFileNameExtra(
        intent: Intent?,
        extraName: String,
    ): String? {
        if (intent == null) return null
        val name = intent.getStringExtra(extraName)
        if (intent.hasExtra(extraName)) intent.removeExtra(extraName)
        return name?.takeIf(::isWhitelistedFileName)
    }

    fun writeAppPrivateText(
        context: Context,
        name: String,
        value: String,
    ) {
        if (!isWhitelistedFileName(name)) return
        val file = appPrivateFile(context, name) ?: return
        writeAtomically(file, value.toByteArray(Charsets.UTF_8))
    }

    fun readAppPrivateText(
        context: Context,
        name: String,
    ): String? {
        if (!isWhitelistedFileName(name)) return null
        val file = appPrivateFile(context, name) ?: return null
        return file.takeIf(File::isFile)?.readText(Charsets.UTF_8)
    }

    fun deleteAppPrivateFile(
        context: Context,
        name: String?,
    ) {
        if (!isWhitelistedFileName(name)) return
        appPrivateFile(context, name)?.delete()
    }

    fun writeQrScanMarker(
        context: Context,
        name: String?,
        marker: QrScanMarker,
    ) {
        if (!isWhitelistedFileName(name)) return
        writeAppPrivateText(context, checkNotNull(name), marker.encode())
    }

    fun sha256Hex(value: String): String =
        MessageDigest
            .getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }

    private fun consumeAppPrivateText(
        context: Context,
        name: String,
    ): String? {
        if (!isWhitelistedFileName(name)) return null
        val file = appPrivateFile(context, name) ?: return null
        return try {
            file.takeIf(File::isFile)?.readText(Charsets.UTF_8)
        } finally {
            file.delete()
        }
    }

    private fun appPrivateFile(
        context: Context,
        name: String?,
    ): File? {
        if (!isWhitelistedFileName(name)) return null
        return File(context.filesDir, checkNotNull(name))
    }

    private fun QrScanMarker.encode(): String =
        JSONObject()
            .put("schema", QR_SCAN_MARKER_SCHEMA)
            .put("source", "CameraX ImageAnalysis")
            .put("decoder", "ZXing QRCodeReader")
            .put("payload_sha256", payloadSha256Hex)
            .put("payload_bytes", payloadBytes)
            .put("frame_width", frameWidth)
            .put("frame_height", frameHeight)
            .put("row_stride", rowStride)
            .put("pixel_stride", pixelStride)
            .put("rotation_degrees", rotationDegrees)
            .put("luma_width", lumaWidth)
            .put("luma_height", lumaHeight)
            .put("decoded_at_uptime_ms", SystemClock.uptimeMillis())
            .toString()

    private fun writeAtomically(
        file: File,
        bytes: ByteArray,
    ) {
        file.parentFile?.mkdirs()
        val temporary = File(file.parentFile, ".${file.name}.${SystemClock.uptimeMillis()}.tmp")
        try {
            FileOutputStream(temporary).use { output ->
                output.write(bytes)
                output.fd.sync()
            }
            if (!temporary.renameTo(file)) {
                throw IOException("Could not replace app-private test file")
            }
            file.setReadable(false, false)
            file.setWritable(false, false)
            file.setExecutable(false, false)
            file.setReadable(true, true)
            file.setWritable(true, true)
        } finally {
            temporary.delete()
        }
    }

    const val QR_SCAN_MARKER_SCHEMA = "dev.vibescreen.phase3-real-qr-scan-marker/v1"
    const val PRESENTER_READY_SCHEMA = "dev.vibescreen.phase3-real-qr-presenter-ready/v1"
}
