package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class CameraPermissionManagerContractTest {
    @Test
    fun recordsRequestedStateBeforeLaunchingSystemPermissionRequest() {
        val source = sourceFile().readText()
        val request =
            source
                .substringAfter("override fun request(requestCode: Int)")
                .substringBefore("override fun openAppSettings")

        val markIndex = request.indexOf("markRequested(activity)")
        val systemRequestIndex = request.indexOf("ActivityCompat.requestPermissions")
        assertTrue("Camera request state must be recorded", markIndex >= 0)
        assertTrue("Camera permission must use Android's runtime permission API", systemRequestIndex >= 0)
        assertTrue("Camera request state must be visible before a synchronous permission callback", markIndex < systemRequestIndex)
    }

    private fun sourceFile(): File {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            PATHS.map(current::resolve).firstOrNull(File::isFile)?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("CameraPermissionManager.kt not found from ${System.getProperty("user.dir")}")
    }

    private companion object {
        val PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/CameraPermissionManager.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/CameraPermissionManager.kt",
            )
    }
}
