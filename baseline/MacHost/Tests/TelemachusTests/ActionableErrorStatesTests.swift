import Foundation
import XCTest

final class ActionableErrorStatesTests: XCTestCase {
    func testRequiredActionableErrorContractsStayCoveredOffline() throws {
        let statesByCode = try loadActionableErrorStatesByContractCode()

        for expected in Self.expectedContracts {
            let state = try XCTUnwrap(statesByCode[expected.code], "Missing actionable contract \(expected.code)")
            let contract = try XCTUnwrap(state["contract"] as? [String: Any], expected.code)

            XCTAssertEqual(contract["title"] as? String, expected.title, expected.code)
            XCTAssertEqual(contract["body"] as? String, expected.body, expected.code)
            XCTAssertEqual(contract["action"] as? String, expected.action, expected.code)
            XCTAssertEqual(state["gate_status"] as? String, "covered-offline", expected.code)
            XCTAssertEqual(state["readme_gate_closure"] as? Bool, false, expected.code)
            XCTAssertFalse((state["offline_evidence"] as? [Any])?.isEmpty ?? true, expected.code)
        }

        XCTAssertEqual(Set(statesByCode.keys), Set(Self.expectedContracts.map(\.code)))
    }

    private func loadActionableErrorStatesByContractCode() throws -> [String: [String: Any]] {
        let data = try Data(contentsOf: Self.matrixURL())
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let states = try XCTUnwrap(root["states"] as? [[String: Any]])
        var result: [String: [String: Any]] = [:]
        for state in states {
            guard let contract = state["contract"] as? [String: Any],
                  let code = contract["code"] as? String else {
                continue
            }
            result[code] = state
        }
        return result
    }

    private static func matrixURL(filePath: String = #filePath) -> URL {
        var root = URL(fileURLWithPath: filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        return root.appendingPathComponent("docs/changes/2026-08-23-actionable-error-states/actionable-error-states.json")
    }

    private struct ExpectedContract {
        let code: String
        let title: String
        let body: String
        let action: String
    }

    private static let expectedContracts = [
        ExpectedContract(
            code: "host_screen_recording_denied",
            title: "Screen Recording permission denied",
            body: "The macOS Host cannot capture a display because Screen Recording permission is missing or stale for the installed app identity.",
            action: "Grant Screen Recording to the installed Vibe Screen app in System Settings, quit, reopen, and rerun the Host preflight."
        ),
        ExpectedContract(
            code: "accessibility_denied_or_limited",
            title: "Accessibility permission denied",
            body: "macOS input injection or window movement is unavailable because Accessibility is not granted to the stable signed Host app.",
            action: "Grant Accessibility to the stable signed installed app, quit and reopen Vibe Screen, then retry input or window movement."
        ),
        ExpectedContract(
            code: "adb_reverse_missing",
            title: "ADB reverse route missing",
            body: "USB mode cannot reach the Mac because the Android-to-Mac reverse route for TCP 54321 is missing, refused, or stale.",
            action: "Reconnect or authorize the Android device, use the Mac app USB repair action to restore the reverse route, then retry."
        ),
        ExpectedContract(
            code: "usb_disconnected",
            title: "USB device disconnected",
            body: "The Android device is no longer reachable over the authorized USB debugging transport, so the client cannot use the local stream route.",
            action: "Reconnect the cable, unlock and authorize the phone, wait for the Mac app to repair USB routing, then retry."
        ),
        ExpectedContract(
            code: "lan_route_unavailable",
            title: "LAN route unavailable",
            body: "Trusted LAN cannot route from the Android device to the saved Mac address and port on the same private network.",
            action: "Reconnect both devices to the same trusted Wi-Fi, disable VPN or guest isolation, verify the saved Mac address and port, then reconnect."
        ),
        ExpectedContract(
            code: "tcp_54321_unavailable",
            title: "TCP 54321 unavailable",
            body: "The Host is not reachable on TCP port 54321 because the listener is absent, failed to start, or the port is occupied.",
            action: "Start or restart Vibe Screen on the Mac. If another process is listening on TCP 54321, stop it and restart Vibe Screen."
        ),
        ExpectedContract(
            code: "stale_epoch_or_session_errors",
            title: "Stale session epoch",
            body: "The client rejected data from an older Protocol v1 session or configuration epoch to protect the current stream state.",
            action: "Reconnect for a fresh session epoch; if it repeats, update both devices and collect logs instead of treating recovery as device-verified."
        ),
    ]
}
