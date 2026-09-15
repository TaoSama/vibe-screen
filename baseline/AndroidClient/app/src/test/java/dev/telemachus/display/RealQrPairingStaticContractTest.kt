package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Static contract and JVM unit tests for the real-camera QR pairing harness.
 *
 * Verifies that:
 * 1. InternetPairingTestHooks enforces strict filename whitelisting and debug/release source set separation.
 * 2. Release source set is a complete no-op with no file operations or hash calculations.
 * 3. Static inMemoryMarkerName is removed; restricted hooks synchronize via app-private sentinel.
 * 4. RealQrInternetPairingInstrumentedTest strictly avoids addMonitor, ActivityResult injection,
 *    direct onActivityResult, reflection on beginInternetPairing, or direct analyze/deliverResult.
 * 5. Harness wait loop does not catch Throwable to swallow security assertions.
 * 6. Espresso positive action verifies internetPairingAcceptanceErrorText instead of EditText.error.
 * 7. Marker file is retained in instrumentation finally for host runner consumption.
 * 8. QRScannerActivity keeps analyze and deliverResult private, checks isMarkerActive, and avoids hash/allocation when inactive.
 * 9. The real-camera harness is opt-in before its camera permission rule executes.
 */
class RealQrPairingStaticContractTest {

    @Test
    fun testHooksEnforceStrictFilenameWhitelist() {
        val allowed = InternetPairingTestHooks.ALLOWED_APP_PRIVATE_FILE_NAMES
        assertTrue(allowed.contains("internet_pairing_offer.txt"))
        assertTrue(allowed.contains("qr_scan_marker.json"))
        assertTrue(allowed.contains("qr_scan_marker_request.txt"))
        assertEquals(3, allowed.size)

        assertTrue(InternetPairingTestHooks.isWhitelistedFileName("internet_pairing_offer.txt"))
        assertTrue(InternetPairingTestHooks.isWhitelistedFileName("qr_scan_marker.json"))
        assertTrue(InternetPairingTestHooks.isWhitelistedFileName("qr_scan_marker_request.txt"))

        assertFalse(InternetPairingTestHooks.isWhitelistedFileName(null))
        assertFalse(InternetPairingTestHooks.isWhitelistedFileName(""))
        assertFalse(InternetPairingTestHooks.isWhitelistedFileName("arbitrary.txt"))
        assertFalse(InternetPairingTestHooks.isWhitelistedFileName("../internet_pairing_offer.txt"))
        assertFalse(InternetPairingTestHooks.isWhitelistedFileName("/data/data/dev.telemachus.display/files/offer.txt"))
        assertFalse(InternetPairingTestHooks.isWhitelistedFileName("internet_pairing_offer.txt.bak"))
        assertFalse(InternetPairingTestHooks.isWhitelistedFileName("internet_pairing_offer_2.txt"))
        assertFalse(InternetPairingTestHooks.isWhitelistedFileName("qr_scan_marker_2.json"))
    }

    @Test
    fun testHooksMarkerActiveContract() {
        assertTrue(InternetPairingTestHooks.isMarkerActive("qr_scan_marker.json"))
        assertTrue(InternetPairingTestHooks.isMarkerActive("internet_pairing_offer.txt"))
        assertTrue(InternetPairingTestHooks.isMarkerActive("qr_scan_marker_request.txt"))

        assertFalse(InternetPairingTestHooks.isMarkerActive(null))
        assertFalse(InternetPairingTestHooks.isMarkerActive(""))
        assertFalse(InternetPairingTestHooks.isMarkerActive("arbitrary.txt"))
        assertFalse(InternetPairingTestHooks.isMarkerActive("qr_scan_marker_2.json"))
    }

    @Test
    fun testHooksSha256HexConsistency() {
        val hash = InternetPairingTestHooks.sha256Hex("vibescreen://pair?v=1&o=test")
        assertEquals(64, hash.length)
        assertTrue(hash.all { it in '0'..'9' || it in 'a'..'f' })
    }

