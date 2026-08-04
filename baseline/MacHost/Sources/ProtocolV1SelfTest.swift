import Foundation
import VibeScreenProtocol

enum ProtocolV1SelfTest {
    private static let sessionID = Data(repeating: 0xAB, count: 16)
    private static let sessionEpoch: UInt64 = 7

    static func run() -> Bool {
        var failures: [String] = []
        testFramer(failures: &failures)
        testGoldenBytes(failures: &failures)
        testSharedGoldenFixtures(failures: &failures)
        testNegotiationAndMediaGate(failures: &failures)
        testRejections(failures: &failures)
        testInputHeartbeatAndMedia(failures: &failures)
        if failures.isEmpty {
            print("Protocol v1 self-test: PASS (framing, golden, negotiation, display/video gate, epoch, input, heartbeat, error, media)")
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
            let root = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("contracts/fixtures/messages/v1/bin")
            let controls = [
                "client_hello", "host_hello", "session_accepted",
                "list_displays_request", "list_displays_response",
                "start_display_request", "start_display_response",
                "video_config", "video_config_result", "touch", "ping", "pong",
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
            let session = makeSession()
            let helloResponses = try responseEnvelopes(
                session.handleControl(try clientHello().serializedData())
            )
            guard helloResponses.count == 2,
                  case .hostHello? = helloResponses[0].payload,
                  case .sessionAccepted(let accepted)? = helloResponses[1].payload,
                  accepted.sessionID == sessionID else {
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
                  config.bitrateKbps == 20_000 else {
                failures.append("StartDisplay did not produce the configured VideoConfig")
                return
            }
            guard try session.makeMediaFrame(payload: Data([1]), timestamp: 1, keyframe: true) == nil else {
                failures.append("media escaped before VideoConfigResult")
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
            capabilityHello.clientHello.requiredCapabilities = [.keyboard]
            guard try protocolError(capabilitySession.handleControl(capabilityHello.serializedData())).code == .unsupportedCapability else {
                failures.append("unsupported required capability was not rejected")
                return
            }

            let staleSession = makeSession()
            _ = staleSession.handleControl(try clientHello().serializedData())
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

    private static func makeSession() -> ProtocolV1SessionCoordinator {
        ProtocolV1SessionCoordinator(configuration: ProtocolV1SessionConfiguration(
            sessionID: sessionID,
            sessionEpoch: sessionEpoch,
            displayWidth: 1920,
            displayHeight: 1080,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: [.touch, .telemetry],
            requiredClientCapabilities: [.touch],
            supportedCodecs: [.hevc, .h264],
            hostID: "host",
            hostName: "Mac",
            displayID: "active-display",
            displayName: "Display",
            displayIsVirtual: true
        ))
    }

    private static func clientHello() -> VSEnvelope {
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "device"
        hello.deviceName = "Tablet"
        hello.capabilities = [.touch, .telemetry]
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

    private static func displayRequest() -> VSStartDisplayRequest {
        var request = VSStartDisplayRequest()
        request.mode = .existing
        request.sourceDisplayID = "active-display"
        return request
    }

    private static func readySession() throws -> ProtocolV1SessionCoordinator {
        let session = makeSession()
        _ = session.handleControl(try clientHello().serializedData())
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
