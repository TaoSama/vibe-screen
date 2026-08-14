package dev.telemachus.display

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

fun interface WirelessSocketConnector {
    @Throws(IOException::class)
    fun connect(
        socket: Socket,
        host: String,
        port: Int,
        timeoutMs: Int,
    )
}

internal class DefaultRouteSocketConnector : WirelessSocketConnector {
    override fun connect(
        socket: Socket,
        host: String,
        port: Int,
        timeoutMs: Int,
    ) {
        socket.connect(InetSocketAddress(host, port), timeoutMs)
    }
}

internal class TrustedLanSocketConnector(
    context: Context,
) : WirelessSocketConnector {
    private val connectivityManager = context.getSystemService(ConnectivityManager::class.java)

    override fun connect(
        socket: Socket,
        host: String,
        port: Int,
        timeoutMs: Int,
    ) {
        val startedAtNs = System.nanoTime()
        val route = selectRoute(host, minOf(timeoutMs, NETWORK_DISCOVERY_TIMEOUT_MS))
        val elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAtNs)
        val connectTimeoutMs = (timeoutMs - elapsedMs).coerceAtLeast(1L).toInt()
        route.network.bindSocket(socket)
        socket.connect(InetSocketAddress(route.address, port), connectTimeoutMs)
    }

    private fun selectRoute(
        host: String,
        discoveryTimeoutMs: Int,
    ): SelectedLanRoute {
        val candidates = LinkedBlockingQueue<Network>()
        val callback =
            object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    candidates.offer(network)
                }

                override fun onCapabilitiesChanged(
                    network: Network,
                    networkCapabilities: NetworkCapabilities,
                ) {
                    candidates.offer(network)
                }

                override fun onLinkPropertiesChanged(
                    network: Network,
                    linkProperties: android.net.LinkProperties,
                ) {
                    candidates.offer(network)
                }
            }
        val request =
            NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                .build()
        var registered = false
        var primaryFailure: Throwable? = null
        try {
            try {
                connectivityManager.registerNetworkCallback(request, callback)
                registered = true
            } catch (error: RuntimeException) {
                throw IOException("Unable to discover a non-VPN WiFi network", error)
            }
            connectivityManager.activeNetwork?.let(candidates::offer)

            val deadlineNs = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(discoveryTimeoutMs.toLong())
            while (true) {
                val remainingNs = deadlineNs - System.nanoTime()
                if (remainingNs <= 0L) break
                val network =
                    try {
                        candidates.poll(remainingNs, TimeUnit.NANOSECONDS)
                    } catch (error: InterruptedException) {
                        Thread.currentThread().interrupt()
                        throw IOException("WiFi network discovery interrupted", error)
                    } ?: break
                if (!isPhysicalWifi(network)) continue
                resolveRoute(network, host)?.let { return it }
            }
        } catch (error: Throwable) {
            primaryFailure = error
            throw error
        } finally {
            if (registered) {
                try {
                    connectivityManager.unregisterNetworkCallback(callback)
                } catch (cleanupFailure: RuntimeException) {
                    if (primaryFailure != null) {
                        primaryFailure.addSuppressed(cleanupFailure)
                    } else {
                        throw IOException("Unable to release WiFi network discovery", cleanupFailure)
                    }
                }
            }
        }
        throw IOException("No non-VPN WiFi route to $host")
    }

    private fun resolveRoute(
        network: Network,
        host: String,
    ): SelectedLanRoute? {
        val linkProperties = connectivityManager.getLinkProperties(network) ?: return null
        val addresses =
            try {
                network.getAllByName(host)
            } catch (_: IOException) {
                return null
            }
        val routedAddress =
            addresses.firstOrNull { address ->
                linkProperties.routes.any { route -> route.matches(address) }
            } ?: return null
        return SelectedLanRoute(network, routedAddress)
    }

    private fun isPhysicalWifi(network: Network): Boolean {
        val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return false
        return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) &&
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
    }

    private data class SelectedLanRoute(
        val network: Network,
        val address: InetAddress,
    )

    private companion object {
        const val NETWORK_DISCOVERY_TIMEOUT_MS = 1_500
    }
}
