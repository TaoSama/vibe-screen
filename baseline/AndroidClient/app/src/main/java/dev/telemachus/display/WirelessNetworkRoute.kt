package dev.telemachus.display

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import java.io.IOException
import java.net.InetAddress
import java.net.Socket
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

internal data class ResolvedWirelessRoute<T>(
    val network: T,
    val address: InetAddress,
)

internal data class WirelessNetworkCandidate<T>(
    val route: T,
    val isActive: Boolean,
    val isWifi: Boolean,
    val isVpn: Boolean,
    val matchingPrefixLength: Int?,
)

internal object WirelessNetworkRoutePolicy {
    fun <T> select(candidates: List<WirelessNetworkCandidate<T>>): T? =
        candidates
            .asSequence()
            .filter { it.isWifi && !it.isVpn && it.matchingPrefixLength != null }
            .sortedWith(
                compareByDescending<WirelessNetworkCandidate<T>> { it.matchingPrefixLength }
                    .thenByDescending { it.isActive },
            )
            .firstOrNull()
            ?.route
}

internal object AndroidWirelessNetworkRoute {
    private const val DISCOVERY_TIMEOUT_MS = 500L

    @Throws(IOException::class)
    fun bindPreferredWifi(
        context: Context?,
        socket: Socket,
        host: String,
    ): ResolvedWirelessRoute<Network>? {
        if (context == null) return null
        val manager = context.getSystemService(ConnectivityManager::class.java)
        val activeNetwork = manager.activeNetwork
        val candidates = discoverCandidates(manager, activeNetwork, host)
        val route =
            WirelessNetworkRoutePolicy.select(candidates)
                ?: throw IOException("No Wi-Fi route is available for $host")
        route.network.bindSocket(socket)
        return route
    }

    @Throws(IOException::class)
    private fun discoverCandidates(
        manager: ConnectivityManager,
        activeNetwork: Network?,
        host: String,
    ): List<WirelessNetworkCandidate<ResolvedWirelessRoute<Network>>> {
        val available = LinkedBlockingQueue<Network>()
        val lost = ConcurrentHashMap.newKeySet<Network>()
        val callback =
            object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    lost -= network
                    available.offer(network)
                }

                override fun onLost(network: Network) {
                    lost += network
                }
            }
        val request =
            NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                .build()
        var primaryFailure: IOException? = null
        var registered = false
        try {
            manager.registerNetworkCallback(request, callback)
            registered = true
            val deadlineNs = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(DISCOVERY_TIMEOUT_MS)
            val candidates = linkedMapOf<Network, WirelessNetworkCandidate<ResolvedWirelessRoute<Network>>>()
            while (true) {
                val remainingNs = deadlineNs - System.nanoTime()
                if (remainingNs <= 0L) break
                val network = available.poll(remainingNs, TimeUnit.NANOSECONDS) ?: break
                if (network in lost) {
                    candidates -= network
                    continue
                }
                resolveCandidate(manager, network, activeNetwork, host)?.let { candidate ->
                    if (network !in lost) candidates[network] = candidate
                }
            }
            lost.forEach { candidates -= it }
            return candidates.values.toList()
        } catch (error: SecurityException) {
            val wrapped = IOException("Unable to discover Wi-Fi networks", error)
            primaryFailure = wrapped
            throw wrapped
        } catch (error: InterruptedException) {
            Thread.currentThread().interrupt()
            val wrapped = IOException("Wi-Fi discovery was interrupted", error)
            primaryFailure = wrapped
            throw wrapped
        } finally {
            if (registered) {
                try {
                    manager.unregisterNetworkCallback(callback)
                } catch (cleanupError: RuntimeException) {
                    primaryFailure?.addSuppressed(cleanupError)
                        ?: throw IOException("Unable to unregister Wi-Fi network callback", cleanupError)
                }
            }
        }
    }

    private fun resolveCandidate(
        manager: ConnectivityManager,
        network: Network,
        activeNetwork: Network?,
        host: String,
    ): WirelessNetworkCandidate<ResolvedWirelessRoute<Network>>? {
        return try {
            val capabilities = manager.getNetworkCapabilities(network) ?: return null
            if (!capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN)
            ) {
                return null
            }
            val linkProperties = manager.getLinkProperties(network) ?: return null
            val resolvedRoute =
                network.getAllByName(host).mapNotNull { address ->
                    val prefixLength =
                        linkProperties.routes
                            .asSequence()
                            .filter { route -> route.matches(address) }
                            .maxOfOrNull { route -> route.destination.prefixLength }
                            ?: return@mapNotNull null
                    ResolvedWirelessRoute(network, address) to prefixLength
                }.maxByOrNull { (_, prefixLength) -> prefixLength }
                    ?: return null
            WirelessNetworkCandidate(
                route = resolvedRoute.first,
                isActive = network == activeNetwork,
                isWifi = true,
                isVpn = false,
                matchingPrefixLength = resolvedRoute.second,
            )
        } catch (_: IOException) {
            null
        } catch (_: SecurityException) {
            null
        }
    }
}
