package dev.telemachus.display

import android.app.Activity
import android.content.Intent
import android.view.View
import android.widget.Button
import android.widget.TextView

/**
 * Five-state UI machine for the Wireless tab on Android.
 *
 *   ① first-time → ② scanning (QRScannerActivity) → ③ connected
 *                                         ↘ ④ token mismatch / re-pair
 *   ⓹ permission denied permanently
 */
class WirelessTabController(
    private val activity: Activity,
    private val views: Views,
    private val storage: PairedHostStorage,
    private val cameraPerm: CameraPermissionManager,
    private val isTrustedLanAcknowledged: () -> Boolean,
    private val acknowledgeTrustedLan: () -> Unit,
    private val onConnectRequested: (
        host: String,
        port: Int,
        token: ByteArray,
        deviceName: String,
        macName: String,
    ) -> Unit,
) {
    data class Views(
        val connecting: View,
        val firstTime: View,
        val connected: View,
        val pairedIdle: View,
        val repair: View,
        val permDenied: View,
        val scanButton: Button,
        val rescanButton: Button,
        val disconnectButton: Button,
        val forgetButton: Button,
        val reconnectButton: Button,
        val idleForgetButton: Button,
        val openSettingsButton: Button,
        val connectedMacName: TextView,
        val connectedMacIp: TextView,
        val connectingLabel: TextView,
        val connectingSubtitle: TextView,
        val idleMacName: TextView,
        val idleMacIp: TextView,
        val repairTitle: TextView,
        val repairMessage: TextView,
    )

    enum class State { FIRST_TIME, CONNECTING, CONNECTED, PAIRED_IDLE, REPAIR_NEEDED, PERM_DENIED }

    private var state: State = State.FIRST_TIME

    fun bind() {
        views.scanButton.setOnClickListener { triggerScan() }
        views.rescanButton.setOnClickListener { triggerScan() }
        views.openSettingsButton.setOnClickListener { cameraPerm.openAppSettings() }
        views.forgetButton.setOnClickListener {
            storage.clear()
            transition(State.FIRST_TIME)
        }
        views.idleForgetButton.setOnClickListener {
            storage.clear()
            transition(State.FIRST_TIME)
        }
        views.reconnectButton.setOnClickListener {
            val entry =
                storage.load() ?: run {
                    transition(State.FIRST_TIME)
                    return@setOnClickListener
                }
            showConnecting(
                activity.getString(R.string.reconnecting_to_mac, entry.macName),
                activity.getString(R.string.host_port_format, entry.host, entry.port),
            )
            attemptAutoConnect(entry)
        }
    }

    /**
     * Called when the TCP stream goes down (user tapped Disconnect, network drop, etc).
     * Move the UI to a clean "paired but idle" state showing the Mac info + Reconnect button.
     */
    fun onStreamDisconnected() {
        android.util.Log.i(
            "WirelessTabController",
            "onStreamDisconnected called, current state=$state, storage entry exists=${storage.load() != null}",
        )
        val entry =
            storage.load() ?: run {
                transition(State.FIRST_TIME)
                return
            }
        LiveRegionTextApplier.apply(views.idleMacName, entry.macName)
        LiveRegionTextApplier.apply(
            views.idleMacIp,
            activity.getString(R.string.host_port_format, entry.host, entry.port),
        )
        transition(State.PAIRED_IDLE)
    }

    private fun transition(next: State) {
        if (state == next) return
        android.util.Log.i("WirelessTabController", "transition $state → $next")
        state = next
        views.connecting.visibility = if (next == State.CONNECTING) View.VISIBLE else View.GONE
        views.firstTime.visibility = if (next == State.FIRST_TIME) View.VISIBLE else View.GONE
        views.connected.visibility = if (next == State.CONNECTED) View.VISIBLE else View.GONE
        views.pairedIdle.visibility = if (next == State.PAIRED_IDLE) View.VISIBLE else View.GONE
        views.repair.visibility = if (next == State.REPAIR_NEEDED) View.VISIBLE else View.GONE
        views.permDenied.visibility = if (next == State.PERM_DENIED) View.VISIBLE else View.GONE
    }

    /**
     * Called when the Wireless tab becomes visible. Decides initial state based on
     * cached host + camera permission state.
     *
     * No auto-connect: even when a cached pairing exists, the user must press
     * the Reconnect button to actually start a connection. Auto-connect was
     * confusing because it could run silently while the user toggled tabs.
     */
    fun show() {
        val entry = storage.load()
        if (entry != null) {
            // Camera permission is needed only to scan a new QR. A previously
            // paired host must remain reconnectable if permission is denied.
            LiveRegionTextApplier.apply(views.idleMacName, entry.macName)
            LiveRegionTextApplier.apply(
                views.idleMacIp,
                activity.getString(R.string.host_port_format, entry.host, entry.port),
            )
            transition(State.PAIRED_IDLE)
        } else if (cameraPerm.isPermanentlyDenied()) {
            transition(State.PERM_DENIED)
        } else {
            transition(State.FIRST_TIME)
        }
    }

    fun onScanResult(url: String) {
        val parsed = PairingURL.parse(url) ?: return
        val deviceName = (android.os.Build.MODEL ?: "Android").take(64)
        storage.save(PairedHostStorage.Entry(parsed.host, parsed.port, parsed.token, parsed.macName))
        showConnecting(
            activity.getString(R.string.connecting_to_mac, parsed.macName),
            activity.getString(R.string.host_port_format, parsed.host, parsed.port),
        )
        onConnectRequested(parsed.host, parsed.port, parsed.token, deviceName, parsed.macName)
    }

    fun onConnectError(error: StreamClient.WirelessConnectError) {
        val cached = storage.load()
        when (error) {
            is StreamClient.WirelessConnectError.NetworkUnreachable -> {
                LiveRegionTextApplier.apply(views.repairTitle, activity.getString(R.string.wireless_error_title_couldnt_reach_mac))
                LiveRegionTextApplier.apply(
                    views.repairMessage,
                    if (cached != null) {
                        activity.getString(
                            R.string.wireless_error_network_cached,
                            cached.macName,
                            cached.host,
                            cached.port,
                        )
                    } else {
                        activity.getString(R.string.wireless_error_network_uncached)
                    },
                )
                transition(State.REPAIR_NEEDED)
            }

            is StreamClient.WirelessConnectError.TokenRejected -> {
                LiveRegionTextApplier.apply(views.repairTitle, activity.getString(R.string.wireless_error_title_repair_required))
                LiveRegionTextApplier.apply(
                    views.repairMessage,
                    if (cached != null) {
                        activity.getString(R.string.wireless_error_token_rejected_cached, cached.macName)
                    } else {
                        activity.getString(R.string.wireless_error_token_rejected_uncached)
                    },
                )
                transition(State.REPAIR_NEEDED)
            }

            is StreamClient.WirelessConnectError.ProtocolError -> {
                LiveRegionTextApplier.apply(views.repairTitle, activity.getString(R.string.wireless_error_title_connection_error))
                LiveRegionTextApplier.apply(
                    views.repairMessage,
                    activity.getString(R.string.wireless_error_protocol_message),
                )
                transition(State.REPAIR_NEEDED)
            }
        }
    }

    private fun showConnecting(
        title: String,
        subtitle: String,
    ) {
        LiveRegionTextApplier.apply(views.connectingLabel, title)
        LiveRegionTextApplier.apply(views.connectingSubtitle, subtitle)
        transition(State.CONNECTING)
    }

    fun onConnectSuccess(
        macName: String,
        ip: String,
    ) {
        LiveRegionTextApplier.apply(views.connectedMacName, macName)
        LiveRegionTextApplier.apply(views.connectedMacIp, ip)
        transition(State.CONNECTED)
    }

    fun showAutomaticReconnect(
        macName: String,
        host: String,
        port: Int,
        delayMs: Long,
    ) {
        val delaySeconds = delayMs / 1_000.0
        showConnecting(
            activity.getString(R.string.reconnecting_to_mac, macName),
            activity.getString(R.string.reconnect_delay_format, host, port, delaySeconds),
        )
    }

    fun onCameraPermissionResult(granted: Boolean) {
        if (granted) {
            // Re-evaluate; user just granted, jump straight into scanner.
            launchScanner()
        } else if (cameraPerm.isPermanentlyDenied()) {
            transition(State.PERM_DENIED)
        }
        // else: stay in current state; user can tap Scan again to re-prompt.
    }

    /** Reconcile permission changes made in Android Settings while this Activity was stopped. */
    fun onHostForegrounded(): Boolean =
        when (
            CameraPermissionResumePolicy.evaluate(
                state = state,
                granted = cameraPerm.isGranted(),
                permanentlyDenied = cameraPerm.isPermanentlyDenied(),
            )
        ) {
            CameraPermissionResumeAction.NOOP,
            CameraPermissionResumeAction.KEEP_DENIED,
            -> false

            CameraPermissionResumeAction.SHOW_SCAN_ENTRY -> {
                show()
                false
            }

            CameraPermissionResumeAction.SHOW_SCAN_ENTRY_AND_LAUNCH -> {
                show()
                launchScanner()
                true
            }
        }

    private fun triggerScan() {
        if (!isTrustedLanAcknowledged()) {
            android.app.AlertDialog
                .Builder(activity)
                .setTitle(R.string.trusted_network_dialog_title)
                .setMessage(R.string.trusted_network_dialog_message)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.trusted_network_dialog_confirm) { _, _ ->
                    acknowledgeTrustedLan()
                    continueScan()
                }.show()
            return
        }
        continueScan()
    }

    private fun continueScan() {
        if (cameraPerm.isPermanentlyDenied()) {
            transition(State.PERM_DENIED)
            return
        }
        if (!cameraPerm.isGranted()) {
            cameraPerm.request(REQ_CAMERA)
            return
        }
        launchScanner()
    }

    private fun launchScanner() {
        val intent = Intent(activity, QRScannerActivity::class.java)
        activity.startActivityForResult(intent, REQ_SCAN)
    }

    private fun attemptAutoConnect(entry: PairedHostStorage.Entry) {
        val deviceName = (android.os.Build.MODEL ?: "Android").take(64)
        onConnectRequested(entry.host, entry.port, entry.token, deviceName, entry.macName)
    }

    companion object {
        const val REQ_SCAN = 1001
        const val REQ_CAMERA = 1002
    }
}
