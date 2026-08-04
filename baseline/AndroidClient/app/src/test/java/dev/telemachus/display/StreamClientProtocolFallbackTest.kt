package dev.telemachus.display

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import java.net.ServerSocket
import java.util.concurrent.atomic.AtomicInteger

class StreamClientProtocolFallbackTest {
    @Test
    fun upgradeTimeoutClosesProbeAndUsesFreshLegacyConnection() =
        runBlocking {
            ServerSocket(0).use { server ->
                val accepts = AtomicInteger()
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { probe ->
                            accepts.incrementAndGet()
                            assertEquals(PROTOCOL_UPGRADE_BYTE, probe.getInputStream().read())
                            Thread.sleep(PROTOCOL_TIMEOUT_MARGIN_MS)
                            runCatching {
                                probe.getOutputStream().write(byteArrayOf(PROTOCOL_UPGRADE_BYTE.toByte(), 1))
                                probe.getOutputStream().flush()
                            }
                        }
                        server.accept().use { legacy ->
                            accepts.incrementAndGet()
                            val firstLegacyByte = legacy.getInputStream().read()
                            assertNotEquals(PROTOCOL_UPGRADE_BYTE, firstLegacyByte)
                        }
                    }
                val client = StreamClient("127.0.0.1", server.localPort)
                withTimeout(3_000) { client.connect() }
                withTimeout(3_000) { serverJob.await() }
                assertEquals(2, accepts.get())
            }
        }

    companion object {
        private const val PROTOCOL_UPGRADE_BYTE = 0x0d
        private const val PROTOCOL_TIMEOUT_MARGIN_MS = 350L
    }
}
