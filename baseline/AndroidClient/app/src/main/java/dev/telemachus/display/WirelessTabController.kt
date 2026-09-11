package dev.telemachus.display

import android.annotation.SuppressLint
import android.app.Activity
import android.app.Dialog
import android.content.Context
import android.content.Intent
import android.content.res.Resources
import android.text.Layout
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import com.google.android.material.dialog.MaterialAlertDialogBuilder

internal interface WirelessTabHost {
    val resources: Resources

    fun getString(
        resId: Int,
        vararg formatArgs: Any,
    ): String

    fun showTrustedNetworkDialog(onConfirmed: () -> Unit)

    fun launchScanner()
}

interface WirelessPairingStore {
    fun save(entry: PairedHostStorage.Entry)

    fun load(): PairedHostStorage.Entry?

    fun clear()
}

interface WirelessCameraPermission {
    fun isGranted(): Boolean

    fun isPermanentlyDenied(): Boolean

    fun request(requestCode: Int)

    fun openAppSettings()
}

private class ActivityWirelessTabHost(
    private val activity: Activity,
    private val showDialog: (Dialog) -> Dialog,
) : WirelessTabHost {
    override val resources: Resources
        get() = activity.resources

    override fun getString(
        resId: Int,
        vararg formatArgs: Any,
    ): String = activity.getString(resId, *formatArgs)

    override fun showTrustedNetworkDialog(onConfirmed: () -> Unit) {
        showTrustedNetworkDialog(activity, onConfirmed, showDialog)
    }

    override fun launchScanner() {
        val intent = Intent(activity, QRScannerActivity::class.java)
        activity.startActivityForResult(intent, WirelessTabController.REQ_SCAN)
    }
}

internal fun showTrustedNetworkDialog(
    activity: Activity,
    onConfirmed: () -> Unit,
    showDialog: (Dialog) -> Dialog,
): Dialog? {
    if (activity.isFinishing || activity.isDestroyed) return null
    return showDialog(createTrustedNetworkDialog(activity, onConfirmed))
}

internal fun showTrustedNetworkDialog(
    activity: Activity,
    onConfirmed: () -> Unit,
): Dialog? = showTrustedNetworkDialog(activity, onConfirmed) { dialog ->
    dialog.show()
    dialog
}

internal fun createTrustedNetworkDialog(
    context: Context,
    onConfirmed: () -> Unit,
): AlertDialog {
    return MaterialAlertDialogBuilder(context)
        .setTitle(R.string.trusted_network_dialog_title)
        .setMessage(R.string.trusted_network_dialog_message)
        .setNegativeButton(R.string.cancel, null)
        .setPositiveButton(R.string.trusted_network_dialog_confirm, null)
        .create()
        .also { dialog -> configureTrustedNetworkDialogActions(dialog, onConfirmed) }
}

@SuppressLint("WrongConstant")
private fun configureTrustedNetworkDialogActions(
    dialog: AlertDialog,
    onConfirmed: () -> Unit,
) {
    dialog.setOnShowListener {
        dialog.findViewById<TextView>(android.R.id.message)?.apply {
            breakStrategy = Layout.BREAK_STRATEGY_BALANCED
            hyphenationFrequency = Layout.HYPHENATION_FREQUENCY_NORMAL
        }
        listOf(AlertDialog.BUTTON_NEGATIVE, AlertDialog.BUTTON_POSITIVE).forEach { buttonId ->
            checkNotNull(dialog.getButton(buttonId)) {
                "trusted network dialog button $buttonId exists"
            }.apply {
                setSingleLine(false)
                maxLines = TRUSTED_NETWORK_DIALOG_ACTION_MAX_LINES
                ellipsize = null
            }
        }
        checkNotNull(dialog.getButton(AlertDialog.BUTTON_POSITIVE)) {
            "trusted network dialog positive button exists"
        }.setOnClickListener {
            onConfirmed()
            dialog.dismiss()
        }
    }
}

private const val TRUSTED_NETWORK_DIALOG_ACTION_MAX_LINES = 2

/**
 * Five-state UI machine for the Wireless tab on Android.
 *
 *   ① first-time → ② scanning (QRScannerActivity) → ③ connected
 *                                         ↘ ④ token mismatch / re-pair
 *   ⓹ permission denied permanently
 */
