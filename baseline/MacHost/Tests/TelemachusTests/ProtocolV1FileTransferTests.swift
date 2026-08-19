import CryptoKit
import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class ProtocolV1FileTransferTests: XCTestCase {
    func testSafeFilenameRejectsPathTraversalAndSeparators() {
        XCTAssertTrue(ProtocolV1IncomingFileTransferManager.isSafeFileName("hello.txt"))
        XCTAssertFalse(ProtocolV1IncomingFileTransferManager.isSafeFileName(""))
        XCTAssertFalse(ProtocolV1IncomingFileTransferManager.isSafeFileName("."))
        XCTAssertFalse(ProtocolV1IncomingFileTransferManager.isSafeFileName(".."))
        XCTAssertFalse(ProtocolV1IncomingFileTransferManager.isSafeFileName("../escape.txt"))
        XCTAssertFalse(ProtocolV1IncomingFileTransferManager.isSafeFileName("dir/file.txt"))
        XCTAssertFalse(ProtocolV1IncomingFileTransferManager.isSafeFileName("dir\\file.txt"))
        XCTAssertFalse(ProtocolV1IncomingFileTransferManager.isSafeFileName("bad\0name"))
    }

    func testManagedPolicyAndPeerLimitsResolveDenyWins() {
        var remoteStatus = VSManagedPolicyStatus()
        remoteStatus.managed = true
        remoteStatus.fileTransferAllowed = false
        remoteStatus.maximumFileBytes = 5

        var peerLimits = VSResourceLimits()
        peerLimits.maximumFileBytes = 7
        peerLimits.maximumFileChunkBytes = 4

        let base = ProtocolV1FileTransferPolicy(
            allowed: true,
            maximumFileBytes: 10,
            maximumChunkBytes: 8,
            maximumConcurrentTransfers: 1,
            maximumTotalTemporaryBytes: 20
        )
        let managed = base.applying(remote: ProtocolV1RemoteManagedPolicy(status: remoteStatus))
        XCTAssertFalse(managed.allowed)
        XCTAssertEqual(managed.maximumFileBytes, 5)

        let negotiated = base.negotiated(with: peerLimits)
        XCTAssertTrue(negotiated.allowed)
        XCTAssertEqual(negotiated.maximumFileBytes, 7)
        XCTAssertEqual(negotiated.maximumChunkBytes, 4)
    }

    func testIncomingManagerDefaultsToUserDeniedUntilExplicitApproval() throws {
        let manager = try ProtocolV1IncomingFileTransferManager(
            policy: .default,
            directory: temporaryDirectory(),
            approval: { _ in false }
        )

        XCTAssertThrowsError(try manager.accept(
            offer(payload: Data("hello".utf8)),
            remotePolicy: .unmanaged,
            negotiatedPolicy: .default,
            sessionEpoch: 7
        )) { error in
            XCTAssertEqual(error as? ProtocolV1FileTransferError, .userDenied)
        }
        XCTAssertEqual(manager.activeTransferCount, 0)
    }

    func testServerFileApprovalRequestDoesNotSynchronouslyWaitForMainQueue() throws {
        let offer = offer(payload: Data("hello".utf8))
        let callerReturned = DispatchSemaphore(value: 0)
        let releaseApproval = DispatchSemaphore(value: 0)
        let completionReturned = DispatchSemaphore(value: 0)
        let resultLock = NSLock()
        var completedValue: Bool?

        DispatchQueue.global(qos: .userInitiated).async {
            StreamingServer.requestFileTransferApproval(
                offer: offer,
                approval: { receivedOffer in
                    XCTAssertEqual(receivedOffer.transferID, offer.transferID)
                    _ = releaseApproval.wait(timeout: .now() + .seconds(1))
                    return true
                },
                completion: { accepted in
                    resultLock.lock()
                    completedValue = accepted
                    resultLock.unlock()
                    completionReturned.signal()
                }
            )
            callerReturned.signal()
        }

        XCTAssertEqual(callerReturned.wait(timeout: .now() + .milliseconds(250)), .success)
        releaseApproval.signal()

        let deadline = Date(timeIntervalSinceNow: 1)
        var completed = completionReturned.wait(timeout: .now()) == .success
        while !completed, Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.01))
            completed = completionReturned.wait(timeout: .now()) == .success
        }
        XCTAssertTrue(completed)
        resultLock.lock()
        let accepted = completedValue
        resultLock.unlock()
        XCTAssertEqual(accepted, true)
    }

    func testIncomingManagerAcceptsOrderedChunksAndVerifiesCompletedDigest() throws {
        let payload = Data("hello".utf8)
        let directory = temporaryDirectory()
        let manager = try ProtocolV1IncomingFileTransferManager(
            policy: ProtocolV1FileTransferPolicy(maximumChunkBytes: 3),
            directory: directory,
            approval: { _ in true }
        )
        let offer = offer(payload: payload)
        let accept = try manager.accept(
            offer,
            remotePolicy: .unmanaged,
            negotiatedPolicy: ProtocolV1FileTransferPolicy(maximumChunkBytes: 3),
            sessionEpoch: 7
        )
        XCTAssertTrue(accept.accepted)
        XCTAssertEqual(accept.maximumChunkBytes, 3)

        XCTAssertEqual(try manager.append(chunk(offer: offer, offset: 0, payload: Data("hel".utf8), final: false), sessionEpoch: 7), 3)
        XCTAssertEqual(try manager.append(chunk(offer: offer, offset: 3, payload: Data("lo".utf8), final: true), sessionEpoch: 7), 5)

        let completed = try manager.finish(transferID: offer.transferID)
        XCTAssertEqual(completed.fileName, "hello.txt")
        XCTAssertEqual(completed.sha256, Data(SHA256.hash(data: payload)))
        XCTAssertEqual(try Data(contentsOf: completed.stagingURL), payload)
        XCTAssertEqual(manager.activeTransferCount, 0)
    }

    func testIncomingManagerAcceptsSingleFinalChunkForEmptyFile() throws {
        let directory = temporaryDirectory()
        let manager = try ProtocolV1IncomingFileTransferManager(
            policy: ProtocolV1FileTransferPolicy(maximumChunkBytes: 3),
            directory: directory,
            approval: { _ in true }
        )
        let offer = offer(payload: Data())
        _ = try manager.accept(
            offer,
            remotePolicy: .unmanaged,
            negotiatedPolicy: ProtocolV1FileTransferPolicy(maximumChunkBytes: 3),
            sessionEpoch: 7
        )

        XCTAssertEqual(try manager.append(chunk(offer: offer, offset: 0, payload: Data(), final: true), sessionEpoch: 7), 0)
        let completed = try manager.finish(transferID: offer.transferID)
        XCTAssertEqual(completed.sha256, Data(SHA256.hash(data: Data())))
        XCTAssertEqual(try Data(contentsOf: completed.stagingURL), Data())
    }

    func testIncomingManagerRejectsUnexpectedEmptyNonFinalChunk() throws {
        let manager = try ProtocolV1IncomingFileTransferManager(
            policy: ProtocolV1FileTransferPolicy(maximumChunkBytes: 3),
            directory: temporaryDirectory(),
            approval: { _ in true }
        )
        let offer = offer(payload: Data("hello".utf8))
        _ = try manager.accept(offer, remotePolicy: .unmanaged, negotiatedPolicy: .default, sessionEpoch: 7)

        XCTAssertThrowsError(try manager.append(chunk(offer: offer, offset: 0, payload: Data(), final: false), sessionEpoch: 7)) { error in
            XCTAssertEqual(error as? ProtocolV1FileTransferError, .emptyChunk)
        }
    }

    func testIncomingManagerRejectsDigestOffsetEpochAndCleansCancel() throws {
        let payload = Data("hello".utf8)
        let directory = temporaryDirectory()
        let manager = try ProtocolV1IncomingFileTransferManager(
            policy: ProtocolV1FileTransferPolicy(maximumChunkBytes: 8),
            directory: directory,
            approval: { _ in true }
        )
        let offer = offer(payload: payload)
        _ = try manager.accept(offer, remotePolicy: .unmanaged, negotiatedPolicy: .default, sessionEpoch: 7)

        XCTAssertThrowsError(try manager.append(chunk(offer: offer, offset: 1, payload: Data("h".utf8), final: false), sessionEpoch: 7)) { error in
            XCTAssertEqual(error as? ProtocolV1FileTransferError, .unexpectedOffset(expected: 0, actual: 1))
        }
        XCTAssertThrowsError(try manager.append(chunk(offer: offer, offset: 0, payload: Data("h".utf8), final: false, headerEpoch: 6), sessionEpoch: 7)) { error in
            XCTAssertEqual(error as? ProtocolV1FileTransferError, .staleSessionEpoch(expected: 7, actual: 6))
        }

        let badDigest = try chunk(offer: offer, offset: 0, payload: Data("h".utf8), final: false).serializedFrame()
        var corrupted = badDigest
        corrupted[corrupted.count - 1] ^= 0x01
        XCTAssertThrowsError(try ProtocolV1FileChunk(serializedFrame: corrupted)) { error in
            XCTAssertEqual(error as? ProtocolV1FileTransferError, .chunkDigestMismatch)
        }

        manager.cancel(transferID: offer.transferID)
        XCTAssertEqual(manager.activeTransferCount, 0)
        XCTAssertTrue((try FileManager.default.contentsOfDirectory(atPath: directory.path)).isEmpty)
    }

    func testIncomingManagerFailClosedForPolicyLimitsAndUnsafeOfferBeforeApproval() throws {
        var approvalCalls = 0
        let manager = try ProtocolV1IncomingFileTransferManager(
            policy: ProtocolV1FileTransferPolicy(maximumFileBytes: 4),
            directory: temporaryDirectory(),
            approval: { _ in approvalCalls += 1; return true }
        )
        XCTAssertThrowsError(try manager.accept(
            offer(fileName: "../escape.txt", payload: Data("hello".utf8)),
            remotePolicy: .unmanaged,
            negotiatedPolicy: ProtocolV1FileTransferPolicy(maximumFileBytes: 4),
            sessionEpoch: 7
        )) { error in
            XCTAssertEqual(error as? ProtocolV1FileTransferError, .invalidFileName)
        }
        XCTAssertEqual(approvalCalls, 0)

        XCTAssertThrowsError(try manager.accept(
            offer(payload: Data("hello".utf8)),
            remotePolicy: .unmanaged,
            negotiatedPolicy: ProtocolV1FileTransferPolicy(maximumFileBytes: 4),
            sessionEpoch: 7
        )) { error in
            XCTAssertEqual(error as? ProtocolV1FileTransferError, .fileTooLarge(5))
        }
        XCTAssertEqual(approvalCalls, 0)

        var status = VSManagedPolicyStatus()
        status.managed = true
        status.fileTransferAllowed = false
        status.maximumFileBytes = 10
        XCTAssertThrowsError(try manager.accept(
            offer(payload: Data("hi".utf8)),
            remotePolicy: ProtocolV1RemoteManagedPolicy(status: status),
            negotiatedPolicy: .default,
            sessionEpoch: 7
        )) { error in
            XCTAssertEqual(error as? ProtocolV1FileTransferError, .policyDenied)
        }
        XCTAssertEqual(approvalCalls, 0)
    }

    func testOutgoingTransferBuildsOfferAndBoundedChunks() throws {
        let fileURL = temporaryDirectory().appendingPathComponent("send.txt")
        let payload = Data("hello".utf8)
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try payload.write(to: fileURL)
        let transfer = try ProtocolV1OutgoingFileTransfer(
            fileURL: fileURL,
            mimeType: "text/plain",
            policy: ProtocolV1FileTransferPolicy(maximumChunkBytes: 3)
        )
        XCTAssertEqual(transfer.offer.fileName, "send.txt")
        XCTAssertEqual(transfer.offer.mimeType, "text/plain")
        XCTAssertEqual(transfer.offer.byteLength, 5)
        XCTAssertEqual(transfer.offer.sha256, Data(SHA256.hash(data: payload)))

        let first = try XCTUnwrap(transfer.nextChunk(maximumBytes: 2, sessionEpoch: 7))
        XCTAssertEqual(first.header.offset, 0)
        XCTAssertEqual(first.header.sessionEpoch, 7)
        XCTAssertEqual(first.header.payloadLength, 2)
        XCTAssertFalse(first.header.final)
        XCTAssertEqual(try ProtocolV1FileChunk(serializedFrame: first.serializedFrame()), first)

        let second = try XCTUnwrap(transfer.nextChunk(maximumBytes: 8, sessionEpoch: 7))
        XCTAssertEqual(second.header.offset, 2)
        XCTAssertEqual(second.payload, Data("llo".utf8))
        XCTAssertTrue(second.header.final)
        XCTAssertNil(try transfer.nextChunk(maximumBytes: 8, sessionEpoch: 7))
        XCTAssertTrue(transfer.isComplete)
    }

    func testOutgoingTransferSupportsEmptyFileWithSingleFinalChunk() throws {
        let fileURL = temporaryDirectory().appendingPathComponent("empty.txt")
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: fileURL.path, contents: Data())
        let transfer = try ProtocolV1OutgoingFileTransfer(
            fileURL: fileURL,
            mimeType: "text/plain",
            policy: ProtocolV1FileTransferPolicy(maximumChunkBytes: 3)
        )

        let chunk = try XCTUnwrap(transfer.nextChunk(maximumBytes: 2, sessionEpoch: 7))
        XCTAssertEqual(chunk.header.offset, 0)
        XCTAssertEqual(chunk.header.payloadLength, 0)
        XCTAssertTrue(chunk.header.final)
        XCTAssertEqual(chunk.header.chunkSha256, Data(SHA256.hash(data: Data())))
        XCTAssertEqual(try ProtocolV1FileChunk(serializedFrame: chunk.serializedFrame()), chunk)
        XCTAssertNil(try transfer.nextChunk(maximumBytes: 2, sessionEpoch: 7))
        XCTAssertTrue(transfer.isComplete)
    }

    func testOutgoingTransferRemembersAcceptedChunkLimitForProgressDrivenSending() throws {
        let fileURL = temporaryDirectory().appendingPathComponent("send.txt")
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("hello".utf8).write(to: fileURL)
        let transfer = try ProtocolV1OutgoingFileTransfer(
            fileURL: fileURL,
            mimeType: "text/plain",
            policy: ProtocolV1FileTransferPolicy(maximumChunkBytes: 5)
        )
        transfer.applyAcceptedMaximumChunkBytes(2)

        XCTAssertEqual(transfer.maximumChunkBytes(default: 5), 2)
        let first = try XCTUnwrap(transfer.nextChunk(maximumBytes: transfer.maximumChunkBytes(default: 5), sessionEpoch: 7))
        XCTAssertEqual(first.payload, Data("he".utf8))
    }

    func testBulkTransportFrameCarriesFileChunkPayload() throws {
        let offer = offer(payload: Data("hello".utf8))
        let fileChunk = chunk(offer: offer, offset: 0, payload: Data("hello".utf8), final: true)
        let payload = try fileChunk.serializedFrame()
        let frame = try ProtocolV1TransportFrame(channel: .bulk, payload: payload).encoded()
        var framer = ProtocolV1Framer()
        XCTAssertEqual(
            try framer.append(frame),
            [ProtocolV1TransportFrame(channel: .bulk, payload: payload)]
        )
    }

    private func temporaryDirectory() -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("vibescreen-file-transfer-tests", isDirectory: true)
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

    private func chunk(
        offer: VSFileOffer,
        offset: UInt64,
        payload: Data,
        final: Bool,
        headerEpoch: UInt64 = 7
    ) -> ProtocolV1FileChunk {
        var header = VSFileChunkHeader()
        header.transferID = offer.transferID
        header.offset = offset
        header.payloadLength = UInt32(payload.count)
        header.sessionEpoch = headerEpoch
        header.chunkSha256 = Data(SHA256.hash(data: payload))
        header.final = final
        return ProtocolV1FileChunk(header: header, payload: payload)
    }
}
