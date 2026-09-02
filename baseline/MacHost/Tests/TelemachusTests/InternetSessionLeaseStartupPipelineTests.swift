import Foundation
import XCTest
@testable import Telemachus

@MainActor
final class InternetSessionLeaseStartupPipelineTests: XCTestCase {
    func testStartupPipelineQueuesLeaseAndLifecycleSendsWhenSessionStreams() async throws {
        let lifecycle = InternetSessionLeaseDeliveryLifecycle()
        let session = TestInternetSession()
        let delivery = Self.delivery(payload: Data([0x91, 0x92]))
        var events: [String] = []
        var sentPayloads: [Data] = []
        var failClosedReasons: [String] = []

        let pipeline = InternetSessionLeaseStartupPipeline<TestInternetSession>(
            makeSession: { session },
            createDelivery: { _, _, _ in
                events.append("createInternetSessionLeaseDelivery")
                return delivery
            },
            requireCurrentStart: {
                events.append("requireCurrentStart")
            },
            applyDelivery: { configuration, delivery, _ in
                events.append("applyDelivery")
                return Self.configuration(
                    sessionIdentifier: delivery.sessionID,
                    hostToken: delivery.hostSignalingToken
                )
            },
            prepareSession: { observedSession, configuration in
                events.append("prepareSession")
                XCTAssertTrue(observedSession === session)
                XCTAssertEqual(configuration.transport.sessionIdentifier, delivery.sessionID)
                XCTAssertEqual(configuration.transport.signaling?.bearerToken, delivery.hostSignalingToken)
            },
            queueDelivery: { observedDelivery, observedSession in
                events.append("queueInternetSessionLeaseDelivery")
                XCTAssertTrue(observedSession === session)
                return lifecycle.queue(
                    observedDelivery,
                    isCurrent: { true },
                    sessionState: { observedSession.state },
                    send: { queuedDelivery in
                        events.append("sendPendingInternetSessionLeaseDelivery")
                        sentPayloads.append(queuedDelivery.payload)
                        return true
                    }
                )
            },
            resetDelivery: {
                events.append("resetDelivery")
                lifecycle.reset()
            },
            startSession: { observedSession, configuration in
                events.append("session.start")
                XCTAssertTrue(observedSession === session)
                XCTAssertEqual(configuration.transport.sessionIdentifier, delivery.sessionID)
                observedSession.state = .connecting
            },
            startCapture: { observedSession, configuration in
                events.append("startCapture")
                XCTAssertTrue(observedSession === session)
                XCTAssertEqual(configuration.transport.sessionIdentifier, delivery.sessionID)
            },
            didStart: {
                events.append("didStart")
            }
        )

        _ = try await pipeline.start(with: Self.plan())
        XCTAssertEqual(lifecycle.pendingDelivery, delivery)
        XCTAssertFalse(lifecycle.deliverySent)
        XCTAssertTrue(sentPayloads.isEmpty)

        session.state = .streaming(.direct)
        events.append("state.streaming")
        await lifecycle.handleStateChange(
            session.state,
            isCurrent: { true },
            send: { queuedDelivery in
                events.append("sendPendingInternetSessionLeaseDelivery")
                sentPayloads.append(queuedDelivery.payload)
                return true
            },
            failClosed: { failClosedReasons.append($0) }
        )

        XCTAssertNil(lifecycle.pendingDelivery)
        XCTAssertTrue(lifecycle.deliverySent)
        XCTAssertEqual(sentPayloads, [delivery.payload])
        XCTAssertTrue(failClosedReasons.isEmpty)
        XCTAssertEqual(events, [
            "createInternetSessionLeaseDelivery",
            "requireCurrentStart",
            "applyDelivery",
            "prepareSession",
            "queueInternetSessionLeaseDelivery",
            "session.start",
            "startCapture",
            "didStart",
            "state.streaming",
            "sendPendingInternetSessionLeaseDelivery"
        ])
    }

