package dev.telemachus.display.internet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test

class WebRtcInternetTransportTest {
    @Test
    fun validatesChannelSemanticsBeforeStarting() {
        val peer = FakePeerEngine(mediaSemantics = DataChannelSemantics.RELIABLE_CONTROL)
        val transport = fixture(peer = peer)

        assertThrows(IllegalArgumentException::class.java) { transport.start() }
        assertFalse(peer.started)
    }

    @Test
    fun startFailureReleasesNetworkCallbackAndPeer() {
        val peer = FakePeerEngine(startFailure = IllegalStateException("signaling failed"))
        val monitor = FakeNetworkMonitor()
        val transport = fixture(peer, monitor)

        assertThrows(IllegalStateException::class.java) { transport.start() }

        assertEquals(1, monitor.closeCalls)
        assertEquals(1, peer.closeCalls)
        assertEquals(InternetTransportState.CLOSED, transport.state)
    }

    @Test
    fun keepsControlAndMediaOnSeparateEnginePaths() {
        val peer = FakePeerEngine()
        val transport = fixture(peer = peer)
        transport.start()
        peer.observer.onConnected(PeerRoute.DIRECT)

        assertTrue(transport.sendControl(byteArrayOf(1)))
        assertTrue(transport.sendMedia(byteArrayOf(2)))
        assertEquals(listOf(1.toByte()), peer.controlPayloads.map { it.single() })
        assertEquals(listOf(2.toByte()), peer.mediaPayloads.map { it.single() })
    }

    @Test
    fun reportsRelayRouteSelection() {
        val peer = FakePeerEngine()
        val events = mutableListOf<InternetTransportEvent>()
        val transport = fixture(peer = peer, events = events)
        transport.start()

        peer.observer.onConnected(PeerRoute.RELAY)

        assertEquals(InternetTransportState.CONNECTED_RELAY, transport.state)
        assertTrue(events.contains(InternetTransportEvent.RouteSelected(PeerRoute.RELAY)))
    }

    @Test
    fun restartsIceWhenValidatedNetworkChangesAndThrottlesDuplicates() {
        val clock = FakeClock(10_000)
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val transport = fixture(peer, monitor, clock)
        transport.start()
        monitor.available(network("wifi"))
        peer.observer.onConnected(PeerRoute.DIRECT)

        monitor.available(network("cellular"))
        monitor.available(network("vpn"))

        assertEquals(1, peer.iceRestarts)
        clock.now += 5_000
        transport.tick()
        assertEquals(2, peer.iceRestarts)
    }

    @Test
    fun suspendsOnNetworkLossAndRecoversImmediatelyOnValidatedNetwork() {
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val transport = fixture(peer, monitor)
        transport.start()
        monitor.available(network("wifi"))
        peer.observer.onConnected(PeerRoute.DIRECT)

        monitor.lost("wifi")
        assertEquals(InternetTransportState.SUSPENDED, transport.state)
        monitor.available(network("cellular"))

        assertEquals(InternetTransportState.RECOVERING, transport.state)
        assertEquals(1, peer.iceRestarts)
    }

    @Test
    fun suspendsWhenCurrentNetworkLosesInternetValidation() {
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val transport = fixture(peer, monitor)
        transport.start()
        monitor.available(network("wifi"))
        peer.observer.onConnected(PeerRoute.DIRECT)

        monitor.available(network("wifi").copy(validated = false))

        assertEquals(InternetTransportState.SUSPENDED, transport.state)
    }

    @Test
    fun repeatedDisconnectDoesNotPostponeFirstRecoveryAttempt() {
        val clock = FakeClock(1_000)
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val transport = fixture(peer, monitor, clock)
        transport.start()
        monitor.available(network("wifi"))

        peer.observer.onDisconnected()
        clock.now += 400
        peer.observer.onDisconnected()
        clock.now += 100
        transport.tick()

        assertEquals(1, peer.iceRestarts)
    }

    @Test
    fun failedIceRestartRemainsPendingForNextTick() {
        val clock = FakeClock(1_000)
        val peer = FakePeerEngine(iceRestartFailuresRemaining = 1)
        val monitor = FakeNetworkMonitor()
        val transport = fixture(peer, monitor, clock)
        transport.start()
        monitor.available(network("wifi"))
        peer.observer.onConnected(PeerRoute.DIRECT)

        assertThrows(IllegalStateException::class.java) { monitor.available(network("cellular")) }
        transport.tick()

        assertEquals(2, peer.iceRestartCalls)
    }

    @Test
    fun dropsPacketsFromOldEpochAndWhileRecovering() {
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val transport = fixture(peer, monitor)
        val received = mutableListOf<Int>()
        transport.onMediaPacket = { received += it.single().toInt() }
        transport.start()
        monitor.available(network("wifi"))
        peer.observer.onConnected(PeerRoute.DIRECT)

        peer.observer.onMediaPacket(6, byteArrayOf(1))
        peer.observer.onMediaPacket(7, byteArrayOf(2))
        peer.observer.onDisconnected()
        peer.observer.onMediaPacket(7, byteArrayOf(3))

        assertEquals(listOf(2), received)
    }

