import Foundation

enum WebRTCSignal: Equatable {
    case offer(String)
    case answer(String)
    case candidate(sdp: String, mid: String?, lineIndex: Int32)
    case peerReady
}

protocol WebRTCSignalingClientPort: AnyObject {
    var onSignal: ((WebRTCSignal) -> Void)? { get set }
    var onFailure: ((Error) -> Void)? { get set }
    func connect(configuration: WebRTCTransportConfiguration) throws
    func send(_ signal: WebRTCSignal, completion: @escaping (Result<Void, Error>) -> Void)
    func close()
}

enum WebRTCSignalingError: Error, LocalizedError {
    case missingConfiguration
    case invalidResponse(Int)
    case invalidMessage
    case unsupportedSignal
    case notConnected

    var errorDescription: String? {
        switch self {
        case .missingConfiguration:
            return "Production WebRTC requires an explicit signaling endpoint, role token, and role."
        case .invalidResponse(let status): return "The signaling service returned HTTP \(status)."
        case .invalidMessage: return "The signaling service returned an invalid message."
        case .unsupportedSignal: return "The signaling service returned an unsupported message type."
        case .notConnected: return "The signaling client is not connected."
        }
    }
}

/// Authenticated HTTPS long-poll client for `services/signaling`.
///
/// The service intentionally does not retain a WebSocket per peer. Messages
/// are idempotent POSTs, while a bounded long poll delivers the opposite role's
/// events. SDP and candidates are never logged here.
final class HTTPSignalingClient: WebRTCSignalingClientPort {
    var onSignal: ((WebRTCSignal) -> Void)?
    var onFailure: ((Error) -> Void)?

    private struct Candidate: Codable {
        let candidate: String
        let sdpMid: String?
        let sdpMLineIndex: UInt16?

        enum CodingKeys: String, CodingKey {
            case candidate
            case sdpMid = "sdp_mid"
            case sdpMLineIndex = "sdp_mline_index"
        }
    }

    private struct MessageRequest: Encodable {
        let messageID: String
        let type: String
        let sdp: String?
        let candidate: Candidate?

        enum CodingKeys: String, CodingKey {
            case messageID = "message_id"
            case type, sdp, candidate
        }
    }

    private struct Event: Decodable {
        let type: String
        let sdp: String?
        let candidate: Candidate?
    }

    private struct PollResponse: Decodable {
        let events: [Event]
        let nextCursor: UInt64

        enum CodingKeys: String, CodingKey {
            case events
            case nextCursor = "next_cursor"
        }
    }

    private struct PendingMessage {
        let request: URLRequest
        let completion: (Result<Void, Error>) -> Void
    }

    private let session: URLSession
    private let queue = DispatchQueue(label: "dev.vibescreen.webrtc.signaling")
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private var configuration: WebRTCTransportConfiguration?
    private var cursor: UInt64 = 0
    private var pollTask: URLSessionDataTask?
    private var messageTask: URLSessionDataTask?
    private var pendingMessages: [PendingMessage] = []
    private var isClosed = true

    init(session: URLSession = .shared) {
        self.session = session
    }

    func connect(configuration: WebRTCTransportConfiguration) throws {
        guard configuration.signaling != nil else { throw WebRTCSignalingError.missingConfiguration }
        queue.sync {
            self.configuration = configuration
            cursor = 0
            isClosed = false
            pollNext()
            if configuration.signaling?.role == .offerer { onSignal?(.peerReady) }
        }
    }

    func send(_ signal: WebRTCSignal, completion: @escaping (Result<Void, Error>) -> Void) {
        queue.async { [weak self] in
            guard let self, let request = self.makeRequest(for: signal) else {
                completion(.failure(WebRTCSignalingError.notConnected))
                return
            }
            self.pendingMessages.append(PendingMessage(request: request, completion: completion))
            self.sendNextMessage()
        }
    }

    func close() {
        queue.sync {
            isClosed = true
            pollTask?.cancel()
            pollTask = nil
            messageTask?.cancel()
            messageTask = nil
            let pending = pendingMessages
            pendingMessages.removeAll()
            pending.forEach { $0.completion(.failure(WebRTCSignalingError.notConnected)) }
            configuration = nil
        }
    }

