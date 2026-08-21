package dev.telemachus.display

import com.google.protobuf.ByteString
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class WakeHostTest {
    @Test
    fun magicPacketRepeatsTargetMacAndAppendsSecureOnPassword() {
        val mac = mac(0x01, 0x23, 0x45, 0x67, 0x89, 0xab)
        val password = mac(0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff)

        val packet = WakeHostMagicPacket.build(mac, password)

        assertEquals(WakeHostMagicPacket.BASE_PACKET_BYTES + WakeHostMagicPacket.SECURE_ON_PASSWORD_BYTES, packet.size)
        assertTrue(packet.take(6).all { it == 0xff.toByte() })
        repeat(16) { index ->
            assertArrayEquals(mac.toByteArray(), packet.copyOfRange(6 + index * 6, 12 + index * 6))
        }
        assertArrayEquals(password.toByteArray(), packet.copyOfRange(102, 108))
    }

    @Test
    fun magicPacketRejectsInvalidMacAndSecureOnPassword() {
        assertFailure(WakeHostRequestFailure.INVALID_MAC_ADDRESS) {
            WakeHostMagicPacket.build(ByteString.EMPTY)
        }
        assertFailure(WakeHostRequestFailure.INVALID_MAC_ADDRESS) {
            WakeHostMagicPacket.build(ByteString.copyFrom(ByteArray(6)))
        }
        assertFailure(WakeHostRequestFailure.INVALID_MAC_ADDRESS) {
            WakeHostMagicPacket.build(ByteString.copyFrom(ByteArray(6) { 0xff.toByte() }))
        }
        assertFailure(WakeHostRequestFailure.INVALID_SECURE_ON_PASSWORD) {
            WakeHostMagicPacket.build(mac(1, 2, 3, 4, 5, 6), ByteString.copyFrom(byteArrayOf(1, 2, 3)))
        }
    }

    @Test
    fun decisionDefaultsToDenyAndAllowsExplicitPolicy() {
        val request =
            WakeHostRequestContext(
                requestId = ByteString.copyFrom(byteArrayOf(0x42)),
                targetMacAddress = mac(1, 2, 3, 4, 5, 6),
            )

        assertFailure(WakeHostRequestFailure.POLICY_DENIED) { WakeHostDecision.magicPacket(request) }

        assertEquals(
            WakeHostMagicPacket.BASE_PACKET_BYTES,
            WakeHostDecision.magicPacket(request, StaticWakeHostPolicy(true)).size,
        )
    }

    @Test
    fun decisionRejectsEmptyRequestIdBeforePolicy() {
        val request =
            WakeHostRequestContext(
                requestId = ByteString.EMPTY,
                targetMacAddress = mac(1, 2, 3, 4, 5, 6),
            )

        assertFailure(WakeHostRequestFailure.INVALID_REQUEST_ID) {
            WakeHostDecision.magicPacket(request, StaticWakeHostPolicy(true))
        }
    }

    @Test
    fun sharedSecretPolicyAcceptsSignedRequestOnceAndRejectsReplay() {
        val secret = ByteArray(32) { it.toByte() }
        val request = signedRequest(secret = secret, issuedAt = 1_000L, expiresAt = 1_060L)
        val policy = SharedSecretWakeHostPolicy(secret, nowUnixSeconds = { 1_010L })

        assertTrue(policy.wakeAllowed(request))
        assertEquals(WakeHostRequestFailure.REPLAYED_REQUEST, policy.authorizationFailure(request))
    }

    @Test
    fun sharedSecretPolicyRejectsMalformedExpiredAndTamperedProofs() {
        val secret = ByteArray(32) { it.toByte() }
        val policy = SharedSecretWakeHostPolicy(secret, nowUnixSeconds = { 1_010L })

        val tampered = signedRequest(secret = secret, issuedAt = 1_000L, expiresAt = 1_060L).let {
            it.copy(signature = ByteString.copyFrom(it.signature.toByteArray().also { bytes -> bytes[0] = (bytes[0].toInt() xor 1).toByte() }))
        }
        assertEquals(WakeHostRequestFailure.INVALID_AUTHORIZATION, policy.authorizationFailure(tampered))

        val wrongKey = signedRequest(secret = secret, issuedAt = 1_000L, expiresAt = 1_060L).copy(keyId = "wrong")
        assertEquals(WakeHostRequestFailure.INVALID_AUTHORIZATION, policy.authorizationFailure(wrongKey))

        val shortNonce = signedRequest(secret = secret, issuedAt = 1_000L, expiresAt = 1_060L).copy(nonce = ByteString.copyFrom(byteArrayOf(1)))
        assertEquals(WakeHostRequestFailure.INVALID_AUTHORIZATION, policy.authorizationFailure(shortNonce))

        val expired = signedRequest(secret = secret, issuedAt = 900L, expiresAt = 950L)
        assertEquals(WakeHostRequestFailure.EXPIRED_AUTHORIZATION, policy.authorizationFailure(expired))

        val tooLong = signedRequest(secret = secret, issuedAt = 900L, expiresAt = 1_200L)
        assertEquals(WakeHostRequestFailure.EXPIRED_AUTHORIZATION, policy.authorizationFailure(tooLong))
    }

    @Test
    fun wakeHostProofGoldenVectorMatchesMacHost() {
        val secret = ByteArray(32) { it.toByte() }
        val request = signedRequest(secret = secret, issuedAt = 1_000L, expiresAt = 1_060L)

        assertEquals("630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd", request.keyId)
        assertEquals("5651fe6601bff89f975e6a02981b020fbb219e3b920477c02bfe37775ae08ea7", request.signature.toByteArray().toHex())
        assertTrue(WakeHostProof.constantTimeEquals(request.signature.toByteArray(), request.signature.toByteArray()))
        assertFalse(WakeHostProof.constantTimeEquals(request.signature.toByteArray(), byteArrayOf(1, 2, 3)))
    }

    @Test
    fun broadcastTargetValidationAllowsOnlyBroadcastAddressesAndValidPorts() {
        assertEquals(WakeHostBroadcastTarget("255.255.255.255", 9), WakeHostBroadcastTarget.parse("255.255.255.255", 9))
        assertEquals("192.168.1.255", WakeHostBroadcastTarget.parse("192.168.1.255", 7).address)
        assertSenderFailure(WakeHostPacketSenderFailure.INVALID_BROADCAST_ADDRESS) {
            WakeHostBroadcastTarget.parse("192.168.1.10", 9)
        }
        assertSenderFailure(WakeHostPacketSenderFailure.INVALID_BROADCAST_ADDRESS) {
            WakeHostBroadcastTarget.parse("0.0.0.0", 9)
        }
        assertSenderFailure(WakeHostPacketSenderFailure.INVALID_BROADCAST_ADDRESS) {
            WakeHostBroadcastTarget.parse("example.test", 9)
        }
        assertSenderFailure(WakeHostPacketSenderFailure.INVALID_PORT) {
            WakeHostBroadcastTarget.parse("255.255.255.255", 0)
        }
    }

    private fun assertFailure(
        expected: WakeHostRequestFailure,
        block: () -> Unit,
    ) {
        val failure = assertThrows(WakeHostRequestException::class.java, block)
        assertEquals(expected, failure.failure)
    }

    private fun assertSenderFailure(
        expected: WakeHostPacketSenderFailure,
        block: () -> Unit,
    ) {
        val failure = assertThrows(WakeHostPacketSenderException::class.java, block)
        assertEquals(expected, failure.failure)
    }

    private fun signedRequest(
        secret: ByteArray,
        issuedAt: Long,
        expiresAt: Long,
    ): WakeHostRequestContext {
        val keyId = WakeHostProof.keyId(secret)
        val nonce = ByteString.copyFrom(ByteArray(WakeHostProof.MINIMUM_NONCE_BYTES) { (0xa0 + it).toByte() })
        val request =
            WakeHostRequestContext(
                requestId = ByteString.copyFrom(byteArrayOf(0x42)),
                targetMacAddress = mac(1, 2, 3, 4, 5, 6),
                hostId = "host",
                deviceId = "device",
                keyId = keyId,
                issuedAtUnixSeconds = issuedAt,
                expiresAtUnixSeconds = expiresAt,
                nonce = nonce,
            )
        return request.copy(signature = ByteString.copyFrom(WakeHostProof.signature(request, secret)))
    }

    private fun mac(vararg bytes: Int): ByteString =
        ByteString.copyFrom(bytes.map { it.toByte() }.toByteArray())

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
}
