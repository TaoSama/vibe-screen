package dev.telemachus.display.internet.security

import dev.telemachus.display.internet.PeerRole
import dev.telemachus.display.internet.SessionChannel
import java.nio.ByteBuffer
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ChannelRecordSecurityTest {
    @Test
    fun sharedFixtureMatchesInitialRotationAndAdvancedRecords() {
        val fixture = SharedChannelSecurityFixture.load()
        assertEquals("dev.vibescreen.channel-security-fixture/v1", fixture.schema)
        val initial = deriveFixtureKeys(fixture)

        assertEquals(fixture.keyId("initial"), initial.keyId)
        assertArrayEquals(fixture.keyMaterial("initial"), initial.material())
        assertEquals(8, initial.allBuffers().map(ByteArray::toHex).toSet().size)
        val rotated = TrafficKeyDerivation.rotate(initial, 2, fixture.input("rotation_nonce"))
        assertEquals(fixture.keyId("rotated"), rotated.keyId)
        assertArrayEquals(fixture.keyMaterial("rotated"), rotated.material())
        assertEquals(8, rotated.allBuffers().map(ByteArray::toHex).toSet().size)

        val host = fixtureCipher(fixture, PeerRole.HOST, deriveFixtureKeys(fixture))
        val device = fixtureCipher(fixture, PeerRole.DEVICE, deriveFixtureKeys(fixture))
        val records = listOf(
            FixtureRecord(fixture.record("host_control"), SessionChannel.CONTROL, host, device),
            FixtureRecord(fixture.record("device_media"), SessionChannel.MEDIA, device, host),
            FixtureRecord(fixture.record("host_audio"), SessionChannel.AUDIO, host, device),
            FixtureRecord(fixture.record("device_bulk"), SessionChannel.BULK, device, host),
        )
        records.forEach { record ->
            assertArrayEquals(record.fixture.encoded, record.sender.seal(record.channel, record.fixture.payload))
            SessionChannel.values().filterNot { it == record.channel }.forEach { wrongChannel ->
                assertNull(record.receiver.open(wrongChannel, record.fixture.encoded))
            }
            assertArrayEquals(record.fixture.payload, record.receiver.open(record.channel, record.fixture.encoded))
        }
    }

    @Test
    fun authenticatedRecordsCannotBeRelabeledAcrossChannels() {
        val fixture = SharedChannelSecurityFixture.load()
        val host = fixtureCipher(fixture, PeerRole.HOST, deriveFixtureKeys(fixture))
        val device = fixtureCipher(fixture, PeerRole.DEVICE, deriveFixtureKeys(fixture))
        val records = listOf(
            Triple(fixture.record("host_control").encoded, SessionChannel.CONTROL, device),
            Triple(fixture.record("device_media").encoded, SessionChannel.MEDIA, host),
            Triple(fixture.record("host_audio").encoded, SessionChannel.AUDIO, device),
            Triple(fixture.record("device_bulk").encoded, SessionChannel.BULK, host),
        )

        records.forEach { (record, originalChannel, receiver) ->
            SessionChannel.values().filterNot { it == originalChannel }.forEach { relabeledChannel ->
                val relabeled = record.copyOf()
                relabeled[HEADER_CHANNEL_OFFSET] = relabeledChannel.securityWireValue.toByte()
                ByteBuffer.wrap(relabeled, NONCE_OFFSET, Int.SIZE_BYTES).putInt(relabeledChannel.securityWireValue)
                assertNull(receiver.open(relabeledChannel, relabeled))
            }
        }
    }

    @Test
    fun audioAllowsBoundedReorderingWhileBulkIsStrictlyOrdered() {
        val host = counterCipher(PeerRole.HOST)
        val device = counterCipher(PeerRole.DEVICE)
        val audioOne = host.seal(SessionChannel.AUDIO, byteArrayOf(1))
        val audioTwo = host.seal(SessionChannel.AUDIO, byteArrayOf(2))
        val bulkOne = host.seal(SessionChannel.BULK, byteArrayOf(3))
        val bulkTwo = host.seal(SessionChannel.BULK, byteArrayOf(4))

        assertArrayEquals(byteArrayOf(2), device.open(SessionChannel.AUDIO, audioTwo))
        assertArrayEquals(byteArrayOf(1), device.open(SessionChannel.AUDIO, audioOne))
        assertNull(device.open(SessionChannel.AUDIO, audioTwo))
        assertArrayEquals(byteArrayOf(4), device.open(SessionChannel.BULK, bulkTwo))
        assertNull(device.open(SessionChannel.BULK, bulkOne))
        assertNull(device.open(SessionChannel.MEDIA, audioOne))
    }

    @Test
    fun everyDirectionalChannelCombinationRoundTrips() {
        val host = counterCipher(PeerRole.HOST)
        val device = counterCipher(PeerRole.DEVICE)

        SessionChannel.values().forEach { channel ->
            val hostPayload = byteArrayOf(channel.securityWireValue.toByte(), 1)
            val devicePayload = byteArrayOf(channel.securityWireValue.toByte(), 2)
            assertArrayEquals(hostPayload, device.open(channel, host.seal(channel, hostPayload)))
            assertArrayEquals(devicePayload, host.open(channel, device.seal(channel, devicePayload)))
        }
        host.close()
        device.close()
    }

    @Test
    fun invalidAllocatedNoncesFailClosedBeforeEncryption() {
        listOf(
            byteArrayOf(0, 0, 0, 3),
            nonce(channel = 4, sequence = 1),
            nonce(channel = 3, sequence = 0),
        ).forEach { invalidNonce ->
            val cipher = cipher(PeerRole.HOST, TrafficKeyDerivation.initial(keysInput, keysInput, keysInput)) {
                invalidNonce
            }
            assertThrows(IllegalStateException::class.java) {
                cipher.seal(SessionChannel.AUDIO, byteArrayOf(1))
            }
        }
    }

    @Test
    fun rotationAndCloseClearOwnedKeyBuffersAndRejectOldState() {
        val initial = TrafficKeyDerivation.initial(keysInput, keysInput, keysInput)
        val cipher = counterCipher(PeerRole.HOST, initialKeys = initial)

        cipher.rotateTrafficKeys(ByteArray(16) { it.toByte() })
        assertTrue(initial.allBuffers().all { it.isZeroized() })
        cipher.close()
        assertThrows(IllegalStateException::class.java) {
            cipher.seal(SessionChannel.AUDIO, byteArrayOf(1))
        }
        assertNull(cipher.open(SessionChannel.AUDIO, byteArrayOf()))
        assertThrows(IllegalStateException::class.java) {
            cipher.rotateTrafficKeys(ByteArray(16))
        }
    }

    @Test
    fun failedRotationPreservesCurrentKeysAndRecordUsability() {
        val initial = TrafficKeyDerivation.initial(keysInput, keysInput, keysInput)
        val host = counterCipher(PeerRole.HOST, initialKeys = initial)
        val device = counterCipher(PeerRole.DEVICE)

        assertThrows(IllegalArgumentException::class.java) {
            host.rotateTrafficKeys(ByteArray(15))
        }

        assertTrue(initial.allBuffers().all { buffer -> buffer.any { it != 0.toByte() } })
        val record = host.seal(SessionChannel.BULK, byteArrayOf(5, 6))
        assertArrayEquals(byteArrayOf(5, 6), device.open(SessionChannel.BULK, record))
        host.close()
        device.close()
    }

    private fun deriveFixtureKeys(fixture: SharedChannelSecurityFixture): SessionTrafficKeys =
        TrafficKeyDerivation.initial(
            fixture.input("shared_secret"),
            fixture.input("bootstrap_secret"),
            fixture.input("context"),
        )

    private fun fixtureCipher(
        fixture: SharedChannelSecurityFixture,
        role: PeerRole,
        initialKeys: SessionTrafficKeys,
    ): AndroidSessionPacketCipher = cipher(role, initialKeys, fixture.sessionId, fixture.sessionEpoch) { channel ->
        nonce(channel, 1)
    }

    private fun counterCipher(
        role: PeerRole,
        initialKeys: SessionTrafficKeys = TrafficKeyDerivation.initial(keysInput, keysInput, keysInput),
    ): AndroidSessionPacketCipher {
        val counters = mutableMapOf<Int, Long>()
        return cipher(role, initialKeys) { channel ->
            val sequence = (counters[channel] ?: 0) + 1
            counters[channel] = sequence
            nonce(channel, sequence)
        }
    }

    private fun cipher(
        role: PeerRole,
        initialKeys: SessionTrafficKeys,
        sessionId: String = "advanced-channel-test",
        sessionEpoch: Long = 9,
        nonceAllocator: (Int) -> ByteArray,
    ) = AndroidSessionPacketCipher(
        sessionId = sessionId,
        sessionEpoch = sessionEpoch,
        localRole = role,
        initialKeys = initialKeys,
        sealWithActiveEpoch = { _, channel, _, _, operation -> operation(nonceAllocator(channel)) },
        openWithActiveEpoch = { _, operation -> operation() },
        rotateKeys = { current, updateNonce ->
            TrafficKeyDerivation.rotate(current, current.keyEpoch + 1, updateNonce)
        },
    )

    private fun nonce(channel: Int, sequence: Long): ByteArray =
        ByteBuffer.allocate(12).putInt(channel).putLong(sequence).array()

    private fun SessionTrafficKeys.material(): ByteArray =
        allBuffers().fold(ByteArray(0)) { material, key -> material + key }

    private fun SessionTrafficKeys.allBuffers(): List<ByteArray> = listOf(
        hostControl, deviceControl, hostMedia, deviceMedia,
        hostAudio, deviceAudio, hostBulk, deviceBulk,
    )

    private fun ByteArray.isZeroized(): Boolean = all { it == 0.toByte() }

    private val SessionChannel.securityWireValue: Int
        get() =
            when (this) {
                SessionChannel.CONTROL -> 1
                SessionChannel.MEDIA -> 2
                SessionChannel.AUDIO -> 3
                SessionChannel.BULK -> 4
            }

    private data class FixtureRecord(
        val fixture: SharedChannelSecurityFixture.Record,
        val channel: SessionChannel,
        val sender: AndroidSessionPacketCipher,
        val receiver: AndroidSessionPacketCipher,
    )

    companion object {
        private const val HEADER_CHANNEL_OFFSET = 38
        private const val NONCE_OFFSET = 39
        private val keysInput = ByteArray(32) { 3 }
    }
}

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
