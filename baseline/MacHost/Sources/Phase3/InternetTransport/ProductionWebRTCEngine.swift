import Foundation
import Network
import WebRTC

final class ProductionWebRTCEngine: NSObject, WebRTCEnginePort {
    private enum AdapterError: Error, LocalizedError {
        case alreadyStarted
        case peerCreationFailed
        case channelCreationFailed(String)
        case channelUnavailable(InternetTransportChannel)
        case channelNotOpen(InternetTransportChannel)
        case sendRejected(InternetTransportChannel)
        case sendAlreadyPending(InternetTransportChannel)
        case sdkBacklogExceeded(InternetTransportChannel, UInt64)
        case closedBeforeDrain(InternetTransportChannel)

        var errorDescription: String? {
            switch self {
            case .alreadyStarted: return "The WebRTC engine is already started."
            case .peerCreationFailed: return "libwebrtc could not create a peer connection."
            case .channelCreationFailed(let label): return "libwebrtc could not create data channel \(label)."
            case .channelUnavailable(let channel): return "The \(channel) data channel is unavailable."
            case .channelNotOpen(let channel): return "The \(channel) data channel is not open."
            case .sendRejected(let channel): return "libwebrtc rejected a \(channel) data message."
            case .sendAlreadyPending(let channel):
                return "A \(channel) data message is still buffered by libwebrtc."
            case .sdkBacklogExceeded(let channel, let maximum):
                return "The \(channel) libwebrtc buffer exceeded \(maximum) bytes."
            case .closedBeforeDrain(let channel):
                return "The \(channel) data channel closed before buffered data drained."
            }
        }
    }

    private struct PendingSDKSend {
        let baselineBufferedAmount: UInt64
        let completion: (Result<Void, Error>) -> Void
    }

    private static let initializeWebRTC: Void = {
        RTCInitializeSSL()
    }()
    private static let candidatePairResolutionTimeoutSeconds = 5

    private let factory: RTCPeerConnectionFactory
    private let signaling: WebRTCSignalingClientPort
    private let queue = DispatchQueue(label: "dev.vibescreen.webrtc.peer")
    private let queueKey = DispatchSpecificKey<UInt8>()
    private let pathMonitor = NWPathMonitor()
    private let pathQueue = DispatchQueue(label: "dev.vibescreen.webrtc.path")
    private var callbacks: WebRTCEngineCallbacks?
    private var peerConnection: RTCPeerConnection?
    private var channelByKind: [InternetTransportChannel: RTCDataChannel] = [:]
    private var pendingSDKSendByKind: [InternetTransportChannel: PendingSDKSend] = [:]
    private var kindByLabel: [String: InternetTransportChannel] = [:]
    private var pendingRemoteCandidates: [RTCIceCandidate] = []
    private var pendingLocalCandidates: [RTCIceCandidate] = []
    private var localDescriptionPublished = false
    private var configuration: WebRTCTransportConfiguration?
    private var statsTimer: DispatchSourceTimer?
    private var candidatePairResolutionTimer: DispatchSourceTimer?
    private var selectedPath: InternetPathKind = .unknown
    private var selectedCandidatePair: WebRTCSelectedCandidatePair?
    private var didPublishConnected = false
    private var peerIsConnected = false
    private var isClosed = false

    init(
        factory: RTCPeerConnectionFactory? = nil,
        signaling: WebRTCSignalingClientPort = HTTPSignalingClient()
    ) {
        _ = Self.initializeWebRTC
        self.factory = factory ?? RTCPeerConnectionFactory()
        self.signaling = signaling
        super.init()
        queue.setSpecific(key: queueKey, value: 1)
        signaling.onSignal = { [weak self] signal in self?.queue.async { self?.handle(signal) } }
        signaling.onFailure = { [weak self] error in
            self?.queue.async { self?.fail("Signaling failed: \(error.localizedDescription)") }
        }
    }

