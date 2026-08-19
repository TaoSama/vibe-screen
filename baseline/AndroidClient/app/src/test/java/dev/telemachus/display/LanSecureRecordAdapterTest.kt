package dev.telemachus.display

import dev.telemachus.display.internet.PeerRole
import dev.telemachus.display.internet.SessionChannel
import dev.telemachus.display.internet.security.AndroidSessionPacketCipher
import dev.telemachus.display.internet.security.ecdh
import dev.telemachus.display.internet.security.generateEphemeral
import dev.telemachus.display.internet.security.publicPoint
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class LanSecureRecordAdapterTest {
    @Test
    fun negotiationRequestAndResponseRoundTrip() {
        val device = generateEphemeral(java.security.SecureRandom())
        val host = generateEphemeral(java.security.SecureRandom())
        val request = LanSecureRecordNegotiation.encodeRequest(publicPoint(device), allowLegacyFallback = false)
        val parsedRequest = LanSecureRecordNegotiation.decodeRequest(request)
        assertArrayEquals(publicPoint(device), parsedRequest.publicKey)
        assertFalse(parsedRequest.allowLegacyFallback)

        val response = LanSecureRecordNegotiation.encodeResponse(
            publicPoint(host),
            encrypted = true,
            explicitLegacyFallback = false,
        )
        val parsedResponse = LanSecureRecordNegotiation.decodeResponse(response)
        assertArrayEquals(publicPoint(host), parsedResponse.publicKey)
        assertTrue(parsedResponse.encrypted)
        assertFalse(parsedResponse.legacy)
    }

    @Test
    fun legacyFallbackMustBeExplicit() {
        val publicKey = publicPoint(generateEphemeral(java.security.SecureRandom()))
        assertThrows(IllegalArgumentException::class.java) {
            LanSecureRecordNegotiation.encodeResponse(publicKey, encrypted = false, explicitLegacyFallback = false)
        }
        assertThrows(IllegalArgumentException::class.java) {
            LanSecureRecordNegotiation.encodeResponse(publicKey, encrypted = true, explicitLegacyFallback = true)
        }

        val legacy = LanSecureRecordNegotiation.encodeResponse(
            publicKey,
            encrypted = false,
            explicitLegacyFallback = true,
        )
        val parsed = LanSecureRecordNegotiation.decodeResponse(legacy)
        assertFalse(parsed.encrypted)
        assertTrue(parsed.legacy)
    }

    @Test
    fun recordsProtectControlAndMediaDirections() {
        val pair = makePair()
        val control = pair.device.seal(SessionChannel.CONTROL, byteArrayOf(1, 2, 3))
        val media = pair.host.seal(SessionChannel.MEDIA, byteArrayOf(4, 5, 6))

        assertArrayEquals(byteArrayOf(1, 2, 3), pair.host.open(SessionChannel.CONTROL, control))
        assertArrayEquals(byteArrayOf(4, 5, 6), pair.device.open(SessionChannel.MEDIA, media))
        assertThrows(LanSecureRecordException::class.java) { pair.host.open(SessionChannel.MEDIA, control) }
        assertThrows(LanSecureRecordException::class.java) { pair.device.open(SessionChannel.CONTROL, media) }
    }

    @Test
    fun replayTamperAndWrongSessionFailClosed() {
        val pair = makePair()
        val wrong = makePair(sessionId = "lan-session-other")
        val record = pair.host.seal(SessionChannel.MEDIA, byteArrayOf(7))

        assertArrayEquals(byteArrayOf(7), pair.device.open(SessionChannel.MEDIA, record))
        assertThrows(LanSecureRecordException::class.java) { pair.device.open(SessionChannel.MEDIA, record) }
        assertThrows(LanSecureRecordException::class.java) { wrong.device.open(SessionChannel.MEDIA, record) }

        val tampered = pair.host.seal(SessionChannel.MEDIA, byteArrayOf(8))
        tampered[tampered.lastIndex] = (tampered[tampered.lastIndex].toInt() xor 1).toByte()
        assertThrows(LanSecureRecordException::class.java) { pair.device.open(SessionChannel.MEDIA, tampered) }
    }

    @Test
    fun clientNegotiationRejectsImplicitLegacyFallback() {
        val hostPublic = publicPoint(generateEphemeral(java.security.SecureRandom()))
        val legacyResponse = LanSecureRecordNegotiation.encodeResponse(
            hostPublic,
            encrypted = false,
            explicitLegacyFallback = true,
        )
        val output = ByteArrayOutputStream()

        assertThrows(LanSecureRecordException::class.java) {
            negotiateLanSecureRecordsAsClient(
                input = ByteArrayInputStream(legacyResponse),
                output = output,
                token = ByteArray(32),
            )
        }
    }

    @Test
    fun outputAndInputStreamsFrameEncryptedRecords() {
        val pair = makePair()
        val raw = ByteArrayOutputStream()
        val output = LanSecureRecordOutputStream(raw, pair.device)
        output.write(byteArrayOf(1, 2, 3))
        output.write(byteArrayOf(4, 5))
        output.flush()

        val input = LanSecureRecordInputStream(ByteArrayInputStream(raw.toByteArray()), pair.host)
        assertEquals(1, input.read())
        assertEquals(2, input.read())
        assertEquals(3, input.read())
        assertEquals(4, input.read())
        assertEquals(5, input.read())
    }

    @Test
    fun inputStreamAcceptsHostMediaRecords() {
        val pair = makePair()
        val mediaRecord = pair.host.seal(SessionChannel.MEDIA, byteArrayOf(9, 8))
        val raw = ByteArrayOutputStream()
        raw.write(java.nio.ByteBuffer.allocate(4).putInt(mediaRecord.size).array())
        raw.write(mediaRecord)

        val input = LanSecureRecordInputStream(ByteArrayInputStream(raw.toByteArray()), pair.device)
        assertEquals(9, input.read())
        assertEquals(8, input.read())
    }

    @Test
    fun inputStreamOpensTheDeclaredRecordChannel() {
        val pair = makePair()
        val controlRecord = pair.device.seal(SessionChannel.CONTROL, byteArrayOf(1))
        val mediaRecord = pair.host.seal(SessionChannel.MEDIA, byteArrayOf(2))

        assertEquals(SessionChannel.CONTROL, AndroidSessionPacketCipher.declaredSessionChannel(controlRecord))
        assertEquals(SessionChannel.MEDIA, AndroidSessionPacketCipher.declaredSessionChannel(mediaRecord))
        assertArrayEquals(byteArrayOf(1), pair.host.openDeclaredChannel(controlRecord))
        assertArrayEquals(byteArrayOf(2), pair.device.openDeclaredChannel(mediaRecord))
    }

    private fun makePair(sessionId: String = "lan-session-1"): PairSessions {
        val token = ByteArray(32) { it.toByte() }
        val hostKey = generateEphemeral(java.security.SecureRandom())
        val deviceKey = generateEphemeral(java.security.SecureRandom())
        val hostPublic = publicPoint(hostKey)
        val devicePublic = publicPoint(deviceKey)
        val context = LanSecureRecordSession.transcriptContext(sessionId, hostPublic, devicePublic)
        val hostSecret = ecdh(hostKey.private, devicePublic)
        val deviceSecret = ecdh(deviceKey.private, hostPublic)
        assertArrayEquals(hostSecret, deviceSecret)
        return PairSessions(
            host = LanSecureRecordSession(PeerRole.HOST, sessionId, 1, hostSecret, token, context),
            device = LanSecureRecordSession(PeerRole.DEVICE, sessionId, 1, deviceSecret, token, context),
        )
    }

    private data class PairSessions(
        val host: LanSecureRecordSession,
        val device: LanSecureRecordSession,
    )
}