    @Test
    fun realQrHarnessStrictlyForbidsInjectionAndBypasses() {
        val rawContent = readSource("RealQrInternetPairingInstrumentedTest.kt")
        val codeOnly = stripComments(rawContent)

        assertFalse(
            "RealQrInternetPairingInstrumentedTest must not use addMonitor",
            codeOnly.contains("addMonitor"),
        )
        assertFalse(
            "RealQrInternetPairingInstrumentedTest must not inject ActivityResult",
            codeOnly.contains("Instrumentation.ActivityResult") || codeOnly.contains("ActivityResult("),
        )
        assertFalse(
            "RealQrInternetPairingInstrumentedTest must not invoke onActivityResult directly",
            codeOnly.contains(".onActivityResult(") || codeOnly.contains("onActivityResult("),
        )
        assertFalse(
            "RealQrInternetPairingInstrumentedTest must not invoke beginInternetPairing via reflection",
            codeOnly.contains("beginInternetPairing"),
        )
        assertFalse(
            "RealQrInternetPairingInstrumentedTest must not call analyze directly",
            codeOnly.contains(".analyze(") || codeOnly.contains("::analyze"),
        )
        assertFalse(
            "RealQrInternetPairingInstrumentedTest must not call deliverResult directly",
            codeOnly.contains(".deliverResult(") || codeOnly.contains(".deliverAcceptedResult("),
        )
        assertFalse(
            "RealQrInternetPairingInstrumentedTest must not catch Throwable in wait loop",
            codeOnly.contains("catch (_: Throwable)") || codeOnly.contains("catch (e: Throwable)"),
        )
        assertTrue(
            "RealQrInternetPairingInstrumentedTest must catch NoMatchingViewException in wait loop",
            codeOnly.contains("NoMatchingViewException"),
        )
        assertFalse(
            "RealQrInternetPairingInstrumentedTest must not check EditText.error",
            codeOnly.contains(".error ==") || codeOnly.contains(".error != null") || codeOnly.contains("EditText).error"),
        )
        assertTrue(
            "RealQrInternetPairingInstrumentedTest must check internetPairingAcceptanceErrorText",
            codeOnly.contains("R.id.internetPairingAcceptanceErrorText"),
        )
        assertFalse(
            "RealQrInternetPairingInstrumentedTest must not delete marker file in finally",
            extractFinallyBlock(rawContent).contains("deleteAppPrivateFile(context, markerFileName)"),
        )
        assertTrue(
            "RealQrInternetPairingInstrumentedTest must require an explicit instrumentation opt-in",
            codeOnly.contains("OPT_IN_ARGUMENT") && codeOnly.contains("assumeTrue("),
        )
        assertTrue(
            "The opt-in rule must run before the camera permission rule",
            codeOnly.contains("RuleChain.outerRule(optInRule).around(cameraPermission)"),
        )
    }

    @Test
    fun internetAcceptanceRestoresEspressoFailureHandler() {
        val codeOnly = stripComments(readSource("InternetMainActivityAcceptanceInstrumentedTest.kt"))

        assertTrue(
            "Internet UI/bootstrap acceptance must require an explicit instrumentation opt-in",
            codeOnly.contains("OPT_IN_ARGUMENT") && codeOnly.contains("assumeTrue("),
        )
        assertFalse(
            "Internet UI/bootstrap acceptance must not grant Camera for no-Host lease UX runs",
            codeOnly.contains("GrantPermissionRule") || codeOnly.contains("cameraPermission"),
        )
        assertTrue(
            "The opt-in rule must remain the outer acceptance rule",
            codeOnly.contains("RuleChain.outerRule(optInRule)"),
        )
        assertTrue(
            "Internet acceptance must restore Espresso's default failure handler after every test",
            codeOnly.contains("@After") &&
                codeOnly.contains("Espresso.setFailureHandler(DefaultFailureHandler(context))"),
        )
        assertTrue(
            "Internet acceptance must reset its diagnostic stage after every test",
            codeOnly.contains("acceptanceStage = \"initialization\""),
        )
        assertTrue(
            "Internet acceptance should prove rejected import drafts remain retryable",
            codeOnly.contains("importLeaseAfterRejectedDraft") &&
                codeOnly.contains("INVALID_LEASE_JSON") &&
                codeOnly.contains("expectDialogError = true") &&
                codeOnly.contains("Rejected draft must not persist a profile"),
        )
    }

