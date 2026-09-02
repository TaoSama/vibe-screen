import Foundation

struct InternetSessionLeaseStartupPlan {
    let configuration: InternetProductSessionConfiguration
    let request: InternetSignalingSessionProfileRequest
    let signalingBaseURL: URL
    let issuerToken: String
}

struct InternetSessionLeaseRefreshPlan {
    let currentConfiguration: InternetProductSessionConfiguration
    let request: InternetSignalingSessionProfileRequest
    let signalingBaseURL: URL
    let issuerToken: String
}

enum InternetSessionLeaseDeliveryLifecycleDisposition: Equatable {
    case queued
    case delivered
    case alreadyDelivered
    case alreadyPending
    case noPendingDelivery
    case stale
    case deliveryFailed

    var permitsStartup: Bool {
        switch self {
        case .queued, .delivered, .alreadyDelivered:
            return true
        case .alreadyPending, .noPendingDelivery, .stale, .deliveryFailed:
            return false
        }
    }
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
    ) -> InternetSessionLeaseDeliveryLifecycleDisposition {
        guard isCurrent() else { return .stale }
        guard !deliverySent else { return .alreadyDelivered }
        guard pendingDelivery == nil else { return .alreadyPending }
        pendingDelivery = result
        if case .streaming = sessionState() {
            return sendPending(isCurrent: isCurrent, send: send)
        }
        return .queued
    }

    @discardableResult
    func sendPending(
        isCurrent: () -> Bool,
        send: (InternetSessionLeaseDeliveryResult) -> Bool
    ) -> InternetSessionLeaseDeliveryLifecycleDisposition {
        guard isCurrent() else { return .stale }
        guard let delivery = pendingDelivery else {
            return deliverySent ? .alreadyDelivered : .noPendingDelivery
        }
        guard send(delivery) else { return .deliveryFailed }
        pendingDelivery = nil
        deliverySent = true
        return .delivered
    }

    func handleStateChange(
        _ state: InternetProductSessionState,
        isCurrent: () -> Bool,
        send: (InternetSessionLeaseDeliveryResult) -> Bool,
        failClosed: (String) async -> Void
    ) async {
        guard case .streaming = state else { return }
        switch sendPending(isCurrent: isCurrent, send: send) {
        case .deliveryFailed, .noPendingDelivery:
            await failClosed(Self.deliveryFailureReason)
        case .delivered, .alreadyDelivered, .alreadyPending, .queued, .stale:
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
    let queueDelivery: (InternetSessionLeaseDeliveryResult, Session) -> InternetSessionLeaseDeliveryLifecycleDisposition
    let resetDelivery: () -> Void
    let startSession: (Session, InternetProductSessionConfiguration) throws -> Void
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
        let disposition = queueDelivery(delivery, session)
        guard disposition.permitsStartup else {
            resetDelivery()
            if case .stale = disposition {
                throw CancellationError()
            }
            throw InternetProductSessionError.securityFailure(
                "The authoritative session lease could not be attached to the active Internet session."
            )
        }
        do {
            try startSession(session, configuration)
        } catch {
            resetDelivery()
            throw error
        }
        try await startCapture(session, configuration)
        didStart()
        return session
    }

    func refresh(
        session: Session,
        with plan: InternetSessionLeaseRefreshPlan,
        provideFreshSession: (Session, InternetProductSessionConfiguration) throws -> Void
    ) async throws {
        let delivery = try await createDelivery(
            plan.signalingBaseURL,
            plan.issuerToken,
            plan.request
        )
        try requireCurrentStart()
        let configuration = try applyDelivery(
            plan.currentConfiguration,
            delivery,
            plan.signalingBaseURL
        )
        resetDelivery()
        let disposition = queueDelivery(delivery, session)
        guard disposition.permitsStartup else {
            resetDelivery()
            if case .stale = disposition {
                throw CancellationError()
            }
            throw InternetProductSessionError.securityFailure(
                "The authoritative session lease could not be attached to the fresh Internet session."
            )
        }
        do {
            try provideFreshSession(session, configuration)
        } catch {
            resetDelivery()
            throw error
        }
    }
}
