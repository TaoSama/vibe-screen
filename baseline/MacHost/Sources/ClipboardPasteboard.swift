import AppKit
import Foundation

@MainActor
protocol ClipboardPasteboardStorage: AnyObject {
    func string(forType dataType: NSPasteboard.PasteboardType) -> String?
    func writeObjects(_ objects: [NSPasteboardWriting]) -> Bool
}

extension NSPasteboard: ClipboardPasteboardStorage {}

/// Abstracts the macOS pasteboard so clipboard reads and writes can be tested
/// without touching `NSPasteboard.general`. Every implementation must be
/// confined to the main actor: `NSPasteboard` is a main-thread-only AppKit
/// type and the clipboard UI never reads or writes it from a background queue.
@MainActor
protocol ClipboardPasteboard: AnyObject {
    /// Read the current `text/plain` string from the pasteboard. Returns nil
    /// when the pasteboard has no string content.
    func readString() -> String?

    /// Replace the pasteboard contents with the given `text/plain` string.
    /// Returns true when the write succeeded, false otherwise so the caller
    /// can surface the failure to the user instead of silently dropping it.
    @discardableResult
    func writeString(_ string: String) -> Bool
}

/// Production adapter backed by `NSPasteboard.general`. All access is guarded
/// by a main-queue precondition so a caller that accidentally hops off the
/// main actor crashes loudly instead of racing AppKit's pasteboard state.
@MainActor
final class NSPasteboardClipboardAdapter: ClipboardPasteboard {
    private let pasteboard: ClipboardPasteboardStorage

    init(pasteboard: ClipboardPasteboardStorage = NSPasteboard.general) {
        self.pasteboard = pasteboard
    }

    func readString() -> String? {
        dispatchPrecondition(condition: .onQueue(.main))
        return pasteboard.string(forType: .string)
    }

    func writeString(_ string: String) -> Bool {
        dispatchPrecondition(condition: .onQueue(.main))
        let item = NSPasteboardItem()
        guard item.setString(string, forType: .string) else { return false }
        return pasteboard.writeObjects([item])
    }
}
