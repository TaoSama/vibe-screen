import Foundation
import VibeScreenProtocol

enum InternetProductProtocolError: Error, Equatable, LocalizedError {
    case controlPayloadTooLarge(actual: Int, maximum: Int)
    case mediaPayloadTooLarge(actual: Int, maximum: Int)
    case malformedControl(String)
    case unsupportedProtocol(UInt32)
    case sessionMismatch
    case staleSessionEpoch(received: UInt64, expected: UInt64)
    case invalidMessageID
    case unexpectedMessage(String)
    case peerIdentityMismatch
    case missingCapability(VSCapability)
    case unsupportedCodec
    case rejectedVideoConfiguration(String)
    case invalidTouch

    var errorDescription: String? {
        switch self {
        case .controlPayloadTooLarge(let actual, let maximum):
            return "Control message is \(actual) bytes; maximum is \(maximum)."
        case .mediaPayloadTooLarge(let actual, let maximum):
            return "Media message is \(actual) bytes; maximum is \(maximum)."
        case .malformedControl(let reason): return "Malformed Protocol v1 control message: \(reason)"
        case .unsupportedProtocol(let version): return "Internet peer selected unsupported protocol \(version)."
        case .sessionMismatch: return "Protocol message belongs to a different Internet session."
        case .staleSessionEpoch(let received, let expected):
            return "Protocol message uses session epoch \(received); expected \(expected)."
        case .invalidMessageID: return "Protocol control message ID must be positive and monotonic."
        case .unexpectedMessage(let name): return "Unexpected Protocol v1 message while \(name)."
        case .peerIdentityMismatch: return "The connected peer does not match the paired device identity."
        case .missingCapability(let capability):
            return "Internet peer omitted required capability \(capability.rawValue)."
        case .unsupportedCodec: return "Internet peer does not support the configured video codec."
        case .rejectedVideoConfiguration(let reason):
            return "Internet peer rejected the video configuration: \(reason)"
        case .invalidTouch: return "Internet peer sent an invalid touch event."
        }
    }
}

struct InternetProductVideoConfiguration: Equatable {
    let codec: VSCodec
    let width: Int
    let height: Int
    let framesPerSecond: Int
    let bitrateKbps: Int
    let streamID: UInt64
    let configEpoch: UInt64
    let rotationDegrees: Int

    init(
        codec: VSCodec,
        width: Int,
        height: Int,
        framesPerSecond: Int,
        bitrateKbps: Int,
        streamID: UInt64 = 1,
        configEpoch: UInt64 = 1,
        rotationDegrees: Int = 0
    ) {
        self.codec = codec
        self.width = width
        self.height = height
        self.framesPerSecond = framesPerSecond
        self.bitrateKbps = bitrateKbps
        self.streamID = streamID
        self.configEpoch = configEpoch
        self.rotationDegrees = rotationDegrees
    }

    func validate() throws {
        guard codec == .h264 || codec == .hevc,
              width > 0, height > 0,
              framesPerSecond > 0, bitrateKbps > 0,
              streamID > 0, configEpoch > 0,
              [0, 90, 180, 270].contains(rotationDegrees) else {
            throw InternetProductProtocolError.unsupportedCodec
        }
    }

    func replacingRotation(_ rotationDegrees: Int) throws -> Self {
        guard configEpoch < UInt64.max else {
            throw InternetProductProtocolError.rejectedVideoConfiguration(
                "Video configuration epoch is exhausted."
            )
        }
        return Self(
            codec: codec,
            width: width,
            height: height,
            framesPerSecond: framesPerSecond,
            bitrateKbps: bitrateKbps,
            streamID: streamID,
            configEpoch: configEpoch + 1,
            rotationDegrees: rotationDegrees
        )
    }
}

struct InternetProductProtocolCodec {
    static let protocolVersion: UInt32 = 1
    static let requiredCapabilities: Set<VSCapability> = [
        .deviceIdentity,
        .endToEndEncryption,
        .replayProtection,
    ]

    let sessionID: Data
    let sessionEpoch: UInt64
    let hostID: String
    let hostName: String
    let peerDeviceID: String
    private(set) var video: InternetProductVideoConfiguration
    let maximumControlBytes: Int
    let maximumMediaBytes: Int

    private(set) var nextMessageID: UInt64 = 1
    private(set) var nextFrameID: UInt64 = 1
    private(set) var lastReceivedMessageID: UInt64 = 0

