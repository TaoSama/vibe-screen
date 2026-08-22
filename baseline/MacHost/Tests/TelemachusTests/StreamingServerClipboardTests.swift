import CryptoKit
import Foundation
import Network
import XCTest
import VibeScreenProtocol
@testable import Telemachus

/// Direct integration tests for the StreamingServer clipboard surface.
///
/// These tests exercise the server-level clipboard APIs (`shareClipboard`,
/// `requestClipboard`) and the main-actor callbacks that forward incoming
/// clipboard offers/content to the UI. They cover the legacy-fallback and
/// capability-not-negotiated rejection paths, the solicited/direct content
/// dispatch, and the client-callback generation filter that drops callbacks
/// from a previous connection.
final class StreamingServerClipboardTests: XCTestCase {
    private let queue = DispatchQueue(
        label: "StreamingServerClipboardTests",
        qos: .userInitiated
    )

    private var server: StreamingServer!
    private var client: NWConnection?
    private var inboundFramer = ProtocolV1Framer()
    private var sessionID = Data()
    private var sessionEpoch: UInt64 = 0

    override func tearDown() {
        client?.cancel()
        client = nil
        inboundFramer = ProtocolV1Framer()
        sessionID = Data()
        sessionEpoch = 0
        server?.stop()
        server = nil
        super.tearDown()
    }

    // MARK: - Legacy fallback

    func testShareClipboardReturnsFalseInLegacyMode() throws {
        let port = testPort(offset: 100)
        server = StreamingServer(port: port)
        let connected = expectation(description: "legacy client connected")
        server.onClientConnected = { _ in connected.fulfill() }
        try server.start()

        client = try readyClient(port: port)
        wait(for: [connected], timeout: 2)

        XCTAssertFalse(server.shareClipboard("hello from mac"))
    }

    func testRequestClipboardReturnsFalseInLegacyMode() throws {
        let port = testPort(offset: 101)
        server = StreamingServer(port: port)
        let connected = expectation(description: "legacy client connected")
        server.onClientConnected = { _ in connected.fulfill() }
        try server.start()

        client = try readyClient(port: port)
        wait(for: [connected], timeout: 2)

        let changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        XCTAssertFalse(server.requestClipboard(changeID: changeID))
    }

    // MARK: - Capability not negotiated

    func testShareClipboardReturnsFalseWhenClipboardNotNegotiated() throws {
        let port = testPort(offset: 102)
        server = StreamingServer(port: port)
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()

        // Drive the handshake to STREAMING without the clipboard capability.
        try driveHandshakeToStreaming(clipboard: false)

        XCTAssertFalse(server.shareClipboard("hello from mac"))
    }

    func testRequestClipboardReturnsFalseWhenClipboardNotNegotiated() throws {
        let port = testPort(offset: 103)
        server = StreamingServer(port: port)
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()

        try driveHandshakeToStreaming(clipboard: false)

        let changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        XCTAssertFalse(server.requestClipboard(changeID: changeID))
    }

    // MARK: - Incoming clipboard dispatch

    func testClipboardOfferCallbackFiresOnMainActorWithGeneration() throws {
        let port = testPort(offset: 104)
        server = StreamingServer(port: port)
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()
        let generation = try driveHandshakeToStreaming(clipboard: true)

        let offerReceived = expectation(description: "clipboard offer received")
        var receivedMetadata: ClipboardOfferMetadata?
        var receivedGeneration: UInt64?
        var callbackIsMainThread = false
        server.onClipboardOfferReceived = { metadata, gen in
            callbackIsMainThread = Thread.isMainThread
            receivedMetadata = metadata
            receivedGeneration = gen
            offerReceived.fulfill()
        }

        let text = "from android"
        let bytes = Data(text.utf8)
        let changeID = Data(repeating: 0x0A, count: ClipboardCore.changeIDByteCount)
        var offer = VSClipboardOffer()
        offer.changeID = changeID
        offer.originDeviceID = clientDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64(bytes.count)
        offer.sha256 = sha256(bytes)
        try sendControl(payload: .clipboardOffer(offer), messageID: 10)

        wait(for: [offerReceived], timeout: 2)

        XCTAssertTrue(callbackIsMainThread)
        XCTAssertEqual(receivedMetadata?.changeID, changeID)
        XCTAssertEqual(receivedMetadata?.originDeviceID, clientDeviceID)
        XCTAssertEqual(receivedGeneration, generation)
    }

