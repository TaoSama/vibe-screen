package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityShareFileContractTest {
    @Test
    fun manifestExposesOnlySingleFileSystemShareEntry() {
        val manifest = sourceFile("app/src/main/AndroidManifest.xml").readText()

        assertTrue(manifest.contains("android.intent.action.SEND"))
        assertTrue(manifest.contains("android.intent.category.DEFAULT"))
        assertTrue(manifest.contains("android:mimeType=") && manifest.contains("*/*"))
        assertFalse(manifest.contains("android.intent.action.SEND_MULTIPLE"))
    }

    @Test
    fun activityConsumesCreateAndNewIntentsOnceAndSharesPickerPipeline() {
        val source = sourceFile("app/src/main/java/dev/telemachus/display/MainActivity.kt").readText()
        val onCreate = extractMethod(source, "override fun onCreate")
        val onNewIntent = extractMethod(source, "override fun onNewIntent")
        val onSave = extractMethod(source, "override fun onSaveInstanceState")
        val consume = extractMethod(source, "private fun consumeShareFileIntentIfNeeded")
        val picker = extractMethod(source, "private fun handleFileTransferPickerResult")
        val handleUri = extractMethod(source, "private fun handleOutgoingFileTransferUri")
        val launchPolicy = extractMethod(source, "private fun applyLaunchIntentPolicy")

        assertTrue(onCreate.contains("restoredConsumedShareIntentToken = savedInstanceState?.getString(STATE_CONSUMED_SHARE_INTENT_TOKEN)"))
        assertTrue(onCreate.contains("allowImplicitUsbFallback = !ShareFileIntentPolicy.isShareCandidate(intent)"))
        assertTrue(onCreate.contains("consumeShareFileIntentIfNeeded(intent)"))
        assertTrue(onNewIntent.contains("setIntent(intent)"))
        assertTrue(onNewIntent.contains("consumeShareFileIntentIfNeeded(intent)"))
        assertTrue(onSave.contains("STATE_CONSUMED_SHARE_INTENT_TOKEN"))
        assertTrue(consume.contains("token == restoredConsumedShareIntentToken"))
        assertFalse(consume.contains("token == consumedShareIntentTokenForState"))
        assertEquals(1, Regex("consumedShareIntentTokenForState = token").findAll(consume).count())
        assertTrue(consume.contains("unavailableMessage = R.string.file_transfer_share_unavailable"))
        assertTrue(consume.contains("shareIntentToken = token"))
        assertTrue(picker.contains("handleOutgoingFileTransferUri(uri)"))
        assertTrue(handleUri.contains("stageOutgoingFileTransfer(uri, maximumFileBytes)"))
        assertTrue(handleUri.contains("transferOwnershipOrCleanup"))
        assertTrue(handleUri.contains("promptOutgoingFileTransfer("))
        assertTrue(launchPolicy.contains("!shareCandidate && launchIntent?.hasExtra(EXTRA_AUTO_CONNECT) == true"))
        assertTrue(launchPolicy.contains("if (hasAutoConnectExtra)"))
    }

    @Test
    fun noSessionFailsClosedBeforeAnyUriReadOrPickerLaunch() {
        val source = sourceFile("app/src/main/java/dev/telemachus/display/MainActivity.kt").readText()
        val handleUri = extractMethod(source, "private fun handleOutgoingFileTransferUri")
        val activeTransfer = handleUri.indexOf("if (hasActiveFileTransfer())")
        val activeTransferReturn = handleUri.indexOf("return", activeTransfer)
        val sessionResolution = handleUri.indexOf("val session = activeFileTransferSession()")
        val noSession = handleUri.indexOf("if (session == null)")
        val earlyReturn = handleUri.indexOf("return", noSession)
        val staging = handleUri.indexOf("stageOutgoingFileTransfer(uri, maximumFileBytes)")

        assertTrue(activeTransfer >= 0)
        assertTrue(activeTransferReturn > activeTransfer)
        assertTrue(sessionResolution > activeTransferReturn)
        assertTrue(noSession >= 0)
        assertTrue(earlyReturn > noSession)
        assertTrue(staging > earlyReturn)
        assertTrue(staging > sessionResolution)
        assertTrue(handleUri.contains("title = R.string.file_transfer_unavailable_title"))
        assertTrue(handleUri.contains("R.string.file_transfer_share_unavailable"))
        assertTrue(handleUri.contains("R.string.file_transfer_unavailable"))
        assertTrue(handleUri.contains("allowRetry = false"))
        assertFalse(handleUri.substring(0, earlyReturn).contains("contentResolver"))
        assertFalse(handleUri.contains("ACTION_OPEN_DOCUMENT"))
        assertFalse(handleUri.contains("startActivityForResult"))
    }

    private fun sourceFile(path: String): File {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            current.resolve(path).takeIf(File::isFile)?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("Source file not found: $path")
    }

    private fun extractMethod(source: String, signature: String): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Method not found: $signature" }
        val bodyStart = source.indexOf('{', start)
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
}