    func testStartupPipelineOrdersAuthorityDeliveryBeforeSessionStartQueueAndCapture() async throws {
        var events: [String] = []
        var queuedDelivery: InternetSessionLeaseDeliveryResult?
        var startedConfiguration: InternetProductSessionConfiguration?
        var capturedConfiguration: InternetProductSessionConfiguration?
        let session = TestInternetSession()
        let baseConfiguration = Self.configuration(sessionIdentifier: "request-id", hostToken: "pending-token")
        let request = Self.profileRequest(sessionEpoch: baseConfiguration.authoritativeSessionEpoch)
        let delivery = Self.delivery(sessionID: "authority-session", hostToken: "authority-host-token")
        let plan = InternetSessionLeaseStartupPlan(
            configuration: baseConfiguration,
            request: request,
            signalingBaseURL: URL(string: "https://signal.example.test")!,
            issuerToken: "issuer-token"
        )
        let pipeline = InternetSessionLeaseStartupPipeline<TestInternetSession>(
            makeSession: {
                events.append("makeSession")
                return session
            },
            createDelivery: { baseURL, issuerToken, observedRequest in
                events.append("createDelivery")
                XCTAssertEqual(baseURL, plan.signalingBaseURL)
                XCTAssertEqual(issuerToken, "issuer-token")
                XCTAssertEqual(observedRequest, request)
                return delivery
            },
            requireCurrentStart: {
                events.append("requireCurrentStart")
            },
            applyDelivery: { configuration, observedDelivery, baseURL in
                events.append("applyDelivery")
                XCTAssertEqual(configuration.transport.sessionIdentifier, "request-id")
                XCTAssertEqual(observedDelivery, delivery)
                XCTAssertEqual(baseURL, plan.signalingBaseURL)
                return Self.configuration(
                    sessionIdentifier: observedDelivery.sessionID,
                    hostToken: observedDelivery.hostSignalingToken
                )
            },
            prepareSession: { observedSession, configuration in
                events.append("prepareSession")
                XCTAssertTrue(observedSession === session)
                XCTAssertEqual(configuration.transport.sessionIdentifier, delivery.sessionID)
                XCTAssertEqual(configuration.transport.signaling?.bearerToken, delivery.hostSignalingToken)
            },
            queueDelivery: { observedDelivery, observedSession in
                events.append("queueDelivery")
                XCTAssertTrue(observedSession === session)
                queuedDelivery = observedDelivery
                return .queued
            },
            resetDelivery: {
                events.append("resetDelivery")
            },
            startSession: { observedSession, configuration in
                events.append("session.start")
                XCTAssertTrue(observedSession === session)
                startedConfiguration = configuration
                observedSession.state = .connecting
            },
            startCapture: { observedSession, configuration in
                events.append("startCapture")
                XCTAssertTrue(observedSession === session)
                capturedConfiguration = configuration
            },
            didStart: {
                events.append("didStart")
            }
        )

        let returnedSession = try await pipeline.start(with: plan)

        XCTAssertTrue(returnedSession === session)
        XCTAssertEqual(queuedDelivery, delivery)
        XCTAssertEqual(startedConfiguration?.transport.sessionIdentifier, delivery.sessionID)
        XCTAssertEqual(startedConfiguration?.transport.signaling?.bearerToken, delivery.hostSignalingToken)
        XCTAssertEqual(capturedConfiguration?.transport.sessionIdentifier, delivery.sessionID)
        XCTAssertEqual(events, [
            "createDelivery",
            "requireCurrentStart",
            "applyDelivery",
            "makeSession",
            "prepareSession",
            "queueDelivery",
            "session.start",
            "startCapture",
            "didStart"
        ])
    }

    func testStartupPipelineFailsClosedWhenQueueRejectsStreamingDelivery() async throws {
        let pipeline = InternetSessionLeaseStartupPipeline<TestInternetSession>(
            makeSession: { TestInternetSession() },
            createDelivery: { _, _, _ in Self.delivery() },
            requireCurrentStart: {},
            applyDelivery: { configuration, _, _ in configuration },
            prepareSession: { _, _ in },
            queueDelivery: { _, _ in .deliveryFailed },
            resetDelivery: {},
            startSession: { session, _ in session.state = .streaming(.direct) },
            startCapture: { _, _ in XCTFail("capture must not start after lease delivery failure") },
            didStart: { XCTFail("startup must not complete after lease delivery failure") }
        )

        do {
            _ = try await pipeline.start(with: Self.plan())
            XCTFail("Expected startup to fail closed when delivery cannot be queued or sent.")
        } catch InternetProductSessionError.securityFailure(let reason) {
            XCTAssertTrue(reason.contains("authoritative session lease"))
        }
    }

