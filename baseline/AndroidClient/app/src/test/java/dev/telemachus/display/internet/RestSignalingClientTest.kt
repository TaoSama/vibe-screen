package dev.telemachus.display.internet

import com.google.gson.JsonParser
import java.io.BufferedReader
import java.io.Closeable
import java.io.InputStreamReader
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class RestSignalingClientTest {
    private lateinit var server: MiniSignalingServer
    private val token = "t".repeat(32)

    @Before
    fun startServer() {
        server = MiniSignalingServer(token)
    }

    @After
    fun stopServer() {
        server.close()
    }

    @Test
    fun exchangesAuthenticatedOfferAnswerAndCandidates() {
        val offers = Collections.synchronizedList(mutableListOf<String>())
        val candidates = Collections.synchronizedList(mutableListOf<SignalingIceCandidate>())
        val received = CountDownLatch(2)
        val asyncFailure = AtomicReference<Throwable?>()
        val client = RestSignalingClient(testConfiguration(), "session-1")
        client.start(
            object : SignalingClient.Listener {
                override fun onOffer(sdp: String) {
                    offers += sdp
                    received.countDown()
                }

                override fun onAnswer(sdp: String) = Unit

                override fun onIceCandidate(candidate: SignalingIceCandidate) {
                    candidates += candidate
                    received.countDown()
                }

                override fun onEndOfCandidates() = Unit

                override fun onFailure(error: Throwable) {
                    asyncFailure.compareAndSet(null, error)
                }
            },
        )

        client.sendAnswer("v=0\r\nanswer")
        client.sendIceCandidate(SignalingIceCandidate("candidate:device", "0", 0))

        assertTrue("incoming signaling events timed out", received.await(5, TimeUnit.SECONDS))
        assertTrue("outgoing signaling messages timed out", server.posted.await(5, TimeUnit.SECONDS))
        assertTrue("poll cursor did not advance", server.cursorAdvanced.await(5, TimeUnit.SECONDS))
        client.close()
        assertEquals(listOf("v=0\r\noffer"), offers)
        assertEquals(listOf(SignalingIceCandidate("candidate:host", "0", 0)), candidates)
        val documents = server.postedBodies.map { JsonParser.parseString(it).asJsonObject }
        assertEquals(listOf("answer", "ice_candidate"), documents.map { it["type"].asString })
        assertTrue(documents.all { it["message_id"].asString.isNotBlank() })
        assertEquals("v=0\r\nanswer", documents[0]["sdp"].asString)
        assertEquals("candidate:device", documents[1]["candidate"].asJsonObject["candidate"].asString)
        assertEquals("0", documents[1]["candidate"].asJsonObject["sdp_mid"].asString)
        assertEquals(0, documents[1]["candidate"].asJsonObject["sdp_mline_index"].asInt)
        assertEquals(null, asyncFailure.get())
    }

    @Test
    fun plaintextSignalingRequiresExplicitTestOptIn() {
        assertThrows(IllegalArgumentException::class.java) {
            SignalingConfiguration(
                baseUrl = "http://127.0.0.1:${server.port}",
                bearerToken = token,
                role = PeerRole.DEVICE,
            )
        }
    }

    @Test
    fun rejectsUnsafeSessionIdentifierBeforeNetworkAccess() {
        val configuration = testConfiguration()
        assertThrows(IllegalArgumentException::class.java) {
            RestSignalingClient(configuration, "../other-session")
        }
        assertTrue(configuration.bearerTokenSecret.isDestroyedForTest())
    }

    @Test
    fun configurationStringsNeverExposeBearerOrTurnCredentials() {
        val signaling = testConfiguration()
        val peer =
            PeerConfiguration(
                iceServers = listOf(IceServer(listOf("turns:relay.example:5349"), "turn-user", "turn-secret")),
                sessionId = "session-1",
                sessionEpoch = 1,
                signaling = signaling,
            )

        assertTrue(token !in signaling.toString())
        assertTrue("turn-secret" !in peer.toString())
        assertTrue("turn-user" !in peer.toString())
    }

    private fun testConfiguration() =
        SignalingConfiguration(
            baseUrl = "http://127.0.0.1:${server.port}",
            bearerToken = token,
            role = PeerRole.DEVICE,
            pollWaitSeconds = 0,
            allowInsecureForTesting = true,
        )
}

private class MiniSignalingServer(
    private val token: String,
) : Closeable {
    private val socket = ServerSocket(0, 16, java.net.InetAddress.getLoopbackAddress())
    private val closed = AtomicBoolean(false)
    private val servedEvents = AtomicBoolean(false)
    val postedBodies = Collections.synchronizedList(mutableListOf<String>())
    val posted = CountDownLatch(2)
    val cursorAdvanced = CountDownLatch(1)
    val port: Int = socket.localPort
    private val thread =
        Thread(::serve, "signaling-test-server").apply {
            isDaemon = true
            start()
        }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        socket.close()
        thread.join(2_000)
    }

    private fun serve() {
        while (!closed.get()) {
            try {
                socket.accept().use(::handle)
            } catch (failure: java.net.SocketException) {
                if (!closed.get()) throw failure
            }
        }
    }

    private fun handle(client: Socket) {
        val reader = BufferedReader(InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8))
        val request = reader.readLine() ?: return
        val headers = mutableMapOf<String, String>()
        while (true) {
            val line = reader.readLine() ?: return
            if (line.isEmpty()) break
            val separator = line.indexOf(':')
            if (separator > 0) headers[line.substring(0, separator).lowercase()] = line.substring(separator + 1).trim()
        }
        check(headers["authorization"] == "Bearer $token")
        val contentLength = headers["content-length"]?.toInt() ?: 0
        val requestBody = CharArray(contentLength)
        var offset = 0
        while (offset < contentLength) {
            val count = reader.read(requestBody, offset, contentLength - offset)
            if (count < 0) break
            offset += count
        }

        val path = request.split(' ')[1]
        if (path.startsWith("/v1/sessions/session-1/events") && "after=2" in path) cursorAdvanced.countDown()
        val responseBody =
            when {
                path.startsWith("/v1/sessions/session-1/events") -> {
                    if (servedEvents.compareAndSet(false, true)) {
                        """{"events":[{"sequence":1,"type":"offer","sdp":"v=0\r\noffer"},{"sequence":2,"type":"ice_candidate","candidate":{"candidate":"candidate:host","sdp_mid":"0","sdp_mline_index":0}}],"next_cursor":2}"""
                    } else {
                        Thread.sleep(20)
                        """{"events":[],"next_cursor":2}"""
                    }
                }
                path == "/v1/sessions/session-1/messages" -> {
                    postedBodies += String(requestBody, 0, offset)
                    posted.countDown()
                    "{}"
                }
                else -> error("Unexpected request path: $path")
            }
        val bytes = responseBody.toByteArray(StandardCharsets.UTF_8)
        val response =
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n"
                .toByteArray(StandardCharsets.UTF_8)
        client.getOutputStream().apply {
            write(response)
            write(bytes)
            flush()
        }
    }
}