    @Test
    fun disconnectedPeerUsesBoundedTimerDrivenRecovery() {
        val clock = FakeClock(1_000)
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val transport = fixture(peer, monitor, clock)
        transport.start()
        monitor.available(network("wifi"))
        peer.observer.onDisconnected()

        transport.tick()
        assertEquals(0, peer.iceRestarts)
        clock.now += 500
        transport.tick()
        assertEquals(1, peer.iceRestarts)
        clock.now += 1_000
        transport.tick()
        assertEquals(2, peer.iceRestarts)
    }

    @Test
    fun weakNetworkAppliesAdaptiveProfile() {
        val peer = FakePeerEngine()
        val transport = fixture(peer = peer)
        transport.start()
        val poor = WebRtcStats(2_000, 9.0, 350, 70)

        peer.observer.onStats(poor)
        peer.observer.onStats(poor)

        assertEquals(VideoProfile(1600, 900, 45, 7_000), peer.profiles.last())
    }

    @Test
    fun closeReleasesNetworkCallbackAndPeerExactlyOnce() {
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val transport = fixture(peer, monitor)
        transport.start()

        transport.close()
        transport.close()

        assertEquals(1, monitor.closeCalls)
        assertEquals(1, peer.closeCalls)
        assertEquals(InternetTransportState.CLOSED, transport.state)
        assertFalse(transport.sendControl(byteArrayOf(1)))
    }

    @Test
    fun rejectsTurnServerWithoutCredentials() {
        assertThrows(IllegalArgumentException::class.java) {
            IceServer(listOf("turns:relay.example.test:5349"))
        }
    }

    private fun fixture(
        peer: FakePeerEngine = FakePeerEngine(),
        monitor: FakeNetworkMonitor = FakeNetworkMonitor(),
        clock: FakeClock = FakeClock(0),
        events: MutableList<InternetTransportEvent> = mutableListOf(),
    ) = WebRtcInternetTransport(
        configuration =
            PeerConfiguration(
                iceServers =
                    listOf(
                        IceServer(listOf("stun:stun.example.test:3478")),
                        IceServer(listOf("turns:relay.example.test:5349"), "device", "ephemeral-secret"),
                    ),
                sessionId = "session-1",
                sessionEpoch = 7,
            ),
        peerEngine = peer,
        networkMonitor = monitor,
        clock = clock,
        eventSink = events::add,
    )

    private fun network(id: String) =
        NetworkSnapshot(id, validated = true, metered = false, transports = setOf(NetworkTransport.WIFI))
}

private class FakeClock(var now: Long) : MonotonicClock {
    override fun nowMillis(): Long = now
}

private class FakeNetworkMonitor : NetworkMonitor {
    private lateinit var listener: NetworkMonitor.Listener
    var closeCalls = 0

    override fun start(listener: NetworkMonitor.Listener) {
        this.listener = listener
    }

    fun available(network: NetworkSnapshot) = listener.onAvailable(network)

    fun lost(id: String) = listener.onLost(id)

    override fun close() {
        closeCalls++
    }
}

private class FakePeerEngine(
    override val controlSemantics: DataChannelSemantics = DataChannelSemantics.RELIABLE_CONTROL,
    override val mediaSemantics: DataChannelSemantics = DataChannelSemantics.LATEST_MEDIA,
    private val startFailure: Throwable? = null,
    private var iceRestartFailuresRemaining: Int = 0,
) : WebRtcPeerEngine {
    lateinit var observer: WebRtcPeerEngine.Observer
    var started = false
    var iceRestartCalls = 0
    var iceRestarts = 0
    var closeCalls = 0
    val profiles = mutableListOf<VideoProfile>()
    val controlPayloads = mutableListOf<ByteArray>()
    val mediaPayloads = mutableListOf<ByteArray>()

    override fun start(
        configuration: PeerConfiguration,
        observer: WebRtcPeerEngine.Observer,
    ) {
        startFailure?.let { throw it }
        started = true
        this.observer = observer
    }

    override fun sendControl(payload: ByteArray): Boolean = controlPayloads.add(payload)

    override fun sendMedia(payload: ByteArray): Boolean = mediaPayloads.add(payload)

    override fun restartIce() {
        iceRestartCalls++
        if (iceRestartFailuresRemaining > 0) {
            iceRestartFailuresRemaining--
            throw IllegalStateException("ICE restart failed")
        }
        iceRestarts++
    }

    override fun applyVideoProfile(profile: VideoProfile) {
        profiles.add(profile)
    }

    override fun close() {
        closeCalls++
    }
}
