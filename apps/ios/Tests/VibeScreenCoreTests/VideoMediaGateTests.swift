import XCTest
@testable import VibeScreenCore
import VibeScreenProtocol

private final class DecoderSpy {
    private(set) var decodedFrameIDs: [UInt64] = []

    func deliver(
        _ header: VSMediaPacketHeader,
        payload: Data = Data([0x01]),
        through gate: inout VideoMediaGate,
        owner: SessionOwner
    ) {
        guard case let .success(frame) = gate.admit(header, payload: payload, owner: owner) else { return }
        decodedFrameIDs.append(frame.frameID)
    }
}

final class VideoMediaGateTests: XCTestCase {
    func testPreAckStaleReplayAndFragmentsNeverReachDecoder() throws {
        let owner = SessionOwner(connectionOwner: ConnectionOwner())
        var gate = VideoMediaGate()
        try gate.reset(owner: owner, sessionEpoch: 7)
        try gate.bindStream(10, owner: owner)
        let token = try gate.beginConfiguration(config(streamID: 10, epoch: 3), owner: owner)
        let decoder = DecoderSpy()

        decoder.deliver(header(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 1), through: &gate, owner: owner)
        XCTAssertTrue(decoder.decodedFrameIDs.isEmpty, "pre-ack media reached decoder")

        try gate.acknowledgementSent(token, streamID: 10, owner: owner)
        decoder.deliver(
            header(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 1),
            payload: Data(),
            through: &gate,
            owner: owner
        )
        decoder.deliver(header(streamID: 10, sessionEpoch: 6, configEpoch: 3, frameID: 1), through: &gate, owner: owner)
        decoder.deliver(header(streamID: 10, sessionEpoch: 7, configEpoch: 2, frameID: 1), through: &gate, owner: owner)
        decoder.deliver(header(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 1, fragmentIndex: 0, fragmentCount: 2), through: &gate, owner: owner)
        decoder.deliver(header(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 1, fragmentIndex: 1, fragmentCount: 1), through: &gate, owner: owner)
        XCTAssertTrue(decoder.decodedFrameIDs.isEmpty, "rejected media reached decoder")

        decoder.deliver(header(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 1), through: &gate, owner: owner)
        XCTAssertEqual(decoder.decodedFrameIDs, [1])
        decoder.deliver(header(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 1), through: &gate, owner: owner)
        decoder.deliver(header(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 0), through: &gate, owner: owner)
        XCTAssertEqual(decoder.decodedFrameIDs, [1], "replay reached decoder")
    }

    func testReconfigurationBlocksOldFramesAndOldAckToken() throws {
        let owner = SessionOwner(connectionOwner: ConnectionOwner())
        var gate = VideoMediaGate()
        try gate.reset(owner: owner, sessionEpoch: 8)
        try gate.bindStream(5, owner: owner)
        let first = try gate.beginConfiguration(config(streamID: 5, epoch: 1), owner: owner)
        try gate.acknowledgementSent(first, streamID: 5, owner: owner)
        let decoder = DecoderSpy()
        decoder.deliver(header(streamID: 5, sessionEpoch: 8, configEpoch: 1, frameID: 100), through: &gate, owner: owner)

        let replacement = try gate.beginConfiguration(config(streamID: 5, epoch: 2), owner: owner)
        decoder.deliver(header(streamID: 5, sessionEpoch: 8, configEpoch: 1, frameID: 101), through: &gate, owner: owner)
        decoder.deliver(header(streamID: 5, sessionEpoch: 8, configEpoch: 2, frameID: 1), through: &gate, owner: owner)
        XCTAssertEqual(decoder.decodedFrameIDs, [100])
        XCTAssertThrowsError(try gate.acknowledgementSent(first, streamID: 5, owner: owner))

        try gate.acknowledgementSent(replacement, streamID: 5, owner: owner)
        XCTAssertEqual(
            gate.admit(
                header(streamID: 5, sessionEpoch: 8, configEpoch: 1, frameID: 101),
                owner: owner
            ),
            .failure(.configEpochMismatch(expected: 2, received: 1))
        )
        decoder.deliver(header(streamID: 5, sessionEpoch: 8, configEpoch: 1, frameID: 101), through: &gate, owner: owner)
        decoder.deliver(header(streamID: 5, sessionEpoch: 8, configEpoch: 2, frameID: 1), through: &gate, owner: owner)
        decoder.deliver(header(streamID: 5, sessionEpoch: 8, configEpoch: 2, frameID: 1), through: &gate, owner: owner)
        XCTAssertEqual(decoder.decodedFrameIDs, [100, 1])
    }
}

private func config(streamID: UInt64, epoch: UInt64) -> VSVideoConfig {
    var value = VSVideoConfig()
    value.streamID = streamID
    value.configEpoch = epoch
    value.codec = .h264
    value.encodedSize.width = 1_920
    value.encodedSize.height = 1_080
    value.framesPerSecond = 60
    value.bitrateKbps = 8_000
    return value
}

private func header(
    streamID: UInt64,
    sessionEpoch: UInt64,
    configEpoch: UInt64,
    frameID: UInt64,
    fragmentIndex: UInt32 = 0,
    fragmentCount: UInt32 = 1
) -> VSMediaPacketHeader {
    var value = VSMediaPacketHeader()
    value.streamID = streamID
    value.sessionEpoch = sessionEpoch
    value.configEpoch = configEpoch
    value.frameID = frameID
    value.codec = .h264
    value.fragmentIndex = fragmentIndex
    value.fragmentCount = fragmentCount
    return value
}
