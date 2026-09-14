@file:Suppress("UNUSED_PARAMETER")

package dev.telemachus.display

import android.content.Context
import android.content.Intent

/** Release source-set no-op implementation of [InternetPairingTestHooks]. */
internal object InternetPairingTestHooks {
    const val EXTRA_QR_SCAN_MARKER_NAME =
        "dev.telemachus.display.extra.QR_SCAN_MARKER_NAME"

    const val FILE_INTERNET_PAIRING_OFFER = "internet_pairing_offer.txt"
    const val FILE_QR_SCAN_MARKER = "qr_scan_marker.json"
    const val FILE_QR_SCAN_MARKER_REQUEST = "qr_scan_marker_request.txt"

    val ALLOWED_APP_PRIVATE_FILE_NAMES: Set<String> = emptySet()

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

    fun isWhitelistedFileName(name: String?): Boolean = false

    fun isMarkerActive(name: String?): Boolean = false

    fun attachQrScanMarkerExtra(
        context: Context,
        intent: Intent,
    ) = Unit

    fun consumeAppPrivateFileNameExtra(
        intent: Intent?,
        extraName: String,
    ): String? = null

    fun writeAppPrivateText(
        context: Context,
        name: String,
        value: String,
    ) = Unit

    fun readAppPrivateText(
        context: Context,
        name: String,
    ): String? = null

    fun deleteAppPrivateFile(
        context: Context,
        name: String?,
    ) = Unit

    fun writeQrScanMarker(
        context: Context,
        name: String?,
        marker: QrScanMarker,
    ) = Unit

    fun sha256Hex(value: String): String = ""

    const val QR_SCAN_MARKER_SCHEMA = "dev.vibescreen.phase3-real-qr-scan-marker/v1"
    const val PRESENTER_READY_SCHEMA = "dev.vibescreen.phase3-real-qr-presenter-ready/v1"
}
