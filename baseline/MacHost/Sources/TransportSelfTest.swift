import Foundation
import Network
import VibeScreenProtocol

/// Loopback smoke test for the exact production transport implementation.
/// It validates startup capability negotiation, display configuration, a
/// metadata-bearing keyframe, ping/pong, and client-to-host touch parsing.
enum TransportSelfTest {
    private final class ResultState {
        let lock = NSLock()
        var receivedConfig = false
        var receivedKeyframe = false
        var receivedPong = false
        var receivedTouch = false
        var rejectedMalformedTouch = false
        var codecNegotiationCount = 0
        var failure: String?

        var isComplete: Bool {
            lock.withLock {
                receivedConfig && receivedKeyframe && receivedPong &&
                    receivedTouch && rejectedMalformedTouch &&
                    codecNegotiationCount == 1
            }
        }

        func recordFailureIfIncomplete(_ message: String) {
            lock.withLock {
                guard !(receivedConfig && receivedKeyframe && receivedPong &&
                        receivedTouch && rejectedMalformedTouch &&
                        codecNegotiationCount == 1) else { return }
                failure = message
            }
        }
    }

    static func run() -> Bool {
        let port: UInt16 = 55432
        let state = ResultState()
        let server = StreamingServer(port: port)
        server.setDisplaySize(width: 2000, height: 1124)
        server.onCodecNegotiated = { _, _, completion in
            state.lock.withLock { state.codecNegotiationCount += 1 }
            DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(50)) {
                completion(NegotiatedDisplayConfiguration(
                    width: 2000,
                    height: 1124,
                    rotation: 0
                ))
            }
        }
        server.onTouchEvent = { x, y, action, pointers, _, _, _ in
            state.lock.withLock {
                state.receivedTouch =
                    abs(x - 0.25) < 0.001 &&
                    abs(y - 0.75) < 0.001 &&
                    action == 1 &&
                    pointers == 1
            }
        }
        server.onInputCancelled = { _ in
            state.lock.withLock {
                state.rejectedMalformedTouch = true
            }
        }
        server.onClientConnected = { _ in
            let keyframe = Data([0, 0, 0, 1, 0x26, 0x01, 0xAA, 0x55])
            server.sendFrame(
                keyframe,
                timestamp: DispatchTime.now().uptimeNanoseconds,
                isKeyframe: true,
                sessionEpoch: server.currentSessionEpoch
            )
        }
        do {
            try server.start()
        } catch {
            print("Transport self-test: FAIL (listener startup: \(error))")
            return false
        }

        let conflictingServer = StreamingServer(port: port)
        let portConflictRejected: Bool
        do {
            try conflictingServer.start(timeout: 1)
            portConflictRejected = false
        } catch {
            portConflictRejected = true
        }
        conflictingServer.stop()
        guard portConflictRejected else {
            server.stop()
            print("Transport self-test: FAIL (second listener reused active port)")
            return false
        }

        let queue = DispatchQueue(label: "transport-self-test", qos: .userInteractive)
        let client = NWConnection(
            host: NWEndpoint.Host("127.0.0.1"),
            port: NWEndpoint.Port(rawValue: port)!,
            using: .tcp
        )
        var buffer = Data()

        func receiveNext() {
            client.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { data, _, complete, error in
                if let data {
                    buffer.append(data)
                    parseServerMessages(buffer: &buffer, state: state)
                }
                if let error {
                    state.recordFailureIfIncomplete(error.localizedDescription)
                    return
                }
                if complete {
                    state.recordFailureIfIncomplete("Server closed before all messages arrived")
                    return
                }
                receiveNext()
            }
        }

