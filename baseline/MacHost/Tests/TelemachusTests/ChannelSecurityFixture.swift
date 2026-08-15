import Foundation

struct ChannelSecurityFixture: Decodable {
    struct Session: Decodable { let id: String; let epoch: UInt64 }
    struct Input: Decodable {
        let sharedSecret: String
        let bootstrapSecret: String
        let context: String
        let rotationNonce: String
    }
    struct KeyStage: Decodable { let keyId: String; let keys: String }
    struct Record: Decodable { let payload: String; let record: String }
    struct Records: Decodable {
        let hostControl: Record
        let deviceMedia: Record
        let hostAudio: Record
        let deviceBulk: Record
    }

    let schema: String
    let session: Session
    let input: Input
    let initial: KeyStage
    let rotated: KeyStage
    let records: Records

    static func load(filePath: String = #filePath) throws -> Self {
        var repositoryRoot = URL(fileURLWithPath: filePath)
        for _ in 0..<5 { repositoryRoot.deleteLastPathComponent() }
        let fixtureURL = repositoryRoot
            .appendingPathComponent("contracts/fixtures/security/v1/channel-records.json")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Self.self, from: Data(contentsOf: fixtureURL))
    }
}
