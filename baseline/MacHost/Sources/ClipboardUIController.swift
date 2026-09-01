import AppKit
import Foundation
import VibeScreenProtocol

/// The transport the active clipboard session is running over. Drives whether
/// the UI surfaces the trusted-private-network warning before any clipboard
/// read or write.
enum ClipboardTransport: Equatable {
    case usb
    case trustedLAN
    case secureInternet
}

/// The subset of `StreamingServer` the clipboard UI needs. The core layer
/// implements these on `StreamingServer`; the UI depends on the protocol so
/// menu actions can be unit-tested with a double.
protocol ClipboardServer: AnyObject {
    /// Whether the connected peer negotiated the clipboard capability. The
    /// menu items are disabled while this is false so the user cannot attempt
    /// clipboard operations against a peer that did not agree to them.
    var clipboardAvailable: Bool { get }

    /// Share the Mac clipboard text with the connected peer. The server runs
    /// the text through `ClipboardCore.prepareOffer(text:)`, caches the
    /// snapshot, and sends the resulting `ClipboardOffer`. A subsequent
    /// `ClipboardRequest` from the peer is answered from the cached snapshot
    /// without re-reading the pasteboard. Returns true when the offer was
    /// sent; false when clipboard was not negotiated, the session is not
    /// streaming, or the content failed validation.
    @discardableResult
    func shareClipboardText(_ text: String) -> Bool

    /// Request the full content for a change ID the peer previously offered.
    /// Returns true when the request was sent; false when the change ID is
    /// unknown, clipboard was not negotiated, or the session is not streaming.
    @discardableResult
    func sendClipboardRequest(_ request: VSClipboardRequest) -> Bool

    /// Release an exact request after the bounded UI wait expires. Returns
    /// false when the core already consumed or superseded the request.
    @discardableResult
    func expireClipboardRequest(changeID: Data) -> Bool
}

/// Presents the explicit user confirmations the clipboard controller needs.
/// The production implementation uses `NSAlert`; tests inject a double so no
/// real modal runs.
@MainActor
protocol ClipboardAlertPresenter: AnyObject {
    /// Present a confirmation dialog and return true when the user approves.
    func presentConfirmation(
        title: String,
        message: String,
        confirmButtonTitle: String
    ) -> Bool

    /// Present an informational dialog with a single OK button.
    func presentInformation(title: String, message: String)
}

/// Schedules the bounded wait for a requested clipboard body. Production uses
/// a main-run-loop timer; tests inject a manual scheduler.
@MainActor
protocol ClipboardRequestTimeoutScheduling: AnyObject {
    func schedule(_ action: @escaping @MainActor () -> Void)
    func cancel()
}

@MainActor
final class MainQueueClipboardRequestTimeoutScheduler: ClipboardRequestTimeoutScheduling {
    private static let timeout: TimeInterval = 10
    private var timer: Timer?

    nonisolated init() {}

    func schedule(_ action: @escaping @MainActor () -> Void) {
        cancel()
        timer = Timer.scheduledTimer(withTimeInterval: Self.timeout, repeats: false) { _ in
            Task { @MainActor in action() }
        }
    }

    func cancel() {
        timer?.invalidate()
        timer = nil
    }
}

/// Production alert presenter backed by `NSAlert`. Runs modally on the main
/// thread, which is safe because every clipboard action is already gated on
/// an explicit menu click.
@MainActor
final class NSAlertClipboardPresenter: ClipboardAlertPresenter {
    /// The presenter holds no stored state, so its initializer can run in any
    /// isolation context. This allows `ClipboardUIController` to use it as a
    /// default argument value without triggering a MainActor isolation error.
    nonisolated init() {}

    func presentConfirmation(
        title: String,
        message: String,
        confirmButtonTitle: String
    ) -> Bool {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: confirmButtonTitle)
        alert.addButton(withTitle: "Cancel")
        return alert.runModal() == .alertFirstButtonReturn
    }

    func presentInformation(title: String, message: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = .informational
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
}

/// A pending clipboard transfer awaiting explicit user approval.
private enum PendingClipboardTransfer {
    /// The remote peer advertised an offer; the user must click receive to
    /// pull the content.
    case offer(ClipboardOfferMetadata)
    /// The remote peer sent content directly (no offer/request). The user
    /// must still approve before it overwrites the local pasteboard.
    case directContent(ValidatedClipboardContent)

