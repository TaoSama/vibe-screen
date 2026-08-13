import Cocoa
import SwiftUI
import Combine

enum DisplaySourceMode: String, CaseIterable, Identifiable {
    case extended
    case mirrorMain
    case currentMain
    case selectedDisplay

    var id: String { rawValue }
    var title: String {
        switch self {
        case .extended: return "New extended display"
        case .mirrorMain: return "Mirror main display"
        case .currentMain: return "Current Mac display"
        case .selectedDisplay: return "Choose existing display"
        }
    }

    var helpText: String {
        switch self {
        case .extended:
            return "Experimental: uses private macOS APIs to create an additional desktop."
        case .mirrorMain:
            return "Creates a client display that mirrors the current main display."
        case .currentMain:
            return "Follows whichever display macOS currently considers main."
        case .selectedDisplay:
            return "Captures the chosen existing display without creating another desktop."
        }
    }
}

// MARK: - Frosted GroupBox Component

struct FrostedGroupBox<Content: View, Trailing: View>: View {
    let title: String
    var icon: String?
    @ViewBuilder let content: Content
    @ViewBuilder let trailing: Trailing

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                if let icon = icon {
                    Image(systemName: icon)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(.accentColor)
                }
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
                trailing
            }
            content
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(.ultraThinMaterial)
        }
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        }
    }
}

extension FrostedGroupBox where Trailing == EmptyView {
    init(title: String, icon: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.icon = icon
        self.content = content()
        self.trailing = EmptyView()
    }
}

// MARK: - Visual Effect Blur

struct VisualEffectBlur: NSViewRepresentable {
    var material: NSVisualEffectView.Material
    var blendingMode: NSVisualEffectView.BlendingMode
    var state: NSVisualEffectView.State = .active

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = blendingMode
        view.state = state
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
        nsView.blendingMode = blendingMode
        nsView.state = state
    }
}

// MARK: - Settings View

struct SettingsView: View {
    @ObservedObject var settings: DisplaySettings
    @State private var showPermissionAlert = false
    @State private var showResetConfirmation = false
    @State private var headerHovered = false
    // Plain strings for the custom resolution fields: TextField(value:format:)
    // only commits on Return/focus-loss, so clicking Apply read stale values,
    // and .number formatting injected locale grouping separators ("1,200").
    @State private var customWidthText = ""
    @State private var customHeightText = ""
    @State private var daemonEnabled = false
    @State private var daemonStatusGuidance: String?

    private var customWidthValue: Int? { Int(customWidthText.trimmingCharacters(in: .whitespaces)) }
    private var customHeightValue: Int? { Int(customHeightText.trimmingCharacters(in: .whitespaces)) }
    private var customResolutionValid: Bool {
        guard let w = customWidthValue, let h = customHeightValue else { return false }
        return DisplaySettings.isValidCustomResolution(width: w, height: h)
    }

    var body: some View {
        ZStack {
            VisualEffectBlur(material: .sidebar, blendingMode: .behindWindow)
                .ignoresSafeArea()

            VStack(spacing: 0) {
                // Header with frosted glass
                HStack(spacing: 14) {
                    Image(nsImage: NSApplication.shared.applicationIconImage)
                        .resizable()
                        .interpolation(.high)
                        .frame(width: 48, height: 48)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .shadow(color: Color.accentColor.opacity(0.22), radius: 8, y: 4)
                    .scaleEffect(headerHovered ? 1.05 : 1)
                    .animation(.spring(response: 0.3), value: headerHovered)
                    .onHover { headerHovered = $0 }

                    VStack(alignment: .leading, spacing: 3) {
                        Text("Vibe Screen")
                            .font(.system(size: 20, weight: .bold, design: .rounded))
                        Text("Turn your tablet into a second display")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundColor(.secondary)
                        Link(
                            "Forked from SideScreen",
                            destination: URL(string: "https://github.com/tranvuongquocdat/SideScreen")!
                        )
                        .font(.system(size: 10, weight: .medium))
                    }

                    Spacer()

                    Button(action: { showResetConfirmation = true }) {
                        Image(systemName: "arrow.counterclockwise")
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                            .frame(width: 28, height: 28)
                            .background {
                                Circle().fill(.ultraThinMaterial)
                            }
                    }
                    .buttonStyle(.plain)
                    .disabled(settings.internetRevocationCleanupPending)
                    .help("Reset settings")
                    .alert("Reset Settings", isPresented: $showResetConfirmation) {
                        Button("Cancel", role: .cancel) { }
                        Button("Reset", role: .destructive) {
                            settings.resetToDefaults()
                            if let window = NSApp.windows.first(where: { $0.title == "Vibe Screen" }) {
                                window.center()
                            }
                        }
                    } message: {
                        Text("This will reset all settings to default values.")
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 18)
                .background(.ultraThinMaterial)

                Rectangle()
                    .fill(Color.primary.opacity(0.06))
                    .frame(height: 1)

                // Connection mode picker — pinned, NOT scrollable.
                HStack(spacing: 6) {
                    ForEach(ConnectionMode.allCases, id: \.self) { mode in
                        Button(action: { settings.connectionMode = mode }) {
                            HStack(spacing: 4) {
                                Image(systemName: mode.systemImage)
                                Text(mode.title)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 8)
                            .background(settings.connectionMode == mode ? Color.accentColor : Color.clear)
                            .foregroundColor(settings.connectionMode == mode ? .white : .primary)
                            .cornerRadius(6)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(4)
                .background(.ultraThinMaterial)
                .cornerRadius(8)
                .padding(.horizontal, 20)
                .padding(.vertical, 10)
                .background(.ultraThinMaterial)

                Rectangle()
                    .fill(Color.primary.opacity(0.06))
                    .frame(height: 1)

                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        // Display Configuration
                        FrostedGroupBox(title: "Display Configuration", icon: "display") {
                            VStack(alignment: .leading, spacing: 16) {
                                VStack(alignment: .leading, spacing: 6) {
                                    Text("Source")
                                        .font(.system(size: 11))
                                        .foregroundColor(.secondary)
                                    Picker("Source", selection: $settings.displaySource) {
                                        ForEach(DisplaySourceMode.allCases) { source in
                                            Text(source.title).tag(source)
                                        }
                                    }
                                    .labelsHidden()
                                    .pickerStyle(.menu)
                                    .disabled(settings.isRunning)

                                    if settings.displaySource == .selectedDisplay {
                                        Picker("Display", selection: $settings.selectedDisplayID) {
                                            ForEach(settings.availableDisplays) { display in
                                                Text(display.label).tag(display.id)
                                            }
                                        }
                                        .labelsHidden()
                                        .disabled(settings.isRunning)
                                    }

                                    Text(settings.displaySource.helpText)
                                        .font(.system(size: 10))
                                        .foregroundColor(.secondary.opacity(0.75))
                                }

                                // Resolution
                                VStack(alignment: .leading, spacing: 8) {
                                    HStack {
                                        Text("Resolution")
                                            .font(.system(size: 11))
                                            .foregroundColor(.secondary)
                                        Spacer()
                                        Toggle("Show all", isOn: $settings.showAllResolutions)
                                            .toggleStyle(.switch)
                                            .controlSize(.mini)
                                    }

                                    ScrollView {
                                        VStack(alignment: .leading, spacing: 0) {
                                            if settings.showAllResolutions {
                                                // Custom (Apply) values aren't in any preset group —
                                                // surface them so the selection is visible in the list.
                                                if !DisplaySettings.allResolutions.contains(settings.resolution) {
                                                    HStack(spacing: 6) {
                                                        Text("Custom")
                                                            .font(.system(size: 11, weight: .semibold))
                                                        Text("User defined")
                                                            .font(.system(size: 10))
                                                            .foregroundColor(.secondary)
                                                    }
                                                    .padding(.horizontal, 12)
                                                    .padding(.vertical, 6)
                                                    .frame(maxWidth: .infinity, alignment: .leading)
                                                    .background(Color.primary.opacity(0.03))

                                                    ResolutionRow(resolution: settings.resolution, isSelected: true) {}
                                                }
                                                ForEach(DisplaySettings.resolutionGroups) { group in
                                                    HStack(spacing: 6) {
                                                        Text(group.name)
                                                            .font(.system(size: 11, weight: .semibold))
                                                        Text(group.ratio)
                                                            .font(.system(size: 10))
                                                            .foregroundColor(.secondary)
                                                    }
                                                    .padding(.horizontal, 12)
                                                    .padding(.vertical, 6)
                                                    .frame(maxWidth: .infinity, alignment: .leading)
                                                    .background(Color.primary.opacity(0.03))

                                                    ForEach(group.resolutions, id: \.self) { res in
                                                        ResolutionRow(resolution: res, isSelected: settings.resolution == res) {
                                                            settings.resolution = res
                                                        }
                                                    }
                                                }
                                            } else {
                                                ForEach(DisplaySettings.commonResolutions, id: \.self) { res in
                                                    ResolutionRow(resolution: res, isSelected: settings.resolution == res) {
                                                        settings.resolution = res
                                                    }
                                                }
                                                // Current selection from the full list or a custom
                                                // Apply — keep it visible in the compact list too.
                                                if !DisplaySettings.commonResolutions.contains(settings.resolution) {
                                                    ResolutionRow(resolution: settings.resolution, isSelected: true) {}
                                                }
                                            }
                                        }
                                    }
                                    .frame(height: settings.showAllResolutions ? 180 : 140)
                                    .background(.ultraThinMaterial)
                                    .cornerRadius(8)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 8)
                                            .strokeBorder(Color.primary.opacity(0.1), lineWidth: 1)
                                    )

                                    if settings.showAllResolutions {
                                        HStack(spacing: 8) {
                                            TextField("W", text: $customWidthText)
                                                .textFieldStyle(.roundedBorder)
                                                .frame(width: 70)
                                            Text("x")
                                                .foregroundColor(.secondary)
                                            TextField("H", text: $customHeightText)
                                                .textFieldStyle(.roundedBorder)
                                                .frame(width: 70)
                                            Button("Apply") {
                                                guard customResolutionValid,
                                                      let w = customWidthValue,
                                                      let h = customHeightValue else { return }
                                                settings.customWidth = w
                                                settings.customHeight = h
                                                settings.applyCustomResolution()
                                            }
                                            .buttonStyle(.bordered)
                                            .controlSize(.small)
                                            .disabled(!customResolutionValid)
                                        }
                                        .onAppear {
                                            customWidthText = String(settings.customWidth)
                                            customHeightText = String(settings.customHeight)
                                        }
                                        if !customResolutionValid {
                                            Text("Supported range: 640–7680 × 480–4320")
                                                .font(.system(size: 10))
                                                .foregroundColor(.orange)
                                        }
                                    }
                                }

                                // HiDPI (Retina)
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("HiDPI (Retina)")
                                            .font(.system(size: 11))
                                            .foregroundColor(.secondary)
                                        Text("Renders at 2× resolution for sharper text. Increases bandwidth.")
                                            .font(.system(size: 10))
                                            .foregroundColor(.secondary.opacity(0.7))
                                    }
                                    Spacer()
                                    Toggle("", isOn: $settings.hiDPI)
                                        .toggleStyle(.switch)
                                        .controlSize(.mini)
                                        .disabled(settings.isRunning)
                                }

                                // Rotation
                                VStack(alignment: .leading, spacing: 8) {
                                    Text("Rotation")
                                        .font(.system(size: 11))
                                        .foregroundColor(.secondary)

                                    HStack(spacing: 12) {
                                        ZStack {
                                            RoundedRectangle(cornerRadius: 4)
                                                .stroke(Color.accentColor.opacity(0.5), lineWidth: 1)
                                                .frame(width: 80, height: 50)
                                                .rotationEffect(.degrees(Double(settings.rotation)))

                                            Text(settings.rotation == 90 || settings.rotation == 270 ? "Portrait" : "Landscape")
                                                .font(.system(size: 8))
                                                .foregroundColor(.secondary)
                                        }
                                        .frame(width: 100, height: 80)

                                        VStack(spacing: 6) {
                                            HStack(spacing: 6) {
                                                RotationButton(degrees: 270, label: "270", isSelected: settings.rotation == 270) {
                                                    settings.rotation = 270
                                                }
                                                RotationButton(degrees: 0, label: "0", isSelected: settings.rotation == 0) {
                                                    settings.rotation = 0
                                                }
                                                RotationButton(degrees: 90, label: "90", isSelected: settings.rotation == 90) {
                                                    settings.rotation = 90
                                                }
                                            }
                                            HStack(spacing: 6) {
                                                Spacer()
                                                RotationButton(degrees: 180, label: "180", isSelected: settings.rotation == 180) {
                                                    settings.rotation = 180
                                                }
                                                Spacer()
                                            }
                                        }
                                    }

                                    if settings.rotation == 90 || settings.rotation == 270 {
                                        Text("Display will be in portrait mode")
                                            .font(.system(size: 10))
                                            .foregroundColor(.accentColor)
                                    }

                                    HStack {
                                        Spacer()
                                        Button(action: {
                                            NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.displays?displayArrangement")!)
                                        }) {
                                            HStack(spacing: 4) {
                                                Image(systemName: "rectangle.connected.to.line.below")
                                                Text("Arrange Displays…")
                                            }
                                        }
                                        .buttonStyle(.bordered)
                                        .controlSize(.small)
                                    }
                                    .padding(.top, 10)
                                }

                            }
                        }

                        // Refresh Rate (own block)
                        FrostedGroupBox(title: "Refresh Rate", icon: "speedometer") {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text("Frame Rate")
                                        .font(.system(size: 11))
                                        .foregroundColor(.secondary)
                                    Spacer()
                                    Text("\(settings.refreshRate) Hz")
                                        .font(.system(size: 11, weight: .medium))
                                }

                                HStack(spacing: 6) {
                                    ForEach([30, 60, 90, 120], id: \.self) { rate in
                                        BitrateButton(
                                            label: "\(rate)",
                                            value: rate,
                                            currentValue: settings.refreshRate,
                                            disabled: false
                                        ) {
                                            settings.refreshRate = rate
                                        }
                                    }
                                }

                                if settings.clientConnected,
                                   let model = settings.connectedDeviceModel,
                                   let maxHz = settings.connectedDeviceMaxRefreshRate {
                                    if settings.refreshRate <= maxHz {
                                        Text("\(model) supports up to \(maxHz) Hz")
                                            .font(.system(size: 10))
                                            .foregroundColor(.green)
                                    } else {
                                        Text("\(model) may not support \(settings.refreshRate) Hz (max \(maxHz) Hz)")
                                            .font(.system(size: 10))
                                            .foregroundColor(.orange)
                                    }
                                } else if settings.refreshRate >= 90 {
                                    Text("Use only with a tablet panel that supports this refresh rate.")
                                        .font(.system(size: 10))
                                        .foregroundColor(.secondary)
                                }
                            }
                        }

                        // Touch Control
                        FrostedGroupBox(title: "Touch Control", icon: "hand.tap") {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("Enable Touch Input")
                                            .font(.system(size: 12, weight: .medium))
                                        Text("Control Mac from tablet touch")
                                            .font(.system(size: 10))
                                            .foregroundColor(.secondary)
                                    }
                                    Spacer()
                                    Toggle("", isOn: $settings.touchEnabled)
                                        .labelsHidden()
                                }