    @Test
    fun internetImportDialogClearsRetryableErrorWhenUserEditsInput() {
        val importDialog = stripComments(extractMethod(readSource("MainActivity.kt"), "private fun showInternetProfileImportDialog"))

        assertTrue(
            "Internet profile import should expose one inline error updater for EditText and live-region state",
            importDialog.contains("fun updateImportError(message: CharSequence?)") &&
                importDialog.contains("input.error = message") &&
                importDialog.contains("LiveRegionTextApplier.hide(errorText)") &&
                importDialog.contains("LiveRegionTextApplier.show(errorText, message)"),
        )
        assertTrue(
            "Internet profile import should clear a rejected draft error as soon as the user changes the input",
            importDialog.contains("input.addTextChangedListener") &&
                importDialog.contains("override fun afterTextChanged") &&
                importDialog.contains("if (input.error != null || errorText.visibility == View.VISIBLE)") &&
                importDialog.contains("updateImportError(null)"),
        )
        assertTrue(
            "Visible import errors should scroll into the parent dialog viewport",
            importDialog.contains("errorText.post {") &&
                importDialog.contains("errorText.requestRectangleOnScreen") &&
                importDialog.contains("Rect(0, 0, errorText.width, errorText.height)"),
        )
    }

    @Test
    fun qrScannerActivityKeepsInternalMethodsPrivateAndRecordsMarker() {
        val rawContent = readSource("QRScannerActivity.kt")
        val codeOnly = stripComments(rawContent)

        assertTrue(
            "analyze method must be private",
            codeOnly.contains("private fun analyze(proxy: ImageProxy)"),
        )
        assertTrue(
            "deliverResult method must be private",
            codeOnly.contains("private fun deliverResult(raw: String)"),
        )
        assertTrue(
            "QRScannerActivity must invoke writeQrScanMarker upon successful decode",
            codeOnly.contains("InternetPairingTestHooks.writeQrScanMarker"),
        )
        assertTrue(
            "QRScannerActivity must check isMarkerActive before writing marker",
            codeOnly.contains("InternetPairingTestHooks.isMarkerActive"),
        )
        assertFalse(
            "QRScannerActivity must not reference activeMarkerName",
            codeOnly.contains("activeMarkerName"),
        )
        assertFalse(
            "QRScannerActivity must never log the raw QR payload",
            codeOnly.contains("Log.d(TAG, raw") ||
                codeOnly.contains("Log.i(TAG, raw") ||
                codeOnly.contains("Log.e(TAG, raw") ||
                codeOnly.contains("println(raw"),
        )
    }

    @Test
    fun testHooksEnforceDebugAndReleaseSeparation() {
        val mainFile = findSourceFile("app/src/main/java/dev/telemachus/display/InternetPairingTestHooks.kt")
        assertNull(
            "InternetPairingTestHooks.kt must NOT exist in src/main; it must be separated into debug/release source sets",
            mainFile,
        )

        val debugContent = stripComments(readSourceDirect("app/src/debug/java/dev/telemachus/display/InternetPairingTestHooks.kt"))
        val releaseContent = stripComments(readSourceDirect("app/src/release/java/dev/telemachus/display/InternetPairingTestHooks.kt"))

        // Neither source set may contain static in-memory marker
        assertFalse("debug source set must not have inMemoryMarkerName", debugContent.contains("inMemoryMarkerName"))
        assertFalse("release source set must not have inMemoryMarkerName", releaseContent.contains("inMemoryMarkerName"))
        assertFalse("debug source set must not have setActiveMarkerName", debugContent.contains("setActiveMarkerName"))
        assertFalse("release source set must not have setActiveMarkerName", releaseContent.contains("setActiveMarkerName"))

        // Release must be a complete no-op
        assertTrue("release source set must return false for isMarkerActive", releaseContent.contains("isMarkerActive(name: String?): Boolean = false"))
        assertTrue("release source set must return false for isWhitelistedFileName", releaseContent.contains("isWhitelistedFileName(name: String?): Boolean = false"))
        assertTrue("release source set must return null for consumeAppPrivateFileNameExtra", releaseContent.contains("): String? = null"))
        assertTrue("release source set must return empty string for sha256Hex", releaseContent.contains("sha256Hex(value: String): String = \"\""))
        assertFalse("release source set must not import java.io.File", releaseContent.contains("java.io.File"))
        assertFalse("release source set must not import java.io.FileOutputStream", releaseContent.contains("java.io.FileOutputStream"))
        assertFalse("release source set must not import org.json.JSONObject", releaseContent.contains("org.json.JSONObject"))

        // Debug must have active implementations
        assertTrue("debug source set must implement isMarkerActive", debugContent.contains("isMarkerActive"))
        assertTrue("debug source set must implement attachQrScanMarkerExtra", debugContent.contains("attachQrScanMarkerExtra"))
        assertTrue("debug source set must implement writeQrScanMarker", debugContent.contains("writeQrScanMarker"))
    }

