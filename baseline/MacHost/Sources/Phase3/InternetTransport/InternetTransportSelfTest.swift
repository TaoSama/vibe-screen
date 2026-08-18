import Foundation
import VibeScreenProtocol

enum InternetTransportSelfTest {
    static func run() -> Bool {
        let ciphers: (host: PlatformSessionPacketCipher, device: PlatformSessionPacketCipher)
        do {
            ciphers = try PlatformSessionPacketCipher.selfTestPair(
                sessionIdentifier: "session-test",
                sharedSecret: Data(repeating: 0x11, count: 32),
                bootstrapSecret: Data(repeating: 0x22, count: 32),
                transcriptContext: Data(repeating: 0x33, count: 32)
            )
        } catch {
            print("Phase 3 Internet self-test: FAIL (cipher setup: \(error))")
            return false
        }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 32,
            maximumBufferedControlBytes: 64,
            maximumMediaFrameBytes: 64,
            maximumRelayBytesPerSession: 500
        )
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            limits: limits,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2),
            adaptivePolicy: AdaptiveMediaPolicy(
                observationsBeforeDowngrade: 1,
                observationsBeforeUpgrade: 1
            )
        )

        var requestedKeyframes = 0
        var adaptiveProfile: AdaptiveMediaProfile?
        var receivedControl: [Data] = []
        transport.onKeyframeRequired = { requestedKeyframes += 1 }
        transport.onAdaptiveProfileChanged = { adaptiveProfile = $0 }
        transport.onControlReceived = { receivedControl.append($0) }

        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [
                    WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!]),
                    WebRTCICEServer(
                        urls: [URL(string: "turns:relay.example.test:5349")!],
                        username: "short-lived-user",
                        credential: "short-lived-secret"
                    )
                ],
                peerIdentity: "device-test",
                sessionIdentifier: "session-test",
                forceRelay: true
            ))
        } catch {
            print("Phase 3 Internet self-test: FAIL (start: \(error))")
            return false
        }

        engine.connect(path: .relay)
        let inboundControl = try? ciphers.device.seal(Data("encrypted-inbound".utf8), channel: .control)
        if let inboundControl {
            engine.receive(inboundControl, channel: .control)
            engine.receive(inboundControl, channel: .control)
        }
        guard let keyframe = encodedFrame(
            payloads: [
                Data(repeating: 0x01, count: 15),
                Data(repeating: 0x11, count: 15),
            ],
            captureTimestamp: 1,
            isKeyframe: true
        ), let staleFrame = encodedFrame(
            payloads: [Data(repeating: 0x02, count: 30)],
            captureTimestamp: 2,
            isKeyframe: true
        ), let latestFrame = encodedFrame(
            payloads: [
                Data(repeating: 0x04, count: 10),
                Data(repeating: 0x14, count: 20),
            ],
            captureTimestamp: 3,
            isKeyframe: true
        ), let overBudgetFrame = encodedFrame(
            payloads: [
                Data(repeating: 0x05, count: 16),
                Data(repeating: 0x15, count: 16),
                Data(repeating: 0x25, count: 16),
                Data(repeating: 0x35, count: 16),
            ],
            captureTimestamp: 4,
            isKeyframe: true
        ) else {
            print("Phase 3 Internet self-test: FAIL (media frame setup)")
            return false
        }

        let controlAccepted = transport.sendControl(Data(repeating: 0x03, count: 10)).isSuccess
        let emptyControlRejected = transport.sendControl(Data()).isEmptyPayloadFailure
        let keyframeAccepted = transport.sendMedia(keyframe).isSuccess
        let staleFrameAccepted = transport.sendMedia(staleFrame).isSuccess
        let latestFrameAccepted = transport.sendMedia(latestFrame).isSuccess
        let overBudgetRejected = transport.sendMedia(overBudgetFrame).isRelayBudgetFailure
        engine.completeAllSends()
        let expectedRelayBytes = InternetMediaRecordContract.encryptedRecordBytes(forPlaintextBytes: 10)
            + keyframe.totalEncryptedRecordBytes
            + latestFrame.totalEncryptedRecordBytes

        engine.changePath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))
        engine.changePath(InternetNetworkPath(
            interface: .cellular,
            isSatisfied: true,
            fingerprint: "cellular-b"
        ))
        engine.sample(InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 500,
            packetLossFraction: 0.2,
            availableOutgoingBitrateBps: 1_000_000
        ))

        let snapshot = transport.snapshot()
        let missingSignalingRejected = productionRejectsMissingSignaling()
        let backlogFailsClosed = controlBacklogFailsClosed()
        let mediaFragmentationPasses = mediaFragmentationContractPasses()
        let mediaGenerationGatePasses = mediaGenerationGateContractPasses()
        let relayKeyframeGatePasses = relayKeyframeGateContractPasses()
        let mediaBatchValidationPasses = mediaBatchValidationContractPasses()
        let restartAdmissionGatePasses = restartAdmissionGateContractPasses()
        let controlGenerationGatePasses = controlGenerationGateContractPasses()
        let controlRestartAdmissionGatePasses = controlRestartAdmissionGateContractPasses()
        let controlPathDecisionGatePasses = controlPathDecisionGateContractPasses()
        let staleRelayAccountingPasses = staleRelayAccountingContractPasses()
        let controlFailureCloseGatePasses = controlFailureCloseGateContractPasses()
        let failureTransitionOrderingPasses = failureTransitionOrderingContractPasses()
        let sdkTransmissionEpochGatePasses = sdkTransmissionEpochGateContractPasses()
        let recoveryExhaustionFailClosedPasses = recoveryExhaustionFailClosedContractPasses()
        let finalReviewContractsPassed = finalReviewContractsPass()
        let legacyCleanupCrashSafe = LegacyGlobalRevocationCleanupSelfTest.run()
        let unknownCandidatePathFailsClosed =
            SelectedCandidatePathResolver.resolve(
                localCandidateType: nil,
                remoteCandidateType: "host"
            ) == .unknown &&
            SelectedCandidatePathResolver.resolve(
                localCandidateType: "host",
                remoteCandidateType: "srflx"
            ) == .direct &&
            SelectedCandidatePathResolver.mustFailClosed(
                publishedPath: .direct,
                observedPath: .unknown
            ) &&
            SelectedCandidatePathResolver.mustFailClosed(
                publishedPath: .relay,
                observedPath: nil
            )
        let passed = controlAccepted && emptyControlRejected && keyframeAccepted && staleFrameAccepted
            && latestFrameAccepted && overBudgetRejected
            && engine.channelConfigurations == InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
            && engine.restartCount == 1
            && snapshot.relayBytesSent == expectedRelayBytes
            && snapshot.relayBytesReserved == 0
            && snapshot.droppedMediaFrames == 1
            && engine.mediaPayloads == keyframe.records + latestFrame.records
            && receivedControl == [Data("encrypted-inbound".utf8)]
            && requestedKeyframes >= 1
            && adaptiveProfile == AdaptiveMediaPolicy.constrained
            && missingSignalingRejected
            && backlogFailsClosed
            && mediaFragmentationPasses
            && mediaGenerationGatePasses
            && relayKeyframeGatePasses
            && mediaBatchValidationPasses
            && restartAdmissionGatePasses
            && controlGenerationGatePasses
            && controlRestartAdmissionGatePasses
            && controlPathDecisionGatePasses
            && staleRelayAccountingPasses
            && controlFailureCloseGatePasses
            && failureTransitionOrderingPasses
            && sdkTransmissionEpochGatePasses
            && recoveryExhaustionFailClosedPasses
            && finalReviewContractsPassed
            && legacyCleanupCrashSafe
            && unknownCandidatePathFailsClosed

        transport.close()
        print(
            "Phase 3 Internet self-test: \(passed ? "PASS" : "FAIL") "
                + "(channels=\(engine.channelConfigurations.count), relayBytes=\(snapshot.relayBytesSent), "
                + "reserved=\(snapshot.relayBytesReserved), latestFrameDrops=\(snapshot.droppedMediaFrames), "
                + "iceRestarts=\(engine.restartCount), mediaFragmentation=\(mediaFragmentationPasses), "
                + "mediaGenerationGate=\(mediaGenerationGatePasses), "
                + "relayKeyframeGate=\(relayKeyframeGatePasses), "
                + "mediaBatchValidation=\(mediaBatchValidationPasses), "
                + "restartAdmissionGate=\(restartAdmissionGatePasses), "
                + "controlGenerationGate=\(controlGenerationGatePasses), "
                + "controlRestartAdmissionGate=\(controlRestartAdmissionGatePasses), "
                + "controlPathDecisionGate=\(controlPathDecisionGatePasses), "
                + "staleRelayAccounting=\(staleRelayAccountingPasses), "
                + "controlFailureCloseGate=\(controlFailureCloseGatePasses), "
                + "failureTransitionOrdering=\(failureTransitionOrderingPasses), "
                + "sdkTransmissionEpochGate=\(sdkTransmissionEpochGatePasses), "
                + "recoveryExhaustionFailClosed=\(recoveryExhaustionFailClosedPasses), "
                + "finalReviewContracts=\(finalReviewContractsPassed), "
                + "legacyCleanupCrashSafe=\(legacyCleanupCrashSafe), "
                + "unknownCandidatePathFailsClosed=\(unknownCandidatePathFailsClosed))"
        )
        return passed
    }

    private static func mediaFragmentationContractPasses() -> Bool {
        guard var codec = try? InternetProductProtocolCodec(
            sessionIdentifier: "fragmentation-self-test",
            sessionEpoch: 1,
            hostID: "host",
            hostName: "Mac",
            peerDeviceID: "device",
            video: InternetProductVideoConfiguration(
                codec: .hevc,
                width: 1920,
                height: 1080,
                framesPerSecond: 60,
                bitrateKbps: 20_000
            ),
            limits: .standard
        ) else { return false }

        let negotiatedMaximum = InternetMediaRecordContract.minimumNegotiatedEncryptedRecordBytes
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var limits = VSResourceLimits()
        limits.maximumEncryptedMediaRecordBytes = UInt32(negotiatedMaximum)
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "device"
        hello.deviceName = "Synthetic Device"
        hello.capabilities = Array(InternetProductProtocolCodec.requiredCapabilities) + [.touch]
        hello.requiredCapabilities = Array(InternetProductProtocolCodec.requiredCapabilities)
        hello.codecs = [.hevc]
        hello.transports = [.internet]
        hello.resourceLimits = limits
        guard (try? codec.validate(hello)) != nil,
              codec.negotiatedMaximumEncryptedMediaRecordBytes == negotiatedMaximum,
              let acceptedData = try? codec.sessionAccepted(
                  heartbeatIntervalMilliseconds: 1_000,
                  peerSupportsTouch: true
              ),
              let acceptedEnvelope = try? VSEnvelope(serializedBytes: acceptedData),
              acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.mediaRecordFragmentation),
              acceptedEnvelope.sessionAccepted.negotiatedResourceLimits.maximumEncryptedMediaRecordBytes
                == UInt32(negotiatedMaximum) else {
            return false
        }

        for removedCapability in [
            VSCapability.mediaRecordFragmentation,
            .audioDataChannel,
            .bulkDataChannel,
        ] {
            var legacyCodec = codec
            var legacyHello = hello
            legacyHello.capabilities.removeAll { $0 == removedCapability }
            legacyHello.requiredCapabilities.removeAll { $0 == removedCapability }
            guard (try? legacyCodec.validate(legacyHello)) == nil else { return false }
        }
        var invalidLimitCodec = codec
        var invalidLimitHello = hello
        invalidLimitHello.resourceLimits.maximumEncryptedMediaRecordBytes = 0
        guard (try? invalidLimitCodec.validate(invalidLimitHello)) == nil else { return false }

        for payloadBytes in [4 * 1_024 * 1_024, 16 * 1_024 * 1_024] {
            let payload = Data(repeating: 0x41, count: payloadBytes)
            guard let frame = try? codec.mediaFrame(
                payload: payload,
                timestamp: UInt64(payloadBytes),
                isKeyframe: true
            ), frame.records.count > 1 else { return false }
            var reassembled = Data()
            for (index, record) in frame.records.enumerated() {
                guard record.count <= InternetMediaRecordContract.maximumPlaintextRecordBytes(
                    negotiatedEncryptedRecordBytes: negotiatedMaximum
                ),
                      record.count + InternetMediaRecordContract.applicationAEADRecordOverheadBytes
                        <= negotiatedMaximum,
                      let packet = try? ProtocolV1MediaPacketCodec.decode(record),
                      packet.header.fragmentIndex == UInt32(index),
                      packet.header.fragmentCount == UInt32(frame.records.count) else {
                    return false
                }
                reassembled.append(packet.payload)
            }
            guard reassembled == payload else { return false }
        }

        guard (try? codec.mediaFrame(
            payload: Data(repeating: 0x41, count: 16 * 1_024 * 1_024 + 1),
            timestamp: 1,
            isKeyframe: true
        )) == nil else { return false }

        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "maximum-media-record-self-test",
            sharedSecret: Data(repeating: 0x21, count: 32),
            bootstrapSecret: Data(repeating: 0x22, count: 32),
            transcriptContext: Data(repeating: 0x23, count: 32)
        ) else { return false }
        defer {
            ciphers.host.close()
            ciphers.device.close()
        }
        let maximumPlaintext = Data(
            repeating: 0x41,
            count: InternetMediaRecordContract.maximumPlaintextRecordBytes
        )
        guard let maximumRecord = try? ciphers.host.seal(maximumPlaintext, channel: .media) else {
            return false
        }
        return maximumRecord.count == InternetMediaRecordContract.maximumEncryptedRecordBytes
            && ciphers.device.open(maximumRecord, channel: .media) == maximumPlaintext
    }

    private static func mediaGenerationGateContractPasses() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "generation-gate-self-test",
            sharedSecret: Data(repeating: 0x31, count: 32),
            bootstrapSecret: Data(repeating: 0x32, count: 32),
            transcriptContext: Data(repeating: 0x33, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        var transport: WebRTCInternetTransport?
        var sendEntries = 0
        transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            beforeMediaRecordSend: {
                sendEntries += 1
                if sendEntries == 2 { transport?.close() }
            }
        )
        do {
            try transport?.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "generation-gate-peer",
                sessionIdentifier: "generation-gate-self-test",
                forceRelay: false
            ))
        } catch {
            transport?.close()
            return false
        }
        engine.connect(path: .direct)
        guard let frame = encodedFrame(
            payloads: [Data([1]), Data([2])],
            captureTimestamp: 1,
            isKeyframe: true
        ) else { return false }
        let accepted = transport?.sendMedia(frame).isSuccess == true
        engine.completeAllSends()
        return accepted
            && engine.mediaPayloads == [frame.records[0]]
            && transport?.snapshot().state == .closed
    }

    private static func relayKeyframeGateContractPasses() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "relay-keyframe-gate-self-test",
            sharedSecret: Data(repeating: 0x41, count: 32),
            bootstrapSecret: Data(repeating: 0x42, count: 32),
            transcriptContext: Data(repeating: 0x43, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let encryptedRecordBytes = UInt64(1 + PlatformSessionPacketCipher.recordOverhead)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 8,
                maximumBufferedControlBytes: 8,
                maximumMediaFrameBytes: 8,
                maximumRelayBytesPerSession: encryptedRecordBytes - 1
            )
        )
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(
                    urls: [URL(string: "turns:relay.example.test:5349")!],
                    username: "short-lived-user",
                    credential: "short-lived-secret"
                )],
                peerIdentity: "relay-keyframe-gate-peer",
                sessionIdentifier: "relay-keyframe-gate-self-test",
                forceRelay: true
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .relay)
        guard let keyframe = encodedFrame(
            payloads: [Data([1])],
            captureTimestamp: 1,
            isKeyframe: true
        ), let delta = encodedFrame(
            payloads: [Data([2])],
            captureTimestamp: 2,
            isKeyframe: false
        ) else { return false }
        let keyframeRejected = transport.sendMedia(keyframe).isRelayBudgetFailure
        let deltaDropped = transport.sendMedia(delta).isSuccess
        let snapshot = transport.snapshot()
        transport.close()
        return keyframeRejected
            && deltaDropped
            && engine.mediaPayloads.isEmpty
            && snapshot.relayBytesReserved == 0
            && snapshot.droppedMediaFrames == 1
    }

    private static func mediaBatchValidationContractPasses() -> Bool {
        guard let valid = encodedFrame(
            payloads: [Data([1]), Data([2])],
            captureTimestamp: 9,
            isKeyframe: true
        ) else { return false }
        guard valid.mediaPayloadBytes == 2 else { return false }
        guard (try? EncodedInternetFrame(
            records: [],
            mediaPayloadBytes: 0,
            captureTimestamp: 9,
            isKeyframe: true
        )) == nil else { return false }
        guard (try? EncodedInternetFrame(
            records: valid.records,
            mediaPayloadBytes: 3,
            captureTimestamp: 9,
            isKeyframe: true
        )) == nil else { return false }
        guard let wrongScopeRecord = try? mediaRecord(
            payload: Data([2]),
            captureTimestamp: 9,
            isKeyframe: true,
            frameID: 10,
            fragmentIndex: 1,
            fragmentCount: 2
        ) else { return false }
        guard (try? EncodedInternetFrame(
            records: [valid.records[0], wrongScopeRecord],
            mediaPayloadBytes: 2,
            captureTimestamp: 9,
            isKeyframe: true
        )) == nil else { return false }
        return (try? EncodedInternetFrame(
            records: [Data(
                repeating: 0x41,
                count: InternetMediaRecordContract.maximumPlaintextRecordBytes + 1
            )],
            mediaPayloadBytes: 1,
            captureTimestamp: 9,
            isKeyframe: true
        )) == nil
    }

    private static func restartAdmissionGateContractPasses() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "restart-admission-gate-self-test",
            sharedSecret: Data(repeating: 0x51, count: 32),
            bootstrapSecret: Data(repeating: 0x52, count: 32),
            transcriptContext: Data(repeating: 0x53, count: 32)
        ), let recoveryFrame = encodedFrame(
            payloads: [Data([1])],
            captureTimestamp: 1,
            isKeyframe: true
        ), let postRecoveryFrame = encodedFrame(
            payloads: [Data([2])],
            captureTimestamp: 2,
            isKeyframe: true
        ) else { return false }

        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let transitionEntered = DispatchSemaphore(value: 0)
        let releaseTransition = DispatchSemaphore(value: 0)
        let recoveryFinished = DispatchSemaphore(value: 0)
        let sendStarted = DispatchSemaphore(value: 0)
        let sendFinished = DispatchSemaphore(value: 0)
        let sendResult = LockedSelfTestTransportResult()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            duringMediaRecoveryTransition: {
                transitionEntered.signal()
                _ = releaseTransition.wait(timeout: .now() + 2)
            }
        )
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "restart-admission-gate-peer",
                sessionIdentifier: "restart-admission-gate-self-test",
                forceRelay: false
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .direct)
        let engineBox = UncheckedSendableBox(engine)
        let transportBox = UncheckedSendableBox(transport)

        DispatchQueue.global().async {
            engineBox.value.disconnect()
            recoveryFinished.signal()
        }
        guard transitionEntered.wait(timeout: .now() + 2) == .success else {
            releaseTransition.signal()
            transport.close()
            return false
        }
        DispatchQueue.global().async {
            sendStarted.signal()
            sendResult.store(transportBox.value.sendMedia(recoveryFrame))
            sendFinished.signal()
        }
        guard sendStarted.wait(timeout: .now() + 2) == .success else {
            releaseTransition.signal()
            transport.close()
            return false
        }
        let admissionCompletedWithoutWaitingForCallback =
            sendFinished.wait(timeout: .now() + 0.1) == .success
        releaseTransition.signal()
        let recoveryCompleted = recoveryFinished.wait(timeout: .now() + 2) == .success
        let rejectedDuringRecovery = sendResult.load()?.isNotConnectedFailure == true
        let recoverySnapshot = transport.snapshot()

        engine.connect(path: .direct)
        let postRecoveryAccepted = transport.sendMedia(postRecoveryFrame).isSuccess
        let pipelineReusable = engine.mediaPayloads == postRecoveryFrame.records
        engine.completeAllSends()
        transport.close()
        return admissionCompletedWithoutWaitingForCallback
            && recoveryCompleted
            && rejectedDuringRecovery
            && recoverySnapshot.state == .recovering(attempt: 1)
            && !recoverySnapshot.hasPendingMediaFrame
            && recoverySnapshot.relayBytesReserved == 0
            && postRecoveryAccepted
            && pipelineReusable
    }

    private static func controlGenerationGateContractPasses() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "control-generation-gate-self-test",
            sharedSecret: Data(repeating: 0x71, count: 32),
            bootstrapSecret: Data(repeating: 0x72, count: 32),
            transcriptContext: Data(repeating: 0x73, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        var sendEntries = 0
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            beforeControlSend: {
                sendEntries += 1
                if sendEntries == 2 {
                    engine.changePath(InternetNetworkPath(
                        interface: .cellular,
                        isSatisfied: true,
                        fingerprint: "cellular-b"
                    ))
                }
            }
        )
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(
                    urls: [URL(string: "turns:relay.example.test:5349")!],
                    username: "short-lived-user",
                    credential: "short-lived-secret"
                )],
                peerIdentity: "control-generation-gate-peer",
                sessionIdentifier: "control-generation-gate-self-test",
                forceRelay: true
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .relay)
        engine.changePath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))
        let firstAccepted = transport.sendControl(Data([1])).isSuccess
        let secondAccepted = transport.sendControl(Data([2])).isSuccess
        engine.completeAllSends()
        let snapshot = transport.snapshot()
        let encryptedRecordBytes = InternetMediaRecordContract.encryptedRecordBytes(forPlaintextBytes: 1)
        transport.close()
        return firstAccepted
            && secondAccepted
            && engine.controlPayloads == [Data([1])]
            && engine.restartCount == 1
            && snapshot.state == .recovering(attempt: 1)
            && snapshot.bufferedControlBytes == 0
            && snapshot.relayBytesReserved == 0
            && snapshot.relayBytesSent == encryptedRecordBytes
    }

    private static func controlRestartAdmissionGateContractPasses() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "control-restart-admission-self-test",
            sharedSecret: Data(repeating: 0x81, count: 32),
            bootstrapSecret: Data(repeating: 0x82, count: 32),
            transcriptContext: Data(repeating: 0x83, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let transitionEntered = DispatchSemaphore(value: 0)
        let releaseTransition = DispatchSemaphore(value: 0)
        let recoveryFinished = DispatchSemaphore(value: 0)
        let sendStarted = DispatchSemaphore(value: 0)
        let sendFinished = DispatchSemaphore(value: 0)
        let sendResult = LockedSelfTestTransportResult()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            duringMediaRecoveryTransition: {
                transitionEntered.signal()
                _ = releaseTransition.wait(timeout: .now() + 2)
            }
        )
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "control-restart-admission-peer",
                sessionIdentifier: "control-restart-admission-self-test",
                forceRelay: false
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .direct)
        let engineBox = UncheckedSendableBox(engine)
        let transportBox = UncheckedSendableBox(transport)

        DispatchQueue.global().async {
            engineBox.value.disconnect()
            recoveryFinished.signal()
        }
        guard transitionEntered.wait(timeout: .now() + 2) == .success else {
            releaseTransition.signal()
            transport.close()
            return false
        }
        DispatchQueue.global().async {
            sendStarted.signal()
            sendResult.store(transportBox.value.sendControl(Data([1])))
            sendFinished.signal()
        }
        guard sendStarted.wait(timeout: .now() + 2) == .success else {
            releaseTransition.signal()
            transport.close()
            return false
        }
        let admissionCompletedWithoutWaitingForCallback =
            sendFinished.wait(timeout: .now() + 0.1) == .success
        releaseTransition.signal()
        let recoveryCompleted = recoveryFinished.wait(timeout: .now() + 2) == .success
        let rejectedDuringRecovery = sendResult.load()?.isNotConnectedFailure == true
        let snapshot = transport.snapshot()
        transport.close()
        return admissionCompletedWithoutWaitingForCallback
            && recoveryCompleted
            && rejectedDuringRecovery
            && engine.controlPayloads.isEmpty
            && snapshot.state == .recovering(attempt: 1)
            && snapshot.bufferedControlBytes == 0
            && snapshot.relayBytesReserved == 0
    }

    private static func controlPathDecisionGateContractPasses() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "control-path-decision-self-test",
            sharedSecret: Data(repeating: 0x91, count: 32),
            bootstrapSecret: Data(repeating: 0x92, count: 32),
            transcriptContext: Data(repeating: 0x93, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let decisionEntered = DispatchSemaphore(value: 0)
        let releaseDecision = DispatchSemaphore(value: 0)
        let pathChangeFinished = DispatchSemaphore(value: 0)
        let sendStarted = DispatchSemaphore(value: 0)
        let sendFinished = DispatchSemaphore(value: 0)
        let sendResult = LockedSelfTestTransportResult()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            duringRecoveryDecision: {
                decisionEntered.signal()
                _ = releaseDecision.wait(timeout: .now() + 2)
            }
        )
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "control-path-decision-peer",
                sessionIdentifier: "control-path-decision-self-test",
                forceRelay: false
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .direct)
        engine.changePath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))
        let engineBox = UncheckedSendableBox(engine)
        let transportBox = UncheckedSendableBox(transport)

        DispatchQueue.global().async {
            engineBox.value.changePath(InternetNetworkPath(
                interface: .cellular,
                isSatisfied: true,
                fingerprint: "cellular-b"
            ))
            pathChangeFinished.signal()
        }
        guard decisionEntered.wait(timeout: .now() + 2) == .success else {
            releaseDecision.signal()
            transport.close()
            return false
        }
        DispatchQueue.global().async {
            sendStarted.signal()
            sendResult.store(transportBox.value.sendControl(Data([1])))
            sendFinished.signal()
        }
        guard sendStarted.wait(timeout: .now() + 2) == .success else {
            releaseDecision.signal()
            transport.close()
            return false
        }
        let admissionCompletedWithoutWaitingForCallback =
            sendFinished.wait(timeout: .now() + 0.1) == .success
        releaseDecision.signal()
        let pathChangeCompleted = pathChangeFinished.wait(timeout: .now() + 2) == .success
        let rejectedDuringRecovery = sendResult.load()?.isNotConnectedFailure == true
        let snapshot = transport.snapshot()
        transport.close()
        return admissionCompletedWithoutWaitingForCallback
            && pathChangeCompleted
            && rejectedDuringRecovery
            && engine.controlPayloads.isEmpty
            && snapshot.state == .recovering(attempt: 1)
            && snapshot.bufferedControlBytes == 0
    }

    private static func staleRelayAccountingContractPasses() -> Bool {
        staleRelayControlAccountingPasses() && staleRelayMediaAccountingPasses()
    }

    private static func controlFailureCloseGateContractPasses() -> Bool {
        controlBacklogCloseCallbackPasses() && synchronousControlFailureCloseCallbackPasses()
    }

    private static func failureTransitionOrderingContractPasses() -> Bool {
        preparedFailureRejectsConnectedCallback() && explicitCloseSupersedesFailureNotification()
    }

    private static func sdkTransmissionEpochGateContractPasses() -> Bool {
        queuedControlTransmissionEpochGatePasses()
            && queuedMediaTransmissionEpochGatePasses()
            && restartDelegateGenerationOwnershipPasses()
            && connectionAttemptTimeoutExhaustsRecoveryPasses()
            && staleCandidateStatisticsCannotReviveRecoveryContext()
            && consecutiveRestartAttemptsRejectDelayedCandidateStatistics()
            && transmissionEpochCannotWrap()
            && candidatePairTimeoutCanRearmAfterPreconnectionFire()
            && newerCandidateStatisticsPreventOlderPathRollback()
            && statisticsRequestSequenceCannotWrap()
            && freshSessionRecoveryDoesNotCountPeerReplacement()
            && freshSessionRecoveryBudgetCannotResetAcrossProfiles()
            && transportSequenceExhaustionFailsClosed()
    }

    private static func restartDelegateGenerationOwnershipPasses() -> Bool {
        let sessionIdentifier = "restart-delegate-generation-self-test"
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: sessionIdentifier,
            sharedSecret: Data(repeating: 0xc1, count: 32),
            bootstrapSecret: Data(repeating: 0xc2, count: 32),
            transcriptContext: Data(repeating: 0xc3, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "restart-delegate-generation-peer",
                sessionIdentifier: sessionIdentifier,
                forceRelay: false
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .direct)
        let initialGeneration = engine.currentPeerDelegateGeneration
        engine.emitDelegateConnection(
            .disconnected,
            source: .iceConnection,
            generation: initialGeneration
        )
        guard transport.snapshot().state == .recovering(attempt: 1),
              engine.restartCount == 1 else {
            transport.close()
            return false
        }
        let firstAttemptGeneration = engine.currentPeerDelegateGeneration
        for source in SelfTestPeerDelegateSource.allCases {
            engine.emitDelegateConnection(
                .disconnected,
                source: source,
                generation: initialGeneration
            )
            engine.emitDelegateConnection(
                .failed("stale delegate failure"),
                source: source,
                generation: initialGeneration
            )
        }
        guard transport.snapshot().state == .recovering(attempt: 1),
              engine.restartCount == 1,
              !engine.didClose else {
            transport.close()
            return false
        }

        engine.emitDelegateConnection(
            .disconnected,
            source: .peerConnection,
            generation: firstAttemptGeneration
        )
        guard transport.snapshot().state == .recovering(attempt: 2),
              engine.restartCount == 2 else {
            transport.close()
            return false
        }
        let secondAttemptGeneration = engine.currentPeerDelegateGeneration
        engine.emitDelegateConnection(
            .failed("stale first-attempt failure"),
            source: .iceConnection,
            generation: firstAttemptGeneration
        )
        guard transport.snapshot().state == .recovering(attempt: 2),
              !engine.didClose else {
            transport.close()
            return false
        }
        engine.emitDelegateConnection(
            .connected(path: .direct),
            source: .iceConnection,
            generation: secondAttemptGeneration
        )
        let passed = transport.snapshot().state == .connected(.direct)
            && engine.restartCount == 2
            && !engine.didClose
        transport.close()
        return passed
    }

    private static func consecutiveRestartAttemptsRejectDelayedCandidateStatistics() -> Bool {
        var state = WebRTCEngineTransmissionEpochState()
        state.markPeerConnected()
        guard let initial = state.selectPath(.direct)?.context else { return false }
        guard state.markPeerDisconnected() else { return false }

        guard !state.beginRestart() else { return false }
        let firstAttemptEpoch = state.epoch
        state.markPeerConnected()
        guard state.acceptsCandidateStatistics(expectedEpoch: firstAttemptEpoch) else { return false }

        guard !state.beginRestart() else { return false }
        let secondAttemptEpoch = state.epoch
        state.markPeerConnected()
        guard firstAttemptEpoch == initial.epoch + 2,
              secondAttemptEpoch == firstAttemptEpoch + 1,
              !state.acceptsCandidateStatistics(expectedEpoch: firstAttemptEpoch),
              state.acceptsCandidateStatistics(expectedEpoch: secondAttemptEpoch),
              let recovered = state.selectPath(.relay)?.context else {
            return false
        }
        return recovered.epoch == secondAttemptEpoch
    }

    private static func connectionAttemptTimeoutExhaustsRecoveryPasses() -> Bool {
        let sessionIdentifier = "restart-progress-timeout-self-test"
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: sessionIdentifier,
            sharedSecret: Data(repeating: 0xd1, count: 32),
            bootstrapSecret: Data(repeating: 0xd2, count: 32),
            transcriptContext: Data(repeating: 0xd3, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "restart-progress-timeout-peer",
                sessionIdentifier: sessionIdentifier,
                forceRelay: false
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .direct)
        let initialGeneration = engine.currentPeerDelegateGeneration
        engine.emitDelegateConnection(
            .disconnected,
            source: .iceConnection,
            generation: initialGeneration
        )
        guard transport.snapshot().state == .recovering(attempt: 1),
              engine.restartCount == 1 else {
            transport.close()
            return false
        }
        engine.fireRestartProgressTimeout()
        guard transport.snapshot().state == .recovering(attempt: 2),
              engine.restartCount == 2 else {
            transport.close()
            return false
        }
        engine.fireRestartProgressTimeout()
        let snapshot = transport.snapshot()
        guard case .failed(let reason) = snapshot.state else {
            transport.close()
            return false
        }
        return reason.contains("ICE recovery exhausted after 2 attempts")
            && engine.didClose
            && engine.restartCount == 2
    }

    private static func transmissionEpochCannotWrap() -> Bool {
        var state = WebRTCEngineTransmissionEpochState(
            epoch: UInt64.max,
            peerIsConnected: true,
            activePath: .direct
        )
        guard let staleContext = state.currentContext,
              state.markPeerDisconnected(),
              state.isExhausted,
              state.epoch == UInt64.max,
              state.currentContext == nil,
              !state.acceptsCandidateStatistics,
              !state.acceptsCandidateStatistics(expectedEpoch: UInt64.max),
              !state.acceptsSend(expectedContext: staleContext) else {
            return false
        }
        state.markPeerConnected()
        return state.selectPath(.direct) == nil
            && !state.beginRestart()
            && state.epoch == UInt64.max
    }

    private static func candidatePairTimeoutCanRearmAfterPreconnectionFire() -> Bool {
        var state = WebRTCCandidatePairResolutionTimeoutState()
        guard let cancelledToken = state.scheduleIfNeeded() else { return false }
        state.cancel()
        guard let activeToken = state.scheduleIfNeeded(),
              state.fire(
                  token: cancelledToken,
                  peerIsConnected: true,
                  selectedPath: .unknown
              ) == nil,
              state.isScheduled,
              state.fire(
                  token: activeToken,
                  peerIsConnected: true,
                  selectedPath: .unknown
              ) == true,
              !state.isScheduled,
              let preconnectionToken = state.scheduleIfNeeded(),
              state.fire(
                  token: preconnectionToken,
                  peerIsConnected: false,
                  selectedPath: .unknown
              ) == false else {
            return false
        }
        return !state.isScheduled
    }

    private static func newerCandidateStatisticsPreventOlderPathRollback() -> Bool {
        var state = WebRTCStatisticsRequestOrderingState()
        guard let oldPairRequest = state.beginRequest(),
              let freshPairRequest = state.beginRequest(),
              state.acceptsResponse(sequence: freshPairRequest),
              !state.acceptsResponse(sequence: oldPairRequest) else {
            return false
        }
        guard let subsequentRequest = state.beginRequest() else { return false }
        return state.acceptsResponse(sequence: subsequentRequest)
    }

    private static func statisticsRequestSequenceCannotWrap() -> Bool {
        var state = WebRTCStatisticsRequestOrderingState(nextSequence: UInt64.max - 1)
        return state.beginRequest() == UInt64.max
            && state.beginRequest() == nil
            && state.nextSequence == UInt64.max
    }

    private static func freshSessionRecoveryDoesNotCountPeerReplacement() -> Bool {
        let sessionIdentifier = "fresh-session-disposition-self-test"
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: sessionIdentifier,
            sharedSecret: Data(repeating: 0xf1, count: 32),
            bootstrapSecret: Data(repeating: 0xf2, count: 32),
            transcriptContext: Data(repeating: 0xf3, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(
            remoteCipher: ciphers.device,
            recoveryDisposition: .requiresFreshSession("fresh signaling session required")
        )
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        var recoveryAttempts: [Int] = []
        transport.onFreshSessionRecoveryRequired = { recoveryAttempts.append($0) }
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "fresh-session-disposition-peer",
                sessionIdentifier: sessionIdentifier,
                forceRelay: false
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .direct)
        engine.disconnect()
        let snapshot = transport.snapshot()
        let passed = recoveryAttempts == [1]
            && engine.restartCount == 1
            && snapshot.iceRestartCount == 0
            && snapshot.state == .recovering(attempt: 1)
            && transport.sendControl(Data([1])).isNotConnectedFailure
        transport.close()
        return passed
    }

    private static func freshSessionRecoveryBudgetCannotResetAcrossProfiles() -> Bool {
        var budget = FreshSessionRecoveryBudget(
            policy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        guard budget.nextAttempt() == 1,
              budget.nextAttempt() == 2,
              budget.nextAttempt() == nil,
              budget.attempt == 2 else { return false }
        budget.reset()
        return budget.nextAttempt() == 1
    }

    private static func transportSequenceExhaustionFailsClosed() -> Bool {
        guard let controlCiphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "control-sequence-exhaustion-self-test",
            sharedSecret: Data(repeating: 0xa4, count: 32),
            bootstrapSecret: Data(repeating: 0xa5, count: 32),
            transcriptContext: Data(repeating: 0xa6, count: 32)
        ), let mediaCiphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "media-sequence-exhaustion-self-test",
            sharedSecret: Data(repeating: 0xb4, count: 32),
            bootstrapSecret: Data(repeating: 0xb5, count: 32),
            transcriptContext: Data(repeating: 0xb6, count: 32)
        ), let pipelineCiphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "pipeline-sequence-exhaustion-self-test",
            sharedSecret: Data(repeating: 0xc4, count: 32),
            bootstrapSecret: Data(repeating: 0xc5, count: 32),
            transcriptContext: Data(repeating: 0xc6, count: 32)
        ), let frame = encodedFrame(
            payloads: [Data([1])],
            captureTimestamp: 1,
            isKeyframe: true
        ) else { return false }

        let controlEngine = SelfTestWebRTCEngine(remoteCipher: controlCiphers.device)
        let controlTransport = WebRTCInternetTransport(
            engine: controlEngine,
            packetCipher: controlCiphers.host,
            initialControlTransmissionIdentifier: UInt64.max
        )
        let mediaEngine = SelfTestWebRTCEngine(remoteCipher: mediaCiphers.device)
        let mediaTransport = WebRTCInternetTransport(
            engine: mediaEngine,
            packetCipher: mediaCiphers.host,
            initialMediaTransmissionIdentifier: UInt64.max
        )
        let pipelineEngine = SelfTestWebRTCEngine(remoteCipher: pipelineCiphers.device)
        let pipelineTransport = WebRTCInternetTransport(
            engine: pipelineEngine,
            packetCipher: pipelineCiphers.host,
            initialPipelineGeneration: UInt64.max
        )

        do {
            try controlTransport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "control-sequence-exhaustion-peer",
                sessionIdentifier: "control-sequence-exhaustion-self-test",
                forceRelay: false
            ))
            try mediaTransport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "media-sequence-exhaustion-peer",
                sessionIdentifier: "media-sequence-exhaustion-self-test",
                forceRelay: false
            ))
            try pipelineTransport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "pipeline-sequence-exhaustion-peer",
                sessionIdentifier: "pipeline-sequence-exhaustion-self-test",
                forceRelay: false
            ))
        } catch {
            controlTransport.close()
            mediaTransport.close()
            pipelineTransport.close()
            return false
        }
        controlEngine.connect(path: .direct)
        mediaEngine.connect(path: .direct)
        pipelineEngine.connect(path: .direct)

        let controlRejected = controlTransport.sendControl(Data([1])).isSequenceExhaustedFailure
        _ = mediaTransport.sendMedia(frame)
        pipelineEngine.disconnect()
        pipelineEngine.connect(path: .direct)

        let controlFailed = controlTransport.snapshot().state.isFailed
            && controlEngine.didClose
            && controlEngine.controlPayloads.isEmpty
        let mediaFailed = mediaTransport.snapshot().state.isFailed
            && mediaEngine.didClose
            && mediaEngine.mediaPayloads.isEmpty
        let pipelineFailed = pipelineTransport.snapshot().state.isFailed
            && pipelineEngine.didClose
        controlTransport.close()
        mediaTransport.close()
        pipelineTransport.close()
        return controlRejected && controlFailed && mediaFailed && pipelineFailed
    }

    private static func staleCandidateStatisticsCannotReviveRecoveryContext() -> Bool {
        var state = WebRTCEngineTransmissionEpochState()
        state.markPeerConnected()
        guard let initial = state.selectPath(.direct)?.context else { return false }
        let invalidated = state.markPeerDisconnected()
        let staleUpdate = state.selectPath(.relay)
        let staleSendRejected = !state.acceptsSend(expectedContext: initial)
        guard invalidated,
              !state.acceptsCandidateStatistics,
              staleUpdate == nil,
              staleSendRejected else { return false }

        state.markPeerConnected()
        guard let recovered = state.selectPath(.relay)?.context else { return false }
        return recovered != initial
            && recovered.epoch == initial.epoch + 1
            && state.acceptsCandidateStatistics
            && state.acceptsSend(expectedContext: recovered)
    }

    private static func queuedControlTransmissionEpochGatePasses() -> Bool {
        let sessionIdentifier = "queued-control-epoch-self-test"
        guard let engine = try? QueuedSelfTestWebRTCEngine(sessionIdentifier: sessionIdentifier) else {
            return false
        }
        var triggeredDisconnect = false
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            beforeControlSend: {
                guard !triggeredDisconnect else { return }
                triggeredDisconnect = true
                _ = engine.enqueueDisconnectAndWaitForInvalidation()
            }
        )
        do {
            try transport.start(configuration: relaySelfTestConfiguration(
                sessionIdentifier: sessionIdentifier
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .relay)
        let accepted = transport.sendControl(Data([1])).isSuccess
        let completed = engine.waitForEventCount(2)
        let snapshot = transport.snapshot()
        let passed = accepted
            && completed
            && engine.events == ["D", "R"]
            && engine.sentPlaintext.isEmpty
            && snapshot.state == .recovering(attempt: 1)
            && snapshot.bufferedControlBytes == 0
            && snapshot.relayBytesReserved == 0
            && snapshot.relayBytesSent == 0
        transport.close()
        return passed
    }

    private static func queuedMediaTransmissionEpochGatePasses() -> Bool {
        let sessionIdentifier = "queued-media-epoch-self-test"
        guard let engine = try? QueuedSelfTestWebRTCEngine(sessionIdentifier: sessionIdentifier),
              let frame = encodedFrame(
                payloads: [Data([1])],
                captureTimestamp: 1,
                isKeyframe: true
              ) else { return false }
        var triggeredDisconnect = false
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            beforeMediaRecordSend: {
                guard !triggeredDisconnect else { return }
                triggeredDisconnect = true
                _ = engine.enqueueDisconnectAndWaitForInvalidation()
            }
        )
        do {
            try transport.start(configuration: relaySelfTestConfiguration(
                sessionIdentifier: sessionIdentifier
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .relay)
        let accepted = transport.sendMedia(frame).isSuccess
        let completed = engine.waitForEventCount(2)
        let snapshot = transport.snapshot()
        let passed = accepted
            && completed
            && engine.events == ["D", "R"]
            && engine.sentPlaintext.isEmpty
            && snapshot.state == .recovering(attempt: 1)
            && !snapshot.hasPendingMediaFrame
            && snapshot.relayBytesReserved == 0
            && snapshot.relayBytesSent == 0
        transport.close()
        return passed
    }

    private static func recoveryExhaustionFailClosedContractPasses() -> Bool {
        let sessionIdentifier = "recovery-exhaustion-self-test"
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: sessionIdentifier,
            sharedSecret: Data(repeating: 0xa1, count: 32),
            bootstrapSecret: Data(repeating: 0xa2, count: 32),
            transcriptContext: Data(repeating: 0xa3, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        var receivedControl: [Data] = []
        var receivedMedia: [Data] = []
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        transport.onControlReceived = { receivedControl.append($0) }
        transport.onMediaReceived = { receivedMedia.append($0) }
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "recovery-exhaustion-peer",
                sessionIdentifier: sessionIdentifier,
                forceRelay: false
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .direct)
        guard let lateControl = engine.makeInboundRecord(Data([1]), channel: .control),
              let lateMedia = engine.makeInboundRecord(Data([2]), channel: .media) else {
            transport.close()
            return false
        }

        engine.disconnect()
        guard transport.snapshot().state == .recovering(attempt: 1),
              engine.restartCount == 1 else {
            transport.close()
            return false
        }
        engine.connecting()
        guard transport.snapshot().state == .recovering(attempt: 1) else {
            transport.close()
            return false
        }
        engine.disconnect()
        guard transport.snapshot().state == .recovering(attempt: 2),
              engine.restartCount == 2 else {
            transport.close()
            return false
        }
        engine.connecting()
        guard transport.snapshot().state == .recovering(attempt: 2) else {
            transport.close()
            return false
        }
        engine.disconnect()
        let failedSnapshot = transport.snapshot()
        engine.connect(path: .direct)
        engine.receive(lateControl, channel: .control)
        engine.receive(lateMedia, channel: .media)
        let controlRejected = transport.sendControl(Data([3])).isNotConnectedFailure

        guard case .failed(let reason) = failedSnapshot.state else { return false }
        return reason.contains("ICE recovery exhausted after 2 attempts")
            && engine.didClose
            && engine.restartCount == 2
            && controlRejected
            && receivedControl.isEmpty
            && receivedMedia.isEmpty
            && engine.controlPayloads.isEmpty
            && engine.mediaPayloads.isEmpty
    }

    private static func preparedFailureRejectsConnectedCallback() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "failure-revival-self-test",
            sharedSecret: Data(repeating: 0xe1, count: 32),
            bootstrapSecret: Data(repeating: 0xe2, count: 32),
            transcriptContext: Data(repeating: 0xe3, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        var transport: WebRTCInternetTransport?
        var resurrectionResult: Result<Void, InternetTransportError>?
        var states: [InternetTransportState] = []
        transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 8,
                maximumBufferedControlBytes: 1,
                maximumMediaFrameBytes: 8,
                maximumRelayBytesPerSession: 100
            ),
            beforeFailureSideEffects: {
                engine.connecting()
                engine.connect(path: .direct)
                resurrectionResult = transport?.sendControl(Data([9]))
            }
        )
        transport?.onStateChanged = { states.append($0) }
        do {
            try transport?.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "failure-revival-peer",
                sessionIdentifier: "failure-revival-self-test",
                forceRelay: false
            ))
        } catch {
            transport?.close()
            return false
        }
        engine.connect(path: .direct)
        guard transport?.sendControl(Data([1])).isSuccess == true,
              transport?.sendControl(Data([2])).isControlBacklogFailure == true,
              resurrectionResult?.isNotConnectedFailure == true,
              engine.controlPayloads == [Data([1])],
              states.count == 3 else { return false }
        guard states[0] == .connecting,
              states[1] == .connected(.direct) else { return false }
        guard case .failed = states[2] else { return false }
        if case .failed = transport?.snapshot().state { return true }
        return false
    }

    private static func explicitCloseSupersedesFailureNotification() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "failure-close-supersession-self-test",
            sharedSecret: Data(repeating: 0xf1, count: 32),
            bootstrapSecret: Data(repeating: 0xf2, count: 32),
            transcriptContext: Data(repeating: 0xf3, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        var transport: WebRTCInternetTransport?
        transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 8,
                maximumBufferedControlBytes: 1,
                maximumMediaFrameBytes: 8,
                maximumRelayBytesPerSession: 100
            ),
            beforeFailureSideEffects: { transport?.close() }
        )
        var states: [InternetTransportState] = []
        var reportedError: InternetTransportError?
        transport?.onStateChanged = { states.append($0) }
        transport?.onError = { reportedError = $0 }
        do {
            try transport?.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "failure-close-supersession-peer",
                sessionIdentifier: "failure-close-supersession-self-test",
                forceRelay: false
            ))
        } catch {
            transport?.close()
            return false
        }
        engine.connect(path: .direct)
        // Ignore the normal connecting/connected notifications emitted before the failure window.
        states.removeAll()
        guard transport?.sendControl(Data([1])).isSuccess == true,
              transport?.sendControl(Data([2])).isControlBacklogFailure == true else { return false }
        return transport?.snapshot().state == .closed
            && states == [.closed]
            && reportedError == nil
    }

    private static func controlBacklogCloseCallbackPasses() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "control-backlog-close-self-test",
            sharedSecret: Data(repeating: 0xc1, count: 32),
            bootstrapSecret: Data(repeating: 0xc2, count: 32),
            transcriptContext: Data(repeating: 0xc3, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(
            remoteCipher: ciphers.device,
            emitClosedSynchronouslyOnClose: true
        )
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 8,
                maximumBufferedControlBytes: 1,
                maximumMediaFrameBytes: 8,
                maximumRelayBytesPerSession: 100
            )
        )
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "control-backlog-close-peer",
                sessionIdentifier: "control-backlog-close-self-test",
                forceRelay: false
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .direct)
        guard transport.sendControl(Data([1])).isSuccess else {
            transport.close()
            return false
        }
        let finished = DispatchSemaphore(value: 0)
        let result = LockedSelfTestTransportResult()
        let transportBox = UncheckedSendableBox(transport)
        DispatchQueue.global().async {
            result.store(transportBox.value.sendControl(Data([2])))
            finished.signal()
        }
        guard finished.wait(timeout: .now() + 2) == .success else { return false }
        guard result.load()?.isControlBacklogFailure == true,
              engine.didClose else { return false }
        if case .failed = transport.snapshot().state { return true }
        return false
    }

    private static func synchronousControlFailureCloseCallbackPasses() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "control-sync-failure-self-test",
            sharedSecret: Data(repeating: 0xd1, count: 32),
            bootstrapSecret: Data(repeating: 0xd2, count: 32),
            transcriptContext: Data(repeating: 0xd3, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(
            remoteCipher: ciphers.device,
            emitClosedSynchronouslyOnClose: true,
            synchronousSendFailure: SelfTestSendError.failed
        )
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: ciphers.host)
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "control-sync-failure-peer",
                sessionIdentifier: "control-sync-failure-self-test",
                forceRelay: false
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .direct)
        let finished = DispatchSemaphore(value: 0)
        let result = LockedSelfTestTransportResult()
        let transportBox = UncheckedSendableBox(transport)
        DispatchQueue.global().async {
            result.store(transportBox.value.sendControl(Data([1])))
            finished.signal()
        }
        guard finished.wait(timeout: .now() + 2) == .success,
              result.load()?.isSuccess == true,
              engine.didClose else { return false }
        if case .failed = transport.snapshot().state { return true }
        return false
    }

    private static func staleRelayControlAccountingPasses() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "stale-control-accounting-self-test",
            sharedSecret: Data(repeating: 0xa1, count: 32),
            bootstrapSecret: Data(repeating: 0xa2, count: 32),
            transcriptContext: Data(repeating: 0xa3, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let encryptedRecordBytes = InternetMediaRecordContract.encryptedRecordBytes(forPlaintextBytes: 1)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 8,
                maximumBufferedControlBytes: 8,
                maximumMediaFrameBytes: 8,
                maximumRelayBytesPerSession: encryptedRecordBytes
            )
        )
        do {
            try transport.start(configuration: relaySelfTestConfiguration(
                sessionIdentifier: "stale-control-accounting-self-test"
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .relay)
        let accepted = transport.sendControl(Data([1])).isSuccess
        forcePathRestart(engine)
        let reservationSurvived = transport.snapshot().relayBytesReserved == encryptedRecordBytes
        engine.completeAllSends()
        let snapshot = transport.snapshot()
        transport.close()
        return accepted
            && reservationSurvived
            && engine.controlPayloads == [Data([1])]
            && snapshot.relayBytesReserved == 0
            && snapshot.relayBytesSent == encryptedRecordBytes
            && snapshot.controlBytesSent == 1
    }

    private static func staleRelayMediaAccountingPasses() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "stale-media-accounting-self-test",
            sharedSecret: Data(repeating: 0xb1, count: 32),
            bootstrapSecret: Data(repeating: 0xb2, count: 32),
            transcriptContext: Data(repeating: 0xb3, count: 32)
        ), let frame = encodedFrame(
            payloads: [Data([1])],
            captureTimestamp: 1,
            isKeyframe: true
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 8,
                maximumBufferedControlBytes: 8,
                maximumMediaFrameBytes: frame.mediaPayloadBytes,
                maximumRelayBytesPerSession: frame.totalEncryptedRecordBytes
            )
        )
        do {
            try transport.start(configuration: relaySelfTestConfiguration(
                sessionIdentifier: "stale-media-accounting-self-test"
            ))
        } catch {
            transport.close()
            return false
        }
        engine.connect(path: .relay)
        let accepted = transport.sendMedia(frame).isSuccess
        forcePathRestart(engine)
        let reservationSurvived = transport.snapshot().relayBytesReserved == frame.totalEncryptedRecordBytes
        engine.completeAllSends()
        let snapshot = transport.snapshot()
        transport.close()
        return accepted
            && reservationSurvived
            && engine.mediaPayloads == frame.records
            && snapshot.relayBytesReserved == 0
            && snapshot.relayBytesSent == frame.totalEncryptedRecordBytes
            && snapshot.mediaBytesSent == UInt64(frame.records[0].count)
    }

    private static func relaySelfTestConfiguration(
        sessionIdentifier: String
    ) -> WebRTCTransportConfiguration {
        WebRTCTransportConfiguration(
            iceServers: [WebRTCICEServer(
                urls: [URL(string: "turns:relay.example.test:5349")!],
                username: "short-lived-user",
                credential: "short-lived-secret"
            )],
            peerIdentity: "relay-accounting-peer",
            sessionIdentifier: sessionIdentifier,
            forceRelay: true
        )
    }

    private static func forcePathRestart(_ engine: SelfTestWebRTCEngine) {
        engine.changePath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))
        engine.changePath(InternetNetworkPath(
            interface: .cellular,
            isSatisfied: true,
            fingerprint: "cellular-b"
        ))
    }

    private static func encodedFrame(
        payloads: [Data],
        captureTimestamp: UInt64,
        isKeyframe: Bool,
        frameID: UInt64 = 1
    ) -> EncodedInternetFrame? {
        do {
            let records = try payloads.enumerated().map { index, payload in
                try mediaRecord(
                    payload: payload,
                    captureTimestamp: captureTimestamp,
                    isKeyframe: isKeyframe,
                    frameID: frameID,
                    fragmentIndex: index,
                    fragmentCount: payloads.count
                )
            }
            return try EncodedInternetFrame(
                records: records,
                mediaPayloadBytes: payloads.reduce(0) { $0 + $1.count },
                captureTimestamp: captureTimestamp,
                isKeyframe: isKeyframe
            )
        } catch {
            return nil
        }
    }

    private static func mediaRecord(
        payload: Data,
        captureTimestamp: UInt64,
        isKeyframe: Bool,
        frameID: UInt64,
        fragmentIndex: Int,
        fragmentCount: Int
    ) throws -> Data {
        var header = VSMediaPacketHeader()
        header.streamID = 1
        header.sessionEpoch = 1
        header.configEpoch = 1
        header.frameID = frameID
        header.fragmentIndex = UInt32(fragmentIndex)
        header.fragmentCount = UInt32(fragmentCount)
        header.captureTimestampNs = captureTimestamp
        header.keyframe = isKeyframe
        header.codec = .hevc
        return try ProtocolV1MediaPacketCodec.encode(header: header, payload: payload)
    }

    private static func productionRejectsMissingSignaling() -> Bool {
        let engine = ProductionWebRTCEngine()
        defer { engine.close() }
        do {
            try engine.start(
                configuration: WebRTCTransportConfiguration(
                    iceServers: [WebRTCICEServer(urls: [URL(string: "stun:127.0.0.1:9")!])],
                    peerIdentity: "missing-signaling",
                    sessionIdentifier: "missing-signaling-session",
                    forceRelay: false
                ),
                channels: InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
            )
            return false
        } catch WebRTCSignalingError.missingConfiguration {
            return true
        } catch {
            return false
        }
    }

    private static func controlBacklogFailsClosed() -> Bool {
        guard let ciphers = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "backlog-session",
            sharedSecret: Data(repeating: 0x61, count: 32),
            bootstrapSecret: Data(repeating: 0x62, count: 32),
            transcriptContext: Data(repeating: 0x63, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: ciphers.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: ciphers.host,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 8,
                maximumBufferedControlBytes: 1,
                maximumMediaFrameBytes: 8,
                maximumRelayBytesPerSession: 8
            )
        )
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "backlog-peer",
                sessionIdentifier: "backlog-session",
                forceRelay: false
            ))
        } catch {
            return false
        }
        engine.connect(path: .direct)
        guard transport.sendControl(Data([1])).isSuccess else { return false }
        guard transport.sendControl(Data([2])).isControlBacklogFailure else { return false }
        if case .failed = transport.snapshot().state { return true }
        return false
    }

    private static func finalReviewContractsPass() -> Bool {
        controlEntryLimitPasses()
            && startupCallbackOrderingPasses()
            && closeBeforeStartIsTerminalPasses()
            && startupCloseBeforeEngineStartPasses()
            && repeatedStartIsRejectedPasses()
            && preconnectionDisconnectRecoversPasses()
            && recoveryCallbackClosePasses()
            && idempotentClosePasses()
            && mediaAccountingOverflowFailsClosedPasses()
            && recoveringPathDoesNotConsumeBudget()
            && exhaustedPathActionFailsClosed()
            && relayReservationOverflowFailsClosed()
    }

    private static func closeBeforeStartIsTerminalPasses() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "close-before-start-self-test",
            sharedSecret: Data(repeating: 0x38, count: 32),
            bootstrapSecret: Data(repeating: 0x39, count: 32),
            transcriptContext: Data(repeating: 0x3a, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: pair.host)
        transport.close()
        guard !startSelfTestTransport(
            transport,
            sessionIdentifier: "close-before-start-self-test"
        ) else { return false }
        return engine.startCount == 0
            && engine.closeCount == 1
            && transport.snapshot().state == .closed
    }

    private static func startupCloseBeforeEngineStartPasses() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "startup-close-self-test",
            sharedSecret: Data(repeating: 0x41, count: 32),
            bootstrapSecret: Data(repeating: 0x42, count: 32),
            transcriptContext: Data(repeating: 0x43, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        var transport: WebRTCInternetTransport!
        transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: pair.host,
            beforeEngineStart: { transport.close() }
        )
        guard !startSelfTestTransport(transport, sessionIdentifier: "startup-close-self-test") else {
            return false
        }
        return engine.channelConfigurations.isEmpty
            && engine.startCount == 0
            && engine.closeCount == 1
            && transport.snapshot().state == .closed
    }

    private static func repeatedStartIsRejectedPasses() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "repeated-start-self-test",
            sharedSecret: Data(repeating: 0x3b, count: 32),
            bootstrapSecret: Data(repeating: 0x3c, count: 32),
            transcriptContext: Data(repeating: 0x3d, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: pair.host)
        guard startSelfTestTransport(transport, sessionIdentifier: "repeated-start-self-test"),
              !startSelfTestTransport(transport, sessionIdentifier: "repeated-start-self-test") else {
            return false
        }
        return engine.startCount == 1 && transport.snapshot().state == .connecting
    }

    private static func preconnectionDisconnectRecoversPasses() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "preconnection-disconnect-self-test",
            sharedSecret: Data(repeating: 0x44, count: 32),
            bootstrapSecret: Data(repeating: 0x45, count: 32),
            transcriptContext: Data(repeating: 0x46, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: pair.host,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 1)
        )
        guard startSelfTestTransport(
            transport,
            sessionIdentifier: "preconnection-disconnect-self-test"
        ) else { return false }
        engine.disconnect()
        return transport.snapshot().state == .recovering(attempt: 1)
            && engine.restartCount == 1
    }

    private static func recoveryCallbackClosePasses() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "recovery-close-self-test",
            sharedSecret: Data(repeating: 0x47, count: 32),
            bootstrapSecret: Data(repeating: 0x48, count: 32),
            transcriptContext: Data(repeating: 0x49, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: pair.host)
        guard startSelfTestTransport(transport, sessionIdentifier: "recovery-close-self-test") else {
            return false
        }
        engine.connect(path: .direct)
        transport.onStateChanged = { state in
            if case .recovering = state { transport.close() }
        }
        engine.disconnect()
        return transport.snapshot().state == .closed
            && engine.restartCount == 0
            && engine.closeCount == 1
    }

    private static func idempotentClosePasses() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "idempotent-close-self-test",
            sharedSecret: Data(repeating: 0x4a, count: 32),
            bootstrapSecret: Data(repeating: 0x4b, count: 32),
            transcriptContext: Data(repeating: 0x4c, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: pair.host)
        var closedCount = 0
        transport.onStateChanged = { state in
            guard state == .closed else { return }
            closedCount += 1
            transport.close()
        }
        guard startSelfTestTransport(transport, sessionIdentifier: "idempotent-close-self-test") else {
            return false
        }
        transport.close()
        transport.close()
        return closedCount == 1 && engine.closeCount == 1
    }

    private static func mediaAccountingOverflowFailsClosedPasses() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "media-accounting-overflow-self-test",
            sharedSecret: Data(repeating: 0x4d, count: 32),
            bootstrapSecret: Data(repeating: 0x4e, count: 32),
            transcriptContext: Data(repeating: 0x4f, count: 32)
        ), let first = encodedFrame(
            payloads: [Data([1])],
            captureTimestamp: 1,
            isKeyframe: true
        ), let pending = encodedFrame(
            payloads: [Data([2])],
            captureTimestamp: 2,
            isKeyframe: true
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: pair.host,
            initialMediaBytesSent: UInt64.max
        )
        guard startSelfTestTransport(
            transport,
            sessionIdentifier: "media-accounting-overflow-self-test"
        ) else { return false }
        engine.connect(path: .direct)
        guard transport.sendMedia(first).isSuccess,
              transport.sendMedia(pending).isSuccess else { return false }
        engine.completeAllSends()
        guard case .failed = transport.snapshot().state else { return false }
        return !transport.snapshot().mediaInFlight
            && !transport.snapshot().hasPendingMediaFrame
            && transport.snapshot().relayBytesReserved == 0
            && engine.didClose
    }

    private static func controlEntryLimitPasses() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "control-entry-limit-self-test",
            sharedSecret: Data(repeating: 0x31, count: 32),
            bootstrapSecret: Data(repeating: 0x32, count: 32),
            transcriptContext: Data(repeating: 0x33, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: pair.host,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 8,
                maximumBufferedControlBytes: 64,
                maximumBufferedControlMessages: 2,
                maximumMediaFrameBytes: 8,
                maximumRelayBytesPerSession: 100
            )
        )
        guard startSelfTestTransport(transport, sessionIdentifier: "control-entry-limit-self-test") else {
            return false
        }
        engine.connect(path: .direct)
        return transport.sendControl(Data([1])).isSuccess
            && transport.sendControl(Data([2])).isSuccess
            && transport.snapshot().bufferedControlMessages == 2
            && transport.sendControl(Data([3])).isControlBacklogFailure
            && engine.didClose
    }

    private static func startupCallbackOrderingPasses() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "startup-ordering-self-test",
            sharedSecret: Data(repeating: 0x41, count: 32),
            bootstrapSecret: Data(repeating: 0x42, count: 32),
            transcriptContext: Data(repeating: 0x43, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: pair.host)
        transport.onStateChanged = { state in
            if state == .connecting { transport.close() }
        }
        guard startSelfTestTransport(transport, sessionIdentifier: "startup-ordering-self-test") else {
            return false
        }
        return engine.channelConfigurations.count == InternetTransportChannel.allCases.count
            && engine.didClose
            && !engine.startedAfterClose
            && transport.snapshot().state == .closed
    }

    private static func recoveringPathDoesNotConsumeBudget() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "recovering-path-self-test",
            sharedSecret: Data(repeating: 0x51, count: 32),
            bootstrapSecret: Data(repeating: 0x52, count: 32),
            transcriptContext: Data(repeating: 0x53, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: pair.host,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        guard startSelfTestTransport(transport, sessionIdentifier: "recovering-path-self-test") else {
            return false
        }
        engine.connect(path: .direct)
        engine.changePath(.init(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        engine.disconnect()
        engine.changePath(.init(interface: .cellular, isSatisfied: true, fingerprint: "cell-b"))
        engine.changePath(.init(interface: .wiredEthernet, isSatisfied: true, fingerprint: "ethernet-c"))
        return transport.snapshot().state == .recovering(attempt: 1) && engine.restartCount == 1
    }

    private static func exhaustedPathActionFailsClosed() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "exhausted-path-self-test",
            sharedSecret: Data(repeating: 0x61, count: 32),
            bootstrapSecret: Data(repeating: 0x62, count: 32),
            transcriptContext: Data(repeating: 0x63, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: pair.host,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 0)
        )
        guard startSelfTestTransport(transport, sessionIdentifier: "exhausted-path-self-test") else {
            return false
        }
        engine.connect(path: .direct)
        engine.changePath(.init(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        engine.changePath(.init(interface: .wiredEthernet, isSatisfied: true, fingerprint: "ethernet-b"))
        if case .failed = transport.snapshot().state { return engine.didClose && engine.restartCount == 0 }
        return false
    }

    private static func relayReservationOverflowFailsClosed() -> Bool {
        guard let pair = try? PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "relay-overflow-self-test",
            sharedSecret: Data(repeating: 0x71, count: 32),
            bootstrapSecret: Data(repeating: 0x72, count: 32),
            transcriptContext: Data(repeating: 0x73, count: 32)
        ) else { return false }
        let engine = SelfTestWebRTCEngine(remoteCipher: pair.device)
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: pair.host,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 8,
                maximumBufferedControlBytes: 16,
                maximumMediaFrameBytes: 8,
                maximumRelayBytesPerSession: UInt64.max
            ),
            initialRelayBytesSent: UInt64.max - 1,
            initialRelayBytesReserved: 1
        )
        guard startSelfTestTransport(transport, sessionIdentifier: "relay-overflow-self-test") else {
            return false
        }
        engine.connect(path: .relay)
        return transport.sendControl(Data([1])).isRelayBudgetFailure
            && engine.controlPayloads.isEmpty
    }

    private static func startSelfTestTransport(
        _ transport: WebRTCInternetTransport,
        sessionIdentifier: String
    ) -> Bool {
        do {
            try transport.start(configuration: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test:3478")!])],
                peerIdentity: "\(sessionIdentifier)-peer",
                sessionIdentifier: sessionIdentifier,
                forceRelay: false
            ))
            return true
        } catch {
            return false
        }
    }
}

