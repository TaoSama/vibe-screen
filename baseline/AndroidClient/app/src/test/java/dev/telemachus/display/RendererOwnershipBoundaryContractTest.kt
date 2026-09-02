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
        val owners = listOf(RENDERER_VIEWPORT_STATE, RENDERER_OWNER, DECODER_PRESENTATION_OWNER).joinToString("\n") { source(it) }

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
        val decoderPresentationOwner = source(DECODER_PRESENTATION_OWNER)

        assertTrue(activity.contains("RendererOwner("))
        assertTrue(activity.contains("rendererOwner.updateViewportParent"))
        assertTrue(activity.contains("rendererOwner.mapTouchPoint"))
        assertTrue(activity.contains("rendererOwner.rotationPolicy"))
        assertTrue(activity.contains("DecoderPresentationOwner<VideoDecoder, ProductVideoConfiguration>"))
        assertTrue(activity.contains("decoderPresentationOwner.routeLocalFrame"))
        assertTrue(activity.contains("decoderPresentationOwner.routeInternetFrame"))
        assertTrue(activity.contains("decoderPresentationOwner.publishRenderTarget"))
        assertTrue(activity.contains("decoderPresentationOwner.invalidateRenderTarget"))
        assertTrue(decoderPresentationOwner.contains("rendererOwner.localFrameDecision"))
        assertTrue(decoderPresentationOwner.contains("rendererOwner.internetFrameDecision"))
        assertTrue(decoderPresentationOwner.contains("rendererOwner.publishRenderTarget"))
        assertTrue(decoderPresentationOwner.contains("rendererOwner.invalidateRenderTarget"))
        assertTrue(activity.contains("rendererOwner.renderTargetReadyAction"))
        FORBIDDEN_MAIN_ACTIVITY_RENDERER_OWNER_CALLS.forEach { call ->
            assertFalse(
                "MainActivity must route `$call` through DecoderPresentationOwner",
                activity.contains(call),
            )
        }
        FORBIDDEN_MAIN_ACTIVITY_VIEWPORT_POLICY_CALLS.forEach { call ->
            assertFalse(
                "MainActivity must route viewport policy `$call` through RendererOwner",
                activity.contains(call),
            )
        }
        assertFalse(activity.contains("private val rendererViewportState"))
        assertFalse(activity.contains("private val surfaceGeneration"))
        assertFalse(activity.contains("private val videoDecoder"))
        assertFalse(activity.contains("private var videoDecoder"))
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
        const val DECODER_PRESENTATION_OWNER =
            "app/src/main/java/dev/telemachus/display/DecoderPresentationOwner.kt"
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
        val FORBIDDEN_MAIN_ACTIVITY_RENDERER_OWNER_CALLS =
            listOf(
                "rendererOwner.publishRenderTarget",
                "rendererOwner.invalidateRenderTarget",
                "rendererOwner.snapshotRenderTarget",
                "rendererOwner.acceptsRenderTarget",
                "rendererOwner.commitDecoderPresentation",
                "rendererOwner.installDecoderPresentation",
                "rendererOwner.clearDecoderPresentation",
                "rendererOwner.updateDisplayGeometry",
                "rendererOwner.clearDisplayGeometry",
                "rendererOwner.localFrameDecision",
                "rendererOwner.internetFrameDecision",
            )
        val FORBIDDEN_MAIN_ACTIVITY_VIEWPORT_POLICY_CALLS =
            listOf(
                "TouchMapper" + ".map",
                "InternetTouchMapper" + ".map",
                "ViewportPolicy" + ".effectiveRotation",
                "ViewportPolicy" + ".screenOrientationFor",
                "ViewportPolicy" + ".surfaceTransformRotation",
            )
    }
}
