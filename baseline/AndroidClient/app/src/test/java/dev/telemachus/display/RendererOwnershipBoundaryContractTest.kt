package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RendererOwnershipBoundaryContractTest {
    @Test
    fun `renderer owners are installed as focused boundary sources`() {
        assertTrue(source(RENDERER_VIEWPORT_STATE).isNotBlank())
        assertTrue(source(RENDERER_OWNER).isNotBlank())
        assertTrue(source(RENDERER_VIEWPORT_STATE_TEST).isNotBlank())
        assertTrue(source(RENDERER_OWNER_TEST).isNotBlank())
    }

    @Test
    fun `renderer owners stay independent from android ui protocol transport and decoder layers`() {
        val owners = listOf(RENDERER_VIEWPORT_STATE, RENDERER_OWNER).joinToString("\n") { source(it) }

        FORBIDDEN_IMPORT_OR_TYPE_REFERENCES.forEach { reference ->
            assertFalse(
                "Renderer owners must not depend on `$reference`",
                owners.contains(reference),
            )
        }
    }

    @Test
    fun `main activity routes renderer state and frame admission through renderer owner`() {
        val activity = source(MAIN_ACTIVITY)

        assertTrue(activity.contains("RendererOwner("))
        assertTrue(activity.contains("rendererOwner.updateViewportParent"))
        assertTrue(activity.contains("rendererOwner.localFrameDecision"))
        assertTrue(activity.contains("rendererOwner.internetFrameDecision"))
        assertTrue(activity.contains("rendererOwner.publishRenderTarget"))
        assertTrue(activity.contains("rendererOwner.invalidateRenderTarget"))
        assertFalse(activity.contains("private val rendererViewportState"))
        assertFalse(activity.contains("private val surfaceGeneration"))
        assertFalse(activity.contains("@Volatile private var activeDecoderConfigEpoch"))
        assertFalse(activity.contains("activeDecoderConfigEpoch = 0L"))
        assertFalse(activity.contains("surfaceGeneration.get()"))
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
        const val RENDERER_OWNER =
            "app/src/main/java/dev/telemachus/display/RendererOwner.kt"
        const val RENDERER_VIEWPORT_STATE_TEST =
            "app/src/test/java/dev/telemachus/display/RendererViewportStateTest.kt"
        const val RENDERER_OWNER_TEST =
            "app/src/test/java/dev/telemachus/display/RendererOwnerTest.kt"
        const val MAIN_ACTIVITY =
            "app/src/main/java/dev/telemachus/display/MainActivity.kt"
        val FORBIDDEN_IMPORT_OR_TYPE_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
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
