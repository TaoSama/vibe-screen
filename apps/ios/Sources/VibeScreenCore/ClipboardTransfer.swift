import CryptoKit
import Foundation
import VibeScreenProtocol

public enum ClipboardUserOperation: Sendable {
    case userInitiatedSend
    case userApprovedReceive
}

public struct ValidatedClipboardContent: Equatable, Sendable {
    public let changeID: Data
    public let originDeviceID: String
    public let mimeType: String
    public let content: Data
}

public enum ClipboardTransferError: Error, Equatable {
    case policyDenied
    case explicitUserActionRequired
    case unsupportedMIME(String)
    case contentTooLarge(Int)
    case invalidChangeID
    case digestMismatch
    case feedbackLoop
}

public struct ClipboardTransferCoordinator: Sendable {
    public let maximumBytes: Int
    public let supportedMIMETypes: Set<String>
    private var localChangeIDs: [Data] = []
    private let historyLimit = 128

    public init(
        maximumBytes: Int = 1_024 * 1_024,
        supportedMIMETypes: Set<String> = ["text/plain", "image/png"]
    ) {
        self.maximumBytes = max(1, maximumBytes)
        self.supportedMIMETypes = supportedMIMETypes
    }

    public mutating func prepareOutgoing(
        content: Data,
        mimeType: String,
        originDeviceID: String,
        operation: ClipboardUserOperation,
        policy: ManagedPolicy
    ) throws -> VSClipboardContent {
        guard case .userInitiatedSend = operation else {
            throw ClipboardTransferError.explicitUserActionRequired
        }
        guard policy.clipboardAllowed else { throw ClipboardTransferError.policyDenied }
        try validate(content: content, mimeType: mimeType)
        let changeID = withUnsafeBytes(of: UUID().uuid) { Data($0) }
        remember(changeID)
        var message = VSClipboardContent()
        message.changeID = changeID
        message.originDeviceID = originDeviceID
        message.mimeType = mimeType
        message.content = content
        message.sha256 = Data(SHA256.hash(data: content))
        return message
    }

    public mutating func acceptIncoming(
        _ message: VSClipboardContent,
        operation: ClipboardUserOperation,
        policy: ManagedPolicy
    ) throws -> ValidatedClipboardContent {
        guard case .userApprovedReceive = operation else {
            throw ClipboardTransferError.explicitUserActionRequired
        }
        guard policy.clipboardAllowed else { throw ClipboardTransferError.policyDenied }
        guard !message.changeID.isEmpty else { throw ClipboardTransferError.invalidChangeID }
        guard !localChangeIDs.contains(message.changeID) else { throw ClipboardTransferError.feedbackLoop }
        try validate(content: message.content, mimeType: message.mimeType)
        guard Data(SHA256.hash(data: message.content)) == message.sha256 else {
            throw ClipboardTransferError.digestMismatch
        }
        remember(message.changeID)
        return ValidatedClipboardContent(
            changeID: message.changeID,
            originDeviceID: message.originDeviceID,
            mimeType: message.mimeType,
            content: message.content
        )
    }

    private func validate(content: Data, mimeType: String) throws {
        guard supportedMIMETypes.contains(mimeType) else {
            throw ClipboardTransferError.unsupportedMIME(mimeType)
        }
        guard content.count <= maximumBytes else {
            throw ClipboardTransferError.contentTooLarge(content.count)
        }
    }

    private mutating func remember(_ changeID: Data) {
        localChangeIDs.append(changeID)
        if localChangeIDs.count > historyLimit {
            localChangeIDs.removeFirst(localChangeIDs.count - historyLimit)
        }
    }
}
