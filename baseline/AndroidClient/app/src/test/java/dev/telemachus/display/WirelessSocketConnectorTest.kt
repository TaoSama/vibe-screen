package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.atomic.AtomicInteger

class WirelessSocketConnectorTest {
    @Test
    fun defaultConnectorUsesRequestedEndpoint() {
        ServerSocket(0).use { server ->
            Socket().use { socket ->
                DefaultRouteSocketConnector().connect(socket, "127.0.0.1", server.localPort, 1_000)
                server.accept().use {
                    assertEquals(InetSocketAddress("127.0.0.1", server.localPort), socket.remoteSocketAddress)
                }
            }
        }
    }

    @Test
    fun injectedConnectorOwnsConnectionRouting() {
        val calls = AtomicInteger()
        val connector =
            WirelessSocketConnector { socket, host, port, timeoutMs ->
                calls.incrementAndGet()
                assertEquals("127.0.0.1", host)
                assertEquals(54321, port)
                assertEquals(3_000, timeoutMs)
                socket.close()
            }

        connector.connect(Socket(), "127.0.0.1", 54321, 3_000)

        assertEquals(1, calls.get())
    }
}
