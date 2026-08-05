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

    lazy var transport = TCPTransport { [weak self] result in
        let delivery = TransportDelivery(result)
        DispatchQueue.main.async { [weak self, delivery] in
            MainActor.assumeIsolated { self?.handle(delivery.result) }
        }
    }
    let audioPlayback = AudioPlaybackController()
    var audioFormat: PCMStreamFormat?
    var audioConfig: VSAudioConfig?
    var audioJitter = AudioJitterBuffer(firstSequence: 0)
    var decoders: [UInt64: VideoDecoder] = [:]
    var configuredCodecs: [UInt64: VSCodec] = [:]
    var registry = MultiDisplaySessionRegistry(
        maximumClients: 1,
        maximumStreamsPerClient: maximumDisplayStreams
    )
    var sessionKey: ClientSessionKey?
    var factory = EnvelopeFactory()
    var state = SessionState()
    var nextInputID: UInt64 = 1
    var touchActive = false
    var pendingHostHello: VSHostHello?
    var controlValidator = ClientControlEnvelopeValidator()
    var negotiatedCapabilities: Set<VSCapability> = []
    var negotiatedLimits = VSResourceLimits()
    var heartbeatIntervalMilliseconds: UInt32 = 0
    var heartbeatSequence: UInt64 = 0
    var lastPongSequence: UInt64 = 0
    var pendingHeartbeatCorrelations: [UInt64: UInt64] = [:]
    var heartbeatTask: Task<Void, Never>?
    var sessionGeneration: UInt64 = 0
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
        isConnecting = true
        errorMessage = nil
        do {
            try state.beginConnection()
            try await transport.connect(pairing: pairing, deviceName: UIDevice.current.name)
            try state.transportConnected()
            let hello = factory.clientHello(
                deviceID: deviceID,
                deviceName: UIDevice.current.name,
                capabilities: advertisedCapabilities(policy: policy),
                codecs: [.hevc, .h264],
                resourceLimits: clientResourceLimits(policy: policy),
                videoDecodeCapabilities: Self.sdrDecodeCapabilities
            )
            controlValidator.reset()
            try await send(hello)
        } catch {
            state.fail(error.localizedDescription)
            errorMessage = error.localizedDescription
            endSession(disconnectTransport: true, resetState: false)
        }
        isConnecting = false
    }

    func disconnect() {
        heartbeatTask?.cancel()
        heartbeatTask = nil
        guard !state.sessionID.isEmpty, state.sessionEpoch > 0 else {
            endSession(disconnectTransport: true)
            return
        }
        let generation = sessionGeneration
        let notice = factory.disconnectNotice(
            reasonCode: "client_disconnect",
            mayResume: false,
            sessionID: state.sessionID,
            sessionEpoch: state.sessionEpoch
        )
        isStreaming = false
        Task {
            try? await send(notice, timeout: 0.25)
            guard generation == sessionGeneration else { return }
            endSession(disconnectTransport: true)
        }
    }

    func endSession(disconnectTransport: Bool, resetState: Bool = true) {
        sessionGeneration &+= 1
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
        lastPongSequence = 0
        pendingHeartbeatCorrelations = [:]
        pendingHostHello = nil
        controlValidator.reset()
        decoders.removeAll()
        configuredCodecs.removeAll()
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
    }

    func sendTouch(location: CGPoint, size: CGSize, ended: Bool) {
        guard isStreaming, size.width > 0, size.height > 0 else { return }
        let phase: VSInputPhase = ended ? .ended : (touchActive ? .changed : .began)
        var target: VSInputTarget?
        if let selectedStreamID,
           let binding = displayBindings.first(where: { $0.streamID == selectedStreamID }) {
            var value = VSInputTarget()
            value.displayID = binding.displayID
            value.streamID = binding.streamID
            target = value
        }
        let envelope = factory.touch(
            inputID: nextInputID,
            pointerID: 0,
            phase: phase,
            x: location.x / size.width,
            y: location.y / size.height,
            pressure: ended ? 0 : 1,
            sessionID: state.sessionID,
            sessionEpoch: state.sessionEpoch,
            target: target
        )
        nextInputID += 1
        touchActive = !ended
        sendInBackground(envelope)
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
            sendInBackground(factory.clipboardContent(
                content,
                sessionID: state.sessionID,
                sessionEpoch: state.sessionEpoch
            ))
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
            sendInBackground(factory.fileOffer(
                transfer.offer,
                sessionID: state.sessionID,
                sessionEpoch: state.sessionEpoch
            ))
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
            sendInBackground(factory.fileAccept(
                response,
                sessionID: state.sessionID,
                sessionEpoch: state.sessionEpoch
            ))
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
        sendInBackground(factory.fileAccept(
            response,
            sessionID: state.sessionID,
            sessionEpoch: state.sessionEpoch
        ))
    }

    func cancelFileTransfer(transferID: Data) {
        cancelLocalFileTransfer(transferID: transferID)
        var cancel = VSFileTransferCancel()
        cancel.transferID = transferID
        cancel.reasonCode = "user_cancelled"
        sendInBackground(factory.fileTransferCancel(
            cancel,
            sessionID: state.sessionID,
            sessionEpoch: state.sessionEpoch
        ))
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

private struct TransportDelivery: @unchecked Sendable {
    let result: Result<TransportFrame, Error>

    init(_ result: Result<TransportFrame, Error>) {
        self.result = result
    }
}
