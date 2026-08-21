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
            let channel: PlatformSecurityChannel = record.channel == "AUDIO" ? .audio : .bulk
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
            let channel: PlatformSecurityChannel = record.channel == "AUDIO" ? .audio : .bulk
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
}

private extension Data {
    var hex: String {
        map { String(format: "%02x", $0) }.joined()
    }
}