class WirelessTabController internal constructor(
    private val host: WirelessTabHost,
    private val views: Views,
    private val storage: WirelessPairingStore,
    private val cameraPerm: WirelessCameraPermission,
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
    constructor(
        activity: Activity,
        views: Views,
        storage: PairedHostStorage,
        cameraPerm: CameraPermissionManager,
        isTrustedLanAcknowledged: () -> Boolean,
        acknowledgeTrustedLan: () -> Unit,
        showDialog: (Dialog) -> Dialog = { dialog ->
            dialog.show()
            dialog
        },
        onConnectRequested: (
            host: String,
            port: Int,
            token: ByteArray,
            deviceName: String,
            macName: String,
        ) -> Unit,
    ) : this(
        host = ActivityWirelessTabHost(activity, showDialog),
        views = views,
        storage = storage,
        cameraPerm = cameraPerm,
        isTrustedLanAcknowledged = isTrustedLanAcknowledged,
        acknowledgeTrustedLan = acknowledgeTrustedLan,
        onConnectRequested = onConnectRequested,
    )
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
        val idleStatusLabel: TextView,
        val idleMacName: TextView,
        val idleMacIp: TextView,
        val reconnectCountdown: TextView,
        val permissionRetryMessage: TextView,
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
                host.getString(R.string.reconnecting_to_mac, entry.macName),
                host.getString(R.string.host_port_format, entry.host, entry.port),
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
            host.getString(R.string.host_port_format, entry.host, entry.port),
        )
        showIdleReconnectState()
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
        hideCameraPermissionRetryHint()
        if (entry != null) {
            // Camera permission is needed only to scan a new QR. A previously
            // paired host must remain reconnectable if permission is denied.
            LiveRegionTextApplier.apply(views.idleMacName, entry.macName)
            LiveRegionTextApplier.apply(
                views.idleMacIp,
                host.getString(R.string.host_port_format, entry.host, entry.port),
            )
            showIdleReconnectState()
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
            host.getString(R.string.connecting_to_mac, parsed.macName),
            host.getString(R.string.host_port_format, parsed.host, parsed.port),
        )
        onConnectRequested(parsed.host, parsed.port, parsed.token, deviceName, parsed.macName)
    }

    fun onConnectError(error: StreamClient.WirelessConnectError) {
        val cached = storage.load()
        when (error) {
            is StreamClient.WirelessConnectError.NetworkUnreachable -> {
                showRepairMessage(
                    title = host.getString(R.string.wireless_error_title_couldnt_reach_mac),
                    message =
                        if (cached != null) {
                            host.getString(
                                R.string.wireless_error_network_cached,
                                cached.macName,
                                cached.host,
                                cached.port,
                            )
                        } else {
                            host.getString(R.string.wireless_error_network_uncached)
                        },
                )
                transition(State.REPAIR_NEEDED)
            }

            is StreamClient.WirelessConnectError.TokenRejected -> {
                showRepairMessage(
                    title = host.getString(R.string.wireless_error_title_repair_required),
                    message =
                        if (cached != null) {
                            host.getString(R.string.wireless_error_token_rejected_cached, cached.macName)
                        } else {
                            host.getString(R.string.wireless_error_token_rejected_uncached)
                        },
                )
                transition(State.REPAIR_NEEDED)
            }

            is StreamClient.WirelessConnectError.ProtocolError -> {
                showRepairMessage(
                    title = host.getString(R.string.wireless_error_title_connection_error),
                    message = host.getString(R.string.wireless_error_protocol_message),
                )
                transition(State.REPAIR_NEEDED)
            }
        }
    }

    internal fun showConnectionGuidance(guidance: ConnectionGuidance) {
        showRepairMessage(
            title = ConnectionGuidanceTextFormatter.format(host.resources, guidance.status),
            message = ConnectionGuidanceTextFormatter.format(host.resources, guidance.message),
        )
        transition(State.REPAIR_NEEDED)
    }

    private fun showRepairMessage(
        title: CharSequence,
        message: CharSequence,
    ) {
        LiveRegionTextApplier.apply(views.repairTitle, title)
        LiveRegionTextApplier.apply(views.repairMessage, message)
        views.repairMessage.contentDescription =
            host.getString(
                R.string.connection_guidance_full_message,
                title.toString(),
                message.toString(),
            )
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
        hostName: String,
        port: Int,
        remainingSeconds: Int,
    ) {
        LiveRegionTextApplier.apply(views.idleStatusLabel, host.getString(R.string.reconnect_countdown_title))
        LiveRegionTextApplier.apply(views.idleMacName, macName)
        LiveRegionTextApplier.apply(
            views.idleMacIp,
            host.getString(R.string.host_port_format, hostName, port),
        )
        LiveRegionTextApplier.show(
            views.reconnectCountdown,
            host.getString(R.string.reconnect_countdown_message, macName, hostName, port, remainingSeconds),
        )
        views.reconnectButton.text = host.getString(R.string.retry_now)
        views.reconnectButton.isEnabled = true
        transition(State.PAIRED_IDLE)
    }

    fun showAutomaticReconnectAttempting(
        macName: String,
        hostName: String,
        port: Int,
    ) {
        LiveRegionTextApplier.apply(views.idleStatusLabel, host.getString(R.string.reconnecting_short))
        LiveRegionTextApplier.show(
            views.reconnectCountdown,
            host.getString(R.string.reconnect_attempting_message, macName, hostName, port),
        )
        views.reconnectButton.text = host.getString(R.string.connecting)
        views.reconnectButton.isEnabled = false
    }

    private fun showIdleReconnectState() {
        LiveRegionTextApplier.apply(views.idleStatusLabel, host.getString(R.string.disconnected_status))
        LiveRegionTextApplier.hide(views.reconnectCountdown)
        views.reconnectButton.text = host.getString(R.string.reconnect)
        views.reconnectButton.isEnabled = true
    }

    fun onCameraPermissionResult(granted: Boolean) {
        if (granted) {
            // Re-evaluate; user just granted, jump straight into scanner.
            hideCameraPermissionRetryHint()
            launchScanner()
        } else if (cameraPerm.isPermanentlyDenied()) {
            hideCameraPermissionRetryHint()
            transition(State.PERM_DENIED)
        } else {
            showCameraPermissionRetryHint()
            transition(State.FIRST_TIME)
        }
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
            host.showTrustedNetworkDialog {
                acknowledgeTrustedLan()
                continueScan()
            }
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
            hideCameraPermissionRetryHint()
            cameraPerm.request(REQ_CAMERA)
            return
        }
        hideCameraPermissionRetryHint()
        launchScanner()
    }

    private fun showCameraPermissionRetryHint() {
        val message = host.getString(R.string.camera_permission_retry_instructions)
        views.permissionRetryMessage.contentDescription = message
        LiveRegionTextApplier.show(views.permissionRetryMessage, message)
    }

    private fun hideCameraPermissionRetryHint() {
        views.permissionRetryMessage.contentDescription = null
        LiveRegionTextApplier.hide(views.permissionRetryMessage)
    }

    private fun launchScanner() {
        host.launchScanner()
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