                                if !settings.touchEnabled {
                                    Text("Touch input is disabled — tablet is display-only")
                                        .font(.system(size: 10))
                                        .foregroundColor(.orange)
                                }
                            }
                        }

                        // USB and trusted-LAN use a local TCP listener. Internet
                        // mode uses signaling plus WebRTC DataChannels instead.
                        if settings.connectionMode != .internet {
                            FrostedGroupBox(title: "Network Settings", icon: "network") {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text("Server Port")
                                        .font(.system(size: 11))
                                        .foregroundColor(.secondary)
                                    Spacer()
                                    TextField("Port", value: $settings.port, format: .number)
                                        .textFieldStyle(.roundedBorder)
                                        .frame(width: 80)
                                        .disabled(settings.isRunning)
                                }

                                if settings.isRunning {
                                    Text("Stop server to change port")
                                        .font(.system(size: 10))
                                        .foregroundColor(.orange)
                                } else if settings.connectionMode == .wireless {
                                    Text("Changing the port invalidates existing pairings — re-scan the QR on each tablet.")
                                        .font(.system(size: 10))
                                        .foregroundColor(.secondary)
                                } else if settings.port != 54321 {
                                    Text("Custom port set — Android client must use the same port.")
                                        .font(.system(size: 10))
                                        .foregroundColor(.secondary)
                                }
                            }
                        }
                        }

                        // Wireless-mode-only: QR + Paired Devices.
                        if settings.connectionMode == .wireless {
                            WirelessSection(settings: settings,
                                            pairedDeviceStore: (NSApp.delegate as? AppDelegate)?.pairedDeviceStore ?? PairedDeviceStore())
                        }

                        if settings.connectionMode == .internet {
                            InternetSection(settings: settings)
                        }

                        // Startup / headless behaviour
                        FrostedGroupBox(title: "Startup", icon: "power") {
                            VStack(alignment: .leading, spacing: 12) {
                                if #available(macOS 13.0, *) {
                                    HStack {
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text("Launch at Login")
                                                .font(.system(size: 12, weight: .medium))
                                            Text("Run Vibe Screen in the background automatically after you log in.")
                                                .font(.system(size: 10))
                                                .foregroundColor(.secondary)
                                        }
                                        Spacer()
                                        Toggle("", isOn: Binding(
                                            get: { daemonEnabled },
                                            set: { newValue in
                                                do {
                                                    if newValue {
                                                        try DaemonManager.shared.enable()
                                                    } else {
                                                        try DaemonManager.shared.disable()
                                                    }
                                                } catch {
                                                    print("Daemon toggle failed: \(error)")
                                                }
                                                refreshDaemonStatus()
                                            }
                                        ))
                                        .labelsHidden()
                                    }
                                    if let daemonStatusGuidance {
                                        Text(daemonStatusGuidance)
                                            .font(.system(size: 10))
                                            .foregroundColor(.orange)
                                    }
                                    Divider()
                                }

                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("Auto-start streaming on launch")
                                            .font(.system(size: 12, weight: .medium))
                                        Text("Start the server automatically when the app opens, so the tablet can connect without touching the Mac.")
                                            .font(.system(size: 10))
                                            .foregroundColor(.secondary)
                                    }
                                    Spacer()
                                    Toggle("", isOn: $settings.autoStartStreamingOnLaunch)
                                        .labelsHidden()
                                }

                                Divider()

                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("Hide Dock icon")
                                            .font(.system(size: 12, weight: .medium))
                                        Text("Run as a menu bar–only utility. Open Settings from the menu bar icon.")
                                            .font(.system(size: 10))
                                            .foregroundColor(.secondary)
                                    }
                                    Spacer()
                                    Toggle("", isOn: $settings.hideDockIcon)
                                        .labelsHidden()
                                }

                                Divider()

                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("Startup mode")
                                            .font(.system(size: 12, weight: .medium))
                                        Text("Which connection mode to start in when auto-starting.")
                                            .font(.system(size: 10))
                                            .foregroundColor(.secondary)
                                    }
                                    Spacer()
                                    Picker("", selection: $settings.startupMode) {
                                        ForEach(ConnectionMode.allCases, id: \.self) { mode in
                                            Text(mode.title).tag(mode)
                                        }
                                    }
                                    .pickerStyle(.segmented)
                                    .labelsHidden()
                                    .frame(width: 220)
                                    .disabled(!settings.autoStartStreamingOnLaunch)
                                }
                            }
                        }
                        .onAppear {
                            if #available(macOS 13.0, *) {
                                refreshDaemonStatus()
                            }
                        }

                        // Gaming Boost
                        FrostedGroupBox(title: "Gaming Boost", icon: settings.gamingBoost ? "bolt.fill" : "bolt") {
                            VStack(alignment: .leading, spacing: 16) {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("Enable Gaming Mode")
                                            .font(.system(size: 12, weight: .medium))
                                        Text("Optimized for competitive gaming")
                                            .font(.system(size: 10))
                                            .foregroundColor(.secondary)
                                    }
                                    Spacer()
                                    Toggle("", isOn: $settings.gamingBoost)
                                        .labelsHidden()
                                }

                                if settings.gamingBoost {
                                    VStack(alignment: .leading, spacing: 6) {
                                        HStack(spacing: 4) {
                                            Image(systemName: "checkmark.circle.fill")
                                                .foregroundColor(.green)
                                                .font(.system(size: 10))
                                            Text("USB 2-safe bitrate (45 Mbps)")
                                                .font(.system(size: 11))
                                        }
                                        HStack(spacing: 4) {
                                            Image(systemName: "checkmark.circle.fill")
                                                .foregroundColor(.green)
                                                .font(.system(size: 10))
                                            Text("No frame reordering and one-frame encode backpressure")
                                                .font(.system(size: 11))
                                        }
                                        HStack(spacing: 4) {
                                            Image(systemName: "checkmark.circle.fill")
                                                .foregroundColor(.green)
                                                .font(.system(size: 10))
                                            Text("Ultra-low latency encoding")
                                                .font(.system(size: 11))
                                        }
                                    }
                                    .padding(.leading, 4)
                                    .foregroundColor(.secondary)
                                }
                            }
                        }

                        // Streaming Settings
                        FrostedGroupBox(title: "Streaming Settings", icon: "antenna.radiowaves.left.and.right") {
                            VStack(alignment: .leading, spacing: 16) {
                                // Bitrate
                                VStack(alignment: .leading, spacing: 10) {
                                    HStack {
                                        Text("Bitrate")
                                            .font(.system(size: 11))
                                            .foregroundColor(.secondary)
                                        Spacer()
                                        Text("\(settings.effectiveBitrate) Mbps")
                                            .font(.system(size: 13, weight: .semibold, design: .monospaced))
                                            .foregroundColor(.accentColor)
                                    }

                                    HStack(spacing: 6) {
                                        BitrateButton(label: "20", value: 20, currentValue: settings.bitrate, disabled: settings.gamingBoost) {
                                            settings.bitrate = 20
                                        }
                                        BitrateButton(label: "35", value: 35, currentValue: settings.bitrate, disabled: settings.gamingBoost) {
                                            settings.bitrate = 35
                                        }
                                        BitrateButton(label: "50", value: 50, currentValue: settings.bitrate, disabled: settings.gamingBoost) {
                                            settings.bitrate = 50
                                        }
                                        BitrateButton(label: "80", value: 80, currentValue: settings.bitrate, disabled: settings.gamingBoost) {
                                            settings.bitrate = 80
                                        }
                                        BitrateButton(label: "120", value: 120, currentValue: settings.bitrate, disabled: settings.gamingBoost) {
                                            settings.bitrate = 120
                                        }
                                    }

                                    HStack(spacing: 8) {
                                        Text("20")
                                            .font(.system(size: 9))
                                            .foregroundColor(.secondary)
                                        Slider(value: Binding(
                                            get: { Double(settings.bitrate) },
                                            set: { settings.bitrate = Int($0) }
                                        ), in: 10...200, step: 5)
                                        .disabled(settings.gamingBoost)
                                        Text("200")
                                            .font(.system(size: 9))
                                            .foregroundColor(.secondary)
                                    }

                                    if settings.gamingBoost {
                                        HStack(spacing: 4) {
                                            Image(systemName: "bolt.fill")
                                                .font(.system(size: 10))
                                            Text("Locked at 45 Mbps in Gaming Boost")
                                                .font(.system(size: 10))
                                        }
                                        .foregroundColor(.orange)
                                    }
                                }

                                // Quality
                                VStack(alignment: .leading, spacing: 8) {
                                    Text("Quality Preset")
                                        .font(.system(size: 11))
                                        .foregroundColor(.secondary)

                                    Picker("", selection: $settings.quality) {
                                        Text("Ultra Low").tag("ultralow")
                                        Text("Low").tag("low")
                                        Text("Medium").tag("medium")
                                        Text("High").tag("high")
                                    }
                                    .pickerStyle(.segmented)
                                    .disabled(settings.gamingBoost)

                                    if settings.gamingBoost {
                                        Text("Quality locked to Ultra Low in Gaming Boost mode")
                                            .font(.system(size: 10))
                                            .foregroundColor(.orange)
                                    } else if settings.quality == "ultralow" {
                                        Text("Fastest encoding, lowest latency")
                                            .font(.system(size: 10))
                                            .foregroundColor(.green)
                                    }
                                }
                            }
                        }

                        // Status
                        FrostedGroupBox(title: "Status", icon: "checkmark.circle") {
                            VStack(alignment: .leading, spacing: 12) {
                                if settings.showPostUpdatePermissionHint {
                                    VStack(alignment: .leading, spacing: 8) {
                                        HStack(spacing: 6) {
                                            Image(systemName: "arrow.triangle.2.circlepath")
                                                .foregroundColor(.orange)
                                            Text("Permissions after update")
                                                .font(.system(size: 12, weight: .medium))
                                            Spacer()
                                            Button("Dismiss") {
                                                settings.dismissPostUpdatePermissionHint()
                                            }
                                            .buttonStyle(.borderless)
                                            .font(.system(size: 11))
                                        }
                                        Text("After a rebuild or re-sign, macOS can leave a stale Screen Recording or Accessibility entry that still looks checked but no longer works. Remove Vibe Screen with the − button, then add it again with + (or relaunch so macOS re-prompts). Uncheck → check alone often keeps the old grant.")
                                            .font(.system(size: 11))
                                            .foregroundColor(.secondary)
                                            .fixedSize(horizontal: false, vertical: true)
                                        HStack(spacing: 8) {
                                            Button(action: {
                                                NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!)
                                            }) {
                                                Text("Screen Recording")
                                            }
                                            .buttonStyle(.bordered)
                                            .controlSize(.small)
                                            Button(action: {
                                                NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
                                            }) {
                                                Text("Accessibility")
                                            }
                                            .buttonStyle(.bordered)
                                            .controlSize(.small)
                                        }
                                    }
                                    .padding(10)
                                    .background(Color.orange.opacity(0.1))
                                    .cornerRadius(8)
                                }

                                StatusRow(title: "Display Source",
                                          status: settings.displayCreated ? "Active" : "Inactive",
                                          color: settings.displayCreated ? .green : .secondary,
                                          hint: settings.displaySource.helpText)
                                StatusRow(title: "Client Connected",
                                          status: settings.clientConnected ? "Yes" : "No",
                                          color: settings.clientConnected ? .green : .secondary,
                                          hint: "Whether the Android client app currently has an active stream session.")
                                StatusRow(
                                    title: ProcessInfo.processInfo.operatingSystemVersion.majorVersion >= 26 ? "Screen & System Audio" : "Screen Recording",
                                    status: settings.hasScreenRecordingPermission ? "Granted" : "Required",
                                    color: settings.hasScreenRecordingPermission ? .green : .red,
                                    hint: "macOS privacy permission required to capture the virtual display. Grant in System Settings → Privacy & Security → Screen Recording."
                                )
                                StatusRow(title: "Accessibility",
                                          status: settings.hasAccessibilityPermission ? "Granted" : "Optional",
                                          color: settings.hasAccessibilityPermission ? .green : .orange,
                                          hint: "Optional permission. Required only if you want touch/tap input from the tablet to control the Mac. Streaming works without it.")
                                if settings.isRunning {
                                    StatusRow(title: "Capture Method",
                                              status: settings.captureMethod,
                                              color: settings.captureMethod.contains("fallback") ? .orange : .green,
                                              hint: "Which macOS API is currently capturing the virtual display. SCStream is the modern path; CGDisplayStream fallback activates if SCStream fails (e.g. on certain virtual display configs).")
                                }

                                // Mode-aware contextual rows
                                Divider().padding(.vertical, 4)
                                if settings.connectionMode == .usb {
                                    StatusRow(title: "ADB installed",
                                              status: settings.adbInstalled ? "Installed" : "Missing",
                                              color: settings.adbInstalled ? .green : .red,
                                              hint: "USB mode tunnels the TCP stream through the cable using `adb reverse`. Requires the `adb` command on the Mac. Searched paths: Homebrew, /usr/local/bin, ~/Library/Android/sdk/platform-tools, and PATH (`which adb`).")
                                    if !settings.adbInstalled {
                                        Text("brew install android-platform-tools")
                                            .font(.system(size: 10, design: .monospaced))
                                            .padding(6)
                                            .background(Color.black.opacity(0.08))
                                            .cornerRadius(4)
                                            .frame(maxWidth: .infinity, alignment: .leading)
                                            .textSelection(.enabled)
                                    }
                                    StatusRow(title: "ADB reverse",
                                              status: settings.adbReverseConfigured ? "OK" : "Pending",
                                              color: settings.adbReverseConfigured ? .green : .orange,
                                              hint: "Whether `adb reverse tcp:\(settings.port) tcp:\(settings.port)` is currently configured. The Mac app sets this up automatically when you click Start. Goes green within ~2 seconds after the tablet is plugged in and authorized.")
                                    StatusRow(title: "USB device",
                                              status: settings.usbDeviceConnected
                                                ? "Detected"
                                                : (settings.availableADBDevices.isEmpty
                                                    ? "Not detected"
                                                    : "Select a target"),
                                              color: settings.usbDeviceConnected
                                                ? .green
                                                : (settings.availableADBDevices.isEmpty
                                                    ? .red
                                                    : .orange),
                                              hint: "An Android device authorized for ADB and visible to your Mac. Plug in via USB-C and tap Allow on the device's USB debugging prompt.")
                                    let selectedADBDeviceIsUnavailable =
                                        !settings.adbDeviceSerial.isEmpty &&
                                        !settings.availableADBDevices.contains(settings.adbDeviceSerial)
                                    if settings.availableADBDevices.count > 1 ||
                                        (selectedADBDeviceIsUnavailable &&
                                         !settings.availableADBDevices.isEmpty) {
                                        Picker(
                                            "Target tablet",
                                            selection: $settings.adbDeviceSerial
                                        ) {
                                            Text("Automatic (one connected device)").tag("")
                                            ForEach(settings.availableADBDevices, id: \.self) {
                                                Text($0).tag($0)
                                            }
                                        }
                                        .font(.system(size: 11))
                                        .help(
                                            "ADB serial used for reverse forwarding and automatic launch. " +
                                            "Automatic mode connects only when exactly one device is available."
                                        )
                                        if selectedADBDeviceIsUnavailable {
                                            Text(
                                                "The selected Android device is offline. " +
                                                "Reconnect it or choose an available device."
                                            )
                                            .font(.caption)
                                            .foregroundColor(.orange)
                                            .fixedSize(horizontal: false, vertical: true)
                                        }
                                    }
                                } else if settings.connectionMode == .wireless {
                                    StatusRow(title: "WiFi",
                                              status: settings.wifiConnected ? "Connected" : "Disconnected",
                                              color: settings.wifiConnected ? .green : .red,
                                              hint: "Whether the Mac currently has a working internet route. Wireless mode requires the Mac to be on a WiFi (or Ethernet) network — the same network the tablet is on.")
                                    StatusRow(title: "Listening on",
                                              status: settings.listeningAddress.map { "\($0):\(settings.port)" } ?? "—",
                                              color: settings.listeningAddress != nil ? .green : .secondary,
                                              hint: "The LAN address the tablet must reach. The QR code embeds this exact host:port — if it changes (e.g. you switch WiFi), re-scan the new QR on the tablet.")
                                } else {
                                    StatusRow(
                                        title: "Internet session",
                                        status: settings.internetStatus.title,
                                        color: settings.internetStatusColor,
                                        hint: "Experimental Internet transport state for authenticated, application-encrypted Protocol v1 records."
                                    )
                                    StatusRow(
                                        title: "Route",
                                        status: settings.internetRoutePreference.title,
                                        color: settings.internetStatus == .direct ? .green : .secondary,
                                        hint: settings.internetRoutePreference.helpText
                                    )
                                }

                                if !settings.hasScreenRecordingPermission {
                                    VStack(alignment: .leading, spacing: 8) {
                                        HStack(spacing: 6) {
                                            Image(systemName: "exclamationmark.triangle.fill")
                                                .foregroundColor(.orange)
                                            Text(ProcessInfo.processInfo.operatingSystemVersion.majorVersion >= 26 ? "Screen & System Audio Recording Required" : "Screen Recording Required")
                                                .font(.system(size: 12, weight: .medium))
                                        }
                                        Text(ProcessInfo.processInfo.operatingSystemVersion.majorVersion >= 26
                                            ? "Required to capture the virtual display. Go to System Settings > Privacy & Security > Screen & System Audio Recording."
                                            : "Required to capture the virtual display.")
                                            .font(.system(size: 11))
                                            .foregroundColor(.secondary)
                                        Button(action: {
                                            NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!)
                                        }) {
                                            HStack {
                                                Image(systemName: "gear")
                                                Text("Open System Settings")
                                            }
                                        }
                                        .buttonStyle(.borderedProminent)
                                        .controlSize(.small)
                                    }
                                    .padding(10)
                                    .background(Color.orange.opacity(0.1))
                                    .cornerRadius(8)
                                }

                                if !settings.hasAccessibilityPermission {
                                    VStack(alignment: .leading, spacing: 8) {
                                        HStack(spacing: 6) {
                                            Image(systemName: "hand.tap.fill")
                                                .foregroundColor(.blue)
                                            Text("Enable Touch Control")
                                                .font(.system(size: 12, weight: .medium))
                                        }
                                        Text("Control your Mac from your tablet.")
                                            .font(.system(size: 11))
                                            .foregroundColor(.secondary)
                                        Button(action: {
                                            NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
                                        }) {
                                            HStack {
                                                Image(systemName: "gear")
                                                Text("Open Settings")
                                            }
                                            .frame(maxWidth: .infinity)
                                        }
                                        .buttonStyle(.borderedProminent)
                                        .controlSize(.small)
                                    }
                                    .padding(10)
                                    .background(Color.blue.opacity(0.08))
                                    .cornerRadius(8)
                                }
                            }
                        }

                        // Performance (when connected)
                        if settings.clientConnected {
                            FrostedGroupBox(title: "Performance", icon: "speedometer") {
                                // Live FPS/bitrate render through an AppKit bridge so the
                                // once-per-second telemetry never re-evaluates this SwiftUI body.
                                LiveMetricsView(metrics: settings.metrics)
                                    .frame(height: 34)
                            }
                        }
                    }
                    .padding(20)
                }

                // Footer
                VStack(spacing: 0) {
                    Rectangle()
                        .fill(Color.primary.opacity(0.06))
                        .frame(height: 1)

                    HStack(spacing: 12) {
                        Button(action: {
                            withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                                settings.toggleServer()
                            }
                        }) {
                            HStack(spacing: 6) {
                                Image(systemName: settings.hasRunningIntent ? "stop.fill" : "play.fill")
                                    .font(.system(size: 12))
                                Text(settings.hasRunningIntent ? "Stop" : "Start")
                                    .font(.system(size: 13, weight: .medium))
                            }
                            .frame(width: 90)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(settings.hasRunningIntent ? .red : .accentColor)
                        .controlSize(.large)
                        .disabled(!settings.hasScreenRecordingPermission)

                        if settings.isRunning {
                            HStack(spacing: 6) {
                                Circle()
                                    .fill(Color.green)
                                    .frame(width: 8, height: 8)
                                    .overlay {
                                        Circle()
                                            .stroke(Color.green.opacity(0.3), lineWidth: 2)
                                            .scaleEffect(1.5)
                                    }
                                Text(settings.connectionMode == .internet
                                     ? settings.internetStatus.title
                                     : "Running on port \(settings.port)")
                                    .font(.system(size: 12))
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background {
                                Capsule().fill(.ultraThinMaterial)
                                    .overlay {
                                        Capsule().strokeBorder(Color.green.opacity(0.2), lineWidth: 1)
                                    }
                            }
                            .transition(.scale.combined(with: .opacity))
                        }

                        Spacer()

                        // Restart button
                        Button(action: {
                            restartApp()
                        }) {
                            Image(systemName: "arrow.clockwise")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(.secondary)
                                .frame(width: 32, height: 32)
                                .background {
                                    Circle().fill(.ultraThinMaterial)
                                        .overlay {
                                            Circle().strokeBorder(Color.primary.opacity(0.1), lineWidth: 1)
                                        }
                                }
                        }
                        .buttonStyle(.plain)
                        .help("Restart App")

                        // Quit button
                        Button(action: {
                            NSApp.terminate(nil)
                        }) {
                            Image(systemName: "power")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(.secondary)
                                .frame(width: 32, height: 32)
                                .background {
                                    Circle().fill(.ultraThinMaterial)
                                        .overlay {
                                            Circle().strokeBorder(Color.primary.opacity(0.1), lineWidth: 1)
                                        }
                                }
                        }
                        .buttonStyle(.plain)
                        .help("Quit Vibe Screen (⌘Q)")
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 14)
                    .background(.ultraThinMaterial)
                }
            }
        }
        .frame(width: 480, height: 780)
        .onReceive(
            NotificationCenter.default.publisher(
                for: NSApplication.didBecomeActiveNotification
            )
        ) { _ in
            refreshDaemonStatus()
        }
    }

    private func refreshDaemonStatus() {
        daemonEnabled = DaemonManager.shared.isEnabled
        daemonStatusGuidance = DaemonManager.shared.statusGuidance
    }

    /// Restart the app by launching a new instance and terminating current one
    private func restartApp() {
        // Get the app bundle path
        guard let appPath = Bundle.main.bundlePath as String? else {
            print("❌ Could not get app path")
            return
        }

        // Use Process to launch a new instance after a short delay
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/sh")
        task.arguments = ["-c", "sleep 0.5 && open \"\(appPath)\""]

        do {
            try task.run()
            // Terminate current app
            NSApp.terminate(nil)
        } catch {
            print("❌ Failed to restart: \(error)")
        }
    }
}