    func testSolicitedClipboardContentCallbackFires() throws {
        let port = testPort(offset: 105)
        server = StreamingServer(port: port)
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()
        try driveHandshakeToStreaming(clipboard: true)

        let text = "solicited content"
        let bytes = Data(text.utf8)
        let changeID = Data(repeating: 0x0B, count: ClipboardCore.changeIDByteCount)

        // 1. Client offers.
        let offerReceived = expectation(description: "offer received")
        server.onClipboardOfferReceived = { _, _ in offerReceived.fulfill() }
        var offer = VSClipboardOffer()
        offer.changeID = changeID
        offer.originDeviceID = clientDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64(bytes.count)
        offer.sha256 = sha256(bytes)
        try sendControl(payload: .clipboardOffer(offer), messageID: 10)

        wait(for: [offerReceived], timeout: 2)

        // 2. Host requests the content.
        XCTAssertTrue(server.requestClipboard(changeID: changeID))

        // 3. Client sends the matching content; it is solicited.
        let contentReceived = expectation(description: "solicited content received")
        var receivedText: String?
        server.onClipboardContentReceived = { content, _ in
            receivedText = content.text
            contentReceived.fulfill()
        }
        var content = VSClipboardContent()
        content.changeID = changeID
        content.originDeviceID = clientDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        try sendControl(payload: .clipboardContent(content), messageID: 11)

        wait(for: [contentReceived], timeout: 2)
        XCTAssertEqual(receivedText, text)
    }

    func testDirectClipboardContentCallbackFires() throws {
        let port = testPort(offset: 106)
        server = StreamingServer(port: port)
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()
        try driveHandshakeToStreaming(clipboard: true)

        let text = "unsolicited content"
        let bytes = Data(text.utf8)
        let changeID = Data(repeating: 0x0C, count: ClipboardCore.changeIDByteCount)

        let directReceived = expectation(description: "direct content received")
        var receivedText: String?
        server.onClipboardDirectContentReceived = { content, _ in
            receivedText = content.text
            directReceived.fulfill()
        }
        var content = VSClipboardContent()
        content.changeID = changeID
        content.originDeviceID = clientDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        try sendControl(payload: .clipboardContent(content), messageID: 10)

        wait(for: [directReceived], timeout: 2)
        XCTAssertEqual(receivedText, text)
    }

    // MARK: - Generation filtering

    func testStaleClipboardOfferCallbackIsDroppedAfterGenerationAdvance() throws {
        let port = testPort(offset: 107)
        server = StreamingServer(port: port)
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()
        try driveHandshakeToStreaming(clipboard: true)

        // The offer callback must not fire after the client-callback generation
        // has advanced past the connection's active generation.
        let staleDropped = expectation(description: "stale offer dropped")
        staleDropped.isInverted = true
        server.onClipboardOfferReceived = { _, _ in staleDropped.fulfill() }

        // Suspend the network queue so the offer sits in the input buffer
        // until we have advanced the generation gate.
        let entered = DispatchSemaphore(value: 0)
        let resume = DispatchSemaphore(value: 0)
        server.suspendNetworkQueueForSelfTest(entered: entered, resume: resume)
        XCTAssertEqual(entered.wait(timeout: .now() + 2), .success)

        let text = "stale"
        let bytes = Data(text.utf8)
        let changeID = Data(repeating: 0x0D, count: ClipboardCore.changeIDByteCount)
        var offer = VSClipboardOffer()
        offer.changeID = changeID
        offer.originDeviceID = clientDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64(bytes.count)
        offer.sha256 = sha256(bytes)
        let frame = try ProtocolV1TransportFrame(
            channel: .control,
            payload: envelope(messageID: 10, payload: .clipboardOffer(offer)).serializedData()
        ).encoded()
        client?.send(content: frame, completion: .contentProcessed { _ in })

        // Advance the client-callback generation past the active connection
        // generation so the dispatched main-actor callback is dropped.
        server.advanceClientGenerationForSelfTest(to: UInt64.max)

        resume.signal()

        wait(for: [staleDropped], timeout: 1)
    }