    func install(callbacks: WebRTCEngineCallbacks) {
        performSync { self.callbacks = callbacks }
    }

    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws {
        guard configuration.signaling != nil else { throw WebRTCSignalingError.missingConfiguration }
        try performSync {
            guard peerConnection == nil else { throw AdapterError.alreadyStarted }
            isClosed = false
            localDescriptionPublished = false
            pendingLocalCandidates.removeAll()
            pendingRemoteCandidates.removeAll()
            pendingSDKSendByKind.removeAll()
            self.configuration = configuration
            selectedPath = .unknown
            selectedCandidatePair = nil
            didPublishConnected = false
            kindByLabel = Dictionary(uniqueKeysWithValues: channels.compactMap { descriptor in
                InternetTransportChannel.allCases.first(where: {
                    $0.dataChannelConfiguration.label == descriptor.label
                }).map { (descriptor.label, $0) }
            })

            let rtcConfiguration = RTCConfiguration()
            rtcConfiguration.sdpSemantics = .unifiedPlan
            rtcConfiguration.continualGatheringPolicy = .gatherContinually
            rtcConfiguration.iceTransportPolicy = configuration.forceRelay ? .relay : .all
            rtcConfiguration.iceServers = configuration.iceServers.map {
                RTCIceServer(
                    urlStrings: $0.urls.map(\.absoluteString),
                    username: $0.username,
                    credential: $0.credential
                )
            }
            let constraints = RTCMediaConstraints(
                mandatoryConstraints: nil,
                optionalConstraints: ["DtlsSrtpKeyAgreement": "true"]
            )
            guard let peer = factory.peerConnection(
                with: rtcConfiguration,
                constraints: constraints,
                delegate: self
            ) else { throw AdapterError.peerCreationFailed }
            peerConnection = peer
            if configuration.signaling?.role == .offerer {
                for descriptor in channels {
                    let rtcDescriptor = RTCDataChannelConfiguration()
                    rtcDescriptor.isOrdered = descriptor.isOrdered
                    rtcDescriptor.maxRetransmits = descriptor.maximumRetransmits.map(Int32.init) ?? -1
                    guard let channel = peer.dataChannel(
                        forLabel: descriptor.label,
                        configuration: rtcDescriptor
                    ), let kind = kindByLabel[descriptor.label] else {
                        throw AdapterError.channelCreationFailed(descriptor.label)
                    }
                    install(channel: channel, kind: kind)
                }
            }
            callbacks?.connectionStateChanged(.connecting)
            startPathMonitor()
            try signaling.connect(configuration: configuration)
        }
    }

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        queue.async { [weak self] in
            guard let self, let dataChannel = self.channelByKind[channel] else {
                completion(.failure(AdapterError.channelUnavailable(channel)))
                return
            }
            guard dataChannel.readyState == .open else {
                completion(.failure(AdapterError.channelNotOpen(channel)))
                return
            }
            guard self.pendingSDKSendByKind[channel] == nil else {
                completion(.failure(AdapterError.sendAlreadyPending(channel)))
                return
            }
            let bufferedBefore = dataChannel.bufferedAmount
            let maximumBuffered = self.maximumBufferedAmount(for: channel)
            let payloadBytes = UInt64(payload.count)
            guard WebRTCDataChannelBackpressurePolicy.canAdmit(
                bufferedAmount: bufferedBefore,
                payloadBytes: payloadBytes,
                maximumBufferedAmount: maximumBuffered
            ) else {
                completion(.failure(AdapterError.sdkBacklogExceeded(channel, maximumBuffered)))
                return
            }
            self.pendingSDKSendByKind[channel] = PendingSDKSend(
                baselineBufferedAmount: bufferedBefore,
                completion: completion
            )
            let accepted = dataChannel.sendData(RTCDataBuffer(data: payload, isBinary: true))
            guard accepted else {
                self.pendingSDKSendByKind.removeValue(forKey: channel)
                completion(.failure(AdapterError.sendRejected(channel)))
                return
            }
            self.completeSDKSendIfDrained(channel: channel, currentBufferedAmount: dataChannel.bufferedAmount)
        }
    }

    func restartICE() {
        queue.async { [weak self] in
            guard let self, let peerConnection = self.peerConnection else { return }
            self.selectedPath = .unknown
            self.selectedCandidatePair = nil
            self.didPublishConnected = false
            self.localDescriptionPublished = false
            self.pendingLocalCandidates.removeAll()
            self.callbacks?.connectionStateChanged(.connecting)
            self.publishConnectedIfReady()
            peerConnection.restartIce()
            if self.configuration?.signaling?.role == .offerer { self.createAndSendOffer() }
        }
    }

    func requestMediaKeyframe() {
        // Encoded media is carried over the unreliable data channel. The host
        // encoder owns keyframe production through WebRTCInternetTransport's callback.
    }

    func close() {
        performSync {
            guard !isClosed else { return }
            isClosed = true
            stopCandidatePairResolutionTimeout()
            stopStats()
            failPendingSDKSends()
            pathMonitor.cancel()
            channelByKind.values.forEach {
                $0.delegate = nil
                $0.close()
            }
            channelByKind.removeAll()
            pendingLocalCandidates.removeAll()
            pendingRemoteCandidates.removeAll()
            peerConnection?.delegate = nil
            peerConnection?.close()
            peerConnection = nil
            signaling.close()
            callbacks?.connectionStateChanged(.closed)
        }
    }

    private func install(channel: RTCDataChannel, kind: InternetTransportChannel) {
        channel.delegate = self
        channelByKind[kind] = channel
    }

    private func maximumBufferedAmount(for channel: InternetTransportChannel) -> UInt64 {
        switch channel {
        case .control:
            return UInt64(
                InternetTransportLimits.standard.maximumBufferedControlBytes
                    + PlatformSessionPacketCipher.recordOverhead
            )
        case .media:
            return UInt64(
                InternetTransportLimits.standard.maximumMediaFrameBytes
                    + PlatformSessionPacketCipher.recordOverhead
            )
        }
    }

    private func completeSDKSendIfDrained(
        channel: InternetTransportChannel,
        currentBufferedAmount: UInt64
    ) {
        guard let pending = pendingSDKSendByKind[channel],
              WebRTCDataChannelBackpressurePolicy.hasDrained(
                currentBufferedAmount: currentBufferedAmount,
                baselineBufferedAmount: pending.baselineBufferedAmount
              ) else { return }
        pendingSDKSendByKind.removeValue(forKey: channel)
        pending.completion(.success(()))
    }

    private func failPendingSDKSends() {
        let pending = pendingSDKSendByKind
        pendingSDKSendByKind.removeAll()
        for (channel, send) in pending {
            send.completion(.failure(AdapterError.closedBeforeDrain(channel)))
        }
    }

    private func handle(_ signal: WebRTCSignal) {
        guard let peer = peerConnection, !isClosed else { return }
        switch signal {
        case .peerReady:
            if configuration?.signaling?.role == .offerer, peer.localDescription == nil {
                createAndSendOffer()
            }
        case .offer(let sdp):
            guard configuration?.signaling?.role == .answerer else { return }
            let description = RTCSessionDescription(type: .offer, sdp: sdp)
            peer.setRemoteDescription(description) { [weak self] error in
                self?.queue.async {
                    if let error { self?.fail("Remote offer rejected: \(error.localizedDescription)") }
                    else {
                        self?.flushRemoteCandidates()
                        self?.createAndSendAnswer()
                    }
                }
            }
        case .answer(let sdp):
            guard configuration?.signaling?.role == .offerer else { return }
            peer.setRemoteDescription(RTCSessionDescription(type: .answer, sdp: sdp)) { [weak self] error in
                self?.queue.async {
                    if let error { self?.fail("Remote answer rejected: \(error.localizedDescription)") }
                    else { self?.flushRemoteCandidates() }
                }
            }
        case .candidate(let sdp, let mid, let lineIndex):
            let candidate = RTCIceCandidate(sdp: sdp, sdpMLineIndex: lineIndex, sdpMid: mid)
            guard peer.remoteDescription != nil else {
                pendingRemoteCandidates.append(candidate)
                return
            }
            addRemoteCandidate(candidate)
        }
    }

    private func createAndSendOffer() {
        guard let peer = peerConnection else { return }
        peer.offer(for: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)) {
            [weak self] description, error in
            self?.queue.async {
                guard let self else { return }
                if let error { self.fail("Offer creation failed: \(error.localizedDescription)"); return }
                guard let description else { self.fail("Offer creation returned no SDP."); return }
                self.setLocalAndSignal(description, signal: .offer(description.sdp))
            }
        }
    }

    private func createAndSendAnswer() {
        guard let peer = peerConnection else { return }
        peer.answer(for: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)) {
            [weak self] description, error in
            self?.queue.async {
                guard let self else { return }
                if let error { self.fail("Answer creation failed: \(error.localizedDescription)"); return }
                guard let description else { self.fail("Answer creation returned no SDP."); return }
                self.setLocalAndSignal(description, signal: .answer(description.sdp))
            }
        }
    }

    private func setLocalAndSignal(_ description: RTCSessionDescription, signal: WebRTCSignal) {
        peerConnection?.setLocalDescription(description) { [weak self] error in
            self?.queue.async {
                guard let self else { return }
                if let error { self.fail("Local SDP rejected: \(error.localizedDescription)"); return }
                self.signaling.send(signal) { [weak self] result in
                    self?.queue.async {
                        guard let self else { return }
                        switch result {
                        case .success:
                            self.localDescriptionPublished = true
                            self.flushLocalCandidates()
                        case .failure(let error):
                            self.fail("SDP signaling failed: \(error.localizedDescription)")
                        }
                    }
                }
            }
        }
    }

    private func addRemoteCandidate(_ candidate: RTCIceCandidate) {
        peerConnection?.add(candidate) { [weak self] error in
            if let error { self?.queue.async { self?.fail("ICE candidate rejected: \(error.localizedDescription)") } }
        }
    }

    private func flushRemoteCandidates() {
        let candidates = pendingRemoteCandidates
        pendingRemoteCandidates.removeAll()
        candidates.forEach(addRemoteCandidate)
    }

    private func flushLocalCandidates() {
        let candidates = pendingLocalCandidates
        pendingLocalCandidates.removeAll()
        candidates.forEach(sendLocalCandidate)
    }

    private func sendLocalCandidate(_ candidate: RTCIceCandidate) {
        signaling.send(.candidate(
            sdp: candidate.sdp,
            mid: candidate.sdpMid,
            lineIndex: candidate.sdpMLineIndex
        )) { [weak self] result in
            if case .failure(let error) = result {
                self?.queue.async { self?.fail("ICE signaling failed: \(error.localizedDescription)") }
            }
        }
    }

    private func publishConnectedIfReady() {
        guard peerIsConnected,
              InternetTransportChannel.allCases.allSatisfy({ channelByKind[$0]?.readyState == .open }) else {
            return
        }
        startStats()
        guard selectedPath != .unknown else {
            startCandidatePairResolutionTimeout()
            return
        }
        stopCandidatePairResolutionTimeout()
        guard !didPublishConnected else { return }
        didPublishConnected = true
        callbacks?.connectionStateChanged(.connected(path: selectedPath))
    }

    private func startCandidatePairResolutionTimeout() {
        guard candidatePairResolutionTimer == nil else { return }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + .seconds(Self.candidatePairResolutionTimeoutSeconds))
        timer.setEventHandler { [weak self] in
            guard let self, !self.isClosed,
                  self.peerIsConnected,
                  self.selectedPath == .unknown else { return }
            self.stopCandidatePairResolutionTimeout()
            self.fail("Selected ICE candidate pair statistics were unavailable before timeout.")
        }
        candidatePairResolutionTimer = timer
        timer.resume()
    }

    private func stopCandidatePairResolutionTimeout() {
        candidatePairResolutionTimer?.cancel()
        candidatePairResolutionTimer = nil
    }

    private func startPathMonitor() {
        pathMonitor.pathUpdateHandler = { [weak self] path in
            guard let self else { return }
            let interface: InternetNetworkPath.Interface
            if path.usesInterfaceType(.wiredEthernet) { interface = .wiredEthernet }
            else if path.usesInterfaceType(.wifi) { interface = .wifi }
            else if path.usesInterfaceType(.cellular) { interface = .cellular }
            else { interface = .other("other") }
            let fingerprint = NetworkPathFingerprint.make(path)
            self.callbacks?.networkPathChanged(InternetNetworkPath(
                interface: interface,
                isSatisfied: path.status == .satisfied,
                fingerprint: fingerprint
            ))
        }
        pathMonitor.start(queue: pathQueue)
    }

    private func startStats() {
        guard statsTimer == nil else { return }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: .seconds(1))
        timer.setEventHandler { [weak self] in self?.sampleStats() }
        statsTimer = timer
        timer.resume()
    }

    private func stopStats() {
        statsTimer?.cancel()
        statsTimer = nil
    }

    private func sampleStats() {
        peerConnection?.statistics { [weak self] report in
            self?.queue.async { self?.consume(report) }
        }
    }

    private func consume(_ report: RTCStatisticsReport) {
        let selectedPairID = report.statistics.values.lazy.compactMap { statistic -> String? in
            guard statistic.type == "transport" else { return nil }
            return statistic.values["selectedCandidatePairId"] as? String
        }.first
        var availableBitrate: UInt64 = 0
        var roundTripTime: Double = 0
        var packetsLost: Double = 0
        var packetsReceived: Double = 0
        var observedSelectedPath: InternetPathKind?
        for statistic in report.statistics.values {
            if statistic.type == "candidate-pair", statistic.id == selectedPairID {
                availableBitrate = (statistic.values["availableOutgoingBitrate"] as? NSNumber)?.uint64Value ?? 0
                roundTripTime = ((statistic.values["currentRoundTripTime"] as? NSNumber)?.doubleValue ?? 0) * 1_000
                let localID = statistic.values["localCandidateId"] as? String
                let remoteID = statistic.values["remoteCandidateId"] as? String
                let localCandidate = report.statistics.values.first { $0.id == localID }
                let remoteCandidate = report.statistics.values.first { $0.id == remoteID }
                let localType = localCandidate?.values["candidateType"] as? String
                let remoteType = remoteCandidate?.values["candidateType"] as? String
                let newPath = SelectedCandidatePathResolver.resolve(
                    localCandidateType: localType,
                    remoteCandidateType: remoteType
                )
                observedSelectedPath = newPath
                let pair = WebRTCSelectedCandidatePair(
                    path: newPath,
                    localCandidateType: localType ?? "unknown",
                    remoteCandidateType: remoteType ?? "unknown",
                    networkProtocol: (localCandidate?.values["protocol"] as? String ?? "unknown").lowercased()
                )
                if pair != selectedCandidatePair {
                    selectedCandidatePair = pair
                    callbacks?.selectedCandidatePairChanged(pair)
                }
                if newPath != .unknown, newPath != selectedPath {
                    selectedPath = newPath
                    if didPublishConnected {
                        callbacks?.connectionStateChanged(.connected(path: newPath))
                    } else {
                        publishConnectedIfReady()
                    }
                }
            }
            if statistic.type == "data-channel" {
                packetsLost += (statistic.values["messagesDiscardedOnSend"] as? NSNumber)?.doubleValue ?? 0
                packetsReceived += (statistic.values["messagesReceived"] as? NSNumber)?.doubleValue ?? 0
            }
        }
        if SelectedCandidatePathResolver.mustFailClosed(
            publishedPath: didPublishConnected ? selectedPath : nil,
            observedPath: observedSelectedPath
        ) {
            fail("Selected ICE candidate pair statistics became unavailable or unknown.")
            return
        }
        let denominator = packetsLost + packetsReceived
        callbacks?.networkQualitySampled(InternetNetworkQualitySample(
            roundTripTimeMilliseconds: roundTripTime,
            packetLossFraction: denominator > 0 ? packetsLost / denominator : 0,
            availableOutgoingBitrateBps: availableBitrate
        ))
    }

    private func fail(_ reason: String) {
        guard !isClosed else { return }
        stopCandidatePairResolutionTimeout()
        failPendingSDKSends()
        callbacks?.connectionStateChanged(.failed(reason))
    }

    private func performSync<T>(_ operation: () throws -> T) rethrows -> T {
        if DispatchQueue.getSpecific(key: queueKey) != nil { return try operation() }
        return try queue.sync(execute: operation)
    }
}