// MARK: - Supporting Views

struct StatusRow: View {
    let title: String
    let status: String
    let color: Color
    var hint: String?
    @State private var showHint = false
    @State private var hovering = false

    var body: some View {
        HStack {
            Text(title)
                .font(.system(size: 12))
            if let hint = hint {
                Button(action: { showHint.toggle() }) {
                    Image(systemName: "info.circle")
                        .font(.system(size: 11))
                        .foregroundColor(hovering ? .accentColor : .secondary)
                        .frame(width: 18, height: 18)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .onHover { hovering = $0 }
                .help(hint)
                .popover(isPresented: $showHint, arrowEdge: .top) {
                    Text(hint)
                        .font(.system(size: 12))
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(width: 280, alignment: .leading)
                        .padding(12)
                }
            }
            Spacer()
            HStack(spacing: 6) {
                Circle()
                    .fill(color)
                    .frame(width: 6, height: 6)
                Text(status)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(color)
            }
        }
    }
}

struct ResolutionRow: View {
    let resolution: String
    let isSelected: Bool
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack {
                Text(resolution.replacingOccurrences(of: "x", with: " x "))
                    .font(.system(size: 12))
                Spacer()
                if isSelected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(.white)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(isSelected ? Color.accentColor : (isHovered ? Color.primary.opacity(0.05) : Color.clear))
            .foregroundColor(isSelected ? .white : .primary)
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
    }
}

struct BitrateButton: View {
    let label: String
    let value: Int
    let currentValue: Int
    let disabled: Bool
    let action: () -> Void
    @State private var isHovered = false