    func testLeaseDeliveryLifecycleQueuesNonStreamingDeliveryAndSendsOnStreaming() async {
        let lifecycle = InternetSessionLeaseDeliveryLifecycle()
        let delivery = Self.delivery(payload: Data([0xA1]))
        var sentPayloads: [Data] = []
        var failClosedReasons: [String] = []

        XCTAssertEqual(lifecycle.queue(
            delivery,
            isCurrent: { true },
            sessionState: { .connecting },
            send: { sentPayloads.append($0.payload); return true }
        ), .queued)
        XCTAssertEqual(lifecycle.pendingDelivery, delivery)
        XCTAssertFalse(lifecycle.deliverySent)
        XCTAssertTrue(sentPayloads.isEmpty)

        await lifecycle.handleStateChange(
            .streaming(.direct),
            isCurrent: { true },
            send: { sentPayloads.append($0.payload); return true },
            failClosed: { failClosedReasons.append($0) }
        )

        XCTAssertNil(lifecycle.pendingDelivery)
        XCTAssertTrue(lifecycle.deliverySent)
        XCTAssertEqual(sentPayloads, [delivery.payload])
        XCTAssertTrue(failClosedReasons.isEmpty)

        await lifecycle.handleStateChange(
            .streaming(.relay),
            isCurrent: { true },
            send: { sentPayloads.append($0.payload); return true },
            failClosed: { failClosedReasons.append($0) }
        )
        XCTAssertEqual(sentPayloads, [delivery.payload])
        XCTAssertTrue(failClosedReasons.isEmpty)
    }

    func testLeaseDeliveryLifecycleDropsStaleStreamingCallbackWithoutFailClosed() async {
        let lifecycle = InternetSessionLeaseDeliveryLifecycle()
        let delivery = Self.delivery(payload: Data([0xA2]))
        var sentPayloads: [Data] = []
        var failClosedReasons: [String] = []

        XCTAssertEqual(lifecycle.queue(
            delivery,
            isCurrent: { true },
            sessionState: { .connecting },
            send: { sentPayloads.append($0.payload); return true }
        ), .queued)

        await lifecycle.handleStateChange(
            .streaming(.direct),
            isCurrent: { false },
            send: { _ in XCTFail("stale streaming callback must not deliver"); return true },
            failClosed: { failClosedReasons.append($0) }
        )

        XCTAssertEqual(lifecycle.pendingDelivery, delivery)
        XCTAssertFalse(lifecycle.deliverySent)
        XCTAssertTrue(sentPayloads.isEmpty)
        XCTAssertTrue(failClosedReasons.isEmpty)
    }

    func testLeaseDeliveryLifecycleTreatsRepeatedStreamingAsExactlyOnce() async {
        let lifecycle = InternetSessionLeaseDeliveryLifecycle()
        let delivery = Self.delivery(payload: Data([0xA3]))
        var sentPayloads: [Data] = []
        var failClosedReasons: [String] = []

        XCTAssertEqual(lifecycle.queue(
            delivery,
            isCurrent: { true },
            sessionState: { .connecting },
            send: { sentPayloads.append($0.payload); return true }
        ), .queued)

        await lifecycle.handleStateChange(
            .streaming(.direct),
            isCurrent: { true },
            send: { sentPayloads.append($0.payload); return true },
            failClosed: { failClosedReasons.append($0) }
        )
        await lifecycle.handleStateChange(
            .streaming(.relay),
            isCurrent: { true },
            send: { sentPayloads.append($0.payload); return true },
            failClosed: { failClosedReasons.append($0) }
        )

        XCTAssertNil(lifecycle.pendingDelivery)
        XCTAssertTrue(lifecycle.deliverySent)
        XCTAssertEqual(sentPayloads, [delivery.payload])
        XCTAssertTrue(failClosedReasons.isEmpty)
    }

    func testLeaseDeliveryLifecycleRejectsStaleOwnershipWithoutMutatingState() {
        let lifecycle = InternetSessionLeaseDeliveryLifecycle()

        XCTAssertEqual(lifecycle.queue(
            Self.delivery(),
            isCurrent: { false },
            sessionState: { .connecting },
            send: { _ in XCTFail("stale delivery must not send"); return true }
        ), .stale)
        XCTAssertNil(lifecycle.pendingDelivery)
        XCTAssertFalse(lifecycle.deliverySent)

        XCTAssertEqual(lifecycle.sendPending(
            isCurrent: { false },
            send: { _ in XCTFail("stale pending delivery must not send"); return true }
        ), .stale)
    }