        client.stateUpdateHandler = { connectionState in
            switch connectionState {
            case .ready:
                // Opt in to frame metadata before the host finishes startup.
                client.send(content: Data([8]), completion: .contentProcessed { error in
                    if let error {
                        state.lock.withLock { state.failure = error.localizedDescription }
                        return
                    }

                    var messages = Data([4])
                    var pingValue: UInt64 = 0x0102_0304_0506_0708
                    withUnsafeBytes(of: &pingValue) { messages.append(contentsOf: $0) }
                    messages.append(2)
                    messages.append(1)
                    var x: Float = 0.25
                    var y: Float = 0.75
                    var action: Int32 = 1
                    withUnsafeBytes(of: &x) { messages.append(contentsOf: $0) }
                    withUnsafeBytes(of: &y) { messages.append(contentsOf: $0) }
                    withUnsafeBytes(of: &action) { messages.append(contentsOf: $0) }
                    messages.append(2)
                    messages.append(1)
                    var malformedX = Float.nan
                    var malformedY: Float = 0.5
                    var malformedAction: Int32 = 2
                    withUnsafeBytes(of: &malformedX) { messages.append(contentsOf: $0) }
                    withUnsafeBytes(of: &malformedY) { messages.append(contentsOf: $0) }
                    withUnsafeBytes(of: &malformedAction) { messages.append(contentsOf: $0) }
                    client.send(content: messages, completion: .contentProcessed { _ in })
                })
                receiveNext()

            case .failed(let error):
                state.recordFailureIfIncomplete(error.localizedDescription)

            default:
                break
            }
        }
        client.start(queue: queue)