    var isSelected: Bool { currentValue == value }

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 11, weight: isSelected ? .semibold : .regular))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
                .background {
                    if isSelected {
                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .fill(Color.accentColor)
                    } else {
                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .fill(.ultraThinMaterial)
                            .overlay {
                                RoundedRectangle(cornerRadius: 6, style: .continuous)
                                    .strokeBorder(Color.primary.opacity(0.1), lineWidth: 1)
                            }
                    }
                }
                .foregroundColor(isSelected ? .white : (disabled ? .secondary : .primary))
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.5 : 1)
        .onHover { isHovered = $0 }
    }
}

struct RotationButton: View {
    let degrees: Int
    let label: String
    let isSelected: Bool
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            VStack(spacing: 2) {
                RoundedRectangle(cornerRadius: 2)
                    .stroke(isSelected ? Color.accentColor : Color.secondary.opacity(0.5), lineWidth: 1)
                    .frame(width: degrees == 90 || degrees == 270 ? 16 : 24, height: degrees == 90 || degrees == 270 ? 24 : 16)

                Text("\(label)")
                    .font(.system(size: 9))
                    .foregroundColor(isSelected ? .accentColor : .secondary)
            }
            .frame(width: 50, height: 40)
            .background {
                if isSelected {
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .fill(Color.accentColor.opacity(0.15))
                        .overlay {
                            RoundedRectangle(cornerRadius: 6, style: .continuous)
                                .strokeBorder(Color.accentColor, lineWidth: 1)
                        }
                } else {
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .fill(.ultraThinMaterial)
                        .overlay {
                            RoundedRectangle(cornerRadius: 6, style: .continuous)
                                .strokeBorder(Color.primary.opacity(0.1), lineWidth: 1)
                        }
                }
            }
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
    }
}

// MARK: - Internet Session

private struct InternetSection: View {
    @ObservedObject var settings: DisplaySettings
    @State private var signalingToken = ""
    @State private var turnCredential = ""
    @State private var pairingDeviceRequest = ""

    private var endpointIsValid: Bool {
        DisplaySettings.isSafeInternetSignalingEndpoint(settings.internetSignalingEndpoint)
    }

