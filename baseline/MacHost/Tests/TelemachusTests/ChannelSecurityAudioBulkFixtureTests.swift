import CryptoKit
import Foundation
import XCTest
@testable import Telemachus

/// Cross-platform AUDIO/BULK channel-security fixture.
///
/// The fixture pins the session key-derivation inputs, epoch, channel, sender,
/// sequence, and plaintext. Both Swift and Android derive the same directional
/// traffic keys and seal the same plaintext with AES-256-GCM, so the sealed
/// records must match byte-for-byte.
final class ChannelSecurityAudioBulkFixtureTests: XCTestCase {
    private struct Fixture: Decodable {
        struct Session: Decodable {
            let sessionIdentifier: String
            let sessionEpoch: UInt64
            let keyEpoch: UInt64
            let keyId: String
            let sessionIdHash: String
            let keyDerivation: KeyDerivation
            let keys: [String: String]
        }

        struct KeyDerivation: Decodable {
            let sharedSecret: String
            let bootstrapSecret: String
            let context: String
        }

        struct Record: Decodable {
            let name: String
            let channel: String
            let sender: String
            let sequence: UInt64
            let plaintext: String
            let nonce: String
            let header: String
            let ciphertextAndTag: String
            let record: String
        }

        let session: Session
        let records: [Record]
    }

