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
    fun `protocol batch notifies unavailable session before returning`() {
        val streamClient = source(PRODUCTION_STREAM_CLIENT)
        val outboundCommand = source(PRODUCTION_STREAM_OUTBOUND_COMMAND)
        val protocolBatchCommand = outboundCommand.indexOf("class ProtocolBatch(")
        val unavailableCallback = outboundCommand.indexOf("val onUnavailable: (() -> Unit)? = null", protocolBatchCommand)
        val buildCallback = outboundCommand.indexOf("val build: (ProtocolV1Session) -> List<Envelope>", protocolBatchCommand)
        val protocolBatchHandler = streamClient.indexOf("is StreamOutboundCommand.ProtocolBatch ->")
        val sessionLookup = streamClient.indexOf("val session = protocolSessionOwner.currentSession", protocolBatchHandler)
        val unavailableCheck = streamClient.indexOf("if (session == null)", sessionLookup)
        val unavailableNotify = streamClient.indexOf("command.onUnavailable?.invoke()", unavailableCheck)
        val unavailableReturn = streamClient.indexOf("return", unavailableNotify)
        val batchBuild = streamClient.indexOf("command.build(session)", unavailableReturn)

        assertTrue("ProtocolBatch must retain unavailable callback ownership hook", unavailableCallback >= 0)
        assertTrue("ProtocolBatch must keep trailing lambdas bound to build", unavailableCallback < buildCallback)
        assertTrue("StreamClient must handle ProtocolBatch commands", protocolBatchHandler >= 0)
        assertTrue("ProtocolBatch handling must read the current protocol session", sessionLookup > protocolBatchHandler)
        assertTrue("ProtocolBatch handling must branch when the session is unavailable", unavailableCheck > sessionLookup)
        assertTrue("ProtocolBatch handling must notify unavailable sessions", unavailableNotify > unavailableCheck)
        assertTrue("ProtocolBatch handling must stop after unavailable notification", unavailableReturn > unavailableNotify)
        assertTrue("ProtocolBatch envelopes must only build after unavailable handling", batchBuild > unavailableReturn)
    }

    @Test
    fun `clipboard expiry completion is notified when queued batch loses its session`() {
        val streamClient = source(PRODUCTION_STREAM_CLIENT)
        val expireMethod = streamClient.indexOf("fun expireClipboardRequest(")
        val protocolBatch = streamClient.indexOf("StreamOutboundCommand.ProtocolBatch(", expireMethod)
        val unavailableCompletion = streamClient.indexOf("onUnavailable = { completion(false) }", protocolBatch)
        val buildCallback = streamClient.indexOf(") { activeSession ->", unavailableCompletion)
        val expireCall = streamClient.indexOf("completion(activeSession.expireClipboardRequest(id))", buildCallback)

        assertTrue("StreamClient must keep expireClipboardRequest", expireMethod >= 0)
        assertTrue("expireClipboardRequest must queue a protocol batch", protocolBatch > expireMethod)
        assertTrue("queued clipboard expiry must notify false if the session disappears", unavailableCompletion > protocolBatch)
        assertTrue("clipboard expiry must keep trailing lambda bound to the batch build callback", buildCallback > unavailableCompletion)
        assertTrue("clipboard expiry must only complete true/false from an active session inside build", expireCall > buildCallback)
    }

    @Test
    fun `file offer decisions release claimed offers when capability guard fails`() {
        val streamClient = source(PRODUCTION_STREAM_CLIENT)
        val respondMethod = streamClient.indexOf("fun respondToFileOffer(")
        val claim = streamClient.indexOf("fileTransferProductOwner.claimFileOfferDecision(offer)", respondMethod)
        val nullableSession = streamClient.indexOf("val session = owner.ownerToken as? ProtocolV1Session", claim)
        val capabilityGuard = streamClient.indexOf("if (session == null || wireMode != WireMode.V1 || !session.canTransferFiles)", nullableSession)
        val guardRelease = streamClient.indexOf("fileTransferProductOwner.releaseFileOfferDecision(offer)", capabilityGuard)
        val guardReturn = streamClient.indexOf("return false", guardRelease)
        val submit = streamClient.indexOf("val submission = submitOutbound(", guardReturn)
        val backpressureRelease = streamClient.indexOf("fileTransferProductOwner.releaseFileOfferDecision(offer)", submit)

        assertTrue("StreamClient must keep respondToFileOffer", respondMethod >= 0)
        assertTrue("respondToFileOffer must claim the pending offer before sending a decision", claim > respondMethod)
        assertTrue("respondToFileOffer must preserve nullable session guard after claim", nullableSession > claim)
        assertTrue("respondToFileOffer must gate stale session, wire mode, and capability together", capabilityGuard > nullableSession)
        assertTrue("respondToFileOffer must release claimed offers when the capability guard fails", guardRelease > capabilityGuard)
        assertTrue("respondToFileOffer must stop after releasing a failed guard claim", guardReturn > guardRelease)
        assertTrue("respondToFileOffer must submit only after guard release handling", submit > guardReturn)
        assertTrue("respondToFileOffer must still release claimed offers on outbound backpressure", backpressureRelease > submit)
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
    fun `phase zero docs identify closed ownership sub gate without closing runtime gates`() {
        val readme = repositorySource(REPOSITORY_README)
        val audit = repositorySource(OPEN_GATES_AUDIT)
        val phaseZeroTech = repositorySource(PHASE_ZERO_TECH)

        val phaseZeroStatus = readme.normalizedWhitespace()
        val phaseZeroTechStatus = phaseZeroTech.normalizedWhitespace()
        listOf(
            "standalone JVM transport",
            "local product-session lifecycle state",
            "Protocol v1",
            "action dispatch",
            "side-effect owner",
            "file-transfer product state",
            "WakeHost request lifecycle/callback delivery/packet-sender admission",
            "input envelope routing",
            "media-frame routing",
        ).forEach { phrase ->
            assertTrue("README Phase 0 status missing current-base ownership phrase `$phrase`", phaseZeroStatus.contains(phrase))
        }
        assertTrue(phaseZeroStatus.contains("`MainActivity` hands renderer viewport/layout/render-target readiness/admission"))
        assertTrue(phaseZeroStatus.contains("`RendererOwner` and `RendererViewportState`"))
        assertTrue(phaseZeroStatus.contains("Android decoder admission"))
        assertTrue(phaseZeroStatus.contains("UI/product-session coordination now have focused owner coverage"))
        assertTrue(phaseZeroStatus.contains("`ProductSessionCoordinator` owns Internet generation/freshness"))
        assertTrue(phaseZeroStatus.contains("current-base module ownership state is tracked by"))
        assertTrue(phaseZeroStatus.contains("`make phase0-module-ownership-gate`"))
        assertTrue(phaseZeroStatus.contains("`can_close_phase0_module_ownership_extraction=true`"))
        assertTrue(phaseZeroStatus.contains("WakeHost real sleeping-Mac"))
        assertTrue(phaseZeroStatus.contains("runtime/product evidence gates"))
        assertTrue(phaseZeroStatus.contains("fail-closed requirements"))
        assertTrue(audit.contains("Phase 0 module ownership extraction"))
        assertTrue(audit.contains("No source-boundary gap remains for this sub-gate"))
        assertTrue(audit.contains("Keep `make phase0-module-ownership-gate` passing"))
        assertTrue(audit.contains("the open PR snapshot contains only PR #531"))
        assertFalse(audit.contains("remaining module ownership"))
        assertFalse(audit.contains("Remaining module gaps are the decoder platform-adapter/device-evidence"))
        assertFalse(audit.contains("README.md:288-293"))
        assertTrue(phaseZeroTechStatus.contains("The WakeHost product"))
        assertTrue(phaseZeroTechStatus.contains("owner now owns request lifecycle"))
        assertTrue(phaseZeroTechStatus.contains("sleeping-Mac wake, router/NIC WOL behavior"))
        assertTrue(phaseZeroTechStatus.contains("Decoder ownership and UI/product session ownership now have focused"))
        assertFalse(phaseZeroTechStatus.contains("before Phase 0 module ownership can be called complete"))
        assertTrue(phaseZeroTechStatus.contains("`FileTransferProductOwner` owns the Android file-transfer product"))
        assertTrue(phaseZeroTechStatus.contains("`RendererOwner` gates viewport/layout, render-target"))
        assertTrue(phaseZeroTechStatus.contains("render-target readiness actions, and local/Internet frame admission"))
        assertTrue(phaseZeroTechStatus.contains("must flow through `DecoderPresentationOwner`/`RendererOwner`"))
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
        const val PRODUCTION_STREAM_OUTBOUND_COMMAND =
            "app/src/main/java/dev/telemachus/display/StreamOutboundCommand.kt"
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
        const val PRODUCTION_WAKE_HOST_PRODUCT_OWNER =
            "app/src/main/java/dev/telemachus/display/WakeHostProductOwner.kt"

        val REQUIRED_BOUNDARY_OWNERS =
            listOf(
                PRODUCTION_LOCAL_SESSION_STATE,
                PRODUCTION_INPUT_DISPATCHER,
                PRODUCTION_PROTOCOL_ACTION_DISPATCHER,
                PRODUCTION_MEDIA_FRAME_ROUTER,
                PRODUCTION_PROTOCOL_SIDE_EFFECT_OWNER,
                PRODUCTION_PROTOCOL_SESSION_OWNER,
                PRODUCTION_FILE_TRANSFER_PRODUCT_OWNER,
                PRODUCTION_WAKE_HOST_PRODUCT_OWNER,
            )

        val REQUIRED_OWNER_TESTS =
            listOf(
                "app/src/test/java/dev/telemachus/display/StreamClientLocalSessionStateTest.kt",
                "app/src/test/java/dev/telemachus/display/StreamInputDispatcherTest.kt",
                "app/src/test/java/dev/telemachus/display/StreamProtocolActionDispatcherTest.kt",
                "app/src/test/java/dev/telemachus/display/StreamProtocolSideEffectOwnerTest.kt",
                "app/src/test/java/dev/telemachus/display/FileTransferProductOwnerTest.kt",
                "app/src/test/java/dev/telemachus/display/WakeHostProductOwnerTest.kt",
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
                "protocolSessionOwner.activate(",
                "protocolSessionOwner.deactivate()",
                "protocolSessionOwner.clearSideEffectAdmission()",
                "protocolSessionOwner.clear()",
                "private val wakeHostProductOwner =",
                "wakeHostProductOwner.request(",
                "wakeHostProductOwner.dispatchRequest(",
                "wakeHostProductOwner.deliverCompletion(",
                "wakeHostProductOwner.complete(",
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
                "private fun performWakeHostRequest",
                "private fun dispatchWakeHostRequest",
                "private fun processWakeHostCompletion",
                "WakeHostDecision.magicPacket",
                "wakeHostPacketSender.send",
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
                BoundaryOwnerRule(
                    name = "WakeHostProductOwner",
                    path = PRODUCTION_WAKE_HOST_PRODUCT_OWNER,
                    forbiddenReferences = OWNER_LAYER_FORBIDDEN_REFERENCES +
                        listOf(
                            "DataInputStream",
                            "StreamTransportOwner",
                            "SocketStreamTransportConnection",
                        ),
                ),
            )
    }
}
