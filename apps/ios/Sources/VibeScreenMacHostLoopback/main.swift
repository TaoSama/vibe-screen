import Foundation
import VibeScreenCore
import VibeScreenProtocol

private enum LoopbackError: Error, LocalizedError {
    case timeout
    case transport(String)
    case unexpected(String)

    var errorDescription: String? {
        switch self {
        case .timeout: "等待 MacHost 消息超时"
        case let .transport(message): "传输失败：\(message)"
        case let .unexpected(message): "MacHost 返回了意外结果：\(message)"
        }
    }
}

private final class FrameInbox: @unchecked Sendable {
    private let condition = NSCondition()
    private var results: [Result<TransportFrame, Error>] = []

    func append(_ result: Result<TransportFrame, Error>) {
        condition.lock()
        results.append(result)
        condition.signal()
        condition.unlock()
    }

    func next(timeout: TimeInterval = 4) throws -> TransportFrame {
        let deadline = Date(timeIntervalSinceNow: timeout)
        condition.lock()
        defer { condition.unlock() }
        while results.isEmpty {
            guard condition.wait(until: deadline) else { throw LoopbackError.timeout }
        }
        switch results.removeFirst() {
        case let .success(frame): return frame
        case let .failure(error): throw LoopbackError.transport(error.localizedDescription)
        }
    }
}

private struct MacHostLoopbackClient {
    static let token = Data((0..<32).map(UInt8.init))
    static let expectedMedia = Data([0, 0, 0, 1, 0x65, 0x88, 0x84, 0x21])

    private let inbox = FrameInbox()

