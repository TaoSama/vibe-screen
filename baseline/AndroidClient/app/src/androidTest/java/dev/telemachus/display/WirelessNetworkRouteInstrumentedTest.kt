package dev.telemachus.display

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Test
import java.net.Inet4Address
import java.net.Socket

class WirelessNetworkRouteInstrumentedTest {
    @Test
    fun bindsSocketToWifiRouteForCurrentLanAddress() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val manager = context.getSystemService(ConnectivityManager::class.java)
        @Suppress("DEPRECATION")
        val availableNetworks = manager.allNetworks
        val wifiNetwork =
            availableNetworks.firstOrNull { network ->
                manager.getNetworkCapabilities(network)?.let { capabilities ->
                    capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) &&
                        !capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN)
                } == true
            }
        assertNotNull("device must have an available WiFi network", wifiNetwork)
        val wifiAddress =
            manager.getLinkProperties(checkNotNull(wifiNetwork))
                ?.linkAddresses
                ?.firstOrNull { it.address is Inet4Address }
                ?.address
        assertNotNull("WiFi network must have an IPv4 address", wifiAddress)

        Socket().use { socket ->
            val route =
                AndroidWirelessNetworkRoute.bindPreferredWifi(
                    context = context,
                    socket = socket,
                    host = checkNotNull(wifiAddress).hostAddress.orEmpty(),
                )
            val resolvedRoute = checkNotNull(route)
            val selectedCapabilities = manager.getNetworkCapabilities(resolvedRoute.network)
            val selectedLinkProperties = manager.getLinkProperties(resolvedRoute.network)

            assertEquals(wifiAddress, resolvedRoute.address)
            assertEquals(true, selectedCapabilities?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI))
            assertEquals(false, selectedCapabilities?.hasTransport(NetworkCapabilities.TRANSPORT_VPN))
            assertEquals(true, selectedLinkProperties?.routes?.any { it.matches(resolvedRoute.address) })
            assertFalse(socket.isConnected)
        }
    }
}
