import Foundation

struct InternetSessionLeaseStartupPlan {
    let configuration: InternetProductSessionConfiguration
    let request: InternetSignalingSessionProfileRequest
    let signalingBaseURL: URL
    let issuerToken: String
}

@MainActor
final class InternetSessionLeaseDeliveryLifecycle {
    static let deliveryFailureReason =
        "The authoritative session lease could not be delivered to the peer."

    private(set) var pendingDelivery: InternetSessionLeaseDeliveryResult?
    private(set) var deliverySent = false

    func queue(
        _ result: InternetSessionLeaseDeliveryResult,
        isCurrent: () -> Bool,
        sessionState: () -> InternetProductSessionState,
        send: (InternetSessionLeaseDeliveryResult) -> Bool
    ) -> Bool {
        guard isCurrent() else { return false }
        pendingDelivery = result
        if case .streaming = sessionState() {
            return sendPending(isCurrent: isCurrent, send: send)
        }
        return true
    }

    @discardableResult
    func sendPending(
        isCurrent: () -> Bool,
        send: (InternetSessionLeaseDeliveryResult) -> Bool
    ) -> Bool {
        guard isCurrent(), let delivery = pendingDelivery else {
            return deliverySent
        }
        guard send(delivery) else { return false }
        pendingDelivery = nil
        deliverySent = true
        return true
    }

    func handleStateChange(
        _ state: InternetProductSessionState,
        isCurrent: () -> Bool,
        send: (InternetSessionLeaseDeliveryResult) -> Bool,
        failClosed: (String) async -> Void
    ) async {
        guard case .streaming = state else { return }
        guard sendPending(isCurrent: isCurrent, send: send) else {
            await failClosed(Self.deliveryFailureReason)
            return
        }
    }

    func reset() {
        pendingDelivery = nil
        deliverySent = false
    }
}

@MainActor
struct InternetSessionLeaseStartupPipeline<Session: AnyObject> {
    typealias DeliveryFactory = (
        URL,
        String,
        InternetSignalingSessionProfileRequest
    ) async throws -> InternetSessionLeaseDeliveryResult
    typealias ApplyDelivery = (
        InternetProductSessionConfiguration,
        InternetSessionLeaseDeliveryResult,
        URL
    ) throws -> InternetProductSessionConfiguration

    let makeSession: () -> Session
    let createDelivery: DeliveryFactory
    let requireCurrentStart: () throws -> Void
    let applyDelivery: ApplyDelivery
    let prepareSession: (Session, InternetProductSessionConfiguration) -> Void
    let startSession: (Session, InternetProductSessionConfiguration) throws -> Void
    let queueDelivery: (InternetSessionLeaseDeliveryResult, Session) -> Bool
    let startCapture: (Session, InternetProductSessionConfiguration) async throws -> Void
    let didStart: () -> Void

    @discardableResult
    func start(with plan: InternetSessionLeaseStartupPlan) async throws -> Session {
        let delivery = try await createDelivery(
            plan.signalingBaseURL,
            plan.issuerToken,
            plan.request
        )
        try requireCurrentStart()
        let configuration = try applyDelivery(
            plan.configuration,
            delivery,
            plan.signalingBaseURL
        )
        let session = makeSession()
        prepareSession(session, configuration)
        try startSession(session, configuration)
        guard queueDelivery(delivery, session) else {
            throw InternetProductSessionError.securityFailure(
                "The authoritative session lease could not be attached to the active Internet session."
            )
        }
        try await startCapture(session, configuration)
        didStart()
        return session
    }
}