    private func sendNextMessage() {
        guard messageTask == nil, let pending = pendingMessages.first else { return }
        messageTask = session.dataTask(with: pending.request) { [weak self] _, response, error in
            guard let self else { return }
            self.queue.async {
                guard !self.pendingMessages.isEmpty else { return }
                let completed = self.pendingMessages.removeFirst()
                self.messageTask = nil
                if let error {
                    completed.completion(.failure(error))
                } else {
                    let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                    if status == 200 || status == 201 {
                        completed.completion(.success(()))
                    } else {
                        completed.completion(.failure(WebRTCSignalingError.invalidResponse(status)))
                    }
                }
                self.sendNextMessage()
            }
        }
        messageTask?.resume()
    }

    private func makeRequest(for signal: WebRTCSignal) -> URLRequest? {
        guard !isClosed, let configuration, let signaling = configuration.signaling,
              signal != .peerReady else { return nil }
        let message: MessageRequest
        switch signal {
        case .offer(let sdp):
            message = MessageRequest(messageID: UUID().uuidString.lowercased(), type: "offer", sdp: sdp, candidate: nil)
        case .answer(let sdp):
            message = MessageRequest(messageID: UUID().uuidString.lowercased(), type: "answer", sdp: sdp, candidate: nil)
        case .candidate(let sdp, let mid, let lineIndex):
            guard lineIndex >= 0, lineIndex <= Int32(UInt16.max) else { return nil }
            message = MessageRequest(
                messageID: UUID().uuidString.lowercased(),
                type: "ice_candidate",
                sdp: nil,
                candidate: Candidate(candidate: sdp, sdpMid: mid, sdpMLineIndex: UInt16(lineIndex))
            )
        case .peerReady:
            return nil
        }
        let url = signaling.endpoint
            .appendingPathComponent("v1/sessions")
            .appendingPathComponent(configuration.sessionIdentifier)
            .appendingPathComponent("messages")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = try? encoder.encode(message)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(signaling.bearerToken)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 15
        return request
    }

    private func pollNext() {
        guard !isClosed, let configuration, let signaling = configuration.signaling else { return }
        var components = URLComponents(
            url: signaling.endpoint
                .appendingPathComponent("v1/sessions")
                .appendingPathComponent(configuration.sessionIdentifier)
                .appendingPathComponent("events"),
            resolvingAgainstBaseURL: false
        )
        components?.queryItems = [
            URLQueryItem(name: "after", value: String(cursor)),
            URLQueryItem(name: "wait_seconds", value: "20")
        ]
        guard let url = components?.url else {
            onFailure?(WebRTCSignalingError.invalidMessage)
            return
        }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(signaling.bearerToken)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 30
        pollTask = session.dataTask(with: request) { [weak self] data, response, error in
            guard let self else { return }
            self.queue.async {
                guard !self.isClosed else { return }
                if let error {
                    if (error as NSError).code != NSURLErrorCancelled { self.onFailure?(error) }
                    return
                }
                let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                guard status == 200, let data else {
                    self.onFailure?(WebRTCSignalingError.invalidResponse(status))
                    return
                }
                do {
                    let poll = try self.decoder.decode(PollResponse.self, from: data)
                    self.cursor = poll.nextCursor
                    for event in poll.events { self.onSignal?(try self.signal(from: event)) }
                    self.pollNext()
                } catch {
                    self.onFailure?(error)
                }
            }
        }
        pollTask?.resume()
    }

    private func signal(from event: Event) throws -> WebRTCSignal {
        switch event.type {
        case "offer":
            guard let sdp = event.sdp else { throw WebRTCSignalingError.invalidMessage }
            return .offer(sdp)
        case "answer":
            guard let sdp = event.sdp else { throw WebRTCSignalingError.invalidMessage }
            return .answer(sdp)
        case "ice_candidate":
            guard let candidate = event.candidate else { throw WebRTCSignalingError.invalidMessage }
            return .candidate(
                sdp: candidate.candidate,
                mid: candidate.sdpMid,
                lineIndex: Int32(candidate.sdpMLineIndex ?? 0)
            )
        case "end_of_candidates":
            return .peerReady
        default:
            throw WebRTCSignalingError.unsupportedSignal
        }
    }
}