private final class SelfTestWebRTCEngine: WebRTCEnginePort {
    private let remoteCipher: PlatformSessionPacketCipher
    private let recoveryDisposition: WebRTCEngineRecoveryDisposition
    private var callbacks: WebRTCEngineCallbacks?
    private var peerDelegateGenerationState = WebRTCPeerConnectionDelegateGenerationState()
    private let emitClosedSynchronouslyOnClose: Bool
    private let synchronousSendFailure: Error?
    private var pendingCompletions: [(Result<Void, Error>) -> Void] = []
    private var transmissionEpoch: UInt64 = 0
    private var activeTransmissionPath: InternetPathKind?
    private var lastNetworkPathFingerprint: String?
    private(set) var channelConfigurations: [WebRTCDataChannelConfiguration] = []
    private(set) var controlPayloads: [Data] = []
    private(set) var mediaPayloads: [Data] = []
    private(set) var restartCount = 0
    private(set) var didClose = false
    private(set) var startedAfterClose = false
    private(set) var closeCount = 0
    private(set) var startCount = 0

    var currentPeerDelegateGeneration: UInt64 {
        peerDelegateGenerationState.currentGeneration
    }

    init(
        remoteCipher: PlatformSessionPacketCipher,
        emitClosedSynchronouslyOnClose: Bool = false,
        synchronousSendFailure: Error? = nil,
        recoveryDisposition: WebRTCEngineRecoveryDisposition = .peerReplacementStarted
    ) {
        self.remoteCipher = remoteCipher
        self.emitClosedSynchronouslyOnClose = emitClosedSynchronouslyOnClose
        self.synchronousSendFailure = synchronousSendFailure
        self.recoveryDisposition = recoveryDisposition
    }

