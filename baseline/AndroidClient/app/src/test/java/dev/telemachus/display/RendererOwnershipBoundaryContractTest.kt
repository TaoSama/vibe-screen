package dev.telemachus.display

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class RendererOwnershipBoundaryContractTest {
    @Test
    fun `renderer viewport owner is installed as focused boundary source`() {
        assertTrue(source(RENDERER_VIEWPORT_STATE).isNotBlank())
        assertTrue(source(RENDERER_VIEWPORT_STATE_TEST).isNotBlank())
    }

    @Test
    fun `renderer viewport owner stays independent from android ui protocol transport and decoder layers`() {
        val owner = source(RENDERER_VIEWPORT_STATE)

        FORBIDDEN_IMPORT_OR_TYPE_REFERENCES.forEach { reference ->
            assertFalse(
                "RendererViewportState must not depend on `$reference`",
                owner.contains(Regex("\\b${Regex.escape(reference)}\\b")),
            )
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
        const val RENDERER_VIEWPORT_STATE =
            "app/src/main/java/dev/telemachus/display/RendererViewportState.kt"
        const val RENDERER_VIEWPORT_STATE_TEST =
            "app/src/test/java/dev/telemachus/display/RendererViewportStateTest.kt"
        val FORBIDDEN_IMPORT_OR_TYPE_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "StreamTransportOwner",
                "SocketStreamTransportConnection",
                "java.net.Socket",
                "VideoDecoder",
                "MediaCodec",
                "ProtocolV1Session",
                "StreamProtocolSideEffectOwner",
                "InternetProductSession",
            )
    }
}
