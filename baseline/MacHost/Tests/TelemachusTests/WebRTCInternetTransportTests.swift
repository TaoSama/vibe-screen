import Foundation
import VibeScreenProtocol
import XCTest
@testable import Telemachus

private enum TestError: Error { case sendFailed }

final class WebRTCInternetTransportTests: XCTestCase {
    func testPeerDelegateGenerationAcceptsOnlyCurrentReplacementPeer() throws {
        var state = WebRTCPeerConnectionDelegateGenerationState()
        let initialGeneration = state.currentGeneration

        XCTAssertTrue(state.accepts(delegateGeneration: initialGeneration))

        let restartGeneration = try XCTUnwrap(state.beginRestart())
        XCTAssertFalse(state.accepts(delegateGeneration: initialGeneration))
        XCTAssertTrue(state.accepts(delegateGeneration: restartGeneration))

        let nextGeneration = try XCTUnwrap(state.beginRestart())
        XCTAssertFalse(state.accepts(delegateGeneration: restartGeneration))
        XCTAssertTrue(state.accepts(delegateGeneration: nextGeneration))
    }

    func testTransmissionEpochStateRejectsStaleStatisticsUntilPeerReconnects() throws {
        var state = WebRTCEngineTransmissionEpochState()
        state.markPeerConnected()
        let initial = try XCTUnwrap(state.selectPath(.direct)?.context)

        XCTAssertTrue(state.markPeerDisconnected())
        XCTAssertFalse(state.acceptsCandidateStatistics)
        XCTAssertNil(state.selectPath(.relay))
        XCTAssertFalse(state.acceptsSend(expectedContext: initial))

        state.markPeerConnected()
        let recovered = try XCTUnwrap(state.selectPath(.relay)?.context)
        XCTAssertEqual(recovered.epoch, initial.epoch + 1)
        XCTAssertNotEqual(recovered, initial)
        XCTAssertTrue(state.acceptsCandidateStatistics)
        XCTAssertTrue(state.acceptsSend(expectedContext: recovered))
    }

    func testTransmissionEpochExhaustionFailsClosedWithoutWrapping() throws {
        var state = WebRTCEngineTransmissionEpochState(
            epoch: UInt64.max,
            peerIsConnected: true,
            activePath: .direct
        )
        let staleContext = try XCTUnwrap(state.currentContext)

        XCTAssertTrue(state.markPeerDisconnected())
        XCTAssertTrue(state.isExhausted)
        XCTAssertEqual(state.epoch, UInt64.max)
        XCTAssertNil(state.currentContext)
        XCTAssertFalse(state.acceptsCandidateStatistics)
        XCTAssertFalse(state.acceptsCandidateStatistics(expectedEpoch: UInt64.max))
        XCTAssertFalse(state.acceptsSend(expectedContext: staleContext))

        state.markPeerConnected()
        XCTAssertNil(state.selectPath(.direct))
        XCTAssertFalse(state.beginRestart())
        XCTAssertEqual(state.epoch, UInt64.max)
    }

    func testConsecutiveRestartAttemptsRejectDelayedCandidateStatisticsFromPriorAttempt() throws {
        var state = WebRTCEngineTransmissionEpochState()
        state.markPeerConnected()
        let initial = try XCTUnwrap(state.selectPath(.direct)?.context)

        XCTAssertTrue(state.markPeerDisconnected())
        XCTAssertFalse(state.beginRestart())
        let firstAttemptEpoch = state.epoch
        state.markPeerConnected()
        XCTAssertTrue(state.acceptsCandidateStatistics(expectedEpoch: firstAttemptEpoch))

        XCTAssertFalse(state.beginRestart())
        let secondAttemptEpoch = state.epoch
        state.markPeerConnected()

        XCTAssertEqual(firstAttemptEpoch, initial.epoch + 2)
        XCTAssertEqual(secondAttemptEpoch, firstAttemptEpoch + 1)
        XCTAssertFalse(
            state.acceptsCandidateStatistics(expectedEpoch: firstAttemptEpoch),
            "A delayed candidate pair from attempt 1 must not publish attempt 2"
        )
        XCTAssertTrue(state.acceptsCandidateStatistics(expectedEpoch: secondAttemptEpoch))
        let recovered = try XCTUnwrap(state.selectPath(.relay)?.context)
        XCTAssertEqual(recovered.epoch, secondAttemptEpoch)
    }

    func testCandidatePairTimeoutRejectsCancelledStaleTokenWithoutClearingReplacementTimer() throws {
        var state = WebRTCCandidatePairResolutionTimeoutState()
        let cancelledToken = try XCTUnwrap(state.scheduleIfNeeded())
        state.cancel()
        let activeToken = try XCTUnwrap(state.scheduleIfNeeded())

        XCTAssertNil(state.fire(
            token: cancelledToken,
            peerIsConnected: true,
            selectedPath: .unknown
        ))
        XCTAssertTrue(state.isScheduled)
        XCTAssertEqual(state.fire(
            token: activeToken,
            peerIsConnected: true,
            selectedPath: .unknown
        ), true)
        XCTAssertFalse(state.isScheduled)

        let preconnectionToken = try XCTUnwrap(state.scheduleIfNeeded())
        XCTAssertEqual(state.fire(
            token: preconnectionToken,
            peerIsConnected: false,
            selectedPath: .unknown
        ), false)
    }

    func testConnectionAttemptDeadlineRejectsCancelledStaleTokenWithoutClearingReplacementTimer() throws {
        var generation = WebRTCPeerConnectionDelegateGenerationState()
        var state = WebRTCConnectionAttemptDeadlineState()
        let cancelledToken = try XCTUnwrap(state.schedule(
            generation: generation.currentGeneration,
            attemptKind: .initial
        ))
        state.cancel()
        let replacementGeneration = try XCTUnwrap(generation.beginRestart())
        let activeToken = try XCTUnwrap(state.schedule(
            generation: replacementGeneration,
            attemptKind: .localRecovery
        ))

        XCTAssertNil(state.fire(
            token: cancelledToken,
            currentGeneration: replacementGeneration
        ))
        XCTAssertEqual(state.activeToken, activeToken)
        XCTAssertEqual(state.fire(
            token: activeToken,
            currentGeneration: replacementGeneration
        ), .localRecovery)
        XCTAssertNil(state.activeToken)
    }

    func testNewerCandidateStatisticsPreventOlderResponseFromRollingPathBack() throws {
        var state = WebRTCStatisticsRequestOrderingState()
        let oldPairRequest = try XCTUnwrap(state.beginRequest())
        let freshPairRequest = try XCTUnwrap(state.beginRequest())

        XCTAssertTrue(state.acceptsResponse(sequence: freshPairRequest))
        XCTAssertFalse(
            state.acceptsResponse(sequence: oldPairRequest),
            "A late old-pair response must not overwrite a newer candidate-pair decision"
        )

        let subsequentRequest = try XCTUnwrap(state.beginRequest())
        XCTAssertTrue(state.acceptsResponse(sequence: subsequentRequest))
    }

    func testStatisticsRequestSequenceFailsClosedInsteadOfWrapping() throws {
        var state = WebRTCStatisticsRequestOrderingState(nextSequence: UInt64.max - 1)

        XCTAssertEqual(try XCTUnwrap(state.beginRequest()), UInt64.max)
        XCTAssertNil(state.beginRequest())
        XCTAssertEqual(state.nextSequence, UInt64.max)
    }

    func testCandidatePathResolutionFailsClosedForMissingOrUnknownStats() {
        XCTAssertEqual(
            SelectedCandidatePathResolver.resolve(
                localCandidateType: nil,
                remoteCandidateType: "host"
            ),
            .unknown
        )
        XCTAssertEqual(
            SelectedCandidatePathResolver.resolve(
                localCandidateType: "unknown",
                remoteCandidateType: "host"
            ),
            .unknown
        )
        XCTAssertEqual(
            SelectedCandidatePathResolver.resolve(
                localCandidateType: "host",
                remoteCandidateType: "srflx"
            ),
            .direct
        )
        XCTAssertEqual(
            SelectedCandidatePathResolver.resolve(
                localCandidateType: "relay",
                remoteCandidateType: "host"
            ),
            .relay
        )
        XCTAssertTrue(
            SelectedCandidatePathResolver.mustFailClosed(
                publishedPath: .direct,
                observedPath: .unknown
            )
        )
        XCTAssertTrue(
            SelectedCandidatePathResolver.mustFailClosed(
                publishedPath: .direct,
                observedPath: nil
            )
        )
        XCTAssertTrue(
            SelectedCandidatePathResolver.mustFailClosed(
                publishedPath: .relay,
                observedPath: .unknown
            )
        )
        XCTAssertTrue(
            SelectedCandidatePathResolver.mustFailClosed(
                publishedPath: .relay,
                observedPath: nil
            )
        )
    }