    func install(callbacks: WebRTCEngineCallbacks) {
        self.callbacks = callbacks
    }

    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws {
        startCount += 1
        startedAfterClose = didClose
        peerDelegateGenerationState.reset()
        channelConfigurations = channels
    }

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        expectedContext: WebRTCEngineTransmissionContext,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard expectedContext == currentTransmissionContext else {
            completion(.failure(SelfTestSendError.staleTransmissionContext))
            return
        }
        guard let plaintext = remoteCipher.open(payload, channel: channel) else {
            completion(.failure(PlatformSecurityError.invalidInput("Self-test record authentication failed.")))
            return
        }
        if let synchronousSendFailure {
            completion(.failure(synchronousSendFailure))
            return
        }
        if channel == .control {
            controlPayloads.append(plaintext)
        } else {
            mediaPayloads.append(plaintext)
        }
        pendingCompletions.append(completion)
    }

    func restartICE() -> WebRTCEngineRecoveryDisposition {
        invalidateTransmissionContext()
        restartCount += 1
        guard recoveryDisposition == .peerReplacementStarted else {
            return recoveryDisposition
        }
        guard peerDelegateGenerationState.beginRestart() != nil else {
            callbacks?.connectionStateChanged(.failed("Self-test peer delegate generation exhausted."))
            return .failed("Self-test peer delegate generation exhausted.")
        }
        callbacks?.connectionStateChanged(.connecting)
        return .peerReplacementStarted
    }
    func requestMediaKeyframe() {}
    func close() {
        invalidateTransmissionContext()
        closeCount += 1
        didClose = true
        if emitClosedSynchronouslyOnClose {
            callbacks?.connectionStateChanged(.closed)
        }
        remoteCipher.close()
    }

    func receive(_ record: Data, channel: InternetTransportChannel) {
        callbacks?.messageReceived(record, channel)
    }

    func makeInboundRecord(_ payload: Data, channel: InternetTransportChannel) -> Data? {
        try? remoteCipher.seal(payload, channel: channel)
    }

    func connect(path: InternetPathKind) {
        activeTransmissionPath = path
        callbacks?.transmissionContextChanged(currentTransmissionContext)
        callbacks?.connectionStateChanged(.connected(path: path))
    }

    func connecting() {
        invalidateTransmissionContext()
        callbacks?.connectionStateChanged(.connecting)
    }

    func disconnect() {
        invalidateTransmissionContext()
        callbacks?.connectionStateChanged(.disconnected)
    }

    func emitDelegateConnection(
        _ state: WebRTCEngineConnectionState,
        source: SelfTestPeerDelegateSource,
        generation: UInt64
    ) {
        _ = source
        guard peerDelegateGenerationState.accepts(delegateGeneration: generation) else { return }
        switch state {
        case .connected(let path):
            connect(path: path)
        case .connecting:
            connecting()
        case .disconnected:
            disconnect()
        case .failed, .closed:
            invalidateTransmissionContext()
            callbacks?.connectionStateChanged(state)
        }
    }

    func fireRestartProgressTimeout() {
        callbacks?.connectionStateChanged(.connecting)
        callbacks?.connectionStateChanged(.disconnected)
    }

    func changePath(_ path: InternetNetworkPath) {
        let changed = lastNetworkPathFingerprint.map { $0 != path.fingerprint } ?? false
        lastNetworkPathFingerprint = path.fingerprint
        if changed { invalidateTransmissionContext() }
        callbacks?.networkPathChanged(path)
    }

    func sample(_ sample: InternetNetworkQualitySample) {
        callbacks?.networkQualitySampled(sample)
    }

    func completeAllSends() {
        while !pendingCompletions.isEmpty {
            pendingCompletions.removeFirst()(.success(()))
        }
    }

    private var currentTransmissionContext: WebRTCEngineTransmissionContext? {
        guard let activeTransmissionPath else { return nil }
        return WebRTCEngineTransmissionContext(epoch: transmissionEpoch, path: activeTransmissionPath)
    }

    private func invalidateTransmissionContext() {
        guard activeTransmissionPath != nil else { return }
        activeTransmissionPath = nil
        transmissionEpoch &+= 1
        callbacks?.transmissionContextChanged(nil)
    }
}