    private func loadFixture(file: StaticString = #filePath) throws -> Fixture {
        var root = URL(fileURLWithPath: "\(file)")
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let url = root.appendingPathComponent("contracts/fixtures/channel-security/v1/audio-bulk-records.json")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Fixture.self, from: Data(contentsOf: url))
    }

    private func fixtureChannel(_ value: String) throws -> PlatformSecurityChannel {
        switch value {
        case "AUDIO":
            return .audio
        case "BULK":
            return .bulk
        default:
            throw FixtureError.unsupportedChannel(value)
        }
    }

    private func senderWireValue(_ value: String) throws -> UInt8 {
        switch value {
        case "HOST":
            return 1
        case "DEVICE":
            return 2
        default:
            throw FixtureError.unsupportedSender(value)
        }
    }

    private func hex(_ string: String) -> Data {
        var data = Data(capacity: string.count / 2)
        var index = string.startIndex
        while index < string.endIndex {
            let next = string.index(index, offsetBy: 2)
            guard let byte = UInt8(string[index..<next], radix: 16) else {
                preconditionFailure("invalid hex in fixture")
            }
            data.append(byte)
            index = next
        }
        return data
    }

    func testHostAndDeviceSealAudioAndBulkRecordsMatchFixture() throws {
        let fixture = try loadFixture()
        let session = fixture.session
        let sharedSecret = hex(session.keyDerivation.sharedSecret)
        let bootstrapSecret = hex(session.keyDerivation.bootstrapSecret)
        let context = hex(session.keyDerivation.context)

        let pair = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: session.sessionIdentifier,
            sharedSecret: sharedSecret,
            bootstrapSecret: bootstrapSecret,
            transcriptContext: context,
            sessionEpoch: session.sessionEpoch
        )

        for record in fixture.records {
            let channel = try fixtureChannel(record.channel)
            let plaintext = hex(record.plaintext)
            let expectedRecord = hex(record.record)

            let sealed: Data
            switch record.sender {
            case "HOST":
                sealed = try pair.host.sealAdvanced(plaintext, channel: channel)
            case "DEVICE":
                sealed = try pair.device.sealAdvanced(plaintext, channel: channel)
            default:
                XCTFail("unexpected sender \(record.sender)")
                continue
            }

            XCTAssertEqual(
                sealed,
                expectedRecord,
                "sealed record mismatch for \(record.name)"
            )
        }
    }

    func testHostAndDeviceOpenFixtureRecordsReturnPlaintext() throws {
        let fixture = try loadFixture()
        let session = fixture.session
        let sharedSecret = hex(session.keyDerivation.sharedSecret)
        let bootstrapSecret = hex(session.keyDerivation.bootstrapSecret)
        let context = hex(session.keyDerivation.context)

        let pair = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: session.sessionIdentifier,
            sharedSecret: sharedSecret,
            bootstrapSecret: bootstrapSecret,
            transcriptContext: context,
            sessionEpoch: session.sessionEpoch
        )

        for record in fixture.records {
            let channel = try fixtureChannel(record.channel)
            let plaintext = hex(record.plaintext)
            let expectedRecord = hex(record.record)

            let opened: Data?
            switch record.sender {
            case "HOST":
                // Host-sealed records are opened by the device cipher.
                opened = pair.device.openAdvanced(expectedRecord, channel: channel)
            case "DEVICE":
                // Device-sealed records are opened by the host cipher.
                opened = pair.host.openAdvanced(expectedRecord, channel: channel)
            default:
                XCTFail("unexpected sender \(record.sender)")
                continue
            }

            XCTAssertEqual(
                opened,
                plaintext,
                "opened plaintext mismatch for \(record.name)"
            )
        }
    }

    func testFixtureDerivedKeysMatchDeclaredKeys() throws {
        let fixture = try loadFixture()
        let session = fixture.session
        let sharedSecret = hex(session.keyDerivation.sharedSecret)
        let bootstrapSecret = hex(session.keyDerivation.bootstrapSecret)
        let context = hex(session.keyDerivation.context)

        let derived = try TrafficKeyDerivation.initial(
            sharedSecret: sharedSecret,
            bootstrapSecret: bootstrapSecret,
            context: context
        )

        XCTAssertEqual(derived.keyEpoch, session.keyEpoch)
        XCTAssertEqual(derived.hostAudio.hex, session.keys["host_audio"])
        XCTAssertEqual(derived.deviceAudio.hex, session.keys["device_audio"])
        XCTAssertEqual(derived.hostBulk.hex, session.keys["host_bulk"])
        XCTAssertEqual(derived.deviceBulk.hex, session.keys["device_bulk"])
    }

    func testFixtureSessionIdHashMatchesDeclaredHash() throws {
        let fixture = try loadFixture()
        let session = fixture.session
        let digest = Data(SHA256.hash(data: Data(session.sessionIdentifier.utf8))).prefix(16)
        XCTAssertEqual(digest.hex, session.sessionIdHash)
    }

    func testFixtureRecordMetadataMatchesWireLayout() throws {
        let fixture = try loadFixture()
        let session = fixture.session
        for record in fixture.records {
            let channel = try fixtureChannel(record.channel)
            let nonce = hex(record.nonce)
            let header = hex(record.header)
            let ciphertextAndTag = hex(record.ciphertextAndTag)
            let expectedHeader = makeHeader(
                sessionIdHash: hex(session.sessionIdHash),
                sessionEpoch: session.sessionEpoch,
                keyEpoch: session.keyEpoch,
                sender: try senderWireValue(record.sender),
                channel: UInt8(channel.rawValue),
                nonce: nonce
            )

            XCTAssertEqual(header, expectedHeader, "header mismatch for \(record.name)")
            XCTAssertEqual(nonce, makeNonce(channel: channel.rawValue, sequence: record.sequence))
            XCTAssertEqual(header + ciphertextAndTag, hex(record.record), "record split mismatch for \(record.name)")
        }
    }

    func testCrossChannelOpenIsRejected() throws {
        let fixture = try loadFixture()
        let session = fixture.session
        let sharedSecret = hex(session.keyDerivation.sharedSecret)
        let bootstrapSecret = hex(session.keyDerivation.bootstrapSecret)
        let context = hex(session.keyDerivation.context)

        let pair = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: session.sessionIdentifier,
            sharedSecret: sharedSecret,
            bootstrapSecret: bootstrapSecret,
            transcriptContext: context,
            sessionEpoch: session.sessionEpoch
        )

        let hostAudio = try XCTUnwrap(fixture.records.first { $0.name == "host_audio_seq1" })
        let hostBulk = try XCTUnwrap(fixture.records.first { $0.name == "host_bulk_seq1" })

        XCTAssertNil(pair.device.openAdvanced(hex(hostAudio.record), channel: .bulk))
        XCTAssertNil(pair.device.openAdvanced(hex(hostBulk.record), channel: .audio))
    }

    func testFixtureParserRejectsUnexpectedChannelAndSenderValues() throws {
        XCTAssertThrowsError(try fixtureChannel("CONTROL"))
        XCTAssertThrowsError(try senderWireValue("UNKNOWN"))
    }

    private func makeNonce(channel: UInt32, sequence: UInt64) -> Data {
        var channelValue = channel.bigEndian
        var sequenceValue = sequence.bigEndian
        return Data(bytes: &channelValue, count: MemoryLayout<UInt32>.size)
            + Data(bytes: &sequenceValue, count: MemoryLayout<UInt64>.size)
    }

    private func makeHeader(
        sessionIdHash: Data,
        sessionEpoch: UInt64,
        keyEpoch: UInt64,
        sender: UInt8,
        channel: UInt8,
        nonce: Data
    ) -> Data {
        var magic = UInt32(0x56534352).bigEndian
        var epoch = sessionEpoch.bigEndian
        var keyEpochValue = keyEpoch.bigEndian
        return Data(bytes: &magic, count: MemoryLayout<UInt32>.size)
            + Data([1])
            + sessionIdHash
            + Data(bytes: &epoch, count: MemoryLayout<UInt64>.size)
            + Data(bytes: &keyEpochValue, count: MemoryLayout<UInt64>.size)
            + Data([sender, channel])
            + nonce
    }

    private enum FixtureError: Error {
        case unsupportedChannel(String)
        case unsupportedSender(String)
    }
}

private extension Data {
    var hex: String {
        map { String(format: "%02x", $0) }.joined()
    }
}
