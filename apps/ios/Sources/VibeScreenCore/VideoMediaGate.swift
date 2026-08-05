import Foundation
import VibeScreenProtocol

/// Owns the protocol state which must be satisfied before a video access unit
/// can be delivered to a decoder.
public struct VideoMediaGate: Sendable {
    /// A receipt for one specific configuration acknowledgement. Tokens are
    /// intentionally opaque and never reused, including across session resets.
    public struct ConfigurationToken: Equatable, Hashable, Sendable {
        fileprivate let value: UUID

        fileprivate init() {
            value = UUID()
        }
    }

    public struct AcceptedFrame: Equatable, Sendable {
        public let streamID: UInt64
        public let configEpoch: UInt64
        public let frameID: UInt64
        public let codec: VSCodec
    }

    private struct Configuration: Sendable {
        let epoch: UInt64
        let codec: VSCodec
        let token: ConfigurationToken
        var acknowledgementSent: Bool
    }

    private struct StreamState: Sendable {
        var configuration: Configuration?
        var lastFrameID: UInt64 = 0
    }

    private var owner: SessionOwner?
    private var sessionEpoch: UInt64?
    private var streams: [UInt64: StreamState] = [:]

    public init() {}

    /// Starts a fresh session and invalidates every stream, configuration token,
    /// and frame sequence owned by the previous session owner.
    public mutating func reset(owner newOwner: SessionOwner, sessionEpoch: UInt64) throws {
        guard sessionEpoch > 0 else {
            throw VideoMediaGateError.invalidSessionEpoch
        }
        owner = newOwner
        self.sessionEpoch = sessionEpoch
        streams.removeAll(keepingCapacity: true)
    }

    /// Ends the session only when the caller still owns it. A late callback from
    /// an old connection therefore cannot tear down a replacement session.
    @discardableResult
    public mutating func endSession(owner: SessionOwner) -> Bool {
        guard self.owner == owner else { return false }
        self.owner = nil
        sessionEpoch = nil
        streams.removeAll(keepingCapacity: false)
        return true
    }

    public mutating func bindStream(_ streamID: UInt64, owner: SessionOwner) throws {
        try requireOwner(owner)
        guard streamID > 0 else { throw VideoMediaGateError.invalidStreamID }
        guard streams[streamID] == nil else {
            throw VideoMediaGateError.streamAlreadyBound(streamID)
        }
        streams[streamID] = StreamState()
    }

    @discardableResult
    public mutating func endStream(_ streamID: UInt64, owner: SessionOwner) -> Bool {
        guard self.owner == owner else { return false }
        return streams.removeValue(forKey: streamID) != nil
    }

    /// Blocks media for the stream until `acknowledgementSent` is called with
    /// the exact token returned by this invocation.
    public mutating func beginConfiguration(
        _ config: VSVideoConfig,
        owner: SessionOwner
    ) throws -> ConfigurationToken {
        try requireOwner(owner)
        guard config.streamID > 0 else { throw VideoMediaGateError.invalidStreamID }
        guard config.configEpoch > 0 else { throw VideoMediaGateError.invalidConfigEpoch }
        guard Self.isSupportedVideoCodec(config.codec) else {
            throw VideoMediaGateError.invalidCodec
        }
        guard var stream = streams[config.streamID] else {
            throw VideoMediaGateError.unboundStream(config.streamID)
        }
        if let currentEpoch = stream.configuration?.epoch,
           config.configEpoch <= currentEpoch {
            throw VideoMediaGateError.nonIncreasingConfigEpoch(
                previous: currentEpoch,
                received: config.configEpoch
            )
        }

        let token = ConfigurationToken()
        stream.configuration = Configuration(
            epoch: config.configEpoch,
            codec: config.codec,
            token: token,
            acknowledgementSent: false
        )
        streams[config.streamID] = stream
        return token
    }

    /// Activates the configuration only after the caller has observed
    /// successful completion of its positive control send.
    public mutating func acknowledgementSent(
        _ token: ConfigurationToken,
        streamID: UInt64,
        owner: SessionOwner
    ) throws {
        try requireOwner(owner)
        guard var stream = streams[streamID] else {
            throw VideoMediaGateError.unboundStream(streamID)
        }
        guard var configuration = stream.configuration else {
            throw VideoMediaGateError.configurationMissing(streamID)
        }
        guard !configuration.acknowledgementSent else {
            throw VideoMediaGateError.configurationAlreadyAcknowledged(streamID)
        }
        guard configuration.token == token else {
            throw VideoMediaGateError.staleConfigurationToken(streamID)
        }
        configuration.acknowledgementSent = true
        stream.configuration = configuration
        streams[streamID] = stream
    }

    /// Validates and advances the frame sequence as one synchronous operation.
    /// Rejected headers never mutate the sequence.
    public mutating func admit(
        _ header: VSMediaPacketHeader,
        payload: Data,
        owner: SessionOwner
    ) -> Result<AcceptedFrame, VideoMediaGateError> {
        guard !payload.isEmpty else { return .failure(.emptyPayload) }
        return admit(header, owner: owner)
    }