    func testLeaseDeliveryLifecycleFailsClosedWhenStreamingSendFails() async {
        let lifecycle = InternetSessionLeaseDeliveryLifecycle()
        let delivery = Self.delivery(payload: Data([0xB1]))
        var failClosedReasons: [String] = []

        XCTAssertEqual(lifecycle.queue(
            delivery,
            isCurrent: { true },
            sessionState: { .streaming(.direct) },
            send: { _ in false }
        ), .deliveryFailed)
        XCTAssertEqual(lifecycle.pendingDelivery, delivery)
        XCTAssertFalse(lifecycle.deliverySent)

        await lifecycle.handleStateChange(
            .streaming(.direct),
            isCurrent: { true },
            send: { _ in false },
            failClosed: { failClosedReasons.append($0) }
        )

        XCTAssertEqual(failClosedReasons, [InternetSessionLeaseDeliveryLifecycle.deliveryFailureReason])
        XCTAssertEqual(lifecycle.pendingDelivery, delivery)
        XCTAssertFalse(lifecycle.deliverySent)

        lifecycle.reset()
        XCTAssertNil(lifecycle.pendingDelivery)
        XCTAssertFalse(lifecycle.deliverySent)
    }

    func testLeaseDeliverySendForwardsPayloadOnBulkTransferID() {
        let session = TestLeaseSendable()
        let delivery = Self.delivery(payload: Data([0xC1, 0xC2]))

        XCTAssertTrue(InternetSessionLeaseDelivery.send(delivery, on: session))
        XCTAssertEqual(session.receivedPayload, delivery.payload)
        XCTAssertEqual(session.receivedTransferID, InternetSessionLeaseDelivery.bulkTransferID)
    }

    func testLeaseDeliverySendReturnsSessionFailure() {
        let session = TestLeaseSendable(sendResult: false)
        let delivery = Self.delivery(payload: Data([0xD1]))

        XCTAssertFalse(InternetSessionLeaseDelivery.send(delivery, on: session))
        XCTAssertEqual(session.receivedPayload, delivery.payload)
        XCTAssertEqual(session.receivedTransferID, InternetSessionLeaseDelivery.bulkTransferID)
    }

    func testLeaseDeliveryLifecycleReturnsNoPendingDeliveryWhenSendPendingWithoutQueue() {
        let lifecycle = InternetSessionLeaseDeliveryLifecycle()

        XCTAssertEqual(
            lifecycle.sendPending(
                isCurrent: { true },
                send: { _ in XCTFail("must not send when no delivery is pending"); return true }
            ),
            .noPendingDelivery
        )
        XCTAssertNil(lifecycle.pendingDelivery)
        XCTAssertFalse(lifecycle.deliverySent)
    }

    func testLeaseDeliveryLifecycleRejectsSecondQueueWhilePending() {
        let lifecycle = InternetSessionLeaseDeliveryLifecycle()
        let first = Self.delivery(payload: Data([0x01]))
        let second = Self.delivery(payload: Data([0x02]))

        XCTAssertEqual(lifecycle.queue(
            first,
            isCurrent: { true },
            sessionState: { .connecting },
            send: { _ in XCTFail("must not send while not streaming"); return true }
        ), .queued)
        XCTAssertEqual(lifecycle.pendingDelivery, first)

        XCTAssertEqual(lifecycle.queue(
            second,
            isCurrent: { true },
            sessionState: { .connecting },
            send: { _ in XCTFail("must not send when a pending delivery already exists"); return true }
        ), .alreadyPending)
        XCTAssertEqual(lifecycle.pendingDelivery, first)
        XCTAssertFalse(lifecycle.deliverySent)
    }

    func testStartupPipelineResetsDeliveryWhenStartSessionFails() async throws {
        var resetCount = 0
        let pipeline = InternetSessionLeaseStartupPipeline<TestInternetSession>(
            makeSession: { TestInternetSession() },
            createDelivery: { _, _, _ in Self.delivery() },
            requireCurrentStart: {},
            applyDelivery: { configuration, _, _ in configuration },
            prepareSession: { _, _ in },
            queueDelivery: { _, _ in .queued },
            resetDelivery: { resetCount += 1 },
            startSession: { _, _ in
                throw NSError(domain: "test", code: 1, userInfo: nil)
            },
            startCapture: { _, _ in XCTFail("capture must not start after session start failure") },
            didStart: { XCTFail("startup must not complete after session start failure") }
        )

        do {
            _ = try await pipeline.start(with: Self.plan())
            XCTFail("Expected startup to fail when session start throws.")
        } catch {
            XCTAssertEqual(resetCount, 1)
        }
    }

