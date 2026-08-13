import CoreMedia
import CoreVideo
import Combine
import Foundation
import SwiftUI
import UIKit
import VibeScreenCore
import VibeScreenProtocol
import VibeScreenVideo

@MainActor
final class StreamViewModel: ObservableObject {
    static let maximumDisplayStreams = 4
    static let nativeInputAvailability = NativeInputAvailability(
        keyboard: true,
        pointer: true,
        stylus: false,
        controller: false
    )

    @Published private(set) var isConnecting = false
    @Published var isStreaming = false
    @Published var errorMessage: String?
    @Published var pixelBuffer: CVPixelBuffer?
    @Published var displayBindings: [DisplayStreamBinding] = []
    @Published var selectedStreamID: UInt64?
    @Published var pendingFileName: String?
    @Published var completedFileURL: URL?
    @Published var availableHostActions: [String] = []
    @Published var gestureProfile = GestureProfile.defaults
    @Published private(set) var keyboardFocusRequest = 0

    let clipboard = ClipboardController()
    let managedConfiguration = ManagedConfigurationProvider()
    var viewportSize = CGSize(width: 1, height: 1)

    lazy var transport = TCPTransport { [weak self] delivery in
        // TCPTransport emits frames serially; one serial Main queue hop preserves
        // that order while the owner check runs at the final actor boundary.
        DispatchQueue.main.async { [weak self, delivery] in
            MainActor.assumeIsolated { self?.handle(delivery) }
        }
    }
    lazy var controlOutbox = ControlOutbox(
        sender: { [weak self] owner, frame, timeout in
            guard let transport = await MainActor.run(body: { self?.transport }) else {
                throw ControlOutboxError.inactive
            }
            try await transport.send(frame, owner: owner, timeout: timeout)
        },
        onFailure: { [weak self] failure in
            guard let self, self.sessionOwner == failure.owner else { return }
            self.terminateSession(
                message: failure.error.localizedDescription,
                failure: .transientTransport
            )
        }
    )
    let audioPlayback = AudioPlaybackController()
    var audioFormat: PCMStreamFormat?
    var audioConfig: VSAudioConfig?
    var audioJitter = AudioJitterBuffer(firstSequence: 0)
    var decoders: [UInt64: VideoDecoder] = [:]
    var decoderOwners: [UInt64: DecoderOwner] = [:]
    var mediaGate = VideoMediaGate()
    var registry = MultiDisplaySessionRegistry(
        maximumClients: 1,
        maximumStreamsPerClient: maximumDisplayStreams
    )
    var sessionKey: ClientSessionKey?
    var state = SessionState()
    var nextInputID: UInt64 = 1
    var touchActive = false
    var lastTouchLocation = CGPoint.zero
    var pointerHoverActive = false
    var lastPointerLocation = CGPoint.zero
    var pressedKeyboardUsages: Set<UInt32> = []
    var pendingHostHello: VSHostHello?
    var controlValidator = ClientControlEnvelopeValidator()
    var negotiatedCapabilities: Set<VSCapability> = []
    var negotiatedLimits = VSResourceLimits()
    var heartbeatIntervalMilliseconds: UInt32 = 0
    var heartbeatSequence: UInt64 = 0
    var heartbeatMonitor = HeartbeatMonitor(nowNanoseconds: { DispatchTime.now().uptimeNanoseconds })
    var heartbeatTask: Task<Void, Never>?
    var reconnectCoordinator = ReconnectCoordinator()
    var reconnectTask: Task<Void, Never>?
    var activePairing: TrustedLANPairing?
    var connectionGeneration: UInt64?
    var deliveryGate = OwnedDeliveryGate()
    var sessionOwner: SessionOwner?
    var pendingFileOffers: [Data: VSFileOffer] = [:]
    var outgoingFiles: [Data: SecurityScopedOutgoingFile] = [:]
    let incomingFiles: IncomingFileTransferManager?
    let deviceID = UIDevice.current.identifierForVendor?.uuidString ?? UUID().uuidString
    var policySubscription: AnyCancellable?