    /// Header-only entry point retained for protocol-state tests. Production
    /// decoder delivery uses the payload-validating overload above.
    public mutating func admit(
        _ header: VSMediaPacketHeader,
        owner: SessionOwner
    ) -> Result<AcceptedFrame, VideoMediaGateError> {
        do {
            try requireOwner(owner)
            guard let sessionEpoch else {
                throw VideoMediaGateError.sessionInactive
            }
            guard header.sessionEpoch == sessionEpoch else {
                throw VideoMediaGateError.sessionEpochMismatch(
                    expected: sessionEpoch,
                    received: header.sessionEpoch
                )
            }
            guard header.streamID > 0 else { throw VideoMediaGateError.invalidStreamID }
            guard var stream = streams[header.streamID] else {
                throw VideoMediaGateError.unboundStream(header.streamID)
            }
            guard let configuration = stream.configuration else {
                throw VideoMediaGateError.configurationMissing(header.streamID)
            }
            guard configuration.acknowledgementSent else {
                throw VideoMediaGateError.configurationAcknowledgementPending(header.streamID)
            }
            guard header.configEpoch == configuration.epoch else {
                throw VideoMediaGateError.configEpochMismatch(
                    expected: configuration.epoch,
                    received: header.configEpoch
                )
            }
            guard header.codec == configuration.codec else {
                throw VideoMediaGateError.codecMismatch(
                    expected: configuration.codec,
                    received: header.codec
                )
            }
            guard header.fragmentCount == 1, header.fragmentIndex == 0 else {
                throw VideoMediaGateError.unsupportedFragment(
                    index: header.fragmentIndex,
                    count: header.fragmentCount
                )
            }
            guard header.frameID > 0 else { throw VideoMediaGateError.invalidFrameID }
            guard header.frameID > stream.lastFrameID else {
                throw VideoMediaGateError.nonIncreasingFrameID(
                    previous: stream.lastFrameID,
                    received: header.frameID
                )
            }

            stream.lastFrameID = header.frameID
            streams[header.streamID] = stream
            return .success(AcceptedFrame(
                streamID: header.streamID,
                configEpoch: header.configEpoch,
                frameID: header.frameID,
                codec: header.codec
            ))
        } catch let error as VideoMediaGateError {
            return .failure(error)
        } catch {
            preconditionFailure("VideoMediaGate emitted an undeclared error: \(error)")
        }
    }

    private func requireOwner(_ candidate: SessionOwner) throws {
        guard let owner else { throw VideoMediaGateError.sessionInactive }
        guard owner == candidate else { throw VideoMediaGateError.sessionOwnerMismatch }
    }

    private static func isSupportedVideoCodec(_ codec: VSCodec) -> Bool {
        switch codec {
        case .h264, .hevc, .av1:
            true
        case .unspecified, .UNRECOGNIZED:
            false
        }
    }
}

public enum VideoMediaGateError: Error, Equatable, LocalizedError, Sendable {
    case sessionInactive
    case invalidSessionEpoch
    case sessionOwnerMismatch
    case sessionEpochMismatch(expected: UInt64, received: UInt64)
    case invalidStreamID
    case unboundStream(UInt64)
    case streamAlreadyBound(UInt64)
    case invalidConfigEpoch
    case nonIncreasingConfigEpoch(previous: UInt64, received: UInt64)
    case invalidCodec
    case configurationMissing(UInt64)
    case configurationAcknowledgementPending(UInt64)
    case configurationAlreadyAcknowledged(UInt64)
    case staleConfigurationToken(UInt64)
    case configEpochMismatch(expected: UInt64, received: UInt64)
    case codecMismatch(expected: VSCodec, received: VSCodec)
    case unsupportedFragment(index: UInt32, count: UInt32)
    case emptyPayload
    case invalidFrameID
    case nonIncreasingFrameID(previous: UInt64, received: UInt64)

    public var errorDescription: String? {
        switch self {
        case .sessionInactive: "视频会话尚未激活"
        case .invalidSessionEpoch: "视频会话 epoch 无效"
        case .sessionOwnerMismatch: "视频消息属于过期会话"
        case let .sessionEpochMismatch(expected, received):
            "视频 session_epoch 不匹配：期望 \(expected)，收到 \(received)"
        case .invalidStreamID: "视频 stream_id 无效"
        case let .unboundStream(streamID): "视频流 \(streamID) 尚未绑定"
        case let .streamAlreadyBound(streamID): "视频流 \(streamID) 已绑定"
        case .invalidConfigEpoch: "视频 config_epoch 无效"
        case let .nonIncreasingConfigEpoch(previous, received):
            "视频 config_epoch 未递增：上一值 \(previous)，收到 \(received)"
        case .invalidCodec: "视频 codec 不受支持"
        case let .configurationMissing(streamID): "视频流 \(streamID) 尚未配置"
        case let .configurationAcknowledgementPending(streamID):
            "视频流 \(streamID) 的配置确认尚未发送完成"
        case let .configurationAlreadyAcknowledged(streamID):
            "视频流 \(streamID) 的配置已确认"
        case let .staleConfigurationToken(streamID): "视频流 \(streamID) 的配置确认已过期"
        case let .configEpochMismatch(expected, received):
            "视频 config_epoch 不匹配：期望 \(expected)，收到 \(received)"
        case let .codecMismatch(expected, received):
            "视频 codec 不匹配：期望 \(expected)，收到 \(received)"
        case let .unsupportedFragment(index, count):
            "不支持的视频分片：index=\(index)，count=\(count)"
        case .emptyPayload: "视频帧 payload 为空"
        case .invalidFrameID: "视频 frame_id 无效"
        case let .nonIncreasingFrameID(previous, received):
            "视频 frame_id 未递增：上一值 \(previous)，收到 \(received)"
        }
    }
}