    var changeID: Data {
        switch self {
        case .offer(let metadata): return metadata.changeID
        case .directContent(let content): return content.changeID
        }
    }

    var byteCount: Int {
        switch self {
        case .offer(let metadata): return Int(metadata.byteLength)
        case .directContent(let content): return content.text.utf8.count
        }
    }
}

/// Owns the status-bar clipboard menu items and the explicit-action state
/// machine. All pasteboard access is routed through an injected
/// `ClipboardPasteboard` on the main actor; the controller never polls the
/// pasteboard and never writes it without a user click.
@MainActor
final class ClipboardUIController: NSObject {
    private let pasteboard: ClipboardPasteboard
    private let alertPresenter: ClipboardAlertPresenter
    private let requestTimeoutScheduler: ClipboardRequestTimeoutScheduling
    private weak var server: ClipboardServer?
    /// Capability snapshot captured while binding the exact active server
    /// generation. Reading it from the server during menu updates would race
    /// the network queue and could accidentally observe a replacement session.
    private var clipboardAvailable = false
    private var pendingTransfer: PendingClipboardTransfer?
    /// The client generation this controller is bound to. Incoming events
    /// from any other generation are dropped.
    private var boundGeneration: UInt64 = 0
    /// The transport the active session runs over. Controls whether the
    /// trusted-private-network warning is shown.
    private var transport: ClipboardTransport = .usb
    /// True after the user has approved a receive request and the request
    /// was successfully sent. The receive menu stays disabled until the
    /// matching content arrives or a newer offer replaces it.
    private var requestInFlight = false

    /// Menu items this controller manages. They are enabled/disabled based on
    /// connection, capability, and pending-transfer state.
    let shareMenuItem: NSMenuItem
    let receiveMenuItem: NSMenuItem

    init(
        pasteboard: ClipboardPasteboard,
        shareMenuItem: NSMenuItem,
        receiveMenuItem: NSMenuItem,
        alertPresenter: ClipboardAlertPresenter = NSAlertClipboardPresenter(),
        requestTimeoutScheduler: ClipboardRequestTimeoutScheduling =
            MainQueueClipboardRequestTimeoutScheduler()
    ) {
        self.pasteboard = pasteboard
        self.alertPresenter = alertPresenter
        self.requestTimeoutScheduler = requestTimeoutScheduler
        self.shareMenuItem = shareMenuItem
        self.receiveMenuItem = receiveMenuItem
        super.init()
        shareMenuItem.target = self
        shareMenuItem.action = #selector(shareMacClipboard)
        receiveMenuItem.target = self
        receiveMenuItem.action = #selector(receiveAndroidClipboard)
        updateMenuState()
    }

    // MARK: - Server / session binding

    /// Bind the controller to the active server, client generation, and
    /// transport. Stale pending transfers from a previous generation are
    /// dropped. The generation and transport are stored so incoming events
    /// can be validated and the right risk warnings can be shown.
    func bind(
        server: ClipboardServer,
        generation: UInt64,
        transport: ClipboardTransport,
        clipboardAvailable: Bool
    ) {
        if self.server === server,
           self.boundGeneration == generation,
           self.transport == transport {
            self.clipboardAvailable = clipboardAvailable
            if !clipboardAvailable {
                clearPending(reason: "clipboard unavailable")
            } else {
                updateMenuState()
            }
            return
        }
        self.server = server
        self.boundGeneration = generation
        self.transport = transport
        self.clipboardAvailable = clipboardAvailable
        clearPending(reason: "new client generation \(generation)")
    }

    /// Drop the server binding and any pending transfer. Called on disconnect
    /// or server teardown.
    func unbind() {
        server = nil
        boundGeneration = 0
        clipboardAvailable = false
        requestInFlight = false
        clearPending(reason: "disconnect")
    }

    // MARK: - Incoming events from the core layer

    /// The remote peer offered clipboard content. Only the menu state is
    /// updated; no content request is sent until the user clicks receive.
    func handleOffer(_ metadata: ClipboardOfferMetadata, generation: UInt64) {
        guard server != nil, isCurrentGeneration(generation) else { return }
        requestTimeoutScheduler.cancel()
        pendingTransfer = .offer(metadata)
        requestInFlight = false
        updateMenuState()
    }