    init() {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("VibeScreenIncoming", isDirectory: true)
        incomingFiles = try? IncomingFileTransferManager(
            policy: FileTransferPolicy(),
            directory: directory
        )
        if let data = UserDefaults.standard.data(forKey: "gestureProfile"),
           let stored = try? JSONDecoder().decode(GestureProfile.self, from: data) {
            gestureProfile = stored
        }
        policySubscription = managedConfiguration.$policy.dropFirst().sink { [weak self] _ in
            Task { @MainActor in self?.enforceCurrentPolicy() }
        }
    }

    func connect(pairingURL: String) async {
        let pairing: TrustedLANPairing
        do {
            pairing = try TrustedLANPairing(
                urlString: pairingURL.trimmingCharacters(in: .whitespacesAndNewlines)
            )
        } catch {
            errorMessage = "配对链接无效：\(error.localizedDescription)"
            return
        }
        let policy = managedConfiguration.policy
        guard policy.allowedHosts.isEmpty || policy.allowedHosts.contains(pairing.host) else {
            errorMessage = "此主机不在组织允许列表中"
            return
        }
        stopAutomaticReconnect(clearPairing: true)
        endSession(disconnectTransport: true)
        activePairing = pairing
        let generation = reconnectCoordinator.start()
        await connect(pairing: pairing, generation: generation)
    }

    private func connect(pairing: TrustedLANPairing, generation: UInt64) async {
        guard reconnectCoordinator.accepts(generation: generation), activePairing == pairing else { return }
        let policy = managedConfiguration.policy
        let newConnectionOwner = ConnectionOwner()
        let newSessionOwner = SessionOwner(connectionOwner: newConnectionOwner)
        deliveryGate.reset(to: newConnectionOwner)
        sessionOwner = newSessionOwner
        connectionGeneration = generation
        controlOutbox.activate(owner: newSessionOwner)
        isConnecting = true
        errorMessage = nil
        do {
            try state.beginConnection()
            try await transport.connect(
                pairing: pairing,
                deviceName: UIDevice.current.name,
                owner: newConnectionOwner
            )
            guard sessionOwner == newSessionOwner else { return }
            try state.transportConnected()
            controlValidator.reset()
            try await controlOutbox.sendAndWait(owner: newSessionOwner) { factory in
                factory.clientHello(
                    deviceID: self.deviceID,
                    deviceName: UIDevice.current.name,
                    capabilities: self.advertisedCapabilities(policy: policy),
                    codecs: [.hevc, .h264],
                    resourceLimits: self.clientResourceLimits(policy: policy),
                    videoDecodeCapabilities: Self.sdrDecodeCapabilities
                )
            }
            guard sessionOwner == newSessionOwner else { return }
        } catch {
            guard sessionOwner == newSessionOwner,
                  reconnectCoordinator.accepts(generation: generation) else { return }
            terminateSession(
                message: error.localizedDescription,
                failure: reconnectFailure(for: error),
                generation: generation
            )
        }
        if sessionOwner == newSessionOwner { isConnecting = false }
    }

    func disconnect() {
        stopAutomaticReconnect(clearPairing: true)
        heartbeatTask?.cancel()
        heartbeatTask = nil
        guard !state.sessionID.isEmpty, state.sessionEpoch > 0 else {
            endSession(disconnectTransport: true)
            return
        }
        guard let owner = sessionOwner else {
            endSession(disconnectTransport: true)
            return
        }
        isStreaming = false
        let ticket = try? controlOutbox.enqueue(owner: owner, timeout: 0.25) { factory in
            factory.disconnectNotice(
                reasonCode: "client_disconnect",
                mayResume: false,
                sessionID: self.state.sessionID,
                sessionEpoch: self.state.sessionEpoch
            )
        }
        Task { [weak self] in
            _ = try? await ticket?.wait()
            guard let self, self.sessionOwner == owner else { return }
            endSession(disconnectTransport: true)
        }
    }

