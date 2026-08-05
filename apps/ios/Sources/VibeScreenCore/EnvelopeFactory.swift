import Foundation
import VibeScreenProtocol

public struct EnvelopeFactory: Sendable {
    private var nextMessageID: UInt64

    public init(firstMessageID: UInt64 = 1) {
        nextMessageID = firstMessageID
    }

    public mutating func clientHello(
        deviceID: String,
        deviceName: String,
        capabilities: [VSCapability],
        codecs: [VSCodec],
        transports: [VSTransportKind] = [.lan],
        resourceLimits: VSResourceLimits = VSResourceLimits(),
        videoDecodeCapabilities: [VSVideoDecodeCapability] = []
    ) -> VSEnvelope {
        var supported = VSProtocolRange()
        supported.minimum = SessionState.protocolVersion
        supported.maximum = SessionState.protocolVersion

        var hello = VSClientHello()
        hello.supportedProtocols = supported
        hello.deviceID = deviceID
        hello.deviceName = deviceName
        hello.capabilities = capabilities
        hello.codecs = codecs
        hello.transports = transports
        hello.resourceLimits = resourceLimits
        hello.videoDecodeCapabilities = videoDecodeCapabilities

        var envelope = baseEnvelope()
        envelope.clientHello = hello
        return envelope
    }

    public mutating func touch(
        inputID: UInt64,
        pointerID: UInt32,
        phase: VSInputPhase,
        x: Double,
        y: Double,
        pressure: Double,
        sessionID: Data,
        sessionEpoch: UInt64,
        target: VSInputTarget? = nil
    ) -> VSEnvelope {
        var point = VSNormalizedPoint()
        point.x = min(max(x, 0), 1)
        point.y = min(max(y, 0), 1)

        var event = VSTouchEvent()
        event.inputID = inputID
        event.pointerID = pointerID
        event.phase = phase
        event.position = point
        event.pressure = min(max(pressure, 0), 1)
        if let target { event.target = target }

        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.touchEvent = event
        return envelope
    }

    public mutating func listDisplays(sessionID: Data, sessionEpoch: UInt64) -> VSEnvelope {
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.listDisplaysRequest = VSListDisplaysRequest()
        return envelope
    }

    public mutating func ping(
        sequence: UInt64,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var ping = VSPing()
        ping.sequence = sequence
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.ping = ping
        return envelope
    }

    public mutating func pong(
        sequence: UInt64,
        correlationID: UInt64,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var pong = VSPong()
        pong.sequence = sequence
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.correlationID = correlationID
        envelope.pong = pong
        return envelope
    }

    public mutating func disconnectNotice(
        reasonCode: String,
        mayResume: Bool,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var notice = VSDisconnectNotice()
        notice.reasonCode = reasonCode
        notice.mayResume = mayResume
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.disconnectNotice = notice
        return envelope
    }

    public mutating func startExistingDisplay(
        displayID: String,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var request = VSStartDisplayRequest()
        request.mode = .existing
        request.sourceDisplayID = displayID
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.startDisplayRequest = request
        return envelope
    }

    public mutating func clipboardContent(
        _ content: VSClipboardContent,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.clipboardContent = content
        return envelope
    }

    public mutating func fileOffer(
        _ offer: VSFileOffer,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.fileOffer = offer
        return envelope
    }

    public mutating func fileAccept(
        _ response: VSFileAccept,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.fileAccept = response
        return envelope
    }

    public mutating func fileTransferComplete(
        _ result: VSFileTransferComplete,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.fileTransferComplete = result
        return envelope
    }

    public mutating func fileTransferCancel(
        _ cancel: VSFileTransferCancel,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.fileTransferCancel = cancel
        return envelope
    }

    public mutating func audioConfigResult(
        _ result: VSAudioConfigResult,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.audioConfigResult = result
        return envelope
    }

    public mutating func videoConfigResult(
        _ result: VSVideoConfigResult,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.videoConfigResult = result
        return envelope
    }

    public mutating func hostActionInvoke(
        _ invocation: VSHostActionInvoke,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.hostActionInvoke = invocation
        return envelope
    }

    public mutating func managedPolicyStatus(
        _ status: VSManagedPolicyStatus,
        sessionID: Data,
        sessionEpoch: UInt64
    ) -> VSEnvelope {
        var envelope = baseEnvelope(sessionID: sessionID, sessionEpoch: sessionEpoch)
        envelope.managedPolicyStatus = status
        return envelope
    }

    private mutating func baseEnvelope(
        sessionID: Data = Data(),
        sessionEpoch: UInt64 = 0
    ) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = SessionState.protocolVersion
        envelope.messageID = nextMessageID
        nextMessageID += 1
        envelope.sessionID = sessionID
        envelope.sessionEpoch = sessionEpoch
        envelope.sentAtMonotonicNs = DispatchTime.now().uptimeNanoseconds
        return envelope
    }
}
