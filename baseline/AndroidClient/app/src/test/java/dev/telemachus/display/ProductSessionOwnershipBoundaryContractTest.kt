package dev.telemachus.display

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class ProductSessionOwnershipBoundaryContractTest {
    @Test
    fun `product session coordinator is installed with focused tests`() {
        assertTrue(source(PRODUCT_SESSION_COORDINATOR).isNotBlank())
        assertTrue(source(PRODUCT_SESSION_COORDINATOR_TEST).isNotBlank())
    }

    @Test
    fun `product session coordinator stays out of android transport protocol side effect and decoder layers`() {
        val coordinator = source(PRODUCT_SESSION_COORDINATOR)

        FORBIDDEN_COORDINATOR_REFERENCES.forEach { reference ->
            assertFalse(
                "ProductSessionCoordinator must not depend on `$reference`",
                coordinator.contains(reference),
            )
        }
    }

    @Test
    fun `main activity routes local product session state through coordinator`() {
        val source = source(MAIN_ACTIVITY)

        assertTrue(source.contains("private val productSessionCoordinator = ProductSessionCoordinator<StreamClient>()"))
        assertTrue(source.contains("productSessionCoordinator.activate(client)"))
        assertTrue(source.contains("productSessionCoordinator.accepts(client, generation)"))
        assertTrue(source.contains("productSessionCoordinator.currentBinding()"))
        assertTrue(source.contains("productSessionCoordinator.updateNegotiatedSession(client, generation, binding)"))
        assertTrue(source.contains("productSessionCoordinator.invalidate(client, generation)"))
        assertTrue(source.contains("productSessionCoordinator.onConnectionStatus(callbackClient, callbackGeneration, connected)"))
        assertTrue(source.contains("productSessionCoordinator.requestDisplaySelection(option.id)"))
        assertTrue(source.contains("productSessionCoordinator.requestHostAction(actionId)"))

        listOf(
            "private val sessionState = SessionState<StreamClient>()",
            "private var availableDisplays = emptyList<StreamDisplayOption>()",
            "private var selectedDisplayId = \"\"",
            "private var pendingDisplaySelectionId: String? = null",
            "private var availableHostActions = emptyList<HostActionOption>()",
            "sessionState.activate(client)",
            "sessionState.accepts(client, generation)",
            "sessionState.updateNegotiatedSession(client, generation, binding)",
            "sessionState.invalidate(client, generation)",
        ).forEach { reference ->
            assertFalse("MainActivity must not keep local product-session state path `$reference`", source.contains(reference))
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
        const val MAIN_ACTIVITY = "app/src/main/java/dev/telemachus/display/MainActivity.kt"
        const val PRODUCT_SESSION_COORDINATOR =
            "app/src/main/java/dev/telemachus/display/ProductSessionCoordinator.kt"
        const val PRODUCT_SESSION_COORDINATOR_TEST =
            "app/src/test/java/dev/telemachus/display/ProductSessionCoordinatorTest.kt"

        val FORBIDDEN_COORDINATOR_REFERENCES =
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
                "WakeHostPacketSender",
                "DataInputStream",
                "DataOutputStream",
            )
    }
}