    func testUnknownCandidatePathCannotPublishConnected() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher
        )
        try transport.start(configuration: validConfiguration())

        engine.emitConnection(.connected(path: .unknown))

        guard case .failed = transport.snapshot().state else {
            return XCTFail("Unknown candidate path must fail closed")
        }
        XCTAssertFailure(
            transport.sendControl(Data([1])),
            expected: .notConnected
        )
    }

    func testStartsEngineWithAllProtocolV1DataChannels() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: engine.localCipher)

        try transport.start(configuration: validConfiguration())

        XCTAssertEqual(engine.startedChannels, InternetTransportChannel.allCases.map(\.dataChannelConfiguration))
    }

    func testRejectsTURNWithoutCredentials() {
        let configuration = WebRTCTransportConfiguration(
            iceServers: [WebRTCICEServer(urls: [URL(string: "turn:relay.example.com:3478")!])],
            peerIdentity: "device-key-id",
            sessionIdentifier: "session-1",
            forceRelay: false
        )

        XCTAssertThrowsError(try configuration.validate()) { error in
            XCTAssertEqual(
                error as? InternetTransportError,
                .invalidConfiguration("TURN servers require a username and credential.")
            )
        }
    }

    func testRejectsCleartextRemoteSignaling() {
        let configuration = WebRTCTransportConfiguration(
            iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.com:3478")!])],
            peerIdentity: "device-key-id",
            sessionIdentifier: "session-1",
            forceRelay: false,
            signaling: WebRTCSignalingConfiguration(
                endpoint: URL(string: "http://signaling.example.com")!,
                bearerToken: "role-token",
                role: .offerer
            )
        )

        XCTAssertThrowsError(try configuration.validate()) { error in
            guard case .invalidConfiguration(let reason) = error as? InternetTransportError else {
                return XCTFail("Expected signaling configuration rejection, got \(error)")
            }
            XCTAssertTrue(reason.contains("https://"))
        }
    }

    func testDefaultProductionEngineRequiresExplicitSignaling() {
        let ciphers = makeCipherPair()
        let transport = WebRTCInternetTransport(packetCipher: ciphers.host)

        XCTAssertThrowsError(try transport.start(configuration: validConfiguration())) { error in
            guard case .engineUnavailable(let reason) = error as? InternetTransportError else {
                return XCTFail("Expected explicit production configuration failure, got \(error)")
            }
            XCTAssertTrue(reason.contains("signaling"))
        }
        transport.close()
    }

    func testUnavailableEngineFailsExplicitly() {
        let ciphers = makeCipherPair()
        let transport = WebRTCInternetTransport(
            engine: UnavailableWebRTCEngine(),
            packetCipher: ciphers.host
        )

        XCTAssertThrowsError(try transport.start(configuration: validConfiguration())) { error in
            guard case .engineUnavailable = error as? InternetTransportError else {
                return XCTFail("Expected an explicit missing-engine error, got \(error)")
            }
        }
        guard case .failed = transport.snapshot().state else {
            return XCTFail("Missing production engine must move the transport to failed")
        }
    }

    func testReliableControlMessagesRemainOrderedWhileSendIsInFlight() throws {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let first = Data([1])
        let second = Data([2])
        let third = Data([3])

        XCTAssertSuccess(transport.sendControl(first))
        XCTAssertSuccess(transport.sendControl(second))
        XCTAssertSuccess(transport.sendControl(third))
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [first])

        engine.completeSend(at: 0)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [first, second])
        engine.completeSend(at: 1)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [first, second, third])
        engine.completeSend(at: 2)

        XCTAssertEqual(transport.snapshot().controlBytesSent, 3)
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
    }

    func testControlCompletionReportsSuccessfulEngineDelivery() throws {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let completion = LockedTransportResult()

        XCTAssertSuccess(transport.sendControl(Data([1])) { result in
            completion.store(result)
        })
        XCTAssertNil(completion.load())

        engine.completeSend(at: 0)

        guard case .success? = completion.load() else {
            return XCTFail("Successful engine delivery must complete the control send")
        }
    }

    func testControlCompletionReportsEngineSendFailure() throws {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let failedCompletion = LockedTransportResult()
        let queuedCompletion = LockedTransportResult()

        XCTAssertSuccess(transport.sendControl(Data([1])) { result in
            failedCompletion.store(result)
        })
        XCTAssertSuccess(transport.sendControl(Data([2])) { result in
            queuedCompletion.store(result)
        })
        engine.completeSend(at: 0, result: .failure(TestError.sendFailed))

        guard case .failure(let error)? = failedCompletion.load() else {
            return XCTFail("Failed engine delivery must complete the control send")
        }
        guard case .engineSendFailed = error else {
            return XCTFail("Expected engineSendFailed, got \(error)")
        }
        XCTAssertFailure(try XCTUnwrap(queuedCompletion.load()), expected: .notConnected)
        XCTAssertEqual(failedCompletion.invocationCount, 1)
        XCTAssertEqual(queuedCompletion.invocationCount, 1)
        guard case .failed = transport.snapshot().state else {
            return XCTFail("A failed control completion must fail the transport")
        }
    }

    func testPipelineInvalidationCompletesInFlightAndQueuedControlExactlyOnce() throws {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let inFlightCompletion = LockedTransportResult()
        let queuedCompletion = LockedTransportResult()

        XCTAssertSuccess(transport.sendControl(Data([1])) { result in
            inFlightCompletion.store(result)
        })
        XCTAssertSuccess(transport.sendControl(Data([2])) { result in
            queuedCompletion.store(result)
        })

        engine.emitPath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))
        engine.emitPath(InternetNetworkPath(
            interface: .cellular,
            isSatisfied: true,
            fingerprint: "cellular-b"
        ))

        XCTAssertFailure(try XCTUnwrap(inFlightCompletion.load()), expected: .notConnected)
        XCTAssertFailure(try XCTUnwrap(queuedCompletion.load()), expected: .notConnected)
        XCTAssertEqual(inFlightCompletion.invocationCount, 1)
        XCTAssertEqual(queuedCompletion.invocationCount, 1)

        engine.completeSend(at: 0)

        XCTAssertEqual(inFlightCompletion.invocationCount, 1)
        XCTAssertEqual(queuedCompletion.invocationCount, 1)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
    }

    func testCloseCompletesInFlightAndQueuedControlExactlyOnce() throws {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let inFlightCompletion = LockedTransportResult()
        let queuedCompletion = LockedTransportResult()

        XCTAssertSuccess(transport.sendControl(Data([1])) { result in
            inFlightCompletion.store(result)
        })
        XCTAssertSuccess(transport.sendControl(Data([2])) { result in
            queuedCompletion.store(result)
        })

        transport.close()

        XCTAssertFailure(try XCTUnwrap(inFlightCompletion.load()), expected: .notConnected)
        XCTAssertFailure(try XCTUnwrap(queuedCompletion.load()), expected: .notConnected)
        XCTAssertEqual(inFlightCompletion.invocationCount, 1)
        XCTAssertEqual(queuedCompletion.invocationCount, 1)

        engine.completeSend(at: 0)

        XCTAssertEqual(inFlightCompletion.invocationCount, 1)
        XCTAssertEqual(queuedCompletion.invocationCount, 1)
        XCTAssertEqual(transport.snapshot().state, .closed)
    }

    func testDeinitCompletesInFlightAndQueuedControlExactlyOnce() throws {
        let engine = FakeWebRTCEngine()
        var transport: WebRTCInternetTransport? = connectedTransport(engine: engine)
        weak var weakTransport = transport
        let inFlightCompletion = LockedTransportResult()
        let queuedCompletion = LockedTransportResult()

        XCTAssertSuccess(try XCTUnwrap(transport).sendControl(Data([1])) { result in
            inFlightCompletion.store(result)
        })
        XCTAssertSuccess(try XCTUnwrap(transport).sendControl(Data([2])) { result in
            queuedCompletion.store(result)
        })

        transport = nil

        XCTAssertNil(weakTransport)
        XCTAssertFailure(try XCTUnwrap(inFlightCompletion.load()), expected: .notConnected)
        XCTAssertFailure(try XCTUnwrap(queuedCompletion.load()), expected: .notConnected)
        XCTAssertEqual(inFlightCompletion.invocationCount, 1)
        XCTAssertEqual(queuedCompletion.invocationCount, 1)

        engine.completeSend(at: 0)

        XCTAssertEqual(inFlightCompletion.invocationCount, 1)
        XCTAssertEqual(queuedCompletion.invocationCount, 1)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(engine.closeCount, 1)
    }

    func testControlCompletionCanCloseReentrantlyAndCancelQueueExactlyOnce() throws {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let deliveredCompletion = LockedTransportResult()
        let queuedCompletion = LockedTransportResult()

        XCTAssertSuccess(transport.sendControl(Data([1])) { result in
            deliveredCompletion.store(result)
            transport.close()
        })
        XCTAssertSuccess(transport.sendControl(Data([2])) { result in
            queuedCompletion.store(result)
        })

        engine.completeSend(at: 0)

        guard case .success? = deliveredCompletion.load() else {
            return XCTFail("The delivered control message must complete successfully")
        }
        XCTAssertFailure(try XCTUnwrap(queuedCompletion.load()), expected: .notConnected)
        XCTAssertEqual(deliveredCompletion.invocationCount, 1)
        XCTAssertEqual(queuedCompletion.invocationCount, 1)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(transport.snapshot().state, .closed)
    }

    func testControlBacklogIsBounded() {
        let engine = FakeWebRTCEngine()
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 3,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: 100
        )
        let transport = connectedTransport(engine: engine, limits: limits)

        XCTAssertSuccess(transport.sendControl(Data([1, 2])))
        XCTAssertFailure(
            transport.sendControl(Data([3, 4])),
            expected: .controlBacklogExceeded(maximumBytes: 3)
        )
        guard case .failed = transport.snapshot().state else {
            return XCTFail("A reliable-control overflow must fail the session")
        }
        XCTAssertTrue(engine.didClose)
    }

    func testControlBacklogEntryCountIsBoundedWithFIFOQueue() {
        let engine = FakeWebRTCEngine()
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 64,
            maximumBufferedControlMessages: 2,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: 100
        )
        let transport = connectedTransport(engine: engine, limits: limits)

        XCTAssertSuccess(transport.sendControl(Data([1])))
        XCTAssertSuccess(transport.sendControl(Data([2])))
        XCTAssertEqual(transport.snapshot().bufferedControlMessages, 2)
        XCTAssertFailure(
            transport.sendControl(Data([3])),
            expected: .controlBacklogExceeded(maximumBytes: 64)
        )

        guard case .failed = transport.snapshot().state else {
            return XCTFail("A reliable-control entry overflow must fail closed")
        }
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertTrue(engine.didClose)
    }

    func testConnectingCallbackRunsOnlyAfterEngineStartCompletes() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: engine.localCipher)
        transport.onStateChanged = { state in
            if state == .connecting { transport.close() }
        }

        try transport.start(configuration: validConfiguration())

        XCTAssertEqual(engine.startedChannels.count, InternetTransportChannel.allCases.count)
        XCTAssertTrue(engine.didClose)
        XCTAssertFalse(engine.startedAfterClose)
        XCTAssertEqual(transport.snapshot().state, .closed)
    }

    func testCloseBeforeStartIsAnIrreversibleTerminalState() {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: engine.localCipher)

        transport.close()

        XCTAssertThrowsError(try transport.start(configuration: validConfiguration())) { error in
            guard case .engineUnavailable(let reason) = error as? InternetTransportError else {
                return XCTFail("Expected closed transport rejection, got \(error)")
            }
            XCTAssertTrue(reason.contains("closed"))
        }
        XCTAssertEqual(engine.startCount, 0)
        XCTAssertEqual(engine.closeCount, 1)
        XCTAssertEqual(transport.snapshot().state, .closed)
    }

    func testCloseInsertedBeforeEngineStartPreventsEngineSideEffect() {
        let engine = FakeWebRTCEngine()
        var transport: WebRTCInternetTransport!
        transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            beforeEngineStart: { transport.close() }
        )

        XCTAssertThrowsError(try transport.start(configuration: validConfiguration())) { error in
            guard case .engineUnavailable(let reason) = error as? InternetTransportError else {
                return XCTFail("Expected closed transport rejection, got \(error)")
            }
            XCTAssertTrue(reason.contains("closed"))
        }

        XCTAssertTrue(engine.startedChannels.isEmpty)
        XCTAssertEqual(engine.startCount, 0)
        XCTAssertEqual(engine.closeCount, 1)
        XCTAssertEqual(transport.snapshot().state, .closed)
    }

    func testConcurrentCloseThatCompletesBeforeLifecycleAdmissionWins() {
        let engine = FakeWebRTCEngine()
        let closeCompleted = DispatchSemaphore(value: 0)
        var transport: WebRTCInternetTransport!
        transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            beforeEngineStart: {
                DispatchQueue.global().async {
                    transport.close()
                    closeCompleted.signal()
                }
                XCTAssertEqual(closeCompleted.wait(timeout: .now() + 2), .success)
            }
        )

        XCTAssertThrowsError(try transport.start(configuration: validConfiguration()))
        XCTAssertEqual(engine.startCount, 0)
        XCTAssertEqual(engine.closeCount, 1)
        XCTAssertEqual(transport.snapshot().state, .closed)
    }

    func testRepeatedStartIsRejectedWithoutStartingEngineTwice() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: engine.localCipher)

        try transport.start(configuration: validConfiguration())

        XCTAssertThrowsError(try transport.start(configuration: validConfiguration())) { error in
            guard case .engineUnavailable(let reason) = error as? InternetTransportError else {
                return XCTFail("Expected repeated-start rejection, got \(error)")
            }
            XCTAssertTrue(reason.contains("already started"))
        }
        XCTAssertEqual(engine.startCount, 1)
        XCTAssertEqual(transport.snapshot().state, .connecting)
    }

    func testFailedStartCannotBeRetried() {
        let engine = FakeWebRTCEngine(startError: TestError.sendFailed)
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: engine.localCipher)

        XCTAssertThrowsError(try transport.start(configuration: validConfiguration()))
        XCTAssertThrowsError(try transport.start(configuration: validConfiguration())) { error in
            guard case .engineUnavailable(let reason) = error as? InternetTransportError else {
                return XCTFail("Expected failed transport rejection, got \(error)")
            }
            XCTAssertTrue(reason.contains("failed and cannot be restarted"))
        }
        XCTAssertEqual(engine.startCount, 1)
        guard case .failed = transport.snapshot().state else {
            return XCTFail("A failed start must remain terminal")
        }
    }

    func testProductionEngineCloseBeforeStartCannotBeRevived() {
        let signaling = TestWebRTCSignalingClient()
        let engine = ProductionWebRTCEngine(signaling: signaling)
        engine.close()

        XCTAssertThrowsError(try engine.start(
            configuration: productionConfiguration(),
            channels: InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
        )) { error in
            XCTAssertTrue(error.localizedDescription.contains("closed"))
        }
        XCTAssertEqual(signaling.connectCount, 0)
    }

    func testProductionEngineFailedStartCannotBeRetried() {
        let signaling = TestWebRTCSignalingClient(connectError: TestError.sendFailed)
        let engine = ProductionWebRTCEngine(signaling: signaling)

        XCTAssertThrowsError(try engine.start(
            configuration: productionConfiguration(),
            channels: InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
        ))
        XCTAssertThrowsError(try engine.start(
            configuration: productionConfiguration(),
            channels: InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
        )) { error in
            XCTAssertTrue(error.localizedDescription.contains("failed"))
        }
        XCTAssertEqual(signaling.connectCount, 1)
    }

    func testProductionEngineStartsOnceAndRejectsRepeatedStart() throws {
        let signaling = TestWebRTCSignalingClient()
        let engine = ProductionWebRTCEngine(signaling: signaling)

        try engine.start(
            configuration: productionConfiguration(),
            channels: InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
        )
        XCTAssertThrowsError(try engine.start(
            configuration: productionConfiguration(),
            channels: InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
        )) { error in
            XCTAssertTrue(error.localizedDescription.contains("already started"))
        }
        XCTAssertEqual(signaling.connectCount, 1)
        engine.close()
    }

    func testPreConnectionDisconnectConsumesRecoveryBudgetInsteadOfStallingConnecting() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 1)
        )
        try transport.start(configuration: validConfiguration())

        engine.emitConnection(.disconnected)

        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(engine.restartICECount, 1)
    }

    func testRecoveringCallbackClosePreventsRestartICESideEffect() throws {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        transport.onStateChanged = { state in
            if case .recovering = state { transport.close() }
        }

        engine.emitConnection(.disconnected)

        XCTAssertEqual(transport.snapshot().state, .closed)
        XCTAssertEqual(engine.restartICECount, 0)
        XCTAssertEqual(engine.closeCount, 1)
    }

    func testCloseIsIdempotentAndReentrantClosedCallbackPublishesOnce() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(engine: engine, packetCipher: engine.localCipher)
        var states: [InternetTransportState] = []
        transport.onStateChanged = { state in
            states.append(state)
            if state == .closed { transport.close() }
        }
        try transport.start(configuration: validConfiguration())

        transport.close()
        transport.close()

        XCTAssertEqual(states, [.connecting, .closed])
        XCTAssertEqual(engine.closeCount, 1)
    }

    func testRemoteClosedStateClosesEngineExactlyOnce() throws {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        var states: [InternetTransportState] = []
        transport.onStateChanged = { states.append($0) }

        engine.emitConnection(.closed)
        XCTAssertEqual(engine.closeCount, 1)
        transport.close()
        transport.close()

        XCTAssertEqual(states, [.closed])
        XCTAssertEqual(transport.snapshot().state, .closed)
        XCTAssertEqual(engine.closeCount, 1)
    }

    func testMediaAccountingOverflowFailsAndClearsEntireMediaPipeline() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            initialMediaBytesSent: UInt64.max
        )
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .direct))
        XCTAssertSuccess(transport.sendMedia(frame(1, isKeyframe: true)))
        XCTAssertSuccess(transport.sendMedia(frame(2, isKeyframe: true)))

        engine.completeSend(at: 0)

        guard case .failed(let reason) = transport.snapshot().state else {
            return XCTFail("Media byte accounting overflow must fail the transport")
        }
        XCTAssertTrue(reason.contains("transport byte accounting"))
        XCTAssertFalse(transport.snapshot().mediaInFlight)
        XCTAssertFalse(transport.snapshot().hasPendingMediaFrame)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertTrue(engine.didClose)
    }

    func testControlAccountingOverflowCompletesExactlyOnceAndFailsClosed() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            initialControlBytesSent: UInt64.max
        )
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .direct))
        let completion = LockedTransportResult()

        XCTAssertSuccess(transport.sendControl(Data([1])) { result in
            completion.store(result)
        })
        engine.completeSend(at: 0)

        XCTAssertFailure(
            try XCTUnwrap(completion.load()),
            expected: .sequenceExhausted("transport byte accounting")
        )
        XCTAssertEqual(completion.invocationCount, 1)
        guard case .failed(let reason) = transport.snapshot().state else {
            return XCTFail("Control byte accounting overflow must fail the transport")
        }
        XCTAssertTrue(reason.contains("transport byte accounting"))
        XCTAssertTrue(engine.didClose)
    }

    func testRelayReservationOverflowFailsClosed() throws {
        let engine = FakeWebRTCEngine()
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 16,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: UInt64.max
        )
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            limits: limits,
            initialRelayBytesSent: UInt64.max - 1,
            initialRelayBytesReserved: 1
        )
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .relay))

        XCTAssertFailure(
            transport.sendControl(Data([1])),
            expected: .relayBudgetExceeded(maximumBytes: UInt64.max)
        )
        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().relayBytesSent, UInt64.max - 1)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 1)
    }

    func testEmptyMessagesAreRejectedWithoutEnteringQueues() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)

        XCTAssertFailure(transport.sendControl(Data()), expected: .emptyPayload(channel: .control))
        XCTAssertFailure(
            transport.sendMedia(encodedFrame(
                payloads: [Data()],
                captureTimestamp: 1,
                isKeyframe: true
            )),
            expected: .emptyPayload(channel: .media)
        )
        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
    }

    func testOversizedEncryptedInboundRecordFailsBeforeDecryption() {
        let engine = FakeWebRTCEngine()
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 16,
            maximumMediaFrameBytes: 16,
            maximumRelayBytesPerSession: 100
        )
        let transport = connectedTransport(engine: engine, limits: limits)

        engine.receiveRaw(
            Data(repeating: 0x41, count: 8 + PlatformSessionPacketCipher.recordOverhead + 1),
            channel: .control
        )

        guard case .failed(let reason) = transport.snapshot().state else {
            return XCTFail("Oversized encrypted input must fail the transport")
        }
        XCTAssertTrue(reason.contains("inbound limit"))
    }

    func testRepeatedAuthenticationFailuresExhaustBudgetAndFailClosed() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let invalidRecord = Data(repeating: 0x41, count: PlatformSessionPacketCipher.recordOverhead)

        engine.receiveRaw(invalidRecord, channel: .control)
        engine.receiveRaw(invalidRecord, channel: .control)
        XCTAssertEqual(transport.snapshot().state, .connected(.direct))
        engine.receiveRaw(invalidRecord, channel: .control)

        guard case .failed(let reason) = transport.snapshot().state else {
            return XCTFail("Authentication failure budget must fail the transport")
        }
        XCTAssertTrue(reason.contains("application-record authentication failed repeatedly"))
    }

    func testFailedControlSendDoesNotDeliverLaterOrderedMessages() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        var reportedError: InternetTransportError?
        transport.onError = { reportedError = $0 }

        XCTAssertSuccess(transport.sendControl(Data([1])))
        XCTAssertSuccess(transport.sendControl(Data([2])))
        engine.completeSend(at: 0, result: .failure(TestError.sendFailed))

        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
        guard case .engineSendFailed = reportedError else {
            return XCTFail("Control failure was not reported")
        }
        guard case .failed = transport.snapshot().state else {
            return XCTFail("A failed reliable-control send must fail the session")
        }
    }

    func testControlBacklogFailureReleasesSendGateBeforeSynchronousCloseCallback() {
        let engine = FakeWebRTCEngine(emitClosedSynchronouslyOnClose: true)
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 1,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: 100
        )
        let transport = connectedTransport(engine: engine, limits: limits)
        let finished = DispatchSemaphore(value: 0)
        let result = LockedTransportResult()

        XCTAssertSuccess(transport.sendControl(Data([1])))
        DispatchQueue.global().async {
            result.store(transport.sendControl(Data([2])))
            finished.signal()
        }

        XCTAssertEqual(finished.wait(timeout: .now() + 2), .success)
        XCTAssertFailure(
            try! XCTUnwrap(result.load()),
            expected: .controlBacklogExceeded(maximumBytes: 1)
        )
        guard case .failed = transport.snapshot().state else {
            return XCTFail("Backlog failure must remain failed after the synchronous close callback")
        }
        XCTAssertTrue(engine.didClose)
    }

    func testSynchronousControlSendFailureClosesOutsideSendGate() {
        let engine = FakeWebRTCEngine(
            emitClosedSynchronouslyOnClose: true,
            synchronousSendFailure: TestError.sendFailed
        )
        let transport = connectedTransport(engine: engine)
        var reportedError: InternetTransportError?
        transport.onError = { reportedError = $0 }

        XCTAssertSuccess(transport.sendControl(Data([1])))

        guard case .failed = transport.snapshot().state else {
            return XCTFail("Synchronous engine failure must fail the transport without deadlocking")
        }
        guard case .engineSendFailed = reportedError else {
            return XCTFail("Synchronous engine failure was not reported")
        }
        XCTAssertTrue(engine.didClose)
    }

    func testConnectingAndConnectedCallbacksCannotRevivePreparedFailureBeforeEngineClose() {
        let engine = FakeWebRTCEngine()
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 1,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: 100
        )
        var transport: WebRTCInternetTransport!
        var resurrectionResult: Result<Void, InternetTransportError>?
        transport = connectedTransport(
            engine: engine,
            limits: limits,
            beforeFailureSideEffects: {
                engine.emitConnection(.connecting)
                engine.emitConnection(.connected(path: .direct))
                resurrectionResult = transport.sendControl(Data([9]))
            }
        )
        var states: [InternetTransportState] = []
        transport.onStateChanged = { states.append($0) }

        XCTAssertSuccess(transport.sendControl(Data([1])))
        XCTAssertFailure(
            transport.sendControl(Data([2])),
            expected: .controlBacklogExceeded(maximumBytes: 1)
        )

        XCTAssertFailure(
            try! XCTUnwrap(resurrectionResult),
            expected: .notConnected
        )
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(states.count, 1)
        guard case .failed = states[0] else {
            return XCTFail("Prepared failure must be the only published transition")
        }
        guard case .failed = transport.snapshot().state else {
            return XCTFail("Late connecting/connected callbacks must not revive a prepared failure")
        }
    }

    func testExplicitCloseSupersedesPreparedFailureNotification() {
        let engine = FakeWebRTCEngine()
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 1,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: 100
        )
        var transport: WebRTCInternetTransport!
        transport = connectedTransport(
            engine: engine,
            limits: limits,
            beforeFailureSideEffects: { transport.close() }
        )
        var states: [InternetTransportState] = []
        var reportedError: InternetTransportError?
        transport.onStateChanged = { states.append($0) }
        transport.onError = { reportedError = $0 }

        XCTAssertSuccess(transport.sendControl(Data([1])))
        XCTAssertFailure(
            transport.sendControl(Data([2])),
            expected: .controlBacklogExceeded(maximumBytes: 1)
        )

        XCTAssertEqual(transport.snapshot().state, .closed)
        XCTAssertEqual(states, [.closed])
        XCTAssertNil(reportedError)
        XCTAssertEqual(engine.closeCount, 1)
    }

    func testInitialControlSendRechecksGenerationAfterCloseBeforeEngineSend() {
        let engine = FakeWebRTCEngine()
        var transport: WebRTCInternetTransport!
        transport = connectedTransport(
            engine: engine,
            path: .relay,
            beforeControlSend: { transport.close() }
        )

        XCTAssertSuccess(transport.sendControl(Data([1])))

        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().state, .closed)
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(transport.snapshot().relayBytesSent, 0)
    }

    func testControlPreSendStateRejectionDropsQueueAndRelayReservations() {
        let engine = FakeWebRTCEngine()
        var rejectedFirstSend = false
        let transport = connectedTransport(
            engine: engine,
            path: .relay,
            beforeControlSend: {
                guard !rejectedFirstSend else { return }
                rejectedFirstSend = true
                engine.emitConnection(.connecting)
            }
        )

        XCTAssertSuccess(transport.sendControl(Data([1])))

        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().state, .connecting)
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)

        engine.emitConnection(.connected(path: .relay))
        XCTAssertSuccess(transport.sendControl(Data([2])))
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([2])])
    }

    func testQueuedRelayControlCannotCrossRestartGeneration() {
        let engine = FakeWebRTCEngine()
        var sendEntries = 0
        let transport = connectedTransport(
            engine: engine,
            path: .relay,
            beforeControlSend: {
                sendEntries += 1
                if sendEntries == 2 {
                    engine.emitPath(InternetNetworkPath(
                        interface: .cellular,
                        isSatisfied: true,
                        fingerprint: "cellular-b"
                    ))
                }
            }
        )
        engine.emitPath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))

        XCTAssertSuccess(transport.sendControl(Data([1])))
        XCTAssertSuccess(transport.sendControl(Data([2])))
        engine.completeSend(at: 0)

        let encryptedRecordBytes = UInt64(1 + PlatformSessionPacketCipher.recordOverhead)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(engine.restartICECount, 1)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(transport.snapshot().relayBytesSent, encryptedRecordBytes)
    }

    func testRecoveryTransitionSerializesControlAdmission() {
        let engine = FakeWebRTCEngine()
        let transitionEntered = DispatchSemaphore(value: 0)
        let releaseTransition = DispatchSemaphore(value: 0)
        let recoveryFinished = DispatchSemaphore(value: 0)
        let sendStarted = DispatchSemaphore(value: 0)
        let sendFinished = DispatchSemaphore(value: 0)
        let result = LockedTransportResult()
        let transport = connectedTransport(
            engine: engine,
            duringMediaRecoveryTransition: {
                transitionEntered.signal()
                _ = releaseTransition.wait(timeout: .now() + 2)
            }
        )

        DispatchQueue.global().async {
            engine.emitConnection(.disconnected)
            recoveryFinished.signal()
        }
        XCTAssertEqual(transitionEntered.wait(timeout: .now() + 2), .success)
        DispatchQueue.global().async {
            sendStarted.signal()
            result.store(transport.sendControl(Data([1])))
            sendFinished.signal()
        }
        XCTAssertEqual(sendStarted.wait(timeout: .now() + 2), .success)
        let admissionCompletedWithoutWaitingForCallback =
            sendFinished.wait(timeout: .now() + 0.1) == .success

        releaseTransition.signal()
        XCTAssertEqual(recoveryFinished.wait(timeout: .now() + 2), .success)
        XCTAssertTrue(admissionCompletedWithoutWaitingForCallback)
        XCTAssertFailure(try! XCTUnwrap(result.load()), expected: .notConnected)
        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
    }

    func testPathDecisionSerializesControlAdmissionBeforeGenerationInvalidation() {
        let engine = FakeWebRTCEngine()
        let decisionEntered = DispatchSemaphore(value: 0)
        let releaseDecision = DispatchSemaphore(value: 0)
        let pathChangeFinished = DispatchSemaphore(value: 0)
        let sendStarted = DispatchSemaphore(value: 0)
        let sendFinished = DispatchSemaphore(value: 0)
        let result = LockedTransportResult()
        let transport = connectedTransport(
            engine: engine,
            duringRecoveryDecision: {
                decisionEntered.signal()
                _ = releaseDecision.wait(timeout: .now() + 2)
            }
        )
        engine.emitPath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))

        DispatchQueue.global().async {
            engine.emitPath(InternetNetworkPath(
                interface: .cellular,
                isSatisfied: true,
                fingerprint: "cellular-b"
            ))
            pathChangeFinished.signal()
        }
        XCTAssertEqual(decisionEntered.wait(timeout: .now() + 2), .success)
        DispatchQueue.global().async {
            sendStarted.signal()
            result.store(transport.sendControl(Data([1])))
            sendFinished.signal()
        }
        XCTAssertEqual(sendStarted.wait(timeout: .now() + 2), .success)
        let admissionCompletedWithoutWaitingForCallback =
            sendFinished.wait(timeout: .now() + 0.1) == .success

        releaseDecision.signal()
        XCTAssertEqual(pathChangeFinished.wait(timeout: .now() + 2), .success)
        XCTAssertTrue(admissionCompletedWithoutWaitingForCallback)
        XCTAssertFailure(try! XCTUnwrap(result.load()), expected: .notConnected)
        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
    }

    func testQueuedEngineRejectsStaleControlBeforeSDKSendInDisconnectSendRestartOrder() throws {
        let engine = QueuedTransmissionWebRTCEngine()
        var triggeredDisconnect = false
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            beforeControlSend: {
                guard !triggeredDisconnect else { return }
                triggeredDisconnect = true
                XCTAssertTrue(engine.enqueueDisconnectAndWaitForHandling())
            }
        )
        try transport.start(configuration: validConfiguration())
        engine.connect(path: .relay)

        XCTAssertSuccess(transport.sendControl(Data([1])))
        XCTAssertTrue(engine.waitForEventCount(2))

        XCTAssertEqual(engine.events, ["D", "R"])
        XCTAssertTrue(engine.sentPlaintext.isEmpty)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(transport.snapshot().relayBytesSent, 0)

        engine.connect(path: .relay)
        XCTAssertSuccess(transport.sendControl(Data([2])))
        XCTAssertTrue(engine.waitForSentPayloadCount(1))
        XCTAssertEqual(engine.sentPlaintext.map(\.payload), [Data([2])])
    }

    func testMediaKeepsAtMostOneNewestPendingFrame() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let keyframe = frame(1, isKeyframe: true)
        let firstDelta = frame(2, isKeyframe: false)
        let newerDelta = frame(3, isKeyframe: false)

        XCTAssertSuccess(transport.sendMedia(keyframe))
        XCTAssertSuccess(transport.sendMedia(firstDelta))
        XCTAssertSuccess(transport.sendMedia(newerDelta))

        XCTAssertEqual(engine.sentPayloads.map(\.payload), keyframe.records)
        XCTAssertFalse(transport.snapshot().hasPendingMediaFrame)
        XCTAssertEqual(transport.snapshot().droppedMediaFrames, 2)
        XCTAssertEqual(engine.keyframeRequestCount, 2, "One request on connect and one after reference-chain invalidation")

        engine.completeSend(at: 0)
        XCTAssertEqual(engine.sentPayloads.count, 1)
        XCTAssertSuccess(transport.sendMedia(frame(4, isKeyframe: false)))
        XCTAssertEqual(engine.sentPayloads.count, 1, "Delta frames wait for the requested recovery point")
        let recoveryKeyframe = frame(5, isKeyframe: true)
        XCTAssertSuccess(transport.sendMedia(recoveryKeyframe))
        XCTAssertEqual(engine.sentPayloads.map(\.payload), keyframe.records + recoveryKeyframe.records)
    }

    func testNewerKeyframeReplacesPendingDeltaFrame() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let firstKeyframe = frame(1, isKeyframe: true)
        let delta = frame(2, isKeyframe: false)
        let newerKeyframe = frame(3, isKeyframe: true)

        XCTAssertSuccess(transport.sendMedia(firstKeyframe))
        XCTAssertSuccess(transport.sendMedia(delta))
        XCTAssertSuccess(transport.sendMedia(newerKeyframe))
        engine.completeSend(at: 0)

        XCTAssertEqual(
            engine.sentPayloads.map(\.payload),
            firstKeyframe.records + newerKeyframe.records
        )
        XCTAssertEqual(transport.snapshot().droppedMediaFrames, 1)
    }

    func testAudioRecordKeepsNewestPendingRealtimeRecord() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)

        XCTAssertSuccess(transport.sendAudioRecord(Data([1])))
        XCTAssertSuccess(transport.sendAudioRecord(Data([2])))
        XCTAssertSuccess(transport.sendAudioRecord(Data([3])))

        XCTAssertEqual(engine.sentPayloads.map(\.channel), [.audio])
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(transport.snapshot().droppedAudioRecords, 1)
        XCTAssertTrue(transport.snapshot().hasPendingAudioRecord)

        engine.completeSend(at: 0)

        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1]), Data([3])])
        engine.completeSend(at: 1)
        XCTAssertEqual(transport.snapshot().audioBytesSent, 2)
        XCTAssertFalse(transport.snapshot().audioInFlight)
    }

    func testAudioRecordRejectsOversizedPlaintextBeforeEngineSend() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let oversized = Data(
            repeating: 0x61,
            count: InternetAudioRecordContract.maximumPlaintextRecordBytes + 1
        )

        XCTAssertFailure(
            transport.sendAudioRecord(oversized),
            expected: .payloadTooLarge(
                channel: .audio,
                actual: oversized.count,
                maximum: InternetAudioRecordContract.maximumPlaintextRecordBytes
            )
        )
        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().audioBytesSent, 0)
    }

    func testBulkRecordsRemainReliableAndOrdered() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)

        XCTAssertSuccess(transport.sendBulkRecord(Data([1])))
        XCTAssertSuccess(transport.sendBulkRecord(Data([2])))
        XCTAssertSuccess(transport.sendBulkRecord(Data([3])))

        XCTAssertEqual(engine.sentPayloads.map(\.channel), [.bulk])
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(transport.snapshot().bufferedBulkMessages, 3)

        engine.completeSend(at: 0)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1]), Data([2])])
        engine.completeSend(at: 1)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1]), Data([2]), Data([3])])
        engine.completeSend(at: 2)

        XCTAssertEqual(transport.snapshot().bulkBytesSent, 3)
        XCTAssertEqual(transport.snapshot().bufferedBulkMessages, 0)
    }

    func testBulkRecordRejectsOversizedPlaintextBeforeEngineSend() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let oversized = Data(
            repeating: 0x62,
            count: InternetBulkRecordContract.maximumPlaintextRecordBytes + 1
        )

        XCTAssertFailure(
            transport.sendBulkRecord(oversized),
            expected: .payloadTooLarge(
                channel: .bulk,
                actual: oversized.count,
                maximum: InternetBulkRecordContract.maximumPlaintextRecordBytes
            )
        )
        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().bufferedBulkMessages, 0)
    }

    func testBulkBacklogByteLimitFailsClosed() {
        let engine = FakeWebRTCEngine()
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 8,
            maximumMediaFrameBytes: 8,
            maximumBufferedBulkBytes: 3,
            maximumBufferedBulkMessages: 64,
            maximumRelayBytesPerSession: 100
        )
        let transport = connectedTransport(engine: engine, limits: limits)

        XCTAssertSuccess(transport.sendBulkRecord(Data([1, 2])))
        XCTAssertFailure(
            transport.sendBulkRecord(Data([3, 4])),
            expected: .bulkBacklogExceeded(maximumBytes: 3)
        )
        guard case .failed = transport.snapshot().state else {
            return XCTFail("A reliable-bulk byte overflow must fail the session")
        }
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1, 2])])
        XCTAssertTrue(engine.didClose)
    }

    func testBulkBacklogEntryCountFailsClosed() {
        let engine = FakeWebRTCEngine()
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 8,
            maximumMediaFrameBytes: 8,
            maximumBufferedBulkBytes: 64,
            maximumBufferedBulkMessages: 2,
            maximumRelayBytesPerSession: 100
        )
        let transport = connectedTransport(engine: engine, limits: limits)

        XCTAssertSuccess(transport.sendBulkRecord(Data([1])))
        XCTAssertSuccess(transport.sendBulkRecord(Data([2])))
        XCTAssertEqual(transport.snapshot().bufferedBulkMessages, 2)
        XCTAssertFailure(
            transport.sendBulkRecord(Data([3])),
            expected: .bulkBacklogExceeded(maximumBytes: 64)
        )
        guard case .failed = transport.snapshot().state else {
            return XCTFail("A reliable-bulk entry overflow must fail closed")
        }
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertTrue(engine.didClose)
    }

    func testInboundAudioAndBulkRecordsAreDeliveredAsRawTransportRecords() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        var audio: [Data] = []
        var bulk: [Data] = []
        transport.onAudioRecordReceived = { audio.append($0) }
        transport.onBulkRecordReceived = { bulk.append($0) }

        engine.receiveRaw(engine.makeInboundRecord(Data([4]), channel: .audio), channel: .audio)
        engine.receiveRaw(engine.makeInboundRecord(Data([5]), channel: .bulk), channel: .bulk)

        XCTAssertEqual(audio, [Data([4])])
        XCTAssertEqual(bulk, [Data([5])])
    }

    func testFragmentedMediaSendsCompleteFrameBatchBeforeNewestReplacement() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let first = fragmentedFrame([1, 2, 3], isKeyframe: true)
        let replacement = fragmentedFrame([4, 5], isKeyframe: true)

        XCTAssertSuccess(transport.sendMedia(first))
        XCTAssertSuccess(transport.sendMedia(replacement))
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [first.records[0]])

        engine.completeSend(at: 0)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), Array(first.records.prefix(2)))
        engine.completeSend(at: 1)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), first.records)
        engine.completeSend(at: 2)
        XCTAssertEqual(
            engine.sentPayloads.map(\.payload),
            first.records + [replacement.records[0]]
        )
        engine.completeSend(at: 3)
        XCTAssertEqual(
            engine.sentPayloads.map(\.payload),
            first.records + replacement.records
        )
    }

    func testFragmentFailureSkipsOldRemainderBeforePendingKeyframeBatch() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let first = fragmentedFrame([1, 2, 3], isKeyframe: true)
        let replacement = fragmentedFrame([4, 5], isKeyframe: true)

        XCTAssertSuccess(transport.sendMedia(first))
        XCTAssertSuccess(transport.sendMedia(replacement))
        engine.completeSend(at: 0)
        engine.completeSend(at: 1, result: .failure(TestError.sendFailed))

        XCTAssertEqual(
            engine.sentPayloads.map(\.payload),
            [first.records[0], first.records[1], replacement.records[0]],
            "A failed frame must not send its remaining fragments before the pending keyframe"
        )
        engine.completeSend(at: 2)
        XCTAssertEqual(
            engine.sentPayloads.map(\.payload),
            [first.records[0], first.records[1]] + replacement.records
        )
        XCTAssertEqual(transport.snapshot().droppedMediaFrames, 1)
    }

    func testInitialMediaSendRechecksGenerationAfterCloseBeforeEngineSend() {
        let engine = FakeWebRTCEngine()
        var transport: WebRTCInternetTransport!
        transport = connectedTransport(
            engine: engine,
            beforeMediaRecordSend: { transport.close() }
        )

        XCTAssertSuccess(transport.sendMedia(fragmentedFrame([1, 2], isKeyframe: true)))

        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().state, .closed)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
    }

    func testRestartBetweenSelectedFragmentsPreventsOldFrameContinuation() {
        let engine = FakeWebRTCEngine()
        var sendEntries = 0
        let transport = connectedTransport(
            engine: engine,
            beforeMediaRecordSend: {
                sendEntries += 1
                if sendEntries == 2 {
                    engine.emitPath(InternetNetworkPath(
                        interface: .cellular,
                        isSatisfied: true,
                        fingerprint: "cellular-b"
                    ))
                }
            }
        )
        engine.emitPath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))

        XCTAssertSuccess(transport.sendMedia(fragmentedFrame([1, 2, 3], isKeyframe: true)))
        engine.completeSend(at: 0)

        let first = fragmentedFrame([1, 2, 3], isKeyframe: true)
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [first.records[0]])
        XCTAssertEqual(engine.restartICECount, 1)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
    }

    func testRecoveryTransitionSerializesAdmissionAndLeavesPipelineReusable() {
        let engine = FakeWebRTCEngine()
        let transitionEntered = DispatchSemaphore(value: 0)
        let releaseTransition = DispatchSemaphore(value: 0)
        let recoveryFinished = DispatchSemaphore(value: 0)
        let sendStarted = DispatchSemaphore(value: 0)
        let sendFinished = DispatchSemaphore(value: 0)
        let result = LockedTransportResult()
        let transport = connectedTransport(
            engine: engine,
            duringMediaRecoveryTransition: {
                transitionEntered.signal()
                _ = releaseTransition.wait(timeout: .now() + 2)
            }
        )
        let recoveryFrame = frame(1, isKeyframe: true)

        DispatchQueue.global().async {
            engine.emitConnection(.disconnected)
            recoveryFinished.signal()
        }
        XCTAssertEqual(transitionEntered.wait(timeout: .now() + 2), .success)
        DispatchQueue.global().async {
            sendStarted.signal()
            result.store(transport.sendMedia(recoveryFrame))
            sendFinished.signal()
        }
        XCTAssertEqual(sendStarted.wait(timeout: .now() + 2), .success)
        let admissionCompletedWithoutWaitingForCallback =
            sendFinished.wait(timeout: .now() + 0.1) == .success

        releaseTransition.signal()
        XCTAssertEqual(recoveryFinished.wait(timeout: .now() + 2), .success)
        XCTAssertTrue(admissionCompletedWithoutWaitingForCallback)
        XCTAssertFailure(try! XCTUnwrap(result.load()), expected: .notConnected)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertFalse(transport.snapshot().hasPendingMediaFrame)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)

        engine.emitConnection(.connected(path: .direct))
        XCTAssertSuccess(transport.sendMedia(frame(2, isKeyframe: true)))
        XCTAssertEqual(engine.sentPayloads.map(\.payload), frame(2, isKeyframe: true).records)
    }

    func testPreSendStateRejectionRollsBackRelayReservationAndInFlightState() {
        let engine = FakeWebRTCEngine()
        var transport: WebRTCInternetTransport!
        var rejectedFirstSend = false
        transport = connectedTransport(
            engine: engine,
            path: .relay,
            beforeMediaRecordSend: {
                guard !rejectedFirstSend else { return }
                rejectedFirstSend = true
                engine.emitConnection(.connecting)
            }
        )

        XCTAssertSuccess(transport.sendMedia(frame(1, isKeyframe: true)))
        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertFalse(transport.snapshot().hasPendingMediaFrame)

        engine.emitConnection(.connected(path: .relay))
        let recoveryFrame = frame(2, isKeyframe: true)
        XCTAssertSuccess(transport.sendMedia(recoveryFrame))
        XCTAssertEqual(engine.sentPayloads.map(\.payload), recoveryFrame.records)
    }

    func testQueuedEngineRejectsStaleMediaBeforeSDKSendInDisconnectSendRestartOrder() throws {
        let engine = QueuedTransmissionWebRTCEngine()
        var triggeredDisconnect = false
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            beforeMediaRecordSend: {
                guard !triggeredDisconnect else { return }
                triggeredDisconnect = true
                XCTAssertTrue(engine.enqueueDisconnectAndWaitForHandling())
            }
        )
        try transport.start(configuration: validConfiguration())
        engine.connect(path: .relay)

        XCTAssertSuccess(transport.sendMedia(frame(1, isKeyframe: true)))
        XCTAssertTrue(engine.waitForEventCount(2))

        XCTAssertEqual(engine.events, ["D", "R"])
        XCTAssertTrue(engine.sentPlaintext.isEmpty)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertFalse(transport.snapshot().hasPendingMediaFrame)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(transport.snapshot().relayBytesSent, 0)

        engine.connect(path: .relay)
        let currentFrame = frame(2, isKeyframe: true)
        XCTAssertSuccess(transport.sendMedia(currentFrame))
        XCTAssertTrue(engine.waitForSentPayloadCount(1))
        XCTAssertEqual(engine.sentPlaintext.map(\.payload), currentFrame.records)
    }

    func testRecoveringTransportRejectsAuthenticatedLateInboundControlAndMedia() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        let lateControl = engine.makeInboundRecord(Data([1]), channel: .control)
        let lateMedia = engine.makeInboundRecord(Data([2]), channel: .media)
        var controls: [Data] = []
        var media: [Data] = []
        transport.onControlReceived = { controls.append($0) }
        transport.onMediaReceived = { media.append($0) }

        engine.emitConnection(.disconnected)
        engine.receiveRaw(lateControl, channel: .control)
        engine.receiveRaw(lateMedia, channel: .media)

        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertTrue(controls.isEmpty)
        XCTAssertTrue(media.isEmpty)
    }

    func testRecoveryExhaustionWithoutFreshSessionCallbackClosesEngineAndRejectsReconnectAndLateInbound() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .direct))
        let lateControl = engine.makeInboundRecord(Data([1]), channel: .control)
        let lateMedia = engine.makeInboundRecord(Data([2]), channel: .media)
        var controls: [Data] = []
        var media: [Data] = []
        transport.onControlReceived = { controls.append($0) }
        transport.onMediaReceived = { media.append($0) }

        engine.emitConnection(.disconnected)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(engine.restartICECount, 1)
        engine.emitConnection(.connecting)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        engine.emitConnection(.disconnected)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 2))
        XCTAssertEqual(engine.restartICECount, 2)
        engine.emitConnection(.connecting)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 2))
        engine.emitConnection(.disconnected)

        guard case .failed(let reason) = transport.snapshot().state else {
            return XCTFail("Recovery exhaustion must fail the transport")
        }
        XCTAssertTrue(reason.contains("ICE recovery exhausted after 2 attempts"))
        XCTAssertTrue(engine.didClose)
        XCTAssertEqual(engine.restartICECount, 2)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)

        engine.emitConnection(.connected(path: .direct))
        engine.receiveRaw(lateControl, channel: .control)
        engine.receiveRaw(lateMedia, channel: .media)

        XCTAssertTrue(controls.isEmpty)
        XCTAssertTrue(media.isEmpty)
        XCTAssertFailure(transport.sendControl(Data([3])), expected: .notConnected)
        XCTAssertFailure(transport.sendMedia(frame(3, isKeyframe: true)), expected: .notConnected)
        XCTAssertTrue(engine.sentPayloads.isEmpty)
    }

    func testRecoveryExhaustionRequestsFreshSessionWhenCallbackIsInstalled() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        var recoveryAttempts: [Int] = []
        transport.onFreshSessionRecoveryRequired = { recoveryAttempts.append($0) }
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .direct))

        engine.emitConnection(.disconnected)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(engine.restartICECount, 1)
        engine.emitConnection(.connecting)
        engine.emitConnection(.disconnected)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 2))
        XCTAssertEqual(engine.restartICECount, 2)
        engine.emitConnection(.connecting)
        engine.emitConnection(.disconnected)

        XCTAssertEqual(recoveryAttempts, [2])
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 2))
        XCTAssertFalse(engine.didClose)
        XCTAssertEqual(engine.restartICECount, 2)
        XCTAssertFailure(transport.sendControl(Data([3])), expected: .notConnected)
    }

    func testPathChangesDuringRecoveryDoNotConsumeRecoveryBudget() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .direct))
        engine.emitPath(.init(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        engine.emitConnection(.disconnected)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))

        engine.emitPath(.init(interface: .cellular, isSatisfied: true, fingerprint: "cell-b"))
        engine.emitPath(.init(interface: .wiredEthernet, isSatisfied: true, fingerprint: "ethernet-c"))

        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(engine.restartICECount, 1)
        engine.emitConnection(.disconnected)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 2))
        XCTAssertEqual(engine.restartICECount, 2)
    }

    func testExhaustedPathRecoveryActionFailsInsteadOfBeingDropped() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 0)
        )
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .direct))
        engine.emitPath(.init(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        engine.emitPath(.init(interface: .wiredEthernet, isSatisfied: true, fingerprint: "ethernet-b"))

        guard case .failed(let reason) = transport.snapshot().state else {
            return XCTFail("An exhausted path recovery action must fail closed")
        }
        XCTAssertTrue(reason.contains("ICE recovery exhausted after 0 attempts"))
        XCTAssertTrue(engine.didClose)
        XCTAssertEqual(engine.restartICECount, 0)
    }

    func testFreshSessionRecoveryDoesNotCountPeerReplacement() throws {
        let engine = FakeWebRTCEngine(
            recoveryDisposition: .requiresFreshSession("fresh signaling session required")
        )
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        var recoveryAttempts: [Int] = []
        transport.onFreshSessionRecoveryRequired = { recoveryAttempts.append($0) }
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .direct))

        engine.emitConnection(.disconnected)

        XCTAssertEqual(recoveryAttempts, [1])
        XCTAssertEqual(engine.restartICECount, 1)
        XCTAssertEqual(transport.snapshot().iceRestartCount, 0)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertFailure(transport.sendControl(Data([1])), expected: .notConnected)
    }

    func testStaleICEAndPeerDelegateOutcomesDoNotConsumeCurrentRecoveryBudget() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .direct))
        let initialGeneration = engine.currentPeerDelegateGeneration

        engine.emitDelegateConnection(
            .disconnected,
            source: .iceConnection,
            generation: initialGeneration
        )
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(engine.restartICECount, 1)
        let firstAttemptGeneration = engine.currentPeerDelegateGeneration

        for source in TestPeerDelegateSource.allCases {
            engine.emitDelegateConnection(
                .disconnected,
                source: source,
                generation: initialGeneration
            )
            engine.emitDelegateConnection(
                .failed("stale (source) failure"),
                source: source,
                generation: initialGeneration
            )
        }

        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(engine.restartICECount, 1)
        XCTAssertFalse(engine.didClose)

        engine.emitDelegateConnection(
            .disconnected,
            source: .peerConnection,
            generation: firstAttemptGeneration
        )

        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 2))
        XCTAssertEqual(engine.restartICECount, 2)
        let secondAttemptGeneration = engine.currentPeerDelegateGeneration

        engine.emitDelegateConnection(
            .failed("stale first-attempt ICE failure"),
            source: .iceConnection,
            generation: firstAttemptGeneration
        )
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 2))
        XCTAssertFalse(engine.didClose)

        engine.emitDelegateConnection(
            .connected(path: .direct),
            source: .iceConnection,
            generation: secondAttemptGeneration
        )

        XCTAssertEqual(transport.snapshot().state, .connected(.direct))
        XCTAssertEqual(engine.restartICECount, 2)
        XCTAssertFalse(engine.didClose)
    }

    func testCurrentReplacementPeerFailureFailsClosed() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .direct))
        let initialGeneration = engine.currentPeerDelegateGeneration

        engine.emitDelegateConnection(
            .disconnected,
            source: .iceConnection,
            generation: initialGeneration
        )
        let currentGeneration = engine.currentPeerDelegateGeneration
        engine.emitDelegateConnection(
            .failed("stale failure"),
            source: .peerConnection,
            generation: initialGeneration
        )
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertFalse(engine.didClose)

        engine.emitDelegateConnection(
            .failed("current failure"),
            source: .peerConnection,
            generation: currentGeneration
        )

        guard case .failed(let reason) = transport.snapshot().state else {
            return XCTFail("The current attempt failure must fail closed")
        }
        XCTAssertTrue(reason.contains("current failure"))
        XCTAssertTrue(engine.didClose)
        XCTAssertEqual(engine.restartICECount, 1)
    }

    func testLocalRecoveryConnectionAttemptDeadlineConsumesBudgetAndFailsClosed() throws {
        let engine = FakeWebRTCEngine()
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            recoveryPolicy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )
        try transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: .direct))
        let initialGeneration = engine.currentPeerDelegateGeneration

        engine.emitDelegateConnection(
            .disconnected,
            source: .iceConnection,
            generation: initialGeneration
        )
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(engine.restartICECount, 1)

        engine.fireRestartProgressTimeout()
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 2))
        XCTAssertEqual(engine.restartICECount, 2)
        engine.fireRestartProgressTimeout()

        guard case .failed(let reason) = transport.snapshot().state else {
            return XCTFail("Connection-attempt deadline must eventually exhaust recovery")
        }
        XCTAssertTrue(reason.contains("ICE recovery exhausted after 2 attempts"))
        XCTAssertTrue(engine.didClose)
        XCTAssertEqual(engine.restartICECount, 2)
    }

    func testRelayFragmentFailureAndPendingReplacementRollBackEncryptedReservations() {
        let engine = FakeWebRTCEngine()
        let first = fragmentedFrame([1, 2, 3], isKeyframe: true)
        let stale = fragmentedFrame([4, 5], isKeyframe: true)
        let latest = fragmentedFrame([6, 7], isKeyframe: true)
        let failedRecordBytes = InternetMediaRecordContract.encryptedRecordBytes(
            forPlaintextBytes: first.records[1].count
        )
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 8,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: first.totalEncryptedRecordBytes + latest.totalEncryptedRecordBytes
        )
        let transport = connectedTransport(engine: engine, limits: limits, path: .relay)

        XCTAssertSuccess(transport.sendMedia(first))
        XCTAssertSuccess(transport.sendMedia(stale))
        XCTAssertSuccess(transport.sendMedia(latest))
        XCTAssertEqual(
            transport.snapshot().relayBytesReserved,
            first.totalEncryptedRecordBytes + latest.totalEncryptedRecordBytes
        )

        engine.completeSend(at: 0)
        engine.completeSend(at: 1, result: .failure(TestError.sendFailed))
        XCTAssertEqual(
            engine.sentPayloads.map(\.payload),
            [first.records[0], first.records[1], latest.records[0]]
        )
        XCTAssertEqual(transport.snapshot().relayBytesReserved, latest.totalEncryptedRecordBytes)
        let firstSentRecordBytes = InternetMediaRecordContract.encryptedRecordBytes(
            forPlaintextBytes: first.records[0].count
        )
        XCTAssertEqual(transport.snapshot().relayBytesSent, firstSentRecordBytes)

        engine.completeSend(at: 2)
        engine.completeSend(at: 3)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(
            transport.snapshot().relayBytesSent,
            firstSentRecordBytes + latest.totalEncryptedRecordBytes
        )
        XCTAssertEqual(
            UInt64(engine.sentPayloads.reduce(0) { $0 + $1.networkBytes }),
            transport.snapshot().relayBytesSent + failedRecordBytes
        )
    }

    func testMaximumPlaintextMediaRecordSealsAtAndroidEncryptedLimit() throws {
        let ciphers = makeCipherPair()
        defer {
            ciphers.host.close()
            ciphers.device.close()
        }
        let plaintext = Data(
            repeating: 0x41,
            count: InternetMediaRecordContract.maximumPlaintextRecordBytes
        )

        let record = try ciphers.host.seal(plaintext, channel: .media)

        XCTAssertEqual(record.count, InternetMediaRecordContract.maximumEncryptedRecordBytes)
        XCTAssertEqual(ciphers.device.open(record, channel: .media), plaintext)
    }

    func testFailedMediaSendDropsPendingDeltaAndRequestsRecoveryPoint() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)

        XCTAssertSuccess(transport.sendMedia(frame(1, isKeyframe: true)))
        XCTAssertSuccess(transport.sendMedia(frame(2, isKeyframe: false)))
        engine.completeSend(at: 0, result: .failure(TestError.sendFailed))

        XCTAssertEqual(engine.sentPayloads.count, 1)
        XCTAssertFalse(transport.snapshot().hasPendingMediaFrame)
        XCTAssertEqual(transport.snapshot().droppedMediaFrames, 2)
        XCTAssertEqual(engine.keyframeRequestCount, 2)
    }

    func testNetworkSwitchRestartsICEAndRequiresFreshKeyframe() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        engine.emitPath(InternetNetworkPath(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        engine.emitPath(InternetNetworkPath(interface: .cellular, isSatisfied: true, fingerprint: "cell-b"))

        XCTAssertEqual(engine.restartICECount, 1)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))
        XCTAssertEqual(transport.snapshot().iceRestartCount, 1)
        XCTAssertFailure(
            transport.sendMedia(frame(2, isKeyframe: false)),
            expected: .notConnected
        )

        engine.emitConnection(.connected(path: .relay))
        XCTAssertEqual(transport.snapshot().state, .connected(.relay))
        XCTAssertEqual(engine.keyframeRequestCount, 2)
    }

    func testRepeatedCurrentDisconnectOutcomeAdvancesOnceAndPathEventDoesNotAddRestart() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        engine.emitPath(InternetNetworkPath(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        engine.emitConnection(.disconnected)

        XCTAssertEqual(engine.restartICECount, 1)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 1))

        engine.emitConnection(.disconnected)

        XCTAssertEqual(engine.restartICECount, 2)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 2))

        engine.emitPath(InternetNetworkPath(interface: .cellular, isSatisfied: true, fingerprint: "cell-b"))

        XCTAssertEqual(engine.restartICECount, 2)
        XCTAssertEqual(transport.snapshot().state, .recovering(attempt: 2))
    }

    func testNetworkSwitchInvalidatesOldSendCompletionsAndQueues() {
        let engine = FakeWebRTCEngine()
        let transport = connectedTransport(engine: engine)
        XCTAssertSuccess(transport.sendControl(Data([1])))
        XCTAssertSuccess(transport.sendControl(Data([2])))

        engine.emitPath(InternetNetworkPath(interface: .wifi, isSatisfied: true, fingerprint: "wifi-a"))
        engine.emitPath(InternetNetworkPath(interface: .cellular, isSatisfied: true, fingerprint: "cell-b"))
        engine.completeSend(at: 0)

        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
        XCTAssertEqual(transport.snapshot().bufferedControlBytes, 0)

        engine.emitConnection(.connected(path: .direct))
        XCTAssertSuccess(transport.sendControl(Data([3])))
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1]), Data([3])])
    }

    func testRecoveryStateMachineStopsAfterConfiguredAttempts() {
        var recovery = NetworkRecoveryStateMachine(
            policy: NetworkRecoveryPolicy(maximumAttempts: 2)
        )

        XCTAssertEqual(recovery.connectivityLost(), .restartICE)
        XCTAssertEqual(recovery.connectivityLost(), .restartICE)
        XCTAssertEqual(
            recovery.connectivityLost(),
            .fail("ICE recovery exhausted after 2 attempts.")
        )
    }

    func testAdaptivePolicyDowngradesQuicklyAndUpgradesConservatively() {
        let policy = AdaptiveMediaPolicy(
            observationsBeforeDowngrade: 2,
            observationsBeforeUpgrade: 4
        )
        let poor = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 500,
            packetLossFraction: 0.2,
            availableOutgoingBitrateBps: 2_000_000
        )
        let healthy = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 50,
            packetLossFraction: 0,
            availableOutgoingBitrateBps: 30_000_000
        )

        XCTAssertNil(policy.observe(poor))
        XCTAssertEqual(policy.observe(poor), AdaptiveMediaPolicy.constrained)
        XCTAssertNil(policy.observe(healthy))
        XCTAssertNil(policy.observe(healthy))
        XCTAssertNil(policy.observe(healthy))
        XCTAssertEqual(policy.observe(healthy), AdaptiveMediaPolicy.highQuality)
    }

    func testAdaptivePolicyResetsObservationCountWhenCandidateChanges() {
        let policy = AdaptiveMediaPolicy(
            observationsBeforeDowngrade: 2,
            observationsBeforeUpgrade: 4
        )
        let constrainedSample = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 500,
            packetLossFraction: 0.2,
            availableOutgoingBitrateBps: 2_000_000
        )
        let balancedSample = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 300,
            packetLossFraction: 0.06,
            availableOutgoingBitrateBps: 5_000_000
        )

        // First constrained observation starts the downgrade count.
        XCTAssertNil(policy.observe(constrainedSample))
        // Switching to a different candidate resets the count.
        XCTAssertNil(policy.observe(balancedSample))
        // Returning to constrained restarts the count at 1, not 2.
        XCTAssertNil(policy.observe(constrainedSample))
        // The second consecutive constrained observation finally downgrades.
        XCTAssertEqual(policy.observe(constrainedSample), AdaptiveMediaPolicy.constrained)
    }

    func testAdaptivePolicyRetriesRejectedProfileAgainstAcknowledgedState() {
        let policy = AdaptiveMediaPolicy(
            observationsBeforeDowngrade: 2,
            observationsBeforeUpgrade: 4
        )
        let poor = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 500,
            packetLossFraction: 0.2,
            availableOutgoingBitrateBps: 2_000_000
        )

        XCTAssertNil(policy.observe(poor))
        XCTAssertEqual(policy.observe(poor), AdaptiveMediaPolicy.constrained)
        XCTAssertEqual(policy.currentProfile, AdaptiveMediaPolicy.constrained)
        XCTAssertEqual(policy.acknowledgedProfile, AdaptiveMediaPolicy.highQuality)

        policy.reject(AdaptiveMediaPolicy.constrained)
        XCTAssertEqual(policy.currentProfile, AdaptiveMediaPolicy.highQuality)
        XCTAssertNil(policy.observe(poor))
        XCTAssertEqual(policy.observe(poor), AdaptiveMediaPolicy.constrained)

        policy.commit(AdaptiveMediaPolicy.constrained)
        XCTAssertEqual(policy.acknowledgedProfile, AdaptiveMediaPolicy.constrained)
        XCTAssertNil(policy.observe(poor))
    }

    func testRejectingOlderProfilePreservesNewerQueuedDecision() {
        let policy = AdaptiveMediaPolicy(
            observationsBeforeDowngrade: 2,
            observationsBeforeUpgrade: 4
        )
        let constrained = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 500,
            packetLossFraction: 0.2,
            availableOutgoingBitrateBps: 2_000_000
        )
        let balanced = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 300,
            packetLossFraction: 0.06,
            availableOutgoingBitrateBps: 5_000_000
        )

        XCTAssertNil(policy.observe(constrained))
        XCTAssertEqual(policy.observe(constrained), AdaptiveMediaPolicy.constrained)
        for _ in 0..<3 { XCTAssertNil(policy.observe(balanced)) }
        XCTAssertEqual(policy.observe(balanced), AdaptiveMediaPolicy.balanced)

        policy.reject(AdaptiveMediaPolicy.constrained)
        XCTAssertEqual(policy.currentProfile, AdaptiveMediaPolicy.balanced)
        XCTAssertEqual(policy.acknowledgedProfile, AdaptiveMediaPolicy.highQuality)
    }

    func testAdaptivePolicyTreatsNonFiniteTelemetryAsConstrained() {
        let nanLoss = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 50,
            packetLossFraction: .nan,
            availableOutgoingBitrateBps: 30_000_000
        )
        let nanRTT = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: .nan,
            packetLossFraction: 0,
            availableOutgoingBitrateBps: 30_000_000
        )
        let infiniteLoss = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 50,
            packetLossFraction: .infinity,
            availableOutgoingBitrateBps: 30_000_000
        )
        let negativeRTT = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: -1,
            packetLossFraction: 0,
            availableOutgoingBitrateBps: 30_000_000
        )
        let negativeLoss = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 50,
            packetLossFraction: -0.01,
            availableOutgoingBitrateBps: 30_000_000
        )

        // Non-finite telemetry must never map to highQuality.
        XCTAssertEqual(AdaptiveMediaPolicy.profile(for: nanLoss), AdaptiveMediaPolicy.constrained)
        XCTAssertEqual(AdaptiveMediaPolicy.profile(for: nanRTT), AdaptiveMediaPolicy.constrained)
        XCTAssertEqual(AdaptiveMediaPolicy.profile(for: infiniteLoss), AdaptiveMediaPolicy.constrained)
        XCTAssertEqual(AdaptiveMediaPolicy.profile(for: negativeRTT), AdaptiveMediaPolicy.constrained)
        XCTAssertEqual(AdaptiveMediaPolicy.profile(for: negativeLoss), AdaptiveMediaPolicy.constrained)

        // A single NaN observation must be able to downgrade from highQuality.
        let policy = AdaptiveMediaPolicy(
            observationsBeforeDowngrade: 1,
            observationsBeforeUpgrade: 1
        )
        XCTAssertEqual(policy.observe(nanLoss), AdaptiveMediaPolicy.constrained)
        XCTAssertEqual(policy.currentProfile, AdaptiveMediaPolicy.constrained)
    }

    func testAdaptivePolicyDoesNotReachHighQualityWithMissingRTT() {
        let missingRTT = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 0,
            packetLossFraction: 0,
            availableOutgoingBitrateBps: 30_000_000
        )

        // rtt == 0 is treated as a missing measurement; the candidate is
        // capped at good and must never be highQuality.
        XCTAssertEqual(AdaptiveMediaPolicy.profile(for: missingRTT), AdaptiveMediaPolicy.good)

        let policy = AdaptiveMediaPolicy(
            observationsBeforeDowngrade: 1,
            observationsBeforeUpgrade: 1
        )
        XCTAssertEqual(policy.observe(missingRTT), AdaptiveMediaPolicy.good)
        XCTAssertEqual(policy.currentProfile, AdaptiveMediaPolicy.good)

        // A subsequent real RTT sample can still promote to highQuality.
        let realRTT = InternetNetworkQualitySample(
            roundTripTimeMilliseconds: 50,
            packetLossFraction: 0,
            availableOutgoingBitrateBps: 30_000_000
        )
        XCTAssertEqual(policy.observe(realRTT), AdaptiveMediaPolicy.highQuality)
    }

    func testAdaptivePolicyProfileThresholdBoundaries() {
        // loss boundaries
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 50,
                packetLossFraction: 0.12,
                availableOutgoingBitrateBps: 30_000_000
            )),
            AdaptiveMediaPolicy.constrained
        )
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 50,
                packetLossFraction: 0.05,
                availableOutgoingBitrateBps: 30_000_000
            )),
            AdaptiveMediaPolicy.balanced
        )
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 50,
                packetLossFraction: 0.02,
                availableOutgoingBitrateBps: 30_000_000
            )),
            AdaptiveMediaPolicy.good
        )
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 50,
                packetLossFraction: 0.019,
                availableOutgoingBitrateBps: 30_000_000
            )),
            AdaptiveMediaPolicy.highQuality
        )

        // rtt boundaries
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 450,
                packetLossFraction: 0,
                availableOutgoingBitrateBps: 30_000_000
            )),
            AdaptiveMediaPolicy.constrained
        )
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 250,
                packetLossFraction: 0,
                availableOutgoingBitrateBps: 30_000_000
            )),
            AdaptiveMediaPolicy.balanced
        )
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 150,
                packetLossFraction: 0,
                availableOutgoingBitrateBps: 30_000_000
            )),
            AdaptiveMediaPolicy.good
        )
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 149,
                packetLossFraction: 0,
                availableOutgoingBitrateBps: 30_000_000
            )),
            AdaptiveMediaPolicy.highQuality
        )

        // bitrate boundaries
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 50,
                packetLossFraction: 0,
                availableOutgoingBitrateBps: 2_999_999
            )),
            AdaptiveMediaPolicy.constrained
        )
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 50,
                packetLossFraction: 0,
                availableOutgoingBitrateBps: 6_999_999
            )),
            AdaptiveMediaPolicy.balanced
        )
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 50,
                packetLossFraction: 0,
                availableOutgoingBitrateBps: 13_999_999
            )),
            AdaptiveMediaPolicy.good
        )
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 50,
                packetLossFraction: 0,
                availableOutgoingBitrateBps: 14_000_000
            )),
            AdaptiveMediaPolicy.highQuality
        )

        // bitrate == 0 stays constrained even with otherwise-perfect metrics.
        XCTAssertEqual(
            AdaptiveMediaPolicy.profile(for: InternetNetworkQualitySample(
                roundTripTimeMilliseconds: 50,
                packetLossFraction: 0,
                availableOutgoingBitrateBps: 0
            )),
            AdaptiveMediaPolicy.constrained
        )
    }

    func testRelayBudgetStopsMediaAndSnapshotSeparatesRelayBytes() {
        let engine = FakeWebRTCEngine()
        let first = frame(1, isKeyframe: true)
        let encryptedRecordBytes = first.totalEncryptedRecordBytes
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 8,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: encryptedRecordBytes
        )
        let transport = connectedTransport(engine: engine, limits: limits, path: .relay)
        XCTAssertSuccess(transport.sendMedia(first))
        XCTAssertEqual(transport.snapshot().relayBytesReserved, encryptedRecordBytes)

        XCTAssertFailure(
            transport.sendMedia(encodedFrame(
                payloads: [Data([2, 3])],
                captureTimestamp: 2,
                isKeyframe: true
            )),
            expected: .relayBudgetExceeded(maximumBytes: encryptedRecordBytes)
        )
        engine.completeSend(at: 0)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(transport.snapshot().relayBytesSent, encryptedRecordBytes)
        XCTAssertEqual(engine.sentPayloads[0].networkBytes, Int(encryptedRecordBytes))
    }

    func testRelayBudgetRejectKeepsRecoveryKeyframeGateClosedForDelta() {
        let engine = FakeWebRTCEngine()
        let keyframe = frame(1, isKeyframe: true)
        let encryptedRecordBytes = keyframe.totalEncryptedRecordBytes
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 8,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: encryptedRecordBytes - 1
        )
        let transport = connectedTransport(engine: engine, limits: limits, path: .relay)

        XCTAssertFailure(
            transport.sendMedia(keyframe),
            expected: .relayBudgetExceeded(maximumBytes: encryptedRecordBytes - 1)
        )
        XCTAssertSuccess(transport.sendMedia(frame(2, isKeyframe: false)))

        XCTAssertTrue(engine.sentPayloads.isEmpty)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(transport.snapshot().droppedMediaFrames, 1)
        XCTAssertEqual(engine.keyframeRequestCount, 1, "The connection's recovery keyframe request remains outstanding")
    }

    func testRelayBudgetAndTelemetryCountSealedControlRecordBytes() {
        let engine = FakeWebRTCEngine()
        let encryptedRecordBytes = UInt64(1 + PlatformSessionPacketCipher.recordOverhead)
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 8,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: encryptedRecordBytes
        )
        let transport = connectedTransport(engine: engine, limits: limits, path: .relay)

        XCTAssertSuccess(transport.sendControl(Data([1])))
        XCTAssertEqual(transport.snapshot().relayBytesReserved, encryptedRecordBytes)
        XCTAssertFailure(
            transport.sendControl(Data([2])),
            expected: .relayBudgetExceeded(maximumBytes: encryptedRecordBytes)
        )

        engine.completeSend(at: 0)
        XCTAssertEqual(transport.snapshot().controlBytesSent, 1)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(transport.snapshot().relayBytesSent, encryptedRecordBytes)
        XCTAssertEqual(engine.sentPayloads[0].networkBytes, Int(encryptedRecordBytes))
    }

    func testStaleRelayControlCompletionRetainsAndConsumesGlobalQuota() {
        let engine = FakeWebRTCEngine()
        let encryptedRecordBytes = UInt64(1 + PlatformSessionPacketCipher.recordOverhead)
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 8,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: encryptedRecordBytes
        )
        let transport = connectedTransport(engine: engine, limits: limits, path: .relay)

        XCTAssertSuccess(transport.sendControl(Data([1])))
        engine.emitPath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))
        engine.emitPath(InternetNetworkPath(
            interface: .cellular,
            isSatisfied: true,
            fingerprint: "cellular-b"
        ))
        XCTAssertEqual(transport.snapshot().relayBytesReserved, encryptedRecordBytes)

        engine.emitConnection(.connected(path: .relay))
        XCTAssertFailure(
            transport.sendControl(Data([2])),
            expected: .relayBudgetExceeded(maximumBytes: encryptedRecordBytes)
        )

        engine.completeSend(at: 0)
        XCTAssertEqual(transport.snapshot().controlBytesSent, 1)
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(transport.snapshot().relayBytesSent, encryptedRecordBytes)

        XCTAssertFailure(
            transport.sendControl(Data([2])),
            expected: .relayBudgetExceeded(maximumBytes: encryptedRecordBytes)
        )
        XCTAssertEqual(engine.sentPayloads.map(\.payload), [Data([1])])
    }

    func testStaleRelayMediaCompletionRetainsAndConsumesGlobalQuota() {
        let engine = FakeWebRTCEngine()
        let first = frame(1, isKeyframe: true)
        let encryptedRecordBytes = first.totalEncryptedRecordBytes
        let limits = InternetTransportLimits(
            maximumControlMessageBytes: 8,
            maximumBufferedControlBytes: 8,
            maximumMediaFrameBytes: 8,
            maximumRelayBytesPerSession: encryptedRecordBytes
        )
        let transport = connectedTransport(engine: engine, limits: limits, path: .relay)

        XCTAssertSuccess(transport.sendMedia(first))
        engine.emitPath(InternetNetworkPath(
            interface: .wifi,
            isSatisfied: true,
            fingerprint: "wifi-a"
        ))
        engine.emitPath(InternetNetworkPath(
            interface: .cellular,
            isSatisfied: true,
            fingerprint: "cellular-b"
        ))
        XCTAssertEqual(transport.snapshot().relayBytesReserved, encryptedRecordBytes)

        engine.emitConnection(.connected(path: .relay))
        XCTAssertFailure(
            transport.sendMedia(frame(2, isKeyframe: true)),
            expected: .relayBudgetExceeded(maximumBytes: encryptedRecordBytes)
        )

        engine.completeSend(at: 0)
        XCTAssertEqual(transport.snapshot().mediaBytesSent, UInt64(first.records[0].count))
        XCTAssertEqual(transport.snapshot().relayBytesReserved, 0)
        XCTAssertEqual(transport.snapshot().relayBytesSent, encryptedRecordBytes)
        XCTAssertFailure(
            transport.sendMedia(frame(3, isKeyframe: true)),
            expected: .relayBudgetExceeded(maximumBytes: encryptedRecordBytes)
        )
    }

    private func validConfiguration() -> WebRTCTransportConfiguration {
        WebRTCTransportConfiguration(
            iceServers: [
                WebRTCICEServer(urls: [URL(string: "stun:stun.example.com:3478")!]),
                WebRTCICEServer(
                    urls: [URL(string: "turns:relay.example.com:5349")!],
                    username: "ephemeral-user",
                    credential: "ephemeral-secret"
                )
            ],
            peerIdentity: "device-key-id",
            sessionIdentifier: "session-1",
            forceRelay: false
        )
    }

    private func productionConfiguration() -> WebRTCTransportConfiguration {
        WebRTCTransportConfiguration(
            iceServers: [WebRTCICEServer(urls: [URL(string: "stun:127.0.0.1:9")!])],
            peerIdentity: "production-lifecycle-test-peer",
            sessionIdentifier: "production-lifecycle-test-session",
            forceRelay: false,
            signaling: WebRTCSignalingConfiguration(
                endpoint: URL(string: "https://127.0.0.1.invalid")!,
                bearerToken: "production-lifecycle-test-token",
                role: .answerer
            )
        )
    }

    private func connectedTransport(
        engine: FakeWebRTCEngine,
        limits: InternetTransportLimits = .standard,
        path: InternetPathKind = .direct,
        beforeControlSend: (() -> Void)? = nil,
        beforeMediaRecordSend: (() -> Void)? = nil,
        beforeFailureSideEffects: (() -> Void)? = nil,
        duringRecoveryDecision: (() -> Void)? = nil,
        duringMediaRecoveryTransition: (() -> Void)? = nil
    ) -> WebRTCInternetTransport {
        let transport = WebRTCInternetTransport(
            engine: engine,
            packetCipher: engine.localCipher,
            limits: limits,
            beforeControlSend: beforeControlSend,
            beforeMediaRecordSend: beforeMediaRecordSend,
            beforeFailureSideEffects: beforeFailureSideEffects,
            duringRecoveryDecision: duringRecoveryDecision,
            duringMediaRecoveryTransition: duringMediaRecoveryTransition
        )
        try! transport.start(configuration: validConfiguration())
        engine.emitConnection(.connected(path: path))
        return transport
    }

    private func frame(_ byte: UInt8, isKeyframe: Bool) -> EncodedInternetFrame {
        encodedFrame(
            payloads: [Data([byte])],
            captureTimestamp: UInt64(byte),
            isKeyframe: isKeyframe
        )
    }

    private func fragmentedFrame(
        _ bytes: [UInt8],
        isKeyframe: Bool
    ) -> EncodedInternetFrame {
        encodedFrame(
            payloads: bytes.map { Data([$0]) },
            captureTimestamp: UInt64(bytes[0]),
            isKeyframe: isKeyframe
        )
    }

    private func encodedFrame(
        payloads: [Data],
        captureTimestamp: UInt64,
        isKeyframe: Bool,
        frameID: UInt64 = 1
    ) -> EncodedInternetFrame {
        let records = payloads.enumerated().map { index, payload -> Data in
            var header = VSMediaPacketHeader()
            header.streamID = 1
            header.sessionEpoch = 1
            header.configEpoch = 1
            header.frameID = frameID
            header.fragmentIndex = UInt32(index)
            header.fragmentCount = UInt32(payloads.count)
            header.captureTimestampNs = captureTimestamp
            header.keyframe = isKeyframe
            header.codec = .hevc
            return try! ProtocolV1MediaPacketCodec.encode(header: header, payload: payload)
        }
        return try! EncodedInternetFrame(
            records: records,
            mediaPayloadBytes: payloads.reduce(0) { $0 + $1.count },
            captureTimestamp: captureTimestamp,
            isKeyframe: isKeyframe
        )
    }

    private func makeCipherPair() -> (host: PlatformSessionPacketCipher, device: PlatformSessionPacketCipher) {
        try! PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "session-1",
            sharedSecret: Data(repeating: 0x51, count: 32),
            bootstrapSecret: Data(repeating: 0x52, count: 32),
            transcriptContext: Data(repeating: 0x53, count: 32)
        )
    }

    private func XCTAssertSuccess(
        _ result: Result<Void, InternetTransportError>,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        if case .failure(let error) = result {
            XCTFail("Expected success, got \(error)", file: file, line: line)
        }
    }

    private func XCTAssertFailure(
        _ result: Result<Void, InternetTransportError>,
        expected: InternetTransportError,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        switch result {
        case .success:
            XCTFail("Expected failure \(expected), got success", file: file, line: line)
        case .failure(let error):
            XCTAssertEqual(error, expected, file: file, line: line)
        }
    }
}

