package dev.telemachus.display

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class StreamInputBoundaryContractTest {
    @Test
    fun `stream client delegates input envelope routing to dispatcher`() {
        val streamClient = source(PRODUCTION_STREAM_CLIENT)
        val inputDispatcher = source(PRODUCTION_INPUT_DISPATCHER)

        assertTrue(streamClient.contains("private val inputDispatcher ="))
        assertTrue(streamClient.contains("= inputDispatcher.sendTouch("))
        assertTrue(streamClient.contains("= inputDispatcher.sendMotionTouch("))
        assertTrue(streamClient.contains("inputDispatcher.sendMotionStylus(samples)"))
        assertTrue(streamClient.contains("inputDispatcher.sendPointer("))
        assertTrue(streamClient.contains("inputDispatcher.sendScroll("))
        assertTrue(streamClient.contains("inputDispatcher.sendKey("))
        assertTrue(streamClient.contains("inputDispatcher.sendNativeInputRelease("))
        assertTrue(streamClient.contains("inputDispatcher.sendController("))

        INPUT_ENVELOPE_BUILDERS.forEach { builder ->
            assertFalse("StreamClient must not build input envelope `$builder` directly", streamClient.contains(builder))
            assertTrue("StreamInputDispatcher should own input envelope `$builder`", inputDispatcher.contains(builder))
        }
        assertFalse(
            "StreamClient must not own native release envelope batching",
            streamClient.contains("NativeInputReleaseBatch.build("),
        )
        assertTrue(inputDispatcher.contains("NativeInputReleaseBatch.build("))
    }

    @Test
    fun `input dispatcher stays independent from android ui and transport ownership`() {
        val inputDispatcher = source(PRODUCTION_INPUT_DISPATCHER)

        FORBIDDEN_INPUT_DISPATCHER_REFERENCES.forEach { reference ->
            assertFalse("StreamInputDispatcher must not depend on `$reference`", inputDispatcher.contains(reference))
        }
    }

    private fun source(relativePath: String): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            listOf(relativePath, "baseline/AndroidClient/$relativePath")
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("$relativePath not found from " + System.getProperty("user.dir"))
    }

    private companion object {
        const val PRODUCTION_STREAM_CLIENT = "app/src/main/java/dev/telemachus/display/StreamClient.kt"
        const val PRODUCTION_INPUT_DISPATCHER = "app/src/main/java/dev/telemachus/display/StreamInputDispatcher.kt"

        val INPUT_ENVELOPE_BUILDERS =
            listOf(
                "activeSession.touch(",
                "activeSession.stylus(",
                "activeSession.pointer(",
                "activeSession.scroll(",
                "activeSession.key(",
                "activeSession.controller(",
            )

        val FORBIDDEN_INPUT_DISPATCHER_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
                "StreamTransport",
                "java.net.Socket",
            )
    }
}
