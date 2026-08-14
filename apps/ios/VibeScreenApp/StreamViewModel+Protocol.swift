import CoreMedia
import CoreVideo
import Foundation
import VibeScreenCore
import VibeScreenProtocol
import VibeScreenVideo

extension StreamViewModel {
    func handle(_ delivery: TransportDelivery) {
        guard deliveryGate.accepts(owner: delivery.owner) else { return }
        let frame: TransportFrame
        do {
            frame = try delivery.result.get()
        } catch {
            terminateSession(
                message: error.localizedDescription,
                failure: ReconnectFailure.classify(error)
            )
            return
        }
        do {
            switch frame.channel {
            case .control: try handleControl(EnvelopeCodec.deserialize(frame.payload))
            case .video: try handleVideo(MediaPacket(serializedFrame: frame.payload))
            case .audio: try handleAudio(AudioPacket(serializedFrame: frame.payload))
            case .bulkTransfer: try handleBulk(FileChunk(serializedFrame: frame.payload))
            }
        } catch {
            terminateSession(message: error.localizedDescription, failure: .permanent)
        }
    }

    func handleControl(_ envelope: VSEnvelope) throws {
        try controlValidator.validate(envelope)
        guard let payload = envelope.payload else { return }
        switch payload {
        case .hostHello(let hello):
            pendingHostHello = hello
        case .sessionAccepted(let accepted):
            try acceptSession(accepted)
        case .sessionRejected(let rejected):
            throw ProtocolClientError.rejected(rejected.message)
        case .ping(let ping):
            sendPong(sequence: ping.sequence, correlationID: envelope.messageID)
        case .pong(let pong):
            guard let owner = sessionOwner else { throw ProtocolClientError.invalidPong }
            do {
                try heartbeatMonitor.observePong(
                    owner: owner,
                    sequence: pong.sequence,
                    correlationID: envelope.correlationID
                )
            } catch { throw ProtocolClientError.invalidPong }
        case .disconnectNotice(let notice):
            terminateSession(
                message: "Mac 已断开会话：\(notice.reasonCode)",
                failure: notice.mayResume ? .transientTransport : .permanent
            )
        case .videoConfig(let config):
            handleVideoConfig(config)
        case .audioConfig(let config):
            try handleAudioConfig(config)
        case .listDisplaysResponse(let response):
            startDisplays(response.displays)
        case .startDisplayResponse(let response):
            try bindDisplay(response)
        case .videoStreamEnded(let ended):
            handleVideoStreamEnded(ended)
        case .errorReport(let report):
            terminateSession(message: "主机错误 [\(report.code)]：\(report.message)", failure: .permanent)
        case .protocolError(let error):
            terminateSession(message: "协议错误 [\(error.code)]：\(error.message)", failure: .permanent)
        case .clipboardContent(let content):
            if negotiatedCapabilities.contains(.clipboard) { clipboard.stage(content) }
        case .fileOffer(let offer):
            guard negotiatedCapabilities.contains(.fileTransfer) else { return }
            let maximum = negotiatedLimits.maximumFileBytes == 0 ?
                managedConfiguration.policy.maximumFileBytes :
                min(negotiatedLimits.maximumFileBytes, managedConfiguration.policy.maximumFileBytes)
            if offer.byteLength <= maximum {
                pendingFileOffers[offer.transferID] = offer
                pendingFileName = offer.fileName
            } else {
                var rejection = VSFileAccept()
                rejection.transferID = offer.transferID
                rejection.accepted = false
                rejection.rejectionReason = "negotiated_file_limit_exceeded"
                sendInBackground { factory in
                    factory.fileAccept(
                        rejection,
                        sessionID: self.state.sessionID,
                        sessionEpoch: self.state.sessionEpoch
                    )
                }
            }
        case .fileAccept(let acceptance):
            handleFileAccept(acceptance)
        case .fileTransferCancel(let cancellation):
            cancelLocalFileTransfer(transferID: cancellation.transferID)
        case .fileTransferComplete(let completion):
            outgoingFiles.removeValue(forKey: completion.transferID)?.cancel()
        case .hostActionCatalog(let catalog):
            if negotiatedCapabilities.contains(.hostActions) {
                availableHostActions = catalog.actions.map(\.actionID)
            }
        case .managedPolicyStatus(let status):
            if negotiatedCapabilities.contains(.managedConfiguration) {
                managedConfiguration.applyRemote(status)
                enforceCurrentPolicy()
            }
        case .clientHello, .resumeSessionRequest, .resumeSessionResult,
             .pairingOffer, .pairingRequest, .pairingResult, .deviceRevoked,
             .keyRotationRequest, .keyRotationResult, .deviceRevocation, .trafficKeyUpdate,
             .trafficKeyAck, .listDisplaysRequest, .startDisplayRequest, .stopDisplay,
             .displayChanged, .videoConfigResult, .requestKeyframe,
             .touchEvent, .stylusEvent, .pointerEvent, .scrollEvent, .keyEvent, .inputAck, .streamStats,
             .transportStats, .encryptedControlPacket,
             .audioConfigResult, .clipboardOffer, .clipboardRequest, .fileTransferProgress,
             .setVideoPreferences,
             .hostActionInvoke, .hostActionResult, .wakeHostRequest, .wakeHostResult:
            break
        }
    }

