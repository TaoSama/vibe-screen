package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WirelessNetworkRoutePolicyTest {
    @Test
    fun `selects WiFi when cellular is the active network`() {
        val selected =
            WirelessNetworkRoutePolicy.select(
                listOf(
                    candidate("cellular", active = true),
                    candidate("wifi", wifi = true, prefixLength = 24),
                ),
            )

        assertEquals("wifi", selected)
    }

    @Test
    fun `prefers active WiFi when more than one WiFi route exists`() {
        val selected =
            WirelessNetworkRoutePolicy.select(
                listOf(
                    candidate("stale-wifi", wifi = true, prefixLength = 24),
                    candidate("active-wifi", active = true, wifi = true, prefixLength = 24),
                ),
            )

        assertEquals("active-wifi", selected)
    }

    @Test
    fun `does not bind a VPN route that reports WiFi transport`() {
        val selected =
            WirelessNetworkRoutePolicy.select(
                listOf(
                    candidate("vpn", active = true, wifi = true, vpn = true, prefixLength = 24),
                    candidate("wifi", wifi = true, prefixLength = 24),
                ),
            )

        assertEquals("wifi", selected)
    }

    @Test
    fun `prefers the most specific route over the active WiFi`() {
        val selected =
            WirelessNetworkRoutePolicy.select(
                listOf(
                    candidate("active-default", active = true, wifi = true, prefixLength = 0),
                    candidate("lan-subnet", wifi = true, prefixLength = 24),
                ),
            )

        assertEquals("lan-subnet", selected)
    }

    @Test
    fun `ignores WiFi without a route to the target`() {
        assertNull(WirelessNetworkRoutePolicy.select(listOf(candidate("wifi", wifi = true))))
    }

    @Test
    fun `returns no route when WiFi is unavailable`() {
        assertNull(
            WirelessNetworkRoutePolicy.select(
                listOf(candidate("cellular", active = true)),
            ),
        )
    }

    private fun candidate(
        route: String,
        active: Boolean = false,
        wifi: Boolean = false,
        vpn: Boolean = false,
        prefixLength: Int? = null,
    ) = WirelessNetworkCandidate(route, active, wifi, vpn, prefixLength)
}