    var body: some View {
        FrostedGroupBox(title: "Internet Development Preview", icon: "lock.shield") {
            VStack(alignment: .leading, spacing: 12) {
                Text("Experimental Internet transport. Protocol v1 application records are encrypted on direct and TURN routes. Public Internet traversal, real display capture, cross-service revocation, and soak stability are not yet accepted.")
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)

                VStack(alignment: .leading, spacing: 5) {
                    Text("Signaling endpoint")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                    TextField("https://signal.example.com", text: $settings.internetSignalingEndpoint)
                        .textFieldStyle(.roundedBorder)
                        .disabled(settings.internetStatus.isActive)
                    if !endpointIsValid {
                        Text("Use a credential-free HTTPS URL. Plain HTTP is accepted only for 127.0.0.1 development.")
                            .font(.system(size: 10))
                            .foregroundColor(.red)
                    }
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("Local development session profile")
                        .font(.system(size: 11, weight: .semibold))

                    TextField("Short-lived session ID", text: $settings.internetSessionIdentifier)
                        .textFieldStyle(.roundedBorder)
                        .disabled(settings.internetStatus.isActive)
                    TextField(
                        "Authoritative session epoch",
                        value: $settings.internetAuthoritativeSessionEpoch,
                        format: .number
                    )
                    .textFieldStyle(.roundedBorder)
                    .disabled(settings.internetStatus.isActive)
                    TextField("ICE URLs (comma-separated)", text: $settings.internetICEURLs)
                        .textFieldStyle(.roundedBorder)
                        .disabled(settings.internetStatus.isActive)
                    if !DisplaySettings.isSafeInternetICEURLList(settings.internetICEURLs) {
                        Text("Use credential-free STUN/TURN URLs; enter TURN credentials only in the secure field.")
                            .font(.system(size: 10))
                            .foregroundColor(.red)
                    }
                    TextField("TURN username", text: $settings.internetTURNUsername)
                        .textFieldStyle(.roundedBorder)
                        .disabled(settings.internetStatus.isActive)

                    SecureField("Short-lived host role token", text: $signalingToken)
                        .textFieldStyle(.roundedBorder)
                    SecureField("TURN credential (if TURN is configured)", text: $turnCredential)
                        .textFieldStyle(.roundedBorder)

                    HStack {
                        Button("Save credentials to Keychain") {
                            if settings.saveInternetCredentials(
                                signalingToken: signalingToken,
                                turnCredential: turnCredential
                            ) {
                                signalingToken = ""
                                turnCredential = ""
                            }
                        }
                        .disabled(signalingToken.isEmpty)
                        Spacer()
                        Text(settings.internetCredentialsAvailable ? "Keychain ready" : "Credentials required")
                            .font(.system(size: 10))
                            .foregroundColor(settings.internetCredentialsAvailable ? .green : .orange)
                    }
                    .controlSize(.small)

                    Text("This profile is for local integration only. Role tokens and TURN credentials are never written to preferences or logs.")
                        .font(.system(size: 10))
                        .foregroundColor(.orange)
                }
                .padding(10)
                .background(Color.orange.opacity(0.07))
                .cornerRadius(8)

                VStack(alignment: .leading, spacing: 5) {
                    Picker("Route", selection: $settings.internetRoutePreference) {
                        ForEach(InternetRoutePreference.allCases) { route in
                            Text(route.title).tag(route)
                        }
                    }
                    .pickerStyle(.segmented)
                    .disabled(settings.internetStatus.isActive)
                    Text(settings.internetRoutePreference.helpText)
                        .font(.system(size: 10))
                        .foregroundColor(.secondary)
                }

                HStack(spacing: 8) {
                    Circle()
                        .fill(settings.internetStatusColor)
                        .frame(width: 8, height: 8)
                    Text(settings.internetStatus.title)
                        .font(.system(size: 12, weight: .semibold))
                    Spacer()
                    if let peer = settings.internetPeerDisplayName, !peer.isEmpty {
                        Text(peer)
                            .font(.system(size: 10))
                            .foregroundColor(.secondary)
                    }
                }

                if let pairingCode = settings.internetPairingCode {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Confirm this one-time code on both devices")
                            .font(.system(size: 10))
                            .foregroundColor(.secondary)
                        Text(pairingCode)
                            .font(.system(size: 18, weight: .semibold, design: .monospaced))
                            .textSelection(.enabled)
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.accentColor.opacity(0.08))
                    .cornerRadius(8)
                }

                if let pairingURL = settings.internetPairingURL,
                   let image = QRRenderer.render(url: pairingURL, size: 180) {
                    HStack {
                        Spacer()
                        Image(nsImage: image)
                            .resizable()
                            .interpolation(.none)
                            .frame(width: 180, height: 180)
                            .accessibilityLabel("One-time Internet pairing QR code")
                        Spacer()
                    }

                    VStack(alignment: .leading, spacing: 6) {
                        Text("Device pairing response")
                            .font(.system(size: 10))
                            .foregroundColor(.secondary)
                        TextField("Paste Base64 or JSON response from Android", text: $pairingDeviceRequest)
                            .textFieldStyle(.roundedBorder)
                        Button("Complete pairing") {
                            settings.completeInternetPairing(
                                deviceRequest: pairingDeviceRequest
                            )
                            pairingDeviceRequest = ""
                        }
                        .disabled(pairingDeviceRequest.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        .controlSize(.small)
                    }
                }

                if let acceptance = settings.internetPairingAcceptance {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Return this acceptance to Android")
                            .font(.system(size: 10))
                            .foregroundColor(.secondary)
                        Text(acceptance)
                            .font(.system(size: 9, design: .monospaced))
                            .lineLimit(3)
                            .textSelection(.enabled)
                    }
                    .padding(8)
                    .background(Color.green.opacity(0.08))
                    .cornerRadius(8)
                }

                if let error = settings.internetErrorMessage {
                    VStack(alignment: .leading, spacing: 5) {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(.red)
                        if let recovery = settings.internetRecoverySuggestion {
                            Text(recovery)
                                .font(.system(size: 10))
                                .foregroundColor(.secondary)
                        }
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.red.opacity(0.08))
                    .cornerRadius(8)
                }

                HStack(spacing: 8) {
                    Button(
                        settings.internetStatus == .pairing
                            ? "Pairing…"
                            : (settings.internetStatus == .revoked ? "Pair New Identity" : "Pair")
                    ) {
                        settings.pairInternetDevice()
                    }
                    .disabled(
                        !endpointIsValid ||
                        settings.internetStatus.isActive ||
                        settings.internetStatus == .pairing ||
                        settings.internetRevocationCleanupPending
                    )

                    Button("Revoke", role: .destructive) {
                        settings.revokeInternetDevice()
                    }
                    .disabled(settings.internetStatus == .idle || settings.internetStatus == .revoked)

                    if settings.internetRevocationCleanupPending {
                        Button("Retry Cleanup") {
                            settings.retryInternetRevocationCleanup()
                        }
                    }

                    Spacer()

                    if settings.internetStatus.isActive {
                        Button("Disconnect") {
                            settings.disconnectInternetSession()
                        }
                    } else {
                        Button("Connect") {
                            settings.connectInternetSession()
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(
                            !endpointIsValid ||
                            !settings.internetStatus.canConnect ||
                            !settings.internetCredentialsAvailable
                        )
                    }
                }
                .controlSize(.small)

                Text("Pairing credentials and identity keys are stored only in Keychain. Direct and TURN routes carry identical application-layer ciphertext.")
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

// MARK: - Live Stream Metrics

/// High-frequency streaming telemetry (roughly one update per second) kept out
/// of SwiftUI's observation graph on purpose. Publishing FPS/bitrate through a
/// SwiftUI `ObservableObject` re-evaluated a view body every second, and each
/// evaluation registered fresh SwiftUI Observation entries that accumulated in
/// the host heap over long sessions. Metrics now flow through Combine subjects
/// that an AppKit bridge (`LiveMetricsView`) renders directly into text
/// fields, so per-second updates never invalidate a SwiftUI body.
final class StreamMetrics {
    let fps = CurrentValueSubject<Double, Never>(0)
    let bitrateMbps = CurrentValueSubject<Double, Never>(0)

    /// Update both values from the streaming stats callback. Skips redundant
    /// sends so an unchanged metric does not wake the AppKit subscriber.
    func update(fps newFPS: Double, bitrateMbps newBitrate: Double) {
        if fps.value != newFPS { fps.send(newFPS) }
        if bitrateMbps.value != newBitrate { bitrateMbps.send(newBitrate) }
    }

    /// Reset to zero on disconnect.
    func reset() {
        update(fps: 0, bitrateMbps: 0)
    }
}

/// AppKit bridge that renders live FPS/bitrate without entering SwiftUI's
/// observation graph. The Coordinator subscribes to `StreamMetrics` Combine
/// subjects and mutates `NSTextField`s in place, so recurring metric updates
/// do not trigger any SwiftUI body re-evaluation. The parent view holds only a
/// plain reference to `StreamMetrics` (never `@ObservedObject`).
struct LiveMetricsView: NSViewRepresentable {
    let metrics: StreamMetrics

    func makeCoordinator() -> Coordinator {
        Coordinator(metrics: metrics)
    }

    func makeNSView(context: Context) -> NSView {
        context.coordinator.makeContainer()
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        // Values are pushed by the Coordinator's Combine subscriptions; nothing
        // to reconcile from SwiftUI here.
    }

    static func dismantleNSView(_ nsView: NSView, coordinator: Coordinator) {
        coordinator.cancel()
    }

    final class Coordinator {
        private let metrics: StreamMetrics
        private var cancellables: Set<AnyCancellable> = []
        private let fpsValueLabel = Coordinator.makeValueLabel(color: .systemGreen)
        private let bitrateValueLabel = Coordinator.makeValueLabel(color: .controlAccentColor)

        init(metrics: StreamMetrics) {
            self.metrics = metrics
        }

        func makeContainer() -> NSView {
            let fpsColumn = Coordinator.makeColumn(caption: "FPS", valueLabel: fpsValueLabel)
            let bitrateColumn = Coordinator.makeColumn(caption: "Bitrate", valueLabel: bitrateValueLabel)

            let spacer = NSView()
            spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)

            let row = NSStackView(views: [fpsColumn, spacer, bitrateColumn])
            row.orientation = .horizontal
            row.alignment = .top
            row.distribution = .fill
            row.translatesAutoresizingMaskIntoConstraints = false

            metrics.fps
                .receive(on: DispatchQueue.main)
                .sink { [weak self] value in
                    self?.fpsValueLabel.stringValue = String(format: "%.1f", value)
                }
                .store(in: &cancellables)
            metrics.bitrateMbps
                .receive(on: DispatchQueue.main)
                .sink { [weak self] value in
                    self?.bitrateValueLabel.stringValue = String(format: "%.1f Mbps", value)
                }
                .store(in: &cancellables)

            return row
        }

        func cancel() {
            cancellables.removeAll()
        }

        private static func makeColumn(caption: String, valueLabel: NSTextField) -> NSView {
            let captionLabel = NSTextField(labelWithString: caption)
            captionLabel.font = .systemFont(ofSize: 10)
            captionLabel.textColor = .secondaryLabelColor

            let column = NSStackView(views: [captionLabel, valueLabel])
            column.orientation = .vertical
            column.alignment = .leading
            column.spacing = 2
            return column
        }

        private static func makeValueLabel(color: NSColor) -> NSTextField {
            let label = NSTextField(labelWithString: "0.0")
            label.font = .systemFont(ofSize: 16, weight: .semibold)
            label.textColor = color
            return label
        }
    }
}

// MARK: - Display Settings

class DisplaySettings: ObservableObject {
    private let defaults = UserDefaults.standard
    private let keyPrefix = "Telemachus_"

    @Published var resolution: String {
        didSet { save("resolution", resolution) }
    }
    @Published var refreshRate: Int {
        didSet { save("refreshRate", refreshRate) }
    }
    @Published var hiDPI: Bool {
        didSet { save("hiDPI", hiDPI) }
    }
    @Published var bitrate: Int {
        didSet { save("bitrate", bitrate) }
    }
    @Published var quality: String {
        didSet { save("quality", quality) }
    }
    @Published var gamingBoost: Bool {
        didSet { save("gamingBoost", gamingBoost) }
    }
    @Published var port: UInt16 {
        didSet { save("port", Int(port)) }
    }
    @Published var rotation: Int {
        didSet { save("rotation", rotation) }
    }
    @Published var showAllResolutions: Bool {
        didSet { save("showAllResolutions", showAllResolutions) }
    }
    @Published var customWidth: Int {
        didSet { save("customWidth", customWidth) }
    }
    @Published var customHeight: Int {
        didSet { save("customHeight", customHeight) }
    }
    @Published var touchEnabled: Bool {
        didSet { save("touchEnabled", touchEnabled) }
    }
    @Published var connectionMode: ConnectionMode {
        didSet { save("connectionMode", connectionMode.rawValue) }
    }
    @Published var autoStartStreamingOnLaunch: Bool {
        didSet { save("autoStartStreamingOnLaunch", autoStartStreamingOnLaunch) }
    }
    @Published var hideDockIcon: Bool {
        didSet { save("hideDockIcon", hideDockIcon) }
    }
    @Published var startupMode: ConnectionMode {
        didSet { save("startupMode", startupMode.rawValue) }
    }
    @Published var displaySource: DisplaySourceMode {
        didSet { save("displaySource", displaySource.rawValue) }
    }
    @Published var selectedDisplayID: CGDirectDisplayID {
        didSet {
            save("selectedDisplayID", Int(selectedDisplayID))
            selectedDisplayUUID = DisplayCatalog.persistentUUID(for: selectedDisplayID)
            if let selectedDisplayUUID {
                let uuid = selectedDisplayUUID
                save("selectedDisplayUUID", uuid)
            } else {
                defaults.removeObject(forKey: keyPrefix + "selectedDisplayUUID")
            }
        }
    }
    private(set) var selectedDisplayUUID: String?
    @Published var hasCompletedOnboarding: Bool {
        didSet { save("hasCompletedOnboarding", hasCompletedOnboarding) }
    }
    @Published var adbDeviceSerial: String {
        didSet { save("adbDeviceSerial", adbDeviceSerial) }
    }
    @Published var internetSignalingEndpoint: String {
        didSet {
            // Persist only the non-sensitive service location. Tokens, URL
            // credentials, query strings and fragments must stay out of defaults.
            if Self.isSafeInternetSignalingEndpoint(internetSignalingEndpoint) {
                save("internetSignalingEndpoint", internetSignalingEndpoint)
            }
        }
    }
    @Published var internetRoutePreference: InternetRoutePreference {
        didSet { save("internetRoutePreference", internetRoutePreference.rawValue) }
    }
    @Published var internetSessionIdentifier: String {
        didSet { save("internetSessionIdentifier", internetSessionIdentifier) }
    }
    @Published var internetICEURLs: String {
        didSet {
            if Self.isSafeInternetICEURLList(internetICEURLs) {
                save("internetICEURLs", internetICEURLs)
            }
        }
    }
    @Published var internetTURNUsername: String {
        didSet { save("internetTURNUsername", internetTURNUsername) }
    }
    @Published var internetPeerDeviceID: String {
        didSet { save("internetPeerDeviceID", internetPeerDeviceID) }
    }
    @Published var internetSharedSecretName: String {
        didSet { save("internetSharedSecretName", internetSharedSecretName) }
    }
    @Published var internetBootstrapSecretName: String {
        didSet { save("internetBootstrapSecretName", internetBootstrapSecretName) }
    }
    @Published var internetTranscriptContextBase64: String {
        didSet { save("internetTranscriptContextBase64", internetTranscriptContextBase64) }
    }
    @Published var internetHostDeviceID: String {
        didSet { save("internetHostDeviceID", internetHostDeviceID) }
    }
    @Published var internetPeerKeyID: String {
        didSet { save("internetPeerKeyID", internetPeerKeyID) }
    }
    @Published var internetPeerKeyEpoch: UInt64 {
        didSet { save("internetPeerKeyEpoch", internetPeerKeyEpoch) }
    }
    /// Legacy single-device deny metadata. AppDelegate migrates these fields
    /// into RevokedInternetIdentityStore and clears them after persistence.
    @Published var internetRevokedPeerDeviceID: String {
        didSet { save("internetRevokedPeerDeviceID", internetRevokedPeerDeviceID) }
    }
    @Published var internetRevokedPeerKeyID: String {
        didSet { save("internetRevokedPeerKeyID", internetRevokedPeerKeyID) }
    }
    @Published var internetRevokedPeerKeyEpoch: UInt64 {
        didSet { save("internetRevokedPeerKeyEpoch", internetRevokedPeerKeyEpoch) }
    }
    @Published var internetPeerSigningPublicKeyBase64: String {
        didSet { save("internetPeerSigningPublicKeyBase64", internetPeerSigningPublicKeyBase64) }
    }
    @Published var internetAuthoritativeSessionEpoch: UInt64 {
        didSet {
            let maximum = UInt64(Int64.max)
            guard internetAuthoritativeSessionEpoch <= maximum else {
                internetAuthoritativeSessionEpoch = maximum
                return
            }
            save("internetAuthoritativeSessionEpoch", internetAuthoritativeSessionEpoch)
        }
    }

    // Runtime state (not persisted)
    @Published var displayCreated = false
    @Published var clientConnected = false
    /// Model string reported by the connected Android client (wire type 11).
    @Published var connectedDeviceModel: String?
    /// Max panel refresh rate (Hz) reported by the connected Android client.
    @Published var connectedDeviceMaxRefreshRate: Int?
    /// Device name of the wireless client currently streaming (nil when none).
    /// WirelessSection reads this to show a "Connected" badge on the matching row.
    @Published var currentWirelessDevice: String?
    /// Shown after a build/version change until the user dismisses it or both
    /// privacy grants look healthy again. Avoids the brittle admin `tccutil`
    /// reset path that XProtect has flagged in related apps.
    @Published var showPostUpdatePermissionHint = false
    @Published var hasScreenRecordingPermission = false
    @Published var hasAccessibilityPermission = false
    @Published var adbInstalled = false
    @Published var adbReverseConfigured = false
    @Published var usbDeviceConnected = false
    @Published var availableADBDevices: [String] = []
    @Published var availableDisplays: [HostDisplayDescriptor] = DisplayCatalog.onlineDisplays()
    @Published var wifiConnected = false
    @Published var listeningAddress: String?
    @Published var isRunning = false
    @Published var isStarting = false
    /// High-frequency live telemetry kept outside SwiftUI observation. Updated
    /// by AppDelegate's stats callback and rendered by `LiveMetricsView`.
    let metrics = StreamMetrics()
    @Published var captureMethod: String = "Initializing..."
    @Published var wirelessTokenError: String?
    @Published var internetStatus: InternetConnectionStatus = .idle
    @Published var internetErrorMessage: String?
    @Published var internetRecoverySuggestion: String?
    @Published var internetPairingCode: String?
    @Published var internetPeerDisplayName: String?
    @Published var internetPairingURL: String?
    @Published var internetPairingAcceptance: String?
    @Published var internetCredentialsAvailable = false
    @Published var internetRevocationCleanupPending = false

    var onToggleServer: (() -> Void)?
    var onRequestScreenRecordingPermission: (() -> Void)?
    var onRequestAccessibilityPermission: (() -> Void)?
    var onResetWirelessToken: (() -> Bool)?
    var onPairInternetDevice: (() -> Void)?
    var onRevokeInternetDevice: (() -> Void)?
    var onRetryInternetRevocationCleanup: (() -> Void)?
    var onConnectInternetSession: (() -> Void)?
    var onDisconnectInternetSession: (() -> Void)?

    var hasRunningIntent: Bool {
        isRunning || isStarting
    }
    var onSaveInternetCredentials: ((String, String) -> Bool)?
    var onCompleteInternetPairing: ((String) -> Void)?

    /// Assign a published field only when the new value differs from the
    /// current one, and report whether a write happened. Callers on periodic
    /// timers use this so an unchanged value does not publish a redundant
    /// `objectWillChange`, which would otherwise re-evaluate the settings UI
    /// body every tick and accumulate SwiftUI observation state over time.
    /// Returns `true` when the value changed and was written.
    @discardableResult
    func setIfChanged<Value: Equatable>(
        _ newValue: Value,
        to keyPath: ReferenceWritableKeyPath<DisplaySettings, Value>
    ) -> Bool {
        guard self[keyPath: keyPath] != newValue else { return false }
        self[keyPath: keyPath] = newValue
        return true
    }

    init() {
        self.resolution = defaults.string(forKey: keyPrefix + "resolution") ?? "2000x1200"
        self.refreshRate = defaults.object(forKey: keyPrefix + "refreshRate") as? Int ?? 60  // Default: 60 — balanced for most tablets. 120 may saturate high-res panel pipelines.
        self.hiDPI = defaults.bool(forKey: keyPrefix + "hiDPI")
        self.bitrate = defaults.object(forKey: keyPrefix + "bitrate") as? Int ?? 35
        self.quality = defaults.string(forKey: keyPrefix + "quality") ?? "ultralow"  // Default: fastest encoding
        self.gamingBoost = defaults.bool(forKey: keyPrefix + "gamingBoost")
        // Default port 54321 (was 8888 in <=0.7.1; 8888 collides with jupyter/splunk/HP printers).
        // Existing users keep their saved value.
        self.port = UInt16(defaults.object(forKey: keyPrefix + "port") as? Int ?? 54321)
        self.rotation = defaults.object(forKey: keyPrefix + "rotation") as? Int ?? 0
        self.showAllResolutions = defaults.bool(forKey: keyPrefix + "showAllResolutions")
        self.customWidth = defaults.object(forKey: keyPrefix + "customWidth") as? Int ?? 1920
        self.customHeight = defaults.object(forKey: keyPrefix + "customHeight") as? Int ?? 1200
        self.touchEnabled = defaults.object(forKey: keyPrefix + "touchEnabled") as? Bool ?? true
        let modeRaw = defaults.string(forKey: keyPrefix + "connectionMode") ?? ConnectionMode.usb.rawValue
        self.connectionMode = ConnectionMode(rawValue: modeRaw) ?? .usb
        self.autoStartStreamingOnLaunch = defaults.object(forKey: keyPrefix + "autoStartStreamingOnLaunch") as? Bool ?? true
        self.hideDockIcon = defaults.object(forKey: keyPrefix + "hideDockIcon") as? Bool ?? false
        let startupRaw = defaults.string(forKey: keyPrefix + "startupMode") ?? modeRaw
        self.startupMode = ConnectionMode(rawValue: startupRaw) ?? .usb
        let sourceRaw = defaults.string(forKey: keyPrefix + "displaySource") ?? DisplaySourceMode.currentMain.rawValue
        self.displaySource = DisplaySourceMode(rawValue: sourceRaw) ?? .currentMain
        self.selectedDisplayUUID = defaults.string(
            forKey: keyPrefix + "selectedDisplayUUID"
        )
        let storedDisplayID = CGDirectDisplayID(
            defaults.object(forKey: keyPrefix + "selectedDisplayID") as? Int
                ?? Int(CGMainDisplayID())
        )
        self.selectedDisplayID = DisplayCatalog.resolve(
            persistentUUID: selectedDisplayUUID,
            fallbackID: storedDisplayID
        )
        self.hasCompletedOnboarding = defaults.bool(forKey: keyPrefix + "hasCompletedOnboarding")
        self.adbDeviceSerial = defaults.string(
            forKey: keyPrefix + "adbDeviceSerial"
        ) ?? ""
        let storedInternetEndpoint = defaults.string(
            forKey: keyPrefix + "internetSignalingEndpoint"
        ) ?? "http://127.0.0.1:8088"
        self.internetSignalingEndpoint = Self.isSafeInternetSignalingEndpoint(storedInternetEndpoint)
            ? storedInternetEndpoint
            : "http://127.0.0.1:8088"
        let internetRouteRaw = defaults.string(
            forKey: keyPrefix + "internetRoutePreference"
        ) ?? InternetRoutePreference.preferDirect.rawValue
        self.internetRoutePreference = InternetRoutePreference(rawValue: internetRouteRaw) ?? .preferDirect
        self.internetSessionIdentifier = defaults.string(
            forKey: keyPrefix + "internetSessionIdentifier"
        ) ?? ""
        let storedInternetICEURLs = defaults.string(
            forKey: keyPrefix + "internetICEURLs"
        ) ?? "stun:127.0.0.1:9"
        self.internetICEURLs = Self.isSafeInternetICEURLList(storedInternetICEURLs)
            ? storedInternetICEURLs
            : "stun:127.0.0.1:9"
        self.internetTURNUsername = defaults.string(
            forKey: keyPrefix + "internetTURNUsername"
        ) ?? ""
        self.internetPeerDeviceID = defaults.string(
            forKey: keyPrefix + "internetPeerDeviceID"
        ) ?? ""
        self.internetSharedSecretName = defaults.string(
            forKey: keyPrefix + "internetSharedSecretName"
        ) ?? ""
        self.internetBootstrapSecretName = defaults.string(
            forKey: keyPrefix + "internetBootstrapSecretName"
        ) ?? ""
        self.internetTranscriptContextBase64 = defaults.string(
            forKey: keyPrefix + "internetTranscriptContextBase64"
        ) ?? ""
        self.internetHostDeviceID = defaults.string(
            forKey: keyPrefix + "internetHostDeviceID"
        ) ?? "mac-\(UUID().uuidString.lowercased())"
        self.internetPeerKeyID = defaults.string(
            forKey: keyPrefix + "internetPeerKeyID"
        ) ?? ""
        self.internetPeerKeyEpoch = (defaults.object(
            forKey: keyPrefix + "internetPeerKeyEpoch"
        ) as? NSNumber)?.uint64Value ?? 0
        self.internetRevokedPeerDeviceID = defaults.string(
            forKey: keyPrefix + "internetRevokedPeerDeviceID"
        ) ?? ""
        self.internetRevokedPeerKeyID = defaults.string(
            forKey: keyPrefix + "internetRevokedPeerKeyID"
        ) ?? ""
        self.internetRevokedPeerKeyEpoch = (defaults.object(
            forKey: keyPrefix + "internetRevokedPeerKeyEpoch"
        ) as? NSNumber)?.uint64Value ?? 0
        self.internetPeerSigningPublicKeyBase64 = defaults.string(
            forKey: keyPrefix + "internetPeerSigningPublicKeyBase64"
        ) ?? ""
        self.internetAuthoritativeSessionEpoch = min((defaults.object(
            forKey: keyPrefix + "internetAuthoritativeSessionEpoch"
        ) as? NSNumber)?.uint64Value ?? 0, UInt64(Int64.max))

        if defaults.string(forKey: keyPrefix + "internetHostDeviceID") == nil {
            defaults.set(internetHostDeviceID, forKey: keyPrefix + "internetHostDeviceID")
        }

        if selectedDisplayUUID == nil,
           let migratedUUID = DisplayCatalog.persistentUUID(
               for: selectedDisplayID
           ) {
            selectedDisplayUUID = migratedUUID
            defaults.set(
                migratedUUID,
                forKey: keyPrefix + "selectedDisplayUUID"
            )
        }

        print("Loaded settings: \(resolution) @ \(refreshRate)Hz, bitrate=\(bitrate), quality=\(quality)")
    }

    private func save(_ key: String, _ value: Any) {
        defaults.set(value, forKey: keyPrefix + key)
    }

    static func isSafeInternetSignalingEndpoint(_ value: String) -> Bool {
        guard let components = URLComponents(string: value),
              let scheme = components.scheme?.lowercased(),
              let host = components.host,
              !host.isEmpty,
              components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil else {
            return false
        }
        return scheme == "https" || (scheme == "http" && host == "127.0.0.1")
    }

    static func isSafeInternetICEURLList(_ value: String) -> Bool {
        let values = value.split(separator: ",").map {
            $0.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        guard !values.isEmpty else { return false }
        return values.allSatisfy { raw in
            guard let url = URL(string: raw),
                  let scheme = url.scheme?.lowercased(),
                  ["stun", "stuns", "turn", "turns"].contains(scheme),
                  let separator = raw.firstIndex(of: ":"),
                  raw.index(after: separator) < raw.endIndex else {
                return false
            }
            let authority = raw[raw.index(after: separator)...]
                .split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)[0]
            return !authority.contains("@")
        }
    }

    struct ResolutionGroup: Identifiable {
        let id = UUID()
        let name: String
        let ratio: String
        let resolutions: [String]
    }

    static let resolutionGroups: [ResolutionGroup] = [
        ResolutionGroup(name: "16:10", ratio: "Widescreen", resolutions: [
            "1280x800", "1440x900", "1680x1050", "1920x1200", "2560x1600"
        ]),
        ResolutionGroup(name: "16:9", ratio: "HD/4K", resolutions: [
            "1280x720", "1366x768", "1600x900", "1920x1080", "2560x1440", "3840x2160"
        ]),
        ResolutionGroup(name: "4:3", ratio: "Classic", resolutions: [
            "1024x768", "1280x960", "1600x1200"
        ]),
        ResolutionGroup(name: "3:2", ratio: "Surface/Pixel", resolutions: [
            "1920x1280", "2160x1440", "2736x1824"
        ]),
        ResolutionGroup(name: "5:3", ratio: "Tablet Wide", resolutions: [
            "2000x1200", "2560x1536", "2800x1680"
        ]),
        ResolutionGroup(name: "4:3", ratio: "iPad", resolutions: [
            "2048x1536", "2224x1668", "2388x1668", "2732x2048"
        ])
    ]

    static let commonResolutions = [
        "1920x1080", "1920x1200", "2560x1440", "2560x1600"
    ]

    static var allResolutions: [String] {
        resolutionGroups.flatMap { $0.resolutions }
    }

    var effectiveBitrate: Int {
        return gamingBoost ? 45 : bitrate
    }

    var effectiveQuality: String {
        return gamingBoost ? "ultralow" : quality
    }

    var effectiveRefreshRate: Int {
        return refreshRate
    }

    func toggleServer() {
        onToggleServer?()
    }

    func requestScreenRecordingPermission() {
        onRequestScreenRecordingPermission?()
    }

    func requestAccessibilityPermission() {
        onRequestAccessibilityPermission?()
    }

    func resetWirelessToken() -> Bool {
        onResetWirelessToken?() ?? false
    }

    func pairInternetDevice() {
        internetErrorMessage = nil
        internetRecoverySuggestion = nil
        onPairInternetDevice?()
    }

    func revokeInternetDevice() {
        onRevokeInternetDevice?()
    }

    func retryInternetRevocationCleanup() {
        onRetryInternetRevocationCleanup?()
    }

    func connectInternetSession() {
        internetErrorMessage = nil
        internetRecoverySuggestion = nil
        onConnectInternetSession?()
    }

    func disconnectInternetSession() {
        onDisconnectInternetSession?()
    }

    func saveInternetCredentials(signalingToken: String, turnCredential: String) -> Bool {
        onSaveInternetCredentials?(signalingToken, turnCredential) ?? false
    }

    func completeInternetPairing(deviceRequest: String) {
        onCompleteInternetPairing?(deviceRequest)
    }

    var internetStatusColor: Color {
        switch internetStatus {
        case .direct: return .green
        case .relay: return .blue
        case .pairing, .connecting, .recovering: return .orange
        case .revoked, .failed: return .red
        case .idle, .paired: return .secondary
        }
    }

    /// Detect rebuilds / re-signs that can leave stale TCC grants. Uses a
    /// fingerprint of CFBundleVersion plus the executable's mtime and size so
    /// ad-hoc source builds that keep `0.0.0` still trip the hint.
    func evaluatePostUpdatePermissionHint() {
        let fingerprint = currentBinaryFingerprint()
        guard !fingerprint.isEmpty else {
            showPostUpdatePermissionHint = false
            return
        }

        let lastKey = keyPrefix + "lastKnownBinaryFingerprint"
        let dismissedKey = keyPrefix + "dismissedPostUpdatePermissionHintFingerprint"
        let pendingKey = keyPrefix + "pendingPostUpdatePermissionHintFingerprint"
        let lastFingerprint = defaults.string(forKey: lastKey) ?? ""
        let dismissedFor = defaults.string(forKey: dismissedKey) ?? ""

        if lastFingerprint.isEmpty {
            // First launch of this tracking code. If other Telemachus settings
            // already exist, this is an upgrade/re-sign into the fix — seed the
            // pending hint so the recovery banner appears on this update.
            let looksLikePriorInstall =
                defaults.object(forKey: keyPrefix + "hasCompletedOnboarding") != nil ||
                defaults.object(forKey: keyPrefix + "refreshRate") != nil ||
                defaults.object(forKey: keyPrefix + "port") != nil
            if looksLikePriorInstall {
                defaults.set(fingerprint, forKey: pendingKey)
                debugLog("Prior install detected without fingerprint history; seeding post-update permission hint")
            }
        } else if lastFingerprint != fingerprint {
            defaults.set(fingerprint, forKey: pendingKey)
            debugLog("App binary fingerprint changed; showing post-update permission hint")
        }

        defaults.set(fingerprint, forKey: lastKey)

        let pending = defaults.string(forKey: pendingKey) ?? ""
        showPostUpdatePermissionHint =
            pending == fingerprint && dismissedFor != fingerprint
    }

    func dismissPostUpdatePermissionHint() {
        let fingerprint = currentBinaryFingerprint()
        if !fingerprint.isEmpty {
            defaults.set(fingerprint, forKey: keyPrefix + "dismissedPostUpdatePermissionHintFingerprint")
            defaults.removeObject(forKey: keyPrefix + "pendingPostUpdatePermissionHintFingerprint")
        }
        showPostUpdatePermissionHint = false
    }

    /// Clear only once Screen Recording and Accessibility both look healthy,
    /// so a still-stale Accessibility grant does not lose the recovery guidance.
    /// Users who do not need Accessibility can dismiss manually.
    func clearPostUpdatePermissionHintIfResolved() {
        guard showPostUpdatePermissionHint else { return }
        if hasScreenRecordingPermission && hasAccessibilityPermission {
            dismissPostUpdatePermissionHint()
        }
    }

    /// Version alone is not enough: `scripts/package_mac.sh` defaults to
    /// `CFBundleVersion` `0.0.0` on every local rebuild, which still re-signs
    /// and can invalidate TCC.
    private func currentBinaryFingerprint() -> String {
        let version = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? ""
        guard let executableURL = Bundle.main.executableURL else {
            return version
        }
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: executableURL.path),
              let modified = attrs[.modificationDate] as? Date,
              let size = attrs[.size] as? NSNumber else {
            return version
        }
        return "\(version)|\(Int(modified.timeIntervalSince1970))|\(size.intValue)"
    }

    func resetToDefaults() {
        guard !internetRevocationCleanupPending else {
            internetStatus = .revoked
            internetErrorMessage = "Revoked pairing-secret cleanup is still pending."
            internetRecoverySuggestion = "Choose Retry Cleanup before resetting settings so the peer-scoped cleanup marker remains reachable."
            return
        }
        let keys = ["resolution", "refreshRate", "hiDPI", "bitrate", "quality",
                    "gamingBoost", "port", "rotation", "showAllResolutions",
                    "customWidth", "customHeight", "touchEnabled", "autoStartStreamingOnLaunch", "hideDockIcon", "startupMode",
                    "displaySource", "selectedDisplayID", "selectedDisplayUUID", "adbDeviceSerial",
                    "internetSignalingEndpoint", "internetRoutePreference",
                    "internetSessionIdentifier", "internetICEURLs", "internetTURNUsername",
                    "internetPeerDeviceID", "internetSharedSecretName",
                    "internetBootstrapSecretName", "internetTranscriptContextBase64",
                    "internetHostDeviceID", "internetPeerKeyID", "internetPeerKeyEpoch",
                    "internetPeerSigningPublicKeyBase64", "internetAuthoritativeSessionEpoch"]
        for key in keys {
            defaults.removeObject(forKey: keyPrefix + key)
        }

        resolution = "2000x1200"
        refreshRate = 60
        hiDPI = false
        bitrate = 35
        quality = "ultralow"  // Default: fastest encoding
        gamingBoost = false
        port = 54321
        rotation = 0
        showAllResolutions = false
        customWidth = 1920
        customHeight = 1200
        touchEnabled = true
        autoStartStreamingOnLaunch = true
        hideDockIcon = false
        startupMode = .usb
        displaySource = .currentMain
        selectedDisplayID = CGMainDisplayID()
        selectedDisplayUUID = DisplayCatalog.persistentUUID(
            for: selectedDisplayID
        )
        adbDeviceSerial = ""
        internetSignalingEndpoint = "http://127.0.0.1:8088"
        internetRoutePreference = .preferDirect
        internetSessionIdentifier = ""
        internetICEURLs = "stun:127.0.0.1:9"
        internetTURNUsername = ""
        internetPeerDeviceID = ""
        internetSharedSecretName = ""
        internetBootstrapSecretName = ""
        internetTranscriptContextBase64 = ""
        internetHostDeviceID = "mac-\(UUID().uuidString.lowercased())"
        internetPeerKeyID = ""
        internetPeerKeyEpoch = 0
        internetPeerSigningPublicKeyBase64 = ""
        internetAuthoritativeSessionEpoch = 0

        print("Settings reset to defaults")
    }

    var resolutionSize: (width: Int, height: Int) {
        let parts = resolution.split(separator: "x")
        let baseWidth = Int(parts[0]) ?? 1920
        let baseHeight = Int(parts[1]) ?? 1200
        if rotation == 90 || rotation == 270 {
            return (baseHeight, baseWidth)
        }
        return (baseWidth, baseHeight)
    }

    static func isValidCustomResolution(width: Int, height: Int) -> Bool {
        width >= 640 && width <= 7680 && height >= 480 && height <= 4320
    }

    func applyCustomResolution() {
        if DisplaySettings.isValidCustomResolution(width: customWidth, height: customHeight) {
            resolution = "\(customWidth)x\(customHeight)"
        }
    }
}

// MARK: - Window Controller

class SettingsWindowController: NSWindowController, NSWindowDelegate {
    convenience init(settings: DisplaySettings) {
        let window = ConstrainedWindow(
            contentRect: NSRect(x: 0, y: 0, width: 480, height: 780),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )

        window.title = "Vibe Screen"
        window.titlebarAppearsTransparent = true
        window.backgroundColor = .windowBackgroundColor
        window.isMovableByWindowBackground = true
        window.center()
        window.contentView = NSHostingView(rootView: TelemachusRootView(settings: settings))
        window.isReleasedWhenClosed = false

        self.init(window: window)
        window.delegate = self
    }