extension InternetTransportChannel: CaseIterable {
    static var allCases: [InternetTransportChannel] { [.control, .media] }
}

extension ProductionWebRTCEngine: RTCPeerConnectionDelegate {
    func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {}
    func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceConnectionState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {
        queue.async { [weak self] in
            guard let self else { return }
            guard self.localDescriptionPublished else {
                self.pendingLocalCandidates.append(candidate)
                return
            }
            self.sendLocalCandidate(candidate)
        }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {
        queue.async { [weak self] in
            guard let self, let kind = self.kindByLabel[dataChannel.label] else {
                dataChannel.close()
                return
            }
            self.install(channel: dataChannel, kind: kind)
            self.publishConnectedIfReady()
        }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCPeerConnectionState) {
        queue.async { [weak self] in
            guard let self else { return }
            switch newState {
            case .new, .connecting:
                self.callbacks?.connectionStateChanged(.connecting)
            case .connected:
                self.peerIsConnected = true
                self.publishConnectedIfReady()
            case .disconnected:
                self.peerIsConnected = false
                self.stopCandidatePairResolutionTimeout()
                self.selectedPath = .unknown
                self.selectedCandidatePair = nil
                self.didPublishConnected = false
                self.callbacks?.connectionStateChanged(.disconnected)
            case .failed:
                self.peerIsConnected = false
                self.stopCandidatePairResolutionTimeout()
                self.callbacks?.connectionStateChanged(.failed("libwebrtc peer connection failed."))
            case .closed:
                self.peerIsConnected = false
                self.callbacks?.connectionStateChanged(.closed)
            @unknown default:
                self.callbacks?.connectionStateChanged(.failed("Unknown libwebrtc connection state."))
            }
        }
    }
}

extension ProductionWebRTCEngine: RTCDataChannelDelegate {
    func dataChannelDidChangeState(_ dataChannel: RTCDataChannel) {
        queue.async { [weak self] in self?.publishConnectedIfReady() }
    }

    func dataChannel(_ dataChannel: RTCDataChannel, didReceiveMessageWith buffer: RTCDataBuffer) {
        queue.async { [weak self] in
            guard let self, let kind = self.kindByLabel[dataChannel.label] else { return }
            self.callbacks?.messageReceived(buffer.data, kind)
        }
    }

    func dataChannel(_ dataChannel: RTCDataChannel, didChangeBufferedAmount amount: UInt64) {
        queue.async { [weak self] in
            guard let self, let kind = self.kindByLabel[dataChannel.label] else { return }
            // The property is authoritative across libwebrtc versions; the
            // delegate argument has represented both old and new values.
            self.completeSDKSendIfDrained(
                channel: kind,
                currentBufferedAmount: dataChannel.bufferedAmount
            )
        }
    }
}