    /// The remote peer sent content that matched a pending request. Validate
    /// that the generation and change ID still match the offer the user
    /// approved, then write to the pasteboard.
    func handleContent(_ content: ValidatedClipboardContent, generation: UInt64) {
        guard server != nil, isCurrentGeneration(generation) else { return }
        guard requestInFlight else { return }
        guard case .offer(let metadata) = pendingTransfer,
              metadata.changeID == content.changeID else {
            // Stale or unexpected content must never overwrite the pasteboard.
            // Once the user has an approved request in flight, consume that
            // approval on a mismatch so the peer must publish a fresh offer.
            clearPending(reason: "unexpected clipboard content")
            alertPresenter.presentInformation(
                title: "Clipboard Receive Failed",
                message: "The received clipboard content did not match the approved offer. Ask the device to share again."
            )
            return
        }
        writeToPasteboard(content)
        clearPending(reason: "content written")
    }

    /// The remote peer sent content without a preceding offer/request. Store
    /// it as a pending transfer so the user can explicitly approve it; the
    /// pasteboard is never overwritten automatically.
    func handleDirectContent(_ content: ValidatedClipboardContent, generation: UInt64) {
        guard server != nil, isCurrentGeneration(generation) else { return }
        // An unsolicited transfer cannot replace a request the user already
        // approved or a newer, different offer waiting for explicit approval.
        // A late body for the same request may arrive after the core expired
        // it but before the main actor cleared requestInFlight; allow only
        // that exact ID and still require direct-content confirmation.
        if requestInFlight {
            guard case .offer(let metadata) = pendingTransfer,
                  metadata.changeID == content.changeID else { return }
        } else if case .offer(let metadata) = pendingTransfer, metadata.changeID != content.changeID {
            return
        }
        requestTimeoutScheduler.cancel()
        pendingTransfer = .directContent(content)
        requestInFlight = false
        updateMenuState()
    }

    // MARK: - User actions

    @objc private func shareMacClipboard() {
        guard let server, clipboardAvailable, server.clipboardAvailable else { return }
        guard let text = pasteboard.readString(), !text.isEmpty else {
            alertPresenter.presentInformation(
                title: "Clipboard Is Empty",
                message: "There is no text on the Mac clipboard to share."
            )
            return
        }
        let byteCount = text.utf8.count
        guard byteCount <= ClipboardCore.localMaximumBytes else {
            alertPresenter.presentInformation(
                title: "Clipboard Too Large",
                message: "The Mac clipboard text is \(byteCount) bytes, which exceeds the \(ClipboardCore.localMaximumBytes)-byte clipboard limit."
            )
            return
        }
        switch transport {
        case .usb:
            break
        case .trustedLAN:
            let confirmed = alertPresenter.presentConfirmation(
                title: "Share Mac Clipboard?",
                message: """
                The clipboard text will be sent to the connected device over the trusted LAN. \
                Current macOS and Android peers use encrypted application records, but this is still intended only for a trusted private network.
                """,
                confirmButtonTitle: "Share"
            )
            guard confirmed else { return }
        case .secureInternet:
            let confirmed = alertPresenter.presentConfirmation(
                title: "Share Mac Clipboard?",
                message: "The clipboard text will be sent to the connected device over the secure Internet session.",
                confirmButtonTitle: "Share"
            )
            guard confirmed else { return }
        }

        guard server.shareClipboardText(text) else {
            alertPresenter.presentInformation(
                title: "Clipboard Share Failed",
                message: "The clipboard offer could not be sent on the active session."
            )
            return
        }
    }