    // MARK: - File transfer integration

    func testIncomingFileOfferAcceptsBulkChunkAndCompletes() throws {
        let port = testPort(offset: 108)
        server = StreamingServer(port: port)
        server.onFileTransferApprovalRequested = { offer in
            offer.fileName == "hello.txt"
        }
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()
        try driveHandshakeToStreaming(clipboard: false, fileTransfer: true)

        let payload = Data("from android file".utf8)
        let transferID = Data(repeating: 0x4A, count: 16)
        let completed = expectation(description: "incoming file completed")
        var completedFile: ProtocolV1CompletedIncomingFile?
        server.onIncomingFileCompleted = { file in
            completedFile = file
            completed.fulfill()
        }

        try sendControl(
            payload: .fileOffer(fileOffer(
                transferID: transferID,
                fileName: "hello.txt",
                payload: payload
            )),
            messageID: 10
        )

        let acceptEnvelope = try receiveControlEnvelopes(
            until: { envelope in
                if case .fileAccept = envelope.payload { return true }
                return false
            },
            timeout: 2
        ).last
        guard case .fileAccept(let accept)? = acceptEnvelope?.payload else {
            return XCTFail("Missing FileAccept")
        }
        XCTAssertTrue(accept.accepted)
        XCTAssertEqual(accept.transferID, transferID)

        try sendBulk(chunk(
            transferID: transferID,
            offset: 0,
            payload: payload,
            final: true
        ))

        let resultEnvelopes = try receiveControlEnvelopes(
            until: { envelope in
                if case .fileTransferComplete = envelope.payload { return true }
                return false
            },
            timeout: 2
        )
        XCTAssertTrue(resultEnvelopes.contains { envelope in
            if case .fileTransferProgress(let progress)? = envelope.payload {
                return progress.transferID == transferID && progress.receivedBytes == UInt64(payload.count)
            }
            return false
        })
        guard let completeEnvelope = resultEnvelopes.last,
              case .fileTransferComplete(let result)? = completeEnvelope.payload else {
            return XCTFail("Missing FileTransferComplete")
        }
        XCTAssertTrue(result.accepted)
        XCTAssertEqual(result.sha256, sha256(payload))

        wait(for: [completed], timeout: 2)
        XCTAssertEqual(completedFile?.fileName, "hello.txt")
        XCTAssertEqual(try completedFile.map { try Data(contentsOf: $0.stagingURL) }, payload)
    }

