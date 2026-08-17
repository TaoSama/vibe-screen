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
    case invalidStylus
    case invalidController

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
        case .invalidStylus: return "Internet peer sent an invalid stylus event."
        case .invalidController: return "Internet peer sent an invalid controller event."
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

    func replacing(
        width: Int? = nil,
        height: Int? = nil,
        framesPerSecond: Int? = nil,
        bitrateKbps: Int? = nil,
        configEpoch: UInt64,
        rotationDegrees: Int? = nil
    ) throws -> Self {
        let replacement = Self(
            codec: codec,
            width: width ?? self.width,
            height: height ?? self.height,
            framesPerSecond: framesPerSecond ?? self.framesPerSecond,
            bitrateKbps: bitrateKbps ?? self.bitrateKbps,
            streamID: streamID,
            configEpoch: configEpoch,
            rotationDegrees: rotationDegrees ?? self.rotationDegrees
        )
        try replacement.validate()
        return replacement
    }
}

struct InternetAdaptiveVideoPlan: Equatable {
    let width: Int
    let height: Int
    let framesPerSecond: Int
    let bitrateMbps: Int

    var bitrateKbps: Int { bitrateMbps * 1_000 }

    init?(baseline: InternetProductVideoConfiguration, profile: AdaptiveMediaProfile) {
        guard baseline.width >= 2, baseline.height >= 2,
              baseline.framesPerSecond > 0, baseline.bitrateKbps >= 1_000,
              profile.resolutionScale.isFinite, profile.resolutionScale > 0,
              profile.framesPerSecond > 0 else { return nil }

        let scale = min(1, profile.resolutionScale)
        func scaledEvenDimension(_ value: Int) -> Int {
            let scaled = Int((Double(value) * scale).rounded(.down))
            return max(2, min(value, scaled) & ~1)
        }

        let targetWholeMbps = profile.targetBitrateBps / 1_000_000
            + (profile.targetBitrateBps % 1_000_000 >= 500_000 ? 1 : 0)
        guard targetWholeMbps <= UInt64(Int.max) else { return nil }

        width = scaledEvenDimension(baseline.width)
        height = scaledEvenDimension(baseline.height)
        framesPerSecond = max(1, min(baseline.framesPerSecond, profile.framesPerSecond))
        bitrateMbps = max(
            1,
            min(baseline.bitrateKbps / 1_000, Int(targetWholeMbps))
        )
    }
}

struct InternetAdaptiveRequestToken: Equatable {
    let generation: UInt64
    let requestID: UInt64
}

struct InternetAdaptiveRequestSequence {
    private(set) var nextRequestID: UInt64

    init(nextRequestID: UInt64 = 1) {
        self.nextRequestID = nextRequestID
    }

    mutating func take() -> UInt64? {
        guard nextRequestID > 0 else { return nil }
        let requestID = nextRequestID
        nextRequestID = requestID == UInt64.max ? 0 : requestID + 1
        return requestID
    }
}


/// Outcome of admitting a controller event through the shared
/// `GameControllerStateMachine`. The soft-rejected case keeps the session
/// alive so the host can send an `InputAck` with the exact reason and let
/// the client retry once a controller slot frees up.
enum InternetControllerAdmission {
    case accepted(GameControllerInputEvent)
    case rejected(inputID: UInt64, reason: String)
}

struct InternetProductProtocolCodec {
    static let protocolVersion: UInt32 = 1
    static let requiredCapabilities: Set<VSCapability> = [
        .deviceIdentity,
        .endToEndEncryption,
        .mediaRecordFragmentation,
        .replayProtection,
    ]

    let sessionID: Data
    let sessionEpoch: UInt64
    let hostID: String
    let hostName: String
    let peerDeviceID: String
    let inputEnabled: Bool
    let controllerAvailable: Bool
    private(set) var video: InternetProductVideoConfiguration
    let maximumControlBytes: Int
    let maximumMediaBytes: Int
    private(set) var negotiatedMaximumEncryptedMediaRecordBytes: Int?

    private(set) var nextMessageID: UInt64 = 1
    private(set) var nextFrameID: UInt64 = 1
    private(set) var lastReceivedMessageID: UInt64 = 0
    private(set) var nextConfigEpoch: UInt64?
    private(set) var controllerStateMachine = GameControllerStateMachine()

