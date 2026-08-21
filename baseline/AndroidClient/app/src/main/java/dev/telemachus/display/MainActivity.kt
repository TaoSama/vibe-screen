package dev.telemachus.display

import android.annotation.SuppressLint
import android.app.Dialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ActivityInfo
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.media.MediaFormat
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.InputDevice
import android.view.KeyEvent
import android.view.SurfaceHolder
import android.view.View
import android.view.Window
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.view.accessibility.AccessibilityManager
import android.widget.TextView
import android.widget.Toast
import android.widget.EditText
import android.widget.PopupMenu
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.TooltipCompat
import androidx.constraintlayout.widget.ConstraintSet
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.google.android.material.button.MaterialButton
import com.google.android.material.button.MaterialButtonToggleGroup
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.slider.Slider
import com.google.android.material.switchmaterial.SwitchMaterial
import com.google.protobuf.ByteString
import dev.telemachus.display.databinding.ActivityMainBinding
import dev.telemachus.display.protocol.MotionPointer
import dev.telemachus.display.protocol.MotionSnapshot
import dev.telemachus.display.protocol.TouchSampleMapper
import dev.telemachus.display.protocol.FileTransferPolicy
import dev.telemachus.display.internet.AndroidNetworkMonitor
import dev.telemachus.display.internet.InternetDecoderConfigurationResult
import dev.telemachus.display.internet.InternetProductSession
import dev.telemachus.display.internet.InternetProductSessionCallbacks
import dev.telemachus.display.internet.InternetProductRevocationCoordinator
import dev.telemachus.display.internet.InternetProductSessionState
import dev.telemachus.display.internet.InternetProductRevocationStore
import dev.telemachus.display.internet.InternetSessionProfileStore
import dev.telemachus.display.internet.InternetControllerSendQueue
import dev.telemachus.display.internet.InternetVideoDecoderLifecycle
import dev.telemachus.display.internet.PeerRoute
import dev.telemachus.display.internet.PendingRevocationBarrierException
import dev.telemachus.display.internet.ProductControllerEvent
import dev.telemachus.display.internet.ProductInputPhase
import dev.telemachus.display.internet.ProductStylusEvent
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.VideoQualityPreset
import dev.telemachus.display.internet.ProductTouchEvent
import dev.telemachus.display.internet.ProductVideoCodec
import dev.telemachus.display.internet.ProductVideoConfiguration
import dev.telemachus.display.internet.ProductVideoConfigurationEffect
import dev.telemachus.display.internet.ProductVideoDecision
import dev.telemachus.display.internet.ProductVideoFrame
import dev.telemachus.display.internet.ProtobufProtocolV1ProductCodec
import dev.telemachus.display.internet.runBestEffort
import dev.telemachus.display.internet.security.AndroidDeviceIdentityStore
import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import dev.telemachus.display.internet.security.InternetPairingAcceptance
import dev.telemachus.display.internet.security.InternetPairingCoordinator
import dev.telemachus.display.internet.security.PendingInternetPairing
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.IOException
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.util.Locale
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

private fun mainDiag(msg: String) = DiagLog.log("MA", msg)

internal data class EncodedVideoConfigurationSnapshot(
    val width: Int,
    val height: Int,
    val configEpoch: Long,
)

internal class EncodedVideoConfigurationState {
    private val current = AtomicReference<EncodedVideoConfigurationSnapshot?>()

    fun publish(
        width: Int,
        height: Int,
        configEpoch: Long,
    ): EncodedVideoConfigurationSnapshot =
        EncodedVideoConfigurationSnapshot(width, height, configEpoch).also(current::set)

    fun snapshot(): EncodedVideoConfigurationSnapshot? = current.get()

    fun isCurrent(snapshot: EncodedVideoConfigurationSnapshot): Boolean = current.get() === snapshot

    fun clear() {
        current.set(null)
    }
}

internal data class InternetDecoderPresentationState<Decoder, Configuration>(
    val decoder: Decoder?,
    val configuration: Configuration?,
    val displayWidth: Int,
    val displayHeight: Int,
    val displayRotation: Int,
    val connected: Boolean,
)

internal fun <State> commitInternetDecoderPresentation(
    nextState: State,
    captureState: () -> State,
    installState: (State) -> Unit,
    restoreState: (attempted: State, previous: State) -> Unit,
    presentState: (previous: State) -> Unit,
): State {
    val previousState = captureState()
    try {
        installState(nextState)
        presentState(previousState)
    } catch (failure: Throwable) {
        try {
            restoreState(nextState, previousState)
        } catch (rollbackFailure: Throwable) {
            failure.addSuppressed(rollbackFailure)
        }
        throw failure
    }
    return previousState
}

class MainActivity : AppCompatActivity() {
    private lateinit var wirelessController: WirelessTabController
    private val pairedHostStorage by lazy { PairedHostStorage(this) }
    private val cameraPerm by lazy { CameraPermissionManager(this) }
    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: PreferencesManager
    private val videoDecoderRef = AtomicReference<VideoDecoder?>()
    private val surfaceGeneration = AtomicLong()
    private val decoderConfigurationGeneration = AtomicLong()
    private var videoDecoder: VideoDecoder?
        get() = videoDecoderRef.get()
        set(value) = videoDecoderRef.set(value)
    private val internetDeviceId by lazy { prefs.internetDeviceId }
    private val internetProfileStore by lazy { InternetSessionProfileStore(applicationContext) }
    private val internetRevocationCoordinator = InternetProductRevocationCoordinator.processShared()
    private val internetStoredSessionFactory by lazy {
        AndroidStoredInternetSessionFactory(applicationContext, internetDeviceId)
    }
    private val pendingPairingIdentityAliasPersistence by lazy {
        SharedPreferencesPendingPairingIdentityAliasPersistence(applicationContext)
    }
    @Volatile private var internetSession: InternetProductSession? = null
    private var internetVideoDecoderLifecycle: InternetVideoDecoderLifecycle? = null
    private var internetNetworkMonitor: AndroidNetworkMonitor? = null
    private var internetTickJob: kotlinx.coroutines.Job? = null
    @Volatile private var internetRoute: PeerRoute? = null
    @Volatile private var internetSessionEpoch = 0L
    private var internetVideoConfiguration: ProductVideoConfiguration? = null
    private var requiredFreshInternetEpoch = 0L
    private var pendingInternetPairing: PendingInternetPairing? = null
    private var pendingInternetPairingIdentity: PendingPairingIdentityAlias? = null
    @Volatile private var internetGeneration = 0L
    private val internetInputIds = SessionInputIdSequence()
    private val nextStreamStylusTrackingId = AtomicLong(0)
    private val activeInternetInputIds = mutableMapOf<Int, Long>()
    private val internetStylusInputIds = StylusInputIdTracker(internetInputIds::next)
    private val streamStylusInputIds = StylusInputIdTracker { nextStreamStylusTrackingId.incrementAndGet() }
    private val internetStylusGestureRouter = StylusGestureRouter()
    private val streamStylusGestureRouter = StylusGestureRouter()
    private val internetStylusContactRouter = StylusContactRouter()
    private val streamStylusContactRouter = StylusContactRouter()
    private val stylusReleaseCoordinator = StylusReleaseCoordinator(streamStylusInputIds, internetStylusInputIds)
    private var streamClient: StreamClient? = null
    private var legacyGeneration = 0L
    private var currentSurfaceHolder: SurfaceHolder? = null
    private var mainSessionDisplayLifecycle: MainSessionDisplayLifecycle? = null
    private val encodedVideoConfigurationState = EncodedVideoConfigurationState()
    @Volatile private var activeDecoderConfigEpoch = 0L
    private var displayWidth = 0 // Logical display geometry used by viewport/input mapping
    private var displayHeight = 0 // Logical display geometry used by viewport/input mapping
    private var displayRotation = 0 // 0, 90, 180, 270 degrees
    private var pingJob: kotlinx.coroutines.Job? = null
    private var isInForeground = false
    private val sessionState = SessionState<StreamClient>()
    private val nativeInputSessionState = NativeInputSessionState<StreamClient>()
    private val nativeInputReleaseCoordinator = NativeInputReleaseCoordinator(nativeInputSessionState)
    private val streamControllerSessionState = ControllerSessionState()
    private val internetControllerSessionState = ControllerSessionState()
    private var activeSessionGeneration = 0L
    private var unsupportedKeyboardNoticeShown = false
    private var nextNativePointerMoveDiagAtMs = 0L
    private val inputHandler = Handler(Looper.getMainLooper())
    private var pendingRightClickRelease: Runnable? = null
    private lateinit var deviceHealthMonitor: AndroidDeviceHealthMonitor
    private var deviceHealthSnapshot = DeviceHealthSnapshot()

    // For dragging stats overlay
    private var isDraggingOverlay = false
    private var overlayDx = 0f
    private var overlayDy = 0f
    private var activeSettingsDialog: Dialog? = null

    // Latest non-interactive edge insets (system bars + display cutout) unioned
    // across the whole window. Floating chrome is kept inside the safe region
    // derived from these while the video SurfaceView stays edge-to-edge.
    private var safeAreaInsets = SafeAreaGeometry.Insets.NONE
    private val baseChromeMargins = mutableMapOf<Int, SafeAreaGeometry.Insets>()

    // Input prediction for low-latency gaming
    private val inputPredictor = InputPredictor()

    // Checklist status handler
    private val checklistHandler = Handler(Looper.getMainLooper())
    private var checklistRunnable: Runnable? = null
    private var isConnected = false // Track connection state to prevent checklist conflicts
    private var connectionAttemptInProgress = false
    private var hasAttemptedUsbConnection = false
    private var automaticUsbConnect = false
    private var connectionDetailsVisible = false
    private val connectionSubtitleDisclosure = ConnectionSubtitleDisclosureState()
    private val connectionStatusAnnouncements = ConnectionStatusAnnouncementCoordinator()
    private val autoConnectHandler = Handler(Looper.getMainLooper())
    private val wirelessReconnectHandler = Handler(Looper.getMainLooper())
    private val initialWirelessReconnectBackoff =
        ReconnectBackoff(
            initialDelayMs = WIRELESS_INITIAL_RETRY_DELAY_MS,
            maximumDelayMs = WIRELESS_RECONNECT_MAXIMUM_DELAY_MS,
            jitterRatio = 0.0,
        )
    private var wirelessAutoReconnectEnabled = false
    private var pendingWirelessReconnectDelayMs: Long? = null
    private var pendingTerminalGuidance: ConnectionGuidance? = null
    private var isReconnecting = false
    private var hasConnectedThisRun = false
    private var lastAppliedVideoPreferenceConfigEpoch = 0L
    private val controlBarHandler = Handler(Looper.getMainLooper())
    private val clipboardRequestHandler = Handler(Looper.getMainLooper())
    private val fileTransferApprovalHandler = Handler(Looper.getMainLooper())
    private var clipboardRequestTimeout: Runnable? = null
    private val accessibilityManager by lazy { getSystemService(AccessibilityManager::class.java) }
    private val controlBarHideRunnable =
        Runnable {
            if (ControlBarAccessibilityPolicy.shouldAutoHide(accessibilityManager.isTouchExplorationEnabled)) {
                hideControlBar()
            }
        }
    private val touchExplorationStateChangeListener =
        AccessibilityManager.TouchExplorationStateChangeListener(::reconcileTouchExplorationState)
    private var availableDisplays = emptyList<StreamDisplayOption>()
    private var selectedDisplayId = ""
    private var availableHostActions = emptyList<HostActionOption>()
    private val clipboardApprovalState = ClipboardApprovalState<StreamClient>()
    private var pendingOutgoingFileTransfer: File? = null
    private var pendingIncomingFileDialog: androidx.appcompat.app.AlertDialog? = null
    private var revealOnlyTouchGestureActive = false
    private val autoConnectRunnable =
        Runnable {
            if (automaticUsbConnect && isInForeground && !isConnected && !connectionAttemptInProgress) {
                connect("127.0.0.1", currentUsbPort(), automatic = true)
            }
        }
    private val wirelessReconnectRunnable =
        Runnable {
            val entry = pairedHostStorage.load()
            if (entry == null ||
                !wirelessAutoReconnectEnabled ||
                prefs.connectionMode != ConnectionMode.WIRELESS ||
                isConnected ||
                !isInForeground ||
                connectionAttemptInProgress
            ) {
                return@Runnable
            }
            val deviceName = (Build.MODEL ?: "Android").take(MAX_DEVICE_NAME_LENGTH)
            connectWireless(entry.host, entry.port, entry.token, deviceName, entry.macName)
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        DiagLog.init(applicationContext)
        prefs = PreferencesManager(this)
        deviceHealthMonitor =
            AndroidDeviceHealthMonitor(
                context = this,
                onChanged = ::onDeviceHealthChanged,
                onError = { failure ->
                    mainDiag("device health observation failed: ${failure.message ?: failure.javaClass.simpleName}")
                },
            )

        // Allow rotation based on device sensor when not connected
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR

        // Enable edge-to-edge display (draw behind system bars and cutout)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            window.attributes.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        applyConnectionPanelLayout()

        runCatching(::retryPendingPairingIdentityAliasCleanup).onFailure { failure ->
            android.util.Log.e(INTERNET_LOG_TAG, "Could not recover pending pairing identity alias", failure)
            showInternetFailure(failure)
        }

        // Apply fullscreen mode immediately
        enableFullscreenMode()

        setupSurface()
        setupUI()
        setupDraggableOverlay()
        setupSettingsButton()
        setupControlBar()
        setupSafeAreaInsets()
        restoreOverlayPosition()
        restoreSettingsButtonPosition()
        startChecklistUpdates()
        setupModeToggle()
        setupWirelessController()
        if (savedInstanceState?.getBoolean(STATE_AUTOMATIC_USB_CONNECT) == true) {
            enableAutomaticUsbConnect()
        } else if (!handleLaunchIntent(intent) && prefs.connectionMode == ConnectionMode.USB) {
            // USB is the default mode and the host is reachable over adb-reverse
            // loopback, so a plain launch (icon tap, or a relaunch that dropped the
            // auto_connect extra) should still attach automatically, matching the
            // behavior when the Mac host starts the client with the extra.
            enableAutomaticUsbConnect()
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleLaunchIntent(intent)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean(STATE_AUTOMATIC_USB_CONNECT, automaticUsbConnect)
        super.onSaveInstanceState(outState)
    }

    override fun onStart() {
        super.onStart()
        isInForeground = true
        deviceHealthMonitor.start()
        accessibilityManager.addTouchExplorationStateChangeListener(touchExplorationStateChangeListener)
        reconcileTouchExplorationState(accessibilityManager.isTouchExplorationEnabled)
        mainDiag("lifecycle foreground connected=$isConnected")
        val scannerLaunched =
            ::wirelessController.isInitialized &&
                prefs.connectionMode == ConnectionMode.WIRELESS &&
                wirelessController.onHostForegrounded()
        if (scannerLaunched) return
        if (isConnected) {
            setStreamingWindowState(true)
            streamClient?.requestKeyframe(force = true, reason = FOREGROUND_KEYFRAME_REASON)
            internetSession?.requestKeyframe(FOREGROUND_KEYFRAME_REASON)
        } else if (prefs.connectionMode == ConnectionMode.WIRELESS && wirelessAutoReconnectEnabled) {
            pendingWirelessReconnectDelayMs?.let(::scheduleWirelessReconnect)
                ?: pairedHostStorage.load()?.let { scheduleWirelessReconnect(WIRELESS_INITIAL_RETRY_DELAY_MS) }
        } else {
            scheduleAutomaticUsbConnect(FOREGROUND_RECONNECT_DELAY_MS)
        }
    }

    override fun onStop() {
        deviceHealthMonitor.stop()
        accessibilityManager.removeTouchExplorationStateChangeListener(touchExplorationStateChangeListener)
        finishPendingRightClick()
        completeCurrentNativeInputBoundary(InputPhase.INPUT_PHASE_CANCELLED)
        isInForeground = false
        applyStreamingWindowState(connected = isConnected, foreground = false)
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)
        mainDiag("lifecycle background connected=$isConnected; retries paused")
        super.onStop()
    }

    private fun reconcileTouchExplorationState(enabled: Boolean) {
        controlBarHandler.removeCallbacks(controlBarHideRunnable)
        if (!isConnected) return
        if (enabled) {
            revealControlBar()
        } else if (binding.controlBar.visibility == View.VISIBLE) {
            ControlBarAccessibilityPolicy.autoHideDelayMs(
                touchExplorationEnabled = false,
                revealReason = ControlBarAccessibilityPolicy.RevealReason.USER_REQUEST,
            )?.let { delayMs ->
                controlBarHandler.postDelayed(controlBarHideRunnable, delayMs)
            }
        }
    }

    private fun onDeviceHealthChanged(snapshot: DeviceHealthSnapshot) {
        deviceHealthSnapshot = snapshot
        mainDiag(
            "device health battery=${snapshot.batteryPercent ?: "unknown"} " +
                "charging=${snapshot.charging ?: "unknown"} saver=${snapshot.powerSaveMode} " +
                "thermal=${snapshot.thermalState.name.lowercase(Locale.US)}",
        )
        activeSettingsDialog?.let(::renderDeviceHealth)
    }

