package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class DialogActionButtonLayoutApplierTest {
    @Test
    fun applierEnforcesTwoLineWrappingAndTouchTargetContract() {
        val source = applierSource()

        assertTrue(
            "Applier covers positive, negative, and neutral buttons",
            source.contains("AlertDialog.BUTTON_NEGATIVE") &&
                source.contains("AlertDialog.BUTTON_POSITIVE") &&
                source.contains("AlertDialog.BUTTON_NEUTRAL"),
        )
        assertTrue(
            "Applier disables single-line restrictions and horizontal scrolling",
            source.contains("isSingleLine = false") &&
                source.contains("setHorizontallyScrolling(false)"),
        )
        assertTrue(
            "Applier clears ellipsize and sets maximum action button lines to 2",
            source.contains("ellipsize = null") &&
                source.contains("maxLines = MAX_ACTION_BUTTON_LINES") &&
                source.contains("MAX_ACTION_BUTTON_LINES = 2"),
        )
        assertTrue(
            "Applier enforces minimum touch target of 48dp on width and height",
            source.contains("MINIMUM_TOUCH_TARGET_DP = 48") &&
                source.contains("minWidth = max(minWidth, minimumTouchTarget)") &&
                source.contains("minHeight = max(minHeight, minimumTouchTarget)"),
        )
    }

    @Test
    fun mainActivityDialogsConsistentlyApplyReadableActionButtonLayout() {
        val source = mainActivitySource()
        val fileTransferError = extractMethod(source, "private fun showFileTransferRecoverableError")
        val sendClipboard = extractMethod(source, "private fun beginSendLocalClipboard")
        val receiveClipboard = extractMethod(source, "private fun beginReceiveRemoteClipboard")
        val overwriteClipboard = extractMethod(source, "private fun showClipboardOverwriteConfirmation")

        assertTrue(
            "File transfer recoverable error dialog applies DialogActionButtonLayoutApplier",
            fileTransferError.contains("showImmersiveDialog(builder).also(DialogActionButtonLayoutApplier::apply)"),
        )
        assertTrue(
            "LAN send clipboard dialog applies DialogActionButtonLayoutApplier",
            sendClipboard.contains(".also(DialogActionButtonLayoutApplier::apply)"),
        )
        assertTrue(
            "LAN receive clipboard dialog applies DialogActionButtonLayoutApplier",
            receiveClipboard.contains(".also(DialogActionButtonLayoutApplier::apply)"),
        )
        assertTrue(
            "Direct overwrite clipboard dialog applies DialogActionButtonLayoutApplier",
            overwriteClipboard.contains(".also(DialogActionButtonLayoutApplier::apply)"),
        )
    }

    private fun applierSource(): String = sourceFile(APPLIER_PATHS).readText()

    private fun mainActivitySource(): String = sourceFile(MAIN_ACTIVITY_PATHS).readText()

    private fun sourceFile(paths: List<String>): File {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            paths
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("Source file not found for paths $paths from " + System.getProperty("user.dir"))
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
        val APPLIER_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/DialogActionButtonLayoutApplier.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/DialogActionButtonLayoutApplier.kt",
            )
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
    }
}