    @Test
    fun mainActivityLaunchesScannerWithRestrictedHook() {
        val rawContent = readSource("MainActivity.kt")
        val codeOnly = stripComments(rawContent)

        assertTrue(
            "MainActivity must call attachQrScanMarkerExtra in launchInternetScanner",
            codeOnly.contains("InternetPairingTestHooks.attachQrScanMarkerExtra(this, intent)"),
        )
        assertFalse(
            "MainActivity must not use inMemoryMarkerName",
            codeOnly.contains("inMemoryMarkerName"),
        )
    }

    private fun stripComments(source: String): String {
        return source
            .lines()
            .filterNot {
                val trimmed = it.trim()
                trimmed.startsWith("//") || trimmed.startsWith("/*") || trimmed.startsWith("*") || trimmed.endsWith("*/")
            }.joinToString("\n")
    }

    private fun extractMethod(source: String, signature: String): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Method not found: $signature" }
        var index = start
        var braceDepth = 0
        var inString = false
        var escaped = false
        var methodStarted = false
        while (index < source.length) {
            val current = source[index]
            when {
                inString -> {
                    if (escaped) {
                        escaped = false
                    } else if (current == '\\') {
                        escaped = true
                    } else if (current == '"') {
                        inString = false
                    }
                    index++
                }
                current == '"' -> {
                    inString = true
                    index++
                }
                current == '{' -> {
                    methodStarted = true
                    braceDepth++
                    index++
                }
                current == '}' -> {
                    braceDepth--
                    if (methodStarted && braceDepth == 0) return source.substring(start, index + 1)
                    index++
                }
                else -> index++
            }
        }
        error("Closing brace not found for $signature")
    }

    private fun extractFinallyBlock(source: String): String {
        val finallyIndex = source.lastIndexOf("finally {")
        if (finallyIndex == -1) return ""
        return source.substring(finallyIndex)
    }

    private fun findSourceFile(subpath: String): File? {
        val candidates = listOf(
            subpath,
            "app/" + subpath.removePrefix("app/"),
            "baseline/AndroidClient/" + subpath,
            "baseline/AndroidClient/app/" + subpath.removePrefix("app/")
        )
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            candidates
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        return null
    }

    private fun readSourceDirect(subpath: String): String {
        val file = findSourceFile(subpath)
            ?: error(subpath + " not found from " + System.getProperty("user.dir"))
        return file.readText(Charsets.UTF_8)
    }

    private fun readSource(name: String): String {
        val relativePaths = listOf(
            "app/src/main/java/dev/telemachus/display/" + name,
            "app/src/androidTest/java/dev/telemachus/display/" + name,
            "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/" + name,
            "baseline/AndroidClient/app/src/androidTest/java/dev/telemachus/display/" + name
        )
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            relativePaths
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText(Charsets.UTF_8) }
            current = current.parentFile?.canonicalFile ?: current
        }
        error(name + " not found from " + System.getProperty("user.dir"))
    }
}
