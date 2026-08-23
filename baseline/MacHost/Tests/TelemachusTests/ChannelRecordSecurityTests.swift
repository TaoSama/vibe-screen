import Foundation
import XCTest
@testable import Telemachus

final class ChannelRecordSecurityTests: XCTestCase {
    func testSharedFixtureMatchesInitialRotationAndAdvancedRecords() throws {
        let fixture = try ChannelSecurityFixture.load()
        XCTAssertEqual(fixture.schema, "dev.vibescreen.channel-security-fixture/v1")
        let initial = try fixtureKeys(fixture)
        XCTAssertEqual(initial.keyID, fixture.initial.keyId)
        XCTAssertEqual(initial.material, Data(channelHex: fixture.initial.keys))
        XCTAssertEqual(Set(initial.keyBuffers).count, 8)

        let rotated = try TrafficKeyDerivation.rotate(
            current: initial,
            nextEpoch: 2,
            updateNonce: Data(channelHex: fixture.input.rotationNonce)
        )
        XCTAssertEqual(rotated.keyID, fixture.rotated.keyId)
        XCTAssertEqual(rotated.material, Data(channelHex: fixture.rotated.keys))
        XCTAssertEqual(Set(rotated.keyBuffers).count, 8)

        let pair = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: fixture.session.id,
            sharedSecret: Data(channelHex: fixture.input.sharedSecret),
            bootstrapSecret: Data(channelHex: fixture.input.bootstrapSecret),
            transcriptContext: Data(channelHex: fixture.input.context),
            sessionEpoch: fixture.session.epoch
        )
        let hostControl = fixture.records.hostControl
        let deviceMedia = fixture.records.deviceMedia
        let hostAudio = fixture.records.hostAudio
        let deviceBulk = fixture.records.deviceBulk
        let sealedControl = try pair.host.seal(
            Data(channelHex: hostControl.payload),
            channel: .control
        )
        let sealedMedia = try pair.device.seal(
            Data(channelHex: deviceMedia.payload),
            channel: .media
        )
        let sealedAudio = try pair.host.sealAdvanced(
            Data(channelHex: hostAudio.payload),
            channel: .audio
        )
        let sealedBulk = try pair.device.sealAdvanced(
            Data(channelHex: deviceBulk.payload),
            channel: .bulk
        )

        XCTAssertEqual(sealedControl, Data(channelHex: hostControl.record))
        XCTAssertEqual(sealedMedia, Data(channelHex: deviceMedia.record))
        XCTAssertEqual(sealedAudio, Data(channelHex: hostAudio.record))
        XCTAssertEqual(sealedBulk, Data(channelHex: deviceBulk.record))

        XCTAssertNil(pair.device.open(Data(channelHex: hostControl.record), channel: .media))
        XCTAssertNil(pair.device.openAdvanced(Data(channelHex: hostControl.record), channel: .audio))
        XCTAssertNil(pair.device.openAdvanced(Data(channelHex: hostControl.record), channel: .bulk))
        XCTAssertEqual(
            pair.device.open(Data(channelHex: hostControl.record), channel: .control),
            Data(channelHex: hostControl.payload)
        )

        XCTAssertNil(pair.host.open(Data(channelHex: deviceMedia.record), channel: .control))
        XCTAssertNil(pair.host.openAdvanced(Data(channelHex: deviceMedia.record), channel: .audio))
        XCTAssertNil(pair.host.openAdvanced(Data(channelHex: deviceMedia.record), channel: .bulk))
        XCTAssertEqual(
            pair.host.open(Data(channelHex: deviceMedia.record), channel: .media),
            Data(channelHex: deviceMedia.payload)
        )

