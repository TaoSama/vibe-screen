package dev.telemachus.display.internet.security

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dev.telemachus.display.internet.PeerRole
import dev.telemachus.display.internet.SessionChannel
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest

/**
 * Cross-platform AUDIO/BULK channel-security fixture.
 *
 * The fixture pins the session key-derivation inputs, epoch, channel, sender,
 * sequence, and plaintext. Both Swift and Android derive the same directional
 * traffic keys and seal the same plaintext with AES-256-GCM, so the sealed
 * records must match byte-for-byte.
 */
class ChannelSecurityAudioBulkFixtureTest {
    private val fixture = loadFixture()

    @Test
    fun hostAndDeviceSealAudioAndBulkRecordsMatchFixture() {
        val session = fixture.session
        val keys = TrafficKeyDerivation.initial(
            session.sharedSecret,
            session.bootstrapSecret,
            session.context,
        )
        assertEquals(session.keyEpoch, keys.keyEpoch)

        val host = cipher(PeerRole.HOST, session, keys)
        val device = cipher(PeerRole.DEVICE, session, keys)

        for (record in fixture.records) {
            val channel = when (record.channel) {
                "AUDIO" -> SessionChannel.AUDIO
                "BULK" -> SessionChannel.BULK
                else -> error("unsupported channel ${record.channel}")
            }
            val sealed = when (record.sender) {
                "HOST" -> host.seal(channel, record.plaintext)
                "DEVICE" -> device.seal(channel, record.plaintext)
                else -> error("unsupported sender ${record.sender}")
            }
            assertArrayEquals(
                "sealed record mismatch for ${record.name}",
                record.record,
                sealed,
            )
        }
    }

    @Test
    fun hostAndDeviceOpenFixtureRecordsReturnPlaintext() {
        val session = fixture.session
        val keys = TrafficKeyDerivation.initial(
            session.sharedSecret,
            session.bootstrapSecret,
            session.context,
        )

        val host = cipher(PeerRole.HOST, session, keys)
        val device = cipher(PeerRole.DEVICE, session, keys)

        for (record in fixture.records) {
            val channel = when (record.channel) {
                "AUDIO" -> SessionChannel.AUDIO
                "BULK" -> SessionChannel.BULK
                else -> error("unsupported channel ${record.channel}")
            }
            val opened = when (record.sender) {
                "HOST" -> device.open(channel, record.record)
                "DEVICE" -> host.open(channel, record.record)
                else -> error("unsupported sender ${record.sender}")
            }
            assertArrayEquals(
                "opened plaintext mismatch for ${record.name}",
                record.plaintext,
                opened,
            )
        }
    }

    @Test
    fun fixtureDerivedKeysMatchDeclaredKeys() {
        val session = fixture.session
        val keys = TrafficKeyDerivation.initial(
            session.sharedSecret,
            session.bootstrapSecret,
            session.context,
        )
        assertEquals(session.keyEpoch, keys.keyEpoch)
        assertArrayEquals(session.keys["host_audio"], keys.hostAudio)
        assertArrayEquals(session.keys["device_audio"], keys.deviceAudio)
        assertArrayEquals(session.keys["host_bulk"], keys.hostBulk)
        assertArrayEquals(session.keys["device_bulk"], keys.deviceBulk)
    }

    @Test
    fun fixtureSessionIdHashMatchesDeclaredHash() {
        val session = fixture.session
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(session.sessionIdentifier.toByteArray(StandardCharsets.UTF_8))
            .copyOf(16)
        assertArrayEquals(session.sessionIdHash, digest)
    }

    @Test
    fun crossChannelOpenIsRejected() {
        val session = fixture.session
        val keys = TrafficKeyDerivation.initial(
            session.sharedSecret,
            session.bootstrapSecret,
            session.context,
        )
        val device = cipher(PeerRole.DEVICE, session, keys)

        val hostAudio = fixture.record("host_audio_seq1")
        val hostBulk = fixture.record("host_bulk_seq1")

        // An AUDIO record must not open on the BULK channel.
        assertNull(device.open(SessionChannel.BULK, hostAudio.record))
        // A BULK record must not open on the AUDIO channel.
        assertNull(device.open(SessionChannel.AUDIO, hostBulk.record))
    }

