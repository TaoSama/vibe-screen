import XCTest
import Foundation
import Network
@testable import Telemachus

final class StreamingServerLifecycleTests: XCTestCase {
    private let queue = DispatchQueue(
        label: "StreamingServerLifecycleTests",
        qos: .userInitiated
    )

    func testSecondListenerReportsPortConflict() throws {
        let port = testPort(offset: 1)
        let first = StreamingServer(port: port)
        let second = StreamingServer(port: port)
        defer {
            first.stop()
            second.stop()
        }

        try first.start()
        XCTAssertThrowsError(try second.start(timeout: 1))
    }

    func testAppliedVideoRatesSeedTheNextProtocolSession() {
        let server = StreamingServer(port: testPort(offset: 10))
        server.setProtocolV1VideoConfiguration(
            framesPerSecond: 60,
            bitrateKbps: 13_000,
            displayID: "display",
            displayName: "Display",
            isVirtual: false
        )

        server.setProtocolV1VideoRates(
            framesPerSecond: 30,
            bitrateKbps: 5_000
        )

        var snapshot = server.protocolV1VideoConfigurationForSelfTest()
        XCTAssertEqual(snapshot.bitrateKbps, 5_000)
        XCTAssertEqual(snapshot.framesPerSecond, 30)

        server.setProtocolV1VideoRates(
            framesPerSecond: 120,
            bitrateKbps: 95_000
        )

        snapshot = server.protocolV1VideoConfigurationForSelfTest()
        XCTAssertEqual(snapshot.bitrateKbps, 95_000)
        XCTAssertEqual(snapshot.framesPerSecond, 120)

        server.completeProtocolV1VideoPreferences(
            token: 2,
            accepted: true,
            appliedBitrateKbps: 5_000,
            appliedFramesPerSecond: 30
        )
        waitForNetworkQueue(server)

        snapshot = server.protocolV1VideoConfigurationForSelfTest()
        XCTAssertEqual(snapshot.bitrateKbps, 95_000)
        XCTAssertEqual(snapshot.framesPerSecond, 120)
    }

    func testFragmentedWirelessHandshakeIsAccepted() throws {
        let port = testPort(offset: 2)
        let token = Data(repeating: 0xA5, count: 32)
        let server = StreamingServer(
            port: port,
            mode: .wireless(authToken: token)
        )
        defer { server.stop() }

        let paired = expectation(description: "fragmented handshake accepted")
        server.onWirelessClientPaired = { name, _ in
            XCTAssertEqual(name, "Test tablet")
            paired.fulfill()
        }
        try server.start()

        let client = try readyClient(port: port)
        defer { client.cancel() }
        let request = handshakeRequest(token: token, name: "Test tablet")
        for (index, byte) in request.enumerated() {
            queue.asyncAfter(deadline: .now() + .milliseconds(index)) {
                client.send(
                    content: Data([byte]),
                    completion: .contentProcessed { _ in }
                )
            }
        }

        wait(for: [paired], timeout: 2)
    }

    func testUnauthenticatedCandidateDoesNotEvictActiveClient() throws {
        let port = testPort(offset: 3)
        let token = Data(repeating: 0x5A, count: 32)
        let server = StreamingServer(
            port: port,
            mode: .wireless(authToken: token)
        )
        defer { server.stop() }

        let connected = expectation(description: "legitimate client connected")
        let disconnected = expectation(description: "active client disconnected")
        disconnected.isInverted = true
        server.onClientConnected = { _ in connected.fulfill() }
        server.onClientDisconnected = { _ in disconnected.fulfill() }
        try server.start()

        let legitimate = try readyClient(port: port)
        defer { legitimate.cancel() }
        legitimate.send(
            content: handshakeRequest(token: token, name: "Legitimate"),
            completion: .contentProcessed { _ in }
        )
        wait(for: [connected], timeout: 2)

        let rogue = try readyClient(port: port)
        defer { rogue.cancel() }
        rogue.send(content: Data([0x00]), completion: .contentProcessed { _ in })

        wait(for: [disconnected], timeout: 0.5)
    }

