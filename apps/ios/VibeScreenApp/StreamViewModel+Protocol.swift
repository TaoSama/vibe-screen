import CoreMedia
import CoreVideo
import Foundation
import VibeScreenCore
import VibeScreenProtocol
import VibeScreenVideo

extension StreamViewModel {
    func send(_ envelope: VSEnvelope) async throws {
        try await transport.send(
            TransportFrame(channel: .control, payload: EnvelopeCodec.serialize(envelope))
        )
    }

    func handle(_ result: Result<TransportFrame, Error>) {
        do {
            let frame = try result.get()
            switch frame.channel {
            case .control: try handleControl(EnvelopeCodec.deserialize(frame.payload))
            case .video: try handleVideo(MediaPacket(serializedFrame: frame.payload))
            case .audio: try handleAudio(AudioPacket(serializedFrame: frame.payload))
            case .bulkTransfer: try handleBulk(FileChunk(serializedFrame: frame.payload))
            }
        } catch {
            errorMessage = error.localizedDescription
            isStreaming = false
            state.disconnected(retryAttempt: 1)
        }
    }

    func handleControl(_ envelope: VSEnvelope) throws {
        if envelope.hasHostHello { pendingHostHello = envelope.hostHello }
        if envelope.hasSessionAccepted { try acceptSession(envelope.sessionAccepted) }
        if envelope.hasSessionRejected { throw ProtocolClientError.rejected(envelope.sessionRejected.message) }
        if envelope.hasVideoConfig { handleVideoConfig(envelope.videoConfig) }
        if envelope.hasAudioConfig { try handleAudioConfig(envelope.audioConfig) }
        if envelope.hasListDisplaysResponse { startDisplays(envelope.listDisplaysResponse.displays) }
        if envelope.hasStartDisplayResponse { try bindDisplay(envelope.startDisplayResponse) }
        if envelope.hasClipboardContent, negotiatedCapabilities.contains(.clipboard) {
            clipboard.stage(envelope.clipboardContent)
        }
        if envelope.hasFileOffer, negotiatedCapabilities.contains(.fileTransfer) {
            let maximum = negotiatedLimits.maximumFileBytes == 0 ?
                managedConfiguration.policy.maximumFileBytes :
                min(negotiatedLimits.maximumFileBytes, managedConfiguration.policy.maximumFileBytes)
            if envelope.fileOffer.byteLength <= maximum {
                pendingFileOffers[envelope.fileOffer.transferID] = envelope.fileOffer
                pendingFileName = envelope.fileOffer.fileName
            } else {
                var rejection = VSFileAccept()
                rejection.transferID = envelope.fileOffer.transferID
                rejection.accepted = false
                rejection.rejectionReason = "negotiated_file_limit_exceeded"
                sendInBackground(factory.fileAccept(
                    rejection,
                    sessionID: state.sessionID,
                    sessionEpoch: state.sessionEpoch
                ))
            }
        }
        if envelope.hasFileAccept { handleFileAccept(envelope.fileAccept) }
        if envelope.hasFileTransferCancel { cancelLocalFileTransfer(transferID: envelope.fileTransferCancel.transferID) }
        if envelope.hasFileTransferComplete {
            outgoingFiles.removeValue(forKey: envelope.fileTransferComplete.transferID)?.cancel()
        }
        if envelope.hasHostActionCatalog, negotiatedCapabilities.contains(.hostActions) {
            availableHostActions = envelope.hostActionCatalog.actions.map(\.actionID)
        }
        if envelope.hasManagedPolicyStatus,
           negotiatedCapabilities.contains(.managedConfiguration) {
            managedConfiguration.applyRemote(envelope.managedPolicyStatus)
            enforceCurrentPolicy()
        }
    }

    func acceptSession(_ accepted: VSSessionAccepted) throws {
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
        if negotiatedCapabilities.contains(.deviceIdentity) {
            UserDefaults.standard.set(true, forKey: "hasAuthorizedHostIdentity")
        }
        let key = ClientSessionKey(sessionID: state.sessionID, epoch: state.sessionEpoch)
        try registry.register(key)
        sessionKey = key
        sendManagedPolicyStatus()
        sendInBackground(factory.listDisplays(sessionID: state.sessionID, sessionEpoch: state.sessionEpoch))
    }

    func startDisplays(_ displays: [VSDisplayDescriptor]) {
        let hostMaximum = negotiatedLimits.maximumVideoStreams == 0 ?
            Self.maximumDisplayStreams : Int(negotiatedLimits.maximumVideoStreams)
        let maximum = negotiatedCapabilities.contains(.multiDisplay) ?
            min(Self.maximumDisplayStreams, hostMaximum) : 1
        for display in displays.prefix(maximum) {
            sendInBackground(factory.startExistingDisplay(
                displayID: display.displayID,
                sessionID: state.sessionID,
                sessionEpoch: state.sessionEpoch
            ))
        }
    }