    private fun cipher(
        role: PeerRole,
        session: FixtureSession,
        keys: SessionTrafficKeys,
    ): AndroidSessionPacketCipher {
        val counters = mutableMapOf<String, Long>()
        return AndroidSessionPacketCipher(
            sessionId = session.sessionIdentifier,
            sessionEpoch = session.sessionEpoch,
            localRole = role,
            initialKeys = keys,
            sealWithActiveEpoch = { _, channel, sender, keyEpoch, operation ->
                val counterKey = "$channel:$sender:$keyEpoch"
                val sequence = (counters[counterKey] ?: 0L) + 1L
                counters[counterKey] = sequence
                val nonce = java.nio.ByteBuffer.allocate(12)
                    .putInt(channel)
                    .putLong(sequence)
                    .array()
                operation(nonce)
            },
            openWithActiveEpoch = { _, operation -> operation() },
            rotateKeys = { current, updateNonce ->
                TrafficKeyDerivation.rotate(current, current.keyEpoch + 1, updateNonce)
            },
        )
    }

    private data class FixtureSession(
        val sessionIdentifier: String,
        val sessionEpoch: Long,
        val keyEpoch: Long,
        val sessionIdHash: ByteArray,
        val sharedSecret: ByteArray,
        val bootstrapSecret: ByteArray,
        val context: ByteArray,
        val keys: Map<String, ByteArray>,
    )

    private data class FixtureRecord(
        val name: String,
        val channel: String,
        val sender: String,
        val sequence: Long,
        val plaintext: ByteArray,
        val record: ByteArray,
    )

    private data class Fixture(
        val session: FixtureSession,
        val records: List<FixtureRecord>,
    ) {
        fun record(name: String): FixtureRecord =
            records.firstOrNull { it.name == name } ?: error("missing fixture record $name")
    }

    companion object {
        private fun loadFixture(): Fixture {
            val relative = Path.of("contracts", "fixtures", "channel-security", "v1", "audio-bulk-records.json")
            val fixturePath = generateSequence(Path.of(System.getProperty("user.dir")).toAbsolutePath()) { it.parent }
                .map { it.resolve(relative) }
                .firstOrNull(Files::isRegularFile)
                ?: error("Unable to locate channel-security fixture from ${System.getProperty("user.dir")}")
            val root = JsonParser.parseString(String(Files.readAllBytes(fixturePath), StandardCharsets.UTF_8)).asJsonObject

            val sessionJson = root.getAsJsonObject("session")
            val keyDerivation = sessionJson.getAsJsonObject("key_derivation")
            val keysJson = sessionJson.getAsJsonObject("keys")

            val session = FixtureSession(
                sessionIdentifier = sessionJson.get("session_identifier").asString,
                sessionEpoch = sessionJson.get("session_epoch").asLong,
                keyEpoch = sessionJson.get("key_epoch").asLong,
                sessionIdHash = hex(sessionJson.get("session_id_hash").asString),
                sharedSecret = hex(keyDerivation.get("shared_secret").asString),
                bootstrapSecret = hex(keyDerivation.get("bootstrap_secret").asString),
                context = hex(keyDerivation.get("context").asString),
                keys = keysJson.entrySet().associate { (key, value) -> key to hex(value.asString) },
            )

            val records = root.getAsJsonArray("records").map { record ->
                val obj = record.asJsonObject
                FixtureRecord(
                    name = obj.get("name").asString,
                    channel = obj.get("channel").asString,
                    sender = obj.get("sender").asString,
                    sequence = obj.get("sequence").asLong,
                    plaintext = hex(obj.get("plaintext").asString),
                    record = hex(obj.get("record").asString),
                )
            }

            return Fixture(session, records)
        }

        private fun hex(value: String): ByteArray {
            require(value.length % 2 == 0) { "hex string must have even length" }
            return ByteArray(value.length / 2) { i ->
                value.substring(i * 2, i * 2 + 2).toInt(16).toByte()
            }
        }
    }
}