    func testStartupPipelineResetsDeliveryWhenQueueRejects() async throws {
        var resetCount = 0
        let pipeline = InternetSessionLeaseStartupPipeline<TestInternetSession>(
            makeSession: { TestInternetSession() },
            createDelivery: { _, _, _ in Self.delivery() },
            requireCurrentStart: {},
            applyDelivery: { configuration, _, _ in configuration },
            prepareSession: { _, _ in },
            queueDelivery: { _, _ in .deliveryFailed },
            resetDelivery: { resetCount += 1 },
            startSession: { _, _ in XCTFail("session must not start after queue rejection") },
            startCapture: { _, _ in XCTFail("capture must not start after queue rejection") },
            didStart: { XCTFail("startup must not complete after queue rejection") }
        )

        do {
            _ = try await pipeline.start(with: Self.plan())
            XCTFail("Expected startup to fail when queue rejects delivery.")
        } catch InternetProductSessionError.securityFailure {
            XCTAssertEqual(resetCount, 1)
        }
    }

    private final class TestInternetSession {
        var state: InternetProductSessionState = .idle
    }

    private static func plan() -> InternetSessionLeaseStartupPlan {
        InternetSessionLeaseStartupPlan(
            configuration: configuration(),
            request: profileRequest(),
            signalingBaseURL: URL(string: "https://signal.example.test")!,
            issuerToken: "issuer-token"
        )
    }

    private static func delivery(
        sessionID: String = "authority-session",
        hostToken: String = "authority-host-token",
        payload: Data = Data([0x01, 0x02])
    ) -> InternetSessionLeaseDeliveryResult {
        InternetSessionLeaseDeliveryResult(
            sessionID: sessionID,
            hostSignalingToken: hostToken,
            expiresAt: Date(timeIntervalSince1970: 2_000_000_300),
            payload: payload
        )
    }

    private static func configuration(
        sessionIdentifier: String = "request-id",
        hostToken: String = "pending-token"
    ) -> InternetProductSessionConfiguration {
        InternetProductSessionConfiguration(
            transport: WebRTCTransportConfiguration(
                iceServers: [WebRTCICEServer(urls: [URL(string: "stun:stun.example.test")!])],
                peerIdentity: String(repeating: "d", count: 64),
                sessionIdentifier: sessionIdentifier,
                forceRelay: false,
                signaling: WebRTCSignalingConfiguration(
                    endpoint: URL(string: "https://signal.example.test")!,
                    bearerToken: hostToken,
                    role: .offerer
                )
            ),
            hostDeviceID: "host-1",
            hostName: "Mac",
            peerDeviceID: "device-1",
            peerIdentity: identity(deviceID: "device-1", keyID: String(repeating: "d", count: 64)),
            authoritativeSessionEpoch: 7,
            sharedSecretName: "shared-device-1",
            bootstrapSecretName: "bootstrap-device-1",
            transcriptContext: Data(repeating: 0x22, count: 32),
            video: InternetProductVideoConfiguration(
                codec: .hevc,
                width: 1920,
                height: 1080,
                framesPerSecond: 60,
                bitrateKbps: 20_000
            )
        )
    }

    private static func profileRequest(sessionEpoch: UInt64 = 7) -> InternetSignalingSessionProfileRequest {
        InternetSignalingSessionProfileRequest(
            requestID: "request-id",
            accountID: "acct-1",
            hostDeviceID: "host-1",
            clientDeviceID: "device-1",
            sessionEpoch: sessionEpoch,
            ttlSeconds: 300,
            sessionProfile: InternetSessionProfileLeaseRequest(
                pairingID: "pair-1",
                hostIdentity: identity(deviceID: "host-1", keyID: String(repeating: "h", count: 64)),
                clientIdentity: identity(deviceID: "device-1", keyID: String(repeating: "d", count: 64)),
                signalingURL: "https://signal.example.test",
                transcriptContext: Data(repeating: 0x33, count: 32),
                protocolSessionID: Data("request-id".utf8),
                iceServers: [InternetSessionProfileICEServerRequest(
                    urls: ["stun:stun.example.test"],
                    username: nil,
                    credential: nil
                )]
            )
        )
    }

    private static func identity(deviceID: String, keyID: String) -> PlatformPublicIdentity {
        PlatformPublicIdentity(
            deviceID: deviceID,
            keyID: keyID,
            keyEpoch: 1,
            signingPublicKey: Data([UInt8(0x04)] + Array(repeating: UInt8(0x11), count: 64))
        )
    }
}

private final class TestLeaseSendable: InternetSessionLeaseSendable {
    private let sendResult: Bool
    private(set) var receivedPayload: Data?
    private(set) var receivedTransferID: Data?

    init(sendResult: Bool = true) {
        self.sendResult = sendResult
    }

    func sendBulkRecord(_ payload: Data, transferID: Data) -> Bool {
        receivedPayload = payload
        receivedTransferID = transferID
        return sendResult
    }
}