    func windowDidMove(_ notification: Notification) {
        guard let window = notification.object as? NSWindow,
              let screen = window.screen ?? NSScreen.main else { return }

        var frame = window.frame
        let visibleFrame = screen.visibleFrame
        let minVisibleWidth: CGFloat = 100
        let minVisibleHeight: CGFloat = 50

        if frame.maxX < visibleFrame.minX + minVisibleWidth {
            frame.origin.x = visibleFrame.minX - frame.width + minVisibleWidth
        } else if frame.minX > visibleFrame.maxX - minVisibleWidth {
            frame.origin.x = visibleFrame.maxX - minVisibleWidth
        }

        if frame.maxY < visibleFrame.minY + minVisibleHeight {
            frame.origin.y = visibleFrame.minY - frame.height + minVisibleHeight
        } else if frame.minY > visibleFrame.maxY - minVisibleHeight {
            frame.origin.y = visibleFrame.maxY - minVisibleHeight
        }

        if window.frame != frame {
            window.setFrame(frame, display: true)
        }
    }
}

class ConstrainedWindow: NSWindow {
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect {
        guard let screen = screen ?? self.screen ?? NSScreen.main else {
            return frameRect
        }

        var constrainedRect = frameRect
        let visibleFrame = screen.visibleFrame
        let minVisibleWidth: CGFloat = 100
        let minVisibleHeight: CGFloat = 50

        if constrainedRect.maxX < visibleFrame.minX + minVisibleWidth {
            constrainedRect.origin.x = visibleFrame.minX - constrainedRect.width + minVisibleWidth
        } else if constrainedRect.minX > visibleFrame.maxX - minVisibleWidth {
            constrainedRect.origin.x = visibleFrame.maxX - minVisibleWidth
        }

        if constrainedRect.maxY < visibleFrame.minY + minVisibleHeight {
            constrainedRect.origin.y = visibleFrame.minY - constrainedRect.height + minVisibleHeight
        } else if constrainedRect.minY > visibleFrame.maxY - minVisibleHeight {
            constrainedRect.origin.y = visibleFrame.maxY - minVisibleHeight
        }

        return constrainedRect
    }
}

// MARK: - Wireless Section

struct WirelessSection: View {
    @ObservedObject var settings: DisplaySettings
    let pairedDeviceStore: PairedDeviceStore
    @State private var qrImage: NSImage?
    @State private var pairedDevices: [PairedDevice] = []
    @State private var showResetConfirm = false
    /// Used to force the relative-time labels to recompute every tick even when
    /// the underlying lastConnected timestamp hasn't changed (e.g. while a
    /// device is disconnected and we still want "5 minutes ago" to count up).
    @State private var nowTick: Date = Date()