    func testOfferProtocolV1FileSendsOfferAndBulkChunkAfterAccept() throws {
        let port = testPort(offset: 109)
        server = StreamingServer(port: port)
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()
        try driveHandshakeToStreaming(clipboard: false, fileTransfer: true)

        let payload = Data("from mac file".utf8)
        let fileURL = temporaryDirectory().appendingPathComponent("send.txt")
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try payload.write(to: fileURL)

        try server.offerProtocolV1File(fileURL: fileURL, mimeType: "text/plain")
        let offerEnvelope = try receiveControlEnvelopes(
            until: { envelope in
                if case .fileOffer = envelope.payload { return true }
                return false
            },
            timeout: 2
        ).last
        guard case .fileOffer(let offer)? = offerEnvelope?.payload else {
            return XCTFail("Missing FileOffer")
        }
        XCTAssertEqual(offer.fileName, "send.txt")
        XCTAssertEqual(offer.byteLength, UInt64(payload.count))
        XCTAssertEqual(offer.sha256, sha256(payload))

        var accept = VSFileAccept()
        accept.transferID = offer.transferID
        accept.accepted = true
        accept.maximumChunkBytes = 64 * 1024
        try sendControl(payload: .fileAccept(accept), messageID: 10)

        let bulkFrame = try receiveFrame(channel: .bulk, timeout: 2)
        let fileChunk = try ProtocolV1FileChunk(serializedFrame: bulkFrame.payload)
        XCTAssertEqual(fileChunk.header.transferID, offer.transferID)
        XCTAssertEqual(fileChunk.header.offset, 0)
        XCTAssertTrue(fileChunk.header.final)
        XCTAssertEqual(fileChunk.payload, payload)

        var complete = VSFileTransferComplete()
        complete.transferID = offer.transferID
        complete.accepted = true
        complete.sha256 = offer.sha256
        try sendControl(payload: .fileTransferComplete(complete), messageID: 11)
    }

    func testOfferProtocolV1FileCancelsOnUnexpectedProgressOffset() throws {
        let port = testPort(offset: 111)
        server = StreamingServer(port: port)
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()
        try driveHandshakeToStreaming(clipboard: false, fileTransfer: true)

        let payload = Data("from mac file".utf8)
        let fileURL = temporaryDirectory().appendingPathComponent("send.txt")
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try payload.write(to: fileURL)

        try server.offerProtocolV1File(fileURL: fileURL, mimeType: "text/plain")
        let offerEnvelope = try receiveControlEnvelopes(
            until: { envelope in
                if case .fileOffer = envelope.payload { return true }
                return false
            },
            timeout: 2
        ).last
        guard case .fileOffer(let offer)? = offerEnvelope?.payload else {
            return XCTFail("Missing FileOffer")
        }

        var accept = VSFileAccept()
        accept.transferID = offer.transferID
        accept.accepted = true
        accept.maximumChunkBytes = 2
        try sendControl(payload: .fileAccept(accept), messageID: 10)
        _ = try receiveFrame(channel: .bulk, timeout: 2)

        var progress = VSFileTransferProgress()
        progress.transferID = offer.transferID
        progress.receivedBytes = 1
        try sendControl(payload: .fileTransferProgress(progress), messageID: 11)

        let cancelEnvelope = try receiveControlEnvelopes(
            until: { envelope in
                if case .fileTransferCancel = envelope.payload { return true }
                return false
            },
            timeout: 2
        ).last
        guard case .fileTransferCancel(let cancellation)? = cancelEnvelope?.payload else {
            return XCTFail("Missing FileTransferCancel")
        }
        XCTAssertEqual(cancellation.transferID, offer.transferID)
        XCTAssertEqual(cancellation.reasonCode, ProtocolV1FileTransferError.unexpectedOffset(expected: 2, actual: 1).reasonCode)
    }

    func testOfferProtocolV1FileCancelsOnCompletionDigestMismatch() throws {
        let port = testPort(offset: 112)
        server = StreamingServer(port: port)
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()
        try driveHandshakeToStreaming(clipboard: false, fileTransfer: true)

        let payload = Data("from mac file".utf8)
        let fileURL = temporaryDirectory().appendingPathComponent("send.txt")
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try payload.write(to: fileURL)

        try server.offerProtocolV1File(fileURL: fileURL, mimeType: "text/plain")
        let offerEnvelope = try receiveControlEnvelopes(
            until: { envelope in
                if case .fileOffer = envelope.payload { return true }
                return false
            },
            timeout: 2
        ).last
        guard case .fileOffer(let offer)? = offerEnvelope?.payload else {
            return XCTFail("Missing FileOffer")
        }

        var accept = VSFileAccept()
        accept.transferID = offer.transferID
        accept.accepted = true
        accept.maximumChunkBytes = 64 * 1024
        try sendControl(payload: .fileAccept(accept), messageID: 10)
        _ = try receiveFrame(channel: .bulk, timeout: 2)

        var complete = VSFileTransferComplete()
        complete.transferID = offer.transferID
        complete.accepted = true
        complete.sha256 = Data(repeating: 0xEE, count: SHA256.byteCount)
        try sendControl(payload: .fileTransferComplete(complete), messageID: 11)

        let cancelEnvelope = try receiveControlEnvelopes(
            until: { envelope in
                if case .fileTransferCancel = envelope.payload { return true }
                return false
            },
            timeout: 2
        ).last
        guard case .fileTransferCancel(let cancellation)? = cancelEnvelope?.payload else {
            return XCTFail("Missing FileTransferCancel")
        }
        XCTAssertEqual(cancellation.transferID, offer.transferID)
        XCTAssertEqual(cancellation.reasonCode, ProtocolV1FileTransferError.digestMismatch.reasonCode)
    }