        XCTAssertNil(pair.device.open(Data(channelHex: hostAudio.record), channel: .control))
        XCTAssertNil(pair.device.open(Data(channelHex: hostAudio.record), channel: .media))
        XCTAssertNil(pair.device.openAdvanced(Data(channelHex: hostAudio.record), channel: .bulk))
        XCTAssertEqual(
            pair.device.openAdvanced(Data(channelHex: hostAudio.record), channel: .audio),
            Data(channelHex: hostAudio.payload)
        )

        XCTAssertNil(pair.host.open(Data(channelHex: deviceBulk.record), channel: .control))
        XCTAssertNil(pair.host.open(Data(channelHex: deviceBulk.record), channel: .media))
        XCTAssertNil(pair.host.openAdvanced(Data(channelHex: deviceBulk.record), channel: .audio))
        XCTAssertEqual(
            pair.host.openAdvanced(Data(channelHex: deviceBulk.record), channel: .bulk),
            Data(channelHex: deviceBulk.payload)
        )
    }

    func testAuthenticatedRecordsCannotBeRelabeledAcrossChannels() throws {
        let fixture = try ChannelSecurityFixture.load()
        let pair = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: fixture.session.id,
            sharedSecret: Data(channelHex: fixture.input.sharedSecret),
            bootstrapSecret: Data(channelHex: fixture.input.bootstrapSecret),
            transcriptContext: Data(channelHex: fixture.input.context),
            sessionEpoch: fixture.session.epoch
        )
        let records: [(ChannelSecurityFixture.Record, PlatformSecurityChannel, PlatformSessionPacketCipher)] = [
            (fixture.records.hostControl, .control, pair.device),
            (fixture.records.deviceMedia, .media, pair.host),
            (fixture.records.hostAudio, .audio, pair.device),
            (fixture.records.deviceBulk, .bulk, pair.host),
        ]

        let channels: [PlatformSecurityChannel] = [.control, .media, .audio, .bulk]
        for (fixtureRecord, originalChannel, receiver) in records {
            for relabeledChannel in channels where relabeledChannel != originalChannel {
                var relabeled = Data(channelHex: fixtureRecord.record)
                relabeled[Self.headerChannelOffset] = UInt8(relabeledChannel.rawValue)
                var channelPrefix = relabeledChannel.rawValue.bigEndian
                relabeled.replaceSubrange(
                    Self.nonceOffset..<(Self.nonceOffset + MemoryLayout<UInt32>.size),
                    with: Data(bytes: &channelPrefix, count: MemoryLayout<UInt32>.size)
                )
                XCTAssertNil(open(relabeled, channel: relabeledChannel, receiver: receiver))
            }
        }
    }

    func testAudioAllowsBoundedReorderingWhileBulkIsStrictlyOrdered() throws {
        let pair = try selfTestPair()
        let audioOne = try pair.host.sealAdvanced(Data([1]), channel: .audio)
        let audioTwo = try pair.host.sealAdvanced(Data([2]), channel: .audio)
        let bulkOne = try pair.host.sealAdvanced(Data([3]), channel: .bulk)
        let bulkTwo = try pair.host.sealAdvanced(Data([4]), channel: .bulk)

        XCTAssertEqual(pair.device.openAdvanced(audioTwo, channel: .audio), Data([2]))
        XCTAssertEqual(pair.device.openAdvanced(audioOne, channel: .audio), Data([1]))
        XCTAssertNil(pair.device.openAdvanced(audioTwo, channel: .audio))
        XCTAssertEqual(pair.device.openAdvanced(bulkTwo, channel: .bulk), Data([4]))
        XCTAssertNil(pair.device.openAdvanced(bulkOne, channel: .bulk))
        XCTAssertNil(pair.device.open(bulkTwo, channel: .media))
    }

    func testEveryDirectionalChannelCombinationRoundTrips() throws {
        let pair = try selfTestPair()
        let channels: [PlatformSecurityChannel] = [.control, .media, .audio, .bulk]

        for channel in channels {
            let hostPayload = Data([UInt8(channel.rawValue), 1])
            let devicePayload = Data([UInt8(channel.rawValue), 2])
            XCTAssertEqual(
                open(try seal(hostPayload, channel: channel, sender: pair.host),
                     channel: channel, receiver: pair.device),
                hostPayload
            )
            XCTAssertEqual(
                open(try seal(devicePayload, channel: channel, sender: pair.device),
                     channel: channel, receiver: pair.host),
                devicePayload
            )
        }
    }

    func testRotateRejectsOldAdvancedRecordsAndAcceptsNewEpoch() throws {
        let pair = try selfTestPair()
        let oldAudio = try pair.host.sealAdvanced(Data([1]), channel: .audio)
        let oldBulk = try pair.device.sealAdvanced(Data([2]), channel: .bulk)
        let updateNonce = Data((0..<16).map(UInt8.init))

        try pair.host.rotate(updateNonce: updateNonce)
        try pair.device.rotate(updateNonce: updateNonce)

        XCTAssertNil(pair.device.openAdvanced(oldAudio, channel: .audio))
        XCTAssertNil(pair.host.openAdvanced(oldBulk, channel: .bulk))
        let newAudio = try pair.host.sealAdvanced(Data([3]), channel: .audio)
        let newBulk = try pair.device.sealAdvanced(Data([4]), channel: .bulk)
        XCTAssertEqual(pair.device.openAdvanced(newAudio, channel: .audio), Data([3]))
        XCTAssertEqual(pair.host.openAdvanced(newBulk, channel: .bulk), Data([4]))
    }

    func testAdvancedEntryPointsRejectControlAndMedia() throws {
        let pair = try selfTestPair()
        XCTAssertThrowsError(try pair.host.sealAdvanced(Data([1]), channel: .control))
        XCTAssertThrowsError(try pair.host.sealAdvanced(Data([1]), channel: .media))

        let control = try pair.host.seal(Data([2]), channel: .control)
        let media = try pair.host.seal(Data([3]), channel: .media)
        XCTAssertNil(pair.device.openAdvanced(control, channel: .control))
        XCTAssertNil(pair.device.openAdvanced(media, channel: .media))
    }

    func testInvalidAllocatedNoncesFailClosedBeforeEncryption() throws {
        let invalidNonces = [
            Data([0, 0, 0, 3]),
            nonce(channel: 4, sequence: 1),
            nonce(channel: 3, sequence: 0),
        ]
        for invalidNonce in invalidNonces {
            let pair = try selfTestPair { _, _, _ in invalidNonce }
            XCTAssertThrowsError(try pair.host.sealAdvanced(Data([1]), channel: .audio))
        }
    }

    func testSessionKeysZeroizeOverwritesAllOwnedKeyMaterial() throws {
        let keys = try TrafficKeyDerivation.initial(
            sharedSecret: Data(repeating: 0x13, count: 32),
            bootstrapSecret: Data(repeating: 0x24, count: 32),
            context: Data(repeating: 0x35, count: 32)
        )
        XCTAssertFalse(keys.isClearedForTest)
        XCTAssertTrue(keys.keyBuffers.allSatisfy { $0.contains { $0 != 0 } })

        keys.zeroize()

        XCTAssertTrue(keys.isClearedForTest)
        XCTAssertTrue(keys.keyBuffers.allSatisfy { buffer in
            buffer.count == 32 && buffer.allSatisfy { $0 == 0 }
        })
        keys.zeroize()
        XCTAssertTrue(keys.isClearedForTest)
    }

    func testRotationCloseAndDeinitClearOwnedKeyBuffers() throws {
        let initial = try TrafficKeyDerivation.initial(
            sharedSecret: Data(repeating: 3, count: 32),
            bootstrapSecret: Data(repeating: 3, count: 32),
            context: Data(repeating: 3, count: 32)
        )
        var cipher: PlatformSessionPacketCipher? = PlatformSessionPacketCipher(
            sessionIdentifier: "owned-key-clear-test",
            sessionEpoch: 9,
            localRole: .host,
            initialKeys: initial,
            withActiveSessionEpoch: { try $0() },
            reserveNonce: { channel, _, _ in self.nonce(channel: channel, sequence: 1) },
            rotateKeys: { current, updateNonce in
                try TrafficKeyDerivation.rotate(
                    current: current,
                    nextEpoch: current.keyEpoch + 1,
                    updateNonce: updateNonce
                )
            }
        )
        try cipher?.rotate(updateNonce: Data((0..<16).map(UInt8.init)))
        XCTAssertTrue(initial.isClearedForTest)
        let postRotateRecord = try cipher?.sealAdvanced(Data([7]), channel: .bulk)
        XCTAssertNotNil(postRotateRecord)
        cipher?.close()
        XCTAssertThrowsError(try cipher?.sealAdvanced(Data([1]), channel: .audio))
        XCTAssertThrowsError(try cipher?.rotate(updateNonce: Data(repeating: 1, count: 16)))

        let deinitKeys = try TrafficKeyDerivation.initial(
            sharedSecret: Data(repeating: 4, count: 32),
            bootstrapSecret: Data(repeating: 4, count: 32),
            context: Data(repeating: 4, count: 32)
        )
        cipher = PlatformSessionPacketCipher(
            sessionIdentifier: "owned-key-deinit-test",
            sessionEpoch: 9,
            localRole: .host,
            initialKeys: deinitKeys,
            withActiveSessionEpoch: { try $0() },
            reserveNonce: { channel, _, _ in self.nonce(channel: channel, sequence: 1) },
            rotateKeys: { current, updateNonce in
                try TrafficKeyDerivation.rotate(
                    current: current,
                    nextEpoch: current.keyEpoch + 1,
                    updateNonce: updateNonce
                )
            }
        )
        cipher = nil
        XCTAssertTrue(deinitKeys.isClearedForTest)
    }

    func testFailedRotationPreservesCurrentKeysAndRecordUsability() throws {
        let pair = try selfTestPair()

        XCTAssertThrowsError(try pair.host.rotate(updateNonce: Data(repeating: 1, count: 15)))

        let record = try pair.host.sealAdvanced(Data([5, 6]), channel: .bulk)
        XCTAssertEqual(pair.device.openAdvanced(record, channel: .bulk), Data([5, 6]))
    }

    func testFailedSealConsumesDurableNonceBeforeNextReservation() throws {
        let store = ChannelRecordSecurityStateStore(
            state: PersistedSecurityState(sessionEpoch: 9)
        )
        let lifecycle = SecurityLifecycle(store: store)
        let valid = try TrafficKeyDerivation.initial(
            sharedSecret: Data(repeating: 3, count: 32),
            bootstrapSecret: Data(repeating: 3, count: 32),
            context: Data(repeating: 3, count: 32)
        )
        let invalid = PlatformSessionKeys(
            keyID: valid.keyID,
            keyEpoch: valid.keyEpoch,
            hostControl: valid.hostControl,
            deviceControl: valid.deviceControl,
            hostMedia: valid.hostMedia,
            deviceMedia: valid.deviceMedia,
            hostAudio: Data(repeating: 0, count: 31),
            deviceAudio: valid.deviceAudio,
            hostBulk: valid.hostBulk,
            deviceBulk: valid.deviceBulk
        )
        valid.close()
        let cipher = PlatformSessionPacketCipher(
            sessionIdentifier: "durable-seal-failure",
            sessionEpoch: 9,
            localRole: .host,
            initialKeys: invalid,
            withActiveSessionEpoch: { try lifecycle.withActiveSessionEpoch(9, operation: $0) },
            reserveNonce: { channel, sender, keyEpoch in
                try lifecycle.reserveNonce(
                    sessionEpoch: 9,
                    channel: channel,
                    senderRole: sender,
                    keyEpoch: keyEpoch
                )
            },
            rotateKeys: { current, updateNonce in
                try TrafficKeyDerivation.rotate(
                    current: current,
                    nextEpoch: current.keyEpoch + 1,
                    updateNonce: updateNonce
                )
            }
        )

        XCTAssertThrowsError(try cipher.sealAdvanced(Data([1]), channel: .audio))
        XCTAssertEqual(store.state.nonceHighWatermarks["3:1:1"], 1)
        XCTAssertEqual(
            try lifecycle.reserveNonce(
                sessionEpoch: 9,
                channel: 3,
                senderRole: 1,
                keyEpoch: 1
            ),
            nonce(channel: 3, sequence: 2)
        )
        cipher.close()
    }

    private func fixtureKeys(_ fixture: ChannelSecurityFixture) throws -> PlatformSessionKeys {
        try TrafficKeyDerivation.initial(
            sharedSecret: Data(channelHex: fixture.input.sharedSecret),
            bootstrapSecret: Data(channelHex: fixture.input.bootstrapSecret),
            context: Data(channelHex: fixture.input.context)
        )
    }

    private func selfTestPair(
        reserveNonce: ((UInt32, UInt32, UInt64) throws -> Data)? = nil
    ) throws -> (host: PlatformSessionPacketCipher, device: PlatformSessionPacketCipher) {
        try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "advanced-channel-test",
            sharedSecret: Data(repeating: 3, count: 32),
            bootstrapSecret: Data(repeating: 3, count: 32),
            transcriptContext: Data(repeating: 3, count: 32),
            sessionEpoch: 9,
            reserveNonce: reserveNonce
        )
    }

    private func nonce(channel: UInt32, sequence: UInt64) -> Data {
        var data = Data()
        var channel = channel.bigEndian
        var sequence = sequence.bigEndian
        data.append(Data(bytes: &channel, count: MemoryLayout<UInt32>.size))
        data.append(Data(bytes: &sequence, count: MemoryLayout<UInt64>.size))
        return data
    }

    private func open(
        _ record: Data,
        channel: PlatformSecurityChannel,
        receiver: PlatformSessionPacketCipher
    ) -> Data? {
        switch channel {
        case .control: return receiver.open(record, channel: .control)
        case .media: return receiver.open(record, channel: .media)
        case .audio, .bulk: return receiver.openAdvanced(record, channel: channel)
        }
    }

    private func seal(
        _ payload: Data,
        channel: PlatformSecurityChannel,
        sender: PlatformSessionPacketCipher
    ) throws -> Data {
        switch channel {
        case .control: return try sender.seal(payload, channel: .control)
        case .media: return try sender.seal(payload, channel: .media)
        case .audio, .bulk: return try sender.sealAdvanced(payload, channel: channel)
        }
    }

    private static let headerChannelOffset = 38
    private static let nonceOffset = 39
}

private final class ChannelRecordSecurityStateStore: SecurityStateStore {
    var state: PersistedSecurityState

    init(state: PersistedSecurityState) {
        self.state = state
    }

    func load() throws -> PersistedSecurityState { state }

    func persist(_ state: PersistedSecurityState) throws {
        self.state = state
    }
}

private extension PlatformSessionKeys {
    var material: Data {
        keyBuffers.reduce(into: Data()) { $0.append($1) }
    }

    var keyBuffers: [Data] {
        [hostControl, deviceControl, hostMedia, deviceMedia,
         hostAudio, deviceAudio, hostBulk, deviceBulk]
    }
}

private extension Data {
    init(channelHex: String) {
        precondition(channelHex.count.isMultiple(of: 2))
        self.init(stride(from: 0, to: channelHex.count, by: 2).map { index in
            let start = channelHex.index(channelHex.startIndex, offsetBy: index)
            let end = channelHex.index(start, offsetBy: 2)
            return UInt8(channelHex[start..<end], radix: 16)!
        })
    }
}