    func bindDisplay(_ response: VSStartDisplayResponse) throws {
        guard response.accepted else { throw ProtocolClientError.rejected(response.rejectionReason) }
        guard let sessionKey else { throw SessionRegistryError.unknownSession }
        let streamID = response.streamID == 0 ? UInt64(displayBindings.count + 1) : response.streamID
        let binding = DisplayStreamBinding(displayID: response.display.displayID, streamID: streamID)
        try registry.bind(binding, to: sessionKey)
        displayBindings = registry.bindings(in: sessionKey)
        selectedStreamID = selectedStreamID ?? streamID
        if case .ready = state.phase { try state.startStreaming(streamID: streamID) }
        isStreaming = true
    }

    func handleVideoConfig(_ config: VSVideoConfig) {
        let negotiator = VideoColorNegotiator(decodeCapabilities: Self.sdrDecodeCapabilities)
        var result = VSVideoConfigResult()
        result.configEpoch = config.configEpoch
        result.streamID = config.streamID
        switch negotiator.evaluate(config) {
        case let .accepted(selected):
            result.accepted = true
            result.selectedColorDescription = selected.colorDescription
            configuredCodecs[selected.streamID] = selected.codec
        case let .fallback(fallback, reason):
            result.accepted = false
            result.rejectionReason = reason
            result.selectedColorDescription = fallback.colorDescription
        }
        sendInBackground(factory.videoConfigResult(
            result,
            sessionID: state.sessionID,
            sessionEpoch: state.sessionEpoch
        ))
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
        sendInBackground(factory.audioConfigResult(
            result,
            sessionID: state.sessionID,
            sessionEpoch: state.sessionEpoch
        ))
    }

    func handleVideo(_ packet: MediaPacket) throws {
        guard state.accepts(epoch: packet.header.sessionEpoch) else { return }
        let streamID = packet.header.streamID == 0 ? selectedStreamID ?? 1 : packet.header.streamID
        guard sessionKey.flatMap({ registry.binding(streamID: streamID, in: $0) }) != nil else { return }
        let codec = packet.header.codec == .unspecified ? configuredCodecs[streamID] ?? .h264 : packet.header.codec
        let decoder = decoder(for: streamID)
        let parameterSets = VideoDecoder.parameterSets(codec: codec, from: packet.payload)
        if !parameterSets.isEmpty {
            try decoder.configure(codec: codec, parameterSets: parameterSets)
            configuredCodecs[streamID] = codec
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
            sendInBackground(factory.fileTransferComplete(
                result,
                sessionID: state.sessionID,
                sessionEpoch: state.sessionEpoch
            ))
        }
    }

    func handleFileAccept(_ response: VSFileAccept) {
        guard response.accepted, let scopedFile = outgoingFiles[response.transferID] else {
            outgoingFiles.removeValue(forKey: response.transferID)?.cancel()
            return
        }
        let transfer = scopedFile.transfer
        Task {
            do {
                let negotiatedChunkBytes = response.maximumChunkBytes == 0 ?
                    nil : Int(response.maximumChunkBytes)
                while let chunk = try transfer.nextChunk(
                    maximumBytes: negotiatedChunkBytes,
                    sessionEpoch: state.sessionEpoch
                ) {
                    try await transport.send(
                        TransportFrame(channel: .bulkTransfer, payload: try chunk.serializedFrame())
                    )
                }
            } catch {
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

    func decoder(for streamID: UInt64) -> VideoDecoder {
        if let decoder = decoders[streamID] { return decoder }
        let decoder = VideoDecoder { [weak self] pixelBuffer, _ in
            Task { @MainActor in
                guard self?.selectedStreamID == streamID else { return }
                self?.pixelBuffer = pixelBuffer
            }
        }
        decoders[streamID] = decoder
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
        sendInBackground(factory.hostActionInvoke(
            invocation,
            sessionID: state.sessionID,
            sessionEpoch: state.sessionEpoch
        ))
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
        sendInBackground(factory.managedPolicyStatus(
            status,
            sessionID: state.sessionID,
            sessionEpoch: state.sessionEpoch
        ))
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

    func sendInBackground(_ envelope: VSEnvelope) {
        Task {
            do { try await send(envelope) }
            catch { errorMessage = error.localizedDescription }
        }
    }

    func advertisedCapabilities(policy: ManagedPolicy) -> [VSCapability] {
        var values: [VSCapability] = [
            .touch, .keyboard, .pointer, .telemetry, .sessionResume,
            .multiDisplay, .colorManagement, .hostActions, .managedConfiguration,
        ]
        if policy.audioAllowed { values.append(.audio) }
        if policy.clipboardAllowed { values.append(.clipboard) }
        if policy.fileTransferAllowed { values.append(.fileTransfer) }
        if policy.wakeAllowed { values.append(.wakeHost) }
        return values
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

private enum ProtocolClientError: Error {
    case rejected(String)
}
