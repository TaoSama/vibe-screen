import Foundation
import VibeScreenProtocol

enum ProtocolV1SelfTest {
    private static let sessionID = Data(repeating: 0xAB, count: 16)
    private static let sessionEpoch: UInt64 = 7
    /// Mirrors AppDelegate.virtualExtendedDisplaySyntheticID for the host-side
    /// contract asserted by testVirtualDisplayCatalog.
    private static let virtualSyntheticID = "telemachus-virtual-extended"

    static func run() -> Bool {
        var failures: [String] = []
        testFramer(failures: &failures)
        testGoldenBytes(failures: &failures)
        testSharedGoldenFixtures(failures: &failures)
        testNegotiationAndMediaGate(failures: &failures)
        testMultiDisplaySelection(failures: &failures)
        testVirtualDisplayCatalog(failures: &failures)
        testRejections(failures: &failures)
       testInputHeartbeatAndMedia(failures: &failures)
       testTouchTargetAndDisconnect(failures: &failures)
        testNativePointerKeyboardInput(failures: &failures)
        testNativeInputMapping(failures: &failures)
        testClientVideoPreferences(failures: &failures)
        if failures.isEmpty {
            print("Protocol v1 self-test: PASS (framing, golden, negotiation, display/video gate, epoch, targeted input, heartbeat, graceful disconnect, error, media)")
            return true
        }
        print("Protocol v1 self-test: FAIL (\(failures.joined(separator: "; ")))")
        return false
    }

    private static func testFramer(failures: inout [String]) {
        do {
            let control = try ProtocolV1TransportFrame(channel: .control, payload: Data([1, 2])).encoded()
            let video = try ProtocolV1TransportFrame(channel: .video, payload: Data([3])).encoded()
            var framer = ProtocolV1Framer()
            guard try framer.append(control.prefix(3)).isEmpty else {
                failures.append("framer emitted a split header")
                return
            }
            let frames = try framer.append(Data(control.dropFirst(3)) + video)
            guard frames == [
                ProtocolV1TransportFrame(channel: .control, payload: Data([1, 2])),
                ProtocolV1TransportFrame(channel: .video, payload: Data([3]))
            ] else {
                failures.append("framer did not split coalesced channels")
                return
            }
            var invalid = ProtocolV1Framer()
            do {
                _ = try invalid.append(Data([9, 0, 0, 0, 0]))
                failures.append("framer accepted an unknown channel")
            } catch ProtocolV1FramerError.unknownChannel(9) {
                // Expected.
            } catch {
                failures.append("framer returned the wrong channel error")
            }
            var oversized = ProtocolV1Framer()
            var length = UInt32(ProtocolV1Framer.maximumPayloadBytes + 1).bigEndian
            var header = Data([ProtocolV1LogicalChannel.control.rawValue])
            withUnsafeBytes(of: &length) { header.append(contentsOf: $0) }
            do {
                _ = try oversized.append(header)
                failures.append("framer accepted an oversized payload")
            } catch ProtocolV1FramerError.payloadTooLarge {
                // Expected.
            } catch {
                failures.append("framer returned the wrong oversize error")
            }
        } catch {
            failures.append("framer setup failed: \(error)")
        }
    }

    private static func testGoldenBytes(failures: inout [String]) {
        do {
            var ping = VSPing()
            ping.sequence = 7
            var envelope = VSEnvelope()
            envelope.protocolVersion = 1
            envelope.messageID = 1
            envelope.ping = ping
            let expected = Data([0x08, 0x01, 0x10, 0x01, 0xC2, 0x01, 0x02, 0x08, 0x07])
            if try envelope.serializedData() != expected {
                failures.append("protobuf golden bytes changed")
            }
        } catch {
            failures.append("golden serialization failed: \(error)")
        }
    }

    private static func testSharedGoldenFixtures(failures: inout [String]) {
        do {
            let workingDirectory = URL(
                fileURLWithPath: FileManager.default.currentDirectoryPath,
                isDirectory: true
            )
            let repositoryCandidates = [
                workingDirectory,
                workingDirectory
                    .deletingLastPathComponent()
                    .deletingLastPathComponent()
            ]
            guard let root = repositoryCandidates
                .map({ $0.appendingPathComponent("contracts/fixtures/messages/v1/bin") })
                .first(where: { FileManager.default.fileExists(atPath: $0.path) }) else {
                failures.append("shared golden fixture directory is unavailable from the working directory")
                return
            }
            let controls = [
                "client_hello", "host_hello", "session_accepted",
                "list_displays_request", "list_displays_response",
                "start_display_request", "start_display_response",
                "video_config", "display_changed", "video_config_result", "touch", "ping", "pong",
                "protocol_error"
            ]
            for name in controls {
                let expected = try Data(contentsOf: root.appendingPathComponent("\(name).binpb"))
                let decoded = try VSEnvelope(serializedBytes: expected)
                guard try decoded.serializedData() == expected else {
                    failures.append("shared golden round-trip changed \(name)")
                    return
                }
            }
            let headerBytes = try Data(contentsOf: root.appendingPathComponent("media_packet_header.binpb"))
            let header = try VSMediaPacketHeader(serializedBytes: headerBytes)
            guard try header.serializedData() == headerBytes else {
                failures.append("shared media header golden changed")
                return
            }
            let annexB = Data([0, 0, 0, 1, 0x40, 0x01, 0x0C, 0x01, 0xFF, 0, 0xAA, 0x55])
            let packet = try ProtocolV1MediaPacketCodec.encode(header: header, payload: annexB)
            let expectedPacket = try Data(contentsOf: root.appendingPathComponent("media_packet.bin"))
            guard packet == expectedPacket else {
                failures.append("shared media packet golden changed")
                return
            }
            guard try Data(contentsOf: root.appendingPathComponent("upgrade_offer.bin")) == Data([ProtocolV1Upgrade.offer]),
                  try Data(contentsOf: root.appendingPathComponent("upgrade_acknowledgement.bin")) == ProtocolV1Upgrade.acknowledgement else {
                failures.append("shared upgrade golden changed")
                return
            }
        } catch {
            failures.append("shared golden fixtures failed: \(error)")
        }
    }