    init(
        sessionIdentifier: String,
        sessionEpoch: UInt64,
        hostID: String,
        hostName: String,
        peerDeviceID: String,
        video: InternetProductVideoConfiguration,
        limits: InternetTransportLimits
    ) throws {
        guard !sessionIdentifier.isEmpty, sessionEpoch > 0,
              !hostID.isEmpty, !peerDeviceID.isEmpty else {
            throw InternetProductProtocolError.sessionMismatch
        }
        try video.validate()
        self.sessionID = Data(sessionIdentifier.utf8)
        self.sessionEpoch = sessionEpoch
        self.hostID = hostID
        self.hostName = hostName
        self.peerDeviceID = peerDeviceID
        self.video = video
        self.maximumControlBytes = limits.maximumControlMessageBytes
        self.maximumMediaBytes = limits.maximumMediaFrameBytes
    }

    mutating func decodeControl(_ data: Data, allowUnscopedHello: Bool = false) throws -> VSEnvelope {
        guard data.count <= maximumControlBytes else {
            throw InternetProductProtocolError.controlPayloadTooLarge(
                actual: data.count,
                maximum: maximumControlBytes
            )
        }
        let envelope: VSEnvelope
        do {
            envelope = try VSEnvelope(serializedBytes: data)
        } catch {
            throw InternetProductProtocolError.malformedControl(error.localizedDescription)
        }
        guard envelope.protocolVersion == Self.protocolVersion else {
            throw InternetProductProtocolError.unsupportedProtocol(envelope.protocolVersion)
        }
        guard envelope.messageID > lastReceivedMessageID else {
            throw InternetProductProtocolError.invalidMessageID
        }
        if allowUnscopedHello, case .clientHello = envelope.payload {
            guard envelope.sessionID.isEmpty || envelope.sessionID == sessionID,
                  envelope.sessionEpoch == 0 || envelope.sessionEpoch == sessionEpoch else {
                throw InternetProductProtocolError.sessionMismatch
            }
        } else {
            guard envelope.sessionID == sessionID else {
                throw InternetProductProtocolError.sessionMismatch
            }
            guard envelope.sessionEpoch == sessionEpoch else {
                throw InternetProductProtocolError.staleSessionEpoch(
                    received: envelope.sessionEpoch,
                    expected: sessionEpoch
                )
            }
        }
        lastReceivedMessageID = envelope.messageID
        return envelope
    }

    func validate(_ hello: VSClientHello) throws {
        guard hello.deviceID == peerDeviceID else {
            throw InternetProductProtocolError.peerIdentityMismatch
        }
        guard hello.supportedProtocols.minimum <= Self.protocolVersion,
              hello.supportedProtocols.maximum >= Self.protocolVersion else {
            throw InternetProductProtocolError.unsupportedProtocol(
                hello.supportedProtocols.maximum
            )
        }
        let capabilities = Set(hello.capabilities)
        for capability in Self.requiredCapabilities where !capabilities.contains(capability) {
            throw InternetProductProtocolError.missingCapability(capability)
        }
        guard hello.codecs.contains(video.codec) else {
            throw InternetProductProtocolError.unsupportedCodec
        }
    }

    mutating func hostHello() throws -> Data {
        var hello = VSHostHello()
        hello.selectedProtocol = Self.protocolVersion
        hello.hostID = hostID
        hello.hostName = hostName
        hello.capabilities = (Array(Self.requiredCapabilities) + [.touch]).sorted {
            $0.rawValue < $1.rawValue
        }
        hello.codecs = [video.codec]
        var envelope = baseEnvelope()
        envelope.hostHello = hello
        return try encode(envelope)
    }

    mutating func sessionAccepted(
        heartbeatIntervalMilliseconds: UInt32,
        peerSupportsTouch: Bool
    ) throws -> Data {
        var accepted = VSSessionAccepted()
        accepted.sessionID = sessionID
        accepted.sessionEpoch = sessionEpoch
        accepted.heartbeatIntervalMs = heartbeatIntervalMilliseconds
        accepted.negotiatedCapabilities = (
            Array(Self.requiredCapabilities) + (peerSupportsTouch ? [.touch] : [])
        ).sorted { $0.rawValue < $1.rawValue }
        var envelope = baseEnvelope()
        envelope.sessionAccepted = accepted
        return try encode(envelope)
    }

