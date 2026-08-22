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

    @Test
    fun `stream client delegates local session lifecycle state to boundary owner`() {
        val streamClient = source(PRODUCTION_STREAM_CLIENT)
        val sessionState = source(PRODUCTION_LOCAL_SESSION_STATE)

        assertTrue(streamClient.contains("private val localSessionState = StreamClientLocalSessionState"))
        assertTrue(streamClient.contains("localSessionState.prepareConnectionStart()"))
        assertTrue(streamClient.contains("localSessionState.markConnected()"))
        assertTrue(streamClient.contains("localSessionState.markTerminationClaimed(request.failure)"))
        assertTrue(streamClient.contains("localSessionState.markReady()"))
        assertTrue(streamClient.contains("localSessionState.nextReconnectDelayMs()"))

        FORBIDDEN_STREAM_CLIENT_LOCAL_STATE_FIELDS.forEach { field ->
            assertFalse("StreamClient must not own local session field `$field` directly", streamClient.contains(field))
        }
        FORBIDDEN_LOCAL_SESSION_STATE_REFERENCES.forEach { reference ->
            assertFalse("StreamClientLocalSessionState must not depend on `$reference`", sessionState.contains(reference))
        }
    }

    @Test
    fun `stream client delegates protocol action routing to dispatcher`() {
        val streamClient = source(PRODUCTION_STREAM_CLIENT)
        val protocolActionDispatcher = source(PRODUCTION_PROTOCOL_ACTION_DISPATCHER)

        assertTrue(streamClient.contains("private val protocolActionDispatcher ="))
        assertTrue(streamClient.contains("protocolActionDispatcher.dispatchReceivedActions("))
        assertTrue(streamClient.contains("protocolActionDispatcher.dispatchVideoConfigurationCompletionActions("))

        FORBIDDEN_STREAM_CLIENT_PROTOCOL_ACTION_REFERENCES.forEach { reference ->
            assertFalse("StreamClient must not own protocol action routing `$reference`", streamClient.contains(reference))
        }
        FORBIDDEN_PROTOCOL_ACTION_DISPATCHER_REFERENCES.forEach { reference ->
            assertFalse("StreamProtocolActionDispatcher must not depend on `$reference`", protocolActionDispatcher.contains(reference))
        }
    }

    @Test
    fun `stream client delegates media frame routing to boundary owner`() {
        val streamClient = source(PRODUCTION_STREAM_CLIENT)
        val mediaFrameRouter = source(PRODUCTION_MEDIA_FRAME_ROUTER)

        assertTrue(streamClient.contains("private val mediaFrameRouter ="))
        assertTrue(streamClient.contains("mediaFrameRouter.receiveLegacyFrame("))
        assertTrue(streamClient.contains("mediaFrameRouter.receiveProtocolFrame("))
        assertTrue(streamClient.contains("mediaFrameRouter.releaseBuffer(buffer)"))
        assertTrue(streamClient.contains("mediaFrameRouter.resetStream()"))

        FORBIDDEN_STREAM_CLIENT_MEDIA_ROUTING_REFERENCES.forEach { reference ->
            assertFalse("StreamClient must not own media frame routing `$reference`", streamClient.contains(reference))
        }
        FORBIDDEN_MEDIA_FRAME_ROUTER_REFERENCES.forEach { reference ->
            assertFalse("StreamMediaFrameRouter must not depend on `$reference`", mediaFrameRouter.contains(reference))
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
        const val PRODUCTION_LOCAL_SESSION_STATE =
            "app/src/main/java/dev/telemachus/display/StreamClientLocalSessionState.kt"
        const val PRODUCTION_PROTOCOL_ACTION_DISPATCHER =
            "app/src/main/java/dev/telemachus/display/StreamProtocolActionDispatcher.kt"
        const val PRODUCTION_MEDIA_FRAME_ROUTER =
            "app/src/main/java/dev/telemachus/display/StreamMediaFrameRouter.kt"

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

        val FORBIDDEN_STREAM_CLIENT_LOCAL_STATE_FIELDS =
            listOf(
                "@Volatile private var isConnected",
                "@Volatile private var sessionReady",
                "@Volatile private var stopRequested",
                "@Volatile private var connectionEpoch",
                "@Volatile private var lastTerminationFailure",
                "private val reconnectBackoff = ReconnectBackoff()",
            )

        val FORBIDDEN_LOCAL_SESSION_STATE_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
                "StreamTransport",
                "StreamTransportOwner",
                "java.net.Socket",
                "ProtocolV1Session",
                "onConnectionStatus",
            )

        val FORBIDDEN_STREAM_CLIENT_PROTOCOL_ACTION_REFERENCES =
            listOf(
                "ProtocolV1Session.Action.",
                "is ProtocolV1Session.Action",
            )

        val FORBIDDEN_PROTOCOL_ACTION_DISPATCHER_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
                "StreamTransport",
                "StreamTransportOwner",
                "SocketStreamTransportConnection",
                "java.net.Socket",
                "VideoDecoder",
                "MediaCodec",
            )

        val FORBIDDEN_STREAM_CLIENT_MEDIA_ROUTING_REFERENCES =
            listOf(
                "private val bufferPool",
                "private val poolLock",
                "private fun acquireBuffer",
                "private fun updateStats",
                "private fun checkKeyframeFreshness",
                "ProtocolV1Framing.decodeVideo(",
                "internal fun isSyncFrame",
            )

        val FORBIDDEN_MEDIA_FRAME_ROUTER_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
                "StreamTransport",
                "StreamTransportOwner",
                "SocketStreamTransportConnection",
                "java.net.Socket",
                "VideoDecoder",
                "MediaCodec",
            )
    }
}
