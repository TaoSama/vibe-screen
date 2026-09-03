package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Ownership boundary contract for the Android decoder configuration flow.
 *
 * MainActivity must remain a platform adapter: it supplies Surface/Display
 * objects and UI side effects, but all decoder admission, stale-session and
 * stale-configuration gating, decoder creation, startup commit, and
 * structural-failure recording are owned by
 * [AndroidDecoderConfigurationCoordinator] together with
 * [AndroidDecoderLifecycleOwner] and [DecoderPresentationOwner].
 */
class DecoderOwnershipBoundaryContractTest {
    @Test
    fun `decoder owner sources are present`() {
        assertTrue(source(COORDINATOR).isNotBlank())
        assertTrue(source(LIFECYCLE_OWNER).isNotBlank())
        assertTrue(source(PRESENTATION_OWNER).isNotBlank())
        assertTrue(source(COORDINATOR_TEST).isNotBlank())
        assertTrue(source(LIFECYCLE_OWNER_TEST).isNotBlank())
    }

    @Test
    fun `decoder owners stay independent of android ui transport codec and session layers`() {
        val owners =
            listOf(COORDINATOR, LIFECYCLE_OWNER, PRESENTATION_OWNER)
                .joinToString("\n") { source(it) }

        FORBIDDEN_OWNER_REFERENCES.forEach { reference ->
            assertFalse(
                "Decoder owners must not depend on `$reference`",
                owners.contains(reference),
            )
        }
    }

    @Test
    fun `main activity routes local and internet decoder configuration through the coordinator`() {
        val activity = source(MAIN_ACTIVITY)

        assertTrue(activity.contains("decoderConfigurationCoordinator.configureLocal("))
        assertTrue(activity.contains("decoderConfigurationCoordinator.configureInternet("))
        assertTrue(activity.contains("AndroidDecoderConfigurationCoordinator<VideoDecoder, ProductVideoConfiguration>("))
    }

    @Test
    fun `main activity does not reclaim decoder lifecycle owner internals`() {
        val activity = source(MAIN_ACTIVITY)

        FORBIDDEN_MAIN_ACTIVITY_LIFECYCLE_OWNER_CALLS.forEach { call ->
            assertFalse(
                "MainActivity must route `$call` through AndroidDecoderConfigurationCoordinator",
                activity.contains(call),
            )
        }

        assertFalse(
            "MainActivity must not instantiate AndroidDecoderLifecycleOwner directly",
            activity.contains("AndroidDecoderLifecycleOwner("),
        )
    }

    @Test
    fun `createConfiguredDecoder accepts DecoderCreationCallbacks instead of attempt and lifecycle owner`() {
        val activity = source(MAIN_ACTIVITY)

        assertTrue(activity.contains("callbacks: DecoderCreationCallbacks<VideoDecoder>"))
        assertFalse(activity.contains("attempt: DecoderLifecycleAttempt"))
        assertFalse(activity.contains("decoderLifecycleOwner: AndroidDecoderLifecycleOwner"))
    }

    @Test
    fun `video decoder does not own resolution reconfiguration`() {
        val decoder = source(VIDEO_DECODER)

        assertFalse(
            "VideoDecoder must not recreate MediaCodec for resolution changes; route reconfiguration through AndroidDecoderConfigurationCoordinator",
            decoder.contains("fun updateResolution("),
        )
        assertFalse(
            "VideoDecoder must not request resolution-change keyframes from an internal reconfiguration path",
            decoder.contains("resolution changed"),
        )
    }

    @Test
    fun `local and internet codec failure actions do not record structural failures directly`() {
        val activity = source(MAIN_ACTIVITY)

        assertFalse(
            "MainActivity must not call recordActiveStructuralFailure directly; it is owned by DecoderCreationCallbacks",
            activity.contains("recordActiveStructuralFailure"),
        )
    }

    @Test
    fun `coordinator owns local and internet lifecycle owner construction`() {
        val coordinator = source(COORDINATOR)

        assertTrue(coordinator.contains("AndroidDecoderLifecycleOwner("))
        assertTrue(coordinator.contains("configureLocal("))
        assertTrue(coordinator.contains("configureInternet("))
        assertTrue(coordinator.contains("localLifecycleOwner("))
        assertTrue(coordinator.contains("internetLifecycleOwner("))
    }

    @Test
    fun `coordinator creation callbacks gate runtime callbacks through the active decoder binding`() {
        val coordinator = source(COORDINATOR)

        assertTrue(coordinator.contains("class DecoderCreationCallbacks"))
        assertTrue(coordinator.contains("fun onKeyframeRequired("))
        assertTrue(coordinator.contains("fun onCodecFailure("))
        assertTrue(coordinator.contains("lifecycleOwner.runIfActive("))
        assertTrue(coordinator.contains("lifecycleOwner.recordActiveStructuralFailure("))
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
        const val COORDINATOR =
            "app/src/main/java/dev/telemachus/display/AndroidDecoderConfigurationCoordinator.kt"
        const val LIFECYCLE_OWNER =
            "app/src/main/java/dev/telemachus/display/AndroidDecoderLifecycleOwner.kt"
        const val PRESENTATION_OWNER =
            "app/src/main/java/dev/telemachus/display/DecoderPresentationOwner.kt"
        const val COORDINATOR_TEST =
            "app/src/test/java/dev/telemachus/display/AndroidDecoderConfigurationCoordinatorTest.kt"
        const val LIFECYCLE_OWNER_TEST =
            "app/src/test/java/dev/telemachus/display/AndroidDecoderLifecycleOwnerTest.kt"
        const val MAIN_ACTIVITY =
            "app/src/main/java/dev/telemachus/display/MainActivity.kt"
        const val VIDEO_DECODER =
            "app/src/main/java/dev/telemachus/display/VideoDecoder.kt"

        val FORBIDDEN_OWNER_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
                "StreamTransportOwner",
                "SocketStreamTransportConnection",
                "java.net.Socket",
                "VideoDecoder",
                "MediaCodec",
                "StreamProtocolSideEffectOwner",
                "ProtocolV1Session",
                "InternetProductSession",
                "StreamClient",
            )

        val FORBIDDEN_MAIN_ACTIVITY_LIFECYCLE_OWNER_CALLS =
            listOf(
                ".admitAttempt(",
                ".commitCreatedDecoder(",
                ".handleCreationFailure(",
                ".runIfActive(",
                ".recordActiveStructuralFailure(",
            )
    }
}
