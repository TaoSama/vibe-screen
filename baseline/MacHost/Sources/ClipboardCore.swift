import Foundation
import CryptoKit
import VibeScreenProtocol

/// Metadata advertised by a remote peer before the host decides whether to
/// pull the full clipboard content.
struct ClipboardOfferMetadata: Equatable, Sendable {
    let changeID: Data
    let originDeviceID: String
    let mimeType: String
    let byteLength: UInt64
    let sha256: Data
}

/// Clipboard content that has passed origin, size, MIME, digest, and UTF-8
/// validation. The UI layer is responsible for writing it to the pasteboard
/// only after an explicit user action.
struct ValidatedClipboardContent: Equatable, Sendable {
    let changeID: Data
    let originDeviceID: String
    let mimeType: String
    let text: String
    let sha256: Data
}

enum ClipboardCoreError: Error, Equatable {
    case capabilityNotNegotiated
    case emptyContent
    case contentTooLarge(Int)
    case unsupportedMIME(String)
    case invalidChangeID
    case invalidOrigin
    case invalidDigest
    case invalidUTF8
    case unknownChangeID
    case feedbackLoop
    case tooManyPendingOffers
    case tooManyPendingRequests
    case duplicateRequest
    case offerMetadataMismatch
    case snapshotAlreadyConsumed
}

/// Session-scoped clipboard state for a single Protocol v1 connection.
///
/// The core owns the local snapshot cache, the pending-offer and
/// pending-request sets, and the bounded change-ID history used for loop
/// detection. All mutating entry points are intended to run under the
/// session lock; the type itself performs no additional synchronization.
final class ClipboardCore {
    /// Hard upper bound the host will ever accept or advertise, regardless of
    /// what the remote peer proposes.
    static let localMaximumBytes = 1_024 * 1_024 // 1 MiB

    static let changeIDByteCount = 16
    static let sha256ByteCount = 32
    static let supportedMIMEType = "text/plain"

    /// The negotiated byte limit applied to both directions. It is the minimum
    /// of the host's local cap and the remote peer's non-zero
    /// `maximum_clipboard_bytes`; a zero remote limit means "unbounded from
    /// the peer side", so the host cap wins.
    let maximumBytes: Int

    /// The host's own device identity, used as the origin for outgoing
    /// offers/content.
    let localDeviceID: String

    /// The remote peer's device identity captured from ClientHello. Every
    /// incoming offer/content must carry this exact, non-empty origin.
    let remoteDeviceID: String

    /// The single locally cached clipboard snapshot. Only one snapshot is
    /// retained at a time: a new explicit user share replaces it. The core
    /// never reads the pasteboard itself.
    private struct LocalSnapshot {
        let changeID: Data
        let text: String
        let sha256: Data
        /// True once the snapshot has been served in response to a remote
        /// request. A consumed snapshot cannot be served again: a duplicate
        /// request for the same change ID is rejected.
        var consumed: Bool
    }

    private var localSnapshot: LocalSnapshot?

    /// Offers received from the remote peer, keyed by change ID. Bounded by
    /// `maximumPendingOffers` so a misbehaving peer cannot grow it without
    /// limit.
    private var pendingOffers: [Data: ClipboardOfferMetadata] = [:]

    /// Change IDs the host has requested content for, in insertion order.
    /// Bounded by `maximumPendingRequests`; when the bound is exceeded the
    /// oldest request is evicted (latest-only) so a misbehaving peer cannot
    /// grow this set without limit.
    private var pendingRequests: [Data] = []

    /// Change IDs this core has generated or accepted, in arrival order. Used
    /// to detect feedback loops where the host's own clipboard change ID
    /// echoes back from the peer.
    private var seenChangeIDs: [Data] = []

    /// Only the newest pending offer is retained. A newer offer evicts the
    /// previous one so a peer cannot exhaust host memory by spamming offers.
    private let maximumPendingOffers = 1
    /// Only the newest pending request is retained. A newer request evicts
    /// the previous one; a duplicate request for the same change ID is
    /// rejected rather than silently replacing it.
    private let maximumPendingRequests = 1
    private let historyLimit = 128

    init(maximumBytes: Int, localDeviceID: String, remoteDeviceID: String) {
        self.maximumBytes = max(1, min(maximumBytes, Self.localMaximumBytes))
        self.localDeviceID = localDeviceID
        self.remoteDeviceID = remoteDeviceID
    }

    // MARK: - Outgoing (host shares)

