import Foundation
import VibeScreenCore

final class SecurityScopedOutgoingFile {
    let transfer: OutgoingFileTransfer
    private let url: URL
    private var hasSecurityScope: Bool

    init(
        url: URL,
        mimeType: String,
        policy: FileTransferPolicy,
        managedPolicy: ManagedPolicy
    ) throws {
        self.url = url
        hasSecurityScope = url.startAccessingSecurityScopedResource()
        do {
            transfer = try OutgoingFileTransfer(
                fileURL: url,
                mimeType: mimeType,
                policy: policy,
                managedPolicy: managedPolicy
            )
        } catch {
            if hasSecurityScope { url.stopAccessingSecurityScopedResource() }
            hasSecurityScope = false
            throw error
        }
    }

    deinit {
        if hasSecurityScope { url.stopAccessingSecurityScopedResource() }
    }

    func cancel() {
        transfer.cancel()
        if hasSecurityScope {
            url.stopAccessingSecurityScopedResource()
            hasSecurityScope = false
        }
    }
}
