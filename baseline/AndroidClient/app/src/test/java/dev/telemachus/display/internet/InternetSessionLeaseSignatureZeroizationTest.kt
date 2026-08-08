package dev.telemachus.display.internet

import dev.telemachus.display.internet.security.SensitiveBufferObserver
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class InternetSessionLeaseSignatureZeroizationTest {
    @Test
    fun `streaming lease digest preserves fixture and zeroizes owned temporaries`() {
        val fixture = leaseFixture()
        val observed = mutableListOf<ByteArray>()
        try {
            assertEquals(
                "2e70ad358a425c631805820394d90ad46edb9ebb7f62541f594f5c22c2fbe377",
                InternetSessionLeaseSignature
                    .digest(fixture.profile, fixture.secrets, SensitiveBufferObserver { _, buffer -> observed += buffer })
                    .toHex(),
            )
            assertTrue(observed.isNotEmpty())
            assertTrue(observed.all(ByteArray::isZeroized))
        } finally {
            fixture.close()
        }
    }

    @Test
    fun `lease digest failure zeroizes every allocated temporary`() {
        val fixture = leaseFixture()
        val observed = mutableListOf<ByteArray>()
        var allocationCount = 0
        val observer =
            SensitiveBufferObserver { _, buffer ->
                observed += buffer
                allocationCount += 1
                if (allocationCount == 30) throw InjectedFailure()
            }
        try {
            assertThrows(InjectedFailure::class.java) {
                InternetSessionLeaseSignature.digest(fixture.profile, fixture.secrets, observer)
            }
            assertTrue(observed.isNotEmpty())
            assertTrue(observed.all(ByteArray::isZeroized))
        } finally {
            fixture.close()
        }
    }

    private fun leaseFixture(): DecodedInternetProfile =
        DecodedInternetProfile(
            StoredInternetSessionProfile(
                pairingIdentifier = "pair-1",
                pinnedHostId = "host-1",
                pinnedDeviceId = "device-1",
                leaseDeviceKeyId = "device-key-id",
                signalingUrl = "https://signal.example.test",
                signalingSessionId = "session-7",
                authoritativeSessionEpoch = 7,
                hostIdentityEpoch = 1,
                deviceIdentityEpoch = 1,
                expiresAtUnixSeconds = 4_102_444_800,
                transcriptContext = ByteArray(32) { 1 },
                protocolSessionId = "protocol-session-7".toByteArray(),
                iceServerUrls = listOf(listOf("stun:stun.example.test"), listOf("turn:turn.example.test")),
                allowInsecureForTesting = false,
                leaseHostKeyId = "host-key-id",
                leaseSignature = byteArrayOf(1),
            ),
            ImportedInternetSecrets(
                DestroyableUtf8.fromString("device-token-abcdefghijklmnopqrstuvwxyz"),
                listOf(
                    null to null,
                    DestroyableUtf8.fromString("turn-user") to DestroyableUtf8.fromString("turn-password"),
                ),
            ),
        )

    private class InjectedFailure : RuntimeException()
}

private fun ByteArray.isZeroized(): Boolean = all { it == 0.toByte() }

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