    func endSession(disconnectTransport: Bool, resetState: Bool = true) {
        // Invalidate every owner before cancelling work or touching the transport.
        let endingOwner = sessionOwner
        deliveryGate.reset()
        sessionOwner = nil
        connectionGeneration = nil
        controlOutbox.deactivate()
        heartbeatMonitor.reset()
        if let endingOwner { _ = mediaGate.endSession(owner: endingOwner) }
        decoderOwners.removeAll()
        heartbeatTask?.cancel()
        heartbeatTask = nil
        if disconnectTransport { transport.disconnect() }
        audioPlayback.stop()
        for decoder in decoders.values { decoder.invalidate() }
        for transferID in pendingFileOffers.keys { incomingFiles?.cancel(transferID: transferID) }
        for transfer in outgoingFiles.values { transfer.cancel() }
        if let sessionKey { registry.disconnect(sessionKey) }
        if resetState { state.reset() }
        sessionKey = nil
        negotiatedCapabilities = []
        negotiatedLimits = VSResourceLimits()
        heartbeatIntervalMilliseconds = 0
        heartbeatSequence = 0
        pendingHostHello = nil
        controlValidator.reset()
        decoders.removeAll()
        displayBindings = []
        selectedStreamID = nil
        pendingFileOffers = [:]
        outgoingFiles = [:]
        pendingFileName = nil
        audioConfig = nil
        audioFormat = nil
        audioJitter.reset(firstSequence: 0)
        availableHostActions = []
        pixelBuffer = nil
        nextInputID = 1
        touchActive = false
        lastTouchLocation = .zero
        pointerHoverActive = false
        lastPointerLocation = .zero
        pressedKeyboardUsages.removeAll()
        isStreaming = false
        isConnecting = false
    }

    func terminateSession(
        message: String,
        failure: ReconnectFailure,
        generation: UInt64? = nil
    ) {
        guard let pairing = activePairing,
              let generation = generation ?? connectionGeneration,
              let schedule = reconnectCoordinator.schedule(generation: generation, failure: failure) else {
            state.fail(message)
            errorMessage = message
            endSession(disconnectTransport: true, resetState: false)
            return
        }
        state.fail(message)
        endSession(disconnectTransport: true, resetState: false)
        state.disconnected(retryAttempt: schedule.attempt)
        errorMessage = "\(message)；\(String(format: "%.2g", schedule.delaySeconds)) 秒后重试"
        reconnectTask?.cancel()
        reconnectTask = Task { [weak self] in
            do {
                try await Task.sleep(for: .milliseconds(Int(schedule.delaySeconds * 1_000)))
            } catch {
                return
            }
            guard let self,
                  self.reconnectCoordinator.accepts(generation: schedule.generation),
                  self.activePairing == pairing else { return }
            self.reconnectTask = nil
            await self.connect(pairing: pairing, generation: schedule.generation)
        }
    }

    private func reconnectFailure(for error: Error) -> ReconnectFailure {
        if error is TCPTransportError { return .transientTransport }
        return .permanent
    }

    func stopAutomaticReconnect(clearPairing: Bool) {
        reconnectCoordinator.stop()
        reconnectTask?.cancel()
        reconnectTask = nil
        if clearPairing { activePairing = nil }
    }

    func selectDisplay(streamID: UInt64) {
        guard streamID != selectedStreamID,
              displayBindings.contains(where: { $0.streamID == streamID }) else { return }
        terminateActiveInputBeforeDisplayChange()
        selectedStreamID = streamID
    }

    func terminateActiveInputBeforeDisplayChange() {
        releaseKeyboardInput()
        cancelTouchInput()
        _ = sendPointerHover(location: nil, size: viewportSize)
    }

    var keyboardInputAvailable: Bool {
        isStreaming && negotiatedCapabilities.contains(.keyboard)
    }

    func requestKeyboardInput() {
        guard keyboardInputAvailable else { return }
        keyboardFocusRequest &+= 1
    }

    func sendTouch(location: CGPoint, size: CGSize, ended: Bool) {
        guard isStreaming, size.width > 0, size.height > 0,
              let selectedStreamID,
              decoderOwners[selectedStreamID] != nil else { return }
        let phase: VSInputPhase = ended ? .ended : (touchActive ? .changed : .began)
        var target: VSInputTarget?
        if let binding = displayBindings.first(where: { $0.streamID == selectedStreamID }) {
            var value = VSInputTarget()
            value.displayID = binding.displayID
            value.streamID = binding.streamID
            target = value
        }
        let inputID = nextInputID
        nextInputID += 1
        touchActive = !ended
        lastTouchLocation = location
        sendInBackground { factory in
            factory.touch(
                inputID: inputID,
                pointerID: 0,
                phase: phase,
                x: location.x / size.width,
                y: location.y / size.height,
                pressure: ended ? 0 : 1,
                sessionID: self.state.sessionID,
                sessionEpoch: self.state.sessionEpoch,
                target: target
            )
        }
    }

