import Cocoa
import SwiftUI
import Combine
import ApplicationServices
import Security
import os.log
import VibeScreenProtocol
@preconcurrency import ScreenCaptureKit

private enum TelemachusLog {
    static let unified = Logger(
        subsystem: "dev.telemachus.display",
        category: "runtime"
    )
    static let lock = NSLock()
    static let maximumFileSize: UInt64 = 1_048_576

    static func write(_ message: String) {
        // Dynamic details such as device names and addresses remain private in
        // the unified log. The local file is mode 0600 and rotates at 1 MiB.
        unified.debug("\(message, privacy: .private)")
        lock.withLock {
            do {
                let directory = FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Library/Logs/Telemachus", isDirectory: true)
                try FileManager.default.createDirectory(
                    at: directory,
                    withIntermediateDirectories: true,
                    attributes: [.posixPermissions: 0o700]
                )
                let url = directory.appendingPathComponent("telemachus.log")
                let rotatedURL = directory.appendingPathComponent("telemachus.log.1")
                let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
                if size >= maximumFileSize {
                    try? FileManager.default.removeItem(at: rotatedURL)
                    try? FileManager.default.moveItem(at: url, to: rotatedURL)
                }
                let timestamp = TelemetryTimestamp.string(from: Date())
                let data = Data("\(timestamp) \(message)\n".utf8)
                if !FileManager.default.fileExists(atPath: url.path) {
                    FileManager.default.createFile(
                        atPath: url.path,
                        contents: data,
                        attributes: [.posixPermissions: 0o600]
                    )
                } else {
                    let handle = try FileHandle(forWritingTo: url)
                    try handle.seekToEnd()
                    try handle.write(contentsOf: data)
                    try handle.close()
                }
            } catch {
                unified.error("File logging failed: \(error.localizedDescription, privacy: .private)")
            }
        }
    }
}

func debugLog(_ message: String) {
    TelemachusLog.write(message)
}


// MARK: - Gesture State Machine

enum GestureState {
    case idle
    case pending          // Touch down, waiting to determine gesture
    case scrolling        // 1-finger scroll
    case longPressReady   // Long press detected, waiting for drag or release
    case dragging         // Long press + drag (left mouse drag)
    case twoFingerScroll  // 2-finger scroll
    case pinching         // Pinch zoom
}

struct GestureThresholds {
    static let tapMaxDistance: CGFloat = 15
    static let tapMaxTime: UInt64 = 250_000_000       // 250ms
    static let doubleTapMaxTime: UInt64 = 400_000_000  // 400ms
    static let doubleTapMaxDistance: CGFloat = 20
    static let longPressTime: UInt64 = 500_000_000     // 500ms
    static let scrollSensitivity: CGFloat = 1.2
    static let pinchMinDistance: CGFloat = 20
    static let minTouchInterval: UInt64 = 8_000_000    // ~120Hz
}

private enum HostStartOrigin {
    case manual
    case automatic
    case recovery

    var authorizesRecovery: Bool {
        self == .automatic || self == .recovery
    }
}

struct HostSelectedDisplayIdentity: Equatable {
    let id: CGDirectDisplayID
    let persistentUUID: String?

    func replacing(
        id: CGDirectDisplayID,
        persistentUUID: String?
    ) -> HostSelectedDisplayIdentity {
        HostSelectedDisplayIdentity(id: id, persistentUUID: persistentUUID)
    }
}

private struct HostRuntimeConfiguration: Equatable {
    let origin: HostStartOrigin
    let connectionMode: ConnectionMode
    let resolution: String
    let displaySource: DisplaySourceMode
    let selectedDisplay: HostSelectedDisplayIdentity

    init(
        settings: DisplaySettings,
        origin: HostStartOrigin,
        connectionMode: ConnectionMode? = nil,
        resolution: String? = nil,
        displaySource: DisplaySourceMode? = nil
    ) {
        self.origin = origin
        self.connectionMode = connectionMode ?? settings.connectionMode
        self.resolution = resolution ?? settings.resolution
        self.displaySource = displaySource ?? settings.displaySource
        selectedDisplay = HostSelectedDisplayIdentity(
            id: settings.selectedDisplayID,
            persistentUUID: settings.selectedDisplayUUID
        )
    }

    private init(
        origin: HostStartOrigin,
        connectionMode: ConnectionMode,
        resolution: String,
        displaySource: DisplaySourceMode,
        selectedDisplay: HostSelectedDisplayIdentity
    ) {
        self.origin = origin
        self.connectionMode = connectionMode
        self.resolution = resolution
        self.displaySource = displaySource
        self.selectedDisplay = selectedDisplay
    }

    func updating(
        connectionMode: ConnectionMode? = nil,
        resolution: String? = nil,
        displaySource: DisplaySourceMode? = nil
    ) -> HostRuntimeConfiguration {
        HostRuntimeConfiguration(
            origin: origin,
            connectionMode: connectionMode ?? self.connectionMode,
            resolution: resolution ?? self.resolution,
            displaySource: displaySource ?? self.displaySource,
            selectedDisplay: selectedDisplay
        )
    }

    func updatingSelectedDisplay(
        id: CGDirectDisplayID,
        persistentUUID: String?
    ) -> HostRuntimeConfiguration {
        HostRuntimeConfiguration(
            origin: origin,
            connectionMode: connectionMode,
            resolution: resolution,
            displaySource: displaySource,
            selectedDisplay: selectedDisplay.replacing(
                id: id,
                persistentUUID: persistentUUID
            )
        )
    }

    func resolutionSize(rotation: Int) -> (width: Int, height: Int) {
        let parts = resolution.split(separator: "x")
        let baseWidth = Int(parts.first ?? "") ?? 1920
        let baseHeight = Int(parts.dropFirst().first ?? "") ?? 1200
        if rotation == 90 || rotation == 270 {
            return (baseHeight, baseWidth)
        }
        return (baseWidth, baseHeight)
    }
}

@MainActor
class AppDelegate: NSObject, NSApplicationDelegate {
    private static let internetSignalingTokenName = "internet.local.signaling.host-token.v1"
    private static let internetSignalingIssuerTokenName = "internet.local.signaling.issuer-token.v1"
    private static let internetTURNCredentialName = "internet.local.turn.credential.v1"
    private static let internetSessionProfileTTLSeconds: Int64 = 300

    /// Stable synthetic identity for the optional virtual extended display that
    /// is advertised (but not yet captured) so a single-physical-display Mac can
    /// still offer a second selectable display chip. It never collides with a
    /// real CGDirectDisplayID because it is not numeric. Once the virtual
    /// display is actually created its real numeric id is advertised instead.
    static let virtualExtendedDisplaySyntheticID = "telemachus-virtual-extended"
    /// User-facing name for the virtual extended display chip.
    static let virtualExtendedDisplayName = "Vibe Screen Virtual (扩展屏)"
    /// Fallback advertised size for the virtual extended chip when no explicit
    /// resolution is configured. Actual capture uses the configured resolution.
    static let virtualExtendedDefaultWidth = 1920
    static let virtualExtendedDefaultHeight = 1080

    var streamingServer: StreamingServer?
    private var internetProductSession: InternetProductSession?
    private var internetPairingCoordinator: InternetPairingCoordinator?
    private let internetSessionLeaseDeliveryLifecycle = InternetSessionLeaseDeliveryLifecycle()
    typealias InternetSessionLeaseDeliveryProvisioner = (
        URL,
        String,
        InternetSignalingSessionProfileRequest
    ) async throws -> InternetSessionLeaseDeliveryResult
    var createInternetSessionLeaseDelivery: InternetSessionLeaseDeliveryProvisioner = {
        signalingBaseURL,
        issuerToken,
        request in
        try await InternetSessionLeaseProvisioner().createAuthoritativeLeaseDelivery(
            signalingBaseURL: signalingBaseURL,
            issuerToken: issuerToken,
            request: request
        )
    }
    private let revokedInternetIdentityStore = RevokedInternetIdentityStore()
    var screenCapture: ScreenCapture?
    var virtualDisplayManager: VirtualDisplayManager?
    /// The display currently being captured. This may be a Telemachus-created
    /// extension or an existing macOS display such as Screen Sharing Virtual Display.
    private var activeDisplayID: CGDirectDisplayID?
    var settings = DisplaySettings()
    var settingsWindow: SettingsWindowController?
    var statusItem: NSStatusItem?
    /// Injects client-driven native pointer/scroll/keyboard input as CGEvents.
    /// Shares the touch coordinate mapping via StreamInputMapping.
    private let streamInputInjector = StreamInputInjector()
    private lazy var gameControllerRuntime = GameControllerRuntimeAvailability.probe()
    private lazy var sessionGameControllerInput: SessionGameControllerInput? =
        gameControllerRuntime.factory.map {
            SessionGameControllerInput(injector: GameControllerInjector(factory: $0))
        }
    private var internetControllerInputRoute: SessionGameControllerInputRoute?
    /// Owns the status-bar clipboard menu items and the explicit-action
    /// state machine. Created in setupMenuBar; bound to the active server
    /// on client connect and unbound on disconnect/teardown.
    private var clipboardController: ClipboardUIController?
    private var fileTransferController: FileTransferUIController?
    private var primaryButtonOwner = PrimaryButtonOwnerState()
    let pairedDeviceStore = PairedDeviceStore()
    let windowRecoveryManager = WindowRecoveryManager()
    /// Name of the wireless device currently streaming (nil when no wireless client is active).
    /// Used to roll its `lastConnected` timestamp forward every status refresh tick so the UI
    /// shows "just now" while connected and freezes at the disconnect moment afterward.
    private var currentWirelessDevice: String?
    private var cancellables = Set<AnyCancellable>()
    private var isApplyingClientVideoPreferences = false
    private var permissionCheckTimer: Timer?
    private var statusRefreshTimer: Timer?
    private var permissionMonitoringReady = false
    private var unattendedRecoveryTask: Task<Void, Never>?
    private var teardownTask: Task<Void, Never>?
    private var unattendedRecoveryAttempt = 0
    private let serverLifecycle = HostServerLifecycle()
    private let stopOperationCoordinator = HostStopOperationCoordinator()
    private let terminationCoordinator = HostTerminationCoordinator()
    private let stopRecoveryPreservation = StopRecoveryPreservationAccumulator()
    private let stopFollowUpSuppression = StopFollowUpSuppressionAccumulator()
    private var lastSuppressedStopFollowUpGeneration: UInt64?
    private var lastCompletedStopGeneration: UInt64 = 0
    private var activeRuntimeConfiguration: HostRuntimeConfiguration?
    private lazy var reconfigurationCoordinator = HostReconfigurationCoordinator<HostRuntimeConfiguration>(
        debounceNanoseconds: 150_000_000,
        stop: { [weak self] in
            await self?.stopServer(preserveRecoveryState: false, recordsManualStop: false)
        },
        start: { [weak self] configuration, isCurrent in
            guard let self else { return false }
            self.settings.isStarting = true
            let started = await self.startServer(
                origin: configuration.origin,
                configuration: configuration,
                intentIsCurrent: isCurrent
            )
            if !started, isCurrent() {
                self.settings.isStarting = false
            }
            return started
        }
    )
    private lazy var automaticLaunch = AutomaticLaunchCoordinator(
        enabled: settings.autoStartStreamingOnLaunch
    )
    private var usbStatusProbeGeneration: UInt64 = 0
    private var singleInstanceProcessLock: SingleInstanceProcessLock?
    var isDaemonMode = false // Deprecated: keeping variable for ABI compatibility but unused

