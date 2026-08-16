package dev.telemachus.display

import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionGuidanceTest {
    @Test
    fun usbErrorsUseTheActiveAdbTransportRecoveryPath() {
        val cases =
            listOf(
                AdbTransportKind.USB to listOf("USB data cable", "adb reverse tcp:54321 tcp:54321"),
                AdbTransportKind.WIRELESS to
                    listOf(
                        "Wireless debugging",
                        "adb connect <device-ip>:<wireless-adb-port>",
                        "adb reverse tcp:54321 tcp:54321",
                    ),
                AdbTransportKind.UNAVAILABLE to
                    listOf(
                        "Developer options",
                        "USB data cable",
                        "Wireless debugging",
                        "adb connect <device-ip>:<wireless-adb-port>",
                        "adb reverse tcp:54321 tcp:54321",
                    ),
            )

        cases.forEach { (transport, expectedSteps) ->
            val guidance =
                ConnectionGuidanceFactory.from(
                    ConnectException("ECONNREFUSED"),
                    ConnectionGuidanceContext.adb(54321, transport),
                )

            assertEquals(ConnectionFailureKind.HOST_NOT_RUNNING, guidance.kind)
            expectedSteps.forEach { step ->
                assertTrue("Missing '$step': ${guidance.message}", guidance.message.contains(step))
            }
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
                assertTrue(guidance.message.isNotBlank())
                if (context.mode != ConnectionMode.USB) assertNoAdbReferences(guidance.message)
            }
        }
    }

    @Test
    fun lanErrorsProvideExecutableTrustedNetworkRecoveryWithoutAdb() {
        val expectedTermsByFailure =
            listOf(
                ConnectException("Connection refused") to listOf("LAN mode", "trusted Wi-Fi", "54321", "firewall"),
                NoRouteToHostException("Network is unreachable") to listOf("trusted Wi-Fi", "VPN", "54321"),
                SocketTimeoutException("timeout") to listOf("LAN mode", "54321", "firewall"),
                IOException("unknown") to listOf("LAN mode", "trusted Wi-Fi", "54321", "firewall"),
            )

        expectedTermsByFailure.forEach { (failure, terms) ->
            val message = ConnectionGuidanceFactory.from(failure, ConnectionGuidanceContext.trustedLan(54321)).message
            assertNoAdbReferences(message)
            terms.forEach { term -> assertTrue("Missing '$term': $message", message.contains(term)) }
        }
    }

    @Test
    fun internetErrorsProvideExecutableRouteOrLeaseRecoveryWithoutAdb() {
        val expectedTermsByFailure =
            listOf(
                ConnectException("Connection refused") to listOf("Internet mode", "fresh session profile"),
                NoRouteToHostException("Network is unreachable") to listOf("Internet connection", "TURN"),
                SocketTimeoutException("timeout") to listOf("Direct or TURN", "fresh session profile"),
                IOException("unknown") to listOf("Internet mode", "fresh session profile"),
            )

        expectedTermsByFailure.forEach { (failure, terms) ->
            val message = ConnectionGuidanceFactory.from(failure, ConnectionGuidanceContext.internet()).message
            assertNoAdbReferences(message)
            terms.forEach { term -> assertTrue("Missing '$term': $message", message.contains(term)) }
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
        assertTrue(guidanceByMode.first().message.contains("Update Vibe Screen"))
        assertFalse(guidanceByMode.first().message.contains("99"))
    }

    @Test
    fun nestedSocketCauseIsClassifiedInsteadOfReducedToUnknown() {
        val guidance =
            ConnectionGuidanceFactory.from(
                IOException("outer", SocketTimeoutException("connect timeout")),
                ConnectionGuidanceContext.trustedLan(60000),
            )

        assertEquals(ConnectionFailureKind.TIMEOUT, guidance.kind)
        assertTrue(guidance.message.contains("60000"))
        assertNoAdbReferences(guidance.message)
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
        assertEquals("Session ended", shutdown.status)
        assertEquals("Mac ended the session", shutdown.message)

        val user = ConnectionGuidanceFactory.from(SessionFailure.userRequested(), ConnectionGuidanceContext.internet())
        assertEquals("Disconnected by user", user.message)

        val backpressure =
            ConnectionGuidanceFactory.from(
                SessionFailure(SessionFailureKind.OUTBOUND_BACKPRESSURE, "queue full", retryable = true),
                ConnectionGuidanceContext.trustedLan(54321),
            )
        assertEquals("Input stream overloaded", backpressure.status)

        val codec =
            ConnectionGuidanceFactory.from(SessionFailure.codec("decoder error"), ConnectionGuidanceContext.internet())
        assertEquals("Video decoder recovery", codec.status)
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
                ConnectException("Connection refused") to ConnectionFailureKind.HOST_NOT_RUNNING,
                NoRouteToHostException("ENETUNREACH") to ConnectionFailureKind.NETWORK_UNREACHABLE,
                SocketTimeoutException("connect timeout") to ConnectionFailureKind.TIMEOUT,
                IOException("before display configuration") to ConnectionFailureKind.HOST_NOT_RUNNING,
            )
        val transports = listOf(AdbTransportKind.USB, AdbTransportKind.UNAVAILABLE)

        transports.forEach { transport ->
            failures.forEach { (failure, expectedKind) ->
                val guidance =
                    ConnectionGuidanceFactory.from(failure, ConnectionGuidanceContext.adb(54321, transport))
                assertEquals("$transport ${failure.javaClass.simpleName}", expectedKind, guidance.kind)
                assertTrue(guidance.message.contains("adb reverse tcp:54321 tcp:54321"))
                if (transport == AdbTransportKind.USB) {
                    assertTrue(guidance.message.contains("USB data cable"))
                } else {
                    assertTrue(guidance.message.contains("Developer options"))
                }
            }
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
            assertNoAdbReferences(guidance.message)
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
        assertTrue(guidance.message.contains("Open Vibe Screen"))
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
        assertFalse(guidance.message.contains("10.0.0.4"))
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
            assertFalse(guidance.message.contains(secret))
            assertFalse(guidance.message.contains("Technical detail"))
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

    private fun assertNoAdbReferences(message: String) {
        assertFalse("message must not mention ADB: $message", message.contains("adb", ignoreCase = true))
        assertFalse("message must not mention USB: $message", message.contains("USB", ignoreCase = true))
        assertFalse("message must not mention reverse: $message", message.contains("reverse", ignoreCase = true))
    }
}
