import SwiftUI
import UIKit
import UniformTypeIdentifiers
import VibeScreenCore

struct ContentView: View {
    @ObservedObject var model: StreamViewModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var pairingURL = ""
    @AppStorage("wakeMAC") private var wakeMAC = ""
    @State private var showsAdvancedControls = false

    var body: some View {
        NavigationStack {
            Group {
                if model.isStreaming {
                    StreamSurface(model: model)
                } else {
                    connectionForm
                }
            }
            .navigationTitle("Vibe Screen")
            .toolbar {
                if model.isStreaming {
                    Button("功能") {
                        _ = model.releaseActiveInput()
                        showsAdvancedControls = true
                    }
                    Button { model.requestKeyboardInput() } label: {
                        Label("键盘输入", systemImage: "keyboard")
                    }
                    .disabled(!model.keyboardInputAvailable)
                    Button("断开") { model.disconnect() }
                }
            }
            .sheet(isPresented: $showsAdvancedControls) {
                NavigationStack { AdvancedControlsView(model: model) }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase != .active { _ = model.releaseActiveInput() }
            }
        }
    }

    private var connectionForm: some View {
        Form {
            Section("Mac 主机") {
                TextField("telemachus:// 配对链接", text: $pairingURL, axis: .vertical)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            }
            Section {
                Button(model.isConnecting ? "连接中…" : "连接") {
                    let currentPairingURL = pairingURL
                    pairingURL = ""
                    Task { await model.connect(pairingURL: currentPairingURL) }
                }
                .disabled(pairingURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isConnecting)
            } footer: {
                Text("粘贴 Mac 提供的 trusted-LAN 配对链接；未写端口时使用 54321。首次连接时请允许本地网络访问。")
            }
            Section {
                TextField("MAC 地址", text: $wakeMAC)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                Button("发送 Wake-on-LAN") { model.wake(macAddress: wakeMAC) }
            } header: {
                Text("唤醒已授权主机")
            } footer: {
                Text("仅在此前协商过设备身份且本地策略允许时发送；Magic Packet 本身不提供认证。")
            }
            if model.managedConfiguration.policy.isManaged {
                Section("组织管理") {
                    Text("部分剪贴板、文件、音频、唤醒或手势能力可能被锁定。")
                }
            }
            if let error = model.errorMessage {
                Section("状态") { Text(error).foregroundStyle(.red) }
            }
        }
    }
}

private struct StreamSurface: View {
    @ObservedObject var model: StreamViewModel
    @FocusState private var acceptsHardwareKeyboard: Bool
    @GestureState private var touchGestureActive = false
    @State private var touchActivityRevision: UInt64 = 0
    @State private var touchEndedNormally = false

    var body: some View {
        PixelBufferView(pixelBuffer: model.pixelBuffer)
            .background(.black)
            .ignoresSafeArea()
            .contentShape(Rectangle())
            .focusable()
            .focused($acceptsHardwareKeyboard)
            .gesture(
                DragGesture(minimumDistance: 0)
                    .updating($touchGestureActive) { _, active, _ in active = true }
                    .onChanged { value in
                        touchActivityRevision &+= 1
                        touchEndedNormally = false
                        model.sendTouch(location: value.location, size: model.viewportSize, ended: false)
                    }
                    .onEnded { value in
                        touchActivityRevision &+= 1
                        touchEndedNormally = true
                        model.sendTouch(location: value.location, size: model.viewportSize, ended: true)
                    }
            )
            .simultaneousGesture(
                TapGesture(count: 2).onEnded { model.performGesture(.doubleTap) }
            )
            .simultaneousGesture(
                LongPressGesture().onEnded { _ in model.performGesture(.longPress) }
            )
            .overlay(alignment: .top) {
                if model.displayBindings.count > 1 {
                    Picker("显示器", selection: displaySelection) {
                        ForEach(model.displayBindings, id: \.streamID) { binding in
                            Text(binding.displayID).tag(Optional(binding.streamID))
                        }
                    }
                    .pickerStyle(.segmented)
                    .padding()
                }
            }
            .overlay {
                GeometryReader { geometry in
                    Color.clear.onAppear { model.viewportSize = geometry.size }
                        .onChange(of: geometry.size) { _, size in model.viewportSize = size }
                }
            }
            .onContinuousHover { phase in
                switch phase {
                case .active(let location):
                    _ = model.sendPointerHover(location: location, size: model.viewportSize)
                case .ended:
                    _ = model.releaseActiveInput()
                }
            }
            .onKeyPress(phases: [.down, .up]) { press in
                let standardModifierMask = modifierMask(for: press.modifiers)
                guard let usage = usbHIDUsage(for: press.key) else { return .ignored }
                let pressed = press.phase == .down
                guard !NativeKeyCapturePolicy.shouldIgnoreEvent(
                    standardModifierMask: standardModifierMask,
                    voiceOverRunning: UIAccessibility.isVoiceOverRunning,
                    pressed: pressed,
                    keyWasCaptured: model.hasCapturedKey(usbHIDUsage: usage)
                ) else { return .ignored }
                return model.sendKey(
                    usbHIDUsage: usage,
                    pressed: pressed,
                    standardModifierMask: standardModifierMask,
                    text: pressed ? press.characters : ""
                ) ? .handled : .ignored
            }
            .onAppear { acceptsHardwareKeyboard = model.keyboardInputAvailable }
            .onChange(of: model.keyboardFocusRequest) { _, _ in
                acceptsHardwareKeyboard = model.keyboardInputAvailable
            }
            .onChange(of: acceptsHardwareKeyboard) { _, focused in
                if !focused { _ = model.releaseActiveInput() }
            }
            .onChange(of: touchGestureActive) { wasActive, isActive in
                guard wasActive && !isActive else { return }
                let endingRevision = touchActivityRevision
                Task { @MainActor in
                    await Task.yield()
                    guard touchActivityRevision == endingRevision else { return }
                    if touchEndedNormally {
                        touchEndedNormally = false
                    } else {
                        _ = model.releaseActiveInput()
                    }
                }
            }
            .onDisappear { _ = model.releaseActiveInput() }
            .accessibilityLabel("Mac 显示画面")
    }