    /// Cache a single clipboard snapshot from an explicit user share and
    /// return the offer the host should send. The text is assumed to have
    /// been read from the pasteboard on the main thread by the caller; the
    /// core never touches NSPasteboard.
    func prepareOffer(text: String) throws -> VSClipboardOffer {
        guard !text.isEmpty else { throw ClipboardCoreError.emptyContent }
        let contentBytes = Data(text.utf8)
        guard contentBytes.count <= maximumBytes else {
            throw ClipboardCoreError.contentTooLarge(contentBytes.count)
        }
        let changeID = Self.makeChangeID()
        let digest = Data(SHA256.hash(data: contentBytes))
        localSnapshot = LocalSnapshot(
            changeID: changeID,
            text: text,
            sha256: digest,
            consumed: false
        )
        remember(changeID)

        var offer = VSClipboardOffer()
        offer.changeID = changeID
        offer.originDeviceID = localDeviceID
        offer.mimeType = Self.supportedMIMEType
        offer.byteLength = UInt64(contentBytes.count)
        offer.sha256 = digest
        return offer
    }

    /// Build the content message for a change ID the remote peer requested.
    /// Returns nil when the change ID does not match the cached snapshot
    /// (unknown or stale). The cached snapshot is reused verbatim; the core
    /// never re-reads the pasteboard. After the first successful serve the
    /// snapshot is marked consumed, so a duplicate request for the same
    /// change ID is rejected.
    func makeContent(for changeID: Data) -> VSClipboardContent? {
        guard var snapshot = localSnapshot, snapshot.changeID == changeID else {
            return nil
        }
        guard !snapshot.consumed else { return nil }
        snapshot.consumed = true
        localSnapshot = snapshot

        var content = VSClipboardContent()
        content.changeID = snapshot.changeID
        content.originDeviceID = localDeviceID
        content.mimeType = Self.supportedMIMEType
        content.content = Data(snapshot.text.utf8)
        content.sha256 = snapshot.sha256
        return content
    }

    // MARK: - Incoming (remote shares)

    /// Validate an incoming offer and remember it so the host can later
    /// request its content. Returns the metadata the UI needs to decide
    /// whether to approve the transfer. A duplicate offer for the same
    /// change ID is idempotent when its metadata matches; conflicting
    /// metadata is rejected.
    @discardableResult
    func handleOffer(_ offer: VSClipboardOffer) throws -> ClipboardOfferMetadata {
        try validateOrigin(offer.originDeviceID)
        guard offer.changeID.count == Self.changeIDByteCount else {
            throw ClipboardCoreError.invalidChangeID
        }
        guard !seenChangeIDs.contains(offer.changeID) else {
            throw ClipboardCoreError.feedbackLoop
        }
        guard offer.mimeType == Self.supportedMIMEType else {
            throw ClipboardCoreError.unsupportedMIME(offer.mimeType)
        }
        guard offer.byteLength > 0, offer.byteLength <= maximumBytes else {
            throw ClipboardCoreError.contentTooLarge(Int(clamping: offer.byteLength))
        }
        guard offer.sha256.count == Self.sha256ByteCount else {
            throw ClipboardCoreError.invalidDigest
        }

        let metadata = ClipboardOfferMetadata(
            changeID: offer.changeID,
            originDeviceID: offer.originDeviceID,
            mimeType: offer.mimeType,
            byteLength: offer.byteLength,
            sha256: offer.sha256
        )

        if let existing = pendingOffers[offer.changeID] {
            guard existing == metadata else {
                throw ClipboardCoreError.offerMetadataMismatch
            }
            return existing
        }

        // Latest-only: when the pending-offer bound is reached, evict the
        // oldest offer before admitting the new one. A peer can never grow
        // this map without limit; it can only ever replace the current entry.
        if pendingOffers.count >= maximumPendingOffers,
           let oldestKey = pendingOffers.keys.first {
            pendingOffers.removeValue(forKey: oldestKey)
            // A newer offer supersedes the old transfer. If the user already
            // requested the old content, a late response is now direct
            // content and requires a separate overwrite confirmation instead
            // of failing the healthy session for missing offer metadata.
            pendingRequests.removeAll { $0 == oldestKey }
        }
        pendingOffers[offer.changeID] = metadata
        return metadata
    }

    /// Mark a previously received offer as requested by the user. Returns the
    /// request message to send. Throws if the change ID is unknown or if the
    /// same change ID already has a pending request (duplicate). When the
    /// pending-request bound is reached the oldest request is evicted
    /// (latest-only) so a new request can always be issued for the newest
    /// offer.
    func requestContent(for changeID: Data) throws -> VSClipboardRequest {
        guard pendingOffers[changeID] != nil else {
            throw ClipboardCoreError.unknownChangeID
        }
        // A duplicate request for the same change ID is rejected: the host
        // already asked for this content and should wait for the peer's
        // response rather than re-requesting.
        guard !pendingRequests.contains(changeID) else {
            throw ClipboardCoreError.duplicateRequest
        }
        // Latest-only: evict the oldest pending request when the bound is
        // reached. The evicted request's content (if it later arrives) will
        // be treated as unsolicited/direct and require explicit approval.
        if pendingRequests.count >= maximumPendingRequests {
            pendingRequests.removeFirst()
        }
        pendingRequests.append(changeID)
        var request = VSClipboardRequest()
        request.changeID = changeID
        return request
    }