    @MainActor
    func run(invalidTarget: Bool, port: UInt16) async throws {
        let connectionOwner = ConnectionOwner()
        let sessionOwner = SessionOwner(connectionOwner: connectionOwner)
        let transport = TCPTransport { delivery in
            guard delivery.owner == connectionOwner else { return }
            inbox.append(delivery.result)
        }
        let outbox = ControlOutbox { owner, frame, timeout in
            try await transport.send(frame, owner: owner, timeout: timeout)
        }
        outbox.activate(owner: sessionOwner)
        defer {
            outbox.deactivate()
            transport.disconnect()
        }

        let encodedToken = Self.token.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        let pairing = try TrustedLANPairing(
            urlString: "telemachus://127.0.0.1:\(port)?t=\(encodedToken)&name=Loopback%20Mac"
        )

        var session = SessionState()
        try session.beginConnection()
        try await transport.connect(
            pairing: pairing,
            deviceName: "iOS Core Loopback",
            owner: connectionOwner
        )
        try session.transportConnected()

        let localCapabilities: Set<VSCapability> = [.touch, .telemetry]
        try await outbox.sendAndWait(owner: sessionOwner) { factory in
            factory.clientHello(
                deviceID: "ios-core-loopback",
                deviceName: "iOS Core Loopback",
                capabilities: Array(localCapabilities),
                codecs: [.h264],
                transports: [.lan]
            )
        }

        let hostHello = try nextControl()
        guard case .hostHello(let hello)? = hostHello.payload,
              hello.selectedProtocol == SessionState.protocolVersion,
              hello.codecs.contains(.h264),
              hello.capabilities.contains(.touch) else {
            throw LoopbackError.unexpected("HostHello")
        }
        let acceptedEnvelope = try nextControl()
        guard case .sessionAccepted(let accepted)? = acceptedEnvelope.payload,
              !accepted.sessionID.isEmpty,
              accepted.sessionEpoch > 0,
              accepted.negotiatedCapabilities.contains(.touch) else {
            throw LoopbackError.unexpected("SessionAccepted")
        }
        try session.accept(
            selectedProtocol: hello.selectedProtocol,
            sessionID: accepted.sessionID,
            epoch: accepted.sessionEpoch,
            localCapabilities: localCapabilities,
            hostCapabilities: Set(hello.capabilities)
        )

        try await outbox.sendAndWait(owner: sessionOwner) { factory in
            factory.listDisplays(sessionID: session.sessionID, sessionEpoch: session.sessionEpoch)
        }
        let listEnvelope = try nextControl()
        guard case .listDisplaysResponse(let list)? = listEnvelope.payload,
              list.displays.count == 1,
              let display = list.displays.first,
              !display.displayID.isEmpty else {
            throw LoopbackError.unexpected("ListDisplaysResponse")
        }

        try await outbox.sendAndWait(owner: sessionOwner) { factory in
            factory.startExistingDisplay(
                displayID: display.displayID,
                sessionID: session.sessionID,
                sessionEpoch: session.sessionEpoch
            )
        }
        let startEnvelope = try nextControl()
        guard case .startDisplayResponse(let started)? = startEnvelope.payload,
              started.accepted,
              started.streamID > 0,
              started.display.displayID == display.displayID else {
            throw LoopbackError.unexpected("StartDisplayResponse")
        }
        let configEnvelope = try nextControl()
        guard case .videoConfig(let config)? = configEnvelope.payload,
              config.streamID == started.streamID,
              config.configEpoch > 0,
              config.codec == .h264 else {
            throw LoopbackError.unexpected("VideoConfig")
        }
        var configResult = VSVideoConfigResult()
        configResult.configEpoch = config.configEpoch
        configResult.streamID = config.streamID
        configResult.accepted = true
        try await outbox.sendAndWait(owner: sessionOwner) { factory in
            factory.videoConfigResult(
                configResult,
                sessionID: session.sessionID,
                sessionEpoch: session.sessionEpoch
            )
        }
        try session.startStreaming(streamID: config.streamID)

        let mediaFrame = try inbox.next()
        guard mediaFrame.channel == .video else {
            throw LoopbackError.unexpected("expected video channel")
        }
        let media = try MediaPacket(serializedFrame: mediaFrame.payload)
        guard media.payload == Self.expectedMedia,
              media.header.sessionEpoch == session.sessionEpoch,
              media.header.streamID == config.streamID,
              media.header.configEpoch == config.configEpoch,
              media.header.keyframe,
              media.header.codec == .h264 else {
            throw LoopbackError.unexpected("media framing")
        }

        let pingSequence: UInt64 = 0x0102_0304_0506_0708
        try await outbox.sendAndWait(owner: sessionOwner) { factory in
            factory.ping(
                sequence: pingSequence,
                sessionID: session.sessionID,
                sessionEpoch: session.sessionEpoch
            )
        }
        let pongEnvelope = try nextControl()
        guard case .pong(let pong)? = pongEnvelope.payload,
              pong.sequence == pingSequence else {
            throw LoopbackError.unexpected("Pong")
        }

        var target = VSInputTarget()
        target.displayID = invalidTarget ? "wrong-display" : display.displayID
        target.streamID = invalidTarget ? config.streamID + 1 : config.streamID
        try await outbox.sendAndWait(owner: sessionOwner) { factory in
            factory.touch(
                inputID: 1,
                pointerID: 7,
                phase: .began,
                x: 0.25,
                y: 0.75,
                pressure: 0.5,
                sessionID: session.sessionID,
                sessionEpoch: session.sessionEpoch,
                target: target
            )
        }

        let terminalEnvelope = try nextControl()
        if invalidTarget {
            guard case .protocolError(let protocolError)? = terminalEnvelope.payload,
                  protocolError.code == .invalidState else {
                throw LoopbackError.unexpected("invalid-target ProtocolError")
            }
            print(
                "iOS Core MacHost loopback: PASS " +
                "(scenario=invalid-target, port=\(port), protocolError=invalidState)"
            )
            return
        }
        let disconnectEnvelope = terminalEnvelope
        guard case .disconnectNotice(let notice)? = disconnectEnvelope.payload,
              notice.reasonCode == "host_shutdown",
              !notice.mayResume else {
            throw LoopbackError.unexpected("DisconnectNotice")
        }
        print(
            "iOS Core MacHost loopback: PASS " +
            "(port=\(port), auth=SSWA/SSWR, upgrade=0D/0D01, " +
            "hello=true, displays=true, " +
            "videoAck=true, media=true, pong=true, targetedTouch=true, disconnect=true)"
        )
    }

    private func nextControl() throws -> VSEnvelope {
        let frame = try inbox.next()
        guard frame.channel == .control else {
            throw LoopbackError.unexpected("expected control channel")
        }
        return try EnvelopeCodec.deserialize(frame.payload)
    }
}

Task {
    do {
        let environment = ProcessInfo.processInfo.environment
        let scenario = environment["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO"] ?? "lifecycle"
        guard scenario == "lifecycle" || scenario == "invalid-target" else {
            throw LoopbackError.unexpected("unknown loopback scenario")
        }
        let port = try MacHostLoopbackTestConfiguration.port(environment: environment)
        try await MacHostLoopbackClient().run(
            invalidTarget: scenario == "invalid-target",
            port: port
        )
        exit(EXIT_SUCCESS)
    } catch {
        print("iOS Core MacHost loopback: FAIL (\(error.localizedDescription))")
        exit(EXIT_FAILURE)
    }
}
dispatchMain()
