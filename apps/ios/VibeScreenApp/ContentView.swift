import SwiftUI
import UniformTypeIdentifiers
import VibeScreenCore

struct ContentView: View {
    @ObservedObject var model: StreamViewModel
    @AppStorage("host") private var host = ""
    @AppStorage("port") private var port = 58_008
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
                    Button("功能") { showsAdvancedControls = true }
                    Button("断开") { model.disconnect() }
                }
            }
            .sheet(isPresented: $showsAdvancedControls) {
                NavigationStack { AdvancedControlsView(model: model) }
            }
        }
    }

    private var connectionForm: some View {
        Form {
            Section("Mac 主机") {
                TextField("主机名或 IP", text: $host)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                TextField("端口", value: $port, format: .number)
                    .keyboardType(.numberPad)
            }
            Section {
                Button(model.isConnecting ? "连接中…" : "连接") {
                    Task { await model.connect(host: host, port: port) }
                }
                .disabled(host.isEmpty || model.isConnecting)
            } footer: {
                Text("首次连接时请允许本地网络访问。高级功能只有在双方协商且本地策略允许后启用。")
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

    var body: some View {
        PixelBufferView(pixelBuffer: model.pixelBuffer)
            .background(.black)
            .ignoresSafeArea()
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        model.sendTouch(location: value.location, size: model.viewportSize, ended: false)
                    }
                    .onEnded { value in
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
                    Picker("显示器", selection: $model.selectedStreamID) {
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
            .accessibilityLabel("Mac 显示画面")
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