    @objc private func receiveAndroidClipboard() {
        guard let server, clipboardAvailable, server.clipboardAvailable,
              let pending = pendingTransfer, !requestInFlight else { return }
        switch pending {
        case .offer(let metadata):
            // The user explicitly requested the content; send the request and
            // wait for the matching `clipboardContent` action to write it.
            switch transport {
            case .usb:
                break
            case .trustedLAN:
                let confirmed = alertPresenter.presentConfirmation(
                    title: "Receive Android Clipboard?",
                    message: """
                    A request for the offered clipboard content will be sent over the trusted LAN. \
                    Current macOS and Android peers use encrypted application records, but this is still intended only for a trusted private network.
                    """,
                    confirmButtonTitle: "Receive"
                )
                guard confirmed else { return }
            case .secureInternet:
                let confirmed = alertPresenter.presentConfirmation(
                    title: "Receive Android Clipboard?",
                    message: "A request for the offered clipboard content will be sent over the secure Internet session.",
                    confirmButtonTitle: "Receive"
                )
                guard confirmed else { return }
            }
            var request = VSClipboardRequest()
            request.changeID = metadata.changeID
            let sent = server.sendClipboardRequest(request)
            if sent {
                // Disable the receive menu until the content arrives or a
                // newer offer replaces the pending one.
                requestInFlight = true
                updateMenuState()
                scheduleRequestTimeout(
                    changeID: metadata.changeID,
                    generation: boundGeneration
                )
            } else {
                alertPresenter.presentInformation(
                    title: "Clipboard Receive Failed",
                    message: "The clipboard request could not be sent on the active session."
                )
            }
        case .directContent(let content):
            // The content already arrived; the user is now approving the
            // pasteboard overwrite. Trusted-LAN direct content used encrypted
            // application records, but still requires explicit user approval.
            let message: String
            switch transport {
            case .trustedLAN:
                message = """
                The device sent clipboard content directly. Overwriting the Mac clipboard cannot be undone. \
                The content was delivered over trusted LAN encrypted application records, which are intended only for a trusted private network.
                """
            case .secureInternet:
                message = "The device sent clipboard content directly over the secure Internet session. Overwrite the Mac clipboard?"
            case .usb:
                message = "The device sent clipboard content directly. Overwrite the Mac clipboard?"
            }
            let confirmed = alertPresenter.presentConfirmation(
                title: "Overwrite Mac Clipboard?",
                message: message,
                confirmButtonTitle: "Overwrite"
            )
            guard confirmed else { return }
            writeToPasteboard(content)
            clearPending(reason: "direct content approved")
        }
    }

    // MARK: - Helpers

    private func writeToPasteboard(_ content: ValidatedClipboardContent) {
        guard content.mimeType == ClipboardCore.supportedMIMEType else { return }
        let ok = pasteboard.writeString(content.text)
        if !ok {
            alertPresenter.presentInformation(
                title: "Clipboard Write Failed",
                message: "Could not write the received clipboard text to the Mac pasteboard."
            )
        }
    }

    private func isCurrentGeneration(_ generation: UInt64) -> Bool {
        generation == boundGeneration
    }

    private func scheduleRequestTimeout(changeID: Data, generation: UInt64) {
        requestTimeoutScheduler.schedule { [weak self] in
            guard let self, self.server != nil,
                  self.boundGeneration == generation, self.requestInFlight,
                  case .offer(let metadata) = self.pendingTransfer,
                  metadata.changeID == changeID else { return }
            guard self.clipboardAvailable, self.server?.clipboardAvailable == true else {
                self.clearPending(reason: "clipboard unavailable during request timeout")
                return
            }
            // Serialize expiry through the server's network queue. If content
            // already consumed the request and merely has a main-actor
            // callback pending, expiry returns false and the approval stays
            // intact for that callback.
            guard self.server?.expireClipboardRequest(changeID: changeID) == true else {
                return
            }
            self.requestTimeoutScheduler.cancel()
            self.requestInFlight = false
            self.updateMenuState()
            self.alertPresenter.presentInformation(
                title: "Clipboard Request Timed Out",
                message: "The connected device did not provide clipboard content. Try receiving it again."
            )
        }
    }

    private func clearPending(reason: String) {
        requestTimeoutScheduler.cancel()
        pendingTransfer = nil
        requestInFlight = false
        updateMenuState()
    }

    private func updateMenuState() {
        let hasServer = server != nil
        shareMenuItem.isEnabled = hasServer && clipboardAvailable
        receiveMenuItem.isEnabled = hasServer && clipboardAvailable && pendingTransfer != nil && !requestInFlight
        if let pending = pendingTransfer {
            let bytes = pending.byteCount
            receiveMenuItem.title = "Receive Android Clipboard (\(bytes) bytes)"
        } else {
            receiveMenuItem.title = "Receive Android Clipboard"
        }
    }
}
