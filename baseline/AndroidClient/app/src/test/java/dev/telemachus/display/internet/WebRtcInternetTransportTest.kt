package dev.telemachus.display.internet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class WebRtcInternetTransportTest {
    @Test
    fun productionChannelLabelsMatchTheCrossPlatformContract() {
        assertEquals("vibescreen.control.v1", AndroidWebRtcPeerEngine.CONTROL_CHANNEL_LABEL)
        assertEquals("vibescreen.media.v1", AndroidWebRtcPeerEngine.MEDIA_CHANNEL_LABEL)
        assertEquals("vibescreen.audio.v1", AndroidWebRtcPeerEngine.AUDIO_CHANNEL_LABEL)
        assertEquals("vibescreen.bulk.v1", AndroidWebRtcPeerEngine.BULK_CHANNEL_LABEL)
        assertEquals(
            listOf(
                AndroidWebRtcPeerEngine.CONTROL_CHANNEL_LABEL,
                AndroidWebRtcPeerEngine.MEDIA_CHANNEL_LABEL,
                AndroidWebRtcPeerEngine.AUDIO_CHANNEL_LABEL,
                AndroidWebRtcPeerEngine.BULK_CHANNEL_LABEL,
            ),
            WebRtcDataChannelKind.entries.map { it.label },
        )
    }

    @Test
    fun dataChannelKindsDefineProtocolV1ReliabilityAndRecordLimits() {
        assertEquals(DataChannelSemantics.RELIABLE_CONTROL, WebRtcDataChannelKind.CONTROL.semantics)
        assertEquals(DataChannelSemantics.LATEST_MEDIA, WebRtcDataChannelKind.MEDIA.semantics)
        assertEquals(DataChannelSemantics.LATEST_AUDIO, WebRtcDataChannelKind.AUDIO.semantics)
        assertEquals(DataChannelSemantics.RELIABLE_BULK, WebRtcDataChannelKind.BULK.semantics)
        assertEquals(SessionChannel.AUDIO, WebRtcDataChannelKind.fromLabel("vibescreen.audio.v1")?.sessionChannel)
        assertEquals(SessionChannel.BULK, WebRtcDataChannelKind.fromLabel("vibescreen.bulk.v1")?.sessionChannel)
        assertEquals(256 * 1024, WebRtcDataChannelKind.AUDIO.maximumEncryptedRecordBytes)
        assertEquals(4 * 1024 * 1024, WebRtcDataChannelKind.BULK.maximumEncryptedRecordBytes)
    }

    @Test
    fun validatesChannelSemanticsBeforeStarting() {
        val peer = FakePeerEngine(
            dataChannelSemantics = WebRtcDataChannelKind.entries.associateWith { kind ->
                if (kind == WebRtcDataChannelKind.AUDIO) DataChannelSemantics.RELIABLE_CONTROL else kind.semantics
            },
        )
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
    fun keepsProtocolV1RecordsOnSeparateEnginePaths() {
        val peer = FakePeerEngine()
        val transport = fixture(peer = peer)
        transport.start()
        peer.observer.onConnected(PeerRoute.DIRECT)

        assertTrue(transport.sendControl(byteArrayOf(1)))
        assertTrue(transport.sendMedia(OutboundMediaFrame.single(byteArrayOf(2))))
        assertTrue(transport.sendAudioRecord(byteArrayOf(3)))
        assertTrue(transport.sendBulkRecord(byteArrayOf(4)))
        assertEquals(listOf(1.toByte()), peer.controlPayloads.map { it.single() })
        assertEquals(listOf(2.toByte()), peer.mediaPayloads.map { it.single() })
        assertEquals(listOf(3.toByte()), peer.audioPayloads.map { it.single() })
        assertEquals(listOf(4.toByte()), peer.bulkPayloads.map { it.single() })
    }

    @Test
    fun bulkBackpressureFailurePropagatesFromPeerEngine() {
        val peer = FakePeerEngine(acceptBulkRecords = false)
        val transport = fixture(peer = peer)
        transport.start()
        peer.observer.onConnected(PeerRoute.DIRECT)

        assertFalse(transport.sendBulkRecord(byteArrayOf(4)))
        assertTrue(peer.bulkPayloads.isEmpty())
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
    fun candidatePairArrivesLateThenRouteChangesWithoutRepeatingSelection() {
        val peer = FakePeerEngine()
        val events = mutableListOf<InternetTransportEvent>()
        val transport = fixture(peer = peer, events = events)
        transport.start()

        assertTrue(events.filterIsInstance<InternetTransportEvent.RouteSelected>().isEmpty())
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.observer.onRouteChanged(PeerRoute.RELAY)
        peer.observer.onRouteChanged(PeerRoute.RELAY)

        assertEquals(listOf(InternetTransportEvent.RouteSelected(PeerRoute.DIRECT)), events.filterIsInstance<InternetTransportEvent.RouteSelected>())
        assertEquals(listOf(InternetTransportEvent.RouteUpdated(PeerRoute.RELAY)), events.filterIsInstance<InternetTransportEvent.RouteUpdated>())
        assertEquals(InternetTransportState.CONNECTED_RELAY, transport.state)
    }

    @Test
    fun concurrentRepeatedConnectedCallbacksEmitOneSessionSelection() {
        val peer = FakePeerEngine()
        val events = CopyOnWriteArrayList<InternetTransportEvent>()
        val transport = fixture(peer = peer, events = events)
        transport.start()
        val executor = Executors.newFixedThreadPool(16)
        val ready = CountDownLatch(16)
        val start = CountDownLatch(1)
        repeat(16) { index ->
            executor.execute {
                ready.countDown()
                start.await()
                peer.observer.onConnected(if (index % 2 == 0) PeerRoute.DIRECT else PeerRoute.RELAY)
            }
        }
        assertTrue(ready.await(2, TimeUnit.SECONDS))
        start.countDown()
        executor.shutdown()
        assertTrue(executor.awaitTermination(2, TimeUnit.SECONDS))

        assertEquals(1, events.filterIsInstance<InternetTransportEvent.RouteSelected>().size)
        assertTrue(events.filterIsInstance<InternetTransportEvent.RouteUpdated>().size <= 15)
    }

    @Test
    fun requestsFreshSessionWhenValidatedNetworkChangesAndThrottlesDuplicates() {
        val clock = FakeClock(10_000)
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val events = mutableListOf<InternetTransportEvent>()
        val transport = fixture(peer, monitor, clock, events)
        transport.start()
        monitor.available(network("wifi"))
        peer.observer.onConnected(PeerRoute.DIRECT)

        monitor.available(network("cellular"))
        monitor.available(network("vpn"))

        assertEquals(1, events.filterIsInstance<InternetTransportEvent.FreshSessionRequested>().size)
        assertEquals(0, peer.iceRestarts)
        clock.now += 5_000
        transport.tick()
        assertEquals(2, events.filterIsInstance<InternetTransportEvent.FreshSessionRequested>().size)
        assertEquals(0, peer.iceRestarts)
    }

    @Test
    fun suspendsOnNetworkLossAndRecoversImmediatelyOnValidatedNetwork() {
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val events = mutableListOf<InternetTransportEvent>()
        val transport = fixture(peer, monitor, events = events)
        transport.start()
        monitor.available(network("wifi"))
        peer.observer.onConnected(PeerRoute.DIRECT)

        monitor.lost("wifi")
        assertEquals(InternetTransportState.SUSPENDED, transport.state)
        monitor.available(network("cellular"))

        assertEquals(InternetTransportState.RECOVERING, transport.state)
        assertEquals(1, events.filterIsInstance<InternetTransportEvent.FreshSessionRequested>().size)
        assertEquals(0, peer.iceRestarts)
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
        val events = mutableListOf<InternetTransportEvent>()
        val transport = fixture(peer, monitor, clock, events)
        transport.start()
        monitor.available(network("wifi"))

        peer.observer.onDisconnected()
        clock.now += 400
        peer.observer.onDisconnected()
        clock.now += 100
        transport.tick()

        assertEquals(1, events.filterIsInstance<InternetTransportEvent.FreshSessionRequested>().size)
        assertEquals(0, peer.iceRestarts)
    }

    @Test
    fun relayOnlyPolicyRequiresTurnConfiguration() {
        assertThrows(IllegalArgumentException::class.java) {
            PeerConfiguration(
                iceServers = listOf(IceServer(listOf("stun:stun.example.test:3478"))),
                sessionId = "session-1",
                sessionEpoch = 1,
                iceTransportPolicy = IceTransportPolicy.RELAY_ONLY,
            )
        }
    }

    @Test
    fun dropsPacketsFromOldEpochAndWhileRecovering() {
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val transport = fixture(peer, monitor)
        val received = mutableListOf<Int>()
        val receivedAudio = mutableListOf<Int>()
        val receivedBulk = mutableListOf<Int>()
        transport.onMediaPacket = { received += it.single().toInt() }
        transport.onAudioRecord = { receivedAudio += it.single().toInt() }
        transport.onBulkRecord = { receivedBulk += it.single().toInt() }
        transport.start()
        monitor.available(network("wifi"))
        peer.observer.onConnected(PeerRoute.DIRECT)

        peer.observer.onMediaPacket(6, byteArrayOf(1))
        peer.observer.onMediaPacket(7, byteArrayOf(2))
        peer.observer.onAudioRecord(7, byteArrayOf(4))
        peer.observer.onBulkRecord(7, byteArrayOf(5))
        peer.observer.onDisconnected()
        peer.observer.onMediaPacket(7, byteArrayOf(3))
        peer.observer.onAudioRecord(7, byteArrayOf(6))
        peer.observer.onBulkRecord(7, byteArrayOf(7))

        assertEquals(listOf(2), received)
        assertEquals(listOf(4), receivedAudio)
        assertEquals(listOf(5), receivedBulk)
    }

    @Test
    fun disconnectedPeerUsesBoundedTimerDrivenRecovery() {
        val clock = FakeClock(1_000)
        val peer = FakePeerEngine()
        val monitor = FakeNetworkMonitor()
        val events = mutableListOf<InternetTransportEvent>()
        val transport = fixture(peer, monitor, clock, events)
        transport.start()
        monitor.available(network("wifi"))
        peer.observer.onDisconnected()

        transport.tick()
        assertEquals(0, events.filterIsInstance<InternetTransportEvent.FreshSessionRequested>().size)
        clock.now += 500
        transport.tick()
        assertEquals(1, events.filterIsInstance<InternetTransportEvent.FreshSessionRequested>().size)
        clock.now += 1_000
        transport.tick()
        assertEquals(2, events.filterIsInstance<InternetTransportEvent.FreshSessionRequested>().size)
        assertEquals(0, peer.iceRestarts)
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
    override val dataChannelSemantics: Map<WebRtcDataChannelKind, DataChannelSemantics> =
        WebRtcDataChannelKind.entries.associateWith { it.semantics },
    private val startFailure: Throwable? = null,
    private val acceptBulkRecords: Boolean = true,
) : WebRtcPeerEngine {
    lateinit var observer: WebRtcPeerEngine.Observer
    var started = false
    var iceRestartCalls = 0
    var iceRestarts = 0
    var closeCalls = 0
    val profiles = mutableListOf<VideoProfile>()
    val controlPayloads = mutableListOf<ByteArray>()
    val mediaPayloads = mutableListOf<ByteArray>()
    val audioPayloads = mutableListOf<ByteArray>()
    val bulkPayloads = mutableListOf<ByteArray>()

    override fun start(
        configuration: PeerConfiguration,
        observer: WebRtcPeerEngine.Observer,
    ) {
        startFailure?.let { throw it }
        started = true
        this.observer = observer
    }

    override fun sendControl(payload: ByteArray): Boolean = controlPayloads.add(payload)

    override fun sendMedia(frame: OutboundMediaFrame): Boolean {
        mediaPayloads += frame.records.map(ByteArray::copyOf)
        return true
    }

    override fun sendAudioRecord(payload: ByteArray): Boolean = audioPayloads.add(payload)

    override fun sendBulkRecord(payload: ByteArray): Boolean =
        acceptBulkRecords && bulkPayloads.add(payload)

    override fun restartIce() {
        iceRestartCalls++
        iceRestarts++
    }

    override fun applyVideoProfile(profile: VideoProfile) {
        profiles.add(profile)
    }

    override fun close() {
        closeCalls++
    }
}