    func testOfferProtocolV1FileIsNoOpWhenFileTransferNotNegotiated() throws {
        let port = testPort(offset: 110)
        server = StreamingServer(port: port)
        try server.start()

        client = try readyClient(port: port)
        try upgradeToProtocolV1()
        try driveHandshakeToStreaming(clipboard: false, fileTransfer: false)

        let fileURL = temporaryDirectory().appendingPathComponent("blocked.txt")
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("blocked".utf8).write(to: fileURL)

        try server.offerProtocolV1File(fileURL: fileURL, mimeType: "text/plain")
        XCTAssertThrowsError(try receiveFrame(channel: .control, timeout: 0.3)) { error in
            guard case TestError.timeout = error else {
                return XCTFail("Expected timeout, got \(error)")
            }
        }
    }

    // MARK: - Helpers

    private let clientDeviceID = "android-device"

    private func testPort(offset: UInt16) -> UInt16 {
        let processStride = UInt16(ProcessInfo.processInfo.processIdentifier % 60) * 200
        return 52_000 + processStride + offset
    }

    private func readyClient(port: UInt16) throws -> NWConnection {
        let ready = expectation(description: "client ready")
        var failure: Error?
        let connection = NWConnection(
            host: NWEndpoint.Host("127.0.0.1"),
            port: NWEndpoint.Port(rawValue: port)!,
            using: .tcp
        )
        connection.stateUpdateHandler = { state in
            switch state {
            case .ready:
                ready.fulfill()
            case .failed(let error):
                failure = error
                ready.fulfill()
            default:
                break
            }
        }
        connection.start(queue: queue)
        wait(for: [ready], timeout: 2)
        if let failure { throw failure }
        return connection
    }

    /// Sends the Protocol v1 upgrade byte and consumes the acknowledgement.
    private func upgradeToProtocolV1() throws {
        guard let client else { throw TestError.noClient }
        let ack = expectation(description: "protocol v1 acknowledgement")
        client.receive(minimumIncompleteLength: 2, maximumLength: 2) { data, _, _, error in
            XCTAssertNil(error)
            XCTAssertEqual(data, ProtocolV1Upgrade.acknowledgement)
            ack.fulfill()
        }
        client.send(
            content: Data([ProtocolV1Upgrade.offer]),
            completion: .contentProcessed { error in XCTAssertNil(error) }
        )
        wait(for: [ack], timeout: 2)
    }