private final class QueuedSelfTestWebRTCEngine: WebRTCEnginePort, @unchecked Sendable {
    let localCipher: PlatformSessionPacketCipher

    private let remoteCipher: PlatformSessionPacketCipher
    private let queue = DispatchQueue(label: "dev.vibescreen.self-test.queued-transmission-engine")
    private let queueKey = DispatchSpecificKey<UInt8>()
    private var callbacks: WebRTCEngineCallbacks?
    private var transmissionEpoch: UInt64 = 0
    private var activeTransmissionPath: InternetPathKind?
    private var storedEvents: [String] = []
    private var storedPlaintext: [Data] = []
    private var closed = false

    init(sessionIdentifier: String) throws {
        let ciphers = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: sessionIdentifier,
            sharedSecret: Data(repeating: 0xb1, count: 32),
            bootstrapSecret: Data(repeating: 0xb2, count: 32),
            transcriptContext: Data(repeating: 0xb3, count: 32)
        )
        localCipher = ciphers.host
        remoteCipher = ciphers.device
        queue.setSpecific(key: queueKey, value: 1)
    }

    var events: [String] { performSync { storedEvents } }
    var sentPlaintext: [Data] { performSync { storedPlaintext } }

    func install(callbacks: WebRTCEngineCallbacks) {
        performSync { self.callbacks = callbacks }
    }

    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws {}

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        expectedContext: WebRTCEngineTransmissionContext,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        queue.async { [weak self] in
            guard let self else { return }
            self.storedEvents.append("S")
            guard !self.closed, self.currentTransmissionContext == expectedContext,
                  let plaintext = self.remoteCipher.open(payload, channel: channel) else {
                completion(.failure(SelfTestSendError.staleTransmissionContext))
                return
            }
            self.storedPlaintext.append(plaintext)
            completion(.success(()))
        }
    }

    func restartICE() -> WebRTCEngineRecoveryDisposition {
        queue.async { [weak self] in
            guard let self else { return }
            self.storedEvents.append("R")
            self.invalidateTransmissionContext()
            self.callbacks?.connectionStateChanged(.connecting)
        }
        return .peerReplacementStarted
    }

    func requestMediaKeyframe() {}

    func close() {
        performSync {
            guard !closed else { return }
            invalidateTransmissionContext()
            closed = true
            remoteCipher.close()
        }
    }

    func connect(path: InternetPathKind) {
        performSync {
            if activeTransmissionPath != path {
                invalidateTransmissionContext()
                activeTransmissionPath = path
            }
            callbacks?.transmissionContextChanged(currentTransmissionContext)
            callbacks?.connectionStateChanged(.connected(path: path))
        }
    }

    func enqueueDisconnectAndWaitForInvalidation() -> Bool {
        let invalidated = DispatchSemaphore(value: 0)
        queue.async { [weak self] in
            guard let self else { invalidated.signal(); return }
            self.storedEvents.append("D")
            self.invalidateTransmissionContext(beforeCallback: { invalidated.signal() })
            self.callbacks?.connectionStateChanged(.disconnected)
        }
        return invalidated.wait(timeout: .now() + 2) == .success
    }

    func waitForEventCount(_ count: Int) -> Bool {
        let deadline = DispatchTime.now() + .seconds(2)
        while DispatchTime.now() < deadline {
            if events.count >= count { return true }
            Thread.sleep(forTimeInterval: 0.005)
        }
        return events.count >= count
    }

    private var currentTransmissionContext: WebRTCEngineTransmissionContext? {
        guard let activeTransmissionPath else { return nil }
        return WebRTCEngineTransmissionContext(epoch: transmissionEpoch, path: activeTransmissionPath)
    }

    private func invalidateTransmissionContext(beforeCallback: (() -> Void)? = nil) {
        guard activeTransmissionPath != nil else {
            beforeCallback?()
            return
        }
        activeTransmissionPath = nil
        transmissionEpoch &+= 1
        beforeCallback?()
        callbacks?.transmissionContextChanged(nil)
    }

    private func performSync<T>(_ operation: () -> T) -> T {
        if DispatchQueue.getSpecific(key: queueKey) != nil { return operation() }
        return queue.sync(execute: operation)
    }
}