    private fun renderDeviceHealth(dialog: Dialog) {
        val snapshot = deviceHealthSnapshot
        val status = dialog.findViewById<TextView>(R.id.deviceHealthStatus) ?: return
        val summary = dialog.findViewById<TextView>(R.id.deviceHealthSummary) ?: return
        val attention = DeviceHealthPolicy.attention(snapshot)
        status.setText(
            when (attention) {
                DeviceHealthAttention.UNKNOWN -> R.string.device_health_checking
                DeviceHealthAttention.NORMAL -> R.string.device_health_ready
                DeviceHealthAttention.POWER_SAVER -> R.string.device_health_power_saver_warning
                DeviceHealthAttention.POWER_RECOMMENDED -> R.string.device_health_connect_power
                DeviceHealthAttention.THERMAL_ELEVATED -> R.string.device_health_warm
                DeviceHealthAttention.THERMAL_HIGH -> R.string.device_health_hot
            },
        )
        status.setTextColor(
            getColor(
                when (attention) {
                    DeviceHealthAttention.UNKNOWN -> R.color.on_surface_muted
                    DeviceHealthAttention.NORMAL -> R.color.accent
                    DeviceHealthAttention.POWER_SAVER,
                    DeviceHealthAttention.POWER_RECOMMENDED,
                    DeviceHealthAttention.THERMAL_ELEVATED,
                    -> R.color.warning

                    DeviceHealthAttention.THERMAL_HIGH -> R.color.danger
                },
            ),
        )
        val battery =
            snapshot.batteryPercent?.let { getString(R.string.device_health_battery, it) }
                ?: getString(R.string.device_health_battery_unknown)
        val chargingState =
            getString(
                when (snapshot.charging) {
                    true -> R.string.device_health_charging
                    false -> R.string.device_health_discharging
                    null -> R.string.device_health_power_unknown
                },
            )
        val powerSaver =
            getString(
                if (snapshot.powerSaveMode) {
                    R.string.device_health_power_saver
                } else {
                    R.string.device_health_power_saver_off
                },
            )
        val thermal =
            getString(
                when (snapshot.thermalState) {
                    DeviceThermalState.NOMINAL -> R.string.device_health_thermal_nominal
                    DeviceThermalState.ELEVATED -> R.string.device_health_thermal_elevated
                    DeviceThermalState.SEVERE -> R.string.device_health_thermal_severe
                    DeviceThermalState.CRITICAL -> R.string.device_health_thermal_critical
                    DeviceThermalState.UNKNOWN -> R.string.device_health_thermal_unknown
                },
            )
        summary.text = getString(R.string.device_health_summary, battery, chargingState, powerSaver, thermal)
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (!isInForeground || event.isSystemKey()) return super.dispatchKeyEvent(event)
        ControllerInputMapper.keyChange(event)?.let { change ->
            val active = canSendControllerInput()
            if (active) {
                val state = activeControllerSessionState()
                val dispatch = state.applyKey(change)
                if (dispatch != null && sendStreamControllerDispatch(dispatch, "controller key")) return true
                if (ControllerInputConsumptionPolicy.shouldConsume(active, isSystemKey = false)) return true
            }
        }
        if (!isConnected) return super.dispatchKeyEvent(event)
        val clientEvent =
            AndroidKeyInputMapper.map(
                keyCode = event.keyCode,
                action = event.action,
                metaState = event.metaState,
                repeatCount = event.repeatCount,
            ) ?: return super.dispatchKeyEvent(event)
        when (ClientInputDispatch(currentSessionBinding()).sendKey(clientEvent)) {
            ClientInputDispatchResult.SENT -> return true
            ClientInputDispatchResult.REJECTED -> {
                mainDiag("negotiated keyboard sink rejected HID ${clientEvent.usbHidUsage}")
                return true
            }

            ClientInputDispatchResult.UNSUPPORTED -> Unit
        }
        run {
            if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) {
                mainDiag(
                    "keyboard input blocked by touch-only host " +
                        "hid=${clientEvent.usbHidUsage} modifiers=${clientEvent.modifiers}",
                )
                if (!unsupportedKeyboardNoticeShown) {
                    unsupportedKeyboardNoticeShown = true
                    Toast
                        .makeText(this, R.string.keyboard_requires_compatible_host, Toast.LENGTH_LONG)
                        .show()
                }
            }
            return true
        }
    }

    private fun KeyEvent.isSystemKey(): Boolean =
        keyCode == KeyEvent.KEYCODE_BACK ||
            keyCode == KeyEvent.KEYCODE_VOLUME_UP ||
            keyCode == KeyEvent.KEYCODE_VOLUME_DOWN ||
            keyCode == KeyEvent.KEYCODE_VOLUME_MUTE ||
            keyCode == KeyEvent.KEYCODE_POWER

    private fun handleLaunchIntent(intent: Intent?): Boolean {
        if (intent?.getBooleanExtra(EXTRA_AUTO_CONNECT, false) != true) return false
        // Treat the launch extra as an event. Persisting it on the Activity's
        // Intent would make a deliberate Disconnect resume after recreation.
        intent.removeExtra(EXTRA_AUTO_CONNECT)
        enableAutomaticUsbConnect()
        return true
    }

    private fun enableAutomaticUsbConnect() {
        automaticUsbConnect = true
        prefs.connectionMode = ConnectionMode.USB
        binding.modeToggleGroup.check(R.id.modeUSB)
        applyModeVisibility(ConnectionMode.USB)
        scheduleAutomaticUsbConnect(150)
    }

    private fun currentUsbPort(): Int =
        binding.portInput.text
            .toString()
            .toIntOrNull() ?: 54321

    private fun scheduleAutomaticUsbConnect(delayMs: Long = 1500) {
        if (!automaticUsbConnect || isConnected || !isInForeground) return
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        autoConnectHandler.postDelayed(autoConnectRunnable, delayMs)
        if (hasConnectedThisRun) {
            isReconnecting = true
            if (prefs.connectionMode == ConnectionMode.USB) updateDisconnectedHeader(ConnectionMode.USB)
        }
    }

    private fun setupModeToggle() {
        // Restore previous mode and reflect in toggle.
        val saved = prefs.connectionMode
        binding.modeToggleGroup.check(
            when (saved) {
                ConnectionMode.USB -> R.id.modeUSB
                ConnectionMode.WIRELESS -> R.id.modeWireless
                ConnectionMode.INTERNET -> R.id.modeInternet
            },
        )
        applyModeVisibility(saved)

        binding.modeToggleGroup.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (!isChecked) return@addOnButtonCheckedListener
            val mode =
                when (checkedId) {
                    R.id.modeWireless -> ConnectionMode.WIRELESS
                    R.id.modeInternet -> ConnectionMode.INTERNET
                    else -> ConnectionMode.USB
                }
            if (prefs.connectionMode != mode) {
                cancelConnectionForModeSwitch()
            }
            prefs.connectionMode = mode
            applyModeVisibility(mode)
            if (mode == ConnectionMode.WIRELESS) {
                automaticUsbConnect = false
                autoConnectHandler.removeCallbacks(autoConnectRunnable)
                wirelessController.show()
            } else if (mode == ConnectionMode.INTERNET) {
                automaticUsbConnect = false
                autoConnectHandler.removeCallbacks(autoConnectRunnable)
                cancelWirelessReconnect()
                refreshInternetProfileUi()
            } else if (!isConnected) {
                cancelWirelessReconnect()
                automaticUsbConnect = true
                scheduleAutomaticUsbConnect(150)
            }
        }
    }

    private fun applyModeVisibility(mode: ConnectionMode) {
        connectionSubtitleDisclosure.reset()
        binding.usbModeContent.visibility = if (mode == ConnectionMode.USB) View.VISIBLE else View.GONE
        binding.wirelessModeContent.visibility = if (mode == ConnectionMode.WIRELESS) View.VISIBLE else View.GONE
        binding.internetModeContent.visibility = if (mode == ConnectionMode.INTERNET) View.VISIBLE else View.GONE
        // USB checklist polls 127.0.0.1:port every 2s via adb-reverse to verify Mac
        // server reachability. While in Wireless mode that probe creates loopback
        // connections that fight the wireless session for the Mac's single client
        // slot — kicking the wireless client off seconds after it auths. Pause
        // checklist updates whenever Wireless is the active tab.
        if (mode != ConnectionMode.USB) {
            stopChecklistUpdates()
            clearUsbConnectionGuidance()
        } else {
            startChecklistUpdates()
        }
        applyConnectionPanelLayout(mode)
        updateDisconnectedHeader(mode)
    }

    private fun setupWirelessController() {
        wirelessController =
            WirelessTabController(
                activity = this,
                views =
                    WirelessTabController.Views(
                        connecting = binding.wirelessConnecting,
                        firstTime = binding.wirelessFirstTime,
                        connected = binding.wirelessConnected,
                        pairedIdle = binding.wirelessPairedIdle,
                        repair = binding.wirelessTokenMismatch,
                        permDenied = binding.wirelessPermDenied,
                        scanButton = binding.wirelessScanButton,
                        rescanButton = binding.wirelessRescanButton,
                        disconnectButton = binding.wirelessDisconnectButton,
                        forgetButton = binding.wirelessForgetButton,
                        reconnectButton = binding.wirelessReconnectButton,
                        idleForgetButton = binding.wirelessIdleForgetButton,
                        openSettingsButton = binding.wirelessOpenSettingsButton,
                        connectedMacName = binding.connectedMacName,
                        connectedMacIp = binding.connectedMacIp,
                        connectingLabel = binding.connectingLabel,
                        connectingSubtitle = binding.connectingSubtitle,
                        idleMacName = binding.idleMacName,
                        idleMacIp = binding.idleMacIp,
                        repairTitle = binding.repairTitle,
                        repairMessage = binding.repairMessage,
                    ),
                storage = pairedHostStorage,
                cameraPerm = cameraPerm,
                isTrustedLanAcknowledged = { prefs.trustedLanAcknowledged },
                acknowledgeTrustedLan = { prefs.trustedLanAcknowledged = true },
                onConnectRequested = { host, port, token, deviceName, macName ->
                    wirelessAutoReconnectEnabled = true
                    pendingWirelessReconnectDelayMs = null
                    initialWirelessReconnectBackoff.reset()
                    wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)
                    connectWireless(host, port, token, deviceName, macName)
                },
            )
        wirelessController.bind()
        binding.wirelessDisconnectButton.setOnClickListener { disconnect() }
        if (prefs.connectionMode == ConnectionMode.WIRELESS) {
            wirelessController.show()
        }
    }

    override fun onActivityResult(
        requestCode: Int,
        resultCode: Int,
        data: android.content.Intent?,
    ) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == WirelessTabController.REQ_SCAN && resultCode == RESULT_OK) {
            val url = data?.getStringExtra(QRScannerActivity.EXTRA_URL) ?: return
            wirelessController.onScanResult(url)
        } else if (requestCode == REQ_INTERNET_SCAN && resultCode == RESULT_OK) {
            val value = data?.getStringExtra(QRScannerActivity.EXTRA_URL) ?: return
            beginInternetPairing(value)
        } else if (requestCode == REQ_FILE_TRANSFER_OPEN) {
            handleFileTransferPickerResult(resultCode, data)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == WirelessTabController.REQ_CAMERA) {
            val granted = grantResults.firstOrNull() == android.content.pm.PackageManager.PERMISSION_GRANTED
            wirelessController.onCameraPermissionResult(granted)
        } else if (requestCode == REQ_INTERNET_CAMERA && grantResults.firstOrNull() == android.content.pm.PackageManager.PERMISSION_GRANTED) {
            launchInternetScanner()
        }
    }

    /**
     * Screen capture of streamed Mac pixels is blocked with FLAG_SECURE in
     * production. Debuggable builds may opt into allowing capture for on-device
     * UI verification by setting the system property
     * debug.vibescreen.allow_capture to 1 (via: adb shell setprop). Release
     * builds always keep FLAG_SECURE regardless of the property.
     */
    private fun screenCaptureAllowedForDebug(): Boolean {
        val debuggable =
            (applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
        if (!debuggable) return false
        return try {
            @Suppress("PrivateApi")
            val systemProperties = Class.forName("android.os.SystemProperties")
            val get = systemProperties.getMethod("get", String::class.java)
            (get.invoke(null, "debug.vibescreen.allow_capture") as? String) == "1"
        } catch (error: ReflectiveOperationException) {
            false
        }
    }

    /** FLAG_SECURE unless a debuggable build has explicitly opted into capture. */
    private fun secureFlagIfProtected(): Int =
        if (screenCaptureAllowedForDebug()) 0 else WindowManager.LayoutParams.FLAG_SECURE

    /** Keep the tablet awake only while foregrounded, while preserving screenshot protection when connected. */
    private fun setStreamingWindowState(enabled: Boolean) {
        applyStreamingWindowState(connected = enabled, foreground = isInForeground)
    }

    private fun applyStreamingWindowState(
        connected: Boolean,
        foreground: Boolean,
    ) {
        val update =
            StreamingWindowStatePolicy.update(
                connected = connected,
                foreground = foreground,
                secureFlag = secureFlagIfProtected(),
            )
        if (update.clearFlags != 0) window.clearFlags(update.clearFlags)
        if (update.addFlags != 0) window.addFlags(update.addFlags)
    }

    /**
     * Enable fullscreen immersive mode
     * Uses modern WindowInsets API on Android R+ for better system compatibility
     * Also handles display cutout (notch) to use full screen area
     */
    private fun enableFullscreenMode() {
        // Ensure we draw behind the cutout
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            window.attributes.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            window.insetsController?.let { controller ->
                controller.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                controller.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    or View.SYSTEM_UI_FLAG_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            )
        }
    }

    /**
     * Disable fullscreen mode (when disconnected)
     */
    private fun disableFullscreenMode() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.show(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_VISIBLE
        }
    }

    /**
     * Keep the video edge-to-edge but route the reported system-bar and
     * display-cutout insets into the floating chrome. The root keeps zero
     * padding so the SurfaceView still fills the panel; instead the insets feed
     * [safeAreaInsets], which margins the control bar and settings panel and
     * bounds the draggable overlay and settings button.
     */
    private fun setupSafeAreaInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, windowInsets ->
            // Keep stable system-bar bounds even while immersive mode hides
            // them; using only getInsets() would make chrome jump whenever the
            // transient bars change visibility. Cutout bounds remain physical.
            val bars = windowInsets.getInsetsIgnoringVisibility(WindowInsetsCompat.Type.systemBars())
            val cutout = windowInsets.getInsets(WindowInsetsCompat.Type.displayCutout())
            val updatedInsets =
                SafeAreaGeometry.Insets.of(
                    left = maxOf(bars.left, cutout.left),
                    top = maxOf(bars.top, cutout.top),
                    right = maxOf(bars.right, cutout.right),
                    bottom = maxOf(bars.bottom, cutout.bottom),
                )
            if (updatedInsets != safeAreaInsets) {
                safeAreaInsets = updatedInsets
                // Apply chrome margins before cloning the root constraints in
                // reclampFloatingControls(), so the clone preserves them.
                applySafeAreaToChrome()
                applyControlBarLayout()
                applyStatusOverlayLayout()
                reclampFloatingControls()
                activeSettingsDialog?.let(::resizeSettingsDialog)
            }
            // Do not consume: descendants that also observe insets still see them.
            windowInsets
        }
        // Request an initial pass so the first frame is already safe-inset aware.
        ViewCompat.requestApplyInsets(binding.root)
    }

    /**
     * Lay out the connection panel's header and actions columns for the current
     * configuration. Portrait keeps the original stacked, full-width visual;
     * landscape splits the brand/title header and the connection actions into
     * two weighted columns with a stable gap so the wide screen is not wasted
     * on a single narrow column. Video and safe-area handling are untouched.
     */
    private fun applyConnectionPanelLayout(connectionMode: ConnectionMode = prefs.connectionMode) {
        ConnectionPanelLayoutApplier.apply(
            resources,
            ConnectionPanelLayoutApplier.Views(
                content = binding.connectionContent,
                header = binding.connectionHeader,
                actions = binding.connectionActions,
                subtitle = binding.connectionSubtitle,
            ),
            connectionMode = connectionMode,
            subtitleExpanded = connectionSubtitleDisclosure.expanded,
        )
    }

    /**
     * Margin the control bar and connection panel by the safe insets so their
     * tap targets never sit under a notch or gesture bar. The settings button
     * uses [updateSettingsButtonPosition], which folds the same insets into its
     * constraint margins.
     */
    private fun applySafeAreaToChrome() {
        setInsetMargins(binding.controlBar)
        setInsetMargins(binding.settingsPanel)
    }

    private fun setInsetMargins(view: View) {
        val base =
            baseChromeMargins.getOrPut(view.id) {
                ChromeSafeAreaApplier.captureBaseMargins(view)
            }
        ChromeSafeAreaApplier.applyMargins(view, base, safeAreaInsets)
    }

    /**
     * Re-bound the draggable status overlay and the settings button into the
     * current safe rectangle. Called after insets change and after a rotation
     * or size change so a control saved in one orientation cannot strand
     * off-screen or under a cutout in another.
     */
    private fun reclampFloatingControls() {
        clampOverlayIntoSafeRect()
        // Re-anchor the settings button so its inset-aware margins are rebuilt.
        restoreSettingsButtonPosition()
    }

    /** The safe rectangle within the root using the latest insets. */
    private fun currentSafeRect(): SafeAreaGeometry.Rect {
        val margin = (SETTINGS_CHROME_MARGIN_DP * resources.displayMetrics.density).toInt()
        return SafeAreaGeometry.safeRect(
            parentWidth = binding.root.width,
            parentHeight = binding.root.height,
            insets = safeAreaInsets,
            marginPx = margin,
        )
    }

    /** Clamp the current overlay position into the safe rectangle in place. */
    private fun clampOverlayIntoSafeRect() {
        val overlay = binding.statusBar
        overlay.post {
            if (overlay.width == 0 || binding.root.width == 0) return@post
            val (x, y) =
                SafeAreaGeometry.clampToSafeRect(
                    x = overlay.x,
                    y = overlay.y,
                    viewWidth = overlay.width,
                    viewHeight = overlay.height,
                    safe = currentSafeRect(),
                )
            if (x != overlay.x || y != overlay.y) {
                overlay.x = x
                overlay.y = y
                if (prefs.overlayX >= 0 && prefs.overlayY >= 0) {
                    prefs.overlayX = x
                    prefs.overlayY = y
                }
            }
        }
    }

    override fun onConfigurationChanged(newConfig: android.content.res.Configuration) {
        super.onConfigurationChanged(newConfig)
        // configChanges keeps this activity alive across rotation/size changes,
        // so re-apply immersive mode and re-clamp floating controls once the new
        // insets arrive rather than relying on a recreate.
        enableFullscreenMode()
        ViewCompat.requestApplyInsets(binding.root)
        connectionSubtitleDisclosure.reset()
        applyConnectionPanelLayout()
        applyControlBarLayout()
        applyStatusOverlayLayout()
        if (!isConnected && prefs.connectionMode == ConnectionMode.INTERNET) {
            LiveRegionTextApplier.apply(binding.connectionTitle, getString(internetWaitingTitleResource()))
        }
        reclampFloatingControls()
        activeSettingsDialog?.let { dialog ->
            dialog.window?.decorView?.post { resizeSettingsDialog(dialog) }
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) enableFullscreenMode()
    }

    /**
     * Show a Material dialog without dropping the activity out of immersive
     * fullscreen. The dialog window is made non-focusable until it is shown so
     * the activity's hidden system bars are not revealed, focus is granted
     * immediately after, and immersive mode is re-applied when the dialog is
     * dismissed. Returns the shown dialog for optional further wiring.
     */
    private fun showImmersiveDialog(builder: MaterialAlertDialogBuilder): androidx.appcompat.app.AlertDialog {
        val dialog = builder.create()
        return showImmersiveDialog(dialog)
    }

    private fun showSecureImmersiveDialog(builder: MaterialAlertDialogBuilder): androidx.appcompat.app.AlertDialog {
        val dialog = builder.create()
        return showSecureImmersiveDialog(dialog)
    }

    private fun <T : Dialog> showSecureImmersiveDialog(dialog: T): T {
        dialog.window?.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        return showImmersiveDialog(dialog)
    }

    private fun <T : Dialog> showImmersiveDialog(dialog: T): T {
        dialog.window?.setFlags(
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
        )
        dialog.setOnDismissListener {
            // Re-hide the system bars the dialog may have surfaced.
            enableFullscreenMode()
            if (activeSettingsDialog === dialog) activeSettingsDialog = null
        }
        dialog.show()
        dialog.window?.let { win ->
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                win.decorView.windowInsetsController?.let { controller ->
                    controller.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                    controller.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                }
            } else {
                @Suppress("DEPRECATION")
                win.decorView.systemUiVisibility = window.decorView.systemUiVisibility or
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                    View.SYSTEM_UI_FLAG_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            }
            // Now that the bars are re-hidden, let the dialog take input.
            win.clearFlags(WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE)
        }
        return dialog
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun setupSurface() {
        binding.surfaceView.holder.addCallback(
            object : SurfaceHolder.Callback {
                override fun surfaceCreated(holder: SurfaceHolder) {
                    mainDiag("surfaceCreated")
                    log("Surface created")
                }

                override fun surfaceChanged(
                    holder: SurfaceHolder,
                    format: Int,
                    width: Int,
                    height: Int,
                ) {
                    mainDiag("surfaceChanged: ${width}x$height")
                    log("Surface changed: ${width}x$height")
                    // Don't initialize decoder here — wait for display config
                    // from the server so we use the correct resolution.
                    // Store the holder so we can initialize later.
                    if (currentSurfaceHolder !== holder) surfaceGeneration.incrementAndGet()
                    currentSurfaceHolder = holder
                    // If we already have a video configuration (reconnect case), init now.
                    if (videoDecoder == null) {
                        val internetConfiguration = internetVideoConfiguration
                        if (prefs.connectionMode == ConnectionMode.INTERNET) {
                            val internetLifecycle = internetVideoDecoderLifecycle
                            if (internetLifecycle?.hasPendingConfiguration == true) {
                                internetLifecycle.onSurfaceReady()
                            } else if (internetConfiguration != null && displayWidth > 0 && displayHeight > 0) {
                                val currentInternetSession = internetSession
                                val currentInternetGeneration = internetGeneration
                                configureInternetDecoder(
                                    internetConfiguration,
                                    currentInternetGeneration,
                                    AtomicReference(currentInternetSession),
                                )
                            }
                        } else if (prefs.connectionMode != ConnectionMode.INTERNET &&
                            mainSessionDisplayLifecycle?.hasPendingVideoConfiguration == true
                        ) {
                            mainSessionDisplayLifecycle?.onSurfaceReady()
                        } else if (prefs.connectionMode != ConnectionMode.INTERNET &&
                            encodedVideoConfigurationState.snapshot() != null
                        ) {
                            initializeDecoder(holder)
                        }
                    }
                }

                override fun surfaceDestroyed(holder: SurfaceHolder) {
                    mainDiag("surfaceDestroyed")
                    log("Surface destroyed")
                    completeCurrentNativeInputBoundary(InputPhase.INPUT_PHASE_CANCELLED) {
                        // Only release decoder, NOT the connection.
                        surfaceGeneration.incrementAndGet()
                        if (currentSurfaceHolder === holder) currentSurfaceHolder = null
                        releaseVideoDecoderAsync()
                    }
                }
            },
        )

        binding.inputViewport.setOnTouchListener { view, event ->
            handleTouch(view, event)
            true
        }
        binding.inputViewport.setOnGenericMotionListener { view, event ->
            handleGenericMotion(view, event)
        }
        binding.inputViewport.isFocusableInTouchMode = true
        binding.root.addOnLayoutChangeListener { _, left, _, right, _, oldLeft, _, oldRight, _ ->
            if (right - left != oldRight - oldLeft) {
                applyControlBarLayout()
                applyStatusOverlayLayout()
            }
            updateSurfaceViewportLayout()
        }
    }

    private fun handleGenericMotion(
        view: View,
        event: MotionEvent,
    ): Boolean {
        if (!isInForeground) return false
        if (prefs.connectionMode == ConnectionMode.INTERNET) {
            val session = internetSession ?: return false
            val active = canSendControllerInput(session)
            if (active) ControllerInputMapper.snapshot(event)?.let { snapshot ->
                val dispatch = internetControllerSessionState.applyMotion(snapshot)
                if (dispatch != null && sendStreamControllerDispatch(dispatch, "controller motion")) return true
                return ControllerInputConsumptionPolicy.shouldConsume(active, isSystemKey = false)
            }
            return handleInternetStylus(view, event, session, extendedOnly = true)
        }
        if (!isConnected) return false
        ControllerInputMapper.snapshot(event)?.let { snapshot ->
            val dispatch = streamControllerSessionState.applyMotion(snapshot)
            if (dispatch != null && sendStreamControllerDispatch(dispatch, "controller motion")) return true
            return ControllerInputConsumptionPolicy.shouldConsume(isConnected, isSystemKey = false)
        }
        val stylusSnapshot = StylusInputMapper.snapshot(event) { x, y -> mapInputPoint(view, x, y) }
        val client = streamClient
        if (stylusSnapshot.pointers.any { it.toolKind != null } && client?.canSendExtendedStylus() == true) {
            val samples = streamStylusContactRouter.map(stylusSnapshot, extendedNegotiated = true)
            if (samples.isNotEmpty() && client.sendMotionStylus(samples)) {
                mainDiagStylusForwarded("stream", event, samples, extended = true)
                trackStreamStylus(samples)
                return true
            }
        }
        val point = mapInputPoint(view, event.x, event.y)
        val nativePointerInput =
            when (event.actionMasked) {
                MotionEvent.ACTION_HOVER_MOVE, MotionEvent.ACTION_MOVE ->
                    ClientPointerInput(
                        ClientPointerAction.MOVE,
                        point.x,
                        point.y,
                        buttonState = event.buttonState,
                    )

                MotionEvent.ACTION_BUTTON_PRESS ->
                    ClientPointerInput(
                        ClientPointerAction.BUTTON_PRESS,
                        point.x,
                        point.y,
                        buttonState = event.buttonState,
                        actionButton = event.actionButton,
                    )

                MotionEvent.ACTION_BUTTON_RELEASE ->
                    ClientPointerInput(
                        ClientPointerAction.BUTTON_RELEASE,
                        point.x,
                        point.y,
                        buttonState = event.buttonState,
                        actionButton = event.actionButton,
                    )

                MotionEvent.ACTION_SCROLL ->
                    ClientPointerInput(
                        ClientPointerAction.SCROLL,
                        point.x,
                        point.y,
                        buttonState = event.buttonState,
                        horizontalScroll = event.getAxisValue(MotionEvent.AXIS_HSCROLL),
                        verticalScroll = event.getAxisValue(MotionEvent.AXIS_VSCROLL),
                    )

                else -> null
            }
        if (nativePointerInput != null) {
            when (ClientInputDispatch(currentSessionBinding()).sendPointer(nativePointerInput)) {
                ClientInputDispatchResult.SENT -> {
                    logNativePointerForwarded(event, nativePointerInput)
                    return true
                }
                ClientInputDispatchResult.REJECTED -> {
                    mainDiag("negotiated pointer sink rejected ${nativePointerInput.action}")
                    return true
                }

                ClientInputDispatchResult.UNSUPPORTED -> Unit
            }
        }
        if (event.actionMasked == MotionEvent.ACTION_BUTTON_PRESS &&
            event.isFromSource(InputDevice.SOURCE_MOUSE) &&
            event.buttonState and MotionEvent.BUTTON_SECONDARY != 0
        ) {
            synthesizeLegacyRightClick(view, event)
            return true
        }
        if (event.actionMasked != MotionEvent.ACTION_SCROLL) return false
        val gesture =
            LegacyScrollMapper.map(
                anchor = point,
                horizontalAxis = event.getAxisValue(MotionEvent.AXIS_HSCROLL),
                verticalAxis = event.getAxisValue(MotionEvent.AXIS_VSCROLL),
            ) ?: return false

        streamClient?.sendTouch(
            gesture.startFirst.x,
            gesture.startFirst.y,
            LEGACY_TOUCH_DOWN,
            LEGACY_SCROLL_POINTER_COUNT,
            gesture.startSecond.x,
            gesture.startSecond.y,
        )
        streamClient?.sendTouch(
            gesture.endFirst.x,
            gesture.endFirst.y,
            LEGACY_TOUCH_MOVE,
            LEGACY_SCROLL_POINTER_COUNT,
            gesture.endSecond.x,
            gesture.endSecond.y,
        )
        streamClient?.sendTouch(
            gesture.endFirst.x,
            gesture.endFirst.y,
            LEGACY_TOUCH_UP,
            LEGACY_SCROLL_POINTER_COUNT,
            gesture.endSecond.x,
            gesture.endSecond.y,
        )
        return true
    }

    private fun logNativePointerForwarded(
        event: MotionEvent,
        nativePointerInput: ClientPointerInput,
    ) {
        if (!shouldLogNativePointerForward(nativePointerInput.action)) return
        mainDiag(
            "native pointer forwarded action=${nativePointerInput.action} " +
                "source=${NativeInputWire.mouseLikeSourceNames(event.source, event.device?.sources).joinToString("+").ifEmpty { "OTHER" }} " +
                "buttonState=${event.buttonState} actionButton=${event.actionButton} " +
                "wireButtons=${NativeInputWire.buttonMask(event.buttonState)} " +
                "x=${nativePointerInput.x} y=${nativePointerInput.y}",
        )
    }

    private fun shouldLogNativePointerForward(action: ClientPointerAction): Boolean {
        if (action != ClientPointerAction.MOVE) return true
        val now = SystemClock.elapsedRealtime()
        if (now < nextNativePointerMoveDiagAtMs) return false
        nextNativePointerMoveDiagAtMs = now + NATIVE_POINTER_MOVE_DIAG_INTERVAL_MS
        return true
    }

    private fun synthesizeLegacyRightClick(
        view: View,
        event: MotionEvent,
    ) {
        val point = mapInputPoint(view, event.x, event.y)
        val client = streamClient ?: return
        val generation = activeSessionGeneration
        if (!isCurrentSession(client, generation)) return
        finishPendingRightClick()
        client.sendTouch(point.x, point.y, LEGACY_TOUCH_DOWN)
        val release =
            Runnable {
                if (isCurrentSession(client, generation)) {
                    client.sendTouch(point.x, point.y, LEGACY_TOUCH_UP)
                }
                pendingRightClickRelease = null
            }
        pendingRightClickRelease = release
        inputHandler.postDelayed(release, LEGACY_RIGHT_CLICK_HOLD_MS)
        mainDiag("secondary mouse button adapted to legacy long press")
    }

    private fun sendStreamControllerDispatch(
        dispatch: ControllerDispatch,
        source: String,
    ): Boolean {
        if (prefs.connectionMode == ConnectionMode.INTERNET) {
            return sendInternetControllerDispatch(dispatch, source)
        }
        val result = ClientInputDispatch(currentSessionBinding()).sendController(ClientControllerInput(dispatch))
        return when (result) {
            ClientInputDispatchResult.SENT -> true
            ClientInputDispatchResult.REJECTED -> {
                mainDiag("negotiated controller sink rejected $source")
                false
            }
            ClientInputDispatchResult.UNSUPPORTED -> {
                mainDiag("controller input blocked by host without controller capability source=$source")
                false
            }
        }
    }

    private fun sendInternetControllerDispatch(
        dispatch: ControllerDispatch,
        source: String,
        targetSession: InternetProductSession? = internetSession,
    ): Boolean {
        val session = targetSession ?: return false
        val events = dispatch.samples.map { sample -> ProductControllerEvent(internetInputIds.next(), sample) }
        val delivery =
            when (dispatch.delivery) {
                ControllerDelivery.ANALOG -> InternetControllerSendQueue.Delivery.ANALOG
                ControllerDelivery.STRUCTURAL -> InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL
            }
        val accepted = session.sendController(events, delivery)
        if (!accepted) mainDiag("internet controller sink rejected $source")
        return accepted
    }

    private fun activeControllerSessionState(): ControllerSessionState =
        if (prefs.connectionMode == ConnectionMode.INTERNET) {
            internetControllerSessionState
        } else {
            streamControllerSessionState
        }

    private fun canSendControllerInput(targetSession: InternetProductSession? = internetSession): Boolean =
        if (prefs.connectionMode == ConnectionMode.INTERNET) {
            targetSession?.canSendController() == true
        } else {
            isConnected
        }

    private fun finishPendingRightClick() {
        val release = pendingRightClickRelease ?: return
        inputHandler.removeCallbacks(release)
        release.run()
    }

    private fun setupUI() {
        binding.connectButton.setOnClickListener {
            var host =
                binding.hostInput.text
                    .toString()
                    .ifEmpty { "127.0.0.1" }
            val port =
                binding.portInput.text
                    .toString()
                    .toIntOrNull() ?: 54321

            // Convert localhost to 127.0.0.1 for better Android compatibility
            if (host.equals("localhost", ignoreCase = true)) {
                host = "127.0.0.1"
            }

            // Validate input
            if (host.isBlank()) {
                showUsbConnectionGuidance(
                    ConnectionGuidance(
                        kind = ConnectionFailureKind.UNKNOWN,
                        status = ConnectionGuidanceText(R.string.connection_issue),
                        message = ConnectionGuidanceText(R.string.host_address_required),
                    ),
                )
                return@setOnClickListener
            }

            clearUsbConnectionGuidance()
            updateStatus("Checking for your Mac…")
            automaticUsbConnect = false
            connect(host, port, automatic = false)
        }

        binding.disconnectButton.setOnClickListener {
            disconnect()
        }

        binding.openSourceLicensesButton.setOnClickListener {
            showOpenSourceNotices()
        }

        binding.connectionSettingsButton.setOnClickListener {
            showSettingsDialog()
        }

        setupInternetUi()
        binding.connectionSubtitle.setOnClickListener {
            if (!binding.connectionSubtitle.isClickable) return@setOnClickListener
            connectionSubtitleDisclosure.toggle()
            applyConnectionPanelLayout()
        }

        // Advanced settings toggle
        binding.showAdvanced.setOnClickListener {
            setConnectionDetailsVisible(!connectionDetailsVisible)
        }

        showDisconnectedStreamUi()
    }

    private fun showOpenSourceNotices() {
        val notice =
            try {
                val upstreamNotice = assets.open(UPSTREAM_NOTICE_ASSET).bufferedReader().use { it.readText() }
                val dependencies = assets.open(DEPENDENCY_LICENSES_ASSET).bufferedReader().use { it.readText() }
                "$upstreamNotice\n\n$dependencies"
            } catch (error: IOException) {
                mainDiag("Failed to read packaged open-source notices: ${error.message}")
                showError(getString(R.string.open_source_notices_unavailable))
                return
            }

        android.app.AlertDialog
            .Builder(this)
            .setTitle(R.string.open_source_notices_title)
            .setMessage(notice)
            .setPositiveButton(android.R.string.ok, null)
            .show()
    }

    private fun showError(message: String) {
        runOnUiThread {
            showImmersiveDialog(
                MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.connection_error_title)
                    .setMessage(message)
                    .setPositiveButton(android.R.string.ok, null),
            )
        }
    }

    private fun updateStatus(status: String) {
        runOnUiThread {
            LiveRegionTextApplier.apply(binding.statusText, status)
        }
    }

    private fun showUsbConnectionGuidance(guidance: ConnectionGuidance) {
        runOnUiThread {
            LiveRegionTextApplier.apply(binding.connectionErrorTitle, guidanceStatus(guidance))
            LiveRegionTextApplier.show(binding.connectionErrorMessage, guidanceMessage(guidance))
            binding.connectionErrorContainer.visibility = View.VISIBLE
            if (!connectionDetailsVisible) {
                setConnectionDetailsVisible(true)
            } else {
                updateChecklist()
            }
            updateStatus(guidanceStatus(guidance))
        }
    }

    private fun showTerminalConnectionGuidance(
        mode: ConnectionMode,
        guidance: ConnectionGuidance,
    ) {
        when (mode) {
            ConnectionMode.USB -> showUsbConnectionGuidance(guidance)
            ConnectionMode.WIRELESS -> {
                updateStatus(guidanceStatus(guidance))
                wirelessController.showConnectionGuidance(guidance)
            }
            ConnectionMode.INTERNET -> {
                LiveRegionTextApplier.show(
                    binding.internetErrorText,
                    guidanceFullMessage(guidance),
                )
                LiveRegionTextApplier.apply(
                    binding.internetStateText,
                    getString(
                        R.string.internet_state_format,
                        guidanceStatus(guidance),
                        getString(R.string.internet_route_pending),
                    ),
                )
            }
        }
    }

    private fun guidanceStatus(guidance: ConnectionGuidance): String =
        ConnectionGuidanceTextFormatter.format(resources, guidance.status)

    private fun guidanceMessage(guidance: ConnectionGuidance): String =
        ConnectionGuidanceTextFormatter.format(resources, guidance.message)

    private fun guidanceFullMessage(guidance: ConnectionGuidance): String =
        getString(R.string.connection_guidance_full_message, guidanceStatus(guidance), guidanceMessage(guidance))

    private fun clearUsbConnectionGuidance() {
        if (!::binding.isInitialized) return
        binding.connectionErrorContainer.visibility = View.GONE
        LiveRegionTextApplier.apply(binding.connectionErrorTitle, getString(R.string.connection_issue))
        LiveRegionTextApplier.hide(binding.connectionErrorMessage)
    }

    private fun setConnectionDetailsVisible(visible: Boolean) {
        connectionDetailsVisible = visible
        val visibility = if (visible) View.VISIBLE else View.GONE
        binding.checklistContainer.visibility = visibility
        binding.advancedSettings.visibility = visibility
        binding.showAdvanced.setText(
            if (visible) {
                R.string.hide_connection_details
            } else {
                R.string.connection_details
            },
        )
        if (visible) {
            updateChecklist()
        }
    }

    private fun updateDisconnectedHeader(mode: ConnectionMode) {
        if (!::binding.isInitialized || isConnected) return
        when (mode) {
            ConnectionMode.USB -> {
                LiveRegionTextApplier.apply(
                    binding.connectionTitle,
                    getString(if (isReconnecting) R.string.reconnecting_short else R.string.waiting_for_mac),
                )
                updateUsbTransportSubtitle()
                binding.connectionProgress.visibility = View.VISIBLE
                val connectAction =
                    UsbConnectActionPolicy.resolve(
                        connectionAttemptInProgress = connectionAttemptInProgress,
                        hasAttemptedConnection = hasAttemptedUsbConnection,
                    )
                binding.connectButton.setText(
                    when (connectAction) {
                        UsbConnectActionPolicy.Action.CONNECT -> R.string.connect
                        UsbConnectActionPolicy.Action.CONNECTING -> R.string.connecting
                        UsbConnectActionPolicy.Action.TRY_AGAIN -> R.string.try_again
                    },
                )
                binding.connectButton.isEnabled =
                    connectAction != UsbConnectActionPolicy.Action.CONNECTING
                updateStatus(getString(R.string.looking_for_mac))
            }
            ConnectionMode.WIRELESS -> {
                LiveRegionTextApplier.apply(binding.connectionTitle, getString(R.string.connect_wirelessly))
                LiveRegionTextApplier.apply(binding.connectionSubtitle, getString(R.string.wireless_pair_once))
                binding.connectionProgress.visibility = View.GONE
            }
            ConnectionMode.INTERNET -> {
                LiveRegionTextApplier.apply(binding.connectionTitle, getString(internetWaitingTitleResource()))
                LiveRegionTextApplier.apply(binding.connectionSubtitle, getString(R.string.internet_waiting_description))
                binding.connectionProgress.visibility = View.GONE
                refreshInternetProfileUi()
            }
        }
    }

    private fun internetWaitingTitleResource(): Int =
        if (resources.getBoolean(R.bool.connection_panel_two_column)) {
            R.string.internet_waiting_title_compact
        } else {
            R.string.internet_waiting_title
        }

    private fun setupInternetUi() {
        QUARANTINED_INTERNET_SESSION.get()?.let { internetSession = it }
        binding.internetRouteToggleGroup.check(
            if (prefs.internetForceRelay) R.id.internetForceRelay else R.id.internetPreferDirect,
        )
        binding.internetRouteToggleGroup.addOnButtonCheckedListener { _, checkedId, checked ->
            if (!checked) return@addOnButtonCheckedListener
            prefs.internetForceRelay = checkedId == R.id.internetForceRelay
        }
        binding.internetImportProfileButton.setOnClickListener { showInternetProfileImportDialog() }
        binding.internetScanProfileButton.setOnClickListener {
            when {
                cameraPerm.isGranted() -> launchInternetScanner()
                cameraPerm.isPermanentlyDenied() -> showInternetCameraPermissionBlocked()
                else -> cameraPerm.request(REQ_INTERNET_CAMERA)
            }
        }
        binding.internetConnectButton.setOnClickListener { connectInternet() }
        binding.internetDisconnectButton.setOnClickListener { disconnect() }
        binding.internetRevokeButton.setOnClickListener {
            showSecureImmersiveDialog(
                MaterialAlertDialogBuilder(this)
                .setTitle(R.string.internet_revoke_confirm_title)
                .setMessage(R.string.internet_revoke_confirm_message)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.internet_revoke_confirm_action) { _, _ ->
                    revokeInternetPairing("user_requested")
                },
            )
        }
        val pendingCleanup = retryPendingInternetRevocationCleanup()
        if (pendingCleanup.isNotEmpty()) {
            LiveRegionTextApplier.show(
                binding.internetErrorText,
                getString(R.string.internet_revoke_partial_failure, pendingCleanup.joinToString()),
            )
        }
        try {
            retryPendingPairingPersistenceCleanup()
        } catch (failure: Throwable) {
            showInternetFailure(failure)
        }
        refreshInternetProfileUi()
        if (internetSession != null && internetRevocationCoordinator.hasActiveReservation()) {
            binding.internetDisconnectButton.visibility = View.VISIBLE
        }
    }

    private fun showInternetProfileImportDialog() {
        if (!allowInternetCredentialMutation()) return
        val content = layoutInflater.inflate(R.layout.dialog_internet_profile_import, null, false)
        val input =
            content.findViewById<EditText>(R.id.internetProfileImportInput).apply {
                hint = getString(R.string.internet_import_hint)
                setHorizontallyScrolling(false)
                inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
                imeOptions =
                    android.view.inputmethod.EditorInfo.IME_FLAG_NO_EXTRACT_UI or
                    android.view.inputmethod.EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
                importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
                isSaveEnabled = false
            }
        val dialog =
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.internet_import_title)
                .setView(content)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.internet_import_action, null)
                .create()
        dialog.setOnShowListener {
            dialog.getButton(android.app.AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                try {
                    check(allowInternetCredentialMutation()) { "Internet revocation quarantine is active" }
                    internetProfileStore.import(
                        input.text.toString(),
                        internetStoredSessionFactory,
                        internetRevocationCoordinator,
                    )
                    input.text?.clear()
                    requiredFreshInternetEpoch = 0L
                    LiveRegionTextApplier.hide(binding.internetErrorText)
                    LiveRegionTextApplier.apply(binding.internetStateText, getString(R.string.internet_profile_imported))
                    refreshInternetProfileUi()
                    dialog.dismiss()
                } catch (failure: Throwable) {
                    input.error = failure.message ?: getString(R.string.internet_error_title)
                }
            }
        }
        showSecureImmersiveDialog(dialog)
    }

    private fun launchInternetScanner() {
        if (!allowInternetCredentialMutation()) return
        startActivityForResult(Intent(this, QRScannerActivity::class.java), REQ_INTERNET_SCAN)
    }

    private fun beginInternetPairing(encodedUrl: String) {
        try {
            check(allowInternetCredentialMutation()) { "Internet revocation quarantine is active" }
            check(retryPendingInternetRevocationCleanup().isEmpty()) {
                "Finish the pending local revocation cleanup before pairing again"
            }
            retryPendingPairingPersistenceCleanup()
            discardPendingInternetPairing()
            retryPendingPairingIdentityAliasCleanup()
            val identityEpoch = internetStoredSessionFactory.reserveNextIdentityEpoch()
            val identityStore = AndroidDeviceIdentityStore()
            val identityCleanup =
                PendingPairingIdentityAlias.create(
                    pendingPairingIdentityAliasPersistence,
                    internetDeviceId,
                    identityEpoch,
                    identityStore::delete,
                )
            pendingInternetPairingIdentity = identityCleanup
            val identity =
                try {
                    identityStore.loadOrCreateForPairing(internetDeviceId, identityEpoch)
                } catch (failure: Throwable) {
                    discardPendingInternetPairing(failure = failure)
                    throw failure
                }
            val pending = try {
                InternetPairingCoordinator(identity, internetStoredSessionFactory).begin(
                    encodedUrl,
                    (Build.MODEL ?: "Android").take(MAX_DEVICE_NAME_LENGTH),
                )
            } catch (failure: Throwable) {
                discardPendingInternetPairing(failure = failure)
                throw failure
            }
            pendingInternetPairing = pending
            if (internetProfileStore.isRevoked(pending.publicMetadata.pairingIdentifier)) {
                discardPendingInternetPairing(pending)
                throw IllegalStateException("This Mac pairing is locally revoked")
            }
            showInternetPairingCompletionDialog(pending)
        } catch (failure: Throwable) {
            showInternetFailure(failure)
        }
    }

    private fun showInternetPairingCompletionDialog(pending: PendingInternetPairing) {
        val container = layoutInflater.inflate(R.layout.dialog_internet_pairing_completion, null, false)
        container.findViewById<TextView>(R.id.internetPairingRequestText).apply {
            text = pending.request.encode()
            setTextIsSelectable(true)
            setHorizontallyScrolling(false)
        }
        container.findViewById<TextView>(R.id.internetPairingIdentityText).apply {
            text =
                getString(
                    R.string.internet_pairing_identity_format,
                    pending.publicMetadata.hostIdentity.deviceId,
                    pending.publicMetadata.hostIdentity.keyId.take(16),
                    pending.publicMetadata.deviceIdentity.keyId.take(16),
                )
            setTextIsSelectable(true)
        }
        val acceptance =
            container.findViewById<EditText>(R.id.internetPairingAcceptanceInput).apply {
                hint = getString(R.string.internet_pairing_acceptance_hint)
                inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
                imeOptions =
                    android.view.inputmethod.EditorInfo.IME_FLAG_NO_EXTRACT_UI or
                    android.view.inputmethod.EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
                importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
                isSaveEnabled = false
            }
        val dialog =
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.internet_pairing_complete_title)
                .setMessage(R.string.internet_pairing_complete_message)
                .setView(container)
                .setNegativeButton(R.string.cancel) { _, _ ->
                    runCatching { discardPendingInternetPairing(pending) }.onFailure(::showInternetFailure)
                }
                .setPositiveButton(R.string.internet_pairing_complete_action, null)
                .create()
        dialog.setOnShowListener {
            dialog.getButton(android.app.AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                try {
                    val parsed = InternetPairingAcceptance.parse(acceptance.text.toString())
                    try {
                        internetRevocationCoordinator.withCredentialMutationAdmission(
                            durableBlock = {
                                internetProfileStore.hasDurableCredentialMutationBlock(
                                    pending.publicMetadata.pairingIdentifier,
                                ) || internetStoredSessionFactory.hasPendingPairingPersistenceCleanup()
                            },
                        ) { permit ->
                            pending.complete(parsed).also { completed ->
                                internetProfileStore.recordVerifiedPairing(
                                    permit,
                                    completed.metadata,
                                    internetStoredSessionFactory,
                                )
                            }
                        }
                        val identityCleanup = checkNotNull(pendingInternetPairingIdentity) {
                            "Pending pairing identity ownership is unavailable"
                        }
                        check(pendingInternetPairing === pending) { "Pending pairing changed before identity ownership commit" }
                        identityCleanup.commit()
                        pendingInternetPairingIdentity = null
                        pendingInternetPairing = null
                        refreshInternetProfileUi()
                    } catch (failure: Throwable) {
                        discardPendingInternetPairing(pending, failure)
                        dialog.dismiss()
                        showInternetFailure(failure)
                        return@setOnClickListener
                    }
                    acceptance.text?.clear()
                    LiveRegionTextApplier.apply(binding.internetStateText, getString(R.string.internet_pairing_complete))
                    dialog.dismiss()
                } catch (failure: Throwable) {
                    acceptance.error = failure.message ?: getString(R.string.internet_error_title)
                }
            }
        }
        dialog.setOnCancelListener {
            runCatching { discardPendingInternetPairing(pending) }.onFailure(::showInternetFailure)
        }
        dialog.setCanceledOnTouchOutside(false)
        showSecureImmersiveDialog(dialog)
    }

    private fun discardPendingInternetPairing(
        expected: PendingInternetPairing? = null,
        failure: Throwable? = null,
    ) {
        val pending = pendingInternetPairing
        if (expected != null && pending !== expected) return
        pending?.close()
        val identityCleanup = pendingInternetPairingIdentity
        try {
            identityCleanup?.close()
        } catch (cleanupFailure: Throwable) {
            if (failure == null) throw cleanupFailure
            failure.addSuppressed(cleanupFailure)
            return
        }
        pendingInternetPairing = null
        pendingInternetPairingIdentity = null
    }

    private fun refreshInternetProfileUi() {
        if (!::binding.isInitialized) return
        val profile = internetProfileStore.loadPublicProfile()
        val fingerprint = internetProfileStore.verifiedHostKeyFingerprint()
        val summary =
            if (profile == null && fingerprint == null) {
                getString(R.string.internet_profile_missing)
            } else if (profile == null) {
                getString(R.string.internet_paired_without_lease, fingerprint)
            } else {
                getString(
                    R.string.internet_profile_format,
                    profile.signalingUrl,
                    profile.signalingSessionId,
                    profile.authoritativeSessionEpoch,
                    fingerprint ?: getString(R.string.empty_value),
                )
            }
        LiveRegionTextApplier.apply(binding.internetProfileSummary, summary)
        binding.internetConnectButton.isEnabled =
            profile != null &&
                profile.authoritativeSessionEpoch > requiredFreshInternetEpoch &&
                internetSession == null
        binding.internetRevokeButton.isEnabled = profile != null || internetProfileStore.hasVerifiedPairing()
        allowInternetCredentialMutation()
    }

    private fun showInternetCameraPermissionBlocked() {
        LiveRegionTextApplier.show(
            binding.internetErrorText,
            getString(R.string.internet_camera_permission_blocked),
        )
        cameraPerm.openAppSettings()
    }

    private fun showConnectedStreamUi() {
        val connectedStatus = getString(R.string.connected_streaming)
        clearUsbConnectionGuidance()
        setConnectionDetailsVisible(false)
        updateConnectionSecurityStatus()
        binding.videoViewport.visibility = View.VISIBLE
        binding.disconnectedBackdrop.visibility = View.GONE
        binding.settingsPanel.visibility = View.GONE
        binding.connectionSettingsButton.visibility = View.GONE
        LiveRegionTextApplier.apply(binding.statusText, connectedStatus)
        // Route settings through the tap-to-reveal control bar instead of a
        // persistent floating button that occludes the video.
        binding.settingsButton.visibility = View.GONE
        updateOverlayVisibility(prefs.showStatsOverlay)
        revealControlBar(ControlBarAccessibilityPolicy.RevealReason.SESSION_STARTED)
        connectionStatusAnnouncements.announceIfChanged(connectedStatus) { announcement ->
            binding.controlBar.announceForAccessibility(announcement)
        }
    }

    private fun showDisconnectedStreamUi() {
        connectionStatusAnnouncements.reset()
        // Keep one stable layout while the USB retry loop runs. Showing system
        // bars or changing orientation here resized/recreated the Activity and
        // made the waiting state visibly flash.
        enableFullscreenMode()
        // Keep the video viewport laid out so the SurfaceView holds a live
        // surface while waiting to connect. The opaque backdrop above it hides
        // any stale frames. This lets an incoming video configuration bind the
        // decoder immediately instead of deadlocking on a surface that a GONE
        // view never creates.
        binding.videoViewport.visibility = View.VISIBLE
        binding.disconnectedBackdrop.visibility = View.VISIBLE
        binding.settingsPanel.visibility = View.VISIBLE
        val useInlineSettingsButton = resources.getBoolean(R.bool.connection_panel_inline_settings_button)
        binding.connectionSettingsButton.visibility = if (useInlineSettingsButton) View.VISIBLE else View.GONE
        // Stream overlay opacity can be very low; the disconnected settings
        // entry remains a primary recovery affordance and must stay readable.
        binding.settingsButton.alpha = 1f
        binding.settingsButton.visibility = if (useInlineSettingsButton) View.GONE else View.VISIBLE
        if (!useInlineSettingsButton) {
            binding.settingsButton.translationZ = binding.settingsPanel.elevation + 1f
            binding.settingsButton.bringToFront()
        }
        binding.statusBar.visibility = View.GONE
        binding.connectionSecurityGroup.visibility = View.GONE
        binding.connectButton.isEnabled = true
        binding.statusIndicator.setBackgroundResource(R.drawable.status_indicator_waiting)
        discardPendingOutgoingFileTransfer()
        hideControlBar()
        updateDisconnectedHeader(prefs.connectionMode)
    }

    /** Wires the tap-to-reveal control bar (display capsule, settings, disconnect). */
    private fun setupControlBar() {
        // The video input plane remains reachable after the transient chrome is
        // hidden. TalkBack users can activate it to restore every session
        // control without relying on a raw ACTION_DOWN gesture.
        binding.inputViewport.setOnClickListener { revealControlBar() }
        binding.controlSettingsButton.setOnClickListener {
            showSettingsDialog()
            revealControlBar()
        }
        binding.controlDisconnectButton.setOnClickListener { confirmDisconnect() }
        binding.controlHostActionsButton.setOnClickListener {
            revealControlBar()
            showHostActionsMenu()
        }
        binding.controlClipboardButton.setOnClickListener {
            revealControlBar()
            showClipboardMenu()
        }
        binding.controlFileTransferButton.setOnClickListener {
            revealControlBar()
            beginChooseFileForTransfer()
        }
        // The whole capsule row is the dropdown-selector tap target so touch
        // users hit it reliably, not just the leading icon.
        binding.displayCapsuleGroup.setOnClickListener {
            revealControlBar()
            showDisplaysMenu()
        }
        // Icon-only controls carry a tooltip so their purpose is discoverable
        // on long-press/hover, not just to screen readers via contentDescription.
        TooltipCompat.setTooltipText(binding.controlSettingsButton, getText(R.string.control_settings))
        TooltipCompat.setTooltipText(binding.controlDisconnectButton, getText(R.string.control_disconnect))
        TooltipCompat.setTooltipText(binding.displayCapsuleGroup, getText(R.string.control_displays))
        TooltipCompat.setTooltipText(binding.controlHostActionsButton, getText(R.string.control_host_actions))
        TooltipCompat.setTooltipText(binding.controlClipboardButton, getText(R.string.control_clipboard))
        TooltipCompat.setTooltipText(binding.controlFileTransferButton, getText(R.string.control_file_transfer))
    }

    /**
     * Disconnect is destructive and sits on the same compact bar as the other
     * controls, so confirm before tearing the session down. Keeping the bar
     * revealed while the dialog is up avoids it auto-hiding under the prompt.
     */
    private fun confirmDisconnect() {
        revealControlBar()
        showImmersiveDialog(
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.disconnect_confirm_title)
                .setMessage(R.string.disconnect_confirm_message)
                .setPositiveButton(R.string.disconnect_confirm_action) { _, _ -> disconnect() }
                .setNegativeButton(R.string.disconnect_confirm_cancel, null),
        )
    }

    private fun revealControlBar(
        revealReason: ControlBarAccessibilityPolicy.RevealReason =
            ControlBarAccessibilityPolicy.RevealReason.USER_REQUEST,
    ) {
        if (!isConnected) return
        binding.controlBar.visibility = View.VISIBLE
        ControlBarAccessibilityApplier.applyRevealAction(
            binding.inputViewport,
            connected = true,
            controlBarVisible = true,
        )
        binding.controlBar.animate().alpha(1f).setDuration(120).start()
        controlBarHandler.removeCallbacks(controlBarHideRunnable)
        ControlBarAccessibilityPolicy.autoHideDelayMs(
            touchExplorationEnabled = accessibilityManager.isTouchExplorationEnabled,
            revealReason = revealReason,
        )?.let { delayMs ->
            controlBarHandler.postDelayed(controlBarHideRunnable, delayMs)
        }
    }

    private fun hideControlBar() {
        controlBarHandler.removeCallbacks(controlBarHideRunnable)
        binding.controlBar.visibility = View.GONE
        ControlBarAccessibilityApplier.applyRevealAction(
            binding.inputViewport,
            connected = isConnected,
            controlBarVisible = false,
        )
    }

    /**
     * Reconcile the display-selection capsule with the host list. The capsule
     * is a single displays icon that opens a dropdown menu on tap; the inline
     * chip row was removed because it overflowed the compact, centered capsule
     * and pushed selectable displays off-screen. Display selection is offered
     * only when it was negotiated and more than one display exists; otherwise
     * the whole capsule collapses so single-display sessions expose no dead tap
     * area. The menu itself is built lazily in showDisplaysMenu() from the
     * stored availableDisplays/selectedDisplayId state.
     */
    private fun populateDisplayCapsule(
        displays: List<StreamDisplayOption>,
        selectedId: String,
    ) {
        availableDisplays = displays
        selectedDisplayId = selectedId
        // Collapse the whole display picker on single-display or un-negotiated
        // sessions so the resting capsule stays a minimal, low-misfire target.
        refreshDisplayCapsuleLabel()
        applyControlBarLayout()
    }

    /**
     * Reflect the active display on the capsule so touch users can see which
     * Mac display they are on before opening the dropdown. The TextView owns
     * visual ellipsizing while this full label remains available to TalkBack.
     */
    private fun refreshDisplayCapsuleLabel() {
        DisplayCapsuleViewBinder.bind(
            resources = resources,
            selector = binding.displayCapsuleGroup,
            labelView = binding.controlDisplaysLabel,
            displaySelection = currentSessionBinding().capabilities.displaySelection,
            displays = availableDisplays,
            selectedId = selectedDisplayId,
        )
    }

    /**
     * Present the negotiated displays as a single-choice dropdown anchored on
     * the displays icon. The active display carries a check; selecting a
     * different one drives the existing runtime selectDisplay() path and
     * closes the menu. Ignored when display selection is not selectable.
     */
    private fun showDisplaysMenu() {
        val selectable =
            DisplayCapsulePolicy.isSelectable(
                currentSessionBinding().capabilities.displaySelection,
                availableDisplays,
            )
        if (!selectable) return
        val displays = availableDisplays
        val popup = PopupMenu(this, binding.displayCapsuleGroup)
        val menu = popup.menu
        menu.setGroupCheckable(0, true, true)
        displays.forEachIndexed { index, option ->
            val kindTag =
                when (DisplayCapsulePolicy.displayKind(option)) {
                    DisplayCapsulePolicy.DisplayKind.PRIMARY -> getString(R.string.display_option_primary)
                    DisplayCapsulePolicy.DisplayKind.VIRTUAL -> getString(R.string.display_option_virtual)
                    DisplayCapsulePolicy.DisplayKind.BUILT_IN -> getString(R.string.display_option_builtin)
                    DisplayCapsulePolicy.DisplayKind.EXTERNAL -> getString(R.string.display_option_external)
                }
            val item =
                menu.add(
                    0,
                    index,
                    index,
                    getString(
                        R.string.display_option_format,
                        "${option.name} · $kindTag",
                        option.width,
                        option.height,
                    ),
                )
            item.isChecked = option.id == selectedDisplayId
        }
        popup.setOnMenuItemClickListener { item ->
            val option = displays.getOrNull(item.itemId) ?: return@setOnMenuItemClickListener false
            if (option.id != selectedDisplayId) {
                mainDiag("capsule selectDisplay target=${option.id} from=$selectedDisplayId")
                streamClient?.selectDisplay(option.id)
                selectedDisplayId = option.id
                refreshDisplayCapsuleLabel()
            }
            true
        }
        // The open popup is anchored on the control bar, so its 3s auto-hide is
        // frozen while the menu is up; otherwise the anchor could disappear and
        // dismiss the menu out from under a user still deciding. Restart the
        // timer only once the menu closes.
        controlBarHandler.removeCallbacks(controlBarHideRunnable)
        popup.setOnDismissListener {
            revealControlBar()
        }
        showControlPopupMenu(popup)
    }

    /**
     * Reconcile the host-action control with the negotiated capability and the
     * host-advertised catalog. The button collapses entirely unless host
     * actions were negotiated and the host advertised at least one action this
     * client understands, so unsupported sessions expose no dead tap area. The
     * menu is built lazily in showHostActionsMenu() from the stored list.
     */
    private fun populateHostActions(actions: List<HostActionOption>) {
        availableHostActions = actions
        val available =
            HostActionMenuPolicy.isAvailable(
                currentSessionBinding().capabilities.hostActions,
                actions,
            )
        binding.controlHostActionsButton.visibility = if (available) View.VISIBLE else View.GONE
        binding.controlHostActionsButton.isEnabled = available
        applyControlBarLayout()
    }

    /** Clipboard is absent from legacy and unnegotiated sessions. */
    private fun refreshClipboardControl() {
        val client = streamClient
        val available =
            client != null &&
                ClipboardMenuPolicy.isAvailable(currentSessionBinding().capabilities.clipboard)
        binding.controlClipboardButton.visibility = if (available) View.VISIBLE else View.GONE
        binding.controlClipboardButton.isEnabled = available && client?.canSendClipboard == true
        updateClipboardAccessibilityLabel(client, activeSessionGeneration)
        applyControlBarLayout()
    }

    private fun updateClipboardAccessibilityLabel(
        client: StreamClient?,
        generation: Long,
    ) {
        val pending =
            client != null && clipboardApprovalState.hasPendingReceive(client, generation)
        binding.controlClipboardButton.contentDescription =
            getString(if (pending) R.string.control_clipboard_pending else R.string.control_clipboard)
        TooltipCompat.setTooltipText(
            binding.controlClipboardButton,
            binding.controlClipboardButton.contentDescription,
        )
    }

    /** File transfer is absent from legacy and unnegotiated sessions. */
    private fun refreshFileTransferControl() {
        val client = streamClient
        val available =
            client != null &&
                client.canTransferFiles &&
                ClientControlAvailability.isSupported(
                    ClientControl.FILE_TRANSFER,
                    currentSessionBinding().capabilities,
                )
        binding.controlFileTransferButton.visibility = if (available) View.VISIBLE else View.GONE
        binding.controlFileTransferButton.isEnabled = available
        applyControlBarLayout()
    }

    private fun beginChooseFileForTransfer() {
        val client = streamClient ?: return
        if (!isCurrentSession(client, activeSessionGeneration) ||
            !currentSessionBinding().capabilities.fileTransfer ||
            !client.canTransferFiles
        ) {
            Toast.makeText(this, R.string.file_transfer_unavailable, Toast.LENGTH_SHORT).show()
            return
        }
        val intent =
            Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE)
                .setType("*/*")
        runCatching { startActivityForResult(intent, REQ_FILE_TRANSFER_OPEN) }
            .onFailure { failure ->
                mainDiag("file transfer picker failed: " + failure.javaClass.simpleName)
                Toast.makeText(this, R.string.file_transfer_pick_failed, Toast.LENGTH_SHORT).show()
            }
    }

    private fun handleFileTransferPickerResult(
        resultCode: Int,
        data: Intent?,
    ) {
        if (resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        val client = streamClient
        val generation = activeSessionGeneration
        if (client == null ||
            !isCurrentSession(client, generation) ||
            !currentSessionBinding().capabilities.fileTransfer ||
            !client.canTransferFiles
        ) {
            Toast.makeText(this, R.string.file_transfer_unavailable, Toast.LENGTH_SHORT).show()
            return
        }
        val maximumFileBytes = client.negotiatedMaxFileBytes
        lifecycleScope.launch(Dispatchers.IO) {
            val mimeType = contentResolver.getType(uri) ?: "application/octet-stream"
            val sent =
                runCatching {
                    val file = stageOutgoingFileTransfer(uri, maximumFileBytes)
                    val registered = withContext(Dispatchers.Main) {
                        if (isCurrentSession(client, generation) && client.canTransferFiles) {
                            discardPendingOutgoingFileTransfer()
                            pendingOutgoingFileTransfer = file
                            true
                        } else {
                            file.deleteRecursivelyBestEffort()
                            false
                        }
                    }
                    registered && client.offerFile(file, mimeType)
            }
            withContext(Dispatchers.Main) {
                if (!isCurrentSession(client, generation)) return@withContext
                val sentValue =
                    sent.getOrElse { failure ->
                        mainDiag("file transfer staging failed: " + failure.javaClass.simpleName)
                        discardPendingOutgoingFileTransfer()
                        Toast.makeText(this@MainActivity, R.string.file_transfer_pick_failed, Toast.LENGTH_SHORT).show()
                        return@withContext
                    }
                Toast.makeText(
                    this@MainActivity,
                    if (sentValue) R.string.file_transfer_sent_to_mac else R.string.file_transfer_send_failed,
                    Toast.LENGTH_SHORT,
                ).show()
                if (!sentValue) discardPendingOutgoingFileTransfer()
            }
        }
    }

    private fun stageOutgoingFileTransfer(
        uri: Uri,
        maximumFileBytes: Long,
    ): File {
        val safeName = safeOutgoingFileName(displayNameForUri(uri))
        val directory = File(cacheDir, "vibescreen-outgoing-files/" + UUID.randomUUID())
        if (!directory.mkdirs()) throw IOException("Unable to create outgoing file staging directory")
        val staged = File(directory, safeName)
        var total = 0L
        try {
            contentResolver.openInputStream(uri).use { input ->
                if (input == null) throw IOException("Unable to open selected file")
                FileOutputStream(staged).use { output ->
                    val buffer = ByteArray(FILE_TRANSFER_COPY_BUFFER_BYTES)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        total += read.toLong()
                        if (total > maximumFileBytes) {
                            throw IOException("Selected file exceeds the file transfer limit")
                        }
                        output.write(buffer, 0, read)
                    }
                }
            }
            return staged
        } catch (failure: Throwable) {
            directory.deleteRecursivelyBestEffort()
            throw failure
        }
    }

    private fun displayNameForUri(uri: Uri): String? =
        runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (index >= 0) cursor.getString(index) else null
                } else {
                    null
                }
            }
        }.getOrNull()

    private fun safeOutgoingFileName(displayName: String?): String {
        val candidate =
            displayName
                ?.substringAfterLast('/')
                ?.substringAfterLast('\\')
                ?.replace('\u0000', '_')
                ?.trim()
                ?.take(MAX_FILE_TRANSFER_DISPLAY_NAME_CHARS)
                .orEmpty()
        return if (candidate.isNotEmpty() &&
            candidate != "." &&
            candidate != ".." &&
            !candidate.contains('/') &&
            !candidate.contains('\\')
        ) {
            candidate
        } else {
            "transfer.bin"
        }
    }

    private fun promptIncomingFileOffer(
        client: StreamClient,
        generation: Long,
        offer: dev.vibescreen.protocol.v1.FileOffer,
    ) {
        runOnUiThread {
            if (!isCurrentSession(client, generation) || !client.canTransferFiles) {
                client.respondToFileOffer(offer, accepted = false)
                return@runOnUiThread
            }
            if (pendingIncomingFileDialog != null) {
                client.respondToFileOffer(offer, accepted = false)
                return@runOnUiThread
            }

            var decided = false
            val timeout = Runnable {
                if (pendingIncomingFileDialog == null || decided) return@Runnable
                decided = true
                pendingIncomingFileDialog?.dismiss()
                pendingIncomingFileDialog = null
                client.respondToFileOffer(offer, accepted = false)
                Toast.makeText(this, R.string.file_transfer_offer_expired, Toast.LENGTH_SHORT).show()
            }
            val dialog =
                MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.file_transfer_offer_title)
                    .setMessage(
                        getString(
                            R.string.file_transfer_offer_message,
                            safeIncomingDisplayName(offer.fileName),
                            readableByteCount(offer.byteLength),
                            fileTransferDestinationLabel(),
                        ),
                    )
                    .setPositiveButton(R.string.file_transfer_accept) { _, _ ->
                        if (decided) return@setPositiveButton
                        decided = true
                        pendingIncomingFileDialog = null
                        fileTransferApprovalHandler.removeCallbacks(timeout)
                        client.respondToFileOffer(offer, accepted = true)
                    }
                    .setNegativeButton(R.string.file_transfer_reject) { _, _ ->
                        if (decided) return@setNegativeButton
                        decided = true
                        pendingIncomingFileDialog = null
                        fileTransferApprovalHandler.removeCallbacks(timeout)
                        client.respondToFileOffer(offer, accepted = false)
                    }
                    .setOnCancelListener {
                        if (decided) return@setOnCancelListener
                        decided = true
                        pendingIncomingFileDialog = null
                        fileTransferApprovalHandler.removeCallbacks(timeout)
                        client.respondToFileOffer(offer, accepted = false)
                    }
            pendingIncomingFileDialog = showImmersiveDialog(dialog)
            fileTransferApprovalHandler.postDelayed(timeout, FILE_TRANSFER_APPROVAL_TIMEOUT_MS)
        }
    }

    private fun safeIncomingDisplayName(fileName: String): String =
        fileName.takeIf { it.isNotBlank() }?.take(MAX_FILE_TRANSFER_DISPLAY_NAME_CHARS) ?:
            getString(R.string.file_transfer_unknown_name)

    private fun readableByteCount(bytes: Long): String {
        if (bytes < 1024L) return getString(R.string.file_transfer_size_bytes, bytes)
        val units = arrayOf("KiB", "MiB", "GiB")
        var value = bytes.toDouble()
        var unitIndex = -1
        while (value >= 1024.0 && unitIndex < units.lastIndex) {
            value /= 1024.0
            unitIndex += 1
        }
        return String.format(Locale.US, "%.1f %s", value, units[unitIndex])
    }

    private fun onIncomingFileCompleted(completed: dev.telemachus.display.protocol.CompletedIncomingFile) {
        lifecycleScope.launch(Dispatchers.IO) {
            val displayName = safeIncomingDisplayName(completed.fileName)
            val stagedBytes = completed.stagingFile.length()
            val saved = runCatching { saveIncomingFileToDownloads(completed, displayName) }
            completed.stagingFile.deleteBestEffort()
            runOnUiThread {
                saved
                    .onSuccess {
                        mainDiag(
                            "file transfer saved bytes=$stagedBytes " +
                                "transfer_id=${completed.transferId.shortDebugId()}",
                        )
                        Toast.makeText(
                            this@MainActivity,
                            getString(fileTransferSavedMessage(), displayName),
                            Toast.LENGTH_LONG,
                        ).show()
                    }
                    .onFailure { failure ->
                        mainDiag(
                            "file transfer save failed bytes=$stagedBytes " +
                                "transfer_id=${completed.transferId.shortDebugId()} " +
                                failure.javaClass.simpleName,
                        )
                        Toast.makeText(
                            this@MainActivity,
                            getString(R.string.file_transfer_save_failed, displayName),
                            Toast.LENGTH_LONG,
                        ).show()
                    }
            }
        }
    }

    private fun saveIncomingFileToDownloads(
        completed: dev.telemachus.display.protocol.CompletedIncomingFile,
        displayName: String,
    ): Uri {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values =
                ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, displayName)
                    put(MediaStore.Downloads.MIME_TYPE, completed.mimeType.ifBlank { "application/octet-stream" })
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                    put(MediaStore.Downloads.IS_PENDING, 1)
                }
            val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw IOException("Unable to create downloads entry")
            try {
                contentResolver.openOutputStream(uri)?.use { output ->
                    copyFileTo(completed.stagingFile, output)
                } ?: throw IOException("Unable to open downloads entry")
                ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }.also {
                    contentResolver.update(uri, it, null, null)
                }
                return uri
            } catch (failure: Throwable) {
                runCatching { contentResolver.delete(uri, null, null) }
                throw failure
            }
        }

        val downloads = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            ?: throw IOException("Downloads directory is unavailable")
        if (!downloads.exists() && !downloads.mkdirs()) {
            throw IOException("Unable to create downloads directory")
        }
        val target = File(downloads, displayName)
        FileOutputStream(target).use { output -> copyFileTo(completed.stagingFile, output) }
        return Uri.fromFile(target)
    }

    private fun fileTransferDestinationLabel(): String =
        getString(
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                R.string.file_transfer_downloads_destination
            } else {
                R.string.file_transfer_app_downloads_destination
            },
        )

    private fun fileTransferSavedMessage(): Int =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            R.string.file_transfer_saved_to_downloads
        } else {
            R.string.file_transfer_saved_to_app_downloads
        }


    private fun copyFileTo(source: File, output: OutputStream) {
        BufferedInputStream(source.inputStream()).use { input ->
            BufferedOutputStream(output).use { bufferedOutput ->
                val buffer = ByteArray(FILE_TRANSFER_COPY_BUFFER_BYTES)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    bufferedOutput.write(buffer, 0, read)
                }
            }
        }
    }

    private fun discardPendingOutgoingFileTransfer() {
        pendingOutgoingFileTransfer?.deleteRecursivelyBestEffort()
        pendingOutgoingFileTransfer = null
    }

    private fun File.deleteRecursivelyBestEffort() {
        runCatching {
            if (isDirectory) {
                deleteRecursively()
            } else {
                parentFile?.deleteRecursively() ?: delete()
            }
        }.onFailure { failure ->
            mainDiag("file transfer cleanup failed: " + failure.javaClass.simpleName)
        }
    }

    private fun File.deleteBestEffort() {
        runCatching { delete() }
            .onFailure { failure ->
                mainDiag("file transfer staging delete failed: " + failure.javaClass.simpleName)
            }
    }

    private fun ByteString.shortDebugId(): String =
        toByteArray().take(4).joinToString("") { "%02x".format(it) }

    /**
     * Builds the menu without inspecting Android's clipboard. The local text is
     * read only after the user selects Send to Mac.
     */
    private fun showClipboardMenu() {
        val client = streamClient ?: return
        val generation = activeSessionGeneration
        if (!isCurrentSession(client, generation) ||
            !currentSessionBinding().capabilities.clipboard ||
            !client.canSendClipboard
        ) {
            return
        }
        val popup = PopupMenu(this, binding.controlClipboardButton, Gravity.NO_GRAVITY)
        popup.menu.add(0, CLIPBOARD_MENU_SEND, 0, R.string.clipboard_send_to_mac).isEnabled = true
        popup.menu
            .add(0, CLIPBOARD_MENU_RECEIVE, 1, R.string.clipboard_get_from_mac)
            .isEnabled = clipboardApprovalState.hasPendingReceive(client, generation)
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                CLIPBOARD_MENU_SEND -> beginSendLocalClipboard(client, generation)
                CLIPBOARD_MENU_RECEIVE -> beginReceiveRemoteClipboard(client, generation)
                else -> false
            }
        }
        controlBarHandler.removeCallbacks(controlBarHideRunnable)
        popup.setOnDismissListener { revealControlBar() }
        showControlPopupMenu(popup)
    }

    private fun beginSendLocalClipboard(
        client: StreamClient,
        generation: Long,
    ): Boolean {
        if (!isCurrentSession(client, generation) || !client.canSendClipboard) return false
        if (prefs.connectionMode == ConnectionMode.WIRELESS) {
            showImmersiveDialog(
                MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.clipboard_lan_confirm_title)
                    .setMessage(LanClipboardProtectionMessagePolicy.sendMessage(client.currentLanProtectionState))
                    .setPositiveButton(R.string.clipboard_lan_confirm_action) { _, _ ->
                        sendLocalClipboard(client, generation)
                    }
                    .setNegativeButton(R.string.cancel, null),
            )
            return true
        }
        return sendLocalClipboard(client, generation)
    }

    /** Reads the system clipboard only after the transport-specific approval. */
    private fun sendLocalClipboard(
        client: StreamClient,
        generation: Long,
    ): Boolean {
        if (!isCurrentSession(client, generation) || !client.canSendClipboard) return false
        val text =
            runCatching {
                getSystemService(ClipboardManager::class.java)
                    .primaryClip
                    ?.takeIf { it.itemCount > 0 }
                    ?.getItemAt(0)
                    ?.text
                    ?.toString()
            }.getOrNull()
        if (!ClipboardMenuPolicy.canSend(text)) {
            Toast.makeText(this, R.string.clipboard_empty, Toast.LENGTH_SHORT).show()
            return true
        }
        val clipboardText = requireNotNull(text)
        if (!ClipboardMenuPolicy.isWithinSizeLimit(clipboardText, client.negotiatedMaxClipboardBytes)) {
            Toast.makeText(this, R.string.clipboard_too_large, Toast.LENGTH_SHORT).show()
            return true
        }
        val sent = client.offerClipboard(clipboardText)
        Toast.makeText(
            this,
            if (sent) R.string.clipboard_sent_to_mac else R.string.clipboard_send_failed,
            Toast.LENGTH_SHORT,
        ).show()
        return true
    }

    private fun receiveRemoteClipboard(
        client: StreamClient,
        generation: Long,
    ): Boolean {
        if (!isCurrentSession(client, generation) || !client.canSendClipboard) return false
        val direct = clipboardApprovalState.directContentForConfirmation(client, generation)
        if (direct != null) {
            showDirectClipboardConfirmation(client, generation, direct)
            return true
        }
        val offer = clipboardApprovalState.offerForRequest(client, generation)
        if (offer == null) {
            Toast.makeText(this, R.string.clipboard_mac_unavailable, Toast.LENGTH_SHORT).show()
            return true
        }
        if (!clipboardApprovalState.approveOffer(client, generation, offer.changeId) ||
            !client.requestClipboard(offer.changeId)
        ) {
            clipboardApprovalState.cancelOfferApproval(client, generation, offer.changeId)
            Toast.makeText(this, R.string.clipboard_receive_failed, Toast.LENGTH_SHORT).show()
        } else {
            scheduleClipboardRequestTimeout(client, generation, offer.changeId)
            refreshClipboardControl()
        }
        return true
    }

    private fun beginReceiveRemoteClipboard(
        client: StreamClient,
        generation: Long,
    ): Boolean {
        if (!isCurrentSession(client, generation) || !client.canSendClipboard) return false
        val direct = clipboardApprovalState.directContentForConfirmation(client, generation)
        if (direct != null || prefs.connectionMode != ConnectionMode.WIRELESS) {
            return receiveRemoteClipboard(client, generation)
        }
        showImmersiveDialog(
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.clipboard_lan_receive_confirm_title)
                .setMessage(LanClipboardProtectionMessagePolicy.receiveMessage(client.currentLanProtectionState))
                .setPositiveButton(R.string.clipboard_receive_confirm_action) { _, _ ->
                    receiveRemoteClipboard(client, generation)
                }
                .setNegativeButton(R.string.cancel, null),
        )
        return true
    }

    private fun showDirectClipboardConfirmation(
        client: StreamClient,
        generation: Long,
        content: ClipboardContentData,
    ) {
        showImmersiveDialog(
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.clipboard_receive_confirm_title)
                .setMessage(
                    if (prefs.connectionMode == ConnectionMode.WIRELESS) {
                        LanClipboardProtectionMessagePolicy.directReceiveMessage(client.currentLanProtectionState)
                    } else {
                        R.string.clipboard_receive_confirm_message
                    },
                )
                .setPositiveButton(R.string.clipboard_receive_confirm_action) { _, _ ->
                    val approved =
                        clipboardApprovalState.consumeDirectContent(
                            client,
                            generation,
                            content.changeId,
                        )
                    if (approved != null) writeRemoteClipboard(approved)
                    updateClipboardAccessibilityLabel(client, generation)
                }
                .setNegativeButton(R.string.cancel) { _, _ ->
                    clipboardApprovalState.discardDirectContent(client, generation, content.changeId)
                    updateClipboardAccessibilityLabel(client, generation)
                },
        )
    }

    private fun writeRemoteClipboard(content: ClipboardContentData) {
        val text = content.content.toString(Charsets.UTF_8)
        val result =
            runCatching {
                getSystemService(ClipboardManager::class.java).setPrimaryClip(
                    ClipData.newPlainText(getString(R.string.clipboard_plain_text_label), text),
                )
            }
        Toast.makeText(
            this,
            if (result.isSuccess) R.string.clipboard_copied_from_mac else R.string.clipboard_write_failed,
            Toast.LENGTH_SHORT,
        ).show()
        result.exceptionOrNull()?.let { error ->
            mainDiag("clipboard write failed: " + error.javaClass.simpleName)
        }
    }

    private fun scheduleClipboardRequestTimeout(
        client: StreamClient,
        generation: Long,
        changeId: ByteArray,
    ) {
        cancelClipboardRequestTimeout()
        val exactChangeId = changeId.copyOf()
        val timeout =
            Runnable {
                clipboardRequestTimeout = null
                if (!isCurrentSession(client, generation)) return@Runnable
                val submitted = client.expireClipboardRequest(exactChangeId) { expired ->
                    runOnUiThread {
                        if (!expired || !isCurrentSession(client, generation)) return@runOnUiThread
                        if (!clipboardApprovalState.cancelOfferApproval(client, generation, exactChangeId)) {
                            return@runOnUiThread
                        }
                        refreshClipboardControl()
                        Toast.makeText(this, R.string.clipboard_request_timed_out, Toast.LENGTH_SHORT).show()
                    }
                }
                if (!submitted && clipboardApprovalState.cancelOfferApproval(client, generation, exactChangeId)) {
                    refreshClipboardControl()
                }
            }
        clipboardRequestTimeout = timeout
        clipboardRequestHandler.postDelayed(timeout, CLIPBOARD_REQUEST_TIMEOUT_MS)
    }

    private fun cancelClipboardRequestTimeout() {
        clipboardRequestTimeout?.let(clipboardRequestHandler::removeCallbacks)
        clipboardRequestTimeout = null
    }

    private fun applyControlBarLayout() {
        val windowWidthPx = binding.root.width.takeIf { it > 0 } ?: resources.displayMetrics.widthPixels
        ControlBarLayoutApplier.apply(
            views =
                ControlBarViews(
                    card = binding.controlBar,
                    content = binding.controlBarContent,
                    connectionStatus = binding.connectionSecurityGroup,
                    displaySelector = binding.displayCapsuleGroup,
                    actions = binding.controlActionsGroup,
                    hostAction = binding.controlHostActionsButton,
                    clipboard = binding.controlClipboardButton,
                    fileTransfer = binding.controlFileTransferButton,
                    settings = binding.controlSettingsButton,
                    disconnect = binding.controlDisconnectButton,
                ),
            resources = resources,
            windowWidthPx = windowWidthPx,
            safeAreaInsets = safeAreaInsets,
        )
    }

    private fun applyStatusOverlayLayout() {
        val windowWidthPx = binding.root.width.takeIf { it > 0 } ?: resources.displayMetrics.widthPixels
        StatusOverlayLayoutApplier.apply(
            views =
                StatusOverlayViews(
                    card = binding.statusBar,
                    content = binding.statusBarContent,
                ),
            resources = resources,
            windowWidthPx = windowWidthPx,
            safeAreaInsets = safeAreaInsets,
        )
    }

    private fun updateConnectionSecurityStatus(
        lanProtectionState: LanRecordProtectionState = streamClient?.currentLanProtectionState
            ?: LanRecordProtectionState.NOT_APPLICABLE,
    ) {
        val presentation =
            ConnectionSecurityPresentationPolicy.presentation(
                mode = prefs.connectionMode,
                lanProtectionState = lanProtectionState,
            )
        val label = getString(presentation.labelResource)
        val detail = getString(presentation.detailResource)
        val detailColor =
            ContextCompat.getColor(
                this,
                if (presentation.warning) R.color.warning else R.color.on_surface_muted,
            )
        LiveRegionTextApplier.apply(binding.connectionSecurityLabel, label)
        LiveRegionTextApplier.apply(binding.connectionSecurityDetail, detail)
        binding.connectionSecurityDetail.setTextColor(detailColor)
        binding.connectionSecurityGroup.contentDescription =
            getString(R.string.stream_status_accessibility, label, detail)
        binding.connectionSecurityGroup.visibility = View.VISIBLE
        binding.securityText.text = getString(R.string.stream_status_overlay_format, label, detail)
        binding.securityText.setTextColor(detailColor)
        applyControlBarLayout()
        applyStatusOverlayLayout()
        clampOverlayIntoSafeRect()
    }

    /**
     * Present the advertised host actions as a dropdown anchored on the window
     * icon. Selecting one drives the runtime invokeHostAction() path and closes
     * the menu. Ignored when host actions are not currently available.
     */
    private fun showHostActionsMenu() {
        val actions = availableHostActions
        val available =
            HostActionMenuPolicy.isAvailable(
                currentSessionBinding().capabilities.hostActions,
                actions,
            )
        if (!available) return
        val moveDefault = getString(R.string.host_action_move_window)
        val returnDefault = getString(R.string.host_action_return_windows)
        val popup = PopupMenu(this, binding.controlHostActionsButton, Gravity.NO_GRAVITY)
        val menu = popup.menu
        actions.forEachIndexed { index, option ->
            menu.add(0, index, index, HostActionMenuPolicy.menuLabel(option, moveDefault, returnDefault))
        }
        popup.setOnMenuItemClickListener { item ->
            val option = actions.getOrNull(item.itemId) ?: return@setOnMenuItemClickListener false
            val label = HostActionMenuPolicy.menuLabel(option, moveDefault, returnDefault)
            requestHostAction(option, label)
            true
        }
        // Freeze the control bar's auto-hide while the menu is up so the anchor
        // cannot disappear under a user still deciding; restart it on dismiss.
        controlBarHandler.removeCallbacks(controlBarHideRunnable)
        popup.setOnDismissListener {
            revealControlBar()
        }
        showControlPopupMenu(popup)
    }

    private fun showControlPopupMenu(popup: PopupMenu) {
        popup.gravity = Gravity.END
        popup.show()
    }

    private fun requestHostAction(option: HostActionOption, label: String) {
        if (HostActionMenuPolicy.selectionMode(option) == HostActionSelectionMode.INVOKE) {
            invokeHostActionIfAvailable(option.id, label)
            return
        }
        showImmersiveDialog(
            MaterialAlertDialogBuilder(this)
                .setTitle(label)
                .setMessage(R.string.host_action_confirm_message)
                .setPositiveButton(R.string.host_action_confirm_action) { _, _ ->
                    invokeHostActionIfAvailable(option.id, label)
                }
                .setNegativeButton(R.string.cancel, null),
        )
    }

    private fun invokeHostActionIfAvailable(actionId: String, label: String) {
        val actionIsCurrent =
            HostActionMenuPolicy.isAvailable(
                currentSessionBinding().capabilities.hostActions,
                availableHostActions,
            ) && availableHostActions.any { it.id == actionId }
        val client = streamClient
        if (!actionIsCurrent || client == null) return
        mainDiag("capsule invokeHostAction id=$actionId")
        client.invokeHostAction(actionId)
        Toast.makeText(this, getString(R.string.host_action_sent, label), Toast.LENGTH_SHORT).show()
    }

    @SuppressLint("ClickableViewAccessibility", "InflateParams")
    private fun setupDraggableOverlay() {
        binding.statusBar.setOnTouchListener { view, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    isDraggingOverlay = true
                    overlayDx = view.x - event.rawX
                    overlayDy = view.y - event.rawY
                    true
                }

                MotionEvent.ACTION_MOVE -> {
                    if (isDraggingOverlay) {
                        // Calculate new position
                        var newX = event.rawX + overlayDx
                        var newY = event.rawY + overlayDy

                        // Constrain to the safe rectangle (system bars + cutout)
                        // so the overlay cannot be dragged under a notch or a
                        // gesture bar on any edge.
                        val clamped =
                            SafeAreaGeometry.clampToSafeRect(
                                x = newX,
                                y = newY,
                                viewWidth = view.width,
                                viewHeight = view.height,
                                safe = currentSafeRect(),
                            )
                        newX = clamped.first
                        newY = clamped.second

                        view
                            .animate()
                            .x(newX)
                            .y(newY)
                            .setDuration(0)
                            .start()
                    }
                    true
                }

                MotionEvent.ACTION_UP -> {
                    if (isDraggingOverlay) {
                        // Save position
                        prefs.overlayX = view.x
                        prefs.overlayY = view.y
                        isDraggingOverlay = false
                    }
                    true
                }

                else -> {
                    false
                }
            }
        }
    }

    private fun restoreOverlayPosition() {
        val x = prefs.overlayX
        val y = prefs.overlayY

        if (x >= 0 && y >= 0) {
            positionOverlayAt(x, y)
        }

        updateOverlayOpacity(prefs.overlayOpacity)

        // Apply visibility
        updateOverlayVisibility(prefs.showStatsOverlay)
    }

    /**
     * Place the overlay at a saved position but clamp it into the current safe
     * rectangle first, so a position saved in one orientation cannot land under
     * a cutout or off-screen after a rotation or size change.
     */
    private fun positionOverlayAt(
        x: Float,
        y: Float,
    ) {
        val overlay = binding.statusBar
        overlay.post {
            if (overlay.width == 0 || binding.root.width == 0) {
                overlay.x = x
                overlay.y = y
                return@post
            }
            val (clampedX, clampedY) =
                SafeAreaGeometry.clampToSafeRect(
                    x = x,
                    y = y,
                    viewWidth = overlay.width,
                    viewHeight = overlay.height,
                    safe = currentSafeRect(),
                )
            overlay.x = clampedX
            overlay.y = clampedY
        }
    }

    private fun updateOverlayOpacity(opacity: Float) {
        binding.statusBar.alpha = opacity
    }

    private fun updateOverlayVisibility(show: Boolean) {
        if (streamClient != null && show) {
            applyStatusOverlayLayout()
            binding.statusBar.visibility = View.VISIBLE
            // Restore position when showing
            val x = prefs.overlayX
            val y = prefs.overlayY
            if (x >= 0 && y >= 0) {
                positionOverlayAt(x, y)
            } else {
                clampOverlayIntoSafeRect()
            }
        } else {
            binding.statusBar.visibility = View.GONE
        }
    }

    @SuppressLint("InflateParams", "SetTextI18n")
    /**
     * Wire the settings video controls to the client video-preference sender.
     * When [available] is false the section is disabled and shows a short note,
     * because the host has not negotiated client video control. Quality and
     * frame-rate changes send immediately; the bitrate slider updates its label
     * live and sends once the user stops dragging so a drag does not flood the
     * host with reconfigurations.
     */
    private fun setupVideoControls(
        available: Boolean,
        unavailableNote: TextView,
        qualityGroup: MaterialButtonToggleGroup,
        qualityButtons: Map<VideoQualityChoice, MaterialButton>,
        frameRateGroup: MaterialButtonToggleGroup,
        frameRateButtons: Map<Int, MaterialButton>,
        bitrateSlider: Slider,
        bitrateValue: TextView,
    ) {
        fun renderBitrate(mbps: Int) {
            bitrateValue.text = getString(R.string.video_bitrate_value, mbps)
        }

        // Initialize control state from the saved preferences regardless of
        // availability so the panel reflects the last choice.
        qualityButtons[prefs.videoQuality]?.let { qualityGroup.check(it.id) }
        frameRateButtons[prefs.videoFrameRate]?.let { frameRateGroup.check(it.id) }
        val initialBitrate =
            prefs.videoBitrateMbps.coerceIn(
                ClientVideoBounds.MIN_BITRATE_MBPS,
                ClientVideoBounds.MAX_BITRATE_MBPS,
            )
        bitrateSlider.value = initialBitrate.toFloat()
        renderBitrate(initialBitrate)

        unavailableNote.visibility = if (available) View.GONE else View.VISIBLE
        qualityGroup.isEnabled = available
        frameRateGroup.isEnabled = available
        qualityButtons.values.forEach { it.isEnabled = available }
        frameRateButtons.values.forEach { it.isEnabled = available }
        bitrateSlider.isEnabled = available

        if (!available) return

        var suppressQualityListener = false

        fun syncQualityAutoForExplicitVideoSetting() {
            if (prefs.videoQuality == VideoQualityChoice.AUTO) return
            suppressQualityListener = true
            qualityButtons[VideoQualityChoice.AUTO]?.let { autoButton ->
                qualityGroup.check(autoButton.id)
            }
            suppressQualityListener = false
            prefs.videoQuality = VideoQualityChoice.AUTO
        }

        fun announceRequest(kind: VideoPreferenceFeedbackKind) {
            if (!VideoPreferenceFeedbackPolicy.shouldAnnounceRequest(clientAvailable = available && streamClient != null)) {
                return
            }
            val messageId =
                when (kind) {
                    VideoPreferenceFeedbackKind.QUALITY -> R.string.video_quality_request_sent
                    VideoPreferenceFeedbackKind.FRAME_RATE -> R.string.video_frame_rate_request_sent
                    VideoPreferenceFeedbackKind.BITRATE -> R.string.video_bitrate_request_sent
                }
            Toast.makeText(this, messageId, Toast.LENGTH_SHORT).show()
        }

        qualityGroup.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (suppressQualityListener) return@addOnButtonCheckedListener
            if (!isChecked) return@addOnButtonCheckedListener
            val choice =
                qualityButtons.entries.firstOrNull { it.value.id == checkedId }?.key
                    ?: return@addOnButtonCheckedListener
            // Queue the host request first, then persist, so a stored preference
            // always reflects a request that was actually handed to the client.
            // AUTO cannot be expressed by an empty preset (that means "keep
            // current"), so it sends an explicit reset-to-auto request instead
            // of sending nothing.
            if (choice == VideoQualityChoice.AUTO) {
                streamClient?.setVideoPreferences(
                    bitrateKbps = 0,
                    framesPerSecond = 0,
                    qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
                    resetQualityToAuto = true,
                )
            } else {
                // A preset carries no explicit bitrate, so the host maps the preset.
                streamClient?.setVideoPreferences(
                    bitrateKbps = 0,
                    framesPerSecond = 0,
                    qualityPreset = choice.preset,
                )
            }
            prefs.videoQuality = choice
            announceRequest(VideoPreferenceFeedbackKind.QUALITY)
        }

        frameRateGroup.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (!isChecked) return@addOnButtonCheckedListener
            val fps =
                frameRateButtons.entries.firstOrNull { it.value.id == checkedId }?.key
                    ?: return@addOnButtonCheckedListener
            streamClient?.setVideoPreferences(
                bitrateKbps = 0,
                framesPerSecond = fps,
                qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
                resetQualityToAuto = true,
            )
            syncQualityAutoForExplicitVideoSetting()
            prefs.videoFrameRate = fps
            announceRequest(VideoPreferenceFeedbackKind.FRAME_RATE)
        }

        bitrateSlider.addOnChangeListener { _, value, _ ->
            renderBitrate(value.toInt())
        }
        bitrateSlider.addOnSliderTouchListener(
            object : Slider.OnSliderTouchListener {
                override fun onStartTrackingTouch(slider: Slider) = Unit

                override fun onStopTrackingTouch(slider: Slider) {
                    val mbps = slider.value.toInt()
                    // An explicit bitrate wins over the preset intent.
                    streamClient?.setVideoPreferences(
                        bitrateKbps = mbps * ClientVideoBounds.KBPS_PER_MBPS,
                        framesPerSecond = 0,
                        qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
                        resetQualityToAuto = true,
                    )
                    syncQualityAutoForExplicitVideoSetting()
                    prefs.videoBitrateMbps = mbps
                    announceRequest(VideoPreferenceFeedbackKind.BITRATE)
                }
            },
        )
    }

    private fun showSettingsDialog() {
        val dialog = Dialog(this)
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)
        dialog.setContentView(R.layout.dialog_settings)
        dialog.window?.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))

        val view = dialog.findViewById<View>(android.R.id.content)
        val showStatsSwitch = view.findViewById<SwitchMaterial>(R.id.showStatsSwitch)
        val opacitySlider = view.findViewById<Slider>(R.id.opacitySlider)
        val opacityValue = view.findViewById<TextView>(R.id.opacityValue)
        val resetButton = view.findViewById<View>(R.id.resetPositionButton)
        val resetSettingsBtn = view.findViewById<View>(R.id.resetSettingsButton)
        val disconnectButton = view.findViewById<View>(R.id.disconnectSettingsButton)
        val closeButton = view.findViewById<View>(R.id.closeButton)
        val scaleFitButton = view.findViewById<MaterialButton>(R.id.scaleFitButton)
        val scaleFillButton = view.findViewById<MaterialButton>(R.id.scaleFillButton)
        val rotationGroup = view.findViewById<MaterialButtonToggleGroup>(R.id.rotationGroup)
        val rotationButtons =
            mapOf(
                ClientRotation.FOLLOW_HOST to view.findViewById<MaterialButton>(R.id.rotationFollow),
                ClientRotation.CLOCKWISE_90 to view.findViewById<MaterialButton>(R.id.rotation90),
                ClientRotation.UPSIDE_DOWN to view.findViewById<MaterialButton>(R.id.rotation180),
                ClientRotation.COUNTER_CLOCKWISE_90 to view.findViewById<MaterialButton>(R.id.rotation270),
            )
        val displayCapability = view.findViewById<TextView>(R.id.displayCapability)

        // Video tuning controls.
        val videoControlUnavailable = view.findViewById<TextView>(R.id.videoControlUnavailable)
        val videoQualityGroup = view.findViewById<MaterialButtonToggleGroup>(R.id.videoQualityGroup)
        val videoQualityAuto = view.findViewById<MaterialButton>(R.id.videoQualityAuto)
        val videoQualitySmooth = view.findViewById<MaterialButton>(R.id.videoQualitySmooth)
        val videoQualityBalanced = view.findViewById<MaterialButton>(R.id.videoQualityBalanced)
        val videoQualitySharp = view.findViewById<MaterialButton>(R.id.videoQualitySharp)
        val videoFrameRateGroup = view.findViewById<MaterialButtonToggleGroup>(R.id.videoFrameRateGroup)
        val videoFps30 = view.findViewById<MaterialButton>(R.id.videoFps30)
        val videoFps60 = view.findViewById<MaterialButton>(R.id.videoFps60)
        val videoFps120 = view.findViewById<MaterialButton>(R.id.videoFps120)
        val videoBitrateSlider = view.findViewById<Slider>(R.id.videoBitrateSlider)
        val videoBitrateValue = view.findViewById<TextView>(R.id.videoBitrateValue)

        renderDeviceHealth(dialog)

        // Only show Disconnect when actually streaming. Otherwise the button is
        // a no-op and confuses users into clicking it twice.
        disconnectButton.visibility = if (isConnected) View.VISIBLE else View.GONE

        // Position buttons (8 directions)
        val cornerTopLeft = view.findViewById<MaterialButton>(R.id.cornerTopLeft)
        val cornerTopRight = view.findViewById<MaterialButton>(R.id.cornerTopRight)
        val cornerBottomLeft = view.findViewById<MaterialButton>(R.id.cornerBottomLeft)
        val cornerBottomRight = view.findViewById<MaterialButton>(R.id.cornerBottomRight)
        val positionTopCenter = view.findViewById<MaterialButton>(R.id.positionTopCenter)
        val positionBottomCenter = view.findViewById<MaterialButton>(R.id.positionBottomCenter)
        val positionCenterLeft = view.findViewById<MaterialButton>(R.id.positionCenterLeft)
        val positionCenterRight = view.findViewById<MaterialButton>(R.id.positionCenterRight)
        val positionButtons =
            listOf(
                cornerBottomRight to R.string.settings_position_bottom_right,
                cornerBottomLeft to R.string.settings_position_bottom_left,
                cornerTopRight to R.string.settings_position_top_right,
                cornerTopLeft to R.string.settings_position_top_left,
                positionTopCenter to R.string.settings_position_top,
                positionBottomCenter to R.string.settings_position_bottom,
                positionCenterLeft to R.string.settings_position_left,
                positionCenterRight to R.string.settings_position_right,
            )
        positionButtons.forEach { (button, description) ->
            button.contentDescription = getString(description)
            button.isCheckable = true
        }

        // Load current settings
        showStatsSwitch.isChecked = prefs.showStatsOverlay
        opacitySlider.value = prefs.overlayOpacity
        opacityValue.text = "${(prefs.overlayOpacity * 100).toInt()}%"
        displayCapability.setText(
            if (currentSessionBinding().capabilities.displaySelection) {
                R.string.display_selection_available
            } else {
                R.string.display_selection_host_only
            },
        )

        fun updateViewportButtons() {
            scaleFitButton.isChecked = prefs.videoScaleMode == VideoScaleMode.FIT
            scaleFillButton.isChecked = prefs.videoScaleMode == VideoScaleMode.FILL
            rotationButtons[prefs.clientRotation]?.let { rotationGroup.check(it.id) }
        }
        updateViewportButtons()

        // Highlight current position selection (8 positions)
        // 0=BottomRight, 1=BottomLeft, 2=TopRight, 3=TopLeft
        // 4=TopCenter, 5=BottomCenter, 6=CenterLeft, 7=CenterRight
        fun updatePositionSelection(selectedPosition: Int) {
            positionButtons.forEachIndexed { index, (button, _) ->
                val selected = index == selectedPosition
                button.isChecked = selected
                button.isSelected = selected
                ViewCompat.setStateDescription(
                    button,
                    getString(if (selected) R.string.selected else R.string.not_selected),
                )
                if (selected) {
                    button.backgroundTintList =
                        android.content.res.ColorStateList
                            .valueOf(0x334CAF50)
                } else {
                    button.backgroundTintList = null
                }
            }
        }
        updatePositionSelection(prefs.settingsButtonCorner)

        // Setup listeners
        showStatsSwitch.setOnCheckedChangeListener { _, isChecked ->
            prefs.showStatsOverlay = isChecked
            updateOverlayVisibility(isChecked)
        }

        opacitySlider.addOnChangeListener { _, value, _ ->
            prefs.overlayOpacity = value
            updateOverlayOpacity(value)
            opacityValue.text = "${(value * 100).toInt()}%"
        }

        scaleFitButton.setOnClickListener {
            applyVideoScaleMode(VideoScaleMode.FIT)
            updateSurfaceViewportLayout()
            updateViewportButtons()
        }
        scaleFillButton.setOnClickListener {
            applyVideoScaleMode(VideoScaleMode.FILL)
            updateSurfaceViewportLayout()
            updateViewportButtons()
        }
        rotationGroup.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (!isChecked) return@addOnButtonCheckedListener
            val rotation =
                rotationButtons.entries.firstOrNull { it.value.id == checkedId }?.key
                    ?: return@addOnButtonCheckedListener
            if (prefs.clientRotation == rotation) return@addOnButtonCheckedListener
            prefs.clientRotation = rotation
            applyRotation(displayRotation)
        }

        // Video tuning. The controls are only actionable when the host
        // negotiated client video control; otherwise the section shows a short
        // note instead of sending requests the host would reject.
        val videoControlAvailable =
            streamClient?.negotiatedCapabilities()?.contains(
                dev.vibescreen.protocol.v1.Capability.CAPABILITY_CLIENT_VIDEO_CONTROL,
            ) == true
        setupVideoControls(
            available = videoControlAvailable,
            unavailableNote = videoControlUnavailable,
            qualityGroup = videoQualityGroup,
            qualityButtons =
                mapOf(
                    VideoQualityChoice.AUTO to videoQualityAuto,
                    VideoQualityChoice.SMOOTH to videoQualitySmooth,
                    VideoQualityChoice.BALANCED to videoQualityBalanced,
                    VideoQualityChoice.SHARP to videoQualitySharp,
                ),
            frameRateGroup = videoFrameRateGroup,
            frameRateButtons =
                mapOf(
                    30 to videoFps30,
                    60 to videoFps60,
                    120 to videoFps120,
                ),
            bitrateSlider = videoBitrateSlider,
            bitrateValue = videoBitrateValue,
        )

        resetButton.setOnClickListener {
            prefs.overlayX = -1f
            prefs.overlayY = -1f
            // Return to the resting spot (bottom-left), away from the
            // top-center control bar. The overlay is positioned absolutely to
            // match the drag handler, so compute the bottom-left corner from
            // the parent bounds once the view is measured.
            val overlay = binding.statusBar
            overlay.post {
                val safe = currentSafeRect()
                val targetX = safe.left
                val targetY = (safe.bottom - overlay.height).coerceAtLeast(safe.top)
                overlay
                    .animate()
                    .x(targetX)
                    .y(targetY)
                    .setDuration(300)
                    .start()
            }
        }

        // Position button listeners (8 directions)
        cornerBottomRight.setOnClickListener {
            prefs.settingsButtonCorner = 0
            updatePositionSelection(0)
            updateSettingsButtonPosition(0)
        }

        cornerBottomLeft.setOnClickListener {
            prefs.settingsButtonCorner = 1
            updatePositionSelection(1)
            updateSettingsButtonPosition(1)
        }

        cornerTopRight.setOnClickListener {
            prefs.settingsButtonCorner = 2
            updatePositionSelection(2)
            updateSettingsButtonPosition(2)
        }

        cornerTopLeft.setOnClickListener {
            prefs.settingsButtonCorner = 3
            updatePositionSelection(3)
            updateSettingsButtonPosition(3)
        }

        positionTopCenter.setOnClickListener {
            prefs.settingsButtonCorner = 4
            updatePositionSelection(4)
            updateSettingsButtonPosition(4)
        }

        positionBottomCenter.setOnClickListener {
            prefs.settingsButtonCorner = 5
            updatePositionSelection(5)
            updateSettingsButtonPosition(5)
        }

        positionCenterLeft.setOnClickListener {
            prefs.settingsButtonCorner = 6
            updatePositionSelection(6)
            updateSettingsButtonPosition(6)
        }

        positionCenterRight.setOnClickListener {
            prefs.settingsButtonCorner = 7
            updatePositionSelection(7)
            updateSettingsButtonPosition(7)
        }

        resetSettingsBtn.setOnClickListener {
            prefs.settingsButtonCorner = 0
            updatePositionSelection(0)
            updateSettingsButtonPosition(0)
        }

        disconnectButton.setOnClickListener {
            dialog.dismiss()
            disconnect()
        }

        closeButton.setOnClickListener {
            dialog.dismiss()
        }

        activeSettingsDialog = dialog
        showImmersiveDialog(dialog)
        resizeSettingsDialog(dialog)
    }

    /** Refit the live settings dialog after an orientation or inset change. */
    private fun resizeSettingsDialog(dialog: Dialog) {
        dialog.window?.let { win ->
            // The activity and dialog are both immersive full-screen windows,
            // so the activity's stable insets share this display coordinate space.
            val density = resources.displayMetrics.density
            val margin = (SETTINGS_CHROME_MARGIN_DP * density).toInt()
            val availableWidth =
                (resources.displayMetrics.widthPixels -
                    safeAreaInsets.left - safeAreaInsets.right - margin * 2).coerceAtLeast(1)
            val availableHeight =
                (resources.displayMetrics.heightPixels -
                    safeAreaInsets.top - safeAreaInsets.bottom - margin * 2).coerceAtLeast(1)
            val dialogWidth = minOf((SETTINGS_DIALOG_MAX_WIDTH_DP * density).toInt(), availableWidth)
            val dialogHeight =
                minOf(
                    (resources.displayMetrics.heightPixels * SETTINGS_DIALOG_MAX_HEIGHT_RATIO).toInt(),
                    availableHeight,
                )
            win.setLayout(dialogWidth, dialogHeight)
            dialog.findViewById<View>(R.id.settingsContent)?.let(
                SettingsDialogLayoutApplier::applyAfterNextLayout,
            )
        }
    }

    private fun setupSettingsButton() {
        // Simple click to show settings dialog
        // Position can be changed via corner buttons in settings
        binding.settingsButton.setOnClickListener {
            showSettingsDialog()
        }
    }

    private fun restoreSettingsButtonPosition() {
        updateSettingsButtonPosition(prefs.settingsButtonCorner)
    }

    /**
     * Use ConstraintSet to position settings button - most reliable method
     * Works correctly with orientation changes
     * Supports 8 positions: 4 corners + 4 edges
     */
    private fun updateSettingsButtonPosition(position: Int) {
        val constraintLayout = binding.root
        val constraintSet = ConstraintSet()
        constraintSet.clone(constraintLayout)

        val buttonId = binding.settingsButton.id
        // Fold the safe-area insets into each edge margin so the floating
        // settings button clears the notch/gesture bar on whichever edge it is
        // anchored to, then re-clamp keeps it there across rotations.
        val base = (SETTINGS_CHROME_MARGIN_DP * resources.displayMetrics.density).toInt()
        val topM = base + safeAreaInsets.top
        val bottomM = base + safeAreaInsets.bottom
        val startM = base + safeAreaInsets.left
        val endM = base + safeAreaInsets.right

        // Clear all constraints first
        constraintSet.clear(buttonId, ConstraintSet.TOP)
        constraintSet.clear(buttonId, ConstraintSet.BOTTOM)
        constraintSet.clear(buttonId, ConstraintSet.START)
        constraintSet.clear(buttonId, ConstraintSet.END)

        when (position) {
            0 -> { // Bottom Right (default)
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.BOTTOM,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.BOTTOM,
                    bottomM,
                )
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, endM)
            }

            1 -> { // Bottom Left
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.BOTTOM,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.BOTTOM,
                    bottomM,
                )
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.START,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.START,
                    startM,
                )
            }

            2 -> { // Top Right
                constraintSet.connect(buttonId, ConstraintSet.TOP, ConstraintSet.PARENT_ID, ConstraintSet.TOP, topM)
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, endM)
            }

            3 -> { // Top Left
                constraintSet.connect(buttonId, ConstraintSet.TOP, ConstraintSet.PARENT_ID, ConstraintSet.TOP, topM)
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.START,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.START,
                    startM,
                )
            }

            4 -> { // Top Center
                constraintSet.connect(buttonId, ConstraintSet.TOP, ConstraintSet.PARENT_ID, ConstraintSet.TOP, topM)
                constraintSet.connect(buttonId, ConstraintSet.START, ConstraintSet.PARENT_ID, ConstraintSet.START, 0)
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, 0)
            }

            5 -> { // Bottom Center
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.BOTTOM,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.BOTTOM,
                    bottomM,
                )
                constraintSet.connect(buttonId, ConstraintSet.START, ConstraintSet.PARENT_ID, ConstraintSet.START, 0)
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, 0)
            }

            6 -> { // Center Left
                constraintSet.connect(buttonId, ConstraintSet.TOP, ConstraintSet.PARENT_ID, ConstraintSet.TOP, 0)
                constraintSet.connect(buttonId, ConstraintSet.BOTTOM, ConstraintSet.PARENT_ID, ConstraintSet.BOTTOM, 0)
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.START,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.START,
                    startM,
                )
            }

            7 -> { // Center Right
                constraintSet.connect(buttonId, ConstraintSet.TOP, ConstraintSet.PARENT_ID, ConstraintSet.TOP, 0)
                constraintSet.connect(buttonId, ConstraintSet.BOTTOM, ConstraintSet.PARENT_ID, ConstraintSet.BOTTOM, 0)
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, endM)
            }

            else -> { // Default to bottom right
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.BOTTOM,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.BOTTOM,
                    bottomM,
                )
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, endM)
            }
        }

        // Reset any absolute positioning that might have been set
        binding.settingsButton.translationX = 0f
        binding.settingsButton.translationY = 0f

        constraintSet.applyTo(constraintLayout)
    }

    /**
     * Display config from a new Mac always arrives AFTER codecSelected, so a
     * missing negotiation at this point proves the Mac app predates H.264
     * support — surface that instead of a silent black screen.
     */
    private fun warnIfAvcOnlyWithoutNegotiation() {
        if (CodecCapabilities.shouldAdvertiseAvcOnly && streamClient?.codecNegotiated != true) {
            mainDiag("AVC-only device but Mac did not negotiate codec — Mac app too old")
            runOnUiThread {
                updateStatus("This device has no HEVC decoder. Update the Vibe Screen Mac app to enable H.264 support.")
            }
        }
    }

    private fun activateSession(client: StreamClient): Long {
        cancelClipboardRequestTimeout()
        mainSessionDisplayLifecycle?.invalidate()
        mainSessionDisplayLifecycle = null
        streamControllerSessionState.resetForNewSession()
        val generation = sessionState.activate(client)
        streamClient = client
        activeSessionGeneration = generation
        clipboardApprovalState.activate(client, generation)
        return generation
    }

    private fun isCurrentSession(
        client: StreamClient,
        generation: Long,
    ): Boolean = sessionState.accepts(client, generation)

    private fun currentSessionBinding(): ClientSessionBinding {
        val client = streamClient ?: return ClientSessionBinding.LEGACY_TOUCH_ONLY
        return sessionState.binding(client, activeSessionGeneration)
            ?: ClientSessionBinding.LEGACY_TOUCH_ONLY
    }

    /** Protocol-v1 integration point; capabilities and their sender install atomically. */
    private fun applyNegotiatedSession(
        client: StreamClient,
        generation: Long,
        binding: ClientSessionBinding,
    ): Boolean = sessionState.updateNegotiatedSession(client, generation, binding)

    private fun initializeDecoder(
        holder: SurfaceHolder,
        expectedConfigEpoch: Long = encodedVideoConfigurationState.snapshot()?.configEpoch ?: 0L,
        isConfigurationCurrent: () -> Boolean = { true },
        tryPublishConfigurationCommit: ((() -> Boolean) -> Boolean) = { publish -> publish() },
        configurationCompletion: ((MainSessionDecoderConfigurationResult) -> Unit)? = null,
    ) {
        val completionClaimed = AtomicBoolean()
        fun completeConfiguration(result: MainSessionDecoderConfigurationResult) {
            if (configurationCompletion != null && completionClaimed.compareAndSet(false, true)) {
                configurationCompletion(result)
            }
        }
        fun retryWhenSurfaceReady() {
            completeConfiguration(MainSessionDecoderConfigurationResult.RetryWhenSurfaceReady)
        }
        fun failConfiguration(reason: String) {
            completeConfiguration(MainSessionDecoderConfigurationResult.Failed(reason))
        }

        val ownerClient = streamClient
        if (ownerClient == null) {
            failConfiguration("stale_session")
            return
        }
        val ownerGeneration = activeSessionGeneration
        if (!isCurrentSession(ownerClient, ownerGeneration)) {
            failConfiguration("stale_session")
            return
        }
        val videoConfiguration = encodedVideoConfigurationState.snapshot()
        mainDiag(
            "initializeDecoder called, surface=${holder.surface}, " +
                "valid=${holder.surface.isValid}, " +
                "encoded=${videoConfiguration?.width ?: 0}x${videoConfiguration?.height ?: 0}",
        )
        if (videoConfiguration == null || videoConfiguration.configEpoch != expectedConfigEpoch) {
            mainDiag("initializeDecoder skipped — no video configuration yet")
            failConfiguration("stale_video_configuration")
            return
        }
        val surface = holder.surface
        val expectedSurfaceGeneration = surfaceGeneration.get()
        val expectedConfigurationGeneration = decoderConfigurationGeneration.incrementAndGet()
        val width = videoConfiguration.width
        val height = videoConfiguration.height
        val scaleMode = prefs.videoScaleMode
        val displayObj =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                display
            } else {
                @Suppress("DEPRECATION")
                windowManager.defaultDisplay
            }
        val mime =
            if (ownerClient.streamCodecIsHevc) MediaFormat.MIMETYPE_VIDEO_HEVC else MediaFormat.MIMETYPE_VIDEO_AVC
        DECODER_LIFECYCLE_EXECUTOR.execute {
            if (videoDecoder != null ||
                !surface.isValid ||
                surfaceGeneration.get() != expectedSurfaceGeneration ||
                decoderConfigurationGeneration.get() != expectedConfigurationGeneration ||
                !encodedVideoConfigurationState.isCurrent(videoConfiguration) ||
                !isCurrentSession(ownerClient, ownerGeneration)
            ) {
                if (isCurrentSession(ownerClient, ownerGeneration) &&
                    encodedVideoConfigurationState.isCurrent(videoConfiguration)
                ) {
                    retryWhenSurfaceReady()
                } else {
                    failConfiguration("stale_decoder_configuration")
                }
                return@execute
            }
            val decoder =
                try {
                    createConfiguredDecoder(
                        holder = holder,
                        surface = surface,
                        displayObj = displayObj,
                        width = width,
                        height = height,
                        mime = mime,
                        scaleMode = scaleMode,
                        ownerClient = ownerClient,
                        ownerGeneration = ownerGeneration,
                        expectedConfigEpoch = expectedConfigEpoch,
                        expectedConfigurationGeneration = expectedConfigurationGeneration,
                        expectedSurfaceGeneration = expectedSurfaceGeneration,
                    )
                } catch (e: Exception) {
                    runOnUiThread {
                        if (surface.isValid &&
                            surfaceGeneration.get() == expectedSurfaceGeneration &&
                            decoderConfigurationGeneration.get() == expectedConfigurationGeneration &&
                            encodedVideoConfigurationState.isCurrent(videoConfiguration) &&
                            isConfigurationCurrent() &&
                            isCurrentSession(ownerClient, ownerGeneration)
                        ) {
                            if (e is DecoderInitializationException) {
                                CodecFallbackCommitGate.recordCurrentStructuralHevcFailure(
                                    codec = mime.toStreamCodec(),
                                    failure = e.failure,
                                    isCurrentConfiguration = {
                                        surface.isValid &&
                                            surfaceGeneration.get() == expectedSurfaceGeneration &&
                                            decoderConfigurationGeneration.get() == expectedConfigurationGeneration &&
                                            encodedVideoConfigurationState.isCurrent(videoConfiguration) &&
                                            isConfigurationCurrent() &&
                                            isCurrentSession(ownerClient, ownerGeneration)
                                    },
                                )
                            }
                            reportDecoderInitializationFailure(
                                error = e,
                                ownerClient = ownerClient,
                                ownerGeneration = ownerGeneration,
                                failSession = configurationCompletion == null,
                            )
                            failConfiguration(e.message ?: "decoder_configuration_failure")
                        } else if (isCurrentSession(ownerClient, ownerGeneration) &&
                            encodedVideoConfigurationState.isCurrent(videoConfiguration)
                        ) {
                            retryWhenSurfaceReady()
                        } else {
                            failConfiguration("stale_decoder_configuration")
                        }
                    }
                    return@execute
                }
            runOnUiThread {
                if (!surface.isValid ||
                    surfaceGeneration.get() != expectedSurfaceGeneration ||
                    decoderConfigurationGeneration.get() != expectedConfigurationGeneration ||
                    !encodedVideoConfigurationState.isCurrent(videoConfiguration) ||
                    !isConfigurationCurrent() ||
                    !isCurrentSession(ownerClient, ownerGeneration) ||
                    videoDecoder != null
                ) {
                    DECODER_LIFECYCLE_EXECUTOR.execute { decoder.release() }
                    if (isCurrentSession(ownerClient, ownerGeneration) &&
                        encodedVideoConfigurationState.isCurrent(videoConfiguration)
                    ) {
                        retryWhenSurfaceReady()
                    } else {
                        failConfiguration("stale_decoder_configuration")
                    }
                    return@runOnUiThread
                }
                try {
                    decoder.updateScaleMode(prefs.videoScaleMode)
                } catch (failure: RuntimeException) {
                    DECODER_LIFECYCLE_EXECUTOR.execute { decoder.release() }
                    failConfiguration(failure.message ?: "decoder_configuration_failure")
                    return@runOnUiThread
                }
                when (
                    val startupResult =
                        decoder.commitStartup {
                            tryPublishConfigurationCommit {
                                if (!videoDecoderRef.compareAndSet(null, decoder)) {
                                    false
                                } else {
                                    activeDecoderConfigEpoch = expectedConfigEpoch
                                    true
                                }
                            }
                        }
                ) {
                    DecoderStartupCommitResult.Committed -> Unit
                    DecoderStartupCommitResult.NotCommitted -> {
                        DECODER_LIFECYCLE_EXECUTOR.execute { decoder.release() }
                        failConfiguration("stale_decoder_configuration")
                        return@runOnUiThread
                    }
                    is DecoderStartupCommitResult.Failed -> {
                        CodecFallbackCommitGate.recordCurrentStructuralHevcFailure(
                            codec = mime.toStreamCodec(),
                            failure = startupResult.failure,
                            isCurrentConfiguration = {
                                surface.isValid &&
                                    surfaceGeneration.get() == expectedSurfaceGeneration &&
                                    decoderConfigurationGeneration.get() == expectedConfigurationGeneration &&
                                    encodedVideoConfigurationState.isCurrent(videoConfiguration) &&
                                    isConfigurationCurrent() &&
                                    isCurrentSession(ownerClient, ownerGeneration)
                            },
                        )
                        reportDecoderInitializationFailure(
                            error = DecoderInitializationException(startupResult.failure),
                            ownerClient = ownerClient,
                            ownerGeneration = ownerGeneration,
                            failSession = configurationCompletion == null,
                        )
                        DECODER_LIFECYCLE_EXECUTOR.execute { decoder.release() }
                        failConfiguration(startupResult.reason)
                        return@runOnUiThread
                    }
                }
                if (configurationCompletion != null) {
                    completeConfiguration(MainSessionDecoderConfigurationResult.Configured)
                    mainDiag("Decoder configuration committed ${width}x$height epoch=$expectedConfigEpoch")
                    return@runOnUiThread
                }
                try {
                    ownerClient.requestKeyframe(force = true, reason = "decoder initialized")
                    mainDiag("Decoder initialized OK ${width}x$height mime=$mime, videoDecoder=$decoder")
                    log("✅ Decoder initialized ${width}x$height $mime (${displayObj?.refreshRate ?: 60f}Hz)")
                } catch (e: Exception) {
                    if (surface.isValid &&
                        surfaceGeneration.get() == expectedSurfaceGeneration &&
                        decoderConfigurationGeneration.get() == expectedConfigurationGeneration &&
                        isCurrentSession(ownerClient, ownerGeneration) &&
                        videoDecoder === decoder
                    ) {
                        reportDecoderInitializationFailure(e, ownerClient, ownerGeneration)
                    }
                }
            }
        }
    }

    private fun createConfiguredDecoder(
        holder: SurfaceHolder,
        surface: android.view.Surface,
        displayObj: android.view.Display?,
        width: Int,
        height: Int,
        mime: String,
        scaleMode: VideoScaleMode,
        ownerClient: StreamClient,
        ownerGeneration: Long,
        expectedConfigEpoch: Long,
        expectedConfigurationGeneration: Long,
        expectedSurfaceGeneration: Long,
    ): VideoDecoder {
        fun isCurrentDecoderCallback(
            identity: VideoDecoder,
            generation: Long,
        ): Boolean =
            isCurrentSession(ownerClient, generation) &&
                videoDecoder === identity &&
                activeDecoderConfigEpoch == expectedConfigEpoch &&
                decoderConfigurationGeneration.get() == expectedConfigurationGeneration &&
                encodedVideoConfigurationState.snapshot()?.configEpoch == expectedConfigEpoch &&
                currentSurfaceHolder === holder &&
                surface.isValid &&
                surfaceGeneration.get() == expectedSurfaceGeneration

        val decoder =
            VideoDecoder(
                surface = surface,
                display = displayObj,
                initialWidth = width,
                initialHeight = height,
                mime = mime,
                initialScaleMode = scaleMode,
                onFrameDecoded = { _, buffer -> ownerClient.releaseBuffer(buffer) },
                onKeyframeRequired = { identity, force, reason ->
                    val callbackBinding =
                        ActiveDecoderCallbackBinding(identity, ownerGeneration, ::isCurrentDecoderCallback)
                    runOnUiThread {
                        callbackBinding.runIfActive {
                            ownerClient.requestKeyframe(force = force, reason = reason)
                        }
                    }
                },
                onCodecFailure = { identity, failure ->
                    val callbackBinding =
                        ActiveDecoderCallbackBinding(identity, ownerGeneration, ::isCurrentDecoderCallback)
                    runOnUiThread {
                        callbackBinding.runIfActive {
                            CodecFallbackCommitGate.recordCurrentStructuralHevcFailure(
                                codec = mime.toStreamCodec(),
                                failure = failure,
                                isCurrentConfiguration = callbackBinding::isActive,
                            )
                            ownerClient.failCurrentSession(failure.reason)
                        }
                    }
                },
            )
        try {
            decoder.updateScaleMode(scaleMode)
            return decoder
        } catch (e: Exception) {
            decoder.release()
            throw e
        }
    }

    private fun reportDecoderInitializationFailure(
        error: Exception,
        ownerClient: StreamClient,
        ownerGeneration: Long,
        failSession: Boolean = true,
    ) {
        mainDiag("Decoder init FAILED: ${error.message}")
        log("❌ Failed to initialize decoder: ${error.message}")
        if (isCurrentSession(ownerClient, ownerGeneration)) {
            updateStatus("Video decoder failed: ${error.message}")
            if (failSession) {
                ownerClient.failCurrentSession("codec_configuration_failure")
            }
        }
    }

    private fun applyVideoScaleMode(mode: VideoScaleMode) {
        prefs.videoScaleMode = mode
        DECODER_LIFECYCLE_EXECUTOR.execute {
            videoDecoder?.updateScaleMode(mode)
        }
    }

    private fun releaseVideoDecoderAsync() {
        decoderConfigurationGeneration.incrementAndGet()
        activeDecoderConfigEpoch = 0L
        val decoder = videoDecoderRef.getAndSet(null) ?: return
        DECODER_LIFECYCLE_EXECUTOR.execute { decoder.release() }
    }

    /**
     * Wire up all StreamClient callbacks. Used by both USB connect() and wireless connectWireless().
     */
    private fun createSessionAutomaticRetryCoordinator(
        callbackClient: StreamClient,
        callbackGeneration: Long,
        postAutomaticRetry: () -> Unit,
    ): SessionAutomaticRetryCoordinator {
        val cleanupAdapter =
            SessionAutomaticRetryCleanupAdapter(
                isCurrentGeneration = { isCurrentSession(callbackClient, callbackGeneration) },
                disableAutomaticUsbConnect = { automaticUsbConnect = false },
                cancelWirelessReconnect = ::cancelWirelessReconnect,
                removeAutomaticUsbRunnable = { autoConnectHandler.removeCallbacks(autoConnectRunnable) },
            )
        return SessionAutomaticRetryCoordinator(
            postAutomaticRetry = postAutomaticRetry,
            cancelPendingAutomaticRetry = { runOnUiThread(cleanupAdapter::cleanup) },
            handleServerShutdown = {
                runOnUiThread {
                    if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                    log("📴 Server initiated shutdown — closing app")
                    finishAffinity()
                }
            },
        )
    }

    private fun setupStreamClientCallbacks(
        callbackClient: StreamClient,
        callbackGeneration: Long,
        retryCoordinator: SessionAutomaticRetryCoordinator,
        guidanceContext: ConnectionGuidanceContext,
    ) {
        val displayLifecycle =
            MainSessionDisplayLifecycle(
                isCurrentSession = { isCurrentSession(callbackClient, callbackGeneration) },
                postToUi = { action -> runOnUiThread { action() } },
                updateVideoConfiguration = { configuration ->
                    mainDiag(
                        "onVideoConfiguration: ${configuration.encodedWidth}x${configuration.encodedHeight} " +
                            "@ ${configuration.rotation}° epoch=${configuration.configEpoch}",
                    )
                    warnIfAvcOnlyWithoutNegotiation()
                    encodedVideoConfigurationState.publish(
                        width = configuration.encodedWidth,
                        height = configuration.encodedHeight,
                        configEpoch = configuration.configEpoch,
                    )
                },
                releaseDecoder = ::releaseVideoDecoderAsync,
                configureDecoder = {
                        configuration,
                        isConfigurationCurrent,
                        tryPublishConfigurationCommit,
                        completion,
                    ->
                    val holder = currentSurfaceHolder
                    if (holder != null && holder.surface.isValid) {
                        val encodedConfiguration = encodedVideoConfigurationState.snapshot()
                        mainDiag(
                            "Video config arrived, initializing decoder " +
                                "${encodedConfiguration?.width ?: 0}x${encodedConfiguration?.height ?: 0}",
                        )
                        initializeDecoder(
                            holder = holder,
                            expectedConfigEpoch = configuration.configEpoch,
                            isConfigurationCurrent = isConfigurationCurrent,
                            tryPublishConfigurationCommit = tryPublishConfigurationCommit,
                            configurationCompletion = completion,
                        )
                    } else {
                        mainDiag("Video config is waiting for a valid surface")
                        completion(MainSessionDecoderConfigurationResult.RetryWhenSurfaceReady)
                    }
                },
                updateDisplayGeometry = { geometry ->
                    mainDiag(
                        "onDisplayGeometry: ${geometry.logicalWidth}x${geometry.logicalHeight} " +
                            "@ ${geometry.rotation}°",
                    )
                    displayWidth = geometry.logicalWidth
                    displayHeight = geometry.logicalHeight
                    displayRotation = geometry.rotation
                    binding.resolutionText.text =
                        getString(R.string.resolution_format, geometry.logicalWidth, geometry.logicalHeight)
                    binding.connectButton.isEnabled = false
                    binding.disconnectButton.isEnabled = true
                    binding.statusIndicator.setBackgroundResource(R.drawable.status_indicator_green)
                    showConnectedStreamUi()
                    applyRotation(geometry.rotation)
                    log("Display: ${geometry.logicalWidth}x${geometry.logicalHeight} @ ${geometry.rotation}°")
                },
                scheduleTimeout = { task, delayMs -> inputHandler.postDelayed(task, delayMs) },
                cancelTimeout = { task -> inputHandler.removeCallbacks(task) },
            )
        mainSessionDisplayLifecycle?.invalidate()
        mainSessionDisplayLifecycle = displayLifecycle

        callbackClient.onFrameReceived = frame@{
                frameData,
                frameSize,
                timestamp,
                isKeyframe,
                sessionEpoch,
                configEpoch,
            ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) {
                callbackClient.releaseBuffer(frameData)
                return@frame
            }
            if (configEpoch != activeDecoderConfigEpoch) {
                mainDiag(
                    "FRAME DROPPED: config epoch $configEpoch does not match decoder epoch " +
                        activeDecoderConfigEpoch,
                )
                callbackClient.releaseBuffer(frameData)
                return@frame
            }
            val dec = videoDecoder
            if (dec != null) {
                dec.decode(frameData, frameSize, timestamp, isKeyframe, sessionEpoch)
            } else {
                mainDiag("FRAME DROPPED: videoDecoder is null!")
                callbackClient.releaseBuffer(frameData)
            }
        }

        callbackClient.onLatencyMeasured = latency@{ rttMs ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@latency
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                binding.latencyText.text = String.format(Locale.US, "%.1f ms", rttMs)
            }
        }

        callbackClient.onReconnectSuggested = reconnect@{ delayMs ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@reconnect
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                pendingWirelessReconnectDelayMs = delayMs
                if (wirelessAutoReconnectEnabled && prefs.connectionMode == ConnectionMode.WIRELESS) {
                    scheduleWirelessReconnect(delayMs)
                }
            }
        }

        callbackClient.onWriteFailure = writeFailure@{ reason ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@writeFailure
            mainDiag("session write failed: $reason")
        }

        callbackClient.onSessionEnded = sessionEnded@{ failure ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@sessionEnded
            val showTerminalGuidance = retryCoordinator.onSessionEnded(failure)
            mainDiag(
                "session ended kind=${failure.kind} retryable=${failure.retryable}",
            )
            if (showTerminalGuidance) {
                val guidance =
                    ConnectionGuidanceFactory.from(
                        failure,
                        guidanceContext.withPort(callbackClient.actualPort),
                    )
                runOnUiThread {
                    if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                    pendingTerminalGuidance = guidance
                }
            }
        }

        callbackClient.onConnectionStatus = connectionStatus@{ connected ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@connectionStatus
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                isConnected = connected
                applyStreamingWindowState(connected = connected, foreground = isInForeground)
                if (connected) {
                    nativeInputSessionState.admit(callbackClient, callbackGeneration)
                    if (prefs.connectionMode == ConnectionMode.USB) automaticUsbConnect = true
                    replaySavedVideoPreferencesIfAvailable(callbackClient, callbackGeneration)
                    hasConnectedThisRun = true
                    isReconnecting = false
                    unsupportedKeyboardNoticeShown = false
                    pendingWirelessReconnectDelayMs = null
                    initialWirelessReconnectBackoff.reset()
                    wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)
                    startPingTimer()
                    stopChecklistUpdates()
                    enableFullscreenMode()
                    binding.inputViewport.requestFocus()
                    refreshClipboardControl()
                    refreshFileTransferControl()
                    // For wireless mode, transition controller to CONNECTED here —
                    // not in MainActivity.connectWireless's coroutine after the
                    // receive loop returns (that runs AFTER disconnect, causing
                    // a stale CONNECTED transition that hides the PAIRED_IDLE UI).
                    if (prefs.connectionMode == ConnectionMode.WIRELESS) {
                        val entry = pairedHostStorage.load()
                        wirelessController.onConnectSuccess(
                            entry?.macName ?: "Mac",
                            entry?.host ?: "—",
                        )
                    }
                } else {
                    nativeInputSessionState.discard(callbackClient, callbackGeneration)
                    applyDisconnectedSessionUi()
                }
            }
        }

        callbackClient.onServerShutdown = serverShutdown@{
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@serverShutdown
            retryCoordinator.onServerShutdown()
        }

        callbackClient.onVideoConfiguration = displayLifecycle::onVideoConfiguration
        callbackClient.onVideoConfigurationApplied = applied@{ configuration ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@applied
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration) ||
                    !AppliedVideoPreferenceProjector.shouldPersist(
                        appliesClientVideoPreferences = configuration.appliesClientVideoPreferences,
                        configEpoch = configuration.configEpoch,
                        lastAppliedConfigEpoch = lastAppliedVideoPreferenceConfigEpoch,
                    )
                ) {
                    return@runOnUiThread
                }
                val projection =
                    AppliedVideoPreferenceProjector.project(
                        bitrateKbps = configuration.bitrateKbps,
                        framesPerSecond = configuration.framesPerSecond,
                    )
                projection.bitrateMbps?.let { prefs.videoBitrateMbps = it }
                projection.framesPerSecond?.let { prefs.videoFrameRate = it }
                if (
                    VideoPreferenceFeedbackPolicy.shouldAnnounceApplied(
                        appliesClientVideoPreferences = configuration.appliesClientVideoPreferences,
                        configEpoch = configuration.configEpoch,
                        lastAnnouncedConfigEpoch = lastAppliedVideoPreferenceConfigEpoch,
                    )
                ) {
                    Toast.makeText(this, R.string.video_preferences_applied, Toast.LENGTH_SHORT).show()
                }
                lastAppliedVideoPreferenceConfigEpoch = configuration.configEpoch
                mainDiag(
                    "Applied authoritative video preferences " +
                        "epoch=${configuration.configEpoch} " +
                        "bitrate=${projection.bitrateMbps ?: "unchanged"}Mbps " +
                        "fps=${projection.framesPerSecond ?: "unchanged"}",
                )
            }
        }
        callbackClient.onDisplayGeometry = displayLifecycle::onDisplayGeometry
        callbackClient.onDisplaysAvailable = displays@{ options, selectedId ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@displays
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                mainDiag(
                    "onDisplaysAvailable: count=${options.size} selected=$selectedId " +
                        "negotiated=${callbackClient.negotiatedCapabilities()} " +
                        "displays=${options.joinToString { "${it.id}:${it.name}:${it.width}x${it.height}:primary=${it.isPrimary}" }}",
                )
                // Promote the session binding to reflect negotiated capabilities so
                // the display capsule and other controls unlock only when agreed.
                val negotiated = callbackClient.negotiatedCapabilities()
                val displaySelection =
                    dev.vibescreen.protocol.v1.Capability.CAPABILITY_MULTI_DISPLAY in negotiated
                val keyboard =
                    dev.vibescreen.protocol.v1.Capability.CAPABILITY_KEYBOARD in negotiated
                val nativePointer =
                    dev.vibescreen.protocol.v1.Capability.CAPABILITY_POINTER in negotiated
                val controller =
                    dev.vibescreen.protocol.v1.Capability.CAPABILITY_CONTROLLER in negotiated
                val hostActions =
                    dev.vibescreen.protocol.v1.Capability.CAPABILITY_HOST_ACTIONS in negotiated
                val clipboard =
                    dev.vibescreen.protocol.v1.Capability.CAPABILITY_CLIPBOARD in negotiated
                val fileTransfer =
                    dev.vibescreen.protocol.v1.Capability.CAPABILITY_FILE_TRANSFER in negotiated
                if (displaySelection || keyboard || nativePointer || controller || hostActions || clipboard || fileTransfer) {
                    val capabilities =
                        ClientSessionCapabilities.LEGACY_TOUCH_ONLY.copy(
                            displaySelection = displaySelection,
                            keyboard = keyboard,
                            nativePointer = nativePointer,
                            controller = controller,
                            hostActions = hostActions,
                            clipboard = clipboard,
                            fileTransfer = fileTransfer,
                        )
                    val sink =
                        if (keyboard || nativePointer || controller) {
                            StreamClientInputSink(callbackClient, callbackGeneration)
                        } else {
                            null
                        }
                    applyNegotiatedSession(
                        callbackClient,
                        callbackGeneration,
                        ClientSessionBinding(capabilities, sink),
                    )
                    // HostActionCatalog may arrive before ListDisplaysResponse.
                    // Re-evaluate the cached catalog after capability promotion so
                    // that arrival order cannot leave the button permanently hidden.
                    populateHostActions(availableHostActions)
                    refreshClipboardControl()
                    refreshFileTransferControl()
                    mainDiag(
                        "session binding promoted: displaySelection=$displaySelection " +
                            "keyboard=$keyboard nativePointer=$nativePointer " +
                            "controller=$controller hostActions=$hostActions " +
                            "clipboard=$clipboard fileTransfer=$fileTransfer",
                    )
                }
                populateDisplayCapsule(options, selectedId)
            }
        }

        callbackClient.onHostActionsAvailable = hostActions@{ actions ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@hostActions
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                mainDiag("onHostActionsAvailable: ${actions.joinToString { it.id }}")
                populateHostActions(actions)
            }
        }
        callbackClient.onControllerInputAck = controllerAck@{ connection, accepted, rejectionReason ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@controllerAck
            if (accepted) {
                val resync = streamControllerSessionState.resynchronize() ?: return@controllerAck
                sendStreamControllerDispatch(resync, "controller ack resync")
                return@controllerAck
            }
            if (streamControllerSessionState.rejectConnection(connection.controllerId, connection.controllerEpoch)) {
                mainDiag(
                    "controller connection rejected id=${connection.controllerId} " +
                        "epoch=${connection.controllerEpoch} reason=$rejectionReason",
                )
            }
        }
        callbackClient.onHostActionResult = hostActionResult@{ accepted, rejectionReason ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@hostActionResult
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                mainDiag("onHostActionResult: accepted=$accepted reason=$rejectionReason")
                val message =
                    if (accepted) {
                        getString(R.string.host_action_accepted)
                    } else if (rejectionReason.isNotBlank()) {
                        getString(R.string.host_action_rejected_with_reason, rejectionReason)
                    } else {
                        getString(R.string.host_action_rejected)
                    }
                Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
            }
        }

        callbackClient.onClipboardOffered = clipboardOffer@{ offer ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@clipboardOffer
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                cancelClipboardRequestTimeout()
                val staged =
                    clipboardApprovalState.stageOffer(
                        callbackClient,
                        callbackGeneration,
                        PendingClipboardOffer(
                            changeId = offer.changeId,
                            originDeviceId = offer.originDeviceId,
                            mimeType = offer.mimeType,
                            byteLength = offer.byteLength,
                            sha256 = offer.sha256,
                        ),
                    )
                if (staged) {
                    refreshClipboardControl()
                    binding.controlClipboardButton.announceForAccessibility(
                        getString(R.string.clipboard_pending_from_mac),
                    )
                }
            }
        }
        callbackClient.onClipboardContentReceived = clipboardContent@{ content ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@clipboardContent
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                if (content.pending) {
                    val staged =
                        clipboardApprovalState.stageDirectContent(
                            callbackClient,
                            callbackGeneration,
                            content,
                        )
                    if (staged) {
                        cancelClipboardRequestTimeout()
                        refreshClipboardControl()
                        binding.controlClipboardButton.announceForAccessibility(
                            getString(R.string.clipboard_pending_confirmation),
                        )
                    }
                    return@runOnUiThread
                }
                cancelClipboardRequestTimeout()
                val approved =
                    clipboardApprovalState.consumeSolicitedContent(
                        callbackClient,
                        callbackGeneration,
                        content,
                    )
                if (approved != null) {
                    writeRemoteClipboard(approved)
                    refreshClipboardControl()
                }
            }
        }

        callbackClient.onFileOffer = fileOffer@{ offer ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@fileOffer
            promptIncomingFileOffer(callbackClient, callbackGeneration, offer)
        }
        callbackClient.onIncomingFileCompleted = incomingFile@{ completed ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@incomingFile
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                onIncomingFileCompleted(completed)
            }
        }
        callbackClient.onFileTransferResult = fileResult@{ accepted, reason ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@fileResult
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                discardPendingOutgoingFileTransfer()
                val message =
                    if (accepted) {
                        getString(R.string.file_transfer_completed)
                    } else if (reason.isNotBlank()) {
                        getString(R.string.file_transfer_failed_with_reason, reason)
                    } else {
                        getString(R.string.file_transfer_failed)
                    }
                Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
            }
        }

        callbackClient.onStats = stats@{ fps, mbps ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@stats
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                binding.fpsText.text = String.format(Locale.US, "%.1f", fps)
                binding.bitrateText.text = String.format(Locale.US, "%.1f Mbps", mbps)
            }
        }
    }

    private fun replaySavedVideoPreferencesIfAvailable(
        callbackClient: StreamClient,
        callbackGeneration: Long,
    ) {
        if (!isCurrentSession(callbackClient, callbackGeneration)) return
        if (
            dev.vibescreen.protocol.v1.Capability.CAPABILITY_CLIENT_VIDEO_CONTROL !in
            callbackClient.negotiatedCapabilities()
        ) {
            return
        }
        SavedVideoPreferenceReplayer.replayIfAvailable(
            clientVideoControlAvailable = true,
            quality = prefs.videoQuality,
            bitrateMbps = prefs.videoBitrateMbps,
            framesPerSecond = prefs.videoFrameRate,
        ) { replay ->
            callbackClient.setVideoPreferences(
                bitrateKbps = replay.bitrateKbps,
                framesPerSecond = replay.framesPerSecond,
                qualityPreset = replay.qualityPreset,
                resetQualityToAuto = replay.resetQualityToAuto,
            )
            mainDiag(
                "Replayed saved video preferences " +
                    "bitrate=${replay.bitrateKbps}kbps fps=${replay.framesPerSecond} " +
                    "quality=${replay.qualityPreset.name} resetAuto=${replay.resetQualityToAuto}",
            )
        }
    }

    private fun connectInternet() {
        if (!allowInternetCredentialMutation()) return
        if (internetSession != null || connectionAttemptInProgress) return
        val lease =
            try {
                check(retryPendingInternetRevocationCleanup().isEmpty()) {
                    "Internet revocation cleanup is still pending"
                }
                internetProfileStore.loadLease(prefs.internetForceRelay)
                    ?: throw IllegalStateException(getString(R.string.internet_profile_missing))
            } catch (failure: Throwable) {
                return showInternetFailure(failure)
            }
        if (lease.authoritativeSessionEpoch <= requiredFreshInternetEpoch) {
            return showInternetFailure(
                IllegalStateException("Import a lease newer than epoch $requiredFreshInternetEpoch"),
            )
        }
        connectionAttemptInProgress = true
        internetRoute = null
        internetSessionEpoch = lease.authoritativeSessionEpoch
        resetInternetInputStateForNewSession()
        val generation = ++internetGeneration
        internetVideoDecoderLifecycle?.invalidate()
        internetVideoDecoderLifecycle = null
        val monitor = AndroidNetworkMonitor(applicationContext)
        val sessionReference = AtomicReference<InternetProductSession?>()
        val activeLogged = AtomicBoolean(false)
        fun isCurrentInternetSession(): Boolean =
            generation == internetGeneration && internetSession === sessionReference.get()
        val videoDecoderLifecycle =
            InternetVideoDecoderLifecycle(
                isCurrentSession = ::isCurrentInternetSession,
                postToUi = { action -> runOnUiThread { action() } },
                configureDecoder = { configuration, isConfigurationCurrent, commitEffect, completion ->
                    val decision =
                        configureInternetDecoder(
                            configuration = configuration,
                            generation = generation,
                            sessionReference = sessionReference,
                            isConfigurationCurrent = isConfigurationCurrent,
                            commitConfiguration = commitEffect,
                        )
                    completion(
                        if (!decision.accepted && decision.rejectionReason == "surface_unavailable") {
                            InternetDecoderConfigurationResult.RetryWhenSurfaceReady
                        } else {
                            InternetDecoderConfigurationResult.Completed(decision)
                        },
                    )
                },
                scheduleTimeout = { task, delayMs -> inputHandler.postDelayed(task, delayMs) },
                cancelTimeout = inputHandler::removeCallbacks,
            )
        internetVideoDecoderLifecycle = videoDecoderLifecycle
        fun logActiveIfReady() {
            val current = sessionReference.get() ?: return
            val route = internetRoute ?: return
            if (current.state == InternetProductSessionState.ACTIVE && activeLogged.compareAndSet(false, true)) {
                android.util.Log.i(
                    INTERNET_LOG_TAG,
                    "internet_stream_active session_epoch=${lease.authoritativeSessionEpoch} route=${route.name.lowercase()}",
                )
            }
        }
        val codec =
            ProtobufProtocolV1ProductCodec(
                localDeviceId = internetDeviceId,
                deviceName = (Build.MODEL ?: "Android").take(MAX_DEVICE_NAME_LENGTH),
                supportedCodecs =
                    CodecCapabilities.advertisedStreamCodecs
                        .mapNotNullTo(linkedSetOf(), StreamCodec::toProductVideoCodecOrNull),
                advertiseController = true,
            )
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onStateChanged(state: InternetProductSessionState) {
                    if (!isCurrentInternetSession()) return
                    logActiveIfReady()
                    runOnUiThread {
                        if (!isCurrentInternetSession()) return@runOnUiThread
                        updateInternetState(state)
                    }
                }

                override fun onRouteSelected(route: PeerRoute) {
                    if (!isCurrentInternetSession()) return
                    internetRoute = route
                    logActiveIfReady()
                    runOnUiThread {
                        if (!isCurrentInternetSession()) return@runOnUiThread
                        updateInternetState(sessionReference.get()?.state ?: InternetProductSessionState.CONNECTING)
                    }
                }

                override fun onVideoConfiguration(
                    configuration: ProductVideoConfiguration,
                    effect: ProductVideoConfigurationEffect,
                    completion: (ProductVideoDecision) -> Unit,
                ) {
                    videoDecoderLifecycle.onVideoConfiguration(configuration, effect, completion)
                }

                override fun onVideoConfigurationApplied(configuration: ProductVideoConfiguration) {
                    if (!isCurrentInternetSession()) return
                    runOnUiThread {
                        if (!isCurrentInternetSession()) return@runOnUiThread
                        internetControllerSessionState.resynchronize()?.let { dispatch ->
                            sendInternetControllerDispatch(dispatch, "internet controller video configuration")
                        }
                    }
                }

                override fun onVideoFrame(frame: ProductVideoFrame) {
                    if (!isCurrentInternetSession() || frame.sessionEpoch != internetSessionEpoch) return
                    videoDecoder?.decode(
                        frame.payload,
                        frame.payload.size,
                        System.nanoTime(),
                        frame.keyframe,
                        frame.sessionEpoch,
                    )
                }

                override fun onInputAck(
                    inputId: Long,
                    controllerId: String?,
                    controllerEpoch: Long?,
                    accepted: Boolean,
                    rejectionReason: String,
                ) {
                    if (!isCurrentInternetSession()) return
                    val rejectedConnection =
                        ControllerInputAckPolicy.rejectedConnection(controllerId, controllerEpoch, accepted) ?: return
                    if (internetControllerSessionState.rejectConnection(rejectedConnection.controllerId, rejectedConnection.controllerEpoch)) {
                        mainDiag(
                            "internet controller input rejected input_id=$inputId " +
                                "controller=${rejectedConnection.controllerId} " +
                                "epoch=${rejectedConnection.controllerEpoch} reason=$rejectionReason",
                        )
                    }
                }

                override fun onFreshSessionRequired(reason: String) {
                    if (!isCurrentInternetSession()) return
                    android.util.Log.i(INTERNET_LOG_TAG, "internet_fresh_session_required session_epoch=${lease.authoritativeSessionEpoch}")
                    runOnUiThread {
                        if (!isCurrentInternetSession()) return@runOnUiThread
                        requiredFreshInternetEpoch = internetSessionEpoch
                        disconnectInternet(showIdle = false)
                        LiveRegionTextApplier.show(
                            binding.internetErrorText,
                            getString(R.string.internet_fresh_session_required, reason),
                        )
                        showDisconnectedStreamUi()
                    }
                }

                override fun onRevoked(reason: String) {
                    if (!isCurrentInternetSession()) return
                    android.util.Log.i(INTERNET_LOG_TAG, "internet_session_revoked session_epoch=${lease.authoritativeSessionEpoch}")
                    runOnUiThread {
                        if (!isCurrentInternetSession()) return@runOnUiThread
                        revokeInternetPairing(reason, tombstonePersisted = true)
                    }
                }

                override fun onFailure(error: Throwable) {
                    if (!isCurrentInternetSession()) return
                    android.util.Log.e(INTERNET_LOG_TAG, "internet_session_error type=${error.javaClass.simpleName}")
                    runOnUiThread {
                        if (!isCurrentInternetSession()) return@runOnUiThread
                        showInternetFailure(error)
                    }
                }
            }
        try {
            val created =
                InternetProductSession.create(
                    internetStoredSessionFactory,
                    internetDeviceId,
                    lease,
                    monitor,
                    dev.telemachus.display.internet.MonotonicClock { android.os.SystemClock.elapsedRealtime() },
                    codec,
                    callbacks,
                    object : InternetProductRevocationStore {
                        override fun persistPendingAuthenticatedRevocation(pairingIdentifier: String, reason: String) {
                            internetProfileStore.persistPendingAuthenticatedRevocation(pairingIdentifier, reason)
                        }

                        override fun persistAuthenticatedRevocation(pairingIdentifier: String, reason: String) {
                            internetProfileStore.markAuthenticatedRevoked(pairingIdentifier, reason)
                        }

                        override fun isAdmissionBlocked(pairingIdentifier: String): Boolean =
                            internetProfileStore.isRevoked(pairingIdentifier)
                    },
                    internetRevocationCoordinator,
                )
            sessionReference.set(created)
            internetNetworkMonitor = monitor
            internetSession = created
            binding.internetConnectButton.isEnabled = false
            binding.internetDisconnectButton.visibility = View.VISIBLE
            LiveRegionTextApplier.hide(binding.internetErrorText)
            internetTickJob =
                lifecycleScope.launch(Dispatchers.Default) {
                    while (internetSession === created) {
                        kotlinx.coroutines.delay(INTERNET_TICK_INTERVAL_MS)
                        created.tick()
                    }
                }
            lifecycleScope.launch(Dispatchers.IO) {
                try {
                    created.start()
                } catch (failure: Throwable) {
                    if (generation == internetGeneration) {
                        runOnUiThread {
                            if (isCurrentInternetSession()) showInternetFailure(failure)
                        }
                    }
                } finally {
                    if (generation == internetGeneration) connectionAttemptInProgress = false
                }
            }
        } catch (failure: Throwable) {
            if (generation != internetGeneration) return
            videoDecoderLifecycle.invalidate("session_start_failed")
            if (internetVideoDecoderLifecycle === videoDecoderLifecycle) internetVideoDecoderLifecycle = null
            connectionAttemptInProgress = false
            monitor.close()
            requiredFreshInternetEpoch = maxOf(requiredFreshInternetEpoch, lease.authoritativeSessionEpoch)
            android.util.Log.e(INTERNET_LOG_TAG, "internet_session_error type=${failure.javaClass.simpleName}")
            showInternetFailure(failure)
        }
    }

    private fun configureInternetDecoder(
        configuration: ProductVideoConfiguration,
        generation: Long,
        sessionReference: AtomicReference<InternetProductSession?>,
        isConfigurationCurrent: () -> Boolean = { true },
        commitConfiguration: ((() -> ProductVideoDecision) -> ProductVideoDecision) = { publish -> publish() },
    ): ProductVideoDecision {
        check(Looper.myLooper() == Looper.getMainLooper()) { "Internet decoder must be configured on the main thread" }
        fun isCurrent(): Boolean = generation == internetGeneration && internetSession === sessionReference.get()
        if (!isCurrent()) return ProductVideoDecision.reject("stale_session")
        val mime =
            when (configuration.codec) {
                ProductVideoCodec.H264 -> MediaFormat.MIMETYPE_VIDEO_AVC
                ProductVideoCodec.HEVC -> {
                    if (CodecCapabilities.shouldAdvertiseAvcOnly) {
                        return ProductVideoDecision.reject("hevc_decoder_unavailable")
                    }
                    MediaFormat.MIMETYPE_VIDEO_HEVC
                }
                ProductVideoCodec.AV1 -> return ProductVideoDecision.reject("av1_decoder_unavailable")
            }
        val holder = currentSurfaceHolder
        if (holder == null || !holder.surface.isValid) return ProductVideoDecision.reject("surface_unavailable")
        val surface = holder.surface
        val expectedSurfaceGeneration = surfaceGeneration.get()
        fun isCurrentDecoderCallback(
            identity: VideoDecoder,
            sessionGeneration: Long,
        ): Boolean =
            sessionGeneration == internetGeneration &&
                internetSession === sessionReference.get() &&
                videoDecoder === identity &&
                internetVideoConfiguration?.configEpoch == configuration.configEpoch &&
                currentSurfaceHolder === holder &&
                surface.isValid &&
                surfaceGeneration.get() == expectedSurfaceGeneration

        var candidate: VideoDecoder? = null
        return try {
            val displayObject =
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) display else {
                    @Suppress("DEPRECATION")
                    windowManager.defaultDisplay
                }
            candidate =
                VideoDecoder(
                    surface = surface,
                    display = displayObject,
                    initialWidth = configuration.width,
                    initialHeight = configuration.height,
                    mime = mime,
                    onKeyframeRequired = { identity, _, reason ->
                        val callbackBinding =
                            ActiveDecoderCallbackBinding(identity, generation, ::isCurrentDecoderCallback)
                        runOnUiThread {
                            callbackBinding.runIfActive { sessionReference.get()?.requestKeyframe(reason) }
                        }
                    },
                    onCodecFailure = { identity, failure ->
                        val callbackBinding =
                            ActiveDecoderCallbackBinding(identity, generation, ::isCurrentDecoderCallback)
                        runOnUiThread {
                            callbackBinding.runIfActive {
                                CodecFallbackCommitGate.recordCurrentStructuralHevcFailure(
                                    codec = mime.toStreamCodec(),
                                    failure = failure,
                                    isCurrentConfiguration = callbackBinding::isActive,
                                )
                                showInternetFailure(IllegalStateException("Decoder failed: ${failure.reason}"))
                            }
                        }
                    },
                )
            val configuredDecoder = checkNotNull(candidate)
            val decision =
                commitConfiguration {
                    when (
                        val startupResult =
                            configuredDecoder.commitStartup {
                                if (!isCurrent() ||
                                    !isConfigurationCurrent() ||
                                    currentSurfaceHolder !== holder ||
                                    !surface.isValid ||
                                    surfaceGeneration.get() != expectedSurfaceGeneration
                                ) {
                                    false
                                } else {
                                    val nextPresentation =
                                        InternetDecoderPresentationState(
                                            decoder = configuredDecoder,
                                            configuration = configuration,
                                            displayWidth = configuration.width,
                                            displayHeight = configuration.height,
                                            displayRotation = configuration.rotationDegrees,
                                            connected = true,
                                        )
                                    val previousRequestedOrientation = requestedOrientation
                                    val previousStreamingWindowEnabled = isStreamingWindowStateEnabled()
                                    commitInternetDecoderPresentation(
                                        nextState = nextPresentation,
                                        captureState = ::captureInternetDecoderPresentation,
                                        installState = ::installInternetDecoderPresentation,
                                        restoreState = { attempted, previous ->
                                            restoreInternetDecoderPresentation(
                                                attempted = attempted,
                                                previous = previous,
                                                previousRequestedOrientation = previousRequestedOrientation,
                                                previousStreamingWindowEnabled = previousStreamingWindowEnabled,
                                            )
                                        },
                                    ) { previousPresentation ->
                                        applyRotation(configuration.rotationDegrees)
                                        binding.surfaceView.post {
                                            val callbackBinding =
                                                ActiveDecoderCallbackBinding(
                                                    configuredDecoder,
                                                    generation,
                                                ) { identity, sessionGeneration ->
                                                    sessionGeneration == internetGeneration &&
                                                        internetSession === sessionReference.get() &&
                                                        videoDecoder === identity
                                                }
                                            callbackBinding.runIfActive {
                                                sessionReference.get()?.requestKeyframe("decoder initialized")
                                            }
                                        }
                                        setStreamingWindowState(true)
                                        binding.resolutionText.text =
                                            getString(R.string.resolution_format, configuration.width, configuration.height)
                                        binding.statusIndicator.setBackgroundResource(R.drawable.status_indicator_green)
                                        showConnectedStreamUi()
                                        previousPresentation.decoder?.let { decoder ->
                                            DECODER_LIFECYCLE_EXECUTOR.execute { decoder.release() }
                                        }
                                    }
                                    true
                                }
                            }
                    ) {
                        DecoderStartupCommitResult.Committed -> {
                            candidate = null
                            ProductVideoDecision.ACCEPT
                        }
                        DecoderStartupCommitResult.NotCommitted ->
                            ProductVideoDecision.reject("stale_decoder_configuration")
                        is DecoderStartupCommitResult.Failed ->
                            ProductVideoDecision.reject(startupResult.reason).also {
                                CodecFallbackCommitGate.recordCurrentStructuralHevcFailure(
                                    codec = mime.toStreamCodec(),
                                    failure = startupResult.failure,
                                    isCurrentConfiguration = {
                                        isCurrent() &&
                                            isConfigurationCurrent() &&
                                            currentSurfaceHolder === holder &&
                                            surface.isValid &&
                                            surfaceGeneration.get() == expectedSurfaceGeneration
                                    },
                                )
                            }
                    }
                }
            candidate?.release()
            decision
        } catch (failure: Throwable) {
            candidate?.let { failedCandidate ->
                if (videoDecoder === failedCandidate) videoDecoder = null
                failedCandidate.release()
            }
            if (isCurrent()) {
                if (failure is DecoderInitializationException) {
                    CodecFallbackCommitGate.recordCurrentStructuralHevcFailure(
                        codec = mime.toStreamCodec(),
                        failure = failure.failure,
                        isCurrentConfiguration = {
                            isCurrent() &&
                                isConfigurationCurrent() &&
                                currentSurfaceHolder === holder &&
                                surface.isValid &&
                                surfaceGeneration.get() == expectedSurfaceGeneration
                        },
                    )
                }
            }
            ProductVideoDecision.reject(failure.message ?: "decoder_configuration_failure")
        }
    }

    private fun captureInternetDecoderPresentation() =
        InternetDecoderPresentationState(
            decoder = videoDecoder,
            configuration = internetVideoConfiguration,
            displayWidth = displayWidth,
            displayHeight = displayHeight,
            displayRotation = displayRotation,
            connected = isConnected,
        )

    private fun installInternetDecoderPresentation(
        state: InternetDecoderPresentationState<VideoDecoder, ProductVideoConfiguration>,
    ) {
        videoDecoder = state.decoder
        internetVideoConfiguration = state.configuration
        displayWidth = state.displayWidth
        displayHeight = state.displayHeight
        displayRotation = state.displayRotation
        isConnected = state.connected
    }

    private fun restoreInternetDecoderPresentation(
        attempted: InternetDecoderPresentationState<VideoDecoder, ProductVideoConfiguration>,
        previous: InternetDecoderPresentationState<VideoDecoder, ProductVideoConfiguration>,
        previousRequestedOrientation: Int,
        previousStreamingWindowEnabled: Boolean,
    ) {
        check(
            videoDecoderRef.compareAndSet(attempted.decoder, previous.decoder) ||
                videoDecoder === previous.decoder,
        ) { "Internet decoder changed while presentation rollback was in progress" }
        installInternetDecoderPresentation(previous)
        requestedOrientation = previousRequestedOrientation
        binding.surfaceView.apply {
            rotation = prefs.clientRotation.degrees.toFloat()
            scaleX = 1f
            scaleY = 1f
        }
        updateSurfaceViewportLayout()
        setStreamingWindowState(previousStreamingWindowEnabled)
        val previousConfiguration = previous.configuration
        if (previous.connected && previousConfiguration != null) {
            binding.resolutionText.text =
                getString(R.string.resolution_format, previousConfiguration.width, previousConfiguration.height)
            binding.statusIndicator.setBackgroundResource(R.drawable.status_indicator_green)
            showConnectedStreamUi()
        } else {
            showDisconnectedStreamUi()
        }
    }

    private fun isStreamingWindowStateEnabled(): Boolean {
        // Keep-screen-on is the reliable streaming indicator: FLAG_SECURE may be
        // intentionally absent when a debuggable build opts into screen capture.
        return (window.attributes.flags and WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) != 0
    }

    private fun updateInternetState(state: InternetProductSessionState) {
        val routeLabel =
            when (internetRoute) {
                PeerRoute.DIRECT -> getString(R.string.internet_route_direct)
                PeerRoute.RELAY -> getString(R.string.internet_route_relay)
                null -> getString(R.string.internet_route_pending)
            }
        LiveRegionTextApplier.apply(
            binding.internetStateText,
            getString(R.string.internet_state_format, internetStateLabel(state), routeLabel),
        )
        if (state == InternetProductSessionState.CLOSED || state == InternetProductSessionState.FAILED) {
            isConnected = false
            internetStylusGestureRouter.reset()
            internetStylusInputIds.clear()
            internetStylusContactRouter.reset()
            setStreamingWindowState(false)
        }
    }

    private fun internetStateLabel(state: InternetProductSessionState): String =
        getString(
            when (state) {
                InternetProductSessionState.IDLE -> R.string.internet_state_label_idle
                InternetProductSessionState.CONNECTING -> R.string.internet_state_label_connecting
                InternetProductSessionState.NEGOTIATING -> R.string.internet_state_label_negotiating
                InternetProductSessionState.ACTIVE -> R.string.internet_state_label_active
                InternetProductSessionState.RECOVERING -> R.string.internet_state_label_recovering
                InternetProductSessionState.SUSPENDED -> R.string.internet_state_label_suspended
                InternetProductSessionState.FAILED -> R.string.internet_state_label_failed
                InternetProductSessionState.CLOSED -> R.string.internet_state_label_closed
            },
        )

    private fun showInternetFailure(failure: Throwable) {
        if (!::binding.isInitialized) return
        if (internetSession != null) {
            requiredFreshInternetEpoch = maxOf(requiredFreshInternetEpoch, internetSessionEpoch)
            disconnectInternet(showIdle = false)
        }
        val guidance = ConnectionGuidanceFactory.from(failure, ConnectionGuidanceContext.internet())
        LiveRegionTextApplier.show(
            binding.internetErrorText,
            guidanceFullMessage(guidance),
        )
        LiveRegionTextApplier.apply(
            binding.internetStateText,
            getString(
                R.string.internet_state_format,
                internetStateLabel(InternetProductSessionState.FAILED),
                getString(R.string.internet_route_pending),
            ),
        )
        if (prefs.connectionMode == ConnectionMode.INTERNET) showDisconnectedStreamUi()
    }

    private fun disconnectInternet(showIdle: Boolean) {
        internetVideoDecoderLifecycle?.invalidate("session_stopped")
        internetVideoDecoderLifecycle = null
        val tickJob = internetTickJob
        val session = internetSession
        val networkMonitor = internetNetworkMonitor
        val decoder = videoDecoder
        var sessionCloseFailure: Throwable? = null
        try {
            session?.close()
        } catch (failure: PendingRevocationBarrierException) {
            val recoveredReason = session?.retryPendingRevocationBarrier()
            if (recoveredReason != null) {
                disconnectInternet(showIdle = false)
                revokeInternetPairing(recoveredReason, tombstonePersisted = true)
                return
            }
            if (session?.hasUndurableRevocationBarrier() != true) {
                disconnectInternet(showIdle)
                return
            }
            quarantineInternetSession(tickJob, networkMonitor, decoder, failure)
            return
        } catch (failure: Throwable) {
            sessionCloseFailure = failure
        }
        ++internetGeneration
        internetTickJob = null
        internetSession = null
        QUARANTINED_INTERNET_SESSION.compareAndSet(session, null)
        internetNetworkMonitor = null
        videoDecoder = null
        connectionAttemptInProgress = false
        internetRoute = null
        resetInternetInputStateForNewSession()
        internetVideoConfiguration = null
        displayWidth = 0
        displayHeight = 0
        isConnected = false
        runBestEffort(
            { sessionCloseFailure?.let { throw it } },
            { tickJob?.cancel() },
            { networkMonitor?.close() },
            { decoder?.release() },
            {
                setStreamingWindowState(false)
                binding.internetDisconnectButton.visibility = View.GONE
                val profile = internetProfileStore.loadPublicProfile()
                binding.internetConnectButton.isEnabled =
                    profile != null && profile.authoritativeSessionEpoch > requiredFreshInternetEpoch
                if (showIdle) {
                    LiveRegionTextApplier.apply(binding.internetStateText, getString(R.string.internet_state_idle))
                    LiveRegionTextApplier.hide(binding.internetErrorText)
                    showDisconnectedStreamUi()
                }
            },
        )
    }

    private fun quarantineInternetSession(
        tickJob: kotlinx.coroutines.Job?,
        networkMonitor: AndroidNetworkMonitor?,
        decoder: VideoDecoder?,
        failure: PendingRevocationBarrierException,
    ) {
        internetVideoDecoderLifecycle?.invalidate("session_quarantined")
        internetVideoDecoderLifecycle = null
        internetTickJob = null
        internetNetworkMonitor = null
        videoDecoder = null
        connectionAttemptInProgress = false
        internetRoute = null
        activeInternetInputIds.clear()
        internetStylusInputIds.clear()
        internetStylusGestureRouter.reset()
        internetStylusContactRouter.reset()
        internetVideoConfiguration = null
        displayWidth = 0
        displayHeight = 0
        displayRotation = 0
        isConnected = false
        val quarantinedSession = requireNotNull(internetSession)
        check(
            QUARANTINED_INTERNET_SESSION.compareAndSet(null, quarantinedSession) ||
                QUARANTINED_INTERNET_SESSION.get() === quarantinedSession,
        ) { "Another Internet session already owns the process quarantine" }
        listOf<() -> Unit>(
            { tickJob?.cancel() },
            { networkMonitor?.close() },
            { decoder?.release() },
        ).forEach { cleanup ->
            try {
                cleanup()
            } catch (cleanupFailure: Throwable) {
                failure.addSuppressed(cleanupFailure)
            }
        }
        binding.internetConnectButton.isEnabled = false
        binding.internetImportProfileButton.isEnabled = false
        binding.internetScanProfileButton.isEnabled = false
        binding.internetDisconnectButton.visibility = View.VISIBLE
        setStreamingWindowState(false)
        showDisconnectedStreamUi()
        android.util.Log.e(INTERNET_LOG_TAG, "Internet session retained behind a failed durable revocation barrier", failure)
    }

    private fun allowInternetCredentialMutation(): Boolean {
        val pairingIdentifier = internetProfileStore.verifiedPairingIdentifier()
            ?: internetProfileStore.loadPublicProfile()?.pairingIdentifier
        val quarantined =
            internetRevocationCoordinator.isCredentialMutationBlocked {
                internetProfileStore.hasDurableCredentialMutationBlock(pairingIdentifier) ||
                    internetStoredSessionFactory.hasPendingPairingPersistenceCleanup()
            }
        if (quarantined && ::binding.isInitialized) {
            binding.internetConnectButton.isEnabled = false
            binding.internetImportProfileButton.isEnabled = false
            binding.internetScanProfileButton.isEnabled = false
            LiveRegionTextApplier.show(
                binding.internetErrorText,
                getString(R.string.internet_revocation_quarantine),
            )
        }
        return !quarantined
    }

    private fun revokeInternetPairing(reason: String, tombstonePersisted: Boolean = false) {
        val profile = internetProfileStore.loadPublicProfile()
        val pairingIdentifier = profile?.pairingIdentifier ?: internetProfileStore.verifiedPairingIdentifier()
        val identityEpoch = profile?.identityEpoch ?: internetProfileStore.verifiedLocalIdentityEpoch()
        val cleanupFailures = mutableListOf<String>()
        try {
            disconnectInternet(showIdle = false)
        } catch (_: Throwable) {
            cleanupFailures += "active session"
        }
        if (pairingIdentifier != null) {
            if (identityEpoch == null) {
                cleanupFailures += "identity epoch"
            } else {
                try {
                    internetProfileStore.beginRevocationCleanup(pairingIdentifier, internetDeviceId, identityEpoch)
                } catch (_: Throwable) {
                    cleanupFailures += if (tombstonePersisted) "cleanup intent" else "revocation tombstone"
                }
                cleanupFailures += retryPendingInternetRevocationCleanup()
            }
        }
        requiredFreshInternetEpoch = Long.MAX_VALUE
        val revocationMessage =
            if (cleanupFailures.isEmpty()) {
                getString(R.string.internet_revoked, reason)
            } else {
                getString(R.string.internet_revoke_partial_failure, cleanupFailures.joinToString())
            }
        LiveRegionTextApplier.show(binding.internetErrorText, revocationMessage)
        LiveRegionTextApplier.apply(binding.internetStateText, getString(R.string.internet_profile_revoked))
        refreshInternetProfileUi()
        showDisconnectedStreamUi()
    }

    private fun retryPendingInternetRevocationCleanup(): List<String> {
        return try {
            internetProfileStore.retryPendingAuthenticatedRevocation()
            val result =
                internetProfileStore.retryPendingRevocationCleanup(
                    deletePairingSecret = internetStoredSessionFactory::removePairingSecrets,
                    deleteIdentityKey = { deviceId, epoch -> AndroidDeviceIdentityStore().delete(deviceId, epoch) },
                ) ?: return emptyList()
            result.remainingSteps.map { it.failureLabel }.distinct()
        } catch (failure: Throwable) {
            android.util.Log.e(INTERNET_LOG_TAG, "Could not retry durable Internet revocation cleanup", failure)
            listOf("cleanup state")
        }
    }

    private fun retryPendingPairingPersistenceCleanup(): Boolean {
        val pairingIdentifier = internetProfileStore.verifiedPairingIdentifier()
            ?: internetProfileStore.loadPublicProfile()?.pairingIdentifier
        return internetRevocationCoordinator.withCredentialMutationAdmission(
            durableBlock = { internetProfileStore.hasDurableCredentialMutationBlock(pairingIdentifier) },
        ) { permit ->
            internetStoredSessionFactory.retryPendingPairingPersistenceCleanup(
                currentPairingIdentifier = pairingIdentifier,
                cleanupBusinessState = { cleanupPairingIdentifier ->
                    internetProfileStore.removePairingBindingIfMatches(permit, cleanupPairingIdentifier)
                },
            )
        }
    }

    private fun retryPendingPairingIdentityAliasCleanup(): Boolean {
        val verifiedIdentityEpoch = internetProfileStore.verifiedLocalIdentityEpoch()
        return recoverPendingPairingIdentityAlias(
            persistence = pendingPairingIdentityAliasPersistence,
            isCommittedIdentity = { marker ->
                marker.deviceId == internetDeviceId && marker.identityEpoch == verifiedIdentityEpoch
            },
            deleteIdentity = AndroidDeviceIdentityStore()::delete,
        )
    }

    private fun connectWireless(
        host: String,
        port: Int,
        token: ByteArray,
        deviceName: String,
        macName: String,
    ) {
        if (!isInForeground) {
            wirelessAutoReconnectEnabled = true
            pendingWirelessReconnectDelayMs = WIRELESS_INITIAL_RETRY_DELAY_MS
            return
        }
        if (isConnected || connectionAttemptInProgress) return
        connectionAttemptInProgress = true
        val callbackClient = StreamClient(host, port, applicationContext, advertiseController = true)
        val callbackGeneration = activateSession(callbackClient)
        val retryCoordinator =
            createSessionAutomaticRetryCoordinator(callbackClient, callbackGeneration) {
                val delayMs =
                    pendingWirelessReconnectDelayMs
                        ?: initialWirelessReconnectBackoff.nextDelayMs(jitterUnit = 0.5)
                pendingWirelessReconnectDelayMs = null
                scheduleWirelessReconnect(delayMs)
            }
        setupStreamClientCallbacks(
            callbackClient,
            callbackGeneration,
            retryCoordinator,
            ConnectionGuidanceContext.trustedLan(port),
        )
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                log("Connecting wirelessly to $macName at $host:$port...")
                callbackClient.connectWireless(token, deviceName)
                // NOTE: onConnectSuccess is fired from the onConnectionStatus(true)
                // listener (above) right after handshake OK — not here. This line
                // would otherwise run AFTER the receive loop exits, i.e. AFTER
                // disconnect, incorrectly transitioning back to CONNECTED.
            } catch (e: StreamClient.WirelessConnectError) {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@launch
                runOnUiThread {
                    if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                    if (e !is StreamClient.WirelessConnectError.NetworkUnreachable) {
                        cancelWirelessReconnect()
                    }
                    wirelessController.onConnectError(e)
                }
            } catch (e: Exception) {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@launch
                log("Wireless connect failed: ${e.message}")
                runOnUiThread {
                    if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                    wirelessController.onConnectError(StreamClient.WirelessConnectError.NetworkUnreachable)
                }
            } finally {
                runOnUiThread {
                    if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                    connectionAttemptInProgress = false
                    retryCoordinator.onConnectionFinally(
                        automaticRetryEnabled = wirelessAutoReconnectEnabled,
                        disconnected = !isConnected,
                    )
                }
            }
        }
    }

    private fun scheduleWirelessReconnect(suggestedDelayMs: Long) {
        if (!wirelessAutoReconnectEnabled ||
            prefs.connectionMode != ConnectionMode.WIRELESS ||
            isConnected ||
            !isInForeground
        ) {
            return
        }
        val entry = pairedHostStorage.load() ?: return
        val delayMs = suggestedDelayMs.coerceIn(1L, WIRELESS_RECONNECT_MAXIMUM_DELAY_MS)
        wirelessController.showAutomaticReconnect(entry.macName, entry.host, entry.port, delayMs)
        wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)
        wirelessReconnectHandler.postDelayed(wirelessReconnectRunnable, delayMs)
        isReconnecting = true
        mainDiag("Wireless reconnect scheduled in ${delayMs}ms")
    }

    private fun cancelWirelessReconnect() {
        wirelessAutoReconnectEnabled = false
        pendingWirelessReconnectDelayMs = null
        initialWirelessReconnectBackoff.reset()
        isReconnecting = false
        wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)
    }

    private fun cancelConnectionForModeSwitch() {
        automaticUsbConnect = false
        hasAttemptedUsbConnection = false
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        cancelWirelessReconnect()
        stopPingTimer()
        val client = streamClient
        val generation = activeSessionGeneration
        completeCurrentNativeInputBoundary(InputPhase.INPUT_PHASE_ENDED) {
            client?.disconnect()
            if (client != null) sessionState.invalidate(client, generation)
            if (streamClient === client) streamClient = null
        }
        disconnectInternet(showIdle = false)
        connectionAttemptInProgress = false
        clearUsbConnectionGuidance()
        applyDisconnectedSessionUi()
    }

    private fun connect(
        host: String,
        port: Int,
        automatic: Boolean = false,
    ) {
        if (!isInForeground) {
            scheduleAutomaticUsbConnect(FOREGROUND_RECONNECT_DELAY_MS)
            return
        }
        if (isConnected || connectionAttemptInProgress) return
        connectionAttemptInProgress = true
        hasAttemptedUsbConnection = true
        clearUsbConnectionGuidance()
        if (prefs.connectionMode == ConnectionMode.USB) {
            updateDisconnectedHeader(ConnectionMode.USB)
        }
        val callbackClient = StreamClient(host, port, applicationContext, advertiseController = true)
        val guidanceContext = ConnectionGuidanceContext.adb(port, currentUsbTransportSnapshot().adbTransport)
        val callbackGeneration = activateSession(callbackClient)
        val retryCoordinator =
            createSessionAutomaticRetryCoordinator(callbackClient, callbackGeneration) {
                showDisconnectedStreamUi()
                scheduleAutomaticUsbConnect()
            }
        setupStreamClientCallbacks(callbackClient, callbackGeneration, retryCoordinator, guidanceContext)
        lifecycleScope.launch(Dispatchers.IO) {
            var inlineGuidance: ConnectionGuidance? = null
            try {
                log("Connecting to $host:$port...")
                callbackClient.connect()
            } catch (e: Exception) {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@launch
                val guidance = ConnectionGuidanceFactory.from(e, guidanceContext)
                if (!automatic && e !is SessionProtocolException) {
                    inlineGuidance = guidance
                }
            } finally {
                runOnUiThread {
                    if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                    connectionAttemptInProgress = false
                    retryCoordinator.onConnectionFinally(
                        automaticRetryEnabled = automaticUsbConnect,
                        disconnected = !isConnected,
                    )
                    if (!isConnected && prefs.connectionMode == ConnectionMode.USB) {
                        updateDisconnectedHeader(ConnectionMode.USB)
                        inlineGuidance?.let(::showUsbConnectionGuidance)
                    }
                }
            }
        }
    }

    private fun disconnect() {
        finishPendingRightClick()
        if (prefs.connectionMode == ConnectionMode.INTERNET || internetSession != null) {
            completeCurrentNativeInputBoundary(InputPhase.INPUT_PHASE_ENDED) {
                disconnectInternet(showIdle = true)
            }
            return
        }
        automaticUsbConnect = false
        cancelWirelessReconnect()
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        stopPingTimer()
        isReconnecting = false
        hasConnectedThisRun = false
        hasAttemptedUsbConnection = false
        val client = streamClient
        val generation = activeSessionGeneration
        completeCurrentNativeInputBoundary(InputPhase.INPUT_PHASE_ENDED) {
            client?.disconnect()
            if (client != null) sessionState.invalidate(client, generation)
            if (streamClient === client) streamClient = null
        }
        connectionAttemptInProgress = false
        applyDisconnectedSessionUi()
        log("Disconnected")
    }

    private fun applyDisconnectedSessionUi() {
        isConnected = false
        revealOnlyTouchGestureActive = false
        streamStylusGestureRouter.reset()
        streamStylusContactRouter.reset()
        streamStylusInputIds.clear()
        mainSessionDisplayLifecycle?.invalidate()
        mainSessionDisplayLifecycle = null
        // Drop any host-action state so a stale window-actions button never
        // lingers into the next session.
        availableHostActions = emptyList()
        binding.controlHostActionsButton.visibility = View.GONE
        binding.controlHostActionsButton.isEnabled = false
        cancelClipboardRequestTimeout()
        clipboardApprovalState.clear()
        binding.controlClipboardButton.visibility = View.GONE
        binding.controlClipboardButton.isEnabled = false
        binding.controlClipboardButton.contentDescription = getString(R.string.control_clipboard)
        TooltipCompat.setTooltipText(binding.controlClipboardButton, getText(R.string.control_clipboard))
        availableDisplays = emptyList()
        selectedDisplayId = ""
        DisplayCapsuleViewBinder.bind(
            resources = resources,
            selector = binding.displayCapsuleGroup,
            labelView = binding.controlDisplaysLabel,
            displaySelection = false,
            displays = emptyList(),
            selectedId = "",
        )
        applyControlBarLayout()
        encodedVideoConfigurationState.clear()
        activeDecoderConfigEpoch = 0L
        lastAppliedVideoPreferenceConfigEpoch = 0L
        displayWidth = 0
        displayHeight = 0
        displayRotation = 0
        setStreamingWindowState(false)
        stopPingTimer()
        releaseVideoDecoderAsync()
        showDisconnectedStreamUi()
        val mode = prefs.connectionMode
        if (mode == ConnectionMode.WIRELESS) {
            wirelessController.onStreamDisconnected()
        } else {
            startChecklistUpdates()
        }
        pendingTerminalGuidance?.let { guidance ->
            pendingTerminalGuidance = null
            showTerminalConnectionGuidance(mode, guidance)
        }
    }

    private fun startPingTimer() {
        stopPingTimer()
        pingJob =
            lifecycleScope.launch(Dispatchers.IO) {
                while (true) {
                    kotlinx.coroutines.delay(1000) // Ping every 1 second
                    streamClient?.sendPing()
                }
            }
    }

    private fun stopPingTimer() {
        pingJob?.cancel()
        pingJob = null
    }

    private fun cleanup() {
        try {
            disconnect()
            setStreamingWindowState(false)
        } catch (e: Exception) {
            log("⚠️ Cleanup error: ${e.message}")
        }
    }

    private fun handleTouch(
        view: View,
        event: MotionEvent,
    ) {
        if (!isInForeground) return
        if (consumeHiddenControlRevealGesture(event)) return
        if (prefs.connectionMode == ConnectionMode.INTERNET) {
            handleInternetTouch(view, event)
            return
        }
        if (!isConnected) return
        val stylusSnapshot = StylusInputMapper.snapshot(event) { x, y -> mapInputPoint(view, x, y) }
        val client = streamClient
        if (streamStylusGestureRouter.routesToStylus(stylusSnapshot, client?.canSendStylus() == true)) {
            val stylusSamples =
                streamStylusContactRouter.map(
                    stylusSnapshot,
                    extendedNegotiated = client?.canSendExtendedStylus() == true,
                )
            if (stylusSamples.isNotEmpty() && client?.sendMotionStylus(stylusSamples) == true) {
                mainDiagStylusForwarded(
                    "stream",
                    event,
                    stylusSamples,
                    extended = client.canSendExtendedStylus(),
                )
                trackStreamStylus(stylusSamples)
            }
            if (event.actionMasked == MotionEvent.ACTION_DOWN) revealControlBar()
            return
        }
        val pointerCount = event.pointerCount.coerceAtMost(MAX_FORWARDED_POINTERS)
        val mappedPointers =
            (0 until pointerCount).map { index ->
                val mapped = mapInputPoint(view, event.getX(index), event.getY(index))
                MotionPointer(event.getPointerId(index), mapped.x.toDouble(), mapped.y.toDouble())
            }.toMutableList()
        val first = mappedPointers.firstOrNull() ?: return
        val x = first.x
        val y = first.y
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                inputPredictor.reset()
                inputPredictor.addSample(x.toFloat(), y.toFloat())
                if ((applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
                    android.util.Log.d(
                        TOUCH_MAPPING_LOG_TAG,
                        "raw=${event.x},${event.y} view=${view.width}x${view.height} " +
                            "video=${displayWidth}x$displayHeight scale=${prefs.videoScaleMode} " +
                            "clientRotation=${prefs.clientRotation.degrees} hostRotation=$displayRotation " +
                            "mapped=$x,$y",
                    )
                }
                // A touch on the video reveals the control bar; it fades on its own.
                revealControlBar()
            }

            MotionEvent.ACTION_MOVE -> {
                if (pointerCount == 1) {
                    inputPredictor.addSample(x.toFloat(), y.toFloat())
                    val (px, py) = inputPredictor.predictPosition(12f)
                    mappedPointers[0] =
                        first.copy(
                            x = px.coerceIn(0f, 1f).toDouble(),
                            y = py.coerceIn(0f, 1f).toDouble(),
                        )
                }
            }

            MotionEvent.ACTION_UP -> {
                inputPredictor.reset()
            }

            MotionEvent.ACTION_CANCEL -> {
                inputPredictor.reset()
            }
        }

        val snapshot = MotionSnapshot(event.actionMasked, event.actionIndex, mappedPointers)
        val v1Samples = TouchSampleMapper.map(snapshot)
        val legacyAction =
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> LEGACY_TOUCH_DOWN
                MotionEvent.ACTION_MOVE -> LEGACY_TOUCH_MOVE
                else -> LEGACY_TOUCH_UP
            }
        streamClient?.sendMotionTouch(
            v1Samples = v1Samples,
            legacyAction = legacyAction,
            legacyPointers = mappedPointers,
        )
    }

    /**
     * Bridges negotiated native input into the active Protocol v1 session.
     * Every send is gated on the owning session generation so a stale
     * connection or decoder cannot inject into a newer session.
     */
    private inner class StreamClientInputSink(
        private val client: StreamClient,
        private val generation: Long,
    ) : ClientSessionInputSink {
        override fun sendKey(input: ClientKeyInput): Boolean {
            if (!isCurrentSession(client, generation)) return false
            val admitted =
                client.sendKey(
                    usbHidUsage = input.usbHidUsage,
                    pressed = input.pressed,
                    modifierMask = NativeInputWire.modifierMask(input.modifiers),
                )
            if (admitted) {
                nativeInputSessionState.recordKey(
                    client = client,
                    generation = generation,
                    usbHidUsage = input.usbHidUsage,
                    pressed = input.pressed,
                )
            }
            return admitted
        }

        override fun sendPointer(input: ClientPointerInput): Boolean {
            if (!isCurrentSession(client, generation)) return false
            val buttonMask = NativeInputWire.buttonMask(input.buttonState)
            val changedButtonMask = NativeInputWire.buttonMask(input.actionButton)
            val admitted =
                when (input.action) {
                    ClientPointerAction.SCROLL ->
                        client.sendScroll(
                            deltaX = input.horizontalScroll.toDouble(),
                            deltaY = input.verticalScroll.toDouble(),
                        )

                    else -> {
                        val phase = NativeInputWire.pointerPhase(input.action, buttonMask, changedButtonMask) ?: return false
                        client.sendPointer(
                            phase = phase,
                            x = input.x,
                            y = input.y,
                            buttonMask = buttonMask,
                        )
                    }
                }
            if (admitted && input.action != ClientPointerAction.SCROLL) {
                nativeInputSessionState.recordPointer(client, generation, input.x, input.y, buttonMask)
            }
            return admitted
        }

        override fun sendController(input: ClientControllerInput): Boolean {
            if (!isCurrentSession(client, generation)) return false
            return client.sendController(input.dispatch)
        }
    }

    private fun completeCurrentNativeInputBoundary(
        pointerPhase: InputPhase,
        afterRelease: () -> Unit = {},
    ) {
        val client = streamClient
        val generation = activeSessionGeneration
        val internet = internetSession
        val internetExtended = internet?.canSendExtendedStylus() == true
        stylusReleaseCoordinator.completeBoundary(
            submitStream = { cancellations -> client?.sendMotionStylus(cancellations) },
            submitInternet = { cancellations ->
                cancellations.forEach { cancellation ->
                    internet?.sendStylus(cancellation.sample.toProductStylusEvent(cancellation.inputId, internetExtended))
                }
            },
        ) {
            streamStylusContactRouter.reset()
            internetStylusContactRouter.reset()
            if (internet != null) {
                internetControllerSessionState.takeRelease()?.let { release ->
                    if (!sendInternetControllerDispatch(release, "internet controller release", internet)) {
                        mainDiag("internet controller release was rejected")
                    }
                }
            }
            completeNativeInputBoundary(client, generation, pointerPhase, afterRelease)
        }
    }

    private fun resetInternetInputStateForNewSession() {
        activeInternetInputIds.clear()
        internetStylusInputIds.clear()
        internetStylusGestureRouter.reset()
        internetStylusContactRouter.reset()
        internetControllerSessionState.resetForNewSession()
        internetInputIds.resetForNewSession()
    }

    private fun completeNativeInputBoundary(
        client: StreamClient?,
        generation: Long,
        pointerPhase: InputPhase,
        afterRelease: () -> Unit,
    ) {
        if (client == null) {
            streamControllerSessionState.takeRelease()
            afterRelease()
            return
        }
        streamControllerSessionState.takeRelease()?.let { release ->
            if (!sendStreamControllerDispatch(release, "controller release")) {
                mainDiag("controller release was rejected for generation=$generation")
            }
        }
        val submission =
            nativeInputReleaseCoordinator.completeBoundary(
                client = client,
                generation = generation,
                submitRelease = { release -> client.sendNativeInputRelease(release, pointerPhase) },
                afterRelease = afterRelease,
            )
        if (submission == NativeInputReleaseSubmission.REJECTED) {
            mainDiag("native input release was rejected for generation=$generation")
        }
    }

    private fun trackStreamStylus(samples: List<StylusSample>) {
        samples.forEach { sample ->
            streamStylusInputIds.resolve(sample)
            streamStylusInputIds.complete(sample)
        }
    }

    private fun mapInputPoint(
        view: View,
        x: Float,
        y: Float,
    ): TouchMapper.Point =
        TouchMapper.map(
            x = x,
            y = y,
            viewWidth = view.width,
            viewHeight = view.height,
            videoWidth = displayWidth,
            videoHeight = displayHeight,
            scaleMode = prefs.videoScaleMode,
            renderRotation = prefs.clientRotation.degrees,
        )

    private fun updateSurfaceViewportLayout() {
        if (!::binding.isInitialized || displayWidth <= 0 || displayHeight <= 0) return
        val parentWidth = binding.root.width
        val parentHeight = binding.root.height
        if (parentWidth <= 0 || parentHeight <= 0) return

        val layout =
            ViewportPolicy.layout(
                parentWidth = parentWidth,
                parentHeight = parentHeight,
                videoWidth = displayWidth,
                videoHeight = displayHeight,
                scaleMode = prefs.videoScaleMode,
                renderRotation = prefs.clientRotation.degrees,
            )
        val viewportParams =
            binding.videoViewport.layoutParams as androidx.constraintlayout.widget.ConstraintLayout.LayoutParams
        if (viewportParams.width != layout.viewport.width || viewportParams.height != layout.viewport.height) {
            viewportParams.width = layout.viewport.width
            viewportParams.height = layout.viewport.height
            binding.videoViewport.layoutParams = viewportParams
        }
        val surfaceParams = binding.surfaceView.layoutParams as android.widget.FrameLayout.LayoutParams
        if (surfaceParams.width != layout.surface.width || surfaceParams.height != layout.surface.height) {
            surfaceParams.width = layout.surface.width
            surfaceParams.height = layout.surface.height
            surfaceParams.gravity = android.view.Gravity.CENTER
            binding.surfaceView.layoutParams = surfaceParams
        }
    }

    private fun handleInternetTouch(
        view: View,
        event: MotionEvent,
    ) {
        val session = internetSession ?: return
        if (handleInternetStylus(view, event, session)) return
        if (!session.canSendTouch()) {
            activeInternetInputIds.clear()
            return
        }

        fun send(index: Int, phase: ProductInputPhase) {
            val pointerId = event.getPointerId(index)
            val inputId =
                when (phase) {
                    ProductInputPhase.BEGAN -> internetInputIds.next().also { activeInternetInputIds[pointerId] = it }
                    else -> activeInternetInputIds[pointerId] ?: return
                }
            val point =
                InternetTouchMapper.map(
                    x = event.getX(index),
                    y = event.getY(index),
                    viewWidth = view.width,
                    viewHeight = view.height,
                    videoWidth = displayWidth,
                    videoHeight = displayHeight,
                    scaleMode = prefs.videoScaleMode,
                    clientRotation = prefs.clientRotation,
                )
            session.sendTouch(
                ProductTouchEvent(
                    inputId = inputId,
                    pointerId = pointerId,
                    phase = phase,
                    normalizedX = point.x.toDouble().coerceIn(0.0, 1.0),
                    normalizedY = point.y.toDouble().coerceIn(0.0, 1.0),
                    pressure = event.getPressure(index).toDouble().coerceIn(0.0, 1.0),
                ),
            )
            if (phase == ProductInputPhase.ENDED || phase == ProductInputPhase.CANCELLED) {
                activeInternetInputIds.remove(pointerId)
            }
        }

        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> send(event.actionIndex, ProductInputPhase.BEGAN)
            MotionEvent.ACTION_MOVE -> repeat(event.pointerCount) { send(it, ProductInputPhase.CHANGED) }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP -> send(event.actionIndex, ProductInputPhase.ENDED)
            MotionEvent.ACTION_CANCEL -> repeat(event.pointerCount) { send(it, ProductInputPhase.CANCELLED) }
        }
    }

    private fun handleInternetStylus(
        view: View,
        event: MotionEvent,
        session: InternetProductSession,
        extendedOnly: Boolean = false,
    ): Boolean {
        val snapshot =
            StylusInputMapper.snapshot(event) { x, y ->
                InternetTouchMapper.map(
                    x = x,
                    y = y,
                    viewWidth = view.width,
                    viewHeight = view.height,
                    videoWidth = displayWidth,
                    videoHeight = displayHeight,
                    scaleMode = prefs.videoScaleMode,
                    clientRotation = prefs.clientRotation,
                )
            }
        val extended = session.canSendExtendedStylus()
        val directExtendedRoute = extendedOnly && extended && snapshot.pointers.any { it.toolKind != null }
        if (!directExtendedRoute && !internetStylusGestureRouter.routesToStylus(snapshot, session.canSendStylus())) return false
        val samples = internetStylusContactRouter.map(snapshot, extendedNegotiated = extended)
        if (extendedOnly && samples.isEmpty()) return false
        samples.forEach { sample ->
            val inputId = internetStylusInputIds.resolve(sample) ?: return@forEach
            if (session.sendStylus(sample.toProductStylusEvent(inputId, extended))) {
                mainDiagStylusForwarded("internet", event, listOf(sample), extended)
            }
            internetStylusInputIds.complete(sample)
        }
        if (event.actionMasked == MotionEvent.ACTION_CANCEL) internetStylusInputIds.clear()
        if (event.actionMasked == MotionEvent.ACTION_DOWN) revealControlBar()
        return true
    }

    private fun consumeHiddenControlRevealGesture(event: MotionEvent): Boolean {
        val phase = event.streamTouchPhase()
        val directTouch = event.isDirectTouchGesture()
        if (
            ControlRevealGesturePolicy.shouldStartRevealOnlyGesture(
                connected = isConnected,
                controlBarVisible = binding.controlBar.visibility == View.VISIBLE,
                directTouch = directTouch,
                inRevealHotZone = event.isInControlRevealHotZone(),
                phase = phase,
            )
        ) {
            revealOnlyTouchGestureActive = true
            revealControlBar()
        }
        val consume =
            ControlRevealGesturePolicy.shouldConsumeActiveRevealOnlyGesture(
                revealOnlyGestureActive = revealOnlyTouchGestureActive,
                directTouch = directTouch,
                phase = phase,
            )
        if (!directTouch || ControlRevealGesturePolicy.endsGesture(phase)) {
            revealOnlyTouchGestureActive = false
        }
        return consume
    }

    private fun MotionEvent.streamTouchPhase(): StreamTouchPhase =
        when (actionMasked) {
            MotionEvent.ACTION_DOWN -> StreamTouchPhase.BEGIN
            MotionEvent.ACTION_MOVE,
            MotionEvent.ACTION_POINTER_DOWN,
            MotionEvent.ACTION_POINTER_UP,
            -> StreamTouchPhase.UPDATE
            MotionEvent.ACTION_UP -> StreamTouchPhase.END
            MotionEvent.ACTION_CANCEL -> StreamTouchPhase.CANCEL
            else -> StreamTouchPhase.OTHER
        }

    private fun MotionEvent.isDirectTouchGesture(): Boolean =
        (source and InputDevice.SOURCE_TOUCHSCREEN) == InputDevice.SOURCE_TOUCHSCREEN &&
            (0 until pointerCount).all { index ->
                when (getToolType(index)) {
                    MotionEvent.TOOL_TYPE_FINGER,
                    MotionEvent.TOOL_TYPE_UNKNOWN,
                    -> true
                    else -> false
                }
            }

    private fun MotionEvent.isInControlRevealHotZone(): Boolean {
        val controlBarHeight =
            binding.controlBar.height.takeIf { it > 0 }
                ?: resources.getDimensionPixelSize(R.dimen.display_capsule_min_height)
        val topInset = safeAreaInsets.top + resources.getDimensionPixelSize(R.dimen.control_bar_margin_top)
        val hotZoneBottom = topInset + controlBarHeight + resources.getDimensionPixelSize(R.dimen.control_bar_margin_top)
        return y <= hotZoneBottom
    }

    private fun InputPhase.toProductInputPhase(): ProductInputPhase =
        when (this) {
            InputPhase.INPUT_PHASE_BEGAN -> ProductInputPhase.BEGAN
            InputPhase.INPUT_PHASE_CHANGED -> ProductInputPhase.CHANGED
            InputPhase.INPUT_PHASE_ENDED -> ProductInputPhase.ENDED
            InputPhase.INPUT_PHASE_CANCELLED -> ProductInputPhase.CANCELLED
            else -> error("Unspecified stylus phase")
        }

    private fun StylusSample.toProductStylusEvent(inputId: Long, extended: Boolean): ProductStylusEvent =
        ProductStylusEvent(
            inputId = inputId,
            pointerId = pointerId,
            phase = phase.toProductInputPhase(),
            normalizedX = x,
            normalizedY = y,
            pressure = pressure,
            tiltXDegrees = tiltXDegrees,
            tiltYDegrees = tiltYDegrees,
            toolKind =
                if (extended) {
                    when (toolKind) {
                        StylusToolKind.PEN -> dev.vibescreen.protocol.v1.StylusToolKind.STYLUS_TOOL_KIND_PEN
                        StylusToolKind.ERASER -> dev.vibescreen.protocol.v1.StylusToolKind.STYLUS_TOOL_KIND_ERASER
                    }
                } else null,
            buttonMask = if (extended) buttonMask else 0,
            contactState =
                if (extended) {
                    when (contactState) {
                        StylusContactState.CONTACT ->
                            dev.vibescreen.protocol.v1.StylusContactState.STYLUS_CONTACT_STATE_CONTACT
                        StylusContactState.PROXIMITY ->
                            dev.vibescreen.protocol.v1.StylusContactState.STYLUS_CONTACT_STATE_PROXIMITY
                    }
                } else null,
        )

    private fun mainDiagStylusForwarded(
        transport: String,
        event: MotionEvent,
        samples: List<StylusSample>,
        extended: Boolean,
    ) {
        val sample = samples.firstOrNull() ?: return
        mainDiag(
            "Stylus forwarded: transport=$transport samples=${samples.size} extended=$extended " +
                "rawSource=0x${event.source.toString(16)} rawAction=${event.actionMasked} " +
                "rawTools=${event.toolTypesSummary()} " +
                "phase=${sample.phase} contact=${sample.contactState} tool=${sample.toolKind} " +
                "buttons=${sample.buttonMask} pressure=${sample.pressure} " +
                "tiltX=${sample.tiltXDegrees} tiltY=${sample.tiltYDegrees}",
        )
    }

    private fun MotionEvent.toolTypesSummary(): String =
        (0 until pointerCount).joinToString(separator = ",", prefix = "[", postfix = "]") { index ->
            toolTypeName(getToolType(index))
        }

    private fun toolTypeName(toolType: Int): String =
        when (toolType) {
            MotionEvent.TOOL_TYPE_STYLUS -> "stylus"
            MotionEvent.TOOL_TYPE_ERASER -> "eraser"
            MotionEvent.TOOL_TYPE_FINGER -> "finger"
            MotionEvent.TOOL_TYPE_MOUSE -> "mouse"
            MotionEvent.TOOL_TYPE_UNKNOWN -> "unknown"
            else -> "other-$toolType"
        }

    /**
     * Apply rotation by changing the Activity's screen orientation
     * This provides proper fullscreen portrait/landscape support
     */
    private fun applyRotation(rotation: Int) {
        val effectiveRotation = ViewportPolicy.effectiveRotation(rotation, prefs.clientRotation)
        requestedOrientation =
            when (effectiveRotation) {
                90 -> ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                180 -> ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE
                270 -> ActivityInfo.SCREEN_ORIENTATION_REVERSE_PORTRAIT
                else -> ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE // 0°
            }

        // Host rotation chooses the device orientation. The encoded frame keeps
        // its source orientation, so only the client-local offset transforms it.
        binding.surfaceView.apply {
            this.rotation = prefs.clientRotation.degrees.toFloat()
            scaleX = 1f
            scaleY = 1f
        }
        updateSurfaceViewportLayout()

        log(
            "🔄 Orientation: ${when (effectiveRotation) {
                90 -> "Portrait"
                180 -> "Landscape (flipped)"
                270 -> "Portrait (flipped)"
                else -> "Landscape"
            }}",
        )
    }

    /**
     * Reset orientation to follow device sensor (when disconnected)
     */
    private fun resetOrientationToSensor() {
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR
    }

    @SuppressLint("SetTextI18n") // Developer-only rolling diagnostic output is not user-facing copy.
    private fun log(message: String) {
        runOnUiThread {
            val current = binding.logText.text.toString()
            val lines = current.split("\n").takeLast(5)
            binding.logText.text = (lines + message).joinToString("\n")
        }
    }

    override fun onDestroy() {
        if (::deviceHealthMonitor.isInitialized) deviceHealthMonitor.stop()
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)
        cancelClipboardRequestTimeout()
        fileTransferApprovalHandler.removeCallbacksAndMessages(null)
        pendingIncomingFileDialog?.dismiss()
        pendingIncomingFileDialog = null
        discardPendingOutgoingFileTransfer()
        stopChecklistUpdates()
        activeSettingsDialog?.dismiss()
        runCatching(::discardPendingInternetPairing).onFailure { failure ->
            android.util.Log.e(INTERNET_LOG_TAG, "Could not delete pending pairing identity", failure)
        }
        cleanup()
        super.onDestroy()
    }

    companion object {
        private const val TOUCH_MAPPING_LOG_TAG = "VibeScreenTouchMap"
        private const val CLIPBOARD_REQUEST_TIMEOUT_MS = 10_000L
        private const val EXTRA_AUTO_CONNECT = "auto_connect"
        private const val STATE_AUTOMATIC_USB_CONNECT = "automatic_usb_connect"
        private const val ACTION_USB_STATE = "android.hardware.usb.action.USB_STATE"
        private const val EXTRA_USB_CONNECTED = "connected"
        private const val EXTRA_USB_CONFIGURED = "configured"
        private const val EXTRA_USB_FUNCTION_ADB = "adb"
        private const val WIRELESS_ADB_ENABLED_SETTING = "adb_wifi_enabled"
        private const val MAX_DEVICE_NAME_LENGTH = 64
        private const val WIRELESS_INITIAL_RETRY_DELAY_MS = 500L
        private const val WIRELESS_RECONNECT_MAXIMUM_DELAY_MS = 3_000L
        private const val UPSTREAM_NOTICE_ASSET = "NOTICE"
        private const val DEPENDENCY_LICENSES_ASSET = "ANDROID_RUNTIME_DEPENDENCY_LICENSES.md"
        private const val LEGACY_TOUCH_DOWN = 0
        private const val LEGACY_TOUCH_MOVE = 1
        private const val LEGACY_TOUCH_UP = 2
        private const val LEGACY_SCROLL_POINTER_COUNT = 2
        private const val MAX_FORWARDED_POINTERS = 2
        private const val LEGACY_RIGHT_CLICK_HOLD_MS = 650L
        private const val NATIVE_POINTER_MOVE_DIAG_INTERVAL_MS = 250L
        private const val FOREGROUND_RECONNECT_DELAY_MS = 150L
        private const val FOREGROUND_KEYFRAME_REASON = "client returned to foreground"
        private const val CLIPBOARD_MENU_SEND = 1
        private const val CLIPBOARD_MENU_RECEIVE = 2
        private const val FILE_TRANSFER_APPROVAL_TIMEOUT_MS = 30_000L
        private const val FILE_TRANSFER_COPY_BUFFER_BYTES = 64 * 1024
        private const val MAX_FILE_TRANSFER_DISPLAY_NAME_CHARS = 120

        // Uniform breathing gap, in dp, added on top of the safe-area insets for
        // floating chrome (control bar, settings panel, settings button) and the
        // draggable overlay clamp. Matches the settings button's resting margin.
        private const val SETTINGS_CHROME_MARGIN_DP = 24f
        private const val SETTINGS_DIALOG_MAX_WIDTH_DP = 680f
        private const val SETTINGS_DIALOG_MAX_HEIGHT_RATIO = 0.85f
        private val DECODER_LIFECYCLE_EXECUTOR =
            Executors.newSingleThreadExecutor { runnable ->
                Thread(runnable, "VibeDecoderLifecycle").apply { isDaemon = true }
            }
        private const val REQ_INTERNET_SCAN = 1101
        private const val REQ_INTERNET_CAMERA = 1102
        private const val REQ_FILE_TRANSFER_OPEN = 1103
        private const val INTERNET_TICK_INTERVAL_MS = 250L
        private const val INTERNET_LOG_TAG = "VibeInternet"
        private val QUARANTINED_INTERNET_SESSION = AtomicReference<InternetProductSession?>()
    }

    // ==================== Connection Checklist ====================

    private fun startChecklistUpdates() {
        // Stop any existing runnable first to prevent duplicates
        checklistRunnable?.let {
            checklistHandler.removeCallbacks(it)
        }

        checklistRunnable =
            object : Runnable {
                override fun run() {
                    updateChecklist()
                    checklistHandler.postDelayed(this, 2000) // Update every 2 seconds
                }
            }
        checklistHandler.post(checklistRunnable!!)
    }

    private fun stopChecklistUpdates() {
        checklistRunnable?.let {
            checklistHandler.removeCallbacks(it)
            checklistRunnable = null
        }
    }

    private fun updateChecklist() {
        // Diagnostics are deliberately lazy. The normal disconnected screen
        // should be calm, and a second socket probe used to compete with the
        // real automatic connection loop.
        if (isConnected) return
        if (UsbTransportDisplayPolicy.shouldRefreshSubtitle(prefs.connectionMode)) {
            updateUsbTransportSubtitle()
        }
        if (!connectionDetailsVisible) return

        val transportSnapshot = currentUsbTransportSnapshot()
        val transportProjection = UsbTransportDisplayPolicy.project(transportSnapshot)
        applyUsbTransportChecklist(transportSnapshot, transportProjection)

        if (automaticUsbConnect || connectionAttemptInProgress) {
            ChecklistStatusApplier.apply(
                this,
                binding.checkMacServer,
                binding.textMacServer,
                R.string.mac_server,
                ChecklistStatus.CHECKING,
            )
            updateMainStatus(false)
            return
        }

        // Check Mac Server (try to connect to port)
        ChecklistStatusApplier.apply(
            this,
            binding.checkMacServer,
            binding.textMacServer,
            R.string.mac_server,
            ChecklistStatus.CHECKING,
        )
        lifecycleScope.launch(Dispatchers.IO) {
            // Double-check connection state before socket test
            if (isConnected) return@launch

            val port =
                binding.portInput.text
                    .toString()
                    .toIntOrNull() ?: 54321
            val isServerRunning = checkServerRunning("127.0.0.1", port)
            runOnUiThread {
                if (!ChecklistProbeResultPolicy.shouldApply(
                        connectionMode = prefs.connectionMode,
                        detailsVisible = connectionDetailsVisible,
                        connected = isConnected,
                        connectionAttemptInProgress = connectionAttemptInProgress,
                        automaticUsbConnect = automaticUsbConnect,
                    )
                ) {
                    return@runOnUiThread
                }

                val completedSnapshot =
                    currentUsbTransportSnapshot().copy(serverRunning = isServerRunning)
                val completedProjection = UsbTransportDisplayPolicy.project(completedSnapshot)
                applyUsbTransportChecklist(completedSnapshot, completedProjection)

                ChecklistStatusApplier.apply(
                    this@MainActivity,
                    binding.checkMacServer,
                    binding.textMacServer,
                    R.string.mac_server,
                    if (isServerRunning) ChecklistStatus.READY else ChecklistStatus.NOT_READY,
                )
                updateMainStatus(completedProjection.allReady)
            }
        }
    }

    private fun applyUsbTransportChecklist(
        snapshot: UsbTransportDisplayPolicy.Snapshot,
        projection: UsbTransportDisplayPolicy.Projection,
    ) {
        ChecklistStatusApplier.apply(
            this,
            binding.checkDeveloperMode,
            binding.textDeveloperMode,
            R.string.developer_mode,
            if (snapshot.developerModeEnabled) ChecklistStatus.READY else ChecklistStatus.NOT_READY,
        )

        ChecklistStatusApplier.apply(
            this,
            binding.checkUsbDebugging,
            binding.textUsbDebugging,
            projection.debuggingLabelResource,
            projection.debuggingStatus,
        )

        // Charging alone also succeeds with charge-only cables. The sticky USB
        // state broadcast tells us whether Android configured a real data link.
        // Debugging readiness is reported separately because ADB_ENABLED alone
        // only proves that USB debugging is allowed.
        ChecklistStatusApplier.apply(
            this,
            binding.checkUsbConnected,
            binding.textUsbConnected,
            projection.transportLabelResource,
            projection.transportStatus,
        )
    }

    private fun updateMainStatus(allReady: Boolean) {
        binding.statusIndicator.setBackgroundResource(
            if (allReady) {
                R.drawable.status_indicator_green
            } else {
                R.drawable.status_indicator_waiting
            },
        )
        if (!automaticUsbConnect && !connectionAttemptInProgress) {
            updateStatus(if (allReady) "Ready to connect" else "Check the connection details below")
        }
    }

    private fun isWirelessAdbEnabled(): Boolean =
        Settings.Global.getInt(contentResolver, WIRELESS_ADB_ENABLED_SETTING, 0) == 1

    private fun currentUsbTransportSnapshot(): UsbTransportDisplayPolicy.Snapshot {
        val usbState = registerReceiver(null, IntentFilter(ACTION_USB_STATE))
        val usbDataConnected =
            usbState?.let { state ->
                state.getBooleanExtra(EXTRA_USB_CONNECTED, false) &&
                    state.getBooleanExtra(EXTRA_USB_CONFIGURED, false)
            } == true
        return UsbTransportDisplayPolicy.Snapshot(
            developerModeEnabled =
                Settings.Global.getInt(
                    contentResolver,
                    Settings.Global.DEVELOPMENT_SETTINGS_ENABLED,
                    0,
                ) == 1,
            usbDebuggingSettingEnabled =
                Settings.Global.getInt(
                    contentResolver,
                    Settings.Global.ADB_ENABLED,
                    0,
                ) == 1,
            wirelessDebuggingEnabled = isWirelessAdbEnabled(),
            usbDataConnected = usbDataConnected,
            usbAdbFunctionEnabled =
                usbDataConnected && usbState?.getBooleanExtra(EXTRA_USB_FUNCTION_ADB, false) == true,
            serverRunning = false,
        )
    }

    private fun updateUsbTransportSubtitle() {
        val subtitleResource = UsbTransportDisplayPolicy.project(currentUsbTransportSnapshot()).subtitleResource
        LiveRegionTextApplier.apply(binding.connectionSubtitle, getString(subtitleResource))
    }

    /**
     * Check if Mac server is actually running (not just ADB reverse)
     *
     * Problem: When `adb reverse tcp:54321 tcp:54321` is active, ADB daemon listens on port 54321.
     * A simple socket connect will succeed to ADB daemon, not the actual Mac server.
     *
     * Solution: After connecting, try to read data with a short timeout.
     * Mac server sends display config (type=1) immediately upon connection.
     * ADB daemon doesn't send anything, so read will timeout → false.
     */
    private fun checkServerRunning(
        host: String,
        port: Int,
    ): Boolean {
        var socket: Socket? = null
        return try {
            socket = Socket()
            socket.connect(InetSocketAddress(host, port), 300) // 300ms connect timeout
            socket.soTimeout = 200 // 200ms read timeout

            // Try to read - Mac server sends display config immediately
            // ADB daemon doesn't send anything, so read will timeout
            val input = socket.getInputStream()
            val firstByte = input.read() // Blocks up to soTimeout

            // If we got data (>= 0), it's the real Mac server
            // -1 means EOF (connection closed), anything else is data
            firstByte >= 0
        } catch (e: Exception) {
            // Timeout, connection refused, or other error = server not running
            false
        } finally {
            try {
                socket?.close()
            } catch (e: Exception) {
                // ignore
            }
        }
    }
}