    func acceptSession(_ accepted: VSSessionAccepted) throws {
        guard let owner = sessionOwner else { throw ControlOutboxError.inactive }
        guard let host = pendingHostHello else {
            throw SessionStateError.invalidTransition(from: state.phase, event: "sessionAcceptedBeforeHostHello")
        }
        let local = Set(advertisedCapabilities(policy: managedConfiguration.policy))
        let negotiated = accepted.negotiatedCapabilities.isEmpty ?
            local.intersection(Set(host.capabilities)) : Set(accepted.negotiatedCapabilities)
        try state.accept(
            selectedProtocol: host.selectedProtocol,
            sessionID: accepted.sessionID,
            epoch: accepted.sessionEpoch,
            localCapabilities: local,
            hostCapabilities: negotiated
        )
        negotiatedCapabilities = state.negotiatedCapabilities
        negotiatedLimits = accepted.hasNegotiatedResourceLimits ?
            accepted.negotiatedResourceLimits : host.resourceLimits
        heartbeatIntervalMilliseconds = accepted.heartbeatIntervalMs == 0 ? 1_000 : accepted.heartbeatIntervalMs
        if negotiatedCapabilities.contains(.deviceIdentity) {
            UserDefaults.standard.set(true, forKey: "hasAuthorizedHostIdentity")
        }
        let key = ClientSessionKey(sessionID: state.sessionID, epoch: state.sessionEpoch)
        try registry.register(key)
        sessionKey = key
        if let connectionGeneration {
            reconnectCoordinator.markConnected(generation: connectionGeneration)
        }
        try mediaGate.reset(owner: owner, sessionEpoch: state.sessionEpoch)
        heartbeatMonitor.reset(
            to: owner,
            intervalNanoseconds: UInt64(heartbeatIntervalMilliseconds) * 1_000_000
        )
        startHeartbeat()
        sendManagedPolicyStatus()
        sendInBackground { factory in
            factory.listDisplays(sessionID: self.state.sessionID, sessionEpoch: self.state.sessionEpoch)
        }
    }

    func startDisplays(_ displays: [VSDisplayDescriptor]) {
        let hostMaximum = negotiatedLimits.maximumVideoStreams == 0 ?
            Self.maximumDisplayStreams : Int(negotiatedLimits.maximumVideoStreams)
        let maximum = negotiatedCapabilities.contains(.multiDisplay) ?
            min(Self.maximumDisplayStreams, hostMaximum) : 1
        for display in displays.prefix(maximum) {
            sendInBackground { factory in
                factory.startExistingDisplay(
                    displayID: display.displayID,
                    sessionID: self.state.sessionID,
                    sessionEpoch: self.state.sessionEpoch
                )
            }
        }
    }