    private var displaySelection: Binding<UInt64?> {
        Binding(
            get: { model.selectedStreamID },
            set: { streamID in
                if let streamID { model.selectDisplay(streamID: streamID) }
            }
        )
    }

    private func usbHIDUsage(for key: KeyEquivalent) -> UInt32? {
        switch key {
        case .return: 0x28
        case .escape: 0x29
        case .delete: 0x2A
        case .tab: 0x2B
        case .space: 0x2C
        case .home: 0x4A
        case .pageUp: 0x4B
        case .deleteForward: 0x4C
        case .end: 0x4D
        case .pageDown: 0x4E
        case .rightArrow: 0x4F
        case .leftArrow: 0x50
        case .downArrow: 0x51
        case .upArrow: 0x52
        default: USBHIDKeyboardMapper.usage(for: key.character)
        }
    }

    private func modifierMask(for modifiers: EventModifiers) -> UInt32 {
        var mask: UInt32 = 0
        if modifiers.contains(.control) { mask |= USBHIDModifierWire.leftControl }
        if modifiers.contains(.shift) { mask |= USBHIDModifierWire.leftShift }
        if modifiers.contains(.option) { mask |= USBHIDModifierWire.leftOption }
        if modifiers.contains(.command) { mask |= USBHIDModifierWire.leftCommand }
        return mask
    }
}

private struct AdvancedControlsView: View {
    @ObservedObject var model: StreamViewModel
    @ObservedObject private var clipboard: ClipboardController
    @Environment(\.dismiss) private var dismiss
    @State private var importsFile = false
    @State private var wakeMAC = ""

    init(model: StreamViewModel) {
        self.model = model
        _clipboard = ObservedObject(wrappedValue: model.clipboard)
    }

    var body: some View {
        List {
            Section("剪贴板（仅显式操作）") {
                Button("把当前剪贴板发送到 Mac") { model.sendClipboardFromPasteboard() }
                if clipboard.pendingRemoteContent != nil {
                    Button("允许写入来自 Mac 的剪贴板") { model.approveRemoteClipboard() }
                    Button("拒绝", role: .destructive) { clipboard.rejectPending() }
                }
            }
            Section("文件传输") {
                Button("选择文件发送") { importsFile = true }
                if let name = model.pendingFileName {
                    Text("Mac 请求发送：\(name)")
                    Button("允许接收") { model.approveIncomingFile() }
                    Button("拒绝", role: .destructive) { model.rejectIncomingFile() }
                }
                if let url = model.completedFileURL {
                    ShareLink(item: url) { Label("导出已校验文件", systemImage: "square.and.arrow.up") }
                }
            }
            Section("手势映射") {
                ForEach(GestureTrigger.allCases, id: \.self) { trigger in
                    Menu(trigger.rawValue) {
                        Button("切换显示器") { model.setGestureMapping(trigger: trigger, action: .switchDisplay) }
                        Button("显示键盘") { model.setGestureMapping(trigger: trigger, action: .showKeyboard) }
                        ForEach(model.availableHostActions, id: \.self) { action in
                            Button(action) {
                                model.setGestureMapping(trigger: trigger, action: .invokeHostAction(action))
                            }
                        }
                    }
                }
            }
            Section {
                TextField("MAC 地址，例如 00:11:22:33:44:55", text: $wakeMAC)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                Button("发送 Wake-on-LAN") { model.wake(macAddress: wakeMAC) }
            } header: {
                Text("唤醒已配对 Mac")
            } footer: {
                Text("Magic Packet 本身不提供认证，只允许当前已配对会话且本地策略未禁用时发送。")
            }
        }
        .navigationTitle("高级功能")
        .toolbar { Button("完成") { dismiss() } }
        .fileImporter(isPresented: $importsFile, allowedContentTypes: [.data]) { result in
            switch result {
            case let .success(url): model.sendFile(at: url)
            case let .failure(error): model.report(error)
            }
        }
    }
}