    private func cancelTouchInput() {
        guard touchActive, isStreaming, selectedDecoderIsReady else { return }
        let inputID = takeNextInputID()
        let target = selectedInputTarget()
        let location = lastTouchLocation
        let size = viewportSize
        guard size.width > 0, size.height > 0 else { return }
        touchActive = false
        sendInBackground { factory in
            factory.touch(
                inputID: inputID,
                pointerID: 0,
                phase: .cancelled,
                x: location.x / size.width,
                y: location.y / size.height,
                pressure: 0,
                sessionID: self.state.sessionID,
                sessionEpoch: self.state.sessionEpoch,
                target: target
            )
        }
    }

    @discardableResult
    func sendPointerHover(location: CGPoint?, size: CGSize) -> Bool {
        guard isStreaming, negotiatedCapabilities.contains(.pointer),
              size.width > 0, size.height > 0,
              selectedDecoderIsReady else { return false }

        let phase: VSInputPhase
        let point: CGPoint
        if let location {
            point = location
            phase = pointerHoverActive ? .changed : .began
            pointerHoverActive = true
            lastPointerLocation = location
        } else {
            guard pointerHoverActive else { return false }
            point = lastPointerLocation
            phase = .ended
            pointerHoverActive = false
        }

        let inputID = takeNextInputID()
        let target = selectedInputTarget()
        sendInBackground { factory in
            factory.pointer(
                inputID: inputID,
                phase: phase,
                x: point.x / size.width,
                y: point.y / size.height,
                buttonMask: 0,
                sessionID: self.state.sessionID,
                sessionEpoch: self.state.sessionEpoch,
                target: target
            )
        }
        return true
    }

    @discardableResult
    func sendKey(
        usbHIDUsage: UInt32,
        pressed: Bool,
        modifierMask: UInt32,
        text: String
    ) -> Bool {
        guard isStreaming, negotiatedCapabilities.contains(.keyboard),
              usbHIDUsage > 0, selectedDecoderIsReady else { return false }
        if pressed {
            guard pressedKeyboardUsages.insert(usbHIDUsage).inserted else { return true }
        } else {
            guard pressedKeyboardUsages.remove(usbHIDUsage) != nil else { return true }
        }
        let inputID = takeNextInputID()
        let target = selectedInputTarget()
        sendInBackground { factory in
            factory.key(
                inputID: inputID,
                usbHIDUsage: usbHIDUsage,
                pressed: pressed,
                modifierMask: modifierMask,
                text: pressed ? text : "",
                sessionID: self.state.sessionID,
                sessionEpoch: self.state.sessionEpoch,
                target: target
            )
        }
        return true
    }

    func releaseKeyboardInput() {
        for usage in pressedKeyboardUsages.sorted() {
            _ = sendKey(usbHIDUsage: usage, pressed: false, modifierMask: 0, text: "")
        }
    }

    private var selectedDecoderIsReady: Bool {
        guard let selectedStreamID else { return false }
        return decoderOwners[selectedStreamID] != nil
    }

    private func selectedInputTarget() -> VSInputTarget? {
        guard let selectedStreamID,
              let binding = displayBindings.first(where: { $0.streamID == selectedStreamID }) else {
            return nil
        }
        var target = VSInputTarget()
        target.displayID = binding.displayID
        target.streamID = binding.streamID
        return target
    }

    private func takeNextInputID() -> UInt64 {
        defer { nextInputID += 1 }
        return nextInputID
    }

    func sendClipboardFromPasteboard() {
        do {
            guard negotiatedCapabilities.contains(.clipboard) else {
                throw ClipboardTransferError.policyDenied
            }
            let content = try clipboard.prepareOutgoing(
                originDeviceID: deviceID,
                policy: managedConfiguration.policy
            )
            sendInBackground { factory in
                factory.clipboardContent(
                    content,
                    sessionID: self.state.sessionID,
                    sessionEpoch: self.state.sessionEpoch
                )
            }
        } catch { errorMessage = error.localizedDescription }
    }

    func approveRemoteClipboard() {
        do { try clipboard.approvePending(policy: managedConfiguration.policy) }
        catch { errorMessage = error.localizedDescription }
    }