    mutating func videoConfiguration() throws -> Data {
        var dimensions = VSDimensions()
        dimensions.width = UInt32(video.width)
        dimensions.height = UInt32(video.height)
        var configuration = VSVideoConfig()
        configuration.configEpoch = video.configEpoch
        configuration.codec = video.codec
        configuration.encodedSize = dimensions
        configuration.framesPerSecond = UInt32(video.framesPerSecond)
        configuration.bitrateKbps = UInt32(video.bitrateKbps)
        configuration.streamID = video.streamID
        configuration.rotationDegrees = UInt32(video.rotationDegrees)
        var envelope = baseEnvelope()
        envelope.videoConfig = configuration
        return try encode(envelope)
    }

    mutating func updateRotation(_ rotationDegrees: Int) throws -> [Data] {
        video = try video.replacingRotation(rotationDegrees)
        var size = VSDimensions()
        size.width = UInt32(video.width)
        size.height = UInt32(video.height)
        var display = VSDisplayDescriptor()
        display.displayID = "internet-display"
        display.name = "Internet Preview Display"
        display.logicalSize = size
        display.scaleFactor = 1
        var changed = VSDisplayChanged()
        changed.display = display
        changed.rotationDegrees = UInt32(video.rotationDegrees)
        var envelope = baseEnvelope()
        envelope.displayChanged = changed
        return [try encode(envelope), try videoConfiguration()]
    }

    mutating func pong(sequence: UInt64, correlationID: UInt64) throws -> Data {
        var pong = VSPong()
        pong.sequence = sequence
        var envelope = baseEnvelope(correlationID: correlationID)
        envelope.pong = pong
        return try encode(envelope)
    }

    mutating func ping(sequence: UInt64) throws -> Data {
        var ping = VSPing()
        ping.sequence = sequence
        var envelope = baseEnvelope()
        envelope.ping = ping
        return try encode(envelope)
    }

    mutating func mediaFrame(
        payload: Data,
        timestamp: UInt64,
        isKeyframe: Bool
    ) throws -> EncodedInternetFrame {
        guard payload.count <= maximumMediaBytes else {
            throw InternetProductProtocolError.mediaPayloadTooLarge(
                actual: payload.count,
                maximum: maximumMediaBytes
            )
        }
        var header = VSMediaPacketHeader()
        header.streamID = video.streamID
        header.sessionEpoch = sessionEpoch
        header.configEpoch = video.configEpoch
        header.frameID = nextFrameID
        header.fragmentIndex = 0
        header.fragmentCount = 1
        header.captureTimestampNs = timestamp
        header.keyframe = isKeyframe
        header.codec = video.codec
        header.payloadLength = UInt32(payload.count)
        nextFrameID &+= 1

        let headerBytes = try header.serializedData()
        var framed = Data()
        appendVarint(headerBytes.count, to: &framed)
        framed.append(headerBytes)
        framed.append(payload)
        guard framed.count <= maximumMediaBytes else {
            throw InternetProductProtocolError.mediaPayloadTooLarge(
                actual: framed.count,
                maximum: maximumMediaBytes
            )
        }
        return EncodedInternetFrame(
            payload: framed,
            captureTimestamp: timestamp,
            isKeyframe: isKeyframe
        )
    }

    private mutating func baseEnvelope(correlationID: UInt64 = 0) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = Self.protocolVersion
        envelope.messageID = nextMessageID
        nextMessageID &+= 1
        envelope.correlationID = correlationID
        envelope.sessionID = sessionID
        envelope.sessionEpoch = sessionEpoch
        envelope.sentAtMonotonicNs = DispatchTime.now().uptimeNanoseconds
        return envelope
    }

    private func encode(_ envelope: VSEnvelope) throws -> Data {
        let data = try envelope.serializedData()
        guard data.count <= maximumControlBytes else {
            throw InternetProductProtocolError.controlPayloadTooLarge(
                actual: data.count,
                maximum: maximumControlBytes
            )
        }
        return data
    }

    private func appendVarint(_ value: Int, to output: inout Data) {
        var remaining = UInt64(value)
        while remaining >= 0x80 {
            output.append(UInt8(remaining & 0x7f) | 0x80)
            remaining >>= 7
        }
        output.append(UInt8(remaining))
    }
}
