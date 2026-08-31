package dev.telemachus.display

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class StreamClientOwnershipBoundaryContractTest {
    @Test
    fun `current base keeps StreamClient delegated ownership boundaries installed`() {
        val streamClient = source(PRODUCTION_STREAM_CLIENT)

        REQUIRED_BOUNDARY_OWNERS.forEach { owner ->
            assertTrue("Missing extracted owner source `$owner`", source(owner).isNotBlank())
        }
        REQUIRED_OWNER_TESTS.forEach { test ->
            assertTrue("Missing focused owner test `$test`", source(test).isNotBlank())
        }
        REQUIRED_STREAM_CLIENT_DELEGATIONS.forEach { delegation ->
            assertTrue("StreamClient no longer delegates through `$delegation`", streamClient.contains(delegation))
        }
    }

    @Test
    fun `stream client does not reclaim extracted owner internals`() {
        val streamClient = source(PRODUCTION_STREAM_CLIENT)

        FORBIDDEN_STREAM_CLIENT_RECLAIMED_INTERNALS.forEach { reference ->
            assertFalse("StreamClient must not reclaim extracted owner internal `$reference`", streamClient.contains(reference))
        }
    }

    @Test
    fun `stream client termination keeps session through outbound drain`() {
        val streamClient = source(PRODUCTION_STREAM_CLIENT)
        val terminationClaim = streamClient.indexOf("protocolSessionOwner.clearSideEffectAdmission()")
        val gracefulDrain = streamClient.indexOf("outboundScheduler.shutdownGracefully(OUTBOUND_DRAIN_TIMEOUT_MS)")
        val protocolCleanup = streamClient.indexOf("protocolSessionOwner.clear()")

        assertTrue("termination must close side-effect admission", terminationClaim >= 0)
        assertTrue("cleanup must gracefully drain accepted outbound commands", gracefulDrain >= 0)
        assertTrue("cleanup must clear the protocol session", protocolCleanup >= 0)
        assertTrue(
            "side-effect admission must close before accepted outbound commands drain",
            terminationClaim < gracefulDrain,
        )
        assertTrue(
            "protocol session must stay available until accepted outbound commands drain",
            gracefulDrain < protocolCleanup,
        )
    }

    @Test
    fun `extracted owners stay out of android ui transport socket and decoder layers`() {
        BOUNDARY_OWNER_RULES.forEach { rule ->
            val ownerSource = source(rule.path)
            rule.forbiddenReferences.forEach { reference ->
                assertFalse("${rule.name} must not depend on `$reference`", ownerSource.contains(reference))
            }
        }
    }

    @Test
    fun `phase zero docs identify current base ownership gate without closing open module work`() {
        val readme = repositorySource(REPOSITORY_README)
        val audit = repositorySource(OPEN_GATES_AUDIT)
        val phaseZeroTech = repositorySource(PHASE_ZERO_TECH)

        val phaseZeroStatus = readme.normalizedWhitespace()
        listOf(
            "standalone JVM transport",
            "local product-session lifecycle state",
            "Protocol v1",
            "action dispatch",
            "side-effect owner",
            "file-transfer product state",
            "input envelope routing",
            "media-frame routing",
        ).forEach { phrase ->
            assertTrue("README Phase 0 status missing current-base ownership phrase `$phrase`", phaseZeroStatus.contains(phrase))
        }
        assertTrue(readme.normalizedWhitespace().contains("wake-host product ownership"))
        assertFalse(readme.normalizedWhitespace().contains("broader protocol/session ownership"))
        assertTrue(audit.contains("#259"))
        assertTrue(audit.contains("current-base owner gate"))
        assertTrue(audit.contains("Module extraction draft PRs [#211]"))
        assertTrue(audit.contains("superseded by [#259]"))
        assertTrue(audit.contains("Remaining module gaps include wake-host product ownership"))
        assertTrue(phaseZeroTech.contains("side-effect owner gates file-transfer and WakeHost"))
        assertTrue(phaseZeroTech.contains("WakeHost product, decoder, renderer, and UI ownership"))
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

    private fun repositorySource(relativePath: String): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            if (current.resolve("docs/changes/2026-08-04-phase-0-baseline/TECH.md").isFile &&
                current.resolve("baseline/AndroidClient").isDirectory
            ) {
                return current.resolve(relativePath).readText()
            }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("repository root not found from " + System.getProperty("user.dir"))
    }

    private fun String.normalizedWhitespace(): String =
        split(32.toChar(), 9.toChar(), 10.toChar(), 13.toChar())
            .filter(String::isNotEmpty)
            .joinToString(" ")

    private data class BoundaryOwnerRule(
        val name: String,
        val path: String,
        val forbiddenReferences: List<String>,
    )

    private companion object {
        const val REPOSITORY_README = "README.md"
        const val OPEN_GATES_AUDIT = "docs/changes/2026-08-22-open-gates-coverage-audit/README.md"
        const val PHASE_ZERO_TECH = "docs/changes/2026-08-04-phase-0-baseline/TECH.md"

        const val PRODUCTION_STREAM_CLIENT = "app/src/main/java/dev/telemachus/display/StreamClient.kt"
        const val PRODUCTION_INPUT_DISPATCHER = "app/src/main/java/dev/telemachus/display/StreamInputDispatcher.kt"
        const val PRODUCTION_LOCAL_SESSION_STATE =
            "app/src/main/java/dev/telemachus/display/StreamClientLocalSessionState.kt"
        const val PRODUCTION_PROTOCOL_ACTION_DISPATCHER =
            "app/src/main/java/dev/telemachus/display/StreamProtocolActionDispatcher.kt"
        const val PRODUCTION_MEDIA_FRAME_ROUTER =
            "app/src/main/java/dev/telemachus/display/StreamMediaFrameRouter.kt"
        const val PRODUCTION_PROTOCOL_SIDE_EFFECT_OWNER =
            "app/src/main/java/dev/telemachus/display/StreamProtocolSideEffectOwner.kt"
        const val PRODUCTION_PROTOCOL_SESSION_OWNER =
            "app/src/main/java/dev/telemachus/display/StreamProtocolSessionOwner.kt"
        const val PRODUCTION_FILE_TRANSFER_PRODUCT_OWNER =
            "app/src/main/java/dev/telemachus/display/FileTransferProductOwner.kt"

        val REQUIRED_BOUNDARY_OWNERS =
            listOf(
                PRODUCTION_LOCAL_SESSION_STATE,
                PRODUCTION_INPUT_DISPATCHER,
                PRODUCTION_PROTOCOL_ACTION_DISPATCHER,
                PRODUCTION_MEDIA_FRAME_ROUTER,
                PRODUCTION_PROTOCOL_SIDE_EFFECT_OWNER,
                PRODUCTION_PROTOCOL_SESSION_OWNER,
                PRODUCTION_FILE_TRANSFER_PRODUCT_OWNER,
            )

        val REQUIRED_OWNER_TESTS =
            listOf(
                "app/src/test/java/dev/telemachus/display/StreamClientLocalSessionStateTest.kt",
                "app/src/test/java/dev/telemachus/display/StreamInputDispatcherTest.kt",
                "app/src/test/java/dev/telemachus/display/StreamProtocolActionDispatcherTest.kt",
                "app/src/test/java/dev/telemachus/display/StreamProtocolSideEffectOwnerTest.kt",
                "app/src/test/java/dev/telemachus/display/FileTransferProductOwnerTest.kt",
                "app/src/test/java/dev/telemachus/display/StreamMediaFrameRouterTest.kt",
                "app/src/test/java/dev/telemachus/display/StreamInputBoundaryContractTest.kt",
                "app/src/test/java/dev/telemachus/display/StreamProtocolSessionOwnerTest.kt",
            )

        val REQUIRED_STREAM_CLIENT_DELEGATIONS =
            listOf(
                "private val protocolSessionOwner = StreamProtocolSessionOwner",
                "private val inputDispatcher =",
                "private val protocolActionDispatcher =",
                "StreamProtocolActionDispatcher(StreamProtocolActionSink())",
                "private val mediaFrameRouter =",
                "private val fileTransferProductOwner =",
                "FileTransferProductOwner(",
                "protocolSessionOwner.isCurrent(",
                "protocolSessionOwner.retainsSession(",
                "protocolSessionOwner.runIfCurrent(",
                "protocolSessionOwner.trackFileOffer(",
                "protocolSessionOwner.claimFileOffer(",
                "protocolSessionOwner.releaseFileOffer(",
                "protocolSessionOwner.clearFileOffers(",
                "protocolSessionOwner.trackWakeHostRequest(",
                "protocolSessionOwner.activate(",
                "protocolSessionOwner.deactivate()",
                "protocolSessionOwner.clearSideEffectAdmission()",
                "protocolSessionOwner.clear()",
                "fileTransferProductOwner.receiveIncomingChunk(",
                "fileTransferProductOwner.decideFileOffer(",
                "fileTransferProductOwner.prepareOutgoingFile(",
                "fileTransferProductOwner.handleFileAccept(",
                "mediaFrameRouter.receiveLegacyFrame(",
                "mediaFrameRouter.receiveProtocolFrame(",
            )

        val FORBIDDEN_STREAM_CLIENT_RECLAIMED_INTERNALS =
            listOf(
                "val reconnectBackoff",
                "var isConnected",
                "@Volatile private var sessionReady",
                "private val bufferPool",
                "private val poolLock",
                "private fun acquireBuffer",
                "private fun updateStats",
                "private fun checkKeyframeFreshness",
                "internal fun isSyncFrame",
                "NativeInputReleaseBatch.build(",
                "ProtocolV1Framing.decodeVideo(",
                "private val pendingInboundWakeHostRequests",
                "private fun trackInboundWakeHostRequest",
                "IncomingFileTransferManager(",
                "ConcurrentHashMap<ByteString, OutgoingFileTransfer>",
                "private var remoteManagedPolicy",
                "private val outgoingFileTransfers",
            )

        val OWNER_LAYER_FORBIDDEN_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
                "StreamTransportOwner",
                "SocketStreamTransportConnection",
                "java.net.Socket",
                "VideoDecoder",
                "MediaCodec",
            )

        val BOUNDARY_OWNER_RULES =
            listOf(
                BoundaryOwnerRule(
                    name = "StreamClientLocalSessionState",
                    path = PRODUCTION_LOCAL_SESSION_STATE,
                    forbiddenReferences = OWNER_LAYER_FORBIDDEN_REFERENCES +
                        listOf(
                            "ProtocolV1Session",
                            "OutboundCommandScheduler",
                            "StreamOutboundCommand",
                            "DataInputStream",
                            "DataOutputStream",
                        ),
                ),
                BoundaryOwnerRule(
                    name = "StreamInputDispatcher",
                    path = PRODUCTION_INPUT_DISPATCHER,
                    forbiddenReferences = OWNER_LAYER_FORBIDDEN_REFERENCES +
                        listOf("DataInputStream", "DataOutputStream"),
                ),
                BoundaryOwnerRule(
                    name = "StreamProtocolActionDispatcher",
                    path = PRODUCTION_PROTOCOL_ACTION_DISPATCHER,
                    forbiddenReferences = OWNER_LAYER_FORBIDDEN_REFERENCES,
                ),
                BoundaryOwnerRule(
                    name = "StreamMediaFrameRouter",
                    path = PRODUCTION_MEDIA_FRAME_ROUTER,
                    forbiddenReferences = OWNER_LAYER_FORBIDDEN_REFERENCES,
                ),
                BoundaryOwnerRule(
                    name = "StreamProtocolSideEffectOwner",
                    path = PRODUCTION_PROTOCOL_SIDE_EFFECT_OWNER,
                    forbiddenReferences = OWNER_LAYER_FORBIDDEN_REFERENCES +
                        listOf(
                            "DataInputStream",
                            "DataOutputStream",
                            "FileTransfer",
                            "WakeHostPacketSender",
                            "WakeHostDecision",
                        ),
                ),
                BoundaryOwnerRule(
                    name = "StreamProtocolSessionOwner",
                    path = PRODUCTION_PROTOCOL_SESSION_OWNER,
                    forbiddenReferences = OWNER_LAYER_FORBIDDEN_REFERENCES +
                        listOf(
                            "DataInputStream",
                            "DataOutputStream",
                            "FileTransfer",
                            "WakeHostPacketSender",
                            "WakeHostDecision",
                        ),
                ),
                BoundaryOwnerRule(
                    name = "FileTransferProductOwner",
                    path = PRODUCTION_FILE_TRANSFER_PRODUCT_OWNER,
                    forbiddenReferences = OWNER_LAYER_FORBIDDEN_REFERENCES +
                        listOf(
                            "DataInputStream",
                            "DataOutputStream",
                            "ProtocolV1Session",
                            "ProtocolV1Framing",
                            "ProtocolChannel",
                            "OutboundCommandScheduler",
                            "StreamOutboundCommand",
                            "WakeHostPacketSender",
                            "WakeHostDecision",
                        ),
                ),
            )
    }
}