private final class LockedTransportResult: @unchecked Sendable {
    private let lock = NSLock()
    private var result: Result<Void, InternetTransportError>?
    private var storedInvocationCount = 0

    func store(_ result: Result<Void, InternetTransportError>) {
        lock.lock()
        storedInvocationCount += 1
        self.result = result
        lock.unlock()
    }

    func load() -> Result<Void, InternetTransportError>? {
        lock.lock()
        defer { lock.unlock() }
        return result
    }

    var invocationCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return storedInvocationCount
    }
}

private enum TestPeerDelegateSource: CaseIterable {
    case iceConnection
    case peerConnection
}

private final class TestWebRTCSignalingClient: WebRTCSignalingClientPort {
    var onSignal: ((WebRTCSignal) -> Void)?
    var onFailure: ((Error) -> Void)?
    let supportsNegotiationGeneration = true

    private let connectError: Error?
    private(set) var connectCount = 0

    init(connectError: Error? = nil) {
        self.connectError = connectError
    }

    func connect(configuration: WebRTCTransportConfiguration) throws {
        connectCount += 1
        if let connectError { throw connectError }
    }

    func send(_ signal: WebRTCSignal, completion: @escaping (Result<Void, Error>) -> Void) {
        completion(.success(()))
    }

    func close() {}
}

