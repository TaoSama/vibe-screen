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
import androidx.appcompat.app.AppCompatActivity
import androidx.constraintlayout.widget.ConstraintSet
import androidx.lifecycle.lifecycleScope
import com.google.android.material.button.MaterialButton
import com.google.android.material.slider.Slider
import com.google.android.material.switchmaterial.SwitchMaterial
import dev.telemachus.display.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

private fun mainDiag(msg: String) = DiagLog.log("MA", msg)

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
    private var streamClient: StreamClient? = null
    private var currentSurfaceHolder: SurfaceHolder? = null
    private var displayWidth = 0 // 0 = no config received yet
    private var displayHeight = 0 // 0 = no config received yet
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

        // Apply fullscreen mode immediately
        enableFullscreenMode()

        setupSurface()
        setupUI()
        setupDraggableOverlay()
        setupSettingsButton()
        restoreOverlayPosition()
        restoreSettingsButtonPosition()
        startChecklistUpdates()
        setupModeToggle()
        setupWirelessController()
        if (savedInstanceState?.getBoolean(STATE_AUTOMATIC_USB_CONNECT) == true) {
            enableAutomaticUsbConnect()
        } else {
            handleLaunchIntent(intent)
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

    private fun handleLaunchIntent(intent: Intent?) {
        if (intent?.getBooleanExtra(EXTRA_AUTO_CONNECT, false) != true) return
        // Treat the launch extra as an event. Persisting it on the Activity's
        // Intent would make a deliberate Disconnect resume after recreation.
        intent.removeExtra(EXTRA_AUTO_CONNECT)
        enableAutomaticUsbConnect()
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
    }

    private fun setupModeToggle() {
        // Restore previous mode and reflect in toggle.
        val saved = prefs.connectionMode
        binding.modeToggleGroup.check(if (saved == ConnectionMode.WIRELESS) R.id.modeWireless else R.id.modeUSB)
        applyModeVisibility(saved)

        binding.modeToggleGroup.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (!isChecked) return@addOnButtonCheckedListener
            val mode = if (checkedId == R.id.modeWireless) ConnectionMode.WIRELESS else ConnectionMode.USB
            if (prefs.connectionMode != mode) {
                cancelConnectionForModeSwitch()
            }
            prefs.connectionMode = mode
            applyModeVisibility(mode)
            if (mode == ConnectionMode.WIRELESS) {
                automaticUsbConnect = false
                autoConnectHandler.removeCallbacks(autoConnectRunnable)
                wirelessController.show()
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
        // USB checklist polls 127.0.0.1:port every 2s via adb-reverse to verify Mac
        // server reachability. While in Wireless mode that probe creates loopback
        // connections that fight the wireless session for the Mac's single client
        // slot — kicking the wireless client off seconds after it auths. Pause
        // checklist updates whenever Wireless is the active tab.
        if (mode == ConnectionMode.WIRELESS) {
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
        }
    }

    /** Keep the tablet awake and its streamed Mac pixels out of screenshots only while connected. */
    private fun setStreamingWindowState(enabled: Boolean) {
        val streamingFlags =
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_SECURE
        if (enabled) {
            window.addFlags(streamingFlags)
        } else {
            window.clearFlags(streamingFlags)
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
                    surfaceGeneration.incrementAndGet()
                    currentSurfaceHolder = holder
                    // If we already have a display config (reconnect case), init now
                    if (displayWidth > 0 && displayHeight > 0 && videoDecoder == null) {
                        initializeDecoder(holder)
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
        if (!isConnected || !isInForeground) return false
        val point = mapInputPoint(view, event.x, event.y)
        val nativePointerInput =
            when (event.actionMasked) {
                MotionEvent.ACTION_BUTTON_PRESS ->
                    ClientPointerInput(
                        ClientPointerAction.BUTTON_PRESS,
                        point.x,
                        point.y,
                        buttonState = event.actionButton,
                    )

                MotionEvent.ACTION_BUTTON_RELEASE ->
                    ClientPointerInput(
                        ClientPointerAction.BUTTON_RELEASE,
                        point.x,
                        point.y,
                        buttonState = event.actionButton,
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
        if (mode == ConnectionMode.USB) {
            binding.connectionTitle.setText(R.string.waiting_for_mac)
            binding.connectionSubtitle.setText(R.string.usb_waiting_description)
            binding.connectionProgress.visibility = View.VISIBLE
            binding.connectButton.setText(R.string.try_again)
            updateStatus(getString(R.string.looking_for_mac))
        } else {
            binding.connectionTitle.setText(R.string.connect_wirelessly)
            binding.connectionSubtitle.setText(R.string.wireless_pair_once)
            binding.connectionProgress.visibility = View.GONE
        }
    }

    private fun showConnectedStreamUi() {
        connectionDetailsVisible = false
        binding.checklistContainer.visibility = View.GONE
        binding.advancedSettings.visibility = View.GONE
        binding.showAdvanced.setText(R.string.connection_details)
        binding.videoViewport.visibility = View.VISIBLE
        binding.disconnectedBackdrop.visibility = View.GONE
        binding.settingsPanel.visibility = View.GONE
        binding.settingsButton.visibility = View.VISIBLE
        restoreSettingsButtonPosition()
        updateOverlayVisibility(prefs.showStatsOverlay)
    }

    private fun showDisconnectedStreamUi() {
        // Keep one stable layout while the USB retry loop runs. Showing system
        // bars or changing orientation here resized/recreated the Activity and
        // made the waiting state visibly flash.
        enableFullscreenMode()
        binding.videoViewport.visibility = View.GONE
        binding.disconnectedBackdrop.visibility = View.VISIBLE
        binding.settingsPanel.visibility = View.VISIBLE
        binding.settingsButton.visibility = View.GONE
        binding.statusBar.visibility = View.GONE
        binding.connectButton.isEnabled = true
        binding.statusIndicator.setBackgroundResource(R.drawable.status_indicator_waiting)
        updateDisconnectedHeader(prefs.connectionMode)
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
        val rotationButton = view.findViewById<MaterialButton>(R.id.rotationButton)
        val displayCapability = view.findViewById<TextView>(R.id.displayCapability)

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
            rotationButton.text =
                getString(
                    R.string.rotation_value,
                    when (prefs.clientRotation) {
                        ClientRotation.FOLLOW_HOST -> getString(R.string.rotation_follow_host)
                        ClientRotation.CLOCKWISE_90 -> getString(R.string.rotation_90)
                        ClientRotation.UPSIDE_DOWN -> getString(R.string.rotation_180)
                        ClientRotation.COUNTER_CLOCKWISE_90 -> getString(R.string.rotation_270)
                    },
                )
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
        rotationButton.setOnClickListener {
            prefs.clientRotation =
                when (prefs.clientRotation) {
                    ClientRotation.FOLLOW_HOST -> ClientRotation.CLOCKWISE_90
                    ClientRotation.CLOCKWISE_90 -> ClientRotation.UPSIDE_DOWN
                    ClientRotation.UPSIDE_DOWN -> ClientRotation.COUNTER_CLOCKWISE_90
                    ClientRotation.COUNTER_CLOCKWISE_90 -> ClientRotation.FOLLOW_HOST
                }
            applyRotation(displayRotation)
            updateViewportButtons()
        }

        resetButton.setOnClickListener {
            prefs.overlayX = -1f
            prefs.overlayY = -1f
            // Use displayMetrics for reliable positioning
            val dm = resources.displayMetrics
            binding.statusBar
                .animate()
                .x(dm.widthPixels - binding.statusBar.width - 48f)
                .y(48f)
                .setDuration(300)
                .start()
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

    private fun initializeDecoder(holder: SurfaceHolder) {
        val ownerClient = streamClient ?: return
        val ownerGeneration = activeSessionGeneration
        if (!isCurrentSession(ownerClient, ownerGeneration)) return
        mainDiag(
            "initializeDecoder called, surface=${holder.surface}, " +
                "valid=${holder.surface.isValid}, res=${displayWidth}x$displayHeight",
        )
        if (displayWidth <= 0 || displayHeight <= 0) {
            mainDiag("initializeDecoder skipped — no display config yet")
            return
        }
        val surface = holder.surface
        val expectedSurfaceGeneration = surfaceGeneration.get()
        val expectedConfigurationGeneration = decoderConfigurationGeneration.incrementAndGet()
        val width = displayWidth
        val height = displayHeight
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
                !isCurrentSession(ownerClient, ownerGeneration)
            ) {
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
                    if (surface.isValid &&
                        surfaceGeneration.get() == expectedSurfaceGeneration &&
                        decoderConfigurationGeneration.get() == expectedConfigurationGeneration &&
                        isCurrentSession(ownerClient, ownerGeneration)
                    ) {
                        reportDecoderInitializationFailure(e, ownerClient, ownerGeneration)
                    }
                    return@execute
                }
            if (!surface.isValid ||
                surfaceGeneration.get() != expectedSurfaceGeneration ||
                decoderConfigurationGeneration.get() != expectedConfigurationGeneration ||
                !isCurrentSession(ownerClient, ownerGeneration) ||
                !videoDecoderRef.compareAndSet(null, decoder)
            ) {
                decoder.release()
                return@execute
            }
            if (!surface.isValid ||
                surfaceGeneration.get() != expectedSurfaceGeneration ||
                decoderConfigurationGeneration.get() != expectedConfigurationGeneration ||
                !isCurrentSession(ownerClient, ownerGeneration)
            ) {
                val ownsRelease = videoDecoderRef.compareAndSet(decoder, null)
                if (ownsRelease) decoder.release()
                return@execute
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
        val decoder = VideoDecoder(surface, displayObj, width, height, mime)
        try {
            decoder.updateScaleMode(scaleMode)
            decoder.onFrameDecoded = { buffer -> ownerClient.releaseBuffer(buffer) }
            decoder.onKeyframeRequired = { force, reason ->
                if (isCurrentSession(ownerClient, ownerGeneration) && videoDecoder === decoder) {
                    ownerClient.requestKeyframe(force = force, reason = reason)
                }
            }
            decoder.onCodecFallbackRequired = { reason ->
                if (isCurrentSession(ownerClient, ownerGeneration) && videoDecoder === decoder) {
                    ownerClient.failCurrentSession(reason)
                }
            }
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
    ) {
        mainDiag("Decoder init FAILED: ${error.message}")
        log("❌ Failed to initialize decoder: ${error.message}")
        if (isCurrentSession(ownerClient, ownerGeneration)) {
            updateStatus("Video decoder failed: ${error.message}")
            if (CodecCapabilities.shouldAdvertiseAvcOnly) {
                ownerClient.failCurrentSession("codec_configuration_failure")
            }
        }
    }

    private fun applyVideoScaleMode(mode: VideoScaleMode) {
        prefs.videoScaleMode = mode
        // Invalidate an in-flight constructor, then reconcile on the same
        // serial worker so its publish/post-publish checks finish first.
        decoderConfigurationGeneration.incrementAndGet()
        DECODER_LIFECYCLE_EXECUTOR.execute {
            videoDecoder?.updateScaleMode(mode)
        }
        currentSurfaceHolder
            ?.takeIf { it.surface.isValid && displayWidth > 0 && displayHeight > 0 }
            ?.let(::initializeDecoder)
    }

    private fun releaseVideoDecoderAsync() {
        decoderConfigurationGeneration.incrementAndGet()
        val decoder = videoDecoderRef.getAndSet(null) ?: return
        DECODER_LIFECYCLE_EXECUTOR.execute { decoder.release() }
    }

    /**
     * Wire up all StreamClient callbacks. Used by both USB connect() and wireless connectWireless().
     */
    private fun setupStreamClientCallbacks(
        callbackClient: StreamClient,
        callbackGeneration: Long,
    ) {
        callbackClient.onFrameReceived = frame@{ frameData, frameSize, timestamp, isKeyframe, sessionEpoch ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) {
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
            mainDiag(
                "session ended kind=${failure.kind} retryable=${failure.retryable} " +
                    "detail=${failure.detail}",
            )
            if (!failure.retryable && !failure.intentional) {
                val guidance = ConnectionGuidanceFactory.from(failure, currentUsbPort())
                runOnUiThread {
                    if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                    automaticUsbConnect = false
                    cancelWirelessReconnect()
                    autoConnectHandler.removeCallbacks(autoConnectRunnable)
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
                    window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                    window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                } else {
                    setStreamingWindowState(connected)
                }
                if (connected) {
                    if (prefs.connectionMode == ConnectionMode.USB) automaticUsbConnect = true
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
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                automaticUsbConnect = false
                cancelWirelessReconnect()
                autoConnectHandler.removeCallbacks(autoConnectRunnable)
                log("📴 Server initiated shutdown — closing app")
                finishAffinity()
            }
        }

        callbackClient.onDisplaySize = displaySize@{ width, height, rotation ->
            if (!isCurrentSession(callbackClient, callbackGeneration)) return@displaySize
            mainDiag("onDisplaySize: ${width}x$height @ $rotation°")
            runOnUiThread {
                if (!isCurrentSession(callbackClient, callbackGeneration)) return@runOnUiThread
                warnIfAvcOnlyWithoutNegotiation()
                displayWidth = width
                displayHeight = height
                displayRotation = rotation
                releaseVideoDecoderAsync()
                val holder = currentSurfaceHolder
                if (holder != null && holder.surface.isValid) {
                    mainDiag("Display config arrived, initializing decoder ${width}x$height")
                    initializeDecoder(holder)
                } else {
                    mainDiag("Display config arrived but no valid surface yet")
                }
                updateSurfaceViewportLayout()
                binding.resolutionText.text = getString(R.string.resolution_format, width, height)
                binding.connectButton.isEnabled = false
                binding.disconnectButton.isEnabled = true
                binding.statusIndicator.setBackgroundResource(R.drawable.status_indicator_green)
                updateStatus(getString(R.string.connected_streaming))
                showConnectedStreamUi()
                applyRotation(rotation)
            }
            log("Display: ${width}x$height @ $rotation°")
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
        setupStreamClientCallbacks(callbackClient, callbackGeneration)
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
                    if (!isConnected && wirelessAutoReconnectEnabled) {
                        val delayMs =
                            pendingWirelessReconnectDelayMs
                                ?: initialWirelessReconnectBackoff.nextDelayMs(jitterUnit = 0.5)
                        pendingWirelessReconnectDelayMs = null
                        scheduleWirelessReconnect(delayMs)
                    }
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
        mainDiag("Wireless reconnect scheduled in ${delayMs}ms")
    }

    private fun cancelWirelessReconnect() {
        wirelessAutoReconnectEnabled = false
        pendingWirelessReconnectDelayMs = null
        initialWirelessReconnectBackoff.reset()
        wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)
    }

    private fun cancelConnectionForModeSwitch() {
        automaticUsbConnect = false
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        cancelWirelessReconnect()
        val client = streamClient
        val generation = activeSessionGeneration
        client?.disconnect()
        if (client != null) sessionState.invalidate(client, generation)
        if (streamClient === client) streamClient = null
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
        setupStreamClientCallbacks(callbackClient, callbackGeneration)
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
                    if (automaticUsbConnect && !isConnected) {
                            showDisconnectedStreamUi()
                            scheduleAutomaticUsbConnect()
                    }
                }
            }
        }
    }

    private fun disconnect() {
        finishPendingRightClick()
        automaticUsbConnect = false
        cancelWirelessReconnect()
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        stopPingTimer()
        val client = streamClient
        val generation = activeSessionGeneration
        client?.disconnect()
        if (client != null) sessionState.invalidate(client, generation)
        if (streamClient === client) streamClient = null
        connectionAttemptInProgress = false
        applyDisconnectedSessionUi()
        // Reset display config so next connect defers decoder init until config arrives
        displayWidth = 0
        displayHeight = 0
        log("Disconnected")
    }

    private fun applyDisconnectedSessionUi() {
        isConnected = false
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
        if (!isConnected || !isInForeground) return
        val first = mapInputPoint(view, event.x, event.y)
        val x = first.x
        val y = first.y
        val pointerCount = event.pointerCount.coerceAtMost(2)

        var x2 = 0f
        var y2 = 0f
        if (pointerCount >= 2) {
            val second =
                mapInputPoint(view, event.getX(1), event.getY(1))
            x2 = second.x
            y2 = second.y
        }

        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                inputPredictor.reset()
                inputPredictor.addSample(x, y)
                streamClient?.sendTouch(x, y, 0, pointerCount, x2, y2)
            }

            MotionEvent.ACTION_POINTER_DOWN -> {
                streamClient?.sendTouch(x, y, 0, pointerCount, x2, y2)
            }

            MotionEvent.ACTION_MOVE -> {
                if (pointerCount == 1) {
                    inputPredictor.addSample(x, y)
                    val (px, py) = inputPredictor.predictPosition(12f)
                    streamClient?.sendTouch(px.coerceIn(0f, 1f), py.coerceIn(0f, 1f), 1, 1)
                } else {
                    streamClient?.sendTouch(x, y, 1, pointerCount, x2, y2)
                }
            }

            MotionEvent.ACTION_UP -> {
                inputPredictor.reset()
                streamClient?.sendTouch(x, y, 2, 1)
            }

            MotionEvent.ACTION_POINTER_UP -> {
                streamClient?.sendTouch(x, y, 2, pointerCount, x2, y2)
            }

            MotionEvent.ACTION_CANCEL -> {
                inputPredictor.reset()
                streamClient?.sendTouch(x, y, 2, 1)
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
        super.onDestroy()
        autoConnectHandler.removeCallbacks(autoConnectRunnable)
        wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)
        stopChecklistUpdates()
        cleanup()
    }

    companion object {
        private const val EXTRA_AUTO_CONNECT = "auto_connect"
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
        private const val LEGACY_RIGHT_CLICK_HOLD_MS = 650L
        private const val FOREGROUND_RECONNECT_DELAY_MS = 150L
        private val DECODER_LIFECYCLE_EXECUTOR =
            Executors.newSingleThreadExecutor { runnable ->
                Thread(runnable, "VibeDecoderLifecycle").apply { isDaemon = true }
            }
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
