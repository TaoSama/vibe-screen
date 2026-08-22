import AppKit
import Foundation
import UniformTypeIdentifiers
import VibeScreenProtocol

protocol FileTransferServer: AnyObject {
    var fileTransferAvailable: Bool { get }

    func offerProtocolV1File(fileURL: URL, mimeType: String) throws
}

@MainActor
protocol FileTransferAlertPresenter: AnyObject {
    func presentIncomingFileApproval(fileName: String, byteLength: UInt64, mimeType: String) -> Bool
    func presentInformation(title: String, message: String)
    func presentWarning(title: String, message: String)
}

@MainActor
final class NSAlertFileTransferPresenter: FileTransferAlertPresenter {
    nonisolated init() {}

    func presentIncomingFileApproval(fileName: String, byteLength: UInt64, mimeType: String) -> Bool {
        let alert = NSAlert()
        alert.messageText = "Receive File from Android?"
        alert.informativeText = "\(fileName)\n\(Self.formattedByteCount(byteLength))\n\(mimeType)"
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Receive")
        alert.addButton(withTitle: "Reject")
        return alert.runModal() == .alertFirstButtonReturn
    }

    func presentInformation(title: String, message: String) {
        present(title: title, message: message, style: .informational)
    }

    func presentWarning(title: String, message: String) {
        present(title: title, message: message, style: .warning)
    }

    private func present(title: String, message: String, style: NSAlert.Style) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = style
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private static func formattedByteCount(_ bytes: UInt64) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(clamping: bytes), countStyle: .file)
    }
}

@MainActor
final class FileTransferUIController: NSObject {
    private let alertPresenter: FileTransferAlertPresenter
    private weak var server: FileTransferServer?
    private var fileTransferAvailable = false

    let sendMenuItem: NSMenuItem

    init(
        sendMenuItem: NSMenuItem,
        alertPresenter: FileTransferAlertPresenter = NSAlertFileTransferPresenter()
    ) {
        self.sendMenuItem = sendMenuItem
        self.alertPresenter = alertPresenter
        super.init()
        sendMenuItem.target = self
        sendMenuItem.action = #selector(sendFileToClient)
        updateMenuState()
    }

    func bind(server: FileTransferServer, fileTransferAvailable: Bool) {
        self.server = server
        self.fileTransferAvailable = fileTransferAvailable
        updateMenuState()
    }

    func unbind() {
        server = nil
        fileTransferAvailable = false
        updateMenuState()
    }

    func approveIncomingFileOffer(_ offer: VSFileOffer) -> Bool {
        alertPresenter.presentIncomingFileApproval(
            fileName: offer.fileName,
            byteLength: offer.byteLength,
            mimeType: offer.mimeType.isEmpty ? "application/octet-stream" : offer.mimeType
        )
    }

    func handleIncomingFileCompleted(_ completed: ProtocolV1CompletedIncomingFile) {
        do {
            let destination = try saveIncomingFileToDownloads(completed)
            alertPresenter.presentInformation(
                title: "File Received",
                message: "Saved \(completed.fileName) to Downloads.\nSHA-256: \(Self.hexString(completed.sha256))\nPath: \(destination.path)"
            )
            debugLog("Received file saved to Downloads: name=\(completed.fileName) sha256=\(Self.hexString(completed.sha256))")
        } catch {
            alertPresenter.presentWarning(
                title: "File Save Failed",
                message: "The received file remains in temporary storage.\n\(error.localizedDescription)\nPath: \(completed.stagingURL.path)"
            )
            debugLog("Received file save failed: \(error.localizedDescription)")
        }
    }

    @objc private func sendFileToClient() {
        guard let server, server.fileTransferAvailable else {
            alertPresenter.presentInformation(
                title: "File Transfer Unavailable",
                message: "Connect a Protocol v1 client that negotiated file transfer before sending a file."
            )
            updateMenuState()
            return
        }

        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.prompt = "Send"
        guard panel.runModal() == .OK, let fileURL = panel.url else { return }

        do {
            try server.offerProtocolV1File(
                fileURL: fileURL,
                mimeType: Self.mimeType(for: fileURL)
            )
            alertPresenter.presentInformation(
                title: "File Offered",
                message: "Waiting for Android to approve \(fileURL.lastPathComponent)."
            )
        } catch {
            alertPresenter.presentWarning(
                title: "File Transfer Failed",
                message: error.localizedDescription
            )
        }
    }

    private func saveIncomingFileToDownloads(_ completed: ProtocolV1CompletedIncomingFile) throws -> URL {
        guard let downloads = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first else {
            throw CocoaError(.fileNoSuchFile)
        }
        try FileManager.default.createDirectory(at: downloads, withIntermediateDirectories: true)
        let destination = Self.availableDestination(in: downloads, fileName: completed.fileName)
        do {
            try FileManager.default.moveItem(at: completed.stagingURL, to: destination)
        } catch {
            try FileManager.default.copyItem(at: completed.stagingURL, to: destination)
            try? FileManager.default.removeItem(at: completed.stagingURL)
        }
        return destination
    }

    private func updateMenuState() {
        sendMenuItem.isEnabled = server != nil && fileTransferAvailable
    }

    private static func mimeType(for fileURL: URL) -> String {
        if let type = UTType(filenameExtension: fileURL.pathExtension),
           let mimeType = type.preferredMIMEType {
            return mimeType
        }
        return "application/octet-stream"
    }

    private static func availableDestination(in directory: URL, fileName: String) -> URL {
        let proposed = directory.appendingPathComponent(fileName, isDirectory: false)
        guard FileManager.default.fileExists(atPath: proposed.path) else { return proposed }
        let baseName = (fileName as NSString).deletingPathExtension
        let pathExtension = (fileName as NSString).pathExtension
        for index in 1...999 {
            let candidateName = pathExtension.isEmpty
                ? "\(baseName) \(index)"
                : "\(baseName) \(index).\(pathExtension)"
            let candidate = directory.appendingPathComponent(candidateName, isDirectory: false)
            if !FileManager.default.fileExists(atPath: candidate.path) { return candidate }
        }
        return directory.appendingPathComponent("\(UUID().uuidString)-\(fileName)", isDirectory: false)
    }

    private static func hexString(_ data: Data) -> String {
        data.map { String(format: "%02x", $0) }.joined()
    }
}
