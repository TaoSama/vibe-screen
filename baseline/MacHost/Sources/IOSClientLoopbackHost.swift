import Foundation

/// Evidence host for the external iOS trusted-LAN integration test. This is
/// deliberately a thin configuration of the production StreamingServer, not
/// a second protocol implementation.
enum IOSClientLoopbackHost {
    static let port: UInt16 = 54_321
    static let token = Data((0..<32).map(UInt8.init))
    static let displayID = "loopback-display-1"
    static let mediaPayload = Data([0, 0, 0, 1, 0x65, 0x88, 0x84, 0x21])

    private final class State {
        let lock = NSLock()
        var touchReceived = false
        var clientDisconnected = false
        var failure: String?

        func fail(_ message: String) {
            lock.withLock {
                if failure == nil { failure = message }
            }
        }
    }

    static func run(expectsInvalidTarget: Bool = false) -> Bool {
        let state = State()
        let server = StreamingServer(port: port, mode: .wireless(authToken: token))
        server.setDisplaySize(width: 1_920, height: 1_080)
        server.setProtocolV1VideoConfiguration(
            framesPerSecond: 60,
            bitrateKbps: 12_000,
            displayID: displayID,
            displayName: "Loopback Display",
            isVirtual: false
        )
        server.onCodecNegotiated = { _, _, completion in
            completion(NegotiatedDisplayConfiguration(width: 1_920, height: 1_080, rotation: 0))
        }
        server.onClientConnected = { _ in
            server.sendFrame(
                mediaPayload,
                timestamp: DispatchTime.now().uptimeNanoseconds,
                isKeyframe: true,
                sessionEpoch: server.currentSessionEpoch
            )
        }
        server.onTouchEvent = { x, y, action, pointerCount, _, _, _ in
            if expectsInvalidTarget {
                state.fail("invalid-target touch was dispatched")
                return
            }
            let valid = abs(x - 0.25) < 0.001 && abs(y - 0.75) < 0.001 &&
                action == 0 && pointerCount == 1
            state.lock.withLock { state.touchReceived = valid }
            if !valid {
                state.fail("unexpected touch x=\(x) y=\(y) action=\(action) pointers=\(pointerCount)")
            }
        }
        server.onClientDisconnected = { _ in
            state.lock.withLock { state.clientDisconnected = true }
        }
        server.onServerFailed = { state.fail("listener failed: \($0.localizedDescription)") }

        do {
            try server.start()
        } catch {
            print("iOS MacHost loopback: FAIL (listener startup: \(error))")
            return false
        }
        FileHandle.standardError.write(Data("IOS_LOOPBACK_HOST_READY port=\(port)\n".utf8))

        let deadline = Date(timeIntervalSinceNow: 12)
        while Date() < deadline {
            let finished = state.lock.withLock {
                (expectsInvalidTarget ? state.clientDisconnected : state.touchReceived) ||
                    state.failure != nil
            }
            if finished { break }
            RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.01))
        }

        // In the primary scenario stop() must serialize DisconnectNotice before
        // closing. The invalid-target scenario has already been closed by the
        // production protocol error path.
        server.stop()
        let snapshot = state.lock.withLock {
            (state.touchReceived, state.clientDisconnected, state.failure)
        }
        let passed = (expectsInvalidTarget ? (snapshot.1 && !snapshot.0) : snapshot.0) &&
            snapshot.2 == nil
        print(
            "iOS MacHost loopback: \(passed ? "PASS" : "FAIL") " +
            "(scenario=\(expectsInvalidTarget ? "invalid-target" : "lifecycle"), " +
            "wirelessAuth=true, protocolV1=true, media=true, touch=\(snapshot.0), " +
            "clientDisconnected=\(snapshot.1), error=\(snapshot.2 ?? "none"))"
        )
        return passed
    }
}