    func testIncompleteHandshakeTimesOut() throws {
        let port = testPort(offset: 6)
        let server = StreamingServer(
            port: port,
            mode: .wireless(authToken: Data(repeating: 0x45, count: 32))
        )
        defer { server.stop() }
        try server.start()

        let client = try readyClient(port: port)
        defer { client.cancel() }
        let closed = expectation(description: "incomplete handshake closed")
        client.receive(minimumIncompleteLength: 1, maximumLength: 1) {
            _, _, isComplete, error in
            if isComplete || error != nil {
                closed.fulfill()
            }
        }
        wait(for: [closed], timeout: 4)
    }

    func testTokenRotationDisconnectsAuthenticatedClient() throws {
        let port = testPort(offset: 4)
        let token = Data(repeating: 0x12, count: 32)
        let server = StreamingServer(
            port: port,
            mode: .wireless(authToken: token)
        )
        defer { server.stop() }

        let connected = expectation(description: "client connected")
        let disconnected = expectation(description: "client revoked")
        server.onClientConnected = { _ in connected.fulfill() }
        server.onClientDisconnected = { _ in disconnected.fulfill() }
        try server.start()

        let client = try readyClient(port: port)
        defer { client.cancel() }
        client.send(
            content: handshakeRequest(token: token, name: "Revoked"),
            completion: .contentProcessed { _ in }
        )
        wait(for: [connected], timeout: 2)

        server.rotateAuthToken(Data(repeating: 0x34, count: 32))
        wait(for: [disconnected], timeout: 2)
    }

    func testReplacingConnectionIgnoresStaleCancellationCallback() throws {
        let port = testPort(offset: 5)
        let token = Data(repeating: 0x77, count: 32)
        let server = StreamingServer(
            port: port,
            mode: .wireless(authToken: token)
        )
        defer { server.stop() }

        let firstConnected = expectation(description: "first connected")
        let secondConnected = expectation(description: "second connected")
        var connectionCount = 0
        server.onClientConnected = { _ in
            connectionCount += 1
            if connectionCount == 1 {
                firstConnected.fulfill()
            } else if connectionCount == 2 {
                secondConnected.fulfill()
            }
        }
        let disconnected = expectation(description: "new session disconnected")
        disconnected.isInverted = true
        server.onClientDisconnected = { _ in disconnected.fulfill() }
        try server.start()

        let first = try readyClient(port: port)
        defer { first.cancel() }
        first.send(
            content: handshakeRequest(token: token, name: "First"),
            completion: .contentProcessed { _ in }
        )
        wait(for: [firstConnected], timeout: 2)

        let second = try readyClient(port: port)
        defer { second.cancel() }
        second.send(
            content: handshakeRequest(token: token, name: "Second"),
            completion: .contentProcessed { _ in }
        )
        wait(for: [secondConnected], timeout: 2)
        wait(for: [disconnected], timeout: 0.5)
    }

    func testInvalidPointerCountClosesConnectionWithoutResynchronizing() throws {
        let port = testPort(offset: 7)
        let server = StreamingServer(port: port)
        defer { server.stop() }
        let connected = expectation(description: "client connected")
        let disconnected = expectation(description: "malformed client disconnected")
        server.onClientConnected = { _ in connected.fulfill() }
        server.onClientDisconnected = { _ in disconnected.fulfill() }
        try server.start()

        let client = try readyClient(port: port)
        defer { client.cancel() }
        wait(for: [connected], timeout: 2)
        client.send(
            content: Data([2, 3]),
            completion: .contentProcessed { _ in }
        )
        wait(for: [disconnected], timeout: 2)
    }