    /// Remove an exact in-flight request after the UI's bounded wait expires.
    /// The offer stays cached so the user can explicitly retry it. Returns
    /// false when content already consumed the request or another offer
    /// superseded it.
    func expireRequest(for changeID: Data) -> Bool {
        guard pendingRequests.contains(changeID) else { return false }
        pendingRequests.removeAll { $0 == changeID }
        return true
    }

    /// Validate an incoming content message. When the change ID matches a
    /// pending request AND the content metadata matches the original offer,
    /// the content is treated as an approved transfer; otherwise it is
    /// treated as a direct (unsolicited) transfer that still requires
    /// explicit local approval before being written to the pasteboard.
    func handleContent(_ content: VSClipboardContent) throws -> (
        validated: ValidatedClipboardContent,
        isDirect: Bool
    ) {
        try validateOrigin(content.originDeviceID)
        guard content.changeID.count == Self.changeIDByteCount else {
            throw ClipboardCoreError.invalidChangeID
        }
        guard !seenChangeIDs.contains(content.changeID) else {
            throw ClipboardCoreError.feedbackLoop
        }
        guard content.mimeType == Self.supportedMIMEType else {
            throw ClipboardCoreError.unsupportedMIME(content.mimeType)
        }
        guard !content.content.isEmpty else {
            throw ClipboardCoreError.emptyContent
        }
        guard content.content.count <= maximumBytes else {
            throw ClipboardCoreError.contentTooLarge(content.content.count)
        }
        guard content.sha256.count == Self.sha256ByteCount else {
            throw ClipboardCoreError.invalidDigest
        }
        guard Data(SHA256.hash(data: content.content)) == content.sha256 else {
            throw ClipboardCoreError.invalidDigest
        }
        guard let text = String(data: content.content, encoding: .utf8) else {
            throw ClipboardCoreError.invalidUTF8
        }

        // A solicited content (one matching a pending request) must match
        // the original offer's metadata exactly: byte length, digest, MIME,
        // and origin. A mismatch is a protocol violation and is rejected
        // rather than silently downgraded to a direct/unsolicited transfer,
        // because the user already approved this specific offer.
        let isSolicited = pendingRequests.contains(content.changeID)
        let offer = pendingOffers[content.changeID]
        let matchesOffer = offer.map {
            $0.byteLength == UInt64(content.content.count)
                && $0.sha256 == content.sha256
                && $0.mimeType == content.mimeType
                && $0.originDeviceID == content.originDeviceID
        } ?? false

        if isSolicited {
            guard matchesOffer else {
                throw ClipboardCoreError.offerMetadataMismatch
            }
            // Solicited content consumes its pending request and offer and
            // is remembered for loop detection.
            pendingRequests.removeAll { $0 == content.changeID }
            pendingOffers.removeValue(forKey: content.changeID)
            remember(content.changeID)
        }

        // A direct (unsolicited) content has no matching pending request.
        // It still requires explicit local approval before being written to
        // the pasteboard. The offer (if any) is left in place so the user
        // can still request it through the normal offer flow, and the
        // change ID is not remembered so the subsequent request+content
        // round trip is not falsely rejected as a loop.
        let isDirect = !isSolicited

        let validated = ValidatedClipboardContent(
            changeID: content.changeID,
            originDeviceID: content.originDeviceID,
            mimeType: content.mimeType,
            text: text,
            sha256: content.sha256
        )
        return (validated, isDirect)
    }

    // MARK: - Lifecycle

    /// Drop all cached snapshots, pending offers, pending requests, and
    /// change-ID history. Called when the session disconnects or resets.
    func reset() {
        localSnapshot = nil
        pendingOffers.removeAll()
        pendingRequests.removeAll()
        seenChangeIDs.removeAll()
    }

    // MARK: - Helpers

    private func validateOrigin(_ origin: String) throws {
        guard !origin.isEmpty, origin == remoteDeviceID else {
            throw ClipboardCoreError.invalidOrigin
        }
    }

    private func remember(_ changeID: Data) {
        seenChangeIDs.append(changeID)
        if seenChangeIDs.count > historyLimit {
            seenChangeIDs.removeFirst(seenChangeIDs.count - historyLimit)
        }
    }

    /// Generate a 16-byte change ID from a UUID. UUID.uuid is 16 bytes of
    /// randomness (RFC 4122 v4), which satisfies the nonce requirement
    /// without pulling in the Security framework.
    private static func makeChangeID() -> Data {
        withUnsafeBytes(of: UUID().uuid) { Data($0) }
    }
}
