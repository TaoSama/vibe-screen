import Foundation
import XCTest
@testable import Telemachus

final class AdvancedChannelSecurityGateTests: XCTestCase {
    func testAudioAndBulkReservationsAreOwnerBoundAndIndependentlyAccounted() throws {
        let owner = AdvancedChannelOwner(sessionIdentifier: "session-a", sessionEpoch: 4, generation: 7)
        let replacement = AdvancedChannelOwner(sessionIdentifier: "session-b", sessionEpoch: 5, generation: 8)
        let gate = try makeGate(owner: owner)

        let audio = try gate.reserve(
            payloadBytes: 8,
            binding: .audio(displayID: "display-a", streamID: 11),
            owner: owner
        )
        let bulk = try gate.reserve(
            payloadBytes: 16,
            binding: .bulk(transferID: Data(repeating: 1, count: 16)),
            owner: owner
        )

        XCTAssertEqual(gate.bufferedBytes(for: .audio), 8)
        XCTAssertEqual(gate.bufferedBytes(for: .bulk), 16)
        XCTAssertThrowsError(try gate.reserve(
            payloadBytes: 1,
            binding: .audio(displayID: "display-a", streamID: 11),
            owner: owner
        )) { error in
            XCTAssertEqual(error as? AdvancedChannelSecurityError, .backlogExceeded(maximum: 8))
        }
        XCTAssertThrowsError(try gate.reserve(
            payloadBytes: 1,
            binding: .bulk(transferID: Data(repeating: 2, count: 16)),
            owner: replacement
        )) { error in
            XCTAssertEqual(error as? AdvancedChannelSecurityError, .staleOwner)
        }

        try gate.finish(audio)
        XCTAssertEqual(gate.bufferedBytes(for: .audio), 0)
        XCTAssertEqual(gate.bufferedBytes(for: .bulk), 16)
        try gate.replaceOwner(with: replacement)
        XCTAssertEqual(gate.bufferedBytes(for: .bulk), 0)
        XCTAssertThrowsError(try gate.finish(bulk)) { error in
            XCTAssertEqual(error as? AdvancedChannelSecurityError, .staleOwner)
        }
    }

    func testInvalidOwnersBindingsAndPayloadSizesFailBeforeAdmission() throws {
        let owner = AdvancedChannelOwner(sessionIdentifier: "session-a", sessionEpoch: 1, generation: 1)
        let gate = try makeGate(owner: owner)

        XCTAssertThrowsError(try AdvancedChannelSecurityGate(
            owner: AdvancedChannelOwner(sessionIdentifier: " ", sessionEpoch: 1, generation: 1)
        )) { error in
            XCTAssertEqual(error as? AdvancedChannelSecurityError, .invalidOwner)
        }
        XCTAssertThrowsError(try gate.reserve(
            payloadBytes: 0,
            binding: .audio(displayID: "display-a", streamID: 1),
            owner: owner
        )) { error in
            XCTAssertEqual(error as? AdvancedChannelSecurityError, .emptyPayload)
        }
        XCTAssertThrowsError(try gate.reserve(
            payloadBytes: 9,
            binding: .audio(displayID: "display-a", streamID: 1),
            owner: owner
        )) { error in
            XCTAssertEqual(error as? AdvancedChannelSecurityError, .payloadTooLarge(maximum: 8))
        }
        XCTAssertThrowsError(try gate.reserve(
            payloadBytes: 1,
            binding: .audio(displayID: " ", streamID: 1),
            owner: owner
        )) { error in
            XCTAssertEqual(error as? AdvancedChannelSecurityError, .invalidBinding)
        }
        XCTAssertThrowsError(try gate.reserve(
            payloadBytes: 1,
            binding: .bulk(transferID: Data(repeating: 0, count: 15)),
            owner: owner
        )) { error in
            XCTAssertEqual(error as? AdvancedChannelSecurityError, .invalidBinding)
        }
        XCTAssertThrowsError(try gate.replaceOwner(with: AdvancedChannelOwner(
            sessionIdentifier: "session-b",
            sessionEpoch: 0,
            generation: 1
        ))) { error in
            XCTAssertEqual(error as? AdvancedChannelSecurityError, .invalidOwner)
        }
    }

    private func makeGate(owner: AdvancedChannelOwner) throws -> AdvancedChannelSecurityGate {
        try AdvancedChannelSecurityGate(
            owner: owner,
            limits: .init(
                maximumAudioRecordBytes: 8,
                maximumAudioBacklogBytes: 8,
                maximumBulkRecordBytes: 16,
                maximumBulkBacklogBytes: 16
            )
        )
    }
}