    func testProtocolV1UpgradeInvalidatesPendingLegacyCodecCompletion() throws {
        let port = testPort(offset: 8)
        let server = StreamingServer(port: port)
        defer { server.stop() }

        let legacyNegotiationStarted = expectation(description: "legacy codec negotiation started")
        let completionLock = NSLock()
        var legacyCompletion: ((NegotiatedDisplayConfiguration?) -> Void)?
        server.onCodecNegotiated = { _, _, completion in
            completionLock.withLock { legacyCompletion = completion }
            legacyNegotiationStarted.fulfill()
        }
        let incorrectlyConnected = expectation(description: "stale legacy completion connected")
        incorrectlyConnected.isInverted = true
        server.onClientConnected = { _ in incorrectlyConnected.fulfill() }
        try server.start()

        let client = try readyClient(port: port)
        defer { client.cancel() }
        wait(for: [legacyNegotiationStarted], timeout: 2)

        let upgradeAcknowledged = expectation(description: "protocol v1 upgrade acknowledged")
        client.receive(minimumIncompleteLength: 2, maximumLength: 2) { data, _, _, error in
            XCTAssertNil(error)
            XCTAssertEqual(data, ProtocolV1Upgrade.acknowledgement)
            upgradeAcknowledged.fulfill()
        }
        client.send(
            content: Data([ProtocolV1Upgrade.offer]),
            completion: .contentProcessed { error in XCTAssertNil(error) }
        )
        wait(for: [upgradeAcknowledged], timeout: 2)

        let completion = completionLock.withLock { legacyCompletion }
        completion?(NegotiatedDisplayConfiguration(width: 1_920, height: 1_080, rotation: 0))
        wait(for: [incorrectlyConnected], timeout: 0.25)
    }

    func testWirelessProtocolUpgradeAcceptsOfferAfterLANRoundTripDelay() throws {
        let port = testPort(offset: 9)
        let token = Data(repeating: 0x91, count: 32)
        let server = StreamingServer(port: port, mode: .wireless(authToken: token))
        defer { server.stop() }
        try server.start()

        let client = try readyClient(port: port)
        defer { client.cancel() }
        let authenticated = expectation(description: "wireless authentication response")
        client.receive(minimumIncompleteLength: 5, maximumLength: 5) { data, _, _, error in
            XCTAssertNil(error)
            XCTAssertEqual(data, HandshakeCodec.encodeResponse(status: .ok))
            authenticated.fulfill()
        }
        client.send(
            content: handshakeRequest(token: token, name: "Delayed iOS"),
            completion: .contentProcessed { error in XCTAssertNil(error) }
        )
        wait(for: [authenticated], timeout: 2)

        let delayElapsed = expectation(description: "representative LAN scheduling delay")
        queue.asyncAfter(deadline: .now() + .milliseconds(300)) { delayElapsed.fulfill() }
        wait(for: [delayElapsed], timeout: 1)

        let upgraded = expectation(description: "delayed protocol v1 offer accepted")
        client.receive(minimumIncompleteLength: 2, maximumLength: 2) { data, _, _, error in
            XCTAssertNil(error)
            XCTAssertEqual(data, ProtocolV1Upgrade.acknowledgement)
            upgraded.fulfill()
        }
        client.send(
            content: Data([ProtocolV1Upgrade.offer]),
            completion: .contentProcessed { error in XCTAssertNil(error) }
        )
        wait(for: [upgraded], timeout: 2)
    }

    private func readyClient(port: UInt16) throws -> NWConnection {
        let ready = expectation(description: "client ready")
        var failure: Error?
        let client = NWConnection(
            host: NWEndpoint.Host("127.0.0.1"),
            port: NWEndpoint.Port(rawValue: port)!,
            using: .tcp
        )
        client.stateUpdateHandler = { state in
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
        client.start(queue: queue)
        wait(for: [ready], timeout: 2)
        if let failure { throw failure }
        return client
    }

    private func handshakeRequest(token: Data, name: String) -> Data {
        let nameData = Data(name.utf8)
        var request = Data(HandshakeCodec.requestMagic)
        request.append(token)
        request.append(UInt8(nameData.count))
        request.append(nameData)
        return request
    }

    private func waitForNetworkQueue(_ server: StreamingServer) {
        let entered = DispatchSemaphore(value: 0)
        let resume = DispatchSemaphore(value: 0)
        server.suspendNetworkQueueForSelfTest(entered: entered, resume: resume)
        XCTAssertEqual(entered.wait(timeout: .now() + 2), .success)
        resume.signal()
    }

    private func testPort(offset: UInt16) -> UInt16 {
        56_000 + UInt16(ProcessInfo.processInfo.processIdentifier % 500) + offset
    }
}