    func bindDisplay(_ response: VSStartDisplayResponse) throws {
        guard response.accepted else { throw ProtocolClientError.rejected(response.rejectionReason) }
        guard let sessionKey else { throw SessionRegistryError.unknownSession }
        guard response.streamID > 0 else { throw VideoMediaGateError.invalidStreamID }
        guard let owner = sessionOwner else { throw ControlOutboxError.inactive }
        let streamID = response.streamID
        let binding = DisplayStreamBinding(displayID: response.display.displayID, streamID: streamID)
        try registry.bind(binding, to: sessionKey)
        try mediaGate.bindStream(streamID, owner: owner)
        displayBindings = registry.bindings(in: sessionKey)
        selectedStreamID = selectedStreamID ?? streamID
    }

    func handleVideoConfig(_ config: VSVideoConfig) {
        guard let owner = sessionOwner else { return }
        var result = VSVideoConfigResult()
        result.configEpoch = config.configEpoch
        result.streamID = config.streamID
        var configurationToken: VideoMediaGate.ConfigurationToken?
        do {
            switch try mediaGate.evaluateAndBeginConfiguration(
                config,
                decodeCapabilities: Self.sdrDecodeCapabilities,
                owner: owner
            ) {
            case let .accepted(token, selected):
                // A valid newer config immediately blocks the previous epoch;
                // only a successfully sent positive acknowledgement reopens media.
                configurationToken = token
                result.accepted = true
                result.selectedColorDescription = selected.colorDescription
                decoders.removeValue(forKey: config.streamID)?.invalidate()
                decoderOwners.removeValue(forKey: config.streamID)
            case let .rejected(reason, fallback):
                result.accepted = false
                result.rejectionReason = reason
                if let fallback { result.selectedColorDescription = fallback.colorDescription }
            }
        } catch {
            result.accepted = false
            result.rejectionReason = error.localizedDescription
        }
        let sessionID = state.sessionID
        let sessionEpoch = state.sessionEpoch
        let ticket: ControlSendTicket
        do {
            ticket = try controlOutbox.enqueue(owner: owner) { factory in
                factory.videoConfigResult(
                    result,
                    sessionID: sessionID,
                    sessionEpoch: sessionEpoch
                )
            }
        } catch {
            terminateSession(
                message: "视频配置确认失败：\(error.localizedDescription)",
                failure: ReconnectFailure.classify(error)
            )
            return
        }
        Task { [weak self] in
            do {
                _ = try await ticket.wait()
                guard let self, self.sessionOwner == owner,
                      sessionID == self.state.sessionID,
                      sessionEpoch == self.state.sessionEpoch else { return }
                guard result.accepted else { return }
                guard let configurationToken else { return }
                do {
                    try mediaGate.acknowledgementSent(
                        configurationToken,
                        streamID: result.streamID,
                        owner: owner
                    )
                } catch is VideoMediaGateError {
                    // A newer configuration or stream teardown superseded this
                    // already-sent ACK; it must not activate or tear down that state.
                    return
                }
                decoderOwners[result.streamID] = DecoderOwner(
                    sessionOwner: owner,
                    streamID: result.streamID,
                    configEpoch: result.configEpoch
                )
                if case .ready = state.phase {
                    try state.startStreaming(streamID: result.streamID)
                }
                isStreaming = true
            } catch {
                guard let self, !Task.isCancelled, self.sessionOwner == owner else { return }
                terminateSession(
                    message: "视频配置确认失败：\(error.localizedDescription)",
                    failure: ReconnectFailure.classify(error)
                )
            }
        }
    }