    /// Drives the Protocol v1 handshake to the STREAMING phase.
    ///
    /// Returns the active connection generation captured after the session is
    /// streaming so tests can assert callback generations.
    @discardableResult
    private func driveHandshakeToStreaming(
        clipboard: Bool,
        fileTransfer: Bool = false
    ) throws -> UInt64 {
        guard client != nil else { throw TestError.noClient }

        var generation: UInt64?
        let connected = expectation(description: "streaming connected")
        server.onClientConnected = { activeGeneration in
            generation = activeGeneration
            connected.fulfill()
        }

        let codecNegotiated = expectation(description: "codec negotiated")
        server.onCodecNegotiated = { _, _, completion in
            completion(NegotiatedDisplayConfiguration(width: 1920, height: 1080, rotation: 0))
            codecNegotiated.fulfill()
        }

        // 1. ClientHello.
        var capabilities: [VSCapability] = [.touch, .multiDisplay]
        if clipboard { capabilities.append(.clipboard) }
        if fileTransfer { capabilities.append(.fileTransfer) }
        var hello = VSClientHello()
        hello.supportedProtocols = { var r = VSProtocolRange(); r.minimum = 1; r.maximum = 1; return r }()
        hello.deviceID = clientDeviceID
        hello.deviceName = "Android"
        hello.capabilities = capabilities
        hello.codecs = [.hevc, .h264]
        try sendControl(payload: .clientHello(hello), messageID: 1)

        // Capture the identity selected by the host. Every later client
        // envelope must echo it exactly.
        wait(for: [codecNegotiated], timeout: 2)
        let handshakeResponses = try receiveControlEnvelopes(
            until: { envelope in
                guard case .sessionAccepted(_)? = envelope.payload else { return false }
                return true
            },
            timeout: 2
        )
        guard let accepted = handshakeResponses.compactMap({ envelope -> VSSessionAccepted? in
            if case .sessionAccepted(let accepted)? = envelope.payload { return accepted }
            return nil
        }).first else {
            throw TestError.missingSessionAccepted
        }
        sessionID = accepted.sessionID
        sessionEpoch = accepted.sessionEpoch

        // 2. StartDisplayRequest for the active display.
        var start = VSStartDisplayRequest()
        start.mode = .existing
        start.sourceDisplayID = "active-display"
        try sendControl(payload: .startDisplayRequest(start), messageID: 2)

        let responses = try receiveControlEnvelopes(
            until: { envelope in
                guard case .videoConfig(_)? = envelope.payload else { return false }
                return true
            },
            timeout: 2
        )
        guard let videoConfig = responses.compactMap({ envelope -> VSVideoConfig? in
            if case .videoConfig(let config)? = envelope.payload { return config }
            return nil
        }).first else {
            throw TestError.missingVideoConfig
        }

        // 3. VideoConfigResult accepted.
        var result = VSVideoConfigResult()
        result.configEpoch = videoConfig.configEpoch
        result.streamID = videoConfig.streamID
        result.accepted = true
        try sendControl(payload: .videoConfigResult(result), messageID: 3)

        wait(for: [connected], timeout: 2)
        return try XCTUnwrap(generation)
    }

    private func sendControl(
        payload: VSEnvelope.OneOf_Payload,
        messageID: UInt64
    ) throws {
        guard let client else { throw TestError.noClient }
        let frame = try ProtocolV1TransportFrame(
            channel: .control,
            payload: try envelope(messageID: messageID, payload: payload).serializedData()
        ).encoded()
        let sent = DispatchSemaphore(value: 0)
        client.send(
            content: frame,
            completion: .contentProcessed { error in
                XCTAssertNil(error)
                sent.signal()
            }
        )
        XCTAssertEqual(sent.wait(timeout: .now() + 2), .success)
    }

    private func sendBulk(_ chunk: ProtocolV1FileChunk) throws {
        guard let client else { throw TestError.noClient }
        let frame = try ProtocolV1TransportFrame(
            channel: .bulk,
            payload: try chunk.serializedFrame()
        ).encoded()
        let sent = DispatchSemaphore(value: 0)
        client.send(
            content: frame,
            completion: .contentProcessed { error in
                XCTAssertNil(error)
                sent.signal()
            }
        )
        XCTAssertEqual(sent.wait(timeout: .now() + 2), .success)
    }