    init(
        sessionIdentifier: String,
        sessionEpoch: UInt64,
        hostID: String,
        hostName: String,
        peerDeviceID: String,
        video: InternetProductVideoConfiguration,
        inputEnabled: Bool = true,
        controllerAvailable: Bool = false,
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
        self.inputEnabled = inputEnabled
        self.controllerAvailable = controllerAvailable
        self.video = video
        self.nextConfigEpoch = video.configEpoch < UInt64.max
            ? video.configEpoch + 1
            : nil
        self.maximumControlBytes = limits.maximumControlMessageBytes
        self.maximumMediaBytes = limits.maximumMediaFrameBytes
        self.negotiatedMaximumEncryptedMediaRecordBytes = nil
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

    mutating func validate(_ hello: VSClientHello) throws {
        negotiatedMaximumEncryptedMediaRecordBytes = nil
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
        let requiredByClient = Set(hello.requiredCapabilities)
        guard requiredByClient.isSubset(of: capabilities) else {
            throw InternetProductProtocolError.unexpectedMessage(
                "ClientHello required capabilities were not included in its offer"
            )
        }
        guard !requiredByClient.contains(.stylusExtended)
                || capabilities.contains(.stylus) else {
            throw InternetProductProtocolError.missingCapability(.stylus)
        }
        let hostCapabilities = Self.requiredCapabilities.union(inputCapabilities)
        for capability in requiredByClient where !hostCapabilities.contains(capability) {
            throw InternetProductProtocolError.missingCapability(capability)
        }
        let offeredMaximum = Int(hello.resourceLimits.maximumEncryptedMediaRecordBytes)
        guard offeredMaximum >= InternetMediaRecordContract.minimumNegotiatedEncryptedRecordBytes else {
            throw InternetProductProtocolError.unexpectedMessage(
                "ClientHello did not offer a usable encrypted media record limit"
            )
        }
        negotiatedMaximumEncryptedMediaRecordBytes = min(
            offeredMaximum,
            InternetMediaRecordContract.maximumEncryptedRecordBytes
        )
        guard hello.codecs.contains(video.codec) else {
            throw InternetProductProtocolError.unsupportedCodec
        }
    }

    mutating func hostHello() throws -> Data {
        var hello = VSHostHello()
        hello.selectedProtocol = Self.protocolVersion
        hello.hostID = hostID
        hello.hostName = hostName
        hello.capabilities = Array(Self.requiredCapabilities.union(inputCapabilities)).sorted {
            $0.rawValue < $1.rawValue
        }
        hello.codecs = [video.codec]
        var limits = VSResourceLimits()
        limits.maximumEncryptedMediaRecordBytes = UInt32(
            InternetMediaRecordContract.maximumEncryptedRecordBytes
        )
        hello.resourceLimits = limits
        var envelope = baseEnvelope()
        envelope.hostHello = hello
        return try encode(envelope)
    }

    mutating func sessionAccepted(
        heartbeatIntervalMilliseconds: UInt32,
        peerSupportsTouch: Bool,
        peerSupportsStylus: Bool = false,
        peerSupportsStylusExtended: Bool = false,
        peerSupportsController: Bool = false
    ) throws -> Data {
        var accepted = VSSessionAccepted()
        accepted.sessionID = sessionID
        accepted.sessionEpoch = sessionEpoch
        accepted.heartbeatIntervalMs = heartbeatIntervalMilliseconds
        accepted.negotiatedCapabilities = (
            Array(Self.requiredCapabilities)
                + (inputEnabled && peerSupportsTouch ? [.touch] : [])
                + (inputEnabled && peerSupportsStylus ? [.stylus] : [])
                + (inputEnabled && peerSupportsStylus && peerSupportsStylusExtended
                    ? [.stylusExtended]
                    : [])
                + (controllerAvailable && peerSupportsController ? [.controller] : [])
        ).sorted { $0.rawValue < $1.rawValue }
        guard let negotiatedMaximumEncryptedMediaRecordBytes else {
            throw InternetProductProtocolError.unexpectedMessage(
                "media record limits were not negotiated before session acceptance"
            )
        }
        var limits = VSResourceLimits()
        limits.maximumEncryptedMediaRecordBytes = UInt32(
            negotiatedMaximumEncryptedMediaRecordBytes
        )
        accepted.negotiatedResourceLimits = limits
        var envelope = baseEnvelope()
        envelope.sessionAccepted = accepted
        return try encode(envelope)
    }

    private var inputCapabilities: Set<VSCapability> {
        var capabilities: Set<VSCapability> = []
        if inputEnabled {
            capabilities.formUnion([.touch, .stylus, .stylusExtended])
        }
        if controllerAvailable {
            capabilities.insert(.controller)
        }
        return capabilities
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
        try updateVideoConfiguration(rotationDegrees: rotationDegrees)
    }

    mutating func updateVideoConfiguration(
        width: Int? = nil,
        height: Int? = nil,
        framesPerSecond: Int? = nil,
        bitrateKbps: Int? = nil,
        rotationDegrees: Int? = nil
    ) throws -> [Data] {
        guard let configEpoch = nextConfigEpoch else {
            throw InternetProductProtocolError.rejectedVideoConfiguration(
                "Video configuration epoch is exhausted."
            )
        }
        let previous = video
        let replacement = try video.replacing(
            width: width,
            height: height,
            framesPerSecond: framesPerSecond,
            bitrateKbps: bitrateKbps,
            configEpoch: configEpoch,
            rotationDegrees: rotationDegrees
        )
        nextConfigEpoch = configEpoch == UInt64.max ? nil : configEpoch + 1
        video = replacement
        let displayChanged = video.width != previous.width
            || video.height != previous.height
            || video.rotationDegrees != previous.rotationDegrees
        return displayChanged
            ? [try displayChangedControl(), try videoConfiguration()]
            : [try videoConfiguration()]
    }

    mutating func restoreVideoConfiguration(_ configuration: InternetProductVideoConfiguration) {
        video = configuration
    }

    private mutating func displayChangedControl() throws -> Data {
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
        return try encode(envelope)
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

    mutating func inputAck(
        inputID: UInt64,
        accepted: Bool,
        rejectionReason: String = "",
        correlationID: UInt64
    ) throws -> Data {
        var ack = VSInputAck()
        ack.inputID = inputID
        ack.accepted = accepted
        ack.rejectionReason = rejectionReason
        var envelope = baseEnvelope(correlationID: correlationID)
        envelope.inputAck = ack
        return try encode(envelope)
    }

    mutating func protocolError(
        code: VSProtocolErrorCode,
        message: String,
        correlationID: UInt64
    ) throws -> Data {
        var error = VSProtocolError()
        error.code = code
        error.message = message
        error.retryable = false
        error.component = "macos-host-internet-session"
        var envelope = baseEnvelope(correlationID: correlationID)
        envelope.protocolError = error
        return try encode(envelope)
    }

    /// Authorizes a controller event through the shared
    /// `GameControllerStateMachine`. Hard violations throw
    /// `InternetProductProtocolError.invalidController` so the session fails
    /// closed. Only the bounded "too many active controllers" case returns a
    /// soft rejection so the host can send an `InputAck` with the exact
    /// reason and keep the session running.
    mutating func authorizeController(
        _ event: VSControllerEvent
    ) throws -> InternetControllerAdmission {
        guard let controllerEvent = GameControllerInputEvent(wireEvent: event) else {
            throw InternetProductProtocolError.invalidController
        }
        let admission: GameControllerAdmissionResult
        do {
            admission = try controllerStateMachine.accept(controllerEvent)
        } catch {
            throw InternetProductProtocolError.invalidController
        }
        switch admission {
        case .accepted:
            return .accepted(controllerEvent)
        case .rejectedMaximumActiveControllers:
            return .rejected(
                inputID: controllerEvent.inputID,
                reason: GameControllerContract.maximumActiveControllersRejectionReason
            )
        }
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
        guard let negotiatedMaximumEncryptedMediaRecordBytes else {
            throw InternetProductProtocolError.unexpectedMessage(
                "media record limits were not negotiated before media encoding"
            )
        }
        let maximumPlaintextRecordBytes = InternetMediaRecordContract.maximumPlaintextRecordBytes(
            negotiatedEncryptedRecordBytes: negotiatedMaximumEncryptedMediaRecordBytes
        )
        let fragmentPayloadBytes = InternetMediaRecordContract.maximumFragmentPayloadBytes(
            negotiatedEncryptedRecordBytes: negotiatedMaximumEncryptedMediaRecordBytes
        )
        let fragmentCount = max(1, (payload.count + fragmentPayloadBytes - 1) / fragmentPayloadBytes)
        guard fragmentCount <= InternetMediaRecordContract.maximumFragmentsPerFrame else {
            throw InternetProductProtocolError.mediaPayloadTooLarge(
                actual: payload.count,
                maximum: maximumMediaBytes
            )
        }

        let frameID = nextFrameID
        var records: [Data] = []
        records.reserveCapacity(fragmentCount)
        for fragmentIndex in 0..<fragmentCount {
            let start = fragmentIndex * fragmentPayloadBytes
            let end = min(payload.count, start + fragmentPayloadBytes)
            let fragment = payload.subdata(in: start..<end)
            var header = VSMediaPacketHeader()
            header.streamID = video.streamID
            header.sessionEpoch = sessionEpoch
            header.configEpoch = video.configEpoch
            header.frameID = frameID
            header.fragmentIndex = UInt32(fragmentIndex)
            header.fragmentCount = UInt32(fragmentCount)
            header.captureTimestampNs = timestamp
            header.keyframe = isKeyframe
            header.codec = video.codec
            header.payloadLength = UInt32(fragment.count)

            let headerBytes = try header.serializedData()
            guard headerBytes.count <= InternetMediaRecordContract.maximumMediaHeaderBytes else {
                throw InternetProductProtocolError.mediaPayloadTooLarge(
                    actual: headerBytes.count,
                    maximum: InternetMediaRecordContract.maximumMediaHeaderBytes
                )
            }
            var record = Data()
            appendVarint(headerBytes.count, to: &record)
            record.append(headerBytes)
            record.append(fragment)
            guard record.count <= maximumPlaintextRecordBytes else {
                throw InternetProductProtocolError.mediaPayloadTooLarge(
                    actual: record.count,
                    maximum: maximumPlaintextRecordBytes
                )
            }
            records.append(record)
        }
        nextFrameID &+= 1
        return try EncodedInternetFrame(
            records: records,
            mediaPayloadBytes: payload.count,
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