    func applicationDidFinishLaunching(_ notification: Notification) {
        print("✅ App launched")

        do {
            singleInstanceProcessLock = try SingleInstanceProcessLock.acquireDefault()
        } catch {
            let alert = NSAlert()
            alert.messageText = "Vibe Screen Is Already Running"
            alert.informativeText = error.localizedDescription
            alert.alertStyle = .critical
            alert.runModal()
            NSApp.terminate(nil)
            return
        }

        // Seed permission state synchronously so the first visible window never
        // flashes the onboarding flow for an already-authorized installation.
        settings.hasScreenRecordingPermission = CGPreflightScreenCaptureAccess()
        settings.hasAccessibilityPermission = AXIsProcessTrusted()
        settings.controllerForwardingAvailable = gameControllerRuntime.factory != nil

        // Create menu bar item
        setupMenuBar()

        // Honor the optional menu-bar-only preference before showing windows.
        applyActivationPolicy()

        // Setup settings window
        setupSettingsWindow()

        // Setup settings observers
        setupSettingsObservers()

        // Check permissions
        Task {
            await checkPermissions()
            await MainActor.run {
                permissionMonitoringReady = true
                attemptAutomaticLaunch()
            }
        }

        // Notice grants made after an explicit user action. This polling path
        // only observes permission state; it must never request prompts or open
        // System Settings on its own.
        permissionCheckTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.refreshPermissionState()
            }
        }

        // Periodic status refresh for the per-mode checklist (ADB / WiFi / Listening IP).
        statusRefreshTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.refreshStatusIndicators()
            }
        }
        // Initial refresh so the UI isn't blank for 2 seconds.
        Task { @MainActor in
            refreshStatusIndicators()
        }

        if CommandLine.arguments.contains("--headless-benchmark") {
            debugLog("Headless benchmark mode: settings window suppressed")
        } else if #available(macOS 13.0, *) {
            if DaemonManager.shared.isEnabled && settings.hasCompletedOnboarding {
                print("🚀 Launch at Login is enabled - starting silently in background")
                // Do not show settings window automatically.
                // applicationShouldHandleReopen will show it if the user manually launched the app.
            } else {
                showSettings()
            }
        } else {
            showSettings()
        }

        // Declarative auto-start (no Mac interaction): start the server in the
        // chosen Startup mode if enabled. No blocking permission modal here —
        // it cannot be acted on when the Mac is headless.
        attemptAutomaticLaunch()
        if settings.autoStartStreamingOnLaunch,
           automaticLaunch.state == .pending {
            debugLog("Auto-start deferred until onboarding and Screen Recording are complete")
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            showSettings()
        }
        return true
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        Task { @MainActor in
            refreshPermissionState()
        }
    }

    @MainActor
    private func refreshPermissionState() {
        guard permissionMonitoringReady else { return }

        let hadScreenRecording = settings.hasScreenRecordingPermission
        let hadAccessibility = settings.hasAccessibilityPermission
        let hasScreenRecording = CGPreflightScreenCaptureAccess()
        // Assign the stable published fields only when the value actually
        // changes. These run on a 2-second timer; unconditional writes emit
        // objectWillChange every tick and re-evaluate the settings UI even when
        // nothing changed, which adds needless SwiftUI observation churn.
        settings.setIfChanged(hasScreenRecording, to: \.hasScreenRecordingPermission)
        settings.setIfChanged(AXIsProcessTrusted(), to: \.hasAccessibilityPermission)
        if hadAccessibility && !settings.hasAccessibilityPermission {
            cancelActiveInput(releaseDrag: false)
        }

        guard hasScreenRecording, !hadScreenRecording else { return }
        debugLog("Screen Recording permission became available while app was running")

        attemptAutomaticLaunch()
    }

    private func attemptAutomaticLaunch() {
        let eligible = HostStartupPolicy.shouldAutoStart(
            autoStartEnabled: settings.autoStartStreamingOnLaunch,
            hasScreenRecordingPermission: settings.hasScreenRecordingPermission,
            hasCompletedOnboarding: settings.hasCompletedOnboarding,
            explicitHeadlessBenchmark: isHeadlessBenchmark
        )
        guard automaticLaunch.consumeIfEligible(eligible) else { return }
        settings.connectionMode = settings.startupMode
        requestServerStart(origin: .automatic)
    }

    @MainActor
    private func refreshStatusIndicators() {
        usbStatusProbeGeneration &+= 1
        let probeGeneration = usbStatusProbeGeneration
        settings.setIfChanged(StatusDetector.adbInstalled(), to: \.adbInstalled)
        settings.setIfChanged(StatusDetector.wifiReachable(), to: \.wifiConnected)
        settings.setIfChanged(LANAddressResolver.primaryIPv4(), to: \.listeningAddress)
        settings.setIfChanged(DisplayCatalog.onlineDisplays(), to: \.availableDisplays)
        if let uuid = settings.selectedDisplayUUID,
           let reidentified = settings.availableDisplays.first(where: {
               $0.persistentUUID == uuid
           }), reidentified.id != settings.selectedDisplayID {
            settings.selectedDisplayID = reidentified.id
        }

        // While a wireless client is actively streaming, keep its lastConnected
        // rolling forward so the UI shows "just now". On disconnect, the
        // onClientDisconnected handler clears currentWirelessDevice — from that
        // point lastConnected stays frozen at the disconnect moment, so the
        // "X minutes ago" label counts up correctly.
        if let name = currentWirelessDevice {
            pairedDeviceStore.upsert(name: name, lastConnected: Date())
        }

        guard HostStartupPolicy.shouldProbeUSB(
            connectionMode: settings.connectionMode
        ) else {
            settings.setIfChanged(false, to: \.usbDeviceConnected)
            settings.setIfChanged([], to: \.availableADBDevices)
            settings.setIfChanged(false, to: \.adbReverseConfigured)
            return
        }

        let port = Int(settings.port)
        let selectedSerial = settings.adbDeviceSerial
        Task.detached { [weak self] in
            let devices = StatusDetector.usbDevices()
            let effectiveSerial = ADBDeviceSelectionPolicy.resolveTargetSerial(
                configuredSerial: selectedSerial,
                connectedSerials: devices
            )
            let reverseOK = effectiveSerial.map {
                StatusDetector.adbReverseConfigured(port: port, serial: $0)
            } ?? false
            await MainActor.run { [weak self] in
                guard let self = self else { return }
                guard self.settings.connectionMode == .usb,
                      self.usbStatusProbeGeneration == probeGeneration else {
                    return
                }
                
                let isConnected = effectiveSerial != nil

                self.settings.setIfChanged(isConnected, to: \.usbDeviceConnected)
                self.settings.setIfChanged(devices, to: \.availableADBDevices)
                self.settings.setIfChanged(reverseOK, to: \.adbReverseConfigured)

                // Self-healing USB bridge (level-triggered, not edge-triggered):
                // whenever we are in USB mode with the server running and a
                // device present but adb reverse missing, (re)establish it.
                // Covers replug, adb-server restart, etc. The server lifecycle
                // is NOT tied to device events — it stays up and the tablet
                // reconnects via its own connect button.
                if self.settings.connectionMode == .usb
                    && isConnected
                    && self.settings.isRunning
                    && !reverseOK {
                    debugLog("🔌 USB bridge missing while running — (re)establishing adb reverse")
                    Task { await self.setupADBReverse() }
                }
            }
        }
    }

    @MainActor
    private func handleConnectionModeChange(to mode: ConnectionMode) {
        usbStatusProbeGeneration &+= 1
        debugLog("Connection mode changed to: \(mode.rawValue)")
        guard settings.isRunning || reconfigurationCoordinator.acceptsRuntimeChanges else { return }
        reconfigurationCoordinator.updateIntent {
            $0.updating(connectionMode: mode)
        }
    }

    /// Check permissions on demand (called when settings window opens or manually)
    func refreshPermissions() {
        Task {
            await checkPermissions()
        }
    }

    func setupSettingsObservers() {
        // Observer cho gaming boost changes
        settings.$gamingBoost
            .dropFirst() // Skip initial value
            .sink { [weak self] gamingBoost in
                guard let self else { return }
                self.refreshPendingReconfigurationIntent()
                guard self.settings.isRunning,
                      !self.isApplyingClientVideoPreferences,
                      !self.settings.internetAdaptiveMediaControl.isActive else { return }
                print("🎮 Gaming Boost \(gamingBoost ? "ENABLED" : "DISABLED")")
                self.screenCapture?.updateEncoderSettings(
                    bitrateMbps: self.settings.effectiveBitrate,
                    quality: self.settings.effectiveQuality,
                    gamingBoost: gamingBoost
                )
            }
            .store(in: &cancellables)

        // Observer cho bitrate/quality changes (chỉ khi không gaming boost)
        Publishers.CombineLatest(settings.$bitrate, settings.$quality)
            .dropFirst()
            .sink { [weak self] bitrate, quality in
                guard let self else { return }
                self.refreshPendingReconfigurationIntent()
                guard self.settings.isRunning,
                      !self.settings.gamingBoost,
                      !self.isApplyingClientVideoPreferences,
                      !self.settings.internetAdaptiveMediaControl.isActive else { return }
                print("⚙️ Settings updated: \(bitrate)Mbps, \(quality)")
                self.screenCapture?.updateEncoderSettings(
                    bitrateMbps: bitrate,
                    quality: quality,
                    gamingBoost: false
                )
            }
            .store(in: &cancellables)

        // Observer cho rotation changes - send to connected client immediately
        settings.$rotation
            .dropFirst()
            .sink { [weak self] rotation in
                guard let self else { return }
                self.refreshPendingReconfigurationIntent()
                guard self.settings.isRunning else { return }
                print("🔄 Rotation changed to \(rotation)°")
                self.streamingServer?.updateRotation(rotation)
                guard self.settings.internetStatus == .direct
                    || self.settings.internetStatus == .relay else { return }
                do {
                    try self.internetProductSession?.updateRotation(rotation)
                } catch {
                    self.settings.internetStatus = .failed
                    self.settings.internetErrorMessage = error.localizedDescription
                    self.settings.internetRecoverySuggestion =
                        "Reconnect with a fresh secure session before changing rotation."
                }
            }
            .store(in: &cancellables)

        // Observer cho touch enable/disable - propagate to streaming server so
        // incoming touch frames from the client are dropped early when off.
        settings.$touchEnabled
            .dropFirst()
            .sink { [weak self] enabled in
                self?.refreshPendingReconfigurationIntent()
                self?.streamingServer?.touchEnabled = enabled
                if !enabled {
                    self?.cancelActiveInput(releaseDrag: true)
                }
            }
            .store(in: &cancellables)

        settings.$refreshRate
            .dropFirst()
            .sink { [weak self] _ in
                guard let self,
                      !self.settings.internetAdaptiveMediaControl.isActive else { return }
                self.refreshPendingReconfigurationIntent()
            }
            .store(in: &cancellables)

        for publisher in [
            settings.$hiDPI.map { _ in () }.eraseToAnyPublisher(),
            settings.$port.map { _ in () }.eraseToAnyPublisher(),
            settings.$adbDeviceSerial.map { _ in () }.eraseToAnyPublisher()
        ] {
            publisher
                .dropFirst()
                .sink { [weak self] in
                    self?.refreshPendingReconfigurationIntent()
                }
                .store(in: &cancellables)
        }

        // Observer cho connection mode changes — restart server with new auth/ADB policy.
        settings.$connectionMode
            .dropFirst()
            .removeDuplicates()
            .sink { [weak self] mode in
                self?.handleConnectionModeChange(to: mode)
            }
            .store(in: &cancellables)

        // Observer cho resolution changes — the virtual display is created at
        // server start, so a new resolution (list row or custom Apply) needs a
        // stop/start cycle to take effect, same as a connection-mode change.
        // Without this, changing resolution mid-run silently did nothing.
        settings.$resolution
            .dropFirst()
            .removeDuplicates()
            .sink { [weak self] resolution in
                guard let self = self else { return }
                guard self.settings.isRunning || self.reconfigurationCoordinator.acceptsRuntimeChanges else { return }
                debugLog("Resolution changed to \(resolution) — scheduling capture reconfiguration")
                self.reconfigurationCoordinator.updateIntent {
                    $0.updating(resolution: resolution)
                }
            }
            .store(in: &cancellables)

        settings.$displaySource
            .dropFirst()
            .removeDuplicates()
            .sink { [weak self] source in
                guard let self else { return }
                guard self.settings.isRunning || self.reconfigurationCoordinator.acceptsRuntimeChanges else { return }
                debugLog("Display source changed to \(source.rawValue) — scheduling capture reconfiguration")
                self.reconfigurationCoordinator.updateIntent {
                    $0.updating(displaySource: source)
                }
            }
            .store(in: &cancellables)

        settings.$selectedDisplayID
            .dropFirst()
            .removeDuplicates()
            .sink { [weak self] displayID in
                guard let self,
                      self.settings.isRunning
                        || self.reconfigurationCoordinator.acceptsRuntimeChanges else {
                    return
                }
                self.reconfigurationCoordinator.updateIntent {
                    $0.updatingSelectedDisplay(
                        id: displayID,
                        persistentUUID: DisplayCatalog.persistentUUID(for: displayID)
                    )
                }
            }
            .store(in: &cancellables)

        settings.$hideDockIcon
            .dropFirst()
            .removeDuplicates()
            .sink { [weak self] hideDockIcon in
                // @Published emits in willSet — pass the value through rather
                // than rereading settings.hideDockIcon, which is still stale.
                self?.applyActivationPolicy(hideDockIcon: hideDockIcon)
            }
            .store(in: &cancellables)

        settings.$autoStartStreamingOnLaunch
            .dropFirst()
            .removeDuplicates()
            .sink { [weak self] enabled in
                if !enabled {
                    self?.cancelUnattendedRecovery(resetAttempts: true)
                }
            }
            .store(in: &cancellables)
    }

    private func refreshPendingReconfigurationIntent() {
        guard reconfigurationCoordinator.hasPendingReconfiguration else { return }
        reconfigurationCoordinator.refreshIntentGeneration()
    }

    private func requestServerStart(origin: HostStartOrigin) {
        settings.isStarting = true
        reconfigurationCoordinator.requestStart(
            HostRuntimeConfiguration(settings: settings, origin: origin)
        )
    }

    /// Switches between a normal Dock app and a menu-bar accessory.
    /// Default remains `.regular` so existing workflows keep a Dock icon.
    func applyActivationPolicy(hideDockIcon: Bool? = nil) {
        let hide = hideDockIcon ?? settings.hideDockIcon
        let policy: NSApplication.ActivationPolicy = hide ? .accessory : .regular
        let applied = NSApp.setActivationPolicy(policy)
        if !applied {
            debugLog("Failed to set activation policy to \(hide ? "accessory" : "regular")")
        }
    }

    func setupMenuBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)

        if let button = statusItem?.button {
            button.image = NSImage(systemSymbolName: "display.2", accessibilityDescription: "Virtual Display")
        }

        let menu = NSMenu()

        menu.addItem(NSMenuItem(title: "Settings", action: #selector(showSettings), keyEquivalent: "s"))
        menu.addItem(NSMenuItem(
            title: "Move Focused Window to Client Display",
            action: #selector(moveFocusedWindowToClientDisplay),
            keyEquivalent: ""
        ))
        menu.addItem(NSMenuItem(
            title: "Return Moved Windows",
            action: #selector(returnMovedWindowsToMainDisplay),
            keyEquivalent: ""
        ))
        menu.addItem(NSMenuItem.separator())
        let shareClipboardItem = NSMenuItem(
            title: "Share Mac Clipboard",
            action: nil,
            keyEquivalent: ""
        )
        let receiveClipboardItem = NSMenuItem(
            title: "Receive Android Clipboard",
            action: nil,
            keyEquivalent: ""
        )
        menu.addItem(shareClipboardItem)
        menu.addItem(receiveClipboardItem)
        clipboardController = ClipboardUIController(
            pasteboard: NSPasteboardClipboardAdapter(),
            shareMenuItem: shareClipboardItem,
            receiveMenuItem: receiveClipboardItem
        )
        let sendFileItem = NSMenuItem(
            title: "Send File to Android",
            action: nil,
            keyEquivalent: ""
        )
        menu.addItem(sendFileItem)
        fileTransferController = FileTransferUIController(sendMenuItem: sendFileItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))

        statusItem?.menu = menu
    }

    func setupSettingsWindow() {
        settings.onToggleServer = { [weak self] in
            guard let self else { return }
            if self.reconfigurationCoordinator.hasDesiredRunning
                || !self.serverLifecycle.canStart {
                Task { @MainActor [weak self] in
                    await self?.stopServer()
                }
            } else {
                self.requestServerStart(origin: .manual)
            }
        }

        settings.onRequestScreenRecordingPermission = { [weak self] in
            guard let appDelegate = self else { return }
            Task { @MainActor in
                appDelegate.requestScreenRecordingPermission()
            }
        }

        settings.onRequestAccessibilityPermission = { [weak self] in
            guard let appDelegate = self else { return }
            Task { @MainActor in
                appDelegate.requestAccessibilityPermission()
            }
        }

        settings.onResetWirelessToken = { [weak self] in
            do {
                let token = try WirelessAuth.reset()
                self?.settings.wirelessTokenError = nil
                self?.streamingServer?.rotateAuthToken(token)
                return true
            } catch {
                self?.settings.wirelessTokenError = error.localizedDescription
                debugLog("Could not reset wireless token: \(error.localizedDescription)")
                return false
            }
        }

        settings.onSaveInternetCredentials = { [weak self] issuerToken, turnCredential in
            self?.saveInternetCredentials(
                issuerToken: issuerToken,
                turnCredential: turnCredential
            ) ?? false
        }
        settings.onPairInternetDevice = { [weak self] in
            self?.beginInternetPairing()
        }
        settings.onCompleteInternetPairing = { [weak self] response in
            self?.completeInternetPairing(deviceResponse: response)
        }
        settings.onRevokeInternetDevice = { [weak self] in
            Task { @MainActor [weak self] in
                await self?.revokeInternetPeer()
            }
        }
        settings.onRetryInternetRevocationCleanup = { [weak self] in
            self?.retryInternetRevocationSecretCleanup()
        }
        settings.onConnectInternetSession = { [weak self] in
            self?.requestServerStart(origin: .manual)
        }
        settings.onDisconnectInternetSession = { [weak self] in
            Task { @MainActor [weak self] in
                await self?.stopServer()
            }
        }
        refreshInternetCredentialState()
        guard recoverPendingInternetPairingPersistence() else { return }
        do {
            try migrateLegacyRevokedInternetIdentityIfNeeded()
        } catch {
            settings.internetStatus = .failed
            settings.internetErrorMessage = "Revoked identity history could not be migrated."
            settings.internetRecoverySuggestion = "Keep Internet mode disconnected and retry after persistent settings are available."
            debugLog("Internet revoked identity history migration failed")
            return
        }
        let handledLegacyRevocation = handleLegacyGlobalRevocationIfNeeded()
        if !handledLegacyRevocation, internetPairingMetadataIsComplete {
            do {
                let peerIdentity = try pinnedInternetPeerIdentity()
                let secretNames = try PairedDeviceSecretNames.persistedPairing(
                    sharedSecret: settings.internetSharedSecretName,
                    bootstrapSecret: settings.internetBootstrapSecretName
                )
                guard let pairingIdentifier = secretNames.pairingIdentifier else {
                    throw PlatformSecurityError.persistenceFailure(
                        "The paired-device durable security owner is unknown. Pair again."
                    )
                }
                let persisted = try KeychainSecurityStateStore(
                    peerID: PairedDeviceSecurityScope.identifier(peerIdentity)
                ).validatePairingBinding(pairingIdentifier: pairingIdentifier)
                if persisted.revoked {
                    try rememberRevokedInternetIdentity(peerIdentity)
                }
                settings.internetStatus = persisted.revoked ? .revoked : .paired
                settings.internetRevocationCleanupPending =
                    persisted.revocationSecretCleanup != nil
                if settings.internetRevocationCleanupPending {
                    retryInternetRevocationSecretCleanup()
                }
            } catch {
                settings.internetStatus = .failed
                settings.internetErrorMessage = "Could not read the paired-device security state."
                settings.internetRecoverySuggestion = "Unlock the login Keychain before connecting."
                debugLog("Internet paired-device security state read failed")
            }
        }
    }

    private var internetPairingMetadataIsComplete: Bool {
        !settings.internetPeerDeviceID.isEmpty &&
            !settings.internetPeerKeyID.isEmpty &&
            Data(base64Encoded: settings.internetPeerSigningPublicKeyBase64)?.count == 65 &&
            settings.internetPeerKeyEpoch > 0 &&
            !settings.internetSharedSecretName.isEmpty &&
            !settings.internetBootstrapSecretName.isEmpty &&
            Data(base64Encoded: settings.internetTranscriptContextBase64)?.count == 32
    }

    private func recoverPendingInternetPairingPersistence() -> Bool {
        do {
            let pendingContexts = try InternetPairingCoordinator
                .pendingPersistenceContexts()
            for pendingContext in pendingContexts {
                _ = try InternetPairingCoordinator.retryPendingPersistenceCleanup(
                    pairingIdentifier: pendingContext.pairingIdentifier,
                    cleanupBusinessState: {
                        try KeychainSecurityStateStore(
                            peerID: "lease-authority.\(pendingContext.pairingIdentifier)"
                        ).rollbackPairingBinding(
                            pairingIdentifier: pendingContext.pairingIdentifier
                        )
                        try KeychainSecurityStateStore(
                            peerID: pendingContext.peerSecurityScopeID
                        ).rollbackPairingBinding(
                            pairingIdentifier: pendingContext.pairingIdentifier
                        )
                        if self.settings.internetSharedSecretName ==
                            "pairing.\(pendingContext.pairingIdentifier).shared.v1" {
                            self.clearInternetPairingMetadata()
                        }
                    }
                )
            }
            return true
        } catch {
            settings.internetStatus = .failed
            settings.internetErrorMessage = "An incomplete Internet pairing could not be cleaned up."
            settings.internetRecoverySuggestion = "Unlock the login Keychain and relaunch before pairing or connecting."
            debugLog("Pending Internet pairing persistence cleanup failed")
            return false
        }
    }

    private func clearInternetPairingMetadata() {
        settings.internetPeerDeviceID = ""
        settings.internetPeerKeyID = ""
        settings.internetPeerKeyEpoch = 0
        settings.internetPeerSigningPublicKeyBase64 = ""
        settings.internetSharedSecretName = ""
        settings.internetBootstrapSecretName = ""
        settings.internetTranscriptContextBase64 = ""
        settings.internetAuthoritativeSessionEpoch = 0
        settings.internetSessionIdentifier = ""
        settings.internetPairingAcceptance = nil
        settings.internetPeerDisplayName = nil
    }

    /// Legacy v1 stored revocation as one global bit. Begin writes a durable
    /// cleanup marker before any invalidation. Every restart resumes from that
    /// marker until credentials and pairing metadata are cleared, then removes
    /// the legacy bit and marker last. The old bit is never copied to a peer.
    private func handleLegacyGlobalRevocationIfNeeded() -> Bool {
        do {
            let cleanupStore = KeychainSecurityStateStore(
                peerID: "legacy-global-revocation-cleanup"
            )
            let transaction = LegacyGlobalRevocationCleanupTransaction(
                persistence: cleanupStore
            )
            let currentIdentity = try? pinnedInternetPeerIdentity()
            guard let marker = try transaction.begin(
                fallbackRevokedIdentity: currentIdentity,
                sharedSecretName: settings.internetSharedSecretName.isEmpty
                    ? nil : settings.internetSharedSecretName,
                bootstrapSecretName: settings.internetBootstrapSecretName.isEmpty
                    ? nil : settings.internetBootstrapSecretName
            ) else {
                return false
            }
            if let revokedIdentity = marker.revokedIdentity {
                try rememberRevokedInternetIdentity(revokedIdentity)
            }

            let secrets = KeychainSecretStore()
            if let sharedSecretName = marker.sharedSecretName {
                try secrets.delete(name: sharedSecretName)
            }
            if let bootstrapSecretName = marker.bootstrapSecretName {
                try secrets.delete(name: bootstrapSecretName)
            }
            try secrets.delete(name: Self.internetSignalingTokenName)
            try secrets.delete(name: Self.internetSignalingIssuerTokenName)
            try secrets.delete(name: Self.internetTURNCredentialName)

            settings.internetPeerDeviceID = ""
            settings.internetPeerKeyID = ""
            settings.internetPeerKeyEpoch = 0
            settings.internetPeerSigningPublicKeyBase64 = ""
            settings.internetSharedSecretName = ""
            settings.internetBootstrapSecretName = ""
            settings.internetTranscriptContextBase64 = ""
            settings.internetAuthoritativeSessionEpoch = 0
            settings.internetSessionIdentifier = ""
            settings.internetCredentialsAvailable = false
            settings.internetStatus = .revoked
            settings.internetErrorMessage = "A legacy unscoped revocation was safely cleared. The previous pairing cannot reconnect."
            settings.internetRecoverySuggestion = "Generate a new Android signing identity with a higher key epoch, then choose Pair New Identity. The legacy revoked flag was not applied to other peers."
            try transaction.complete()
            debugLog("Legacy global revocation cleanup committed; existing Internet pairing invalidated")
            return true
        } catch {
            settings.internetStatus = .failed
            settings.internetErrorMessage = "Legacy Internet security state could not be cleared."
            settings.internetRecoverySuggestion = "Unlock the login Keychain and relaunch before pairing another device."
            debugLog("Legacy global revocation cleanup failed")
            return true
        }
    }

    private func migrateLegacyRevokedInternetIdentityIfNeeded() throws {
        guard !settings.internetRevokedPeerDeviceID.isEmpty else { return }
        try revokedInternetIdentityStore.remember(
            deviceID: settings.internetRevokedPeerDeviceID,
            keyID: settings.internetRevokedPeerKeyID,
            keyEpoch: settings.internetRevokedPeerKeyEpoch
        )
        settings.internetRevokedPeerDeviceID = ""
        settings.internetRevokedPeerKeyID = ""
        settings.internetRevokedPeerKeyEpoch = 0
    }

    private func rememberRevokedInternetIdentity(
        _ identity: PlatformPublicIdentity
    ) throws {
        try revokedInternetIdentityStore.remember(identity)
    }

    private func validateInternetReauthorization(
        _ identity: PlatformPublicIdentity
    ) throws {
        try revokedInternetIdentityStore.validateReauthorization(identity)
        let persisted = try KeychainSecurityStateStore(
            peerID: PairedDeviceSecurityScope.identifier(identity)
        ).load()
        guard !persisted.revoked, persisted.peerRevocation == nil else {
            throw PlatformSecurityError.revoked
        }
    }

    private func saveInternetCredentials(
        issuerToken: String,
        turnCredential: String
    ) -> Bool {
        guard !issuerToken.isEmpty else {
            settings.internetErrorMessage = "A short-lived issuer token is required."
            return false
        }
        do {
            let store = KeychainSecretStore()
            try store.persist(
                name: Self.internetSignalingIssuerTokenName,
                secret: Data(issuerToken.utf8)
            )
            if turnCredential.isEmpty {
                try store.delete(name: Self.internetTURNCredentialName)
            } else {
                try store.persist(
                    name: Self.internetTURNCredentialName,
                    secret: Data(turnCredential.utf8)
                )
            }
            refreshInternetCredentialState()
            settings.internetErrorMessage = nil
            settings.internetRecoverySuggestion = nil
            if internetPairingMetadataIsComplete,
               settings.internetStatus != .revoked {
                settings.internetStatus = .paired
            }
            return true
        } catch {
            settings.internetErrorMessage = "Could not save the local development credentials in Keychain."
            settings.internetRecoverySuggestion = "Unlock the login Keychain and try again."
            debugLog("Internet credential Keychain write failed")
            return false
        }
    }

    private func refreshInternetCredentialState() {
        do {
            let store = KeychainSecretStore()
            let issuerToken = try store.load(
                name: Self.internetSignalingIssuerTokenName
            )
            settings.internetCredentialsAvailable = issuerToken?.isEmpty == false
        } catch {
            settings.internetCredentialsAvailable = false
            debugLog("Internet credential Keychain read failed")
        }
    }

    private func beginInternetPairing() {
        guard recoverPendingInternetPairingPersistence() else { return }
        do {
            let identity = try KeychainDeviceIdentityStore().createIfMissing(
                deviceID: settings.internetHostDeviceID
            )
            let coordinator = InternetPairingCoordinator(signer: identity)
            let created = try coordinator.createOffer()
            internetPairingCoordinator = coordinator
            settings.internetPairingURL = created.url.absoluteString
            settings.internetPairingAcceptance = nil
            settings.internetPairingCode = nil
            settings.internetStatus = .pairing
            settings.internetErrorMessage = nil
            settings.internetRecoverySuggestion = "Scan the one-time QR code on the Android device, then complete identity confirmation there."
        } catch {
            settings.internetStatus = .failed
            settings.internetErrorMessage = error.localizedDescription
            settings.internetRecoverySuggestion = "Create a new one-time pairing offer and confirm both device identities."
            debugLog("Internet pairing offer creation failed")
        }
    }

    private func completeInternetPairing(deviceResponse: String) {
        guard let coordinator = internetPairingCoordinator else {
            settings.internetStatus = .failed
            settings.internetErrorMessage = "The pairing offer is no longer active."
            settings.internetRecoverySuggestion = "Create and scan a new one-time pairing offer."
            return
        }
        let trimmed = deviceResponse.trimmingCharacters(in: .whitespacesAndNewlines)
        let responseData = Data(base64Encoded: trimmed) ?? Data(trimmed.utf8)
        let previousPairingMetadata = (
            deviceID: settings.internetPeerDeviceID,
            keyID: settings.internetPeerKeyID,
            keyEpoch: settings.internetPeerKeyEpoch,
            signingPublicKey: settings.internetPeerSigningPublicKeyBase64,
            sharedSecretName: settings.internetSharedSecretName,
            bootstrapSecretName: settings.internetBootstrapSecretName,
            transcriptContext: settings.internetTranscriptContextBase64,
            displayName: settings.internetPeerDisplayName,
            acceptance: settings.internetPairingAcceptance
        )
        do {
            let request = try InternetPairingDeviceRequestWire.parse(responseData)
            let acceptance = try coordinator.accept(request)
            try coordinator.completePersistence(
                secretNames: acceptance.secretNames,
                commitBusinessState: {
                    let acceptedIdentity = PlatformPublicIdentity(
                        deviceID: acceptance.deviceIdentity.deviceID,
                        keyID: acceptance.deviceIdentity.keyID,
                        keyEpoch: acceptance.deviceIdentity.keyEpoch,
                        signingPublicKey: acceptance.deviceIdentity.signingPublicKey
                    )
                    try self.validateInternetReauthorization(acceptedIdentity)
                    try KeychainSecurityStateStore(
                        peerID: PairedDeviceSecurityScope.identifier(acceptedIdentity)
                    ).initializePairingBinding(
                        pairingIdentifier: acceptance.pairingIdentifier
                    )
                    try KeychainSecurityStateStore(
                        peerID: "lease-authority.\(acceptance.pairingIdentifier)"
                    ).initializePairingBinding(
                        pairingIdentifier: acceptance.pairingIdentifier
                    )
                    let encodedAcceptance = try InternetPairingAcceptanceWire.encode(acceptance)
                    self.settings.internetPeerDeviceID = acceptance.deviceIdentity.deviceID
                    self.settings.internetPeerKeyID = acceptance.deviceIdentity.keyID
                    self.settings.internetPeerKeyEpoch = acceptance.deviceIdentity.keyEpoch
                    self.settings.internetPeerSigningPublicKeyBase64 = acceptance.deviceIdentity.signingPublicKey.base64EncodedString()
                    self.settings.internetSharedSecretName = acceptance.secretNames.sharedSecret
                    self.settings.internetBootstrapSecretName = acceptance.secretNames.bootstrapSecret
                    self.settings.internetTranscriptContextBase64 = acceptance.sessionContext.base64EncodedString()
                    self.settings.internetPeerDisplayName = acceptance.deviceName
                    self.settings.internetPairingAcceptance = encodedAcceptance.base64EncodedString()
                },
                cleanupBusinessState: {
                    let acceptedIdentity = PlatformPublicIdentity(
                        deviceID: acceptance.deviceIdentity.deviceID,
                        keyID: acceptance.deviceIdentity.keyID,
                        keyEpoch: acceptance.deviceIdentity.keyEpoch,
                        signingPublicKey: acceptance.deviceIdentity.signingPublicKey
                    )
                    try KeychainSecurityStateStore(
                        peerID: "lease-authority.\(acceptance.pairingIdentifier)"
                    ).rollbackPairingBinding(
                        pairingIdentifier: acceptance.pairingIdentifier
                    )
                    try KeychainSecurityStateStore(
                        peerID: PairedDeviceSecurityScope.identifier(acceptedIdentity)
                    ).rollbackPairingBinding(
                        pairingIdentifier: acceptance.pairingIdentifier
                    )
                    self.settings.internetPeerDeviceID = previousPairingMetadata.deviceID
                    self.settings.internetPeerKeyID = previousPairingMetadata.keyID
                    self.settings.internetPeerKeyEpoch = previousPairingMetadata.keyEpoch
                    self.settings.internetPeerSigningPublicKeyBase64 = previousPairingMetadata.signingPublicKey
                    self.settings.internetSharedSecretName = previousPairingMetadata.sharedSecretName
                    self.settings.internetBootstrapSecretName = previousPairingMetadata.bootstrapSecretName
                    self.settings.internetTranscriptContextBase64 = previousPairingMetadata.transcriptContext
                    self.settings.internetPeerDisplayName = previousPairingMetadata.displayName
                    self.settings.internetPairingAcceptance = previousPairingMetadata.acceptance
                }
            )
            let acceptedIdentity = PlatformPublicIdentity(
                deviceID: acceptance.deviceIdentity.deviceID,
                keyID: acceptance.deviceIdentity.keyID,
                keyEpoch: acceptance.deviceIdentity.keyEpoch,
                signingPublicKey: acceptance.deviceIdentity.signingPublicKey
            )
            do {
                try KeychainSecurityStateStore(
                    peerID: PairedDeviceSecurityScope.identifier(acceptedIdentity)
                ).finalizePairingBinding(
                    pairingIdentifier: acceptance.pairingIdentifier
                )
            } catch {
                debugLog("Committed pairing retained its rollback checkpoint")
            }
            settings.internetPairingURL = nil
            settings.internetPairingCode = nil
            settings.internetStatus = .paired
            settings.internetErrorMessage = nil
            settings.internetRecoverySuggestion = "Return the acceptance to Android, then issue a fresh short-lived session profile."
            internetPairingCoordinator = nil
        } catch {
            // Every malformed response consumes the one-time offer by design.
            internetPairingCoordinator = nil
            settings.internetPairingURL = nil
            let reusedRevokedIdentity = (error as? PlatformSecurityError) == .revoked
            settings.internetStatus = reusedRevokedIdentity ? .revoked : .failed
            settings.internetErrorMessage = error.localizedDescription
            settings.internetRecoverySuggestion = reusedRevokedIdentity
                ? "The old signing identity remains revoked. Generate a new signing key and higher key epoch before choosing Pair New Identity."
                : "Create a new one-time pairing offer; the previous credential cannot be reused."
            debugLog("Internet pairing response rejected")
        }
    }

    private func revokeInternetPeer() async {
        guard !settings.internetPeerDeviceID.isEmpty else {
            settings.internetStatus = .idle
            return
        }
        do {
            let peerIdentity = try pinnedInternetPeerIdentity()
            let peerScopeID = PairedDeviceSecurityScope.identifier(peerIdentity)
            let stateStore = KeychainSecurityStateStore(
                peerID: peerScopeID
            )
            let secretNames = try PairedDeviceSecretNames.persistedPairing(
                sharedSecret: settings.internetSharedSecretName,
                bootstrapSecret: settings.internetBootstrapSecretName
            )
            guard let pairingIdentifier = secretNames.pairingIdentifier else {
                throw PlatformSecurityError.persistenceFailure(
                    "The paired-device durable security owner is unknown. Pair again."
                )
            }
            let persistedSequence = try stateStore.validatePairingBinding(
                pairingIdentifier: pairingIdentifier
            ).revocationSequence
            guard persistedSequence < UInt64.max else {
                throw PlatformSecurityError.exhausted(
                    "The revocation sequence is exhausted."
                )
            }
            let sequence = max(
                persistedSequence + 1,
                UInt64(Date().timeIntervalSince1970 * 1_000)
            )
            // Close the reconfiguration gate before the session queues its
            // onRevoked callback. The local revocation path owns the stop.
            settings.internetStatus = .revoked
            reconfigurationCoordinator.recordManualStop()
            if let session = internetProductSession {
                try session.revoke(sequence: sequence)
            } else {
                let identityStore = KeychainDeviceIdentityStore()
                guard let identityBindingName = secretNames.identityBinding,
                      let encodedIdentityBinding = try KeychainSecretStore().load(
                        name: identityBindingName
                      ) else {
                    throw PlatformSecurityError.persistenceFailure(
                        "The paired host identity binding is missing. Pair again; existing credentials were retained."
                    )
                }
                let identityBinding = try PairedHostIdentityBinding.decode(
                    encodedIdentityBinding
                )
                try identityBinding.requireTarget(
                    deviceID: settings.internetHostDeviceID,
                    keyEpoch: PlatformPublicIdentity.initialKeyEpoch
                )
                let authority = try identityStore.loadVerifiedExisting(
                    binding: identityBinding
                )
                var nonce = Data(count: 32)
                let status = nonce.withUnsafeMutableBytes { bytes in
                    SecRandomCopyBytes(
                        kSecRandomDefault,
                        bytes.count,
                        bytes.baseAddress!
                    )
                }
                guard status == errSecSuccess else {
                    throw PlatformSecurityError.persistenceFailure(
                        "Unable to generate revocation randomness."
                    )
                }
                let tombstone = try authority.signPeerRevocation(
                    peerIdentity: peerIdentity,
                    sequence: sequence,
                    revokedAtUnixSeconds: Int64(Date().timeIntervalSince1970),
                    nonce: nonce,
                    reasonCode: "user_revoked"
                )
                let security = PlatformSessionSecurity(
                    deviceID: settings.internetHostDeviceID,
                    peerID: peerScopeID,
                    identityStore: identityStore,
                    stateStore: stateStore
                )
                try security.requirePairingBinding(pairingIdentifier)
                try security.revokePeer(
                    tombstone,
                    expectedAuthority: authority.publicIdentity,
                    expectedPeer: peerIdentity,
                    secretNames: secretNames
                )
            }
            try rememberRevokedInternetIdentity(peerIdentity)
            let store = KeychainSecretStore()
            try store.delete(name: Self.internetSignalingTokenName)
            try store.delete(name: Self.internetSignalingIssuerTokenName)
            try store.delete(name: Self.internetTURNCredentialName)
            settings.clientConnected = false
            settings.internetCredentialsAvailable = false
            settings.internetRevocationCleanupPending = false
            settings.internetPairingURL = nil
            settings.internetStatus = .revoked
            settings.internetErrorMessage = "This device is revoked and cannot reconnect."
            settings.internetRecoverySuggestion = "The revoked signing key is locally blocked forever; the session authority must propagate the signed tombstone to signaling/TURN. To authorize this device again, generate a new signing identity with a higher key epoch, then choose Pair New Identity."
            await stopServer(preserveRecoveryState: true)
        } catch {
            let cleanupPending = (try? currentInternetRevocationCleanupPending()) == true
            let revocationPersisted = (try? pinnedInternetPeerIdentity()).flatMap { identity in
                try? KeychainSecurityStateStore(
                    peerID: PairedDeviceSecurityScope.identifier(identity)
                ).load().revoked
            } == true
            let finalizationPending = cleanupPending || revocationPersisted
            reconfigurationCoordinator.recordManualStop()
            settings.internetRevocationCleanupPending = finalizationPending
            settings.internetStatus = finalizationPending ? .revoked : .failed
            settings.internetErrorMessage = finalizationPending
                ? "The device is revoked, but secure revocation finalization still needs retry."
                : "Revocation could not be persisted. The active session was stopped."
            settings.internetRecoverySuggestion = finalizationPending
                ? "Unlock the login Keychain and choose Retry Cleanup before pairing another identity."
                : "Keep the session disconnected and retry revocation before reconnecting."
            debugLog("Internet peer revocation failed")
            await stopServer(preserveRecoveryState: true)
        }
    }

    private func currentInternetRevocationCleanupPending() throws -> Bool {
        let peerIdentity = try pinnedInternetPeerIdentity()
        let peerID = PairedDeviceSecurityScope.identifier(peerIdentity)
        let secretNames = try PairedDeviceSecretNames.persistedPairing(
            sharedSecret: settings.internetSharedSecretName,
            bootstrapSecret: settings.internetBootstrapSecretName
        )
        guard let pairingIdentifier = secretNames.pairingIdentifier else {
            throw PlatformSecurityError.persistenceFailure(
                "The paired-device durable security owner is unknown. Pair again."
            )
        }
        let stateStore = KeychainSecurityStateStore(peerID: peerID)
        let security = PlatformSessionSecurity(
            deviceID: settings.internetHostDeviceID,
            peerID: peerID,
            stateStore: stateStore
        )
        try security.requireRevokedPairingBinding(pairingIdentifier)
        return try security.hasPendingRevocationSecretCleanup()
    }

    private func retryInternetRevocationSecretCleanup() {
        do {
            let peerIdentity = try pinnedInternetPeerIdentity()
            let peerID = PairedDeviceSecurityScope.identifier(peerIdentity)
            let secretNames = try PairedDeviceSecretNames.persistedPairing(
                sharedSecret: settings.internetSharedSecretName,
                bootstrapSecret: settings.internetBootstrapSecretName
            )
            guard let pairingIdentifier = secretNames.pairingIdentifier else {
                throw PlatformSecurityError.persistenceFailure(
                    "The paired-device durable security owner is unknown. Pair again."
                )
            }
            let stateStore = KeychainSecurityStateStore(peerID: peerID)
            // The per-device epoch floor is a separate durable record. Commit it
            // before clearing the cleanup gate so a completed secret deletion
            // cannot make a lower-epoch replacement identity eligible.
            try rememberRevokedInternetIdentity(peerIdentity)
            let security = PlatformSessionSecurity(
                deviceID: settings.internetHostDeviceID,
                peerID: peerID,
                stateStore: stateStore
            )
            try security.requireRevokedPairingBinding(pairingIdentifier)
            try security.retryRevocationSecretCleanup()
            settings.internetRevocationCleanupPending = false
            settings.internetStatus = .revoked
            settings.internetErrorMessage = "This device is revoked and its pairing secrets were removed."
            settings.internetRecoverySuggestion = "Generate a new signing identity with a higher key epoch before pairing again."
            debugLog("Internet revocation secret cleanup completed")
        } catch {
            settings.internetRevocationCleanupPending = true
            settings.internetStatus = .revoked
            settings.internetErrorMessage = "The device remains revoked, but pairing-secret cleanup is still pending."
            settings.internetRecoverySuggestion = "Unlock the login Keychain and choose Retry Cleanup before pairing another identity."
            debugLog("Internet revocation secret cleanup retry failed")
        }
    }

    @objc func showSettings() {
        if settingsWindow == nil {
            let controller = SettingsWindowController(settings: settings)
            controller.onWindowClosed = { [weak self, weak controller] in
                guard let self, self.settingsWindow === controller else { return }
                self.settingsWindow = nil
            }
            settingsWindow = controller
        }
        settingsWindow?.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func moveFocusedWindowToClientDisplay() {
        guard let activeDisplayID else {
            presentWindowActionError("Start streaming before moving a window.")
            return
        }
        do {
            try windowRecoveryManager.moveFocusedWindow(to: activeDisplayID)
            debugLog("Moved focused window to display \(activeDisplayID)")
        } catch {
            presentWindowActionError(error.localizedDescription)
        }
    }

    @objc private func returnMovedWindowsToMainDisplay() {
        reportWindowRecovery(windowRecoveryManager.restoreManagedWindows())
    }

    private func presentWindowActionError(_ message: String) {
        debugLog("Window action failed: \(message)")
        let alert = NSAlert()
        alert.messageText = "Could Not Move Window"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
    }

    private func reportWindowRecovery(_ report: WindowRecoveryReport) {
        if report.restoredCount > 0 {
            debugLog("Restored \(report.restoredCount) moved window(s)")
        }
        for failure in report.failedDescriptions {
            debugLog("Window restore failed: \(failure)")
        }
    }

    func checkPermissions() async {
        let version = ProcessInfo.processInfo.operatingSystemVersion
        debugLog("checkPermissions — macOS \(version.majorVersion).\(version.minorVersion).\(version.patchVersion)")

        // Check Screen Recording permission using CoreGraphics API
        let hasScreenCapture = CGPreflightScreenCaptureAccess()
        await MainActor.run {
            settings.hasScreenRecordingPermission = hasScreenCapture
        }
        if hasScreenCapture {
            debugLog("Screen recording permission granted (CGPreflight)")

            // On macOS 26+, also verify ScreenCaptureKit is actually functional
            if version.majorVersion >= 26 {
                do {
                    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
                    if content.displays.isEmpty {
                        debugLog(
                            "WARNING: CGPreflight OK but ScreenCaptureKit returned no displays; " +
                            "unlock the Mac session or attach a physical, dummy, or Screen Sharing display"
                        )
                    } else {
                        debugLog("SCShareableContent verification OK — \(content.displays.count) displays found")
                    }
                } catch {
                    debugLog("WARNING: CGPreflight OK but SCShareableContent failed on macOS 26: \(error.localizedDescription)")
                    debugLog("CGDisplayStream fallback will likely activate at capture time")
                }
            }
        } else {
            debugLog("Screen recording permission not granted yet")
        }

        // Check Accessibility permission (required for touch/mouse injection)
        await checkAccessibilityPermission()
    }

    func checkAccessibilityPermission() async {
        let trusted = AXIsProcessTrusted()
        await MainActor.run {
            settings.hasAccessibilityPermission = trusted
        }
        if trusted {
            print("✅ Accessibility permission granted")
        } else {
            print("⚠️  Accessibility permission not granted - touch control will not work")
        }
    }

    @MainActor
    func requestScreenRecordingPermission() {
        let granted = CGRequestScreenCaptureAccess()
        settings.hasScreenRecordingPermission = granted || CGPreflightScreenCaptureAccess()

        if !settings.hasScreenRecordingPermission,
           let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture") {
            NSWorkspace.shared.open(url)
        }
    }

    @MainActor
    func requestAccessibilityPermission() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        let trusted = AXIsProcessTrustedWithOptions(options)
        settings.hasAccessibilityPermission = trusted

        if !trusted {
            print("⚠️  User needs to grant Accessibility permission in System Settings")
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
                NSWorkspace.shared.open(url)
            }
        }
    }

    /// Setup ADB reverse port forwarding for USB connection
    func setupADBReverse() async {
        let port = settings.port
        let configuredSerial = settings.adbDeviceSerial
        print("🔌 Setting up ADB reverse for port \(port)...")
        debugLog("🔌 setupADBReverse() invoked for port \(port)...")

        await Task.detached(priority: .utility) {
            // Try common adb paths
            let adbPaths = [
                "/usr/local/bin/adb",
                "/opt/homebrew/bin/adb",
                "~/Library/Android/sdk/platform-tools/adb",
                "/Users/\(NSUserName())/Library/Android/sdk/platform-tools/adb"
            ]

            var adbPath: String?
            for path in adbPaths {
                let expandedPath = NSString(string: path).expandingTildeInPath
                if FileManager.default.fileExists(atPath: expandedPath) {
                    adbPath = expandedPath
                    break
                }
            }

            // Also try 'which adb' to find it in PATH
            if adbPath == nil {
                let whichProcess = Process()
                whichProcess.executableURL = URL(fileURLWithPath: "/usr/bin/which")
                whichProcess.arguments = ["adb"]
                let whichPipe = Pipe()
                whichProcess.standardOutput = whichPipe
                whichProcess.standardError = FileHandle.nullDevice

                do {
                    try whichProcess.run()
                    whichProcess.waitUntilExit()
                    let data = whichPipe.fileHandleForReading.readDataToEndOfFile()
                    if let path = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
                       !path.isEmpty {
                        adbPath = path
                    }
                } catch {
                    // Ignore
                }
            }

            guard let finalAdbPath = adbPath else {
                print("⚠️  ADB not found - USB connection may not work")
                print("💡 Install Android SDK or run manually: adb reverse tcp:\(port) tcp:\(port)")
                return
            }

            print("📱 Found ADB at: \(finalAdbPath)")
            let connectedSerials = StatusDetector.usbDevices()
            guard let targetSerial = ADBDeviceSelectionPolicy.resolveTargetSerial(
                configuredSerial: configuredSerial,
                connectedSerials: connectedSerials
            ) else {
                if configuredSerial.isEmpty {
                    debugLog("ADB reverse skipped: no authorized Android device is connected")
                } else {
                    debugLog(
                        "ADB reverse skipped: selected device \(configuredSerial) is not connected; " +
                        "refusing to launch a different device"
                    )
                }
                return
            }

            // Retry adb reverse up to 3 times — handles first-install authorization delay
            for attempt in 1...3 {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: finalAdbPath)
                process.arguments = StatusDetector.adbArguments(
                    serial: targetSerial,
                    command: ["reverse", "tcp:\(port)", "tcp:\(port)"]
                )

                let pipe = Pipe()
                process.standardOutput = pipe
                process.standardError = pipe

                do {
                    try process.run()
                    process.waitUntilExit()

                    let data = pipe.fileHandleForReading.readDataToEndOfFile()
                    let output = String(data: data, encoding: .utf8) ?? ""

                    if process.terminationStatus == 0 {
                        print("✅ ADB reverse setup successful: tcp:\(port) -> tcp:\(port)")
                        Self.launchAndroidClient(
                            adbPath: finalAdbPath,
                            serial: targetSerial
                        )
                        return
                    } else {
                        print("⚠️  ADB reverse attempt \(attempt)/3 failed: \(output.trimmingCharacters(in: .whitespacesAndNewlines))")
                        if attempt < 3 {
                            try? await Task.sleep(nanoseconds: 1_000_000_000)
                        }
                    }
                } catch {
                    print("⚠️  Failed to run ADB (attempt \(attempt)/3): \(error.localizedDescription)")
                    if attempt < 3 {
                        try? await Task.sleep(nanoseconds: 1_000_000_000)
                    }
                }
            }

            print("💡 Make sure Android device is connected via USB with debugging enabled")
        }.value
    }

    /// Bring the Android receiver to the foreground and ask it to connect.
    /// `am start` is idempotent because MainActivity uses singleTop and handles
    /// repeated intents, which gives us cable-driven plug-and-play after setup.
    nonisolated private static func launchAndroidClient(
        adbPath: String,
        serial: String?
    ) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: adbPath)
        process.arguments = StatusDetector.adbArguments(serial: serial, command: [
            "shell", "am", "start",
            "-a", "android.intent.action.MAIN",
            "-n", "dev.telemachus.display/.MainActivity",
            "--ez", "auto_connect", "true"
        ])
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        do {
            try process.run()
            process.waitUntilExit()
            let output = String(
                data: pipe.fileHandleForReading.readDataToEndOfFile(),
                encoding: .utf8
            )?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if process.terminationStatus == 0 {
                debugLog("📱 Android client launched for automatic USB connection")
            } else {
                debugLog("Android auto-launch unavailable: \(output)")
            }
        } catch {
            debugLog("Android auto-launch failed: \(error.localizedDescription)")
        }
    }

    @MainActor
    func showPermissionAlert() {
        let version = ProcessInfo.processInfo.operatingSystemVersion
        let isMacOS26 = version.majorVersion >= 26

        let alert = NSAlert()
        if isMacOS26 {
            alert.messageText = "Screen & System Audio Recording Permission Required"
            alert.informativeText = "Please grant Screen & System Audio Recording permission in System Settings > Privacy & Security."
        } else {
            alert.messageText = "Screen Recording Permission Required"
            alert.informativeText = "Please grant Screen Recording permission in System Settings > Privacy & Security."
        }
        alert.alertStyle = .warning
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    @discardableResult
    private func startServer(
        origin: HostStartOrigin = .manual,
        configuration requestedConfiguration: HostRuntimeConfiguration? = nil,
        intentIsCurrent: @escaping @MainActor () -> Bool = { true }
    ) async -> Bool {
        guard intentIsCurrent() else { return false }
        let configuration = requestedConfiguration ?? HostRuntimeConfiguration(
            settings: settings,
            origin: origin
        )
        guard let startToken = serverLifecycle.beginStart() else {
            debugLog("Ignoring duplicate start request")
            return false
        }
        debugLog("🚀 startServer() invoked. Check permission: \(settings.hasScreenRecordingPermission)")
        guard settings.hasScreenRecordingPermission else {
            debugLog("❌ startServer aborted: Missing Screen Recording permission")
            showPermissionAlert()
            serverLifecycle.failStart(startToken)
            settings.isStarting = false
            return false
        }

        do {
            let size = configuration.resolutionSize(rotation: settings.rotation)
            var captureDisplayID: CGDirectDisplayID
            var streamSize: (width: Int, height: Int)

            switch configuration.displaySource {
            case .extended:
                let manager = VirtualDisplayManager()
                virtualDisplayManager = manager
                try manager.createDisplay(
                    width: size.width,
                    height: size.height,
                    refreshRate: settings.effectiveRefreshRate,
                    hiDPI: settings.hiDPI,
                    name: "Vibe Screen"
                )
                let createdID = try await prepareExtendedVirtualDisplay(manager)
                captureDisplayID = createdID
                streamSize = size

            case .mirrorMain:
                let mainDisplayID = CGMainDisplayID()
                let mainRefreshRate = Int(
                    CGDisplayCopyDisplayMode(mainDisplayID)?.refreshRate ?? 60
                )
                // Preferred path: create a private virtual display and hardware
                // mirror the main display onto it. Some macOS versions/GPUs
                // reject CGConfigureDisplayMirrorOfDisplay for a virtual target
                // (observed as CGError 1001 on macOS 26). In that case fall back
                // to capturing the physical main display directly, which yields
                // the same user-facing outcome (the Mac's main screen on the
                // client) instead of looping unattended recovery forever.
                var mirrorCaptureID: CGDirectDisplayID?
                do {
                    let manager = VirtualDisplayManager()
                    virtualDisplayManager = manager
                    try manager.createDisplay(
                        width: CGDisplayPixelsWide(mainDisplayID),
                        height: CGDisplayPixelsHigh(mainDisplayID),
                        refreshRate: max(30, mainRefreshRate),
                        hiDPI: false,
                        name: "Vibe Screen Mirror"
                    )
                    try manager.enableMirrorMode()
                    guard let createdID = manager.displayID else {
                        throw VirtualDisplayError.creationFailed(
                            "Mirror display was created without a display ID"
                        )
                    }
                    mirrorCaptureID = createdID
                } catch {
                    debugLog(
                        "Virtual-display mirror unavailable (\(error.localizedDescription)); " +
                        "falling back to direct main-display capture"
                    )
                    // Destroy the just-created mirror display before dropping the
                    // reference so it does not leak/stay registered with
                    // WindowServer when we fall back to direct capture.
                    virtualDisplayManager?.destroyDisplay()
                    virtualDisplayManager = nil
                    mirrorCaptureID = mainDisplayID
                }
                captureDisplayID = mirrorCaptureID ?? mainDisplayID
                streamSize = Self.aspectFitStreamSize(
                    sourceWidth: CGDisplayPixelsWide(mainDisplayID),
                    sourceHeight: CGDisplayPixelsHigh(mainDisplayID),
                    maximumWidth: size.width,
                    maximumHeight: size.height
                )

            case .currentMain:
                virtualDisplayManager = nil
                captureDisplayID = CGMainDisplayID()
                streamSize = Self.aspectFitStreamSize(
                    sourceWidth: CGDisplayPixelsWide(captureDisplayID),
                    sourceHeight: CGDisplayPixelsHigh(captureDisplayID),
                    maximumWidth: size.width,
                    maximumHeight: size.height
                )
                debugLog(
                    "Using existing main display \(captureDisplayID): " +
                    "\(CGDisplayPixelsWide(captureDisplayID))x\(CGDisplayPixelsHigh(captureDisplayID)), " +
                    "streaming \(streamSize.width)x\(streamSize.height)"
                )

            case .selectedDisplay:
                virtualDisplayManager = nil
                captureDisplayID = DisplayCatalog.resolve(
                    persistentUUID: configuration.selectedDisplay.persistentUUID,
                    fallbackID: configuration.selectedDisplay.id
                )
                streamSize = Self.aspectFitStreamSize(
                    sourceWidth: CGDisplayPixelsWide(captureDisplayID),
                    sourceHeight: CGDisplayPixelsHigh(captureDisplayID),
                    maximumWidth: size.width,
                    maximumHeight: size.height
                )
                debugLog(
                    "Using selected display \(captureDisplayID): " +
                    "\(CGDisplayPixelsWide(captureDisplayID))x" +
                    "\(CGDisplayPixelsHigh(captureDisplayID)), streaming " +
                    "\(streamSize.width)x\(streamSize.height)"
                )
            }
            activeDisplayID = captureDisplayID

            await MainActor.run {
                settings.displayCreated = true
            }

            // Let display registration settle, then validate the intent before
            // performing mode-specific side effects such as ADB setup.
            try await Task.sleep(nanoseconds: 500_000_000)
            try requireCurrentStart(startToken, intentIsCurrent: intentIsCurrent)
            if configuration.connectionMode == .usb {
                await setupADBReverse()
            } else {
                debugLog("Non-USB mode: skipping ADB setup")
            }
            try requireCurrentStart(startToken, intentIsCurrent: intentIsCurrent)

            if let vdm = virtualDisplayManager,
               configuration.displaySource == .extended {
                vdm.restoreDisplayPosition()
                let registered = vdm.verifyDisplayRegistered()
                if !registered {
                    debugLog("WARNING: Virtual display not found in online display list — capture may fail")
                }
            }

            // Setup capture
            let newCapture = try await ScreenCapture()
            try requireCurrentStart(startToken, intentIsCurrent: intentIsCurrent)
            screenCapture = newCapture
            let configuredCapture = newCapture
            configuredCapture.onCaptureMethodChanged = {
                [weak self, weak configuredCapture] method in
                Task { @MainActor in
                    guard let self, let configuredCapture,
                          self.serverLifecycle.ownsSession(startToken),
                          self.screenCapture === configuredCapture else { return }
                    debugLog("Capture method: \(method)")
                    self.settings.captureMethod = method
                }
            }
            configuredCapture.onDisplayIDChanged = {
                [weak self, weak configuredCapture] displayID in
                Task { @MainActor in
                    guard let self, let configuredCapture,
                          self.serverLifecycle.ownsSession(startToken),
                          self.screenCapture === configuredCapture else { return }
                    self.activeDisplayID = displayID
                }
            }
            configuredCapture.onTerminalCaptureFailure = {
                [weak self, weak configuredCapture] error in
                Task { @MainActor in
                    guard let self, let configuredCapture,
                          self.serverLifecycle.ownsSession(startToken),
                          self.screenCapture === configuredCapture else { return }
                    debugLog("Capture terminated: \(error.localizedDescription)")
                    await self.handleCaptureFailure(error, sessionToken: startToken)
                }
            }
            let existingDisplayOutput = configuration.displaySource == .extended
                ? nil
                : streamSize
            try await screenCapture?.setupForDisplay(
                captureDisplayID,
                refreshRate: settings.effectiveRefreshRate,
                outputSize: existingDisplayOutput,
                followsMainDisplay: configuration.displaySource == .currentMain
            )
            try requireCurrentStart(startToken, intentIsCurrent: intentIsCurrent)
            if configuration.displaySource == .currentMain,
               let resolvedDisplayID = screenCapture?.activeCaptureDisplayID,
               resolvedDisplayID != captureDisplayID {
                debugLog(
                    "Current-main capture adopted display \(resolvedDisplayID) instead of requested \(captureDisplayID)"
                )
                captureDisplayID = resolvedDisplayID
                activeDisplayID = resolvedDisplayID
                streamSize = Self.aspectFitStreamSize(
                    sourceWidth: CGDisplayPixelsWide(resolvedDisplayID),
                    sourceHeight: CGDisplayPixelsHigh(resolvedDisplayID),
                    maximumWidth: size.width,
                    maximumHeight: size.height
                )
            }

            if configuration.connectionMode == .internet {
                try await startInternetProductSession(
                    streamSize: streamSize,
                    sessionToken: startToken
                )
                try requireCurrentStart(startToken, intentIsCurrent: intentIsCurrent)
                guard serverLifecycle.finishStart(startToken) else {
                    throw CancellationError()
                }
                settings.isRunning = true
                settings.isStarting = false
                activeRuntimeConfiguration = configuration
                reconfigurationCoordinator.recordApplied(configuration)
                return true
            }

            // Setup server. USB is loopback-only; wireless authenticates every
            // candidate before it can replace the active client.
            let serverMode: StreamingServerMode
            let wakeHostAuthorizer: any WakeHostAuthorizing
            try requireCurrentStart(startToken, intentIsCurrent: intentIsCurrent)
            if configuration.connectionMode == .wireless {
                do {
                    let authToken = try WirelessAuth.loadOrCreate()
                    serverMode = .wireless(
                        authToken: authToken
                    )
                    wakeHostAuthorizer = SharedSecretWakeHostAuthorizer(secret: authToken)
                    settings.wirelessTokenError = nil
                } catch {
                    settings.wirelessTokenError = error.localizedDescription
                    debugLog("Could not prepare wireless token: \(error.localizedDescription)")
                    throw error
                }
            } else {
                serverMode = .usb
                wakeHostAuthorizer = DenyWakeHostAuthorizer()
            }
            streamingServer = StreamingServer(
                port: settings.port,
                mode: serverMode,
                wakeHostAuthorizer: wakeHostAuthorizer
            )
            let configuredServer = streamingServer
            streamingServer?.touchEnabled = settings.touchEnabled
            streamingServer?.controllerAvailable = gameControllerRuntime.factory != nil
            if let reason = gameControllerRuntime.unavailableReason {
                debugLog("Controller forwarding unavailable: \(reason)")
            } else {
                debugLog("Controller forwarding available: virtual gamepad runtime probe succeeded")
            }
            if configuration.connectionMode == .wireless {
                streamingServer?.onWirelessClientPaired = {
                    [weak self, weak configuredServer] deviceName, clientGeneration in
                    Task { @MainActor in
                        guard let self, let configuredServer else { return }
                        self.performSessionCallback(
                                token: startToken,
                                server: configuredServer,
                                clientGeneration: clientGeneration
                        ) {
                            self.currentWirelessDevice = deviceName
                            self.settings.currentWirelessDevice = deviceName
                            self.pairedDeviceStore.upsert(
                                name: deviceName,
                                lastConnected: Date()
                            )
                        }
                    }
                }
            }
            // Send the LOGICAL resolution that the user picked. The H.264 SPS in
            // the stream still carries the true physical pixel dimensions, so the
            // Android decoder/MediaCodec sets up correctly regardless. Sending the
            // logical dimensions here makes the resolution overlay on Android
            // match the Mac's resolution dropdown (e.g. "2560x1600" instead of
            // the HiDPI-doubled "5120x3200").
            streamingServer?.setDisplaySize(
                width: streamSize.width,
                height: streamSize.height,
                rotation: settings.rotation
            )
            streamingServer?.setProtocolV1VideoConfiguration(
                framesPerSecond: settings.effectiveRefreshRate,
                bitrateKbps: settings.effectiveBitrate * 1_000,
                displayID: String(captureDisplayID),
                displayName: protocolV1DisplayName(
                    displayID: captureDisplayID,
                    isVirtual: configuration.displaySource == .extended
                ),
                // Reflect whether a virtual display actually backs this
                // capture. Extended always is; mirrorMain is virtual only when
                // the private-API hardware mirror succeeded (else it degraded to
                // direct main-display capture, which is physical).
                isVirtual: configuration.displaySource == .extended
                    || (configuration.displaySource == .mirrorMain && virtualDisplayManager != nil)
            )
            // Advertise every online physical display plus, when the private
            // virtual-display API is available, one optional virtual extended
            // display so a single-physical-display Mac still offers a second
            // selectable chip. The captured display keeps its String(id)
            // identity so its descriptor matches the active-stream descriptor.
            streamingServer?.setProtocolV1Displays(
                protocolV1DisplayCatalog(
                    activeCaptureID: captureDisplayID,
                    activeDisplaySource: configuration.displaySource,
                    configuredSize: size
                )
            )
            streamingServer?.onDisplaySelectionRequested = {
                [weak self, weak configuredServer] requestedDisplayID in
                guard let self, let configuredServer,
                      self.streamingServer === configuredServer else { return }
                self.handleClientDisplaySelection(
                    requestedDisplayID,
                    server: configuredServer
                )
            }
            streamingServer?.onVideoPreferencesRequested = {
                [weak self, weak configuredServer] token, bitrateKbps, framesPerSecond, qualityPreset, resetQualityToAuto in
                guard let self, let configuredServer,
                      self.streamingServer === configuredServer else { return }
                self.applyClientVideoPreferences(
                    token: token,
                    bitrateKbps: bitrateKbps,
                    framesPerSecond: framesPerSecond,
                    qualityPreset: qualityPreset,
                    resetQualityToAuto: resetQualityToAuto,
                    server: configuredServer
                )
            }
            streamingServer?.onHostActionRequested = {
                [weak self, weak configuredServer] actionID, invocationID, _ in
                guard let self, let configuredServer,
                      self.streamingServer === configuredServer else { return }
                self.handleClientHostAction(
                    actionID,
                    invocationID: invocationID,
                    server: configuredServer
                )
            }
            let clipboardTransport: ClipboardTransport?
            switch configuration.connectionMode {
            case .usb:
                clipboardTransport = .usb
            case .wireless:
                clipboardTransport = .trustedLAN
            case .internet:
                // Internet sessions return before constructing StreamingServer.
                // Keep this nil so future control-flow changes cannot silently
                // label an Internet clipboard session as USB.
                clipboardTransport = nil
            }
            streamingServer?.onClipboardOfferReceived = {
                [weak self, weak configuredServer] offer, generation in
                guard let self, let configuredServer else { return }
                self.performSessionCallback(
                    token: startToken,
                    server: configuredServer,
                    clientGeneration: generation
                ) {
                    self.clipboardController?.handleOffer(offer, generation: generation)
                }
            }
            streamingServer?.onClipboardContentReceived = {
                [weak self, weak configuredServer] content, generation in
                guard let self, let configuredServer else { return }
                self.performSessionCallback(
                    token: startToken,
                    server: configuredServer,
                    clientGeneration: generation
                ) {
                    self.clipboardController?.handleContent(content, generation: generation)
                }
            }
            streamingServer?.onClipboardDirectContentReceived = {
                [weak self, weak configuredServer] content, generation in
                guard let self, let configuredServer else { return }
                self.performSessionCallback(
                    token: startToken,
                    server: configuredServer,
                    clientGeneration: generation
                ) {
                    self.clipboardController?.handleDirectContent(content, generation: generation)
                }
            }
            streamingServer?.onFileTransferApprovalRequested = { [weak self, weak configuredServer] offer in
                guard let self, let configuredServer,
                      self.streamingServer === configuredServer else { return false }
                return self.fileTransferController?.approveIncomingFileOffer(offer) ?? false
            }
            streamingServer?.onIncomingFileCompleted = { [weak self, weak configuredServer] completed in
                DispatchQueue.main.async { [weak self, weak configuredServer] in
                    guard let self, let configuredServer,
                          self.streamingServer === configuredServer else { return }
                    self.fileTransferController?.handleIncomingFileCompleted(completed)
                }
            }
            streamingServer?.onClientConnected = {
                [weak self, weak configuredServer, weak configuredCapture]
                clientGeneration in
                DispatchQueue.main.async { [weak self, weak configuredServer, weak configuredCapture] in
                    guard let self, let configuredServer, let configuredCapture,
                          self.screenCapture === configuredCapture else { return }
                    let activeServer = configuredServer
                    let clipboardAvailable = activeServer.clipboardAvailable
                    let fileTransferAvailable = activeServer.fileTransferAvailable
                    self.performSessionCallback(
                            token: startToken,
                            server: activeServer,
                            clientGeneration: clientGeneration
                    ) {
                        if let clipboardTransport {
                            self.clipboardController?.bind(
                                server: activeServer,
                                generation: clientGeneration,
                                transport: clipboardTransport,
                                clipboardAvailable: clipboardAvailable
                            )
                        } else {
                            self.clipboardController?.unbind()
                        }
                        self.fileTransferController?.bind(
                            server: activeServer,
                            fileTransferAvailable: fileTransferAvailable
                        )
                        configuredCapture.requestKeyframeOrReplayCachedFrame(force: true)
                        self.unattendedRecoveryAttempt = 0
                        // Clear before the new client's type-11 arrives so a
                        // takeover never leaves the previous tablet's model/Hz up.
                        self.settings.connectedDeviceModel = nil
                        self.settings.connectedDeviceMaxRefreshRate = nil
                        self.settings.clientConnected = true
                    }
                }
            }
            // Protocol startup pauses until this MainActor callback returns a
            // display configuration to the server's network queue.
            streamingServer?.onCodecNegotiated = {
                [weak self, weak configuredServer, weak configuredCapture]
                codec, clientGeneration, completion in
                Task { @MainActor in
                    guard let self, let configuredServer, let configuredCapture,
                          self.screenCapture === configuredCapture else {
                        completion(nil)
                        return
                    }
                    let accepted = self.performSessionCallback(
                            token: startToken,
                            server: configuredServer,
                            clientGeneration: clientGeneration
                    ) {
                        configuredCapture.setCodec(codec)
                        let dimensions: (width: Int, height: Int)
                        switch codec {
                        case .hevc:
                            dimensions = streamSize
                        case .h264:
                            dimensions = configuredCapture.encodeSize(for: .h264)
                        }
                        completion(NegotiatedDisplayConfiguration(
                            width: dimensions.width,
                            height: dimensions.height,
                            rotation: self.settings.rotation
                        ))
                    }
                    if !accepted { completion(nil) }
                }
            }
            streamingServer?.onKeyframeRequested = {
                [weak self, weak configuredServer, weak configuredCapture]
                force, clientGeneration in
                Task { @MainActor in
                    guard let self, let configuredServer, let configuredCapture,
                          self.screenCapture === configuredCapture else { return }
                    self.performSessionCallback(
                            token: startToken,
                            server: configuredServer,
                            clientGeneration: clientGeneration
                    ) {
                        configuredCapture.requestKeyframeOrReplayCachedFrame(force: force)
                    }
                }
            }

            streamingServer?.onClientDisconnected = {
                [weak self, weak configuredServer] clientGeneration in
                Task { @MainActor in
                    guard let self, let configuredServer else { return }
                    self.performSessionCallback(
                            token: startToken,
                            server: configuredServer,
                            clientGeneration: clientGeneration
                    ) {
                        self.cancelSessionInput(releaseDrag: true)
                        self.clipboardController?.unbind()
                        self.fileTransferController?.unbind()
                        self.reportWindowRecovery(
                            self.windowRecoveryManager.restoreManagedWindows()
                        )
                        self.settings.clientConnected = false
                        self.settings.connectedDeviceModel = nil
                        self.settings.connectedDeviceMaxRefreshRate = nil
                        // Final lastConnected snapshot at the disconnect moment, then
                        // freeze (currentWirelessDevice = nil stops the rolling update
                        // in refreshStatusIndicators).
                        if let name = self.currentWirelessDevice {
                            self.pairedDeviceStore.upsert(name: name, lastConnected: Date())
                            self.currentWirelessDevice = nil
                            self.settings.currentWirelessDevice = nil
                        }
                    }
                }
            }

            streamingServer?.onDeviceInfoReceived = {
                [weak self, weak configuredServer]
                model, refreshRate, clientGeneration in
                Task { @MainActor in
                    guard let self, let configuredServer else { return }
                    self.performSessionCallback(
                            token: startToken,
                            server: configuredServer,
                            clientGeneration: clientGeneration
                    ) {
                        self.settings.connectedDeviceModel = model
                        self.settings.connectedDeviceMaxRefreshRate = Int(refreshRate)
                        debugLog("Device info: \(model), \(refreshRate)Hz")
                    }
                }
            }

            streamingServer?.onTouchEvent = {
                [weak self, weak configuredServer]
                x, y, action, pointerCount, x2, y2, clientGeneration in
                Task { @MainActor in
                    guard let self, let configuredServer else { return }
                    self.performSessionCallback(
                            token: startToken,
                            server: configuredServer,
                            clientGeneration: clientGeneration
                    ) {
                        self.handleTouch(
                            x: x, y: y, action: action,
                            pointerCount: pointerCount, x2: x2, y2: y2
                        )
                    }
                }
            }
            streamingServer?.onInputCancelled = {
                [weak self, weak configuredServer] clientGeneration in
                Task { @MainActor in
                    guard let self, let configuredServer else { return }
                    self.performSessionCallback(
                            token: startToken,
                            server: configuredServer,
                            clientGeneration: clientGeneration
                   ) {
                       self.cancelSessionInput(releaseDrag: true)
                   }
               }
           }

            streamingServer?.onPointerEvent = {
                [weak self, weak configuredServer]
                x, y, phase, buttonMask, clientGeneration in
                Task { @MainActor in
                    guard let self, let configuredServer else { return }
                    self.performSessionCallback(
                            token: startToken,
                            server: configuredServer,
                            clientGeneration: clientGeneration
                    ) {
                        self.handleClientPointer(
                            x: x, y: y, phase: phase, buttonMask: buttonMask
                        )
                    }
                }
            }
            streamingServer?.onStylusEvent = {
                [weak self, weak configuredServer]
                inputID, pointerID, x, y, phase, pressure, tiltX, tiltY,
                toolKind, buttonMask, contactState, clientGeneration in
                Task { @MainActor in
                    guard let self, let configuredServer else { return }
                    self.performSessionCallback(
                        token: startToken,
                        server: configuredServer,
                        clientGeneration: clientGeneration
                    ) {
                        self.handleClientStylus(
                            inputID: inputID,
                            pointerID: pointerID,
                            x: x,
                            y: y,
                            phase: phase,
                            pressure: pressure,
                            tiltXDegrees: tiltX,
                            tiltYDegrees: tiltY,
                            toolKind: toolKind,
                            buttonMask: buttonMask,
                            contactState: contactState
                        )
                    }
                }
            }
            streamingServer?.onScrollEvent = {
                [weak self, weak configuredServer]
                deltaX, deltaY, clientGeneration in
                Task { @MainActor in
                    guard let self, let configuredServer else { return }
                    self.performSessionCallback(
                            token: startToken,
                            server: configuredServer,
                            clientGeneration: clientGeneration
                    ) {
                        self.handleClientScroll(deltaX: deltaX, deltaY: deltaY)
                    }
                }
            }
            streamingServer?.onKeyEvent = {
                [weak self, weak configuredServer]
                usage, pressed, modifiers, _, clientGeneration in
                Task { @MainActor in
                    guard let self, let configuredServer else { return }
                    self.performSessionCallback(
                            token: startToken,
                            server: configuredServer,
                            clientGeneration: clientGeneration
                    ) {
                        self.handleClientKey(
                            usage: usage, pressed: pressed, modifiers: modifiers
                        )
                    }
                }
            }
            streamingServer?.onControllerEvent = {
                [weak self, weak configuredServer] event, clientGeneration in
                guard let self, let configuredServer else { return false }
                var injected = false
                let accepted = self.performSessionCallback(
                    token: startToken,
                    server: configuredServer,
                    clientGeneration: clientGeneration
                ) {
                    do {
                        guard let controllerInput = self.sessionGameControllerInput else {
                            throw GameControllerInputError.unavailable(
                                self.gameControllerRuntime.unavailableReason
                                    ?? "runtime availability check failed"
                            )
                        }
                        try controllerInput.handle(event, generation: clientGeneration)
                        injected = true
                    } catch {
                        debugLog("Controller injection failed: \(error.localizedDescription)")
                    }
                }
                if !accepted {
                    debugLog("Discarded stale controller input for generation \(clientGeneration)")
                }
                return accepted && injected
            }

           streamingServer?.onStats = {
               [weak self, weak configuredServer] fps, mbps, clientGeneration in
                Task { @MainActor in
                    guard let self, let configuredServer else { return }
                    self.performSessionCallback(
                            token: startToken,
                            server: configuredServer,
                            clientGeneration: clientGeneration
                    ) {
                        self.settings.metrics.update(fps: fps, bitrateMbps: mbps)
                    }
                }
            }

            streamingServer?.encoderStatsProvider = { [weak configuredCapture] in
                configuredCapture?.encoderStats.map { stats in
                    (
                        inFlight: stats.inFlight,
                        capacity: stats.capacity,
                        frameRegistryCount: stats.frameRegistryCount
                    )
                }
            }
            streamingServer?.frameLifecycleStatsProvider = { [weak configuredCapture] in
                guard let stats = configuredCapture?.frameLifecycleStats else { return nil }
                return StreamFrameLifecycleStats(
                    latestPixelBufferRetained: stats.latestPixelBufferRetained,
                    latestPixelBufferCapacity: stats.latestPixelBufferCapacity,
                    fallbackCaptureActive: stats.fallbackCaptureActive,
                    encoderPresent: stats.encoderPresent
                )
            }

            streamingServer?.onServerFailed = {
                [weak self, weak configuredServer] error in
                Task { @MainActor in
                    guard let self, let configuredServer,
                          self.serverLifecycle.ownsSession(startToken),
                          self.streamingServer === configuredServer else { return }
                    debugLog("Streaming listener stopped: \(error.localizedDescription)")
                    await self.handleServerFailure(sessionToken: startToken)
                }
            }

            try streamingServer?.start()
            try await screenCapture?.startStreaming(
                to: streamingServer,
                bitrateMbps: settings.effectiveBitrate,
                quality: settings.effectiveQuality,
                gamingBoost: settings.gamingBoost,
                frameRate: settings.effectiveRefreshRate
            )
            try requireCurrentStart(startToken, intentIsCurrent: intentIsCurrent)

            guard serverLifecycle.finishStart(startToken) else {
                throw CancellationError()
            }
            settings.isRunning = true
            settings.isStarting = false
            activeRuntimeConfiguration = configuration
            reconfigurationCoordinator.recordApplied(configuration)

            print("✅ Server started on port \(settings.port)")
            return true
        } catch is CancellationError where !serverLifecycle.isCurrentStart(startToken) {
            debugLog("Discarded superseded host start \(startToken)")
            if serverLifecycle.isStopping {
                await stopServer(
                    preserveRecoveryState: true,
                    recordsManualStop: false
                )
            }
            return false
        } catch is CancellationError {
            debugLog("Discarded superseded host configuration \(startToken)")
            await stopServer(
                preserveRecoveryState: true,
                recordsManualStop: false
            )
            return false
        } catch {
            guard serverLifecycle.isCurrentStart(startToken) else {
                debugLog(
                    "Discarded error from superseded host start \(startToken): " +
                    error.localizedDescription
                )
                if serverLifecycle.isStopping {
                    await stopServer(
                        preserveRecoveryState: true,
                        recordsManualStop: false
                    )
                }
                return false
            }
            print("❌ Failed to start: \(error)")
            let shouldRecover = isUnattendedOperation || origin.authorizesRecovery
            if configuration.connectionMode == .internet {
                settings.internetStatus = .failed
                settings.internetErrorMessage = error.localizedDescription
                settings.internetRecoverySuggestion = internetRecoverySuggestion(
                    for: (error as? InternetProductSessionError)
                        ?? .invalidConfiguration(error.localizedDescription)
                )
            }
            let stopResult = await stopServer(
                preserveRecoveryState: true,
                recordsManualStop: false
            )
            guard intentIsCurrent(),
                  canApplyStopFollowUp(
                    result: stopResult,
                    permitsDesiredRunning: true
                  ) else { return false }
            if shouldRecover {
                debugLog("Unattended startup failed: \(error.localizedDescription)")
                scheduleUnattendedRecoveryIfEnabled(
                    allowAutomaticLaunch: origin.authorizesRecovery
                )
            } else {
                let alert = NSAlert()
                alert.messageText = "Failed to Start Server"
                alert.informativeText = error.localizedDescription
                alert.alertStyle = .critical
                alert.runModal()
            }
            return false
        }
    }

    private func requireCurrentStart(
        _ token: UInt64,
        intentIsCurrent: @MainActor () -> Bool = { true }
    ) throws {
        guard serverLifecycle.isCurrentStart(token), intentIsCurrent() else {
            throw CancellationError()
        }
    }

    @discardableResult
    private func performSessionCallback(
        token: UInt64,
        server: StreamingServer,
        clientGeneration: UInt64,
        operation: () -> Void
    ) -> Bool {
        guard serverLifecycle.ownsSession(token),
              streamingServer === server else { return false }
        var accepted = false
        let generationWasCurrent = server.performIfCurrentClientGeneration(
            clientGeneration
        ) {
            guard serverLifecycle.acceptsCallback(
                token,
                sourceMatches: streamingServer === server,
                clientGeneration: clientGeneration
            ) else { return }
            accepted = true
            operation()
        }
        return generationWasCurrent && accepted
    }

    private func startInternetProductSession(
        streamSize: (width: Int, height: Int),
        sessionToken: UInt64
    ) async throws {
        let startup = try makeInternetProductSessionStartup(
            streamSize: streamSize
        )
        let pipeline = InternetSessionLeaseStartupPipeline<InternetProductSession>(
            makeSession: { InternetProductSession() },
            createDelivery: createInternetSessionLeaseDelivery,
            requireCurrentStart: { try self.requireCurrentStart(sessionToken) },
            applyDelivery: { configuration, delivery, signalingBaseURL in
                try self.internetProductSessionConfiguration(
                    configuration,
                    applying: delivery,
                    signalingBaseURL: signalingBaseURL
                )
            },
            prepareSession: { session, configuration in
                self.internetProductSession = session
                self.settings.internetAdaptiveMediaControl = .active(
                    bitrateMbps: configuration.video.bitrateKbps / 1_000,
                    framesPerSecond: configuration.video.framesPerSecond,
                    quality: self.settings.effectiveQuality
                )
                self.installInternetSessionCallbacks(session, sessionToken: sessionToken)
                self.screenCapture?.setCodec(.hevc)
            },
            queueDelivery: { delivery, session in
                self.internetSessionLeaseDeliveryLifecycle.queue(
                    delivery,
                    isCurrent: {
                        self.serverLifecycle.ownsSession(sessionToken)
                            && self.internetProductSession === session
                    },
                    sessionState: { session.snapshotState() },
                    send: { delivery in
                        InternetSessionLeaseDelivery.send(delivery, on: session)
                    }
                )
            },
            resetDelivery: {
                self.internetSessionLeaseDeliveryLifecycle.reset()
            },
            startSession: { session, configuration in
                try session.start(configuration: configuration)
            },
            startCapture: { session, _ in
                try await self.screenCapture?.startStreaming(
                    to: session,
                    bitrateMbps: self.settings.effectiveBitrate,
                    quality: self.settings.effectiveQuality,
                    gamingBoost: self.settings.gamingBoost,
                    frameRate: self.settings.effectiveRefreshRate
                )
            },
            didStart: {
                debugLog("Secure Internet product session started")
            }
        )
        _ = try await pipeline.start(with: startup.leasePlan)
    }

    private struct InternetProductSessionStartup {
        let configuration: InternetProductSessionConfiguration
        let request: InternetSignalingSessionProfileRequest
        let signalingBaseURL: URL
        let issuerToken: String

        var leasePlan: InternetSessionLeaseStartupPlan {
            InternetSessionLeaseStartupPlan(
                configuration: configuration,
                request: request,
                signalingBaseURL: signalingBaseURL,
                issuerToken: issuerToken
            )
        }
    }

    private func makeInternetProductSessionStartup(
        streamSize: (width: Int, height: Int)
    ) throws -> InternetProductSessionStartup {
        let configuration = try makeInternetProductSessionConfiguration(
            streamSize: streamSize
        )
        guard let signalingBaseURL = configuration.transport.signaling?.endpoint else {
            throw InternetProductSessionError.invalidConfiguration(
                "Internet signaling configuration is unavailable."
            )
        }
        let request = try makeInternetSessionProfileRequest(
            configuration: configuration,
            signalingURL: signalingBaseURL
        )
        let issuerToken = try internetIssuerToken()
        return InternetProductSessionStartup(
            configuration: configuration,
            request: request,
            signalingBaseURL: signalingBaseURL,
            issuerToken: issuerToken
        )
    }

    private func makeInternetSessionProfileRequest(
        configuration: InternetProductSessionConfiguration,
        signalingURL: URL
    ) throws -> InternetSignalingSessionProfileRequest {
        guard !settings.internetAccountID.isEmpty else {
            throw InternetProductSessionError.invalidConfiguration(
                "Enter the authority account ID before connecting."
            )
        }
        let secretNames = try PairedDeviceSecretNames.persistedPairing(
            sharedSecret: configuration.sharedSecretName,
            bootstrapSecret: configuration.bootstrapSecretName
        )
        guard let pairingIdentifier = secretNames.pairingIdentifier else {
            throw PlatformSecurityError.persistenceFailure(
                "The paired-device durable security owner is unknown. Pair again."
            )
        }
        guard let identityBindingName = secretNames.identityBinding,
              let encodedIdentityBinding = try KeychainSecretStore().load(
                name: identityBindingName
              ) else {
            throw PlatformSecurityError.persistenceFailure(
                "The paired host identity binding is missing. Pair again."
            )
        }
        let identityBinding = try PairedHostIdentityBinding.decode(
            encodedIdentityBinding
        )
        try identityBinding.requireTarget(
            deviceID: settings.internetHostDeviceID,
            keyEpoch: configuration.identityEpoch
        )
        let hostIdentity = try KeychainDeviceIdentityStore()
            .loadVerifiedExisting(binding: identityBinding)
            .publicIdentity

        let iceServers = configuration.transport.iceServers.map { server in
            InternetSessionProfileICEServerRequest(
                urls: server.urls.map(\.absoluteString),
                username: server.username,
                credential: server.credential
            )
        }
        return InternetSignalingSessionProfileRequest(
            requestID: configuration.transport.sessionIdentifier,
            accountID: settings.internetAccountID,
            hostDeviceID: configuration.hostDeviceID,
            clientDeviceID: configuration.peerDeviceID,
            sessionEpoch: configuration.authoritativeSessionEpoch,
            ttlSeconds: Self.internetSessionProfileTTLSeconds,
            sessionProfile: InternetSessionProfileLeaseRequest(
                pairingID: pairingIdentifier,
                hostIdentity: hostIdentity,
                clientIdentity: configuration.peerIdentity,
                signalingURL: signalingURL.absoluteString,
                transcriptContext: configuration.transcriptContext,
                protocolSessionID: Data(configuration.transport.sessionIdentifier.utf8),
                iceServers: iceServers,
                allowInsecureForTesting: signalingURL.scheme?.lowercased() == "http"
            )
        )
    }

    private func internetIssuerToken() throws -> String {
        guard let tokenData = try KeychainSecretStore().load(
            name: Self.internetSignalingIssuerTokenName
        ), let token = String(data: tokenData, encoding: .utf8),
              !token.isEmpty else {
            throw InternetProductSessionError.invalidConfiguration(
                "Save a fresh short-lived issuer token in Keychain."
            )
        }
        return token
    }

    private func internetProductSessionConfiguration(
        _ configuration: InternetProductSessionConfiguration,
        applying delivery: InternetSessionLeaseDeliveryResult,
        signalingBaseURL: URL
    ) throws -> InternetProductSessionConfiguration {
        let transport = WebRTCTransportConfiguration(
            iceServers: configuration.transport.iceServers,
            peerIdentity: configuration.transport.peerIdentity,
            sessionIdentifier: delivery.sessionID,
            forceRelay: configuration.transport.forceRelay,
            signaling: WebRTCSignalingConfiguration(
                endpoint: signalingBaseURL,
                bearerToken: delivery.hostSignalingToken,
                role: .offerer
            )
        )
        return InternetProductSessionConfiguration(
            transport: transport,
            hostDeviceID: configuration.hostDeviceID,
            hostName: configuration.hostName,
            peerDeviceID: configuration.peerDeviceID,
            peerIdentity: configuration.peerIdentity,
            authoritativeSessionEpoch: configuration.authoritativeSessionEpoch,
            identityEpoch: configuration.identityEpoch,
            sharedSecretName: configuration.sharedSecretName,
            bootstrapSecretName: configuration.bootstrapSecretName,
            transcriptContext: configuration.transcriptContext,
            video: configuration.video,
            inputEnabled: configuration.inputEnabled,
            controllerAvailable: configuration.controllerAvailable,
            fileTransferPolicy: configuration.fileTransferPolicy,
            fileTransferApprovalTimeoutMilliseconds: configuration.fileTransferApprovalTimeoutMilliseconds,
            heartbeatIntervalMilliseconds: configuration.heartbeatIntervalMilliseconds,
            heartbeatTimeoutMilliseconds: configuration.heartbeatTimeoutMilliseconds,
            negotiationTimeoutMilliseconds: configuration.negotiationTimeoutMilliseconds,
            limits: configuration.limits
        )
    }

    private func makeInternetProductSessionConfiguration(
        streamSize: (width: Int, height: Int)
    ) throws -> InternetProductSessionConfiguration {
        guard internetPairingMetadataIsComplete else {
            throw InternetProductSessionError.invalidConfiguration(
                "Pair and confirm an Android device before connecting."
            )
        }
        guard !settings.internetSessionIdentifier.isEmpty else {
            throw InternetProductSessionError.invalidConfiguration(
                "Enter a fresh short-lived signaling request ID."
            )
        }
        guard DisplaySettings.isSafeInternetSignalingEndpoint(
            settings.internetSignalingEndpoint
        ), let signalingEndpoint = URL(string: settings.internetSignalingEndpoint) else {
            throw InternetProductSessionError.invalidConfiguration(
                "Enter a credential-free HTTPS signaling endpoint."
            )
        }
        guard DisplaySettings.isSafeInternetICEURLList(settings.internetICEURLs) else {
            throw InternetProductSessionError.invalidConfiguration(
                "Enter credential-free STUN or TURN URLs."
            )
        }
        let iceURLs = settings.internetICEURLs
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .compactMap(URL.init(string:))
        guard !iceURLs.isEmpty else {
            throw InternetProductSessionError.invalidConfiguration(
                "Enter at least one valid STUN or TURN URL."
            )
        }

        let secretStore = KeychainSecretStore()
        let hasTURN = iceURLs.contains {
            ["turn", "turns"].contains($0.scheme?.lowercased() ?? "")
        }
        var turnCredential: String?
        if hasTURN {
            guard !settings.internetTURNUsername.isEmpty,
                  let credentialData = try secretStore.load(
                    name: Self.internetTURNCredentialName
                  ), let credential = String(data: credentialData, encoding: .utf8),
                  !credential.isEmpty else {
                throw InternetProductSessionError.invalidConfiguration(
                    "TURN URLs require a username and a short-lived Keychain credential."
                )
            }
            turnCredential = credential
        }
        guard let transcriptContext = Data(
            base64Encoded: settings.internetTranscriptContextBase64
        ), transcriptContext.count == 32 else {
            throw InternetProductSessionError.invalidConfiguration(
                "The paired device transcript context is unavailable. Pair again."
            )
        }
        let peerIdentity = try pinnedInternetPeerIdentity()
        guard settings.internetAuthoritativeSessionEpoch > 0 else {
            throw InternetProductSessionError.invalidConfiguration(
                "The authoritative session epoch is unavailable. Issue a fresh session."
            )
        }
        let iceServer = WebRTCICEServer(
            urls: iceURLs,
            username: hasTURN ? settings.internetTURNUsername : nil,
            credential: turnCredential
        )
        let transport = WebRTCTransportConfiguration(
            iceServers: [iceServer],
            peerIdentity: peerIdentity.keyID,
            sessionIdentifier: settings.internetSessionIdentifier,
            forceRelay: settings.internetRoutePreference == .forceTURN,
            signaling: WebRTCSignalingConfiguration(
                endpoint: signalingEndpoint,
                bearerToken: "pending-authority-host-token",
                role: .offerer
            )
        )
        return InternetProductSessionConfiguration(
            transport: transport,
            hostDeviceID: settings.internetHostDeviceID,
            hostName: Host.current().localizedName ?? "Mac",
            peerDeviceID: settings.internetPeerDeviceID,
            peerIdentity: peerIdentity,
            authoritativeSessionEpoch: settings.internetAuthoritativeSessionEpoch,
            sharedSecretName: settings.internetSharedSecretName,
            bootstrapSecretName: settings.internetBootstrapSecretName,
            transcriptContext: transcriptContext,
            video: InternetProductVideoConfiguration(
                codec: .hevc,
                width: streamSize.width,
                height: streamSize.height,
                framesPerSecond: settings.effectiveRefreshRate,
                bitrateKbps: settings.effectiveBitrate * 1_000,
                rotationDegrees: settings.rotation
            ),
            inputEnabled: settings.touchEnabled,
            controllerAvailable: gameControllerRuntime.factory != nil,
            fileTransferPolicy: .default
        )
    }

    private func pinnedInternetPeerIdentity() throws -> PlatformPublicIdentity {
        guard !settings.internetPeerDeviceID.isEmpty,
              !settings.internetPeerKeyID.isEmpty,
              settings.internetPeerKeyEpoch > 0,
              let signingKey = Data(
                base64Encoded: settings.internetPeerSigningPublicKeyBase64
              ), signingKey.count == 65,
              signingKey.first == 0x04 else {
            throw InternetProductSessionError.invalidConfiguration(
                "The pinned paired-device identity is invalid. Pair again."
            )
        }
        return PlatformPublicIdentity(
            deviceID: settings.internetPeerDeviceID,
            keyID: settings.internetPeerKeyID,
            keyEpoch: settings.internetPeerKeyEpoch,
            signingPublicKey: signingKey
        )
    }

    private func installInternetSessionCallbacks(
        _ session: InternetProductSession,
        sessionToken: UInt64
    ) {
        let controllerRoute = sessionGameControllerInput.map {
            SessionGameControllerInputRoute(input: $0)
        }
        internetControllerInputRoute?.invalidate()
        internetControllerInputRoute = controllerRoute
        session.onStateChanged = { [weak self, weak session] state in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                state.inputCleanupScope.apply(
                    transientReset: {
                        // Runtime video renegotiation is still the same product
                        // session. Release transient pointer/stylus state without
                        // tearing down attached virtual controllers.
                        self.cancelActiveInput(releaseDrag: true)
                    },
                    fullSessionReset: {
                        self.cancelSessionInput(releaseDrag: true)
                    }
                )
                if state == .closed {
                    self.applyInternetSessionState(state)
                    await self.stopServer(preserveRecoveryState: true)
                    return
                }
                self.applyInternetSessionState(state)
                if case .streaming = state {
                    await self.internetSessionLeaseDeliveryLifecycle.handleStateChange(
                        state,
                        isCurrent: {
                            self.serverLifecycle.ownsSession(sessionToken)
                                && self.internetProductSession === session
                        },
                        send: { delivery in
                            InternetSessionLeaseDelivery.send(delivery, on: session)
                        },
                        failClosed: { reason in
                            guard self.serverLifecycle.ownsSession(sessionToken),
                                  self.internetProductSession === session else { return }
                            self.settings.internetStatus = .failed
                            self.settings.internetErrorMessage = reason
                            self.settings.internetRecoverySuggestion =
                                "Reconnect with a fresh short-lived Internet session profile."
                            await self.stopServer(preserveRecoveryState: true)
                        }
                    )
                }
            }
        }
        session.onError = { [weak self, weak session] error in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                // A failed product session must release capture/display and all
                // active state so the user can correct the profile and retry.
                self.settings.internetStatus = error == .revoked ? .revoked : .failed
                self.settings.internetErrorMessage = error.localizedDescription
                self.settings.internetRecoverySuggestion = self.internetRecoverySuggestion(for: error)
                debugLog("Secure Internet product session failed")
                await self.stopServer(preserveRecoveryState: true)
            }
        }
        session.onAuthenticatedTouchEvent = {
            [weak self, weak session]
            sessionEpoch, inputID, x, y, action, pointers, x2, y2 in
            let inject = { () -> Bool in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return false }
                return self.handleTouch(
                    x: x, y: y, action: action,
                    pointerCount: pointers, x2: x2, y2: y2
                )
            }
            let injected = Thread.isMainThread
                ? inject()
                : DispatchQueue.main.sync(execute: inject)
            if injected {
                debugLog(
                    "phase3_input_injected session_epoch=\(sessionEpoch) input_id=\(inputID)"
                )
            }
            return injected
        }
        session.onAuthenticatedStylusEvent = {
            [weak self, weak session]
            sessionEpoch, inputID, pointerID, x, y, phase, pressure, tiltX, tiltY,
            toolKind, buttonMask, contactState in
            let inject = { () -> Bool in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return false }
                return self.handleClientStylus(
                    inputID: inputID,
                    pointerID: pointerID,
                    x: x,
                    y: y,
                    phase: phase,
                    pressure: pressure,
                    tiltXDegrees: tiltX,
                    tiltYDegrees: tiltY,
                    toolKind: toolKind,
                    buttonMask: buttonMask,
                    contactState: contactState
                )
            }
            let injected = Thread.isMainThread
                ? inject()
                : DispatchQueue.main.sync(execute: inject)
            if injected {
                debugLog(
                    "phase3_stylus_injected session_epoch=\(sessionEpoch) "
                        + "input_id=\(inputID) pointer_id=\(pointerID)"
                )
            }
            return injected
        }
        session.onAuthenticatedControllerEvent = {
            [weak self, weak session]
            _, sessionGeneration, event in
            let inject = { () -> Bool in
                guard let self, let session, let controllerRoute,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session,
                      self.internetControllerInputRoute === controllerRoute else {
                    return false
                }
                do {
                    try controllerRoute.handle(event, generation: sessionGeneration)
                    return self.serverLifecycle.ownsSession(sessionToken)
                        && self.internetProductSession === session
                        && self.internetControllerInputRoute === controllerRoute
                } catch {
                    debugLog(
                        "Internet controller injection failed: \(error.localizedDescription)"
                    )
                    return false
                }
            }
            return Thread.isMainThread
                ? inject()
                : DispatchQueue.main.sync(execute: inject)
        }
        session.onKeyframeRequired = { [weak self, weak session] in
            let request = {
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                self.screenCapture?.requestKeyframeOrReplayCachedFrame(force: true)
            }
            if Thread.isMainThread {
                request()
            } else {
                DispatchQueue.main.sync(execute: request)
            }
        }
        session.onFreshSessionRecoveryRequired = {
            [weak self, weak session] attempt in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                // The previous signaling token, record keys and PeerConnection
                // are never reused across a handoff. Stop the full product
                // session until authority supplies a fresh short-lived profile.
                do {
                    try KeychainSecretStore().delete(
                        name: Self.internetSignalingTokenName
                    )
                    try KeychainSecretStore().delete(
                        name: Self.internetSignalingIssuerTokenName
                    )
                    try KeychainSecretStore().delete(
                        name: Self.internetTURNCredentialName
                    )
                } catch {
                    debugLog("Fresh-session credential cleanup failed: \(error.localizedDescription)")
                }
                self.settings.internetCredentialsAvailable = false
                self.settings.internetStatus = .recovering
                self.settings.internetErrorMessage = "Network recovery requires a fresh secure session."
                self.settings.internetRecoverySuggestion = "Issue a new short-lived session ID, issuer token and TURN credential, then connect again (attempt \(attempt))."
                await self.stopServer(preserveRecoveryState: true)
            }
        }
        session.onRevocationPropagationRequired = {
            [weak self, weak session] _ in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                self.settings.internetRecoverySuggestion = "Local signed revocation is committed. The session authority must propagate it to signaling, TURN, and the peer before revocation is globally complete."
            }
        }
        session.onRevoked = { [weak self, weak session] in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                self.settings.internetStatus = .revoked
                self.settings.clientConnected = false
                await self.stopServer(preserveRecoveryState: true)
            }
        }
        session.onFileTransferApprovalRequested = { [weak self, weak session] offer, completion in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else {
                    completion(false)
                    return
                }
                completion(self.fileTransferController?.approveIncomingFileOffer(offer) ?? false)
            }
        }
        session.onFileTransferCompleted = { [weak self, weak session] completed in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                self.fileTransferController?.handleIncomingFileCompleted(completed)
            }
        }
        session.onFileTransferResult = { [weak self, weak session] _, direction, accepted, reason in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                self.fileTransferController?.handleFileTransferResult(
                    direction: direction,
                    accepted: accepted,
                    reason: reason
                )
            }
        }
        session.onFileTransferAvailabilityChanged = { [weak self, weak session] _ in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                self.fileTransferController?.refreshAvailability()
            }
        }

        // Internet-only adaptive video. The adaptive controller owns encoder
        // bitrate/quality/fps and capture resolution while an Internet product
        // session is streaming. Manual user changes are gated out for the
        // duration of an active adaptive profile so the controller's decisions
        // are not overwritten; USB/LAN sessions are never affected because
        // internetAdaptiveMediaControl stays inactive outside Internet mode.
        session.onAdaptiveProfileRequested = {
            [weak self, weak session] token, profile, committed, baseline in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                await self.applyInternetAdaptiveProfile(
                    token: token,
                    profile: profile,
                    committed: committed,
                    baseline: baseline,
                    session: session,
                    sessionToken: sessionToken
                )
            }
        }

        session.onAdaptiveProfileRollbackRequested = {
            [weak self, weak session] token, committed, _ in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session,
                      let capture = self.screenCapture,
                      let displayID = self.activeDisplayID else {
                    session?.completeAdaptiveRollback(token: token, succeeded: false)
                    return
                }
                let succeeded = await self.restoreInternetAdaptiveCommitted(
                    committed: committed,
                    capture: capture,
                    displayID: displayID,
                    session: session,
                    sessionToken: sessionToken
                )
                guard self.ownsInternetAdaptiveOperation(
                    session: session,
                    sessionToken: sessionToken,
                    capture: capture,
                    displayID: displayID
                ) else {
                    session.completeAdaptiveRollback(token: token, succeeded: false)
                    return
                }
                session.completeAdaptiveRollback(token: token, succeeded: succeeded)
            }
        }

        session.onAdaptiveProfileCommitted = {
            [weak self, weak session] _, appliedVideo in
            Task { @MainActor in
                guard let self, let session,
                      self.serverLifecycle.ownsSession(sessionToken),
                      self.internetProductSession === session else { return }
                // The peer acknowledged the adaptive configuration. Publish the
                // live adaptive values to the UI without touching the user's
                // persisted bitrate/quality/fps settings.
                let bitrateMbps = max(1, appliedVideo.bitrateKbps / 1_000)
                self.settings.internetAdaptiveMediaControl = .active(
                    bitrateMbps: bitrateMbps,
                    framesPerSecond: appliedVideo.framesPerSecond,
                    quality: self.settings.internetAdaptiveMediaControl.quality
                )
            }
        }
    }

    // MARK: - Internet adaptive video

    /// Applies an Internet adaptive profile to the live encoder/capture and
    /// reports the outcome back to the product session. On any failure the
    /// previously committed configuration is restored so the stream keeps
    /// running; the session is then told to reject (soft) or fail (hard) the
    /// adaptive request. The user's persisted bitrate/quality/fps/gaming-boost
    /// settings are never modified.
    @MainActor
    private func applyInternetAdaptiveProfile(
        token: InternetAdaptiveRequestToken,
        profile: AdaptiveMediaProfile,
        committed: InternetProductVideoConfiguration,
        baseline: InternetProductVideoConfiguration,
        session: InternetProductSession,
        sessionToken: UInt64
    ) async {
        guard let capture = screenCapture,
              let displayID = activeDisplayID else {
            session.failAdaptiveProfile(
                token: token,
                reason: "Adaptive video requires an active capture source and display."
            )
            return
        }
        guard let plan = InternetAdaptiveVideoPlan(
            baseline: baseline,
            profile: profile
        ) else {
            session.rejectAdaptiveProfile(token: token)
            return
        }

        let bitrateMbps = plan.bitrateMbps
        let quality = settings.internetAdaptiveMediaControl.quality
        let fps = plan.framesPerSecond
        let currentSize = capture.encodeSize(for: capture.codec)
        let captureAction = CaptureReconfigurationPolicy.action(
            currentWidth: currentSize.width,
            currentHeight: currentSize.height,
            currentFrameRate: capture.activeCaptureFrameRate,
            targetWidth: plan.width,
            targetHeight: plan.height,
            targetFrameRate: fps
        )
        let needsCaptureRebuild = captureAction == .rebuild

        // Apply encoder bitrate/quality/fps first. The VideoToolbox update is
        // synchronous and reversible, so a failure here is a soft reject. A
        // required capture rebuild below is the authoritative source-rate apply.
        guard capture.updateEncoderSettings(
            bitrateMbps: bitrateMbps,
            quality: quality,
            gamingBoost: false,
            frameRate: fps,
            reconfigureCaptureSource: false
        ) == true else {
            session.rejectAdaptiveProfile(token: token)
            return
        }

        // Geometry changes rebuild the capture surface. FPS-only changes use
        // ScreenCaptureKit's live configuration API and await its completion.
        // Both paths finish before the product session advertises the new
        // configuration and starts the peer-ACK deadline.
        let sourceFrameRateChanged = captureAction == .updateFrameRate
        do {
            if needsCaptureRebuild {
                let followsMain = settings.displaySource == .currentMain
                try await capture.switchCapturedDisplay(
                    to: displayID,
                    refreshRate: fps,
                    outputSize: (plan.width, plan.height),
                    followsMainDisplay: followsMain,
                    reportsTerminalFailure: false
                )
            } else if captureAction == .updateFrameRate {
                try await capture.updateInternetAdaptiveFrameRate(fps)
            }
            guard ownsInternetAdaptiveOperation(
                session: session,
                sessionToken: sessionToken,
                capture: capture,
                displayID: displayID
            ) else {
                handleLostInternetAdaptiveOwnership(
                    token: token,
                    session: session,
                    sessionToken: sessionToken
                )
                return
            }
        } catch {
            guard ownsInternetAdaptiveOperation(
                session: session,
                sessionToken: sessionToken,
                capture: capture,
                displayID: displayID
            ) else {
                handleLostInternetAdaptiveOwnership(
                    token: token,
                    session: session,
                    sessionToken: sessionToken
                )
                return
            }
            if sourceFrameRateChanged && !needsCaptureRebuild {
                await failClosedInternetAdaptiveProfile(
                    token: token,
                    reason: "The host could not confirm the adaptive capture frame rate: \(error.localizedDescription)",
                    session: session,
                    sessionToken: sessionToken,
                    capture: capture,
                    displayID: displayID
                )
                return
            }
            let restored = await restoreInternetAdaptiveCommitted(
                committed: committed,
                capture: capture,
                displayID: displayID,
                session: session,
                sessionToken: sessionToken
            )
            guard ownsInternetAdaptiveOperation(
                session: session,
                sessionToken: sessionToken,
                capture: capture,
                displayID: displayID
            ) else {
                handleLostInternetAdaptiveOwnership(
                    token: token,
                    session: session,
                    sessionToken: sessionToken
                )
                return
            }
            if restored {
                session.rejectAdaptiveProfile(token: token)
            } else {
                await failClosedInternetAdaptiveProfile(
                    token: token,
                    reason: "The host could not restore the acknowledged Internet video configuration.",
                    session: session,
                    sessionToken: sessionToken,
                    capture: capture,
                    displayID: displayID
                )
            }
            return
        }

        let appliedVideo = InternetProductVideoConfiguration(
            codec: committed.codec,
            width: plan.width,
            height: plan.height,
            framesPerSecond: fps,
            bitrateKbps: plan.bitrateKbps,
            streamID: committed.streamID,
            configEpoch: committed.configEpoch,
            rotationDegrees: committed.rotationDegrees
        )

        do {
            let completed = try session.completeAdaptiveProfile(
                token: token,
                appliedVideo: appliedVideo
            )
            if !completed {
                guard ownsInternetAdaptiveOperation(
                    session: session,
                    sessionToken: sessionToken,
                    capture: capture,
                    displayID: displayID
                ) else {
                    handleLostInternetAdaptiveOwnership(
                        token: token,
                        session: session,
                        sessionToken: sessionToken
                    )
                    return
                }
                let restored = await restoreInternetAdaptiveCommitted(
                    committed: committed,
                    capture: capture,
                    displayID: displayID,
                    session: session,
                    sessionToken: sessionToken
                )
                guard ownsInternetAdaptiveOperation(
                    session: session,
                    sessionToken: sessionToken,
                    capture: capture,
                    displayID: displayID
                ) else {
                    handleLostInternetAdaptiveOwnership(
                        token: token,
                        session: session,
                        sessionToken: sessionToken
                    )
                    return
                }
                if restored {
                    if !session.rejectAdaptiveProfile(token: token) {
                        await failClosedInternetAdaptiveProfile(
                            token: token,
                            reason: "The session rejected completion of an uncommitted adaptive video profile.",
                            session: session,
                            sessionToken: sessionToken,
                            capture: capture,
                            displayID: displayID
                        )
                    }
                } else {
                    await failClosedInternetAdaptiveProfile(
                        token: token,
                        reason: "The host could not restore an uncommitted adaptive video profile.",
                        session: session,
                        sessionToken: sessionToken,
                        capture: capture,
                        displayID: displayID
                    )
                }
                return
            }
        } catch {
            guard ownsInternetAdaptiveOperation(
                session: session,
                sessionToken: sessionToken,
                capture: capture,
                displayID: displayID
            ) else {
                handleLostInternetAdaptiveOwnership(
                    token: token,
                    session: session,
                    sessionToken: sessionToken
                )
                return
            }
            if case .failed = session.snapshotState() { return }
            let restored = await restoreInternetAdaptiveCommitted(
                committed: committed,
                capture: capture,
                displayID: displayID,
                session: session,
                sessionToken: sessionToken
            )
            guard ownsInternetAdaptiveOperation(
                session: session,
                sessionToken: sessionToken,
                capture: capture,
                displayID: displayID
            ) else {
                handleLostInternetAdaptiveOwnership(
                    token: token,
                    session: session,
                    sessionToken: sessionToken
                )
                return
            }
            if restored {
                if !session.rejectAdaptiveProfile(token: token) {
                    await failClosedInternetAdaptiveProfile(
                        token: token,
                        reason: "The session could not reject an uncommitted adaptive video profile.",
                        session: session,
                        sessionToken: sessionToken,
                        capture: capture,
                        displayID: displayID
                    )
                }
            } else {
                await failClosedInternetAdaptiveProfile(
                    token: token,
                    reason: error.localizedDescription,
                    session: session,
                    sessionToken: sessionToken,
                    capture: capture,
                    displayID: displayID
                )
            }
        }
    }

    /// Restores the encoder/capture to the last committed Internet video
    /// configuration. Used both when an adaptive profile application fails and
    /// when the peer rejects a committed profile. Returns true when the
    /// committed configuration was successfully re-applied.
    @MainActor
    @discardableResult
    private func restoreInternetAdaptiveCommitted(
        committed: InternetProductVideoConfiguration,
        capture: ScreenCapture,
        displayID: CGDirectDisplayID,
        session: InternetProductSession,
        sessionToken: UInt64
    ) async -> Bool {
        let currentSize = capture.encodeSize(for: capture.codec)
        let currentFrameRate = capture.activeCaptureFrameRate
        let captureAction = CaptureReconfigurationPolicy.action(
            currentWidth: currentSize.width,
            currentHeight: currentSize.height,
            currentFrameRate: currentFrameRate,
            targetWidth: committed.width,
            targetHeight: committed.height,
            targetFrameRate: committed.framesPerSecond
        )
        guard ownsInternetAdaptiveOperation(
            session: session,
            sessionToken: sessionToken,
            capture: capture,
            displayID: displayID
        ), restoreInternetEncoderSettings(
            committed: committed,
            capture: capture,
            reconfigureCaptureSource: false
        ) else {
            return false
        }

        if captureAction == .rebuild {
            let followsMain = settings.displaySource == .currentMain
            do {
                try await capture.switchCapturedDisplay(
                    to: displayID,
                    refreshRate: committed.framesPerSecond,
                    outputSize: (committed.width, committed.height),
                    followsMainDisplay: followsMain,
                    reportsTerminalFailure: false
                )
            } catch {
                return false
            }
            guard ownsInternetAdaptiveOperation(
                session: session,
                sessionToken: sessionToken,
                capture: capture,
                displayID: displayID
            ) else { return false }
        } else if captureAction == .updateFrameRate {
            do {
                try await capture.updateInternetAdaptiveFrameRate(committed.framesPerSecond)
            } catch {
                return false
            }
            guard ownsInternetAdaptiveOperation(
                session: session,
                sessionToken: sessionToken,
                capture: capture,
                displayID: displayID
            ) else { return false }
        }
        return ownsInternetAdaptiveOperation(
            session: session,
            sessionToken: sessionToken,
            capture: capture,
            displayID: displayID
        )
    }

    /// Re-applies the committed bitrate/fps to the live encoder, using the
    /// user's persisted quality and gaming-boost settings. Resolution is left
    /// to the caller (restoreInternetAdaptiveCommitted) because it requires an
    /// async capture rebuild. Returns false when the encoder update fails.
    @MainActor
    @discardableResult
    private func restoreInternetEncoderSettings(
        committed: InternetProductVideoConfiguration,
        capture: ScreenCapture,
        reconfigureCaptureSource: Bool
    ) -> Bool {
        let bitrateMbps = max(1, committed.bitrateKbps / 1_000)
        // Quality is not part of the adaptive profile; preserve the user's
        // baseline quality while applying network-driven rate and geometry.
        let quality = settings.internetAdaptiveMediaControl.quality
        let isUserBaseline = bitrateMbps == settings.effectiveBitrate
            && committed.framesPerSecond == settings.effectiveRefreshRate
        return capture.updateEncoderSettings(
            bitrateMbps: bitrateMbps,
            quality: quality,
            gamingBoost: isUserBaseline && settings.gamingBoost,
            frameRate: committed.framesPerSecond,
            reconfigureCaptureSource: reconfigureCaptureSource
        )
    }

    @MainActor
    private func ownsInternetAdaptiveOperation(
        session: InternetProductSession,
        sessionToken: UInt64,
        capture: ScreenCapture,
        displayID: CGDirectDisplayID
    ) -> Bool {
        serverLifecycle.ownsSession(sessionToken)
            && internetProductSession === session
            && screenCapture === capture
            && activeDisplayID == displayID
    }

    @MainActor
    private func handleLostInternetAdaptiveOwnership(
        token: InternetAdaptiveRequestToken,
        session: InternetProductSession,
        sessionToken: UInt64
    ) {
        guard serverLifecycle.ownsSession(sessionToken),
              internetProductSession === session else {
            _ = session.rejectAdaptiveProfile(token: token)
            return
        }
        _ = session.failAdaptiveProfile(
            token: token,
            reason: "The active capture source changed during adaptive video reconfiguration."
        )
    }

    @MainActor
    private func failClosedInternetAdaptiveProfile(
        token: InternetAdaptiveRequestToken,
        reason: String,
        session: InternetProductSession,
        sessionToken: UInt64,
        capture: ScreenCapture,
        displayID: CGDirectDisplayID
    ) async {
        guard ownsInternetAdaptiveOperation(
            session: session,
            sessionToken: sessionToken,
            capture: capture,
            displayID: displayID
        ) else {
            _ = session.failAdaptiveProfile(token: token, reason: reason)
            return
        }
        if session.failAdaptiveProfile(token: token, reason: reason) { return }
        switch session.snapshotState() {
        case .failed, .closed:
            return
        default:
            settings.internetStatus = .failed
            settings.internetErrorMessage = reason
            settings.internetRecoverySuggestion =
                "Reconnect with a fresh short-lived Internet session profile."
            await stopServer(preserveRecoveryState: true)
        }
    }

    @MainActor
    private func applyInternetSessionState(_ state: InternetProductSessionState) {
        switch state {
        case .idle:
            if internetProductSession != nil { fileTransferController?.unbind() }
            settings.internetStatus = internetPairingMetadataIsComplete ? .paired : .idle
        case .connecting, .authenticating, .awaitingVideoConfiguration:
            if internetProductSession != nil { fileTransferController?.unbind() }
            settings.internetStatus = .connecting
            settings.clientConnected = false
        case .streaming(let path):
            guard path != .unknown else {
                if internetProductSession != nil { fileTransferController?.unbind() }
                settings.internetStatus = .failed
                settings.internetErrorMessage =
                    "The selected ICE candidate path is unknown; no route was published."
                settings.clientConnected = false
                return
            }
            if let session = internetProductSession {
                fileTransferController?.bind(
                    server: session,
                    fileTransferAvailable: session.fileTransferAvailable
                )
            }
            settings.internetStatus = path == .relay ? .relay : .direct
            settings.clientConnected = true
            settings.internetErrorMessage = nil
            settings.internetRecoverySuggestion = nil
            screenCapture?.requestKeyframeOrReplayCachedFrame(force: true)
        case .recovering:
            if internetProductSession != nil { fileTransferController?.unbind() }
            settings.internetStatus = .recovering
            settings.clientConnected = false
        case .failed(let reason):
            if internetProductSession != nil { fileTransferController?.unbind() }
            settings.internetStatus = .failed
            settings.internetErrorMessage = reason
            settings.clientConnected = false
        case .revoked:
            if internetProductSession != nil { fileTransferController?.unbind() }
            settings.internetStatus = .revoked
            settings.clientConnected = false
        case .closed:
            if internetProductSession != nil { fileTransferController?.unbind() }
            settings.clientConnected = false
            if settings.internetStatus != .recovering,
               settings.internetStatus != .revoked,
               settings.internetStatus != .failed {
                settings.internetStatus = internetPairingMetadataIsComplete
                    ? .paired
                    : .idle
            }
        }
    }

    private func internetRecoverySuggestion(
        for error: InternetProductSessionError
    ) -> String {
        switch error {
        case .revoked:
            return "The revoked device ID and key cannot be reused. Pair a newly generated device identity."
        case .invalidConfiguration:
            return "Check the local development profile and issue fresh credentials."
        case .protocolFailure:
            return "Confirm both apps support Protocol v1 application-record encryption for this development preview and pair again."
        case .transportFailure:
            return "Check signaling/TURN reachability. A network handoff requires a fresh session profile."
        case .securityFailure:
            return "Pair again and issue a fresh session; plaintext fallback is disabled."
        }
    }

    /// Idempotent cleanup used for both normal shutdown and a failure after any
    /// partial combination of display, capture, listener, or ADB setup.
    private func teardownStreamingComponents() async {
        clipboardController?.unbind()
        fileTransferController?.unbind()
        if let teardownTask {
            await teardownTask.value
            return
        }

        internetControllerInputRoute?.invalidate()
        internetControllerInputRoute = nil
        cancelSessionInput(releaseDrag: true)
        reportWindowRecovery(windowRecoveryManager.restoreManagedWindows())
        let captureToStop = screenCapture
        captureToStop?.onTerminalCaptureFailure = nil
        let serverToStop = streamingServer
        let internetSessionToStop = internetProductSession
        let displayToDestroy = virtualDisplayManager
        screenCapture = nil
        streamingServer = nil
        internetSessionLeaseDeliveryLifecycle.reset()
        internetProductSession = nil
        virtualDisplayManager = nil
        activeDisplayID = nil
        settings.internetAdaptiveMediaControl = .inactive
        let task = Task { @MainActor in
            internetSessionToStop?.close()
            await HostTeardownOrdering.perform(
                stopListener: { serverToStop?.stop() },
                stopCapture: { await captureToStop?.stopStreaming() },
                destroyDisplay: { displayToDestroy?.destroyDisplay() }
            )
        }
        teardownTask = task
        await task.value
        teardownTask = nil
    }

    /// Serializes runtime display switches so overlapping client taps cannot
    /// interleave two capture rebuilds on the same server/session.
    private var displaySwitchInFlight = false
    /// Latest switch target requested while a switch is already running. Only
    /// the newest pending target is kept: intermediate taps are superseded, so
    /// the device/host stays a single serial resource without an unbounded
    /// backlog.
    private var pendingDisplaySwitchTarget: DisplaySwitchTarget?

    /// Switch the capture source to a client-selected display in place, then
    /// drive the Protocol v1 re-negotiation on the same session so the client
    /// re-negotiates video for the new geometry. Both directions
    /// (physical <-> virtual extended) keep one StreamingServer and one
    /// Protocol v1 session alive: the server is never rebuilt, so no media can
    /// escape to the client before it accepts the new VideoConfig. An offline
    /// or non-numeric id is ignored, keeping the switch safe; the session gate
    /// already rejected unknown ids before streaming.
    /// Apply client-driven video preferences to the host encoder settings. The
    /// session clamped the values. This applies them to the live encoder and
    /// capture pipeline FIRST, then confirms the request so the session emits
    /// the bumped-epoch VideoConfig only after the encoder actually adopted the
    /// settings. The confirmed numeric values are also persisted for future
    /// sessions. bitrate arrives in kbps; the encoder is driven in whole Mbps,
    /// so the request is quantized to Mbps and the confirmed kbps is derived
    /// from that Mbps value, guaranteeing the advertised VideoConfig equals what
    /// the encoder runs. A quality preset or reset-to-auto is honored only when
    /// no explicit bitrate was requested, matching the session apply contract.
    @MainActor
    private func applyClientVideoPreferences(
        token: UInt64,
        bitrateKbps: UInt32,
        framesPerSecond: UInt32,
        qualityPreset: VSVideoQualityPreset,
        resetQualityToAuto: Bool,
        server: StreamingServer
    ) {
        // Quantize to whole Mbps (round to nearest, minimum 1) because the
        // encoder only accepts Mbps. The confirmed kbps is derived from this so
        // advertised == applied.
        let bitrateMbps = max(1, Int((bitrateKbps + 500) / 1_000))
        let appliedBitrateKbps = UInt32(bitrateMbps * 1_000)
        let appliedFps = Int(framesPerSecond)

        let appliedQuality: String
        if resetQualityToAuto {
            appliedQuality = Self.defaultEncoderQuality
        } else {
            appliedQuality = switch qualityPreset {
            case .smooth: "low"
            case .balanced: "medium"
            case .sharp: "high"
            default: settings.quality
            }
        }

        // Apply the complete request as one encoder transaction before changing
        // published UI state or acknowledging the protocol request. A failure
        // keeps both the old encoder configuration and the active session.
        guard !settings.gamingBoost,
              screenCapture?.updateEncoderSettings(
                bitrateMbps: bitrateMbps,
                quality: appliedQuality,
                gamingBoost: false,
                frameRate: appliedFps
              ) == true else {
            server.completeProtocolV1VideoPreferences(
                token: token,
                accepted: false,
                appliedBitrateKbps: UInt32(settings.effectiveBitrate * 1_000),
                appliedFramesPerSecond: UInt32(settings.refreshRate)
            )
            return
        }

        isApplyingClientVideoPreferences = true
        if settings.quality != appliedQuality { settings.quality = appliedQuality }
        if settings.bitrate != bitrateMbps { settings.bitrate = bitrateMbps }
        if settings.refreshRate != appliedFps { settings.refreshRate = appliedFps }
        isApplyingClientVideoPreferences = false

        screenCapture?.updateActiveFrameRate(appliedFps)

        // Persist the encoder's real rates for future sessions at the same
        // MainActor commit point as the UI settings. A stale protocol
        // completion can no longer overwrite this seed.
        server.setProtocolV1VideoRates(
            framesPerSecond: appliedFps,
            bitrateKbps: Int(appliedBitrateKbps)
        )

        // Only after the live pipeline has adopted the settings does the session
        // renegotiate the bumped-epoch VideoConfig, advertising the exact values
        // the encoder now runs.
        // The session already resolved a zero (keep-current) request to the
        // concrete current rate before clamping, so appliedFps is always the
        // real target rate here.
        server.completeProtocolV1VideoPreferences(
            token: token,
            accepted: true,
            appliedBitrateKbps: appliedBitrateKbps,
            appliedFramesPerSecond: UInt32(appliedFps)
        )
    }

    /// The host's default (automatic) encoder quality, restored when a client
    /// asks to reset quality to auto.
    private static let defaultEncoderQuality = "ultralow"

    /// Run a client-invoked host action on the main actor by reusing the same
    /// WindowRecoveryManager that backs the status-menu window migration, then
    /// report the outcome back over the session FIFO. Reusing the manager keeps
    /// a single source of truth for which windows were moved, so the client's
    /// "return moved windows" and the automatic disconnect recovery restore the
    /// exact same set. Errors surface the manager's localizedDescription so the
    /// client can present an actionable message.
    private func handleClientHostAction(
        _ actionID: String,
        invocationID: Data,
        server: StreamingServer
    ) {
        func report(accepted: Bool, reason: String) {
            server.completeProtocolV1HostAction(
                invocationID: invocationID,
                accepted: accepted,
                rejectionReason: reason
            )
        }
        switch actionID {
        case ProtocolV1SessionCoordinator.moveWindowActionID:
            guard let activeDisplayID else {
                report(accepted: false, reason: "Start streaming before moving a window.")
                return
            }
            do {
                try windowRecoveryManager.moveFocusedWindow(to: activeDisplayID)
                debugLog("Moved focused window to client display \(activeDisplayID) for client request")
                report(accepted: true, reason: "")
            } catch {
                debugLog("Client move-window action failed: \(error.localizedDescription)")
                report(accepted: false, reason: error.localizedDescription)
            }
        case ProtocolV1SessionCoordinator.returnWindowsActionID:
            let recovery = windowRecoveryManager.restoreManagedWindows()
            reportWindowRecovery(recovery)
            if recovery.failedDescriptions.isEmpty {
                report(accepted: true, reason: "")
            } else {
                report(
                    accepted: false,
                    reason: recovery.failedDescriptions.joined(separator: "; ")
                )
            }
        default:
            report(accepted: false, reason: "Unknown host action.")
        }
    }

    private func handleClientDisplaySelection(
        _ requestedDisplayID: String,
        server: StreamingServer
    ) {
        // The virtual extended chip is advertised either with its stable
        // synthetic id (while a physical display is captured) or with the real
        // numeric id of the live virtual display (while it is captured). Treat
        // both as a request for the extended source.
        // Keep one managed virtual display alive for the whole host session.
        // Its catalog id must remain selectable after temporarily capturing a
        // physical display; destroying it here leaves clients holding an offline
        // id and lets protocol state diverge from the actual capture source.
        let activeVirtualID = virtualDisplayManager?.displayID
        let selectsVirtual = requestedDisplayID == Self.virtualExtendedDisplaySyntheticID
            || (activeVirtualID.map { requestedDisplayID == String($0) } ?? false)

        if selectsVirtual {
            guard VirtualDisplayPrivateAPICapability.evaluate().isAvailable else {
                debugLog("Client requested the virtual display but the private API is unavailable; ignoring")
                return
            }
            if settings.displaySource == .extended {
                debugLog("Client re-selected the already-active virtual display; no switch needed")
                return
            }
            enqueueDisplaySwitch(target: .virtual, server: server)
            return
        }

        guard let numericID = UInt32(requestedDisplayID) else {
            debugLog("Ignoring client display selection with non-numeric id \(requestedDisplayID)")
            return
        }
        guard let resolved = DisplayCatalog.onlineDisplays().first(where: { $0.id == numericID }) else {
            debugLog("Client selected an offline display \(requestedDisplayID); ignoring")
            return
        }
        if settings.displaySource != .extended, activeDisplayID == resolved.id {
            debugLog("Client re-selected the already-active physical display \(resolved.id); no switch needed")
            return
        }
        enqueueDisplaySwitch(target: .physical(resolved.id), server: server)
    }

    private enum DisplaySwitchTarget: Equatable {
        case virtual
        case physical(CGDirectDisplayID)
    }

    /// Serialize switches: only one capture rebuild runs at a time. A tap that
    /// arrives mid-switch is coalesced into a single pending follow-up (only the
    /// newest is kept) and applied once the current switch completes, so the
    /// device/host stays a single serial resource.
    private func enqueueDisplaySwitch(target: DisplaySwitchTarget, server: StreamingServer) {
        guard !displaySwitchInFlight else {
            debugLog("Display switch already in flight; coalescing latest request")
            pendingDisplaySwitchTarget = target
            return
        }
        displaySwitchInFlight = true
        Task { @MainActor in
            await self.switchCaptureSourceInPlace(target: target, server: server)
            self.displaySwitchInFlight = false
            if let pending = self.pendingDisplaySwitchTarget {
                self.pendingDisplaySwitchTarget = nil
                self.enqueueDisplaySwitch(target: pending, server: server)
            }
        }
    }

    /// Perform the in-place capture switch and Protocol v1 re-negotiation. The
    /// order matters: capture is re-pointed first, host runtime bookkeeping is
    /// reconciled (so the settings Combine observers cannot schedule a
    /// competing full reconfiguration that would rebuild the server), the
    /// server's advertised catalog/video config is refreshed to mark the newly
    /// captured display active, and finally the session epoch is bumped and
    /// gated on the new VideoConfig.
    private func switchCaptureSourceInPlace(
        target: DisplaySwitchTarget,
        server: StreamingServer
    ) async {
        guard let capture = screenCapture,
              streamingServer === server,
              let baseConfiguration = activeRuntimeConfiguration else {
            debugLog("Display switch skipped: capture/server/configuration unavailable")
            return
        }

        let size = baseConfiguration.resolutionSize(rotation: settings.rotation)
        let newDisplaySource: DisplaySourceMode
        let captureDisplayID: CGDirectDisplayID
        let streamSize: (width: Int, height: Int)
        let followsMain: Bool
        let outputSize: (width: Int, height: Int)?
        var newSelectedDisplayID = settings.selectedDisplayID
        let previousVirtualManager = virtualDisplayManager
        // Track a virtual display created during this switch so an early throw
        // (before it is promoted to virtualDisplayManager) still tears it down
        // instead of leaving it registered with WindowServer.
        var createdVirtualManager: VirtualDisplayManager?

        do {
            switch target {
            case .virtual:
                let manager: VirtualDisplayManager
                let createdID: CGDirectDisplayID
                if let existing = previousVirtualManager,
                   let existingID = existing.displayID,
                   existing.verifyDisplayRegistered() {
                    manager = existing
                    createdID = existingID
                    debugLog("Reusing managed virtual display \(existingID) for capture switch")
                } else {
                    previousVirtualManager?.destroyDisplay()
                    let created = VirtualDisplayManager()
                    createdVirtualManager = created
                    try created.createDisplay(
                        width: size.width,
                        height: size.height,
                        refreshRate: settings.effectiveRefreshRate,
                        hiDPI: settings.hiDPI,
                        name: "Vibe Screen"
                    )
                    manager = created
                    createdID = try await prepareExtendedVirtualDisplay(created)
                }
                manager.restoreDisplayPosition()
                if !manager.verifyDisplayRegistered() {
                    debugLog("WARNING: Virtual display not found in online list after switch — capture may fail")
                }
                virtualDisplayManager = manager
                newDisplaySource = .extended
                captureDisplayID = createdID
                streamSize = size
                followsMain = false
                // The extended source captures the virtual display at its native
                // size; no scaled output override.
                outputSize = nil

            case .physical(let displayID):
                newDisplaySource = .selectedDisplay
                captureDisplayID = displayID
                newSelectedDisplayID = displayID
                streamSize = Self.aspectFitStreamSize(
                    sourceWidth: CGDisplayPixelsWide(displayID),
                    sourceHeight: CGDisplayPixelsHigh(displayID),
                    maximumWidth: size.width,
                    maximumHeight: size.height
                )
                followsMain = false
                outputSize = streamSize
            }

            debugLog("Runtime display switch: source=\(newDisplaySource.rawValue) captureID=\(captureDisplayID) stream=\(streamSize.width)x\(streamSize.height)")

            try await capture.switchCapturedDisplay(
                to: captureDisplayID,
                refreshRate: settings.effectiveRefreshRate,
                outputSize: outputSize,
                followsMainDisplay: followsMain
            )
        } catch {
            debugLog("Runtime display switch failed: \(error.localizedDescription)")
            // Roll back a freshly created virtual display so we do not leak it,
            // keyed off the local instance rather than the property (which may
            // not have been promoted yet when the throw happened).
            if let created = createdVirtualManager {
                created.destroyDisplay()
                if virtualDisplayManager === created {
                    virtualDisplayManager = previousVirtualManager
                }
            }
            return
        }

        // Keep the managed virtual display registered while capturing a physical
        // source. Clients retain its catalog id and can switch back in place;
        // stopServer remains the single teardown owner.

        activeDisplayID = captureDisplayID

        // Reconcile host runtime state so the settings observers see the switch
        // as already-applied. recordApplied() runs before the @Published writes
        // so the resulting reconfiguration intent equals the applied config and
        // the coordinator does not stop/rebuild the server.
        let switchedConfiguration: HostRuntimeConfiguration
        switch target {
        case .virtual:
            switchedConfiguration = baseConfiguration.updating(displaySource: .extended)
        case .physical(let displayID):
            switchedConfiguration = baseConfiguration
                .updating(displaySource: .selectedDisplay)
                .updatingSelectedDisplay(
                    id: displayID,
                    persistentUUID: DisplayCatalog.persistentUUID(for: displayID)
                )
        }
        activeRuntimeConfiguration = switchedConfiguration
        reconfigurationCoordinator.recordApplied(switchedConfiguration)
        settings.displaySource = newDisplaySource
        if newDisplaySource == .selectedDisplay {
            settings.selectedDisplayID = newSelectedDisplayID
        }

        // Refresh what the server advertises for the new capture so future
        // ListDisplays requests and any reconnect negotiate against the source
        // that is now actually captured.
        server.setDisplaySize(
            width: streamSize.width,
            height: streamSize.height,
            rotation: settings.rotation
        )
        server.setProtocolV1VideoConfiguration(
            framesPerSecond: settings.effectiveRefreshRate,
            bitrateKbps: settings.effectiveBitrate * 1_000,
            displayID: String(captureDisplayID),
            displayName: protocolV1DisplayName(
                displayID: captureDisplayID,
                isVirtual: newDisplaySource == .extended
            ),
            isVirtual: newDisplaySource == .extended || newDisplaySource == .mirrorMain
        )
        server.setProtocolV1Displays(
            protocolV1DisplayCatalog(
                activeCaptureID: captureDisplayID,
                activeDisplaySource: newDisplaySource,
                configuredSize: size
            )
        )
        // Do NOT re-run the Protocol v1 StartDisplay/VideoConfig negotiation
        // here. This switch is always driven by a client StartDisplayRequest
        // (the only source of the selectDisplay action that reaches
        // onDisplaySelectionRequested), and the session already answered that
        // request in place with a single StartDisplayResponse + VideoConfig and
        // a bumped config epoch. Calling server.selectProtocolV1Display here
        // would emit a second StartDisplayResponse; by the time it arrived the
        // client had returned to STREAMING and rejected it with
        // INVALID_PEER_MESSAGE ("StartDisplayResponse in state STREAMING"),
        // tearing down the session on the virtual->physical switch. A future
        // GUI/menu-initiated switch that has no client request behind it may
        // still call server.selectProtocolV1Display to drive the client.
    }

    /// Wait for a newly created virtual display to settle before forcing extend mode.
    /// WindowServer can transiently reject mirror configuration while registering it.
    private func prepareExtendedVirtualDisplay(
        _ manager: VirtualDisplayManager
    ) async throws -> CGDirectDisplayID {
        guard let createdID = manager.displayID else {
            throw VirtualDisplayError.creationFailed("Display was created without a display ID")
        }

        let registrationAttemptLimit = 20
        let mirrorAttemptLimit = 10
        let retryDelayNanoseconds: UInt64 = 100_000_000

        var registered = manager.verifyDisplayRegistered()
        var registrationAttempts = 0
        while !registered && registrationAttempts < registrationAttemptLimit {
            try await Task.sleep(nanoseconds: retryDelayNanoseconds)
            registered = manager.verifyDisplayRegistered()
            registrationAttempts += 1
        }
        if !registered {
            debugLog("WARNING: Virtual display \(createdID) not online after settle; proceeding may fail")
        }

        var mirrorDisabled = false
        var mirrorAttempts = 0
        var lastMirrorError: Error?
        while !mirrorDisabled && mirrorAttempts < mirrorAttemptLimit {
            do {
                try manager.disableMirrorMode()
                mirrorDisabled = true
            } catch {
                lastMirrorError = error
                try await Task.sleep(nanoseconds: retryDelayNanoseconds)
                mirrorAttempts += 1
            }
        }
        if !mirrorDisabled {
            // Fresh virtual displays are not mirrored unless the mirror source
            // explicitly configured them. A transient disable failure is safe
            // only when WindowServer confirms this display is not in a mirror set.
            if CGDisplayIsInMirrorSet(createdID) != 0 {
                throw lastMirrorError ?? VirtualDisplayError.mirrorModeFailed(
                    "Failed to disable mirror mode"
                )
            }
            debugLog(
                "disableMirrorMode did not complete but display \(createdID) is not mirrored; " +
                "proceeding with extended capture"
            )
        }
        return createdID
    }

    /// Build the ListDisplays catalog advertised for the current capture. Every
    /// online physical display is included with its real numeric id. When the
    /// private virtual-display API is available, one virtual extended entry is
    /// appended so a single-physical-display Mac still offers a second chip:
    /// while a physical display is captured the entry carries the stable
    /// synthetic id; while the virtual display is captured it carries the live
    /// numeric id so the active descriptor matches the streamed identity.
    private func protocolV1DisplayCatalog(
        activeCaptureID: CGDirectDisplayID,
        activeDisplaySource: DisplaySourceMode,
        configuredSize: (width: Int, height: Int)
    ) -> [ProtocolV1DisplayInfo] {
        let managedVirtualID = virtualDisplayManager?.displayID
        var catalog = DisplayCatalog.onlineDisplays().compactMap { display -> ProtocolV1DisplayInfo? in
            // The managed virtual display is present in the online display list
            // even while a physical source is captured. Advertise it exactly once
            // below with its virtual semantics and stable live id.
            if display.id == managedVirtualID ||
                (activeDisplaySource == .extended && display.id == activeCaptureID) {
                return nil
            }
            return ProtocolV1DisplayInfo(
                id: String(display.id),
                name: display.name,
                width: display.width,
                height: display.height,
                isPrimary: display.isMain,
                isVirtual: false
            )
        }
        guard VirtualDisplayPrivateAPICapability.evaluate().isAvailable else {
            return catalog
        }
        let capturingVirtual = activeDisplaySource == .extended
        let virtualID = managedVirtualID.map(String.init)
            ?? (capturingVirtual ? String(activeCaptureID) : Self.virtualExtendedDisplaySyntheticID)
        let managedVirtualBounds = managedVirtualID.map(CGDisplayBounds)
        let virtualWidth = Int(managedVirtualBounds?.width ?? 0) > 0
            ? Int(managedVirtualBounds?.width ?? 0)
            : (configuredSize.width > 0 ? configuredSize.width : Self.virtualExtendedDefaultWidth)
        let virtualHeight = Int(managedVirtualBounds?.height ?? 0) > 0
            ? Int(managedVirtualBounds?.height ?? 0)
            : (configuredSize.height > 0 ? configuredSize.height : Self.virtualExtendedDefaultHeight)
        catalog.append(
            ProtocolV1DisplayInfo(
                id: virtualID,
                name: Self.virtualExtendedDisplayName,
                width: virtualWidth,
                height: virtualHeight,
                isPrimary: false,
                isVirtual: true
            )
        )
        // ListDisplays has no separate active-display field. Preserve a clear
        // wire contract by placing the display currently being captured first;
        // clients select this entry initially while `isPrimary` keeps its macOS
        // main-display meaning for presentation.
        if let activeIndex = catalog.firstIndex(where: { $0.id == String(activeCaptureID) }),
           activeIndex != catalog.startIndex {
            catalog.insert(catalog.remove(at: activeIndex), at: catalog.startIndex)
        }
        return catalog
    }

    private func protocolV1DisplayName(
        displayID: CGDirectDisplayID,
        isVirtual: Bool
    ) -> String {
        if isVirtual { return Self.virtualExtendedDisplayName }
        return DisplayCatalog.onlineDisplays().first(where: { $0.id == displayID })?.name
            ?? "Display \(displayID)"
    }

    private func handleServerFailure(sessionToken: UInt64) async {
        guard serverLifecycle.ownsSession(sessionToken) else { return }
        let stopResult = await stopServer(
            preserveRecoveryState: true,
            suppressesFollowUp: false
        )
        guard canApplyStopFollowUp(result: stopResult) else { return }
        scheduleUnattendedRecoveryIfEnabled()
    }

    private func handleCaptureFailure(_ error: Error, sessionToken: UInt64) async {
        guard serverLifecycle.ownsSession(sessionToken) else { return }
        let selectedDisplayWentOffline = settings.displaySource == .selectedDisplay &&
            DisplayCatalog.resolve(
                persistentUUID: settings.selectedDisplayUUID,
                fallbackID: settings.selectedDisplayID
            ) != activeDisplayID
        let stopResult = await stopServer(
            preserveRecoveryState: true,
            suppressesFollowUp: false
        )
        guard canApplyStopFollowUp(result: stopResult) else { return }
        if selectedDisplayWentOffline {
            debugLog("Selected display went offline; preserving selection and falling back to main display")
            requestServerStart(origin: .recovery)
        } else if isUnattendedOperation {
            scheduleUnattendedRecoveryIfEnabled()
        } else {
            let alert = NSAlert()
            alert.messageText = "Display Capture Stopped"
            alert.informativeText = error.localizedDescription
            alert.alertStyle = .critical
            alert.runModal()
        }
    }

    private var isHeadlessBenchmark: Bool {
        CommandLine.arguments.contains("--headless-benchmark")
    }

    private var isUnattendedOperation: Bool {
        isHeadlessBenchmark ||
            settings.hideDockIcon ||
            (settings.hasCompletedOnboarding && DaemonManager.shared.isEnabled)
    }

    private func scheduleUnattendedRecoveryIfEnabled(
        allowAutomaticLaunch: Bool = false
    ) {
        guard HostStartupPolicy.shouldRecover(
                autoStartEnabled: settings.autoStartStreamingOnLaunch,
                hasScreenRecordingPermission: settings.hasScreenRecordingPermission,
                hasCompletedOnboarding: settings.hasCompletedOnboarding,
                explicitHeadlessBenchmark: isHeadlessBenchmark,
                isUnattendedOperation: isUnattendedOperation || allowAutomaticLaunch
              ),
              let delay = UnattendedRecoveryPolicy.delay(
                afterFailure: unattendedRecoveryAttempt
              ) else {
            debugLog("Unattended recovery stopped after \(unattendedRecoveryAttempt) attempt(s)")
            return
        }
        unattendedRecoveryAttempt += 1
        unattendedRecoveryTask?.cancel()
        debugLog("Scheduling unattended host recovery in \(Int(delay))s")
        unattendedRecoveryTask = Task { @MainActor [weak self] in
            do {
                try await Task.sleep(
                    nanoseconds: UInt64(delay * 1_000_000_000)
                )
                guard let self,
                      self.serverLifecycle.canStart,
                      HostStartupPolicy.shouldRecover(
                        autoStartEnabled: self.settings.autoStartStreamingOnLaunch,
                        hasScreenRecordingPermission: self.settings.hasScreenRecordingPermission,
                        hasCompletedOnboarding: self.settings.hasCompletedOnboarding,
                        explicitHeadlessBenchmark: self.isHeadlessBenchmark,
                        isUnattendedOperation:
                            self.isUnattendedOperation || allowAutomaticLaunch
                      ) else { return }
                self.requestServerStart(origin: .recovery)
            } catch is CancellationError {
                return
            } catch {
                debugLog("Unattended recovery wait failed: \(error.localizedDescription)")
            }
        }
    }

    /// Scale an existing display into the requested stream bounds without
    /// stretching it. VideoToolbox requires even dimensions for reliable
    /// hardware H.264/HEVC operation, so both axes are rounded down to even.
    nonisolated static func aspectFitStreamSize(
        sourceWidth: Int,
        sourceHeight: Int,
        maximumWidth: Int,
        maximumHeight: Int
    ) -> (width: Int, height: Int) {
        guard sourceWidth > 0, sourceHeight > 0, maximumWidth > 0, maximumHeight > 0 else {
            return (max(2, maximumWidth & ~1), max(2, maximumHeight & ~1))
        }

        let scale = min(
            1.0,
            Double(maximumWidth) / Double(sourceWidth),
            Double(maximumHeight) / Double(sourceHeight)
        )
        let fittedWidth = max(2, Int(floor(Double(sourceWidth) * scale)) & ~1)
        let fittedHeight = max(2, Int(floor(Double(sourceHeight) * scale)) & ~1)
        return (fittedWidth, fittedHeight)
    }

    func stopServer() async {
        await stopServer(preserveRecoveryState: false)
    }

    @discardableResult
    private func stopServer(
        preserveRecoveryState: Bool,
        recordsManualStop: Bool = true,
        suppressesFollowUp: Bool? = nil
    ) async -> HostStopOperationCoordinator.Result {
        stopRecoveryPreservation.request(
            preserveRecoveryState: preserveRecoveryState
        )
        stopFollowUpSuppression.request(
            suppressFollowUp: suppressesFollowUp ?? recordsManualStop
        )
        if !preserveRecoveryState {
            cancelUnattendedRecovery(resetAttempts: true)
        }
        if recordsManualStop {
            reconfigurationCoordinator.recordManualStop()
            settings.isStarting = false
        }
        var stopToken: UInt64?
        var shouldPreserveRecoveryState = false
        var shouldSuppressFollowUp = false
        let result = await stopOperationCoordinator.perform({
            stopToken = self.serverLifecycle.beginStop()
            if self.activeRuntimeConfiguration?.displaySource == .extended {
                self.virtualDisplayManager?.saveDisplayPosition()
            }
            await self.teardownStreamingComponents()
            self.activeRuntimeConfiguration = nil
            shouldPreserveRecoveryState = self.stopRecoveryPreservation.consume()
            shouldSuppressFollowUp = self.stopFollowUpSuppression.consume()
        }, finalize: { generation in
            guard let stopToken else { return }
            self.settings.isRunning = false
            self.settings.isStarting = self.reconfigurationCoordinator.hasDesiredRunning
            self.settings.displayCreated = false
            self.settings.clientConnected = false
            self.settings.connectedDeviceModel = nil
            self.settings.connectedDeviceMaxRefreshRate = nil
            self.settings.metrics.reset()
            self.serverLifecycle.finishStop(stopToken)
            if !shouldPreserveRecoveryState,
               self.settings.connectionMode == .internet,
               self.settings.internetStatus != .revoked {
                self.settings.internetStatus = self.internetPairingMetadataIsComplete
                    ? .paired
                    : .idle
            }
            self.lastSuppressedStopFollowUpGeneration = shouldSuppressFollowUp
                ? generation
                : nil
            self.lastCompletedStopGeneration = generation
            print("⏹️ Server stopped")
        })
        return result
    }

    private func canApplyStopFollowUp(
        result: HostStopOperationCoordinator.Result,
        permitsDesiredRunning: Bool = false
    ) -> Bool {
        HostStopFollowUpPolicy.shouldApply(
            performedOperation: result.performedOperation,
            requestedGeneration: result.generation,
            lastCompletedGeneration: lastCompletedStopGeneration,
            lifecycleIsIdle: serverLifecycle.canStart,
            hasActiveConfiguration: activeRuntimeConfiguration != nil,
            hasDesiredRunning: reconfigurationCoordinator.hasDesiredRunning,
            followUpWasSuppressed:
                lastSuppressedStopFollowUpGeneration == result.generation,
            permitsDesiredRunning: permitsDesiredRunning
        )
    }

    private func cancelUnattendedRecovery(resetAttempts: Bool) {
        unattendedRecoveryTask?.cancel()
        unattendedRecoveryTask = nil
        if resetAttempts {
            unattendedRecoveryAttempt = 0
        }
    }

    // MARK: - Gesture Properties

    private let gestureEvents = TouchGestureEventFactory()
    private var accessibilityWarningShown = false
    private var gestureState: GestureState = .idle
    private var lastTouchTime: UInt64 = 0

    // Touch tracking
    private var touchStartPosition: CGPoint = .zero
    private var touchLastPosition: CGPoint = .zero
    private var touchStartTime: UInt64 = 0
    private var touchLastMoveTime: UInt64 = 0
    private var lastScrollDeltaX: CGFloat = 0
    private var lastScrollDeltaY: CGFloat = 0

    // Double tap tracking
    private var lastTapTime: UInt64 = 0
    private var lastTapPosition: CGPoint = .zero

    // Long press timer
    private var longPressTimer: DispatchWorkItem?

    // 2-finger tracking
    private var initialPinchDistance: CGFloat = 0
    private var lastPinchDistance: CGFloat = 0

    // Momentum scrolling
    private var momentumTimer: Timer?
    private var momentumVelocityX: CGFloat = 0
    private var momentumVelocityY: CGFloat = 0
    private var lastMomentumPosition: CGPoint = .zero

   // MARK: - Touch Entry Point

    /// Shared Accessibility gate for native pointer/keyboard injection. Logs
    /// once when denied and points the user at the correct System Settings pane.
    private func nativeInputAccessibilityGranted() -> Bool {
        if AXIsProcessTrusted() { return true }
        if !accessibilityWarningShown {
            accessibilityWarningShown = true
            print("⚠️  Accessibility not granted - native pointer/keyboard input ignored. " +
                  "Enable Vibe Screen under System Settings › Privacy & Security › Accessibility.")
            settings.hasAccessibilityPermission = false
        }
        return false
    }

    /// Resolves the bounds of the currently captured display, matching the
    /// touch path (activeDisplayID -> CGDisplayBounds).
    private func activeDisplayBounds() -> CGRect? {
        guard let activeDisplayID else { return nil }
        return CGDisplayBounds(activeDisplayID)
    }

    // MARK: - Native Pointer / Scroll / Keyboard Entry Points

    @discardableResult
    func handleClientPointer(x: Float, y: Float, phase: VSInputPhase, buttonMask: UInt32) -> Bool {
        guard settings.touchEnabled else { return false }
        guard nativeInputAccessibilityGranted() else { return false }
        guard let bounds = activeDisplayBounds() else { return false }
        let injected = streamInputInjector.handlePointer(
            normalizedX: x, normalizedY: y, phase: phase,
            buttonMask: buttonMask, displayBounds: bounds
        )
        if injected {
            debugLog("Pointer injected: phase=\(phase) buttons=\(buttonMask) x=\(x) y=\(y)")
        }
        return injected
    }

    @discardableResult
    func handleClientStylus(
        inputID: UInt64,
        pointerID: UInt32,
        x: Float,
        y: Float,
        phase: VSInputPhase,
        pressure: Double,
        tiltXDegrees: Double,
        tiltYDegrees: Double,
        toolKind: VSStylusToolKind = .pen,
        buttonMask: UInt32 = 0,
        contactState: VSStylusContactState = .contact
    ) -> Bool {
        guard settings.touchEnabled else { return false }
        guard contactState != .contact
                || primaryButtonOwner.canHandleStylus(pointerID: pointerID, phase: phase) else {
            return false
        }
        guard nativeInputAccessibilityGranted() else { return false }
        guard let bounds = activeDisplayBounds() else { return false }
        let injected = streamInputInjector.handleStylus(
            pointerID: pointerID,
            normalizedX: x,
            normalizedY: y,
            phase: phase,
            pressure: pressure,
            tiltXDegrees: tiltXDegrees,
            tiltYDegrees: tiltYDegrees,
            toolKind: toolKind,
            buttonMask: buttonMask,
            contactState: contactState,
            displayBounds: bounds
        )
        if injected {
            if contactState == .contact && phase == .began {
                cancelLongPressTimer()
                gestureState = .idle
            }
            if contactState == .contact {
                primaryButtonOwner.didHandleStylus(pointerID: pointerID, phase: phase)
            }
            debugLog(
                "Stylus injected: input=\(inputID) pointer=\(pointerID) "
                    + "phase=\(phase) contact=\(contactState) tool=\(toolKind) "
                    + "buttons=\(buttonMask) pressure=\(pressure) "
                    + "tiltX=\(tiltXDegrees) tiltY=\(tiltYDegrees)"
            )
        }
        return injected
    }

    @discardableResult
    func handleClientScroll(deltaX: Double, deltaY: Double) -> Bool {
        guard settings.touchEnabled else { return false }
        guard nativeInputAccessibilityGranted() else { return false }
        let injected = streamInputInjector.handleScroll(deltaX: deltaX, deltaY: deltaY)
        if injected {
            debugLog("Scroll injected: dx=\(deltaX) dy=\(deltaY)")
        }
        return injected
    }

    @discardableResult
    func handleClientKey(usage: UInt32, pressed: Bool, modifiers: UInt32) -> Bool {
        guard settings.touchEnabled else { return false }
        guard nativeInputAccessibilityGranted() else { return false }
        let injected = streamInputInjector.handleKey(
            usbHIDUsage: usage, pressed: pressed, modifierMask: modifiers
        )
        if injected {
            debugLog("Key injected: hid=\(usage) pressed=\(pressed) modifiers=\(modifiers)")
        } else {
            debugLog("Key unmapped (dropped): hid=\(usage)")
        }
        return injected
    }

   @discardableResult
   func handleTouch(x: Float, y: Float, action: Int, pointerCount: Int = 1, x2: Float = 0, y2: Float = 0) -> Bool {
        guard settings.touchEnabled else { return false }
        if case .stylus = primaryButtonOwner.owner { return false }

        if !AXIsProcessTrusted() {
            if !accessibilityWarningShown {
                accessibilityWarningShown = true
                print("⚠️  Accessibility not granted - touch ignored")
                Task { @MainActor in
                    settings.hasAccessibilityPermission = false
                }
            }
            cancelActiveInput(releaseDrag: false)
            return false
        }

        guard let displayID = activeDisplayID,
              pointerCount == 1 || pointerCount == 2,
              (0...2).contains(action) else {
            cancelActiveInput(releaseDrag: true)
            return false
        }
        let bounds = CGDisplayBounds(displayID)

        guard let p1 = StreamInputMapper.point(
            normalizedX: x,
            normalizedY: y,
            in: bounds
        ) else {
            cancelActiveInput(releaseDrag: true)
            return false
        }

        if pointerCount >= 2 {
            guard let p2 = StreamInputMapper.point(
                normalizedX: x2,
                normalizedY: y2,
                in: bounds
            ) else {
                cancelActiveInput(releaseDrag: true)
                return false
            }
            handleTwoFingerTouch(p1: p1, p2: p2, action: action)
        } else {
            handleOneFingerTouch(at: p1, action: action)
        }
        return true
    }

    // MARK: - 1-Finger Gesture State Machine

    private func handleOneFingerTouch(at point: CGPoint, action: Int) {
        switch action {
        case 0: oneFingerDown(at: point)
        case 1: oneFingerMove(to: point)
        case 2: oneFingerUp(at: point)
        default: break
        }
    }

    private func oneFingerDown(at point: CGPoint) {
        stopMomentumScroll()
        cancelLongPressTimer()

        touchStartPosition = point
        touchLastPosition = point
        touchStartTime = DispatchTime.now().uptimeNanoseconds
        touchLastMoveTime = touchStartTime
        gestureState = .pending

        // Move cursor to touch position (absolute)
        moveCursor(to: point)

        // Start long press timer
        let timer = DispatchWorkItem { [weak self] in
            guard let self, self.gestureState == .pending else { return }
            self.gestureState = .longPressReady
            debugLog("Touch gesture: long press ready")
        }
        longPressTimer = timer
        DispatchQueue.main.asyncAfter(
            deadline: .now() + .nanoseconds(Int(GestureThresholds.longPressTime)),
            execute: timer
        )
    }

    private func oneFingerMove(to point: CGPoint) {
        let now = DispatchTime.now().uptimeNanoseconds
        if now - lastTouchTime < GestureThresholds.minTouchInterval { return }
        lastTouchTime = now

        let deltaX = point.x - touchLastPosition.x
        let deltaY = point.y - touchLastPosition.y
        let totalDistance = hypot(point.x - touchStartPosition.x, point.y - touchStartPosition.y)

        switch gestureState {
        case .pending:
            if totalDistance > GestureThresholds.tapMaxDistance {
                cancelLongPressTimer()
                gestureState = .scrolling
                let sx = deltaX * GestureThresholds.scrollSensitivity
                let sy = deltaY * GestureThresholds.scrollSensitivity
                injectScrollEvent(deltaX: sx, deltaY: sy, at: point)
                lastScrollDeltaX = sx
                lastScrollDeltaY = sy
            }

        case .longPressReady:
            if totalDistance > GestureThresholds.tapMaxDistance {
                // Long press + drag → left mouse drag
                guard primaryButtonOwner.beginTouchDrag() else {
                    gestureState = .idle
                    return
                }
                gestureState = .dragging
                injectMouseDown(at: touchStartPosition)
                injectMouseDragged(to: point)
                debugLog("Touch gesture: drag began")
            }

        case .scrolling:
            let sx = deltaX * GestureThresholds.scrollSensitivity
            let sy = deltaY * GestureThresholds.scrollSensitivity
            injectScrollEvent(deltaX: sx, deltaY: sy, at: point)
            let timeDelta = now - touchLastMoveTime
            if timeDelta > 0 && timeDelta < 100_000_000 {
                lastScrollDeltaX = sx
                lastScrollDeltaY = sy
            }

        case .dragging:
            injectMouseDragged(to: point)

        default:
            break
        }

        touchLastPosition = point
        touchLastMoveTime = now
    }

    private func oneFingerUp(at point: CGPoint) {
        cancelLongPressTimer()
        let now = DispatchTime.now().uptimeNanoseconds
        let elapsed = now - touchStartTime
        let distance = hypot(point.x - touchStartPosition.x, point.y - touchStartPosition.y)

        switch gestureState {
        case .pending:
            // Quick release, no movement → tap or double tap
            if distance < GestureThresholds.tapMaxDistance && elapsed < GestureThresholds.tapMaxTime {
                // Check double tap
                let timeSinceLastTap = now - lastTapTime
                let distFromLastTap = hypot(point.x - lastTapPosition.x, point.y - lastTapPosition.y)

                if timeSinceLastTap < GestureThresholds.doubleTapMaxTime
                    && distFromLastTap < GestureThresholds.doubleTapMaxDistance {
                    performDoubleClick(at: point)
                    lastTapTime = 0  // Reset so triple tap doesn't trigger
                } else {
                    performClick(at: point)
                    lastTapTime = now
                    lastTapPosition = point
                }
            }

        case .longPressReady:
            // Held long but didn't drag → right click
            performRightClick(at: point)
            debugLog("Touch gesture: right click injected")

        case .scrolling:
            // Check momentum
            let timeSinceLastMove = now - touchLastMoveTime
            if timeSinceLastMove < 50_000_000 {
                let threshold: CGFloat = 2.0
                if abs(lastScrollDeltaX) > threshold || abs(lastScrollDeltaY) > threshold {
                    startMomentumScroll(
                        velocityX: lastScrollDeltaX * 6.0,
                        velocityY: lastScrollDeltaY * 6.0,
                        at: point
                    )
                }
            }

        case .dragging:
            if primaryButtonOwner.endTouchDrag() {
                injectMouseUp(at: point)
                debugLog("Touch gesture: drag ended")
            }

        default:
            break
        }

        gestureState = .idle
    }

    // MARK: - 2-Finger Gestures

    private func handleTwoFingerTouch(p1: CGPoint, p2: CGPoint, action: Int) {
        let distance = hypot(p2.x - p1.x, p2.y - p1.y)
        let midpoint = CGPoint(x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2)

        switch action {
        case 0: // Down
            cancelLongPressTimer()
            stopMomentumScroll()
            gestureState = .idle  // Reset so 2-finger detection starts fresh
            initialPinchDistance = distance
            lastPinchDistance = distance
            touchLastPosition = midpoint

        case 1: // Move
            let distanceChange = abs(distance - initialPinchDistance)
            let midDelta = hypot(midpoint.x - touchLastPosition.x, midpoint.y - touchLastPosition.y)

            // Determine mode if not yet decided
            if gestureState != .twoFingerScroll && gestureState != .pinching {
                if distanceChange > GestureThresholds.pinchMinDistance {
                    gestureState = .pinching
                    debugLog("Touch gesture: pinch began")
                } else if midDelta > GestureThresholds.tapMaxDistance {
                    gestureState = .twoFingerScroll
                    debugLog("Touch gesture: two-finger scroll began")
                }
            }

            switch gestureState {
            case .twoFingerScroll:
                let dx = (midpoint.x - touchLastPosition.x) * GestureThresholds.scrollSensitivity
                let dy = (midpoint.y - touchLastPosition.y) * GestureThresholds.scrollSensitivity
                injectScrollEvent(deltaX: dx, deltaY: dy, at: midpoint)

            case .pinching:
                let scaleDelta = distance - lastPinchDistance
                // Cmd + scroll = zoom in most Mac apps
                let zoomAmount = Int32(scaleDelta * 0.5)
                if zoomAmount != 0 {
                    injectZoomEvent(delta: zoomAmount, at: midpoint)
                }
                lastPinchDistance = distance

            default:
                break
            }

            touchLastPosition = midpoint

        case 2: // Up
            gestureState = .idle
            // Reset 1-finger tracking so leftover moves don't trigger scroll
            touchStartPosition = .zero
            touchLastPosition = .zero

        default:
            break
        }
    }

    // MARK: - Event Injection

    private func moveCursor(to point: CGPoint) {
        if let event = gestureEvents.mouseEvent(type: .mouseMoved, position: point, button: .left) {
            event.post(tap: .cghidEventTap)
        }
    }

    private func performClick(at point: CGPoint) {
        if let down = gestureEvents.mouseEvent(type: .leftMouseDown, position: point, button: .left, clickState: 1) {
            down.post(tap: .cghidEventTap)
        }
        if let up = gestureEvents.mouseEvent(type: .leftMouseUp, position: point, button: .left, clickState: 1) {
            up.post(tap: .cghidEventTap)
        }
    }

    private func performDoubleClick(at point: CGPoint) {
        if let down = gestureEvents.mouseEvent(type: .leftMouseDown, position: point, button: .left, clickState: 2) {
            down.post(tap: .cghidEventTap)
        }
        if let up = gestureEvents.mouseEvent(type: .leftMouseUp, position: point, button: .left, clickState: 2) {
            up.post(tap: .cghidEventTap)
        }
    }

    private func performRightClick(at point: CGPoint) {
        if let down = gestureEvents.mouseEvent(type: .rightMouseDown, position: point, button: .right) {
            down.post(tap: .cghidEventTap)
        }
        if let up = gestureEvents.mouseEvent(type: .rightMouseUp, position: point, button: .right) {
            up.post(tap: .cghidEventTap)
        }
    }

    private func injectMouseDown(at point: CGPoint) {
        if let event = gestureEvents.mouseEvent(type: .leftMouseDown, position: point, button: .left, clickState: 1) {
            event.post(tap: .cghidEventTap)
        }
    }

    private func injectMouseDragged(to point: CGPoint) {
        if let event = gestureEvents.mouseEvent(type: .leftMouseDragged, position: point, button: .left) {
            event.post(tap: .cghidEventTap)
        }
    }

    private func injectMouseUp(at point: CGPoint) {
        if let event = gestureEvents.mouseEvent(type: .leftMouseUp, position: point, button: .left, clickState: 1) {
            event.post(tap: .cghidEventTap)
        }
    }

    private func injectScrollEvent(deltaX: CGFloat, deltaY: CGFloat, at position: CGPoint) {
        guard let scrollEvent = gestureEvents.scrollEvent(
            deltaX: Int32(deltaX),
            deltaY: Int32(deltaY),
            position: position
        ) else { return }
        scrollEvent.post(tap: .cghidEventTap)
    }

    private func injectZoomEvent(delta: Int32, at position: CGPoint) {
        guard let scrollEvent = gestureEvents.scrollEvent(
            deltaX: 0,
            deltaY: delta,
            position: position,
            commandModified: true
        ) else { return }
        scrollEvent.post(tap: .cghidEventTap)
    }

    // MARK: - Long Press Timer

    private func cancelLongPressTimer() {
        longPressTimer?.cancel()
        longPressTimer = nil
    }

    // MARK: - Momentum Scrolling

    private func startMomentumScroll(velocityX: CGFloat, velocityY: CGFloat, at position: CGPoint) {
        stopMomentumScroll()
        momentumVelocityX = velocityX
        momentumVelocityY = velocityY
        lastMomentumPosition = position
        momentumTimer = Timer.scheduledTimer(withTimeInterval: 0.016, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.momentumTick()
            }
        }
    }

    private func momentumTick() {
        let decay: CGFloat = 0.92
        let minVelocity: CGFloat = 0.5

        if abs(momentumVelocityX) < minVelocity && abs(momentumVelocityY) < minVelocity {
            stopMomentumScroll()
            return
        }

        injectScrollEvent(deltaX: momentumVelocityX, deltaY: momentumVelocityY, at: lastMomentumPosition)
        momentumVelocityX *= decay
        momentumVelocityY *= decay
    }

    private func stopMomentumScroll() {
        momentumTimer?.invalidate()
        momentumTimer = nil
        momentumVelocityX = 0
        momentumVelocityY = 0
    }

    private func cancelSessionInput(releaseDrag: Bool) {
        cancelActiveInput(releaseDrag: releaseDrag)
        do {
            try sessionGameControllerInput?.reset()
        } catch {
            debugLog("Virtual controller reset failed: \(error.localizedDescription)")
        }
    }

   private func cancelActiveInput(releaseDrag: Bool) {
       cancelLongPressTimer()
       stopMomentumScroll()
        let owner = primaryButtonOwner.reset()
        if releaseDrag, owner == .touchDrag, AXIsProcessTrusted() {
            injectMouseUp(at: touchLastPosition)
        }
        // Releases a stylus tip or native pointer button when owned there; a
        // touch drag is owned and released exclusively above.
        streamInputInjector.reset()
        gestureState = .idle
        touchStartPosition = .zero
        touchLastPosition = .zero
        touchStartTime = 0
        touchLastMoveTime = 0
        lastScrollDeltaX = 0
        lastScrollDeltaY = 0
        lastTouchTime = 0
        lastTapTime = 0
        lastTapPosition = .zero
        initialPinchDistance = 0
        lastPinchDistance = 0
    }

    func applicationShouldTerminate(
        _ sender: NSApplication
    ) -> NSApplication.TerminateReply {
        switch terminationCoordinator.requestTermination() {
        case .beginDeferredCleanup:
            prepareForTermination()
            Task { @MainActor in
                await self.stopServer()
                self.terminationCoordinator.completeCleanup()
                sender.reply(toApplicationShouldTerminate: true)
            }
            return .terminateLater
        case .waitForDeferredCleanup:
            return .terminateLater
        case .terminateNow:
            return .terminateNow
        }
    }

    private func prepareForTermination() {
        stopMomentumScroll()
        permissionCheckTimer?.invalidate()
        permissionCheckTimer = nil
        statusRefreshTimer?.invalidate()
        statusRefreshTimer = nil
        unattendedRecoveryTask?.cancel()
        unattendedRecoveryTask = nil
        cancellables.removeAll()
    }

    func applicationWillTerminate(_ notification: Notification) {
        // The deferred applicationShouldTerminate path has already awaited the
        // complete server/capture/display teardown before AppKit reaches here.
        prepareForTermination()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }
}
