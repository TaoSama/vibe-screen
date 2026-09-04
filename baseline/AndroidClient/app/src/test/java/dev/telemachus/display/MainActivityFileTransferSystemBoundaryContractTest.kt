package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityFileTransferSystemBoundaryContractTest {
    @Test
    fun incomingFileTransferExposesProgressAndUserCancelThroughProductState() {
        val source = mainActivitySource()
        val begin = extractMethod(source, "private fun beginIncomingFileTransferState")
        val progress = extractMethod(source, "private fun updateIncomingFileTransferProgress")
        val cancel = extractMethod(source, "private fun cancelIncomingFileTransferFromDialog")
        val callback = extractCallback(source, "callbackClient.onIncomingFileProgress = fileProgress@")
        val cancelledCallback = extractCallback(source, "callbackClient.onIncomingFileCancelled = fileCancelled@")

        assertTrue(
            "Accepting an incoming offer should register active receive state after the protocol response is admitted",
            source.contains("""if (respond(true, ""))""") && source.contains("beginTransfer()"),
        )
        assertTrue(
            "Active receive state should retain transfer id, display name, byte length, and cancel command",
            begin.contains("ActiveIncomingFileTransfer(transferId, displayName, byteLength, cancel)"),
        )
        assertTrue(
            "Incoming progress callback should update the active receive dialog only on the current session",
            callback.contains("updateIncomingFileTransferProgress(transferId, receivedBytes)"),
        )
        assertTrue(
            "Progress updates must be transfer-id scoped",
            progress.contains("if (active.transferId != transferId) return"),
        )
        assertTrue(
            "User cancellation must call the active transfer cancellation boundary",
            cancel.contains("active.cancel(transferId)"),
        )
        assertTrue(
            "Incoming cancellation should clear only the matching active receive state",
            cancelledCallback.contains("finishIncomingFileTransferState(transferId)"),
        )
    }

    @Test
    fun outgoingFileTransferExposesProgressAndUserCancelThroughProductState() {
        val source = mainActivitySource()
        val handlePicker = extractMethod(source, "private fun handleFileTransferPickerResult")
        val begin = extractMethod(source, "private fun beginOutgoingFileTransferState")
        val progress = extractMethod(source, "private fun updateOutgoingFileTransferProgress")
        val finish = extractMethod(source, "private fun finishOutgoingFileTransferState")
        val cancel = extractMethod(source, "private fun cancelOutgoingFileTransferFromDialog")
        val discard = extractMethod(source, "private fun discardPendingOutgoingFileTransfer")
        val failureMessage = extractMethod(source, "private fun fileTransferFailureMessageId")
        val callback = extractCallback(source, "callbackClient.onOutgoingFileProgress = outgoingProgress@")
        val finishedCallback = extractCallback(source, "callbackClient.onOutgoingFileFinished = outgoingFinished@")
        val internetProgress = extractCallback(source, "override fun onOutgoingFileProgress(")
        val internetFinished = extractCallback(source, "override fun onOutgoingFileFinished(transferId: ByteString)")

        assertTrue(
            "Starting an outgoing offer should register active sending state from the returned transfer handle",
            handlePicker.contains("val outgoingValue =") &&
                handlePicker.contains("beginOutgoingFileTransferState(") &&
                handlePicker.contains("transferId = outgoingValue.transferId"),
        )
        assertTrue(
            "Picker completion must not show a dialog after the Activity is destroyed",
            handlePicker.contains("if (isFinishing || isDestroyed || !session.isCurrent()) return@withContext"),
        )
        assertTrue(
            "Started toast should only show when the outgoing progress state is actually displayed",
            handlePicker.contains("val started =") &&
                handlePicker.contains("if (started)") &&
                handlePicker.contains("showDedupedToast(R.string.file_transfer_sent_to_mac)"),
        )
        assertTrue(
            "A finished-before-begin transfer should still clean up staged outgoing files",
            handlePicker.contains("discardPendingOutgoingFileTransfer(clearFinishedTransferMarkers = false)"),
        )
        assertTrue(
            "Active send state should retain transfer id, display name, byte length, and cancel command",
            begin.contains("ActiveOutgoingFileTransfer(transferId, displayName, byteLength, cancel)"),
        )
        assertTrue(
            "A finish callback that arrives before UI state begins must suppress the late outgoing dialog",
            begin.contains("if (hasOutgoingFileTransferAlreadyFinished(transferId)) return false") &&
                finish.contains("transferId?.let(::markOutgoingFileTransferFinished)") &&
                source.contains("private fun hasOutgoingFileTransferAlreadyFinished(transferId: ByteString): Boolean"),
        )
        assertTrue(
            "Outgoing progress callback should update the active send dialog only on the current stream session",
            callback.contains("updateOutgoingFileTransferProgress(transferId, acknowledgedBytes, totalBytes)"),
        )
        assertTrue(
            "Outgoing Internet progress callback should share the same active send dialog",
            internetProgress.contains("updateOutgoingFileTransferProgress(transferId, acknowledgedBytes, totalBytes)"),
        )
        assertTrue(
            "Outgoing progress updates must be transfer-id scoped",
            progress.contains("if (active.transferId != transferId) return"),
        )
        assertTrue(
            "User cancellation must call the active outgoing transfer cancellation boundary",
            cancel.contains("active.cancel(transferId)"),
        )
        assertTrue(
            "User cancellation success should map to cancelled copy, not generic failure",
            failureMessage.contains("\"user_cancelled\"") &&
                failureMessage.contains("R.string.file_transfer_failed_cancelled"),
        )
        assertTrue(
            "If the cancel command cannot be submitted, the UI should not claim it was cancelled",
            cancel.contains("if (!cancelled)") &&
                cancel.contains("showDedupedToast(R.string.file_transfer_cancel_failed)"),
        )
        assertTrue(
            "Outgoing completion should clear only the matching active send state",
            finishedCallback.contains("finishOutgoingFileTransferState(transferId)") &&
                internetFinished.contains("finishOutgoingFileTransferState(transferId)") &&
                finish.contains("activeOutgoingFileTransfer?.transferId == transferId"),
        )
        assertTrue(
            "Generic outgoing cleanup should dismiss active send state and delete staged files",
            discard.contains("finishOutgoingFileTransferState(null)") &&
                discard.contains("if (clearFinishedTransferMarkers) recentlyFinishedOutgoingTransferIds.clear()") &&
                discard.contains("takePendingOutgoingFileTransfer()"),
        )
        assertTrue(
            "File-transfer result callbacks should preserve fresh finished markers for late picker completion",
            source.contains("discardPendingOutgoingFileTransfer(clearFinishedTransferMarkers = false)"),
        )
    }

    @Test
    fun outgoingFileTransferCancelCopyHasDedicatedFailureMessage() {
        val strings = stringsSource()

        assertTrue(strings.contains("file_transfer_failed_cancelled"))
        assertTrue(strings.contains("File transfer request was cancelled."))
        assertTrue(strings.contains("file_transfer_cancel_failed"))
        assertTrue(strings.contains("File transfer could not be cancelled."))
    }

    private fun mainActivitySource(): String {
        return sourceFile(MAIN_ACTIVITY_PATHS).readText()
    }

    private fun stringsSource(): String {
        return sourceFile(STRINGS_PATHS).readText()
    }

    private fun sourceFile(paths: List<String>): File {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            paths
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("Source file not found from " + System.getProperty("user.dir"))
    }

    private fun extractMethod(
        source: String,
        signature: String,
    ): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Method not found: $signature" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Method body not found: $signature" }
        return extractBraceBlock(source, start, bodyStart, signature)
    }

    private fun extractCallback(
        source: String,
        marker: String,
    ): String {
        val start = source.indexOf(marker)
        require(start >= 0) { "Callback not found: $marker" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Callback body not found: $marker" }
        return extractBraceBlock(source, start, bodyStart, marker)
    }

    private fun extractBraceBlock(
        source: String,
        start: Int,
        bodyStart: Int,
        label: String,
    ): String {
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
        error("Closing brace not found: $label")
    }

    private companion object {
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
        val STRINGS_PATHS =
            listOf(
                "app/src/main/res/values/strings.xml",
                "baseline/AndroidClient/app/src/main/res/values/strings.xml",
            )
    }
}
