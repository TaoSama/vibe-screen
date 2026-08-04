package dev.telemachus.display.internet

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import dev.telemachus.display.internet.security.AndroidSessionPacketCipher
import dev.telemachus.display.internet.security.TrafficKeyDerivation
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AndroidWebRtcPeerEngineInstrumentedTest {
    private val nonceCounters = ConcurrentHashMap<String, AtomicLong>()

    @Test
    fun realPeerConnectionsOpenBothDataChannelsAndExchangePackets() {
        val signaling = LoopbackSignalingBus()
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val host = AndroidWebRtcPeerEngine(context, signaling.factory(PeerRole.HOST), {})
        val device = AndroidWebRtcPeerEngine(context, signaling.factory(PeerRole.DEVICE), {})
        val connected = CountDownLatch(2)
        val controlReceived = CountDownLatch(1)
        val mediaReceived = CountDownLatch(1)
        var controlPayload = byteArrayOf()
        var mediaPayload = byteArrayOf()
        val hostObserver = RecordingObserver(connected)
        val deviceObserver =
            RecordingObserver(connected).apply {
                onControl = {
                    controlPayload = it
                    controlReceived.countDown()
                }
                onMedia = {
                    mediaPayload = it
                    mediaReceived.countDown()
                }
            }

        try {
            device.start(configuration(PeerRole.DEVICE), deviceObserver)
            host.start(configuration(PeerRole.HOST), hostObserver)
            assertTrue("PeerConnections did not connect", connected.await(CONNECTION_TIMEOUT_SECONDS, TimeUnit.SECONDS))

            assertTrue(host.sendControl(byteArrayOf(1, 2)))
            assertTrue(host.sendMedia(byteArrayOf(3, 4)))
            assertTrue("Control packet timed out", controlReceived.await(PACKET_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            assertTrue("Media packet timed out", mediaReceived.await(PACKET_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            assertArrayEquals(byteArrayOf(1, 2), controlPayload)
            assertArrayEquals(byteArrayOf(3, 4), mediaPayload)
        } finally {
            host.close()
            device.close()
            signaling.close()
        }
    }

    private fun configuration(role: PeerRole) =
        PeerConfiguration(
            iceServers = listOf(IceServer(listOf("stun:127.0.0.1:9"))),
            sessionId = SESSION_ID,
            sessionEpoch = SESSION_EPOCH,
            signaling =
                SignalingConfiguration(
                    baseUrl = "https://unused.invalid",
                    bearerToken = "instrumentation-token-that-is-never-sent",
                    role = role,
                ),
            sessionCipher = instrumentationCipher(role),
        )

    private fun instrumentationCipher(role: PeerRole) =
        AndroidSessionPacketCipher(
            sessionId = SESSION_ID,
            sessionEpoch = SESSION_EPOCH,
            localRole = role,
            initialKeys =
                TrafficKeyDerivation.initial(
                    sharedSecret = ByteArray(32) { 1 },
                    bootstrapSecret = ByteArray(32) { 2 },
                    context = ByteArray(32) { 3 },
                ),
            reserveNonce = { channel, sender, keyEpoch ->
                val sequence =
                    nonceCounters
                        .computeIfAbsent("$channel:$sender:$keyEpoch") { AtomicLong() }
                        .incrementAndGet()
                java.nio.ByteBuffer.allocate(12).putInt(channel).putLong(sequence).array()
            },
            rotateKeys = { current, nonce ->
                TrafficKeyDerivation.rotate(current, current.keyEpoch + 1, nonce)
            },
        )

    private class RecordingObserver(
        private val connected: CountDownLatch,
    ) : WebRtcPeerEngine.Observer {
        var onControl: (ByteArray) -> Unit = {}
        var onMedia: (ByteArray) -> Unit = {}

        override fun onConnected(route: PeerRoute) = connected.countDown()
        override fun onDisconnected() = Unit
        override fun onControlMessage(sessionEpoch: Long, payload: ByteArray) = onControl(payload)
        override fun onMediaPacket(sessionEpoch: Long, payload: ByteArray) = onMedia(payload)
        override fun onStats(stats: WebRtcStats) = Unit
        override fun onFailure(error: Throwable) = throw AssertionError(error)
    }

    companion object {
        private const val SESSION_ID = "instrumentation-session"
        private const val SESSION_EPOCH = 9L
        private const val CONNECTION_TIMEOUT_SECONDS = 20L
        private const val PACKET_TIMEOUT_SECONDS = 5L
    }
}

private class LoopbackSignalingBus : AutoCloseable {
    private val executor = Executors.newSingleThreadExecutor()
    private val clients = mutableMapOf<PeerRole, Endpoint>()

    fun factory(role: PeerRole) =
        SignalingClientFactory { _, _ ->
            synchronized(clients) { clients.getOrPut(role) { Endpoint(role) } }
        }

    override fun close() {
        executor.shutdownNow()
    }

    private fun peer(role: PeerRole): Endpoint =
        synchronized(clients) {
            clients.getOrPut(if (role == PeerRole.HOST) PeerRole.DEVICE else PeerRole.HOST) {
                Endpoint(if (role == PeerRole.HOST) PeerRole.DEVICE else PeerRole.HOST)
            }
        }

    private inner class Endpoint(
        private val role: PeerRole,
    ) : SignalingClient {
        private var listener: SignalingClient.Listener? = null
        private val pending = ArrayDeque<(SignalingClient.Listener) -> Unit>()

        override fun start(listener: SignalingClient.Listener) {
            val queued = synchronized(this) { this.listener = listener; pending.toList().also { pending.clear() } }
            queued.forEach { executor.execute { it(listener) } }
        }

        override fun sendOffer(sdp: String) = deliver { it.onOffer(sdp) }
        override fun sendAnswer(sdp: String) = deliver { it.onAnswer(sdp) }
        override fun sendIceCandidate(candidate: SignalingIceCandidate) = deliver { it.onIceCandidate(candidate) }
        override fun sendEndOfCandidates() = deliver { it.onEndOfCandidates() }
        override fun close() = Unit

        private fun deliver(event: (SignalingClient.Listener) -> Unit) {
            val target = peer(role)
            val listener = synchronized(target) { target.listener.also { if (it == null) target.pending.addLast(event) } }
            if (listener != null) executor.execute { event(listener) }
        }
    }
}