    func sendFile(at url: URL) {
        guard negotiatedCapabilities.contains(.fileTransfer) else {
            errorMessage = "主机未协商文件传输能力"
            return
        }
        do {
            let negotiatedFileBytes = negotiatedLimits.maximumFileBytes == 0 ?
                managedConfiguration.policy.maximumFileBytes : negotiatedLimits.maximumFileBytes
            let negotiatedChunkBytes = negotiatedLimits.maximumFileChunkBytes == 0 ?
                64 * 1_024 : Int(negotiatedLimits.maximumFileChunkBytes)
            let scopedFile = try SecurityScopedOutgoingFile(
                url: url,
                mimeType: "application/octet-stream",
                policy: FileTransferPolicy(
                    maximumFileBytes: negotiatedFileBytes,
                    maximumChunkBytes: min(64 * 1_024, negotiatedChunkBytes)
                ),
                managedPolicy: managedConfiguration.policy
            )
            let transfer = scopedFile.transfer
            outgoingFiles[transfer.offer.transferID] = scopedFile
            sendInBackground { factory in
                factory.fileOffer(
                    transfer.offer,
                    sessionID: self.state.sessionID,
                    sessionEpoch: self.state.sessionEpoch
                )
            }
        } catch { errorMessage = error.localizedDescription }
    }

    func report(_ error: Error) {
        errorMessage = error.localizedDescription
    }

    func approveIncomingFile() {
        guard let offer = pendingFileOffers.values.first, let incomingFiles else { return }
        do {
            let response = try incomingFiles.accept(offer, managedPolicy: managedConfiguration.policy)
            pendingFileName = nil
            sendInBackground { factory in
                factory.fileAccept(
                    response,
                    sessionID: self.state.sessionID,
                    sessionEpoch: self.state.sessionEpoch
                )
            }
        } catch { errorMessage = error.localizedDescription }
    }

    func rejectIncomingFile() {
        guard let offer = pendingFileOffers.values.first else { return }
        pendingFileOffers.removeValue(forKey: offer.transferID)
        pendingFileName = nil
        var response = VSFileAccept()
        response.transferID = offer.transferID
        response.accepted = false
        response.rejectionReason = "user_rejected"
        sendInBackground { factory in
            factory.fileAccept(response, sessionID: self.state.sessionID, sessionEpoch: self.state.sessionEpoch)
        }
    }

    func cancelFileTransfer(transferID: Data) {
        cancelLocalFileTransfer(transferID: transferID)
        var cancel = VSFileTransferCancel()
        cancel.transferID = transferID
        cancel.reasonCode = "user_cancelled"
        sendInBackground { factory in
            factory.fileTransferCancel(cancel, sessionID: self.state.sessionID, sessionEpoch: self.state.sessionEpoch)
        }
    }

    func wake(macAddress: String) {
        Task {
            do {
                try await WakeOnLANClient.send(
                    macAddress: macAddress,
                    isPaired: UserDefaults.standard.bool(forKey: "hasAuthorizedHostIdentity"),
                    policy: managedConfiguration.policy
                )
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func performGesture(_ trigger: GestureTrigger) {
        do {
            let profile = try gestureProfile.validated(
                availableHostActions: Set(availableHostActions),
                policy: managedConfiguration.policy
            )
            guard let action = profile.mappings.first(where: { $0.trigger == trigger })?.action else { return }
            switch action {
            case .switchDisplay:
                guard !displayBindings.isEmpty else { return }
                let current = displayBindings.firstIndex { $0.streamID == selectedStreamID } ?? -1
                selectDisplay(streamID: displayBindings[(current + 1) % displayBindings.count].streamID)
            case let .invokeHostAction(identifier):
                invokeHostAction(identifier)
            case .showKeyboard:
                requestKeyboardInput()
            case .toggleControls:
                break
            }
        } catch { errorMessage = error.localizedDescription }
    }

    func setGestureMapping(trigger: GestureTrigger, action: GestureAction) {
        gestureProfile.mappings.removeAll { $0.trigger == trigger }
        gestureProfile.mappings.append(GestureMapping(trigger: trigger, action: action))
        do {
            gestureProfile = try gestureProfile.validated(
                availableHostActions: Set(availableHostActions),
                policy: managedConfiguration.policy
            )
            if let data = try? JSONEncoder().encode(gestureProfile) {
                UserDefaults.standard.set(data, forKey: "gestureProfile")
            }
        } catch { errorMessage = error.localizedDescription }
    }
}