private final class FakeWebRTCEngine: WebRTCEnginePort {
    struct SentPayload {
        let payload: Data
        let networkBytes: Int
        let channel: InternetTransportChannel
        let completion: (Result<Void, Error>) -> Void
    }

    private var callbacks: WebRTCEngineCallbacks?
    private var peerDelegateGenerationState = WebRTCPeerConnectionDelegateGenerationState()
    private var transmissionEpoch: UInt64 = 0
    private var activeTransmissionPath: InternetPathKind?
    private var lastNetworkPathFingerprint: String?
    let localCipher: PlatformSessionPacketCipher
    private let remoteCipher: PlatformSessionPacketCipher
    private let emitClosedSynchronouslyOnClose: Bool
    private let synchronousSendFailure: Error?
    private let recoveryDisposition: WebRTCEngineRecoveryDisposition
    private let startError: Error?
    private(set) var startedChannels: [WebRTCDataChannelConfiguration] = []
    private(set) var sentPayloads: [SentPayload] = []
    private(set) var restartICECount = 0
    private(set) var keyframeRequestCount = 0
    private(set) var didClose = false
    private(set) var startedAfterClose = false
    private(set) var closeCount = 0
    private(set) var startCount = 0

    var currentPeerDelegateGeneration: UInt64 {
        peerDelegateGenerationState.currentGeneration
    }

