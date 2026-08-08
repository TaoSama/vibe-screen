package dev.telemachus.display

import android.annotation.SuppressLint
import android.app.Dialog
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ActivityInfo
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.media.MediaFormat
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.MotionEvent
import android.view.InputDevice
import android.view.KeyEvent
import android.view.SurfaceHolder
import android.view.View
import android.view.Window
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.widget.TextView
import android.widget.Toast
import android.widget.EditText
import android.widget.PopupMenu
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.TooltipCompat
import androidx.constraintlayout.widget.ConstraintSet
import androidx.lifecycle.lifecycleScope
import com.google.android.material.button.MaterialButton
import com.google.android.material.button.MaterialButtonToggleGroup
import com.google.android.material.slider.Slider
import com.google.android.material.switchmaterial.SwitchMaterial
import dev.telemachus.display.databinding.ActivityMainBinding
import dev.telemachus.display.protocol.MotionPointer
import dev.telemachus.display.protocol.MotionSnapshot
import dev.telemachus.display.protocol.TouchSampleMapper
import dev.telemachus.display.internet.AndroidNetworkMonitor
import dev.telemachus.display.internet.InternetDecoderConfigurationResult
import dev.telemachus.display.internet.InternetProductSession
import dev.telemachus.display.internet.InternetProductSessionCallbacks
import dev.telemachus.display.internet.InternetProductRevocationCoordinator
import dev.telemachus.display.internet.InternetProductSessionState
import dev.telemachus.display.internet.InternetProductRevocationStore
import dev.telemachus.display.internet.InternetSessionProfileStore
import dev.telemachus.display.internet.InternetVideoDecoderLifecycle
import dev.telemachus.display.internet.PeerRoute
import dev.telemachus.display.internet.PendingRevocationBarrierException
import dev.telemachus.display.internet.ProductInputPhase
import dev.vibescreen.protocol.v1.InputPhase
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
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.util.Locale
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
    private val nextInternetInputId = AtomicLong(0)
    private val activeInternetInputIds = mutableMapOf<Int, Long>()
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
    private var activeSessionGeneration = 0L
    private var unsupportedKeyboardNoticeShown = false
    private val inputHandler = Handler(Looper.getMainLooper())
    private var pendingRightClickRelease: Runnable? = null

    // For dragging stats overlay
    private var isDraggingOverlay = false
    private var overlayDx = 0f
    private var overlayDy = 0f

    // Input prediction for low-latency gaming
    private val inputPredictor = InputPredictor()

    // Checklist status handler
    private val checklistHandler = Handler(Looper.getMainLooper())
    private var checklistRunnable: Runnable? = null
    private var isConnected = false // Track connection state to prevent checklist conflicts
    private var connectionAttemptInProgress = false
    private var automaticUsbConnect = false
    private var connectionDetailsVisible = false
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
    private val controlBarHandler = Handler(Looper.getMainLooper())
    private val controlBarHideRunnable = Runnable { hideControlBar() }
    private var availableDisplays = emptyList<StreamDisplayOption>()
    private var selectedDisplayId = ""
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

        // Allow rotation based on device sensor when not connected
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR

        // Enable edge-to-edge display (draw behind system bars and cutout)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            window.attributes.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

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
        mainDiag("lifecycle foreground connected=$isConnected")
        val scannerLaunched =
            ::wirelessController.isInitialized &&
                prefs.connectionMode == ConnectionMode.WIRELESS &&
                wirelessController.onHostForegrounded()
        if (scannerLaunched) return
        if (isConnected) {
            setStreamingWindowState(true)
            streamClient?.requestKeyframe(force = true, reason = "client returned to foreground")
        } else if (prefs.connectionMode == ConnectionMode.WIRELESS && wirelessAutoReconnectEnabled) {
            pendingWirelessReconnectDelayMs?.let(::scheduleWirelessReconnect)
                ?: pairedHostStorage.load()?.let { scheduleWirelessReconnect(WIRELESS_INITIAL_RETRY_DELAY_MS) }
        } else {
            scheduleAutomaticUsbConnect(FOREGROUND_RECONNECT_DELAY_MS)
        }
    }

    override fun onStop() {
        finishPendingRightClick()
        isInForeground = false
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)
        mainDiag("lifecycle background connected=$isConnected; retries paused")
        super.onStop()
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (!isConnected || event.isSystemKey()) return super.dispatchKeyEvent(event)
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
        } else {
            startChecklistUpdates()
        }
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

    /** Keep the tablet awake and its streamed Mac pixels out of screenshots only while connected. */
    private fun setStreamingWindowState(enabled: Boolean) {
        val streamingFlags =
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                secureFlagIfProtected()
        if (enabled) {
            window.addFlags(streamingFlags)
        } else {
            window.clearFlags(
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_SECURE,
            )
        }
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
                    // Only release decoder, NOT the connection.
                    surfaceGeneration.incrementAndGet()
                    if (currentSurfaceHolder === holder) currentSurfaceHolder = null
                    releaseVideoDecoderAsync()
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
        binding.root.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ ->
            updateSurfaceViewportLayout()
        }
    }

    private fun handleGenericMotion(
        view: View,
        event: MotionEvent,
    ): Boolean {
        if (prefs.connectionMode == ConnectionMode.INTERNET) return false
        if (!isConnected || !isInForeground) return false
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
                    )

                MotionEvent.ACTION_BUTTON_RELEASE ->
                    ClientPointerInput(
                        ClientPointerAction.BUTTON_RELEASE,
                        point.x,
                        point.y,
                        buttonState = event.buttonState,
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
                ClientInputDispatchResult.SENT -> return true
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
                showError("Please enter a host address")
                return@setOnClickListener
            }

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

        setupInternetUi()

        // Advanced settings toggle
        binding.showAdvanced.setOnClickListener {
            connectionDetailsVisible = !connectionDetailsVisible
            val visibility = if (connectionDetailsVisible) View.VISIBLE else View.GONE
            binding.checklistContainer.visibility = visibility
            binding.advancedSettings.visibility = visibility
            binding.showAdvanced.setText(
                if (connectionDetailsVisible) {
                    R.string.hide_connection_details
                } else {
                    R.string.connection_details
                },
            )
            if (connectionDetailsVisible) {
                updateChecklist()
            }
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
            android.app.AlertDialog
                .Builder(this)
                .setTitle("Connection Error")
                .setMessage(message)
                .setPositiveButton("OK", null)
                .show()
        }
    }

    private fun updateStatus(status: String) {
        runOnUiThread {
            binding.statusText.text = status
        }
    }

    private fun updateDisconnectedHeader(mode: ConnectionMode) {
        if (!::binding.isInitialized || isConnected) return
        when (mode) {
            ConnectionMode.USB -> {
                binding.connectionTitle.setText(
                    if (isReconnecting) R.string.reconnecting_short else R.string.waiting_for_mac,
                )
                binding.connectionSubtitle.setText(R.string.usb_waiting_description)
                binding.connectionProgress.visibility = View.VISIBLE
                binding.connectButton.setText(R.string.try_again)
                updateStatus(getString(R.string.looking_for_mac))
            }
            ConnectionMode.WIRELESS -> {
                binding.connectionTitle.setText(R.string.connect_wirelessly)
                binding.connectionSubtitle.setText(R.string.wireless_pair_once)
                binding.connectionProgress.visibility = View.GONE
            }
            ConnectionMode.INTERNET -> {
                binding.connectionTitle.setText(R.string.internet_waiting_title)
                binding.connectionSubtitle.setText(R.string.internet_waiting_description)
                binding.connectionProgress.visibility = View.GONE
                refreshInternetProfileUi()
            }
        }
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
                cameraPerm.isPermanentlyDenied() -> cameraPerm.openAppSettings()
                else -> cameraPerm.request(REQ_INTERNET_CAMERA)
            }
        }
        binding.internetConnectButton.setOnClickListener { connectInternet() }
        binding.internetDisconnectButton.setOnClickListener { disconnectInternet(showIdle = true) }
        binding.internetRevokeButton.setOnClickListener {
            android.app.AlertDialog
                .Builder(this)
                .setTitle(R.string.internet_revoke_confirm_title)
                .setMessage(R.string.internet_revoke_confirm_message)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.internet_revoke_confirm_action) { _, _ ->
                    revokeInternetPairing("user_requested")
                }.show()
        }
        val pendingCleanup = retryPendingInternetRevocationCleanup()
        if (pendingCleanup.isNotEmpty()) {
            binding.internetErrorText.text = getString(R.string.internet_revoke_partial_failure, pendingCleanup.joinToString())
            binding.internetErrorText.visibility = View.VISIBLE
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
        val input =
            EditText(this).apply {
                hint = getString(R.string.internet_import_hint)
                minLines = 8
                maxLines = 16
                setHorizontallyScrolling(false)
                inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
                imeOptions =
                    android.view.inputmethod.EditorInfo.IME_FLAG_NO_EXTRACT_UI or
                    android.view.inputmethod.EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
                importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
                isSaveEnabled = false
            }
        val dialog =
            android.app.AlertDialog
                .Builder(this)
                .setTitle(R.string.internet_import_title)
                .setView(input)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.internet_import_action, null)
                .create()
        dialog.setOnShowListener {
            dialog.window?.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
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
                    binding.internetErrorText.visibility = View.GONE
                    binding.internetStateText.setText(R.string.internet_profile_imported)
                    refreshInternetProfileUi()
                    dialog.dismiss()
                } catch (failure: Throwable) {
                    input.error = failure.message ?: getString(R.string.internet_error_title)
                }
            }
        }
        dialog.show()
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
        val container =
            android.widget.LinearLayout(this).apply {
                orientation = android.widget.LinearLayout.VERTICAL
                setPadding(32, 12, 32, 0)
            }
        val request =
            TextView(this).apply {
                text = pending.request.encode()
                setTextIsSelectable(true)
                maxLines = 6
            }
        val identities =
            TextView(this).apply {
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
            EditText(this).apply {
                hint = getString(R.string.internet_pairing_acceptance_hint)
                minLines = 5
                inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
                imeOptions =
                    android.view.inputmethod.EditorInfo.IME_FLAG_NO_EXTRACT_UI or
                    android.view.inputmethod.EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
                importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
                isSaveEnabled = false
            }
        container.addView(identities)
        container.addView(request)
        container.addView(acceptance)
        val dialog =
            android.app.AlertDialog
                .Builder(this)
                .setTitle(R.string.internet_pairing_complete_title)
                .setMessage(R.string.internet_pairing_complete_message)
                .setView(container)
                .setNegativeButton(R.string.cancel) { _, _ ->
                    runCatching { discardPendingInternetPairing(pending) }.onFailure(::showInternetFailure)
                }
                .setPositiveButton(R.string.internet_pairing_complete_action, null)
                .create()
        dialog.setOnShowListener {
            dialog.window?.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
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
                    binding.internetStateText.setText(R.string.internet_pairing_complete)
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
        dialog.show()
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
        binding.internetProfileSummary.text =
            if (profile == null) {
                if (fingerprint == null) {
                    getString(R.string.internet_profile_missing)
                } else {
                    getString(R.string.internet_paired_without_lease, fingerprint)
                }
            } else {
                getString(
                    R.string.internet_profile_format,
                    profile.signalingUrl,
                    profile.signalingSessionId,
                    profile.authoritativeSessionEpoch,
                    fingerprint ?: getString(R.string.empty_value),
                )
            }
        binding.internetConnectButton.isEnabled =
            profile != null &&
                profile.authoritativeSessionEpoch > requiredFreshInternetEpoch &&
                internetSession == null
        binding.internetRevokeButton.isEnabled = profile != null || internetProfileStore.hasVerifiedPairing()
        allowInternetCredentialMutation()
    }

    private fun showConnectedStreamUi() {
        connectionDetailsVisible = false
        binding.checklistContainer.visibility = View.GONE
        binding.advancedSettings.visibility = View.GONE
        binding.showAdvanced.setText(R.string.connection_details)
        binding.videoViewport.visibility = View.VISIBLE
        binding.disconnectedBackdrop.visibility = View.GONE
        binding.settingsPanel.visibility = View.GONE
        // Route settings through the tap-to-reveal control bar instead of a
        // persistent floating button that occludes the video.
        binding.settingsButton.visibility = View.GONE
        updateOverlayVisibility(prefs.showStatsOverlay)
        revealControlBar()
    }

    private fun showDisconnectedStreamUi() {
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
        binding.settingsButton.visibility = View.GONE
        binding.statusBar.visibility = View.GONE
        binding.connectButton.isEnabled = true
        binding.statusIndicator.setBackgroundResource(R.drawable.status_indicator_waiting)
        hideControlBar()
        updateDisconnectedHeader(prefs.connectionMode)
    }

    /** Wires the tap-to-reveal control bar (display capsule, settings, disconnect). */
    private fun setupControlBar() {
        binding.controlSettingsButton.setOnClickListener {
            showSettingsDialog()
            revealControlBar()
        }
        binding.controlDisconnectButton.setOnClickListener { confirmDisconnect() }
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
    }

    /**
     * Disconnect is destructive and sits on the same compact bar as the other
     * controls, so confirm before tearing the session down. Keeping the bar
     * revealed while the dialog is up avoids it auto-hiding under the prompt.
     */
    private fun confirmDisconnect() {
        revealControlBar()
        android.app.AlertDialog
            .Builder(this)
            .setTitle(R.string.disconnect_confirm_title)
            .setMessage(R.string.disconnect_confirm_message)
            .setPositiveButton(R.string.disconnect_confirm_action) { _, _ -> disconnect() }
            .setNegativeButton(R.string.disconnect_confirm_cancel, null)
            .show()
    }

    private fun revealControlBar() {
        if (!isConnected) return
        binding.controlBar.visibility = View.VISIBLE
        binding.controlBar.animate().alpha(1f).setDuration(120).start()
        controlBarHandler.removeCallbacks(controlBarHideRunnable)
        controlBarHandler.postDelayed(controlBarHideRunnable, CONTROL_BAR_AUTO_HIDE_MS)
    }

    private fun hideControlBar() {
        controlBarHandler.removeCallbacks(controlBarHideRunnable)
        binding.controlBar.visibility = View.GONE
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
        val selectable =
            DisplayCapsulePolicy.isSelectable(
                currentSessionBinding().capabilities.displaySelection,
                displays,
            )
        // Collapse the whole display picker on single-display or un-negotiated
        // sessions so the resting capsule stays a minimal, low-misfire target.
        binding.displayCapsuleGroup.visibility = if (selectable) View.VISIBLE else View.GONE
        binding.displayCapsuleGroup.isEnabled = selectable
        if (selectable) {
            refreshDisplayCapsuleLabel()
        }
    }

    /**
     * Reflect the active display on the capsule so touch users can see which
     * Mac display they are on before opening the dropdown. The name is
     * truncated to keep the compact, centered capsule from overflowing.
     */
    private fun refreshDisplayCapsuleLabel() {
        val label =
            DisplayCapsulePolicy.capsuleLabel(
                availableDisplays,
                selectedDisplayId,
                DISPLAY_CAPSULE_MAX_NAME_LENGTH,
            )
        val shown = label.ifEmpty { getString(R.string.display_capsule_placeholder) }
        binding.controlDisplaysLabel.text = shown
        binding.displayCapsuleGroup.contentDescription =
            getString(R.string.control_displays_current, shown)
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
        val popup = PopupMenu(this, binding.controlDisplaysButton)
        val menu = popup.menu
        menu.setGroupCheckable(0, true, true)
        displays.forEachIndexed { index, option ->
            val kindTag =
                if (option.isVirtual) {
                    getString(R.string.display_option_virtual)
                } else {
                    getString(R.string.display_option_builtin)
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
        popup.show()
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

                        // Get screen bounds
                        val parent = view.parent as View
                        val maxX = parent.width - view.width.toFloat()
                        val maxY = parent.height - view.height.toFloat()

                        // Constrain to screen bounds
                        newX = newX.coerceIn(0f, maxX)
                        newY = newY.coerceIn(0f, maxY)

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
            binding.statusBar.post {
                binding.statusBar.x = x
                binding.statusBar.y = y
            }
        }

        // Apply opacity to both overlay and settings button
        val opacity = prefs.overlayOpacity
        updateOverlayOpacity(opacity)
        updateSettingsButtonOpacity(opacity)

        // Apply visibility
        updateOverlayVisibility(prefs.showStatsOverlay)
    }

    private fun updateOverlayOpacity(opacity: Float) {
        binding.statusBar.alpha = opacity
    }

    private fun updateOverlayVisibility(show: Boolean) {
        if (streamClient != null && show) {
            binding.statusBar.visibility = View.VISIBLE
            // Restore position when showing
            val x = prefs.overlayX
            val y = prefs.overlayY
            if (x >= 0 && y >= 0) {
                binding.statusBar.post {
                    binding.statusBar.x = x
                    binding.statusBar.y = y
                }
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

        qualityGroup.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (!isChecked) return@addOnButtonCheckedListener
            val choice =
                qualityButtons.entries.firstOrNull { it.value.id == checkedId }?.key
                    ?: return@addOnButtonCheckedListener
            prefs.videoQuality = choice
            if (choice == VideoQualityChoice.AUTO) return@addOnButtonCheckedListener
            // A preset carries no explicit bitrate, so the host maps the preset.
            streamClient?.setVideoPreferences(
                bitrateKbps = 0,
                framesPerSecond = 0,
                qualityPreset = choice.preset,
            )
        }

        frameRateGroup.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (!isChecked) return@addOnButtonCheckedListener
            val fps =
                frameRateButtons.entries.firstOrNull { it.value.id == checkedId }?.key
                    ?: return@addOnButtonCheckedListener
            prefs.videoFrameRate = fps
            streamClient?.setVideoPreferences(
                bitrateKbps = 0,
                framesPerSecond = fps,
                qualityPreset = dev.vibescreen.protocol.v1.VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
            )
        }

        bitrateSlider.addOnChangeListener { _, value, _ ->
            renderBitrate(value.toInt())
        }
        bitrateSlider.addOnSliderTouchListener(
            object : Slider.OnSliderTouchListener {
                override fun onStartTrackingTouch(slider: Slider) = Unit

                override fun onStopTrackingTouch(slider: Slider) {
                    val mbps = slider.value.toInt()
                    prefs.videoBitrateMbps = mbps
                    // An explicit bitrate wins over the preset intent.
                    streamClient?.setVideoPreferences(
                        bitrateKbps = mbps * KBPS_PER_MBPS,
                        framesPerSecond = 0,
                        qualityPreset = dev.vibescreen.protocol.v1.VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
                    )
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
            val buttons =
                listOf(
                    cornerBottomRight,
                    cornerBottomLeft,
                    cornerTopRight,
                    cornerTopLeft,
                    positionTopCenter,
                    positionBottomCenter,
                    positionCenterLeft,
                    positionCenterRight,
                )
            buttons.forEachIndexed { index, button ->
                if (index == selectedPosition) {
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
            updateSettingsButtonOpacity(value)
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
                val parent = overlay.parent as View
                val margin = resources.displayMetrics.density * OVERLAY_RESET_MARGIN_DP
                val targetX = margin
                val targetY = parent.height - overlay.height - margin
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

        dialog.show()

        // Cap dialog height to 85% of screen so content scrolls on smaller screens / landscape
        dialog.window?.let { win ->
            val maxH = (resources.displayMetrics.heightPixels * 0.85).toInt()
            win.setLayout(WindowManager.LayoutParams.MATCH_PARENT, maxH)
        }
    }

    private fun updateSettingsButtonOpacity(opacity: Float) {
        binding.settingsButton.alpha = opacity
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
        val marginDp = (24 * resources.displayMetrics.density).toInt()

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
                    marginDp,
                )
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, marginDp)
            }

            1 -> { // Bottom Left
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.BOTTOM,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.BOTTOM,
                    marginDp,
                )
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.START,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.START,
                    marginDp,
                )
            }

            2 -> { // Top Right
                constraintSet.connect(buttonId, ConstraintSet.TOP, ConstraintSet.PARENT_ID, ConstraintSet.TOP, marginDp)
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, marginDp)
            }

            3 -> { // Top Left
                constraintSet.connect(buttonId, ConstraintSet.TOP, ConstraintSet.PARENT_ID, ConstraintSet.TOP, marginDp)
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.START,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.START,
                    marginDp,
                )
            }

            4 -> { // Top Center
                constraintSet.connect(buttonId, ConstraintSet.TOP, ConstraintSet.PARENT_ID, ConstraintSet.TOP, marginDp)
                constraintSet.connect(buttonId, ConstraintSet.START, ConstraintSet.PARENT_ID, ConstraintSet.START, 0)
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, 0)
            }

            5 -> { // Bottom Center
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.BOTTOM,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.BOTTOM,
                    marginDp,
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
                    marginDp,
                )
            }

            7 -> { // Center Right
                constraintSet.connect(buttonId, ConstraintSet.TOP, ConstraintSet.PARENT_ID, ConstraintSet.TOP, 0)
                constraintSet.connect(buttonId, ConstraintSet.BOTTOM, ConstraintSet.PARENT_ID, ConstraintSet.BOTTOM, 0)
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, marginDp)
            }

            else -> { // Default to bottom right
                constraintSet.connect(
                    buttonId,
                    ConstraintSet.BOTTOM,
                    ConstraintSet.PARENT_ID,
                    ConstraintSet.BOTTOM,
                    marginDp,
                )
                constraintSet.connect(buttonId, ConstraintSet.END, ConstraintSet.PARENT_ID, ConstraintSet.END, marginDp)
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
        if (!CodecCapabilities.hasHevcDecoder && streamClient?.codecNegotiated != true) {
            mainDiag("AVC-only device but Mac did not negotiate codec — Mac app too old")
            runOnUiThread {
                updateStatus("This device has no HEVC decoder. Update the Telemachus Mac app to enable H.264 support.")
            }
        }
    }

    private fun activateSession(client: StreamClient): Long {
        mainSessionDisplayLifecycle?.invalidate()
        mainSessionDisplayLifecycle = null
        val generation = sessionState.activate(client)
        streamClient = client
        activeSessionGeneration = generation
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
                        surface = surface,
                        displayObj = displayObj,
                        width = width,
                        height = height,
                        mime = mime,
                        scaleMode = scaleMode,
                        ownerClient = ownerClient,
                        ownerGeneration = ownerGeneration,
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
        surface: android.view.Surface,
        displayObj: android.view.Display?,
        width: Int,
        height: Int,
        mime: String,
        scaleMode: VideoScaleMode,
        ownerClient: StreamClient,
        ownerGeneration: Long,
    ): VideoDecoder {
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
                        ActiveDecoderCallbackBinding(identity, ownerGeneration) { activeIdentity, generation ->
                            isCurrentSession(ownerClient, generation) && videoDecoder === activeIdentity
                        }
                    runOnUiThread {
                        callbackBinding.runIfActive {
                            ownerClient.requestKeyframe(force = force, reason = reason)
                        }
                    }
                },
                onCodecFallbackRequired = { identity, reason ->
                    val callbackBinding =
                        ActiveDecoderCallbackBinding(identity, ownerGeneration) { activeIdentity, generation ->
                            isCurrentSession(ownerClient, generation) && videoDecoder === activeIdentity
                        }
                    runOnUiThread {
                        callbackBinding.runIfActive {
                            ownerClient.failCurrentSession(reason)
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
            if (failSession && CodecCapabilities.shouldAdvertiseAvcOnly) {
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
                    updateStatus(getString(R.string.connected_streaming))
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
                "session ended kind=${failure.kind} retryable=${failure.retryable} " +
                    "detail=${failure.detail}",
            )
            if (showTerminalGuidance) {
                val guidance = ConnectionGuidanceFactory.from(failure, currentUsbPort())
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
                if (connected && !isInForeground) {
                    window.addFlags(secureFlagIfProtected())
                    window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                } else {
                    setStreamingWindowState(connected)
                }
                if (connected) {
                    if (prefs.connectionMode == ConnectionMode.USB) automaticUsbConnect = true
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
                    applyDisconnectedSessionUi()
                }
            }
        }

        callbackClient.onServerShutdown = serverShutdown@{
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@serverShutdown
            retryCoordinator.onServerShutdown()
        }

        callbackClient.onVideoConfiguration = displayLifecycle::onVideoConfiguration
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
                if (displaySelection || keyboard || nativePointer) {
                    val capabilities =
                        ClientSessionCapabilities.LEGACY_TOUCH_ONLY.copy(
                            displaySelection = displaySelection,
                            keyboard = keyboard,
                            nativePointer = nativePointer,
                        )
                    val sink =
                        if (keyboard || nativePointer) {
                            StreamClientInputSink(callbackClient, callbackGeneration)
                        } else {
                            null
                        }
                    applyNegotiatedSession(
                        callbackClient,
                        callbackGeneration,
                        ClientSessionBinding(capabilities, sink),
                    )
                    mainDiag(
                        "session binding promoted: displaySelection=$displaySelection " +
                            "keyboard=$keyboard nativePointer=$nativePointer",
                    )
                }
                populateDisplayCapsule(options, selectedId)
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
                    buildSet {
                        add(ProductVideoCodec.H264)
                        if (CodecCapabilities.hasHevcDecoder) add(ProductVideoCodec.HEVC)
                    },
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

                override fun onFreshSessionRequired(reason: String) {
                    if (!isCurrentInternetSession()) return
                    android.util.Log.i(INTERNET_LOG_TAG, "internet_fresh_session_required session_epoch=${lease.authoritativeSessionEpoch}")
                    runOnUiThread {
                        if (!isCurrentInternetSession()) return@runOnUiThread
                        requiredFreshInternetEpoch = internetSessionEpoch
                        disconnectInternet(showIdle = false)
                        binding.internetErrorText.text = getString(R.string.internet_fresh_session_required, reason)
                        binding.internetErrorText.visibility = View.VISIBLE
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
            binding.internetErrorText.visibility = View.GONE
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
                    if (!CodecCapabilities.hasHevcDecoder) return ProductVideoDecision.reject("hevc_decoder_unavailable")
                    MediaFormat.MIMETYPE_VIDEO_HEVC
                }
                ProductVideoCodec.AV1 -> return ProductVideoDecision.reject("av1_decoder_unavailable")
            }
        val holder = currentSurfaceHolder
        if (holder == null || !holder.surface.isValid) return ProductVideoDecision.reject("surface_unavailable")
        val surface = holder.surface
        val expectedSurfaceGeneration = surfaceGeneration.get()
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
                            ActiveDecoderCallbackBinding(identity, generation) { activeIdentity, sessionGeneration ->
                                sessionGeneration == internetGeneration &&
                                    internetSession === sessionReference.get() &&
                                    videoDecoder === activeIdentity
                            }
                        runOnUiThread {
                            callbackBinding.runIfActive { sessionReference.get()?.requestKeyframe(reason) }
                        }
                    },
                    onCodecFallbackRequired = { identity, reason ->
                        val callbackBinding =
                            ActiveDecoderCallbackBinding(identity, generation) { activeIdentity, sessionGeneration ->
                                sessionGeneration == internetGeneration &&
                                    internetSession === sessionReference.get() &&
                                    videoDecoder === activeIdentity
                            }
                        runOnUiThread {
                            callbackBinding.runIfActive {
                                showInternetFailure(IllegalStateException("Decoder failed: $reason"))
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
                                        binding.statusText.text = getString(R.string.connected_streaming)
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
                            ProductVideoDecision.reject(startupResult.reason)
                    }
                }
            candidate?.release()
            decision
        } catch (failure: Throwable) {
            candidate?.let { failedCandidate ->
                if (videoDecoder === failedCandidate) videoDecoder = null
                failedCandidate.release()
            }
            if (isCurrent()) showInternetFailure(failure)
            ProductVideoDecision.reject("decoder_configuration_failure")
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
            binding.statusText.text = getString(R.string.connected_streaming)
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
        binding.internetStateText.text = getString(R.string.internet_state_format, state.name.lowercase(), routeLabel)
        if (state == InternetProductSessionState.CLOSED || state == InternetProductSessionState.FAILED) {
            isConnected = false
            setStreamingWindowState(false)
        }
    }

    private fun showInternetFailure(failure: Throwable) {
        if (!::binding.isInitialized) return
        if (internetSession != null) {
            requiredFreshInternetEpoch = maxOf(requiredFreshInternetEpoch, internetSessionEpoch)
            disconnectInternet(showIdle = false)
        }
        binding.internetErrorText.text = failure.message ?: failure.javaClass.simpleName
        binding.internetErrorText.visibility = View.VISIBLE
        binding.internetStateText.text = getString(
            R.string.internet_state_format,
            InternetProductSessionState.FAILED.name.lowercase(),
            getString(R.string.internet_route_pending),
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
        activeInternetInputIds.clear()
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
                    binding.internetStateText.setText(R.string.internet_state_idle)
                    binding.internetErrorText.visibility = View.GONE
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
            binding.internetErrorText.setText(R.string.internet_revocation_quarantine)
            binding.internetErrorText.visibility = View.VISIBLE
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
        binding.internetErrorText.text = getString(R.string.internet_revoked, reason)
        binding.internetErrorText.visibility = View.VISIBLE
        binding.internetStateText.setText(R.string.internet_profile_revoked)
        if (cleanupFailures.isNotEmpty()) {
            binding.internetErrorText.text = getString(R.string.internet_revoke_partial_failure, cleanupFailures.joinToString())
        }
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
        val callbackClient = StreamClient(host, port, applicationContext)
        val callbackGeneration = activateSession(callbackClient)
        val retryCoordinator =
            createSessionAutomaticRetryCoordinator(callbackClient, callbackGeneration) {
                val delayMs =
                    pendingWirelessReconnectDelayMs
                        ?: initialWirelessReconnectBackoff.nextDelayMs(jitterUnit = 0.5)
                pendingWirelessReconnectDelayMs = null
                scheduleWirelessReconnect(delayMs)
            }
        setupStreamClientCallbacks(callbackClient, callbackGeneration, retryCoordinator)
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
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        cancelWirelessReconnect()
        stopPingTimer()
        val client = streamClient
        val generation = activeSessionGeneration
        client?.disconnect()
        if (client != null) sessionState.invalidate(client, generation)
        if (streamClient === client) streamClient = null
        disconnectInternet(showIdle = false)
        connectionAttemptInProgress = false
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
        val callbackClient = StreamClient(host, port, applicationContext)
        val callbackGeneration = activateSession(callbackClient)
        val retryCoordinator =
            createSessionAutomaticRetryCoordinator(callbackClient, callbackGeneration) {
                showDisconnectedStreamUi()
                scheduleAutomaticUsbConnect()
            }
        setupStreamClientCallbacks(callbackClient, callbackGeneration, retryCoordinator)
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                log("Connecting to $host:$port...")
                callbackClient.connect()
            } catch (e: Exception) {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@launch
                val guidance = ConnectionGuidanceFactory.from(e, port)
                if (!automatic && e !is SessionProtocolException) {
                    updateStatus(guidance.status)
                    showError(guidance.message)
                }
            } finally {
                runOnUiThread {
                    if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                    connectionAttemptInProgress = false
                    retryCoordinator.onConnectionFinally(
                        automaticRetryEnabled = automaticUsbConnect,
                        disconnected = !isConnected,
                    )
                }
            }
        }
    }

    private fun disconnect() {
        finishPendingRightClick()
        if (prefs.connectionMode == ConnectionMode.INTERNET || internetSession != null) {
            disconnectInternet(showIdle = true)
            return
        }
        automaticUsbConnect = false
        cancelWirelessReconnect()
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        stopPingTimer()
        isReconnecting = false
        hasConnectedThisRun = false
        val client = streamClient
        val generation = activeSessionGeneration
        client?.disconnect()
        if (client != null) sessionState.invalidate(client, generation)
        if (streamClient === client) streamClient = null
        connectionAttemptInProgress = false
        applyDisconnectedSessionUi()
        log("Disconnected")
    }

    private fun applyDisconnectedSessionUi() {
        isConnected = false
        mainSessionDisplayLifecycle?.invalidate()
        mainSessionDisplayLifecycle = null
        encodedVideoConfigurationState.clear()
        activeDecoderConfigEpoch = 0L
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
            updateStatus(guidance.status)
            showError(guidance.message)
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
        if (prefs.connectionMode == ConnectionMode.INTERNET) {
            handleInternetTouch(view, event)
            return
        }
        if (!isConnected || !isInForeground) return
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
            return client.sendKey(
                usbHidUsage = input.usbHidUsage,
                pressed = input.pressed,
                modifierMask = NativeInputWire.modifierMask(input.modifiers),
            )
        }

        override fun sendPointer(input: ClientPointerInput): Boolean {
            if (!isCurrentSession(client, generation)) return false
            return when (input.action) {
                ClientPointerAction.SCROLL ->
                    client.sendScroll(
                        deltaX = input.horizontalScroll.toDouble(),
                        deltaY = input.verticalScroll.toDouble(),
                    )

                ClientPointerAction.MOVE ->
                    client.sendPointer(
                        phase = InputPhase.INPUT_PHASE_CHANGED,
                        x = input.x,
                        y = input.y,
                        buttonMask = NativeInputWire.buttonMask(input.buttonState),
                    )

                ClientPointerAction.BUTTON_PRESS ->
                    client.sendPointer(
                        phase = InputPhase.INPUT_PHASE_BEGAN,
                        x = input.x,
                        y = input.y,
                        buttonMask = NativeInputWire.buttonMask(input.buttonState),
                    )

                ClientPointerAction.BUTTON_RELEASE ->
                    client.sendPointer(
                        phase = InputPhase.INPUT_PHASE_ENDED,
                        x = input.x,
                        y = input.y,
                        buttonMask = NativeInputWire.buttonMask(input.buttonState),
                    )
            }
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

        fun send(index: Int, phase: ProductInputPhase) {
            val pointerId = event.getPointerId(index)
            val inputId =
                when (phase) {
                    ProductInputPhase.BEGAN -> nextInternetInputId.incrementAndGet().also { activeInternetInputIds[pointerId] = it }
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

        // The host already reports upright encoded dimensions. Rotate only by
        // the explicit client-local offset; host rotation still selects the
        // Activity orientation above.
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
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)
        stopChecklistUpdates()
        runCatching(::discardPendingInternetPairing).onFailure { failure ->
            android.util.Log.e(INTERNET_LOG_TAG, "Could not delete pending pairing identity", failure)
        }
        cleanup()
        super.onDestroy()
    }

    companion object {
        private const val EXTRA_AUTO_CONNECT = "auto_connect"
        private const val KBPS_PER_MBPS = 1_000
        private const val OVERLAY_RESET_MARGIN_DP = 16f
        private const val STATE_AUTOMATIC_USB_CONNECT = "automatic_usb_connect"
        private const val ACTION_USB_STATE = "android.hardware.usb.action.USB_STATE"
        private const val EXTRA_USB_CONNECTED = "connected"
        private const val EXTRA_USB_CONFIGURED = "configured"
        private const val EXTRA_USB_FUNCTION_ADB = "adb"
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
        private const val FOREGROUND_RECONNECT_DELAY_MS = 150L
        private const val CONTROL_BAR_AUTO_HIDE_MS = 3_000L
        // Truncation budget for the display name shown on the capsule selector.
        // Keeps long host display names from overflowing the compact capsule;
        // the label view also ellipsizes as a visual backstop.
        private const val DISPLAY_CAPSULE_MAX_NAME_LENGTH = 18
        private val DECODER_LIFECYCLE_EXECUTOR =
            Executors.newSingleThreadExecutor { runnable ->
                Thread(runnable, "VibeDecoderLifecycle").apply { isDaemon = true }
            }
        private const val REQ_INTERNET_SCAN = 1101
        private const val REQ_INTERNET_CAMERA = 1102
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
        if (isConnected || !connectionDetailsVisible) return

        // These values live in Settings.Global. Querying Settings.Secure with
        // Global keys returns false negatives on several Android versions.
        val isDeveloperModeEnabled =
            Settings.Global.getInt(
                contentResolver,
                Settings.Global.DEVELOPMENT_SETTINGS_ENABLED,
                0,
            ) == 1
        updateChecklistItem(binding.checkDeveloperMode, isDeveloperModeEnabled)

        // Check USB Debugging (ADB enabled)
        val isAdbEnabled =
            Settings.Global.getInt(
                contentResolver,
                Settings.Global.ADB_ENABLED,
                0,
            ) == 1
        updateChecklistItem(binding.checkUsbDebugging, isAdbEnabled)

        // Charging alone also succeeds with charge-only cables. The sticky USB
        // state broadcast tells us whether Android configured a real data link
        // and exposed the ADB USB function.
        val isUsbConnected = isUsbDataConnectionActive()
        updateChecklistItem(binding.checkUsbConnected, isUsbConnected)

        if (automaticUsbConnect || connectionAttemptInProgress) {
            updateChecklistItem(binding.checkMacServer, false)
            updateMainStatus(false)
            return
        }

        // Check Mac Server (try to connect to port)
        lifecycleScope.launch(Dispatchers.IO) {
            // Double-check connection state before socket test
            if (isConnected) return@launch

            val port =
                binding.portInput.text
                    .toString()
                    .toIntOrNull() ?: 54321
            val isServerRunning = checkServerRunning("127.0.0.1", port)
            runOnUiThread {
                // Final check before updating UI
                if (isConnected) return@runOnUiThread

                updateChecklistItem(binding.checkMacServer, isServerRunning)

                // Update main status indicator based on all checklist items
                val allReady = isDeveloperModeEnabled && isAdbEnabled && isUsbConnected && isServerRunning
                updateMainStatus(allReady)
            }
        }
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
            binding.statusText.text =
                if (allReady) "Ready to connect" else "Check the connection details below"
        }
    }

    private fun updateChecklistItem(
        indicator: View,
        isOk: Boolean,
    ) {
        indicator.setBackgroundResource(
            if (isOk) {
                R.drawable.status_indicator_green
            } else {
                R.drawable.status_indicator_red
            },
        )
    }

    private fun isUsbDataConnectionActive(): Boolean {
        val usbState = registerReceiver(null, IntentFilter(ACTION_USB_STATE)) ?: return false
        return usbState.getBooleanExtra(EXTRA_USB_CONNECTED, false) &&
            usbState.getBooleanExtra(EXTRA_USB_CONFIGURED, false) &&
            usbState.getBooleanExtra(EXTRA_USB_FUNCTION_ADB, false)
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