    private var pairingEndpoint: WirelessPairingEndpoint {
        WirelessPairingEndpoint(address: settings.listeningAddress, port: settings.port)
    }

    var body: some View {
        VStack(spacing: 12) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "lock.trianglebadge.exclamationmark")
                    .foregroundColor(.orange)
                Text("Wireless is experimental and intended only for a trusted private LAN. Video, input, and the pairing token are not encrypted; the saved token is protected by macOS Keychain.")
                    .font(.system(size: 11))
                    .foregroundColor(.secondary)
                Spacer()
            }
            .padding(8)
            .background(Color.orange.opacity(0.12))
            .cornerRadius(6)

            if !settings.isRunning {
                HStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.orange)
                    Text("Click Start at the top to begin listening, then scan the QR.")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                    Spacer()
                }
                .padding(8)
                .background(Color.orange.opacity(0.12))
                .cornerRadius(6)
            }
            FrostedGroupBox(title: "Pair Device", icon: "qrcode") {
                VStack(spacing: 8) {
                    if let qr = qrImage {
                        Image(nsImage: qr)
                            .interpolation(.none)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 180, height: 180)
                            .padding(8)
                            .background(Color.white)
                            .cornerRadius(8)
                    } else {
                        VStack(spacing: 6) {
                            Text(
                                settings.wirelessTokenError.map {
                                    "Could not access the pairing token: \($0)"
                                } ?? "Connect this Mac to the tablet's trusted LAN to generate a QR code."
                            )
                                .font(.system(size: 11))
                                .foregroundColor(
                                    settings.wirelessTokenError == nil ? .secondary : .red
                                )
                                .multilineTextAlignment(.center)
                            if settings.wirelessTokenError != nil {
                                Button(action: refreshQR) {
                                    Image(systemName: "arrow.clockwise")
                                }
                                .buttonStyle(.borderless)
                                .help("Retry pairing token access")
                            }
                        }
                    }
                    Text("Scan this QR from Vibe Screen Android (Wireless tab)")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                    Text(pairingEndpoint.statusText)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity)
            }

            FrostedGroupBox(
                title: "Paired Devices (\(pairedDevices.count))",
                icon: "ipad.and.iphone",
                content: {
                if pairedDevices.isEmpty {
                    Text("No devices paired yet.")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    VStack(spacing: 6) {
                        ForEach(pairedDevices, id: \.name) { device in
                            let isLive = settings.currentWirelessDevice == device.name
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(device.name).font(.system(size: 12, weight: .medium))
                                    HStack(spacing: 4) {
                                        Circle()
                                            .fill(isLive ? Color.green : Color.secondary)
                                            .frame(width: 6, height: 6)
                                        Text(isLive ? "Connected" : relativeTimeString(from: device.lastConnected, to: nowTick))
                                            .font(.system(size: 10))
                                            .foregroundColor(isLive ? .green : .secondary)
                                    }
                                }
                                Spacer()
                                Button("Remove History") {
                                    pairedDeviceStore.forget(name: device.name)
                                    refreshPaired()
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                                .help("Removes this name from local history. Reset the token below to revoke access.")
                            }
                            .padding(6)
                            .background(.ultraThinMaterial)
                            .cornerRadius(6)
                        }
                    }
                }
                Button("Reset Token (forget all)") {
                    showResetConfirm = true
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .foregroundColor(.red)
                .padding(.top, 6)
            },
            trailing: {
                Button(action: {
                    nowTick = Date()
                    refreshPaired()
                }) {
                    Image(systemName: "arrow.counterclockwise")
                        .font(.system(size: 12, weight: .semibold))
                }
                .buttonStyle(.borderless)
                .help("Refresh list and timestamps")
            })
        }
        .onAppear {
            refreshQR()
            refreshPaired()
            nowTick = Date()
        }
        // One-parameter onChange(of:perform:) works on macOS 13+. The
        // two-parameter form requires macOS 14 and would block Ventura.
        // Deprecation is a compile-time warning only on Xcode 15+ SDKs.
        .onChange(of: pairingEndpoint) { _ in refreshQR() }
        .onReceive(Timer.publish(every: 5, on: .main, in: .common).autoconnect()) { now in
            nowTick = now
            refreshPaired()
        }
        .alert("Reset Token?", isPresented: $showResetConfirm) {
            Button("Cancel", role: .cancel) { }
            Button("Reset", role: .destructive) {
                if settings.resetWirelessToken() {
                    pairedDeviceStore.clear()
                }
                refreshQR()
                refreshPaired()
            }
        } message: {
            Text("This will disconnect all paired devices. They will need to scan the new QR to connect again.")
        }
    }

    private func refreshQR() {
        guard pairingEndpoint.address != nil else {
            qrImage = nil
            return
        }
        let token: Data
        do {
            token = try WirelessAuth.loadOrCreate()
            settings.setIfChanged(nil, to: \.wirelessTokenError)
        } catch {
            settings.setIfChanged(error.localizedDescription, to: \.wirelessTokenError)
            qrImage = nil
            return
        }
        let name = Host.current().localizedName ?? "Mac"
        guard let url = pairingEndpoint.pairingURL(token: token, name: name) else {
            qrImage = nil
            return
        }
        qrImage = QRRenderer.render(url: url, size: 180)
    }

    private func refreshPaired() {
        pairedDevices = pairedDeviceStore.all()
    }

    private func relativeTimeString(from past: Date, to now: Date) -> String {
        let elapsed = max(0, now.timeIntervalSince(past))
        if elapsed < 30 { return "just now" }
        if elapsed < 60 { return "\(Int(elapsed)) seconds ago" }
        if elapsed < 3600 {
            let m = Int(elapsed / 60)
            return "\(m) minute\(m == 1 ? "" : "s") ago"
        }
        if elapsed < 86400 {
            let h = Int(elapsed / 3600)
            return "\(h) hour\(h == 1 ? "" : "s") ago"
        }
        let d = Int(elapsed / 86400)
        return "\(d) day\(d == 1 ? "" : "s") ago"
    }
}