    private static func testNegotiationAndMediaGate(failures: inout [String]) {
        do {
            guard ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: true)
                    == [.touch, .keyboard, .pointer, .multiDisplay, .clientVideoControl],
                  ProtocolV1SessionConfiguration.productionHostCapabilities(touchEnabled: false)
                    == [.multiDisplay, .clientVideoControl] else {
                failures.append("production HostHello capabilities are not exact")
                return
            }
            let session = makeSession()
            var offeredHello = clientHello()
            offeredHello.clientHello.capabilities.append(.telemetry)
            let preparation = session.handleControl(try offeredHello.serializedData())
            guard preparation.contains(where: { if case .codecNegotiated = $0 { true } else { false } }) else {
                failures.append("ClientHello did not request codec preparation")
                return
            }
            let helloResponses = try responseEnvelopes(
                session.completeCodecNegotiation()
            )
            guard helloResponses.count == 2,
                  case .hostHello(let hostHello)? = helloResponses[0].payload,
                  case .sessionAccepted(let accepted)? = helloResponses[1].payload,
                  Set(hostHello.capabilities) == [.touch, .keyboard, .pointer, .multiDisplay, .clientVideoControl],
                  accepted.sessionID == sessionID,
                  accepted.negotiatedCapabilities == [.touch, .multiDisplay] else {
                failures.append("ClientHello did not produce HostHello + SessionAccepted")
                return
            }
            guard try session.makeMediaFrame(payload: Data([1]), timestamp: 1, keyframe: true) == nil else {
                failures.append("media escaped before StartDisplay")
                return
            }
            let list = session.handleControl(try envelope(
                id: 2,
                payload: .listDisplaysRequest(VSListDisplaysRequest())
            ).serializedData())
            guard case .listDisplaysResponse(let displays)? = try responseEnvelopes(list).first?.payload,
                  displays.displays.count == 1 else {
                failures.append("ListDisplays did not return the active display")
                return
            }
            let start = session.handleControl(try envelope(
                id: 3,
                payload: .startDisplayRequest(displayRequest())
            ).serializedData())
            let startResponses = try responseEnvelopes(start)
            guard startResponses.count == 2,
                  case .startDisplayResponse? = startResponses[0].payload,
                  case .videoConfig(let config)? = startResponses[1].payload,
                  config.codec == .hevc,
                  config.framesPerSecond == 60,
                  config.bitrateKbps == 20_000,
                  config.rotationDegrees == 90 else {
                failures.append("StartDisplay did not produce the configured VideoConfig")
                return
            }
            guard try session.makeMediaFrame(payload: Data([1]), timestamp: 1, keyframe: true) == nil else {
                failures.append("media escaped before VideoConfigResult")
                return
            }
            session.updateDisplayGeometry(width: 1920, height: 1080, rotation: 270)
            guard session.makeDisplayChanged().isEmpty else {
                failures.append("DisplayChanged escaped before VideoConfigResult")
                return
            }
            var result = VSVideoConfigResult()
            result.configEpoch = config.configEpoch
            result.streamID = config.streamID
            result.accepted = true
            let actions = session.handleControl(try envelope(
                id: 4,
                payload: .videoConfigResult(result)
            ).serializedData())
            let postNegotiation = try responseEnvelopes(actions)
            guard case .displayChanged(let changed)? = postNegotiation.first?.payload,
                  changed.rotationDegrees == 270 else {
                failures.append("negotiation-time rotation was not coalesced after VideoConfigResult")
                return
            }
            guard actions.contains(where: { if case .connectionReady = $0 { true } else { false } }) else {
                failures.append("accepted VideoConfig did not ready the connection")
                return
            }
            guard try session.makeMediaFrame(payload: Data([1]), timestamp: 1, keyframe: true) != nil else {
                failures.append("media remained blocked after VideoConfigResult")
                return
            }
        } catch {
            failures.append("negotiation test failed: \(error)")
        }
    }

    private static func testMultiDisplaySelection(failures: inout [String]) {
        do {
            let session = makeMultiDisplaySession()
            _ = session.handleControl(try clientHello().serializedData())
            _ = session.completeCodecNegotiation()

            let list = session.handleControl(try envelope(
                id: 2,
                payload: .listDisplaysRequest(VSListDisplaysRequest())
            ).serializedData())
            guard case .listDisplaysResponse(let displays)? = try responseEnvelopes(list).first?.payload,
                  displays.displays.count == 2,
                  displays.displays[0].displayID == "active-display",
                  displays.displays[0].isPrimary,
                  displays.displays[1].displayID == "second-display",
                  displays.displays[1].isPrimary == false,
                  displays.displays[1].logicalSize.width == 3840,
                  displays.displays[1].logicalSize.height == 2160 else {
                failures.append("ListDisplays did not enumerate both configured displays")
                return
            }

            let start = session.handleControl(try envelope(
                id: 3,
                payload: .startDisplayRequest(displayRequest(sourceDisplayID: "second-display"))
            ).serializedData())
            guard start.contains(where: {
                if case .selectDisplay(let id) = $0 { return id == "second-display" }
                return false
            }) else {
                failures.append("StartDisplay on a second display did not emit a selectDisplay action")
                return
            }
            let startResponses = try responseEnvelopes(start)
            guard startResponses.count == 2,
                  case .startDisplayResponse(let response)? = startResponses[0].payload,
                  response.accepted,
                  response.display.displayID == "second-display",
                  response.display.isPrimary == false,
                  case .videoConfig(let config)? = startResponses[1].payload,
                  config.encodedSize.width == 3840,
                  config.encodedSize.height == 2160 else {
                failures.append("StartDisplay on the second display did not adopt its descriptor")
                return
            }

            let unknownSession = makeMultiDisplaySession()
            _ = unknownSession.handleControl(try clientHello().serializedData())
            _ = unknownSession.completeCodecNegotiation()
            let unknown = unknownSession.handleControl(try envelope(
                id: 2,
                payload: .startDisplayRequest(displayRequest(sourceDisplayID: "does-not-exist"))
            ).serializedData())
            guard try protocolError(unknown).code == .invalidState else {
                failures.append("StartDisplay on an unknown display id was not rejected with invalidState")
                return
            }

            // Regression: a client-initiated runtime switch (a StartDisplayRequest
            // that arrives while already streaming) must be answered by exactly
            // one StartDisplayResponse + VideoConfig on this session, plus the
            // selectDisplay action that tells the host to re-point capture. The
            // host must not turn around and re-run the negotiation a second time
            // (via selectProtocolV1Display) for the same client request: the
            // client is back in STREAMING and a second StartDisplayResponse would
            // trip its INVALID_PEER_MESSAGE guard and tear down the session.
            let switchSession = makeMultiDisplaySession()
            _ = switchSession.handleControl(try clientHello().serializedData())
            _ = switchSession.completeCodecNegotiation()
            _ = switchSession.handleControl(try envelope(
                id: 2,
                payload: .startDisplayRequest(displayRequest(sourceDisplayID: "active-display"))
            ).serializedData())
            var accept = VSVideoConfigResult()
            accept.configEpoch = 1
            accept.streamID = 1
            accept.accepted = true
            _ = switchSession.handleControl(try envelope(
                id: 3,
                payload: .videoConfigResult(accept)
            ).serializedData())

            let runtimeSwitch = switchSession.handleControl(try envelope(
                id: 4,
                payload: .startDisplayRequest(displayRequest(sourceDisplayID: "second-display"))
            ).serializedData())
            guard runtimeSwitch.contains(where: {
                if case .selectDisplay(let id) = $0 { return id == "second-display" }
                return false
            }) else {
                failures.append("streaming StartDisplayRequest did not emit a selectDisplay action to switch capture")
                return
            }
            let runtimeResponses = try responseEnvelopes(runtimeSwitch)
            let startResponseCount = runtimeResponses.filter {
                if case .startDisplayResponse = $0.payload { return true }
                return false
            }.count
            guard startResponseCount == 1 else {
                failures.append("streaming StartDisplayRequest produced \(startResponseCount) StartDisplayResponse(s); expected exactly one")
                return
            }
            guard runtimeResponses.count == 2,
                  case .startDisplayResponse(let switched)? = runtimeResponses[0].payload,
                  switched.accepted,
                  switched.display.displayID == "second-display",
                  case .videoConfig(let switchedConfig)? = runtimeResponses[1].payload,
                  switchedConfig.configEpoch == 2 else {
                failures.append("streaming StartDisplayRequest did not renegotiate in place with a bumped epoch")
                return
            }
        } catch {
            failures.append("multi-display selection test failed: \(error)")
        }
    }

    /// Covers the single-physical-display host contract: a synthetic virtual
    /// extended entry is enumerated by ListDisplays as isVirtual, StartDisplay
    /// accepts its id, and a runtime selection bumps the configEpoch so the
    /// client re-negotiates video for the virtual source.
    private static func testVirtualDisplayCatalog(failures: inout [String]) {
        do {
            let session = makeVirtualCatalogSession()
            _ = session.handleControl(try clientHello().serializedData())
            _ = session.completeCodecNegotiation()

            let list = session.handleControl(try envelope(
                id: 2,
                payload: .listDisplaysRequest(VSListDisplaysRequest())
            ).serializedData())
            guard case .listDisplaysResponse(let displays)? = try responseEnvelopes(list).first?.payload,
                  displays.displays.count == 2,
                  displays.displays[0].displayID == "active-display",
                  displays.displays[0].isVirtual == false,
                  displays.displays[1].displayID == virtualSyntheticID,
                  displays.displays[1].isVirtual,
                  displays.displays[1].isPrimary == false else {
                failures.append("ListDisplays did not enumerate the virtual extended display")
                return
            }

            // Drive to streaming on the physical display first.
            _ = session.handleControl(try envelope(
                id: 3,
                payload: .startDisplayRequest(displayRequest(sourceDisplayID: "active-display"))
            ).serializedData())
            var result = VSVideoConfigResult()
            result.configEpoch = 1
            result.streamID = 1
            result.accepted = true
            _ = session.handleControl(try envelope(
                id: 4,
                payload: .videoConfigResult(result)
            ).serializedData())

            // Media flows on the physical source before the switch.
            guard try session.makeMediaFrame(payload: Data([1]), timestamp: 1, keyframe: true) != nil else {
                failures.append("streaming physical display did not encode media before the switch")
                return
            }

            // Runtime switch to the virtual display bumps the epoch.
            let switchActions = session.selectDisplayFromClient(displayID: virtualSyntheticID)
            let switchResponses = try responseEnvelopes(switchActions)
            guard switchResponses.count == 2,
                  case .startDisplayResponse(let response)? = switchResponses[0].payload,
                  response.accepted,
                  response.display.displayID == virtualSyntheticID,
                  response.display.isVirtual,
                  case .videoConfig(let config)? = switchResponses[1].payload,
                  config.configEpoch == 2 else {
                failures.append("Runtime selection of the virtual display did not bump the configEpoch")
                return
            }

            // While the client has not yet accepted the new VideoConfig the
            // session must withhold every media frame. This is the host half of
            // the fix for the "Media received before VideoConfig acceptance"
            // client hard-disconnect: no media may escape mid-switch.
            guard try session.makeMediaFrame(payload: Data([2]), timestamp: 2, keyframe: true) == nil else {
                failures.append("media escaped during the virtual-display switch before VideoConfig acceptance")
                return
            }

            // The client accepts the new VideoConfig; only then does media flow
            // again, now on configEpoch 2 for the virtual source.
            var switched = VSVideoConfigResult()
            switched.configEpoch = 2
            switched.streamID = 1
            switched.accepted = true
            _ = session.handleControl(try envelope(
                id: 5,
                payload: .videoConfigResult(switched)
            ).serializedData())
            guard let postSwitchMedia = try session.makeMediaFrame(payload: Data([3]), timestamp: 3, keyframe: true) else {
                failures.append("media did not resume after accepting the switched VideoConfig")
                return
            }
            let decodedSwitch = try decodeMedia(postSwitchMedia)
            guard decodedSwitch.header.configEpoch == 2 else {
                failures.append("post-switch media did not carry the bumped configEpoch")
                return
            }

            // After the switch the active display the session reports (via the
            // DisplayChanged notice that follows VideoConfig acceptance) is the
            // virtual source, so the client tracks the virtual display as the
            // current/selected one instead of falling back to the physical
            // primary. The StartDisplayResponse descriptor asserted above
            // already carries virtualSyntheticID as the adopted active id.
            let changedActions = session.makeDisplayChanged()
            let changedResponses = try responseEnvelopes(changedActions)
            guard case .displayChanged(let changed)? = changedResponses.first?.payload,
                  changed.display.displayID == virtualSyntheticID,
                  changed.display.isVirtual else {
                failures.append("post-switch active display did not point to the virtual source")
                return
            }
        } catch {
            failures.append("virtual display catalog test failed: \(error)")
        }
    }

    private static func testRejections(failures: inout [String]) {
        do {
            let versionSession = makeSession()
            var versionHello = clientHello()
            versionHello.clientHello.supportedProtocols.minimum = 2
            versionHello.clientHello.supportedProtocols.maximum = 2
            guard try protocolError(versionSession.handleControl(versionHello.serializedData())).code == .unsupportedVersion else {
                failures.append("unsupported protocol version was not rejected")
                return
            }

            let capabilitySession = makeSession()
            var capabilityHello = clientHello()
            // Stylus stays unadvertised by the host, so it is the reliable
            // negative case now that keyboard/pointer are negotiated.
            capabilityHello.clientHello.requiredCapabilities = [.stylus]
            guard try protocolError(capabilitySession.handleControl(capabilityHello.serializedData())).code == .unsupportedCapability else {
                failures.append("unsupported required capability was not rejected")
                return
            }

            let staleSession = makeSession()
            _ = staleSession.handleControl(try clientHello().serializedData())
            _ = staleSession.completeCodecNegotiation()
            var ping = VSPing()
            ping.sequence = 1
            var stale = envelope(id: 2, payload: .ping(ping))
            stale.sessionEpoch -= 1
            guard try protocolError(staleSession.handleControl(stale.serializedData())).code == .unauthorized else {
                failures.append("stale session epoch was not rejected")
                return
            }

            let inputSession = try readySession()
            var pointer = VSPointerEvent()
            pointer.inputID = 1
            pointer.phase = .changed
            var position = VSNormalizedPoint()
            position.x = 0.5
            position.y = 0.5
            pointer.position = position
            guard try protocolError(inputSession.handleControl(
                try envelope(id: 4, payload: .pointerEvent(pointer)).serializedData()
            )).code == .unsupportedCapability else {
                failures.append("unnegotiated pointer input was not rejected")
                return
            }
        } catch {
            failures.append("rejection test failed: \(error)")
        }
    }

    private static func testInputHeartbeatAndMedia(failures: inout [String]) {
        do {
            let session = try readySession()
            var point = VSNormalizedPoint()
            point.x = 0.25
            point.y = 0.75
            var touch = VSTouchEvent()
            touch.inputID = 1
            touch.pointerID = 1
            touch.phase = .began
            touch.position = point
            let touchActions = session.handleControl(try envelope(id: 4, payload: .touchEvent(touch)).serializedData())
            guard touchActions.contains(where: {
                if case .touch(let pointerID, _, _, let phase) = $0 {
                    return pointerID == 1 && phase == .began
                }
                return false
            }) else {
                failures.append("valid touch was not dispatched")
                return
            }
            var aggregator = ProtocolV1TouchAggregator()
            guard aggregator.handle(pointerID: 3, x: 0.1, y: 0.2, phase: .began)?.pointerCount == 1,
                  let two = aggregator.handle(pointerID: 7, x: 0.8, y: 0.9, phase: .began),
                  two.pointerCount == 2,
                  two.x1 == 0.1,
                  two.x2 == 0.8,
                  aggregator.handle(pointerID: 3, x: 0.2, y: 0.3, phase: .ended)?.action == 2,
                  aggregator.handle(pointerID: 7, x: 0.7, y: 0.8, phase: .changed)?.pointerCount == 1 else {
                failures.append("two-pointer touch aggregation is incorrect")
                return
            }

            var ping = VSPing()
            ping.sequence = 42
            let pingActions = session.handleControl(try envelope(id: 5, payload: .ping(ping)).serializedData())
            let responses = try responseEnvelopes(pingActions)
            guard pingActions.contains(where: { if case .heartbeat = $0 { true } else { false } }),
                  case .pong(let pong)? = responses.first?.payload,
                  pong.sequence == 42 else {
                failures.append("Ping did not refresh heartbeat and return Pong")
                return
            }

            let annexB = Data([0, 0, 0, 1, 0x26])
            guard let media = try session.makeMediaFrame(payload: annexB, timestamp: 99, keyframe: true) else {
                failures.append("ready session did not encode media")
                return
            }
            let decoded = try decodeMedia(media)
            guard decoded.header.sessionEpoch == sessionEpoch,
                  decoded.header.configEpoch == 1,
                  decoded.header.streamID == 1,
                  decoded.header.frameID == 1,
                  decoded.header.keyframe,
                  decoded.payload == annexB else {
                failures.append("MediaPacketHeader or Annex-B payload is incorrect")
                return
            }

            var peerError = VSProtocolError()
            peerError.code = .invalidState
            let peerActions = session.handleControl(try envelope(
                id: 6,
                payload: .protocolError(peerError)
            ).serializedData())
            guard peerActions.contains(where: { if case .peerError = $0 { true } else { false } }),
                  peerActions.contains(where: { if case .close = $0 { true } else { false } }) else {
                failures.append("peer ProtocolError did not fail the session")
                return
            }
        } catch {
            failures.append("input/media test failed: \(error)")
        }
    }

    private static func testTouchTargetAndDisconnect(failures: inout [String]) {
        do {
            let accepted = try readySession()
            var activeTarget = VSInputTarget()
            activeTarget.displayID = "active-display"
            activeTarget.streamID = 1
            var targetedTouch = touchEvent()
            targetedTouch.target = activeTarget
            guard accepted.handleControl(try envelope(
                id: 4,
                payload: .touchEvent(targetedTouch)
            ).serializedData()).contains(where: { if case .touch = $0 { true } else { false } }) else {
                failures.append("active stream touch target was not accepted")
                return
            }

            let rejected = try readySession()
            var wrongTarget = activeTarget
            wrongTarget.displayID = "different-display"
            var wrongTouch = touchEvent()
            wrongTouch.target = wrongTarget
            let rejectedActions = rejected.handleControl(try envelope(
                id: 4,
                payload: .touchEvent(wrongTouch)
            ).serializedData())
            guard try protocolError(rejectedActions).code == .invalidState,
                  rejectedActions.contains(where: { if case .close = $0 { true } else { false } }) else {
                failures.append("wrong touch target did not fail closed")
                return
            }

            let disconnected = try readySession()
            var notice = VSDisconnectNotice()
            notice.reasonCode = "client_shutdown"
            let disconnectActions = disconnected.handleControl(try envelope(
                id: 4,
                payload: .disconnectNotice(notice)
            ).serializedData())
            guard disconnected.phase == .closed,
                  disconnectActions.contains(where: { if case .close = $0 { true } else { false } }),
                  try responseEnvelopes(disconnectActions).isEmpty else {
                failures.append("client DisconnectNotice was not closed gracefully")
                return
            }
        } catch {
            failures.append("target/disconnect test failed: \(error)")
        }
    }

    /// Verifies that a client advertising keyboard + pointer negotiates them
    /// and that PointerEvent/ScrollEvent/KeyEvent produce the matching session
    /// actions, while a touch-only client is denied those inputs.
    private static func testNativePointerKeyboardInput(failures: inout [String]) {
        do {
            let session = try readySession(
                clientCapabilities: [.touch, .keyboard, .pointer, .multiDisplay]
            )

            var point = VSNormalizedPoint()
            point.x = 0.4
            point.y = 0.6
            var pointer = VSPointerEvent()
            pointer.inputID = 1
            pointer.phase = .began
            pointer.position = point
            pointer.buttonMask = StreamInputWire.buttonPrimary
            let pointerActions = session.handleControl(try envelope(
                id: 10, payload: .pointerEvent(pointer)
            ).serializedData())
            guard pointerActions.contains(where: {
                if case .pointer(let x, let y, let phase, let mask) = $0 {
                    return abs(x - 0.4) < 0.0001 && abs(y - 0.6) < 0.0001 &&
                        phase == .began && mask == StreamInputWire.buttonPrimary
                }
                return false
            }) else {
                failures.append("negotiated pointer event was not dispatched")
                return
            }

            var scroll = VSScrollEvent()
            scroll.inputID = 2
            scroll.deltaX = 3
            scroll.deltaY = -7
            let scrollActions = session.handleControl(try envelope(
                id: 11, payload: .scrollEvent(scroll)
            ).serializedData())
            guard scrollActions.contains(where: {
                if case .scroll(let dx, let dy) = $0 { return dx == 3 && dy == -7 }
                return false
            }) else {
                failures.append("negotiated scroll event was not dispatched")
                return
            }

            var key = VSKeyEvent()
            key.inputID = 3
            key.usbHidUsage = 0x04
            key.pressed = true
            key.modifierMask = StreamInputWire.modifierCommand
            let keyActions = session.handleControl(try envelope(
                id: 12, payload: .keyEvent(key)
            ).serializedData())
            guard keyActions.contains(where: {
                if case .key(let usage, let pressed, let mods, _) = $0 {
                    return usage == 0x04 && pressed && mods == StreamInputWire.modifierCommand
                }
                return false
            }) else {
                failures.append("negotiated key event was not dispatched")
                return
            }

            // A touch-only client must be refused pointer input with
            // unsupportedCapability (fail closed).
            let touchOnly = try readySession()
            var deniedPointer = VSPointerEvent()
            deniedPointer.inputID = 1
            deniedPointer.phase = .began
            deniedPointer.position = point
            let deniedActions = touchOnly.handleControl(try envelope(
                id: 10, payload: .pointerEvent(deniedPointer)
            ).serializedData())
            guard try protocolError(deniedActions).code == .unsupportedCapability else {
                failures.append("touch-only client was not denied pointer input")
                return
            }
        } catch {
            failures.append("native pointer/keyboard test failed: \(error)")
        }
    }

    /// Exercises the pure input mapping used by the CGEvent injector so button,
    /// scroll, modifier, and HID translations stay correct without a window server.
    private static func testNativeInputMapping(failures: inout [String]) {
        let bounds = CGRect(x: 100, y: 200, width: 1920, height: 1080)
        guard let mid = StreamInputMapping.pointerLocation(normalizedX: 0.5, normalizedY: 0.5, in: bounds),
              abs(mid.x - (100 + 960)) < 0.0001,
              abs(mid.y - (200 + 540)) < 0.0001 else {
            failures.append("pointer location mapping is incorrect")
            return
        }
        if StreamInputMapping.pointerLocation(normalizedX: 1.5, normalizedY: 0.5, in: bounds) != nil {
            failures.append("out-of-range pointer coordinate was not rejected")
            return
        }
        let wheels = StreamInputMapping.scrollWheels(deltaX: 4.4, deltaY: -9.6)
        guard wheels.wheel1 == -10, wheels.wheel2 == 4 else {
            failures.append("scroll wheel mapping is incorrect: \(wheels)")
            return
        }
        let flags = StreamInputMapping.modifierFlags(
            fromModifierMask: StreamInputWire.modifierShift | StreamInputWire.modifierCommand
        )
        guard flags.contains(.maskShift), flags.contains(.maskCommand),
              !flags.contains(.maskControl), !flags.contains(.maskAlternate) else {
            failures.append("modifier flag mapping is incorrect")
            return
        }
        guard StreamInputMapping.macKeyCode(fromUSBHIDUsage: 0x04) == 0x00,
              StreamInputMapping.macKeyCode(fromUSBHIDUsage: 0x28) == 0x24,
              StreamInputMapping.macKeyCode(fromUSBHIDUsage: 0x00) == nil else {
            failures.append("HID-to-keycode mapping is incorrect")
            return
        }
    }

    private static func testClientVideoPreferences(failures: inout [String]) {
        do {
            // Client offers CLIENT_VIDEO_CONTROL, drives to streaming, then asks
            // for an explicit bitrate + fps. The host must return exactly one
            // applyVideoPreferences action carrying the clamped values with the
            // quality preset dropped (an explicit bitrate wins) and must NOT
            // renegotiate video until the host confirms the encoder adopted the
            // settings via completeVideoPreferences.
            let session = try readySession(clientCapabilities: [.touch, .clientVideoControl])
            var prefs = VSSetVideoPreferences()
            prefs.bitrateKbps = 8_000
            prefs.framesPerSecond = 30
            prefs.qualityPreset = .sharp
            let actions = session.handleControl(try envelope(
                id: 4,
                payload: .setVideoPreferences(prefs)
            ).serializedData())
            let apply = actions.compactMap { action -> (UInt64, UInt32, UInt32, VSVideoQualityPreset, Bool)? in
                if case .applyVideoPreferences(let t, let b, let f, let q, let r) = action {
                    return (t, b, f, q, r)
                }
                return nil
            }
            guard apply.count == 1,
                  apply[0].1 == 8_000, apply[0].2 == 30,
                  apply[0].3 == .unspecified, apply[0].4 == false else {
                failures.append("SetVideoPreferences did not apply the clamped bitrate/fps or dropped preset incorrectly")
                return
            }
            // The apply action alone must not renegotiate video: no
            // StartDisplayResponse or VideoConfig may be emitted before the host
            // confirms the encoder reconfiguration.
            guard try responseEnvelopes(actions).isEmpty else {
                failures.append("SetVideoPreferences renegotiated video before the encoder was confirmed")
                return
            }
            // The host confirms the encoder adopted the settings. Only now is a
            // single bumped-epoch VideoConfig advertised, with values that match
            // what the host actually applied.
            let token = apply[0].0
            let commit = session.completeVideoPreferences(
                token: token,
                accepted: true,
                appliedBitrateKbps: 8_000,
                appliedFramesPerSecond: 30
            )
            let responses = try responseEnvelopes(commit)
            let startCount = responses.filter {
                if case .startDisplayResponse = $0.payload { return true }
                return false
            }.count
            guard startCount == 1, responses.count == 2,
                  case .videoConfig(let config)? = responses[1].payload,
                  config.configEpoch == 2,
                  config.bitrateKbps == 8_000,
                  config.framesPerSecond == 30 else {
                failures.append("completeVideoPreferences did not re-advertise exactly one VideoConfig with the applied values on a bumped epoch")
                return
            }
            // A stale/superseded completion token must be a safe no-op that
            // keeps the prior configuration and emits nothing.
            guard session.completeVideoPreferences(
                token: token,
                accepted: true,
                appliedBitrateKbps: 8_000,
                appliedFramesPerSecond: 30
            ).isEmpty else {
                failures.append("A superseded completeVideoPreferences token was not ignored")
                return
            }
            // Each preference change re-gates media until the client accepts the
            // new VideoConfig, exactly like a display switch. Ack epoch 2 to
            // return to streaming before the next request.
            try acceptVideoConfig(session, configEpoch: 2, streamID: 1, messageID: 5)

            // A follow-up request with no explicit bitrate keeps the previous
            // values and forwards the quality preset for the host to map.
            var presetOnly = VSSetVideoPreferences()
            presetOnly.qualityPreset = .smooth
            let presetActions = session.handleControl(try envelope(
                id: 6,
                payload: .setVideoPreferences(presetOnly)
            ).serializedData())
            let presetApply = presetActions.compactMap { action -> (UInt64, UInt32, UInt32, VSVideoQualityPreset, Bool)? in
                if case .applyVideoPreferences(let t, let b, let f, let q, let r) = action {
                    return (t, b, f, q, r)
                }
                return nil
            }
            guard presetApply.count == 1,
                  presetApply[0].1 == 8_000, presetApply[0].2 == 30,
                  presetApply[0].3 == .smooth, presetApply[0].4 == false else {
                failures.append("preset-only SetVideoPreferences did not preserve values or forward the preset")
                return
            }
            _ = session.completeVideoPreferences(
                token: presetApply[0].0,
                accepted: true,
                appliedBitrateKbps: 8_000,
                appliedFramesPerSecond: 30
            )
            try acceptVideoConfig(session, configEpoch: 3, streamID: 1, messageID: 7)

            // reset_quality_to_auto expresses a preset -> AUTO transition. With
            // no explicit bitrate the reset flag is forwarded and the preset is
            // dropped so the host restores its default quality.
            var reset = VSSetVideoPreferences()
            reset.qualityPreset = .sharp
            reset.resetQualityToAuto = true
            let resetActions = session.handleControl(try envelope(
                id: 8,
                payload: .setVideoPreferences(reset)
            ).serializedData())
            let resetApply = resetActions.compactMap { action -> (UInt64, VSVideoQualityPreset, Bool)? in
                if case .applyVideoPreferences(let t, _, _, let q, let r) = action { return (t, q, r) }
                return nil
            }
            guard resetApply.count == 1, resetApply[0].2 == true, resetApply[0].1 == .sharp else {
                failures.append("reset_quality_to_auto was not forwarded to the host apply action")
                return
            }
            _ = session.completeVideoPreferences(
                token: resetApply[0].0,
                accepted: true,
                appliedBitrateKbps: 8_000,
                appliedFramesPerSecond: 30
            )
            try acceptVideoConfig(session, configEpoch: 4, streamID: 1, messageID: 9)

            // Out-of-range values are clamped to the host bounds.
            var extreme = VSSetVideoPreferences()
            extreme.bitrateKbps = 500
            extreme.framesPerSecond = 240
            let clampedActions = session.handleControl(try envelope(
                id: 10,
                payload: .setVideoPreferences(extreme)
            ).serializedData())
            guard clampedActions.contains(where: {
                if case .applyVideoPreferences(_, let b, let f, _, _) = $0 { return b == 1_000 && f == 120 }
                return false
            }) else {
                failures.append("SetVideoPreferences did not clamp out-of-range values")
                return
            }

            // A session that never negotiated CLIENT_VIDEO_CONTROL must reject
            // the message with an unsupported-capability protocol error.
            let ungated = try readySession(clientCapabilities: [.touch, .multiDisplay])
            var gatedPrefs = VSSetVideoPreferences()
            gatedPrefs.bitrateKbps = 8_000
            let rejected = ungated.handleControl(try envelope(
                id: 4,
                payload: .setVideoPreferences(gatedPrefs)
            ).serializedData())
            let error = try protocolError(rejected)
            guard error.code == .unsupportedCapability else {
                failures.append("SetVideoPreferences without the capability was not rejected as unsupported")
                return
            }
        } catch {
            failures.append("client video preferences test failed: \(error)")
        }
    }

    private static func touchEvent() -> VSTouchEvent {
        var point = VSNormalizedPoint()
        point.x = 0.25
        point.y = 0.75
        var touch = VSTouchEvent()
        touch.inputID = 1
        touch.pointerID = 1
        touch.phase = .began
        touch.position = point
        return touch
    }

    private static func makeSession() -> ProtocolV1SessionCoordinator {
        ProtocolV1SessionCoordinator(configuration: ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 90,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true
            ),
            requiredClientCapabilities: [.touch],
            supportedCodecs: [.hevc, .h264],
            hostID: "host",
            hostName: "Mac",
            displayID: "active-display",
            displayName: "Display",
            displayIsVirtual: true
        ))
    }

    private static func makeMultiDisplaySession() -> ProtocolV1SessionCoordinator {
        ProtocolV1SessionCoordinator(configuration: ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 90,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true
            ),
            requiredClientCapabilities: [.touch],
            supportedCodecs: [.hevc, .h264],
            hostID: "host",
            hostName: "Mac",
            displayID: "active-display",
            displayName: "Display",
            displayIsVirtual: true,
            displays: [
                ProtocolV1DisplayInfo(
                    id: "active-display",
                    name: "Built-in Display",
                    width: 1920,
                    height: 1080,
                    isPrimary: true,
                    isVirtual: false
                ),
                ProtocolV1DisplayInfo(
                    id: "second-display",
                    name: "External 4K",
                    width: 3840,
                    height: 2160,
                    isPrimary: false,
                    isVirtual: false
                )
            ]
        ))
    }

    private static func clientHello() -> VSEnvelope {
        return clientHelloEnvelope()
    }

    private static func makeVirtualCatalogSession() -> ProtocolV1SessionCoordinator {
        ProtocolV1SessionCoordinator(configuration: ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 0,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: true
            ),
            requiredClientCapabilities: [.touch],
            supportedCodecs: [.hevc, .h264],
            hostID: "host",
            hostName: "Mac",
            displayID: "active-display",
            displayName: "Built-in Liquid Retina XDR",
            displayIsVirtual: false,
            displays: [
                ProtocolV1DisplayInfo(
                    id: "active-display",
                    name: "Built-in Liquid Retina XDR",
                    width: 1920,
                    height: 1080,
                    isPrimary: true,
                    isVirtual: false
                ),
                ProtocolV1DisplayInfo(
                    id: virtualSyntheticID,
                    name: "Telemachus Virtual",
                    width: 1920,
                    height: 1080,
                    isPrimary: false,
                    isVirtual: true
                )
            ]
        ))
    }

    private static func clientHelloEnvelope() -> VSEnvelope {
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "device"
        hello.deviceName = "Tablet"
        hello.capabilities = [.touch, .multiDisplay]
        hello.codecs = [.hevc, .h264]
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = 1
        envelope.clientHello = hello
        return envelope
    }

    private static func envelope(id: UInt64, payload: VSEnvelope.OneOf_Payload) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = id
        envelope.sessionID = sessionID
        envelope.sessionEpoch = sessionEpoch
        envelope.payload = payload
        return envelope
    }

    private static func displayRequest(sourceDisplayID: String = "active-display") -> VSStartDisplayRequest {
        var request = VSStartDisplayRequest()
        request.mode = .existing
        request.sourceDisplayID = sourceDisplayID
        return request
    }

    /// Ack a pending VideoConfig so the session returns to STREAMING, mirroring
    /// the client accepting a runtime reconfiguration.
    @discardableResult
    private static func acceptVideoConfig(
        _ session: ProtocolV1SessionCoordinator,
        configEpoch: UInt64,
        streamID: UInt64,
        messageID: UInt64
    ) throws -> [ProtocolV1SessionAction] {
        var result = VSVideoConfigResult()
        result.configEpoch = configEpoch
        result.streamID = streamID
        result.accepted = true
        return session.handleControl(try envelope(
            id: messageID,
            payload: .videoConfigResult(result)
        ).serializedData())
    }

   private static func readySession() throws -> ProtocolV1SessionCoordinator {
       let session = makeSession()
       _ = session.handleControl(try clientHello().serializedData())
        _ = session.completeCodecNegotiation()
        _ = session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(displayRequest())
        ).serializedData())
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
       _ = session.handleControl(try envelope(id: 3, payload: .videoConfigResult(result)).serializedData())
       return session
   }

    /// Drives a session to STREAMING with a client that advertises the given
    /// capabilities, so native pointer/keyboard negotiation can be exercised.
    private static func readySession(
        clientCapabilities: [VSCapability]
    ) throws -> ProtocolV1SessionCoordinator {
        let session = makeSession()
        var hello = clientHelloEnvelope()
        hello.clientHello.capabilities = clientCapabilities
        _ = session.handleControl(try hello.serializedData())
        _ = session.completeCodecNegotiation()
        _ = session.handleControl(try envelope(
            id: 2,
            payload: .startDisplayRequest(displayRequest())
        ).serializedData())
        var result = VSVideoConfigResult()
        result.configEpoch = 1
        result.streamID = 1
        result.accepted = true
        _ = session.handleControl(try envelope(id: 3, payload: .videoConfigResult(result)).serializedData())
        return session
    }

    private static func responseEnvelopes(_ actions: [ProtocolV1SessionAction]) throws -> [VSEnvelope] {
        try actions.compactMap { action in
            guard case .sendControl(let data) = action else { return nil }
            return try VSEnvelope(serializedBytes: data)
        }
    }

    private static func protocolError(_ actions: [ProtocolV1SessionAction]) throws -> VSProtocolError {
        guard case .protocolError(let error)? = try responseEnvelopes(actions).first?.payload else {
            throw SelfTestError.missingProtocolError
        }
        return error
    }

    private static func decodeMedia(_ data: Data) throws -> (header: VSMediaPacketHeader, payload: Data) {
        var cursor = 0
        var headerLength = 0
        var shift = 0
        while cursor < data.count, shift <= 28 {
            let byte = data[cursor]
            cursor += 1
            headerLength |= Int(byte & 0x7f) << shift
            if byte & 0x80 == 0 {
                let end = cursor + headerLength
                guard end <= data.count else { throw SelfTestError.invalidMedia }
                return (
                    try VSMediaPacketHeader(serializedBytes: data[cursor..<end]),
                    Data(data.dropFirst(end))
                )
            }
            shift += 7
        }
        throw SelfTestError.invalidMedia
    }

    private enum SelfTestError: Error {
        case missingProtocolError
        case invalidMedia
    }
}
