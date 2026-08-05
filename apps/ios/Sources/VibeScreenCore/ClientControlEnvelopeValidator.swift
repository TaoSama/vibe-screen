import Foundation
import VibeScreenProtocol

public enum ClientControlEnvelopeError: Error, Equatable, LocalizedError {
    case unsupportedProtocol(UInt32)
    case nonMonotonicMessageID(received: UInt64, previous: UInt64)
    case unexpectedHandshakeMessage
    case invalidSession

    public var errorDescription: String? {
        switch self {
        case let .unsupportedProtocol(version): "主机返回了不支持的协议版本：\(version)"
        case let .nonMonotonicMessageID(received, previous):
            "主机消息编号未递增：\(received)（上一条为 \(previous)）"
        case .unexpectedHandshakeMessage: "主机会话握手顺序无效"
        case .invalidSession: "主机消息不属于当前会话"
        }
    }
}

public struct ClientControlEnvelopeValidator: Sendable {
    private enum Phase: Sendable {
        case awaitingHostHello
        case awaitingSessionAccepted
        case active(sessionID: Data, sessionEpoch: UInt64)
    }

    private var phase: Phase = .awaitingHostHello
    private var lastMessageID: UInt64 = 0

    public init() {}

    public mutating func reset() {
        phase = .awaitingHostHello
        lastMessageID = 0
    }

    public mutating func validate(_ envelope: VSEnvelope) throws {
        guard envelope.protocolVersion == SessionState.protocolVersion else {
            throw ClientControlEnvelopeError.unsupportedProtocol(envelope.protocolVersion)
        }
        guard envelope.messageID > lastMessageID else {
            throw ClientControlEnvelopeError.nonMonotonicMessageID(
                received: envelope.messageID,
                previous: lastMessageID
            )
        }
        guard let payload = envelope.payload else {
            throw ClientControlEnvelopeError.unexpectedHandshakeMessage
        }

        switch phase {
        case .awaitingHostHello:
            switch payload {
            case .hostHello:
                guard envelope.sessionID.isEmpty, envelope.sessionEpoch == 0 else {
                    throw ClientControlEnvelopeError.invalidSession
                }
                phase = .awaitingSessionAccepted
            case .sessionRejected, .protocolError, .disconnectNotice:
                break
            default:
                throw ClientControlEnvelopeError.unexpectedHandshakeMessage
            }

        case .awaitingSessionAccepted:
            switch payload {
            case .sessionAccepted(let accepted):
                guard !accepted.sessionID.isEmpty, accepted.sessionEpoch > 0,
                      envelope.sessionID == accepted.sessionID,
                      envelope.sessionEpoch == accepted.sessionEpoch else {
                    throw ClientControlEnvelopeError.invalidSession
                }
                phase = .active(sessionID: accepted.sessionID, sessionEpoch: accepted.sessionEpoch)
            case .sessionRejected, .protocolError, .disconnectNotice:
                break
            default:
                throw ClientControlEnvelopeError.unexpectedHandshakeMessage
            }

        case let .active(sessionID, sessionEpoch):
            guard envelope.sessionID == sessionID, envelope.sessionEpoch == sessionEpoch else {
                throw ClientControlEnvelopeError.invalidSession
            }
            switch payload {
            case .hostHello, .sessionAccepted, .clientHello:
                throw ClientControlEnvelopeError.unexpectedHandshakeMessage
            default:
                break
            }
        }
        lastMessageID = envelope.messageID
    }
}