        // Touch callbacks intentionally arrive on the main queue, so keep its
        // run loop moving instead of blocking it on a semaphore.
        let deadline = Date(timeIntervalSinceNow: 5)
        while Date() < deadline {
            let done = state.lock.withLock {
                state.failure != nil ||
                    (state.receivedConfig &&
                     state.receivedKeyframe &&
                     state.receivedPong &&
                     state.receivedTouch &&
                     state.rejectedMalformedTouch &&
                     state.codecNegotiationCount == 1)
            }
            if done { break }
            RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.01))
        }
        client.cancel()
        server.stop()

        let snapshot = state.lock.withLock {
            (
                state.receivedConfig,
                state.receivedKeyframe,
                state.receivedPong,
                state.receivedTouch,
                state.rejectedMalformedTouch,
                state.codecNegotiationCount,
                state.failure
            )
        }
        let protocolV1ReadyLifecycle = runProtocolV1Lifecycle()
        let protocolV1PreReadyStops = runProtocolV1PreReadyStops()
        let protocolV1Lifecycle = protocolV1ReadyLifecycle && protocolV1PreReadyStops
        let passed = snapshot.0 && snapshot.1 && snapshot.2 && snapshot.3 &&
            snapshot.4 && snapshot.5 == 1 && snapshot.6 == nil &&
            protocolV1Lifecycle
        print(
            "Transport self-test: \(passed ? "PASS" : "FAIL") " +
            "(config=\(snapshot.0), keyframe=\(snapshot.1), " +
            "pong=\(snapshot.2), touch=\(snapshot.3), " +
            "malformedTouchRejected=\(snapshot.4), portConflict=true, " +
            "codecNegotiations=\(snapshot.5), " +
            "protocolV1Lifecycle=\(protocolV1Lifecycle), " +
            "protocolV1ReadyLifecycle=\(protocolV1ReadyLifecycle), " +
            "protocolV1PreReadyStops=\(protocolV1PreReadyStops), " +
            "error=\(snapshot.6 ?? "none"))"
        )
        return passed
    }

    private static func runProtocolV1Lifecycle() -> Bool {
        let port: UInt16 = 55433
        let server = StreamingServer(port: port)
        let connected = DispatchSemaphore(value: 0)
        server.setDisplaySize(width: 1920, height: 1080, rotation: 90)
        server.onCodecNegotiated = { _, _, completion in
            completion(NegotiatedDisplayConfiguration(width: 1920, height: 1080, rotation: 90))
        }
        server.onClientConnected = { _ in connected.signal() }
        do {
            try server.start()
            let client = try BlockingProtocolClient(port: port)
            defer { client.cancel() }
            try client.send(Data([ProtocolV1Upgrade.offer]))
            guard try client.readExactly(2) == ProtocolV1Upgrade.acknowledgement else {
                server.stop()
                return false
            }

            var range = VSProtocolRange()
            range.minimum = 1
            range.maximum = 1
            var hello = VSClientHello()
            hello.supportedProtocols = range
            hello.deviceID = "transport-self-test"
            hello.deviceName = "Transport Self Test"
            hello.capabilities = [.touch, .telemetry]
            hello.requiredCapabilities = [.touch]
            hello.codecs = [.hevc]
            hello.transports = [.usb]
            try client.sendEnvelope(envelope(id: 1, payload: .clientHello(hello), scoped: false))
            let hostHello = try client.readEnvelope()
            let accepted = try client.readEnvelope()
            guard case .hostHello? = hostHello.payload,
                  case .sessionAccepted(let session)? = accepted.payload else {
                server.stop()
                return false
            }

            let sessionID = session.sessionID
            let sessionEpoch = session.sessionEpoch
            try client.sendEnvelope(envelope(
                id: 2,
                payload: .listDisplaysRequest(VSListDisplaysRequest()),
                sessionID: sessionID,
                sessionEpoch: sessionEpoch
            ))
            guard case .listDisplaysResponse? = try client.readEnvelope().payload else {
                server.stop()
                return false
            }
            var start = VSStartDisplayRequest()
            start.mode = .existing
            try client.sendEnvelope(envelope(
                id: 3,
                payload: .startDisplayRequest(start),
                sessionID: sessionID,
                sessionEpoch: sessionEpoch
            ))
            guard case .startDisplayResponse? = try client.readEnvelope().payload,
                  case .videoConfig(let video)? = try client.readEnvelope().payload,
                  video.rotationDegrees == 90 else {
                server.stop()
                return false
            }
            var result = VSVideoConfigResult()
            result.configEpoch = video.configEpoch
            result.streamID = video.streamID
            result.accepted = true
            try client.sendEnvelope(envelope(
                id: 4,
                payload: .videoConfigResult(result),
                sessionID: sessionID,
                sessionEpoch: sessionEpoch
            ))
            guard connected.wait(timeout: .now() + 2) == .success else {
                server.stop()
                return false
            }

            var ping = VSPing()
            ping.sequence = 99
            let rotationBarrierEntered = DispatchSemaphore(value: 0)
            let releaseRotationBarrier = DispatchSemaphore(value: 0)
            server.suspendNetworkQueueForSelfTest(
                entered: rotationBarrierEntered,
                resume: releaseRotationBarrier
            )
            guard rotationBarrierEntered.wait(timeout: .now() + 2) == .success else {
                server.stop()
                return false
            }
            try client.sendEnvelope(envelope(
                id: 5,
                payload: .ping(ping),
                sessionID: sessionID,
                sessionEpoch: sessionEpoch
            ))
            Thread.sleep(forTimeInterval: 0.05)
            server.updateRotation(270)
            releaseRotationBarrier.signal()
            let pongEnvelope = try client.readEnvelope()
            let rotationEnvelope = try client.readEnvelope()
            guard pongEnvelope.messageID < rotationEnvelope.messageID,
                  pongEnvelope.sessionID == sessionID,
                  rotationEnvelope.sessionID == sessionID,
                  case .pong(let pong)? = pongEnvelope.payload,
                  pong.sequence == 99,
                  case .displayChanged(let changed)? = rotationEnvelope.payload,
                  changed.rotationDegrees == 270 else {
                server.stop()
                return false
            }

            ping.sequence = 100
            let stopBarrierEntered = DispatchSemaphore(value: 0)
            let releaseStopBarrier = DispatchSemaphore(value: 0)
            server.suspendNetworkQueueForSelfTest(
                entered: stopBarrierEntered,
                resume: releaseStopBarrier
            )
            guard stopBarrierEntered.wait(timeout: .now() + 2) == .success else {
                server.stop()
                return false
            }
            try client.sendEnvelope(envelope(
                id: 6,
                payload: .ping(ping),
                sessionID: sessionID,
                sessionEpoch: sessionEpoch
            ))
            Thread.sleep(forTimeInterval: 0.05)
            let stopReturned = DispatchSemaphore(value: 0)
            DispatchQueue.global().async {
                server.stop()
                stopReturned.signal()
            }
            Thread.sleep(forTimeInterval: 0.05)
            releaseStopBarrier.signal()
            let finalPong = try client.readEnvelope()
            let shutdown = try client.readEnvelope()
            guard finalPong.messageID < shutdown.messageID,
                  finalPong.sessionID == sessionID,
                  shutdown.sessionID == sessionID,
                  case .pong(let pong)? = finalPong.payload,
                  pong.sequence == 100,
                  case .disconnectNotice(let notice)? = shutdown.payload,
                  notice.reasonCode == "host_shutdown",
                  !notice.mayResume else { return false }
            guard stopReturned.wait(timeout: .now() + 2) == .success else { return false }
            return true
        } catch {
            server.stop()
            return false
        }
    }

    private enum ProtocolStopStage: CaseIterable {
        case upgraded
        case preparingCodec
        case awaitingDisplay
        case awaitingVideoResult
    }

    private static func runProtocolV1PreReadyStops() -> Bool {
        for (offset, stage) in ProtocolStopStage.allCases.enumerated() {
            let port = UInt16(55_434 + offset)
            let server = StreamingServer(port: port)
            let codecRequested = DispatchSemaphore(value: 0)
            server.setDisplaySize(width: 1920, height: 1080, rotation: 90)
            server.onCodecNegotiated = { _, _, completion in
                codecRequested.signal()
                if stage != .preparingCodec {
                    completion(NegotiatedDisplayConfiguration(width: 1920, height: 1080, rotation: 90))
                }
            }
            do {
                try server.start()
                let client = try BlockingProtocolClient(port: port)
                defer { client.cancel() }
                try client.send(Data([ProtocolV1Upgrade.offer]))
                guard try client.readExactly(2) == ProtocolV1Upgrade.acknowledgement else {
                    server.stop()
                    return false
                }

                var sessionID = Data()
                var sessionEpoch: UInt64 = 0
                if stage != .upgraded {
                    var range = VSProtocolRange()
                    range.minimum = 1
                    range.maximum = 1
                    var hello = VSClientHello()
                    hello.supportedProtocols = range
                    hello.deviceID = "stop-stage"
                    hello.deviceName = "Stop Stage"
                    hello.capabilities = [.touch, .telemetry]
                    hello.requiredCapabilities = [.touch]
                    hello.codecs = [.hevc]
                    hello.transports = [.usb]
                    try client.sendEnvelope(envelope(id: 1, payload: .clientHello(hello), scoped: false))
                    guard codecRequested.wait(timeout: .now() + 2) == .success else {
                        server.stop()
                        return false
                    }
                    if stage != .preparingCodec {
                        _ = try client.readEnvelope()
                        let accepted = try client.readEnvelope()
                        guard case .sessionAccepted(let session)? = accepted.payload else {
                            server.stop()
                            return false
                        }
                        sessionID = session.sessionID
                        sessionEpoch = session.sessionEpoch
                    }
                }

                if stage == .awaitingVideoResult {
                    try client.sendEnvelope(envelope(
                        id: 2,
                        payload: .listDisplaysRequest(VSListDisplaysRequest()),
                        sessionID: sessionID,
                        sessionEpoch: sessionEpoch
                    ))
                    _ = try client.readEnvelope()
                    var start = VSStartDisplayRequest()
                    start.mode = .existing
                    try client.sendEnvelope(envelope(
                        id: 3,
                        payload: .startDisplayRequest(start),
                        sessionID: sessionID,
                        sessionEpoch: sessionEpoch
                    ))
                    _ = try client.readEnvelope()
                    _ = try client.readEnvelope()
                }

                server.stop()
                let shutdown = try client.readEnvelope()
                guard case .disconnectNotice(let notice)? = shutdown.payload,
                      notice.reasonCode == "host_shutdown",
                      !notice.mayResume else { return false }
                let expectedID: UInt64
                switch stage {
                case .upgraded, .preparingCodec: expectedID = 1
                case .awaitingDisplay: expectedID = 3
                case .awaitingVideoResult: expectedID = 6
                }
                guard shutdown.messageID == expectedID else { return false }
            } catch {
                server.stop()
                return false
            }
        }
        return true
    }

    private static func envelope(
        id: UInt64,
        payload: VSEnvelope.OneOf_Payload,
        sessionID: Data = Data(),
        sessionEpoch: UInt64 = 0,
        scoped: Bool = true
    ) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = id
        if scoped {
            envelope.sessionID = sessionID
            envelope.sessionEpoch = sessionEpoch
        }
        envelope.sentAtMonotonicNs = id
        envelope.payload = payload
        return envelope
    }

    private final class BlockingProtocolClient {
        private let connection: NWConnection
        private let queue = DispatchQueue(label: "transport-self-test-v1-client")
        private var buffered = Data()

        init(port: UInt16) throws {
            connection = NWConnection(
                host: "127.0.0.1",
                port: NWEndpoint.Port(rawValue: port)!,
                using: .tcp
            )
            let ready = DispatchSemaphore(value: 0)
            var failure: Error?
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready: ready.signal()
                case .failed(let error):
                    failure = error
                    ready.signal()
                default: break
                }
            }
            connection.start(queue: queue)
            guard ready.wait(timeout: .now() + 2) == .success, failure == nil else {
                throw failure ?? ProtocolClientError.timeout
            }
        }

        func cancel() { connection.cancel() }

        func send(_ data: Data) throws {
            let completed = DispatchSemaphore(value: 0)
            var failure: Error?
            connection.send(content: data, completion: .contentProcessed { error in
                failure = error
                completed.signal()
            })
            guard completed.wait(timeout: .now() + 2) == .success else {
                throw ProtocolClientError.timeout
            }
            if let failure { throw failure }
        }

        func sendEnvelope(_ envelope: VSEnvelope) throws {
            try send(ProtocolV1TransportFrame(
                channel: .control,
                payload: try envelope.serializedData()
            ).encoded())
        }

        func readEnvelope() throws -> VSEnvelope {
            let header = try readExactly(5)
            guard header.first == ProtocolV1LogicalChannel.control.rawValue else {
                throw ProtocolClientError.invalidFrame
            }
            let length = header.dropFirst().reduce(UInt32.zero) { ($0 << 8) | UInt32($1) }
            guard length <= ProtocolV1Framer.maximumPayloadBytes else {
                throw ProtocolClientError.invalidFrame
            }
            return try VSEnvelope(serializedBytes: readExactly(Int(length)))
        }

        func readExactly(_ count: Int) throws -> Data {
            while buffered.count < count {
                let received = DispatchSemaphore(value: 0)
                var chunk: Data?
                var failure: Error?
                var complete = false
                connection.receive(minimumIncompleteLength: 1, maximumLength: 65_536) {
                    data, _, isComplete, error in
                    chunk = data
                    failure = error
                    complete = isComplete
                    received.signal()
                }
                guard received.wait(timeout: .now() + 2) == .success else {
                    throw ProtocolClientError.timeout
                }
                if let failure { throw failure }
                if let chunk { buffered.append(chunk) }
                if complete && buffered.count < count { throw ProtocolClientError.closed }
            }
            let result = Data(buffered.prefix(count))
            buffered.removeFirst(count)
            return result
        }
    }

    private enum ProtocolClientError: Error {
        case timeout
        case invalidFrame
        case closed
    }

    private static func parseServerMessages(buffer: inout Data, state: ResultState) {
        while let type = buffer.first {
            switch type {
            case 1:
                guard buffer.count >= 13 else { return }
                let width = readInt32(buffer, offset: 1)
                let height = readInt32(buffer, offset: 5)
                let rotation = readInt32(buffer, offset: 9)
                state.lock.withLock {
                    state.receivedConfig = width == 2000 && height == 1124 && rotation == 0
                }
                buffer.removeFirst(13)

            case 5:
                guard buffer.count >= 9 else { return }
                state.lock.withLock { state.receivedPong = true }
                buffer.removeFirst(9)

            case 6:
                guard buffer.count >= 14 else { return }
                let payloadSize = Int(readInt32(buffer, offset: 1))
                guard payloadSize >= 0, buffer.count >= 14 + payloadSize else { return }
                let flags = buffer[buffer.index(buffer.startIndex, offsetBy: 5)]
                let payloadStart = buffer.index(buffer.startIndex, offsetBy: 14)
                let payloadEnd = buffer.index(payloadStart, offsetBy: payloadSize)
                let payload = buffer[payloadStart..<payloadEnd]
                state.lock.withLock {
                    state.receivedKeyframe =
                        flags & 1 == 1 &&
                        payload.elementsEqual([0, 0, 0, 1, 0x26, 0x01, 0xAA, 0x55])
                }
                buffer.removeFirst(14 + payloadSize)

            default:
                state.lock.withLock { state.failure = "Unexpected server message type \(type)" }
                return
            }
        }
    }

    private static func readInt32(_ data: Data, offset: Int) -> Int32 {
        data.withUnsafeBytes {
            $0.loadUnaligned(fromByteOffset: offset, as: Int32.self).bigEndian
        }
    }
}