    func startHeartbeat() {
        heartbeatTask?.cancel()
        let interval = heartbeatIntervalMilliseconds
        guard let owner = sessionOwner else { return }
        let sessionID = state.sessionID
        let sessionEpoch = state.sessionEpoch
        heartbeatTask = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    try await Task.sleep(for: .milliseconds(Int(interval)))
                    try Task.checkCancellation()
                    guard let self else { return }
                    guard owner == sessionOwner,
                          sessionID == state.sessionID,
                          sessionEpoch == state.sessionEpoch else { return }
                    if try heartbeatMonitor.status(owner: owner) == .timedOut {
                        terminateSession(message: "心跳超时：连续 3 次未收到 Pong", failure: .heartbeat)
                        return
                    }
                    heartbeatSequence += 1
                    let sequence = heartbeatSequence
                    let ticket = try controlOutbox.enqueue(owner: owner) { factory in
                        factory.ping(sequence: sequence, sessionID: sessionID, sessionEpoch: sessionEpoch)
                    }
                    let ping = try heartbeatMonitor.issuePing(owner: owner, messageID: ticket.messageID)
                    guard ping.sequence == sequence else { throw ProtocolClientError.invalidHeartbeatSequence }
                    _ = try await ticket.wait()
                    guard owner == sessionOwner else { return }
                } catch is CancellationError {
                    return
                } catch {
                    guard let self else { return }
                    guard !Task.isCancelled, owner == sessionOwner else { return }
                    terminateSession(message: "心跳发送失败：\(error.localizedDescription)", failure: .heartbeat)
                    return
                }
            }
        }
    }

    func sendPong(sequence: UInt64, correlationID: UInt64) {
        sendInBackground { factory in
            factory.pong(
                sequence: sequence,
                correlationID: correlationID,
                sessionID: self.state.sessionID,
                sessionEpoch: self.state.sessionEpoch
            )
        }
    }

    func handleVideoStreamEnded(_ ended: VSVideoStreamEnded) {
        guard let sessionKey, let owner = sessionOwner else { return }
        let wasSelected = selectedStreamID == ended.streamID
        if wasSelected { terminateActiveInputBeforeDisplayChange() }
        decoders.removeValue(forKey: ended.streamID)?.invalidate()
        decoderOwners.removeValue(forKey: ended.streamID)
        _ = mediaGate.endStream(ended.streamID, owner: owner)
        _ = registry.release(streamID: ended.streamID, in: sessionKey)
        displayBindings = registry.bindings(in: sessionKey)
        if wasSelected {
            selectedStreamID = nil
            if let replacement = displayBindings.first?.streamID {
                selectDisplay(streamID: replacement)
            }
            pixelBuffer = nil
        }
        guard displayBindings.isEmpty else { return }
        terminateSession(message: "视频流已结束：\(ended.reasonCode)", failure: .permanent)
    }

    func handleAudioConfig(_ config: VSAudioConfig) throws {
        var result = VSAudioConfigResult()
        result.streamID = config.streamID
        result.configEpoch = config.configEpoch
        do {
            guard negotiatedCapabilities.contains(.audio), managedConfiguration.policy.audioAllowed else {
                throw ClipboardTransferError.policyDenied
            }
            audioFormat = try audioPlayback.configure(config)
            audioConfig = config
            audioJitter.reset(firstSequence: 0)
            result.accepted = true
        } catch {
            result.accepted = false
            result.rejectionReason = error.localizedDescription
        }
        sendInBackground { factory in
            factory.audioConfigResult(
                result,
                sessionID: self.state.sessionID,
                sessionEpoch: self.state.sessionEpoch
            )
        }
    }

    func handleVideo(_ packet: MediaPacket) throws {
        guard let owner = sessionOwner else { return }
        guard case let .success(accepted) = mediaGate.admit(
            packet.header,
            payload: packet.payload,
            owner: owner
        ) else { return }
        guard let sessionKey,
              registry.binding(streamID: accepted.streamID, in: sessionKey) != nil,
              let decoderOwner = decoderOwners[accepted.streamID],
              decoderOwner.sessionOwner == owner,
              decoderOwner.configEpoch == accepted.configEpoch else { return }
        let decoder = decoder(for: decoderOwner)
        let parameterSets = VideoDecoder.parameterSets(codec: accepted.codec, from: packet.payload)
        if !parameterSets.isEmpty {
            try decoder.configure(codec: accepted.codec, parameterSets: parameterSets)
        }
        try decoder.decode(
            annexB: packet.payload,
            presentationTime: CMTime(
                value: CMTimeValue(packet.header.captureTimestampNs),
                timescale: 1_000_000_000
            )
        )
    }

    func handleAudio(_ packet: AudioPacket) throws {
        guard let audioConfig, let audioFormat else { return }
        _ = try audioJitter.enqueue(
            packet,
            sessionEpoch: state.sessionEpoch,
            configEpoch: audioConfig.configEpoch,
            format: audioFormat
        )
        for ready in audioJitter.drainReady() { _ = try audioPlayback.schedule(ready) }
    }

    func handleBulk(_ chunk: FileChunk) throws {
        guard chunk.header.sessionEpoch == state.sessionEpoch else { return }
        guard let incomingFiles,
              let offer = pendingFileOffers[chunk.header.transferID] else { return }
        let received = try incomingFiles.append(chunk)
        if received == offer.byteLength {
            let completed = try incomingFiles.finish(transferID: offer.transferID)
            pendingFileOffers.removeValue(forKey: offer.transferID)
            completedFileURL = completed.stagingURL
            var result = VSFileTransferComplete()
            result.transferID = offer.transferID
            result.accepted = true
            result.sha256 = completed.sha256
            sendInBackground { factory in
                factory.fileTransferComplete(
                    result,
                    sessionID: self.state.sessionID,
                    sessionEpoch: self.state.sessionEpoch
                )
            }
        }
    }

    func handleFileAccept(_ response: VSFileAccept) {
        guard response.accepted, let scopedFile = outgoingFiles[response.transferID] else {
            outgoingFiles.removeValue(forKey: response.transferID)?.cancel()
            return
        }
        let transfer = scopedFile.transfer
        guard let owner = sessionOwner else { return }
        let sessionEpoch = state.sessionEpoch
        Task { [weak self] in
            do {
                let negotiatedChunkBytes = response.maximumChunkBytes == 0 ?
                    nil : Int(response.maximumChunkBytes)
                while let chunk = try transfer.nextChunk(
                    maximumBytes: negotiatedChunkBytes,
                    sessionEpoch: sessionEpoch
                ) {
                    guard let self, self.sessionOwner == owner else { return }
                    try await transport.send(
                        TransportFrame(channel: .bulkTransfer, payload: try chunk.serializedFrame()),
                        owner: owner.connectionOwner
                    )
                }
            } catch {
                guard let self, !Task.isCancelled, self.sessionOwner == owner else { return }
                cancelLocalFileTransfer(transferID: response.transferID)
                errorMessage = error.localizedDescription
            }
        }
    }

    func cancelLocalFileTransfer(transferID: Data) {
        incomingFiles?.cancel(transferID: transferID)
        outgoingFiles.removeValue(forKey: transferID)?.cancel()
        pendingFileOffers.removeValue(forKey: transferID)
        pendingFileName = pendingFileOffers.values.first?.fileName
    }

    func decoder(for owner: DecoderOwner) -> VideoDecoder {
        if decoderOwners[owner.streamID] == owner, let decoder = decoders[owner.streamID] { return decoder }
        let decoder = VideoDecoder { [weak self] pixelBuffer, _ in
            let frame = DecodedPixelBuffer(pixelBuffer)
            Task { @MainActor in
                guard let self,
                      DecoderDeliveryGate.accepts(
                        owner: owner,
                        activeOwner: self.decoderOwners[owner.streamID],
                        sessionOwner: self.sessionOwner,
                        selectedStreamID: self.selectedStreamID
                      ) else { return }
                self.pixelBuffer = frame.value
            }
        }
        decoders[owner.streamID] = decoder
        return decoder
    }

    func invokeHostAction(_ identifier: String) {
        guard negotiatedCapabilities.contains(.hostActions),
              availableHostActions.contains(identifier) else { return }
        var invocation = VSHostActionInvoke()
        invocation.actionID = identifier
        invocation.invocationID = withUnsafeBytes(of: UUID().uuid) { Data($0) }
        if let selectedStreamID,
           let binding = displayBindings.first(where: { $0.streamID == selectedStreamID }) {
            invocation.target.displayID = binding.displayID
            invocation.target.streamID = binding.streamID
        }
        sendInBackground { factory in
            factory.hostActionInvoke(
                invocation,
                sessionID: self.state.sessionID,
                sessionEpoch: self.state.sessionEpoch
            )
        }
    }

    func sendManagedPolicyStatus() {
        guard negotiatedCapabilities.contains(.managedConfiguration) else { return }
        let policy = managedConfiguration.policy
        var status = VSManagedPolicyStatus()
        status.managed = policy.isManaged
        status.clipboardAllowed = policy.clipboardAllowed
        status.fileTransferAllowed = policy.fileTransferAllowed
        status.audioAllowed = policy.audioAllowed
        status.wakeAllowed = policy.wakeAllowed
        status.maximumFileBytes = policy.maximumFileBytes
        status.customGesturesAllowed = policy.customGesturesAllowed
        status.hostActionsAllowed = policy.customGesturesAllowed
        sendInBackground { factory in
            factory.managedPolicyStatus(
                status,
                sessionID: self.state.sessionID,
                sessionEpoch: self.state.sessionEpoch
            )
        }
    }

    func enforceCurrentPolicy() {
        let policy = managedConfiguration.policy
        if !policy.audioAllowed {
            audioPlayback.stop()
            audioConfig = nil
            audioFormat = nil
        }
        if !policy.clipboardAllowed { clipboard.rejectPending() }
        if !policy.fileTransferAllowed {
            let identifiers = Set(pendingFileOffers.keys).union(outgoingFiles.keys)
            for identifier in identifiers { cancelLocalFileTransfer(transferID: identifier) }
        }
        if !policy.customGesturesAllowed { availableHostActions = [] }
    }

    func sendInBackground(
        timeout: TimeInterval = 3,
        build: @escaping (inout EnvelopeFactory) throws -> VSEnvelope
    ) {
        guard let owner = sessionOwner else { return }
        let ticket: ControlSendTicket
        do {
            ticket = try controlOutbox.enqueue(owner: owner, timeout: timeout, build: build)
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        Task { [weak self] in
            do { _ = try await ticket.wait() }
            catch {
                guard let self, !Task.isCancelled, self.sessionOwner == owner else { return }
                errorMessage = error.localizedDescription
            }
        }
    }

    func advertisedCapabilities(policy: ManagedPolicy) -> [VSCapability] {
        var values: Set<VSCapability> = [
            .telemetry, .sessionResume,
            .multiDisplay, .colorManagement, .hostActions, .managedConfiguration,
        ]
        values.formUnion(Self.nativeInputAvailability.advertisedCapabilities)
        if policy.audioAllowed { values.insert(.audio) }
        if policy.clipboardAllowed { values.insert(.clipboard) }
        if policy.fileTransferAllowed { values.insert(.fileTransfer) }
        if policy.wakeAllowed { values.insert(.wakeHost) }
        return values.sorted { $0.rawValue < $1.rawValue }
    }

    func clientResourceLimits(policy: ManagedPolicy) -> VSResourceLimits {
        var limits = VSResourceLimits()
        limits.maximumClients = 1
        limits.maximumDisplays = UInt32(Self.maximumDisplayStreams)
        limits.maximumVideoStreams = UInt32(Self.maximumDisplayStreams)
        limits.maximumAudioStreams = policy.audioAllowed ? 1 : 0
        limits.maximumClipboardBytes = policy.clipboardAllowed ? 1_024 * 1_024 : 0
        limits.maximumFileBytes = policy.fileTransferAllowed ? policy.maximumFileBytes : 0
        limits.maximumFileChunkBytes = 64 * 1_024
        return limits
    }

    static let sdrDecodeCapabilities: [VSVideoDecodeCapability] = {
        [VSCodec.h264, .hevc].map { codec in
            var capability = VSVideoDecodeCapability()
            capability.codec = codec
            capability.maximumWidth = 3_840
            capability.maximumHeight = 2_160
            capability.maximumFramesPerSecond = 120
            capability.bitDepths = [8]
            capability.transferFunctions = [.bt709, .srgb]
            return capability
        }
    }()
}

private enum ProtocolClientError: Error, LocalizedError {
    case rejected(String)
    case invalidPong
    case invalidHeartbeatSequence

    var errorDescription: String? {
        switch self {
        case let .rejected(message): message
        case .invalidPong: "主机返回了不匹配当前心跳的 Pong"
        case .invalidHeartbeatSequence: "本地心跳序列状态不一致"
        }
    }
}

// The app treats the retained VideoToolbox output as read-only across the UI actor hop.
private struct DecodedPixelBuffer: @unchecked Sendable {
    let value: CVPixelBuffer

    init(_ value: CVPixelBuffer) {
        self.value = value
    }
}
