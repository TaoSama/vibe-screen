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
        pointer: true
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
            guard self.closingSessionOwner != failure.owner else { return }
            self.terminateSession(
                message: failure.error.localizedDescription,
                failure: ReconnectFailure.classify(failure.error)
            )
        }
    )
    let audioPlayback = AudioPlaybackController()
    var audioSession = AudioPlaybackSession()
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
    var touchInputState = ContinuousInputState()
    var pointerHoverInputState = ContinuousInputState()
    var keyboardInputState = PressedKeyboardInputState()
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
    var closingSessionOwner: SessionOwner?
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

    func setConnecting(_ value: Bool) {
        isConnecting = value
    }

    func requestKeyboardFocus() {
        keyboardFocusRequest &+= 1
    }

    func connect(pairingURL: String) async {
        guard closingSessionOwner == nil else {
            errorMessage = "当前会话仍在有序断开，请稍后重试"
            return
        }
        let pairing: TrustedLANPairing
        do {
            pairing = try TrustedLANPairing(
                urlString: pairingURL.trimmingCharacters(in: .whitespacesAndNewlines)
            )
        } catch {
            errorMessage = "配对链接无效：\(error.localizedDescription)"
            return
        }
        guard managedConfiguration.policy.allows(host: pairing.host) else {
            errorMessage = "此主机不在组织允许列表中"
            return
        }
        stopAutomaticReconnect(clearPairing: true)
        endSession(disconnectTransport: true)
        activePairing = pairing
        let generation = reconnectCoordinator.start()
        await connect(pairing: pairing, generation: generation)
    }

    func disconnect() {
        let closureContext = SessionClosureContext.manualDisconnect
        errorMessage = nil
        stopAutomaticReconnect(clearPairing: true)
        finishSessionAfterInputRelease(
            releaseBatch: releaseActiveInput(
                reportErrors: closureContext.reportsEnqueueErrors
            ),
            reasonCode: "client_disconnect",
            resetState: true,
            closureContext: closureContext
        )
    }

    func finishSessionAfterInputRelease(
        releaseBatch: InputReleaseBatch,
        reasonCode: String,
        resetState: Bool,
        expectedOwner: SessionOwner? = nil,
        closureContext: SessionClosureContext = .sessionFailure
    ) {
        if let expectedOwner, expectedOwner != sessionOwner { return }
        guard closingSessionOwner == nil else { return }
        heartbeatTask?.cancel()
        heartbeatTask = nil

        guard let owner = sessionOwner else {
            endSession(disconnectTransport: true, resetState: resetState)
            errorMessage = closureContext.errorOnCompletion(currentError: errorMessage)
            return
        }
        closingSessionOwner = owner
        isStreaming = false

        var disconnectTicket: ControlSendTicket?
        if closureContext.shouldEnqueueDisconnectNotice(
            hasSession: !state.sessionID.isEmpty && state.sessionEpoch > 0,
            allReleasesAdmitted: releaseBatch.allAdmitted
        ) {
            do {
                disconnectTicket = try controlOutbox.enqueue(owner: owner, timeout: 0.25) { factory in
                    factory.disconnectNotice(
                        reasonCode: reasonCode,
                        mayResume: false,
                        sessionID: self.state.sessionID,
                        sessionEpoch: self.state.sessionEpoch
                    )
                }
            } catch {
                errorMessage = closureContext.errorAfterEnqueueFailure(
                    currentError: errorMessage,
                    enqueueError: error.localizedDescription
                )
            }
        }

        Task { [weak self] in
            if let disconnectTicket {
                _ = try? await disconnectTicket.wait()
            } else {
                await releaseBatch.waitForAdmittedReleases()
            }
            guard let self, self.sessionOwner == owner else { return }
            self.endSession(disconnectTransport: true, resetState: resetState)
            self.errorMessage = closureContext.errorOnCompletion(currentError: self.errorMessage)
        }
    }

    func endSession(disconnectTransport: Bool, resetState: Bool = true) {
        // Invalidate every owner before cancelling work or touching the transport.
        let endingOwner = sessionOwner
        deliveryGate.reset()
        sessionOwner = nil
        closingSessionOwner = nil
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
        managedConfiguration.clearRemotePolicy()
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
        audioSession.reset()
        availableHostActions = []
        pixelBuffer = nil
        nextInputID = 1
        touchInputState.reset()
        pointerHoverInputState.reset()
        keyboardInputState.reset()
        isStreaming = false
        isConnecting = false
    }

    func selectDisplay(streamID: UInt64) {
        guard streamID != selectedStreamID,
              displayBindings.contains(where: { $0.streamID == streamID }) else { return }
        guard releaseActiveInput().allAdmitted else { return }
        selectedStreamID = streamID
    }

    @discardableResult
    func sendTouch(location: CGPoint, size: CGSize, ended: Bool) -> Bool {
        if ended {
            let terminalPosition = size.width > 0 && size.height > 0
                ? NormalizedInputPosition(x: location.x / size.width, y: location.y / size.height)
                : nil
            var nextState = touchInputState
            let accepted = nextState.enqueueTerminal(position: terminalPosition) { position in
                enqueueTouch(phase: .ended, position: position, pressure: 0) != nil
            }
            touchInputState = nextState
            return accepted
        }

        guard isStreaming, size.width > 0, size.height > 0,
              let selectedStreamID,
              decoderOwners[selectedStreamID] != nil else { return false }
        let position = NormalizedInputPosition(
            x: location.x / size.width,
            y: location.y / size.height
        )
        var nextState = touchInputState
        let accepted = nextState.enqueueUpdate(position: position) { phase, admittedPosition in
            enqueueTouch(phase: phase, position: admittedPosition, pressure: 1) != nil
        }
        touchInputState = nextState
        return accepted
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
