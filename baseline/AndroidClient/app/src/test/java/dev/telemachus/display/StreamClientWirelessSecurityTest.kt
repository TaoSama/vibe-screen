package dev.telemachus.display

import dev.telemachus.display.internet.PeerRole
import dev.telemachus.display.internet.SessionChannel
import dev.telemachus.display.internet.security.ecdh
import dev.telemachus.display.internet.security.generateEphemeral
import dev.telemachus.display.internet.security.publicPoint
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.nio.ByteBuffer

class StreamClientWirelessSecurityTest {
    @Test
    fun wirelessProtocolProbeTravelsInsideSecureLanRecord() {
        runBlocking {
            val token = ByteArray(32) { (it + 1).toByte() }
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { peer ->
                            val auth = peer.getInputStream().readExactly(authRequestBytes("Android", token))
                            assertEquals(
                                AuthHandshake.encodeRequest(token, "Android").toList(),
                                auth.toList(),
                            )
                            peer.getOutputStream().write(byteArrayOf(0x53, 0x53, 0x57, 0x52, 0x00))
                            peer.getOutputStream().flush()

                            val secureRequest =
                                LanSecureRecordNegotiation.decodeRequest(
                                    peer.getInputStream().readExactly(LanSecureRecordNegotiation.REQUEST_BYTES),
                                )
                            val hostKey = generateEphemeral(java.security.SecureRandom())
                            val hostPublic = publicPoint(hostKey)
                            val sessionId = LanSecureRecordSession.sessionIdentifier(hostPublic, secureRequest.publicKey)
                            val context = LanSecureRecordSession.transcriptContext(
                                sessionId,
                                hostPublic,
                                secureRequest.publicKey,
                            )
                            val hostSession =
                                LanSecureRecordSession(
                                    PeerRole.HOST,
                                    sessionId,
                                    1,
                                    ecdh(hostKey.private, secureRequest.publicKey),
                                    token,
                                    context,
                                )
                            peer.getOutputStream().write(
                                LanSecureRecordNegotiation.encodeResponse(
                                    hostPublic,
                                    encrypted = true,
                                    explicitLegacyFallback = false,
                                ),
                            )
                            peer.getOutputStream().flush()

                            val prefix = peer.getInputStream().readExactly(4)
                            val encryptedRecordSize = ByteBuffer.wrap(prefix).int
                            assertNotEquals(PROTOCOL_UPGRADE_BYTE, prefix[0].toInt() and 0xff)
                            val record = peer.getInputStream().readExactly(encryptedRecordSize)
                            assertEquals(
                                byteArrayOf(PROTOCOL_UPGRADE_BYTE.toByte()).toList(),
                                hostSession.open(SessionChannel.CONTROL, record).toList(),
                            )
                        }
                    }

                val client = StreamClient("127.0.0.1", server.localPort)
                val clientJob = async(Dispatchers.IO) { runCatching { client.connectWireless(token, "Android") } }
                withTimeout(4_000) { serverJob.await() }
                client.disconnect()
                withTimeout(4_000) { clientJob.await() }
            }
        }
    }

    @Test
    fun wirelessLegacyPeerRequiresExplicitPlaintextFallback() {
        runBlocking {
            val token = ByteArray(32) { (it + 2).toByte() }
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { peer ->
                            peer.soTimeout = 500
                            peer.getInputStream().readExactly(authRequestBytes("Android", token))
                            peer.getOutputStream().write(byteArrayOf(0x53, 0x53, 0x57, 0x52, 0x00))
                            peer.getOutputStream().flush()
                            val first = peer.getInputStream().read()
                            assertEquals(
                                "Default wireless startup must negotiate secure records before Protocol v1",
                                LAN_SECURE_REQUEST_FIRST_BYTE,
                                first,
                            )
                        }
                    }

                val client = StreamClient("127.0.0.1", server.localPort)
                val clientJob = async(Dispatchers.IO) { runCatching { client.connectWireless(token, "Android") } }
                withTimeout(4_000) { serverJob.await() }
                client.disconnect()
                withTimeout(4_000) { clientJob.await() }
            }

            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { peer ->
                            peer.soTimeout = 500
                            peer.getInputStream().readExactly(authRequestBytes("Android", token))
                            peer.getOutputStream().write(byteArrayOf(0x53, 0x53, 0x57, 0x52, 0x00))
                            peer.getOutputStream().flush()
                            val first = peer.getInputStream().read()
                            assertEquals(PROTOCOL_UPGRADE_BYTE, first)
                            try {
                                val unexpected = peer.getInputStream().read()
                                assertEquals("Explicit legacy fallback should send only the plaintext upgrade byte first", -1, unexpected)
                            } catch (_: SocketTimeoutException) {
                            }
                        }
                    }

                val client = StreamClient("127.0.0.1", server.localPort)
                val clientJob =
                    async(Dispatchers.IO) {
                        runCatching {
                            client.connectWireless(
                                token = token,
                                deviceName = "Android",
                                allowPlaintextLegacyFallback = true,
                            )
                        }
                    }
                withTimeout(4_000) { serverJob.await() }
                client.disconnect()
                withTimeout(4_000) { clientJob.await() }
            }
        }
    }

    private fun authRequestBytes(
        deviceName: String,
        token: ByteArray,
    ): Int = AuthHandshake.encodeRequest(token, deviceName).size

    companion object {
        private const val PROTOCOL_UPGRADE_BYTE = 0x0d
        private const val LAN_SECURE_REQUEST_FIRST_BYTE = 0x56
    }
}
