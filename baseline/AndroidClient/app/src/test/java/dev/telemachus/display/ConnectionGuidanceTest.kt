package dev.telemachus.display

import java.io.File
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionGuidanceTest {
    @Test
    fun usbErrorsUseTheActiveAdbTransportRecoveryPath() {
        val cases =
            listOf(
                AdbTransportKind.USB to R.string.connection_guidance_usb_recovery_usb,
                AdbTransportKind.WIRELESS to R.string.connection_guidance_usb_recovery_wireless_adb,
                AdbTransportKind.UNAVAILABLE to R.string.connection_guidance_usb_recovery_unavailable,
            )

        cases.forEach { (transport, expectedRecoveryResource) ->
            val guidance =
                ConnectionGuidanceFactory.from(
                    ConnectException("ECONNREFUSED"),
                    ConnectionGuidanceContext.adb(54321, transport),
                )

            assertEquals(ConnectionFailureKind.HOST_NOT_RUNNING, guidance.kind)
            assertEquals(expectedRecoveryResource, guidance.message.resourceId)
            assertEquals(text(R.string.connection_guidance_usb_open_mac_prefix), guidance.message.args[0])
            assertEquals(54321, guidance.message.args[1])
        }
    }

    @Test
    fun allTransportErrorClassesAreModeAware() {
        val failures =
            listOf(
                ConnectException("Connection refused") to ConnectionFailureKind.HOST_NOT_RUNNING,
                NoRouteToHostException("ENETUNREACH") to ConnectionFailureKind.NETWORK_UNREACHABLE,
                SocketTimeoutException("connect timeout") to ConnectionFailureKind.TIMEOUT,
                IOException("unexpected transport failure") to ConnectionFailureKind.UNKNOWN,
            )
        val contexts =
            listOf(
                ConnectionGuidanceContext.adb(54321, AdbTransportKind.WIRELESS),
                ConnectionGuidanceContext.trustedLan(54321),
                ConnectionGuidanceContext.internet(),
            )

        contexts.forEach { context ->
            failures.forEach { (failure, expectedKind) ->
                val guidance = ConnectionGuidanceFactory.from(failure, context)
                assertEquals("${context.mode} ${failure.javaClass.simpleName}", expectedKind, guidance.kind)
                assertTrue(guidance.message.resourceId != 0)
                if (context.mode != ConnectionMode.USB) assertNoAdbReferences(guidance)
            }
        }
    }

    @Test
    fun lanErrorsProvideExecutableTrustedNetworkRecoveryWithoutAdb() {
        val expectedMessageByFailure =
            listOf(
                ConnectException("Connection refused") to R.string.connection_guidance_lan_host_unavailable_message,
                NoRouteToHostException("Network is unreachable") to
                    R.string.connection_guidance_lan_network_unavailable_message,
                SocketTimeoutException("timeout") to R.string.connection_guidance_lan_timeout_message,
                IOException("unknown") to R.string.connection_guidance_lan_unknown_message,
            )

        expectedMessageByFailure.forEach { (failure, expectedMessageResource) ->
            val guidance = ConnectionGuidanceFactory.from(failure, ConnectionGuidanceContext.trustedLan(54321))
            assertEquals(expectedMessageResource, guidance.message.resourceId)
            assertEquals(54321, guidance.message.args.single())
            assertNoAdbReferences(guidance)
        }
    }

    @Test
    fun internetErrorsProvideExecutableRouteOrLeaseRecoveryWithoutAdb() {
        val expectedMessageByFailure =
            listOf(
                ConnectException("Connection refused") to R.string.connection_guidance_internet_host_unavailable_message,
                NoRouteToHostException("Network is unreachable") to
                    R.string.connection_guidance_internet_network_unavailable_message,
                SocketTimeoutException("timeout") to R.string.connection_guidance_internet_timeout_message,
                IOException("unknown") to R.string.connection_guidance_internet_unknown_message,
            )

        expectedMessageByFailure.forEach { (failure, expectedMessageResource) ->
            val guidance = ConnectionGuidanceFactory.from(failure, ConnectionGuidanceContext.internet())
            assertEquals(expectedMessageResource, guidance.message.resourceId)
            assertTrue(guidance.message.args.isEmpty())
            assertNoAdbReferences(guidance)
        }
    }

    @Test
    fun protocolGuidanceRemainsModeIndependent() {
        val failure = SessionFailure.protocol(SessionFailureKind.UNKNOWN_MESSAGE, "Unknown message type: 99")
        val guidanceByMode =
            listOf(
                ConnectionGuidanceContext.adb(54321, AdbTransportKind.USB),
                ConnectionGuidanceContext.trustedLan(54321),
                ConnectionGuidanceContext.internet(),
            ).map { context -> ConnectionGuidanceFactory.from(failure, context) }

        assertTrue(guidanceByMode.all { it == guidanceByMode.first() })
        assertEquals(ConnectionFailureKind.INCOMPATIBLE_SESSION, guidanceByMode.first().kind)
        assertEquals(R.string.connection_guidance_mac_incompatible_title, guidanceByMode.first().status.resourceId)
        assertEquals(R.string.connection_guidance_mac_incompatible_message, guidanceByMode.first().message.resourceId)
        assertNoRawArg(guidanceByMode.first(), "99")
    }

    @Test
    fun nestedSocketCauseIsClassifiedInsteadOfReducedToUnknown() {
        val guidance =
            ConnectionGuidanceFactory.from(
                IOException("outer", SocketTimeoutException("connect timeout")),
                ConnectionGuidanceContext.trustedLan(60000),
            )

        assertEquals(ConnectionFailureKind.TIMEOUT, guidance.kind)
        assertEquals(R.string.connection_guidance_lan_timeout_message, guidance.message.resourceId)
        assertEquals(60000, guidance.message.args.single())
        assertNoAdbReferences(guidance)
    }

    @Test
    fun sessionFailureKindsRouteToTheRightGuidanceFamily() {
        val cases =
            listOf(
                SessionFailure.heartbeat("heartbeat timeout") to ConnectionFailureKind.TIMEOUT,
                SessionFailure.transport("pipe broken") to ConnectionFailureKind.UNKNOWN,
                SessionFailure.write("write failed") to ConnectionFailureKind.UNKNOWN,
                SessionFailure.serverShutdown() to ConnectionFailureKind.UNKNOWN,
                SessionFailure.userRequested() to ConnectionFailureKind.UNKNOWN,
                SessionFailure(SessionFailureKind.OUTBOUND_BACKPRESSURE, "queue full", retryable = true) to
                    ConnectionFailureKind.INPUT_OVERLOADED,
                SessionFailure.codec("decoder error") to ConnectionFailureKind.INCOMPATIBLE_SESSION,
            )

        cases.forEach { (failure, expectedKind) ->
            val guidance =
                ConnectionGuidanceFactory.from(failure, ConnectionGuidanceContext.adb(54321, AdbTransportKind.USB))
            assertEquals(failure.kind.name, expectedKind, guidance.kind)
        }

        val shutdown = ConnectionGuidanceFactory.from(SessionFailure.serverShutdown(), ConnectionGuidanceContext.internet())
        assertEquals(R.string.connection_guidance_session_ended_title, shutdown.status.resourceId)
        assertEquals(R.string.connection_guidance_mac_ended_session_message, shutdown.message.resourceId)

        val user = ConnectionGuidanceFactory.from(SessionFailure.userRequested(), ConnectionGuidanceContext.internet())
        assertEquals(R.string.connection_guidance_user_disconnected_message, user.message.resourceId)

        val backpressure =
            ConnectionGuidanceFactory.from(
                SessionFailure(SessionFailureKind.OUTBOUND_BACKPRESSURE, "queue full", retryable = true),
                ConnectionGuidanceContext.trustedLan(54321),
            )
        assertEquals(R.string.connection_guidance_input_overloaded_title, backpressure.status.resourceId)

        val codec =
            ConnectionGuidanceFactory.from(SessionFailure.codec("decoder error"), ConnectionGuidanceContext.internet())
        assertEquals(R.string.connection_guidance_video_decoder_recovery_title, codec.status.resourceId)
    }

    @Test
    fun everySessionFailureKindHasActionableGuidanceWithoutRawDetails() {
        val rawDetail = "private-host.internal:65432 invalid_media_header host stacktrace"
        val contexts =
            listOf(
                ConnectionGuidanceContext.adb(54321, AdbTransportKind.USB),
                ConnectionGuidanceContext.trustedLan(54321),
                ConnectionGuidanceContext.internet(),
            )

        SessionFailureKind.values().forEach { kind ->
            contexts.forEach { context ->
                val guidance = ConnectionGuidanceFactory.from(failureFor(kind, rawDetail), context)

                assertTrue(kind.name + " " + context.mode + " status", guidance.status.resourceId != 0)
                assertTrue(kind.name + " " + context.mode + " message", guidance.message.resourceId != 0)
                assertNoRawArg(guidance, rawDetail)
                assertNoRawArg(guidance, "invalid_media_header")
                assertNoRawArg(guidance, "host stacktrace")
                if (context.mode != ConnectionMode.USB) assertNoAdbReferences(guidance)
            }
        }
    }

    @Test
    fun heartbeatTransportAndWriteFailuresAreReclassifiedFromTheirDetail() {
        val refused = SessionFailure.heartbeat("Connection refused")
        val guidance =
            ConnectionGuidanceFactory.from(refused, ConnectionGuidanceContext.adb(54321, AdbTransportKind.USB))
        assertEquals(ConnectionFailureKind.HOST_NOT_RUNNING, guidance.kind)
    }

    @Test
    fun sessionProtocolExceptionUnwrapsToUnderlyingFailureGuidance() {
        val failure = SessionFailure.protocol(SessionFailureKind.UNKNOWN_MESSAGE, "Unknown message type: 99")
        val wrapped = SessionProtocolException(failure)

        val direct = ConnectionGuidanceFactory.from(failure, ConnectionGuidanceContext.trustedLan(54321))
        val viaException = ConnectionGuidanceFactory.from(wrapped, ConnectionGuidanceContext.trustedLan(54321))

        assertEquals(direct, viaException)
        assertEquals(ConnectionFailureKind.INCOMPATIBLE_SESSION, viaException.kind)
    }

    @Test
    fun usbAndUnavailableTransportsEachGetTheirOwnRecoveryMatrix() {
        val failures =
            listOf(
                ConnectException("Connection refused") to
                    (ConnectionFailureKind.HOST_NOT_RUNNING to R.string.connection_guidance_usb_open_mac_prefix),
                NoRouteToHostException("ENETUNREACH") to
                    (ConnectionFailureKind.NETWORK_UNREACHABLE to R.string.connection_guidance_usb_route_unavailable_prefix),
                SocketTimeoutException("connect timeout") to
                    (ConnectionFailureKind.TIMEOUT to R.string.connection_guidance_usb_timeout_prefix),
                IOException("before display configuration") to
                    (ConnectionFailureKind.HOST_NOT_RUNNING to R.string.connection_guidance_usb_open_mac_prefix),
            )
        val transports =
            listOf(
                AdbTransportKind.USB to R.string.connection_guidance_usb_recovery_usb,
                AdbTransportKind.UNAVAILABLE to R.string.connection_guidance_usb_recovery_unavailable,
            )

        transports.forEach { (transport, expectedRecoveryResource) ->
            failures.forEach { (failure, expected) ->
                val (expectedKind, expectedPrefixResource) = expected
                val guidance =
                    ConnectionGuidanceFactory.from(failure, ConnectionGuidanceContext.adb(54321, transport))
                assertEquals("$transport ${failure.javaClass.simpleName}", expectedKind, guidance.kind)
                assertEquals(expectedRecoveryResource, guidance.message.resourceId)
                assertEquals(expectedPrefixResource, (guidance.message.args[0] as ConnectionGuidanceText).resourceId)
                assertEquals(54321, guidance.message.args[1])
            }
        }
    }

    @Test
    fun usbRecoveryCopyKeepsExecutableAdbReverseCommand() {
        val resources =
            listOf(
                "connection_guidance_usb_recovery_usb",
                "connection_guidance_usb_recovery_wireless_adb",
                "connection_guidance_usb_recovery_unavailable",
            )
        val strings = stringsXml()

        resources.forEach { name ->
            val text = strings.stringResource(name)
            assertTrue(text, text.contains("adb reverse tcp:%2\$d tcp:%2\$d"))
        }
    }

    @Test
    fun nestedConnectNoRouteAndUnknownHostCausesAreClassified() {
        val cases =
            listOf(
                IOException("outer", ConnectException("Connection refused")) to ConnectionFailureKind.HOST_NOT_RUNNING,
                IOException("outer", NoRouteToHostException("ENETUNREACH")) to
                    ConnectionFailureKind.NETWORK_UNREACHABLE,
                IOException("outer", UnknownHostException("host not found")) to
                    ConnectionFailureKind.NETWORK_UNREACHABLE,
            )

        cases.forEach { (throwable, expectedKind) ->
            val guidance =
                ConnectionGuidanceFactory.from(throwable, ConnectionGuidanceContext.trustedLan(54321))
            assertEquals(throwable.cause!!.javaClass.simpleName, expectedKind, guidance.kind)
            assertNoAdbReferences(guidance)
        }
    }

    @Test
    fun beforeDisplayConfigurationIsTreatedAsHostNotRunning() {
        val guidance =
            ConnectionGuidanceFactory.from(
                IOException("rejected before display configuration"),
                ConnectionGuidanceContext.adb(54321, AdbTransportKind.USB),
            )

        assertEquals(ConnectionFailureKind.HOST_NOT_RUNNING, guidance.kind)
        assertEquals(text(R.string.connection_guidance_usb_open_mac_prefix), guidance.message.args[0])
    }

    @Test
    fun cyclicCauseChainTerminatesAndStillClassifiesKnownFailures() {
        val outer = IOException("private endpoint 10.0.0.4:54321")
        val refused = ConnectException("Connection refused by 10.0.0.4:54321")
        outer.initCause(refused)
        refused.initCause(outer)

        val guidance =
            ConnectionGuidanceFactory.from(
                outer,
                ConnectionGuidanceContext.trustedLan(54321),
            )

        assertEquals(ConnectionFailureKind.HOST_NOT_RUNNING, guidance.kind)
        assertNoRawArg(guidance, "10.0.0.4")
    }

    @Test
    fun userGuidanceDoesNotExposeRawFailureDetails() {
        val secret = "sensitive-host.internal:65432"
        val cases =
            listOf(
                ConnectionGuidanceFactory.from(
                    IOException(secret),
                    ConnectionGuidanceContext.internet(),
                ),
                ConnectionGuidanceFactory.from(
                    SessionFailure.protocol(SessionFailureKind.UNKNOWN_MESSAGE, secret),
                    ConnectionGuidanceContext.internet(),
                ),
                ConnectionGuidanceFactory.from(
                    SessionFailure(SessionFailureKind.OUTBOUND_BACKPRESSURE, secret, retryable = true),
                    ConnectionGuidanceContext.internet(),
                ),
                ConnectionGuidanceFactory.from(
                    SessionFailure.heartbeat(secret),
                    ConnectionGuidanceContext.internet(),
                ),
                ConnectionGuidanceFactory.from(
                    SessionFailure(SessionFailureKind.SERVER_SHUTDOWN, secret, retryable = false),
                    ConnectionGuidanceContext.internet(),
                ),
                ConnectionGuidanceFactory.from(
                    SessionFailure(SessionFailureKind.USER_REQUESTED, secret, retryable = false),
                    ConnectionGuidanceContext.internet(),
                ),
            )

        cases.forEach { guidance ->
            assertNoRawArg(guidance, secret)
            assertNoRawArg(guidance, "Technical detail")
        }
    }

    @Test
    fun withPortReplacesPortWhilePreservingModeAndTransport() {
        val original = ConnectionGuidanceContext.adb(54321, AdbTransportKind.WIRELESS)
        val updated = original.withPort(60000)

        assertEquals(ConnectionMode.USB, updated.mode)
        assertEquals(AdbTransportKind.WIRELESS, updated.adbTransport)
        assertEquals(60000, updated.port)
    }

    @Test
    fun withPortOnLanContextKeepsLanMode() {
        val lan = ConnectionGuidanceContext.trustedLan(54321).withPort(60000)
        assertEquals(ConnectionMode.WIRELESS, lan.mode)
        assertEquals(60000, lan.port)
    }

    private fun assertNoAdbReferences(guidance: ConnectionGuidance) {
        assertFalse("status must not mention ADB", guidance.status.resourceId == R.string.connection_guidance_adb_route_unavailable_title)
        USB_ONLY_RESOURCES.forEach { resourceId ->
            assertFalse(
                "message must not use USB/ADB resource $resourceId: ${guidance.message}",
                containsResource(guidance.message, resourceId),
            )
        }
    }

    private fun assertNoRawArg(
        guidance: ConnectionGuidance,
        rawText: String,
    ) {
        assertFalse(containsStringArg(guidance.status, rawText))
        assertFalse(containsStringArg(guidance.message, rawText))
    }

    private fun containsResource(
        text: ConnectionGuidanceText,
        resourceId: Int,
    ): Boolean =
        text.resourceId == resourceId ||
            text.args.any { arg -> arg is ConnectionGuidanceText && containsResource(arg, resourceId) }

    private fun containsStringArg(
        text: ConnectionGuidanceText,
        rawText: String,
    ): Boolean =
        text.args.any { arg ->
            when (arg) {
                is String -> arg.contains(rawText)
                is ConnectionGuidanceText -> containsStringArg(arg, rawText)
                else -> false
            }
        }

    private fun failureFor(
        kind: SessionFailureKind,
        detail: String,
    ): SessionFailure =
        when (kind) {
            SessionFailureKind.TRANSPORT_CLOSED -> SessionFailure.transport(detail)
            SessionFailureKind.HEARTBEAT_TIMEOUT -> SessionFailure.heartbeat(detail)
            SessionFailureKind.WRITE_FAILED -> SessionFailure.write(detail)
            SessionFailureKind.CODEC_CONFIGURATION -> SessionFailure.codec(detail)
            SessionFailureKind.SERVER_SHUTDOWN -> SessionFailure.serverShutdown()
            SessionFailureKind.USER_REQUESTED -> SessionFailure.userRequested()
            SessionFailureKind.OUTBOUND_BACKPRESSURE ->
                SessionFailure(kind, detail, retryable = true)
            SessionFailureKind.INVALID_DISPLAY,
            SessionFailureKind.INVALID_FRAME,
            SessionFailureKind.INVALID_ENVELOPE,
            SessionFailureKind.INVALID_MEDIA_PAYLOAD,
            SessionFailureKind.INVALID_MEDIA_HEADER,
            SessionFailureKind.INVALID_PEER_MESSAGE,
            SessionFailureKind.SESSION_REJECTED,
            SessionFailureKind.HOST_PROTOCOL_ERROR,
            SessionFailureKind.UNKNOWN_MESSAGE,
            -> SessionFailure.protocol(kind, detail)
        }

    private fun text(
        resourceId: Int,
        vararg args: Any,
    ) = ConnectionGuidanceText(resourceId, args.toList())

    private fun stringsXml(): File {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            STRINGS_XML_PATHS
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("strings.xml not found from " + System.getProperty("user.dir"))
    }

    private fun File.stringResource(name: String): String {
        val document = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(this)
        val strings = document.getElementsByTagName("string")
        for (index in 0 until strings.length) {
            val node = strings.item(index)
            if (node.attributes?.getNamedItem("name")?.nodeValue == name) return node.textContent
        }
        error("String resource not found: $name")
    }

    private companion object {
        val STRINGS_XML_PATHS =
            listOf(
                "app/src/main/res/values/strings.xml",
                "baseline/AndroidClient/app/src/main/res/values/strings.xml",
            )

        val USB_ONLY_RESOURCES =
            setOf(
                R.string.connection_guidance_usb_open_mac_prefix,
                R.string.connection_guidance_usb_route_unavailable_prefix,
                R.string.connection_guidance_usb_timeout_prefix,
                R.string.connection_guidance_usb_unknown_prefix,
                R.string.connection_guidance_usb_recovery_usb,
                R.string.connection_guidance_usb_recovery_wireless_adb,
                R.string.connection_guidance_usb_recovery_unavailable,
            )
    }
}
