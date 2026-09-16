package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class InternetCameraPermissionRecoveryInstrumentationContractTest {
    @Test
    fun permissionRevocationRunsAfterInstrumentationFromTheHostSideTarget() {
        val instrumentation = repositoryFile(INSTRUMENTATION_PATH).readText()
        val makefile = repositoryFile("Makefile").readText()
        val target = makefile.substringAfter("baseline-android-camera-recovery-device-test:")
            .substringBefore("\nbaseline-android-protocol-side-effect-owner:")

        assertFalse(
            "Revoking Camera inside the instrumentation process kills that process on Android 16",
            instrumentation.contains("pm revoke"),
        )
        assertTrue(
            "The host-side target must clean up even when Gradle or instrumentation fails",
            target.contains("trap cleanup EXIT INT TERM") &&
                target.contains("shell pm revoke \"${'$'}${'$'}package\" android.permission.CAMERA") &&
                target.contains("uninstall \"${'$'}${'$'}test_package\"") &&
                target.contains("uninstall \"${'$'}${'$'}package\""),
        )
        assertTrue(
            "The target must refuse to replace an existing app or test package",
            target.contains("test \"${'$'}${'$'}app_was_installed\" = 0") &&
                target.contains("refusing to replace or erase existing app data") &&
                target.contains("test \"${'$'}${'$'}test_was_installed\" = 0"),
        )
        assertTrue(
            "The focused run must stay explicitly opt-in and serial-scoped",
            target.contains("ANDROID_SERIAL=\"${'$'}${'$'}serial\"") &&
                target.contains("vibeScreenInternetCameraRecovery=true"),
        )
    }

    private fun repositoryFile(relativePath: String): File {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            current.resolve(relativePath).takeIf(File::isFile)?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("$relativePath not found from ${System.getProperty("user.dir")}")
    }

    private companion object {
        const val INSTRUMENTATION_PATH =
            "baseline/AndroidClient/app/src/androidTest/java/dev/telemachus/display/" +
                "InternetCameraPermissionRecoveryInstrumentedTest.kt"
    }
}
