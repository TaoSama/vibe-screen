package dev.telemachus.display.internet

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities

/** Process-default network observer. Call [close] from the owning lifecycle. */
class AndroidNetworkMonitor(context: Context) : NetworkMonitor {
    private val connectivityManager = context.getSystemService(ConnectivityManager::class.java)
    private val lock = Any()
    private var callback: ConnectivityManager.NetworkCallback? = null

    override fun start(listener: NetworkMonitor.Listener) {
        synchronized(lock) {
            check(callback == null) { "Network monitor is already started" }
            val registeredCallback =
                object : ConnectivityManager.NetworkCallback() {
                    override fun onAvailable(network: Network) {
                        publish(network, listener)
                    }

                    override fun onCapabilitiesChanged(
                        network: Network,
                        networkCapabilities: NetworkCapabilities,
                    ) {
                        listener.onAvailable(network.toSnapshot(networkCapabilities))
                    }

                    override fun onLost(network: Network) {
                        listener.onLost(network.toString())
                    }
                }
            connectivityManager.registerDefaultNetworkCallback(registeredCallback)
            callback = registeredCallback
        }
    }

    override fun close() {
        val registeredCallback = synchronized(lock) { callback.also { callback = null } } ?: return
        connectivityManager.unregisterNetworkCallback(registeredCallback)
    }

    private fun publish(
        network: Network,
        listener: NetworkMonitor.Listener,
    ) {
        val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return
        listener.onAvailable(network.toSnapshot(capabilities))
    }

    private fun Network.toSnapshot(capabilities: NetworkCapabilities): NetworkSnapshot =
        NetworkSnapshot(
            id = toString(),
            validated = capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED),
            metered = !capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED),
            transports =
                buildSet {
                    if (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) add(NetworkTransport.WIFI)
                    if (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) add(NetworkTransport.CELLULAR)
                    if (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) add(NetworkTransport.ETHERNET)
                    if (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) add(NetworkTransport.VPN)
                    if (isEmpty()) add(NetworkTransport.OTHER)
                },
        )
}
