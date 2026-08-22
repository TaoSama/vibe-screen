package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.InternetPairingSigner
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
    fun proofFactorySignsSessionBoundDigest() {
        val signer = JvmWakeHostSigner("paired-device")
        val requestId = ByteString.copyFrom(byteArrayOf(0x42))
        val mac = mac(1, 2, 3, 4, 5, 6)
        val nonce = ByteString.copyFrom(ByteArray(WakeHostProofFactory.NONCE_BYTES) { it.toByte() })
        val sessionId = ByteString.copyFrom(byteArrayOf(0x10, 0x20, 0x30, 0x40))

        val proof = WakeHostProofFactory.create(
            signer = signer,
            requestId = requestId,
            targetMacAddress = mac,
            secureOnPassword = ByteString.EMPTY,
            hostId = "host",
            issuedAtUnixSeconds = 900,
            expiresAtUnixSeconds = 1_100,
            nonce = nonce,
            sessionId = sessionId,
            sessionEpoch = 7,
        )
        val digest = WakeHostProofFactory.proofDigest(
            requestId = requestId,
            targetMacAddress = mac,
            secureOnPassword = ByteString.EMPTY,
            hostId = "host",
            deviceId = proof.deviceId,
            keyId = proof.keyId,
            issuedAtUnixSeconds = proof.issuedAtUnixSeconds,
            expiresAtUnixSeconds = proof.expiresAtUnixSeconds,
            nonce = proof.nonce,
            sessionId = sessionId,
            sessionEpoch = 7,
        )

        assertEquals("paired-device", proof.deviceId)
        assertTrue(verify(signer.keyPair.public, digest, proof.signature.toByteArray()))
        val otherSessionDigest = WakeHostProofFactory.proofDigest(
            requestId = requestId,
            targetMacAddress = mac,
            secureOnPassword = ByteString.EMPTY,
            hostId = "host",
            deviceId = proof.deviceId,
            keyId = proof.keyId,
            issuedAtUnixSeconds = proof.issuedAtUnixSeconds,
            expiresAtUnixSeconds = proof.expiresAtUnixSeconds,
            nonce = proof.nonce,
            sessionId = ByteString.copyFrom(byteArrayOf(0x7f)),
            sessionEpoch = 7,
        )
        assertFalse(verify(signer.keyPair.public, otherSessionDigest, proof.signature.toByteArray()))
    }

    @Test
    fun proofFactoryRejectsLongLivedProofs() {
        val signer = JvmWakeHostSigner("paired-device")

        assertThrows(IllegalArgumentException::class.java) {
            WakeHostProofFactory.create(
                signer = signer,
                requestId = ByteString.copyFrom(byteArrayOf(0x42)),
                targetMacAddress = mac(1, 2, 3, 4, 5, 6),
                secureOnPassword = ByteString.EMPTY,
                hostId = "host",
                issuedAtUnixSeconds = 900,
                expiresAtUnixSeconds = 1_300,
                nonce = ByteString.copyFrom(ByteArray(WakeHostProofFactory.NONCE_BYTES) { (it + 1).toByte() }),
                sessionId = ByteString.copyFrom(byteArrayOf(0x10)),
                sessionEpoch = 7,
            )
        }
    }

    private fun assertFailure(
        expected: WakeHostRequestFailure,
        block: () -> Unit,
    ) {
        val failure = assertThrows(WakeHostRequestException::class.java, block)
        assertEquals(expected, failure.failure)
    }

    private fun mac(vararg bytes: Int): ByteString =
        ByteString.copyFrom(bytes.map { it.toByte() }.toByteArray())
}

private class JvmWakeHostSigner(deviceId: String) : InternetPairingSigner {
    val keyPair: KeyPair = KeyPairGenerator.getInstance("EC")
        .apply { initialize(ECGenParameterSpec("secp256r1")) }
        .generateKeyPair()
    private val encodedPublicKey = encodePublicKey(keyPair.public as ECPublicKey)

    override val publicIdentity = InternetPairingIdentity(
        deviceId = deviceId,
        keyId = sha256(encodedPublicKey).joinToString("") { "%02x".format(it) },
        keyEpoch = 1,
        signingPublicKey = encodedPublicKey,
    )

    override fun signTranscriptDigest(digest: ByteArray): ByteArray =
        Signature.getInstance("NONEwithECDSA")
            .run {
                initSign(keyPair.private)
                update(digest)
                sign()
            }
}

private fun verify(
    publicKey: java.security.PublicKey,
    digest: ByteArray,
    signature: ByteArray,
): Boolean =
    Signature.getInstance("NONEwithECDSA")
        .run {
            initVerify(publicKey)
            update(digest)
            verify(signature)
        }

private fun encodePublicKey(key: ECPublicKey): ByteArray =
    byteArrayOf(4) + coordinate(key.w.affineX) + coordinate(key.w.affineY)

private fun coordinate(value: java.math.BigInteger): ByteArray {
    val signed = value.toByteArray()
    val unsigned = if (signed.size == 33 && signed[0] == 0.toByte()) signed.copyOfRange(1, signed.size) else signed
    return ByteArray(32 - unsigned.size) + unsigned
}

private fun sha256(value: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(value)