    private func envelope(
        messageID: UInt64,
        payload: VSEnvelope.OneOf_Payload
    ) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = messageID
        if !sessionID.isEmpty {
            envelope.sessionID = sessionID
            envelope.sessionEpoch = sessionEpoch
        }
        envelope.payload = payload
        return envelope
    }

    /// Reads Protocol v1 control envelopes until the required payload appears.
    /// `inboundFramer` persists across calls so a TCP read ending halfway
    /// through the next frame cannot discard those bytes.
    private func receiveControlEnvelopes(
        until matchesTarget: @escaping (VSEnvelope) -> Bool,
        timeout: TimeInterval
    ) throws -> [VSEnvelope] {
        guard let client else { throw TestError.noClient }
        var envelopes: [VSEnvelope] = []
        let done = DispatchSemaphore(value: 0)
        var receiveFailure: Error?

        func receiveNext() {
            client.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { data, _, connectionComplete, error in
                if let data, !data.isEmpty {
                    do {
                        let frames = try self.inboundFramer.append(data)
                        for frame in frames where frame.channel == .control {
                            envelopes.append(try VSEnvelope(serializedBytes: frame.payload))
                        }
                    } catch {
                        receiveFailure = error
                        done.signal()
                        return
                    }
                }
                if let error {
                    receiveFailure = error
                    done.signal()
                    return
                }
                if connectionComplete {
                    receiveFailure = TestError.connectionClosed
                    done.signal()
                    return
                }
                if envelopes.contains(where: matchesTarget) {
                    done.signal()
                    return
                }
                receiveNext()
            }
        }
        receiveNext()

        let result = done.wait(timeout: .now() + timeout)
        if result == .timedOut { throw TestError.timeout }
        if let receiveFailure { throw receiveFailure }
        return envelopes
    }

    private func receiveFrame(
        channel: ProtocolV1LogicalChannel,
        timeout: TimeInterval
    ) throws -> ProtocolV1TransportFrame {
        guard let client else { throw TestError.noClient }
        let done = DispatchSemaphore(value: 0)
        var matchedFrame: ProtocolV1TransportFrame?
        var receiveFailure: Error?

        func receiveNext() {
            client.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { data, _, connectionComplete, error in
                if let data, !data.isEmpty {
                    do {
                        let frames = try self.inboundFramer.append(data)
                        if let frame = frames.first(where: { $0.channel == channel }) {
                            matchedFrame = frame
                            done.signal()
                            return
                        }
                    } catch {
                        receiveFailure = error
                        done.signal()
                        return
                    }
                }
                if let error {
                    receiveFailure = error
                    done.signal()
                    return
                }
                if connectionComplete {
                    receiveFailure = TestError.connectionClosed
                    done.signal()
                    return
                }
                receiveNext()
            }
        }
        receiveNext()

        let result = done.wait(timeout: .now() + timeout)
        if result == .timedOut { throw TestError.timeout }
        if let receiveFailure { throw receiveFailure }
        return try XCTUnwrap(matchedFrame)
    }

    private func temporaryDirectory() -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("vibescreen-streaming-file-tests", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    private func fileOffer(
        transferID: Data,
        fileName: String,
        payload: Data
    ) -> VSFileOffer {
        var offer = VSFileOffer()
        offer.transferID = transferID
        offer.fileName = fileName
        offer.mimeType = "text/plain"
        offer.byteLength = UInt64(payload.count)
        offer.sha256 = sha256(payload)
        return offer
    }

    private func chunk(
        transferID: Data,
        offset: UInt64,
        payload: Data,
        final: Bool
    ) -> ProtocolV1FileChunk {
        var header = VSFileChunkHeader()
        header.transferID = transferID
        header.offset = offset
        header.payloadLength = UInt32(payload.count)
        header.sessionEpoch = sessionEpoch
        header.chunkSha256 = sha256(payload)
        header.final = final
        return ProtocolV1FileChunk(header: header, payload: payload)
    }

    private func sha256(_ data: Data) -> Data {
        Data(SHA256.hash(data: data))
    }

    private enum TestError: Error {
        case noClient
        case missingSessionAccepted
        case missingVideoConfig
        case connectionClosed
        case timeout
    }
}
