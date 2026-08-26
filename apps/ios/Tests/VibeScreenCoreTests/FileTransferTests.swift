import CryptoKit
import Foundation
import XCTest
@testable import VibeScreenCore
import VibeScreenProtocol

final class FileTransferTests: XCTestCase {
    func testIncomingManagerRejectsEmptyFileWhenManagedMaximumIsZero() throws {
        let manager = try IncomingFileTransferManager(
            policy: .init(),
            directory: temporaryDirectory()
        )
        let policy = managedPolicy(fileTransferAllowed: true, maximumFileBytes: 0)

        XCTAssertThrowsError(try manager.accept(offer(payload: Data()), managedPolicy: policy)) { error in
            XCTAssertEqual(error as? FileTransferError, .policyDenied)
        }
        XCTAssertEqual(manager.activeTransferCount, 0)
    }

    func testOutgoingTransferRejectsEmptyFileWhenManagedMaximumIsZero() throws {
        let fileURL = temporaryDirectory().appendingPathComponent("empty.txt")
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: fileURL.path, contents: Data())
        let policy = managedPolicy(fileTransferAllowed: true, maximumFileBytes: 0)

        XCTAssertThrowsError(try OutgoingFileTransfer(
            fileURL: fileURL,
            mimeType: "text/plain",
            policy: .init(),
            managedPolicy: policy
        )) { error in
            XCTAssertEqual(error as? FileTransferError, .policyDenied)
        }
    }

    private func temporaryDirectory() -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("vibescreen-ios-file-transfer-tests", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    private func offer(fileName: String = "hello.txt", payload: Data) -> VSFileOffer {
        var offer = VSFileOffer()
        offer.transferID = Data([1, 2, 3, 4])
        offer.fileName = fileName
        offer.mimeType = "text/plain"
        offer.byteLength = UInt64(payload.count)
        offer.sha256 = Data(SHA256.hash(data: payload))
        return offer
    }

    private func managedPolicy(
        fileTransferAllowed: Bool,
        maximumFileBytes: UInt64
    ) -> ManagedPolicy {
        ManagedPolicy(
            isManaged: true,
            clipboardAllowed: true,
            fileTransferAllowed: fileTransferAllowed,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: maximumFileBytes,
            allowedHosts: []
        )
    }
}