private enum SelfTestPeerDelegateSource: CaseIterable {
    case iceConnection
    case peerConnection
}

private enum SelfTestSendError: Error {
    case failed
    case staleTransmissionContext
}

private final class LockedSelfTestTransportResult: @unchecked Sendable {
    private let lock = NSLock()
    private var result: Result<Void, InternetTransportError>?

    func store(_ result: Result<Void, InternetTransportError>) {
        lock.lock()
        self.result = result
        lock.unlock()
    }

    func load() -> Result<Void, InternetTransportError>? {
        lock.lock()
        defer { lock.unlock() }
        return result
    }
}

private final class UncheckedSendableBox<Value>: @unchecked Sendable {
    let value: Value

    init(_ value: Value) {
        self.value = value
    }
}

private extension Result where Success == Void, Failure == InternetTransportError {
    var isSuccess: Bool {
        if case .success = self { return true }
        return false
    }

    var isRelayBudgetFailure: Bool {
        if case .failure(.relayBudgetExceeded) = self { return true }
        return false
    }

    var isEmptyPayloadFailure: Bool {
        if case .failure(.emptyPayload) = self { return true }
        return false
    }

    var isControlBacklogFailure: Bool {
        if case .failure(.controlBacklogExceeded) = self { return true }
        return false
    }

    var isNotConnectedFailure: Bool {
        if case .failure(.notConnected) = self { return true }
        return false
    }

    var isSequenceExhaustedFailure: Bool {
        if case .failure(.sequenceExhausted) = self { return true }
        return false
    }
}

private extension InternetTransportState {
    var isFailed: Bool {
        if case .failed = self { return true }
        return false
    }
}
