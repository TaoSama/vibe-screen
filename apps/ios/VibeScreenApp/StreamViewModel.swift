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
            self.terminateSession(message: failure.error.localizedDescription)
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
    var pendingHostHello: VSHostHello?
    var controlValidator = ClientControlEnvelopeValidator()
    var negotiatedCapabilities: Set<VSCapability> = []
    var negotiatedLimits = VSResourceLimits()
    var heartbeatIntervalMilliseconds: UInt32 = 0
    var heartbeatSequence: UInt64 = 0
    var heartbeatMonitor = HeartbeatMonitor(nowNanoseconds: { DispatchTime.now().uptimeNanoseconds })
    var heartbeatTask: Task<Void, Never>?
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
        endSession(disconnectTransport: true)
        let newConnectionOwner = ConnectionOwner()
        let newSessionOwner = SessionOwner(connectionOwner: newConnectionOwner)
        deliveryGate.reset(to: newConnectionOwner)
        sessionOwner = newSessionOwner
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
            guard sessionOwner == newSessionOwner else { return }
            state.fail(error.localizedDescription)
            errorMessage = error.localizedDescription
            endSession(disconnectTransport: true, resetState: false)
        }
        if sessionOwner == newSessionOwner { isConnecting = false }
    }

    func disconnect() {
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
        isStreaming = false
        isConnecting = false
    }

    func selectDisplay(streamID: UInt64) {
        guard displayBindings.contains(where: { $0.streamID == streamID }) else { return }
        selectedStreamID = streamID
        touchActive = false
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
                selectedStreamID = displayBindings[(current + 1) % displayBindings.count].streamID
            case let .invokeHostAction(identifier):
                invokeHostAction(identifier)
            case .toggleControls, .showKeyboard:
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