    init(
        emitClosedSynchronouslyOnClose: Bool = false,
        synchronousSendFailure: Error? = nil,
        recoveryDisposition: WebRTCEngineRecoveryDisposition = .peerReplacementStarted,
        startError: Error? = nil
    ) {
        let ciphers = try! PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "session-1",
            sharedSecret: Data(repeating: 0x51, count: 32),
            bootstrapSecret: Data(repeating: 0x52, count: 32),
            transcriptContext: Data(repeating: 0x53, count: 32)
        )
        localCipher = ciphers.host
        remoteCipher = ciphers.device
        self.emitClosedSynchronouslyOnClose = emitClosedSynchronouslyOnClose
        self.synchronousSendFailure = synchronousSendFailure
        self.recoveryDisposition = recoveryDisposition
        self.startError = startError
    }

    func install(callbacks: WebRTCEngineCallbacks) {
        self.callbacks = callbacks
    }

    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws {
        startCount += 1
        if let startError { throw startError }
        startedAfterClose = didClose
        peerDelegateGenerationState.reset()
        startedChannels = channels
    }

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        expectedContext: WebRTCEngineTransmissionContext,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard expectedContext == currentTransmissionContext else {
            completion(.failure(TestError.sendFailed))
            return
        }
        guard let plaintext = remoteCipher.open(payload, channel: channel) else {
            completion(.failure(PlatformSecurityError.invalidInput("Test record authentication failed.")))
            return
        }
        if let synchronousSendFailure {
            completion(.failure(synchronousSendFailure))
            return
        }
        sentPayloads.append(SentPayload(
            payload: plaintext,
            networkBytes: payload.count,
            channel: channel,
            completion: completion
        ))
    }

    func restartICE() -> WebRTCEngineRecoveryDisposition {
        invalidateTransmissionContext()
        restartICECount += 1
        guard recoveryDisposition == .peerReplacementStarted else {
            return recoveryDisposition
        }
        guard peerDelegateGenerationState.beginRestart() != nil else {
            callbacks?.connectionStateChanged(.failed("Test peer delegate generation exhausted."))
            return .failed("Test peer delegate generation exhausted.")
        }
        callbacks?.connectionStateChanged(.connecting)
        return .peerReplacementStarted
    }

    func requestMediaKeyframe() {
        keyframeRequestCount += 1
    }

    func close() {
        invalidateTransmissionContext()
        closeCount += 1
        didClose = true
        if emitClosedSynchronouslyOnClose {
            callbacks?.connectionStateChanged(.closed)
        }
        remoteCipher.close()
    }

    func completeSend(at index: Int, result: Result<Void, Error> = .success(())) {
        sentPayloads[index].completion(result)
    }

    func emitConnection(_ state: WebRTCEngineConnectionState) {
        switch state {
        case .connected(let path):
            if activeTransmissionPath != path {
                invalidateTransmissionContext()
                activeTransmissionPath = path
            }
            callbacks?.transmissionContextChanged(currentTransmissionContext)
        case .connecting, .disconnected, .failed, .closed:
            invalidateTransmissionContext()
        }
        callbacks?.connectionStateChanged(state)
    }

    func emitDelegateConnection(
        _ state: WebRTCEngineConnectionState,
        source: TestPeerDelegateSource,
        generation: UInt64
    ) {
        _ = source
        guard peerDelegateGenerationState.accepts(delegateGeneration: generation) else { return }
        emitConnection(state)
    }

    func fireRestartProgressTimeout() {
        callbacks?.connectionStateChanged(.connecting)
        callbacks?.connectionStateChanged(.disconnected)
    }

    func emitPath(_ path: InternetNetworkPath) {
        let changed = lastNetworkPathFingerprint.map { $0 != path.fingerprint } ?? false
        lastNetworkPathFingerprint = path.fingerprint
        if changed { invalidateTransmissionContext() }
        callbacks?.networkPathChanged(path)
    }

    func receiveRaw(_ record: Data, channel: InternetTransportChannel) {
        callbacks?.messageReceived(record, channel)
    }

    func makeInboundRecord(_ payload: Data, channel: InternetTransportChannel) -> Data {
        try! remoteCipher.seal(payload, channel: channel)
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

private final class QueuedTransmissionWebRTCEngine: WebRTCEnginePort, @unchecked Sendable {
    struct PlaintextPayload: Equatable {
        let payload: Data
        let channel: InternetTransportChannel
    }

    let localCipher: PlatformSessionPacketCipher

    private let remoteCipher: PlatformSessionPacketCipher
    private let queue = DispatchQueue(label: "dev.vibescreen.tests.queued-transmission-engine")
    private let queueKey = DispatchSpecificKey<UInt8>()
    private var callbacks: WebRTCEngineCallbacks?
    private var transmissionEpoch: UInt64 = 0
    private var activeTransmissionPath: InternetPathKind?
    private var storedEvents: [String] = []
    private var storedPlaintext: [PlaintextPayload] = []
    private var closed = false

    init() {
        let ciphers = try! PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "session-1",
            sharedSecret: Data(repeating: 0x61, count: 32),
            bootstrapSecret: Data(repeating: 0x62, count: 32),
            transcriptContext: Data(repeating: 0x63, count: 32)
        )
        localCipher = ciphers.host
        remoteCipher = ciphers.device
        queue.setSpecific(key: queueKey, value: 1)
    }

    var events: [String] { performSync { storedEvents } }
    var sentPlaintext: [PlaintextPayload] { performSync { storedPlaintext } }

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
            guard !self.closed, self.currentTransmissionContext == expectedContext else {
                completion(.failure(TestError.sendFailed))
                return
            }
            guard let plaintext = self.remoteCipher.open(payload, channel: channel) else {
                completion(.failure(TestError.sendFailed))
                return
            }
            self.storedPlaintext.append(PlaintextPayload(payload: plaintext, channel: channel))
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

    func enqueueDisconnectAndWaitForHandling() -> Bool {
        let handled = DispatchSemaphore(value: 0)
        queue.async { [weak self] in
            guard let self else { handled.signal(); return }
            self.storedEvents.append("D")
            self.invalidateTransmissionContext()
            self.callbacks?.connectionStateChanged(.disconnected)
            handled.signal()
        }
        return handled.wait(timeout: .now() + 2) == .success
    }

    func waitForEventCount(_ count: Int) -> Bool {
        waitUntil { events.count >= count }
    }

    func waitForSentPayloadCount(_ count: Int) -> Bool {
        waitUntil { sentPlaintext.count >= count }
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

    private func waitUntil(_ predicate: () -> Bool) -> Bool {
        let deadline = DispatchTime.now() + .seconds(2)
        while DispatchTime.now() < deadline {
            if predicate() { return true }
            Thread.sleep(forTimeInterval: 0.005)
        }
        return predicate()
    }

    private func performSync<T>(_ operation: () -> T) -> T {
        if DispatchQueue.getSpecific(key: queueKey) != nil { return operation() }
        return queue.sync(execute: operation)
    }
}
